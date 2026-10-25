"""An ASSEMBLY: many pieces, defined, measured, gated, rendered and shipped as ONE asset.

Measured need (issue #26, `Landmark_BlacksmithShop`, Sanctuary, 2026-10-24):
a 49-part building of 19,967 triangles and 18 materials could not be shipped
through `export_asset` at all. That op gates ONE mesh — one closed manifold
component under 2000 triangles — and its refusal was accurate and useless:

    triangle count 21328 exceeds budget 2000; 33052 boundary edges (open
    mesh); 6943 disconnected components (budget 1); 6486 self-intersecting
    face pairs ...

because that is what a building assembled from kit pieces IS: 49 closed solids
sharing faces where they meet. So the `.glb` was written by a headless script
outside golem, losing the verification the tool exists to provide, and after 20
turns the assembly existed only in the session's notes.

THE GATE HERE IS NOT `MeshBudget`, AND THE CHOICE IS STATED RATHER THAN IMPLIED:

- every PART is judged by the normal per-piece gate (`analyze_object` with a
  `MeshBudget`), unchanged — a part must still be one closed manifold prop, and
  `export_assembly` fails naming the part that is not;
- parts MAY lap. Part-vs-part interpenetration is REPORTED with the pair's
  names and its box overlap volume, never failed outright, because a kit corner
  leg laps its wall by one wall thickness by design (0.406 m in the session).
  `PartIntersection.kind` separates a LAP (a junction: the two parts' boxes end
  in the SAME plane across the penetration axis, so the pieces were cut to
  meet) from a CLASH (one part's interior pushed through another's face, such
  as a pipe through a bellows — no shared plane bounds it);
- the assembly's own verdict rides on `ExportReport`, not on a report op.
  `AssemblyReport.object_name` names the ASSEMBLY — a registry entry, not a
  scene object — so `gate_target_names` would hand that name to
  `gate_named_object`, which answers "no object named ... in bpy.data.objects"
  on every single call. `ops/_contract.py` forbids claiming a gate verdict for a
  report that names no real object, so `define_assembly` and `assembly_report`
  are NOT gated, and `export_assembly` carries the measurement of the parts it
  actually ships.

`define_assembly` is an ACTION: it moves the parts so the assembly's pivot
holds — footprint centred on X/Y, lowest point on z=0 — which is what makes
`lowest_point_m == 0` a fact instead of a hope. `assembly_report` reads and
changes nothing, so it needs no declared plan.

An assembly that says a CHARACTER USES IT (`define_assembly(interaction_side=...)`)
is additionally measured for USE: each part's declared side against the other
parts' clear space, reported as `interaction_sides`/`blocked_sides` and REFUSED
by `export_assembly`. Measured need, 2026-10-24: two ovens facing each other and
a spout sunk in a wall passed every gate here, and the user found them by
looking. The check is opt-in because a structural set of parts is not an asset
anybody walks up to — see `analyze/interaction.py` for the four geometric
probes that proved an interaction side cannot be inferred and must be declared.

Every measurement here is SHARED, never re-derived: world bounds come from
`ops/transforms._world_bounds_m` (the one place world extents are measured,
OT-34), the pairwise verdict from `analyze.pair_checks.analyze_pair` (the one
pairwise measurement, whose face-pair count is already gated above
`CONTACT_DEPTH_TOLERANCE_M` so resting contact reads zero), the join arithmetic
from `ops/assets._append_part_into` (the code `join_objects` uses, so "several
meshes become one" means one thing), and the renders from
`capture.views.capture_views`, which already frames a set of objects together.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from golem_blender.analyze.interaction import (
    SIDE_LOCAL_NORMAL,
    InteractionReport,
    SideAccess,
    measure_interaction_sides,
)
from golem_blender.analyze.pair_checks import CONTACT_DEPTH_TOLERANCE_M
from golem_blender.export.gltf import ExportReport
from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName

# A part whose base sits within this of the floor, or of another part's top,
# RESTS on it. The same tolerance as resting contact, on purpose: the two
# questions share one answer for "are these touching".
SUPPORT_TOLERANCE_M = CONTACT_DEPTH_TOLERANCE_M

# The pivot the issue asks for, and the only one that makes `lowest_point_m`
# zero: the footprint centred on X/Y with the lowest point on z = 0.
PIVOT_FOOTPRINT_CENTRE_BASE = "footprint_centre_base"
SUPPORTED_PIVOTS = (PIVOT_FOOTPRINT_CENTRE_BASE,)

# What a whole-assembly sheet renders by default: the view names
# `capture.views` knows that look at a building from a useful side. The issue's
# proposed "back"/"left"/"inside" are not directions this renderer has, and a
# view nobody renders is a view nobody inspects.
ASSEMBLY_VIEWS = ("front", "right", "three_quarter", "top")
# A FOCUS capture is a close-up of one junction, from three angles: a bracket
# off its wall, a board hung flat and a pipe through a bellows each read as
# wrong from a side, an end and a corner.
FOCUS_VIEWS = ("front", "right", "three_quarter")

WELDED_OBJECT_SUFFIX = "_welded"
REIMPORT_OBJECT_SUFFIX = "_reimport_check"
# Two bounding planes within this are the SAME plane: pieces cut to meet, not
# two edges a micron apart by accident.
SHARED_PLANE_TOLERANCE_M = 1.0e-6
# A box overlap thinner than a face is a shared plane, not shared volume; the
# AABB of a cylinder or a sphere is also larger than the solid it bounds, so the
# volume below is a size, never an integral.
LAP_KIND = "lap"
CLASH_KIND = "clash"

# HOW MUCH MEASUREMENT A CALL ASKS FOR. Measured need, 2026-10-24: a 77-part
# bakery's `export_assembly` outlived the client's 300 s socket timeout, because
# the full gate measures every part, every pair with triangles and the whole
# welded mesh. The work was never wrong, it was unbounded — so the caller now
# says how much it wants, and `none` exists so an export can be written at all
# when the gate cannot finish.
#
#   none      — the files are written and NOTHING is measured: no part gate, no
#               clearance, no whole-assembly analysis, no re-import. The report
#               says so, and `assembly_failures` refuses to call it verified.
#   structure — what can be decided from BOXES and from each part on its own:
#               the part gate, the clearance check and the pair rows' depths,
#               WITHOUT the per-pair triangle sweep. Minutes become seconds.
#   full      — everything, including `analyze_pair` per candidate, the
#               whole-welded-mesh analysis and the re-import measurement.
GATE_MODES = ("none", "structure", "full")
# The wall-clock budget, in seconds. Deliberately well under the client's
# socket timeout (`connection._TIMEOUT`, 300 s), so a long call returns a
# TRUNCATED report rather than an unanswered socket: a report the caller can
# read beats a socket the caller gives up on.
DEFAULT_BUDGET_S = 120.0
# How many intersection rows one report carries. A row costs a line of text; a
# 77-part assembly with 45 overlapping pairs does not need all of them at once,
# and `part_intersection_count` plus `intersection_offset` page the rest. The
# DEFECTS (`undeclared_clashes`) and the `laps` are computed from the full list,
# so nothing that matters can be paged out of view.
MAXIMUM_INTERSECTION_ROWS = 40
# The distance two parts may stand apart and still count as JOINED. The
# resting-contact tolerance, on purpose: a joint that is butted reads as
# touching, and one with a hand's width of daylight through it does not.
DEFAULT_GAP_TOLERANCE_M = CONTACT_DEPTH_TOLERANCE_M
# How far apart two NON-OVERLAPPING parts' boxes may be and still be measured.
# A corner 0.323 m clear of its wall is a defect no number reported (measured
# 2026-10-24: only a render caught it); a part across the room is not a joint at
# all and measuring every such pair would cost a BVH sweep each.
DEFAULT_SEPARATION_MARGIN_M = 0.5
# The names of the checks, so a report can say which ones did not run.
PART_GATE_CHECK = "part_gate"
SEPARATION_CHECK = "separation"
CLEARANCE_CHECK = "clearance"
COMBINED_ANALYSIS_CHECK = "combined_analysis"
REIMPORT_CHECK = "reimport"


def _validate_gate_and_budget(gate: str, budget_s: float) -> float:
    """The two arguments every gated assembly op takes, refused before any work."""
    if gate not in GATE_MODES:
        raise ValueError(f"gate must be one of {list(GATE_MODES)}, got {gate!r}")
    if not budget_s > 0.0:
        raise ValueError(
            f"budget_s must be a positive number of seconds, got {budget_s!r}; "
            f"the default is {DEFAULT_BUDGET_S} s"
        )
    return float(budget_s)


@dataclass(frozen=True)
class PartIntersection:
    """One pair of parts whose boxes share volume: how deep, how much, and which kind."""

    first_object_name: str
    second_object_name: str
    # LAP (a junction by design) or CLASH (an interior pushed through a face).
    kind: str
    # The world-AABB minimum translation depth, from `analyze_pair`.
    penetration_depth_m: float
    # The two parts' box overlap: an over-estimate for anything not a box.
    overlap_volume_m3: float
    # The triangle pairs that actually intersect. `analyze_pair` reports these
    # only above CONTACT_DEPTH_TOLERANCE_M, so resting contact reads zero.
    # -1 means NOT MEASURED: `gate="structure"` and a budget that ran out both
    # decide a pair from its boxes alone, and a zero there would claim a
    # measurement nobody took.
    intersecting_face_pair_count: int
    # Why this contact is intended, when `declare_join` recorded one. Empty for
    # an undeclared clash — which is the whole point of the declaration: the
    # assembly report can then list `undeclared_clashes` separately from the
    # junctions a kit was built with.
    declared_reason: str = ""


@dataclass(frozen=True)
class PairSeparation:
    """Two parts' distance apart, when they do NOT share volume.

    `part_intersections` only ever holds pairs whose boxes overlap, so an inner
    corner placed 0.323 m clear of its wall was not in the report at all — the
    measured 2026-10-24 case, where a render was the only thing that found it.

    TWO NUMBERS, and they bound the answer from opposite sides:

    - `separation_m` is `analyze_pair.minimum_separation_m`: each mesh's
      evaluated vertices against the other's closest SURFACE, sampled, both
      directions. An UPPER bound on the true gap — exact for two butted box
      faces, but it over-estimates a plus-shaped crossing, where no vertex
      projects onto the other part's face.
    - `box_gap_m` is `_box_gap_m`: a LOWER bound from the two world AABBs,
      exact for boxes and 0.0 whenever they touch or overlap.

    So a structure-mode verdict uses the box gap, which never reports a closed
    joint as open and can miss a gap on a part that is not box-shaped. -1 in
    `separation_m` means NOT MEASURED, never a zero: `gate="structure"` and a
    spent budget both decide the row from the boxes alone.
    """

    first_object_name: str
    second_object_name: str
    separation_m: float
    box_gap_m: float
    gap_tolerance_m: float
    is_open: bool
    # Why these two are meant to touch, when `declare_join` recorded one.
    declared_reason: str = ""


@dataclass(frozen=True)
class AssemblyReport:
    """What an assembly IS, measured now. Numbers, not opinions."""

    # The ASSEMBLY's name — a registry entry, not a scene object, which is why
    # no op returning this report claims a gate verdict.
    object_name: str
    objects: tuple[str, ...]
    triangles_total: int
    dimensions_m: tuple[float, float, float]
    lowest_point_m: float
    materials: tuple[str, ...]
    # Named parts with no MESH object in the scene right now: never linked, or
    # removed after the assembly was defined. Excluded from every total, and
    # listed so the exclusion is never silent.
    unlinked: tuple[str, ...]
    part_intersections: tuple[PartIntersection, ...]
    # Off the ground, and nothing beneath whose top meets its base.
    unsupported: tuple[str, ...]
    # The narrower case: unsupported AND sharing no volume with any other part.
    floating: tuple[str, ...]
    # The name pairs `part_intersections` calls a LAP.
    laps: tuple[tuple[str, str], ...]
    pivot: str = PIVOT_FOOTPRINT_CENTRE_BASE
    # --- whether a character can USE the assembly (issue: assets facing the wall)
    # Every declared interaction side, measured against the other parts. Empty
    # when the assembly declared none, so "no sides declared" and "all clear"
    # cannot be confused with one another.
    interaction_sides: tuple[SideAccess, ...] = ()
    # The sides a character cannot reach: buried in another part, or with less
    # than MINIMUM_APPROACH_M of clear space over most of the face.
    # `ExportReport.blocked_sides` carries the same measurement to export, which
    # REFUSES the assembly naming the part, the side and its blocker.
    blocked_sides: tuple[SideAccess, ...] = ()
    # Which side each part's measurement used, so a reader can tell a part that
    # declared its own side from one that inherited the assembly's.
    interaction_side_by_part: tuple[tuple[str, str], ...] = ()
    # --- how much was measured, and whether it finished (the 77-part wedge) ---
    # The mode this report was measured in: "none", "structure" or "full".
    gate: str = "full"
    # True only when `budget_s` cut a check THIS gate asked for. A truncated
    # report is a real measurement of less than was requested, never a failure.
    truncated: bool = False
    # Pairs measured with triangles (`analyze_pair`), against the pairs whose
    # boxes share volume. Under `gate="structure"` or a spent budget the second
    # number is the truth and the first is smaller — by design.
    pairs_checked: int = 0
    pairs_total: int = 0
    # How many rows `part_intersections` could hold, and where this page starts:
    # `part_intersection_count` is the FULL count, so a paged report never
    # understates what it found.
    part_intersection_count: int = 0
    part_intersection_offset: int = 0
    # The defects, computed from ALL rows and never paged: clashes nobody
    # declared as intended.
    undeclared_clashes: tuple[tuple[str, str], ...] = ()
    # Declared joins whose two parts are both in this assembly but do not touch.
    # A declaration that stopped being true is a part that moved.
    declared_without_contact: tuple[tuple[str, str], ...] = ()
    # The session's safety copy, written before a full gate on a large
    # assembly started: the scene as it was, on disk, if the call went wrong.
    scratch_blend_path: str = ""
    scratch_save_error: str = ""
    # --- how far apart nearby NON-OVERLAPPING pairs stand (the 0.323 m corner)
    # Pairs whose boxes are within `separation_margin_m` of each other (or that
    # `declare_join` named, at any distance), measured. Paged like
    # `part_intersections`, and for the same reason.
    separations: tuple[PairSeparation, ...] = ()
    # How many rows `separations` could hold — the FULL count, so a paged report
    # never understates what it found.
    separation_count: int = 0
    separation_offset: int = 0
    # Rows carrying a real surface measurement; the rest are box bounds.
    separations_measured: int = 0
    # The joints with daylight through them, from the FULL list and never paged:
    # what a caller acts on, in the same words a refusal would use.
    open_gaps: tuple[str, ...] = ()
    gap_tolerance_m: float = DEFAULT_GAP_TOLERANCE_M
    separation_margin_m: float = DEFAULT_SEPARATION_MARGIN_M


# The session's assemblies: name -> part names. NAMES only, so a part removed
# after definition shows up in `unlinked` instead of quietly shrinking every
# total. Module-level because an assembly is a fact about the session, like an
# object's name — and two assemblies sharing pieces each read their own totals
# because each holds its own tuple.
_ASSEMBLIES: dict[str, tuple[str, ...]] = {}

# The interaction side each part DECLARES: part name -> one of
# `INTERACTION_SIDES`. Module-level like `_ASSEMBLIES`, and keyed by PART
# rather than by assembly: one part in two assemblies is the same physical
# side of the same object, so it cannot mean two different things.
#
# DECLARING IS OPT-IN, AND THE ASSEMBLY SAYS WHETHER IT IS USED AT ALL. The
# first design checked every part's `front` by default and failed a wall with
# a crate 0.2 m from it — a crate beside a wall is not a defect, and a set of
# parts is not always an asset a character walks up to (measured: the 49-part
# building fixture, `WallWest0` "blocked" by its own crates). So an assembly
# states its interaction side (`define_assembly(interaction_side=...)`), and
# ONLY THEN is every part measured against the others; `None` means this
# assembly is a structural set and nothing is claimed about use. A part may
# override the side it personally presents.
_INTERACTION_SIDES: dict[str, str] = {}
# assembly name -> the side a character uses it from, or None when the
# assembly makes no claim.
_ASSEMBLY_INTERACTION_SIDE: dict[str, str | None] = {}

# The pairs DECLARED to touch on purpose: frozenset({a, b}) -> why. A frozenset
# because a join is symmetric — an axle through a hub is the same fact whichever
# name is written first — so `declare_join(a, b)` and `declare_join(b, a)` are
# one declaration, and re-declaring replaces the reason. Keyed by PART names,
# like `_INTERACTION_SIDES`, because it is a fact about two pieces and not about
# one assembly that happens to hold them.
_DECLARED_JOINS: dict[frozenset[str], str] = {}


def _mesh_part(object_name: str):
    """The named MESH object, or None when there is no such mesh to measure."""
    import bpy

    blender_object = bpy.data.objects.get(object_name)
    if blender_object is None or blender_object.type != "MESH":
        return None
    return blender_object


def _assembly_bounds(part_objects) -> tuple[list[float], list[float]]:
    """The parts' JOINT world box; one shared measurement for the whole report."""
    from golem_blender.ops.transforms import _world_bounds_m

    if not part_objects:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return _world_bounds_m(part_objects)


