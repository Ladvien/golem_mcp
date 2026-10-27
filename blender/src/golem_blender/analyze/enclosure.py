"""Is this space sealed, and where does it leak — the two questions a room asks.

The measured need: a Sanctuary abbey was rendering light through a wall and the
leak was visible only in a night render. Whether a space is SEALED has two halves, and a report that
answers only one is worse than none:

1. **Is there a hole?** Voxelise the parts, flood the free space from the inside
   seeds, and ask which reached cells are on the boundary of the enclosed region.
   That finds a missing roof, a doorway, an unbounded room — a leak you could
   walk through.

2. **Does a JOINT leak?** Two walls meeting flush look sealed and are: a joint
   with a 2 mm gap between two solid parts is not a hole, and flood fill cannot
   see it because both parts still block the flood on either side of the seam.
   So every junction between two parts whose boxes touch is SWEPT with rays
   along the three aligned axes, and a ray that crosses from the inside region
   to the outside region without hitting anything is a seam leak.

The frame is ALIGNED to the geometry first (`dominant_yaw_deg`): a room turned
37 degrees is the same room, and a grid built on world X/Y would zig-zag its
walls into a staircase of false leaks. Everything is measured in the aligned
frame and reported back in world.

Pure helpers here (no bpy, no numpy) are the two decisions that a test can pin
without a scene; the numpy half is imported inside the functions, because
Blender's Python has numpy and the dev venv does not.
"""

from __future__ import annotations

import math

# A cap on the voxel grid. 16M cells at 2 cm is a 40 m cube: bigger than any
# room this is asked about, and small enough that the flood is interactive.
MAXIMUM_ENCLOSURE_CELLS = 16_000_000
# The grid is padded so a boundary cell exists on every side: the flood needs
# somewhere to start, and a room that touches the grid edge would otherwise
# have no "outside" to reach.
GRID_PADDING_CELLS = 2
# Two parts whose boxes are within this of each other are a JUNCTION and get
# swept. Below the minimum it stops being a joint and becomes a gap the flood
# already reports as a hole.
JUNCTION_MARGIN_MINIMUM_M = 0.05
# The sweep's origin sits this many cells beyond the junction region's own face,
# so the ray starts outside the region it is testing.
SWEEP_CLEARANCE_CELLS = 2
# A leak smaller than this is a voxel artefact, not a defect.
MINIMUM_REPORTED_LEAK_M = 0.005
# Azimuth bins for the alignment histogram: half a degree resolves a wall that
# was rotated by hand from one that was rotated by 37 degrees.
YAW_BIN_DEG = 0.5
# A face steeper than this (|n_z| above it) is a FLOOR or a CEILING and says
# nothing about the plan's yaw.
YAW_VERTICAL_FACE_LIMIT = 0.5


def dominant_yaw_deg(normals_and_areas) -> float:
    """The plan-view rotation of a piece of geometry, in degrees, from its faces.

    An area-weighted histogram of each face's azimuth mod 90 degrees, in
    `YAW_BIN_DEG` bins, returning the best bin's centre. Mod 90 because a room's
    walls are perpendicular in pairs: a wall at 37 and a wall at 127 vote for the
    SAME rotation, and taking them separately would split the vote.

    Vertical faces only (|n_z| under `YAW_VERTICAL_FACE_LIMIT`): a floor's normal
    is straight up and its azimuth is 0 by accident, and a room with a big floor
    would vote itself back to world axes.
    """
    histogram: dict[float, float] = {}
    for normal, area in normals_and_areas:
        length = math.sqrt(sum(component * component for component in normal))
        if length == 0.0 or area <= 0.0:
            continue
        unit = tuple(component / length for component in normal)
        if abs(unit[2]) >= YAW_VERTICAL_FACE_LIMIT:
            continue
        azimuth = math.degrees(math.atan2(unit[1], unit[0])) % 90.0
        bin_centre = (math.floor(azimuth / YAW_BIN_DEG) + 0.5) * YAW_BIN_DEG
        histogram[bin_centre] = histogram.get(bin_centre, 0.0) + area
    if not histogram:
        return 0.0
    # Biggest bin wins; a tie goes to the smaller angle so the answer is stable.
    best = max(histogram.items(), key=lambda item: (item[1], -item[0]))
    return float(best[0])


