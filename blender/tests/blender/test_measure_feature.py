"""`measure_feature` measured against real geometry the tests build themselves.

Measured need, 2026-10-24: four questions came up repeatedly in a live bakery
session and every one was answered by a hand-written `run_python` raycast or
plane fit. Each test below builds the shape the question is about and asserts
the MEASURED NUMBER — a pitch in degrees, a height in metres, a side name —
never a message.

The opening case is the one that cost the user a session: an oven whose mouth
faced its twin. The op measures how deep each local side reads, so
`declare_interaction_side` has evidence; the ROTATED case is the same part
turned 180 degrees, which must still name the same local side, because "which
side of this part" is a question about the part's own frame.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TOLERANCE_DEG = 0.5
TOLERANCE_M = 1.0e-3


@pytest.fixture()
def empty_scene():
    """A clean scene and clean registries."""
    from golem_blender.ops import assembly

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()


def _linked(name):
    from golem_blender.ops import link_into_scene

    link_into_scene(name)
    return name


def _box(name, width_m, depth_m, height_m, location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops import add_box

    return _linked(add_box(name, width_m, depth_m, height_m, location_m))


def _side_for(report, side_name):
    matches = [row for row in report.sides if row.side == side_name]
    assert len(matches) == 1, f"no measured row for side {side_name!r}"
    return matches[0]


# --- surface_height -------------------------------------------------------------


def test_a_flat_box_top_measures_its_own_height_and_a_level_pitch(empty_scene):
    from golem_blender.ops import measure_feature

    _box("Slab", 2.0, 2.0, 1.0)

    report = measure_feature("Slab", "surface_height", x_m=0.0, y_m=0.0)

    assert report.hit
    assert report.point_m[2] == pytest.approx(1.0, abs=TOLERANCE_M)
    assert report.point_m[0] == pytest.approx(0.0, abs=TOLERANCE_M)
    assert report.point_m[1] == pytest.approx(0.0, abs=TOLERANCE_M)
    assert report.normal == pytest.approx((0.0, 0.0, 1.0), abs=1.0e-3)
    assert report.slope_deg == pytest.approx(0.0, abs=TOLERANCE_DEG)


def test_a_miss_reports_no_hit_and_leaves_the_other_fields_alone(empty_scene):
    from golem_blender.ops import measure_feature

    _box("Slab", 1.0, 1.0, 1.0)

    report = measure_feature("Slab", "surface_height", x_m=5.0, y_m=5.0)

    assert not report.hit
    assert report.slope_deg == 0.0
    assert report.point_m == (0.0, 0.0, 0.0)


# --- plane_fit ------------------------------------------------------------------


def test_a_slab_rotated_thirty_degrees_fits_a_thirty_degree_plane(empty_scene):
    """The pitch is the measurement, and it must agree with the rotation applied."""
    from golem_blender.ops import measure_feature, rotate_object_euler
    from golem_blender.ops.selectors import FaceSelector

    slab = _box("Panel", 2.0, 2.0, 0.1)
    rotate_object_euler(slab, x_rad=math.radians(30.0))

    report = measure_feature(
        slab,
        "plane_fit",
        face_selector=FaceSelector(
            kind="axis_normal", axis="+z", normal_tolerance_deg=45.0
        ),
    )

    assert report.hit
    assert report.slope_deg == pytest.approx(30.0, abs=TOLERANCE_DEG)
    # Four corners, one face: a perfectly planar quad fits with no residual.
    assert report.face_count == 1
    assert report.vertex_count == 4
    assert report.residual_m == pytest.approx(0.0, abs=1.0e-6)
    # The normal points OUT of the top face, not into it.
    assert report.normal[2] > 0.0


def test_the_surface_probe_of_a_rotated_slab_reads_the_same_pitch(empty_scene):
    """Two measurements of one tilt must agree, or one of them is wrong."""
    from golem_blender.ops import measure_feature, rotate_object_euler

    slab = _box("Panel", 2.0, 2.0, 0.1)
    rotate_object_euler(slab, x_rad=math.radians(30.0))

    report = measure_feature(slab, "surface_height", x_m=0.0, y_m=0.0)

    assert report.hit
    assert report.slope_deg == pytest.approx(30.0, abs=TOLERANCE_DEG)


# --- opening --------------------------------------------------------------------


def _oven_with_a_mouth(name):
    """A 1 m box with a 0.6 x 0.8 x 0.6 cutter taken out of its -Y side."""
    from golem_blender.ops import (
        add_box,
        boolean_difference,
        link_into_scene,
    )

    body = _box(name, 1.0, 1.0, 1.0)
    # A boolean operand must be LINKED: an unlinked one makes the modifier
    # evaluate nothing and the difference silently return the unchanged target.
    cutter = link_into_scene(add_box(f"{name}_cutter", 0.6, 0.8, 0.6, (0.0, -0.2, 0.2)))
    boolean_difference(body, cutter)
    return body


def test_the_opening_of_a_box_with_a_mouth_is_its_front(empty_scene):
    """`front` is local -Y, and the mouth is cut into that side."""
    from golem_blender.ops import measure_feature

    oven = _oven_with_a_mouth("Oven")

    report = measure_feature(oven, "opening")

    assert len(report.sides) == 6
    assert report.deepest_side == "front"
    front = _side_for(report, "front")
    # The cutter stops 0.7 m into the body, which is what an oven mouth IS: a
    # recess with a back wall, not a hole through the part. So the deepest ray
    # reaches that back wall and nothing passes clean through.
    assert front.maximum_depth_m == pytest.approx(0.7, abs=0.02)
    assert front.through_fraction == 0.0
    assert front.mean_depth_m > 0.1
    # The back of the part is solid all the way through, so every ray meets the
    # front wall at once: the two sides are told apart by their depth.
    back = _side_for(report, "back")
    assert back.mean_depth_m == pytest.approx(0.0, abs=1.0e-3)
    assert back.maximum_depth_m == pytest.approx(0.0, abs=1.0e-3)


def test_a_rotated_oven_still_names_its_front_and_its_world_normal_flips(empty_scene):
    """The 180-degree turn: same LOCAL side, opposite WORLD direction."""
    from golem_blender.ops import measure_feature, rotate_object_euler

    oven = _oven_with_a_mouth("Oven")

    before = measure_feature(oven, "opening")
    rotate_object_euler(oven, z_rad=math.pi)
    after = measure_feature(oven, "opening")

    assert before.deepest_side == "front"
    assert after.deepest_side == "front"
    # Local -Y now points along world +Y.
    assert _side_for(before, "front").normal[1] < -0.9
    assert _side_for(after, "front").normal[1] > 0.9


# --- exterior_face --------------------------------------------------------------


def test_a_wall_measured_against_a_room_box_faces_away_from_it(empty_scene):
    """The room sits on the wall's +Y, so the side pointing away is local -Y."""
    from golem_blender.ops import measure_feature

    _box("Wall", 4.0, 0.3, 3.0)
    _box("Room", 4.0, 4.0, 3.0, (0.0, 3.0, 0.0))

    report = measure_feature("Wall", "exterior_face", against_name="Room")

    assert report.facing_side == "front"
    assert report.against_name == "Room"
    alignments = dict(report.side_alignments)
    assert alignments["front"] == pytest.approx(1.0, abs=1.0e-3)
    assert alignments["back"] == pytest.approx(-1.0, abs=1.0e-3)


# --- refusals -------------------------------------------------------------------


def test_each_kind_refuses_the_argument_it_needs_and_did_not_get(empty_scene):
    from golem_blender.ops import measure_feature

    _box("Thing", 1.0, 1.0, 1.0)

    with pytest.raises(ValueError, match="needs x_m and y_m"):
        measure_feature("Thing", "surface_height")
    with pytest.raises(ValueError, match="needs face_selector"):
        measure_feature("Thing", "plane_fit")
    with pytest.raises(ValueError, match="needs against_name"):
        measure_feature("Thing", "exterior_face")


def test_measuring_an_object_against_itself_is_refused(empty_scene):
    from golem_blender.ops import measure_feature

    _box("Thing", 1.0, 1.0, 1.0)

    with pytest.raises(ValueError, match="against itself"):
        measure_feature("Thing", "exterior_face", against_name="Thing")


def test_an_unknown_object_and_an_unknown_kind_are_each_refused(empty_scene):
    from golem_blender.ops import measure_feature
    from golem_blender.ops._objects import UnknownObject

    with pytest.raises(UnknownObject):
        measure_feature("NoSuchThing", "opening")
    with pytest.raises(ValueError, match="kind must be one of"):
        measure_feature("Whatever", "how_it_faces")
