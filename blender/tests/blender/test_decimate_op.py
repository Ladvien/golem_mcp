"""Issue #16: a piece golem built can be given LOD levels, in the live session.

Sanctuary's decision 0294 wants every kit piece shipped three times — LOD0,
LOD1 at 60% of LOD0's triangles and LOD2 at 30%. Building a piece through
golem was the preferred path, but the only decimation in the tree was inside
`import_generated_asset`, so an LOD meant leaving the session for a headless
`--background` Blender and losing the gate, the viewport and the analyzer.

Every acceptance condition here is the issue's own, measured on a real mesh
rather than asserted from the implementation. Two of the issue's own beliefs
about COLLAPSE turned out to be wrong, and both are recorded where they were
measured: a mesh does NOT stop at 48 triangles (four boxes flatten to 8, two
coincident triangles each, at zero volume), and a ratio does NOT land exactly
on its product (it lands within a face or two, which is why the op aims,
measures and aims again).
"""

import bmesh
import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

POSITION_TOLERANCE_M = 1.0e-4
# A four-part fixture's parts are 0.4 m boxes, so each holds 0.064 m3.
BOX_VOLUME_M3 = 0.064
PART_COUNT = 4
# The issue's acceptance condition 1: within 2% of the requested count.
TARGET_TOLERANCE = 0.02


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _triangle_count(object_name):
    from golem_blender.ops.assets import _triangle_count as count_triangles

    return count_triangles(bpy.data.objects[object_name].data)


def _subdivide(object_name, cut_count):
    """Subdivide every edge in place, through bmesh rather than bpy.ops.

    An edit-mode operator needs an active object and a context override; the
    bmesh op needs neither, and this suite runs headless.
    """
    blender_object = bpy.data.objects[object_name]
    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(blender_object.data)
        bmesh.ops.subdivide_edges(
            working_mesh,
            edges=list(working_mesh.edges),
            cuts=cut_count,
            use_grid_fill=True,
        )
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _four_separate_boxes(cut_count=1):
    """Four boxes joined into ONE mesh, as a kit piece's parts are after join_objects."""
    from golem_blender.ops.assets import join_objects
    from golem_blender.ops.primitives import add_box, link_into_scene

    parts = []
    for part_index in range(PART_COUNT):
        part_name = add_box(
            f"Part{part_index}", 0.4, 0.4, 0.4, (part_index * 0.5, 0.0, 0.0)
        )
        link_into_scene(part_name)
        _subdivide(part_name, cut_count)
        parts.append(part_name)
    return join_objects(parts, "FourParts")


def _part_triangle_counts(object_name):
    """Triangles per edge-connected part, in no particular order."""
    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(bpy.data.objects[object_name].data)
        working_mesh.faces.ensure_lookup_table()
        working_mesh.faces.index_update()
        part_of_face = [-1] * len(working_mesh.faces)
        part_count = 0
        for face in working_mesh.faces:
            if part_of_face[face.index] != -1:
                continue
            frontier = [face]
            part_of_face[face.index] = part_count
            while frontier:
                current_face = frontier.pop()
                for edge in current_face.edges:
                    for neighbour in edge.link_faces:
                        if part_of_face[neighbour.index] == -1:
                            part_of_face[neighbour.index] = part_count
                            frontier.append(neighbour)
            part_count += 1
        counts = [0] * part_count
        for face in working_mesh.faces:
            counts[part_of_face[face.index]] += len(face.verts) - 2
        return counts
    finally:
        working_mesh.free()


