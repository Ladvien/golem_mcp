"""`import_rigged_glb` and `play_clip`: a character survives the import, and its clip actually poses it.

The tube humanoid from skinclip's own fixtures is a real glTF with a real
skeleton and a real animation, imported through Blender's own glTF
importer. So the slotted-action layout, the bone names and the mesh
parenting are Blender's, not this repo's assumptions.

What each test defends:
  - the import leaves ONE armature and its bound meshes, with the clips
    it created named in the report (read back from bpy.data.actions);
  - a re-import under the same name leaves no `.001` siblings and no
    stale action, so the fixed clip is the one that plays;
  - `play_clip` moves the posed hand, and the SLOT TRAP is the control:
    clearing `action_slot` and re-evaluating the same frame leaves the
    hand at rest, while `play_clip` rebinds it and the hand moves;
  - every refusal leaves nothing behind.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")
mathutils = pytest.importorskip("mathutils", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAMES_PER_SECOND = 30
EXPECTED_BONE_COUNT = 22
# The clip's own motion over the middle of its range: the left hand swings
# down and across the hip. Measured 2026-10-27 on skinclip's tube humanoid
# imported through `import_rigged_glb`: the hand's evaluated head travels
# 0.66 m from its rest head by the middle frame, so 0.01 m is a probe that
# cannot fire on float noise and cannot miss a working clip.
MINIMUM_HAND_TRAVEL_DISTANCE = 0.01
CLIP = "hand_through_torso"
ARM = "smoke_body"
# Measured 2026-10-27 on Blender 5.2's glTF importer: one animation becomes
# one muted NLA track holding one strip plus the assigned action.
IMPORTED_NLA_TRACK_COUNT = 1
# The identity basis a pose bone relaxes to — mathutils' 4x4 identity, so
# this is "no pose", not a copy of any bone's rest pose.


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FRAMES_PER_SECOND
    bpy.context.scene.render.fps_base = 1.0
    yield


POSE_REST_BASIS = mathutils.Matrix.Identity(4)


def _write_tube(tmp_path, clip: str = CLIP):
    from skinclip.testing import tube_humanoid

    path = tmp_path / f"{clip}.glb"
    tube_humanoid(path, "ue5", clip)
    return path


def _import(path, armature_name: str = ARM):
    from golem_blender.ops.assets import import_rigged_glb

    return import_rigged_glb(str(path), armature_name)


def _object_names() -> set[str]:
    return {scene_object.name for scene_object in bpy.data.objects}


def _action_names() -> set[str]:
    return {action.name for action in bpy.data.actions}


def _hand_head(armature_name: str):
    """The evaluated world head of `hand_l` — read from the DEPSGRAPH, not the pose bone's stored value."""
    armature = bpy.data.objects[armature_name]
    evaluated = armature.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return evaluated.matrix_world @ evaluated.pose.bones["hand_l"].head


def test_the_import_leaves_one_armature_its_meshes_and_its_clips(tmp_path, empty_scene):
    path = _write_tube(tmp_path)
    report = _import(path)

    assert bpy.data.objects[report.object_name].type == "ARMATURE"
    assert [o.name for o in bpy.data.objects if o.type == "ARMATURE"] == [ARM]
    assert report.bone_count == EXPECTED_BONE_COUNT
    assert report.mesh_names, "a rigged import with no bound mesh is not a character"
    for mesh_name in report.mesh_names:
        assert mesh_name.startswith(f"{ARM}_"), (
            f"{mesh_name!r} is not named after its armature, so two imports "
            f"of different characters would collide"
        )
        assert bpy.data.objects[mesh_name].type == "MESH"

    # The report's action list is what the import CREATED, measured.
    assert report.action_names == tuple(sorted(_action_names()))
    assert report.active_action_name in report.action_names
    assert report.frame_end > report.frame_start
    # Measured 2026-10-27 on Blender 5.2's glTF importer: an animated node
    # comes back with the action assigned AND in one MUTED NLA track named
    # after it. That track is why `play_clip` mutes every track rather than
    # assuming the importer left none.
    assert report.nla_track_count == IMPORTED_NLA_TRACK_COUNT


