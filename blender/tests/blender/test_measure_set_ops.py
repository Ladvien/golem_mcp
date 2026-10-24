"""Issue #23: a piece is several objects, so measure the SET as one piece.

`analyze_object` / `inspect_object` measure ONE object. Every real asset is
several, so the three questions a piece actually has to answer were
unanswerable from inside golem:

1. how many triangles is the piece (Sanctuary's LOD budget is per piece:
   2 000 at LOD0, 60% at LOD1, 30% at LOD2),
2. do its parts pass through each other,
3. are all its parts actually linked (a run shipped a piece whose second
   object was created unlinked, so the export silently missed it).

Each was answered by a script over the written `.glb`/`.blend` — a
verification path that bypasses the gate. These are the issue's own six
acceptance criteria.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

# Exactly 100 triangles: subdividing the cube's four vertical edges into 12
# quads each leaves 48 side quads plus the two caps = 50 quads = 100
# triangles. Measured in Blender 5.2: 50 polygons / 100 triangles.
VERTICAL_EDGE_CUTS = 11
BOX_TRIANGLES = 100
BOX_EDGE_M = 1.0
# "One at the origin and one at (3, 0, 0)": the boxes' minimum corners, so
# the union spans 0..4 on x and the gap between their near faces is 3 m.
ORIGIN_BOX_MIN_X_M = 0.0
SECOND_BOX_MIN_X_M = 3.0
EXPECTED_PIECE_X_M = SECOND_BOX_MIN_X_M + BOX_EDGE_M - ORIGIN_BOX_MIN_X_M

BOUNDS_TOLERANCE_M = 1.0e-3

# Criterion 3: the boxes share 0.1 m of x. y and z are staggered by the
# same 0.1 m so no face plane of one lies in a face plane of the other —
# the interpenetration is genuinely three-dimensional, and the depth is
# the x overlap alone.
OVERLAP_M = 0.1
TOUCHING_X_M = ORIGIN_BOX_MIN_X_M + BOX_EDGE_M


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _hundred_triangle_box(name: str, min_corner_m: tuple[float, float, float]):
    """A BOX_EDGE_M cube carrying exactly BOX_TRIANGLES triangles, linked."""
    import bmesh

    mesh_data = bpy.data.meshes.new(name)
    box_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(box_object)

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=BOX_EDGE_M)
        vertical_edges = [
            edge
            for edge in working_mesh.edges
            if abs(edge.verts[0].co.z - edge.verts[1].co.z) > BOX_EDGE_M / 2.0
        ]
        bmesh.ops.subdivide_edges(
            working_mesh,
            edges=vertical_edges,
            cuts=VERTICAL_EDGE_CUTS,
            use_grid_fill=True,
        )
        half_edge_m = BOX_EDGE_M / 2.0
        for vertex in working_mesh.verts:
            vertex.co.x += min_corner_m[0] + half_edge_m
            vertex.co.y += min_corner_m[1] + half_edge_m
            vertex.co.z += min_corner_m[2] + half_edge_m
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    mesh_data.update()
    return box_object


def _triangle_count(mesh_data) -> int:
    return sum(len(polygon.vertices) - 2 for polygon in mesh_data.polygons)


def _world_vertex_bounds_m(blender_objects):
    """The parts' joint world bounds from their VERTICES.

    Independent of the op's own measurement on purpose: an assertion that
    reads the number back through the code under test proves nothing.
    """
    import math

    from mathutils import Vector

    minimum = [math.inf] * 3
    maximum = [-math.inf] * 3
    for blender_object in blender_objects:
        for vertex in blender_object.data.vertices:
            world = blender_object.matrix_world @ Vector(vertex.co)
            for axis in range(3):
                minimum[axis] = min(minimum[axis], world[axis])
                maximum[axis] = max(maximum[axis], world[axis])
    return minimum, maximum


# --- criterion 1: the piece's triangle total and its span -------------------


def test_two_hundred_triangle_boxes_measure_as_one_piece(empty_scene):
    """Two 100-triangle boxes, one at the origin and one at (3, 0, 0):
    200 triangles, and the piece's x span is the union 0..4, not a sum."""
    from golem_blender.ops import measure_objects

    first = _hundred_triangle_box("PieceBase", (ORIGIN_BOX_MIN_X_M, 0.0, 0.0))
    second = _hundred_triangle_box("PieceTop", (SECOND_BOX_MIN_X_M, 0.0, 0.0))
    assert _triangle_count(first.data) == BOX_TRIANGLES
    assert _triangle_count(second.data) == BOX_TRIANGLES

    report = measure_objects(["PieceBase", "PieceTop"])

    assert report.triangles_total == 2 * BOX_TRIANGLES
    assert report.object_name == "PieceBase", (
        "the report's anchor is the FIRST NAME GIVEN, so the same call always "
        "describes the same piece"
    )
    assert report.triangles_by_object == {
        "PieceBase": BOX_TRIANGLES,
        "PieceTop": BOX_TRIANGLES,
    }
    assert report.objects == ("PieceBase", "PieceTop")
    assert report.dimensions_m[0] == pytest.approx(
        EXPECTED_PIECE_X_M, abs=BOUNDS_TOLERANCE_M
    ), (
        f"x span {report.dimensions_m[0]} m; the boxes' near corners are 3 m "
        f"apart and each is {BOX_EDGE_M} m wide, so the union spans "
        f"{EXPECTED_PIECE_X_M} m"
    )


