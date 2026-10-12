"""Animation ops: keyframing and frame-range contracts.

Measured 2026-09-04 on Blender 5.2.0 LTS (hash fbe6228777e7):
``action.fcurves`` is gone — fcurves are read through the slotted
action API ``action.layers[0].strips[0].channelbag(slot).fcurves``.
These tests prove that keyframe insertion actually lands fcurves and
keyframe points through that path, and that the report summarises them
correctly.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

DEG_90_Z = 90.0
DEG_180_Z = 180.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box():
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("Subject", 0.2, 0.2, 0.2)
    link_into_scene(box)
    return box


def _two_bone_armature():
    """Build a 2-bone armature via the data API + edit-mode override.

    Does not depend on rigging.py (written concurrently).  edit-bone
    creation needs the armature to be active and in edit mode, which
    requires ``bpy.context.temp_override`` — one of the few justified
    bpy.ops uses because there is no data-API path for entering edit
    mode.
    """
    arm_data = bpy.data.armatures.new("TestArm")
    arm_obj = bpy.data.objects.new("TestArm", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_data.edit_bones
    b1 = edit_bones.new("Bone1")
    b1.head = (0.0, 0.0, 0.0)
    b1.tail = (0.0, 0.0, 1.0)
    b2 = edit_bones.new("Bone2")
    b2.head = (0.0, 0.0, 1.0)
    b2.tail = (0.0, 0.0, 2.0)
    b2.parent = b1
    bpy.ops.object.mode_set(mode="POSE")
    return arm_obj


def test_set_frame_range_updates_scene(empty_scene):
    from blended.ops.animation import set_frame_range

    scene = bpy.context.scene
    set_frame_range(5, 25)

    assert scene.frame_start == 5
    assert scene.frame_end == 25


def test_set_frame_range_rejects_start_geq_end(empty_scene):
    from blended.ops.animation import set_frame_range

    with pytest.raises(ValueError):
        set_frame_range(10, 10)
    with pytest.raises(ValueError):
        set_frame_range(20, 10)


def test_two_keyframes_on_box_match_channel_count(empty_scene):
    from blended.ops.animation import keyframe_object_transform

    box = _box()
    count_after_first = keyframe_object_transform(
        box, frame=1, location_m=(0.0, 0.0, 0.0), rotation_euler_deg=(0.0, 0.0, 0.0)
    )
    count_after_second = keyframe_object_transform(
        box,
        frame=10,
        location_m=(1.0, 0.0, 0.0),
        rotation_euler_deg=(0.0, 0.0, DEG_90_Z),
    )

    # location (3) + rotation_euler (3) = 6 fcurves
    assert count_after_first == 6
    assert count_after_second == 6

    # 2 keyframes per fcurve channel
    ad = bpy.data.objects[box].animation_data
    slot = ad.action_slot
    fcurves = ad.action.layers[0].strips[0].channelbag(slot).fcurves
    total_kps = sum(len(fc.keyframe_points) for fc in fcurves)
    assert total_kps == 2 * 6


def test_location_only_keyframes_skip_other_channels(empty_scene):
    from blended.ops.animation import keyframe_object_transform

    box = _box()
    count = keyframe_object_transform(box, frame=1, location_m=(1.0, 2.0, 3.0))

    assert count == 3


def test_rotation_degrees_converted_to_radians(empty_scene):
    from blended.ops.animation import keyframe_object_transform

    box = _box()
    keyframe_object_transform(box, frame=1, rotation_euler_deg=(0.0, 0.0, DEG_180_Z))

    assert bpy.data.objects[box].rotation_euler[2] == pytest.approx(math.pi)


def test_pose_bone_rotation_keyframes_on_armature_action(empty_scene):
    from blended.ops.animation import keyframe_pose_bone_rotation

    arm_obj = _two_bone_armature()
    count = keyframe_pose_bone_rotation(
        arm_obj.name, "Bone1", frame=1, rotation_euler_deg=(0.0, 0.0, DEG_90_Z)
    )
    keyframe_pose_bone_rotation(
        arm_obj.name, "Bone1", frame=10, rotation_euler_deg=(0.0, 0.0, DEG_180_Z)
    )

    # XYZ Euler → 3 fcurves
    assert count == 3

    ad = arm_obj.animation_data
    slot = ad.action_slot
    fcurves = ad.action.layers[0].strips[0].channelbag(slot).fcurves

    # Each fcurve data_path must name the pose bone
    for fc in fcurves:
        assert "Bone1" in fc.data_path
    # 2 frames × 3 channels
    total_kps = sum(len(fc.keyframe_points) for fc in fcurves)
    assert total_kps == 6

    bpy.ops.object.mode_set(mode="OBJECT")


def test_report_on_never_animated_object_is_all_zero(empty_scene):
    from blended.ops.animation import animation_report

    box = _box()
    report = animation_report(box)

    assert report.action_name == ""
    assert report.fcurve_count == 0
    assert report.keyframe_count == 0
    assert report.animated_data_paths == ()


def test_report_on_animated_box_counts_correctly(empty_scene):
    from blended.ops.animation import (
        animation_report,
        keyframe_object_transform,
        set_frame_range,
    )

    box = _box()
    set_frame_range(1, 20)
    keyframe_object_transform(box, frame=1, location_m=(0.0, 0.0, 0.0))
    keyframe_object_transform(box, frame=15, location_m=(2.0, 0.0, 0.0))

    report = animation_report(box)

    assert report.action_name != ""
    assert report.fcurve_count == 3
    assert report.keyframe_count == 2 * 3
    assert report.frame_start == 1
    assert report.frame_end == 20
    assert "location" in report.animated_data_paths
