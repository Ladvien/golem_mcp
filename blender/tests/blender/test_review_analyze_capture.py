"""Regression tests for the analyze_capture review slice (needs bpy)."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

FOLDED_HOLE_SUBDIVISIONS = 3
FOLDED_HOLE_RADIUS_M = 0.15
LOOSE_VERTEX_LOCATIONS_M = ((3.0, 3.0, 3.0), (3.0, 3.0, 4.0))


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _folded_hole_object_with_loose_vertices(name):
    """A sphere with one hole whose fill folds (a rim vertex mirrored
    through the hole plane) plus loose vertices that cleanup deletes."""
    import bmesh
    import mathutils

    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(
            working_mesh,
            subdivisions=FOLDED_HOLE_SUBDIVISIONS,
            radius=FOLDED_HOLE_RADIUS_M,
        )
        for face in working_mesh.faces:
            face.smooth = True
        working_mesh.faces.ensure_lookup_table()
        working_mesh.faces.remove(working_mesh.faces[0])
        rim_vertices = list(
            {
                vertex
                for edge in working_mesh.edges
                if len(edge.link_faces) == 1
                for vertex in edge.verts
            }
        )
        rim_centre = mathutils.Vector((0.0, 0.0, 0.0))
        for vertex in rim_vertices:
            rim_centre += mathutils.Vector(vertex.co)
        rim_centre /= len(rim_vertices)
        rim_vertices[0].co = rim_centre * 2.0 - mathutils.Vector(rim_vertices[0].co)
        for location_m in LOOSE_VERTEX_LOCATIONS_M:
            working_mesh.verts.new(location_m)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    scene_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(scene_object)
    return scene_object


def test_reverted_fill_keeps_the_cleanup_that_preceded_it(empty_scene):
    """Measured: on a folded hole with two loose vertices the actions log
    said "deleted 2 loose vertices" and then REVERTED the fill, but the
    revert restored the untouched ORIGINAL mesh (the snapshot was copied
    from blender_object.data before the bmesh edits were written back),
    so both loose vertices were back and the component count was 3."""
    from blended.analyze import analyze_object
    from blended.ingest import CleanupSettings, cleanup_mesh

    scene_object = _folded_hole_object_with_loose_vertices("FoldedHoleLoose")
    vertex_count_before = len(scene_object.data.vertices)
    before_report = analyze_object(scene_object)
    assert before_report.connected_component_count == 1 + len(LOOSE_VERTEX_LOCATIONS_M)

    cleanup_report = cleanup_mesh(scene_object, CleanupSettings())

    assert cleanup_report.reverted_hole_fills == 1
    assert any(
        "deleted 2 loose vertices" in action for action in cleanup_report.actions
    )
    assert cleanup_report.after.connected_component_count == 1
    assert cleanup_report.after.boundary_edge_count == before_report.boundary_edge_count
    assert len(scene_object.data.vertices) == (
        vertex_count_before - len(LOOSE_VERTEX_LOCATIONS_M)
    )


def test_analyzer_gate_fails_an_empty_mesh(empty_scene):
    from blended.analyze import MeshBudget, analyze_object

    mesh_data = bpy.data.meshes.new("Nothing")
    empty_object = bpy.data.objects.new("Nothing", mesh_data)
    bpy.context.scene.collection.objects.link(empty_object)

    report = analyze_object(empty_object)

    assert report.triangle_count == 0
    assert any("no faces" in failure for failure in report.failures(MeshBudget()))


def _cone_with_diameter():
    bpy.ops.mesh.primitive_cone_add(diameter1=1.0)


def _read_use_auto_smooth():
    return bpy.data.meshes.new("auto_smooth_probe").use_auto_smooth


def _index_specular_socket():
    material = bpy.data.materials.new("specular_probe")
    material.use_nodes = True
    return material.node_tree.nodes["Principled BSDF"].inputs["Specular"]


def _reach_for_bpy_mathutils():
    return bpy.mathutils


def _index_bmesh_without_lookup_table():
    import bmesh

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh)
        return working_mesh.verts[0]
    finally:
        working_mesh.free()


def _read_action_fcurves():
    return bpy.data.actions.new("fcurves_probe").fcurves


@pytest.mark.parametrize(
    ("raising_call", "expected_symbol_fragment"),
    [
        (_cone_with_diameter, "diameter1"),
        (_read_use_auto_smooth, "use_auto_smooth"),
        (_index_specular_socket, "Specular"),
        (_reach_for_bpy_mathutils, "bpy.mathutils"),
        (_index_bmesh_without_lookup_table, "BMVert.index"),
        (_read_action_fcurves, "Action.fcurves"),
    ],
)
def test_drift_signatures_match_the_error_blender_really_raises(
    empty_scene, raising_call, expected_symbol_fragment
):
    """A signature that never appears in the real traceback makes an
    entry dead weight: measured on 5.2.0, the cone entry looked for
    `is invalid` while Blender says `unrecognized`."""
    import traceback

    from blended.drift.catalog import match_traceback

    with pytest.raises(Exception) as raised:
        raising_call()
    traceback_text = "".join(
        traceback.format_exception(raised.type, raised.value, raised.tb)
    )

    matched_symbols = [entry.symbol for entry in match_traceback(traceback_text)]
    assert any(expected_symbol_fragment in symbol for symbol in matched_symbols), (
        f"{traceback_text.splitlines()[-1]!r} matched {matched_symbols}"
    )
