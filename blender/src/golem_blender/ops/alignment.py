"""Placement by FEATURE: a face on a face, standing against a wall, spanning two objects.

Every placement op before this module set an object's ORIGIN. An origin
is frequently not the centre of the geometry and never a particular
face, so "put this there" could not be expressed: the blacksmith-shop
session placed three back wall piers at one y and two side piers at
another and got two rear corners 11.10 cm apart, because the village
kit's pier is 2.000 x 0.406 x 3.123 m with bounds y in [-0.092, 0.314]
— its origin sits 11.1 cm off its bounds centre. The same fault class
recurred four times in one session (a shelf's brackets 111.9 cm off its
wall, a tool board hung flat, a tuyere pipe 50 cm from the nozzle while
its bounding box overlapped the bellows by 30 cm).

WHERE EACH MEASUREMENT COMES FROM, because the two are not
interchangeable:

* A FEATURE coordinate (`min_x` .. `max_z`, `center`) is always read
  from the EVALUATED MESH's world vertices. `bound_box` is the LOCAL
  box, so `matrix_world @ bound_box` over-reads the moment the object
  is turned: measured in Blender 5.2 on a 24-gon cylinder of radius
  1.0 m yawed 45 degrees, that expression spans x in
  [-1.4142, 1.4142] while the mesh itself spans [-1.0, 1.0] — a 41%
  error, and exactly the "a yawed object gives the wrong face" case
  the issue names. Modifiers are applied in the evaluated mesh too, so
  a displaced surface is measured as it renders.
* `_world_bounds_m` from `ops/transforms.py` (the one place world
  extents are measured, OT-34) is used ONLY as the axis-aligned
  prefilter and support-adjacency test in `_clash_sweep` and
  `_supported_by`, never for a feature coordinate. Its `bound_box`
  reading is an OVER-estimate on a turned object, which is the right
  direction for a prefilter (it can never skip a pair that really
  overlaps) and the wrong one for a feature.
* `_refresh_dependency_graph` (also from `ops/transforms.py`) runs
  before every read and after every write: `matrix_world` is evaluated
  lazily, and a read before the graph runs returns the previous frame's
  matrix — the trap that once collapsed three splayed legs into a
  central post.
* Interpenetration is `analyze.pair_checks.analyze_pair`, the one
  pairwise measure: `aabb_penetration_depth_m` against its
  `CONTACT_DEPTH_TOLERANCE_M` (2 mm) is what separates a LAP from a
  CLASH, so resting contact reads clear. No second pairwise
  measurement is written here.
* `_surface_probe` and `_surface_distance_m` measure points ON A
  SURFACE (`closest_point_on_mesh`), never against vertices: a
  bounding-box overlap is not a connection. They sample at
  `PAIR_SEPARATION_SAMPLE_LIMIT`, the same density `analyze_pair`
  uses, so the two agree about what a mesh is.

`gap_m`'s SIGN is deterministic, not state-dependent: a positive gap
moves the object AWAY from the target in the direction it is being
placed, so a MAXIMUM face against a MINIMUM face (or against a plane)
takes `-1`, and every other pair (min against max, the same-side
pairs, anything involving `center`) takes `+1`. A negative gap
therefore interpenetrates, which is what a boolean operand wants; the
overlap is then REPORTED in `collides_with` rather than swallowed,
because the report is the measurement and undoing a placement the
caller asked for would hide it.

`align_to(..., "center", "center")` names no axis at all, so it moves
along the SHORTEST of the three (the issue's rule for `axis=None`);
call it once per axis with `axis=` to centre on all three. Two features
naming DIFFERENT axes is refused: no single translation puts an x face
on a y face.

`TargetPlane` is the tool-facing spelling of the issue's
`("plane", "y", 2.594)` triple: the schema generator maps a frozen
dataclass to an object and raises on a heterogeneous tuple, so the
triple is accepted from a Python caller (`_parse_target_plane`) and the
dataclass is what the generated tool schema declares. Both mean the
same thing and produce the same move. `TargetPlane` is deliberately NOT
in `manifest.OP_CONFIG_DATACLASSES`: the generated tool schema is the
one description of an op (OT-24) and that manifest section is rendered
into the system prompt, so registering it would move the
assembled-prompt pin for a parameter the schema already spells out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from golem_blender.ops._contract import op
from golem_blender.ops.transforms import _refresh_dependency_graph, _world_bounds_m

AXIS_COUNT = 3
AXIS_INDEX = {"x": 0, "y": 1, "z": 2}
AXIS_NAMES = ("x", "y", "z")

# The feature vocabulary. A feature is a face or the bounds centre; the
# reported point for a face is the extreme coordinate on its axis and
# the bounds centre on the other two, which for an axis-aligned face IS
# the face centre.
FEATURE_KINDS = (
    "min_x",
    "max_x",
    "min_y",
    "max_y",
    "min_z",
    "max_z",
    "center",
)

# `stand_against`'s sides name the OBJECT's own near face, and map to
# the wall face it meets: a `+x` near face (its `max_x`) meets the
# wall's `min_x`.
STAND_AGAINST_SIDES = ("+x", "-x", "+y", "-y")
SIDE_AXIS = {"+x": "x", "-x": "x", "+y": "y", "-y": "y"}
SIDE_OBJECT_FEATURE = {
    "+x": "max_x",
    "-x": "min_x",
    "+y": "max_y",
    "-y": "min_y",
}
SIDE_TARGET_FEATURE = {
    "+x": "min_x",
    "-x": "max_x",
    "+y": "min_y",
    "-y": "max_y",
}

# How far below its base another object's top may sit and still count as
# support. The upper bound on the other side is the pair module's
# contact tolerance: one number for "resting on", not two.
SUPPORT_TOLERANCE_M = 0.01

# Only objects whose world bounds are this close to the placed object's
# are probed for a clash. `bound_box` over-reads on a turned object, so
# a wider AABB gap than this cannot hide an overlap; the margin bounds
# the sweep on a 49-part building without changing an answer.
CONTACT_PROBE_MARGIN_M = 0.05

# The band at each end of a span object that counts as its end face, as
# a fraction of the object's own length, floored so a very short piece
# still selects its end vertices.
END_BAND_FRACTION = 1.0e-3
MINIMUM_END_BAND_M = 1.0e-6

# A zero-scaled local axis has no direction to align along.
MINIMUM_AXIS_LENGTH = 1.0e-9

# A feature already within this of its target needs no move on that
# axis, so `_shortest_axis` does not choose it: a zero-length move does
# not "achieve" an alignment, and float32 vertex data leaves ~1.4e-7 m
# of residual that must not be mistaken for work still to do.
AXIS_ALIGNED_TOLERANCE_M = 1.0e-6


@dataclass(frozen=True)
class TargetPlane:
    """An explicit world plane at coordinate_m on axis, for a target with no feature there."""

    axis: Literal["x", "y", "z"]
    coordinate_m: float


@dataclass(frozen=True)
class AlignReport:
    """What a feature placement moved, where the features landed, and what it touches."""

    object_name: str
    moved_m: tuple[float, float, float]
    feature_object_m: tuple[float, float, float]
    feature_target_m: tuple[float, float, float]
    # How far the measured relation is from the one requested: 0 for an
    # exact face-on-face, the signed stand-off for a gap, the worse end
    # for a span.
    achieved_gap_m: float
    # Probed and found clear, and probed and found PENETRATING (a
    # penetration deeper than CONTACT_DEPTH_TOLERANCE_M, so resting
    # contact is clear). An object in neither tuple was too far away to
    # reach.
    clear_of: tuple[str, ...]
    collides_with: tuple[str, ...]
    # Nothing in the SCENE under the object's base. The build plane at
    # z=0 is not an object, so a piece standing on the ground also reads
    # True here; `supported_by` is what names a real support.
    hangs_in_air: bool
    supported_by: tuple[str, ...]
    # The axis the move was made on; `align_to` with no axis in either
    # feature picks the shortest, and this is how the caller sees which.
    aligned_axis: str = ""
    # `span_between` only: the object's own length along its span axis,
    # the distance from each end to ITS OWN object's SURFACE, and
    # whether both are inside the `radius_m` the caller declared.
    span_m: float | None = None
    end_gap_from_m: float | None = None
    end_gap_to_m: float | None = None
    within_radius: bool | None = None


# --- pure logic: the vocabulary, the axis, the gap sign -----------------
# Kept free of bpy so the pure layer tests them without Blender.


def _feature_kind(feature: str) -> str:
    """The `min`/`max`/`center` part of a feature name, loudly."""
    if feature not in FEATURE_KINDS:
        raise ValueError(f"unknown feature {feature!r}; one of {list(FEATURE_KINDS)}")
    if feature == "center":
        return "center"
    return feature.split("_", 1)[0]


def _feature_axis(feature: str) -> str | None:
    """The axis a feature names, or None for `center`."""
    if _feature_kind(feature) == "center":
        return None
    return feature.split("_", 1)[1]


def _parse_target_plane(target_feature) -> TargetPlane | None:
    """A `TargetPlane`, the issue's `("plane", axis, coordinate)` triple, or None."""
    if isinstance(target_feature, TargetPlane):
        if target_feature.axis not in AXIS_INDEX:
            raise ValueError(
                f"plane axis {target_feature.axis!r} is not one of {list(AXIS_INDEX)}"
            )
        return target_feature
    if isinstance(target_feature, tuple | list):
        if len(target_feature) != 3 or target_feature[0] != "plane":
            raise ValueError(
                f"a plane target is ('plane', axis, coordinate), got {target_feature!r}"
            )
        _word, axis, coordinate_m = target_feature
        if axis not in AXIS_INDEX:
            raise ValueError(f"plane axis {axis!r} is not one of {list(AXIS_INDEX)}")
        if isinstance(coordinate_m, bool) or not isinstance(coordinate_m, int | float):
            raise TypeError(
                f"plane coordinate must be a number in metres, got {coordinate_m!r}"
            )
        return TargetPlane(axis=axis, coordinate_m=float(coordinate_m))
    if isinstance(target_feature, str):
        return None
    raise TypeError(
        f"target_feature must be a feature name, a TargetPlane or a "
        f"('plane', axis, coordinate) triple, got "
        f"{type(target_feature).__name__}"
    )


