"""Did the boolean solver actually CUT? Measure the cutter's region in the result.

Measured need, 2026-10-25 (a parapet with eight quatrefoil holes): the cutter
was built from eight overlapping cylinders, so its own mesh intersected itself.
The EXACT solver returned the target WITHOUT the holes — and the result still
differed from the input (400 triangles against the input's), so the no-op check
in `ops/booleans._apply_boolean` stayed quiet and the gate passed a parapet with
no holes in it. A boolean that silently drops its cut is a wrong answer that no
existing check names, in either direction:

- the OPERAND's own shape is never inspected, so a self-intersecting cutter
  reaches the solver at all (`_count_self_intersecting_pairs` is the
  measurement, from `analyze.mesh_checks`);
- the RESULT is compared to the input by counts and positions only, so "the
  mesh changed" is mistaken for "the cut happened".

This module answers the second question directly: take the volume the cutter
and the target SHARED before the operation, and ask how much of it is still
solid after. A correct difference empties that whole region; a dropped cut
leaves it all behind.

Why not parity from triangle centroids (`mesh_checks`' flipped-normal check) or
a depth probe (`ops/features._opening_sides`): both answer a different question.
The first asks whether a triangle's winding faces out of its own solid; the
second asks how deep a face's opening runs. Neither asks "is this point inside
the result", which is what a missing cut changes.

TWO FRAMES, ONE MEASUREMENT. Every tree here is WORLD space, built by
`analyze.interaction._world_bvhs` (which transforms the evaluated triangles).
`BVHTree.FromObject` builds in the OBJECT's local space and would silently
measure the wrong frame — the failure that already cost four probes in
`analyze/interaction.py`.

Importable without Blender: the module-level names are plain Python, and bpy /
mathutils are imported inside the functions that need them.
"""

from __future__ import annotations

from dataclasses import dataclass

# Probe grid over the shared region: 8^3 = 512 points, of which the ones inside
# BOTH solids and off both surfaces are counted. A cut region is a solid volume,
# so even a thin cutter carries points; a grid finer than this costs ray casts
# per point and buys nothing a difference either does or does not do.
CUT_PROBE_GRID = 8
# A point this close to the cutter's or the target's surface is not probed: a
# CORRECT cut puts new faces exactly on the cutter's surface, so a point that
# sits on it is inside the result's skin and would read solid either way.
CUT_PROBE_SURFACE_MARGIN_M = 1.0e-4
# More than this fraction of the probed region still solid means the cut did not
# happen. Not zero: a coplanar sliver at a region's edge survives a correct cut,
# and the solver's own tessellation is not exact.
CUT_REMAINING_FRACTION_LIMIT = 0.02
# Three oblique directions, normalised in code. Never axis-aligned: a grid point
# on a box's symmetry line would otherwise ray along that box's own edge and
# read a grazing hit as a crossing. A point is inside when at least two of the
# three directions agree — one ray can always graze something.
INSIDE_VOTE_DIRECTIONS = (
    (0.31, 0.53, 0.79),
    (-0.67, 0.23, 0.71),
    (0.43, -0.83, 0.37),
)
# How many of the three directions must read an odd crossing count. Two of
# three: a single ray that grazes an edge reports an even count by accident.
INSIDE_VOTE_MINIMUM = 2


@dataclass(frozen=True)
class CutRegionReport:
    """How much of the cutter's overlap with the target survived the cut."""

    # Points inside BOTH the cutter and the target-before, off both surfaces.
    probed_point_count: int
    # Of those, the ones still inside the result.
    remaining_point_count: int

    @property
    def remaining_fraction(self) -> float:
        """How much of the probed region is still solid; 0.0 when nothing was probed."""
        if self.probed_point_count == 0:
            return 0.0
        return self.remaining_point_count / self.probed_point_count


def _probe_points(
    minimum, maximum, grid: int = CUT_PROBE_GRID
) -> list[tuple[float, float, float]]:
    """Cell CENTRES of a `grid`^3 lattice over the box, so no point sits on a face."""
    from mathutils import Vector

    low = Vector((float(minimum[0]), float(minimum[1]), float(minimum[2])))
    high = Vector((float(maximum[0]), float(maximum[1]), float(maximum[2])))
    span = high - low
    points: list[tuple[float, float, float]] = []
    for first_index in range(grid):
        for second_index in range(grid):
            for third_index in range(grid):
                point = low + Vector(
                    (
                        span.x * (first_index + 0.5) / grid,
                        span.y * (second_index + 0.5) / grid,
                        span.z * (third_index + 0.5) / grid,
                    )
                )
                points.append((point.x, point.y, point.z))
    return points