def cluster_cells(cells) -> list[list[tuple[int, int, int]]]:
    """26-connected components of a cell set, each sorted, components by smallest cell.

    26-connectivity, not 6: a leak is a surface defect and two cells that share
    only an EDGE are the same opening. Sorting makes the result deterministic,
    which is what lets a test compare a rotated room with its original.
    """
    remaining = set(cells)
    components: list[list[tuple[int, int, int]]] = []
    offsets = [
        (dx, dy, dz)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        for dz in (-1, 0, 1)
        if (dx, dy, dz) != (0, 0, 0)
    ]
    while remaining:
        seed = min(remaining)
        remaining.discard(seed)
        component = [seed]
        frontier = [seed]
        while frontier:
            x, y, z = frontier.pop()
            for dx, dy, dz in offsets:
                neighbour = (x + dx, y + dy, z + dz)
                if neighbour in remaining:
                    remaining.discard(neighbour)
                    component.append(neighbour)
                    frontier.append(neighbour)
        components.append(sorted(component))
    components.sort(key=lambda component: component[0])
    return components


def aligned_point(point, yaw_deg: float, origin) -> tuple[float, float, float]:
    """`point` in the frame turned BACK by `yaw_deg` about +Z around `origin`.

    Rotating by -yaw is what puts a room's own walls on the grid's axes: the
    world-space walls at 37 degrees become axis-aligned here, and every grid cell,
    ray and junction box below is axis-aligned as a result.
    """
    radians = math.radians(-yaw_deg)
    cos, sin = math.cos(radians), math.sin(radians)
    dx = point[0] - origin[0]
    dy = point[1] - origin[1]
    return (dx * cos - dy * sin, dx * sin + dy * cos, point[2] - origin[2])


def world_point(aligned, yaw_deg: float, origin) -> tuple[float, float, float]:
    """The exact inverse of `aligned_point`."""
    radians = math.radians(yaw_deg)
    cos, sin = math.cos(radians), math.sin(radians)
    return (
        origin[0] + aligned[0] * cos - aligned[1] * sin,
        origin[1] + aligned[0] * sin + aligned[1] * cos,
        origin[2] + aligned[2],
    )


def flood_neighbours(cell: tuple[int, int, int]):
    """The 6 axis neighbours of a cell — the free space one voxel step away."""
    x, y, z = cell
    return (
        (x + 1, y, z),
        (x - 1, y, z),
        (x, y + 1, z),
        (x, y - 1, z),
        (x, y, z + 1),
        (x, y, z - 1),
    )


def resolution_that_fits(
    minimum, maximum, maximum_cells: int = MAXIMUM_ENCLOSURE_CELLS
):
    """The smallest resolution (rounded up to 1 mm) whose padded grid fits the cap.

    The padding is counted, because the grid that is allocated is the padded one:
    computing a resolution from the unpadded box is how a compliant-looking call
    still allocates past the cap.
    """
    extents = [maximum[axis] - minimum[axis] for axis in range(3)]
    volume = extents[0] * extents[1] * extents[2]
    # cells = product(ceil((extent + 2*pad*r) / r)) ~= product(extent / r) for
    # r << extent, so the cube-root estimate is the right starting point and the
    # exact loop below only ever corrects it upward.
    estimate = (volume / max(1, maximum_cells)) ** (1.0 / 3.0)
    resolution = max(math.ceil(estimate * 1000.0) / 1000.0, 0.001)
    while True:
        shape = [
            math.ceil(
                (extents[axis] + 2.0 * GRID_PADDING_CELLS * resolution) / resolution
            )
            for axis in range(3)
        ]
        if shape[0] * shape[1] * shape[2] <= maximum_cells:
            return resolution
        resolution = math.ceil((resolution + 0.001) * 1000.0) / 1000.0
        if resolution > max(extents) or resolution > 1000.0:
            raise ValueError(
                f"no resolution above 1 mm fits {shape[0] * shape[1] * shape[2]} "
                f"cells within the {maximum_cells}-cell cap for extents {extents}"
            )


