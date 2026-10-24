"""Array operations: one part repeated along an axis, a grid, a ring or a path.

Note the honest intermediate state: an applied array is N disconnected
copies in ONE mesh — deliberately multi-component. It only becomes a
gate-passing solid once something (usually a boolean_union with a
connecting part) bridges the copies. Builders own that step; the gate
verifies it happened.

Three layouts cover the repeated parts a piece is made of: a pen's stakes
around a perimeter (`radial_array`), a ladder's rungs along a sag
(`path_array`), a stack's staggered courses (`grid_array`). Each bakes
every copy into the object's own mesh, so a 16-stake pen is one call and
one object rather than sixteen calls and sixteen objects (issue #22).

`linear_array` stays the modifier path it always was: one axis, one
constant offset, and the pallet builder calls it on every build. The grid
op is its superset (`counts=(n, 1, 1)`) but the two are kept apart because
a modifier is the cheaper bake and existing callers must not move.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName

MINIMUM_ARRAY_COUNT = 2
ARRAY_MODIFIER_NAME = "LinearArray"
# Two consecutive path points closer than this are the same place: laying a
# copy there would append coincident geometry with zero-length faces, which
# the analyzer reads as degenerate rather than as a repeat.
MINIMUM_COPY_SEPARATION_M = 1.0e-9
# A copy whose lowest point is below this is under the floor. A baked
# transform leaves float dust, so a base exactly at z=0 can read -1e-17 and
# is not a copy under the ground.
GROUND_TOLERANCE_M = 1.0e-6
# Two copies whose boxes share a face are touching, not overlapping: the
# difference matters because the analyzer counts coplanar contact too.
TOUCHING_TOLERANCE_M = 1.0e-9
AXIS_COUNT = 3


def linear_array(
    object_name: str,
    count: int,
    offset_m: tuple[float, float, float],
) -> ObjectName:
    """Repeat the named object `count` times at a constant metric offset, baked into its mesh."""
    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.modifiers import apply_all_modifiers

    if count < MINIMUM_ARRAY_COUNT:
        raise ValueError(f"Array count must be >= {MINIMUM_ARRAY_COUNT}.")

    blender_object = object_by_name(object_name, "MESH")
    array_modifier = blender_object.modifiers.new(
        name=ARRAY_MODIFIER_NAME, type="ARRAY"
    )
    array_modifier.count = count
    array_modifier.use_relative_offset = False
    array_modifier.use_constant_offset = True
    array_modifier.constant_offset_displace = offset_m
    apply_all_modifiers(object_name)
    return ObjectName(object_name)


@dataclass(frozen=True)
class ArrayReport:
    """What an array left in the scene: every copy's place, and what the gate will read."""

    object_name: str
    copies: int
    # Path points dropped for sitting on the copy before them. A grid and a
    # ring compute their own spacing, so they always report 0.
    skipped_point_count: int
    triangle_count_before: int
    triangle_count: int
    material_slots: int
    # N copies of a closed solid are N islands in ONE mesh: the honest
    # intermediate `linear_array` already produces, now measured.
    connected_component_count: int
    # Each copy's own origin, in world metres, in the order the op laid them.
    copy_origins_m: tuple[tuple[float, float, float], ...]
    # Copy PAIRS whose world bounding boxes overlap — the intended overlaps a
    # pitch smaller than the part produces. A superset of the analyzer's
    # count below, which is the number the gate actually reads.
    overlapping_copy_pair_count: int
    self_intersecting_face_pair_count: int
    # Copies whose lowest point is under z=0. The piece's base check is on
    # the whole piece, so one sunk copy fails the layout.
    below_ground_copy_count: int
    bounds_min_m: tuple[float, float, float]
    bounds_max_m: tuple[float, float, float]


# --- the shared bake and the shared measurement ---------------------------


def _source_origin_m(object_name: str) -> tuple[float, float, float]:
    """The named mesh's world origin, after a depsgraph refresh.

    `matrix_world` evaluates lazily, so an object that was only MOVED reads
    its previous place until the view layer updates (drift catalog).
    """
    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.transforms import _refresh_dependency_graph

    _refresh_dependency_graph()
    return tuple(object_by_name(object_name, "MESH").matrix_world.translation)


def _source_slot_mapper(source_mesh):
    """The material slots a copy keeps: its indices already index the source's.

    Every copy IS the source mesh, so no index translation is needed — but
    the shared append helper remaps through a callable, and handing it the
    identity keeps the slots at one per source material instead of
    multiplying them per copy.
    """
    slots = list(source_mesh.materials)

    def slot_of_material(material_key, material):
        for index, slot in enumerate(slots):
            if slot == material:
                return index
        raise RuntimeError(
            f"material {material_key!r} is not one of the source mesh's slots, "
            f"so a copy's face index would point at the wrong material"
        )

    return slot_of_material


