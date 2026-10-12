"""The domain lanes' own "reports healthy, does nothing" holes.

The mesh gate learned this lesson first: flawless geometry nobody can
see is not a pass. The rig, weight and animation reports had the same
shape of hole — every sign of finished work present, and nothing
actually deforming or moving:

* an Armature modifier that is DISABLED still binds nothing;
* a vertex group whose name matches NO bone drives nothing, however
  many vertices carry a weight in it (one typo does this);
* a MUTED fcurve keeps its keyframes and animates nothing, and keys
  outside the scene's frame range never play.

Each test drives the pathology and asserts the report NAMES it, beside a
control that must stay clean — a check that only fires on the broken
case is the only kind worth keeping.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAME_RANGE = (1, 48)
OUTSIDE_FRAME = 200
WEIGHT = 1.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _rigged_pair():
    """A box bound to a two-bone armature, weights on both bones."""
    from blended.ops.primitives import add_box, link_into_scene
    from blended.ops.rigging import BoneSpec, add_armature, bind_mesh_to_armature
    from blended.ops.weights import assign_weights_by_height

    box = add_box("Subject", 0.3, 0.3, 1.0)
    link_into_scene(box)
    armature = add_armature(
        "Rig",
        (
            BoneSpec("Root", (0, 0, 0.0), (0, 0, 0.5)),
            BoneSpec(
                "Tip", (0, 0, 0.5), (0, 0, 1.0), parent_name="Root", connected=True
            ),
        ),
    )
    bind_mesh_to_armature(box, armature, automatic_weights=False)
    assign_weights_by_height(box, "Root", 0.0, 0.5, WEIGHT)
    assign_weights_by_height(box, "Tip", 0.5, 1.0, WEIGHT)
    bpy.context.view_layer.update()
    return box, armature


def _armature_modifier(mesh_object):
    from blended.ops.rigging import ARMATURE_MODIFIER_TYPE

    for modifier in mesh_object.modifiers:
        if modifier.type == ARMATURE_MODIFIER_TYPE:
            return modifier
    raise AssertionError("the fixture did not create an Armature modifier")


def test_a_disabled_armature_modifier_is_not_a_binding(empty_scene):
    from blended.ops.rigging import rig_report

    box, armature = _rigged_pair()
    assert rig_report(armature).bound_mesh_names == ("Subject",)
    assert rig_report(armature).disabled_modifier_mesh_names == ()

    _armature_modifier(bpy.data.objects[box]).show_viewport = False
    bpy.context.view_layer.update()
    report = rig_report(armature)
    assert report.bound_mesh_names == (), (
        "a modifier switched off in the viewport deforms nothing"
    )
    assert report.disabled_modifier_mesh_names == ("Subject",)


def test_a_render_disabled_modifier_is_not_a_binding_either(empty_scene):
    """`show_render` alone is enough: the rig would vanish from every
    render even though the viewport looks correct."""
    from blended.ops.rigging import rig_report

    box, armature = _rigged_pair()
    _armature_modifier(bpy.data.objects[box]).show_render = False
    bpy.context.view_layer.update()
    report = rig_report(armature)
    assert report.bound_mesh_names == ()
    assert report.disabled_modifier_mesh_names == ("Subject",)


def test_a_vertex_group_that_names_no_bone_is_reported(empty_scene):
    """The typo case: weights that drive nothing still count as weights
    in `nonzero_weight_counts`, so the cross-check is the only signal."""
    from blended.ops.weights import assign_weights_by_height, weight_report

    box, _ = _rigged_pair()
    clean = weight_report(box)
    assert clean.groups_without_bones == ()
    assert clean.bones_without_groups == ()

    assign_weights_by_height(box, "Tp", 0.5, 1.0, WEIGHT)
    report = weight_report(box)
    assert report.nonzero_weight_counts["Tp"] > 0, "the weights are real"
    assert report.groups_without_bones == ("Tp",), (
        "a group naming no bone moves nothing and must be named"
    )


def test_a_bone_no_group_names_is_reported(empty_scene):
    from blended.ops.primitives import add_box, link_into_scene
    from blended.ops.rigging import BoneSpec, add_armature, bind_mesh_to_armature
    from blended.ops.weights import assign_weights_by_height, weight_report

    box = add_box("Subject", 0.3, 0.3, 1.0)
    link_into_scene(box)
    armature = add_armature(
        "Rig",
        (
            BoneSpec("Root", (0, 0, 0.0), (0, 0, 0.5)),
            BoneSpec(
                "Unused", (0, 0, 0.5), (0, 0, 1.0), parent_name="Root", connected=True
            ),
        ),
    )
    bind_mesh_to_armature(box, armature, automatic_weights=False)
    assign_weights_by_height(box, "Root", 0.0, 1.0, WEIGHT)
    bpy.context.view_layer.update()

    report = weight_report(box)
    assert report.bones_without_groups == ("Unused",)
    assert report.groups_without_bones == ()


def test_an_unrigged_mesh_is_not_accused_of_dead_groups(empty_scene):
    """With no armature there is nothing to compare against, and
    guessing would invent failures on ordinary modelling work."""
    from blended.ops.primitives import add_box, link_into_scene
    from blended.ops.weights import assign_vertex_group_weights, weight_report

    box = add_box("Plain", 1.0, 1.0, 1.0)
    link_into_scene(box)
    assign_vertex_group_weights(box, "Handle", WEIGHT)
    report = weight_report(box)
    assert report.nonzero_weight_counts["Handle"] > 0
    assert report.groups_without_bones == ()
    assert report.bones_without_groups == ()


def _animated_box():
    from blended.ops.animation import keyframe_object_transform, set_frame_range
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("Mover", 0.5, 0.5, 0.5)
    link_into_scene(box)
    set_frame_range(*FRAME_RANGE)
    keyframe_object_transform(box, FRAME_RANGE[0], location_m=(0.0, 0.0, 0.0))
    keyframe_object_transform(box, FRAME_RANGE[1], location_m=(2.0, 0.0, 0.0))
    return box


def test_a_muted_fcurve_is_reported(empty_scene):
    # `_action_fcurves` is the module's own accessor for Blender 5.2's
    # SLOTTED actions: `Action.fcurves` no longer exists there, which is
    # why the report never touches it either.
    from blended.ops.animation import _action_fcurves, animation_report

    box = _animated_box()
    clean = animation_report(box)
    assert clean.keyframe_count >= 2
    assert clean.muted_fcurve_count == 0

    for curve in _action_fcurves(bpy.data.objects[box]):
        curve.mute = True
    report = animation_report(box)
    assert report.keyframe_count == clean.keyframe_count, (
        "the keyframes are still there — that is the trap"
    )
    assert report.muted_fcurve_count == report.fcurve_count


def test_keyframes_outside_the_frame_range_are_reported(empty_scene):
    """An action keyed past frame_end reports keyframes and plays
    nothing."""
    from blended.ops.animation import animation_report, keyframe_object_transform

    box = _animated_box()
    assert animation_report(box).keyframes_outside_frame_range_count == 0

    keyframe_object_transform(box, OUTSIDE_FRAME, location_m=(5.0, 0.0, 0.0))
    report = animation_report(box)
    assert report.keyframes_outside_frame_range_count == 3, (
        "one key past frame_end on each of the three location channels"
    )


def test_inspect_domain_surfaces_the_new_fields(empty_scene, tmp_path):
    """The writer only ever sees these through the tool, so the tool has
    to carry them."""
    from blended.agent.tools import dispatch_tool
    from blended.ops.weights import assign_weights_by_height

    box, _ = _rigged_pair()
    assign_weights_by_height(box, "Tp", 0.5, 1.0, WEIGHT)
    _outcome = dispatch_tool(
        "inspect_domain", {"object_name": "Subject", "domain": "weights"}, tmp_path
    )
    text, _ = _outcome.text, list(_outcome.images)
    assert "groups_without_bones" in text
    assert "Tp" in text
