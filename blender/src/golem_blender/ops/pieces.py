"""A piece: several objects that are ONE asset, measured as one.

Sanctuary's convention — which golem's own output encourages — is one
object per material, named `<Piece>__<Material>`, so a scarecrow comes out
as `Prop_Scarecrow__Crop_Grain` plus `Prop_Scarecrow__MI_WoodTrim`. Every
downstream operation was per-object (the gate measures one object, the
analyzer's counts are per object), so the triangle count the asset was
judged on had to be re-summed by hand after every call — and in the
22-piece run it was recomputed outside golem entirely, by a script that
opened the written `.glb` files (issue #17).

So this module holds a piece: a NAMED SET of object names, kept for the
session, and one report that measures the set as an asset.

FOUR DECISIONS, because each can be disagreed with:

1. DEFINING THE SAME NAME TWICE UPDATES IT. An update is the ONLY way to
   repair a piece after a member is removed (there is no unregister op), so
   it is always allowed and always replaces the stored set. It cannot be
   the silent smaller total the issue forbids: the caller names every
   member of the new set explicitly, so nothing shrinks behind its back —
   the loudness lives on the READS (decision 2), which is where a stale set
   would otherwise be measured as if it were whole.

2. A REMOVED MEMBER IS LOUD, NEVER A SMALLER TOTAL. There is no scene
   hook that could unregister a member, so every read of a piece resolves
   its names against `bpy.data.objects` and raises `PieceChangedError`
   naming the piece and the missing members. `piece_report`,
   `save_blend(piece=...)` and `snap_base_to_ground(piece=...)` all go
   through that one resolution, so a vanished part cannot be measured,
   saved or grounded out of any of them.

3. THE SET IS STORED SORTED BY NAME, so order cannot leak into a total,
   into the extents, or into the file that is written. The issue's
   condition 5 asks only that the totals match either way; a canonical
   order makes the whole report identical, which is the stronger and the
   simpler thing to reason about.

4. THE EXTENTS ARE MEASURED ON THE PARTS THAT HAVE GEOMETRY. A piece may
   legitimately hold an armature or an empty beside its meshes (a rigged
   piece), and their bounding boxes are not the asset's shape — an
   armature sitting at the origin would drag the piece's lowest point to
   0 and make a floating asset read as grounded. So the joint box comes
   from the MESH parts, and a piece with no mesh parts reports zero
   extents. Triangles are counted the same way: the analyzer's own count
   for a mesh, zero for anything else.

The registry is SESSION state (`bpy.data` is not involved): it holds names,
not datablocks, which is why a removed object surfaces as decision 2 rather
than as a stale reference. It is not cleared by `reset_scene` — a wipe
leaves the names unresolvable, which is precisely loud.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender.ops._contract import op

# name -> the object names of that piece, sorted. Module-level because a
# piece outlives one call: that is the whole point of defining it.
_PIECES: dict[str, tuple[str, ...]] = {}


class UnknownPiece(LookupError):
    """No piece of that name was defined in this session."""


class PieceChangedError(LookupError):
    """A member of the piece is gone, so the piece is no longer what it was.

    A LookupError because what failed is a name lookup, and because
    `ops._objects.object_by_name` raises one too: a caller catching
    LookupError handles both without knowing which layer noticed.
    """


@dataclass(frozen=True)
class PiecePart:
    """One member of a piece, with the numbers the piece's total is built from."""

    name: str
    triangles: int
    material_names: tuple[str, ...]


@dataclass(frozen=True)
class PieceReport:
    """What a piece is, measured as one asset.

    `object_name` is the PIECE's name (the gate's target field, empty when
    a bare list was measured and nothing was ever defined), and `parts`
    carries the per-object numbers the total is the sum of — so the
    bookkeeping that used to happen outside golem has one home.
    """

    object_name: str
    objects: tuple[str, ...]
    triangles_total: int
    dimensions_m: tuple[float, float, float]
    # The lowest point of the piece's GEOMETRY in world z. A piece at or
    # above 0 reads 0 or more; `snap_base_to_ground(piece=...)` moves every
    # part so this reads exactly 0.
    lowest_point_m: float
    parts: tuple[PiecePart, ...]


def _checked_names(object_names) -> tuple[str, ...]:
    """The names as a sorted tuple, or the named error for a bad list."""
    if isinstance(object_names, str):
        # TypeError, not ValueError: what is wrong is the TYPE. Same rule as
        # `ops._objects.object_by_name`, which refuses a str parameter given
        # something that is not a name.
        raise TypeError(
            f"object_names must be a list of names, got the string "
            f"{object_names!r} (one object is still one piece: pass [{object_names!r}])"
        )
    names = tuple(object_names)
    if not names:
        raise ValueError("object_names is empty: a piece is at least one object")
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"object name {name!r} is not a non-empty string")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"object_names repeats {duplicates}; a repeated part would be counted twice"
        )
    return tuple(sorted(names))


def _resolved_names(piece_name: str) -> tuple[str, ...]:
    """The stored names of a defined piece, checked present RIGHT NOW.

    Decision 2: one resolution, used by every reader, so no entry point can
    report a smaller total than the piece was defined with.
    """
    recorded = _PIECES.get(piece_name)
    if recorded is None:
        known = sorted(_PIECES)
        raise UnknownPiece(
            f"no piece named {piece_name!r} was defined in this session "
            f"(defined: {known}). Call define_piece first."
        )

    import bpy

    missing = [name for name in recorded if name not in bpy.data.objects]
    if missing:
        raise PieceChangedError(
            f"piece {piece_name!r} no longer names {missing}: it was defined "
            f"as {list(recorded)} and {missing} has since been removed. "
            f"Re-define the piece (define_piece({piece_name!r}, ...)) before "
            f"measuring, saving or snapping it — a smaller total would be a "
            f"lie about the asset."
        )
    return recorded


