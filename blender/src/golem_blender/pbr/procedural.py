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
# How wide the JOINT is, as a fraction of the distance to the nearest
# edge.
#
# It was 0.30, and that made the joint cover 28.8% of the image -
# so every pattern read as a soft blob with a blurred band through
# it, and a brick wall read as blue-white pillows. A brick's mortar
# is a LINE: measured, a width of 0.05 covers 6.2% of the image and
# a width of 0.10 covers 12.1%.
#
# The joint's width is also a MATERIAL's word: a stone's joint is
# wide and a tile's is a thin line, and the truths show it.
DEFAULT_MORTAR_WIDTH = 0.08
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
PROCEDURAL_COLOUR_KINDS = ("voronoi", "brick", "grain", "metal")
# How wide a LINE is, as a fraction of the distance to the nearest
# line. A grain's rings and a metal's grain are soft, and the truth's
# wood measures a luma spread of 0.0162 - so the line is narrow and
# the falloff is smooth.
#
# Measured, the width trades the scale against the contrast: at 0.5
# the wood's contrast read 0.69x the truth's and its scale 0.95x, and
# at 0.8 the contrast read 0.73x with the scale at 0.96x.
#
# But a wide line is a BAND, and a grain's fibre is a thin dark line
# on a base - so the line is narrow and the falloff carries it.
# Measured on the truth's own row: the range is 0.0797 and the
# spread 0.0135, so the fibre occupies a fifth of the row's range.
DEFAULT_LINE_WIDTH = 0.35
# The ENVELOPE's line: how wide it is, as a fraction of its own
# field's reach, and how much of the spread it carries.
#
# The envelope is a BROAD gradient - the slow cathedral swirl a
# plank's fibre follows - and it is drawn wide, so it reads as a
# gradient and not as a set of rings. Measured, a narrow envelope
# drew hard white waves where the truth has a soft gradient.
ENVELOPE_LINE_WIDTH = 1.0
ENVELOPE_STRENGTH = 0.40
# The FIBRE's line: how wide it is, and how much of the spread it
# carries.
#
# The fibre is FINE and it is most of the spread: the truth's own
# wood carries 0.51 of its spread in the fibre and 0.49 in the
# envelope, and the two are nearly equal.
FIBRE_LINE_WIDTH = 0.35
FIBRE_STRENGTH = 0.35
# The METAL's grain is fainter than the wood's fibre.
#
# A sheet's grain is a brushed streak - a very fine variation - and
# the truth's polished silver carries a spread of 0.0061 against the
# wood's 0.0162. So the grain is a tenth of the wood's fibre.
#
# Measured, a grain as strong as the wood's fibre put the metal's
# scale at 3.33x the truth's - the measure read the grain and not
# the sheet's bands.
METAL_FIBRE_STRENGTH = 0.30
# How many FINE lines each cell of a line pattern carries.
#
# A grain is TWO scales: the envelope - the slow cathedral swirl a
# plank's fibre follows - and the fibre itself. Measured, the truth's
# wood crosses its own midpoint 69 times where its envelope's
# autocorrelation says thirteen features, and the truth's polished
# silver crosses it 122 times where its envelope says nine.
#
# So the cells are the envelope and the lines are inside them.
#
# Measured, the truth's fibre is much finer than that: its lines come
# 3, 5, 6, 9, 14 and 17 pixels apart in a 1024 image, so a wood
# carries a hundred or more of them - and they are irregular, which
# is what the fractal is for.
#
# So the multiplier is 8: at eight lines per cell and sixteen cells
# the row carries 128 lines, which is the truth's own order.
DEFAULT_LINES_PER_CELL = 8
# The contrast a LINE pattern gets when the description says nothing
# about its spread. The truth sets' spreads run from 0.0061 on a
# polished metal to 0.0926 on a mossy rock, and this is the middle.
LINE_CONTRAST = 0.030


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


