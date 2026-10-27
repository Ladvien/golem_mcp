"""Work in a named scene without moving the user's window, or move it on purpose.

Three ops, one session state (`scene_target`):

- `use_scene(name, create, follow)` — the scene this session's ops resolve in.
  `follow=False` leaves the user's window where it is: the scene is swapped for
  the duration of each call and swapped back before the next redraw, so a
  modelling pass in a background scene never takes over the user's view.
- `list_scenes()` — every scene, its counts, which one the session is working in,
  which one the window shows, and whether the viewport follow is held.
- `hold_view(held)` — the user's veto on the viewport follow.

Why this is ops and not a setting: the gate, the boolean operand check and
`link_into_scene` all resolve through `bpy.context.scene`, so "which scene" is
part of what an op MEANS. A session that selected a scene and then had a boolean
silently operate in another one would be the same class of bug as a stale
depsgraph, and just as invisible.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender import scene_target
from golem_blender.ops._contract import op


class UnknownScene(LookupError):
    """No scene of that name exists, and `create` was not asked for."""


@dataclass(frozen=True)
class SceneSelection:
    """The scene now being worked in, what it replaced, and whether the window follows."""

    scene_name: str
    previous_scene_name: str
    follow: bool
    created: bool


@dataclass(frozen=True)
class SceneEntry:
    """One scene and how much is in it."""

    name: str
    object_count: int
    mesh_count: int


@dataclass(frozen=True)
class SceneListing:
    """Every scene, the working one, the window's one, and the view's state."""

    scenes: tuple[SceneEntry, ...]
    working_scene_name: str
    window_scene_name: str
    view_held: bool


@op()
def use_scene(name: str, create: bool = False, follow: bool = True) -> SceneSelection:
    """Make ops, the gate and booleans resolve in the named scene; follow=False leaves your window where it is.

    A name of "" clears the selection, so calls resolve in the window's own scene
    again — that is the state a session starts in, and the state `reset_scene`
    returns to.

    `follow=True` also moves the window into the scene, which is what a user
    watching wants. `follow=False` is what an agent doing a long pass in a
    background scene wants: the window is never moved, and each call swaps the
    scene for its own duration only. Either way the scene is where this session's
    ops resolve: `link_into_scene`, the gate and the boolean operand check all
    read `bpy.context.scene`, so a boolean run while working elsewhere creates its
    result THERE and not in the user's scene.

    A name that does not exist raises `UnknownScene` naming the scenes that do,
    unless `create=True`, which makes it. `previous_scene_name` is what the
    session was working in before (or the window's scene when nothing was
    selected), so a caller can put things back.
    """
    import bpy

    previous = scene_target.working_scene_name() or scene_target.window_scene_name()
    if not name:
        scene_target.select(None, follow)
        return SceneSelection(
            scene_name="",
            previous_scene_name=previous,
            follow=follow,
            created=False,
        )
    scene = bpy.data.scenes.get(name)
    created = False
    if scene is None:
        if not create:
            raise UnknownScene(
                f"no scene named {name!r} (scenes: "
                f"{sorted(existing.name for existing in bpy.data.scenes)}); pass "
                f"create=True to make it"
            )
        scene = bpy.data.scenes.new(name)
        created = True
    scene_target.select(scene.name, follow)
    if follow:
        window = bpy.context.window
        if window is None:
            from golem_blender.scene_target import _first_window

            window = _first_window()
        if window is not None:
            window.scene = scene
    return SceneSelection(
        scene_name=scene.name,
        previous_scene_name=previous,
        follow=follow,
        created=created,
    )


def _scene_entry(scene) -> SceneEntry:
    return SceneEntry(
        name=scene.name,
        object_count=len(scene.objects),
        mesh_count=sum(1 for item in scene.objects if item.type == "MESH"),
    )


@op(reads_only=True)
def list_scenes() -> SceneListing:
    """List every scene with its object counts, the working scene, the window's scene and whether the view is held.

    The two scene names are separate on purpose: a session can be WORKING in one
    scene while the user's window shows another, and a caller that cannot see both
    cannot tell whether the user is looking at what the agent is doing.
    """
    import bpy

    return SceneListing(
        scenes=tuple(
            _scene_entry(scene)
            for scene in sorted(bpy.data.scenes, key=lambda item: item.name)
        ),
        working_scene_name=scene_target.working_scene_name() or "",
        window_scene_name=scene_target.window_scene_name(),
        view_held=scene_target.view_is_held(),
    )


@op()
def hold_view(held: bool = True) -> SceneListing:
    """Stop (or resume) golem moving the 3D view after scene-changing calls; reports the scene listing.

    The viewport follow frames the part a call touched so a watching user sees the
    work without the agent spending a call on it. That is usually wanted and
    sometimes not — a user comparing two parts, or reading a viewport, does not
    want it jumped. With `held=True` every following call answers with a
    `viewport: held` line instead of framing anything, and that line is the proof
    it did not move: the framing code is never reached, so the camera-view to
    perspective flip it performs does not happen either.

    Returns the scene listing, so one call both sets the state and shows the
    scenes it applies to.
    """
    scene_target.set_view_held(held)
    return list_scenes()
