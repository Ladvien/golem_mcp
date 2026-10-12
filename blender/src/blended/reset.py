"""Wipe the scene to a canonical empty state, then assert the wipe took.

A rebuild that starts from residue measures the previous build. scp's
harness learned this twice: Blender's undo stack is unreliable from
script-driven operators, so an undo-based rewind is not a mechanism a
rebuild may trust, and a wipe that is not asserted is a
wipe that silently left an object behind — after which every count,
extent and digest in the run belongs to two builds at once.

So this module does two separable things, and the postcondition is the
important half: `reset_scene()` wipes, `assert_clean_scene()` proves it.
Anything that rebuilds (the metamorphic probe, the reproducibility
digest) calls the assertion, not just the wipe.

Scene settings belong in a *reset* for one measured reason: the FBX
importer rewrites `scene.render.fps` on load, which resamples every clip
already in the scene. A canonical fps is therefore part of "clean", and
`CANONICAL_FPS` is the number to save and restore around any import that
touches it (see `blended.drift.catalog`). The frame range, the current
frame, the unit system, unit scale and length unit, and the render
resolution are restored and asserted for the same reason as the datablocks:
a build that changed one leaves it for the next build, which then measures
residue.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

CANONICAL_FPS = 24

# Blender 5.2.0 factory values (read_factory_settings(use_empty=True)).
CANONICAL_FRAME_START = 1
CANONICAL_FRAME_END = 250
CANONICAL_FRAME_CURRENT = 1
CANONICAL_UNIT_SYSTEM = "METRIC"
CANONICAL_UNIT_SCALE_LENGTH = 1.0
CANONICAL_LENGTH_UNIT = "METERS"
CANONICAL_RESOLUTION_X_PX = 1920
CANONICAL_RESOLUTION_Y_PX = 1080
CANONICAL_RESOLUTION_PERCENTAGE = 100

# Wiped in dependency order: objects before the data they reference, so
# removing a mesh never trips a user count that an object still holds.
WIPE_COLLECTIONS = (
    "objects",
    "meshes",
    "armatures",
    "curves",
    "metaballs",
    "volumes",
    "grease_pencils",
    "materials",
    "images",
    "cameras",
    "lights",
    "lightprobes",
    "speakers",
    "actions",
    "particles",
    "collections",
)

# Materials and images are deliberately NOT required to be empty: a live
# GUI session holds an unremovable "Render Result" / "Viewer Node" image,
# and default materials regenerate. Requiring them would make the
# assertion fail in the GUI and pass headless, which is worse than not
# checking them.
MUST_BE_EMPTY = ("objects", "meshes", "armatures", "collections")

# A failure lists the leftover datablocks by name, because "3 objects
# remain" sends the reader back to the console. Capped so a wipe that
# left 4,000 objects behind does not produce a 4,000-name message.
LEFTOVER_NAMES_REPORTED = 10


class SceneNotClean(RuntimeError):
    """The wipe did not take, or the scene is not in canonical state."""


def _canonical_scene_settings(scene) -> tuple[tuple[str, object, object], ...]:
    """(name, current, canonical) for every scene setting `reset_scene` restores
    besides fps, which has its own message and its own argument."""
    unit_settings = scene.unit_settings
    render = scene.render
    return (
        ("scene.frame_start", scene.frame_start, CANONICAL_FRAME_START),
        ("scene.frame_end", scene.frame_end, CANONICAL_FRAME_END),
        ("scene.frame_current", scene.frame_current, CANONICAL_FRAME_CURRENT),
        ("scene.unit_settings.system", unit_settings.system, CANONICAL_UNIT_SYSTEM),
        (
            "scene.unit_settings.scale_length",
            unit_settings.scale_length,
            CANONICAL_UNIT_SCALE_LENGTH,
        ),
        (
            "scene.unit_settings.length_unit",
            unit_settings.length_unit,
            CANONICAL_LENGTH_UNIT,
        ),
        ("scene.render.resolution_x", render.resolution_x, CANONICAL_RESOLUTION_X_PX),
        ("scene.render.resolution_y", render.resolution_y, CANONICAL_RESOLUTION_Y_PX),
        (
            "scene.render.resolution_percentage",
            render.resolution_percentage,
            CANONICAL_RESOLUTION_PERCENTAGE,
        ),
    )


def reset_scene(fps: int = CANONICAL_FPS) -> None:
    """Wipe to an empty canonical scene, then assert the wipe took.

    Every name in WIPE_COLLECTIONS must resolve on bpy.data: a renamed
    collection is a loud failure surfaced by assert_clean_scene, not a
    silent skip, because a silent skip is how a whole datablock class
    stops being wiped forever.  Measured in Blender 5.2.0: the RNA
    collection is named ``grease_pencils`` (type BlendDataGreasePencilsV3),
    NOT ``grease_pencils_v3`` — the latter was never a bpy.data attribute
    and the row was dead until this fix.
    """
    import bpy

    missing = [
        name for name in WIPE_COLLECTIONS if getattr(bpy.data, name, None) is None
    ]
    if missing:
        raise SceneNotClean(
            f"bpy.data has no collection(s): {', '.join(missing)} — "
            f"a wipe-list name does not resolve; update WIPE_COLLECTIONS"
        )

    for collection_name in WIPE_COLLECTIONS:
        collection = getattr(bpy.data, collection_name)
        for datablock in list(collection):
            collection.remove(datablock)

    # Removal drops the direct users; the purge collects what those
    # datablocks referenced in turn (node groups, node trees, actions).
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    scene = bpy.context.scene
    scene.render.fps = fps
    # Frame range before the current frame, so the current frame is in range.
    scene.frame_start = CANONICAL_FRAME_START
    scene.frame_end = CANONICAL_FRAME_END
    scene.frame_set(CANONICAL_FRAME_CURRENT)
    scene.unit_settings.system = CANONICAL_UNIT_SYSTEM
    scene.unit_settings.scale_length = CANONICAL_UNIT_SCALE_LENGTH
    scene.unit_settings.length_unit = CANONICAL_LENGTH_UNIT
    scene.render.resolution_x = CANONICAL_RESOLUTION_X_PX
    scene.render.resolution_y = CANONICAL_RESOLUTION_Y_PX
    scene.render.resolution_percentage = CANONICAL_RESOLUTION_PERCENTAGE
    assert_clean_scene(fps)


def assert_clean_scene(fps: int = CANONICAL_FPS) -> None:
    """Raise SceneNotClean listing EVERY problem at once.

    One problem per raise would make a caller fix, re-run, and discover
    the next one — three Blender launches to learn what one message can
    say.
    """
    import bpy

    problems: list[str] = []

    for collection_name in MUST_BE_EMPTY:
        collection = getattr(bpy.data, collection_name, None)
        if collection is None:
            problems.append(f"bpy.data has no {collection_name!r} collection")
            continue
        leftover = [datablock.name for datablock in collection]
        if leftover:
            shown = ", ".join(leftover[:LEFTOVER_NAMES_REPORTED])
            if len(leftover) > LEFTOVER_NAMES_REPORTED:
                shown += f", +{len(leftover) - LEFTOVER_NAMES_REPORTED} more"
            problems.append(f"{len(leftover)} {collection_name} remain: {shown}")

    scene = bpy.context.scene
    scene_fps = scene.render.fps
    if scene_fps != fps:
        problems.append(
            f"scene.render.fps is {scene_fps}, not the canonical {fps}: "
            f"an FBX import rewrites it and resamples every clip"
        )
    for setting_name, value, canonical_value in _canonical_scene_settings(scene):
        if value != canonical_value:
            problems.append(
                f"{setting_name} is {value}, not the canonical {canonical_value}"
            )

    # A scene that cannot be evaluated is not clean, it is broken: every
    # measurement downstream reads `evaluated_get` and would return
    # stored values with no error.
    try:
        bpy.context.view_layer.update()
        bpy.context.evaluated_depsgraph_get()
    except Exception as error:  # noqa: BLE001 — reported, not raised
        problems.append(f"depsgraph will not evaluate: {error}")

    if problems:
        raise SceneNotClean("; ".join(problems))