def _pattern_resolution(limit: int, target: int, cells: int) -> int:
    """The resolution the pattern is computed at.

    Two things have to hold:

    - the upscale to the output is a WHOLE NUMBER, because the
      upscale is bilinear and a fractional scale shifts the pattern's
      own periodicity - so the resolution DIVIDES the output;
    - the resolution is a MULTIPLE of the pattern's own cell count,
      so its cells land on whole pixels and the last cell is not cut
      in half.

    Measured, the brick's seam read 3.85x the truth's with a
    fractional scale and 0.00x with a whole one.
    """
    # The divisors of the output, largest first, that are a multiple
    # of the cell count.
    for candidate in range(limit, 0, -1):
        if limit % candidate != 0:
            continue
        if candidate % cells != 0:
            continue
        if candidate <= target:
            return candidate
    # Nothing satisfies both, so the cell count is the thing that
    # gives: a resolution of the cells' own multiple, as close to the
    # target as the divisors allow.
    for candidate in range(limit, 0, -1):
        if limit % candidate == 0 and candidate % cells == 0:
            return candidate
    return min(limit, max(cells, 1))


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
    line_width: float = DEFAULT_LINE_WIDTH,
    line_contrast: float | None = None,
    target_spread: float | None = None,
    lines_per_cell: int = DEFAULT_LINES_PER_CELL,
    fibre_strength: float = FIBRE_STRENGTH,
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
    from golem_blender.pbr.pattern import SURFACE_SHARE

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
    # The pattern is computed AT THE OUTPUT'S RESOLUTION, not at a
    # smaller one and upscaled.
    #
    # The upscale was bilinear, and a scale that is not a whole
    # number shifts the pattern's own periodicity - so the map's seam
    # showed. Measured, the brick's seam read 3.85x the truth's with
    # a scale of 8.53, and the fix is not to scale at all.
    #
    # The cost is the nearest-point search, and it is affordable:
    # the Voronoi takes 3.5 s at 2048 across, against 0.2 s at 240.
    resolution = min(width_px, height_px)

    cell_width = cells
    cell_height = cells
    if kind == "voronoi":
        # The stones are FRACTAL: the base octave is the cell count
        # the truth asks for, and each octave above it adds a finer
        # set of cells inside the same field. A ground is a dense
        # spread of small pebbles, and one octave's cells were a
        # handful of giant amoebas.
        #
        # The FBM-Worley's own distance to the BISECTOR is what a
        # joint's width needs, because it is an exact distance to the
        # cell's border - so a joint drawn from it is the same width
        # in pixels whatever the cell's size.
        stones = pattern.fractal_stones(resolution, cells)
        cell = stones["cell"]
        edge = stones["distance"]
        grid = (cells, cells)
    elif kind == "brick":
        cell, edge, grid = pattern.brick_field(resolution, cells)
    elif kind == "grain":
        cell, edge, grid, fibre = pattern.grain_field(
            resolution, cells, lines_per_cell=lines_per_cell
        )
    else:
        cell, edge, grid, fibre = pattern.metal_field(
            resolution, cells, lines_per_cell=lines_per_cell
        )
    cell_width, cell_height = grid

    if kind in ("grain", "metal"):
        # A GRAIN and a METAL are LINES on a surface, not stones in a
        # joint. A cobblestone's treatment - a random colour per
        # cell, a mortar joint, a wear wave - is wrong for both: a
        # wood's rings are a subtle variation on ONE colour, and a
        # steel plate is an even sheet.
        #
        # Measured, the truth's wood has a luma spread of 0.0162 and
        # 13.13 features, and the cobblestone treatment read 3.00x
        # that contrast. The lines carry the whole image, so the
        # colour is the palette's base and the lines are the only
        # variation.
        #
        # The line is the base DARKER, and by how much is the
        # description's own SPREAD - the same number the stone ramp
        # uses, and for the same reason: the truth sets' spreads run
        # from 0.0061 on a polished metal to 0.0926 on a mossy rock,
        # and the words carry them.
        #
        # The spread is ABSOLUTE, so the darkening is a fraction of
        # the base: a dark surface's lines are darker by less in
        # absolute terms than a pale one's, which is what the truth
        # does.
        if line_contrast is None:
            line_contrast = LINE_CONTRAST
        base = sum(stone_dark_rgb) / 3.0
        darkening = 0.0 if base <= 0.0 else min(1.0, line_contrast / base)
        line_rgb = tuple(
            max(0.0, channel * (1.0 - darkening)) for channel in stone_dark_rgb
        )
        return _write_line_pattern(
            output_path,
            edge=edge,
            fibre=fibre,
            grid=(cell_width, cell_height),
            resolution=resolution,
            width_px=width_px,
            height_px=height_px,
            base_rgb=stone_dark_rgb,
            line_rgb=line_rgb,
            line_width=line_width,
            target_spread=target_spread,
            fibre_strength=(
                METAL_FIBRE_STRENGTH if kind == "metal" else fibre_strength
            ),
        )

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
    # It is the stone's own SURFACE, and it is at a much finer scale
    # than the stone: a close crop of the truth's ground is a field
    # of small light and dark patches, and the lane's was a flat grey
    # blob. So the surface is a sum of sines at high frequencies, and
    # the frequencies are integers so the field is periodic and the
    # map still tiles.
    #
    # The wear is a fraction of the RAMP's spread, not a constant. It
    # used to be a fixed 0.15 of a stone's own colour, which is
    # sixteen times the whole spread of a soft fabric - and the
    # fabric's contrast read 4.84x the truth's while the ramp alone
    # read 0.35x.
    ramp_spread = max(0.0, (max(stone_light_rgb) - min(stone_dark_rgb)) / 2.0)
    # The surface is computed at the OUTPUT's resolution, not the
    # pattern's. The pattern is small - a few hundred pixels - and
    # the image is upscaled afterwards, and an upscale of a field
    # that is not periodic over the OUTPUT's domain breaks the
    # periodicity: the brick's seam read 3.85x the truth's.
    #
    # So the mottle is computed at the size it will be seen at, and
    # the upscale carries the pattern's own structure.
    #
    # The mottle is at the OUTPUT's resolution and the pattern at
    # its own, so the mottle is RESIZED to the pattern's grid before
    # it is added - and a resize of a periodic field is not periodic,
    # so the mottle is instead sampled at the pattern's own
    # coordinates and its lattice size is chosen to divide the
    # pattern's domain.
    surface = pattern.surface_texture(resolution, cells)
    surface_amplitude = float(surface.max() - surface.min())
    if surface_amplitude > 0.0:
        surface = surface / surface_amplitude * 2.0 - 1.0
    wear = surface * min(variation, 1.0) * ramp_spread * SURFACE_SHARE
    colour = stone + wear[:, :, numpy.newaxis]

    # The joint replaces the stone where the joint is.
    mortar = numpy.array(mortar_rgb, dtype=numpy.float32).reshape(1, 1, 3)
    joint = joint[:, :, numpy.newaxis]
    colour = colour * (1.0 - joint) + mortar * joint
    colour = numpy.clip(colour, 0.0, 1.0)
    # The image's variation is scaled so its spread IS the
    # description's - a pattern's contrast depends on its SHAPE and
    # not only on its numbers, and only measuring says how much of
    # the spread this one carries.
    colour = _scale_to_spread(colour, float(sum(stone_dark_rgb) / 3.0), target_spread)

    # The image is written at the resolution the pattern was computed
    # at, which is the requested one - there is no upscale, because an
    # upscale shifts the pattern's periodicity and the map's seam
    # shows.
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


