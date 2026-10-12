"""Blender-side regression tests for the 2026-10-07 review follow-up.

Every test failed on the code it guards before the fix; the measured failure is
in the matching MistakeRecord (``blended.evaluate.mistake_memory``).
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

CUBE_HALF_EXTENT_M = 0.5
WIRE_VERTEX_OFFSET_M = 1.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _link_mesh_object(name, vertices, edges, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, edges, faces)
    mesh.update()
    blender_object = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(blender_object)
    return blender_object


def _cube_vertices_and_faces():
    half = CUBE_HALF_EXTENT_M
    vertices = [
        (x, y, z) for z in (-half, half) for y in (-half, half) for x in (-half, half)
    ]
    faces = [
        (0, 2, 3, 1),
        (4, 5, 7, 6),
        (0, 1, 5, 4),
        (2, 6, 7, 3),
        (0, 4, 6, 2),
        (1, 3, 7, 5),
    ]
    return vertices, faces


# --- 2.1: a wire edge is a non-manifold edge ---


def test_a_wire_edge_on_a_closed_cube_fails_the_manifold_gate(empty_scene):
    """A cube plus one edge to a lone vertex has link_faces == 0 on that edge.
    Counted only for `> 2`, the analyzer reported 0 non-manifold edges and the
    gate passed it; Blender's own Select Non-Manifold selects wire edges."""
    from blended.analyze.mesh_checks import MeshBudget, analyze_object

    vertices, faces = _cube_vertices_and_faces()
    wire_vertex_index = len(vertices)
    vertices.append((CUBE_HALF_EXTENT_M + WIRE_VERTEX_OFFSET_M,) * 3)
    corner_index = len(vertices) - 2
    blender_object = _link_mesh_object(
        "WireProbe", vertices, [(corner_index, wire_vertex_index)], faces
    )

    report = analyze_object(blender_object)

    assert report.non_manifold_edge_count == 1
    assert any("non-manifold" in failure for failure in report.failures(MeshBudget()))


# --- 2.3: import_glb recentres on the bounding-box centre ---

BOUNDING_BOX_CENTRE_TOLERANCE_M = 1e-5
LOPSIDED_FACE_CUT_COUNT = 10


def _exported_lopsided_cube_glb(tmp_path):
    """A unit cube whose +X face edges are subdivided, so the vertex MEAN sits
    well off the bounding-box centre (which stays at the origin)."""
    import bmesh

    vertices, faces = _cube_vertices_and_faces()
    blender_object = _link_mesh_object("Lopsided", vertices, [], faces)
    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(blender_object.data)
        working_mesh.edges.ensure_lookup_table()
        positive_x_face_edges = [
            edge
            for edge in working_mesh.edges
            if all(vertex.co.x > 0 for vertex in edge.verts)
        ]
        bmesh.ops.subdivide_edges(
            working_mesh, edges=positive_x_face_edges, cuts=LOPSIDED_FACE_CUT_COUNT
        )
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()
    for scene_object in bpy.data.objects:
        scene_object.select_set(scene_object is blender_object)
    bpy.context.view_layer.objects.active = blender_object
    glb_path = tmp_path / "lopsided.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path), export_format="GLB", use_selection=True
    )
    bpy.data.objects.remove(blender_object)
    return glb_path


def test_import_glb_centres_on_the_bounding_box_not_the_vertex_mean(
    empty_scene, tmp_path
):
    """Recentring on the vertex mean left a mesh with dense vertices on one
    side visibly off-centre: the stated convention is 'centered on X/Y'."""
    from blended.ingest.import_glb import import_glb

    glb_path = _exported_lopsided_cube_glb(tmp_path)

    imported = import_glb(glb_path, "Probe")

    coordinates = [vertex.co for vertex in imported.data.vertices]
    centre_x_m = (min(c.x for c in coordinates) + max(c.x for c in coordinates)) / 2
    centre_y_m = (min(c.y for c in coordinates) + max(c.y for c in coordinates)) / 2
    assert abs(centre_x_m) < BOUNDING_BOX_CENTRE_TOLERANCE_M
    assert abs(centre_y_m) < BOUNDING_BOX_CENTRE_TOLERANCE_M
    assert abs(min(c.z for c in coordinates)) < BOUNDING_BOX_CENTRE_TOLERANCE_M


# --- 2.4: reset_scene restores scene settings, not only datablocks ---

STALE_FRAME_START = 5
STALE_FRAME_END = 99
STALE_FRAME_CURRENT = 42
STALE_UNIT_SCALE_LENGTH = 0.01
STALE_RESOLUTION_X_PX = 321


def test_reset_scene_restores_frame_range_units_and_resolution(empty_scene):
    """A build that changed the frame range, unit scale or resolution left
    them for the next build: reset wiped datablocks only, so a rebuild started
    from residue."""
    from blended import reset

    scene = bpy.context.scene
    scene.frame_start = STALE_FRAME_START
    scene.frame_end = STALE_FRAME_END
    scene.frame_set(STALE_FRAME_CURRENT)
    scene.unit_settings.scale_length = STALE_UNIT_SCALE_LENGTH
    scene.render.resolution_x = STALE_RESOLUTION_X_PX

    reset.reset_scene()

    assert scene.frame_start == reset.CANONICAL_FRAME_START
    assert scene.frame_end == reset.CANONICAL_FRAME_END
    assert scene.frame_current == reset.CANONICAL_FRAME_CURRENT
    assert scene.unit_settings.system == reset.CANONICAL_UNIT_SYSTEM
    assert scene.unit_settings.scale_length == reset.CANONICAL_UNIT_SCALE_LENGTH
    assert scene.unit_settings.length_unit == reset.CANONICAL_LENGTH_UNIT
    assert scene.render.resolution_x == reset.CANONICAL_RESOLUTION_X_PX
    assert scene.render.resolution_y == reset.CANONICAL_RESOLUTION_Y_PX
    assert scene.render.resolution_percentage == reset.CANONICAL_RESOLUTION_PERCENTAGE


def test_a_stale_frame_end_after_reset_is_not_a_clean_scene(empty_scene):
    from blended import reset

    reset.reset_scene()
    bpy.context.scene.frame_end = STALE_FRAME_END

    with pytest.raises(reset.SceneNotClean, match="frame_end"):
        reset.assert_clean_scene()
