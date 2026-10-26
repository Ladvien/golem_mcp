"""Coplanar faces that can z-fight, in the engine's own depth resolution.

The measurement is `analyze/coplanar.py` (pure arithmetic); this module is the
half that reads a scene, decides what a pair MEANS there, and moves the smaller
side when asked to fix it.

Three things are this module's own decisions, and each is stated once:

1. **A report runs the detector's controls before it measures anything.** Flush
   quads must pair and a 5 mm gap must not. A detector that fails its own
   controls reports NOTHING and says so (`CoplanarSelfTestFailed`): zero pairs
   from a broken detector and zero pairs from a clean asset look identical, and
   only one of them means the asset is fine.

2. **Which side moves.** Of the two sides of a coplanar group, the one with less
   coplanar AREA moves outward along its own normal by 2 x the tolerance. Two
   sides each moving a millimetre apart is a visible change to a modelled
   junction; moving the smaller side twice is the same clearance with half as
   much of the asset disturbed.

3. **`declare_flush` is intent, and intent is not geometry.** Two parts whose
   contact is meant (a trim laid on a plank) report the same geometry as a
   defect; the declaration is what tells them apart, and it is the ONLY thing
   that removes a row from `flicker_count`. The row keeps its geometry-derived
   `kind` and carries the reason, so a reader still sees what the geometry does.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from golem_blender.analyze.coplanar import (
    DEFAULT_DEPTH_BITS,
    DEFAULT_FAR_M,
    DEFAULT_MINIMUM_OVERLAP_M2,
    DEFAULT_NEAR_M,
    DEFAULT_NORMAL_TOLERANCE_DEG,
    DEFAULT_TOLERANCE_M,
    FACING_MINIMUM_DOT,
    KINDS,
    VISIBILITY_OFFSET_M,
    SoupTriangle,
    classify,
    control_soups,
    coplanar_triangle_pairs,
    depth_quantum_m,
)
from golem_blender.analyze.view_geometry import (
    ISO_PITCH_DEG,
    ISO_YAWS_DEG,
    TOP_VIEW_LABEL,
    view_direction,
    view_label,
)
from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName, UnknownObject
from golem_blender.ops._targets import resolve_mesh_targets

# The report pages its rows the way `assembly_report` pages its intersections:
# a defect that repeats a thousand times is unreadable in one answer, and the
# COUNT is what a caller decides on.
MAXIMUM_PAIR_ROWS = 40

# A declared contact, keyed by the unordered pair of object names. Re-declaring
# replaces the reason, so a correction is one call.
_DECLARED_FLUSH: dict[frozenset[str], str] = {}

# Floating-point keys for the visibility memo and the fix grouping: a millimetre
# and 0.01 of a unit normal are both far under any modelling tolerance, and two
# pairs agreeing to those places are the same place on the same plane.
_POSITION_KEY_DECIMALS = 3
_NORMAL_KEY_DECIMALS = 2
_PLANE_KEY_DECIMALS = 4
# The move is twice the tolerance, so a face 1 mm flush becomes 2 mm apart: two
# depth quanta of the engine's buffer, the point at which the depth test
# resolves the pair the same way every frame.
MOVE_TOLERANCE_FACTOR = 2.0


@dataclass(frozen=True)
class CoplanarSettings:
    """How coplanar faces are detected and which views count as seeing them."""

    tolerance_m: float = DEFAULT_TOLERANCE_M
    normal_tolerance_deg: float = DEFAULT_NORMAL_TOLERANCE_DEG
    minimum_overlap_m2: float = DEFAULT_MINIMUM_OVERLAP_M2
    view_yaws_deg: tuple[float, ...] = ISO_YAWS_DEG
    view_pitch_deg: float = ISO_PITCH_DEG
    include_top_view: bool = True
    near_m: float = DEFAULT_NEAR_M
    far_m: float = DEFAULT_FAR_M
    depth_bits: int = DEFAULT_DEPTH_BITS
    same_material: Literal["ignore", "report"] = "ignore"


@dataclass(frozen=True)
class CoplanarPair:
    """One coplanar pair, what its overlap measures, and what that means."""

    first_object_name: str
    first_material: str
    first_face_index: int
    second_object_name: str
    second_material: str
    second_face_index: int
    plane_gap_m: float
    plane_gap_quanta: float
    overlap_m2: float
    overlap_polygon_m: tuple[tuple[float, float, float], ...]
    normal: tuple[float, float, float]
    at_m: tuple[float, float, float]
    kind: str  # one of coplanar.KINDS
    visible_from: tuple[str, ...]  # the view labels whose ray escaped
    declared_reason: str = ""


@dataclass(frozen=True)
class CoplanarFix:
    """A coplanar face patch to push out, and how far."""

    object_name: str
    material: str
    face_indices: tuple[int, ...]
    normal: tuple[float, float, float]
    move_m: float


@dataclass(frozen=True)
class CoplanarReport:
    """What the target's coplanar faces do, and one move per flickering patch."""

    target: str
    objects: tuple[str, ...]
    pair_count: int
    flicker_count: int
    counts_by_kind: tuple[tuple[str, int], ...]  # every kind in KINDS order
    pairs: tuple[CoplanarPair, ...]
    pair_offset: int
    fixes: tuple[CoplanarFix, ...]
    control_flush_seen: bool
    control_gap_silent: bool
    depth_quantum_m: float
    tolerance_m: float


