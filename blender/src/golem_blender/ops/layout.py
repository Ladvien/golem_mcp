"""Lay several models out in a grid so each can be inspected side by side.

When a scene holds more than one model, the inspector's question is
"which of these is right?" and a stack of models at the origin answers
nothing. `grid_array` (`ops/arrays.py`) does not answer it either: it
bakes N COPIES into ONE mesh, so the copies share a material, a name and
a gate verdict. This op moves N separate models — a piece's objects
staying together — into one uniform grid, and reports where each landed.

FIVE DECISIONS, because each can be disagreed with:

1. GROUPING IS BY PIECE AND BY PREFIX. An item is a defined piece
   (`define_piece`), a `<Piece>__<Material>` prefix group, or a single
   object. Sanctuary's one-object-per-material convention is what makes
   the prefix rule safe: `Post__Wood` and `Post__Iron` are one post, and
   a shelf that split them would show two half-posts. PRECEDENCE is
   piece, then object (or its prefix), then view-layer siblings named
   `<name>__*`, then a missing name — in that order, because a DEFINED
   piece is the caller's explicit statement about what belongs together,
   and a convention cannot overrule it. Only LISTED objects join a
   prefix group: a listed `Post__Wood` does not silently drag in an
   unlisted `Post__Iron`.

2. NO ORIGIN MEANS "CLEAR OF EVERYTHING ELSE". Cell (0, 0) sits just
   past every other mesh on +X, centred on their Y span, grounded at
   z = 0. A caller who wants the grid somewhere specific names `origin_m`
   and gets exactly that, even if it overlaps — which is why the report
   carries `overlaps_with` rather than the op refusing.

3. ONE CELL SIZE FOR EVERY ITEM: the largest footprint plus the gap, on
   each axis. A grid whose cells hug their contents stops reading as a
   grid — the columns wander and the eye cannot compare two models. The
   cost is whitespace around small models, which is the point of a
   contact sheet.

4. +X IS A COLUMN, +Y IS A ROW, and items fill row-major from the
   origin. That is the kitbash shelf's own convention ("assembly offsets
   are always +X/+Y" in `kitbash/procedure.md`), so a shelf and a layout
   agree about which way the scene grows.

5. ONLY THE ROOTS MOVE, IN WORLD SPACE. A child keeps its offset from
   its parent because the parent carries it; moving both would double the
   offset. The move writes `matrix_world` rather than `.location` because
   `.location` is PARENT-RELATIVE — the trap `move_object_to` documents —
   and a piece member parented to an unlisted empty would otherwise land
   somewhere the arithmetic never asked for.

Arithmetic without bpy lives in `_grid_cells` and `_auto_origin_m`, so
`tests/pure` measures the grid without launching Blender.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from golem_blender.ops._contract import op

# The separator of the one-object-per-material convention
# (`Prop_Scarecrow__MI_WoodTrim`): everything before it is the piece.
PIECE_SEPARATOR = "__"
AXIS_COUNT = 3


# --- the arithmetic, with no bpy -----------------------------------------


def _grid_cells(
    footprints_m: Sequence[tuple[float, float]],
    gap_m: float,
    column_count: int | None,
    origin_m: tuple[float, float, float],
) -> tuple[int, int, tuple[float, float], tuple[tuple[float, float, float], ...]]:
    """(columns, rows, cell_m, cell_centres_m) for items laid row-major from origin_m.

    One cell size for every item: the widest footprint plus the gap on each
    axis (decision 3). Item `i` is column `i % columns` of row
    `i // columns`, and columns run along +X while rows run along +Y
    (decision 4).
    """
    footprints = tuple(footprints_m)
    if not footprints:
        raise ValueError("footprints_m is empty: a grid is at least one item")
    if gap_m < 0.0:
        raise ValueError(f"gap_m must be 0 or more, got {gap_m}")
    if column_count is not None and column_count < 1:
        raise ValueError(f"column_count must be 1 or more, got {column_count}")

    item_count = len(footprints)
    columns = (
        math.ceil(math.sqrt(item_count))
        if column_count is None
        else min(column_count, item_count)
    )
    rows = math.ceil(item_count / columns)
    cell_x_m = max(footprint[0] for footprint in footprints) + gap_m
    cell_y_m = max(footprint[1] for footprint in footprints) + gap_m

    origin_x_m, origin_y_m, origin_z_m = origin_m
    centres_m = tuple(
        (
            origin_x_m + (index % columns) * cell_x_m,
            origin_y_m + (index // columns) * cell_y_m,
            origin_z_m,
        )
        for index in range(item_count)
    )
    return columns, rows, (cell_x_m, cell_y_m), centres_m


def _auto_origin_m(
    others_bounds_m: tuple[list[float], list[float]] | None,
    cell_m: tuple[float, float],
    gap_m: float,
) -> tuple[float, float, float]:
    """Cell (0,0)'s centre: just past every other mesh on +X, or the world origin when there is none.

    Decision 2. Y is centred on the others' span so the grid sits beside
    them rather than beyond their corner, and z is 0 so the laid-out models
    are grounded.
    """
    if others_bounds_m is None:
        return (0.0, 0.0, 0.0)
    minimum, maximum = others_bounds_m
    return (
        maximum[0] + gap_m + cell_m[0] / 2.0,
        minimum[1] + cell_m[1] / 2.0,
        0.0,
    )


# --- the reports ---------------------------------------------------------


@dataclass(frozen=True)
class GridCell:
    """One laid-out item: its objects, its cell, how far it moved, where it ended up."""

    item_name: str
    object_names: tuple[str, ...]
    column: int
    row: int
    moved_m: tuple[float, float, float]
    # Re-measured AFTER the move, so the report shows what the scene holds
    # rather than what the arithmetic intended.
    bounds_min_m: tuple[float, float, float]
    bounds_max_m: tuple[float, float, float]


@dataclass(frozen=True)
class GridLayoutReport:
    """Where every model landed, the grid's shape, and anything it overlaps."""

    item_count: int
    column_count: int
    row_count: int
    cell_m: tuple[float, float]
    origin_m: tuple[float, float, float]
    cells: tuple[GridCell, ...]
    bounds_min_m: tuple[float, float, float]
    bounds_max_m: tuple[float, float, float]
    # NON-layout meshes whose box overlaps a cell's box: empty when the grid
    # stands clear, and the caller's answer when they forced `origin_m`.
    overlaps_with: tuple[str, ...]


