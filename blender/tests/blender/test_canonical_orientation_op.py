"""The bpy half of the depth-axis rule, in a real scene.

`apply_canonical_depth_axis` is the epilogue appended to every emitted
3DCodeBench script, so what it does to a live scene IS the benchmark
artifact. Pinned here: the middle world extent ends up on Blender Y (glTF
Z after `export_yup`), a writer's existing rotation is respected rather
than overwritten, a second call is a no-op, and an empty scene fails loud.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

from mathutils import Vector

pytestmark = pytest.mark.blender

QUARTER_TURN_RAD = math.pi / 2.0
EXTENT_TOLERANCE_M = 1e-5
# X longest, Y thinnest: the middle extent (1.0 m) sits on Z and must be
# turned onto Y. Same anchor case the pure test pins.
SUBJECT_EXTENTS_M = (2.0, 0.1, 1.0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _subject(extents_m=SUBJECT_EXTENTS_M):
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("Subject", *extents_m)
    link_into_scene(box)
    return box


def _world_extents_m(object_name):
    """Measured independently of the op under test: corners through
    `matrix_world`, the ground truth the op's own helper must match."""
    blender_object = bpy.data.objects[object_name]
    bpy.context.view_layer.update()
    corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    return tuple(
        max(corner[axis] for corner in corners)
        - min(corner[axis] for corner in corners)
        for axis in range(3)
    )


def test_the_middle_extent_ends_up_on_the_depth_axis(empty_scene):
    from blended.ops.canonical_orientation import apply_canonical_depth_axis

    box = _subject()
    record = apply_canonical_depth_axis()

    assert record["objects"] == ["Subject"]
    assert record["depth_axis_extent_rank"] == 1
    extents_m = _world_extents_m(box)
    assert extents_m == pytest.approx((2.0, 1.0, 0.1), abs=EXTENT_TOLERANCE_M)
    assert record["extents_after_m"] == pytest.approx(extents_m, abs=EXTENT_TOLERANCE_M)


def test_a_writers_own_rotation_is_composed_not_discarded(empty_scene):
    """The writer already turned the box; the epilogue corrects from there."""
    from blended.ops.canonical_orientation import apply_canonical_depth_axis
    from blended.ops.transforms import rotate_object_euler

    box = _subject()
    # A quarter turn about X puts the 1.0 m extent on Y already: the rule
    # must then do nothing, which is only possible if it measures the
    # ROTATED world extents instead of the local ones.
    rotate_object_euler(box, x_rad=QUARTER_TURN_RAD)
    record = apply_canonical_depth_axis()

    assert record["rotation_applied_rad"] == (0.0, 0.0, 0.0)
    assert _world_extents_m(box) == pytest.approx(
        (2.0, 1.0, 0.1), abs=EXTENT_TOLERANCE_M
    )


def test_a_second_call_is_a_no_op(empty_scene):
    """The emitted script is re-baked; the epilogue must be idempotent."""
    from blended.ops.canonical_orientation import apply_canonical_depth_axis

    box = _subject()
    apply_canonical_depth_axis()
    first_extents_m = _world_extents_m(box)
    record = apply_canonical_depth_axis()

    assert record["rotation_applied_rad"] == (0.0, 0.0, 0.0)
    assert _world_extents_m(box) == pytest.approx(
        first_extents_m, abs=EXTENT_TOLERANCE_M
    )


def test_every_mesh_turns_together(empty_scene):
    """A run that leaves two meshes is scored as one exported cloud."""
    from blended.ops.canonical_orientation import apply_canonical_depth_axis
    from blended.ops.primitives import add_box, link_into_scene
    from blended.ops.transforms import move_object_to

    first = _subject()
    second = add_box("Second", 0.2, 0.2, 0.2)
    link_into_scene(second)
    move_object_to(second, (1.5, 0.0, 0.0))
    record = apply_canonical_depth_axis()

    assert sorted(record["objects"]) == ["Second", "Subject"]
    # Rigid: the joint box turns, so the pair's relative offset turns too.
    assert bpy.data.objects[first].matrix_world.to_euler().x == pytest.approx(
        bpy.data.objects[second].matrix_world.to_euler().x
    )
    joint_before_m = record["extents_before_m"]
    joint_after_m = record["extents_after_m"]
    assert sorted(joint_after_m) == pytest.approx(
        sorted(joint_before_m), abs=EXTENT_TOLERANCE_M
    )


def test_a_named_object_can_be_targeted(empty_scene):
    from blended.ops.canonical_orientation import apply_canonical_depth_axis

    _subject()
    record = apply_canonical_depth_axis("Subject")
    assert record["objects"] == ["Subject"]


def test_an_empty_scene_fails_loud(empty_scene):
    from blended.ops.canonical_orientation import apply_canonical_depth_axis

    with pytest.raises(RuntimeError):
        apply_canonical_depth_axis()


def test_a_missing_name_fails_loud(empty_scene):
    from blended.ops.canonical_orientation import apply_canonical_depth_axis

    _subject()
    with pytest.raises(RuntimeError):
        apply_canonical_depth_axis("NoSuchObject")