@dataclass(frozen=True)
class CoplanarFixReport:
    """What the fix moved, and what the target measures now."""

    target: str
    flicker_before: int
    flicker_after: int
    moved: tuple[CoplanarFix, ...]
    moved_vertex_count: int
    report_after: CoplanarReport


@dataclass(frozen=True)
class CoplanarSelection:
    """The faces selected for a pair's two sides, and where the view was put."""

    target: str
    flicker_count: int
    selected: tuple[tuple[str, tuple[int, ...]], ...]
    viewport: str


class CoplanarSelfTestFailed(RuntimeError):
    """The detector did not recognise its own controls, so its report means nothing."""


def _face_records(objects):
    """(soup triangles, owner names) of the objects' evaluated world geometry.

    The owner table is the object ORDER, so a soup triangle's `owner` indexes
    `owner_names`. The material comes from the polygon's slot, read through the
    OBJECT's slots (the evaluated mesh has none of its own); an empty slot is ""
    because a face with no material renders as the default grey and must not be
    mistaken for a named one.
    """
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    soup: list[SoupTriangle] = []
    owner_names: list[str] = []
    for owner, blender_object in enumerate(objects):
        owner_names.append(blender_object.name)
        evaluated = blender_object.evaluated_get(dependency_graph)
        mesh = evaluated.to_mesh()
        try:
            world_matrix = blender_object.matrix_world
            world_normal_matrix = world_matrix.to_3x3()
            vertices = [world_matrix @ vertex.co for vertex in mesh.vertices]
            mesh.calc_loop_triangles()
            slots = blender_object.material_slots
            material_of_slot = [
                slot.material.name if slot.material is not None else ""
                for slot in slots
            ]
            for loop_triangle in mesh.loop_triangles:
                polygon_index = loop_triangle.polygon_index
                slot_index = mesh.polygons[polygon_index].material_index
                material_name = (
                    material_of_slot[slot_index]
                    if 0 <= slot_index < len(material_of_slot)
                    else ""
                )
                corners = tuple(
                    tuple(vertices[index]) for index in loop_triangle.vertices
                )
                # The WORLD normal, not the local one: a rotated part's faces
                # must group with the faces they actually lie against.
                normal = (world_normal_matrix @ loop_triangle.normal).normalized()
                soup.append(
                    SoupTriangle(
                        corners=corners,
                        normal=(normal.x, normal.y, normal.z),
                        owner=owner,
                        face_index=polygon_index,
                        material=material_name,
                    )
                )
        finally:
            evaluated.to_mesh_clear()
    return soup, owner_names