# --- resolving the items -------------------------------------------------


def _checked_item_names(item_names) -> tuple[str, ...]:
    """The names in the order given, or the named error for a bad list.

    Order is kept — unlike a piece's set (which is sorted because every
    number it feeds is an order-free total), the order here IS the layout:
    the first name is cell (0, 0).
    """
    if isinstance(item_names, str):
        # TypeError, not ValueError: what is wrong is the TYPE. Same rule as
        # `ops.pieces._checked_names`, which refuses a str the same way.
        raise TypeError(
            f"item_names must be a list of names, got the string "
            f"{item_names!r} (one item is still one cell: pass [{item_names!r}])"
        )
    names = tuple(item_names)
    if not names:
        raise ValueError("item_names is empty: a grid is at least one item")
    for name in names:
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"item name {name!r} is not a non-empty string")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"item_names repeats {duplicates}; a repeated item would be "
            f"placed twice and the second cell would win"
        )
    return names


def _siblings_of(prefix: str) -> tuple[str, ...]:
    """View-layer objects named `<prefix>__*`, sorted by name."""
    import bpy

    return tuple(
        sorted(
            blender_object.name
            for blender_object in bpy.context.view_layer.objects
            if blender_object.name.startswith(f"{prefix}{PIECE_SEPARATOR}")
        )
    )


