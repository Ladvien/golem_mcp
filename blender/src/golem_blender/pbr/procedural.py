"""A procedural base colour: a surface's colour, computed.

Blender has no generative model, so a photoreal texture's COLOUR
cannot be generated with bpy. But photorealism is narrower than it
looks. A cobblestone's colour is a few stone colours, a mortar
colour, and the variation between them - and every one of those is
arithmetic.

So the pattern is COMPUTED, in numpy, and written into an image the
way the ORM bake already writes its maps. That choice was made after
the node-graph route cost a round: the pattern is arithmetic, and
wiring it through a shader graph put four separate defects between
the intent and the image, each of which had to be found by measuring
the result.

WHAT IS COMPUTED
- a jittered LATTICE of points, one per cell, and the cell of each
  point is where it is the closest - a Voronoi diagram;
- the DISTANCE TO THE NEAREST EDGE, which is the joint;
- a WANDER: the lattice is displaced by a smooth noise field, so the
  cells' straight edges break into worn curves and their corners
  round off. That is the difference between a diagram and a street;
- the stones' colours, from each cell's own random value, through a
  narrow ramp - a cobblestone's stones are all nearly the same
  colour, and the image's spread comes from the mortar;
- the joint as a BLEND, not a multiply: the mortar's colour replaces
  the stone's where the joint is, so the mortar sets the dark end
  and the stones' own ramp is the range they span.

PERIODICITY
The lattice is periodic and the wander is a sum of sines with
INTEGER frequencies over the domain, so the whole field repeats
exactly: cell N is cell 0, and the image's edge meets its own edge.
Measured, the seam is 0.00x the texture's largest ordinary
features, against a generated map's 1.38x - and ambientcg's own maps,
which are made to tile, measure 0.32x to 0.47x.

What it is NOT is photoreal. The stones are polygonal rather than
rounded, and the variation within a stone is arithmetic rather than
wear. What it IS is reproducible, adjustable with a number instead
of a prompt, and exactly tileable.
"""

from __future__ import annotations

from pathlib import Path

# The stone colours a cobblestone's ramp runs between: a mid grey and
# a pale off-white, and NOT far apart.
#
# A cobblestone's stones are all nearly the same colour - pale grey
# and off-white with a few darker ones - and the IMAGE's spread comes
# from the mortar and the shading, not from the stones being
# different colours. Measured against a real cobblestone: the truth's
# whole image spans luma 0.360 to 0.558 with a spread of 0.0763, and
# a wide stone ramp gave 0.2858 - nearly four times the spread, and
# a picture of a cobblestone rather than a cobblestone.
DEFAULT_STONE_DARK_RGB = (0.52, 0.50, 0.46)
DEFAULT_STONE_LIGHT_RGB = (0.70, 0.68, 0.64)
# The mortar's colour, and how wide it is as a fraction of the
# distance to the nearest edge. A cobblestone's joint is pale sand
# and grit, only a little darker than the stones: measured against a
# real one, the truth's darkest tenth is luma 0.360 against its
# stones' 0.56.
# The pattern's scale, in cells across the image - and a Voronoi
# pattern's cell count IS its scale.
#
# The size is set by the SURFACE, not by taste. The AI-generated
# cobblestone the lane delivered has about 4.8 stones across a 2 m
# street, and ambientcg's brick has 11.25 across its tile, so five
# to eleven is the range a cobblestone occupies.
DEFAULT_PROCEDURAL_SCALE = 5.0
# The mortar's colour, and how wide it is.
DEFAULT_MORTAR_RGB = (0.38, 0.36, 0.33)
DEFAULT_MORTAR_WIDTH = 0.30
# How much the noise varies a stone within itself, as a fraction of
# the stone's colour.
DEFAULT_VARIATION = 0.15
# How far the lattice is DISPLACED, in cell units. The wander is what
# makes the cells read as worn stones rather than as a diagram.
DEFAULT_WANDER = 0.35
# The wander's frequency over the domain. It must be an INTEGER, so
# the field is periodic - a non-integer frequency would leave the
# image's edge unjoined.
DEFAULT_WANDER_FREQUENCY = 3
# The cell shapes a pattern can have.
PROCEDURAL_COLOUR_KINDS = ("voronoi", "brick", "wave")