# --- the numpy half (Blender's Python only) ---------------------------------
#
# These import numpy INSIDE the function: Blender ships 2.3.4 and the dev venv
# has none, so a module-level import would make every pure test fail on an
# import that is only needed in the scene half.


def voxelise(triangles, minimum, resolution_m: float, shape):
    """A boolean grid: which cells a triangle set touches.

    Each triangle is sampled on a barycentric grid with spacing at most half a
    cell, so a triangle thinner than a voxel still marks the voxels it crosses.
    Sampling the three corners alone would leave a wall with a hole wherever a
    face is bigger than a voxel — which is every wall.

    `triangles` are in the ALIGNED frame and `minimum` is the grid's corner, so
    cell (i, j, k) spans [minimum + (i,j,k) * resolution, + resolution).
    """
    import numpy

    occupied = numpy.zeros(shape, dtype=bool)
    for corners in triangles:
        edge_1 = [corners[1][axis] - corners[0][axis] for axis in range(3)]
        edge_2 = [corners[2][axis] - corners[0][axis] for axis in range(3)]
        longest = max(
            math.sqrt(sum(component * component for component in edge))
            for edge in (edge_1, edge_2)
        )
        steps = max(1, math.ceil(longest / (resolution_m / 2.0)))
        samples = []
        for i in range(steps + 1):
            for j in range(steps + 1 - i):
                u = i / steps
                v = j / steps
                samples.append(
                    tuple(
                        corners[0][axis] + edge_1[axis] * u + edge_2[axis] * v
                        for axis in range(3)
                    )
                )
        for point in samples:
            index = tuple(
                math.floor((point[axis] - minimum[axis]) / resolution_m)
                for axis in range(3)
            )
            if all(0 <= index[axis] < shape[axis] for axis in range(3)):
                occupied[index] = True
    return occupied


def solid_voxels(triangles_by_object, minimum, resolution_m: float, shape):
    """A boolean grid of SOLID cells: each part's surface and everything inside it.

    `voxelise` marks the SURFACE a triangle crosses, which is right for "is there
    geometry here" and wrong for "can a ray pass here": a 0.1 m wall at a 2 cm
    resolution has three free cells through its middle, and a ray along the wall
    travels inside the solid and meets no surface at all. Measured consequence of
    the surface-only mask: every flush wall-to-roof contact read as a 2 cm seam,
    because the sweep's ray ran through the roof's interior and nothing stopped
    it.

    The interior is the part's bounding box minus the cells its own outside can
    reach: a closed shell's inside is exactly what its outside cannot reach. Done
    PER PART, because one part's interior is another part's room — a room's
    inside is also unreachable from outside, and a whole-scene flood could not
    tell the two apart.

    A part whose surface has a gap has no interior here — its own outside reaches
    its middle — which is correct: an open shell encloses nothing.
    """
    import numpy

    solid = numpy.zeros(shape, dtype=bool)
    for triangles in triangles_by_object:
        surface = voxelise(triangles, minimum, resolution_m, shape)
        if not surface.any():
            continue
        # The part's own box, EXACTLY: the surface grid already marks every cell
        # a face crosses, so growing the box would claim the free ring around it
        # as "interior". Measured cost of a one-cell growth: a 2 cm slot between
        # a floor's edge and a wall was swallowed by the floor's own box fill and
        # the room read sealed.
        low = [
            max(
                0,
                math.floor(
                    (
                        min(corner[axis] for t in triangles for corner in t)
                        - minimum[axis]
                    )
                    / resolution_m
                ),
            )
            for axis in range(3)
        ]
        high = [
            min(
                shape[axis],
                math.ceil(
                    (
                        max(corner[axis] for t in triangles for corner in t)
                        - minimum[axis]
                    )
                    / resolution_m
                )
                + 1,
            )
            for axis in range(3)
        ]
        included = numpy.zeros(shape, dtype=bool)
        included[low[0] : high[0], low[1] : high[1], low[2] : high[2]] = True
        if not included.any():
            solid |= surface
            continue
        seeds = [
            (x, y, z)
            for x in range(max(0, low[0] - 1), min(shape[0], high[0] + 1))
            for y in range(max(0, low[1] - 1), min(shape[1], high[1] + 1))
            for z in range(max(0, low[2] - 1), min(shape[2], high[2] + 1))
            if (
                x < low[0]
                or x >= high[0]
                or y < low[1]
                or y >= high[1]
                or z < low[2]
                or z >= high[2]
            )
        ]
        reached = flood(~surface, seeds)
        solid |= surface
        solid |= included & ~reached
    return solid