# --- criterion 2: the silent-skip case --------------------------------------


def test_a_name_with_no_object_is_reported_unlinked_and_excluded(empty_scene):
    """A name that resolves to nothing is REPORTED, never raised, and its
    phantom triangles are in no total."""
    from golem_blender.ops import measure_objects

    _hundred_triangle_box("PresentPart", (0.0, 0.0, 0.0))

    report = measure_objects(["PresentPart", "NeverCreated"])

    assert report.unlinked == ("NeverCreated",)
    assert report.objects == ("PresentPart",)
    assert report.triangles_total == BOX_TRIANGLES
    assert "NeverCreated" not in report.triangles_by_object


def test_an_object_created_but_never_linked_is_reported_unlinked(empty_scene):
    """The bug the issue was filed from: `add_box` returns an object that
    is NOT in the scene until `link_into_scene`. It exists in
    bpy.data.objects, so a naive set measurement counts its triangles while
    the export silently misses it. It belongs in `unlinked`."""
    from golem_blender.ops import add_box, link_into_scene, measure_objects

    linked = add_box("LinkedPart", 0.5, 0.5, 0.5)
    link_into_scene(linked)
    unlinked = add_box("ForgottenPart", 0.5, 0.5, 0.5)
    assert unlinked in bpy.data.objects, "the fixture must EXIST and be unlinked"
    assert unlinked not in bpy.context.scene.objects

    report = measure_objects(["LinkedPart", "ForgottenPart"])

    assert report.unlinked == ("ForgottenPart",)
    assert report.triangles_total == 12, (
        f"counted {report.triangles_total} triangles: the unlinked box's 12 "
        f"must be in no total, or the piece measures geometry that will "
        f"never ship"
    )


def test_a_set_whose_every_name_is_unlinked_is_refused(empty_scene):
    """A piece of zero measured parts would report 0 triangles and pass any
    LOD budget. That is the same silent wrong answer, so it raises."""
    from golem_blender.ops import measure_objects

    with pytest.raises(ValueError, match="Nothing to measure"):
        measure_objects(["GhostOne", "GhostTwo"])


