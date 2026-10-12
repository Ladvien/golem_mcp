"""inspect_domain reports what the domain ops actually did, through the
same dispatch the chat uses — so the writer can verify rigging,
weighting, keyframes and materials the way inspect_object verifies
geometry.
"""

import json

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

BOX_HEIGHT_M = 1.0
BONE_COUNT = 3
KEYFRAME_FRAMES = (1, 24)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _rigged_animated_textured_box():
    from blended.ops import (
        BoneSpec,
        add_armature,
        add_box,
        assign_procedural_material,
        bind_mesh_to_armature,
        keyframe_pose_bone_rotation,
        link_into_scene,
        set_frame_range,
    )

    box = add_box(
        "Body", 0.2, 0.2, BOX_HEIGHT_M, location_m=(0.0, 0.0, BOX_HEIGHT_M / 2)
    )
    link_into_scene(box)
    step = BOX_HEIGHT_M / BONE_COUNT
    bones = tuple(
        BoneSpec(
            name=f"spine_{i}",
            head_m=(0.0, 0.0, i * step),
            tail_m=(0.0, 0.0, (i + 1) * step),
            parent_name=f"spine_{i - 1}" if i else "",
            connected=bool(i),
        )
        for i in range(BONE_COUNT)
    )
    rig = add_armature("Rig", bones)
    bind_mesh_to_armature(box, rig)
    set_frame_range(*KEYFRAME_FRAMES)
    for frame in KEYFRAME_FRAMES:
        keyframe_pose_bone_rotation(rig, "spine_1", frame, (0.0, 0.0, 20.0 * frame))
    assign_procedural_material(box, "Skin", "checker")
    return box, rig


def _inspect(object_name, domain, tmp_path):
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool(
        "inspect_domain", {"object_name": object_name, "domain": domain}, tmp_path
    )
    text, images = _outcome.text, list(_outcome.images)
    assert images == []
    return json.loads(text.split("\n", 1)[1])


def test_every_domain_reports_the_built_state(empty_scene, tmp_path):
    _rigged_animated_textured_box()

    rig = _inspect("Rig", "rig", tmp_path)
    assert rig["bone_count"] == BONE_COUNT
    assert rig["bound_mesh_names"] == ["Body"]

    weights = _inspect("Body", "weights", tmp_path)
    assert weights["unweighted_vertex_count"] == 0
    assert any(count > 0 for count in weights["nonzero_weight_counts"].values())

    animation = _inspect("Rig", "animation", tmp_path)
    assert animation["keyframe_count"] == len(KEYFRAME_FRAMES) * 3
    assert (animation["frame_start"], animation["frame_end"]) == KEYFRAME_FRAMES
    assert any("spine_1" in path for path in animation["animated_data_paths"])

    material = _inspect("Body", "material", tmp_path)
    assert material["base_color_linked"] is True
    assert "ShaderNodeTexChecker" in material["node_type_counts"]


def test_a_wrong_object_type_is_named_not_crashed(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    _rigged_animated_textured_box()
    _outcome = dispatch_tool(
        "inspect_domain", {"object_name": "Body", "domain": "rig"}, tmp_path
    )
    text, _ = _outcome.text, list(_outcome.images)
    assert "not an ARMATURE" in text
    _outcome = dispatch_tool(
        "inspect_domain", {"object_name": "Nope", "domain": "rig"}, tmp_path
    )
    text, _ = _outcome.text, list(_outcome.images)
    assert "No object named" in text
