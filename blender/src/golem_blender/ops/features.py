"""Measure HOW an object faces: its surface height, its pitch, its deepest opening, its far side.

Measured need, 2026-10-24, in the live bakery session: four questions came up
over and over, and every one of them was answered by a hand-written
`run_python` snippet that re-derived world-space raycasts and a plane fit from
scratch — the escape hatch, used for measurements, which is exactly what the
escape hatch exists not to be used for:

- "how high is this surface at this plan point?" — laying a board on a table,
  standing a crate on a shelf, checking a floor is where the plan says;
- "what is this face's pitch?" — a roof panel, a ramp, a tabletop that was
  supposed to be level and is not. Four snippets fitted four planes;
- "which side of this part is its opening?" — the oven whose mouth faced its
  twin, the spout sunk in the wall. `analyze/interaction.py` records why the
  side cannot be INFERRED (it is intent) and measures clear space from a
  DECLARED side; this op measures the thing that can be measured, so the
  declaration has evidence: how deep the part reads when probed inward from
  each of its six local box faces;
- "which side of this part points away from that one?" — a wall against a
  plinth, a shelf against a backing board. Pure arithmetic on two world boxes.

Every ray here is a WORLD-space ray against a WORLD-space BVH, for the reason
`analyze/interaction.py` paid for once already: `BVHTree.FromObject` builds in
the object's LOCAL space, so a world ray against it silently measures a frame
the viewport does not show. `_world_bvhs` is imported from there rather than
copied.

WHAT THIS OP IS NOT: a gate. `opening` reports how deep a side reads, and an
open-sided piece (a table, a hollow barrel) legitimately reads deep — the
measurement feeds `declare_interaction_side`, it does not replace the
declaration, and it is never a reason to refuse an export.

MAIN THREAD ONLY: every call below touches bpy/mathutils.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
from typing import Literal

from golem_blender.analyze.interaction import (
    INTERACTION_SIDES,
    SIDE_LOCAL_NORMAL,
    _side_normal_world,
    _world_bvhs,
)
from golem_blender.ops._contract import op
from golem_blender.ops.selectors import FaceSelector, select_faces

FEATURE_KINDS = ("surface_height", "plane_fit", "opening", "exterior_face")

# How far above the object's own top a surface probe starts. A metre clears any
# part this op is asked about and keeps the ray's origin outside its box, so the
# probe measures the object's own surface and never its underside.
SURFACE_PROBE_ABOVE_M = 1.0
# Rays across each side of the opening probe. 12 x 12 = 144 matches
# `analyze/interaction.CLEARANCE_GRID`, so the two measurements of one side are
# taken at the same resolution and can be read side by side.
OPENING_GRID = 12
# Rays start this far outside the face, so a ray entering exactly on the plane
# does not graze coincident geometry at zero distance.
OPENING_RAY_OFFSET_M = 0.002
# Fewer points than this cannot define a plane, so a fit is refused rather than
# returned as a degenerate normal.
MINIMUM_PLANE_POINTS = 3
# A direction shorter than this is not a direction: two objects with the same
# bbox centre give no side that points away.
MINIMUM_DIRECTION_LENGTH = 1.0e-6
_FLOAT_DIGITS = 4


@dataclass(frozen=True)
class SideDepth:
    """How deep one bbox side of an object reads when probed inward."""

    # The side's name in the object's LOCAL frame (`front` is local -Y, the
    # documented interaction side).
    side: str
    # The side's outward direction in WORLD space, so a reader can see which way
    # the asset ended up turned.
    normal: tuple[float, float, float]
    # The mean and worst depth a ray reached into the object, in metres. A ray
    # that meets nothing counts as `box_depth_m`, because a hole has no floor.
    mean_depth_m: float
    maximum_depth_m: float
    # The fraction of the grid whose ray passed clean through the side.
    through_fraction: float
    # The extent of the object's LOCAL box along this side's axis: the depth a
    # solid part would read.
    box_depth_m: float


@dataclass(frozen=True)
class FeatureReport:
    """One measurement of how an object faces. Numbers, not opinions."""

    object_name: str
    kind: str
    # surface_height: the ray met the object.
    hit: bool = False
    # The measurement's own point in world space: where the ray met the surface
    # (surface_height) or the fitted plane's centroid (plane_fit).
    point_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # The fitted plane's unit normal, and its PITCH from horizontal in degrees:
    # 0 is level, 90 is a wall. For surface_height these are the met face's own.
    normal: tuple[float, float, float] = (0.0, 0.0, 0.0)
    slope_deg: float = 0.0
    # plane_fit: how many selected faces and unique vertices it fitted, and how
    # far the vertices stray from the fitted plane.
    face_count: int = 0
    vertex_count: int = 0
    residual_m: float = 0.0
    maximum_residual_m: float = 0.0
    # opening: every side of the object's local box, and which reads deepest.
    sides: tuple[SideDepth, ...] = ()
    deepest_side: str = ""
    # exterior_face: the object it was measured against, the side that points
    # away from it, and every side's alignment along that direction (-1 is
    # directly towards it, +1 directly away).
    against_name: str = ""
    facing_side: str = ""
    side_alignments: tuple[tuple[str, float], ...] = ()


# A rotation this small leaves the matrix effectively diagonal: the off-diagonal
# energy is under a relative 1e-18, which is far below what a vertex coordinate
# in metres can resolve.
_JACOBI_TOLERANCE = 1.0e-18
_JACOBI_MAXIMUM_SWEEPS = 64


def _smallest_eigenvector(matrix: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """The eigenvector of a symmetric 3x3 matrix with the SMALLEST eigenvalue.

    A cyclic Jacobi sweep, in plain arithmetic and on purpose: numpy is bundled
    by BLENDER and deliberately absent from the venv the pure tier runs in, so a
    `numpy.linalg.eigh` here would make the one measurement this module exists
    for untestable outside Blender. Three-by-three is small enough that the
    textbook method is shorter than the import would be, and it is exact to
    machine precision for the matrices a plane fit produces.
    """
    matrix_rows = [[float(value) for value in row] for row in matrix]
    vectors = [
        [1.0 if row == column else 0.0 for column in range(3)] for row in range(3)
    ]
    for _sweep in range(_JACOBI_MAXIMUM_SWEEPS):
        off_diagonal = (
            abs(matrix_rows[0][1]) + abs(matrix_rows[0][2]) + abs(matrix_rows[1][2])
        )
        diagonal = (
            abs(matrix_rows[0][0]) + abs(matrix_rows[1][1]) + abs(matrix_rows[2][2])
        )
        if off_diagonal <= _JACOBI_TOLERANCE * max(1.0, diagonal):
            break
        for first, second in ((0, 1), (0, 2), (1, 2)):
            if matrix_rows[first][second] == 0.0:
                continue
            angle = (matrix_rows[second][second] - matrix_rows[first][first]) / (
                2.0 * matrix_rows[first][second]
            )
            tangent = math.copysign(1.0, angle) / (
                abs(angle) + math.sqrt(angle * angle + 1.0)
            )
            cosine = 1.0 / math.sqrt(tangent * tangent + 1.0)
            sine = tangent * cosine
            for index in range(3):
                first_value = matrix_rows[first][index]
                second_value = matrix_rows[second][index]
                matrix_rows[first][index] = cosine * first_value - sine * second_value
                matrix_rows[second][index] = sine * first_value + cosine * second_value
            for index in range(3):
                first_value = matrix_rows[index][first]
                second_value = matrix_rows[index][second]
                matrix_rows[index][first] = cosine * first_value - sine * second_value
                matrix_rows[index][second] = sine * first_value + cosine * second_value
            for index in range(3):
                first_value = vectors[index][first]
                second_value = vectors[index][second]
                vectors[index][first] = cosine * first_value - sine * second_value
                vectors[index][second] = sine * first_value + cosine * second_value
    smallest_index = min(range(3), key=lambda index: matrix_rows[index][index])
    return tuple(vectors[row][smallest_index] for row in range(3))


def _fit_plane(
    points: Sequence[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float], float, float]:
    """(centroid, unit normal, RMS residual, maximum residual) of a best-fit plane.

    The normal is the eigenvector of the points' covariance with the SMALLEST
    eigenvalue — the direction the points vary least along, which is the plane's
    own normal — and the residuals are measured along it.
    """
    count = len(points)
    if count < MINIMUM_PLANE_POINTS:
        raise ValueError(
            f"a plane needs at least {MINIMUM_PLANE_POINTS} points, got {count}"
        )
    centroid = tuple(sum(point[axis] for point in points) / count for axis in range(3))
    covariance = [
        [
            sum(
                (point[first] - centroid[first]) * (point[second] - centroid[second])
                for point in points
            )
            for second in range(3)
        ]
        for first in range(3)
    ]
    normal = _smallest_eigenvector(covariance)
    normal = tuple(
        component / math.sqrt(sum(value * value for value in normal))
        for component in normal
    )
    residuals = [
        abs(sum((point[axis] - centroid[axis]) * normal[axis] for axis in range(3)))
        for point in points
    ]
    return (
        centroid,
        normal,
        math.sqrt(sum(residual * residual for residual in residuals) / count),
        max(residuals),
    )


def _slope_deg(normal: tuple[float, float, float]) -> float:
    """The pitch of a face from horizontal: 0 level, 90 a wall."""
    vertical = min(1.0, abs(float(normal[2])))
    return math.degrees(math.acos(vertical))


def _deepest_side(rows: Sequence[SideDepth]) -> str:
    """The side whose mean depth is greatest; ties go to `INTERACTION_SIDES` order."""
    if not rows:
        return ""
    best = max(rows, key=lambda row: row.mean_depth_m)
    return best.side


def _facing_side(alignments: Sequence[tuple[str, float]]) -> str:
    """The side most aligned with the direction given; ties go to `INTERACTION_SIDES` order."""
    if not alignments:
        return ""
    best = max(alignments, key=lambda item: item[1])
    return best[0]


def _opening_sides(blender_object) -> tuple[SideDepth, ...]:
    """Probe inward from each side of the object's LOCAL box, and measure the depth.

    The grid is built in LOCAL space and transformed by `matrix_world`, because
    "which side of this part" is a question about the part's own frame: a piece
    rotated 180 degrees has the same opening on the same LOCAL side, and a
    world-frame probe would report the opposite one. The BVH is world-space, so
    the origin and the direction are transformed too — the two must share a
    frame or the ray measures nothing.
    """
    tree = _world_bvhs([blender_object]).get(blender_object.name)
    if tree is None:
        return ()
    matrix_world = blender_object.matrix_world
    local_box = blender_object.bound_box
    local_minimum = [
        min(float(corner[axis]) for corner in local_box) for axis in range(3)
    ]
    local_maximum = [
        max(float(corner[axis]) for corner in local_box) for axis in range(3)
    ]

    rows: list[SideDepth] = []
    rotation_scale = blender_object.matrix_world.to_3x3()
    for side in INTERACTION_SIDES:
        local_normal = SIDE_LOCAL_NORMAL[side]
        # The two axes that SPAN this side, so the grid covers the face.
        span_axes = [axis for axis in range(3) if local_normal[axis] == 0.0]
        axis = next(index for index in range(3) if local_normal[index] != 0.0)
        face_coordinate = (
            local_maximum[axis] if local_normal[axis] > 0.0 else local_minimum[axis]
        )
        outward_world = _vector(_side_normal_world(blender_object, side))
        inward_world = -outward_world
        # The depth a SOLID part would read: the local box's own extent along
        # this axis, carried into world metres by the transform. Reading
        # `world_maximum[axis] - world_minimum[axis]` would mix a LOCAL axis
        # with a WORLD one, which disagree the moment the part is rotated.
        box_depth_m = float(rotation_scale.col[axis].length) * (
            local_maximum[axis] - local_minimum[axis]
        )

        depths: list[float] = []
        through_count = 0
        for first_index, second_index in product(range(OPENING_GRID), repeat=2):
            local_point = [0.0, 0.0, 0.0]
            local_point[axis] = face_coordinate
            for span_axis, index in zip(span_axes, (first_index, second_index)):
                low, high = local_minimum[span_axis], local_maximum[span_axis]
                local_point[span_axis] = low + (index + 0.5) / OPENING_GRID * (
                    high - low
                )
            origin = (
                matrix_world @ _vector(local_point)
                + outward_world * OPENING_RAY_OFFSET_M
            )
            _hit, _hit_normal, _face_index, distance = tree.ray_cast(
                origin, inward_world
            )
            if _hit is None:
                through_count += 1
                depths.append(box_depth_m)
            else:
                depths.append(max(0.0, float(distance) - OPENING_RAY_OFFSET_M))
        rows.append(
            SideDepth(
                side=side,
                normal=tuple(
                    round(component, _FLOAT_DIGITS) for component in outward_world
                ),
                mean_depth_m=round(sum(depths) / len(depths), _FLOAT_DIGITS),
                maximum_depth_m=round(max(depths), _FLOAT_DIGITS),
                through_fraction=round(through_count / len(depths), _FLOAT_DIGITS),
                box_depth_m=round(box_depth_m, _FLOAT_DIGITS),
            )
        )
    return tuple(rows)


def _vector(values):
    """A mathutils Vector, imported here so this module imports without bpy."""
    from mathutils import Vector

    return Vector(values)


def _world_centre(blender_object) -> tuple[float, float, float]:
    """The centre of the object's world bounding box, measured fresh."""
    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([blender_object])
    return tuple(
        (float(minimum[axis]) + float(maximum[axis])) / 2.0 for axis in range(3)
    )