def _piece_object_names(piece_name: str) -> tuple[str, ...]:
    """A defined piece's object names, for a caller outside this module."""
    return _resolved_names(piece_name)


def _piece_all_objects(piece_name: str):
    """The `bpy.data.objects` entries of a defined piece, in stored order."""
    import bpy

    return [bpy.data.objects[name] for name in _resolved_names(piece_name)]


def _piece_mesh_objects(piece_name: str):
    """A defined piece's MESH members, the only ones with geometry (decision 4).

    The one place the piece's shape is decided, shared by the measurement
    and by `snap_base_to_ground(piece=...)`: if they disagreed, a snap
    would put the piece's lowest point where the report does not read it.
    """
    return [
        blender_object
        for blender_object in _piece_all_objects(piece_name)
        if blender_object.type == "MESH"
    ]


def _measure(piece_name: str, names: tuple[str, ...]) -> PieceReport:
    """Measure the set: per-part counts, the total, and the joint box.

    A name with no object is refused HERE, for the one caller that did not
    resolve it first (a bare list handed to `piece_report`); a defined piece
    never gets this far with a missing member, because `_resolved_names`
    raises `PieceChangedError` — a different statement ("the piece changed")
    about a different situation.
    """
    import bpy

    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.ops._objects import UnknownObject
    from golem_blender.ops.transforms import _world_bounds_m

    # A budget that ALLOWS UV overlaps: the overlap count is a pairwise
    # test over every UV triangle (30.2 s measured on 131k triangles) and
    # a piece's triangle total does not need it.
    measurement_budget = MeshBudget()
    parts: list[PiecePart] = []
    mesh_objects = []
    for name in names:
        blender_object = bpy.data.objects.get(name)
        if blender_object is None:
            raise UnknownObject(
                f"no object named {name!r} in bpy.data.objects (present: "
                f"{sorted(candidate.name for candidate in bpy.data.objects)})"
                + (
                    f", so piece {piece_name!r} cannot be measured"
                    if piece_name
                    else ""
                )
            )
        if blender_object.type == "MESH":
            mesh_objects.append(blender_object)
            # The analyzer's OWN count, so a piece's total and a standalone
            # reading of the same object can never disagree.
            triangle_count = analyze_object(
                blender_object, measurement_budget
            ).triangle_count
        else:
            # An armature or an empty beside the meshes is a legal member
            # of a rigged piece and contributes no triangles (decision 4).
            triangle_count = 0
        parts.append(
            PiecePart(
                name=blender_object.name,
                triangles=triangle_count,
                material_names=tuple(
                    material.name
                    for material in getattr(blender_object.data, "materials", ())
                    if material is not None
                ),
            )
        )

    if mesh_objects:
        minimum, maximum = _world_bounds_m(mesh_objects)
        dimensions_m = (
            maximum[0] - minimum[0],
            maximum[1] - minimum[1],
            maximum[2] - minimum[2],
        )
        lowest_point_m = minimum[2]
    else:
        dimensions_m = (0.0, 0.0, 0.0)
        lowest_point_m = 0.0

    return PieceReport(
        object_name=piece_name,
        objects=names,
        triangles_total=sum(part.triangles for part in parts),
        dimensions_m=dimensions_m,
        lowest_point_m=lowest_point_m,
        parts=tuple(parts),
    )


def define_piece(name: str, object_names: list[str]) -> PieceReport:
    """Define a named set of objects as one piece for this session; reports it measured.

    Defining the same name twice UPDATES it — that is the only way to
    repair a piece after one of its members was removed, since there is no
    unregister op. The new set is named explicitly by the caller, so an
    update can never shrink a piece behind its back; a STALE set is caught
    by every read instead (decision 2), which raises PieceChangedError.
    The stored set is sorted, so the order the names were given in changes
    nothing in the report.
    """
    import bpy

    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"a piece name must be a non-empty string, got {name!r}")
    names = _checked_names(object_names)
    missing = [part_name for part_name in names if part_name not in bpy.data.objects]
    if missing:
        from golem_blender.ops._objects import UnknownObject

        raise UnknownObject(
            f"piece {name!r} names {missing}, which no object in this scene "
            f"has (present: {sorted(blender_object.name for blender_object in bpy.data.objects)})"
        )
    _PIECES[name] = names
    return _measure(name, names)


@op(reads_only=True)
def piece_report(name_or_objects: str | list[str]) -> PieceReport:
    """Report a named piece, or a bare list of objects, as one asset; reads only.

    A named piece is resolved against the scene, so a member removed after
    the piece was defined raises PieceChangedError naming it rather than
    reporting a smaller total. A bare list is measured as given and carries
    no name; it is not registered.
    """
    if isinstance(name_or_objects, str):
        return _measure(name_or_objects, _resolved_names(name_or_objects))
    # A bare list was never registered, so it has no stored set to be stale
    # against: `_measure` refuses a name that has no object, which is the
    # right statement for a list the caller wrote out itself.
    return _measure("", _checked_names(name_or_objects))