def _self_test(settings: CoplanarSettings) -> tuple[bool, bool]:
    """(flush seen, gap silent) from the detector's own controls.

    The flush control's VISIBILITY is checked too, against an empty occluder
    index: if the detector cannot see its own flush quads from above, its
    visibility half is broken as well and every row it produces would read
    "buried" for no reason.
    """
    from golem_blender.analyze.occluders import OccluderIndex

    flush, gap = control_soups()
    arguments = (
        settings.tolerance_m,
        settings.normal_tolerance_deg,
        settings.minimum_overlap_m2,
    )
    flush_pairs = coplanar_triangle_pairs(flush, *arguments)
    gap_pairs = coplanar_triangle_pairs(gap, *arguments)
    flush_seen = False
    if flush_pairs:
        first = flush[flush_pairs[0].first]
        start = tuple(
            point + VISIBILITY_OFFSET_M * normal
            for point, normal in zip(flush_pairs[0].centroid, first.normal)
        )
        flush_seen = not OccluderIndex([]).cast(start, (0.0, 0.0, 1.0), 1)
    return flush_seen, not gap_pairs


def _view_directions(
    settings: CoplanarSettings,
) -> list[tuple[str, tuple[float, float, float]]]:
    """Every labelled direction the detector calls a view, yaws first then top."""
    views = [
        (view_label(yaw_deg), view_direction(yaw_deg, settings.view_pitch_deg))
        for yaw_deg in settings.view_yaws_deg
    ]
    if settings.include_top_view:
        views.append((TOP_VIEW_LABEL, (0.0, 0.0, 1.0)))
    return views


def _facing(normal, direction) -> float:
    return sum(normal[axis] * direction[axis] for axis in range(3))


def _visible_from(normal, start, index, views) -> tuple[str, ...]:
    """The view labels that both face the pair and reach it unobstructed.

    A view that FACES the pair but is blocked does not count: the pair is then
    buried from that side, and saying "visible from yaw_45" because the normal
    happens to point that way would be a lie about the render.
    """
    labels = []
    for label, direction in views:
        if _facing(normal, direction) <= FACING_MINIMUM_DOT:
            continue
        if not index.cast(start, direction, 1):
            labels.append(label)
    return tuple(labels)


def _coplanar_patch(
    objects, owner, material, plane_normal, plane_offset, seeds, settings
):
    """(face indices, world area m^2) of one side's coplanar plate around `seeds`.

    Seeds are the side's PAIRED faces; the flood grows from them over faces of
    the same object and material that share a vertex AND lie in the plane
    (within the tolerance, facing the same way). Plate, not triangle: two
    coplanar faces meeting along an edge are ONE plate and moving half of it
    would tear the seam the modeller built. Starting from the paired faces is
    what keeps a separate island of the same material in the same plane — the
    crate's four corner brackets, each its own island — out of the move; moving
    only "the biggest island in the plane" left 40 of the shipped crate's 52
    pairs still flush, measured 2026-11-02.
    """
    import bpy

    bpy.context.view_layer.update()
    blender_object = objects[owner]
    mesh = blender_object.data
    world_matrix = blender_object.matrix_world
    world_normal_matrix = world_matrix.to_3x3()
    cos_limit = math.cos(math.radians(settings.normal_tolerance_deg))
    normal_vector = __import__("mathutils").Vector(plane_normal)
    slots = blender_object.material_slots
    candidates: set[int] = set()
    for polygon in mesh.polygons:
        slot = polygon.material_index
        face_material = (
            slots[slot].material.name
            if slot < len(slots) and slots[slot].material is not None
            else ""
        )
        if face_material != material:
            continue
        face_normal = (world_normal_matrix @ polygon.normal).normalized()
        if face_normal.dot(normal_vector) < cos_limit:
            continue
        centre = world_matrix @ polygon.center
        if abs(normal_vector.dot(centre) - plane_offset) > settings.tolerance_m:
            continue
        candidates.add(polygon.index)
    starting = sorted(candidates.intersection(seeds))
    if not starting:
        return (), 0.0

    by_vertex: dict[int, list[int]] = {}
    for polygon_index in candidates:
        for vertex_index in mesh.polygons[polygon_index].vertices:
            by_vertex.setdefault(vertex_index, []).append(polygon_index)
    patch = list(starting)
    seen = set(starting)
    cursor = 0
    while cursor < len(patch):
        current = patch[cursor]
        cursor += 1
        for vertex_index in mesh.polygons[current].vertices:
            for neighbour in by_vertex[vertex_index]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    patch.append(neighbour)
    # `polygon.area` is LOCAL area; a scaled object's world area differs, and
    # the side that moves is chosen by world area.
    determinant = abs(world_normal_matrix.determinant())
    world_scale = math.sqrt(determinant) if determinant else 1.0
    area = sum(mesh.polygons[index].area for index in patch) * world_scale
    return tuple(sorted(patch)), area


