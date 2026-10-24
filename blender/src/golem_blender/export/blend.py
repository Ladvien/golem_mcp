"""Save the editable .blend source of an exported asset.

A .glb is a baked artifact: the exporter applies modifiers and splits
vertices along flat-shading seams, so the file cannot be edited and
re-exported faithfully. The owner requires every exported asset to ship
with its Blender source (OT-50). `save_blend` writes that source and then
measures the file it wrote, the same stance as `export_glb`: the write
call's return proves nothing about the artifact.

The write goes through `bpy.data.libraries.write` from a TEMPORARY scene
(an emptied copy of the current one), so the file holds exactly the named objects with their
mesh and material data and nothing else from the session (no camera, no
sibling objects, no other scenes). The session is the user's open
Blender, often unsaved, so nothing about it may change: the temporary
scene is removed again, the objects keep their own
collections, and `bpy.data.filepath` is never touched (the write is a
library export, not a Save As).

The check re-reads the file as a LINKED library. Linked datablocks live in
the library's own namespace, so a name check against the live session is
not confused by `.001` suffixes (an append would rename every object that
already exists live), and `bpy.data.libraries.remove` takes them all away
again afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BLEND_SUFFIX = ".blend"
TEMPORARY_SCENE_PREFIX = "golem_blender_save_blend_"


class BlendSaveError(RuntimeError):
    """The .blend was not written, or the written file is not what was asked."""


@dataclass(frozen=True)
class BlendSaveReport:
    blend_path: Path
    file_size_bytes: int
    object_names: tuple[str, ...]
    # Triangles per object as re-read from the written file, not from the
    # live session.
    triangle_counts: dict[str, int]


def validate_blend_request(
    object_names: Sequence[str] | None, blend_path: Path | None
) -> tuple[tuple[str, ...], Path]:
    """The argument checks that need no Blender; raises BlendSaveError."""
    if object_names is None:
        raise BlendSaveError(
            "no objects to save: give object_names=[...] or piece='Name'"
        )
    if isinstance(object_names, str):
        raise BlendSaveError(
            f"object_names must be a list of names, got the string "
            f"{object_names!r}"
        )
    names = tuple(object_names)
    if not names:
        raise BlendSaveError("object_names is empty: there is nothing to save")
    for name in names:
        if not isinstance(name, str) or not name:
            raise BlendSaveError(f"object name {name!r} is not a non-empty string")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise BlendSaveError(f"object_names repeats {duplicates}")
    if blend_path is None:
        raise BlendSaveError(
            f"blend_path is REQUIRED: the .blend source must be written to a "
            f"path ending in {BLEND_SUFFIX!r}, got nothing"
        )
    destination = Path(blend_path)
    if destination.suffix != BLEND_SUFFIX:
        raise BlendSaveError(
            f"the .blend source must be written to a path ending in "
            f"{BLEND_SUFFIX!r}, got {str(destination)!r}"
        )
    return names, destination


def _triangle_count(blender_object) -> int:
    if blender_object.type != "MESH":
        return 0
    return sum(len(polygon.vertices) - 2 for polygon in blender_object.data.polygons)


def save_blend(
    object_names: Sequence[str] | None = None,
    blend_path: Path | None = None,
    *,
    piece: str | None = None,
) -> BlendSaveReport:
    """Write the named objects, or a defined PIECE, to a compressed .blend and verify it.

    The file's one scene holds exactly these objects, with their mesh and
    material data, under the same names and with their transforms. The
    running session is not changed. Raises BlendSaveError for an
    unusable argument, a missing object, a path that is the open file,
    an object the file does not hold, any object the file holds beyond
    the requested ones (a parent or modifier target pulled in as a
    dependency) and any triangle-count mismatch; a file that fails the
    check is deleted rather than left behind as an unverified artifact.

    `piece` names a set held by `golem_blender.ops.pieces`, so a piece is
    saved by its own name instead of by repeating its members. The two
    spellings are exclusive: a call with both is refused rather than
    silently ignoring one, and a piece with a removed member is refused
    by name (the piece is not what it was, so its file would be a lie).
    """
    import bpy

    if piece is not None:
        if object_names is not None:
            raise BlendSaveError(
                f"give object_names or piece, not both: piece {piece!r} "
                f"already names its objects, so a list beside it is ambiguous"
            )
        from golem_blender.ops.pieces import (
            PieceChangedError,
            UnknownPiece,
            _piece_object_names,
        )

        try:
            object_names = list(_piece_object_names(piece))
        except (UnknownPiece, PieceChangedError) as error:
            # Re-raised as this module's one error type, carrying the piece
            # module's own message (which names the piece and the members).
            raise BlendSaveError(str(error)) from error
    elif object_names is None:
        raise BlendSaveError(
            "no objects to save: give object_names=[...] or piece='Name'"
        )

    names, destination = validate_blend_request(object_names, blend_path)
    live_objects = []
    for name in names:
        live_object = bpy.data.objects.get(name)
        if live_object is None:
            raise BlendSaveError(
                f"No object named {name!r} in the session; nothing was written."
            )
        live_objects.append(live_object)
    if bpy.data.filepath and Path(bpy.data.filepath).resolve() == destination.resolve():
        raise BlendSaveError(
            f"{str(destination)!r} is the open file of this session; a "
            f"library write would overwrite it. Choose another path."
        )
    live_triangle_counts = {
        live_object.name: _triangle_count(live_object) for live_object in live_objects
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    # A scene made by `bpy.data.scenes.new` SEGFAULTS `libraries.write`
    # (Blender 5.2.0 LTS, measured 2026-10-10 even for an empty one; a
    # temporary Collection and the session's own scene write fine). So the
    # file's scene is a shallow COPY of the current scene, emptied: its
    # master collection is the copy's own, so unlinking children and
    # objects from it leaves the live collections alone. It keeps the
    # unit and frame settings, which a saved asset should carry.
    temporary_scene = bpy.context.scene.copy()
    temporary_scene.name = TEMPORARY_SCENE_PREFIX + destination.stem
    try:
        master_collection = temporary_scene.collection
        for child_collection in list(master_collection.children):
            master_collection.children.unlink(child_collection)
        for linked_object in list(master_collection.objects):
            master_collection.objects.unlink(linked_object)
        temporary_scene.camera = None
        temporary_scene.world = None
        for live_object in live_objects:
            master_collection.objects.link(live_object)
        bpy.data.libraries.write(
            str(destination),
            {temporary_scene},
            path_remap="ABSOLUTE",
            compress=True,
        )
    finally:
        bpy.data.scenes.remove(temporary_scene)

    try:
        written_triangle_counts = _reread_triangle_counts(destination, names)
    except BlendSaveError:
        destination.unlink(missing_ok=True)
        raise
    mismatches = [
        f"{name}: {live_triangle_counts[name]} triangles live, "
        f"{written_triangle_counts[name]} in the file"
        for name in names
        if written_triangle_counts[name] != live_triangle_counts[name]
    ]
    if mismatches:
        destination.unlink(missing_ok=True)
        raise BlendSaveError(
            "the written .blend does not match the session (file deleted): "
            + "; ".join(mismatches)
        )
    return BlendSaveReport(
        blend_path=destination,
        file_size_bytes=destination.stat().st_size,
        object_names=names,
        triangle_counts=written_triangle_counts,
    )


def _reread_triangle_counts(
    destination: Path, names: tuple[str, ...]
) -> dict[str, int]:
    """Open the written file as a linked library and count what is in it."""
    import bpy

    try:
        with bpy.data.libraries.load(str(destination), link=True) as (
            data_from,
            data_to,
        ):
            held_names = tuple(data_from.objects)
            if set(held_names) == set(names):
                data_to.objects = list(names)
    except Exception as error:
        raise BlendSaveError(
            f"the written file {str(destination)!r} cannot be re-read: {error}"
        ) from error
    missing = sorted(set(names) - set(held_names))
    extra = sorted(set(held_names) - set(names))
    if missing or extra:
        raise BlendSaveError(
            f"the written .blend holds {sorted(held_names)}, expected exactly "
            f"{sorted(names)} (missing {missing}, unexpected {extra}; an "
            f"unexpected object is a parent or modifier target pulled in as "
            f"a dependency)"
        )
    library = next(
        (
            candidate
            for candidate in bpy.data.libraries
            if Path(bpy.path.abspath(candidate.filepath)).resolve()
            == destination.resolve()
        ),
        None,
    )
    if library is None:
        raise BlendSaveError(
            f"the re-read of {str(destination)!r} registered no library"
        )
    try:
        reread_objects = {
            reread_object.name: reread_object
            for reread_object in bpy.data.objects
            if reread_object.library == library
        }
        return {name: _triangle_count(reread_objects[name]) for name in names}
    finally:
        bpy.data.libraries.remove(library)