def _selected_world_vertices(
    blender_object, face_indices
) -> list[tuple[float, float, float]]:
    """The UNIQUE world-space vertices of the named base-mesh polygons.

    Selector indices refer to the BASE mesh, so the fit uses the base mesh too:
    measuring the evaluated one would fit a plane through faces the selector
    never picked.
    """
    matrix_world = blender_object.matrix_world
    mesh = blender_object.data
    vertex_indices: set[int] = set()
    for face_index in face_indices:
        vertex_indices.update(mesh.polygons[face_index].vertices)
    return [
        tuple(
            float(component) for component in (matrix_world @ mesh.vertices[index].co)
        )
        for index in sorted(vertex_indices)
    ]


def _world_normal_sum(blender_object, face_indices) -> tuple[float, float, float]:
    """The summed world normals of the named base-mesh polygons, for orienting a fit.

    Normals transform by the inverse-transpose, not the plain 3x3, so a
    non-uniform scale does not skew them — the same rule `select_faces` applies.
    """
    mesh = blender_object.data
    normal_matrix = blender_object.matrix_world.to_3x3().inverted_safe().transposed()
    total = _vector((0.0, 0.0, 0.0))
    for face_index in face_indices:
        total += normal_matrix @ mesh.polygons[face_index].normal
    return tuple(float(component) for component in total)