def _scale_to_spread(colour, base, target_spread):
    """Scale the image's variation so its spread IS the target.

    A pattern's contrast depends on its SHAPE and not only on its
    numbers: a soft line's falloff carries a fraction of what a hard
    joint's does, and the two patterns carry it differently again. So
    a factor per pattern is not enough - the metal's spread read
    0.18x the truth's for one material and 2.25x for another with
    the same factor.

    So the image is MEASURED and SCALED: the pattern is built, its
    own spread is taken, and the variation about the base is scaled
    by the ratio of the target to what it read. The base colour is
    not moved, so the brightness is the description's own.

    The measurement is on the RAW values, which is the space the file
    holds and the space the truths are measured in. Blender's image
    API takes and returns the file's own values unchanged - measured
    on a ramp of eight values, what was written came back as what
    was written - so there is no transfer to undo.

    That makes the contrast the description's spread, whatever the
    pattern's shape.
    """
    import numpy as _np

    if target_spread is None or target_spread <= 0.0:
        return colour
    channel = colour[:, :, 0] - base
    measured = float(channel.std())
    if measured <= 1e-9:
        return colour
    scale = target_spread / measured
    scaled = base + (colour - base) * scale
    return _np.clip(scaled, 0.0, 1.0)


def _write_line_pattern(
    output_path: Path,
    edge,
    fibre,
    grid,
    resolution: int,
    width_px: int,
    height_px: int,
    base_rgb,
    line_rgb,
    line_width: float,
    target_spread: float | None = None,
    fibre_strength: float = FIBRE_STRENGTH,
) -> Path:
    """Write a pattern of LINES on a base colour; returns the path.

    A grain and a metal are both LINES on a surface, and a line
    pattern is a different thing from a cell pattern: the whole image
    is ONE colour, and the lines are the only variation on it.

    So the base is the palette's colour and the lines are a second
    colour blended in by their distance to the nearest line. The
    blend is a smooth falloff, not a hard edge, because a wood's
    rings and a metal's grain are soft.

    THE TWO SCALES ARE DRAWN SEPARATELY. A grain is an ENVELOPE -
    the slow cathedral swirl the fibre follows - and a FIBRE, and
    they are different widths and different strengths. Combining
    them into one field and drawing that put the envelope's rings
    over the fibre, and the close crop showed hard white waves
    where the truth has fibre: the envelope was doing all the
    reading and the fibre was invisible.

    So the envelope is drawn as a broad gradient and the fibre as a
    set of fine lines, and each has its own width and its own
    strength. The truth's own wood carries 0.51 of its spread in the
    fibre and 0.49 in the envelope, so the two are nearly equal -
    and the envelope's RING POSITIONS are what the feature scale
    reads.
    """
    import bpy
    import numpy as _np

    def line_of(field, width):
        """The field's own DARKNESS: a smooth falloff from its darkest.

        The field is a DARKNESS - one at the darkest and zero at the
        lightest - so the line is the field's own value and the line
        is dark where the field is large.

        It used to be a DISTANCE, read as one, and the two are
        opposites: a distance is small where the field is dark, so
        the light and the dark were swapped - and the wood's mean
        came out at 0.159 against a base of 0.600.
        """
        reach = max(1e-6, float(field.max()))
        line = _np.clip(field / reach / max(1e-6, width), 0.0, 1.0)
        return line * line * (3.0 - 2.0 * line)

    # The envelope: a broad gradient, at a third of the spread.
    envelope_line = line_of(edge, ENVELOPE_LINE_WIDTH) * ENVELOPE_STRENGTH
    # The fibre: fine lines, at the rest of the spread.
    fibre_line = line_of(fibre, FIBRE_LINE_WIDTH) * fibre_strength

    base = _np.array(base_rgb, dtype=_np.float32).reshape(1, 1, 3)
    lines = _np.array(line_rgb, dtype=_np.float32).reshape(1, 1, 3)
    # The two are COMBINED as a blend, and the base colour stays
    # reachable.
    #
    # A sum of two darknesses can exceed one, and the clip then takes
    # the base colour away entirely: the corrugated steel's mean came
    # out at 0.000 against a base of 0.430. And the fibre's strength
    # was applied twice - once to the fibre and once to the sum.
    #
    # So the fibre's darkness is ADDED to the envelope's and the sum
    # is scaled back so it cannot exceed one. The base is reachable
    # wherever the sum is small, which is what keeps the map's
    # brightness the description's.
    darkness = envelope_line + fibre_line
    peak = max(1e-6, float(darkness.max()))
    if peak > 1.0:
        darkness = darkness / peak
    colour = (
        base * (1.0 - darkness[:, :, _np.newaxis]) + lines * darkness[:, :, _np.newaxis]
    )
    colour = _np.clip(colour, 0.0, 1.0)
    # The image's variation is scaled so its spread IS the
    # description's - a line's falloff carries a different amount of
    # contrast than a joint's, and only measuring says how much of
    # the spread this one carries.
    colour = _scale_to_spread(colour, float(base_rgb[0]), target_spread)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source = bpy.data.images.new(
        f"{output_path.stem}_pattern", width=resolution, height=resolution, alpha=False
    )
    try:
        pixels = _np.empty(resolution * resolution * 4, dtype=_np.float32)
        pixels.reshape((resolution, resolution, 4))[:, :, :3] = colour
        pixels.reshape((resolution, resolution, 4))[:, :, 3] = 1.0
        source.pixels.foreach_set(pixels.ravel())
        pixels = _np.empty(width_px * height_px * 4, dtype=_np.float32)
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