def _flicker_rows(pairs) -> list[CoplanarPair]:
    """The rows that count as an undeclared flicker: the ones a fix acts on."""
    return [
        pair for pair in pairs if pair.kind == "flicker" and not pair.declared_reason
    ]


def _fixes_for(
    flicker_pairs, objects, owner_names, settings
) -> tuple[CoplanarFix, ...]:
    """One movement per flickering coplanar plate, smaller side first.

    Rows are grouped by (side A, side B, plane), then EACH side's plate is
    measured and the smaller one moves. Fixes naming the same object, material
    and normal merge, so a plate with forty flickering triangles gets one move
    rather than forty.
    """
    groups: dict[tuple, dict] = {}
    for pair in flicker_pairs:
        plane_offset = sum(pair.normal[axis] * pair.at_m[axis] for axis in range(3))
        key = (
            pair.first_object_name,
            pair.first_material,
            pair.second_object_name,
            pair.second_material,
            tuple(round(component, _NORMAL_KEY_DECIMALS) for component in pair.normal),
            round(plane_offset, _PLANE_KEY_DECIMALS),
        )
        group = groups.setdefault(
            key, {"normal": pair.normal, "plane_offset": plane_offset, "sides": {}}
        )
        group["sides"].setdefault(
            (pair.first_object_name, pair.first_material), set()
        ).add(pair.first_face_index)
        group["sides"].setdefault(
            (pair.second_object_name, pair.second_material), set()
        ).add(pair.second_face_index)

    index_of = {name: position for position, name in enumerate(owner_names)}
    merged: dict[tuple, dict] = {}
    for group in groups.values():
        normal = group["normal"]
        plane_offset = group["plane_offset"]
        sides = []
        for (object_name, material), seeds in group["sides"].items():
            owner = index_of[object_name]
            face_indices, area = _coplanar_patch(
                objects, owner, material, normal, plane_offset, seeds, settings
            )
            if not face_indices:
                face_indices, area = tuple(sorted(seeds)), 0.0
            sides.append((object_name, material, face_indices, area))
        if len(sides) < 2:
            continue
        # Smallest plate moves. A tie is broken by the later-sorting
        # (object, material) so the choice is deterministic rather than
        # whichever side the pair loop happened to see first.
        sides.sort(key=lambda side: (side[3], side[0], side[1]))
        object_name, material = sides[0][0], sides[0][1]
        merge_key = (
            object_name,
            material,
            tuple(round(component, _NORMAL_KEY_DECIMALS) for component in normal),
        )
        record = merged.setdefault(merge_key, {"normal": normal, "faces": set()})
        record["faces"].update(sides[0][2])

    fixes = [
        CoplanarFix(
            object_name=object_name,
            material=material,
            face_indices=tuple(sorted(record["faces"])),
            normal=tuple(record["normal"]),
            move_m=MOVE_TOLERANCE_FACTOR * settings.tolerance_m,
        )
        for (object_name, material, _key), record in merged.items()
    ]
    fixes.sort(key=lambda fix: (fix.object_name, fix.material, fix.face_indices))
    return tuple(fixes)