@op(reads_only=True)
def measure_feature(
    object_name: str,
    kind: Literal["surface_height", "plane_fit", "opening", "exterior_face"],
    x_m: float | None = None,
    y_m: float | None = None,
    face_selector: FaceSelector | None = None,
    against_name: str | None = None,
) -> FeatureReport:
    """Measure how an object faces: surface height at a plan point, a fitted plane, its deepest opening, or its far side.

    `kind` picks the question, and each kind names the arguments it needs:

    - `surface_height` needs `x_m` and `y_m`: it casts one ray straight down
      from `SURFACE_PROBE_ABOVE_M` above the object's own top and reports the
      surface point it met, that face's unit normal and its pitch (`slope_deg`;
      0 is level). A miss reports `hit=False` and nothing else.
    - `plane_fit` needs `face_selector`: it fits a plane through the UNIQUE
      vertices of the selected base-mesh polygons, in world space, and reports
      the centroid, the normal, the pitch, and the RMS and maximum residual.
      The normal is flipped to agree with the selected faces' own world normals,
      so a roof panel's normal points out of the roof and not into it. Selector
      indices refer to the BASE mesh, so modifiers are not applied here.
    - `opening` takes no other argument: it probes inward from all six sides of
      the object's LOCAL box, 12 x 12 rays each, and reports every side's mean
      and maximum depth, the fraction of rays that passed clean through, and the
      side that reads deepest (`deepest_side`). This is a MEASUREMENT that feeds
      `declare_interaction_side(object_name, deepest_side)`, not a gate: an
      open-sided piece (a table, a hollow barrel) also reads deep, which is why
      the side still has to be declared.
    - `exterior_face` needs `against_name`: the direction from the other
      object's world bbox centre to this one's decides which side points away,
      reported as `facing_side` beside every side's alignment.
    """
    from golem_blender.ops._objects import object_by_name

    if kind not in FEATURE_KINDS:
        raise ValueError(f"kind must be one of {list(FEATURE_KINDS)}, got {kind!r}")
    blender_object = object_by_name(object_name, "MESH")

    if kind == "surface_height":
        if x_m is None or y_m is None:
            raise ValueError(
                f"kind={kind!r} needs x_m and y_m: a surface height is measured at "
                f"a plan point"
            )
        return _surface_height(blender_object, float(x_m), float(y_m))

    if kind == "plane_fit":
        if face_selector is None:
            raise ValueError(
                f"kind={kind!r} needs face_selector: a plane is fitted through the "
                f"faces it selects"
            )
        return _plane_fit(blender_object, face_selector)

    if kind == "opening":
        sides = _opening_sides(blender_object)
        return FeatureReport(
            object_name=blender_object.name,
            kind=kind,
            sides=sides,
            deepest_side=_deepest_side(sides),
        )

    if against_name is None:
        raise ValueError(
            f"kind={kind!r} needs against_name: a side only points away from something"
        )
    if against_name == object_name:
        raise ValueError(
            f"{object_name!r} cannot be measured against itself: no side of an "
            f"object points away from it"
        )
    return _exterior_face(blender_object, against_name)