def _gap_sign(object_kind: str, target_kind: str) -> float:
    """+1 or -1: the direction a positive gap pushes the object.

    `-1` exactly when the object's face is its MAXIMUM and the target's
    is a MINIMUM or an explicit plane — that object sits on the
    target's negative side, so standing off moves it further negative.
    """
    object_is_maximum = object_kind == "max"
    target_is_floor = target_kind in ("min", "plane")
    return -1.0 if object_is_maximum and target_is_floor else 1.0


def _resolve_axis(
    object_feature: str, plane: TargetPlane | None, target_feature
) -> str | None:
    """The one axis to move on, or None when the caller must pick the shortest.

    Two features naming different axes is a loud error rather than a
    silent pick: no single translation puts an x face on a y face.
    """
    named: list[str] = []
    object_axis = _feature_axis(object_feature)
    if object_axis is not None:
        named.append(object_axis)
    if plane is not None:
        named.append(plane.axis)
    elif isinstance(target_feature, str):
        target_axis = _feature_axis(target_feature)
        if target_axis is not None:
            named.append(target_axis)
    distinct = sorted(set(named))
    if len(distinct) > 1:
        raise ValueError(
            f"object_feature {object_feature!r} and target_feature "
            f"{target_feature!r} name different axes ({distinct}); no single "
            f"move puts a face on a face across axes"
        )
    return distinct[0] if distinct else None


