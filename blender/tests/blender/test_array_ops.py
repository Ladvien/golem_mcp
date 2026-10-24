"""Issue #22: one call lays a grid, a ring or a path of copies.

`linear_array` moves a copy along one constant offset and `duplicate_object`
places one at a time, so a 16-stake pen was 16 calls and a five-course timber
stack was 40. `grid_array`, `radial_array` and `path_array` bake the whole
layout into ONE mesh in one call, and each acceptance condition is the
issue's own, measured rather than asserted from the implementation.

A copy is measured as a connected COMPONENT of the baked mesh: copies of a
closed solid share no topology, so a component IS a part however the parts
overlap in space. Clustering vertices by nearest origin would be ambiguous
the moment two copies touch, which a 12-copy ring on a 1 m radius does.

The layouts are the honest intermediate `linear_array` already produces: N
copies of a closed solid are N islands in one mesh until something bridges
them, so the report carries the overlaps and the sunk copies rather than
hiding them behind a passing verdict.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

POSITION_TOLERANCE_M = 1.0e-4
RADIAL_TOLERANCE_M = 1.0e-3
BOX_SIDE_M = 1.0
BOX_TRIANGLES = 12
# `add_box` centres a box on X/Y and sits its BASE at location_m[2], so its
# vertex centroid is half its height ABOVE its own origin. Every copy's
# centroid is therefore its placement point plus this.
BOX_CENTRE_OFFSET_M = (0.0, 0.0, BOX_SIDE_M / 2.0)
RED_RGB = (0.9, 0.1, 0.1)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _linked_box(name, location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops.primitives import add_box, link_into_scene

    box_name = add_box(name, BOX_SIDE_M, BOX_SIDE_M, BOX_SIDE_M, location_m)
    link_into_scene(box_name)
    return box_name


def _measured(object_name):
    from golem_blender.analyze.mesh_checks import analyze_object

    return analyze_object(bpy.data.objects[object_name])


def _component_centroids_m(object_name):
    """Each connected component's vertex centroid, in world metres."""
    import bmesh

    blender_object = bpy.data.objects[object_name]
    matrix = blender_object.matrix_world
    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        unvisited = set(working_mesh.verts)
        centroids = []
        while unvisited:
            start = unvisited.pop()
            members = [start]
            frontier = [start]
            while frontier:
                current = frontier.pop()
                for edge in current.link_edges:
                    neighbour = edge.other_vert(current)
                    if neighbour in unvisited:
                        unvisited.remove(neighbour)
                        frontier.append(neighbour)
                        members.append(neighbour)
            world_positions = [matrix @ vertex.co for vertex in members]
            centroids.append(
                tuple(
                    sum(position[axis] for position in world_positions) / len(members)
                    for axis in range(3)
                )
            )
        return centroids
    finally:
        working_mesh.free()


def _distinct_rounded(values, digits=4):
    return sorted({round(value, digits) for value in values})


def _centroid_of(origin_m):
    """Where a copy placed at `origin_m` has its vertex centroid."""
    return tuple(origin_m[axis] + BOX_CENTRE_OFFSET_M[axis] for axis in range(3))


def _geometry_signature(object_name):
    import bmesh

    blender_object = bpy.data.objects[object_name]
    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(blender_object.data)
        vertex_count = len(working_mesh.verts)
        coordinates = sorted(
            tuple(round(value, 6) for value in v.co) for v in working_mesh.verts
        )
    finally:
        working_mesh.free()
    return (
        vertex_count,
        coordinates,
        _measured(object_name).triangle_count,
        tuple(round(value, 6) for value in blender_object.matrix_world.translation),
    )


# --- condition 1: a grid ----------------------------------------------------


def test_grid_array_lays_every_copy_at_the_requested_pitch(empty_scene):
    """Condition 1: counts=(3,2,1) is 6x the triangles at the grid pitches."""
    from golem_blender.ops import grid_array

    box_name = _linked_box("Stake")
    triangles_before = _measured(box_name).triangle_count
    assert triangles_before == BOX_TRIANGLES

    report = grid_array(box_name, counts=(3, 2, 1), spacing_m=(1.5, 2.5, 3.0))

    assert report.object_name == box_name
    assert report.copies == 6
    assert report.triangle_count == 6 * triangles_before
    assert report.connected_component_count == 6

    centroids = _component_centroids_m(box_name)
    assert len(centroids) == 6
    assert _distinct_rounded([centroid[0] for centroid in centroids]) == [0.0, 1.5, 3.0]
    assert _distinct_rounded([centroid[1] for centroid in centroids]) == [0.0, 2.5]
    assert _distinct_rounded([centroid[2] for centroid in centroids]) == [
        BOX_CENTRE_OFFSET_M[2]
    ]
    # Every copy's own origin, as reported, is the lattice point itself, in the
    # order the op lays them: x slowest, then y, then z.
    expected_origins = [
        (x_m, y_m, 0.0) for x_m in (0.0, 1.5, 3.0) for y_m in (0.0, 2.5)
    ]
    assert len(report.copy_origins_m) == len(expected_origins)
    for origin_m, expected_m in zip(report.copy_origins_m, expected_origins):
        assert origin_m == pytest.approx(expected_m, abs=POSITION_TOLERANCE_M)


