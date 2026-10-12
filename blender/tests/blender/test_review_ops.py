"""Regression pins for the defects the 2026-10-07 ops review measured.

Each test reproduces a failure observed in Blender 5.2 against the
unfixed code; the number in each comment is what the old code did.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

PLACEMENT_TOLERANCE_M = 1e-6
ARMATURE_HEIGHT_M = 1.0
PARENT_HEIGHT_M = 5.0
FLATTENED_Z_SCALE = 10.0
SLANTED_FACE_TOLERANCE_DEG = 10.0
OVERLONG_OBJECT_NAME_LENGTH = 300


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _linked_box(name, location_m=(0.0, 0.0, 0.0)):
    from blended.ops.primitives import add_box, link_into_scene

    return link_into_scene(add_box(name, 1.0, 1.0, 1.0, location_m=location_m))


def _one_bone():
    from blended.ops.rigging import BoneSpec

    return (BoneSpec("Bone", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),)


def test_a_constructor_replaces_an_object_of_another_type(empty_scene):
    # Old: TypeError from bpy.data.meshes.remove(<Armature>) AFTER the
    # armature object had already been removed.
    from blended.ops.primitives import add_box
    from blended.ops.rigging import add_armature

    add_armature("Shared", _one_bone())
    add_box("Shared", 1.0, 1.0, 1.0)

    assert bpy.data.objects["Shared"].type == "MESH"
    assert len(bpy.data.armatures) == 0


def test_a_parent_listed_after_its_child_is_rejected_before_any_mutation(empty_scene):
    # Old: KeyError raised inside EDIT mode, stranding the half-built rig.
    from blended.ops.rigging import BoneSpec, add_armature

    bones = (
        BoneSpec("Child", (0.0, 0.0, 1.0), (0.0, 0.0, 2.0), parent_name="Parent"),
        BoneSpec("Parent", (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    )
    with pytest.raises(ValueError, match="parents must come first"):
        add_armature("Rig", bones)
    assert "Rig" not in bpy.data.objects


def test_binding_without_automatic_weights_leaves_the_mesh_in_place(empty_scene):
    # Old: an armature at z=1 lifted the bound box from z 0..1 to z 1..2.
    from blended.ops.rigging import add_armature, bind_mesh_to_armature
    from blended.ops.transforms import world_bounds

    armature = add_armature(
        "Rig", _one_bone(), location_m=(0.0, 0.0, ARMATURE_HEIGHT_M)
    )
    mesh = _linked_box("Subject")
    before_m = world_bounds(mesh)["min_m"]

    bind_mesh_to_armature(mesh, armature, automatic_weights=False)

    after_m = world_bounds(mesh)["min_m"]
    assert after_m == pytest.approx(before_m, abs=PLACEMENT_TOLERANCE_M)


def test_move_object_to_places_a_parented_object_in_world_space(empty_scene):
    # Old: `.location` is parent-relative, so the child stayed at world z=5.
    from blended.ops.transforms import move_object_to

    child = _linked_box("Child")
    parent = bpy.data.objects.new("Parent", None)
    bpy.context.scene.collection.objects.link(parent)
    parent.location = (0.0, 0.0, PARENT_HEIGHT_M)
    bpy.context.view_layer.update()
    bpy.data.objects[child].parent = parent

    move_object_to(child, (0.0, 0.0, 0.0))

    translation_m = tuple(bpy.data.objects[child].matrix_world.translation)
    assert translation_m == pytest.approx((0.0, 0.0, 0.0), abs=PLACEMENT_TOLERANCE_M)


def test_axis_normal_selection_uses_true_world_normals_under_non_uniform_scale(
    empty_scene,
):
    # Old: a 45-degree face under z-scale 10 read as a +z face (normal
    # (-0.10, 0, 0.995)); its true world normal is (-0.995, 0, 0.10).
    import bmesh

    from blended.ops.selectors import FaceSelector, select_faces

    mesh_data = bpy.data.meshes.new("Slant")
    slanted = bpy.data.objects.new("Slant", mesh_data)
    bpy.context.scene.collection.objects.link(slanted)
    working = bmesh.new()
    try:
        corners = [
            working.verts.new(point)
            for point in ((0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 0.0))
        ]
        working.faces.new(corners)
        working.to_mesh(mesh_data)
    finally:
        working.free()
    slanted.scale = (1.0, 1.0, FLATTENED_Z_SCALE)

    selects_up = select_faces(
        "Slant",
        FaceSelector(
            kind="axis_normal",
            axis="+z",
            normal_tolerance_deg=SLANTED_FACE_TOLERANCE_DEG,
        ),
    )
    selects_left = select_faces(
        "Slant",
        FaceSelector(
            kind="axis_normal",
            axis="-x",
            normal_tolerance_deg=SLANTED_FACE_TOLERANCE_DEG,
        ),
    )
    assert selects_up == ()
    assert selects_left == (0,)


def test_height_weights_see_a_location_set_a_moment_ago(empty_scene):
    # Old: matrix_world was stale, so a box moved to z=10 selected 0 vertices
    # in the world range 10..10.6 instead of its 4 base vertices.
    from blended.ops.weights import assign_weights_by_height

    box = _linked_box("Box")
    bpy.data.objects[box].location = (0.0, 0.0, 10.0)

    assigned = assign_weights_by_height(box, "Base", 10.0, 10.6, 1.0)

    assert assigned == 4


def test_animation_report_on_an_action_with_no_keyframes_is_empty_not_an_error(
    empty_scene,
):
    # Old: IndexError from action.layers[0] on an action nobody keyed.
    from blended.ops.animation import animation_report

    box = _linked_box("Box")
    blender_object = bpy.data.objects[box]
    blender_object.animation_data_create()
    blender_object.animation_data.action = bpy.data.actions.new("Unkeyed")

    report = animation_report(box)

    assert report.action_name == "Unkeyed"
    assert report.fcurve_count == 0
    assert report.keyframe_count == 0


def test_a_rejected_euler_order_leaves_the_rotation_mode_alone(empty_scene):
    # Old: rotation_mode was already AXIS_ANGLE when the Euler raised.
    from blended.ops.transforms import rotate_object_euler

    box = _linked_box("Box")
    with pytest.raises(ValueError):
        rotate_object_euler(box, z_rad=math.pi, order="AXIS_ANGLE")
    assert bpy.data.objects[box].rotation_mode == "XYZ"


def test_rename_returns_the_name_the_object_actually_has(empty_scene):
    # Old: returned the requested 300-char name; Blender stores 255 bytes.
    from blended.ops.primitives import rename_object

    box = _linked_box("Box")
    returned = rename_object(box, "n" * OVERLONG_OBJECT_NAME_LENGTH)

    assert returned in bpy.data.objects


def test_a_failed_unwrap_leaves_the_object_out_of_edit_mode(empty_scene):
    # Old: the unwrap operator's poll failure on a mesh with no geometry left
    # the object in EDIT mode, and the finally block's select_all (no poll in
    # edit mode) replaced it with an unrelated RuntimeError.
    from blended.ops.uv import unwrap_uvs

    empty_mesh = bpy.data.meshes.new("Empty")
    empty_object = bpy.data.objects.new("Empty", empty_mesh)
    bpy.context.scene.collection.objects.link(empty_object)

    with pytest.raises(RuntimeError) as failure:
        unwrap_uvs("Empty")

    assert empty_object.mode == "OBJECT"
    assert "select_all" not in str(failure.value)


def test_a_flat_colour_replaces_a_texture_left_on_a_reused_material(empty_scene):
    # Old: the checker stayed linked to Base Color, so the requested flat
    # colour was ignored by every renderer but Workbench.
    from blended.ops.material_nodes import assign_procedural_material, material_report
    from blended.ops.materials import assign_material

    box = _linked_box("Box")
    assign_procedural_material(box, "Shared", "checker")
    assign_material(box, "Shared", base_color_rgb=(1.0, 0.0, 0.0))

    assert material_report(box).base_color_linked is False


def test_a_failed_sole_trim_does_not_leave_its_cutter_in_the_scene(empty_scene):
    # Old: a box floating above z=0 gave BooleanNoOp and left `Float_SoleCutter`
    # linked into the scene as a second, unconsumed object.
    from blended.ops.booleans import BooleanNoOp
    from blended.ops.legs import trim_soles_flat

    floating = _linked_box("Float", location_m=(0.0, 0.0, PARENT_HEIGHT_M))

    with pytest.raises(BooleanNoOp):
        trim_soles_flat(floating, span_m=1.0)

    assert sorted(blender_object.name for blender_object in bpy.data.objects) == [
        "Float"
    ]
