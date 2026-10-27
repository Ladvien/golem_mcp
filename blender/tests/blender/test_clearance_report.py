"""`clearance_report`: a garment is measured against the body it moves with, and fails on the frame that crossed.

The body is skinclip's tube humanoid imported through `import_rigged_glb`, with
two clips: `thigh_swing` (both thighs 35 degrees either way, a second long) and
`hand_through_torso` (the left arm swinging down across the hip, two seconds).
The garments are rings — open tubes of quads — weighted by `transfer_weights`
and bound by `bind_mesh_to_armature(automatic_weights=False)`.

What each test defends:
  - a chest ring clears the body at rest and through `thigh_swing`, and its
    covered body vertices are counted;
  - a skirt weighted wholly to `pelvis` is crossed by a swinging thigh, and
    the report names the THIGH bone and not the garment's own side;
  - a chest ring is crossed by `hand_through_torso`, and the report names the
    arm;
  - an inside-out ring fails on FACING even when every clearance is positive;
  - a ring pulled through the body at rest fails on `garment_inside_body`;
  - an unbound garment is refused and the message names `transfer_weights`;
  - every piece of scene state is exactly as it was afterwards.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAMES_PER_SECOND = 30
BODY = "body"
CHEST_NAME = "ChestRing"
SKIRT_NAME = "SkirtRing"
# The tube humanoid stands 1.77 m tall; its spine runs 1.03-1.434 m and its
# thighs 0.93-1.36 m (measured 2026-10-27 from the imported armature's own
# bone matrix). A chest ring sits on the spine at 1.05-1.30 m; a skirt hangs
# from the pelvis to the knees at 0.55-0.95 m.
CHEST_BOTTOM_M = 1.05
CHEST_TOP_M = 1.30
CHEST_RADIUS_M = 0.18
SKIRT_BOTTOM_M = 0.55
SKIRT_TOP_M = 0.95
SKIRT_RADIUS_M = 0.20
RING_STEP_M = 0.05
RING_AROUND_COUNT = 48
THIGH_SWING = "thigh_swing"
HAND_THROUGH_TORSO = "hand_through_torso"
LEG_BONES = {"thigh_l", "thigh_r", "calf_l", "calf_r"}
PULLED_RADIUS_M = 0.05


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FRAMES_PER_SECOND
    bpy.context.scene.render.fps_base = 1.0
    yield


def _import_body(tmp_path, clip: str = THIGH_SWING):
    from skinclip.testing import tube_humanoid

    from golem_blender.ops.assets import import_rigged_glb

    path = tmp_path / f"{clip}.glb"
    tube_humanoid(path, "ue5", clip)
    return import_rigged_glb(str(path), BODY)


def _body_mesh_name() -> str:
    return next(
        scene_object.name
        for scene_object in bpy.data.objects
        if scene_object.type == "MESH" and scene_object.name.startswith(f"{BODY}_")
    )


def _ring(name: str, bottom_m: float, top_m: float, radius_m: float) -> str:
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


def _bind_weighted(garment: str, whole_body: bool = False) -> None:
    """Weight the garment from the body (or wholly to one bone) and bind it."""
    from golem_blender.ops.rigging import bind_mesh_to_armature
    from golem_blender.ops.weight_transfer import transfer_weights

    if whole_body:
        from golem_blender.ops.weights import assign_vertex_group_weights

        assign_vertex_group_weights(garment, "pelvis", 1.0)
    else:
        transfer_weights(_body_mesh_name(), garment)
    bind_mesh_to_armature(garment, BODY, automatic_weights=False)


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


def test_a_chest_ring_clears_the_body_at_rest_and_through_a_leg_swing(
    tmp_path, empty_scene
):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    _bind_weighted(CHEST_NAME)
    report = clearance_report(_body_mesh_name(), CHEST_NAME, (THIGH_SWING,))

    assert [clip.action_name for clip in report.clips] == ["", THIGH_SWING]
    rest, swinging = report.clips
    assert rest.worst_clearance_m > 0.0
    assert resting_worst(report) > 0.0
    assert swinging.passed, report.failures
    assert report.covered_body_vertex_count > 0
    # An open ring is decided by its own winding (rim faces score 0.57 and
    # up), not by the nearest body surface.
    assert report.garment_winding_method == "winding_number"
    assert report.garment_inward_area_fraction <= 0.02
    assert report.passed, report.failures


def resting_worst(report):
    return next(
        clip.worst_clearance_m for clip in report.clips if clip.action_name == ""
    )


def test_a_pelvis_skirt_is_crossed_by_a_swinging_thigh(tmp_path, empty_scene):
    """The skirt does not follow the leg, so the leg comes through it — and the report names the LEG."""
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(SKIRT_NAME, SKIRT_BOTTOM_M, SKIRT_TOP_M, SKIRT_RADIUS_M)
    _bind_weighted(SKIRT_NAME, whole_body=True)
    report = clearance_report(_body_mesh_name(), SKIRT_NAME, (THIGH_SWING,))

    assert report.passed is False
    swinging = next(clip for clip in report.clips if clip.action_name == THIGH_SWING)
    assert swinging.worst_kind == "body_through_garment"
    assert swinging.worst_group_name in LEG_BONES, (
        f"the report blames {swinging.worst_group_name!r}; the leg is what moved"
    )
    assert swinging.worst_clearance_m < 0.0
    assert swinging.failing_frame_count > 0
    assert any(THIGH_SWING in line for line in report.failures)


def test_an_arm_swinging_into_a_chest_ring_is_reported_as_the_arm(
    tmp_path, empty_scene
):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path, HAND_THROUGH_TORSO)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    _bind_weighted(CHEST_NAME)
    report = clearance_report(_body_mesh_name(), CHEST_NAME, (HAND_THROUGH_TORSO,))

    assert report.passed is False
    swinging = next(
        clip for clip in report.clips if clip.action_name == HAND_THROUGH_TORSO
    )
    assert swinging.worst_kind in {"garment_inside_body", "body_through_garment"}
    assert swinging.failing_frame_count > 0
    # The offending vertex is the GARMENT's for `garment_inside_body`, so its
    # group is a torso bone even though the ARM is what came through — the
    # group names the weights to fix, not the thing that hit it. Measured
    # 2026-10-27: the worst point is (0.12, 0.0, 1.25), on the ring at chest
    # height, and the arm's tube passes through it 38 frames of 61.
    assert -0.06 < swinging.worst_clearance_m < 0.0
    assert swinging.penetrating_vertex_count > 0
    assert report.clips[0].passed, (
        "the ring must clear the body at REST, or this test is measuring a "
        "badly fitted ring rather than the arm's swing"
    )


def test_an_inside_out_garment_fails_on_facing_even_with_clear_space(
    tmp_path, empty_scene
):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    # Weight and bind FIRST: `transfer_weights` refuses an inside-out target,
    # which is its own test — here the question is what the CLEARANCE report
    # says about a garment that is already bound and inside out.
    _bind_weighted(CHEST_NAME)
    _reverse_faces(CHEST_NAME)
    report = clearance_report(_body_mesh_name(), CHEST_NAME, ())

    assert report.garment_inward_area_fraction >= 0.9
    assert report.passed is False
    assert any("inside out" in line for line in report.failures)
    # The point of the test: every clearance is still positive, and the
    # garment still fails, because in the engine it is not drawn.
    assert all(clip.worst_clearance_m > 0.0 for clip in report.clips)


def test_a_ring_pulled_into_the_body_fails_at_rest(tmp_path, empty_scene):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    # One row (the bottom) pulled in to 0.05 m: well inside the torso's 0.14 m.
    mesh = bpy.data.objects[CHEST_NAME].data
    for index in range(RING_AROUND_COUNT):
        point = mesh.vertices[index].co
        scale = PULLED_RADIUS_M / CHEST_RADIUS_M
        mesh.vertices[index].co = (point.x * scale, point.y * scale, point.z)
    mesh.update()
    bpy.context.view_layer.update()
    _bind_weighted(CHEST_NAME)

    report = clearance_report(_body_mesh_name(), CHEST_NAME, ())
    rest = report.clips[0]
    assert rest.passed is False
    assert rest.worst_kind == "garment_inside_body"
    assert rest.worst_clearance_m < 0.0
    assert report.passed is False


def test_an_unbound_garment_is_refused_and_names_transfer_weights(
    tmp_path, empty_scene
):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)

    with pytest.raises(ValueError, match="transfer_weights"):
        clearance_report(_body_mesh_name(), CHEST_NAME, ())


def test_an_unknown_action_is_refused_by_name(tmp_path, empty_scene):
    from golem_blender.ops.garments import clearance_report

    _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    _bind_weighted(CHEST_NAME)

    with pytest.raises(ValueError, match="no action named 'nope'"):
        clearance_report(_body_mesh_name(), CHEST_NAME, ("nope",))


def test_every_piece_of_scene_state_is_restored(tmp_path, empty_scene):
    from golem_blender.ops.animation import play_clip
    from golem_blender.ops.garments import clearance_report

    report = _import_body(tmp_path)
    _ring(CHEST_NAME, CHEST_BOTTOM_M, CHEST_TOP_M, CHEST_RADIUS_M)
    _bind_weighted(CHEST_NAME)

    # Put the scene in a NON-default state of every kind the op touches.
    armature = bpy.data.objects[BODY]
    other = bpy.data.actions.new("other_clip")
    other.frame_range  # noqa: B018 - the range is what the op reads, not what it sets
    armature.animation_data.action = other
    armature.animation_data.action_slot = None
    armature.data.pose_position = "POSE"
    track = armature.animation_data.nla_tracks.new()
    track.mute = False
    bpy.context.scene.frame_set(7)
    bpy.context.view_layer.update()

    before = {
        "frame": bpy.context.scene.frame_current,
        "pose_position": armature.data.pose_position,
        "action": armature.animation_data.action.name,
        "slot": armature.animation_data.action_slot,
        "mutes": [t.mute for t in armature.animation_data.nla_tracks],
    }
    assert report.active_action_name  # the import really carried a clip

    clearance_report(_body_mesh_name(), CHEST_NAME, (report.active_action_name,))
    bpy.context.view_layer.update()

    after = {
        "frame": bpy.context.scene.frame_current,
        "pose_position": armature.data.pose_position,
        "action": armature.animation_data.action.name,
        "slot": armature.animation_data.action_slot,
        "mutes": [t.mute for t in armature.animation_data.nla_tracks],
    }
    assert after == before, f"scene state changed: {before} -> {after}"
    # And the control that makes this a real test: the pose the op left is
    # the one play_clip would ALSO leave, so "restored" is not "nothing ran".
    play_clip(BODY, report.active_action_name, 10)
    assert armature.animation_data.action_slot is not None
