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
# A ROAD MARKING's own colour, and it is not the road's: the truth's
# own Road007 is a pale white line and Road008A a yellow one.
DEFAULT_PAINT_RGB = (0.80, 0.80, 0.78)
# A ROAD MARKING's own spread, and it is NOT the road's.
#
# Measured on the truth's own Road007: the map's spread is 0.071
# where the road's own texture carries 0.0301 - so the painted line
# IS the surface's variation and the asphalt is the quiet part.
MARKINGS_SPREAD = 0.071
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
# The joint's width, as a fraction of the MEDIAN distance to the
# edge - the typical pebble's own radius.
#
# It was 0.08 of the distance field's MAXIMUM, and the maximum is the
# widest cell's, so the joint came out as a thread: the ground read
# as a mosaic of flat stones with no gravel in them.
#
# Measured on the truth's own ground: the joints are a sixth of the
# surface - the dark tail covers 16.9% of it - and a width of 0.95
# of the median distance covers 17% of ours.
DEFAULT_MORTAR_WIDTH = 0.95
# How much LIGHTER than the base a line pattern's light parts go.
#
# The truth's own wood is drawn both ways about its median: its p5 is
# 0.604 and its p95 is 0.690, around a mean of 0.649.
LINE_LIGHT_FRACTION = 0.18
# A SCATTER's MATRIX is wide: the truth's own ground is a gravel
# with a matrix twelve pixels wide between stones that are sixteen
# pixels across.
SCATTER_MATRIX_WIDTH = 2.0
# How much of the surface's spread the SLOW drift carries.
#
# The drift is the surface's own slow variation, and it is what the
# feature measure finds: the truth's ground measures nineteen
# features across where its stones are a couple of pixels across.
#
# So the drift carries a real share of the spread and not a trace of
# it. Measured, the ground's period read fourteen pixels against the
# truth's fifty-three when the drift was on the stone's own tone,
# and the drift's own share is what moved it.
#
# And the share is a tenth and not more. The truth's own ground
# carries 0.0206 of its spread in the coarse - the forty-pixel blur -
# and the lane's carried 0.0385 at two fifths, so the ground came
# out with dark blotches on it where the truth's is an even gravel.
# At a tenth the coarse carries 0.0291, and the truth's own Ground108
# reads 0.0318 against its 0.0282.
SCATTER_DRIFT_SHARE = 0.12
# How much a STONE's hue varies from the surface's own.
#
# The DEFAULT is in the palette - `hue_variation_for_description` -
# because a leaf mat is a patchwork of many colours and a gravel is
# a family, and the description says which.
# How much of the surface's spread a PARQUET's block grain carries.
#
# A parquet is a wood floor, and a wood's fibre is most of its
# variation: the truth's own wood carries 0.51 of its spread in the
# fibre and 0.49 in the envelope. So the block's grain is the same
# share.
PARQUET_FIBRE_STRENGTH = 0.5
# How deep a WOVEN cloth's threads are, as a fraction of the cloth's
# own colour.
#
# The truth's own fabrics carry a spread of 0.08 to 0.13, and a
# thread is a hard edge - so the threads are most of the surface's
# variation.
#
# It was 0.55 and the cloth came out as a bold plaid, and the
# truth's own Fabric030 is a fine twill whose threads are barely
# there.
WOVEN_THREAD_DEPTH = 0.22
# How deep a WALLPAPER's design is printed, as a fraction of the
# sheet's own colour.
#
# Measured on the truth's own printed plastisol: its spread is 0.0032
# and its wallpaper's 0.0072 - so the design carries a twentieth of
# what the sheet's own variation would.
WALLPAPER_DESIGN_DEPTH = 0.05
# How much of a LEATHER's spread its crackle carries.
#
# The truth's own leathers carry two thirds of their spread in the
# fine and a third in the envelope, and the truth's own Leather037
# measures five hundred and twelve features across - its envelope is
# nearly flat and the crackle is everything.
LEATHER_CRACKLE_STRENGTH = 0.7
# How much of the ramp a ROOF's shingle tone covers.
#
# The truth's own RoofingTiles013A's eight-by-eight blocks of shingles
# measure between 0.165 and 0.214 - a spread of 0.049, a seventh of
# the surface's own mean - and the hash spans the whole ramp, so the
# roof came out with a threefold spread of shingles.
ROOF_SHINGLE_TONE = 0.25
# A WALLPAPER's DESIGN's own spread.
#
# Measured on the truth's own printed plastisol: its design measures
# 0.0032 and its wallpaper 0.0072 - so a design carries a twentieth
# of what the description's own spread says.
WALLPAPER_DESIGN_SPREAD = 0.0072
# How much of the surface's spread a CARPET's pile carries.
#
# The truth's own carpet measures a spread of 0.0301 and its pile IS
# the variation - there is nothing else on a carpet but the pile.
CARPET_FIBRE_STRENGTH = 1.0
# Where a stone's joint becomes hard. A stone's edge is an edge and
# not a gradient, and the soft falloff made the ground a field of
# glowing blobs.
SCATTER_JOINT_EDGE = 0.5
# How much of the full width a SOLID surface's joint gets. A loose
# ground's matrix between its stones is a sixth of the surface, and a
# concrete's or a tile's joint is a hairline.
JOINT_SOLID_FRACTION = 0.12
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
PROCEDURAL_COLOUR_KINDS = (
    "voronoi",
    "brick",
    "grain",
    "metal",
    "flat",
    "scattered",
    "parquet",
    "carpet",
    "leather",
    "wallpaper",
    "markings",
    "woven",
    "roof",
    "herringbone",
)
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


# The BRICK's own FACE is a GRAIN, and above this share it is one.
#
# Below it the surface is a GLAZED one - a tile - and its cells take
# their tone from the stain and not from a hash.
BRICK_FACE_GRAIN_CUTOFF = 0.25

# How much of the DRIFT is CONTINUOUS across a tile, and not the
# tile's own flat tone.
#
# A stain crosses the joints and does not step at them: the truth's
# own Tiles141 carries a drift of 0.0349 and a period of a hundred
# and ninety-two pixels, so five features cross a wall of tiles, and
# a per-tile flat tone would step at every joint.
BRICK_FACE_DRIFT_CONTINUITY = 0.7