def _bake_copies(source_object, copy_world_matrices) -> None:
    """Replace the object's mesh with the source mesh appended once per copy.

    The copies are placed in WORLD space and baked into the object's own
    local mesh, so the object's matrix (and therefore its origin and pivot)
    does not move: `M⁻¹ · D · M` is the local form of the world placement D.
    """
    import bmesh
    import bpy

    from golem_blender.ops.assets import _append_part_into

    source_mesh = source_object.data
    inverse_object_matrix = source_object.matrix_world.inverted()
    slot_of_material = _source_slot_mapper(source_mesh)
    new_mesh = bpy.data.meshes.new("__array_mesh")
    working_mesh = bmesh.new()
    try:
        for copy_world_matrix in copy_world_matrices:
            _append_part_into(
                working_mesh,
                source_mesh,
                inverse_object_matrix @ copy_world_matrix,
                slot_of_material,
            )
        working_mesh.to_mesh(new_mesh)
    finally:
        working_mesh.free()
    for material in source_mesh.materials:
        new_mesh.materials.append(material)
    source_mesh_name = source_mesh.name
    source_object.data = new_mesh
    if source_mesh.users == 0:
        bpy.data.meshes.remove(source_mesh)
    # Taken unconditionally: with the old mesh gone the name is free, and with
    # a mesh SHARED by another object it is not, so Blender yields the
    # de-duplicated name rather than this op stealing it.
    new_mesh.name = source_mesh_name


def _corners_bounds(local_corners, world_matrix):
    """(minimum, maximum) per world axis of the local box under `world_matrix`."""
    from mathutils import Vector

    world_corners = [world_matrix @ Vector(corner) for corner in local_corners]
    minimum = tuple(min(corner[axis] for corner in world_corners) for axis in range(3))
    maximum = tuple(max(corner[axis] for corner in world_corners) for axis in range(3))
    return minimum, maximum


def _boxes_overlap(first, second) -> bool:
    """Do two (minimum, maximum) boxes share volume, beyond face contact?"""
    for axis in range(3):
        if (
            first[1][axis] <= second[0][axis] + TOUCHING_TOLERANCE_M
            or second[1][axis] <= first[0][axis] + TOUCHING_TOLERANCE_M
        ):
            return False
    return True


def _array(object_name: str, placements, skipped_point_count: int = 0) -> ArrayReport:
    """Bake one copy per world placement into the object's mesh, then measure it.

    ONE placement is a no-op: the object is left exactly as it is and the
    report says so, because a single copy of the thing that is already there
    is a degenerate duplicate, not a layout (issue #22's first edge case).
    """
    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.assets import _triangle_count
    from golem_blender.ops.transforms import _refresh_dependency_graph, _world_bounds_m

    source_object = object_by_name(object_name, "MESH")
    _refresh_dependency_graph()
    object_matrix = source_object.matrix_world.copy()
    triangle_count_before = _triangle_count(source_object.data)
    local_corners = [tuple(corner) for corner in source_object.bound_box]
    copy_world_matrices = [placement @ object_matrix for placement in placements]

    if len(copy_world_matrices) > 1:
        _bake_copies(source_object, copy_world_matrices)
        _refresh_dependency_graph()

    from golem_blender.analyze.mesh_checks import analyze_object

    measured = analyze_object(source_object)
    minimum, maximum = _world_bounds_m([source_object])
    copy_bounds = [
        _corners_bounds(local_corners, copy_world_matrix)
        for copy_world_matrix in copy_world_matrices
    ]
    return ArrayReport(
        object_name=source_object.name,
        copies=len(copy_world_matrices),
        skipped_point_count=skipped_point_count,
        triangle_count_before=triangle_count_before,
        triangle_count=measured.triangle_count,
        material_slots=len(
            [material for material in source_object.data.materials if material]
        ),
        connected_component_count=measured.connected_component_count,
        copy_origins_m=tuple(
            tuple(float(value) for value in copy_world_matrix.translation)
            for copy_world_matrix in copy_world_matrices
        ),
        overlapping_copy_pair_count=sum(
            1
            for first, second in itertools.combinations(copy_bounds, 2)
            if _boxes_overlap(first, second)
        ),
        self_intersecting_face_pair_count=measured.self_intersecting_face_pair_count,
        below_ground_copy_count=sum(
            1
            for copy_minimum, _copy_maximum in copy_bounds
            if copy_minimum[2] < -GROUND_TOLERANCE_M
        ),
        bounds_min_m=(minimum[0], minimum[1], minimum[2]),
        bounds_max_m=(maximum[0], maximum[1], maximum[2]),
    )


# --- the three layouts ----------------------------------------------------