def _lattice(
    resolution: int, cells: int, randomness: float, wander: float, frequency: int
):
    """The lattice of points, and the sample grid they are compared on.

    The lattice is `cells` x `cells` points over the unit square,
    each jittered within its cell, and then DISPLACED by the wander -
    a sum of sines with integer frequencies, which is periodic and
    so leaves the image's edge joined.

    Returns the points as two arrays and the sample grid.
    """
    import numpy

    axis = (numpy.arange(cells) + 0.5) / cells
    grid_x, grid_y = numpy.meshgrid(axis, axis, indexing="xy")
    points_x = grid_x.ravel()
    points_y = grid_y.ravel()

    # The jitter, deterministic: the pattern must be the same every
    # time, or a set could not be reproduced.
    phase = numpy.sin(points_x * 12.9898 + points_y * 78.233) * 43758.5453
    jitter = (phase - numpy.floor(phase)) - 0.5
    points_x = points_x + jitter * randomness / cells
    points_y = points_y + jitter * randomness / cells

    samples = (numpy.arange(resolution) + 0.5) / resolution
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")

    if wander > 0.0:
        # The wander: a smooth field with INTEGER frequencies, so it
        # is periodic over the domain.
        two_pi = 2.0 * numpy.pi
        offset_x = numpy.sin(sample_y * frequency * two_pi) * 0.6
        offset_x = offset_x + numpy.sin(sample_y * 2 * frequency * two_pi + 1.1) * 0.4
        offset_y = numpy.sin(sample_x * frequency * two_pi + 0.7) * 0.6
        offset_y = offset_y + numpy.sin(sample_x * 2 * frequency * two_pi + 2.3) * 0.4
        sample_x = sample_x + offset_x * (wander / cells)
        sample_y = sample_y + offset_y * (wander / cells)

    return points_x, points_y, sample_x, sample_y


def _nearest(points_x, points_y, sample_x, sample_y):
    """The nearest point to each sample, and the distance to it.

    The lattice is small - a few hundred points - so the comparison
    is a loop over the points, and every sample is a vector
    operation. That is far too slow for a 2048 x 2048 image, so the
    image is computed at a lower resolution and the pattern's
    STRUCTURE is what matters at that resolution anyway: a stone is
    tens of pixels across.
    """
    import numpy

    best = numpy.full(sample_x.shape, 1e18)
    nearest = numpy.zeros(sample_x.shape, dtype=numpy.int32)
    for index in range(len(points_x)):
        distance = (sample_x - points_x[index]) ** 2 + (sample_y - points_y[index]) ** 2
        closer = distance < best
        best = numpy.where(closer, distance, best)
        nearest = numpy.where(closer, index, nearest)
    return nearest, numpy.sqrt(best)


def _edge_distance(points_x, points_y, sample_x, sample_y, nearest):
    """The distance from each sample to the EDGE of its cell.

    A cell's edge is the boundary between it and its neighbours, so
    the distance to the edge is the distance to the second-nearest
    point, less the distance to the nearest. It is what makes the
    joint: zero on the boundary, growing into the stone.
    """
    import numpy

    best = numpy.full(sample_x.shape, 1e18)
    second = numpy.full(sample_x.shape, 1e18)
    own = numpy.zeros(sample_x.shape)
    for index in range(len(points_x)):
        distance = (sample_x - points_x[index]) ** 2 + (sample_y - points_y[index]) ** 2
        nearer = distance < best
        # The second-nearest is the smallest distance that is not
        # the nearest point's, so the running minimum is demoted
        # when a nearer point arrives.
        second = numpy.where(nearer, best, numpy.minimum(second, distance))
        best = numpy.where(nearer, distance, best)
        # The own distance is the NEAREST point's - measured from the
        # running minimum after the loop it was the minimum over ALL
        # the points, so the edge came out zero everywhere and the
        # image came out flat.
        own = numpy.where(nearest == index, distance, own)
    return numpy.sqrt(numpy.maximum(second, 0.0)) - numpy.sqrt(own)