def _measure(
    target: str | list[str], settings: CoplanarSettings, pair_offset: int = 0
) -> tuple[CoplanarReport, list[CoplanarPair]]:
    """(the report, its FULL row list) for the target.

    The second half is returned because the report pages its rows and the fix
    must act on every flickering face, not on the first page of them.
    """
    from golem_blender.analyze.occluders import OccluderIndex

    if pair_offset < 0:
        raise ValueError(
            f"pair_offset must be 0 or more, got {pair_offset!r}; a negative "
            f"offset would read from the end of the list"
        )
    flush_seen, gap_silent = _self_test(settings)
    if not (flush_seen and gap_silent):
        raise CoplanarSelfTestFailed(
            f"coplanar self-test failed: flush pair seen={flush_seen}, 5 mm gap "
            f"silent={gap_silent}; no pairs are reported from a detector that "
            f"fails its own controls"
        )
    label, objects = resolve_mesh_targets(target)
    if not objects:
        raise UnknownObject(f"target {target!r} resolved to no MESH objects")
    soup, owner_names = _face_records(objects)
    index = OccluderIndex(objects)
    views = _view_directions(settings)
    quantum = depth_quantum_m(settings.near_m, settings.far_m, settings.depth_bits)
    found = coplanar_triangle_pairs(
        soup,
        settings.tolerance_m,
        settings.normal_tolerance_deg,
        settings.minimum_overlap_m2,
    )

    memo: dict[tuple, tuple[str, ...]] = {}
    pairs: list[CoplanarPair] = []
    for pair in found:
        first = soup[pair.first]
        second = soup[pair.second]
        start = tuple(
            point + VISIBILITY_OFFSET_M * normal
            for point, normal in zip(pair.centroid, first.normal)
        )
        key = (
            *(
                round(coordinate, _POSITION_KEY_DECIMALS)
                for coordinate in pair.centroid
            ),
            *(round(component, _NORMAL_KEY_DECIMALS) for component in first.normal),
        )
        if key not in memo:
            memo[key] = _visible_from(first.normal, start, index, views)
        visible_from = memo[key]
        facing_any = any(
            _facing(first.normal, direction) > FACING_MINIMUM_DOT
            for _label, direction in views
        )
        kinds = classify(
            same_material_ignored=(
                settings.same_material == "ignore" and first.material == second.material
            ),
            facing_any=facing_any,
            visible=bool(visible_from),
            quanta=pair.separation_m / quantum if quantum else 0.0,
        )
        first_name = owner_names[first.owner]
        pairs.append(
            CoplanarPair(
                first_object_name=first_name,
                first_material=first.material,
                first_face_index=first.face_index,
                second_object_name=owner_names[second.owner],
                second_material=second.material,
                second_face_index=second.face_index,
                plane_gap_m=pair.separation_m,
                plane_gap_quanta=pair.separation_m / quantum if quantum else 0.0,
                overlap_m2=pair.overlap_m2,
                overlap_polygon_m=pair.polygon,
                normal=first.normal,
                at_m=pair.centroid,
                kind=kinds,
                visible_from=visible_from,
                declared_reason=_DECLARED_FLUSH.get(
                    frozenset((first_name, owner_names[second.owner])), ""
                ),
            )
        )

    # Order: kind, then a declared flicker after every undeclared one, then the
    # biggest overlap, then names — so a page of rows is the worst of them.
    pairs.sort(
        key=lambda pair: (
            KINDS.index(pair.kind),
            1 if pair.declared_reason else 0,
            -pair.overlap_m2,
            pair.first_object_name,
            pair.second_object_name,
            pair.first_face_index,
            pair.second_face_index,
        )
    )
    report = CoplanarReport(
        target=label,
        objects=tuple(owner_names),
        pair_count=len(pairs),
        flicker_count=len(_flicker_rows(pairs)),
        counts_by_kind=tuple(
            (kind, sum(1 for pair in pairs if pair.kind == kind)) for kind in KINDS
        ),
        pairs=tuple(pairs[pair_offset : pair_offset + MAXIMUM_PAIR_ROWS]),
        pair_offset=pair_offset,
        fixes=_fixes_for(_flicker_rows(pairs), objects, owner_names, settings),
        control_flush_seen=flush_seen,
        control_gap_silent=gap_silent,
        depth_quantum_m=quantum,
        tolerance_m=settings.tolerance_m,
    )
    return report, pairs


def _require_object_mode(action: str) -> None:
    """A face index means an OBJECT-mode polygon; refuse to guess in Edit mode."""
    import bpy

    if bpy.context.mode != "OBJECT":
        raise ValueError(
            f"{action} needs OBJECT mode, got {bpy.context.mode!r}; leave Edit "
            f"mode first (object.mode_set(mode='OBJECT')) and call again"
        )