def _overlap_on_axis(first_bounds, second_bounds, axis: int) -> float:
    (first_minimum, first_maximum), (second_minimum, second_maximum) = (
        first_bounds,
        second_bounds,
    )
    return min(first_maximum[axis], second_maximum[axis]) - max(
        first_minimum[axis], second_minimum[axis]
    )


def _shares_a_bounding_plane_on(first_bounds, second_bounds, axis: int) -> bool:
    """Do the two boxes END in the same plane across the penetration axis?

    That is the shape of kit joinery: a wall's end face and a return's end face
    lie in one plane, so on the penetration axis BOTH parts own the overlap's
    end. A clash is the other shape — the overlap's ends belong to different
    parts on that axis, which is exactly one solid's interior pushed through the
    other's face and stopped nowhere.
    """
    (first_minimum, first_maximum), (second_minimum, second_maximum) = (
        first_bounds,
        second_bounds,
    )
    overlap_minimum = max(first_minimum[axis], second_minimum[axis])
    overlap_maximum = min(first_maximum[axis], second_maximum[axis])
    shares_maximum = (
        abs(overlap_maximum - first_maximum[axis]) <= SHARED_PLANE_TOLERANCE_M
        and abs(overlap_maximum - second_maximum[axis]) <= SHARED_PLANE_TOLERANCE_M
    )
    shares_minimum = (
        abs(overlap_minimum - first_minimum[axis]) <= SHARED_PLANE_TOLERANCE_M
        and abs(overlap_minimum - second_minimum[axis]) <= SHARED_PLANE_TOLERANCE_M
    )
    return shares_maximum or shares_minimum