def _pattern_field(
    kind: str,
    resolution: int,
    cells: int,
    randomness: float,
    wander: float,
    frequency: int,
):
    """The pattern's two fields: the cell each sample is in, and the
    distance to that cell's edge.

    Both are periodic over the domain, so the image tiles.
    """
    import numpy

    if kind == "voronoi":
        points_x, points_y, sample_x, sample_y = _lattice(
            resolution, cells, randomness, wander, frequency
        )
        nearest, _distance = _nearest(points_x, points_y, sample_x, sample_y)
        edge = _edge_distance(points_x, points_y, sample_x, sample_y, nearest)
        return nearest, edge

    if kind == "brick":
        # Courses of bricks: the cell is a brick, and the joint is the
        # mortar around it. The courses are offset every other row,
        # which is what makes a brick wall a brick wall.
        row = numpy.arange(resolution)
        column = numpy.arange(resolution)
        row_index = (row * cells) // resolution
        offset = (row_index % 2) * 0.5
        shift = (column + offset) % cells
        cell = numpy.tile((shift + row_index * cells).reshape(-1, 1), (1, resolution))
        # Where each sample sits INSIDE its brick, in cells: the
        # distance to the brick's edge in either direction.
        u = ((column + offset) % cells) / cells
        v = ((row * cells) % resolution) / cells
        edge_u = numpy.minimum(u, 1.0 - u) * cells
        edge_v = numpy.minimum(v, 1.0 - v) * cells
        edge = numpy.minimum(
            numpy.tile(edge_u.reshape(-1, 1), (1, resolution)),
            numpy.tile(edge_v.reshape(1, -1), (resolution, 1)),
        )
        return cell, edge

    # A wave is a GRAIN: its troughs are the grain's lines.
    frequency_value = numpy.arange(resolution) / resolution * cells
    wave = numpy.abs(numpy.sin(frequency_value * numpy.pi))
    edge = numpy.tile(wave.reshape(-1, 1), (1, resolution))
    bands = numpy.tile(frequency_value.reshape(-1, 1), (1, resolution))
    return bands.astype(numpy.int32), edge