def _shortest_axis(deltas_m: tuple[float, float, float]) -> str:
    """The axis whose move is smallest and not already made, in x/y/z order on a tie.

    An axis the features already agree on is skipped: it needs no move,
    so choosing it would report a successful alignment that translated
    nothing. When every axis already agrees the largest is returned, so
    the caller gets a defined axis (and a zero move) rather than an
    error — the features ARE aligned, and the report says so.
    """
    outstanding = [
        axis_index
        for axis_index in range(AXIS_COUNT)
        if abs(deltas_m[axis_index]) > AXIS_ALIGNED_TOLERANCE_M
    ]
    candidates = outstanding or list(range(AXIS_COUNT))
    smallest_index = min(candidates, key=lambda axis: (abs(deltas_m[axis]), axis))
    return AXIS_NAMES[smallest_index]


# --- measured helpers (bpy) ---------------------------------------------


def _evaluated_world_vertices(blender_object) -> list:
    """Every world-space vertex of the EVALUATED mesh, modifiers applied."""
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = blender_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        to_world = evaluated.matrix_world
        return [to_world @ vertex.co for vertex in evaluated_mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


def _bounds_from_vertices_m(vertices) -> tuple[list[float], list[float], list[float]]:
    """(minimum, maximum, centre) per world axis, from mesh VERTICES."""
    if not vertices:
        raise ValueError("mesh has no vertices to measure")
    minimum = [min(vertex[axis] for vertex in vertices) for axis in range(AXIS_COUNT)]
    maximum = [max(vertex[axis] for vertex in vertices) for axis in range(AXIS_COUNT)]
    centre = [0.5 * (minimum[axis] + maximum[axis]) for axis in range(AXIS_COUNT)]
    return minimum, maximum, centre


def _feature_point_m(minimum, maximum, centre, feature: str) -> tuple:
    """The feature's world point: the extreme coordinate on its own axis.

    `center` is the bounds centre. For a face the other two components
    are the bounds centre, which for an axis-aligned face is the face
    centre; on a turned mesh it is the point on that extreme plane, not
    necessarily a point of the surface — the face's POSITION is what a
    placement chains on.
    """
    point = list(centre)
    kind = _feature_kind(feature)
    if kind != "center":
        axis = AXIS_INDEX[_feature_axis(feature)]
        point[axis] = maximum[axis] if kind == "max" else minimum[axis]
    return (point[0], point[1], point[2])


def _plane_point_m(plane: TargetPlane, reference_m) -> tuple:
    """The point of `plane` level with `reference_m` on the plane's own axis."""
    point = list(reference_m)
    point[AXIS_INDEX[plane.axis]] = plane.coordinate_m
    return (point[0], point[1], point[2])


def _surface_distance_m(blender_object, world_point_m) -> float:
    """World distance from a point to the object's SURFACE, never to a vertex."""
    import bpy
    from mathutils import Vector

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = blender_object.evaluated_get(dependency_graph)
    to_world = evaluated.matrix_world
    query = Vector(world_point_m)
    hit, location, _normal, _index = evaluated.closest_point_on_mesh(
        to_world.inverted() @ query
    )
    if not hit:
        raise ValueError(
            f"{blender_object.name!r} has no surface to measure against (no faces?)"
        )
    return ((to_world @ location) - query).length


def _surface_probe(source_object, target_object):
    """(distance, source point, target point): a sampled surface to the other's SURFACE.

    Every ``ceil(count / PAIR_SEPARATION_SAMPLE_LIMIT)``-th vertex of the
    source, nearest point on the target's SURFACE — the sampling density
    `analyze_pair` uses, so the two agree about what a mesh is.
    """
    import bpy

    from golem_blender.analyze.pair_checks import PAIR_SEPARATION_SAMPLE_LIMIT

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    source_evaluated = source_object.evaluated_get(dependency_graph)
    source_mesh = source_evaluated.to_mesh()
    target_evaluated = target_object.evaluated_get(dependency_graph)
    try:
        vertex_count = len(source_mesh.vertices)
        if not vertex_count:
            return None
        sample_step = (
            1
            if vertex_count <= PAIR_SEPARATION_SAMPLE_LIMIT
            else -(-vertex_count // PAIR_SEPARATION_SAMPLE_LIMIT)
        )
        source_to_world = source_evaluated.matrix_world
        target_to_world = target_evaluated.matrix_world
        target_to_local = target_to_world.inverted()
        nearest = None
        for vertex_index in range(0, vertex_count, sample_step):
            world_point = source_to_world @ source_mesh.vertices[vertex_index].co
            hit, location, _normal, _index = target_evaluated.closest_point_on_mesh(
                target_to_local @ world_point
            )
            if not hit:
                continue
            world_closest = target_to_world @ location
            distance_m = (world_closest - world_point).length
            if nearest is None or distance_m < nearest[0]:
                nearest = (distance_m, world_point.copy(), world_closest.copy())
        return nearest
    finally:
        source_evaluated.to_mesh_clear()


def _nearest_surface_points_m(first_object, second_object):
    """The nearest pair of points ON the two SURFACES; both directions, minimised.

    A bounding-box overlap is not a connection, so a span runs between
    these two points and each end is measured back to its own surface.
    """
    candidates = [
        probe
        for probe in (
            _surface_probe(first_object, second_object),
            _surface_probe(second_object, first_object),
        )
        if probe is not None
    ]
    if not candidates:
        raise ValueError(
            f"neither {first_object.name!r} nor {second_object.name!r} has "
            f"vertices to measure"
        )
    _distance_m, first_point, second_point = min(candidates, key=lambda p: p[0])
    return (
        (first_point[0], first_point[1], first_point[2]),
        (second_point[0], second_point[1], second_point[2]),
    )


def _scene_mesh_objects(placed_object) -> list:
    """Every other MESH object in the scene, by name so a sweep is stable."""
    import bpy

    return sorted(
        (
            candidate
            for candidate in bpy.context.scene.objects
            if candidate.type == "MESH" and candidate.name != placed_object.name
        ),
        key=lambda candidate: candidate.name,
    )


def _bounds_m(blender_object) -> tuple[list[float], list[float]]:
    """World AABB of one object, through the one world-extents helper."""
    return _world_bounds_m([blender_object])


def _clash_sweep(placed_object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(clear_of, collides_with) for the placed object against the scene.

    `analyze_pair`'s `aabb_penetration_depth_m` above
    `CONTACT_DEPTH_TOLERANCE_M` is the clash line: resting contact (a
    2 mm stand-off, a lid on a rim) reads clear, a genuine overlap does
    not. Only objects within `CONTACT_PROBE_MARGIN_M` are probed — an
    AABB gap wider than that cannot hide an overlap — so a name in
    neither tuple is an object the placement could not reach.
    """
    from golem_blender.analyze.pair_checks import (
        CONTACT_DEPTH_TOLERANCE_M,
        analyze_pair,
    )

    placed_minimum, placed_maximum = _bounds_m(placed_object)
    clear_of: list[str] = []
    collides_with: list[str] = []
    for candidate in _scene_mesh_objects(placed_object):
        candidate_minimum, candidate_maximum = _bounds_m(candidate)
        if any(
            candidate_minimum[axis] > placed_maximum[axis] + CONTACT_PROBE_MARGIN_M
            or candidate_maximum[axis] < placed_minimum[axis] - CONTACT_PROBE_MARGIN_M
            for axis in range(AXIS_COUNT)
        ):
            continue
        pair_report = analyze_pair(placed_object, candidate)
        if pair_report.aabb_penetration_depth_m > CONTACT_DEPTH_TOLERANCE_M:
            collides_with.append(candidate.name)
        else:
            clear_of.append(candidate.name)
    return tuple(clear_of), tuple(collides_with)


def _supported_by(placed_object) -> tuple[str, ...]:
    """Names of objects whose top holds the placed object's base up.

    Support needs both: the other object's top within
    `SUPPORT_TOLERANCE_M` of the base (or up to the contact tolerance
    ABOVE it, a lid sunk into its rim), AND an overlapping footprint — a
    wall beside a shelf reaches far above the shelf's base and holds
    nothing up.
    """
    from golem_blender.analyze.pair_checks import CONTACT_DEPTH_TOLERANCE_M

    placed_minimum, _placed_maximum = _bounds_m(placed_object)
    base_z_m = placed_minimum[2]
    supporters: list[str] = []
    for candidate in _scene_mesh_objects(placed_object):
        candidate_minimum, candidate_maximum = _bounds_m(candidate)
        drop_m = base_z_m - candidate_maximum[2]
        if drop_m > SUPPORT_TOLERANCE_M or drop_m < -CONTACT_DEPTH_TOLERANCE_M:
            continue
        if any(
            candidate_minimum[axis] >= placed_minimum[axis] + CONTACT_PROBE_MARGIN_M
            for axis in (0, 1)
        ):
            continue
        supporters.append(candidate.name)
    return tuple(sorted(supporters))


def _report(
    placed_object,
    moved_m,
    feature_object_m,
    feature_target_m,
    achieved_gap_m,
    aligned_axis,
    span_m=None,
    end_gap_from_m=None,
    end_gap_to_m=None,
    within_radius=None,
) -> AlignReport:
    """Measure the placement's surroundings and assemble the report."""
    _refresh_dependency_graph()
    clear_of, collides_with = _clash_sweep(placed_object)
    supported_by = _supported_by(placed_object)
    return AlignReport(
        object_name=placed_object.name,
        moved_m=moved_m,
        feature_object_m=feature_object_m,
        feature_target_m=feature_target_m,
        achieved_gap_m=achieved_gap_m,
        clear_of=clear_of,
        collides_with=collides_with,
        hangs_in_air=not supported_by,
        supported_by=supported_by,
        aligned_axis=aligned_axis,
        span_m=span_m,
        end_gap_from_m=end_gap_from_m,
        end_gap_to_m=end_gap_to_m,
        within_radius=within_radius,
    )


def _translate_world_m(blender_object, delta_m) -> None:
    """Move the object by a WORLD delta, parent or not, then refresh."""
    from mathutils import Vector

    _refresh_dependency_graph()
    world_matrix = blender_object.matrix_world.copy()
    world_matrix.translation = world_matrix.translation + Vector(delta_m)
    blender_object.matrix_world = world_matrix
    _refresh_dependency_graph()


# --- the ops -----------------------------------------------------------


@op(gated=True)
def align_to(
    object_name: str,
    target_name: str,
    object_feature: str,
    target_feature: str | TargetPlane,
    gap_m: float = 0.0,
    axis: str | None = None,
) -> AlignReport:
    """Put the named object's feature on the named target's feature along one axis.

    `object_feature` is `min_x` .. `max_z` or `center`, measured from
    the evaluated mesh. `target_feature` is the same vocabulary, or a
    `TargetPlane` (a `("plane", "y", 2.594)` triple from Python) when
    the target has no measurable feature on the axis — a wall whose box
    extends past its inner face. `gap_m` is the stand-off: positive
    keeps the object clear, negative interpenetrates for a boolean
    operand. `axis` is needed only when neither feature names one (a
    centre-to-centre alignment), which then moves on the axis of
    SHORTEST movement. A move that puts the object through a third
    object is applied and named in `collides_with`, never swallowed.
    """
    from golem_blender.ops._objects import object_by_name

    plane = _parse_target_plane(target_feature)
    if plane is None:
        _feature_kind(target_feature)
    object_kind = _feature_kind(object_feature)
    resolved_axis = (
        axis
        if axis is not None
        else _resolve_axis(object_feature, plane, target_feature)
    )
    if resolved_axis is not None and resolved_axis not in AXIS_INDEX:
        raise ValueError(f"axis {resolved_axis!r} is not one of {list(AXIS_INDEX)}")

    blender_object = object_by_name(object_name)
    target_object = object_by_name(target_name)
    _refresh_dependency_graph()

    object_minimum, object_maximum, object_centre = _bounds_from_vertices_m(
        _evaluated_world_vertices(blender_object)
    )
    object_point = _feature_point_m(
        object_minimum, object_maximum, object_centre, object_feature
    )
    if plane is None:
        target_kind = _feature_kind(target_feature)
        target_minimum, target_maximum, target_centre = _bounds_from_vertices_m(
            _evaluated_world_vertices(target_object)
        )
        target_point = _feature_point_m(
            target_minimum, target_maximum, target_centre, target_feature
        )
    else:
        target_kind = "plane"
        target_point = _plane_point_m(plane, object_point)

    deltas_m = tuple(
        target_point[axis_index] - object_point[axis_index]
        for axis_index in range(AXIS_COUNT)
    )
    if resolved_axis is None:
        resolved_axis = _shortest_axis(deltas_m)
    axis_index = AXIS_INDEX[resolved_axis]
    sign = _gap_sign(object_kind, target_kind)
    delta_m = [0.0] * AXIS_COUNT
    delta_m[axis_index] = deltas_m[axis_index] + sign * gap_m
    _translate_world_m(blender_object, delta_m)

    moved_minimum, moved_maximum, moved_centre = _bounds_from_vertices_m(
        _evaluated_world_vertices(blender_object)
    )
    moved_point = _feature_point_m(
        moved_minimum, moved_maximum, moved_centre, object_feature
    )
    return _report(
        placed_object=blender_object,
        moved_m=tuple(delta_m),
        feature_object_m=moved_point,
        feature_target_m=target_point,
        achieved_gap_m=(moved_point[axis_index] - target_point[axis_index]) * sign
        # `* -1.0` on an exact zero yields -0.0; the report says 0.0.
        + 0.0,
        aligned_axis=resolved_axis,
    )


@op(gated=True)
def stand_against(
    object_name: str,
    wall_name: str,
    side: str,
    gap_m: float = 0.002,
) -> AlignReport:
    """Stand the named object against a wall: its near face a gap_m from the wall's face.

    `side` names the OBJECT's own near face (issue #25, condition 3):
    `"+x"` puts its `max_x` face one gap_m from the wall's `min_x`
    face, `"-x"` puts `min_x` on the wall's `max_x`, and likewise for
    `"+y"`/`"-y"`. Only that axis moves, so the object's base is
    untouched. `hangs_in_air` and `supported_by` say whether anything
    below holds it up — a shelf whose base is above every other
    object's top reports that it hangs.
    """
    if side not in STAND_AGAINST_SIDES:
        raise ValueError(f"side {side!r} is not one of {list(STAND_AGAINST_SIDES)}")
    return align_to(
        object_name,
        wall_name,
        SIDE_OBJECT_FEATURE[side],
        SIDE_TARGET_FEATURE[side],
        gap_m=gap_m,
        axis=SIDE_AXIS[side],
    )


@op(gated=True)
def span_between(
    object_name: str,
    from_name: str,
    to_name: str,
    radius_m: float,
) -> AlignReport:
    """Place and orient a span so its long axis runs between two objects' nearest surface points.

    The anchors are the nearest pair of points ON the two objects'
    SURFACES, not a bounding-box overlap. The object is turned so its
    longest own axis runs from `from` to `to` and its mid-span is put on
    the anchors' midpoint: a piece as long as the span lands both ends on
    the anchors, a short one floats symmetrically, a long one overlaps.
    `end_gap_from_m` and `end_gap_to_m` are each measured to ITS OWN
    object's SURFACE, and `radius_m` is the caller's threshold, checked
    into `within_radius`. A third object the line passes through is
    named in `collides_with`.
    """
    from mathutils import Vector

    from golem_blender.ops._objects import object_by_name

    if radius_m <= 0.0:
        raise ValueError(f"radius_m must be positive, got {radius_m}")
    blender_object = object_by_name(object_name, "MESH")
    from_object = object_by_name(from_name)
    to_object = object_by_name(to_name)
    _refresh_dependency_graph()

    from_point, to_point = _nearest_surface_points_m(from_object, to_object)
    span_vector = Vector(to_point) - Vector(from_point)
    if span_vector.length <= MINIMUM_AXIS_LENGTH:
        raise ValueError(
            f"{from_name!r} and {to_name!r} meet, so there is no span between "
            f"them to run an object along"
        )
    span_direction = span_vector.normalized()

    _orient_long_axis_along(blender_object, span_direction)

    vertices = _evaluated_world_vertices(blender_object)
    along_span_m = [vertex.dot(span_direction) for vertex in vertices]
    centroid = sum(vertices, Vector()) / len(vertices)
    mid_span_m = centroid + span_direction * (
        0.5 * (min(along_span_m) + max(along_span_m)) - centroid.dot(span_direction)
    )
    anchor_mid_m = (Vector(from_point) + Vector(to_point)) * 0.5
    translation_m = anchor_mid_m - mid_span_m
    _translate_world_m(blender_object, tuple(translation_m))

    vertices = _evaluated_world_vertices(blender_object)
    along_span_m = [vertex.dot(span_direction) for vertex in vertices]
    low_m, high_m = min(along_span_m), max(along_span_m)
    band_m = max(MINIMUM_END_BAND_M, END_BAND_FRACTION * (high_m - low_m))
    near_end_m = _end_centre_m(vertices, along_span_m, low_m, band_m)
    far_end_m = _end_centre_m(vertices, along_span_m, high_m, band_m)
    span_m = (Vector(far_end_m) - Vector(near_end_m)).length

    near_to_from_m = _surface_distance_m(from_object, near_end_m)
    near_to_to_m = _surface_distance_m(to_object, near_end_m)
    far_to_from_m = _surface_distance_m(from_object, far_end_m)
    far_to_to_m = _surface_distance_m(to_object, far_end_m)
    # The ends belong to the objects they are NEARER: swap when the
    # "far" end is the one nearest `from` and the "near" end the one
    # nearest `to`, which is what a reversed span direction produces.
    if far_to_from_m < near_to_from_m and near_to_to_m < far_to_to_m:
        near_end_m, far_end_m = far_end_m, near_end_m
        near_to_from_m, far_to_from_m = far_to_from_m, near_to_from_m
        near_to_to_m, far_to_to_m = far_to_to_m, near_to_to_m

    achieved_gap_m = max(near_to_from_m, far_to_to_m)
    return _report(
        placed_object=blender_object,
        moved_m=tuple(translation_m),
        feature_object_m=tuple((Vector(near_end_m) + Vector(far_end_m)) * 0.5),
        feature_target_m=(anchor_mid_m[0], anchor_mid_m[1], anchor_mid_m[2]),
        achieved_gap_m=achieved_gap_m,
        aligned_axis="",
        span_m=span_m,
        end_gap_from_m=near_to_from_m,
        end_gap_to_m=far_to_to_m,
        within_radius=(near_to_from_m <= radius_m and far_to_to_m <= radius_m),
    )


def _end_centre_m(vertices, along_span_m, end_coordinate_m, band_m) -> tuple:
    """Centroid of the vertices within `band_m` of one end of the span."""
    from mathutils import Vector

    band_vertices = [
        vertex
        for vertex, coordinate_m in zip(vertices, along_span_m)
        if abs(coordinate_m - end_coordinate_m) <= band_m
    ]
    if not band_vertices:
        raise ValueError("no vertices at the span's end to measure")
    centre = sum(band_vertices, Vector()) / len(band_vertices)
    return (centre[0], centre[1], centre[2])


def _orient_long_axis_along(blender_object, span_direction) -> None:
    """Turn the object so its longest own axis points along `span_direction`.

    The axis is found on the object's LOCAL axes projected into the
    world, so a piece imported with its length on local z is recognised
    as long on z, and the extra rotation is composed with whatever
    rotation the object already had — the roll about the span is left
    alone.
    """
    from mathutils import Matrix, Vector

    _refresh_dependency_graph()
    vertices = _evaluated_world_vertices(blender_object)
    centroid = sum(vertices, Vector()) / len(vertices)
    basis = blender_object.matrix_world.to_3x3()
    longest_axis = None
    longest_span_m = -1.0
    for unit in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        direction = basis @ Vector(unit)
        if direction.length <= MINIMUM_AXIS_LENGTH:
            continue  # a zero-scaled axis has no direction to align along
        direction.normalize()
        projections = [(vertex - centroid).dot(direction) for vertex in vertices]
        span_m = max(projections) - min(projections)
        if span_m > longest_span_m:
            longest_span_m = span_m
            longest_axis = direction
    if longest_axis is None:
        raise ValueError(
            f"{blender_object.name!r} has no axis with a length to orient "
            f"(every local axis is zero-length)"
        )
    extra_rotation = longest_axis.rotation_difference(span_direction)
    location, rotation, scale = blender_object.matrix_world.decompose()
    blender_object.matrix_world = Matrix.LocRotScale(
        location, extra_rotation @ rotation, scale
    )
    _refresh_dependency_graph()
