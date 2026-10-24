"""Issue #25: placement that puts a FACE on a target, not an origin at a
coordinate.

Every acceptance condition below is the issue's own, measured on the
finished scene rather than asserted from the implementation. The pier
fixture is the issue's own measured village-kit piece
(2.000 x 0.406 x 3.123 m, bounds y in [-0.092, 0.314]), so its origin
sits 11.1 cm off its bounds centre and an origin-based placement CANNOT
satisfy condition 1 — that is the fault the issue was filed for.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

from mathutils import Vector

pytestmark = pytest.mark.blender

# The issue's own pier: 2.000 x 0.406 x 3.123 m with its origin 11.1 cm
# off the bounds centre in y.
PIER_MINIMUM_CORNER_M = (-1.0, -0.092, 0.0)
PIER_MAXIMUM_CORNER_M = (1.0, 0.314, 3.123)
PIER_Y_OFFSET_M = 0.111

# Condition 1's tolerance, verbatim from the issue.
FACE_TOLERANCE_M = 1.0e-4
# Condition 2's tolerance, verbatim from the issue.
CHAIN_TOLERANCE_M = 1.0e-3
# Condition 5's radius.
SPAN_RADIUS_M = 0.05
# `stand_against`'s default stand-off, and condition 3's stated 2 mm.
STAND_OFF_M = 0.002


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _piece(name, minimum_corner_m, maximum_corner_m):
    """A closed box whose LOCAL coordinates are the given corners.

    Built from `bmesh.ops.create_cube` rather than `from_pydata`, because
    a hand-written face list winds every face inward and the gate then
    fails the object on 12 flipped triangles — the placement would be
    right and the verdict would still be FAILED.

    The origin is world (0,0,0) until an op moves the object, which is
    exactly the condition a face-based placement has to survive: for the
    pier the local y range is [-0.092, 0.314], so the origin sits
    11.1 cm off the bounds centre and `move_object_to` cannot put a face
    on a target.
    """
    import bmesh

    x_min, y_min, z_min = minimum_corner_m
    x_max, y_max, z_max = maximum_corner_m
    mesh_data = bpy.data.meshes.new(name)
    piece_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(piece_object)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        for vertex in working_mesh.verts:
            vertex.co.x = x_min + (vertex.co.x + 0.5) * (x_max - x_min)
            vertex.co.y = y_min + (vertex.co.y + 0.5) * (y_max - y_min)
            vertex.co.z = z_min + (vertex.co.z + 0.5) * (z_max - z_min)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    mesh_data.update()
    return name


def _world_vertices_m(object_name):
    """Every EVALUATED world vertex of the named object — the measurement
    the issue demands instead of `bound_box`."""
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = bpy.data.objects[object_name].evaluated_get(dependency_graph)
    mesh = evaluated.to_mesh()
    try:
        to_world = evaluated.matrix_world
        return [to_world @ vertex.co for vertex in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _bounds_m(object_name):
    """(minimum, maximum) per axis, from the evaluated mesh's vertices."""
    vertices = _world_vertices_m(object_name)
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return minimum, maximum


def _surface_distance_m(point_m, object_name):
    """World distance from a point to the named object's SURFACE."""
    target = bpy.data.objects[object_name]
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(dependency_graph)
    to_local = evaluated.matrix_world.inverted()
    hit, location, _normal, _index = evaluated.closest_point_on_mesh(
        to_local @ Vector(point_m)
    )
    assert hit, f"no closest point on {object_name} for {point_m}"
    return ((evaluated.matrix_world @ location) - Vector(point_m)).length


def _end_face_centre_along_x_m(object_name, which):
    """The centre of the box's end face at its minimum or maximum world x."""
    minimum, maximum = _bounds_m(object_name)
    x_m = minimum[0] if which == "min" else maximum[0]
    return (
        x_m,
        0.5 * (minimum[1] + maximum[1]),
        0.5 * (minimum[2] + maximum[2]),
    )


# --- condition 1: a face on a face, from an off-centre origin ------------


