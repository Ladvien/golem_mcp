"""Which scene the ops resolve in, and whether the user's window follows (MCP only).

The measured need: an agent working in an abbey's workshop scene either moved the
user's window into that scene (so the user's own view was taken over) or could
not work in it at all, because the gate, the boolean operand check and
`link_into_scene` all read `bpy.context.scene`. A session therefore needs to say
WHICH scene its calls resolve in, separately from whether the window is moved
there.

Two independent switches, because they answer two questions:

- **the working scene** — the scene this session's ops resolve in. `None` means
  the window's own scene, which is the behaviour with nothing set.
- **follow** — whether the WINDOW is moved into the working scene. `False` leaves
  the user's view where it is; the swap happens for the duration of one call and
  is undone before the next redraw, so nothing is ever seen to flicker.

They are separate because "work in scene B" and "show me scene B" are different
intentions and either can be wanted without the other.

A third switch, `hold_view`, is the user's veto on the viewport follow: with it
on, a scene-changing call reports that it did not move the view instead of
framing the part it touched.

What makes the temporary swap safe: `bpy.context.temp_override(scene=...,
view_layer=...)` — measured in headless Blender, the SCENE alone leaves
`view_layer` on the window's layer, so no object is visible and a boolean finds
nothing. Both keys are set here, always.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import contextlib

# The session's own state. One module-level dict rather than three globals, so
# `reset()` is one assignment and a test can see the whole state at once.
_STATE: dict = {"scene": None, "follow": True, "hold_view": False}


class WorkingSceneMissing(RuntimeError):
    """The scene this session was working in has been deleted."""


def select(scene_name: str | None, follow: bool) -> None:
    """Make `scene_name` the working scene (`None` clears it) and set `follow`."""
    _STATE["scene"] = scene_name or None
    _STATE["follow"] = bool(follow)


def reset() -> None:
    """Forget the selection, re-enable following and release the view.

    Called by `reset_scene`, because a wipe leaves no scene to be working IN and
    a later call that resolved into a deleted scene would fail confusingly.
    """
    _STATE["scene"] = None
    _STATE["follow"] = True
    _STATE["hold_view"] = False


def working_scene_name() -> str | None:
    """The scene this session's ops resolve in, or None for the window's own."""
    return _STATE["scene"]


def follows() -> bool:
    """Does the window move into the working scene for a call?"""
    return bool(_STATE["follow"])


def view_is_held() -> bool:
    """Is the viewport follow suppressed?"""
    return bool(_STATE["hold_view"])


def set_view_held(held: bool) -> None:
    _STATE["hold_view"] = bool(held)


def _first_window():
    import bpy

    window = bpy.context.window
    if window is not None:
        return window
    windows = getattr(bpy.context.window_manager, "windows", None)
    if windows:
        return windows[0]
    return None


@contextlib.contextmanager
def working_scene_context():
    """Make the working scene (and its view layer) `bpy.context`'s for one call.

    Three cases, each the defined behaviour rather than a fallback chain:

    - no working scene: yield unchanged, so a session that never selected one
      behaves exactly as it did before this module existed;
    - the working scene is gone: raise `WorkingSceneMissing`, naming the scenes
      that do exist — silently working in the user's scene would be worse;
    - otherwise the context's scene and view layer are the working scene's, and
      the WINDOW is moved there only when following, then put back.

    Both `scene` and `view_layer` are overridden together: measured in headless
    Blender, `temp_override(scene=other)` alone leaves `view_layer` on the
    window's layer, so no object in the target scene is visible to an operator.
    """
    name = working_scene_name()
    if name is None:
        # Nothing selected: the call resolves where bpy.context already points,
        # which is the behaviour before this module existed. Returning here also
        # keeps the PURE dispatch path importable — a test that drives
        # `dispatch_tool` with no Blender in sys.modules never reaches the bpy
        # import below.
        yield
        return
    import bpy

    target = bpy.data.scenes.get(name)
    if target is None:
        raise WorkingSceneMissing(
            f"the working scene {name!r} no longer exists; call use_scene again "
            f"(scenes: {sorted(scene.name for scene in bpy.data.scenes)})"
        )
    window = _first_window()
    if window is None:
        with bpy.context.temp_override(scene=target, view_layer=target.view_layers[0]):
            yield
        return
    previous = window.scene
    # The window's scene drives every operator's context, so this is what makes
    # `link_into_scene`, the gate and the boolean operand check resolve in the
    # working scene rather than the user's.
    with bpy.context.temp_override(window=window):
        window.scene = target
        try:
            yield
        finally:
            # With follow on, the window STAYS on the working scene: that is what
            # following means. With it off, the user never sees the swap.
            if not follows():
                window.scene = previous


def window_scene_name() -> str:
    """The scene the user's window shows, or "" when there is no window."""
    window = _first_window()
    if window is None or window.scene is None:
        return ""
    return window.scene.name