def test_a_grid_that_overlaps_reports_the_overlap(empty_scene):
    """Edge case: a pitch smaller than the part is the analyzer's finding too."""
    from golem_blender.ops import grid_array

    box_name = _linked_box("Stake")

    report = grid_array(box_name, counts=(2, 1, 1), spacing_m=(0.5, 0.0, 0.0))

    assert report.copies == 2
    assert report.overlapping_copy_pair_count == 1
    assert report.self_intersecting_face_pair_count > 0, (
        "the report's own overlap count and the analyzer's must agree that "
        "two 1 m boxes 0.5 m apart intersect"
    )


def test_a_grid_with_a_clear_gap_reports_no_overlap(empty_scene):
    from golem_blender.ops import grid_array

    box_name = _linked_box("Stake")

    report = grid_array(box_name, counts=(3, 1, 1), spacing_m=(2.0, 0.0, 0.0))

    assert report.copies == 3
    assert report.overlapping_copy_pair_count == 0
    assert report.self_intersecting_face_pair_count == 0


def test_a_zero_pitch_that_repeats_is_refused(empty_scene):
    from golem_blender.ops import grid_array

    box_name = _linked_box("Stake")

    with pytest.raises(ValueError, match="zero pitch"):
        grid_array(box_name, counts=(3, 1, 1), spacing_m=(0.0, 0.0, 0.0))
    assert _measured(box_name).triangle_count == BOX_TRIANGLES, (
        "a refused call changed the mesh"
    )


# --- condition 2: a ring ----------------------------------------------------


def test_radial_array_puts_twelve_copies_on_a_one_metre_circle(empty_scene):
    """Condition 2: every copy's centroid is 1.0 m from the Z axis, to 1 mm."""
    from golem_blender.ops import radial_array

    box_name = _linked_box("Stone")

    report = radial_array(box_name, count=12, radius_m=1.0)

    assert report.copies == 12
    assert report.connected_component_count == 12
    centroids = _component_centroids_m(box_name)
    assert len(centroids) == 12
    radial_distances = [math.hypot(centroid[0], centroid[1]) for centroid in centroids]
    for distance_m in radial_distances:
        assert distance_m == pytest.approx(1.0, abs=RADIAL_TOLERANCE_M), (
            f"copy centroid {distance_m} m from the Z axis"
        )
    # Evenly spaced: twelve distinct bearings, and each copy's own height kept.
    bearings = _distinct_rounded(
        [math.atan2(centroid[1], centroid[0]) for centroid in centroids], digits=6
    )
    assert len(bearings) == 12
    assert _distinct_rounded([centroid[2] for centroid in centroids]) == [
        BOX_CENTRE_OFFSET_M[2]
    ]


def test_a_radial_turn_spirals_the_copies(empty_scene):
    """turn_rad is a per-copy extra turn, so a 2-copy ring turned 90 deg swaps its extents."""
    from golem_blender.ops import radial_array
    from golem_blender.ops.transforms import _world_bounds_m

    box_name = _linked_box("Post")
    oblong = bpy.data.objects[box_name]
    # An oblong makes a copy's own turn measurable from the joint bounds: a
    # 2 x 1 m box turned 90 deg spans 1 x 2 m.
    oblong.scale = (2.0, 1.0, 1.0)
    bpy.context.view_layer.update()

    radial_array(box_name, count=2, radius_m=2.0, turn_rad=math.pi / 2)

    minimum, maximum = _world_bounds_m([bpy.data.objects[box_name]])
    extent_x_m, extent_y_m = maximum[0] - minimum[0], maximum[1] - minimum[1]
    # Copy 0 sits at x=+2 unturned (x 1..3), copy 1 at x=-2 turned a quarter
    # turn (x -2.5..-1.5, y -1..1). Unturned, copy 1 would span y -0.5..0.5.
    assert extent_x_m == pytest.approx(5.5, abs=POSITION_TOLERANCE_M)
    assert extent_y_m == pytest.approx(2.0, abs=POSITION_TOLERANCE_M)


def test_a_ring_needs_a_positive_radius(empty_scene):
    from golem_blender.ops import radial_array

    box_name = _linked_box("Stone")

    with pytest.raises(ValueError, match="radius_m must be positive"):
        radial_array(box_name, count=4, radius_m=0.0)
    assert _measured(box_name).triangle_count == BOX_TRIANGLES


# --- condition 4: an explicit path -----------------------------------------