def test_align_to_puts_the_piers_max_y_exactly_on_the_walls_min_y(empty_scene):
    """Condition 1: within 1e-4 m, and `achieved_gap_m` is 0.

    The fixture's origin is 11.1 cm off its bounds centre, so this
    cannot be satisfied by setting an origin: the assertion that the
    offset exists comes first, or the test could pass on a piece whose
    origin happens to be the centre.
    """
    from golem_blender.ops.alignment import align_to

    _piece("Pier", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    _piece("Wall", (2.0, 2.0, 0.0), (5.0, 2.2, 3.0))

    pier_minimum, pier_maximum = _bounds_m("Pier")
    bounds_centre_y_m = 0.5 * (pier_minimum[1] + pier_maximum[1])
    origin_y_m = bpy.data.objects["Pier"].matrix_world.translation.y
    assert abs(bounds_centre_y_m - origin_y_m) == pytest.approx(
        PIER_Y_OFFSET_M, abs=1.0e-6
    ), "fixture no longer carries the issue's 11.1 cm off-centre origin"

    report = align_to("Pier", "Wall", "max_y", "min_y")

    pier_minimum, pier_maximum = _bounds_m("Pier")
    assert pier_maximum[1] == pytest.approx(2.0, abs=FACE_TOLERANCE_M)
    assert report.achieved_gap_m == pytest.approx(0.0, abs=FACE_TOLERANCE_M)
    assert report.feature_object_m[1] == pytest.approx(2.0, abs=FACE_TOLERANCE_M)
    assert report.moved_m == pytest.approx((0.0, 2.0 - 0.314, 0.0), abs=1.0e-5)
    # Only y moved: a face alignment must not disturb the other axes.
    assert pier_minimum[0] == pytest.approx(-1.0, abs=FACE_TOLERANCE_M)
    assert pier_minimum[2] == pytest.approx(0.0, abs=FACE_TOLERANCE_M)


def test_a_yawed_objects_face_is_measured_from_the_mesh_not_the_bound_box(empty_scene):
    """The issue's first edge case: `bound_box` gives the wrong face.

    Measured in Blender 5.2 on a 24-gon cylinder of radius 1.0 m yawed
    45 degrees: `matrix_world @ bound_box` spans x in
    [-1.41421, 1.41421] while the mesh spans [-1.0, 1.0] — a 41% error.
    A placement that trusted the box would leave the face 41 cm off the
    target; this asserts the face measured from the mesh, and asserts
    the box reading really differs so the test cannot pass vacuously.
    """
    from mathutils import Vector

    from golem_blender.ops.alignment import align_to
    from golem_blender.ops.primitives import add_cylinder, link_into_scene
    from golem_blender.ops.transforms import rotate_object_euler

    _piece("Wall", (3.0, -2.0, 0.0), (3.2, 2.0, 3.0))
    barrel = add_cylinder("Barrel", 1.0, 2.0, location_m=(0.0, 0.0, 0.0))
    link_into_scene(barrel)
    rotate_object_euler("Barrel", z_rad=math.pi / 4.0)

    # The 24-gon's own ring reaches exactly 1.0 on x at the segment that
    # lands on a multiple of pi/2; a 45-degree yaw keeps that vertex at
    # radius 1.0 and the MESH says x_max 1.0.
    mesh_x_max_m = max(vertex.x for vertex in _world_vertices_m("Barrel"))
    assert mesh_x_max_m == pytest.approx(1.0, abs=1.0e-6)
    barrel_object = bpy.data.objects["Barrel"]
    bound_box_x_max_m = max(
        (barrel_object.matrix_world @ Vector(corner)).x
        for corner in barrel_object.bound_box
    )
    assert bound_box_x_max_m == pytest.approx(2.0**0.5, abs=1.0e-4), (
        "fixture no longer shows the drift: the bound_box reading must "
        "OVER-read a yawed object"
    )

    report = align_to("Barrel", "Wall", "max_x", "min_x")

    assert report.feature_object_m[0] == pytest.approx(3.0, abs=FACE_TOLERANCE_M)
    assert max(vertex.x for vertex in _world_vertices_m("Barrel")) == pytest.approx(
        3.0, abs=FACE_TOLERANCE_M
    )


# --- condition 2: chainable without accumulating error ------------------


def test_three_piers_chain_with_every_adjacent_face_within_1mm(empty_scene):
    """Condition 2: two piers, then a third, all faces within 1 mm."""
    from golem_blender.ops.alignment import align_to

    _piece("Wall", (2.0, 2.0, 0.0), (5.0, 2.2, 3.0))
    _piece("PierA", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    _piece("PierB", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    _piece("PierC", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)

    align_to("PierA", "Wall", "max_y", "min_y")
    align_to("PierB", "PierA", "max_y", "min_y")
    align_to("PierC", "PierB", "max_y", "min_y")

    seams = [
        abs(_bounds_m("PierA")[1][1] - 2.0),
        abs(_bounds_m("PierB")[1][1] - _bounds_m("PierA")[0][1]),
        abs(_bounds_m("PierC")[1][1] - _bounds_m("PierB")[0][1]),
    ]
    assert max(seams) <= CHAIN_TOLERANCE_M, f"seams {seams} m"
    # The run's total length is three pier depths to within 1 mm: the
    # accumulation this condition exists to rule out would show here.
    run_length_m = _bounds_m("PierA")[1][1] - _bounds_m("PierC")[0][1]
    assert run_length_m == pytest.approx(3.0 * 0.406, abs=CHAIN_TOLERANCE_M)


# --- condition 3: stand against a wall, base unchanged -----------------


def test_stand_against_leaves_two_mm_and_does_not_move_the_base(empty_scene):
    """Condition 3: `max_x` 2 mm from the wall's `min_x`, base unchanged."""
    from golem_blender.ops.alignment import stand_against

    _piece("Shelf", (0.0, 0.0, 1.0), (0.3, 1.0, 1.05))
    _piece("Wall", (2.0, -1.0, 0.0), (2.2, 1.0, 3.0))
    # A floor whose top is the shelf's base: the support the report must
    # name, so `hangs_in_air` is not vacuously True.
    _piece("Floor", (-2.0, -2.0, 0.0), (4.0, 2.0, 1.0))

    shelf_base_before_m = _bounds_m("Shelf")[0][2]
    report = stand_against("Shelf", "Wall", "+x")

    shelf_minimum, shelf_maximum = _bounds_m("Shelf")
    assert shelf_maximum[0] == pytest.approx(2.0 - STAND_OFF_M, abs=FACE_TOLERANCE_M)
    assert report.achieved_gap_m == pytest.approx(STAND_OFF_M, abs=FACE_TOLERANCE_M)
    assert shelf_minimum[2] == pytest.approx(shelf_base_before_m, abs=1.0e-9)
    assert report.hangs_in_air is False
    assert report.supported_by == ("Floor",)


# --- condition 4: an object left hanging in air ------------------------


def test_stand_against_reports_an_object_hanging_in_air(empty_scene):
    """Condition 4: the report field is `hangs_in_air`.

    The shelf's base (3.5 m) is above every other object's TOP (the
    wall is 3.0 m tall, the floor 0.2 m), so nothing is beneath it —
    while the wall still reaches up to meet it laterally, which is what
    makes the placement succeed and the support test honest.
    """
    from golem_blender.ops.alignment import stand_against

    _piece("Shelf", (0.0, 0.0, 3.5), (0.3, 1.0, 3.55))
    _piece("Wall", (2.0, -1.0, 0.0), (2.2, 1.0, 3.0))
    _piece("Floor", (-2.0, -2.0, 0.0), (4.0, 2.0, 0.2))

    tallest_other_top_m = max(_bounds_m(name)[1][2] for name in ("Wall", "Floor"))
    assert tallest_other_top_m < _bounds_m("Shelf")[0][2]

    report = stand_against("Shelf", "Wall", "+x")

    assert report.hangs_in_air is True
    assert report.supported_by == ()
    # The placement itself still happened: a hanging shelf is a
    # reported fault, not a refused move.
    assert _bounds_m("Shelf")[1][0] == pytest.approx(
        2.0 - STAND_OFF_M, abs=FACE_TOLERANCE_M
    )


# --- condition 5: a span measured to each SURFACE ----------------------


def test_span_between_lands_both_ends_on_their_own_objects_surface(empty_scene):
    """Condition 5: both end gaps under 0.05 m, measured on the surface.

    The two congruent boxes' nearest vertex-to-surface pair is a corner
    pair at exactly the x gap (all four candidate corners tie, and every
    one of them is the same segment in x), so the anchors are 1.2 m
    apart on x and the pipe is 1.2 m long.
    """
    from golem_blender.ops.alignment import span_between

    _piece("Bellows", (-1.5, -0.3, 0.0), (-0.5, 0.3, 0.6))
    _piece("Forge", (0.7, -0.3, 0.0), (1.7, 0.3, 0.6))
    # Long local axis z, 1.2 m: the span between the two faces.
    _piece("Pipe", (0.0, -0.05, -0.6), (0.1, 0.05, 0.6))

    report = span_between("Pipe", "Bellows", "Forge", SPAN_RADIUS_M)

    assert report.span_m == pytest.approx(1.2, abs=1.0e-3)
    assert report.end_gap_from_m < SPAN_RADIUS_M
    assert report.end_gap_to_m < SPAN_RADIUS_M
    assert report.achieved_gap_m < SPAN_RADIUS_M

    # Orientation: the pipe's long axis now runs on world x.
    pipe_minimum, pipe_maximum = _bounds_m("Pipe")
    assert (pipe_maximum[0] - pipe_minimum[0]) == pytest.approx(1.2, abs=1.0e-3)
    assert (pipe_maximum[2] - pipe_minimum[2]) == pytest.approx(0.1, abs=1.0e-3)

    # Independent measurement of the same ends, from the AABB face
    # centres, against each mesh's SURFACE.
    near_end_m = _end_face_centre_along_x_m("Pipe", "min")
    far_end_m = _end_face_centre_along_x_m("Pipe", "max")
    near_to_bellows_m = _surface_distance_m(near_end_m, "Bellows")
    near_to_forge_m = _surface_distance_m(near_end_m, "Forge")
    far_to_forge_m = _surface_distance_m(far_end_m, "Forge")
    far_to_bellows_m = _surface_distance_m(far_end_m, "Bellows")

    assert near_to_bellows_m < SPAN_RADIUS_M
    assert far_to_forge_m < SPAN_RADIUS_M
    # Each end is nearer its OWN object than the other's — a bounding-box
    # overlap would not prove this.
    assert near_to_bellows_m < near_to_forge_m
    assert far_to_forge_m < far_to_bellows_m


# --- condition 6: a span that passes through a third object ------------


def test_a_span_crossing_a_third_object_lists_it_in_collides_with(empty_scene):
    """Condition 6: the crossed object is named, and the two ends are not."""
    from golem_blender.ops.alignment import span_between

    _piece("Bellows", (-1.5, -0.3, 0.0), (-0.5, 0.3, 0.6))
    _piece("Forge", (0.7, -0.3, 0.0), (1.7, 0.3, 0.6))
    # Wide enough in y/z to contain the pipe's cross-section wherever the
    # corner anchors land it.
    _piece("Blocker", (-0.1, -0.35, -0.1), (0.1, 0.35, 0.7))
    _piece("Pipe", (0.0, -0.05, -0.6), (0.1, 0.05, 0.6))

    report = span_between("Pipe", "Bellows", "Forge", SPAN_RADIUS_M)

    assert "Blocker" in report.collides_with
    # Resting contact is not a clash: the ends stay clear of their own
    # objects, which is what makes `collides_with` mean penetration.
    assert "Bellows" in report.clear_of
    assert "Forge" in report.clear_of
    assert "Bellows" not in report.collides_with


# --- condition 7: a child of an empty ---------------------------------


def test_aligning_a_child_moves_the_world_feature_not_the_parent(empty_scene):
    """Condition 7: the parent's world location is untouched and the
    child's world feature lands on the target."""
    from golem_blender.ops.alignment import align_to

    _piece("Wall", (2.0, 2.0, 0.0), (5.0, 2.2, 3.0))
    _piece("Pier", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    empty = bpy.data.objects.new("Root", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (0.0, 5.0, 0.0)
    bpy.data.objects["Pier"].parent = empty
    bpy.context.view_layer.update()

    parent_location_before_m = tuple(empty.matrix_world.translation)
    assert _bounds_m("Pier")[1][1] == pytest.approx(5.0 + 0.314, abs=1.0e-5)

    align_to("Pier", "Wall", "max_y", "min_y")

    assert _bounds_m("Pier")[1][1] == pytest.approx(2.0, abs=FACE_TOLERANCE_M)
    assert tuple(empty.matrix_world.translation) == pytest.approx(
        parent_location_before_m, abs=1.0e-9
    )


# --- condition 8: gated, with a verdict -------------------------------


def test_the_placement_ops_are_gated_and_the_dispatch_reports_a_verdict(empty_scene):
    """Condition 8: the same verdict shape every gated op produces."""
    from golem_blender.agent.op_call import call_op
    from golem_blender.agent.tools import OP_FUNCTIONS
    from golem_blender.ops._contract import is_gated
    from golem_blender.ops.alignment import align_to, span_between, stand_against
    from golem_blender.stages import STAGE_DONE

    for placement_op in (align_to, stand_against, span_between):
        assert is_gated(placement_op), placement_op.__name__

    _piece("Pier", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    _piece("Wall", (2.0, 2.0, 0.0), (5.0, 2.2, 3.0))

    result = call_op(
        "align_to",
        OP_FUNCTIONS["align_to"],
        {
            "object_name": "Pier",
            "target_name": "Wall",
            "object_feature": "max_y",
            "target_feature": "min_y",
        },
    )

    # The gate measures the report's own `object_name` field.
    assert [gate.object_name for gate in result.gates] == ["Pier"]
    assert result.gates[0].stage_reached == STAGE_DONE
    assert result.ok and result.stage_reached == STAGE_DONE
    assert "gate: PASS" in result.summary(1500)


# --- the issue's plane spelling --------------------------------------


def test_a_plane_target_is_the_same_placement_in_both_spellings(empty_scene):
    """The issue's edge case: a target with no measurable feature on the
    axis is given as an explicit coordinate, and both accepted spellings
    must produce the same move.

    Two congruent piers placed on the SAME plane, one spelled
    `TargetPlane(...)` (what the generated tool schema declares) and one
    the issue's `("plane", axis, coordinate)` triple: identical local
    geometry means any difference in the result is the spelling's.
    """
    from golem_blender.ops.alignment import TargetPlane, align_to

    _piece("PierA", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)
    _piece("PierB", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)

    by_dataclass = align_to("PierA", "PierB", "max_y", TargetPlane("y", 2.594))
    by_triple = align_to("PierB", "PierA", "max_y", ("plane", "y", 2.594))

    assert by_dataclass.feature_target_m[1] == pytest.approx(2.594, abs=1.0e-9)
    assert by_triple.feature_target_m[1] == pytest.approx(2.594, abs=1.0e-9)
    # The pier's origin is 11.1 cm off its bounds centre, so the move is
    # the plane minus the FACE, never minus the origin: 2.594 - 0.314.
    assert by_dataclass.moved_m == pytest.approx((0.0, 2.594 - 0.314, 0.0), abs=1.0e-5)
    assert by_triple.moved_m == by_dataclass.moved_m
    # Float32 vertex data leaves ~1.4e-7 m of residual, four orders
    # under the issue's own 1e-4 face tolerance.
    assert by_dataclass.achieved_gap_m == pytest.approx(0.0, abs=FACE_TOLERANCE_M)
    assert by_triple.achieved_gap_m == pytest.approx(0.0, abs=FACE_TOLERANCE_M)
    assert _bounds_m("PierA")[1][1] == pytest.approx(
        _bounds_m("PierB")[1][1], abs=FACE_TOLERANCE_M
    )


def test_a_gap_against_a_plane_stands_off_the_target_side(empty_scene):
    """The plane target takes the same gap sign rule as a `min` face: a
    `max_y` face on the plane at 2.594 with 10 mm of stand-off lands at
    2.584, not 2.604 — the direction the issue's boolean case needs."""
    from golem_blender.ops.alignment import TargetPlane, align_to

    _piece("Pier", PIER_MINIMUM_CORNER_M, PIER_MAXIMUM_CORNER_M)

    report = align_to("Pier", "Pier", "max_y", TargetPlane("y", 2.594), gap_m=0.01)

    assert _bounds_m("Pier")[1][1] == pytest.approx(2.584, abs=FACE_TOLERANCE_M)
    assert report.achieved_gap_m == pytest.approx(0.01, abs=FACE_TOLERANCE_M)