def _shared_volume(first_bounds, second_bounds):
    """(kind, depth_m, volume_m3) for a box overlap, or None when disjoint."""
    overlaps = [
        _overlap_on_axis(first_bounds, second_bounds, axis) for axis in range(3)
    ]
    if any(overlap <= 0.0 for overlap in overlaps):
        return None
    depth_axis = min(range(3), key=lambda axis: overlaps[axis])
    depth_m = overlaps[depth_axis]
    if depth_m <= CONTACT_DEPTH_TOLERANCE_M or _shares_a_bounding_plane_on(
        first_bounds, second_bounds, depth_axis
    ):
        kind = LAP_KIND
    else:
        kind = CLASH_KIND
    return kind, depth_m, overlaps[0] * overlaps[1] * overlaps[2]


def _open_gap_line(row: "PairSeparation") -> str:
    """One open joint, in the words a caller can act on.

    A measured row states the gap; an unmeasured one states the bound it does
    have and says so, because "at least X" and "X" are different facts and a
    structure-mode report must not pass one off as the other.
    """
    if row.separation_m >= 0.0:
        return (
            f"{row.first_object_name} → {row.second_object_name}: "
            f"{row.separation_m:.3f} m apart, expected ≤ {row.gap_tolerance_m:.3f} m"
        )
    return (
        f"{row.first_object_name} → {row.second_object_name}: at least "
        f"{row.box_gap_m:.3f} m apart (bounding boxes; surface not measured), "
        f"expected ≤ {row.gap_tolerance_m:.3f} m"
    )


def _box_gap_m(first_bounds, second_bounds) -> float:
    """Euclidean distance between two world AABBs; 0.0 when they touch or overlap.

    An exact LOWER bound on the surface gap between any two shapes inside those
    boxes: the boxes are supersets of the parts, so anything inside them cannot
    be closer than this.
    """
    squared_gap_m2 = 0.0
    for axis in range(3):
        first_minimum, first_maximum = first_bounds[0][axis], first_bounds[1][axis]
        second_minimum, second_maximum = second_bounds[0][axis], second_bounds[1][axis]
        axis_gap_m = max(
            0.0, first_minimum - second_maximum, second_minimum - first_maximum
        )
        squared_gap_m2 += axis_gap_m * axis_gap_m
    return math.sqrt(squared_gap_m2)


def _supported_by(part_bounds, other_bounds) -> bool:
    """Does `other` hold `part` up?

    Two answers, both a measurement of the boxes: the other part's TOP meets the
    part's BASE (a lid on a crate, a floor under a leg), or the part's base lies
    inside the other's z-range with their footprints overlapping (a bracket
    embedded in a wall). Support is deliberately NOT transitive — one level is
    what tells a writer which part to move.
    """
    part_minimum, part_maximum = part_bounds
    other_minimum, other_maximum = other_bounds
    if not all(
        _overlap_on_axis(part_bounds, other_bounds, axis) > 0.0 for axis in range(2)
    ):
        return False
    if abs(other_maximum[2] - part_minimum[2]) <= SUPPORT_TOLERANCE_M:
        return True
    return (
        other_minimum[2] - SUPPORT_TOLERANCE_M
        <= part_minimum[2]
        <= other_maximum[2] + SUPPORT_TOLERANCE_M
        and part_maximum[2] > other_minimum[2]
    )


def _assembly_side(assembly_name: str) -> str | None:
    """The side this assembly is USED from, or None when it claims nothing."""
    return _ASSEMBLY_INTERACTION_SIDE.get(assembly_name)


def _declared_side(assembly_name: str, object_name: str) -> str | None:
    """The side one part of this assembly declares, or None when unmeasured.

    A part's own declaration wins, so one piece that faces differently (a
    shelf's opening, a chimney's flue) says so once. An assembly that claims
    no side measures nothing; an assembly that claims one measures every
    part from it unless that part overrode it.
    """
    part_side = _INTERACTION_SIDES.get(object_name)
    if part_side is not None:
        return part_side
    return _assembly_side(assembly_name)