# The MATRIX's own SHADOW, and how far below the palette's dark end
# the gaps go.
#
# The ramp is the stone-to-matrix contrast, and the matrix is the
# shadow in the gaps between the stones - so the matrix has to have
# somewhere darker than the stones' own darkest to sit, and the
# palette's ramp has no room there. The truth's own ground reads a
# matrix of 0.172 where the palette's ramp starts at 0.218.
MATRIX_SHADOW_SHARE = 0.55
# And where the matrix's own tone RIDES on that extended ramp: at
# the bottom, for the gaps, and up to the top of it for a worn patch.
#
# The matrix ran to a third of the way up the palette's own ramp, so
# the gaps were a pale grey: measured, the matrix read 0.246 against
# a truth's 0.172, and the stone-to-matrix contrast read 0.372
# against a truth's 0.430.
MATRIX_TONE_BASE = 0.20
# How much of the MATRIX's own grit the surface's mottle carries.
#
# The truth's own ground's matrix carries a spread of 0.0824 - two
# thirds of the whole surface's - and the lane's carried 0.0183, so
# the gaps between the stones were a smooth sheet where the truth's
# is packed dirt.
MATRIX_GRIT_SHARE = 0.35
# How high the MATRIX's own ramp reaches, as a share of the palette's
# dark end.
#
# The truth's own ground's matrix runs from 0.12 to 0.29 - a width of
# 0.17 - and a narrow ramp cannot carry the grit in it: the
# correlation at a four-pixel lag was 0.226 where the truth's is
# 0.466, and at a sixteen-pixel lag 0.191 where the truth's is
# 0.135 - so the lane's ground was all coarse structure and no fine.
MATRIX_TONE_CEILING = 1.0
# How much of a surface's cells carry the MOSS, and how strongly the
# others do.
#
# The truth's own Rock064 is a grey rock with green MOSS in parts of
# it, and the moss is a MINORITY of the surface - a cell with a full
# hue swing on every cell gave a green and a tan patchwork.
MOSS_FRACTION = 0.55
MOSS_PATCH_SHARE = 0.15
MATRIX_TONE_RANGE = 0.80
# A MEASUREMENT PLACEHOLDER - the sweep below picks the value.


