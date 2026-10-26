"""Which two same-facing triangles share a plane closely enough to z-fight.

The game draws this geometry with an ORTHOGRAPHIC camera, so its depth buffer is
linear and its resolution is uniform over the whole range. With `near` 0.1 m,
`far` 6000 m and 24 depth bits, one quantum is (6000 - 0.1) / 2**24 = 0.358 mm.
Two faces 5 mm apart are 14 quanta apart and the depth test resolves them the
same way every frame; two flush faces are 0 quanta apart and the GPU picks a
winner per pixel and flips it as the camera moves. So the tolerance is 1 mm
(~3 quanta) and the report says how many QUANTA each pair is actually apart,
because that number, not the metre gap, is what decides whether a pair can
flicker in the engine the asset ships to.

What counts as a pair (`coplanar_triangle_pairs`):
  * the two triangles face the same way — normals within `normal_tolerance_deg`;
  * they lie in (nearly) the same plane — the second's centroid is within
    5 cm of the first's plane, and the overlap polygon's corners, lifted onto
    the first's plane, are at most `tolerance_m` from the second's;
  * their projections overlap by more than `minimum_overlap_m2`;
  * they are not the same face (two triangles of one quad are neighbours, not a
    defect).
Every quantity is measured in the FIRST triangle's plane, so a pair is symmetric
in its members but the reported polygon belongs to `first`.

Pure arithmetic: no bpy, no numpy — `blender/.venv` has no numpy, so this module
must import without Blender and without the venv's site-packages.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# The game's iso camera: an orthographic projection with this depth range and
# this many bits (`src/prototype/iso_camera.rs`). A LINEAR depth buffer is what
# makes "quanta" a fixed length; a perspective one would need the distance too.
DEFAULT_NEAR_M = 0.1
DEFAULT_FAR_M = 6000.0
DEFAULT_DEPTH_BITS = 24

# ~3 quanta of the buffer above: close enough to swap under a sub-millimetre
# nudge, far enough that a MODELLED gap (a crate's iron band 9 mm proud of its
# plank) is not reported. The measured cost of a 1 cm tolerance was ~50 pieces
# reported for deliberate clearances.
DEFAULT_TOLERANCE_M = 0.001
DEFAULT_NORMAL_TOLERANCE_DEG = 2.0
# 1 cm^2. Below this the shared area is a sliver the modeller did not mean.
DEFAULT_MINIMUM_OVERLAP_M2 = 1.0e-4
# A triangle this small has no reliable normal and no area worth reporting.
MINIMUM_TRIANGLE_AREA_M2 = 1.0e-9
# Broadphase cell on each unit-normal component. Two normals within 2 degrees
# differ by at most 0.035 in a component, so neighbours (+-1 cell) always cover
# a legal pair; the cell only has to keep the candidate list small.
NORMAL_CELL = 0.05
# Sanctuary's plane prefilter: the second centroid must be this close to the
# first triangle's plane before the exact clip is worth doing. Deliberately
# looser than `tolerance_m` — it is a filter, not a verdict.
BROADPHASE_PLANE_SLACK_M = 0.05
# Projected triangles that only touch along an edge cannot overlap by 1 cm^2,
# so anything penetrating less than 0.1 mm on an in-plane axis is dropped before
# the exact clip. Ported from Sanctuary's `_pair_overlaps` SAT prefilter.
SAT_MINIMUM_PENETRATION_M = 1.0e-4
# Sanctuary's ray start: 12 mm in front of the overlap centroid, so the ray
# leaves from outside both faces and cannot immediately re-hit them.
VISIBILITY_OFFSET_M = 0.012
# A view only counts as SEEING the pair when the pair's normal faces it by more
# than this (about 1.1 degrees). Sanctuary's constant, kept exact.
FACING_MINIMUM_DOT = 0.02
# Two depth quanta apart is the point where the depth test resolves a pair the
# same way every frame. Below it the winner is rounding noise.
RESOLVED_GAP_QUANTA = 2.0

# Report order, and the vocabulary of `kind`. A declared contact is not a
# separate kind: the row keeps its geometry-derived kind and carries
# `declared_reason`, so a reader still sees WHAT the geometry does.
KINDS = ("flicker", "clearance", "buried", "back_facing", "same_material")


@dataclass(frozen=True)
class SoupTriangle:
    """One world-space triangle and who owns it."""

    corners: tuple[tuple[float, float, float], ...]  # world, 3 corners
    normal: tuple[float, float, float]
    owner: int  # index into the caller's owner table
    face_index: int
    material: str


@dataclass(frozen=True)
class TrianglePair:
    """Two coplanar triangles, and what their overlap measures."""

    first: int  # index into the soup; always < second
    second: int
    overlap_m2: float
    separation_m: float
    centroid: tuple[float, float, float]
    polygon: tuple[tuple[float, float, float], ...]  # lifted onto `first`'s plane


def _subtract(first, second):
    return (
        first[0] - second[0],
        first[1] - second[1],
        first[2] - second[2],
    )


def _add(first, second):
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _scale(vector, factor):
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _dot(first, second):
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _length(vector):
    return math.sqrt(_dot(vector, vector))


def triangle_normal(corners) -> tuple[float, float, float]:
    """Unit normal of a triangle from its winding (right-hand rule), or zeros."""
    edge_1 = _subtract(corners[1], corners[0])
    edge_2 = _subtract(corners[2], corners[0])
    cross = _cross(edge_1, edge_2)
    size = _length(cross)
    if size == 0.0:
        return (0.0, 0.0, 0.0)
    return _scale(cross, 1.0 / size)


def triangle_area_m2(corners) -> float:
    """Area of a triangle by the half cross-product's length."""
    edge_1 = _subtract(corners[1], corners[0])
    edge_2 = _subtract(corners[2], corners[0])
    return 0.5 * _length(_cross(edge_1, edge_2))


