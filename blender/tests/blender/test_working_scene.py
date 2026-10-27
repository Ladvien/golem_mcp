"""Work in a background scene without taking over the user's window.

The measured need: an agent working in an abbey's workshop either moved the user's
window into that scene (taking the view over) or could not work in it at all,
because `link_into_scene`, the gate and the boolean operand check all resolve
through `bpy.context.scene`.

Each test states one of those as an observable: the boolean's result lands in the
named scene and NOT in the user's, the window's scene is unchanged after every
call, a deleted working scene fails LOUDLY rather than silently working in the
wrong place, and `hold_view` stops the viewport follow from framing anything.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

WORKSHOP = "Abbey Workshop"
CUTTER_OFFSET_M = 0.5


@pytest.fixture()
def two_scenes():
    """A home scene with one object, and an empty second scene; clean session state."""
    from golem_blender import scene_target
    from golem_blender.ops import assembly, coplanar, pieces

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()
    scene_target.reset()

    home = bpy.context.scene
    home.name = "Home"
    from golem_blender.ops import add_box, link_into_scene

    sentinel = add_box("HomeSentinel", 1.0, 1.0, 1.0)
    link_into_scene(sentinel)
    yield home
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()
    scene_target.reset()


def _dispatch(tool_name, arguments):
    from golem_blender.agent.tools import dispatch_tool

    return dispatch_tool(tool_name, dict(arguments))


def _object_names(scene):
    return {item.name for item in scene.objects}


def test_a_boolean_in_a_background_scene_lands_there_and_not_in_the_home_scene(
    two_scenes,
):
    """The whole point: the result is in the named scene, and the window never moved."""
    home = two_scenes
    selection = _dispatch(
        "use_scene", {"name": WORKSHOP, "create": True, "follow": False}
    )
    assert selection.ok, selection.text
    workshop = bpy.data.scenes[WORKSHOP]
    assert _object_names(workshop) == set()

    assert _dispatch(
        "add_box", {"name": "Block", "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}
    ).ok
    assert _dispatch("link_into_scene", {"object_name": "Block"}).ok
    assert bpy.context.window.scene is home, (
        "follow=False must leave the window where it was"
    )

    assert _dispatch(
        "add_box",
        {
            "name": "Cutter",
            "width_m": 0.4,
            "depth_m": 0.4,
            "height_m": 0.4,
            "location_m": [CUTTER_OFFSET_M, 0.0, 0.0],
        },
    ).ok
    assert _dispatch("link_into_scene", {"object_name": "Cutter"}).ok
    outcome = _dispatch(
        "boolean_difference", {"target_name": "Block", "cutter_name": "Cutter"}
    )
    assert outcome.ok, outcome.text

    assert "Block" in _object_names(workshop), (
        "the boolean's result belongs to the working scene"
    )
    assert "Block" not in _object_names(home), "the user's scene must be untouched"
    assert bpy.context.window.scene is home, (
        "the window must be back on the user's scene after every call"
    )


def test_following_moves_the_window_into_the_working_scene(two_scenes):
    home = two_scenes
    outcome = _dispatch("use_scene", {"name": WORKSHOP, "create": True, "follow": True})
    assert outcome.ok, outcome.text
    assert bpy.context.window.scene.name == WORKSHOP
    assert bpy.context.window.scene is not home


def test_clearing_the_selection_restores_the_window_s_scene(two_scenes):
    home = two_scenes
    _dispatch("use_scene", {"name": WORKSHOP, "create": True, "follow": False})
    cleared = _dispatch("use_scene", {"name": ""})
    assert cleared.ok, cleared.text
    assert bpy.context.window.scene is home
    # A call now resolves in the window's own scene again.
    assert _dispatch(
        "add_box",
        {"name": "HomeBlock", "width_m": 0.2, "depth_m": 0.2, "height_m": 0.2},
    ).ok
    assert _dispatch("link_into_scene", {"object_name": "HomeBlock"}).ok
    assert "HomeBlock" in _object_names(home)


def test_a_deleted_working_scene_fails_loudly(two_scenes):
    """Silently working in the user's scene would be worse than failing."""
    _dispatch("use_scene", {"name": WORKSHOP, "create": True, "follow": False})
    bpy.data.scenes.remove(bpy.data.scenes[WORKSHOP])
    outcome = _dispatch(
        "add_box", {"name": "Orphan", "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}
    )
    assert outcome.ok is False
    assert "no longer exists" in outcome.text


def test_a_missing_scene_is_refused_by_name(two_scenes):
    outcome = _dispatch("use_scene", {"name": "Nope"})
    assert outcome.ok is False
    assert "no scene named 'Nope'" in outcome.text
    assert "create=True" in outcome.text


def test_the_listing_shows_both_scenes_and_both_scene_names(two_scenes):
    home = two_scenes
    _dispatch("use_scene", {"name": WORKSHOP, "create": True, "follow": False})
    _dispatch(
        "add_box", {"name": "Block", "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}
    )
    _dispatch("link_into_scene", {"object_name": "Block"})
    listing = _dispatch("list_scenes", {})
    assert listing.ok, listing.text

    from golem_blender.ops import list_scenes

    scenes = {entry.name: entry for entry in list_scenes().scenes}
    assert set(scenes) == {"Home", WORKSHOP}
    assert scenes["Home"].object_count == 1  # the sentinel
    assert scenes[WORKSHOP].mesh_count == 1  # Block
    reported = list_scenes()
    assert reported.working_scene_name == WORKSHOP
    assert reported.window_scene_name == home.name
    assert reported.view_held is False


def test_hold_view_stops_the_viewport_follow_from_framing_anything(two_scenes):
    from golem_blender import scene_target, viewport_follow
    from golem_blender.agent.outcome import ToolOutcome

    held = _dispatch("hold_view", {"held": True})
    assert held.ok, held.text
    assert scene_target.view_is_held() is True

    def _must_not_frame(*args, **kwargs):
        raise AssertionError("the viewport follow must not frame anything while held")

    original = viewport_follow.frame_in_viewports
    viewport_follow.frame_in_viewports = _must_not_frame
    try:
        outcome = viewport_follow.follow_viewport(ToolOutcome("done"))
    finally:
        viewport_follow.frame_in_viewports = original
    assert outcome.text.splitlines()[-1].startswith("viewport: held")

    released = _dispatch("hold_view", {"held": False})
    assert released.ok, released.text
    assert scene_target.view_is_held() is False


def test_reset_scene_clears_the_working_scene(two_scenes):
    from golem_blender import scene_target
    from golem_blender.reset import reset_scene

    _dispatch("use_scene", {"name": WORKSHOP, "create": True, "follow": False})
    scene_target.set_view_held(True)
    reset_scene()
    assert scene_target.working_scene_name() is None
    assert scene_target.view_is_held() is False
    assert scene_target.follows() is True