def _surface_height(blender_object, x_m: float, y_m: float) -> FeatureReport:
    """One downward ray onto the object's top surface."""
    from golem_blender.ops.transforms import _world_bounds_m

    tree = _world_bvhs([blender_object]).get(blender_object.name)
    _minimum, maximum = _world_bounds_m([blender_object])
    origin = _vector((x_m, y_m, float(maximum[2]) + SURFACE_PROBE_ABOVE_M))
    if tree is None:
        return FeatureReport(object_name=blender_object.name, kind="surface_height")
    hit, hit_normal, _face_index, _distance = tree.ray_cast(
        origin, _vector((0.0, 0.0, -1.0))
    )
    if hit is None:
        return FeatureReport(object_name=blender_object.name, kind="surface_height")
    normal = tuple(float(component) for component in hit_normal.normalized())
    return FeatureReport(
        object_name=blender_object.name,
        kind="surface_height",
        hit=True,
        point_m=tuple(round(float(component), _FLOAT_DIGITS) for component in hit),
        normal=tuple(round(component, _FLOAT_DIGITS) for component in normal),
        slope_deg=round(_slope_deg(normal), _FLOAT_DIGITS),
    )


def _plane_fit(blender_object, face_selector: FaceSelector) -> FeatureReport:
    """Fit one plane through the vertices of the selected faces."""
    face_indices = select_faces(blender_object.name, face_selector)
    if not face_indices:
        raise ValueError(f"face_selector selected no faces on {blender_object.name!r}")
    points = _selected_world_vertices(blender_object, face_indices)
    if len(points) < MINIMUM_PLANE_POINTS:
        raise ValueError(
            f"the selected faces of {blender_object.name!r} share "
            f"{len(points)} vertices; a plane needs at least "
            f"{MINIMUM_PLANE_POINTS}"
        )
    centroid, normal, residual_m, maximum_residual_m = _fit_plane(points)
    # Point the normal the same way the selected faces' own normals point, so a
    # roof reads as facing up and not as its own underside.
    normal_sum = _world_normal_sum(blender_object, face_indices)
    if sum(component * other for component, other in zip(normal, normal_sum)) < 0.0:
        normal = tuple(-component for component in normal)
    return FeatureReport(
        object_name=blender_object.name,
        kind="plane_fit",
        hit=True,
        point_m=tuple(round(component, _FLOAT_DIGITS) for component in centroid),
        normal=tuple(round(component, _FLOAT_DIGITS) for component in normal),
        slope_deg=round(_slope_deg(normal), _FLOAT_DIGITS),
        face_count=len(face_indices),
        vertex_count=len(points),
        residual_m=round(residual_m, _FLOAT_DIGITS + 2),
        maximum_residual_m=round(maximum_residual_m, _FLOAT_DIGITS + 2),
    )


def _exterior_face(blender_object, against_name: str) -> FeatureReport:
    """Which side of the object points away from another object."""
    from golem_blender.ops._objects import object_by_name

    against_object = object_by_name(against_name, "MESH")
    own_centre = _world_centre(blender_object)
    other_centre = _world_centre(against_object)
    direction = _vector(
        tuple(own - other for own, other in zip(own_centre, other_centre))
    )
    if direction.length <= MINIMUM_DIRECTION_LENGTH:
        raise ValueError(
            f"{blender_object.name!r} and {against_object.name!r} share a "
            f"bounding-box centre; no side points away"
        )
    direction.normalize()
    alignments = tuple(
        (
            side,
            round(
                _vector(_side_normal_world(blender_object, side)).dot(direction),
                _FLOAT_DIGITS,
            ),
        )
        for side in INTERACTION_SIDES
    )
    return FeatureReport(
        object_name=blender_object.name,
        kind="exterior_face",
        against_name=against_object.name,
        facing_side=_facing_side(alignments),
        side_alignments=alignments,
    )