def _resolve_items(
    item_names: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(item_name, object_names) per item, in the order the items were given.

    Decision 1's precedence, one branch per rule, in this order: a defined
    piece, an object (or its prefix group), a bare prefix with `__*`
    siblings, else missing. Every missing name is collected so one call
    reports them all instead of the first.
    """
    import bpy

    from golem_blender.ops import pieces
    from golem_blender.ops._objects import UnknownObject

    present = {blender_object.name for blender_object in bpy.data.objects}
    # [item_name, object names]. A list of pairs rather than a dict because
    # the ORDER is the layout, and item names stay unique: the two ways an
    # item can be named (a piece, a prefix) collide loudly below instead of
    # one silently absorbing the other.
    items: list[list] = []
    piece_item_names: set[str] = set()
    missing: list[str] = []

    def item_named(item_name: str):
        return next((item for item in items if item[0] == item_name), None)

    for name in item_names:
        if name in pieces._PIECES:
            # `_piece_all_objects` raises PieceChangedError for a removed
            # member: that statement ("the piece changed") is the right one
            # here, so it propagates rather than being restated.
            if item_named(name) is not None:
                raise ValueError(
                    f"{name!r} is both a defined piece and a "
                    f"`<name>{PIECE_SEPARATOR}*` prefix group of the names "
                    f"already listed, so one of its objects would be laid out "
                    f"in two cells. Drop either the piece name or the "
                    f"{name}{PIECE_SEPARATOR}* names from item_names"
                )
            items.append(
                [
                    name,
                    [
                        blender_object.name
                        for blender_object in pieces._piece_all_objects(name)
                    ],
                ]
            )
            piece_item_names.add(name)
        elif name in present:
            key = name.split(PIECE_SEPARATOR, 1)[0] or name
            existing = item_named(key)
            if existing is None:
                items.append([key, [name]])
            elif key in piece_item_names:
                raise ValueError(
                    f"{name!r} is a member of the defined piece {key!r}, which "
                    f"is already an item: listing it again would lay one "
                    f"object out in two cells. Drop either {key!r} or "
                    f"{name!r} from item_names"
                )
            else:
                existing[1].append(name)
        else:
            siblings = _siblings_of(name)
            if siblings:
                items.append([name, list(siblings)])
            else:
                missing.append(name)

    if missing:
        raise UnknownObject(
            f"no object named {missing} in this scene, and no piece or "
            f"`<name>{PIECE_SEPARATOR}*` group of that name (present: "
            f"{sorted(present)}); nothing was moved"
        )

    claimed: dict[str, str] = {}
    for item_name, object_names in items:
        for object_name in object_names:
            earlier = claimed.get(object_name)
            if earlier is not None and earlier != item_name:
                raise ValueError(
                    f"{object_name!r} lands in two items, {earlier!r} and "
                    f"{item_name!r}: a model cannot be laid out twice"
                )
            claimed[object_name] = item_name

    return tuple((item_name, tuple(object_names)) for item_name, object_names in items)


def _item_objects(object_names: tuple[str, ...]):
    """The `bpy.data.objects` entries of one item, checked linked into the scene."""
    import bpy

    objects = []
    for object_name in object_names:
        blender_object = bpy.data.objects[object_name]
        if blender_object.name not in bpy.context.view_layer.objects:
            raise ValueError(
                f"{object_name!r} is not linked into the scene; call "
                f"link_into_scene first — an unlinked object is invisible to "
                f"inspection, so laying it out would move nothing visible"
            )
        objects.append(blender_object)
    return objects


def _roots(blender_objects):
    """The members with no ancestor inside the item: moving these moves the item."""
    member_names = {blender_object.name for blender_object in blender_objects}
    roots = []
    for blender_object in blender_objects:
        ancestor = blender_object.parent
        while ancestor is not None and ancestor.name not in member_names:
            ancestor = ancestor.parent
        if ancestor is None:
            roots.append(blender_object)
    return roots


def _box_overlaps(first, second) -> bool:
    """Do two (minimum, maximum) boxes share volume, beyond face contact?"""
    from golem_blender.ops.arrays import TOUCHING_TOLERANCE_M

    return all(
        first[0][axis] < second[1][axis] - TOUCHING_TOLERANCE_M
        and second[0][axis] < first[1][axis] - TOUCHING_TOLERANCE_M
        for axis in range(AXIS_COUNT)
    )


# --- the op --------------------------------------------------------------


@op()
def lay_out_grid(
    item_names: list[str],
    gap_m: float = 0.5,
    column_count: int | None = None,
    origin_m: tuple[float, float, float] | None = None,
) -> GridLayoutReport:
    """Lay several models out side by side in a grid for inspection; a piece's objects share one cell.

    Each item moves as ONE model: its footprint centre goes to its cell's
    centre and its base to the cell's z, so a grid from the default origin
    is grounded at 0 and clear of every other mesh on +X. Nothing moves
    until every name, link and conflict check has passed, so a refusal
    leaves the scene exactly as it was.

    Name an item by a defined piece, by a `<Piece>__<Material>` prefix, by
    one object, or by a bare prefix whose `__*` siblings exist — in that
    order of precedence.
    """
    import bpy
    from mathutils import Vector

    from golem_blender.ops.transforms import _refresh_dependency_graph, _world_bounds_m

    items = _resolve_items(_checked_item_names(item_names))
    # Every name, link and conflict is checked before this line: below it,
    # the scene changes.
    resolved = [(item_name, _item_objects(names)) for item_name, names in items]

    item_meshes = []
    for item_name, blender_objects in resolved:
        mesh_objects = [
            blender_object
            for blender_object in blender_objects
            if blender_object.type == "MESH"
        ]
        if not mesh_objects:
            raise ValueError(
                f"item {item_name!r} has no MESH members (its objects are "
                f"{[blender_object.type for blender_object in blender_objects]}), "
                f"so there is nothing to lay out"
            )
        item_meshes.append(mesh_objects)

    claimed = {
        blender_object.name
        for _, blender_objects in resolved
        for blender_object in blender_objects
    }
    others = [
        blender_object
        for blender_object in bpy.context.view_layer.objects
        if blender_object.type == "MESH" and blender_object.name not in claimed
    ]
    # The others do not move, so their boxes are read once: the overlap
    # report needs per-object boxes, and the default origin needs their
    # joint one.
    other_boxes = {
        blender_object.name: _world_bounds_m([blender_object])
        for blender_object in others
    }
    others_bounds = _world_bounds_m(others) if others else None

    item_bounds = [_world_bounds_m(mesh_objects) for mesh_objects in item_meshes]
    footprints_m = [
        (maximum[0] - minimum[0], maximum[1] - minimum[1])
        for minimum, maximum in item_bounds
    ]
    if origin_m is not None:
        grid_origin_m = tuple(origin_m)
    else:
        grid_origin_m = _auto_origin_m(
            others_bounds,
            (
                max(footprint[0] for footprint in footprints_m) + gap_m,
                max(footprint[1] for footprint in footprints_m) + gap_m,
            ),
            gap_m,
        )

    columns, rows, cell_m, centres_m = _grid_cells(
        footprints_m, gap_m, column_count, grid_origin_m
    )

    _refresh_dependency_graph()
    placements = []
    for index, (item_name, blender_objects) in enumerate(resolved):
        minimum, maximum = item_bounds[index]
        centre_m = centres_m[index]
        delta_m = (
            centre_m[0] - (minimum[0] + maximum[0]) / 2.0,
            centre_m[1] - (minimum[1] + maximum[1]) / 2.0,
            centre_m[2] - minimum[2],
        )
        # Only the ROOTS move (decision 5): a child's offset from its parent
        # is the parent's to carry.
        for blender_object in _roots(blender_objects):
            world_matrix = blender_object.matrix_world.copy()
            world_matrix.translation = world_matrix.translation + Vector(delta_m)
            blender_object.matrix_world = world_matrix
        placements.append((item_name, blender_objects, delta_m, index))
    _refresh_dependency_graph()

    # Re-measured, so the report shows the scene rather than the arithmetic.
    cells = []
    moved_bounds = []
    for item_name, blender_objects, delta_m, index in placements:
        minimum, maximum = _world_bounds_m(item_meshes[index])
        moved_bounds.append((minimum, maximum))
        cells.append(
            GridCell(
                item_name=item_name,
                object_names=tuple(
                    sorted(blender_object.name for blender_object in blender_objects)
                ),
                column=index % columns,
                row=index // columns,
                moved_m=delta_m,
                bounds_min_m=tuple(minimum),
                bounds_max_m=tuple(maximum),
            )
        )

    overlaps_with = sorted(
        other_name
        for other_name, other_box in other_boxes.items()
        if any(_box_overlaps(other_box, moved_box) for moved_box in moved_bounds)
    )
    return GridLayoutReport(
        item_count=len(cells),
        column_count=columns,
        row_count=rows,
        cell_m=cell_m,
        origin_m=grid_origin_m,
        cells=tuple(cells),
        bounds_min_m=tuple(
            min(minimum[axis] for minimum, _ in moved_bounds)
            for axis in range(AXIS_COUNT)
        ),
        bounds_max_m=tuple(
            max(maximum[axis] for _, maximum in moved_bounds)
            for axis in range(AXIS_COUNT)
        ),
        overlaps_with=tuple(overlaps_with),
    )