def flood(free, seeds):
    """Every free cell reachable from `seeds`, by 6-neighbour frontier dilation.

    Dilation with shifts rather than a Python queue: a 16M-cell grid at one cell
    per Python step is minutes, and the whole point of the cap is that this stays
    interactive.
    """
    import numpy

    reached = numpy.zeros(free.shape, dtype=bool)
    for seed in seeds:
        inside_grid = all(0 <= seed[axis] < free.shape[axis] for axis in range(3))
        if inside_grid and free[seed]:
            reached[seed] = True
    frontier = reached.copy()
    while frontier.any():
        grown = numpy.zeros(free.shape, dtype=bool)
        grown[1:, :, :] |= frontier[:-1, :, :]
        grown[:-1, :, :] |= frontier[1:, :, :]
        grown[:, 1:, :] |= frontier[:, :-1, :]
        grown[:, :-1, :] |= frontier[:, 1:, :]
        grown[:, :, 1:] |= frontier[:, :, :-1]
        grown[:, :, :-1] |= frontier[:, :, 1:]
        grown &= free
        grown &= ~reached
        reached |= grown
        frontier = grown
    return reached


def enclosed_mask(occupied, outside: str):
    """Cells with occupied geometry on BOTH sides along every axis.

    The plan-view test for "inside": a cell that has geometry to its left AND to
    its right, in front AND behind, and (for `outside == "sky"`) above but none
    below is enclosed on every side a player cannot leave through. Reading it
    this way — geometry beyond me, in both directions — is a plan test, so a room
    with a missing roof is NOT enclosed: nothing is above it.

    `outside == "any"` also demands a floor, which is what a sealed INTERIOR
    means when the space below is another room rather than the sky.

    Each test is two cumulative ORs on a boolean array (one per direction), so
    the whole mask is six passes and no per-cell Python.
    """
    import numpy

    enclosed = numpy.ones(occupied.shape, dtype=bool)
    for axis in (0, 1, 2):
        enclosed &= _geometry_beyond(occupied, axis, higher=True)
        # The sky is ABOVE, so with outside == "sky" a cell needs a ceiling but
        # no floor; every other direction is required in both modes.
        if not (outside == "sky" and axis == 2):
            enclosed &= _geometry_beyond(occupied, axis, higher=False)
    return enclosed


def _geometry_beyond(mask, axis: int, *, higher: bool):
    """For each cell: is any occupied cell at a STRICTLY higher (or lower) index
    along `axis`?

    One direction is implemented and the other is the SAME test on the reversed
    axis — a cell at index i has something lower if, when the axis is flipped, it
    has something higher. Writing both by hand is how the first version of this
    got one of them backwards (measured: it read "nothing below" as "nothing
    above" and called a roofed room with a floor unenclosed).
    """
    import numpy

    if not higher:
        return numpy.flip(
            _geometry_beyond(numpy.flip(mask, axis=axis), axis, higher=True), axis=axis
        )
    # index i should hold mask[i + 1], so a cell never counts itself as its own
    # occluder along its own axis.
    shifted = mask.copy()
    take = [slice(None)] * 3
    give = [slice(None)] * 3
    take[axis] = slice(1, None)
    give[axis] = slice(None, -1)
    shifted[tuple(give)] = mask[tuple(take)]
    edge_index = [slice(None)] * 3
    edge_index[axis] = -1
    shifted[tuple(edge_index)] = False
    flipped = numpy.flip(shifted, axis=axis)
    return numpy.flip(numpy.cumsum(flipped, axis=axis), axis=axis) > 0