def _cell_mean(field, cell, width: int, height: int):
    """The field's own MEAN over each cell.

    A cell is a set of pixels, and the field's mean over that set is
    the cell's own value. The cell at the pattern's edge and the cell
    at its start are the SAME cell - the index is reduced into the
    pattern's grid - so the two are the same value and the wrap
    shows no step.

    The sums are accumulated by the cell's reduced index, so it is
    one pass over the image and not one per cell.
    """
    import numpy as _np

    count = max(1, width) * max(1, height)
    reduced = _np.mod(cell, count)
    flat = reduced.reshape(-1)
    sums = _np.bincount(flat, weights=field.reshape(-1), minlength=count)
    counts = _np.bincount(flat, minlength=count)
    means = sums / _np.maximum(counts, 1)
    return means[flat].reshape(field.shape)


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
    fibre_scale: float | None = None,
    width_px: int = 2048,
    height_px: int = 2048,
    stone_dark_rgb: tuple[float, float, float] = DEFAULT_STONE_DARK_RGB,
    stone_light_rgb: tuple[float, float, float] = DEFAULT_STONE_LIGHT_RGB,
    mortar_rgb: tuple[float, float, float] = DEFAULT_MORTAR_RGB,
    paint_rgb: tuple[float, float, float] | None = None,
    hue_variation: float | None = None,
    mortar_width: float = DEFAULT_MORTAR_WIDTH,
    variation: float = DEFAULT_VARIATION,
    line_width: float = DEFAULT_LINE_WIDTH,
    line_contrast: float | None = None,
    target_spread: float | None = None,
    target_value: float | None = None,
    lines_per_cell: int = DEFAULT_LINES_PER_CELL,
    fibre_strength: float = FIBRE_STRENGTH,
    pebble_factor: float = 1.0,
    curvature_strength: float = 0.0,
    scratch_strength: float = 0.0,
    brick_face_strength: float = 0.0,
    drift_strength: float = 0.0,
    brick_aspect: float | None = None,
    metal_horizontal: bool = False,
    metal_banded: bool = True,
    metal_envelope_factor: float = 1.0,
    stone_tone_fraction: float = 1.0,
) -> Path:
    # `pebble_factor` is how many PEBBLES a cell holds: a loose
    # ground's four, and a solid surface's one.
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
    curvature_field = None
    brick_face = None
    if kind == "scattered":
        # A loose ground is SCATTERED stones, not a Voronoi.
        #
        # A Voronoi's cells tile the plane, and a heap of loose stones
        # does not: the truth's own ground is fifty-six bright stones
        # along a row of a thousand and twenty-four, a matrix twelve
        # pixels wide between them, and the stones' sizes varying by
        # eight times.
        #
        # So the stones are SCATTERED - Material Maker's `splatter`
        # node, MIT licensed, and ours wraps so the map tiles.
        #
        # The joint is the MATRIX between the stones, and the stones'
        # own tone is the matrix's mottle.
        cell, edge, grid, fibre, slow, stone_hue = pattern.scattered_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "voronoi":
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
        # The STONES' cell count is the surface's own feature count.
        #
        # The feature count is the whole surface's - the stones AND
        # the joints - and the fractal's finer octaves are what make
        # the features finer than the cells.
        stones = pattern.fractal_stones(
            resolution,
            max(2, round(cells * pattern.STONE_CELL_FACTOR)),
            pebble_factor=pebble_factor,
            curvature_strength=curvature_strength,
        )
        cell = stones["cell"]
        edge = stones["distance"]
        curvature_field = stones.get("curvature")
        grid = (cells, cells)
    elif kind == "brick":
        # A BRICK's face is a WORKED surface, and the field returns
        # it: the truth's own Bricks113A measures a spread of 0.0716
        # on the face alone - nearly the whole map's.
        cell, edge, grid, brick_face = pattern.brick_field(
            resolution,
            cells,
            aspect=brick_aspect if brick_aspect is not None else pattern.BRICK_ASPECT,
        )
    elif kind == "parquet":
        # A PARQUET is the brick's courses with a wood's palette and
        # a much wider block, and the wide set says so: the truth's
        # own parquet measures a row-to-column change ratio of 0.24.
        cell, edge, grid, fibre = pattern.parquet_field(
            resolution,
            cells,
            aspect=brick_aspect if brick_aspect is not None else pattern.PARQUET_ASPECT,
        )
    elif kind == "herringbone":
        # A HERRINGBONE floor is BOARDS at ninety degrees to each
        # other, in pairs, and the truth's own parquet is a
        # basketweave and not a staggered course.
        cell, edge, grid, _fibre = pattern.herringbone_field(
            resolution,
            cells,
            aspect=pattern.HERRINGBONE_ASPECT,
        )
    elif kind == "woven":
        # A WOVEN cloth is a CROSSHATCH, and the lane's answer for a
        # fabric was a VORONOI - whose cells are large flat pieces
        # with hard borders - so a fabric came out as a field of
        # pebbles.
        cell, edge, grid, fibre = pattern.woven_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "roof":
        # A ROOF is courses of overlapping shingles, and each shingle
        # carries its own tone: a roof is a patchwork of weathered
        # tiles and the patchwork is what the eye reads.
        cell, edge, grid, fibre = pattern.roof_field(
            resolution,
            cells,
            aspect=pattern.ROOF_ASPECT,
        )
    elif kind == "carpet":
        # A CARPET is a pile of fibres, and the truth's own carpet is
        # almost flat - a spread of 0.029 over twenty-seven thousand
        # specks - and a directional fine grain.
        cell, edge, grid, fibre = pattern.carpet_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "leather":
        # A LEATHER is a fine even pebbled hide, and it is the loose
        # ground's primitive at a much finer scale and a much
        # tighter packing.
        cell, edge, grid, fibre = pattern.leather_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "markings":
        # A ROAD MARKING is painted GEOMETRY on a surface, and the
        # surface's own texture goes on underneath it.
        cell, edge, grid, fibre = pattern.markings_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "wallpaper":
        cell, edge, grid, fibre = pattern.wallpaper_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    elif kind == "grain":
        # A GRAIN's RINGS are the down count and its FIBRE is the
        # across count, and the two are different numbers.
        #
        # Measured on the truth's own Wood096: sixty-eight features
        # across and eight down. The rings were built at the across
        # count, so they were eight times too fine and the wood's
        # feature scale read 2.79x the truth's.
        # The RINGS are the ENVELOPE and the FIBRE is the fine one.
        #
        # The rings were at the surface's own feature count, and the
        # ring's own count is not the feature count: the surface's
        # feature count is the WHOLE surface's - the rings AND the
        # fibre - and the fibre decorrelates the rings.
        #
        # Measured on the truth's own: at four cells the lane reads
        # 9.2 features and at eight it reads 19.3, so the features
        # are two and a third times the cells. The truth's own
        # Wood096 measures 5.8 and its rings are two and a half; the
        # truth's own Wood092 measures 37.9 and its rings are
        # sixteen.
        cell, edge, grid, fibre = pattern.grain_field(
            resolution,
            max(2, round(cells / pattern.GRAIN_CELLS_PER_FEATURE)),
            lines_per_cell=lines_per_cell,
            fibre_cells=max(2, round(cells * pattern.FIBRE_CELLS_PER_RING)),
        )
    elif kind == "metal":
        cell, edge, grid, fibre = pattern.metal_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
            horizontal=metal_horizontal,
            banded=metal_banded,
            scratch_strength=scratch_strength,
            envelope_factor=metal_envelope_factor,
        )
    else:
        # A FLAT sheet: a plaster, a paint, a wallpaper, a smooth
        # concrete. It has no cells at all - it is one surface - and
        # its whole structure is a fine, soft variation.
        #
        # The lane had no such a kind, so every smooth surface became
        # a field of separate pieces: a plaster became cobbles.
        # Measured on the truth's own plaster - its correlation
        # decays smoothly and its cells are not there to be read.
        cell, edge, grid, fibre = pattern.flat_field(
            resolution,
            cells,
            lines_per_cell=lines_per_cell,
        )
    cell_width, cell_height = grid

    if kind in ("flat", "wallpaper"):
        # A FLAT sheet is a SOFT variation about its base, and not a
        # set of lines.
        #
        # The line pattern draws a line per cycle, and a line is a
        # strong single frequency: the plaster's feature scale read
        # 9.27x the truth's with it.
        #
        # So the sheet's variation is its own mottle, taken about the
        # middle of its range, and the base colour is the middle.
        import numpy as _np

        base = _np.array(stone_dark_rgb, dtype=numpy.float32).reshape(1, 1, 3)
        # The sheet's own SLOW variation, and it is the ENVELOPE - the
        # Perlin at the cell count. The truth's own plaster measures
        # ten features across, and that is the cell count.
        #
        # The mottle was the variation, and the mottle is at twice the
        # cell count: the plaster's feature scale read 25.50x the
        # truth's with it.
        reach = max(1e-6, float(edge.max() - edge.min()))
        variation = (edge - float(edge.min())) / reach - 0.5
        # The sheet's variation is the SPREAD the description asks
        # for, and it is not capped: the truth's own plaster carries a
        # spread of 0.0218 and ours read 0.20x that.
        colour = base + variation[:, :, _np.newaxis] * (
            base * max(1e-6, float(target_spread)) * 4.0
        )
        if kind == "wallpaper":
            # A WALLPAPER's DESIGN is on the sheet, and it is a
            # whisper: the truth's own printed plastisol measures a
            # spread of 0.0032 and its wallpaper 0.0072.
            #
            # The design was drawn as a chequer of black and white
            # squares and the contrast read 24.51x the truth's.
            motif = fibre if fibre is not None else numpy.zeros_like(edge)
            reach = max(1e-6, float(motif.max() - motif.min()))
            motif = (motif - float(motif.min())) / reach
            colour = base * (1.0 - WALLPAPER_DESIGN_DEPTH * motif)[:, :, _np.newaxis]
        colour = _np.clip(colour, 0.0, 1.0)
        # The sheet's CONTRAST is the description's spread, and it is
        # measured and scaled like every other pattern's: a sheet's
        # own shape carries a different amount of contrast than a
        # joint's, and only measuring says how much.
        #
        # The sheet skipped the scale entirely, so the truth's own
        # plaster read 0.77x the truth's contrast and the truth's
        # concrete 0.77x as well.
        if kind == "wallpaper":
            # A WALLPAPER's contrast is its DESIGN's and not the
            # description's.
            #
            # The description's spread is the SHEET's own - the
            # printed plastisol's words carry a spread of 0.0546 from
            # the word "printed" - and the design carries a twentieth
            # of that: the truth's own design measures 0.0032.
            #
            # So the design is scaled to its own spread and the
            # sheet's texture keeps the description's.
            colour = _scale_to_spread(colour, WALLPAPER_DESIGN_SPREAD)
        else:
            colour = _scale_to_spread(colour, target_spread)
        # And the sheet's MEAN is the description's own value, for
        # the same reason the cell patterns' is: the sheet's own
        # variation is centred and the base is the palette's, and the
        # two together are not the description's value.
        if target_value is not None:
            colour = _shift_to_value(colour, target_value)
        return _write_image(output_path, resolution, width_px, height_px, colour)

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
        base = _luma_of(stone_dark_rgb)
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
            target_value=target_value,
            fibre_strength=(
                METAL_FIBRE_STRENGTH if kind == "metal" else fibre_strength
            ),
        )

    # The joint's width, as a fraction of the distance to the edge.
    #
    # The reach is the MEDIAN of the distance, not its MAXIMUM. The
    # maximum is the distance at the middle of the largest cell, and
    # the largest cell is much bigger than the typical one - so a
    # width taken as a fraction of the maximum is a fraction of the
    # BIGGEST pebble, and the joints came out as threads.
    #
    # Measured on the truth's own ground: the joints are a sixth of
    # the surface - the dark tail below the tenth percentile covers
    # 16.9% of it. So the joint's width is a fraction of the typical
    # distance to the edge.
    if kind == "voronoi":
        # The joint is the MATRIX between the stones, and the matrix
        # is the COARSE lattice's - so the joint's distance is the
        # coarse one, and the stones are what is left.
        #
        # The truth's own ground is a gravel: a row carries fifty-six
        # bright stones and they are a third of the row, so the
        # ground is mostly DARK MATRIX with small bright stones in it.
        median_edge = float(numpy.median(edge))
        reach = median_edge if median_edge > 0 else 1.0
        joint = numpy.clip(edge / reach, 0.0, 1.0)
    elif kind in ("markings", "roof"):
        # The MARKINGS and a ROOF's shingles are their own masks and
        # not joints: a painted line is a stripe of a colour and it is
        # either there or it is not, and a shingle lies ON the one
        # below it.
        #
        # The joint's falloff - a gradient from the edge - is a BEVEL,
        # and the truth's own roof is a mosaic of FLAT shingles with a
        # per-shingle tone and a thin shadow at the edge.
        #
        # The joint's normalisation divides the field by its
        # maximum, and the markings' field is one on the road and
        # zero on the paint - so the normalisation would have made
        # every road pixel a full joint and every painted pixel
        # nothing, and the road would have been all paint.
        joint = numpy.clip(edge, 0.0, 1.0)
    else:
        joint = numpy.clip(edge / max(1e-6, float(edge.max())), 0.0, 1.0)
    # The joint is where the distance to the edge is SMALL.
    #
    # The width is a threshold on the distance: the joint is fully
    # dark at the edge and fades out by the threshold. It used to be
    # a fraction of the DISTANCE FIELD's maximum, and the maximum is
    # the widest cell's - so the joint came out as a thread and the
    # ground read as a mosaic of flat stones.
    #
    # And the width is the PEBBLE factor's: a loose ground crazes
    # with a wide matrix between its stones, and a solid surface's
    # joint is a hairline.
    #
    # Measured on the truth's own ground: the dark tail between the
    # stones covers 16.9% of the surface. The truth's tiles' grout
    # line is one or two pixels in a thousand, and the truth's
    # asphalt has no visible joint at all.
    #
    # The SPREAD is not the discriminator - the truth's bricks have a
    # spread of 0.076 and a hairline grout, and the truth's ground
    # has a spread of 0.124 and a wide matrix. The SURFACE'S KIND
    # is.
    if pebble_factor > 1.5:
        width = mortar_width
    else:
        width = mortar_width * JOINT_SOLID_FRACTION
    if kind == "scattered":
        # A SCATTER's joint is the MATRIX between its stones, and the
        # matrix is WIDE: the truth's own ground is a gravel with a
        # matrix twelve pixels wide between stones that are sixteen
        # pixels across, and the matrix is SEVENTY PER CENT of the
        # surface.
        #
        # So the joint's width is a large fraction of the stone's own
        # size, and not the hairline a cell's joint is.
        width = mortar_width * SCATTER_MATRIX_WIDTH
        # And the joint is HARD: a stone's edge is an edge and not a
        # gradient, and the soft falloff made the ground a field of
        # glowing blobs.
        joint = numpy.where(joint > SCATTER_JOINT_EDGE, joint, 1.0)
    if kind == "roof":
        # A ROOF's joint is a THIN SHADOW and not a bevel: the
        # shingle above casts a line on the one below.
        #
        # And it is a SHADOW and not a hard step: a hard step at the
        # wrap joins two shingles of a different tone and the seam
        # read 12.4x the truth's.
        joint = numpy.clip((joint - 0.90) / 0.10, 0.0, 1.0)
        # And the shadow is DARK and not the pale mortar: a roof's
        # shadow is a shadow.
        joint = joint * 0.45
    if kind not in ("markings", "roof"):
        # The joint's FALLOFF, and the MARKINGS' mask is not one.
        #
        # The falloff turns a distance into a joint - one at the
        # edge and zero at the distance's width - and the markings'
        # field is a MASK and not a distance: one on the road and
        # zero on the paint.
        #
        # So the falloff inverted the markings, and the road came
        # out white with the paint dark.
        joint = numpy.clip(1.0 - joint / max(width, 1e-6), 0.0, 1.0)

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
    if kind == "voronoi":
        # A VORONOI's cells each carry their own HUE, and a rock is
        # a patchwork of them.
        #
        # The hue variation was applied only to the scattered path's
        # stones, so a rock came out with ONE hue over the whole
        # surface: the truth's own Rock064's green share has a
        # standard deviation of 0.0336 and the lane's has 0.0019 -
        # and the truth's is a grey rock with green MOSS on it, and
        # the moss is a patch and not a tint.
        #
        # So the cell's own hue offset is the cell's hash, the same
        # way the scattered path's stones are, and it is applied to
        # the HUE and not to the brightness - so a cell is a patch of
        # a different colour and not a lighter or darker one.
        variation = hue_variation if hue_variation is not None else 0.10
        weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
        stone_luma = (stone * weights).sum(axis=2)
        stone_hue_vector = stone / _np.maximum(stone_luma[:, :, _np.newaxis], 1e-6)
        # The hue's variation is a SMOOTH FIELD and not a per-cell
        # constant, and it is at the MOSS's own scale.
        #
        # The truth's own Rock064's green share has a spread of
        # 0.0258 over sixteen-pixel blocks and its moss patches are
        # sixteen to thirty pixels across - and the lane's per-cell
        # hash put the variation in patches as big as the cell, a
        # hundred pixels, and the spread over the blocks was 0.0092.
        #
        # So the moss is a fine field of its own, and it is the
        # surface's own slow field at the moss's scale.
        from golem_blender.pbr import noise_perlin

        samples = pattern._domain_samples(resolution)
        sample_x, sample_y = _np.meshgrid(samples, samples, indexing="ij")
        # The moss is a FEW PATCHES and not a per-cell hue, and its
        # patches are the CELL's own size.
        #
        # It was a fine perlin at the moss's scale - sixteen to thirty
        # pixels - and a rock came out as a green and an orange
        # patchwork: a per-pixel hue change is a different COLOUR and
        # not a patch of moss.
        #
        # So the hue is the cell's own hash - a patch of a cell's
        # size - and the field's own slow variation rides on it, so
        # the patches are not all the same.
        hue_lattice = max(2, round(cells / 2))
        hue_field = noise_perlin.perlin_2d(
            sample_x * hue_lattice,
            sample_y * hue_lattice,
            period=hue_lattice,
            seed=13,
        )
        hue_reach = max(1e-6, float(hue_field.max() - hue_field.min()))
        # And only SOME of the cells carry the moss: the truth's own
        # Rock064 is a grey rock with green moss in parts of it, and
        # the moss is a MINORITY - a cell with a full hue swing on
        # every cell gave a green and a tan patchwork.
        #
        # So the hue's offset is the cell's own hash, and a cell
        # carries it only when its hash says so: the moss is in some
        # places and not in others.
        cell_hue = (hashed - 0.5) * 2.0 + (hue_field - 0.5) * 0.8
        cell_hue = _np.where(
            hashed > MOSS_FRACTION,
            cell_hue,
            cell_hue * MOSS_PATCH_SHARE,
        )
        offsets = _np.stack(
            (
                cell_hue * variation,
                -cell_hue * 0.4 * variation,
                -cell_hue * 1.2 * variation,
            ),
            axis=2,
        )
        stone = _np.clip(
            stone + stone_hue_vector * offsets * stone_luma[:, :, _np.newaxis],
            0.0,
            1.0,
        )
    if kind == "brick" and brick_face_strength <= BRICK_FACE_GRAIN_CUTOFF:
        # A TILE is a GLAZED surface, and its cells do not each have
        # their own random tone - they are all one firing, and what
        # varies across them is the STAIN.
        #
        # The truth's own Tiles141 measures a per-block tone spread of
        # 0.0336, so its tiles DO differ - and a hundred-and-twenty-
        # eight-pixel blur of it still carries 0.0349, a fifth of the
        # map's variance. So the difference between one tile and the
        # next is a SLOW field crossing the wall and not a hash per
        # cell: the lane's hash gave every tile its own tone and the
        # wall came out as a sharp chequerboard where the truth's is
        # a soft stain.
        #
        # So the cell's tone is the DRIFT, and the drift is the
        # surface's own slow field - and it is the drift's MEAN over
        # the cell, so a tile is one tone across its whole face and
        # the stain crosses the wall.
        #
        # And the drift is added CONTINUOUSLY on top of that, so the
        # stain crosses the joints and does not step at them: the
        # cell's own mean is the tile's tone and the drift's own
        # field is the stain that runs over it.
        drift = pattern.slow_variation(resolution, pattern.BRICK_FACE_DRIFT_CELLS)
        drift_at_cell = _cell_mean(drift, cell, cell_width, cell_height)
        for channel in range(3):
            ramp = _np.linspace(stone_dark_rgb[channel], stone_light_rgb[channel], 256)
            tone = drift_at_cell + (drift - drift_at_cell) * BRICK_FACE_DRIFT_CONTINUITY
            stone[:, :, channel] = ramp[
                _np.clip((tone * 255).astype(numpy.int32), 0, 255)
            ]
    if kind == "scattered":
        # The STONES' own tone is the matrix's mottle, and the matrix
        # between them is dark.
        #
        # A scatter has no cells to hash - the stones are placed, not
        # tiled - so the tone is the mottle and the joint is the
        # scatter's own field.
        #
        # And the mottle is the WHOLE RAMP: the stone is the ramp's
        # LIGHT end and the matrix is its DARK end, and not both of
        # them at the middle.
        #
        # Measured on the truth's own ground: the bright stones read
        # a luma of 0.547 and the dark matrix 0.242, against a
        # palette ramp of 0.262 to 0.520 - so the stones sit at 1.10
        # of the ramp and the matrix at -0.08 of it. The ramp IS the
        # stone-to-matrix contrast.
        #
        # The stones were drawn about the ramp's MIDDLE, so the
        # contrast between a stone and the matrix beside it was a
        # quarter of the ramp and not all of it, and the ground came
        # out as pale stones in a pale matrix. Measured, the stones
        # read 0.722 against a truth's 0.547 and the matrix 0.397
        # against a truth's 0.242.
        # The STONES' own tone is the ramp's LIGHT end and the ramp
        # is the stone-to-matrix contrast.
        #
        # The tone field is the SLOW field sampled at each stone, and
        # it spans the WHOLE ramp: the truth's own ground has stones
        # from 0.467 to 0.690 and a matrix at 0.244, and a ramp that
        # the stones sat in the middle of made them flat.
        #
        # The ramp's own width is the description's SPREAD and it is
        # narrow - a surface's colour varies little across itself -
        # but the stone-to-matrix contrast IS the whole spread, and it
        # has to be scaled up to fill it.
        for channel in range(3):
            ramp = _np.linspace(stone_dark_rgb[channel], stone_light_rgb[channel], 256)
            stone[:, :, channel] = ramp[
                _np.clip((fibre * 255).astype(numpy.int32), 0, 255)
            ]
    if pebble_factor > 1.5 and kind != "scattered":
        # A STONE's own tone is a SMALL part of the surface's
        # variation, and the MATRIX is the rest.
        #
        # The truth's own ground is a gravel of stones that are all
        # much the same grey - the variation is in the MATRIX and in
        # the stones' EDGES, and not in the stones' tones. So a
        # stone's tone is drawn about the middle of the ramp, and the
        # ramp is the MATRIX's.
        #
        # With the stones on the whole ramp the colour's variation
        # was as strong as the truth's, the feature measure read the
        # stones' own count, and the ground's feature scale read
        # 3.12x the truth's.
        for channel in range(3):
            middle = (stone_dark_rgb[channel] + stone_light_rgb[channel]) * 0.5
            stone[:, :, channel] = (
                middle + (stone[:, :, channel] - middle) * stone_tone_fraction
            )
    # A PEBBLE's own tone was drawn about the middle of the ramp, at a
    # fraction of its width, so the MATRIX would carry the surface's
    # contrast. It was not needed: the cell is the COARSE lattice's
    # and the pebbles are the JOINT, so the cell's tone is already
    # the envelope's. Measured, the fraction had to be the whole ramp
    # for the ground's brightness to read 1.06x the truth's - and with
    # the cell at the pebbles' lattice the ground's feature scale read
    # 2.94x the truth's whatever the fraction was.

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
    if kind == "leather":
        # A LEATHER's wear is its own CRACKLE, and it is the fine
        # texture on the hide.
        #
        # The truth's own leathers carry two thirds of their spread in
        # the fine and a third in the envelope, and the generic
        # mottle was the wear - so the crackle was a thin joint and
        # the whole spread was in the mottle.
        #
        # And the truth's own Leather037 measures five hundred and
        # twelve features across: its envelope is nearly flat and the
        # crackle is everything.
        if fibre is not None:
            surface = numpy.clip(fibre, 0.0, 1.0)
            surface = surface / max(1e-6, float(surface.max())) * 2.0 - 1.0
            wear = surface * LEATHER_CRACKLE_STRENGTH * ramp_spread
        else:
            surface = pattern.surface_texture(resolution, cells)
            surface_amplitude = float(surface.max() - surface.min())
            if surface_amplitude > 0.0:
                surface = surface / surface_amplitude * 2.0 - 1.0
            wear = surface * min(variation, 1.0) * ramp_spread * SURFACE_SHARE
    elif kind == "carpet":
        # A CARPET's wear is its own PILE, and it is a fine
        # directional mottle.
        #
        # The cell path draws a joint from the edge field, and the
        # carpet's edge is the pile's complement - so the pile was
        # drawn as a JOINT and the carpet came out as a smooth
        # sheet with a dark line in it.
        #
        # So the carpet's own field is the wear, and the wear is the
        # pile and not a generic mottle: a carpet is a pile of
        # fibres and the fibres are what the eye reads.
        if fibre is not None:
            surface = numpy.clip(fibre, 0.0, 1.0)
            surface = surface / max(1e-6, float(surface.max())) * 2.0 - 1.0
            wear = surface * CARPET_FIBRE_STRENGTH * ramp_spread
        else:
            surface = pattern.surface_texture(resolution, cells)
            surface_amplitude = float(surface.max() - surface.min())
            if surface_amplitude > 0.0:
                surface = surface / surface_amplitude * 2.0 - 1.0
            wear = surface * min(variation, 1.0) * ramp_spread * SURFACE_SHARE
    elif kind == "parquet" and fibre is not None:
        # A PARQUET's wear is the block's own GRAIN, and it is the
        # wood's own fibre - and not a generic mottle.
        #
        # The mottle is a fine noise, and a fine noise over a wood
        # floor is a field of swirls where the truth has fine lines
        # along each board.
        #
        # The fibre is a DARKNESS - one at the line and zero between
        # the lines - and the wear is signed about the middle, so
        # the light parts go above the base and the dark parts below
        # it, which is what a board's grain does.
        # The grain is a SUBTLE variation and not a corduroy: the
        # truth's own parquet carries 0.87 of its spread in the fine
        # and 0.13 in the blocks, and the fine is a *smooth*
        # variation - a board's grain is a slow change of colour and
        # not a set of lines.
        #
        # So the grain is the fibre's own SMOOTHED value and not its
        # ridge: the ridge is a hard line and the truth's board is
        # not.
        surface = numpy.clip(fibre, 0.0, 1.0)
        surface = surface / max(1e-6, float(surface.max())) * 2.0 - 1.0
        wear = surface * PARQUET_FIBRE_STRENGTH * ramp_spread * 0.25
    else:
        surface = pattern.surface_texture(resolution, cells)
        surface_amplitude = float(surface.max() - surface.min())
        if surface_amplitude > 0.0:
            surface = surface / surface_amplitude * 2.0 - 1.0
        wear = surface * min(variation, 1.0) * ramp_spread * SURFACE_SHARE
    if brick_face is not None:
        # A BRICK's FACE is its own surface, and it is the bulk of
        # the map's variation: the truth's own Bricks113A measures a
        # spread of 0.0716 on the face alone.
        #
        # The generic mottle was the wear, and a mottle is a fine
        # noise and not a worked stone - so the brick came out as a
        # flat colour in a frame.
        surface = numpy.clip(brick_face, 0.0, 1.0)
        surface = surface / max(1e-6, float(surface.max())) * 2.0 - 1.0
        wear = surface * brick_face_strength * ramp_spread
        # And the surface's SLOW DRIFT, which a TILE carries and a
        # BRICK does not: a tile is a large flat surface and it
        # stains.
        if drift_strength > 0.0:
            # The DRIFT is at the SURFACE's own scale, and it is a
            # slow field: the truth's own Tiles141's drift has a
            # period of a hundred and ninety-two pixels, so five
            # features across a thousand and twenty-four.
            #
            # And it carries a quarter of the map's VARIANCE - the
            # truth's is 0.22 - so it is a major part of the surface
            # and not a tint on it.
            drift = pattern.slow_variation(resolution, pattern.BRICK_FACE_DRIFT_CELLS)
            wear = wear + (drift - 0.5) * drift_strength * ramp_spread
    elif curvature_field is not None:
        # A ROCK's FACETS, and they are the CURVATURE.
        #
        # The curvature is the map that gives a hand-painted edge
        # treatment its rim and a cavity mask its darkness - and a
        # rock is a set of flat faces with sharp edges between them.
        #
        # The truth's own Rock051 carries a gradient of 0.037, one and
        # a half times the sheet's own variation, and the lane's rock
        # is a smooth blob field with no edge in it.
        curved = numpy.clip(curvature_field, 0.0, 1.0)
        curved = curved / max(1e-6, float(curved.max()))
        wear = wear + (curved - 0.5) * curvature_strength * ramp_spread
    # The wear is a change of LUMA, not of each channel equally: a
    # grey wear on a chromatic stone GREYS the stone out, and the
    # truth's ground is warm to the last. So the wear is added along
    # the luma's own direction - the stone keeps its hue and the
    # wear moves it lighter or darker.
    weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
    stone_luma = (stone * weights).sum(axis=2)
    hue = stone / _np.maximum(stone_luma[:, :, numpy.newaxis], 1e-6)
    colour = _np.clip(stone + hue * wear[:, :, numpy.newaxis], 0.0, 1.0)

    # The joint replaces the stone where the joint is.
    mortar = numpy.array(mortar_rgb, dtype=numpy.float32).reshape(1, 1, 3)
    joint = joint[:, :, numpy.newaxis]
    if kind == "scattered":
        # The MATRIX's own grit, and it is the surface's own mottle.
        #
        # The truth's own ground's matrix carries a spread of 0.0824
        # - two thirds of the whole surface's - and the lane's carried
        # 0.0183, so the gaps between the stones were a smooth brown
        # sheet where the truth's is packed dirt.
        matrix_grit = pattern.surface_texture(resolution, cells)
        matrix_grit = matrix_grit - float(matrix_grit.min())
        matrix_grit = matrix_grit / max(1e-6, float(matrix_grit.max()))
        # A SCATTER's joint is the MATRIX, and the matrix is the
        # surface's own slow variation and not a flat colour.
        #
        # A flat mortar filled every gap between the stones with one
        # colour, and the ground read as pale stones on a pale sheet.
        # The truth's matrix is DARK and it VARIES: a worn patch of
        # ground is a patch of paler matrix.
        #
        # So the matrix is the ramp's DARK end, moved by the scatter's
        # own slow field - and the scatter's field is the `fibre`
        # the stones' own tone came from.
        # The matrix's tone is the ramp's DARK end, and the SLOW
        # variation rides on it - so a worn patch of ground is a
        # patch of paler stones AND a paler matrix.
        #
        # The scatter's `fibre` is the STONES' own tone: zero on the
        # matrix and the stone's own tone where the stone is. So the
        # matrix's own tone is the complement, and the slow variation
        # is the surface's own mottle.
        #
        # The slow variation matters for the MEASURE and not only for
        # the eye: the truth's ground measures nineteen features
        # across where the stones alone are a couple of pixels
        # across, and the measure finds the surface's slow variation.
        # The MATRIX is the ramp's DARK end, and the slow variation
        # moves it within that dark end - so a worn patch of ground is
        # a patch of paler matrix.
        #
        # And the matrix goes BELOW the ramp's dark end, because the
        # ramp is the stone-to-matrix contrast and the matrix is the
        # shadow in the gaps. The truth's own ground reads a matrix
        # of 0.172 where the palette's ramp starts at 0.186 - so the
        # matrix was on the ramp's dark end and not under it, and the
        # gap between the stones had no depth.
        #
        # And the matrix's tone stays at the BOTTOM of the ramp: it
        # ran to a third of the way up, so the gaps between the stones
        # were a pale grey and the ground came out flat. Measured:
        # the matrix read 0.246 against a truth's 0.172 - a third too
        # bright - and the stone-to-matrix contrast read 0.372 against
        # a truth's 0.430.
        #
        # So the matrix's ramp starts UNDER the palette's dark end -
        # the shadow's own share - and the matrix's tone rides at the
        # bottom of it, with the slow variation for the patches.
        matrix_tone = _np.clip(MATRIX_TONE_BASE + MATRIX_TONE_RANGE * slow, 0.0, 1.0)
        # And the MATRIX's own GRIT, and the matrix between the
        # stones is DIRT and not a flat sheet.
        #
        # The truth's own ground's matrix carries a spread of 0.0824
        # - two thirds of the whole surface's - and the lane's carried
        # 0.0183, so the gaps between the stones were a smooth brown
        # sheet and the truth's is packed dirt.
        matrix_tone = _np.clip(matrix_tone + matrix_grit * MATRIX_GRIT_SHARE, 0.0, 1.0)
        matrix_colour = numpy.empty_like(stone)
        for channel in range(3):
            # The matrix's own ramp is EXTENDED below the palette's
            # dark end, so the shadow in the gaps has somewhere to go
            # that is darker than the stones' own darkest.
            # The matrix's own ramp is WIDE, and the shadow's share
            # is its floor and not its ceiling: the truth's own ground's
            # matrix runs from 0.12 to 0.29 and a narrow ramp cannot
            # carry the grit in it.
            dark = stone_dark_rgb[channel] * MATRIX_SHADOW_SHARE
            ramp = _np.linspace(
                dark, stone_dark_rgb[channel] * MATRIX_TONE_CEILING, 256
            )
            matrix_colour[:, :, channel] = ramp[
                _np.clip((matrix_tone * 255).astype(_np.int32), 0, 255)
            ]
        colour = colour * (1.0 - joint) + matrix_colour * joint
        # And the STONES' own HUE variation, which is a per-stone
        # constant.
        #
        # The whole surface was one hue, so a ground of grey stones
        # came out as a ground of tan ones. The truth's own gravel
        # carries stones whose red share runs from 0.351 to 0.393 -
        # a fiftieth - and a close crop of the truth shows it.
        #
        # The offset is applied to the HUE and not to the channels:
        # a stone that is a little greener is a stone with a
        # different hue and not a different brightness.
        if stone_hue is not None:
            # The offsets are the hue's OWN direction, and a warm
            # stone is red and blue against the green: the truth's
            # stones' red and blue shares move together and their
            # green share barely moves.
            #
            # Measured, the truth's stones' red share varies by
            # 0.0153 and their blue by 0.0186 and their green by
            # 0.0060 - so the green is a third of the red.
            # The hue's own variation, and it is a fraction of the
            # surface's SPREAD: a surface whose colour varies a lot
            # has stones that vary a lot in hue too.
            #
            # The truth's own gravel carries stones whose red share
            # varies by 0.0153 and its spread is 0.124, and the
            # truth's fallen leaves vary by 0.0223 and their spread
            # is 0.0812. So the leaves vary MORE in hue on a
            # SMALLER spread - a mat of many colours and not one
            # colour in many shades.
            #
            # So the hue's variation is its own number and the
            # spread does not decide it.
            variation = hue_variation if hue_variation is not None else 0.10
            offsets = numpy.stack(
                (
                    stone_hue * variation,
                    -stone_hue * 0.4 * variation,
                    -stone_hue * 1.2 * variation,
                ),
                axis=2,
            )
            weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
            stone_luma = (colour * weights).sum(axis=2)
            stone_hue_vector = colour / _np.maximum(
                stone_luma[:, :, numpy.newaxis], 1e-6
            )
            colour = _np.clip(
                colour + stone_hue_vector * offsets * stone_luma[:, :, numpy.newaxis],
                0.0,
                1.0,
            )
        # And the SLOW drift rides on the WHOLE image, as a
        # continuous layer.
        #
        # It was on the stone's own tone, and the stone is a couple of
        # pixels across - so the drift was sampled at the stone's own
        # scale and it broke up, and the surface's autocorrelation
        # read the stones and not the drift.
        #
        # Measured: the ground's period read fourteen pixels against
        # the truth's fifty-three.
        #
        # So the drift is added over the whole image, after the
        # stones, and it moves the luma and not the hue - so a worn
        # patch of ground is a paler patch and not a patch of a
        # different colour.
        #
        # And the drift's SHARE is two fifths and not more: the
        # truth's own ground carries about a third of its spread in
        # the envelope and two thirds in the fine, and the drift was
        # carrying a half and a half."
        drift = (slow - 0.5) * ramp_spread * SCATTER_DRIFT_SHARE
        weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
        image_luma = (colour * weights).sum(axis=2)
        image_hue = colour / _np.maximum(image_luma[:, :, _np.newaxis], 1e-6)
        colour = _np.clip(colour + image_hue * drift[:, :, _np.newaxis], 0.0, 1.0)
    elif kind == "roof":
        # A ROOF's shingles are a MOSAIC of flat tiles, and the line
        # between them is a SHADOW.
        #
        # The joint blended with the pale mortar, and the roof came
        # out as a light brickwork with a bright outline around every
        # shingle - and the truth's own roof is a dark sheet where the
        # shingles' edges are barely there.
        #
        # And the shingle's tone is a SMALL part of the ramp: the
        # truth's own RoofingTiles013A's eight-by-eight blocks of
        # shingles measure between 0.165 and 0.214 - a spread of
        # 0.049, a seventh of the surface's own mean.
        #
        # The hash spans the whole ramp, so the roof came out with a
        # threefold spread of shingles and a contrast of 3.55x the
        # truth's.
        #
        # And the shingle's tone is a SMOOTH field and not a per
        # shingle hash, and that is what tiles: the half-shingle
        # stagger means the wrap joins a shingle to one a whole row
        # away, and a per-shingle hash makes that a colour step.
        # Measured, the roof's seam read 12.4x the truth's.
        middle = (
            numpy.array(stone_dark_rgb, dtype=numpy.float32)
            + numpy.array(stone_light_rgb, dtype=numpy.float32)
        ) * 0.5
        # And the shingle's tone is the roof's own SMOOTH field, and
        # not a per-shingle hash: the half-shingle stagger means the
        # wrap joins a shingle to one a whole row away, and a hash
        # makes that a colour step. Measured, the roof's seam read
        # 12.4x the truth's.
        if fibre is not None:
            tone = numpy.clip(fibre, 0.0, 1.0)
            reach = numpy.array(stone_light_rgb, dtype=numpy.float32) - numpy.array(
                stone_dark_rgb, dtype=numpy.float32
            )
            colour = middle + (tone - 0.5)[:, :, numpy.newaxis] * (
                ROOF_SHINGLE_TONE * reach
            )
        colour = colour * (1.0 - joint) + mortar * joint
    elif kind == "woven":
        # A WOVEN cloth is a CROSSHATCH of two thread fields, and it
        # is drawn as a WEAR and not as a joint.
        #
        # The joint's falloff softens a hard edge, and a thread is a
        # hard edge - so the weave came out as a haze where the truth
        # has a crosshatch.
        #
        # And the cloth's own base is the palette's colour, and not
        # a cell's hash: a weave has no cells to hash.
        base = numpy.array(stone_dark_rgb, dtype=numpy.float32).reshape(1, 1, 3)
        threads = numpy.clip(fibre, 0.0, 1.0) if fibre is not None else None
        if threads is None:
            threads = numpy.zeros_like(edge)
        reach = max(1e-6, float(threads.max()))
        threads = threads / reach
        colour = base * (1.0 - WOVEN_THREAD_DEPTH * threads)[:, :, numpy.newaxis]
    elif kind == "markings":
        # A ROAD MARKING is painted GEOMETRY, and it is drawn OVER
        # the road - in the paint's own colour, which is not the
        # road's.
        #
        # The lane had no kind for a road with markings on it, and
        # the wide set has four: they came out as a field of asphalt
        # with the lines missing.
        #
        # So the markings are drawn over the road's own colour, and
        # the road keeps its texture underneath.
        # The ROAD's own colour is the palette's BASE and not a
        # cell's hash: a road is one surface and the markings are on
        # it, so there are no cells to hash. The road's own texture
        # is the markings' slow field.
        base = numpy.array(stone_dark_rgb, dtype=numpy.float32).reshape(1, 1, 3)
        road = fibre if fibre is not None else numpy.zeros_like(colour[:, :, 0])
        road_reach = max(1e-6, float(road.max() - road.min()))
        road = (road - float(road.min())) / road_reach
        # The road's own TEXTURE, and it is the road's spread: the
        # truth's own asphalt carries 0.0301 and the painted line is
        # the rest of the map's contrast.
        texture = (road - 0.5) * (target_spread or 0.03)
        colour = base + texture[:, :, numpy.newaxis]
        paint = numpy.array(
            paint_rgb if paint_rgb is not None else DEFAULT_PAINT_RGB,
            dtype=numpy.float32,
        ).reshape(1, 1, 3)
        # The markings' own field is a DARKNESS - one on a stripe and
        # zero on the road - and the writer's joint is the road's own
        # distance to its edge, so the paint is drawn with the
        # markings' own mask.
        # The joint is already a column of three, so the paint's mask
        # is one minus it and the road is under it.
        marked = 1.0 - joint
        colour = colour * (1.0 - marked) + paint * marked
    else:
        colour = colour * (1.0 - joint) + mortar * joint
    colour = numpy.clip(colour, 0.0, 1.0)
    # The image's variation is scaled so its spread IS the
    # description's - a pattern's contrast depends on its SHAPE and
    # not only on its numbers, and only measuring says how much of
    # the spread this one carries.
    if kind == "markings":
        # The MARKINGS' contrast is NOT the surface's spread, and the
        # image is not scaled to it.
        #
        # A painted line is a hard edge and it is a BIG contrast: the
        # truth's own Road007 is a white line on a luma of 0.309 and
        # its spread is 0.071 - and the road's own spread is 0.0301.
        #
        # The image was scaled to that spread, and the scaling is
        # about the image's own mean - so the road, which was dark,
        # was lifted to white and the paint came out grey. The
        # scaling moves the variation and the MEAN with it, and here
        # the mean IS the picture.
        #
        # So the road's own texture is scaled to the road's spread
        # and the paint keeps its own colour, and the map's contrast
        # is the paint's.
        pass
    else:
        colour = _scale_to_spread(colour, target_spread)
    # And the image's MEAN is the description's own VALUE.
    #
    # The spread is scaled about the image's mean and the mean is
    # left alone, so whatever the pattern put there is what the
    # image's brightness is. And a pattern does not necessarily put
    # the description's value there: the scattered ground's stones
    # sit at the ramp's light end and its matrix at the dark end,
    # and the two together do not average to the ramp's middle.
    #
    # Measured: the ground's luma came out at 0.304 where the
    # description's value is 0.391 and the truth's own is 0.360.
    #
    # So the image is shifted to the description's value, along its
    # own hue so the shift does not change the colour.
    if target_value is not None and kind != "markings":
        colour = _shift_to_value(colour, target_value)

    # The image is written at the resolution the pattern was computed
    # at, which is the requested one - there is no upscale, because an
    # upscale shifts the pattern's periodicity and the map's seam
    # shows.
    return _write_image(output_path, resolution, width_px, height_px, colour)


