"""The sole lands where it was asked to land — measured, not derived.

`tests/pure/test_splayed_leg_spec.py` checks the algebra. This checks
the mesh: build a leg through the op, cut it flush with the floor, and
measure the area-weighted centroid of the faces that actually touch
z=0. That centroid is what `GroundContactProbe` grades, and it is the
number that read 0.1281 against a specified 0.1400 twice — once from
this suite's own reference stool, once from the agent at iteration 17.

The naive construction is built here too, and asserted to still fail.
A guard that only proves the fixed path works would pass just as
happily if the fix were deleted.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

from blended.evaluate import briefs
from blended.ops.legs import (
    SplayedLegSpec,
    add_splayed_leg,
    splayed_leg_ring,
    trim_soles_flat,
)

LEG_RADIUS_M = 0.022
TOP_RADIUS_M = briefs.STOOL_SEAT_DIAMETER_M / 2.0 * 0.45
TOP_Z_M = briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M

# The placement probe's tolerance, quoted from the brief rather than
# chosen here: a guard graded more loosely than the gate guards nothing.
PLACEMENT_TOLERANCE_M = 0.0100

# A face counts as touching the floor within this much of z=0. Matches
# the sole-planarity scale the acceptance gate uses.
GROUND_TOLERANCE_M = 0.0005

# The measured signature of the naive build. Asserted as a floor on the
# error, not an equality: the point is that it clears the tolerance.
NAIVE_MINIMUM_ERROR_M = 0.0100

BEARING_TOLERANCE_DEG = 5.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _stool_leg_spec(bearing_deg: float = 0.0) -> SplayedLegSpec:
    return SplayedLegSpec(
        foot_radius_m=briefs.STOOL_FOOT_CIRCLE_RADIUS_M,
        foot_bearing_deg=bearing_deg,
        top_radius_m=TOP_RADIUS_M,
        top_z_m=TOP_Z_M,
        leg_radius_m=LEG_RADIUS_M,
    )


def _sole_centroids(object_name):
    """Area-weighted centres of the downward faces sitting on z=0.

    Clustered by bearing so a multi-leg object reports one centroid per
    foot, which is how the acceptance gate reads them.
    """
    mesh = bpy.data.objects[object_name].data
    clusters: dict[int, list] = {}
    for polygon in mesh.polygons:
        centre = polygon.center
        if abs(centre.z) > GROUND_TOLERANCE_M:
            continue
        if polygon.normal.z > -0.9:  # not a downward face
            continue
        bearing_deg = math.degrees(math.atan2(centre.y, centre.x)) % 360.0
        key = round(bearing_deg / 10.0)
        clusters.setdefault(key, []).append((polygon.area, centre))
    centroids = []
    for faces in clusters.values():
        total_area = sum(area for area, _ in faces)
        if total_area <= 0.0:
            continue
        x = sum(area * centre.x for area, centre in faces) / total_area
        y = sum(area * centre.y for area, centre in faces) / total_area
        centroids.append((math.hypot(x, y), math.degrees(math.atan2(y, x)) % 360.0))
    return centroids


def test_a_trimmed_splayed_leg_lands_on_the_foot_circle(empty_scene):
    leg = add_splayed_leg("Leg", _stool_leg_spec())
    trim_soles_flat(leg, span_m=briefs.STOOL_SEAT_DIAMETER_M)
    bpy.context.view_layer.update()

    centroids = _sole_centroids(leg)
    assert len(centroids) == 1, f"expected one sole, measured {centroids}"
    radius_m, bearing_deg = centroids[0]
    assert radius_m == pytest.approx(
        briefs.STOOL_FOOT_CIRCLE_RADIUS_M, abs=PLACEMENT_TOLERANCE_M
    ), f"sole centre r={radius_m:.4f} m"
    assert bearing_deg == pytest.approx(0.0, abs=BEARING_TOLERANCE_DEG)


def test_the_naive_placement_still_lands_inboard(empty_scene):
    """Delete the outboard offset and this is what comes back.

    Builds the leg the way iteration 17 did — base centre on the foot
    circle, no drop — and asserts the sole misses by more than the
    gate's tolerance. If someone "simplifies" `base_radius_m` back to
    `foot_radius_m`, the fixed test above and this one both change, and
    this one says why.
    """
    from mathutils import Euler

    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform

    spec = _stool_leg_spec()
    leg = add_cylinder(
        "NaiveLeg",
        radius_m=LEG_RADIUS_M,
        height_m=math.hypot(spec.rise_m, spec.run_m),
        segment_count=spec.segment_count,
    )
    link_into_scene(leg)
    leg_obj = bpy.data.objects[leg]
    leg_obj.rotation_euler = Euler((0.0, -spec.splay_rad, 0.0), "XYZ")
    leg_obj.location = (briefs.STOOL_FOOT_CIRCLE_RADIUS_M, 0.0, 0.0)
    apply_object_transform(leg)
    trim_soles_flat(leg, span_m=briefs.STOOL_SEAT_DIAMETER_M)
    bpy.context.view_layer.update()

    centroids = _sole_centroids(leg)
    assert centroids, "the naive leg left no sole at all"
    radius_m = centroids[0][0]
    error_m = briefs.STOOL_FOOT_CIRCLE_RADIUS_M - radius_m
    assert error_m > NAIVE_MINIMUM_ERROR_M, (
        f"the naive build measured r={radius_m:.4f} m, only "
        f"{error_m:.4f} m inboard — it used to clear the tolerance, so "
        f"either the trap changed or the op is being bypassed"
    )


def test_a_ring_of_legs_lands_on_its_bearings(empty_scene):
    from blended.ops.booleans import boolean_union
    from blended.ops.primitives import add_cylinder, link_into_scene

    seat = add_cylinder(
        "Stool",
        radius_m=briefs.STOOL_SEAT_DIAMETER_M / 2.0,
        height_m=briefs.STOOL_SEAT_THICKNESS_M,
        segment_count=24,
        location_m=(0.0, 0.0, TOP_Z_M),
    )
    link_into_scene(seat)
    for leg in splayed_leg_ring("Leg", briefs.STOOL_LEG_COUNT, _stool_leg_spec()):
        boolean_union(seat, leg)
    trim_soles_flat(seat, span_m=briefs.STOOL_SEAT_DIAMETER_M)
    bpy.context.view_layer.update()

    centroids = _sole_centroids(seat)
    assert len(centroids) == briefs.STOOL_LEG_COUNT
    # Matched by nearest bearing rather than by sort order: the leg on
    # +X measures 359.99 as often as 0.01, and a sorted zip would pair
    # it with the wrong expectation.
    for expected_deg in (0.0, 120.0, 240.0):
        matches = [
            (radius_m, bearing_deg)
            for radius_m, bearing_deg in centroids
            if abs(((bearing_deg - expected_deg + 180.0) % 360.0) - 180.0)
            <= BEARING_TOLERANCE_DEG
        ]
        assert len(matches) == 1, (
            f"expected exactly one sole near {expected_deg} deg, measured {centroids}"
        )
        assert matches[0][0] == pytest.approx(
            briefs.STOOL_FOOT_CIRCLE_RADIUS_M, abs=PLACEMENT_TOLERANCE_M
        )