def triangle_centroid(corners) -> tuple[float, float, float]:
    """Mean of a triangle's three corners."""
    return (
        (corners[0][0] + corners[1][0] + corners[2][0]) / 3.0,
        (corners[0][1] + corners[1][1] + corners[2][1]) / 3.0,
        (corners[0][2] + corners[1][2] + corners[2][2]) / 3.0,
    )


def clip_polygon(subject, clip) -> list[tuple[float, float]]:
    """Sutherland-Hodgman: `subject` clipped by the convex CCW polygon `clip`.

    2D tuples. The `>= 0` convention is Sanctuary's own (ported exactly): a
    corner ON the clipping edge is kept, which keeps a shared edge producing a
    degenerate polygon for the area test to reject rather than losing the
    interior overlap entirely.
    """
    out = list(subject)
    for index in range(len(clip)):
        ax, ay = clip[index]
        bx, by = clip[(index + 1) % len(clip)]
        source, out = out, []
        if not source:
            break
        for corner_index in range(len(source)):
            p = source[corner_index]
            q = source[(corner_index + 1) % len(source)]
            sp = (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
            sq = (bx - ax) * (q[1] - ay) - (by - ay) * (q[0] - ax)
            if sp >= 0.0:
                out.append(p)
            if (sp >= 0.0) != (sq >= 0.0):
                t = sp / (sp - sq)
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def _polygon_area(polygon) -> float:
    """Shoelace area of a 2D polygon, unsigned."""
    total = 0.0
    for index in range(len(polygon)):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % len(polygon)]
        total += x1 * y2 - x2 * y1
    return 0.5 * abs(total)