def _write_image(
    output_path: Path,
    resolution: int,
    width_px: int,
    height_px: int,
    colour,
) -> Path:
    """Write a colour field as a PNG, and return the path.

    The field is written through Blender's own image API, and the
    values that go in are the values that come out - so nothing
    renders them and nothing can distort them.
    """
    import bpy
    import numpy

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


def _luma_of(rgb) -> float:
    """The LUMA of an RGB triple, on the same weights the benchmark uses.

    The channel MEAN is not the luma: a blue fabric's mean is 0.37
    while its luma is 0.33, and the image's brightness is the luma.
    """
    return 0.2126 * float(rgb[0]) + 0.7152 * float(rgb[1]) + 0.0722 * float(rgb[2])


def _shift_to_value(colour, target_value: float):
    """Shift the image so its LUMA is the description's own value.

    The shift is along the image's own hue - a surface's colour does
    not change when it is lighter or darker, it is the same colour at
    another level - so the hue survives the shift.
    """
    import numpy as _np

    weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
    luma = (colour * weights).sum(axis=2)
    measured = float(luma.mean())
    if measured <= 1e-9:
        return colour
    hue = colour / _np.maximum(luma[:, :, _np.newaxis], 1e-6)
    shifted = colour + hue * (target_value - measured)
    return _np.clip(shifted, 0.0, 1.0)


