"""The cleanup pass against a synthetic generator-grade messy mesh."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _messy_sphere(name, punch_face_count=3):
    """An icosphere with seeded defects: a hole, duplicate vertices,
    a zero-length-edge degenerate face, and loose vertices — the defect
    profile of raw generated geometry."""
    import bmesh

    from blended.ops.primitives import remove_object_and_mesh

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(working_mesh, subdivisions=5, radius=0.5)
        working_mesh.faces.ensure_lookup_table()
        for face in list(working_mesh.faces[:punch_face_count]):
            working_mesh.faces.remove(face)

        working_mesh.verts.ensure_lookup_table()
        for source_vertex in list(working_mesh.verts[:5]):
            working_mesh.verts.new(source_vertex.co)  # exact doubles, loose

        working_mesh.verts.new((2.0, 2.0, 2.0))  # a far loose vertex

        # Degenerate face: two coincident vertices -> zero-length edge.
        degenerate_anchor = working_mesh.verts.new((0.9, 0.0, 0.0))
        degenerate_twin = working_mesh.verts.new((0.9, 0.0, 0.0))
        degenerate_third = working_mesh.verts.new((0.95, 0.05, 0.0))
        working_mesh.faces.new((degenerate_anchor, degenerate_twin, degenerate_third))

        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    messy_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(messy_object)
    return messy_object


def test_cleanup_takes_messy_mesh_to_gate_pass(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.ingest import CleanupSettings, cleanup_mesh

    messy_object = _messy_sphere("MessySphere")
    before_report = analyze_object(messy_object)
    assert before_report.boundary_edge_count > 0
    assert before_report.duplicate_vertex_pair_count > 0
    assert before_report.triangle_count > MeshBudget().maximum_triangle_count

    cleanup_report = cleanup_mesh(messy_object, CleanupSettings())

    failures = cleanup_report.after.failures(MeshBudget())
    assert failures == [], (
        f"failures after cleanup: {failures}; actions: {cleanup_report.actions}"
    )
    assert cleanup_report.after.triangle_count <= MeshBudget().maximum_triangle_count
    assert any("welded" in action for action in cleanup_report.actions)
    assert any("filled hole" in action for action in cleanup_report.actions)
    assert any("decimated" in action for action in cleanup_report.actions)


def test_a_regressing_fill_is_reverted(empty_scene):
    """A fill that costs more than it buys is undone.

    scp measured every cap ordering on valkyrie_body trading open edges
    for non-manifold edges and inverted facets (241 boundary / 0
    non-manifold / 5 inverted -> 36 / 18 / 21). Here one rim vertex is
    mirrored through the hole plane, so the fan folds: filling creates
    an inverted facet and cleanup_mesh must revert, leaving the hole
    open.
    """
    import bmesh
    import mathutils

    from blended.ingest import CleanupSettings, cleanup_mesh

    mesh_data = bpy.data.meshes.new("FoldedHole")
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(working_mesh, subdivisions=3, radius=0.15)
        for face in working_mesh.faces:
            face.smooth = True
        working_mesh.faces.ensure_lookup_table()
        working_mesh.faces.remove(working_mesh.faces[0])
        working_mesh.faces.ensure_lookup_table()
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
        # Mirror one rim vertex through the hole plane: the fan cannot
        # fill it without folding.
        rim_vertices[0].co = rim_centre * 2.0 - mathutils.Vector(rim_vertices[0].co)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    folded_object = bpy.data.objects.new("FoldedHole", mesh_data)
    bpy.context.scene.collection.objects.link(folded_object)

    cleanup_report = cleanup_mesh(folded_object, CleanupSettings())
    assert cleanup_report.reverted_hole_fills == 1
    assert any("REVERTED" in action for action in cleanup_report.actions)
    # The hole stays open: the original boundary count is intact.
    assert cleanup_report.after.boundary_edge_count == (
        cleanup_report.before.boundary_edge_count
    )


def test_a_plain_small_hole_is_still_filled(empty_scene):
    """The revert guard must not switch the fill off: a plain single
    hole on a closed prop is still filled and reports no revert."""
    import bmesh

    from blended.ingest import CleanupSettings, cleanup_mesh

    mesh_data = bpy.data.meshes.new("PlainHole")
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(working_mesh, subdivisions=3, radius=0.05)
        for face in working_mesh.faces:
            face.smooth = True
        working_mesh.faces.ensure_lookup_table()
        working_mesh.faces.remove(working_mesh.faces[0])
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    plain_object = bpy.data.objects.new("PlainHole", mesh_data)
    bpy.context.scene.collection.objects.link(plain_object)

    cleanup_report = cleanup_mesh(plain_object, CleanupSettings())
    assert cleanup_report.reverted_hole_fills == 0
    assert cleanup_report.after.boundary_edge_count == 0
    assert any("filled hole" in action for action in cleanup_report.actions)