def is_inside(tree, point) -> bool:
    """True when the point is inside the closed solid `tree` was built from.

    Ray parity per direction: cast, step past each hit by `PARITY_RAY_OFFSET_M`
    and cast again, stopping at `PARITY_MAXIMUM_CASTS`. An odd crossing count
    means the point was inside. `PARITY_RAY_OFFSET_M` is the step
    `mesh_checks._count_flipped_normal_triangles` uses for exactly this reason:
    without it the next cast re-hits the surface it just crossed.
    """
    from mathutils import Vector

    from golem_blender.analyze.mesh_checks import (
        PARITY_MAXIMUM_CASTS,
        PARITY_RAY_OFFSET_M,
    )

    if tree is None:
        return False
    origin = Vector((float(point[0]), float(point[1]), float(point[2])))
    inside_votes = 0
    for direction in INSIDE_VOTE_DIRECTIONS:
        heading = Vector(direction).normalized()
        ray_origin = origin.copy()
        crossing_count = 0
        for _ in range(PARITY_MAXIMUM_CASTS):
            hit_location = tree.ray_cast(ray_origin, heading)[0]
            if hit_location is None:
                break
            crossing_count += 1
            ray_origin = hit_location + heading * PARITY_RAY_OFFSET_M
        if crossing_count % 2 == 1:
            inside_votes += 1
    return inside_votes >= INSIDE_VOTE_MINIMUM


def _distance_to_surface(tree, point) -> float:
    """How far the point is from the tree's surface; `inf` when it has none."""
    from mathutils import Vector

    if tree is None:
        return float("inf")
    nearest = tree.find_nearest(Vector((point[0], point[1], point[2])))
    if nearest is None or nearest[3] is None:
        return float("inf")
    return float(nearest[3])


def measure_surviving_region(
    target_before_tree,
    cutter_tree,
    target_minimum,
    target_maximum,
) -> int:
    """How many probe points of the target the cutter does NOT touch.

    The complement of `measure_cut_region` over the TARGET's own box: material a
    DIFFERENCE has no reason to remove. Measured only when a result came back
    EMPTY, to tell a cutter that legitimately consumed the whole target (the
    complement is zero, so nothing had to survive) from a solver that destroyed
    it (the complement is not zero, and none of it is there). Measured, 2026-10-25
    on the parapet: with the operand guard patched out, the EXACT solver returned
    a `Parapet` of ZERO polygons — a worse outcome than the dropped cut, and one
    no count-based check can see because an empty mesh "changed".
    """
    surviving_point_count = 0
    for point in _probe_points(target_minimum, target_maximum):
        if not is_inside(target_before_tree, point):
            continue
        if is_inside(cutter_tree, point):
            continue
        if _distance_to_surface(target_before_tree, point) < CUT_PROBE_SURFACE_MARGIN_M:
            continue
        if _distance_to_surface(cutter_tree, point) < CUT_PROBE_SURFACE_MARGIN_M:
            continue
        surviving_point_count += 1
    return surviving_point_count


def measure_cut_region(
    target_before_tree,
    cutter_tree,
    result_tree,
    region_minimum,
    region_maximum,
) -> CutRegionReport:
    """How much of `cutter ∩ target-before` is still solid in the result.

    The region is the two boxes' intersection (`ops.transforms._world_bounds_m`
    supplies both); the probe lattice is `CUT_PROBE_GRID`^3 cell centres. A point
    counts only when it is inside BOTH the cutter and the target as they were
    before the operation, and at least `CUT_PROBE_SURFACE_MARGIN_M` off both
    surfaces: a correct cut leaves new faces exactly on the cutter's surface, so
    a point there is inside the result's skin and tells nobody anything.

    `result_tree` may be None — no result to measure — and then every probed
    point reads as remaining, which is the honest answer.
    """
    probed_point_count = 0
    remaining_point_count = 0
    for point in _probe_points(region_minimum, region_maximum):
        if not is_inside(cutter_tree, point):
            continue
        if not is_inside(target_before_tree, point):
            continue
        if _distance_to_surface(cutter_tree, point) < CUT_PROBE_SURFACE_MARGIN_M:
            continue
        if _distance_to_surface(target_before_tree, point) < CUT_PROBE_SURFACE_MARGIN_M:
            continue
        probed_point_count += 1
        if result_tree is not None and is_inside(result_tree, point):
            remaining_point_count += 1
    return CutRegionReport(
        probed_point_count=probed_point_count,
        remaining_point_count=remaining_point_count,
    )
