"""Flipped-normal detection: the fixtures and the clean control."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box_with_flipped_faces(name, flip_face_indices=None, flip_all=False):
    import bmesh

    from blended.ops.primitives import remove_object_and_mesh

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        working_mesh.faces.ensure_lookup_table()
        if flip_all:
            for face in working_mesh.faces:
                face.normal_flip()
        elif flip_face_indices:
            for face_index in flip_face_indices:
                working_mesh.faces[face_index].normal_flip()
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    box_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(box_object)
    return box_object


def test_clean_control_has_no_flipped_triangles(empty_scene):
    from blended.analyze import analyze_object
    from blended.builders import BarrelBuilder, BarrelParameters

    report = analyze_object(BarrelBuilder(BarrelParameters()).build())
    assert report.flipped_normal_triangle_count == 0


def test_single_flipped_face_is_detected(empty_scene):
    from blended.analyze import MeshBudget, analyze_object

    TRIANGLES_PER_QUAD = 2
    box_object = _box_with_flipped_faces("OneFlipped", flip_face_indices=[0])
    report = analyze_object(box_object)
    assert report.flipped_normal_triangle_count == TRIANGLES_PER_QUAD
    assert not report.passes(MeshBudget())


def test_open_mesh_inverted_facet_is_counted(empty_scene):
    """The case that read 0 before the port: an OPEN mesh with a face
    whose winding disagrees with its own normals.

    The parity-ray flipped-normal test only runs on closed manifolds,
    so the old code reported zero normals checking for every open
    prop. Inverted facets are created by decimation and boolean work
    (scp measured backpack 0 -> 15/164 facets, body 0 -> 5/749) and
    recalculating normals does NOT fix them — the geometry has folded.
    """
    import bmesh

    from blended.analyze import MeshBudget, analyze_object

    mesh_data = bpy.data.meshes.new("OpenInverted")
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_icosphere(working_mesh, subdivisions=3, radius=1.0)
        for face in working_mesh.faces:
            face.smooth = True
        working_mesh.faces.ensure_lookup_table()
        bmesh.ops.reverse_faces(working_mesh, faces=[working_mesh.faces[0]])
        bmesh.ops.delete(working_mesh, geom=[working_mesh.faces[1]], context="FACES")
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    open_object = bpy.data.objects.new("OpenInverted", mesh_data)
    bpy.context.scene.collection.objects.link(open_object)

    report = analyze_object(open_object)
    assert report.inverted_facet_count >= 1
    # The mesh is OPEN, so the parity test must be suppressed — the
    # inverted-facet test must not depend on it.
    assert report.boundary_edge_count > 0
    assert report.flipped_normal_triangle_count == 0
    failures = report.failures(MeshBudget())
    assert any("inverted facets" in failure for failure in failures)


def test_clean_open_box_reads_zero_inverted_facets(empty_scene):
    """A clean box, open or closed, must read zero inverted facets —
    the port must not have made every open mesh fail."""
    from blended.analyze import analyze_object

    box_object = _box_with_flipped_faces("CleanBox")
    report = analyze_object(box_object)
    assert report.inverted_facet_count == 0