def _uv_layout(object_name):
    """(UV area / 3D area) of every triangle: medians move if islands are cut."""
    mesh = bpy.data.objects[object_name].data
    mesh.calc_loop_triangles()
    uv_data = mesh.uv_layers.active.data
    ratios = []
    for triangle in mesh.loop_triangles:
        loops = list(triangle.loops)
        corners = [mesh.vertices[mesh.loops[loop].vertex_index].co for loop in loops]
        uvs = [uv_data[loop].uv for loop in loops]
        geometric_area = (corners[1] - corners[0]).cross(corners[2] - corners[0]).length
        uv_area = abs((uvs[1] - uvs[0]).cross(uvs[2] - uvs[0]))
        if geometric_area > 1.0e-12:
            ratios.append(uv_area / geometric_area)
    ratios.sort()
    return ratios[len(ratios) // 2]


def _linked_cylinder(name, segment_count):
    from golem_blender.ops.primitives import add_cylinder, link_into_scene

    cylinder_name = add_cylinder(name, 0.3, 1.0, segment_count)
    link_into_scene(cylinder_name)
    return cylinder_name


# --- acceptance condition 1: a 10 000-triangle mesh reaches 3000 -----------


def test_a_ten_thousand_triangle_mesh_reaches_its_target(empty_scene):
    """Condition 1: 10 000 tris with target_triangles=3000 lands within 2%."""
    from golem_blender.ops.modifiers import decimate_object

    mesh_name = _linked_cylinder("Vessel", 2600)
    assert _triangle_count(mesh_name) > 10_000

    report = decimate_object(mesh_name, target_triangles=3000)

    assert report.triangles_before > 10_000
    assert report.triangles_after == pytest.approx(3000, rel=TARGET_TOLERANCE)
    assert report.reached_target is True
    # The count in the report IS the count on the object, not the plan.
    assert _triangle_count(mesh_name) == report.triangles_after
    assert report.target_triangles == 3000


def test_the_ratio_argument_aims_at_the_same_budget(empty_scene):
    """A ratio is the shorthand for the same thing: ratio * before, in triangle terms."""
    from golem_blender.ops.modifiers import decimate_object

    mesh_name = _linked_cylinder("Vessel", 2600)
    triangles_before = _triangle_count(mesh_name)

    report = decimate_object(mesh_name, ratio=0.3)

    assert report.target_triangles == round(triangles_before * 0.3)
    assert report.triangles_after == pytest.approx(
        report.target_triangles, rel=TARGET_TOLERANCE
    )
    assert report.reached_target is True


# --- acceptance condition 2: a target below the topology is reported -----


def test_an_unreachable_target_is_reported_and_every_part_survives(empty_scene):
    """Condition 2: below the floor, `reached_target` is false and nothing is lost.

    MEASURED, against what the issue believed: the issue says four boxes
    "cannot be collapsed below 48 triangles without deleting one". A box CAN
    be collapsed further — at 50 triangles the four parts survive at their
    full 0.064 m3 each, and the true floor is 8 triangles (two coincident
    triangles per part, at zero volume). So the unreachable target is 4, not
    50, and the caller reading `reached_target: false` still finds every part
    present.
    """
    from golem_blender.ops.modifiers import decimate_object

    joined = _four_separate_boxes()
    assert joined.parts_joined == PART_COUNT
    assert _triangle_count("FourParts") == 192

    report = decimate_object("FourParts", target_triangles=4)

    assert report.reached_target is False
    assert report.triangles_after > 0, "an empty mesh is a deleted piece, not an LOD"
    assert report.parts_present == PART_COUNT
    assert len(_part_triangle_counts("FourParts")) == PART_COUNT
    assert all(
        triangle_count > 0 for triangle_count in _part_triangle_counts("FourParts")
    )


def test_fifty_triangles_from_two_hundred_keeps_every_part_at_its_volume(empty_scene):
    """The issue's own example number, measured: 50 IS reachable, and it is honest.

    Recorded so the next reader does not re-derive it: the issue expected
    `reached_target: false` at 50. Collapse reaches 50 exactly, and all four
    parts keep their full volume, so reporting failure there would be a lie
    that made callers drop a part for no reason.
    """
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.modifiers import decimate_object

    _four_separate_boxes()

    report = decimate_object("FourParts", target_triangles=50)

    assert report.triangles_after == pytest.approx(50, rel=TARGET_TOLERANCE)
    assert report.reached_target is True
    assert report.parts_present == PART_COUNT
    measured = analyze_object(bpy.data.objects["FourParts"])
    # 4 x 0.064 m3: no part was flattened, so no part is missing volume.
    assert measured.volume_m3 == pytest.approx(PART_COUNT * BOX_VOLUME_M3, rel=0.01)


# --- acceptance condition 3: no-op at the count it already has ------------


def test_a_target_at_the_current_count_moves_no_vertex(empty_scene):
    """Condition 3: byte-identical positions, and no pass is spent."""
    from golem_blender.ops.modifiers import decimate_object

    mesh_name = _linked_cylinder("Vessel", 400)
    positions_before = [
        tuple(vertex.co) for vertex in bpy.data.objects[mesh_name].data.vertices
    ]

    report = decimate_object(mesh_name, target_triangles=_triangle_count(mesh_name))

    positions_after = [
        tuple(vertex.co) for vertex in bpy.data.objects[mesh_name].data.vertices
    ]
    assert positions_after == positions_before
    assert report.decimate_passes == 0
    assert report.reached_target is True
    assert report.triangles_before == report.triangles_after


def test_a_ratio_of_one_moves_no_vertex(empty_scene):
    """The same no-op by the other argument, so neither path can drift."""
    from golem_blender.ops.modifiers import decimate_object

    mesh_name = _linked_cylinder("Vessel", 400)
    positions_before = [
        tuple(vertex.co) for vertex in bpy.data.objects[mesh_name].data.vertices
    ]

    report = decimate_object(mesh_name, ratio=1.0)

    assert [
        tuple(v.co) for v in bpy.data.objects[mesh_name].data.vertices
    ] == positions_before
    assert report.decimate_passes == 0 and report.reached_target is True


# --- acceptance condition 4: the gate verdict ----------------------------


def test_the_op_is_gated_and_the_dispatch_reports_a_verdict(empty_scene):
    """Condition 4: the same verdict shape every other gated op produces."""
    from golem_blender.agent.op_call import call_op
    from golem_blender.agent.tools import OP_FUNCTIONS
    from golem_blender.ops._contract import is_gated
    from golem_blender.ops.modifiers import decimate_object
    from golem_blender.stages import STAGE_DONE

    assert is_gated(decimate_object)
    mesh_name = _linked_cylinder("Vessel", 400)

    result = call_op(
        "decimate_object",
        OP_FUNCTIONS["decimate_object"],
        {"object_name": mesh_name, "ratio": 0.3},
    )

    # The gate measures the report's own `object_name` field, never the
    # dataclass, so a report-returning gated op cannot crash the dispatcher.
    assert [gate.object_name for gate in result.gates] == [mesh_name]
    assert result.gates[0].stage_reached == STAGE_DONE
    assert result.ok and result.stage_reached == STAGE_DONE
    assert "gate: PASS" in result.summary(1500)


# --- acceptance condition 5: material slots ------------------------------


def test_three_material_slots_still_three_after_the_op(empty_scene):
    """Condition 5: collapse reassigns faces across slots, it does not drop them."""
    from golem_blender.ops.modifiers import decimate_object
    from golem_blender.ops.primitives import add_box, link_into_scene

    box_name = add_box("ThreeSlots", 1.0, 1.0, 1.0, (0.0, 0.0, 0.0))
    link_into_scene(box_name)
    _subdivide(box_name, 3)
    mesh = bpy.data.objects[box_name].data
    for slot_name in ("Red", "Green", "Blue"):
        mesh.materials.append(bpy.data.materials.new(slot_name))
    for polygon in mesh.polygons:
        polygon.material_index = polygon.index % 3

    report = decimate_object(box_name, ratio=0.4)

    assert report.material_slots == 3
    assert [
        material.name for material in bpy.data.objects[box_name].data.materials
    ] == ["Red", "Green", "Blue"]
    # Every slot still wears faces: a slot kept but unused would satisfy the
    # count while having dropped a third of the piece's material.
    used_slots = {
        polygon.material_index for polygon in bpy.data.objects[box_name].data.polygons
    }
    assert used_slots == {0, 1, 2}
    assert report.triangles_after < report.triangles_before


# --- the boundary decision the issue asks to be made explicitly ----------


def test_preserve_boundary_keeps_every_open_edge_vertex(empty_scene):
    """`preserve_boundary` is measurable, not decorative.

    A COLLAPSE modifier has no boundary flag, so the op pins open-edge
    vertices with an inverted vertex group. Measured on a 40x40 grid at ratio
    0.3: 160 boundary edge-keys before and after with the pin, 79 without it.
    The pin also keeps quads, so the surface keeps its structure.
    """
    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.ops.modifiers import decimate_object

    bpy.ops.mesh.primitive_grid_add(x_subdivisions=40, y_subdivisions=40, size=2.0)
    grid = bpy.context.object
    boundary_before = analyze_object(grid, MeshBudget()).boundary_edge_count

    keep = grid.copy()
    keep.data = grid.data.copy()
    keep.name = "Pinned"
    bpy.context.scene.collection.objects.link(keep)
    keep_report = decimate_object("Pinned", ratio=0.3, preserve_boundary=True)

    drop = grid.copy()
    drop.data = grid.data.copy()
    drop.name = "Unpinned"
    bpy.context.scene.collection.objects.link(drop)
    drop_report = decimate_object("Unpinned", ratio=0.3, preserve_boundary=False)

    assert keep_report.boundary_edge_count == boundary_before
    assert drop_report.boundary_edge_count < boundary_before
    assert keep_report.triangles_after == pytest.approx(
        drop_report.triangles_after, rel=0.1
    ), "the pin must cost a comparable count, or it is not the same decimation"


def test_the_pin_group_is_removed_and_other_groups_kept(empty_scene):
    """The reserved group must not leak into a rigged piece's groups."""
    from golem_blender.ops.modifiers import BOUNDARY_PIN_GROUP_NAME, decimate_object

    mesh_name = _linked_cylinder("Vessel", 400)
    bpy.data.objects[mesh_name].vertex_groups.new(name="RigWeight")

    decimate_object(mesh_name, ratio=0.3)

    group_names = [group.name for group in bpy.data.objects[mesh_name].vertex_groups]
    assert group_names == ["RigWeight"]
    assert BOUNDARY_PIN_GROUP_NAME not in group_names


# --- UVs: the layer survives, the layout is the caller's problem ----------


def test_the_uv_layer_survives_and_is_reported(empty_scene):
    """The issue's UV edge case, measured rather than documented as a risk."""
    from golem_blender.ops.modifiers import decimate_object

    bpy.ops.mesh.primitive_uv_sphere_add(segments=102, ring_count=51)
    sphere = bpy.context.object
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project()
    bpy.ops.object.mode_set(mode="OBJECT")
    sphere.name = "Sphere"
    scale_before = _uv_layout("Sphere")

    report = decimate_object("Sphere", target_triangles=3000)

    assert report.uv_layer_count == 1
    assert len(bpy.data.objects["Sphere"].data.uv_layers) == 1
    # Measured: smart-project's per-triangle UV/3D area ratio is 0.0477 before
    # and 0.0463 after at 3000 triangles, so the layout stretches by ~3%; it
    # is not the wholesale destruction the issue anticipated and the layer
    # count alone could not show.
    assert _uv_layout("Sphere") == pytest.approx(scale_before, rel=0.25)


# --- the refusals: a call that cannot succeed mutates nothing ------------


def test_both_budgets_or_neither_is_refused(empty_scene):
    from golem_blender.ops.modifiers import decimate_object

    mesh_name = _linked_cylinder("Vessel", 64)
    positions_before = [
        tuple(vertex.co) for vertex in bpy.data.objects[mesh_name].data.vertices
    ]

    with pytest.raises(ValueError, match="target_triangles or ratio"):
        decimate_object(mesh_name)
    with pytest.raises(ValueError, match="not both"):
        decimate_object(mesh_name, target_triangles=32, ratio=0.5)

    assert [
        tuple(v.co) for v in bpy.data.objects[mesh_name].data.vertices
    ] == positions_before


def test_a_pending_modifier_is_refused_rather_than_baked(empty_scene):
    """`apply_all_modifiers` bakes the whole stack; decimating would apply a bevel."""
    from golem_blender.ops.modifiers import add_bevel, decimate_object

    mesh_name = _linked_cylinder("Vessel", 64)
    add_bevel(mesh_name, 0.01, 2)

    with pytest.raises(ValueError, match="unapplied"):
        decimate_object(mesh_name, ratio=0.5)


def test_a_mesh_outside_the_scene_is_refused(empty_scene):
    """An unlinked object's modifier evaluates to nothing (drift catalog)."""
    from golem_blender.ops.modifiers import decimate_object
    from golem_blender.ops.primitives import add_cylinder

    unlinked_name = add_cylinder("Unlinked", 0.3, 1.0, 64)

    with pytest.raises(ValueError, match="not linked into the scene"):
        decimate_object(unlinked_name, ratio=0.5)
