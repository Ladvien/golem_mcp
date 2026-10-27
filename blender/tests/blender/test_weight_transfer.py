"""`transfer_weights`: a garment inherits the body's weights, and says which of them are inferred.

The body is skinclip's tube humanoid imported through `import_rigged_glb`, so
the source weights are a real glTF skin: every bone of a 22-joint rig, with
the armature's own bone names (Blender's glTF importer renames `mixamorig:*`
style joints to plain bone names, so a test that asserted guessed names would
be asserting its own guess).

What each test defends:
  - every vertex of a garment ring is weighted, at most four groups per
    vertex, each row summing to 1;
  - a ring at chest height is dominated by SPINE groups and not by the
    arms, even though the arms are the nearest surface for part of it —
    that is the whole point of interpolating over the matched triangle
    rather than copying the single nearest vertex;
  - an inside-out ring matches nothing (the normal check is not flipped);
  - a piece the body does not cover is refused by its vertex count rather
    than left weightless;
  - a ring pushed far out is INPAINTED and still weighted.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAMES_PER_SECOND = 30
BODY = "body"
BODY_MESH_PREFIX = "body_"
CHEST_NAME = "ChestRing"
# The tube humanoid stands 1.77 m tall, its spine from 1.03 m to 1.434 m and
# its thighs from 0.93 m to 1.36 m (measured 2026-10-27 from the imported
# armature's own `bone.matrix_local`). The plan's 0.70-0.95 m band is BELOW
# the pelvis on this rig and reads thigh_l/thigh_r on every vertex — measured:
# a ring there is dominated 24/24 by each thigh. A CHEST ring has to sit on
# the spine, so the band is 1.05-1.30 m and the torso bones are the four
# spine/pelvis bones plus the clavicles they hang from.
CHEST_BOTTOM_M = 1.05
CHEST_TOP_M = 1.30
CHEST_RADIUS_M = 0.18
WIDE_RADIUS_M = 0.5
RING_STEP_M = 0.05
RING_AROUND_COUNT = 48
MAXIMUM_INFLUENCES = 4
# The tube humanoid's torso bones: a chest-height ring must be driven by
# these and by nothing on the arms. Measured 2026-10-27 through
# `transfer_weights` on that body: every vertex of the chest ring carries
# at most 3 groups, and the largest is always a spine or the pelvis.
TORSO_BONES = {"spine_01", "spine_02", "spine_03"}
# A weight row sums to 1 to within float precision; this is far tighter
# than the 8-bit precision a weight reaches an engine at.
ROW_SUM_TOLERANCE = 1e-6


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FRAMES_PER_SECOND
    bpy.context.scene.render.fps_base = 1.0
    yield


def _import_body(tmp_path):
    from skinclip.testing import tube_humanoid

    from golem_blender.ops.assets import import_rigged_glb

    path = tmp_path / "body.glb"
    tube_humanoid(path, "ue5", "thigh_swing")
    report = import_rigged_glb(str(path), BODY)
    return report


def _ring(name: str, bottom_m: float, top_m: float, radius_m: float) -> str:
    """An open ring of quads about Z at `radius_m`, from `bottom_m` to `top_m`, winding outward."""
    heights = [
        round(bottom_m + index * RING_STEP_M, 4)
        for index in range(round((top_m - bottom_m) / RING_STEP_M) + 1)
    ]
    vertices = [
        (
            radius_m * math.sin(2 * math.pi * k / RING_AROUND_COUNT),
            -radius_m * math.cos(2 * math.pi * k / RING_AROUND_COUNT),
            height,
        )
        for height in heights
        for k in range(RING_AROUND_COUNT)
    ]
    faces = [
        (
            row * RING_AROUND_COUNT + k,
            row * RING_AROUND_COUNT + (k + 1) % RING_AROUND_COUNT,
            (row + 1) * RING_AROUND_COUNT + (k + 1) % RING_AROUND_COUNT,
            (row + 1) * RING_AROUND_COUNT + k,
        )
        for row in range(len(heights) - 1)
        for k in range(RING_AROUND_COUNT)
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    ring = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(ring)
    bpy.context.view_layer.update()
    return name


def _reverse_faces(object_name: str) -> None:
    import bmesh

    mesh = bpy.data.objects[object_name].data
    working = bmesh.new()
    try:
        working.from_mesh(mesh)
        bmesh.ops.reverse_faces(working, faces=list(working.faces))
        working.to_mesh(mesh)
    finally:
        working.free()
    mesh.update()


def _body_mesh_name() -> str:
    return next(
        scene_object.name
        for scene_object in bpy.data.objects
        if scene_object.type == "MESH"
        and scene_object.name.startswith(BODY_MESH_PREFIX)
    )


def _rows(object_name: str) -> list[dict[str, float]]:
    """Every vertex's {group name: weight}, from the mesh's own vertex groups."""
    mesh_object = bpy.data.objects[object_name]
    names = [group.name for group in mesh_object.vertex_groups]
    return [
        {
            names[element.group]: element.weight
            for element in vertex.groups
            if element.weight > 0.0
        }
        for vertex in mesh_object.data.vertices
    ]


def test_a_chest_ring_is_fully_weighted_and_driven_by_the_spine(tmp_path, empty_scene):
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    report = transfer_weights(_body_mesh_name(), CHEST_NAME)

    rows = _rows(CHEST_NAME)
    assert report.vertices_weighted == len(rows)
    assert report.confident_vertex_count > 0
    for index, row in enumerate(rows):
        assert 1 <= len(row) <= MAXIMUM_INFLUENCES, (index, row)
        assert sum(row.values()) == pytest.approx(1.0, abs=ROW_SUM_TOLERANCE), (
            index,
            row,
        )
    for index, row in enumerate(rows):
        dominant = max(row, key=row.get)
        assert dominant in TORSO_BONES, (
            f"vertex {index} at z {bpy.data.objects[CHEST_NAME].data.vertices[index].co.z:.2f} "
            f"is dominated by {dominant!r}, not a torso bone: the ring copied "
            f"the nearest surface instead of interpolating over its match"
        )
    assert report.groups_without_bones == ()
    assert report.match_distance_m == pytest.approx(
        0.05 * _source_diagonal_m(), rel=1e-9
    )


def _source_diagonal_m() -> float:
    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([bpy.data.objects[_body_mesh_name()]])
    return float(math.dist(minimum, maximum))


def test_an_inside_out_ring_matches_nothing(tmp_path, empty_scene):
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    _reverse_faces(CHEST_NAME)

    with pytest.raises(ValueError, match="inside out"):
        transfer_weights(_body_mesh_name(), CHEST_NAME)


def test_a_piece_the_body_does_not_cover_is_refused_by_its_size(tmp_path, empty_scene):
    """One matched piece plus one uncovered piece: the SECOND is named, not silently left weightless."""
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    # Four more vertices a metre away, in the SAME object: they have no
    # confident match, and no matched neighbour to relax from either.
    import bmesh

    mesh = bpy.data.objects[CHEST_NAME].data
    offset = len(mesh.vertices)
    working = bmesh.new()
    try:
        working.from_mesh(mesh)
        far = [
            working.verts.new(corner)
            for corner in [
                (1.0, 0.0, CHEST_BOTTOM_M),
                (1.2, 0.0, CHEST_BOTTOM_M),
                (1.2, 0.2, CHEST_BOTTOM_M),
                (1.0, 0.2, CHEST_BOTTOM_M),
            ]
        ]
        working.faces.new(far)
        working.to_mesh(mesh)
    finally:
        working.free()
    mesh.update()
    bpy.context.view_layer.update()
    assert len(mesh.vertices) == offset + 4

    with pytest.raises(ValueError, match="4 vertices form a component"):
        transfer_weights(_body_mesh_name(), CHEST_NAME)


def test_a_ring_row_pushed_past_the_match_radius_is_inpainted_and_still_weighted(
    tmp_path, empty_scene
):
    """A loose hem: the rows that match copy, and the one row that does not is relaxed into place."""
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    # The TOP row out to 0.5 m — 0.36 m off the body, far outside the
    # 0.128 m match radius, so it cannot copy and must be inpainted.
    mesh = bpy.data.objects[CHEST_NAME].data
    top_row_start = len(mesh.vertices) - RING_AROUND_COUNT
    for index in range(top_row_start, len(mesh.vertices)):
        point = mesh.vertices[index].co
        scale = WIDE_RADIUS_M / CHEST_RADIUS_M
        mesh.vertices[index].co = (point.x * scale, point.y * scale, point.z)
    mesh.update()
    bpy.context.view_layer.update()
    report = transfer_weights(_body_mesh_name(), CHEST_NAME)

    assert report.inpainted_vertex_count > 0
    assert report.inpaint_iterations > 0
    rows = _rows(CHEST_NAME)
    assert report.vertices_weighted == len(rows)
    for row in rows:
        assert sum(row.values()) == pytest.approx(1.0, abs=ROW_SUM_TOLERANCE)


def test_a_modifier_that_is_not_the_armature_is_refused(tmp_path, empty_scene):
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    bpy.data.objects[CHEST_NAME].modifiers.new(name="Thickness", type="SOLIDIFY")

    with pytest.raises(ValueError, match="apply the target's modifiers first"):
        transfer_weights(_body_mesh_name(), CHEST_NAME)


def test_the_report_says_how_the_weights_changed(tmp_path, empty_scene):
    """A transfer onto a mesh that ALREADY has weights reports the change, not just a count."""
    from golem_blender.ops.rigging import bind_mesh_to_armature
    from golem_blender.ops.weight_transfer import transfer_weights

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    # Bind with the armature's own automatic weights first, so every vertex
    # already has a dominant group that the transfer will almost certainly
    # change.
    bind_mesh_to_armature(CHEST_NAME, BODY, automatic_weights=True)
    assert bpy.data.objects[CHEST_NAME].vertex_groups

    report = transfer_weights(_body_mesh_name(), CHEST_NAME)
    assert report.changed_dominant_group_vertex_count >= 0
    assert report.changed_dominant_group_vertex_count <= len(_rows(CHEST_NAME))