def triangle_overlap(first: SoupTriangle, second: SoupTriangle):
    """(area m^2, largest separation m, centroid, polygon) of two triangles' overlap.

    Measured in `first`'s plane: u is `first`'s edge 0, v = n x u, both triangles
    are flipped to counter-clockwise in that frame and `second` is clipped by
    `first`. The separation is the largest distance of the overlap polygon's
    corners (lifted back onto `first`'s plane) from `second`'s plane, which is
    the largest anywhere in the overlap. Fewer than 3 corners after clipping
    means no overlap: (0, 0, origin, ()).
    """
    edge = _subtract(first.corners[1], first.corners[0])
    edge_length = _length(edge)
    if edge_length == 0.0:
        return 0.0, 0.0, (0.0, 0.0, 0.0), ()
    u = _scale(edge, 1.0 / edge_length)
    v = _cross(first.normal, u)
    origin = first.corners[0]

    def flatten(corners):
        points = [
            (_dot(_subtract(corner, origin), u), _dot(_subtract(corner, origin), v))
            for corner in corners
        ]
        signed = (points[1][0] - points[0][0]) * (points[2][1] - points[0][1]) - (
            points[1][1] - points[0][1]
        ) * (points[2][0] - points[0][0])
        return points if signed > 0.0 else points[::-1]

    polygon = clip_polygon(flatten(second.corners), flatten(first.corners))
    if len(polygon) < 3:
        return 0.0, 0.0, (0.0, 0.0, 0.0), ()

    third_plane_offset = _dot(second.normal, second.corners[0])
    lifted = [_add(origin, _add(_scale(u, x), _scale(v, y))) for x, y in polygon]
    separation = max(
        abs(_dot(second.normal, corner) - third_plane_offset) for corner in lifted
    )
    centroid = (
        sum(corner[0] for corner in lifted) / len(lifted),
        sum(corner[1] for corner in lifted) / len(lifted),
        sum(corner[2] for corner in lifted) / len(lifted),
    )
    return _polygon_area(polygon), separation, centroid, tuple(lifted)


def _in_plane_penetration_m(first: SoupTriangle, second: SoupTriangle) -> float:
    """Smallest overlap of the two triangles projected on `first`'s dominant plane.

    Six separating axes — three edge normals from each triangle — and the answer
    is the smallest of the six overlaps: positive means the projections really
    overlap, and a value under `SAT_MINIMUM_PENETRATION_M` means they only touch
    along an edge. Ported from Sanctuary's `_pair_overlaps` SAT prefilter.
    """
    normal = first.normal
    axis = max(range(3), key=lambda index: abs(normal[index]))
    u_index, v_index = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[axis]

    def project(corners):
        return [(corner[u_index], corner[v_index]) for corner in corners]

    first_2d = project(first.corners)
    second_2d = project(second.corners)
    edges = []
    for points in (first_2d, second_2d):
        for index in range(3):
            p = points[index]
            q = points[(index + 1) % 3]
            edges.append((q[0] - p[0], q[1] - p[1]))
    smallest = math.inf
    for dx, dy in edges:
        length = math.sqrt(dx * dx + dy * dy)
        if length < 1.0e-12:
            continue
        nx, ny = -dy / length, dx / length
        first_projection = [nx * x + ny * y for x, y in first_2d]
        second_projection = [nx * x + ny * y for x, y in second_2d]
        overlap = min(max(first_projection), max(second_projection)) - max(
            min(first_projection), min(second_projection)
        )
        smallest = min(smallest, overlap)
    return smallest


def _boxes_overlap(first: SoupTriangle, second: SoupTriangle, slack: float) -> bool:
    """Do the two triangles' AABBs overlap, with `slack` of give per side?"""
    for axis in range(3):
        first_low = min(corner[axis] for corner in first.corners)
        first_high = max(corner[axis] for corner in first.corners)
        second_low = min(corner[axis] for corner in second.corners)
        second_high = max(corner[axis] for corner in second.corners)
        if first_low > second_high + slack or second_low > first_high + slack:
            return False
    return True