def _interaction(name: str, part_objects) -> InteractionReport:
    """Measure the sides this assembly CLAIMS; nothing at all when it claims none."""
    declared = {
        part_object.name: side
        for part_object in part_objects
        if (side := _declared_side(name, part_object.name)) is not None
    }
    return measure_interaction_sides(name, part_objects, declared)


def _measure(
    name: str,
    object_names: tuple[str, ...],
    gate: str = "full",
    budget_s: float = DEFAULT_BUDGET_S,
    intersection_offset: int = 0,
    gap_tolerance_m: float = DEFAULT_GAP_TOLERANCE_M,
    separation_margin_m: float = DEFAULT_SEPARATION_MARGIN_M,
    separation_offset: int = 0,
) -> AssemblyReport:
    """The assembly's numbers, measured now from the scene, within `gate` and `budget_s`.

    The pair loop is the expensive half: `analyze_pair` builds two world BVHs and
    counts the triangle pairs that actually cross, and the 77-part bakery had 45
    candidate pairs on top of a 77-part gate. So the loop is where the budget is
    checked and where `gate="structure"` stops measuring: a row's DEPTH comes
    from the boxes in every mode (it is arithmetic), and only the triangle count
    needs the sweep.
    """
    from golem_blender.analyze.pair_checks import analyze_pair
    from golem_blender.ops.transforms import _world_bounds_m
    from golem_blender.run.call_context import Deadline, report_progress

    deadline = Deadline(budget_s)
    truncated = False

    part_objects = []
    unlinked: list[str] = []
    for object_name in object_names:
        blender_object = _mesh_part(object_name)
        if blender_object is None:
            unlinked.append(object_name)
        else:
            part_objects.append(blender_object)

    minimum, maximum = _assembly_bounds(part_objects)
    dimensions_m = tuple(float(maximum[axis] - minimum[axis]) for axis in range(3))
    lowest_point_m = float(minimum[2]) if part_objects else 0.0

    part_bounds = [_world_bounds_m([part_object]) for part_object in part_objects]

    triangles_total = 0
    material_names: set[str] = set()
    for part_object in part_objects:
        triangles_total += sum(
            len(polygon.vertices) - 2 for polygon in part_object.data.polygons
        )
        for material in part_object.data.materials:
            if material is not None:
                material_names.add(material.name)

    # The candidate pairs FIRST, from the boxes alone: the budget has to know how
    # much work is coming before it decides anything, and `pairs_total` is a
    # measurement a truncated report must still carry.
    candidates: list[tuple[int, int, tuple[str, float, float]]] = []
    touching: set[int] = set()
    if gate != "none":
        for first_index in range(len(part_objects)):
            for second_index in range(first_index + 1, len(part_objects)):
                shared = _shared_volume(
                    part_bounds[first_index], part_bounds[second_index]
                )
                if shared is None:
                    continue
                candidates.append((first_index, second_index, shared))
                touching.update((first_index, second_index))

    pairs_total = len(candidates)
    pairs_checked = 0
    measured_rows: list[PartIntersection] = []
    for candidate_index, (first_index, second_index, shared) in enumerate(
        candidates, start=1
    ):
        kind, depth_m, volume_m3 = shared
        first_object = part_objects[first_index]
        second_object = part_objects[second_index]
        report_progress("pair check", candidate_index, pairs_total)
        measure_with_triangles = gate == "full" and not deadline.expired()
        if measure_with_triangles:
            pair_report = analyze_pair(first_object, second_object)
            depth_m = float(pair_report.aabb_penetration_depth_m)
            face_pair_count = pair_report.intersecting_face_pair_count
            pairs_checked += 1
        else:
            face_pair_count = -1
            if gate == "full":
                truncated = True
        measured_rows.append(
            PartIntersection(
                first_object_name=first_object.name,
                second_object_name=second_object.name,
                kind=kind,
                penetration_depth_m=depth_m,
                overlap_volume_m3=volume_m3,
                intersecting_face_pair_count=face_pair_count,
                declared_reason=_DECLARED_JOINS.get(
                    frozenset((first_object.name, second_object.name)), ""
                ),
            )
        )

    # --- how far apart the NEARBY NON-OVERLAPPING pairs stand
    #
    # `candidates` holds only pairs whose boxes share volume, which is why an
    # inner corner 0.323 m clear of its wall was absent from every number the
    # report carried (measured 2026-10-24; a render was what found it). This pass
    # takes the complementary set: pairs close enough to be a joint in intent,
    # plus every pair somebody DECLARED, and measures how far apart they are.
    #
    # Reported, never refused: a gap is a number a writer acts on, and an
    # assembly under `gate="none"` claims no measurement at all.
    separation_rows: list[PairSeparation] = []
    separations_measured = 0
    if gate != "none":
        overlapping_pairs = {
            frozenset((part_objects[first_index].name, part_objects[second_index].name))
            for first_index, second_index, _shared in candidates
        }
        separation_candidates: list[tuple[int, int]] = []
        for first_index in range(len(part_objects)):
            for second_index in range(first_index + 1, len(part_objects)):
                pair = frozenset(
                    (
                        part_objects[first_index].name,
                        part_objects[second_index].name,
                    )
                )
                if pair in overlapping_pairs:
                    continue
                if pair in _DECLARED_JOINS:
                    separation_candidates.append((first_index, second_index))
                    continue
                if (
                    _box_gap_m(part_bounds[first_index], part_bounds[second_index])
                    <= separation_margin_m
                ):
                    separation_candidates.append((first_index, second_index))

        for candidate_index, (first_index, second_index) in enumerate(
            separation_candidates, start=1
        ):
            first_object = part_objects[first_index]
            second_object = part_objects[second_index]
            report_progress(
                "separation check", candidate_index, len(separation_candidates)
            )
            measure_with_triangles = gate == "full" and not deadline.expired()
            separation_m = -1.0
            if measure_with_triangles:
                separation_m = float(
                    analyze_pair(first_object, second_object).minimum_separation_m
                )
                if math.isfinite(separation_m):
                    separations_measured += 1
                else:
                    separation_m = -1.0
            elif gate == "full":
                truncated = True
            box_gap_m = _box_gap_m(part_bounds[first_index], part_bounds[second_index])
            # The SURFACE number when there is one, the box bound otherwise: a
            # structure-mode verdict must never call a closed joint open.
            deciding_gap_m = separation_m if separation_m >= 0.0 else box_gap_m
            separation_rows.append(
                PairSeparation(
                    first_object_name=first_object.name,
                    second_object_name=second_object.name,
                    separation_m=separation_m,
                    box_gap_m=box_gap_m,
                    gap_tolerance_m=gap_tolerance_m,
                    is_open=deciding_gap_m > gap_tolerance_m,
                    declared_reason=_DECLARED_JOINS.get(
                        frozenset((first_object.name, second_object.name)), ""
                    ),
                )
            )

    # The widest gap first, so the page a caller reads names the worst joint; the
    # open ones before the closed ones for the same reason. `open_gaps` and
    # `declared_without_contact` come from the FULL list, so paging cannot hide a
    # joint with daylight in it.
    ordered_separations = sorted(
        separation_rows,
        key=lambda row: (
            0 if row.is_open else 1,
            -(row.separation_m if row.separation_m >= 0.0 else row.box_gap_m),
            row.first_object_name,
            row.second_object_name,
        ),
    )
    separation_page = tuple(
        ordered_separations[
            separation_offset : separation_offset + MAXIMUM_INTERSECTION_ROWS
        ]
    )
    open_gaps = tuple(_open_gap_line(row) for row in ordered_separations if row.is_open)

    interaction = InteractionReport(assembly_name=name, sides=(), blocked=())
    if gate != "none":
        if deadline.expired():
            # The clearance check is a ray grid per declared side: real work, and
            # the first thing to go when the budget is spent.
            truncated = True
        else:
            report_progress("clearance", 0, 1)
            interaction = _interaction(name, part_objects)
            report_progress("clearance", 1, 1)

    unsupported: list[str] = []
    floating: list[str] = []
    for part_index, bounds in enumerate(part_bounds):
        if bounds[0][2] <= SUPPORT_TOLERANCE_M:
            continue  # standing on the ground
        if any(
            _supported_by(bounds, other_bounds)
            for other_index, other_bounds in enumerate(part_bounds)
            if other_index != part_index
        ):
            continue
        unsupported.append(part_objects[part_index].name)
        if part_index not in touching:
            floating.append(part_objects[part_index].name)

    # A defect sorts before a junction and a junction before a lap, so the page a
    # caller reads first is the page that matters; the count and the two defect
    # tuples come from the FULL list, so paging can hide a row but never a fault.
    ordered_rows = sorted(
        measured_rows,
        key=lambda row: (
            _row_priority(row),
            row.first_object_name,
            row.second_object_name,
        ),
    )
    page = tuple(
        ordered_rows[
            intersection_offset : intersection_offset + MAXIMUM_INTERSECTION_ROWS
        ]
    )

    return AssemblyReport(
        object_name=name,
        objects=object_names,
        triangles_total=triangles_total,
        dimensions_m=(dimensions_m[0], dimensions_m[1], dimensions_m[2]),
        lowest_point_m=lowest_point_m,
        materials=tuple(sorted(material_names)),
        unlinked=tuple(unlinked),
        part_intersections=page,
        unsupported=tuple(unsupported),
        floating=tuple(floating),
        laps=tuple(
            (intersection.first_object_name, intersection.second_object_name)
            for intersection in measured_rows
            if intersection.kind == LAP_KIND
        ),
        interaction_sides=interaction.sides,
        blocked_sides=interaction.blocked,
        interaction_side_by_part=tuple(
            (part_object.name, side)
            for part_object in part_objects
            if (side := _declared_side(name, part_object.name)) is not None
        ),
        gate=gate,
        truncated=truncated,
        pairs_checked=pairs_checked,
        pairs_total=pairs_total,
        part_intersection_count=len(measured_rows),
        part_intersection_offset=intersection_offset,
        undeclared_clashes=tuple(
            (row.first_object_name, row.second_object_name)
            for row in measured_rows
            if row.kind == CLASH_KIND and not row.declared_reason
        ),
        # A declaration that stopped being true is a part that moved. Measured
        # from the separation rows, so an exactly butted declared pair — which is
        # what a declaration is FOR — is not a defect; the old test asked only
        # whether the pair appeared among the OVERLAPPING candidates, and a
        # butted joint never does.
        declared_without_contact=tuple(
            tuple(sorted((row.first_object_name, row.second_object_name)))
            for row in ordered_separations
            if row.declared_reason and row.is_open
        ),
        separations=separation_page,
        separation_count=len(separation_rows),
        separation_offset=separation_offset,
        separations_measured=separations_measured,
        open_gaps=open_gaps,
        gap_tolerance_m=gap_tolerance_m,
        separation_margin_m=separation_margin_m,
    )


