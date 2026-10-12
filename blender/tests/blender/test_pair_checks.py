"""Pair separation is measured on the SURFACE, never on vertices, and
it is measured in BOTH directions.

scp's measured trap: palm-to-weapon distance read 60 mm against mesh
vertices and 6.5 mm against the mesh surface, because on box geometry
the nearest vertex is a far corner. Two wrong root causes were
announced off that artifact.

The second trap is argument order. Sampling only the first object's
vertices makes the measurement a function of which mesh is denser, so
``analyze_pair(a, b)`` and ``analyze_pair(b, a)`` disagreed. Measured
on the fixtures below: 0.0224 m one way, 0.3274 m the other, a 14.6x
spread on the same two solids.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

# A 24-gon cylinder against an 8-vertex cube: the density ratio that
# makes the one-directional measurement disagree with itself.
CUBE_HALF_WIDTH_M = 0.5
CUBE_HEIGHT_M = 1.0
CYLINDER_SEGMENT_COUNT = 24
CYLINDER_RADIUS_M = 0.3
CYLINDER_HEIGHT_M = 0.5
CYLINDER_BASE_Z_M = 0.25
CYLINDER_CENTER_X_M = 0.6

# The cylinder's x extent starts at CENTER_X - RADIUS; the cube's ends
# at +HALF_WIDTH. Exact because CYLINDER_SEGMENT_COUNT is EVEN: segment
# 12 of 24 lands at exactly math.pi, where cos returns -1.0, so the
# ring's minimum x is CENTER_X - RADIUS to the bit. An odd count makes
# this constant silently wrong. x is also the MINIMUM-overlap axis only
# for these parameters (y overlaps by 0.6, z by CYLINDER_HEIGHT_M);
# lowering CYLINDER_HEIGHT_M below 0.2 makes the reported depth a
# different axis with no warning.
EXPECTED_AABB_OVERLAP_M = CUBE_HALF_WIDTH_M - (CYLINDER_CENTER_X_M - CYLINDER_RADIUS_M)

# Two plates, each thinner than the contact tolerance, crossing at the
# origin: the interpenetration class BOTH gated numbers miss. The
# thickness is deliberately under CONTACT_DEPTH_TOLERANCE_M (2 mm), so
# the face-pair count is suppressed on geometry that genuinely shares
# volume.
PLATE_HALF_SPAN_M = 1.0
PLATE_THICKNESS_M = 0.001
# Both plates' vertices sit at their far corners, so the sampled
# vertex-to-surface distance is a whole span minus one thickness even
# though the true separation is zero. This is the upper-bound property
# the module docstring names.
PLATE_SAMPLED_SEPARATION_FLOOR_M = 0.5

# Symmetry is exact arithmetic (the same two numbers, min'd in the
# other order), so the tolerance is float noise only.
SYMMETRY_TOLERANCE_M = 1.0e-9
BOUNDS_TOLERANCE_M = 1.0e-6

# How far apart the two one-directional readings must be before the
# symmetry assertion means anything: a pair that is already symmetric
# would pass it while measuring nothing.
ASYMMETRY_FLOOR_M = 1.0e-3


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box(name, minimum_corner_m, maximum_corner_m):
    """An axis-aligned box between two world-space corners.

    One source of truth for every fixture in this file: a named
    constant that the construction does not read is worse than a
    literal, because it looks authoritative while the geometry moves
    independently of it.
    """
    x_min, y_min, z_min = minimum_corner_m
    x_max, y_max, z_max = maximum_corner_m
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(
        [
            (x_min, y_min, z_min),
            (x_max, y_min, z_min),
            (x_max, y_max, z_min),
            (x_min, y_max, z_min),
            (x_min, y_min, z_max),
            (x_max, y_min, z_max),
            (x_max, y_max, z_max),
            (x_min, y_max, z_max),
        ],
        [],
        [
            (0, 1, 2, 3),
            (7, 6, 5, 4),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        ],
    )
    mesh_data.update()
    box_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(box_object)
    return box_object


def _unit_cube(name, center_xy_m, z_min_m=0.0):
    """A CUBE_HEIGHT_M-tall cube with its base at z_min_m."""
    return _box(
        name,
        (
            center_xy_m[0] - CUBE_HALF_WIDTH_M,
            center_xy_m[1] - CUBE_HALF_WIDTH_M,
            z_min_m,
        ),
        (
            center_xy_m[0] + CUBE_HALF_WIDTH_M,
            center_xy_m[1] + CUBE_HALF_WIDTH_M,
            z_min_m + CUBE_HEIGHT_M,
        ),
    )


def test_separation_is_measured_on_the_surface(empty_scene):
    """Two 1 m cubes whose faces sit 0.01 m apart must report a
    minimum separation within 1e-3 of 0.01 — a nearest-vertex
    implementation reads roughly the cube diagonal instead."""
    from blended.analyze.pair_checks import analyze_pair

    first = _unit_cube("First", (-1.005, 0.0))
    second = _unit_cube("Second", (0.005, 0.0))
    pair_report = analyze_pair(first, second)

    assert pair_report.intersecting_face_pair_count == 0
    assert abs(pair_report.minimum_separation_m - 0.01) <= 1.0e-3, (
        f"surface separation {pair_report.minimum_separation_m}, "
        f"expected ~0.01; a nearest-vertex implementation reads the "
        f"diagonal instead"
    )


def test_overlapping_cubes_report_intersecting_pairs(empty_scene):
    from blended.analyze.pair_checks import analyze_pair

    first = _unit_cube("OverlapA", (-0.25, 0.0))
    second = _unit_cube("OverlapB", (0.25, 0.0))
    pair_report = analyze_pair(first, second)

    assert pair_report.intersecting_face_pair_count > 0


def _cylinder(
    name,
    center_xy_m,
    z_min_m=CYLINDER_BASE_Z_M,
    radius_m=CYLINDER_RADIUS_M,
    height_m=CYLINDER_HEIGHT_M,
    segment_count=CYLINDER_SEGMENT_COUNT,
):
    """A closed cylinder built from explicit angles, so its x/y extent
    is exactly +/-radius (the primitive operator's ring phase is not
    part of this file's contract)."""
    import math

    bottom_ring = []
    top_ring = []
    for index in range(segment_count):
        angle_rad = 2.0 * math.pi * index / segment_count
        x_m = center_xy_m[0] + radius_m * math.cos(angle_rad)
        y_m = center_xy_m[1] + radius_m * math.sin(angle_rad)
        bottom_ring.append((x_m, y_m, z_min_m))
        top_ring.append((x_m, y_m, z_min_m + height_m))
    faces = [
        (
            index,
            (index + 1) % segment_count,
            segment_count + (index + 1) % segment_count,
            segment_count + index,
        )
        for index in range(segment_count)
    ]
    faces.append(tuple(range(segment_count, 2 * segment_count)))  # +Z cap
    faces.append(tuple(reversed(range(segment_count))))  # -Z cap

    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(bottom_ring + top_ring, [], faces)
    mesh_data.update()
    cylinder_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(cylinder_object)
    return cylinder_object


def _one_directional_minimum_m(query_object, target_object):
    """The pre-fix measurement: sample only the query object's own
    vertices. Kept here, not in the module, so the asymmetry this file
    guards against stays reproducible."""
    from blended.analyze.pair_checks import _sampled_minimum_distance_m

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    query_evaluated = query_object.evaluated_get(dependency_graph)
    query_mesh = query_evaluated.to_mesh()
    target_evaluated = target_object.evaluated_get(dependency_graph)
    try:
        return _sampled_minimum_distance_m(
            query_mesh,
            query_evaluated.matrix_world,
            target_evaluated,
            target_evaluated.matrix_world,
        )
    finally:
        query_evaluated.to_mesh_clear()


def test_separation_does_not_depend_on_argument_order(empty_scene):
    """A separation measure that changes when the arguments swap is not
    a measure. Asserts the pair is genuinely density-asymmetric first,
    so the symmetry assertion cannot pass vacuously."""
    from blended.analyze.pair_checks import analyze_pair

    cube = _unit_cube("SymmetryCube", (0.0, 0.0))
    cylinder = _cylinder("SymmetryCylinder", (CYLINDER_CENTER_X_M, 0.0))

    cube_to_cylinder_m = _one_directional_minimum_m(cube, cylinder)
    cylinder_to_cube_m = _one_directional_minimum_m(cylinder, cube)
    assert abs(cube_to_cylinder_m - cylinder_to_cube_m) > ASYMMETRY_FLOOR_M, (
        f"fixture no longer exercises the defect: one-directional "
        f"readings {cube_to_cylinder_m} and {cylinder_to_cube_m} agree"
    )

    cube_first = analyze_pair(cube, cylinder)
    cylinder_first = analyze_pair(cylinder, cube)

    assert cube_first.minimum_separation_m == pytest.approx(
        cylinder_first.minimum_separation_m, abs=SYMMETRY_TOLERANCE_M
    )
    assert cube_first.minimum_separation_m == pytest.approx(
        min(cube_to_cylinder_m, cylinder_to_cube_m), abs=SYMMETRY_TOLERANCE_M
    )


def test_aabb_penetration_depth_is_reported(empty_scene):
    """The depth that gates the face-pair count is now visible: it
    matches the AABB overlap on a deep crossing and is zero on a pair
    that is apart."""
    from blended.analyze.pair_checks import analyze_pair

    cube = _unit_cube("DepthCube", (0.0, 0.0))
    cylinder = _cylinder("DepthCylinder", (CYLINDER_CENTER_X_M, 0.0))
    separated = _unit_cube("DepthFar", (5.0, 0.0))

    crossing = analyze_pair(cube, cylinder)
    assert crossing.aabb_penetration_depth_m == pytest.approx(
        EXPECTED_AABB_OVERLAP_M, abs=BOUNDS_TOLERANCE_M
    )
    assert crossing.intersecting_face_pair_count > 0

    apart = analyze_pair(cube, separated)
    assert apart.aabb_penetration_depth_m == 0.0


def _crossing_plates():
    """Two plates thinner than the contact tolerance, sharing volume.

    Horizontal plate: x, y over the full span, z in
    [0, PLATE_THICKNESS_M]. Vertical plate: x, z over the full span, y
    in [0, PLATE_THICKNESS_M]. Their intersection is the whole x span
    by one thickness squared, so these solids genuinely pass through
    each other.
    """
    horizontal = _box(
        "PlateHorizontal",
        (-PLATE_HALF_SPAN_M, -PLATE_HALF_SPAN_M, 0.0),
        (PLATE_HALF_SPAN_M, PLATE_HALF_SPAN_M, PLATE_THICKNESS_M),
    )
    vertical = _box(
        "PlateVertical",
        (-PLATE_HALF_SPAN_M, 0.0, -PLATE_HALF_SPAN_M),
        (PLATE_HALF_SPAN_M, PLATE_THICKNESS_M, PLATE_HALF_SPAN_M),
    )
    return horizontal, vertical


def test_a_shallow_crossing_is_visible_only_in_the_depth(empty_scene):
    """The blind spot the depth field exists for, pinned.

    Two solids that genuinely pass through each other report ZERO
    intersecting face pairs (the count is suppressed below
    CONTACT_DEPTH_TOLERANCE_M) and a HEALTHY minimum separation (every
    vertex is a span away from the other plate's surface, because the
    closest approach is edge-to-edge and touches no vertex). Only
    aabb_penetration_depth_m sees it.

    This is also the measured proof that minimum_separation_m is an
    upper bound on the true separation, which here is exactly 0.
    """
    from blended.analyze.pair_checks import (
        CONTACT_DEPTH_TOLERANCE_M,
        analyze_pair,
    )

    horizontal, vertical = _crossing_plates()
    assert PLATE_THICKNESS_M < CONTACT_DEPTH_TOLERANCE_M, (
        "fixture no longer exercises the blind spot: the plates are "
        "thicker than the tolerance that suppresses the pair count"
    )

    report = analyze_pair(horizontal, vertical)

    assert report.intersecting_face_pair_count == 0
    assert report.minimum_separation_m > PLATE_SAMPLED_SEPARATION_FLOOR_M
    assert 0.0 < report.aabb_penetration_depth_m < CONTACT_DEPTH_TOLERANCE_M
    assert report.aabb_penetration_depth_m == pytest.approx(
        PLATE_THICKNESS_M, abs=BOUNDS_TOLERANCE_M
    )
