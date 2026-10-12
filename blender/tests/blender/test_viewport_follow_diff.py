"""Rule 1: a scene-changing call frames what it CHANGED, found by diffing the scene.

Before, the viewport followed only the objects a call named (gated objects and
op arguments). A `run_python` chunk that moved, edited or created an object
without naming it left the user's view where it was.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

MOVED_BY_M = (0.5, 0.0, 0.0)
EDIT_NUDGE_M = 0.01
ARRAY_COUNT = 2
LARGER_ARRAY_COUNT = 3


@pytest.fixture()
def scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield bpy.context.scene


def _add_cube(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        [(x, y, z) for z in (-0.5, 0.5) for y in (-0.5, 0.5) for x in (-0.5, 0.5)],
        [],
        [
            (0, 2, 3, 1),
            (4, 5, 7, 6),
            (0, 1, 5, 4),
            (2, 6, 7, 3),
            (0, 4, 6, 2),
            (1, 3, 7, 5),
        ],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _changed_since(before):
    from blended.viewport_follow import changed_object_names

    return changed_object_names(before)


def test_an_unchanged_scene_changes_nothing(scene):
    from blended.viewport_follow import snapshot_scene

    _add_cube("A")
    before = snapshot_scene()

    assert _changed_since(before) == ()


def test_a_created_object_is_changed_and_a_bystander_is_not(scene):
    from blended.viewport_follow import snapshot_scene

    _add_cube("Bystander")
    before = snapshot_scene()
    _add_cube("Created", (3.0, 0.0, 0.0))

    assert _changed_since(before) == ("Created",)


def test_a_moved_object_is_changed_without_a_view_layer_update(scene):
    """matrix_world is stale after `obj.location = ...` until the depsgraph runs;
    the snapshot must refresh it, or a pure move reads as no change."""
    from blended.viewport_follow import snapshot_scene

    mover = _add_cube("Mover")
    _add_cube("Bystander", (5.0, 0.0, 0.0))
    before = snapshot_scene()
    mover.location = MOVED_BY_M

    assert _changed_since(before) == ("Mover",)


def test_an_in_place_vertex_edit_is_changed(scene):
    """Same name, same transform, same counts: only a coordinate moved."""
    from blended.viewport_follow import snapshot_scene

    edited = _add_cube("Edited")
    _add_cube("Bystander", (5.0, 0.0, 0.0))
    before = snapshot_scene()
    edited.data.vertices[0].co.x -= EDIT_NUDGE_M

    assert _changed_since(before) == ("Edited",)


def test_a_material_assigned_is_changed(scene):
    from blended.viewport_follow import snapshot_scene

    painted = _add_cube("Painted")
    before = snapshot_scene()
    painted.data.materials.append(bpy.data.materials.new("Paint"))

    assert _changed_since(before) == ("Painted",)


def test_a_modifier_setting_changed_is_changed(scene):
    """The stack and the base mesh are identical; only the array count changed,
    which grows the evaluated bounding box. (A bevel width would not: a bevel
    leaves a cube's bounds as they were, and the snapshot says it cannot see
    a setting that does.)"""
    from blended.viewport_follow import snapshot_scene

    repeated = _add_cube("Repeated")
    modifier = repeated.modifiers.new("Array", "ARRAY")
    modifier.count = ARRAY_COUNT
    before = snapshot_scene()
    modifier.count = LARGER_ARRAY_COUNT

    assert _changed_since(before) == ("Repeated",)


def test_a_reparented_object_is_changed(scene):
    from blended.viewport_follow import snapshot_scene

    parent = _add_cube("Parent")
    child = _add_cube("Child", (3.0, 0.0, 0.0))
    before = snapshot_scene()
    child.parent = parent

    assert "Child" in _changed_since(before)


def test_the_names_to_frame_are_the_outcome_names_then_the_diff(scene):
    """A gated `Hole` the outcome names, plus an unnamed `Stray` the chunk moved."""
    from blended.agent.outcome import ToolOutcome
    from blended.viewport_follow import names_to_frame, snapshot_scene

    _add_cube("Hole")
    stray = _add_cube("Stray", (4.0, 0.0, 0.0))
    before = snapshot_scene()
    stray.location = (4.0, 1.0, 0.0)
    outcome = ToolOutcome("ok", intermediates_resolved=("Hole",))

    assert names_to_frame(outcome, before) == ("Hole", "Stray")
    assert names_to_frame(outcome, None) == ("Hole",)