def _row_priority(row: PartIntersection) -> int:
    """0 for an undeclared clash, 1 for a declared one, 2 for a lap."""
    if row.kind == CLASH_KIND and not row.declared_reason:
        return 0
    if row.kind == CLASH_KIND:
        return 1
    return 2


def _apply_pivot(part_objects, pivot: str) -> None:
    """Move every part so the assembly's pivot holds, in world space."""
    from mathutils import Matrix, Vector

    from golem_blender.ops.transforms import _refresh_dependency_graph, _world_bounds_m

    if pivot not in SUPPORTED_PIVOTS:
        raise ValueError(
            f"unknown pivot {pivot!r}; the supported pivots are "
            f"{list(SUPPORTED_PIVOTS)}"
        )
    if not part_objects:
        return
    minimum, maximum = _world_bounds_m(part_objects)
    # Translated in WORLD space rather than by writing `.location`, so a part
    # carrying a rotation or scale keeps it; the depsgraph is refreshed
    # afterwards so the very next read is truthful (the stale-`matrix_world`
    # trap ops/transforms.py's docstring exists for).
    shift = Matrix.Translation(
        Vector(
            (
                -((minimum[0] + maximum[0]) / 2.0),
                -((minimum[1] + maximum[1]) / 2.0),
                -minimum[2],
            )
        )
    )
    for part_object in part_objects:
        part_object.matrix_world = shift @ part_object.matrix_world
    _refresh_dependency_graph()


def _resolved_parts(name: str) -> tuple[tuple[str, ...], list]:
    """(the names, the live MESH objects) of a defined assembly."""
    object_names = _ASSEMBLIES.get(name)
    if object_names is None:
        raise KeyError(
            f"no assembly named {name!r}; define one with define_assembly "
            f"(defined: {sorted(_ASSEMBLIES)})"
        )
    part_objects = [
        part
        for part in (_mesh_part(object_name) for object_name in object_names)
        if part is not None
    ]
    return object_names, part_objects


@op()
def define_assembly(
    name: str,
    object_names: list[str],
    pivot: str = "footprint_centre_base",
    interaction_side: str | None = None,
    gate: Literal["none", "structure", "full"] = "full",
    budget_s: float = DEFAULT_BUDGET_S,
) -> AssemblyReport:
    """Define the named objects as ONE assembly called `name`, moved so its pivot holds.

    The assembly is a registry entry, so `name` is NOT a scene object: nothing
    is joined, linked or renamed, and the parts keep their own names, meshes and
    materials. The parts are moved so the footprint is centred on X/Y and the
    lowest point sits on z=0. A name listed twice is refused loudly — counting
    one part twice would double its triangles and lie about the total — and a
    name with no mesh yet is kept in `objects` and reported in `unlinked`, so a
    later report says what went missing instead of shrinking silently.
    Re-running under the same name replaces the definition.

    `interaction_side` says a CHARACTER USES this assembly and from which side
    (`front`, `back`, `left`, `right`, `top`, `bottom`; `front` is the
    documented local -Y). Every part is then measured: how much clear space
    its side has, up to the other parts of the assembly, and a part whose
    usable side is buried or most of it inside 0.6 m appears in
    `blocked_sides`. `None` (the default) claims nothing and measures nothing —
    a kit of parts or a structural set is not an asset anybody walks up to,
    and demanding clear space around every wall would fail a building for
    having crates in it.

    `gate` says how much to measure ("full", "structure", "none"); `budget_s`
    caps the wall-clock time and returns `truncated: true` rather than running
    on. A full gate on `SCRATCH_SAVE_MINIMUM_PARTS` or more parts saves the
    session to `<output>/scratch/define_assembly.blend` first, and reports that
    path in `scratch_blend_path`.
    """
    if not name.strip():
        raise ValueError("an assembly needs a non-empty name")
    budget_s = _validate_gate_and_budget(gate, budget_s)
    if not object_names:
        raise ValueError(f"assembly {name!r} names no parts")
    if len(set(object_names)) != len(object_names):
        duplicated = sorted(
            {item for item in object_names if object_names.count(item) > 1}
        )
        raise ValueError(
            f"assembly {name!r} lists {duplicated} twice; every part is counted "
            f"once, so a repeat would double its triangles"
        )
    part_objects = [
        part
        for part in (_mesh_part(object_name) for object_name in object_names)
        if part
    ]
    if interaction_side is not None and interaction_side not in SIDE_LOCAL_NORMAL:
        raise ValueError(
            f"interaction_side must be one of {list(SIDE_LOCAL_NORMAL)} or None, "
            f"got {interaction_side!r}"
        )
    _apply_pivot(part_objects, pivot)
    _ASSEMBLIES[name] = tuple(object_names)
    _ASSEMBLY_INTERACTION_SIDE[name] = interaction_side
    scratch_blend_path, scratch_save_error = _scratch_before_measuring(
        "define_assembly", gate, len(part_objects)
    )
    report = _measure(name, _ASSEMBLIES[name], gate, budget_s)
    return replace(
        report,
        scratch_blend_path=scratch_blend_path,
        scratch_save_error=scratch_save_error,
    )