def _require_no_modifiers(objects, action: str) -> None:
    """Evaluated-mesh face indices are only the mesh's own when nothing is applied."""
    for blender_object in objects:
        if blender_object.modifiers:
            raise ValueError(
                f"{blender_object.name!r} has modifiers; face indices are "
                f"evaluated-mesh indices, so apply_all_modifiers("
                f"{blender_object.name!r}) first, then {action}"
            )


@op(reads_only=True)
def coplanar_report(
    target: str | list[str],
    settings: CoplanarSettings = CoplanarSettings(),
    pair_offset: int = 0,
) -> CoplanarReport:
    """Find same-facing faces that share a plane and can z-fight; reports overlap, depth quanta, views and a fix.

    `target` is one object name, a list of names, an assembly name or a piece
    name. The report runs the detector's own controls first (flush quads must
    pair, a five-millimetre gap must not) and refuses with
    `CoplanarSelfTestFailed` if they do not, because zero pairs from a broken
    detector is indistinguishable from a clean asset.

    Every length is metres. `plane_gap_quanta` measures the gap in steps of the
    engine's own depth buffer, `(far - near) / 2**depth_bits`: two faces less
    than two quanta apart are resolved differently from frame to frame — that is
    the flicker — while a pair several quanta apart is a modelled clearance that
    cannot flicker whatever its metre gap. `kind` says which it is: `flicker`,
    `clearance`, `buried` (visible from no view), `back_facing` (facing away
    from all of them), `same_material` (both faces the same material, which
    cannot flicker in colour). `visible_from` lists the view labels whose ray
    escaped. `fixes` names the plate that would move, and `declare_flush` marks
    an intended contact so it stops counting as flicker.

    `pairs` carries at most `MAXIMUM_PAIR_ROWS` rows and `pair_offset` reads the
    next page; `pair_count` and `flicker_count` are the FULL counts.
    """
    report, _all_pairs = _measure(target, settings, pair_offset)
    return report


@op()
def declare_flush(first_name: str, second_name: str, reason: str) -> ObjectName:
    """Declare two parts' coplanar contact intended, so coplanar_report lists it apart from flicker.

    A kit's trim is laid ON its plank: the two faces are flush by design and the
    overlap is the join, not a defect. `coplanar_report` cannot know that — the
    geometry of an intended flush and an unintended one is identical — so the
    intent is declared here, the way `declare_join` declares an axle through its
    hub. A declared pair keeps its geometry-derived `kind` and carries
    `declared_reason`; it leaves `flicker_count` and produces no fix.
    Re-declaring replaces the reason, so a correction is one call.
    """
    from golem_blender.ops.assembly import _mesh_part

    for object_name in (first_name, second_name):
        if not isinstance(object_name, str) or not object_name.strip():
            raise ValueError(
                f"an object name must be a non-empty string, got {object_name!r}"
            )
        if _mesh_part(object_name) is None:
            raise UnknownObject(
                f"no MESH object named {object_name!r} to declare a flush for (a "
                f"coplanar contact describes two pieces of geometry)"
            )
    if first_name == second_name:
        raise ValueError(
            f"a flush needs two different parts, got {first_name!r} twice: a part "
            f"is not coplanar with itself"
        )
    if not reason.strip():
        raise ValueError(
            "a flush needs a reason: say why the contact is intended (trim laid "
            "on a plank, a panel against its frame)"
        )
    _DECLARED_FLUSH[frozenset((first_name, second_name))] = reason.strip()
    return ObjectName(first_name)