@op(gated=True)
def grid_array(
    object_name: str,
    counts: tuple[int, int, int],
    spacing_m: tuple[float, float, float],
) -> ArrayReport:
    """Repeat the named object over a 3-axis grid in one mesh: counts and spacing per axis.

    Copy (i, j, k) sits at `(i, j, k) * spacing_m` from the object's own
    origin, so the object itself is copy (0, 0, 0) and a count of 1 on an
    axis adds nothing along it. `counts=(1, 1, 1)` is a no-op and returns
    the object as it is. A count below 1, or a zero pitch on an axis that
    repeats, is refused: at zero pitch every copy lands on the same place,
    which is a self-intersecting duplicate rather than a layout. The
    report carries the copy pairs whose boxes overlap and the analyzer's
    own intersection count, because a pitch smaller than the part is a
    layout decision the gate will see.
    """
    if len(counts) != AXIS_COUNT or len(spacing_m) != AXIS_COUNT:
        raise ValueError(
            f"counts and spacing_m are per axis, so each needs exactly "
            f"{AXIS_COUNT} values (x, y, z); got {len(counts)} counts and "
            f"{len(spacing_m)} spacings"
        )
    for axis_index, (axis_count, pitch_m) in enumerate(zip(counts, spacing_m)):
        if axis_count < 1:
            raise ValueError(
                f"counts[{axis_index}] is {axis_count}: a grid axis needs at "
                f"least 1 copy (1 means no repetition along that axis)"
            )
        if axis_count > 1 and pitch_m == 0.0:
            raise ValueError(
                f"spacing_m[{axis_index}] is 0 while counts[{axis_index}] is "
                f"{axis_count}: a zero pitch stacks every copy on the same "
                f"place, which is a self-intersecting duplicate"
            )
    from mathutils import Matrix

    offsets = [
        (ix * spacing_m[0], iy * spacing_m[1], iz * spacing_m[2])
        for ix, iy, iz in itertools.product(*(range(count) for count in counts))
    ]
    return _array(object_name, [Matrix.Translation(offset) for offset in offsets])


@op(gated=True)
def radial_array(
    object_name: str,
    count: int,
    radius_m: float,
    turn_rad: float = 0.0,
    start_bearing_rad: float = 0.0,
) -> ArrayReport:
    """Repeat the named object around the Z axis on a circle of radius_m, turned turn_rad per copy.

    Copy k's own origin lands on the circle at bearing
    `start_bearing_rad + 2*pi*k/count` about the WORLD Z axis, at the
    object's own height, and is turned `k * turn_rad` about Z on top of its
    own orientation — a spiral when turn_rad is non-zero. The object itself
    is copy 0, so the count is the ring's total and the result's pivot is
    the ring's centre. `count=1` is a no-op and returns the object as it
    is: one copy is not a ring, and a radius would move a piece that was
    never repeated.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    if count > 1 and radius_m <= 0.0:
        raise ValueError(
            f"radius_m must be positive, got {radius_m}: every copy of a ring "
            f"stands radius_m from the axis"
        )
    from mathutils import Matrix, Vector

    if count == 1:
        return _array(object_name, [Matrix.Identity(4)])
    source_origin = Vector(_source_origin_m(object_name))
    placements = []
    for index in range(count):
        bearing_rad = start_bearing_rad + math.tau * index / count
        copy_origin = Vector(
            (
                radius_m * math.cos(bearing_rad),
                radius_m * math.sin(bearing_rad),
                source_origin.z,
            )
        )
        placements.append(
            Matrix.Translation(copy_origin)
            @ Matrix.Rotation(index * turn_rad, 4, "Z")
            @ Matrix.Translation(-source_origin)
        )
    return _array(object_name, placements)


@op(gated=True)
def path_array(
    object_name: str,
    points_m: list[tuple[float, float, float]],
) -> ArrayReport:
    """Repeat the named object once per point, each copy's own origin at that point in metres.

    The copies keep the object's orientation — a rung on a sagging rope
    ladder hangs the way it was built — so this is the op for a spacing that
    is not a constant. A point that sits on the copy before it is skipped
    rather than appended: a zero-length segment would lay coincident
    geometry the analyzer reads as degenerate, and the report says how many
    points were skipped. One point is a no-op and returns the object as it
    is, so `count=1` never moves a piece that was not repeated.
    """
    if not points_m:
        raise ValueError("points_m is empty: a path needs at least one point")
    distinct_points: list[tuple[float, float, float]] = []
    skipped_point_count = 0
    for point in points_m:
        if len(point) != AXIS_COUNT:
            raise ValueError(
                f"every path point needs {AXIS_COUNT} coordinates (x, y, z), "
                f"got {len(point)} in {tuple(point)!r}"
            )
        coordinates = tuple(float(value) for value in point)
        if distinct_points:
            previous = distinct_points[-1]
            separation = math.dist(coordinates, previous)
            if separation <= MINIMUM_COPY_SEPARATION_M:
                skipped_point_count += 1
                continue
        distinct_points.append(coordinates)
    from mathutils import Matrix, Vector

    if len(distinct_points) == 1:
        return _array(
            object_name,
            [Matrix.Identity(4)],
            skipped_point_count=skipped_point_count,
        )
    source_origin = Vector(_source_origin_m(object_name))
    placements = [
        Matrix.Translation(Vector(point) - source_origin) for point in distinct_points
    ]
    return _array(object_name, placements, skipped_point_count=skipped_point_count)