def _scratch_before_measuring(
    tool_name: str, gate: str, part_count: int
) -> tuple[str, str]:
    """Save the session first when a FULL gate on a large assembly is about to run.

    `("", "")` in every other case: no copy was asked for, so no path claims one
    was written. Never raises — `save_scratch_copy` reports its own failure.
    """
    from golem_blender.run.call_context import (
        SCRATCH_SAVE_MINIMUM_PARTS,
        save_scratch_copy,
    )

    if gate != "full" or part_count < SCRATCH_SAVE_MINIMUM_PARTS:
        return "", ""
    return save_scratch_copy(tool_name)


@op(reads_only=True)
def assembly_report(
    name: str,
    gate: Literal["none", "structure", "full"] = "full",
    budget_s: float = DEFAULT_BUDGET_S,
    intersection_offset: int = 0,
    gap_tolerance_m: float = DEFAULT_GAP_TOLERANCE_M,
    separation_margin_m: float = DEFAULT_SEPARATION_MARGIN_M,
    separation_offset: int = 0,
) -> AssemblyReport:
    """Re-measure the named assembly as it stands now; changes nothing at all.

    Every number is recomputed from the scene, so a part moved, removed or
    replaced since the definition shows up here: a removed part appears in
    `unlinked` and is excluded from every total. Reading is all this does — no
    transform, material or object is touched, so it needs no declared plan.

    `gate` says how much to measure ("full", "structure", "none"); `budget_s`
    caps the wall-clock time and returns `truncated: true` rather than running
    on. The scratch copy is NOT taken here — this op is a reader and writes no
    file side effect a caller did not ask for. `part_intersections` carries at
    most `MAXIMUM_INTERSECTION_ROWS` rows; `intersection_offset` reads the next
    page, and `part_intersection_count` is the full count.

    `separations` is the other half of the same question: `part_intersections`
    holds only pairs whose boxes OVERLAP, so a corner placed 0.323 m clear of its
    wall — measured 2026-10-24, found by a render and by no number — used to
    appear nowhere. Every non-overlapping pair whose boxes are within
    `separation_margin_m` (default 0.5 m) is measured, and so is every pair
    `declare_join` named, at any distance; a pair further apart than
    `gap_tolerance_m` (default 0.002 m, the resting-contact tolerance) is an
    OPEN joint. `open_gaps` states each of them in one line, from the FULL list
    and never paged, and `separations`/`separation_offset` page the rows the way
    `part_intersections` does. A gap is REPORTED, never refused: it is a number
    a writer acts on, and `export_assembly` is unchanged.
    """
    budget_s = _validate_gate_and_budget(gate, budget_s)
    if intersection_offset < 0:
        raise ValueError(
            f"intersection_offset must be 0 or more, got {intersection_offset!r}; "
            f"a negative offset would read from the end of the list"
        )
    if gap_tolerance_m < 0:
        raise ValueError(
            f"gap_tolerance_m must be 0 or more, got {gap_tolerance_m!r}; it is "
            f"the distance two parts may stand apart and still count as joined"
        )
    if separation_margin_m < 0:
        raise ValueError(
            f"separation_margin_m must be 0 or more, got {separation_margin_m!r}; "
            f"it is how far apart two boxes may be and still be measured"
        )
    if separation_offset < 0:
        raise ValueError(
            f"separation_offset must be 0 or more, got {separation_offset!r}; "
            f"a negative offset would read from the end of the list"
        )
    object_names, _part_objects = _resolved_parts(name)
    return _measure(
        name,
        object_names,
        gate,
        budget_s,
        intersection_offset,
        gap_tolerance_m,
        separation_margin_m,
        separation_offset,
    )


@op()
def declare_interaction_side(object_name: str, side: str) -> ObjectName:
    """Declare which side of this part a character uses, so a blocked side can be measured.

    The side is INTENT and cannot be read off the triangles: four geometric
    probes on a real kit's own opening-bearing pieces (an oven's mouth, a
    wall's door, a spout, a hopper) all failed to tell an opening from a
    merely open face, because which side is used is a decision, not a shape.
    `units.yaml` already carries that decision as `front: "-Y"`, which is the
    default; this op records a different one for one part.

    Re-declaring replaces the side, so a repair is one call. The declared
    side is measured by `declare_assembly`/`assembly_report`
    (`interaction_sides`, `blocked_sides`) and REFUSED by `export_assembly`
    when a character cannot reach it.
    """
    if not isinstance(object_name, str) or not object_name.strip():
        raise ValueError(
            f"an object name must be a non-empty string, got {object_name!r}"
        )
    if side not in SIDE_LOCAL_NORMAL:
        raise ValueError(f"side must be one of {list(SIDE_LOCAL_NORMAL)}, got {side!r}")
    if _mesh_part(object_name) is None:
        from golem_blender.ops._objects import UnknownObject

        raise UnknownObject(
            f"no MESH object named {object_name!r} to declare an interaction "
            f"side for (a side describes geometry, so it needs a mesh)"
        )
    _INTERACTION_SIDES[object_name] = side
    return ObjectName(object_name)


@op()
def declare_join(first_name: str, second_name: str, reason: str) -> ObjectName:
    """Declare two parts' contact intended (an axle through its hub), so the assembly report lists it apart from defects.

    A kit's junctions are supposed to overlap: a corner leg laps its wall by one
    wall thickness, a shelf's tenon sits inside its post. `assembly_report`
    already tells a LAP (the two boxes end in one plane) from a CLASH (one
    interior pushed through another's face), and a clash is not always a defect
    either — an axle genuinely passes through its hub. So the clash's INTENT is
    declared, the same way an interaction side is, and the report returns two
    lists a reader can act on: `undeclared_clashes` (the ones nobody claimed)
    and `declared_without_contact` (a claim that stopped being true, because a
    part moved).

    Nothing here fails a build: clashes are reported, never refused, exactly as
    before. What changes is that a report can now separate the junctions the
    asset was built with from the ones it was not. Re-declaring the pair
    replaces the reason, so a correction is one call.
    """
    for object_name in (first_name, second_name):
        if not isinstance(object_name, str) or not object_name.strip():
            raise ValueError(
                f"an object name must be a non-empty string, got {object_name!r}"
            )
        if _mesh_part(object_name) is None:
            from golem_blender.ops._objects import UnknownObject

            raise UnknownObject(
                f"no MESH object named {object_name!r} to declare a join for (a "
                f"join describes two pieces of geometry)"
            )
    if first_name == second_name:
        raise ValueError(
            f"a join needs two different parts, got {first_name!r} twice: a part "
            f"does not join itself"
        )
    if not reason.strip():
        raise ValueError(
            "a join needs a reason: say why the contact is intended (an axle "
            "through its hub, a tenon in its post)"
        )
    _DECLARED_JOINS[frozenset((first_name, second_name))] = reason.strip()
    return ObjectName(first_name)