@op()
def separate_coplanar_faces(
    target: str | list[str],
    settings: CoplanarSettings = CoplanarSettings(),
) -> CoplanarFixReport:
    """Push each flickering coplanar face patch out along its normal by twice the tolerance, smaller side first.

    Measures first, then moves the SMALLER plate of each coplanar group: two
    sides each moving a millimetre apart is a visible change to a modelled
    junction, and moving the smaller side twice gives the same clearance with
    half as much of the asset disturbed. The offset is converted into the
    object's own space, so a rotated or scaled part moves along its normal by
    the named distance rather than along a world axis.

    Then measures AGAIN and reports `flicker_after`. It does not roll back when
    pairs remain: a fix that leaves flicker is a number the caller acts on, and
    a rollback would hide which faces it could not resolve.

    Refused on a target with modifiers (face indices are evaluated-mesh indices)
    and outside OBJECT mode.
    """
    import bpy
    from mathutils import Vector

    _require_object_mode("separate_coplanar_faces")
    label, objects = resolve_mesh_targets(target)
    _require_no_modifiers(objects, "separate_coplanar_faces")
    before, _all_before = _measure(target, settings)
    by_name = {blender_object.name: blender_object for blender_object in objects}
    moved_vertices = 0
    applied: list[CoplanarFix] = []
    for fix in before.fixes:
        blender_object = by_name.get(fix.object_name)
        if blender_object is None:
            continue
        mesh = blender_object.data
        offset_world = tuple(component * fix.move_m for component in fix.normal)
        # The object's own frame, so a rotated or scaled part moves along its
        # own normal by the named distance.
        local_offset = blender_object.matrix_world.inverted_safe().to_3x3() @ Vector(
            offset_world
        )
        touched: set[int] = set()
        for face_index in fix.face_indices:
            if face_index >= len(mesh.polygons):
                continue
            touched.update(mesh.polygons[face_index].vertices)
        for vertex_index in touched:
            mesh.vertices[vertex_index].co = (
                mesh.vertices[vertex_index].co + local_offset
            )
        moved_vertices += len(touched)
        applied.append(fix)
        mesh.update()
    bpy.context.view_layer.update()
    after, _all_after = _measure(target, settings)
    return CoplanarFixReport(
        target=label,
        flicker_before=before.flicker_count,
        flicker_after=after.flicker_count,
        moved=tuple(applied),
        moved_vertex_count=moved_vertices,
        report_after=after,
    )


@op()
def select_coplanar_faces(
    target: str | list[str],
    settings: CoplanarSettings = CoplanarSettings(),
) -> CoplanarSelection:
    """Select the faces of every flickering coplanar pair and frame them in the 3D viewport.

    A selection changes UI state, which is why it is an action and not a flag on
    the report. Every face of the target is deselected first, then both faces of
    every undeclared flicker pair are selected, the target objects become the
    selection and the first one with a selected face becomes active. `viewport`
    says where the view was put, so a caller can tell whether a user is looking
    at the same faces.
    """
    import bpy

    from golem_blender import viewport_follow

    _require_object_mode("select_coplanar_faces")
    label, objects = resolve_mesh_targets(target)
    _require_no_modifiers(objects, "select_coplanar_faces")
    report, all_pairs = _measure(target, settings)
    by_name = {blender_object.name: blender_object for blender_object in objects}
    wanted: dict[str, set[int]] = {}
    for pair in _flicker_rows(all_pairs):
        wanted.setdefault(pair.first_object_name, set()).add(pair.first_face_index)
        wanted.setdefault(pair.second_object_name, set()).add(pair.second_face_index)
    for blender_object in objects:
        for polygon in blender_object.data.polygons:
            polygon.select = False
    for object_name, face_indices in wanted.items():
        mesh = by_name[object_name].data
        for face_index in face_indices:
            if face_index < len(mesh.polygons):
                mesh.polygons[face_index].select = True
    for blender_object in bpy.context.view_layer.objects:
        blender_object.select_set(False)
    active = None
    for object_name in sorted(wanted):
        blender_object = by_name[object_name]
        blender_object.select_set(True)
        if active is None:
            active = blender_object
    if active is not None:
        bpy.context.view_layer.objects.active = active
    framing = viewport_follow.frame_in_viewports(tuple(sorted(wanted)))
    return CoplanarSelection(
        target=label,
        flicker_count=report.flicker_count,
        selected=tuple(
            (name, tuple(sorted(face_indices)))
            for name, face_indices in sorted(wanted.items())
        ),
        viewport=framing.line,
    )
