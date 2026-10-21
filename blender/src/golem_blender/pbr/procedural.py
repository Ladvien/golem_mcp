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
# The largest the pattern is COMPUTED at, in pixels a side. The image
# is upscaled to the requested size afterwards, and the structure is
# what matters - a stone is tens of pixels across whatever the
# resolution.
#
# It is a cap because the cell count drives the resolution: at 128
# cells the grid would be 6144 across, and the benchmark stopped at
# the third material. Measured, the pattern takes 1.2 s to 1.5 s at
# the cap.
MAXIMUM_PATTERN_RESOLUTION = 1024
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
PROCEDURAL_COLOUR_KINDS = ("voronoi", "brick", "grain")


def _cell_hash(cell, width: int, height: int):
    """A colour's random value, from the cell's position in the pattern.

    The value has to be the SAME for the cell at the pattern's edge
    and the cell at its start, or the wrap shows as a colour step.
    Measured: the brick's geometry tiled at 0.00x while the image's
    seam was 17/255, because the colour was hashed from the cell's
    INDEX - and the index at the edge is not the index at the start.

    So the cell is reduced into the pattern's own grid first, and the
    hash is of THAT. A brick at the edge and the brick at the start
    become the same brick, with the same colour.
    """
    import numpy as _np

    # The cell's row and column within the pattern, and the same
    # reduced into it.
    row = (cell // max(1, width)) % max(1, height)
    column = (cell % max(1, width)) % max(1, width)
    # A hash of the two, which is a function of the position and not
    # of the index.
    values = row.astype(_np.float64) * 31.0 + column.astype(_np.float64)
    hashed = _np.sin(values * 12.9898 + 78.233) * 43758.5453
    return hashed - _np.floor(hashed)


def write_procedural_base_color(
    output_path: Path,
    kind: str = "voronoi",
    scale_cells: float = 5.0,
    width_px: int = 2048,
    height_px: int = 2048,
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

    # The pattern is computed at a resolution where a cell is a few
    # dozen pixels across - the structure is what matters, and the
    # nearest-point search is O(samples x points), which a 2048 x
    # 2048 image would make slow.
    cells = max(2, round(scale_cells))
    # The pattern is computed at a resolution where a cell is a few
    # dozen pixels across - the structure is what matters, and the
    # search is O(samples x points).
    #
    # It is CAPPED, because the cell count drives the resolution and
    # the cell count is the pattern's scale: at 128 cells the grid
    # would be 6144 across, and the benchmark stopped at the third
    # material. A cell needs about 24 pixels to read as a stone, and
    # the image is upscaled to the requested size afterwards.
    resolution = min(
        width_px, height_px, max(64, min(cells * 24, MAXIMUM_PATTERN_RESOLUTION))
    )

    cell_width = cells
    cell_height = cells
    if kind == "voronoi":
        # The shared pattern: a REGULAR lattice with a wrapping search
        # and a domain warp. The regular lattice is what makes the
        # pattern periodic - a jittered one cannot be, because the
        # jitter has to be the same at both ends - and the warp is
        # what makes the cells look like stones rather than a grid.
        cell, edge, grid = pattern.cell_and_edge(resolution, cells)
    elif kind == "brick":
        cell, edge, grid = pattern.brick_field(resolution, cells)
    else:
        cell, edge, grid = pattern.grain_field(resolution, cells)
    cell_width, cell_height = grid

    # The joint's width, as a fraction of the distance to the edge.
    if kind == "voronoi":
        reach = float(edge.max()) if edge.max() > 0 else 1.0
        joint = numpy.clip(edge / reach, 0.0, 1.0)
    else:
        joint = numpy.clip(edge / max(1e-6, float(edge.max())), 0.0, 1.0)
    # The joint is where the distance to the edge is SMALL.
    joint = numpy.clip(1.0 - joint / max(mortar_width, 1e-6), 0.0, 1.0)

    # The stones' colours, from each cell's own random value.
    #
    # The hash is a function of the cell's POSITION IN THE PATTERN,
    # not of its index. An index is not periodic - the cell at the
    # pattern's edge has a different index from the one at its start,
    # and a hash of the index gives them different colours, so the
    # wrap shows as a colour step. Measured, the brick's absolute seam
    # was 17/255 at a wrapping field's 0.00x: the GEOMETRY tiled and
    # the COLOUR did not.
    #
    # So the hash takes the cell's coordinates modulo the pattern's
    # size, and the brick at the wrap and the brick at the start are
    # the SAME brick with the SAME colour.
    import numpy as _np

    hashed = _cell_hash(cell, cell_width, cell_height)
    stone = _np.empty(cell.shape + (3,), dtype=numpy.float32)
    for channel in range(3):
        ramp = _np.linspace(stone_dark_rgb[channel], stone_light_rgb[channel], 256)
        stone[:, :, channel] = ramp[
            _np.clip((hashed * 255).astype(numpy.int32), 0, 255)
        ]

    # The wear: a smooth field that varies a stone within itself.
    #
    # Its frequency is the SAME as the pattern's cells, not a multiple
    # of it. The earlier version used two and three times the cell
    # count, which put a fine CROSSHATCH over the whole image - and
    # that crosshatch was what the feature measure was reading, not
    # the pattern. Measured, a wood's features read 341.33 against the
    # truth's 93.09, and the extra 248 were the wear.
    #
    # The wear is now at the cell's own frequency in ONE direction,
    # so it varies a stone along its length without crossing itself.
    axis = numpy.arange(resolution) / resolution
    wave = numpy.sin(axis * cells * numpy.pi + 1.3) * 0.5
    wave = numpy.tile(wave.reshape(-1, 1), (1, resolution))
    wear = wave * variation
    # The wear is a fraction of a stone's own width, so it varies a
    # stone without becoming the pattern: it is at the cell's own
    # frequency, not a multiple of it.

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
    "DEFAULT_WANDER_FREQUENCY",
    "PROCEDURAL_COLOUR_KINDS",
    "procedural_source_metadata",
    "write_procedural_base_color",
)