def _combined_object(part_objects, name: str):
    """The parts' geometry as ONE mesh object built in the scene, sources untouched.

    The join arithmetic is `ops/assets._append_part_into`, the code
    `join_objects` uses, so a welded export and a join cannot disagree about
    what baking a world matrix, reversing a mirrored face and re-indexing a
    material slot means. The parts STAY in the scene: an export must not eat
    the assembly it exports.
    """
    import bmesh
    import bpy

    from golem_blender.ops.assets import _append_part_into

    materials: list = []
    slot_of: dict[str | None, int] = {}

    def slot_of_material(material_key, material):
        if material_key not in slot_of:
            slot_of[material_key] = len(materials)
            materials.append(material)
        return slot_of[material_key]

    combined_mesh = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        for part_object in part_objects:
            _append_part_into(
                working_mesh,
                part_object.data,
                part_object.matrix_world,
                slot_of_material,
            )
        working_mesh.to_mesh(combined_mesh)
    finally:
        working_mesh.free()
    for material in materials:
        combined_mesh.materials.append(material)
    combined = bpy.data.objects.new(name, combined_mesh)
    bpy.context.scene.collection.objects.link(combined)
    bpy.context.view_layer.update()
    return combined


def _reimport_measurements(glb_path, joined_name: str, budget) -> dict:
    """Import the written .glb and measure EXACTLY what it delivers.

    The file's own nodes are what an engine walks, so the object count is read
    off a real import and not off the scene that produced it; the triangle
    counts are the joined import measured raw (glTF splits vertices along
    flat-shading seams) and again after welding. Both are removed afterwards.

    `budget` is forwarded to both analyses: it says whether the UV overlap
    count is asked for at all, and the count is a pairwise test over every UV
    triangle (30.2 s measured on 131072 triangles), so a budget that allows
    overlaps must not pay for it.
    """
    import bpy

    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.heal import weld_and_dissolve
    from golem_blender.ops.primitives import remove_object_and_mesh
    from golem_blender.ops.transforms import _world_bounds_m

    objects_before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported_objects = [
        scene_object
        for scene_object in bpy.data.objects
        if scene_object not in objects_before
    ]
    imported_meshes = [
        imported_object
        for imported_object in imported_objects
        if imported_object.type == "MESH"
    ]
    try:
        if not imported_meshes:
            raise ValueError(f"{glb_path} re-imported with no mesh objects")
        minimum, maximum = _world_bounds_m(imported_meshes)
        joined = _combined_object(imported_meshes, joined_name)
        try:
            raw_report = analyze_object(joined, budget)
            weld_and_dissolve(joined.name)
            welded_report = analyze_object(joined, budget)
        finally:
            remove_object_and_mesh(joined.name)
        return {
            "object_count": len(imported_meshes),
            "dimensions_m": tuple(
                float(maximum[axis] - minimum[axis]) for axis in range(3)
            ),
            "raw": raw_report,
            "welded": welded_report,
        }
    finally:
        for imported_object in imported_objects:
            remove_object_and_mesh(imported_object.name)


def _material_names_in(glb_path) -> tuple[str, ...]:
    """The material names the written file carries, read from its own bytes."""
    from golem_blender.export.glb_report import parse_glb

    gltf, _binary = parse_glb(glb_path)
    names = [str(material.get("name", "")) for material in gltf.get("materials", [])]
    return tuple(sorted(name for name in names if name))


def _write_selection(selected_objects, path) -> int:
    """Write exactly the selected objects to `path`; return the byte count."""
    import bpy

    for scene_object in bpy.context.scene.objects:
        scene_object.select_set(scene_object in selected_objects)
    bpy.context.view_layer.objects.active = selected_objects[0]
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )
    return path.stat().st_size


def _part_gate_failures(
    part_objects, budget, deadline=None
) -> tuple[tuple[tuple[str, str], ...], int, int]:
    """Every part's own piece-gate verdict, and how much of it was measured.

    Returns `(failures, checked_count, triangle_total)`. A part is still judged
    as a prop; `checked_count` is how many parts got as far as an analysis, so a
    `truncated` report can say what it actually looked at, and `triangle_total`
    is the sum of the parts' own counts — the number the shipped file must carry.
    """
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.run.call_context import report_progress

    failures: list[tuple[str, str]] = []
    checked_count = 0
    triangle_total = 0
    part_count = len(part_objects)
    for part_index, part_object in enumerate(part_objects, start=1):
        if deadline is not None and deadline.expired():
            break
        report_progress("part gate", part_index, part_count)
        part_report = analyze_object(part_object, budget)
        checked_count += 1
        triangle_total += part_report.triangle_count
        part_failures = part_report.failures(budget)
        if part_failures:
            failures.append((part_object.name, "; ".join(part_failures)))
    else:
        report_progress("part gate", part_count, part_count)
    return tuple(failures), checked_count, triangle_total