def test_an_empty_or_duplicated_name_list_is_refused(empty_scene):
    """Nothing to anchor the report on, and a name twice would double a
    part's triangles in the piece's budget."""
    from golem_blender.ops import measure_objects

    _hundred_triangle_box("SoloPart", (0.0, 0.0, 0.0))

    with pytest.raises(ValueError, match="at least one object name"):
        measure_objects([])
    with pytest.raises(ValueError, match="more than once"):
        measure_objects(["SoloPart", "SoloPart"])


# --- criterion 3: interpenetration, and what is NOT interpenetration --------


def _overlapping_pair():
    first = _hundred_triangle_box("OverlapBase", (0.0, 0.0, 0.0))
    second = _hundred_triangle_box(
        "OverlapLid", (BOX_EDGE_M - OVERLAP_M, OVERLAP_M, OVERLAP_M)
    )
    return first, second


def test_two_parts_overlapping_by_ten_centimetres_report_one_intersection(
    empty_scene,
):
    from golem_blender.ops import measure_objects

    _overlapping_pair()

    report = measure_objects(
        ["OverlapBase", "OverlapLid"], check_part_intersections=True
    )

    assert report.part_intersections_checked is True
    assert report.part_intersections == (("OverlapBase", "OverlapLid"),)


def test_touching_parts_report_no_intersection(empty_scene):
    """A lid sitting exactly on its body shares a face and is not an
    intersection — the distinction `boolean_union`'s BooleanNoOp and
    pair_checks' contact tolerance already carry."""
    from golem_blender.ops import measure_objects, move_object_to

    _overlapping_pair()
    move_object_to("OverlapLid", (TOUCHING_X_M, 0.0, 0.0))

    report = measure_objects(
        ["OverlapBase", "OverlapLid"], check_part_intersections=True
    )

    assert report.part_intersections_checked is True
    assert report.part_intersections == (), (
        f"face-to-face contact reported as {report.part_intersections}; a "
        f"part resting on another is not a clash"
    )


def test_pairs_are_not_measured_unless_asked_for(empty_scene):
    """The pairwise measurement is the expensive one, so it is opt-in —
    and the report says whether it ran, because an empty tuple means
    'none found' only when it did."""
    from golem_blender.ops import measure_objects

    _overlapping_pair()

    report = measure_objects(["OverlapBase", "OverlapLid"])

    assert report.part_intersections_checked is False
    assert report.part_intersections == ()


# --- criterion 4: the union of world bounds, never a sum --------------------


def test_dimensions_are_the_union_of_the_parts_world_bounds(empty_scene):
    """Two parts inside one another's span: a SUM would report 2 m, a union
    reports 1 m. One part is yawed, so a local-space box reports the wrong
    thing as well."""
    import math

    from golem_blender.ops import measure_objects, rotate_object_euler

    _hundred_triangle_box("UnionBase", (0.0, 0.0, 0.0))
    _hundred_triangle_box("UnionInset", (0.25, 0.25, 0.25))
    rotate_object_euler("UnionInset", z_rad=math.radians(30.0))

    report = measure_objects(["UnionBase", "UnionInset"])

    minimum, maximum = _world_vertex_bounds_m(
        [bpy.data.objects["UnionBase"], bpy.data.objects["UnionInset"]]
    )
    for axis in range(3):
        assert report.dimensions_m[axis] == pytest.approx(
            maximum[axis] - minimum[axis], abs=BOUNDS_TOLERANCE_M
        ), f"axis {axis}: report {report.dimensions_m}, world {minimum}..{maximum}"
    assert report.dimensions_m[0] < 2 * BOX_EDGE_M, (
        "the parts overlap, so summing their extents is not a measurement"
    )
    assert report.lowest_point_m == pytest.approx(minimum[2], abs=BOUNDS_TOLERANCE_M)


# --- criterion 5: the same triangle count the analyzer reports --------------