def coplanar_triangle_pairs(
    soup,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    normal_tolerance_deg: float = DEFAULT_NORMAL_TOLERANCE_DEG,
    minimum_overlap_m2: float = DEFAULT_MINIMUM_OVERLAP_M2,
) -> list[TrianglePair]:
    """Every same-facing, same-plane, overlapping triangle pair in the soup.

    Broadphase is a hash on the rounded normal (27 neighbour cells searched), so
    the cost is proportional to the pairs that could possibly match rather than
    to the square of the triangle count: a 20k-triangle kit measured in a second
    rather than a minute. Pairs come back sorted by (first, second).
    """
    triangles = [
        triangle
        for triangle in soup
        if triangle_area_m2(triangle.corners) > MINIMUM_TRIANGLE_AREA_M2
    ]
    if len(triangles) < 2:
        return []
    cos_limit = math.cos(math.radians(normal_tolerance_deg))
    cells: dict[tuple[int, int, int], list[int]] = {}
    for index, triangle in enumerate(triangles):
        key = tuple(round(component / NORMAL_CELL) for component in triangle.normal)
        cells.setdefault(key, []).append(index)

    centroids = [triangle_centroid(triangle.corners) for triangle in triangles]
    planes = [_dot(triangle.normal, triangle.corners[0]) for triangle in triangles]
    found: list[TrianglePair] = []
    for index, triangle in enumerate(triangles):
        key = tuple(round(component / NORMAL_CELL) for component in triangle.normal)
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    candidates.extend(
                        cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                    )
        for other in candidates:
            if other <= index:
                continue
            second = triangles[other]
            if _dot(triangle.normal, second.normal) < cos_limit:
                continue
            if abs(_dot(triangle.normal, centroids[other]) - planes[index]) > (
                BROADPHASE_PLANE_SLACK_M
            ):
                continue
            if triangle.owner == second.owner and (
                triangle.face_index == second.face_index
            ):
                continue
            if not _boxes_overlap(triangle, second, tolerance_m):
                continue
            if _in_plane_penetration_m(triangle, second) <= (SAT_MINIMUM_PENETRATION_M):
                continue
            area, separation, centroid, polygon = triangle_overlap(triangle, second)
            if area > minimum_overlap_m2 and separation <= tolerance_m:
                found.append(
                    TrianglePair(
                        first=index,
                        second=other,
                        overlap_m2=area,
                        separation_m=separation,
                        centroid=centroid,
                        polygon=polygon,
                    )
                )
    found.sort(key=lambda pair: (pair.first, pair.second))
    return found


def depth_quantum_m(
    near_m: float = DEFAULT_NEAR_M,
    far_m: float = DEFAULT_FAR_M,
    depth_bits: int = DEFAULT_DEPTH_BITS,
) -> float:
    """One step of an orthographic depth buffer: (far - near) / 2**bits.

    Linear, because the game's iso camera is orthographic; a perspective camera
    has no single quantum and this number would not describe it.
    """
    return (far_m - near_m) / float(2**depth_bits)


def classify(
    *,
    same_material_ignored: bool,
    facing_any: bool,
    visible: bool,
    quanta: float,
) -> str:
    """Which kind of pair this is, in the order the report sorts them."""
    if same_material_ignored:
        return "same_material"
    if not facing_any:
        return "back_facing"
    if not visible:
        return "buried"
    if quanta >= RESOLVED_GAP_QUANTA:
        return "clearance"
    return "flicker"


def _quad_triangle(corners, owner: int, face_index: int, material: str):
    return SoupTriangle(
        corners=tuple(corners),
        normal=triangle_normal(corners),
        owner=owner,
        face_index=face_index,
        material=material,
    )


def control_soups():
    """(flush, gap) soups: the detector's own controls, and its self-test.

    Flush: two 1 m quads facing +Z at z = 0, the second offset (0.25, 0.25, 0)
    — different owners, different materials, 0 m apart. A detector that does not
    report this cannot recognise the defect it exists for.

    Gap: the same two quads with the second at z = 0.005 — 5 mm, five times the
    tolerance and 14 depth quanta. A detector that reports this cannot tell a
    defect from a modelled clearance. Both are checked before any scene is
    measured, so a broken detector says so instead of reporting zero pairs and
    looking like a clean asset.
    """

    def soup_with_second_height(second_height: float):
        soup = []
        for owner, (dx, dy, height, material) in enumerate(
            ((0.0, 0.0, 0.0, "A"), (0.25, 0.25, second_height, "B"))
        ):
            corners = [
                (dx + 0.0, dy + 0.0, height),
                (dx + 1.0, dy + 0.0, height),
                (dx + 1.0, dy + 1.0, height),
                (dx + 0.0, dy + 1.0, height),
            ]
            soup.append(
                _quad_triangle((corners[0], corners[1], corners[2]), owner, 0, material)
            )
            soup.append(
                _quad_triangle((corners[0], corners[2], corners[3]), owner, 1, material)
            )
        return soup

    return soup_with_second_height(0.0), soup_with_second_height(0.005)