@op()
def export_assembly(
    name: str,
    path: str,
    blend_path: str,
    keep_parts: bool = True,
    gate: Literal["none", "structure", "full"] = "full",
    budget_s: float = DEFAULT_BUDGET_S,
) -> ExportReport:
    """Ship the named assembly as ONE .glb + .blend, gated per part and verified by re-import.

    `keep_parts=True` (the default) ships the parts as their own objects, which
    is what an assembly IS: 49 closed solids sharing faces. The gate is the
    per-piece one, applied to every part, and the export fails naming the part
    that is not closed; part-vs-part interpenetration is reported by
    `assembly_report` and never fails the export, because a kit corner laps by
    design. `keep_parts=False` welds them into one mesh and REPORTS what welding
    did — its component and boundary counts, measured, not assumed — because
    welding kit pieces does not close an assembly.

    The `.blend` holds exactly what shipped: the parts, or the welded mesh.
    `blend_path` is required, as for `export_asset`: an asset without its source
    cannot be edited and re-exported. A part removed since the definition fails
    the export instead of shipping a silently shorter assembly.

    `gate` says how much to measure ("full", "structure", "none") and `budget_s`
    caps the wall-clock time, returning `truncated: true` with `skipped_checks`
    naming what did not run. The `.blend` is written BEFORE any of that, so a
    spent budget still leaves the source; a full gate on
    `SCRATCH_SAVE_MINIMUM_PARTS` or more parts also saves the whole session to
    `<output>/scratch/export_assembly.blend` first (`scratch_blend_path`).
    """
    from pathlib import Path

    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.export.blend import save_blend, validate_blend_request
    from golem_blender.export.glb_report import asset_report
    from golem_blender.ops.primitives import remove_object_and_mesh
    from golem_blender.ops.transforms import _world_bounds_m
    from golem_blender.run.call_context import Deadline, report_progress

    object_names, part_objects = _resolved_parts(name)
    unlinked = [
        object_name
        for object_name in object_names
        if object_name not in {part.name for part in part_objects}
    ]
    if unlinked:
        raise ValueError(
            f"assembly {name!r} names part(s) {unlinked} with no mesh object in "
            f"the scene; link or re-create them, or re-define the assembly"
        )
    budget_s = _validate_gate_and_budget(gate, budget_s)

    welded_name = f"{name}{WELDED_OBJECT_SUFFIX}"
    shipped_names = (
        tuple(part.name for part in part_objects) if keep_parts else (welded_name,)
    )
    # Both arguments are checked BEFORE anything is written, so no .glb is ever
    # left without its source.
    _, blend_destination = validate_blend_request(shipped_names, blend_path)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = Deadline(budget_s)
    # SAVE FIRST, GATE SECOND. The gate is what can outlive a socket timeout; the
    # files are what an hour of assembly work is worth. So the session's safety
    # copy, then the .blend, are written before the first measurement — and the
    # .blend is the SHIPPED source, verified by `save_blend` re-reading it.
    scratch_blend_path, scratch_save_error = _scratch_before_measuring(
        "export_assembly", gate, len(part_objects)
    )
    shipped_objects = part_objects
    combined = None
    if not keep_parts or gate == "full":
        combined = _combined_object(part_objects, welded_name)
        if not keep_parts:
            shipped_objects = [combined]

    skipped_checks: list[str] = []
    truncated = False
    budget = MeshBudget()
    part_failures: tuple[tuple[str, str], ...] = ()
    gate_checked_parts = 0
    expected_triangle_count = 0
    pre_export_report = None
    measurements = None
    interaction = InteractionReport(assembly_name=name, sides=(), blocked=())

    try:
        report_progress("save .blend", 0, 1)
        blend_report = save_blend(shipped_names, blend_destination)
        report_progress("save .blend", 1, 1)
        file_size_bytes = _write_selection(shipped_objects, output_path)
        file_report = asset_report(output_path)

        minimum, maximum = _world_bounds_m(part_objects)
        pre_export_dimensions_m = tuple(
            float(maximum[axis] - minimum[axis]) for axis in range(3)
        )
        expected_material_names = tuple(
            sorted(
                {
                    material.name
                    for part_object in part_objects
                    for material in part_object.data.materials
                    if material is not None
                }
            )
        )

        if gate == "none":
            skipped_checks.extend(
                (
                    PART_GATE_CHECK,
                    CLEARANCE_CHECK,
                    COMBINED_ANALYSIS_CHECK,
                    REIMPORT_CHECK,
                )
            )
        else:
            report_progress("part gate", 0, len(part_objects))
            part_failures, gate_checked_parts, expected_triangle_count = (
                _part_gate_failures(part_objects, budget, deadline)
            )
            if gate_checked_parts < len(part_objects):
                truncated = True

            if deadline.expired():
                truncated = True
                skipped_checks.append(CLEARANCE_CHECK)
            else:
                interaction = _interaction(name, part_objects)

            if gate == "full":
                if deadline.expired():
                    truncated = True
                    skipped_checks.append(COMBINED_ANALYSIS_CHECK)
                elif combined is not None:
                    report_progress("combined analysis", 0, 1)
                    pre_export_report = analyze_object(combined, budget)
                    report_progress("combined analysis", 1, 1)
                if deadline.expired():
                    truncated = True
                    skipped_checks.append(REIMPORT_CHECK)
                else:
                    report_progress("re-import", 0, 1)
                    measurements = _reimport_measurements(
                        output_path, f"{name}{REIMPORT_OBJECT_SUFFIX}", budget
                    )
                    report_progress("re-import", 1, 1)
            else:
                skipped_checks.extend((COMBINED_ANALYSIS_CHECK, REIMPORT_CHECK))
    finally:
        # The combined mesh is the FULL gate's measurement target as well as a
        # possible shipped object, so it lives until every check is done; both
        # files are written by then, so it is removed exactly as before.
        if combined is not None:
            remove_object_and_mesh(welded_name)

    return ExportReport(
        export_path=output_path,
        file_size_bytes=file_size_bytes,
        pre_export=pre_export_report,
        reimported_raw=measurements["raw"] if measurements else None,
        reimported_welded=measurements["welded"] if measurements else None,
        pre_export_dimensions_m=pre_export_dimensions_m,
        reimported_dimensions_m=(
            measurements["dimensions_m"] if measurements else pre_export_dimensions_m
        ),
        file_report=file_report,
        blend=blend_report,
        assembly_name=name,
        keep_parts=len(shipped_objects),
        part_count=len(part_objects),
        part_failures=part_failures,
        reimported_object_count=(measurements["object_count"] if measurements else 0),
        material_names=_material_names_in(output_path),
        expected_material_names=expected_material_names,
        expected_root_node_names=shipped_names,
        blocked_sides=interaction.blocked,
        gate=gate,
        truncated=truncated,
        skipped_checks=_ordered_checked_names(skipped_checks),
        gate_checked_parts=gate_checked_parts,
        expected_triangle_count=expected_triangle_count,
        scratch_blend_path=scratch_blend_path,
        scratch_save_error=scratch_save_error,
    )


def _ordered_checked_names(skipped_checks) -> tuple[str, ...]:
    """The skipped checks in the order the export runs them, so a list reads as a sequence."""
    order = (PART_GATE_CHECK, CLEARANCE_CHECK, COMBINED_ANALYSIS_CHECK, REIMPORT_CHECK)
    unique = set(skipped_checks)
    return tuple(name for name in order if name in unique)


def _safe_path_component(text: str) -> str:
    """A file-name-safe rendering of an object name: 'Wall North' -> 'Wall_North'."""
    safe = "".join(
        character if (character.isalnum() or character in "-_") else "_"
        for character in text
    )
    return safe or "unnamed"


def _focus_pairs(focus) -> list[tuple[str, str]]:
    """The `focus` argument as pairs of names, refusing anything else loudly."""
    names = list(focus)
    if len(names) % 2:
        raise ValueError(
            f"focus takes names in PAIRS — a junction is two objects — got "
            f"{len(names)}: {names}"
        )
    return [(names[index], names[index + 1]) for index in range(0, len(names), 2)]


@op()
def render_assembly(
    name: str,
    views: tuple[str, ...] = ASSEMBLY_VIEWS,
    focus: list[str] | None = None,
    output_dir: str | None = None,
) -> list[str]:
    """Render the whole assembly, then a tight close-up per named PAIR from three angles.

    Twelve of the blacksmith session's defects were found only by LOOKING — a
    bracket 111.9 cm off its wall, a board hung flat, a pipe through a bellows,
    two walls 11.10 cm apart — and each needed a close-up of TWO named objects
    at an angle that shows their junction. So `focus` takes names two at a time,
    every returned path names its own pair, and each close-up is FRAMED BY THE
    PAIR (orthographic scale and frame aspect both fitted to it), so the
    junction dominates the image instead of sitting in a building-sized frame.

    A focus capture hides the assembly's other parts for the length of that
    render — a wall in front of the junction is exactly what hid these defects —
    and restores them afterwards. The whole-assembly sheet frames every part
    together.
    """
    from pathlib import Path

    import bpy

    from golem_blender.capture.views import CaptureSettings, capture_views

    _object_names, part_objects = _resolved_parts(name)
    if not part_objects:
        raise ValueError(
            f"assembly {name!r} has no mesh part in the scene, so there is "
            f"nothing to render"
        )

    root_directory = (
        Path(output_dir)
        if output_dir is not None
        else Path(bpy.app.tempdir) / f"assembly_{_safe_path_component(name)}"
    )

    written: list[str] = []
    captured = capture_views(
        part_objects[0],
        root_directory,
        CaptureSettings(),
        extra_objects=tuple(part_objects[1:]),
        view_names=tuple(views),
    )
    written.extend(str(captured[view_name]) for view_name in captured)

    known_names = {part.name for part in part_objects}
    for first_name, second_name in _focus_pairs(focus or ()):
        unknown = [
            part for part in (first_name, second_name) if part not in known_names
        ]
        if unknown:
            raise ValueError(
                f"focus names {unknown}, which are not parts of assembly "
                f"{name!r} (parts: {sorted(known_names)})"
            )
        pair_directory = root_directory / (
            f"focus_{_safe_path_component(first_name)}_"
            f"{_safe_path_component(second_name)}"
        )
        hidden_parts = [
            part for part in part_objects if part.name not in (first_name, second_name)
        ]
        previous_hidden = [bool(part.hide_render) for part in hidden_parts]
        try:
            for part in hidden_parts:
                part.hide_render = True
            captured_pair = capture_views(
                bpy.data.objects[first_name],
                pair_directory,
                CaptureSettings(fit_projection=True),
                extra_objects=(bpy.data.objects[second_name],),
                view_names=FOCUS_VIEWS,
            )
        finally:
            for part, previous in zip(hidden_parts, previous_hidden):
                part.hide_render = previous
        written.extend(str(captured_pair[view_name]) for view_name in captured_pair)

    return written