def test_triangles_total_matches_the_analyzer_per_object(empty_scene):
    """The piece's budget has to be the sum of the numbers `inspect_object`
    prints, or the writer checks its LOD against one measurement and ships
    another."""
    from golem_blender.analyze import analyze_object
    from golem_blender.ops import (
        add_box,
        add_cylinder,
        link_into_scene,
        measure_objects,
    )

    _hundred_triangle_box("CountBox100", (0.0, 0.0, 0.0))
    plain_box = add_box("CountBox12", 0.4, 0.4, 0.4)
    link_into_scene(plain_box)
    cylinder = add_cylinder("CountCylinder", radius_m=0.2, height_m=0.5)
    link_into_scene(cylinder)
    names = ["CountBox100", "CountBox12", "CountCylinder"]

    report = measure_objects(names)

    from_analyzer = {
        name: analyze_object(bpy.data.objects[name]).triangle_count for name in names
    }
    assert report.triangles_by_object == from_analyzer
    assert report.triangles_total == sum(from_analyzer.values())


# --- materials: distinct, not slots ----------------------------------------


def test_one_material_worn_by_two_parts_counts_once(empty_scene):
    from golem_blender.ops import (
        add_box,
        assign_material,
        link_into_scene,
        measure_objects,
    )

    for name in ("BodyPart", "LidPart"):
        link_into_scene(add_box(name, 0.4, 0.4, 0.4))
        assign_material(name, "CrateWood")

    assert measure_objects(["BodyPart", "LidPart"]).material_slots == 1

    link_into_scene(add_box("IronPart", 0.2, 0.2, 0.2))
    assign_material("IronPart", "CrateIron")

    report = measure_objects(["BodyPart", "LidPart", "IronPart"])
    assert report.material_slots == 2, (
        f"counted {report.material_slots}: slots are 3 and materials are 2"
    )


# --- criterion 6: the op is read-only --------------------------------------


def test_measure_objects_changes_nothing(empty_scene):
    """Criterion 6, measured rather than declared: no object, transform or
    material moves, and no datablock appears or disappears."""
    from golem_blender.ops import assign_material, link_into_scene, measure_objects
    from golem_blender.ops.primitives import add_box

    _hundred_triangle_box("ReadBase", (0.0, 0.0, 0.0))
    _hundred_triangle_box("ReadLid", (BOX_EDGE_M - OVERLAP_M, OVERLAP_M, OVERLAP_M))
    link_into_scene(add_box("ReadPlain", 0.3, 0.3, 0.3))
    assign_material("ReadBase", "ReadMaterial")

    def _snapshot():
        return {
            "objects": sorted(bpy.data.objects.keys()),
            "meshes": sorted(bpy.data.meshes.keys()),
            "materials": sorted(bpy.data.materials.keys()),
            "scene_objects": sorted(bpy.context.scene.objects.keys()),
            "state": {
                name: (
                    tuple(
                        round(value, 9)
                        for row in blender_object.matrix_world
                        for value in row
                    ),
                    len(blender_object.data.vertices),
                    len(blender_object.data.polygons),
                    tuple(
                        round(coordinate, 9)
                        for vertex in blender_object.data.vertices
                        for coordinate in vertex.co
                    ),
                    tuple(
                        slot.material.name if slot.material else ""
                        for slot in blender_object.material_slots
                    ),
                )
                for name, blender_object in bpy.data.objects.items()
            },
        }

    before = _snapshot()
    measure_objects(["ReadBase", "ReadLid", "ReadPlain"], check_part_intersections=True)
    after = _snapshot()

    assert after == before


def test_measure_objects_is_a_declared_reader():
    """A reader needs no declared plan; the contract reads this marker."""
    from golem_blender.ops import measure_objects
    from golem_blender.ops._contract import changes_scene, is_gated, is_reads_only

    assert is_reads_only(measure_objects)
    assert not changes_scene(measure_objects)
    assert not is_gated(measure_objects), (
        "a set report may name the first part, but the gate measures a scene "
        "object with a mesh budget; this op measures and must not claim a "
        "verdict it does not issue"
    )