def test_path_array_puts_the_first_and_last_copies_at_their_points(empty_scene):
    """Condition 4: three non-collinear points, both ends exactly where asked."""
    from golem_blender.ops import path_array

    box_name = _linked_box("Rung")
    points_m = [(0.0, 0.0, 1.0), (0.5, 0.0, 0.9), (1.0, 0.0, 0.8)]

    report = path_array(box_name, points_m)

    assert report.copies == 3
    assert report.skipped_point_count == 0
    assert report.copy_origins_m[0] == pytest.approx(
        points_m[0], abs=POSITION_TOLERANCE_M
    )
    assert report.copy_origins_m[-1] == pytest.approx(
        points_m[-1], abs=POSITION_TOLERANCE_M
    )
    centroids = _component_centroids_m(box_name)
    assert len(centroids) == 3
    # The ends are identified by their own points, not by an axis extreme: the
    # LAST point is also the lowest, so "the lowest copy" would pick it.
    for end_point_m in (points_m[0], points_m[-1]):
        nearest = min(
            centroids,
            key=lambda centroid: math.dist(centroid, _centroid_of(end_point_m)),
        )
        assert nearest == pytest.approx(
            _centroid_of(end_point_m), abs=POSITION_TOLERANCE_M
        ), f"no copy's centroid sits at {end_point_m}"


def test_a_skipped_path_point_leaves_no_degenerate_geometry(empty_scene):
    """Edge case: two identical consecutive points must not make a zero-length copy."""
    from golem_blender.ops import path_array

    box_name = _linked_box("Rung")

    report = path_array(box_name, [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    assert report.copies == 2
    assert report.skipped_point_count == 1
    measured = _measured(box_name)
    assert measured.zero_area_face_count == 0
    assert measured.duplicate_vertex_pair_count == 0
    assert measured.triangle_count == 2 * BOX_TRIANGLES


def test_a_copy_below_the_ground_is_reported(empty_scene):
    """Edge case: the piece's base check is on the whole piece."""
    from golem_blender.ops import path_array

    box_name = _linked_box("Rung")

    report = path_array(box_name, [(0.0, 0.0, 0.0), (2.0, 0.0, -0.5)])

    assert report.copies == 2
    assert report.below_ground_copy_count == 1
    assert report.bounds_min_m[2] == pytest.approx(-0.5, abs=POSITION_TOLERANCE_M)


def test_a_path_on_the_floor_reports_no_sunk_copy(empty_scene):
    from golem_blender.ops import path_array

    box_name = _linked_box("Rung")

    report = path_array(box_name, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])

    assert report.below_ground_copy_count == 0


# --- condition 3: count 1 is a no-op ---------------------------------------


def test_a_single_copy_changes_no_geometry(empty_scene):
    """Condition 3: count 1 on each op leaves the object exactly as it was."""
    from golem_blender.ops import grid_array, path_array, radial_array

    layouts = {
        "grid": lambda name: grid_array(
            name, counts=(1, 1, 1), spacing_m=(1.0, 1.0, 1.0)
        ),
        "radial": lambda name: radial_array(name, count=1, radius_m=1.0),
        "path": lambda name: path_array(name, [(0.0, 0.0, 0.0)]),
    }
    for label, layout in layouts.items():
        box_name = _linked_box(f"Stake_{label}")
        before = _geometry_signature(box_name)

        report = layout(box_name)

        assert report.object_name == box_name, label
        assert report.copies == 1, label
        assert report.triangle_count == report.triangle_count_before == BOX_TRIANGLES
        assert _geometry_signature(box_name) == before, label


# --- condition 5: one object, one slot per material ------------------------


def test_the_result_keeps_one_slot_per_source_material(empty_scene):
    """Condition 5: slots do not multiply with the copies."""
    from golem_blender.ops import grid_array
    from golem_blender.ops.materials import assign_material

    box_name = _linked_box("Stake")
    assign_material(box_name, "Oak", RED_RGB)

    report = grid_array(box_name, counts=(2, 2, 1), spacing_m=(2.0, 2.0, 0.0))

    assert report.copies == 4
    assert report.material_slots == 1
    assert [
        material.name for material in bpy.data.objects[box_name].data.materials
    ] == ["Oak"]
    assert bpy.data.objects[box_name].data.materials[0] is bpy.data.materials["Oak"]


# --- the existing single-axis behaviour is unchanged -----------------------


def test_linear_array_still_bakes_a_single_axis(empty_scene):
    """The pallet builder's op: unchanged count, spacing and component count."""
    from golem_blender.ops import linear_array
    from golem_blender.ops.transforms import _world_bounds_m

    box_name = _linked_box("Board")
    triangles_before = _measured(box_name).triangle_count

    returned = linear_array(box_name, count=4, offset_m=(0.2, 0.0, 0.0))

    assert returned == box_name
    measured = _measured(box_name)
    assert measured.triangle_count == 4 * triangles_before
    assert measured.connected_component_count == 4
    minimum, maximum = _world_bounds_m([bpy.data.objects[box_name]])
    # Four 1 m boxes at a 0.2 m pitch span 0.6 m more than one.
    assert (maximum[0] - minimum[0]) == pytest.approx(
        BOX_SIDE_M + 3 * 0.2, abs=POSITION_TOLERANCE_M
    )


def test_linear_array_still_refuses_a_count_below_two(empty_scene):
    from golem_blender.ops import linear_array

    box_name = _linked_box("Board")

    with pytest.raises(ValueError, match=">= 2"):
        linear_array(box_name, count=1, offset_m=(0.2, 0.0, 0.0))