def _scale_to_spread(colour, target_spread):
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

    The variation is scaled about the image's OWN MEAN and not about
    the palette's base colour, and that is the whole point of the
    correction: scaling about a point that is not the mean MOVES the
    mean, and the image's brightness is then not the description's.

    It scaled about the palette's DARK end - the ramp's low value -
    and the ramp's low value is below the image's own mean whenever
    the pattern does not fill its ramp. So the correction that made
    the contrast right also made the surface BRIGHTER, by exactly
    the amount the pattern sat above the ramp's floor.

    Measured: the scattered ground's own luma was 0.344 with a
    spread of 0.087, and the target spread was 0.129 - so the
    correction was a factor of 1.49, and scaling about a base of
    0.168 lifted the mean from 0.344 to 0.430. The ground's
    brightness then read 1.44x the truth's.

    So the variation is scaled about the image's own mean, and the
    mean is left where it was: the brightness is the description's
    own and the contrast is the description's own, and the two are
    independent.
    """
    import numpy as _np

    if target_spread is None or target_spread <= 0.0:
        return colour
    # The measure is the LUMA, and the base is the LUMA too - the
    # benchmark measures the luma, and the palette is chromatic now.
    # A blue fabric's red channel is 0.24 while its luma is 0.33, so
    # a red-channel measure scaled the image by the wrong factor.
    weights = _np.array([0.2126, 0.7152, 0.0722], dtype=_np.float32)
    luma = (colour * weights).sum(axis=2)
    measured = float(luma.std())
    if measured <= 1e-9:
        return colour
    scale = target_spread / measured
    # The image's own MEAN, and not the palette's base: the scaling
    # moves the variation about a point, and a point that is not the
    # mean drags the mean with it.
    centre = float(luma.mean())
    scaled = colour + (luma[:, :, _np.newaxis] - centre) * (scale - 1.0)
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
    target_value: float | None = None,
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
    # The darkness is RE-CENTRED, so the base colour is reached.
    #
    # The two darknesses summed to a mean of 0.657, so the base
    # colour was reachable in no part of the image at all - the whole
    # surface was drawn in the line colour, which is the base
    # darkened, and the wood came out at 0.73x the truth's brightness.
    #
    # The truth's own wood is the other way round: its p5 is 0.604
    # and its p95 is 0.690, and its mean is 0.649 - so the base
    # colour is the wood's MEDIAN and the surface is drawn both
    # lighter and darker than it.
    #
    # So the darkness is shifted so that its own mean is the half,
    # and the base is reached in the light parts and the line colour
    # in the dark ones.
    darkness = darkness - 0.5 * float(darkness.mean())
    darkness = _np.clip(darkness * 2.0, 0.0, 1.0)
    # The surface is drawn BOTH LIGHTER AND DARKER than the base.
    #
    # The blend was one-sided - the base colour everywhere the
    # darkness was zero and the line colour everywhere else - and the
    # darkness's mean was 0.657, so the base was reachable in no part
    # of the image and the whole surface was drawn in the line
    # colour, which is the base DARKENED. The wood came out at 0.73x
    # the truth's brightness.
    #
    # The truth's own wood is the other way round: its p5 is 0.604
    # and its p95 is 0.690 and its mean is 0.649 - the base colour
    # is the wood's MEDIAN, and the surface is drawn both lighter and
    # darker than it.
    #
    # So the colour is the base plus a signed variation: the light
    # parts go above the base and the dark parts below it, and the
    # base is the middle.
    signed = darkness * 2.0 - 1.0
    light = base * (1.0 + LINE_LIGHT_FRACTION)
    colour = base + signed[:, :, _np.newaxis] * (light - lines) * 0.5
    colour = _np.clip(colour, 0.0, 1.0)
    # The image's variation is scaled so its spread IS the
    # description's - a line's falloff carries a different amount of
    # contrast than a joint's, and only measuring says how much of
    # the spread this one carries.
    colour = _scale_to_spread(colour, target_spread)
    # And the image's MEAN is the description's own value.
    if target_value is not None:
        colour = _shift_to_value(colour, target_value)

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