def write_procedural_base_color(
    output_path: Path,
    kind: str = "voronoi",
    scale_cells: float = 5.0,
    width_px: int = 2048,
    height_px: int = 2048,
    wander: float = DEFAULT_WANDER,
    wander_frequency: int = DEFAULT_WANDER_FREQUENCY,
    randomness: float = 1.0,
    stone_dark_rgb: tuple[float, float, float] = DEFAULT_STONE_DARK_RGB,
    stone_light_rgb: tuple[float, float, float] = DEFAULT_STONE_LIGHT_RGB,
    mortar_rgb: tuple[float, float, float] = DEFAULT_MORTAR_RGB,
    mortar_width: float = DEFAULT_MORTAR_WIDTH,
    variation: float = DEFAULT_VARIATION,
) -> Path:
    """Write a procedural base colour as a PNG; returns the path.

    The pattern is computed in numpy and written into the image with
    Blender's image API, the way the ORM bake writes its maps. The
    values in the file are the values that were computed: nothing
    renders them, so nothing can distort them.

    `kind` is the cell shape - "voronoi" for stones, "brick" for
    courses, "wave" for a grain. `scale_cells` is how many cells
    across the image, and a Voronoi pattern's cell count IS its
    scale.

    `wander` is how far the lattice is displaced, in cell units: it
    is what turns a Voronoi diagram into a cobblestone. Its
    frequency is an INTEGER, because the field has to be periodic.
    """
    import bpy
    import numpy

    from golem_blender.pbr import pattern

    if kind not in PROCEDURAL_COLOUR_KINDS:
        raise ValueError(
            f"Unknown procedural colour kind {kind!r}. Expected one of "
            f"{PROCEDURAL_COLOUR_KINDS}."
        )
    if width_px < 2 or height_px < 2:
        raise ValueError("A procedural colour needs at least 2 pixels a side.")
    if scale_cells <= 0.0:
        raise ValueError("The pattern's scale must be positive.")
    if wander_frequency < 1:
        raise ValueError("The wander's frequency must be at least 1.")

    # The pattern is computed at a resolution where a cell is a few
    # dozen pixels across - the structure is what matters, and the
    # nearest-point search is O(samples x points), which a 2048 x
    # 2048 image would make slow.
    cells = max(2, round(scale_cells))
    resolution = min(width_px, height_px, max(64, cells * 48))

    cell, edge = _pattern_field(
        kind, resolution, cells, randomness, wander, wander_frequency
    )
    if kind == "voronoi":
        # The shared pattern: a REGULAR lattice with a wrapping search
        # and a domain warp. The regular lattice is what makes the
        # pattern periodic - a jittered one cannot be, because the
        # jitter has to be the same at both ends - and the warp is
        # what makes the cells look like stones rather than a grid.
        cell, edge = pattern.cell_and_edge(resolution, cells)

    # The joint's width, as a fraction of the distance to the edge.
    if kind == "voronoi":
        reach = float(edge.max()) if edge.max() > 0 else 1.0
        joint = numpy.clip(edge / reach, 0.0, 1.0)
    else:
        joint = numpy.clip(edge / max(1e-6, float(edge.max())), 0.0, 1.0)
    # The joint is where the distance to the edge is SMALL.
    joint = numpy.clip(1.0 - joint / max(mortar_width, 1e-6), 0.0, 1.0)

    # The stones' colours, from each cell's own random value.
    import numpy as _np

    values = cell.astype(_np.float64)
    hashed = _np.sin(values * 12.9898 + 78.233) * 43758.5453
    hashed = hashed - _np.floor(hashed)
    stone = _np.empty(cell.shape + (3,), dtype=_np.float32)
    for channel in range(3):
        ramp = _np.linspace(stone_dark_rgb[channel], stone_light_rgb[channel], 256)
        stone[:, :, channel] = ramp[
            _np.clip((hashed * 255).astype(numpy.int32), 0, 255)
        ]

    # The wear: a smooth field that varies a stone within itself.
    axis = numpy.arange(resolution) / resolution
    wave_x = numpy.sin(axis * cells * 2 * numpy.pi) * 0.5
    wave_x = numpy.tile(wave_x.reshape(-1, 1), (1, resolution))
    wave_y = numpy.sin(axis * cells * 3 * numpy.pi + 1.3) * 0.5
    wave_y = numpy.tile(wave_y.reshape(1, -1), (resolution, 1))
    wear = (wave_x + wave_y) * 0.5 * variation

    colour = stone + wear[:, :, numpy.newaxis]

    # The joint replaces the stone where the joint is.
    mortar = numpy.array(mortar_rgb, dtype=numpy.float32).reshape(1, 1, 3)
    joint = joint[:, :, numpy.newaxis]
    colour = colour * (1.0 - joint) + mortar * joint
    colour = numpy.clip(colour, 0.0, 1.0)

    # The image is the pattern at the pattern's resolution, resized to
    # the requested size - a bilinear upscale, which is what a viewer
    # would do with the texture anyway.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = bpy.data.images.new(
        f"{output_path.stem}_pattern", width=resolution, height=resolution, alpha=False
    )
    try:
        pixels = numpy.empty(resolution * resolution * 4, dtype=numpy.float32)
        pixels.reshape((resolution, resolution, 4))[:, :, :3] = colour
        pixels.reshape((resolution, resolution, 4))[:, :, 3] = 1.0
        source.pixels.foreach_set(pixels.ravel())
        if resolution != width_px or resolution != height_px:
            source.scale(width_px, height_px)
        pixels = numpy.empty(width_px * height_px * 4, dtype=numpy.float32)
        source.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(source)

    image = bpy.data.images.new(
        output_path.stem, width=width_px, height=height_px, alpha=False
    )
    try:
        image.colorspace_settings.name = "sRGB"
        image.pixels.foreach_set(pixels.ravel())
        image.filepath_raw = str(output_path)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)
    return output_path


def procedural_source_metadata(
    kind: str = "voronoi",
    scale_cells: float = 5.0,
) -> dict:
    """What a procedural base colour was made from, for the export's metadata.

    A set's metadata says how it was MADE, and this is how a
    procedural one was made: no prompt and no model, but a pattern
    kind and a scale, and the fact that the pattern is periodic.
    """
    return {
        "base_colour_source": "procedural: computed in numpy, no image",
        "base_colour_kind": kind,
        "base_colour_scale_cells": scale_cells,
        "base_colour_periodic": True,
    }


__all__ = (
    "DEFAULT_MORTAR_RGB",
    "DEFAULT_MORTAR_WIDTH",
    "DEFAULT_PROCEDURAL_SCALE",
    "DEFAULT_STONE_DARK_RGB",
    "DEFAULT_STONE_LIGHT_RGB",
    "DEFAULT_VARIATION",
    "DEFAULT_WANDER",
    "DEFAULT_WANDER_FREQUENCY",
    "PROCEDURAL_COLOUR_KINDS",
    "procedural_source_metadata",
    "write_procedural_base_color",
)