def test_a_re_import_under_the_same_name_leaves_no_suffixed_siblings(
    tmp_path, empty_scene
):
    path = _write_tube(tmp_path)
    first = _import(path)
    objects_after_first = _object_names()
    actions_after_first = _action_names()

    second = _import(path)

    assert _object_names() == objects_after_first, (
        f"a re-import changed the object set: {sorted(_object_names())}"
    )
    assert _action_names() == actions_after_first, (
        f"a re-import changed the action set: {sorted(_action_names())}"
    )
    assert not [name for name in _object_names() if name.endswith(".001")]
    assert not [name for name in _action_names() if name.endswith(".001")]
    assert second.mesh_names == first.mesh_names
    assert second.action_names == first.action_names


def test_play_clip_moves_the_hand_and_the_slot_is_what_does_it(tmp_path, empty_scene):
    from golem_blender.ops.animation import play_clip

    path = _write_tube(tmp_path)
    report = _import(path)
    armature = bpy.data.objects[report.object_name]
    rest_head = _hand_head(ARM)
    middle = (report.frame_start + report.frame_end) // 2

    played = play_clip(ARM, report.active_action_name, middle)
    assert played.moved_bone_count > 0
    assert played.fcurve_count > 0
    assert played.slot_identifier
    posed_head = _hand_head(ARM)
    travel = (posed_head - rest_head).length
    assert travel > MINIMUM_HAND_TRAVEL_DISTANCE, (
        f"the hand moved {travel:.4f} m at frame {middle}; the clip is not "
        f"driving the pose"
    )

    # The control: unbound slot, same frame, nothing moves. This is the
    # trap that made a whole round trip in the user's report. The pose is
    # reset first because a pose bone with no action keeps its LAST
    # evaluated basis (measured in test_motion_ops' own note): without the
    # reset, "no slot" and "no motion" cannot be told apart.
    armature.animation_data.action_slot = None
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis = POSE_REST_BASIS
    bpy.context.scene.frame_set(middle)
    unbound_head = _hand_head(ARM)
    assert (unbound_head - rest_head).length < MINIMUM_HAND_TRAVEL_DISTANCE, (
        "clearing the action slot did not stop the clip from posing the rig, "
        "so the slot is not what binds it and this test proves nothing"
    )

    # And play_clip rebinds it: the probe varies in the right direction.
    rebound = play_clip(ARM, report.active_action_name, middle)
    assert rebound.moved_bone_count > 0
    assert (rebound.slot_identifier, (rebound.frame,)) == (
        played.slot_identifier,
        (middle,),
    )
    assert (armature.animation_data.action_slot is not None)


def test_an_unknown_action_is_refused_by_name(tmp_path, empty_scene):
    from golem_blender.ops.animation import play_clip

    path = _write_tube(tmp_path)
    report = _import(path)
    with pytest.raises(ValueError, match="no action named 'nope'"):
        play_clip(ARM, "nope", report.frame_start)
    assert report.active_action_name in str(_action_names())


def test_a_frame_outside_the_clip_is_refused_with_the_range(tmp_path, empty_scene):
    from golem_blender.ops.animation import play_clip

    path = _write_tube(tmp_path)
    report = _import(path)
    with pytest.raises(ValueError, match=f"{report.frame_start}..{report.frame_end}"):
        play_clip(ARM, report.active_action_name, report.frame_end + 5)


def test_a_glb_with_no_armature_is_refused_and_imports_nothing(tmp_path, empty_scene):
    from golem_blender.export import export_glb
    from golem_blender.ops.assets import import_rigged_glb
    from golem_blender.ops.primitives import add_box, link_into_scene

    box = add_box("cube", 0.5, 0.5, 0.5)
    link_into_scene(box)
    export_glb(
        bpy.data.objects[box], tmp_path / "cube.glb", blend_path=tmp_path / "cube.blend"
    )
    objects_before = _object_names()
    actions_before = _action_names()

    with pytest.raises(ValueError, match="no armature in"):
        import_rigged_glb(str(tmp_path / "cube.glb"), "not_a_character")

    assert _object_names() == objects_before, (
        f"a refused import left objects behind: "
        f"{sorted(_object_names() - objects_before)}"
    )
    assert _action_names() == actions_before


def test_a_missing_file_is_refused_before_anything_is_imported(tmp_path, empty_scene):
    from golem_blender.ops.assets import import_rigged_glb

    objects_before = _object_names()
    with pytest.raises(FileNotFoundError):
        import_rigged_glb(str(tmp_path / "absent.glb"), ARM)
    assert _object_names() == objects_before
