"""Is this space sealed, and where does it leak — a report, not a night render.

The measured need: a Sanctuary abbey rendered light through a wall and the leak
was only visible in a night render. Two independent halves, because they find
different defects and a report with only one of them is worse than none:

- **HOLES.** Voxelise the parts, flood the free space from the inside seeds, and
  read which reached cells are NOT enclosed by geometry on all sides
  (`analyze/enclosure.py`). That finds a missing roof, a doorway, an open side —
  a leak a character could walk through.
- **SEAMS.** Two walls meeting flush ARE sealed, and flood fill agrees with them
  even when a 2 mm gap runs between two solid parts. So every junction between
  two parts whose boxes touch is swept with rays along the three aligned axes: a
  ray that crosses from the inside region to the outside region is a seam leak.

Everything is measured in a frame ALIGNED to the geometry's own yaw, because a
room turned 37 degrees is the same room and a world-axis grid would staircase
its walls into a row of false leaks. Coordinates are reported back in world, so
a rotated room and its original answer with the same numbers.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from golem_blender.analyze.enclosure import (
    GRID_PADDING_CELLS,
    JUNCTION_MARGIN_MINIMUM_M,
    MAXIMUM_ENCLOSURE_CELLS,
    SWEEP_CLEARANCE_CELLS,
    aligned_point,
    cluster_cells,
    dominant_yaw_deg,
    enclosed_mask,
    flood,
    resolution_that_fits,
    solid_voxels,
    world_point,
)
from golem_blender.ops._contract import op
from golem_blender.ops._objects import UnknownObject
from golem_blender.ops._targets import resolve_mesh_targets

# The sweep samples a junction's cross-section at this fraction of
# `leak_minimum_m`: sampling at the leak size itself can step over the leak.
SWEEP_SPACING_FRACTION = 0.5
# A junction region is the two boxes' intersection grown by the margin, so a ray
# that crosses the whole joint (and nothing outside it) is what is tested.
SWEEP_DIRECTIONS = ((0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1))
# A point this close to the inside region counts as inside: the seeds are voxel
# centres, so a ray's endpoint lands within half a cell of the region it names.
REGION_TOLERANCE_CELLS = 1
# A voxel grid cannot represent an opening narrower than one cell, so a report
# whose resolution is coarser than the leak it claims to find is a lie in its
# own units. Measured: a 2 cm slot at a 2 cm resolution is exactly one cell wide
# and the floor's surface cell claims it, so a genuinely open room read sealed.
MAXIMUM_RESOLUTION_PER_LEAK = 0.5
# A seam must have CLEARANCE: a ray's midpoint must be at least this fraction of
# `leak_minimum_m` from both parts' surfaces. Zero clearance is a flush contact
# — two faces meeting in one plane — which z-fights but does not leak.
SEAM_CLEARANCE_FRACTION = 0.5


@dataclass(frozen=True)
class EnclosureLeak:
    """One opening: where it is, how big, which way it opens, and between what."""

    at_m: tuple[float, float, float]
    size_m: float
    direction: tuple[float, float, float]  # unit, inside -> outside, world
    between: tuple[str, ...]  # the nearest parts ("hole") or the junction's pair
    kind: str  # "hole" (flood + enclosure) or "seam" (junction sweep)
    allowed: bool


@dataclass(frozen=True)
class JunctionVerdict:
    """Whether one pair of touching parts seals the joint between them."""

    first_object_name: str
    second_object_name: str
    verdict: str  # "sealed" | "leak"


@dataclass(frozen=True)
class EnclosureReport:
    """Whether the target is sealed, and every opening found."""

    target: str
    sealed: bool
    leaks: tuple[EnclosureLeak, ...]
    junctions: tuple[JunctionVerdict, ...]
    inside_points_m: tuple[tuple[float, float, float], ...]
    outside: str
    resolution_m: float
    grid_yaw_deg: float
    cell_count: int


def _world_triangles(objects):
    """(world triangles, per-triangle owner index, (normal, area) per triangle)."""
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    triangles = []
    owners = []
    normals_and_areas = []
    for owner, blender_object in enumerate(objects):
        evaluated = blender_object.evaluated_get(dependency_graph)
        mesh = evaluated.to_mesh()
        try:
            world_matrix = blender_object.matrix_world
            world_normal_matrix = world_matrix.to_3x3()
            vertices = [world_matrix @ vertex.co for vertex in mesh.vertices]
            mesh.calc_loop_triangles()
            for loop_triangle in mesh.loop_triangles:
                corners = tuple(
                    tuple(vertices[index]) for index in loop_triangle.vertices
                )
                triangles.append(corners)
                owners.append(owner)
                normal = (world_normal_matrix @ loop_triangle.normal).normalized()
                local_area = loop_triangle.area
                scale = math.sqrt(abs(world_normal_matrix.determinant()))
                normals_and_areas.append(
                    ((normal.x, normal.y, normal.z), local_area * scale)
                )
        finally:
            evaluated.to_mesh_clear()
    return triangles, owners, normals_and_areas


def _junction_pairs(objects, margin_m: float):
    """Pairs of parts whose aligned boxes are within `margin_m` of each other."""
    from golem_blender.ops.transforms import _world_bounds_m

    boxes = []
    for blender_object in objects:
        _minimum, _maximum = _world_bounds_m([blender_object])
        boxes.append((_minimum, _maximum))
    pairs = []
    for first in range(len(objects)):
        for second in range(first + 1, len(objects)):
            first_min, first_max = boxes[first]
            second_min, second_max = boxes[second]
            if any(
                first_min[axis] > second_max[axis] + margin_m
                or second_min[axis] > first_max[axis] + margin_m
                for axis in range(3)
            ):
                continue
            pairs.append((first, second))
    return pairs


def _cell_index(point, minimum, resolution_m, shape):
    """The cell holding an aligned point, or None when it is outside the grid."""
    index = tuple(
        math.floor((point[axis] - minimum[axis]) / resolution_m) for axis in range(3)
    )
    if all(0 <= index[axis] < shape[axis] for axis in range(3)):
        return index
    return None


def _region_of(cell, reached_in, reached_out, tolerance: int = REGION_TOLERANCE_CELLS):
    """Which region a cell belongs to: "in", "out", "both" or "" (neither)."""
    if cell is None:
        return ""
    inside = False
    outside = False
    for dx in range(-tolerance, tolerance + 1):
        for dy in range(-tolerance, tolerance + 1):
            for dz in range(-tolerance, tolerance + 1):
                neighbour = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                if not all(
                    0 <= neighbour[axis] < reached_in.shape[axis] for axis in range(3)
                ):
                    continue
                inside = inside or bool(reached_in[neighbour])
                outside = outside or bool(reached_out[neighbour])
    if inside and outside:
        return "both"
    if inside:
        return "in"
    if outside:
        return "out"
    return ""


@op(reads_only=True)
def enclosure_report(
    target: str | list[str],
    inside_points_m: tuple[tuple[float, float, float], ...] = (),
    outside: Literal["sky", "any"] = "sky",
    leak_minimum_m: float = 0.01,
    resolution_m: float = 0.02,
    allowed_opening_names: tuple[str, ...] = (),
) -> EnclosureReport:
    """Flood the space from inside points and sweep every junction: is it sealed, and where does it leak.

    `target` is the envelope — an object, a list, an assembly or a piece.
    `inside_points_m` are world points known to be inside the space; empty means
    the free cell nearest the target's centre, which is right for one room and
    wrong for a corridor, so name them when the space is not one blob. Each named
    point must be free (a point inside a wall raises and names itself).

    `outside` says what the space is sealed against: `sky` (nothing above it, so a
    ceiling and side walls are required but a floor is not) or `any` (a sealed
    interior, where the space below is another room and a floor is required too).

    Two kinds of leak are reported, because they are found two ways. A `hole` is
    a reached cell that is not enclosed by geometry on every side — a missing
    roof, a doorway, an open side — reported where the reached region meets the
    enclosed region. A `seam` is a line between two parts that touch: those walls
    look sealed, and a 2 mm gap running between two solid parts is invisible to a
    flood, so every junction's cross-section is swept with rays along the aligned
    axes and a ray that crosses from the inside region to the outside region is a
    cross. `junctions` says `sealed` or `leak` for every pair.

    The grid is aligned to the geometry's own yaw, so a room turned 37 degrees
    measures the same as the original and its leaks are reported in world
    coordinates. `resolution_m` is the voxel size; a grid over the cell cap
    raises with the resolution that would fit. `allowed_opening_names` are
    objects a leak is EXPECTED to pass through (a doorway, a window): a leak whose
    centre falls inside one of their bounds is reported with `allowed: true` and
    does not make the target unsealed. `sealed` is true when no un-allowed leak
    exists.
    """
    import bpy

    from golem_blender.analyze.occluders import OccluderIndex
    from golem_blender.ops.transforms import _world_bounds_m

    if resolution_m <= 0.0:
        raise ValueError(f"resolution_m must be positive, got {resolution_m!r}")
    if leak_minimum_m <= 0.0:
        raise ValueError(f"leak_minimum_m must be positive, got {leak_minimum_m!r}")
    if resolution_m > leak_minimum_m * MAXIMUM_RESOLUTION_PER_LEAK:
        raise ValueError(
            f"resolution_m={resolution_m:g} is coarser than the leaks this call "
            f"claims to find: a {leak_minimum_m:g} m opening cannot be represented "
            f"in {resolution_m:g} m cells, so a real leak would read sealed. Use "
            f"resolution_m <= "
            f"{leak_minimum_m * MAXIMUM_RESOLUTION_PER_LEAK:g}, or ask for a "
            f"coarser leak_minimum_m (the grid is capped at "
            f"{MAXIMUM_ENCLOSURE_CELLS} cells, so a big target may need both)."
        )
    if outside not in ("sky", "any"):
        raise ValueError(f"outside must be 'sky' or 'any', got {outside!r}")
    label, objects = resolve_mesh_targets(target)
    if not objects:
        raise UnknownObject(f"target {target!r} resolved to no MESH objects")
    if len(objects) < 2:
        # One part can be a closed shell, and a report of its interior is a
        # legitimate question; but a single open part is not an ENCLOSURE, and
        # silently answering "not sealed" for it would be a guess.
        pass
    _minimum_world, _maximum_world = _world_bounds_m(objects)
    triangles, owners, normals_and_areas = _world_triangles(objects)
    grid_yaw_deg = dominant_yaw_deg(normals_and_areas)
    origin = tuple(
        (_minimum_world[axis] + _maximum_world[axis]) / 2.0 for axis in range(3)
    )
    aligned_triangles = [
        tuple(aligned_point(corner, grid_yaw_deg, origin) for corner in triangle)
        for triangle in triangles
    ]
    aligned_minimum = aligned_point(_minimum_world, grid_yaw_deg, origin)
    aligned_maximum = aligned_point(_maximum_world, grid_yaw_deg, origin)
    # The aligned box must contain every rotated corner, not just the rotated
    # world box: a box rotated by 37 degrees has corners outside its own
    # world-aligned bounds once both are turned.
    for triangle in aligned_triangles:
        for corner in triangle:
            aligned_minimum = tuple(
                min(aligned_minimum[axis], corner[axis]) for axis in range(3)
            )
            aligned_maximum = tuple(
                max(aligned_maximum[axis], corner[axis]) for axis in range(3)
            )

    padding = GRID_PADDING_CELLS * resolution_m
    grid_minimum = tuple(value - padding for value in aligned_minimum)
    grid_maximum = tuple(value + padding for value in aligned_maximum)
    shape = tuple(
        max(1, math.ceil((grid_maximum[axis] - grid_minimum[axis]) / resolution_m))
        for axis in range(3)
    )
    cell_count = shape[0] * shape[1] * shape[2]
    if cell_count > MAXIMUM_ENCLOSURE_CELLS:
        fitting = resolution_that_fits(
            aligned_minimum,
            aligned_maximum,
            MAXIMUM_ENCLOSURE_CELLS,
        )
        raise ValueError(
            f"a {shape[0]} x {shape[1]} x {shape[2]} grid is {cell_count} cells, over "
            f"the {MAXIMUM_ENCLOSURE_CELLS}-cell cap for {len(objects)} parts; "
            f"resolution_m={fitting:g} is the smallest that fits. The target's "
            f"aligned extents are "
            f"{[round(aligned_maximum[axis] - aligned_minimum[axis], 3) for axis in range(3)]} m"
        )

    # SOLID, not surface: see `solid_voxels` — a surface-only mask lets a ray
    # travel through a wall's interior and reports every flush contact as a seam.
    per_object_triangles = [[] for _ in objects]
    for triangle, owner in zip(aligned_triangles, owners):
        per_object_triangles[owner].append(triangle)
    occupied = solid_voxels(per_object_triangles, grid_minimum, resolution_m, shape)
    free = ~occupied
    outside_shapes = _outside_seed_cells(shape, outside)
    reached_out = flood(free, outside_shapes)

    if inside_points_m:
        inside_cells = []
        for point in inside_points_m:
            aligned = aligned_point(tuple(point), grid_yaw_deg, origin)
            cell = _cell_index(aligned, grid_minimum, resolution_m, shape)
            if cell is None:
                raise ValueError(
                    f"inside point {tuple(point)} is outside the target's aligned "
                    f"grid; every inside point must lie within the geometry"
                )
            if occupied[cell]:
                raise ValueError(
                    f"inside point {tuple(point)} lands in an OCCUPIED cell "
                    f"(cell {cell}): the point is inside a wall, not the space"
                )
            inside_cells.append(cell)
    else:
        centre = aligned_point(origin, grid_yaw_deg, origin)
        cell = _cell_index(centre, grid_minimum, resolution_m, shape)
        if cell is None or occupied[cell]:
            # Walk outward from the centre for the nearest free cell, so a
            # solid object's own bbox centre does not refuse the call.
            cell = _nearest_free_cell(occupied, cell)
        if cell is None:
            raise ValueError(
                f"the target is solid at {resolution_m:g} m — there is no free cell "
                f"to flood from; pass inside_points_m"
            )
        inside_cells = [cell]
    reached_in = flood(free, inside_cells)

    leaks: list[EnclosureLeak] = []
    enclosed = enclosed_mask(occupied, outside)
    leaks.extend(
        _hole_leaks(
            reached_in,
            reached_out,
            enclosed,
            occupied,
            free,
            shape,
            grid_minimum,
            resolution_m,
            grid_yaw_deg,
            origin,
            objects,
            leak_minimum_m,
            aligned_minimum,
            aligned_maximum,
        )
    )

    occluders = OccluderIndex(objects)
    margin = max(2.0 * resolution_m, JUNCTION_MARGIN_MINIMUM_M)
    junction_pairs = _junction_pairs(objects, margin)
    junction_verdicts: list[JunctionVerdict] = []
    seam_leaks, junctions_with_leaks = _seam_leaks(
        objects,
        junction_pairs,
        occluders,
        aligned_minimum,
        aligned_maximum,
        grid_minimum,
        shape,
        resolution_m,
        grid_yaw_deg,
        origin,
        reached_in,
        reached_out,
        free,
        leak_minimum_m,
        inside_cells,
        margin,
    )
    leaks.extend(seam_leaks)
    for first, second in junction_pairs:
        junction_verdicts.append(
            JunctionVerdict(
                first_object_name=objects[first].name,
                second_object_name=objects[second].name,
                verdict="leak" if (first, second) in junctions_with_leaks else "sealed",
            )
        )

    allowed_bounds = []
    for object_name in allowed_opening_names:
        allowed_object = bpy.data.objects.get(object_name)
        if allowed_object is None or allowed_object.type != "MESH":
            raise UnknownObject(
                f"allowed_opening_names names {object_name!r}, which is not a MESH "
                f"object (mesh objects: "
                f"{sorted(o.name for o in bpy.data.objects if o.type == 'MESH')})"
            )
        low, high = _world_bounds_m([allowed_object])
        allowed_bounds.append(
            (
                tuple(low[axis] - 2.0 * resolution_m for axis in range(3)),
                tuple(high[axis] + 2.0 * resolution_m for axis in range(3)),
            )
        )
    finalised = []
    for leak in leaks:
        allowed = any(
            all(low[axis] <= leak.at_m[axis] <= high[axis] for axis in range(3))
            for low, high in allowed_bounds
        )
        finalised.append(_with_allowed(leak, allowed=allowed))
    finalised.sort(key=lambda leak: (leak.allowed, -leak.size_m, leak.kind))
    return EnclosureReport(
        target=label,
        sealed=not any(leak for leak in finalised if not leak.allowed),
        leaks=tuple(finalised),
        junctions=tuple(junction_verdicts),
        inside_points_m=tuple(
            world_point(
                _cell_centre(cell, grid_minimum, resolution_m), grid_yaw_deg, origin
            )
            for cell in inside_cells
        ),
        outside=outside,
        resolution_m=resolution_m,
        grid_yaw_deg=grid_yaw_deg,
        cell_count=cell_count,
    )


def _with_allowed(leak: EnclosureLeak, *, allowed: bool) -> EnclosureLeak:
    """A copy of `leak` with `allowed` set — one place, so the field list cannot drift."""
    return EnclosureLeak(
        at_m=leak.at_m,
        size_m=leak.size_m,
        direction=leak.direction,
        between=leak.between,
        kind=leak.kind,
        allowed=allowed,
    )


def _cell_centre(cell, minimum, resolution_m):
    return tuple(minimum[axis] + (cell[axis] + 0.5) * resolution_m for axis in range(3))


def _outside_seed_cells(shape, outside):
    """Every boundary cell of the padded grid, except the floor when the sky is up."""
    seeds = []
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                on_boundary = (
                    x in (0, shape[0] - 1)
                    or y in (0, shape[1] - 1)
                    or z in (0, shape[2] - 1)
                )
                if not on_boundary:
                    continue
                if outside == "sky" and z == 0:
                    continue
                seeds.append((x, y, z))
    return seeds


def _nearest_free_cell(occupied, start):
    """The free cell nearest `start` (or the grid's centre), searched by shell."""
    import numpy

    shape = occupied.shape
    if start is None:
        start = tuple(size // 2 for size in shape)
    if not occupied[start]:
        return start
    radius = 1
    while radius < max(shape):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    cell = (start[0] + dx, start[1] + dy, start[2] + dz)
                    if not all(0 <= cell[axis] < shape[axis] for axis in range(3)):
                        continue
                    if not occupied[cell]:
                        return cell
        radius += 1
    del numpy
    return None


def _hole_leaks(
    reached_in,
    reached_out,
    enclosed,
    occupied,
    free,
    shape,
    grid_minimum,
    resolution_m,
    grid_yaw_deg,
    origin,
    objects,
    leak_minimum_m,
    aligned_minimum,
    aligned_maximum,
):
    """Holes: reached cells that are not enclosed and are on the enclosed region's edge."""
    from golem_blender.analyze.occluders import OccluderIndex

    opening = reached_in & ~enclosed
    if not opening.any():
        # A sealed box: nothing reached is un-enclosed.
        return []
    if (reached_in & reached_out).any():
        # The inside and the outside are the SAME region: the space has no
        # separation at all — a room with no roof, a fence with no gate. There is
        # no enclosed region to take a boundary against, so the whole leak is
        # reported as one opening whose direction is the one the space is open
        # to. Measured need: a roofless room's `reached_in` and `reached_out` were
        # identical sets, and the per-cell boundary search reported the room's own
        # centre with a direction pointing at a wall.
        return _unseparated_leaks(
            reached_in,
            occupied,
            shape,
            grid_minimum,
            resolution_m,
            grid_yaw_deg,
            origin,
            objects,
            leak_minimum_m,
            aligned_minimum,
            aligned_maximum,
        )
    # A hole is where the reached region leaves the enclosed region: an opening
    # cell that touches an enclosed one. Without that adjacency, a room with no
    # roof at all would report every reached cell, which is not a leak report.
    touching = enclosed & reached_in
    boundary_cells = []
    for cell in zip(*opening.nonzero()):
        x, y, z = cell
        for dx, dy, dz in (
            (1, 0, 0),
            (-1, 0, 0),
            (0, 1, 0),
            (0, -1, 0),
            (0, 0, 1),
            (0, 0, -1),
        ):
            neighbour = (x + dx, y + dy, z + dz)
            if not all(0 <= neighbour[axis] < shape[axis] for axis in range(3)):
                continue
            if touching[neighbour]:
                boundary_cells.append(cell)
                break
    if not boundary_cells:
        boundary_cells = list(zip(*opening.nonzero()))
    index = OccluderIndex(objects)
    leaks = []
    for component in cluster_cells(boundary_cells):
        centre_cell = component[len(component) // 2]
        centre = _cell_centre(centre_cell, grid_minimum, resolution_m)
        extent = max(
            max(cell[axis] for cell in component)
            - min(cell[axis] for cell in component)
            for axis in range(3)
        )
        size = extent * resolution_m + resolution_m
        if size < leak_minimum_m:
            continue
        direction = _opening_direction(centre_cell, reached_out, shape, grid_yaw_deg)
        nearest = index.nearest_object_names(
            world_point(centre, grid_yaw_deg, origin), 2
        )
        leaks.append(
            EnclosureLeak(
                at_m=world_point(centre, grid_yaw_deg, origin),
                size_m=size,
                direction=direction,
                between=nearest,
                kind="hole",
                allowed=False,
            )
        )
    return leaks


def _unseparated_leaks(
    reached_in,
    occupied,
    shape,
    grid_minimum,
    resolution_m,
    grid_yaw_deg,
    origin,
    objects,
    leak_minimum_m,
    envelope_low,
    envelope_high,
):
    """Report where the space crosses its OWN envelope, when inside and outside merge.

    When the inside and the outside are one flood there is no enclosed region to
    take a boundary against — the space simply has no separation. What is still
    well defined is the ENVELOPE: the target's own aligned bounding box. Any exit
    crosses that box's shell, so the openings are exactly the free, reached cells
    on the shell, clustered.

    Measured need, twice: locating by "the grid face the flood covers most" and by
    "the boundary cell nearest the centre" both reported the same arbitrary point
    (1.02, -0.13, -0.12) for three unrelated fixtures, and a doorway's own bounds
    test then failed for a leak that was nowhere near the door. The envelope shell
    is where the answer actually is.
    """
    from golem_blender.analyze.occluders import OccluderIndex

    shell_cells = []
    for axis in range(3):
        others = [value for value in range(3) if value != axis]
        for edge in (envelope_low[axis], envelope_high[axis]):
            index = math.floor((edge - grid_minimum[axis]) / resolution_m)
            for offset in (-1, 0, 1):
                position = index + offset
                if not 0 <= position < shape[axis]:
                    continue
                selector = [slice(None)] * 3
                selector[axis] = position
                slab = reached_in[tuple(selector)]
                found = slab.nonzero()
                for first, second in zip(*found):
                    cell = [0, 0, 0]
                    cell[axis] = position
                    cell[others[0]] = int(first)
                    cell[others[1]] = int(second)
                    shell_cells.append(tuple(cell))
    if not shell_cells:
        return []
    index_of_geometry = OccluderIndex(objects)
    leaks = []
    for component in cluster_cells(shell_cells):
        # The component here is the WHOLE open shell, so its extent is the
        # target's own size. Reporting that as the "leak size" would be a 2 m
        # hole, which is not a number anybody acts on; the smallest envelope
        # dimension is the space that has no separation, which is.
        size = min(envelope_high[value] - envelope_low[value] for value in range(3))
        if size < leak_minimum_m:
            continue

        # WHICH cell of the shell: the one FURTHEST from the target's geometry.
        # That is the mouth — the middle of the opening. Taking the middle of the
        # cluster instead gave the cluster's own midpoint along the shell, which
        # for a merged region is an arbitrary wall: measured, a declared skylight
        # over an open-topped room reported its leak at z = 0.06 (the floor) while
        # the roof gap was at z = 2.0.
        def opening_clearance(cell):
            point = world_point(
                _cell_centre(cell, grid_minimum, resolution_m), grid_yaw_deg, origin
            )
            return index_of_geometry.nearest_distance_m(point)

        middle = max(component, key=opening_clearance)
        centre = _cell_centre(middle, grid_minimum, resolution_m)
        # Direction: INSIDE -> OUTSIDE, i.e. from the envelope's centre through
        # this opening. Stated in world, which is what a reader looks along.
        envelope_centre = [
            (envelope_low[value] + envelope_high[value]) / 2.0 for value in range(3)
        ]
        offset = [centre[value] - envelope_centre[value] for value in range(3)]
        length = math.sqrt(sum(value * value for value in offset))
        direction_aligned = (
            tuple(value / length for value in offset) if length else (0.0, 0.0, 1.0)
        )
        at = world_point(centre, grid_yaw_deg, origin)
        leaks.append(
            EnclosureLeak(
                at_m=at,
                size_m=size,
                direction=_world_direction(direction_aligned, grid_yaw_deg),
                between=index_of_geometry.nearest_object_names(at, 2),
                kind="hole",
                allowed=False,
            )
        )
    return leaks


def _boundary_cells(reached_in, shape):
    """The reached cells on the grid's own boundary, as a list."""
    cells = []
    for axis in range(3):
        for index in (0, shape[axis] - 1):
            selector = [slice(None)] * 3
            selector[axis] = index
            slab = reached_in[tuple(selector)]
            found = slab.nonzero()
            for position in zip(*found):
                cell = [0, 0, 0]
                others = [value for value in range(3) if value != axis]
                cell[axis] = index
                cell[others[0]] = int(position[0])
                cell[others[1]] = int(position[1])
                cells.append(tuple(cell))
    return cells


def _nearest_cluster(cell, cells):
    """The 26-connected component of `cells` containing `cell`."""
    for component in cluster_cells(cells):
        if cell in component:
            return component
    return [cell]


def _opening_direction(cell, reached_out, shape, grid_yaw_deg, resolution_m=1.0):
    """The unit direction from a hole toward the outside it reaches, in world.

    Pointing at the reachable OUTSIDE is the physical statement a reader acts on:
    a missing roof points at the sky, a doorway points out of the door. Averaging
    the axes on which the cells are un-enclosed instead produced a floor-pointing
    vector for a room with no roof at all — measured, and wrong: the room is open
    upward, and there are simply more cells below than above.
    """
    # The nearest OUTSIDE cell reached through a FREE path is the direction the
    # opening faces. Skipping occupied cells is what makes "no roof" point at the
    # sky rather than at whatever solid happens to be nearest: measured, a room
    # with its roof removed reported direction (-1, 0, 0) — pointing at a WALL,
    # because a wall cell was the closest reached_out cell that existed.
    target = _nearest_true(cell, reached_out, shape)
    if target is None:
        return (0.0, 0.0, 1.0)
    offset = [target[axis] - cell[axis] for axis in range(3)]
    length = math.sqrt(sum(value * value for value in offset))
    if length == 0.0:
        return (0.0, 0.0, 1.0)
    aligned = tuple(value / length for value in offset)
    return _world_direction(aligned, grid_yaw_deg)


def _nearest_true(cell, mask, shape, maximum_radius: int = 64):
    """The nearest cell of `mask` to `cell`, searched by growing shell."""
    import numpy

    for radius in range(1, maximum_radius + 1):
        best = None
        best_distance = math.inf
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy), abs(dz)) != radius:
                        continue
                    candidate = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                    if not all(0 <= candidate[axis] < shape[axis] for axis in range(3)):
                        continue
                    if not mask[candidate]:
                        continue
                    distance = dx * dx + dy * dy + dz * dz
                    if distance < best_distance:
                        best, best_distance = candidate, distance
        if best is not None:
            return best
    del numpy
    return None


def _aligned_bounds(blender_object, grid_yaw_deg, origin):
    """One part's world box, in the aligned frame.

    All EIGHT corners are rotated, not just the two opposite ones: a box turned
    37 degrees has a corner further along an aligned axis than its rotated
    min/max corner pair, and reading only the pair shrinks the box — which moves
    the junction region and makes the sweep test the wrong place.
    """
    from golem_blender.ops.transforms import _world_bounds_m

    low, high = _world_bounds_m([blender_object])
    corners = []
    for x in (low[0], high[0]):
        for y in (low[1], high[1]):
            for z in (low[2], high[2]):
                corners.append(aligned_point((x, y, z), grid_yaw_deg, origin))
    return (
        tuple(min(corner[axis] for corner in corners) for axis in range(3)),
        tuple(max(corner[axis] for corner in corners) for axis in range(3)),
    )


def _seam_leaks(
    objects,
    junction_pairs,
    occluders,
    aligned_minimum,
    aligned_maximum,
    grid_minimum,
    shape,
    resolution_m,
    grid_yaw_deg,
    origin,
    reached_in,
    reached_out,
    free,
    leak_minimum_m,
    inside_cells,
    margin_m,
):
    """Sweep every junction's cross-section; report the rays that cross inside -> out.

    Two parts that MEET are sealed by their contact, and flood fill already agrees
    with them even when a hairline gap runs between two solid parts — the gap is
    not a hole either part's surface has. So each junction's shared region is
    swept with rays along its three aligned axes: a ray that crosses the whole
    region and meets nothing, starting in the inside region and ending in the
    outside region, is a seam a character could breathe through.

    The origins sit on a grid across the CROSS-SECTION with spacing half the leak
    minimum, so a leak the size of the minimum cannot be stepped over.
    """

    from golem_blender.analyze.occluders import OccluderIndex

    crossings: dict[tuple[int, int], list[tuple]] = {}
    spacing = leak_minimum_m * SWEEP_SPACING_FRACTION
    clearance = SWEEP_CLEARANCE_CELLS * resolution_m
    seam_clearance_m = leak_minimum_m * SEAM_CLEARANCE_FRACTION
    for first, second in junction_pairs:
        # The pair's own surfaces, for the clearance test below: a ray with no
        # room between the two parts is grazing a flush contact, not passing
        # through a seam. Measured defect this fixes: a wall's top meeting a
        # roof's underside flush reported 2 cm "seams" at every sample whose ray
        # happened to travel exactly along the shared plane.
        pair_index = OccluderIndex([objects[first], objects[second]])
        first_low, first_high = _aligned_bounds(objects[first], grid_yaw_deg, origin)
        second_low, second_high = _aligned_bounds(objects[second], grid_yaw_deg, origin)
        region_low = tuple(
            max(first_low[axis], second_low[axis]) - margin_m for axis in range(3)
        )
        region_high = tuple(
            min(first_high[axis], second_high[axis]) + margin_m for axis in range(3)
        )
        # A pair that only NEARS is still a junction, but a pair whose boxes do
        # not intersect at all has no shared region: its gap is a hole, found by
        # the flood, and sweeping it would report the nearest two walls as a seam.
        if any(region_low[axis] > region_high[axis] for axis in range(3)):
            region_low = tuple(
                min(first_low[axis], second_low[axis]) for axis in range(3)
            )
            region_high = tuple(
                max(first_high[axis], second_high[axis]) for axis in range(3)
            )
        for axis, sign in SWEEP_DIRECTIONS:
            other_axes = [value for value in range(3) if value != axis]
            first_other, second_other = other_axes
            count_first = max(
                1,
                math.floor(
                    (region_high[first_other] - region_low[first_other]) / spacing
                )
                + 1,
            )
            count_second = max(
                1,
                math.floor(
                    (region_high[second_other] - region_low[second_other]) / spacing
                )
                + 1,
            )
            found: list[tuple] = []
            for index_first in range(count_first):
                for index_second in range(count_second):
                    start_point = [0.0, 0.0, 0.0]
                    start_point[axis] = (
                        region_low[axis] - clearance
                        if sign > 0
                        else region_high[axis] + clearance
                    )
                    start_point[first_other] = (
                        region_low[first_other] + (index_first + 0.5) * spacing
                    )
                    start_point[second_other] = (
                        region_low[second_other] + (index_second + 0.5) * spacing
                    )
                    end_point = list(start_point)
                    end_point[axis] = (
                        region_high[axis] + clearance
                        if sign > 0
                        else region_low[axis] - clearance
                    )
                    direction = [0.0, 0.0, 0.0]
                    direction[axis] = float(sign)
                    length = end_point[axis] - start_point[axis]
                    hits = occluders.cast(
                        world_point(tuple(start_point), grid_yaw_deg, origin),
                        _world_direction(tuple(direction), grid_yaw_deg),
                        maximum_hits=1,
                        maximum_distance_m=abs(length) + 2.0 * clearance,
                    )
                    if hits:
                        continue
                    start_cell = _cell_index(
                        start_point, grid_minimum, resolution_m, shape
                    )
                    end_cell = _cell_index(end_point, grid_minimum, resolution_m, shape)
                    # Both ends must be FREE. A ray whose origin is INSIDE a
                    # solid meets nothing on its way out, so without this check
                    # a sweep that starts in the middle of the roof reports the
                    # roof's own thickness as an open seam — measured: a flush
                    # six-wall room read as two seams of 0.07 m.
                    if (
                        start_cell is None
                        or end_cell is None
                        or not free[start_cell]
                        or not free[end_cell]
                    ):
                        continue
                    start_region = _region_of(start_cell, reached_in, reached_out)
                    end_region = _region_of(end_cell, reached_in, reached_out)
                    if {start_region, end_region} != {"in", "out"}:
                        continue
                    middle = tuple(
                        (start_point[axis] + end_point[axis]) / 2.0 for axis in range(3)
                    )
                    if (
                        pair_index.nearest_distance_m(
                            world_point(middle, grid_yaw_deg, origin)
                        )
                        < seam_clearance_m
                    ):
                        continue
                    inside_end = start_point if start_region == "in" else end_point
                    found.append(
                        (
                            index_first,
                            index_second,
                            tuple(
                                (start_point[axis] + end_point[axis]) / 2.0
                                for axis in range(3)
                            ),
                            axis,
                            sign,
                            inside_end,
                        )
                    )
            if not found:
                continue
            # Clusters on adjacent origin indices are ONE crack, not N leaks.
            cell_keys = {(entry[0], entry[1]) for entry in found}
            by_cell = {(entry[0], entry[1]): entry for entry in found}
            for component in _cluster_cells_2d(cell_keys):
                entries = [by_cell[cell] for cell in component]
                centres = [entry[2] for entry in entries]
                centre = tuple(
                    sum(value[axis] for value in centres) / len(centres)
                    for axis in range(3)
                )
                span_first = (
                    max(entry[0] for entry in entries)
                    - min(entry[0] for entry in entries)
                    + 1
                ) * spacing
                span_second = (
                    max(entry[1] for entry in entries)
                    - min(entry[1] for entry in entries)
                    + 1
                ) * spacing
                size = max(span_first, span_second)
                if size < leak_minimum_m:
                    continue
                axis = entries[0][3]
                sign = entries[0][4]
                direction_aligned = [0.0, 0.0, 0.0]
                direction_aligned[axis] = float(sign)
                crossings.setdefault((first, second), []).append(
                    EnclosureLeak(
                        at_m=world_point(centre, grid_yaw_deg, origin),
                        size_m=size,
                        direction=_world_direction(
                            tuple(direction_aligned), grid_yaw_deg
                        ),
                        between=(objects[first].name, objects[second].name),
                        kind="seam",
                        allowed=False,
                    )
                )
    leaks = []
    for entries in crossings.values():
        leaks.extend(entries)
    return leaks, set(crossings)


def _cluster_cells_2d(cells) -> list[list[tuple[int, int]]]:
    """8-connected components of 2-D indices, sorted, components by smallest member."""
    remaining = set(cells)
    components = []
    offsets = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    while remaining:
        seed = min(remaining)
        remaining.discard(seed)
        component = [seed]
        frontier = [seed]
        while frontier:
            x, y = frontier.pop()
            for dx, dy in offsets:
                neighbour = (x + dx, y + dy)
                if neighbour in remaining:
                    remaining.discard(neighbour)
                    component.append(neighbour)
                    frontier.append(neighbour)
        components.append(sorted(component))
    components.sort(key=lambda component: component[0])
    return components


def _world_direction(aligned_direction, grid_yaw_deg):
    """Rotate an aligned unit direction back into world."""
    radians = math.radians(grid_yaw_deg)
    cos, sin = math.cos(radians), math.sin(radians)
    return (
        aligned_direction[0] * cos - aligned_direction[1] * sin,
        aligned_direction[0] * sin + aligned_direction[1] * cos,
        aligned_direction[2],
    )
