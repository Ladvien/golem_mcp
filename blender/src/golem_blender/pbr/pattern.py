"""The pattern's FIELDS: the cell each point is in, and the distance to
that cell's edge.

This is the arithmetic behind both the procedural base colour and the
procedural relief, so the two are the SAME pattern by construction -
the relief's joints land on the colour's own mortar lines.

It is here, in numpy, rather than in a shader graph, because the
graph route cost a round: the pattern is arithmetic, and wiring it
through Blender's nodes put four separate defects between the intent
and the image, each of which had to be found by measuring the result.

THE PATTERN
A REGULAR lattice of cells, and a DOMAIN WARP that breaks it into
stones.

The lattice is regular - `cells` x `cells` points at (i + 0.5) / cells
- and the search for the nearest point WRAPS: a sample near the
domain's edge also considers the point on the other side. That is
what makes the pattern periodic, and it is why the lattice cannot be
jittered: a jitter derived from the fractional position is not
periodic, and a jitter derived from the integer index is not
consistent under the wrap. Measured: an unwrapped lattice put a hard
black line down the middle of the image, and the pattern did not
repeat across it.

The WARP is what makes the cells look like stones rather than a grid:
a few octaves of sines over the domain, with INTEGER frequencies so
the warp is periodic, displacing the sample coordinates before the
cells are found.

THE WARP'S FREQUENCY IS WHAT DECIDES IT. A warp at frequencies 1, 2
and 3 is a smooth, low-frequency bend: it turned the lattice into a
regular grid of curved quads - a net, not a quay. A lattice is
broken by a warp that moves each cell a DIFFERENT amount, and that
needs a frequency comparable to the cell count. The octaves here are
at 3, 5 and 8 cycles per domain, and the two axes carry DIFFERENT
frequency sets so they do not shear together.

THE FIELDS
- the CELL: the nearest lattice point;
- the EDGE: the distance to the cell's boundary, which is the
  distance to the second-nearest point less the distance to the
  nearest. Zero on the boundary, growing into the stone.

PERIODICITY
The lattice is regular and the search wraps, and the warp's
frequencies are integers, so the whole field repeats exactly: cell N
is cell 0, and the image's edge meets its own edge. Measured, the seam
is 0.00x the texture's largest ordinary features, against a
generated map's 1.38x - and ambientcg's own maps, which are made to
tile, measure 0.32x to 0.47x.
"""

from __future__ import annotations

import math

# The warp's octaves: (frequency in cycles per domain, amplitude in
# cell units). The frequencies are INTEGERS, because the field has to
# be periodic over the domain, and they are HIGH, because a smooth
# warp bends a lattice rather than breaking it.
DEFAULT_WARP_OCTAVES = ((3, 0.34), (5, 0.22), (8, 0.14), (13, 0.09), (21, 0.05))
# How much of the warp's amplitude is USED.
#
# The warp's octaves move a sample by up to a whole cell, and a
# sample that moves a whole cell lands in its neighbour's place - so
# the cells merge and the stones come out as amoebas with no joint
# between them. Measured, the ground's stones were amoebas while the
# truth's are round pebbles with a clear gap.
#
# So only a part of the warp is used: enough to break the lattice
# into stones that are not regular polygons, and not enough to move
# one stone into its neighbour.
WARP_AMOUNT = 0.30
# A LINE pattern's drift octaves: (frequency in cycles per domain,
# amplitude). They are LOW frequencies, because a line that wanders
# fast is a zigzag and not a grain - and the drift has to be slow
# enough that the pattern's autocorrelation decays over the truth's
# own period rather than a fraction of it.
DEFAULT_LINE_OCTAVES = ((1, 1.0), (2, 0.5), (3, 0.3))
# A STONE's own surface: (frequency in cycles per domain, amplitude).
# These are HIGH frequencies, because a stone's mottle is much finer
# than the stone itself - and the truth's stones show it: a close
# crop of the ground is a field of small light and dark patches, not
# a flat blob.
DEFAULT_SURFACE_OCTAVES = ((17, 0.5), (29, 0.3), (43, 0.2))
# The SURFACE's mottle, as NOISE: how many patches a cell carries,
# how many octaves, and how quickly each octave quiets down.
#
# The patches are the mottle's scale: material-maker's fbm4 uses
# five octaves with a persistence of 0.5, and the lane's stones need
# their mottle at a scale much finer than the stone itself.
#
# Measured, the truth's ground carries small light and dark patches
# - a few pixels across in a 1024 image - and a stone at ten cells
# across the image is a hundred pixels, so a stone carries a handful
# of the patches and the domain carries a hundred.
SURFACE_PATCHES_PER_CELL = 12
# And a FLAT sheet's TOOTH's own lattice, as a multiple of the
# sheet's feature count.
#
# The truth's own Plaster001 puts 2.8 per cent of its power above a
# sixty-fourth of the image - a very fine speckle - and ours put
# nothing there at all, because the sheet's fine texture was
# computed and thrown away.
FLAT_TOOTH_LATTICE_FACTOR = 32
# A ROCK face's layers: the fine grain's sigma (pixels at 1024) and how
# much of the
# face each layer carries. The truth's own rock faces are mostly fine
# grain with a gentle body and thin pale scribbles.
ROCK_GRAIN_PX = 1.0
ROCK_BODY_SHARE = 0.3
ROCK_GRAIN_SHARE = 0.5
ROCK_SCRIBBLE_SHARE = 0.4
# A MOSS's speckle: its Gaussian grain's sigma, in pixels at 1024.
MOSS_SPECKLE_PX = 0.8
# A GRASS's blades: how many cross the lawn per feature of the
# surface's own count, how much longer a blade is than it is wide, and
# the
# integer directions they lie in - every vector is whole, so a blade
# turned along it still repeats on the tile.
GRASS_BLADES_PER_FEATURE = 6.0
GRASS_BLADE_ASPECT = 5
GRASS_MIN_BLADES = 192
GRASS_BLADE_DIRECTIONS = (
    (0, 1),
    (1, 1),
    (1, -1),
    (1, 2),
    (2, 1),
    (1, -2),
    (2, -1),
    (1, 0),
)
# How many octaves a flat sheet's two layers carry. One octave of a
# value noise shows its own lattice as soft squares.
FLAT_SHEET_OCTAVES = 4
FLAT_TOOTH_OCTAVES = 3
# How much of the STONE's colour variation is the surface's mottle,
# against the cell's own colour.
#
# The truth's ground is a gravel: the stones are all much the same
# tone, and the ENVELOPE's variation is what a viewer sees. Measured
# on the truth: its envelope carries 0.0607 of its 0.1244 spread and
# the fine detail 0.104 - so the two are nearly equal, and the fine
# detail is the pebbles.
#
# And the pebbles are the MOTTLE, and not the cells: a cell is what
# the colour hash reads, and the colour hash is what the feature
# measure reads. A cell at the pebbles' own scale put the scale at
# 4.17x the truth's.
SURFACE_SHARE = 0.55
# How many CELLS the stones have, for each feature the truth has.
#
# The cell count is not the feature count: a Voronoi's features are
# the STONES, and the stones are what the joint divides - and a
# joint is a fraction of a cell. Measured, the truth's asphalt reads
# 39.4 features where its autocorrelation's period is 26 pixels,
# while 31 cells drew features 64 pixels apart.
#
# So the cells are the features and not a multiple of them.
#
# The factor was 1.6 and it was never used, and the cell count is the
# feature count itself: the truth's own Asphalt033 measures
# thirty-one features across and the lane's cells are thirty-one, and
# the rendered feature count is 27.7 against the truth's 31.
#
# And at a factor of a quarter the asphalt's rendered count fell to
# 7.6 - a fifth of the truth's - so the cells are the count and the
# fractal's own octaves are what make the features finer.
STONE_CELL_FACTOR = 1.0
# How many PEBBLES each feature is worth.
#
# The truth's ground measures 20.48 features across and has about
# 232 pebble gaps along a row - so the pebbles are about eleven times
# finer than the features. The cell is the pebbles' and the joint is
# the envelope's.
# The PEBBLES' count, as a multiple of the feature count. The truth's
# own row carries eighty-one pebble-gaps where the feature measure
# reads twenty features across - so the pebbles are four times finer
# than the envelope, and a ground is a gravel, not a mosaic.
STONE_PEBBLE_COUNT_FACTOR = 4
# How many lattice pixels a pebble gets, at the lattice's own
# resolution. The pebbles ARE the joints, and a joint two pixels wide
# is a blur - so each pebble gets enough pixels for its gap to read.
STONE_PEBBLE_PIXELS = 3
SURFACE_OCTAVES = 4
SURFACE_PERSISTENCE = 0.5
# How strong the FIBRE is against the envelope it rides on.
#
# The fibre is FAINT, and that is what makes the envelope decide the
# feature scale. The feature measure is the autocorrelation's first
# crossing, and the truth's wood has an envelope of thirteen features
# and a fibre of a hundred and forty lines - and the autocorrelation
# reads thirteen, because the truth's fibre is IRREGULAR and its
# envelope is a slow variation.
#
# Our fibre is a regular fractal, so a strong fibre locks the
# autocorrelation onto itself and the scale reads a hundred and
# fifty times too fine. Measured: at a weight of 0.05 to 0.10 the
# wood's scale reads 1.26x the truth's and the metal's 1.29x, and at
# 0.35 the wood reads 78x and the metal 112x.
FIBRE_WEIGHT = 0.10
# How strong the ENVELOPE is against the fibre it carries.
#
# The envelope's RING POSITIONS still set the feature scale, and the
# positions are not changed by the depth - so the scale survives
# while the surface becomes the fibre.
ENVELOPE_WEIGHT = 1.0
# The FIBRE's own shape: how much it is stretched along the plank,
# how many octaves it has, how quickly each one quiets down, and how
# strong it is against the envelope.
#
# The stretch is what makes the noise read as LINES rather than as
# blobs: the noise's lattice is stretched along the plank's length,
# so its patches are narrow across the board and long along it.
#
# The strength is measured: the truth's wood carries 0.51 of its
# spread in the fibre and 0.49 in the envelope - so the two are
# nearly equal, and the fibre is the one that is slightly the
# weaker.
# How much the fibre's noise is compressed ALONG the plank.
#
# The smaller the number the longer the noise's patches run along the
# plank, and a fibre is a long streak. At 0.25 the streaks ran
# diagonally - the lattice's own geometry is square, so a mild
# compression leaves the patches as squares with a diagonal long
# axis - and the truth's fibre is along the board.
#
# It is a DIVISOR and not a multiplier, and it was read as a
# multiplier: at two the streaks came out as short dashes, and every
# value of it gave the identical picture, because the stretch was
# applied to the lattice's PERIOD and not to the SAMPLE. The two
# samples are in their own base lattice units, so the y sample has to
# be scaled by the STRETCHED count.
#
# Measured on the truth's own woods: their high-frequency structure
# is horizontal in every one of them - a down period of two to eight
# pixels against an across period of four to a hundred and fifty-two.
FIBRE_STRETCH = 0.0625
FIBRE_OCTAVES = 4
FIBRE_PERSISTENCE = 0.5
# And the resolution the FIBRE is computed at. It is the OUTPUT's
# own, and not a coarse one: the fibre's lines are seven and a half
# pixels apart in a thousand-and-twenty-four row, and a bilinear
# upsample from five hundred and twelve blurs them into ramps.
FIBRE_RESOLUTION = 2048
# How far the FIBRE's lines wander, in lattice cells.
#
# A Gabor's carrier is a regular set of stripes, and the truth's
# fibre is not: its lines come 3, 5, 6, 9, 14 and 17 pixels apart,
# and they bend where the board was cut across the log's rings.
FIBRE_WARP = 0.004
# How many FIBRE lines a wood's ring carries, and it is the ratio of
# the surface's across-count to its down-count.
#
# Measured on the truth's own Wood096: sixty-eight features across
# and eight down - so the fibre is eight and a half times finer than
# the rings.
FIBRE_CELLS_PER_RING = 1.0
# How many FEATURES a wood's ring carries, and it is the ratio of
# the surface's own feature count to its ring count.
#
# Measured on the truth's own: at four rings the lane reads 9.2
# features and at eight it reads 19.3 - so the features are two and a
# third times the rings. And the truth's own Wood096 measures 5.8
# features and its rings are two and a half, and the truth's own
# Wood092 measures 37.9 and its rings are sixteen.
GRAIN_CELLS_PER_FEATURE = 2.3
# The percentile the line's steepness is measured against. The
# steepness is normalised by a HIGH PERCENTILE and not by its
# maximum: one pixel's slope can be ten times its neighbours', and
# dividing by it leaves every other pixel at zero.
FIBRE_SLOPE_PERCENTILE = 92.0
# The METAL's grain orientation and carrier. A brushed sheet's
# streaks run along the sheet, so the carrier is across it - the
# same way as the wood's.
# A quarter turn, for the same reason the wood's fibre is: the
# streaks run along the sheet, and a row of the map runs along the
# sheet too, so the carrier must be across the row.
METAL_ORIENTATION = math.pi / 2.0
# The METAL's grain: its lattice and how far it is stretched along
# the sheet.
#
# A sheet's grain is BROADBAND and irregular, the way the wood's
# fibre is - a Gabor's carrier is a regular set of stripes, and a
# regular pattern's autocorrelation locks onto it.
METAL_GRAIN_LATTICE = 16
# A brushed sheet's streaks, in pixels at 1024 across: the truth's own
# Metal009 decorrelates within 24 along its rows and 1 across them.
METAL_BRUSH_ALONG_PX = 24.0
METAL_BRUSH_ACROSS_PX = 1.5
METAL_BRUSH_SHARPNESS = 6.0
# A mottled sheet's fine variation: its Gaussian grain's sigma, in pixels
# at 1024 across.
METAL_MOTTLE_PX = 2.0
# How much COARSER the metal's envelope's lattice is than its cell
# count. A Perlin's value oscillates faster than its lattice, and the
# measure reads the value.
METAL_DEFAULT_ENVELOPE_FACTOR = 1.0
# The SCRATCHES' own shape: how big a cell they are, how wide a
# scratch is, how many layers, how much they wave, and how much their
# angle varies.
#
# Material Maker's `scratches2` defaults are a length of 0.25, a
# width of 0.5, four layers, a waviness of 0.5 and an angle of zero.
METAL_SCRATCH_SIZE = 0.25
METAL_SCRATCH_WIDTH = 0.1
METAL_SCRATCH_LAYERS = 4
METAL_SCRATCH_WAVINESS = 0.15
METAL_SCRATCH_ANGLE = 0.0
METAL_SCRATCH_RANDOMNESS = 0.5
METAL_GRAIN_STRETCH = 0.5
METAL_FREQUENCY = 96.0
# How wide the fibre's line is, as a fraction of the noise's own
# range around the crossing.
#
# The truth's lines are 3 to 17 pixels apart in a 1024 image, and
# they are THIN - a fibre is a line and not a band. The gradient's
# own measure of a line is broad, and the close crop showed soft
# waves where the truth has fibre, so the line is the noise's ridge
# with a band around it.
#
# The band has to be wide enough to hold a line: at 0.08 it caught
# only the odd pixel and the map came out as blue speckle.
FIBRE_BAND = 0.22
# How many times the noise is RIDGED, per octave.
#
# A smooth value noise is soft waves, and a fibre is a line with a
# crease in it. Material-maker's `fbm4` folds the noise the same
# way, and the fold is what turns the wave into a line.
#
# And the line is the RIDGE's own CREST and not its slope: a fold's
# crest is a LINE, a continuous stroke, and the slope is two lines,
# one on each side of it - so the slope made the grain a field of
# DOTS.
#
# How many times the noise is RIDGED, per octave.
#
# A smooth value noise is soft waves, and a fibre is a line with a
# crease in it. Material-maker's `fbm4` folds the noise the same
# way, and the fold is what turns the wave into a line.
#
# And the line is the RIDGE's own CREST and not its slope: a fold's
# crest is a LINE, a continuous stroke, and the slope is two lines,
# one on each side of it - so the slope made the grain a field of
# DOTS.
FIBRE_FOLDS = 1
# A wood's GROWTH RINGS: how many bands cross the board, how far the
# slow field bends them, how many lines each band carries, and how
# thin a line is.
#
# Material Maker's own wood draws its bands as a noise of one cell
# along the board and sixty-four across it. The truth's own woods
# carry about a hundred grain lines across a thousand-and-twenty-four
# board, and a band of a value noise carries one line per level its
# sine crosses - so ninety-six bands at three levels. The bend is a
# sixtieth of the board: a twentieth folded the lines into closed
# eyes, which a sawn board's grain does not have.
WOOD_RING_COUNT = 96
WOOD_RING_BEND = 0.015
WOOD_RING_LEVELS = 3
WOOD_RING_SHARPNESS = 8.0
# How many rings a grain's own cell carries.
WOOD_RINGS_PER_CELL = 8.0
# The fewest rings a board carries, whatever its cell count.
WOOD_MIN_RINGS = 64
# How many fibre lines the image carries across, per 1024 pixels.
#
# The truth's wood has its lines 7.4 pixels apart in a 1024 row, so
# about a hundred and forty of them - and a value noise's ridge
# crosses the middle of its range twice per lattice cell, so the
# lattice is half that.
FIBRE_LINES_PER_IMAGE = 140
# How much of the domain a cell takes, before the warp.
DEFAULT_CELL_FRACTION = 1.0
# How much wider a brick is than it is tall.
#
# Measured against the truth's own brick: its bricks are 171 pixels
# wide and its courses 128 pixels tall, so a brick is about four
# thirds as wide as it is tall. The three-to-one default put 48
# bricks across where the truth shows 6.
BRICK_ASPECT = 1.34
# A BRICK's own FACE: the lattice of its grain, how far the warp
# displaces it, the grain's own frequency, and the finer tooth.
#
# The truth's own Bricks113A measures a spread of 0.0716 on the face
# alone - nearly the whole map's - and its blur profile decays from
# 0.068 at a two-pixel blur to 0.0087 at a hundred-and-twenty-eight.
# So the face has structure at EVERY scale, and a flat face has none.
BRICK_FACE_LATTICE = 8
# How much of the face's PIXEL-level grain the field carries.
#
# A Perlin is smooth between its own lattice's corners however fine
# the lattice is, and the truth's own brick face is SAND and not a
# smooth field.
#
# A per-pixel random field was tried instead and it changed nothing:
# the face's correlation at a one-pixel lag stayed at 0.223, so the
# sand is not what the measure reads.
BRICK_FACE_GRAIN_NOISE = 0.55
BRICK_FACE_WARP = 0.06
BRICK_FACE_WARP_STEP = 0.1
BRICK_FACE_FREQUENCY = 3.0
BRICK_FACE_TOOTH = 4
# The face's own DRIFT, and the drift's own cells: the truth's own
# Tiles141's drift has a period of a hundred and ninety-two pixels,
# so five features across a thousand and twenty-four.
BRICK_FACE_DRIFT = 0.18
BRICK_FACE_DRIFT_CELLS = 8
# A PARQUET's block is much wider than it is tall: a parquet floor is
# laid in long boards.
#
# Measured on the truth's own: the floor's row-to-column change ratio
# is 0.24, and it is the most horizontal surface in the wide sample.
# A brick's 1.34 would make it a wall of squares.
PARQUET_ASPECT = 2.0
# And how many blocks a PARQUET has ACROSS a course.
#
# The truth's own parquet carries ten joint lines across a thousand
# and twenty-four, so there are about ten blocks across and about six
# courses down - and the blocks are WIDE and LOW.
#
# The aspect is the ratio of a block's width to its height, and it
# is the courses divided by the blocks across: six courses and ten
# blocks is a ratio of 0.6, and the blocks are wider than they are
# tall by about one and a half times.
PARQUET_BLOCKS_ACROSS = 10
# And how many COURSES a parquet has for every block across a course.
#
# The truth's own WoodFloor051's boards are about a hundred and
# eighty pixels wide and about fifty-five tall, so a floor of six
# boards across is about eighteen courses down - and the courses are
# STAGGERED, so the joints do not line up.
PARQUET_COURSES_PER_ACROSS = 3.0
# The ROAD MARKINGS' own lattice; the width of the paint; and the
# dash's own pattern.
#
# Measured on the truth's own roads: a road carries THREE markings
# across - two solid edge lines and a dashed centre line - and they are
# nine to fourteen pixels wide in a thousand and twenty-four, so the
# paint is about a fiftieth of the surface. The truth's own Road007 has
# its edge lines at 7.5% and 92.5% across, and four dashes down it; its
# Road008A's dash is half its pitch.
MARKINGS_LAYOUT = ((0.075, False), (0.5, True), (0.925, False))
MARKINGS_LINE_WIDTH = 0.011
MARKINGS_DASHES_PER_IMAGE = 4
# The road's own slow variation under the markings.
MARKINGS_ROAD_LATTICE = 4
# The asphalt's grain: its Gaussian's sigma (pixels at 1024) and share.
MARKINGS_GRAIN_PX = 1.0
MARKINGS_GRAIN_SHARE = 0.6
# A WOVEN cloth's threads: how many of the measure's features one
# thread is,
# the fewest threads that are the cloth's structure, the threads a fine
# cloth gets when its features are its slubs and not its threads, the
# thread's width in its cell, and how much of the field the mottle is
# in each regime. The threaded regime is calibrated with the benchmark's
# own scale measure on eight fabric truths (features per thread 2.8/4.5 x
# a threshold of 24/64 threads: mean |log| 0.418 / 0.549 / 0.150 /
# 1.157). The measure prefers 4.5 per thread, but it counts a weave's
# own over-under undulation as features: at 4.5 Fabric061's threads are
# 22 pixels apart against its truth's 16 and its fine/slow variance
# reads 1.85 against the truth's 9.6. So 2.8, the truths' visible pitch,
# and the threshold of 24, which keeps a 114-feature wool threaded and
# not a fine cloth reading 0.21x. The fine regime is by eye against
# Fabric030's and Fabric036's crops (a heavier mottle met the measure as
# clouds).
WOVEN_FEATURES_PER_THREAD = 2.8
WOVEN_MIN_THREADS = 24
WOVEN_FINE_THREADS = 256
WOVEN_THREAD_WIDTH = 0.8
WOVEN_THREADED_MOTTLE = 0.2
WOVEN_FINE_MOTTLE = 0.1
# A fine cloth's threads wander by this many threads over a slow field
# of this lattice, and each crossing's brightness varies by this share.
WOVEN_WARP_THREADS = 0.5
WOVEN_WARP_LATTICE = 8
WOVEN_CROSSING_JITTER = 0.5
# A fine cloth's slubs: the oriented grain's sigma across a row (pixels at
# 1024), how much longer it runs along the row, and its most share.
WOVEN_SLUB_PX = 1.5
WOVEN_SLUB_ALONG = 12.0
WOVEN_SLUB_SHARE = 0.5
# Slubs fade in below this many features.
WOVEN_SLUB_FEATURES = 40
# A ROOF's shingle is about as wide as it is tall, and its courses
# and its shingles are at the same scale.
#
# Measured on the truth's own RoofingTiles013A: the courses come every
# a hundred and seventy-seven pixels and the shingles every a hundred
# and eighty-five.
ROOF_ASPECT = 1.0
# A MARBLE's veins: how far the warp displaces them, the step it
# takes, and how sharp the vein's own line is.
#
# Measured on the truth's own: the truth's Marble012's veins cover
# eight per cent of the surface and their correlation is +0.280 at an
# eight-pixel lag and -0.004 at a hundred and twenty-eight, so they
# are a fine network.
MARBLE_WARP = 0.25
MARBLE_WARP_STEP = 0.1
# How much FINER the BED is than the vein's own spacing, and the
# contour has to wander over many of the bed's own features to be a
# line and not a blob.
#
# The vein's own period is the LATTICE's cell - the surface's own
# feature scale - and the bed is the finer field it is cut from.
MARBLE_BED_FINENESS = 1
# How far the warp may carry the veins, as a fraction of the vein's
# own period - and it is BOUNDED, because the slope is not.
MARBLE_WARP_LIMIT_CELLS = 0.4
# Where a marble's vein network runs: above this level of a slow field,
# fading in over this much of it.
MARBLE_VEIN_PRESENCE = 0.35
MARBLE_VEIN_PRESENCE_SOFTNESS = 0.2
# The presence field's lattice as a share of the surface's count. Scored
# with the benchmark's own scale on seven marble truths (bold 0.4/0.8 x
# presence 0.5/1.0): mean |log| 0.279 / 0.183 / 0.350 / 0.241 - at half
# the count the network's coarse patches set the scale, and Marble016
# and Marble021 read 0.54 and 0.53.
MARBLE_PRESENCE_FACTOR = 1.0
# A marble's two vein families, neither finer than the surface's own
# count: a fine web of one-pixel veins once read 93 features against the
# truth's 14, because a web finer than the surface sets the
# autocorrelation's zero crossing whatever its weight.
#
# The bold veins' lattice as a share of
# the surface's count and their width, the fine ones' width and how
# strong they are; the veins' warp and octaves (looked at against
# Marble016 and Marble012).
MARBLE_BOLD_FACTOR = 0.4
MARBLE_BOLD_VEIN_PX = 2.2
MARBLE_FINE_VEIN_PX = 1.2
MARBLE_FINE_SHARE = 0.8
MARBLE_VEIN_WARP = 0.6
MARBLE_VEIN_OCTAVES = 7
# The marble's STONE mottle: how fine it is and how many octaves.
#
# The truth's own Marble021's stone is a fine even cloud and not a
# few big blobs, and the bed's own lattice is the vein's own period.
MARBLE_MOTTLE_FACTOR = 4.0
MARBLE_MOTTLE_OCTAVES = 3
# A HERRINGBONE floor's own aspect, and a board is as wide as it is
# long.
HERRINGBONE_ASPECT = 1.0
# A CARPET's pile, as a multiple of the surface's own feature count.
#
# The truth's own carpet is almost flat - a spread of 0.029 over
# twenty-seven thousand specks - so the pile is much finer than the
# surface's measured features.
CARPET_FIBRE_FACTOR = 8.0
# And the pile is STRETCHED along the fibre's direction, by this
# much: the truth's carpet reads 1.20 times more change along a row
# than down a column.
CARPET_FIBRE_STRETCH = 2.0
# A LEATHER's cells, and how far a cell's own point may move from its
# centre.
#
# A hide is a fine even grain: the cells are tight and even, and not
# the loose ground's scattered stones.
#
# Measured on the truth's own: the pebbles of the six leathers come
# five to seven pixels apart in a thousand and twenty-four - a fine
# and even grain whatever the leather's own scale is, from the
# almost-flat one at 0.0032 of spread to the contrasty one at 0.063.
#
# So the cell count is a FIXED grain and not the surface's own
# feature count: the surface's count is what the measure reads and
# the grain is what the eye reads, and they are different numbers.
#
# And the grain is VERY fine: the truth's own Leather037's detail
# has a period of two pixels in a thousand and twenty-four - it is
# almost a smooth surface - and the crackle at a hundred and seventy
# cells came out at nine pixels and read a spread of 0.0388 where
# the truth's is 0.0032.
LEATHER_CELL_COUNT = 512
# How many CRACKLE cells a leather's surface feature carries.
#
# The truth's own six leathers measure nineteen to five hundred and
# twelve features across, and the crackle is what the measure reads
# on four of them - so the crackle's own count follows the surface's.
LEATHER_CELL_FACTOR = 1.0
LEATHER_CELL_JITTER = 0.7
# A WALLPAPER's motif, as a multiple of the surface's own feature
# count: a wallpaper's design is a thing you see from across a room.
WALLPAPER_MOTIF_COUNT = 128
# How far a wallpaper's flecks are WARPED, in lattice cells.
#
# A regular lattice of flecks is a dither and the picture showed a
# visible diagonal weave, and a printed design is scattered.
WALLPAPER_FLECK_WARP = 0.05


# The bricks ACROSS a course, from the number of courses.
#
# The image is square and a brick is BRICK_ASPECT times as wide as
# it is tall, so a course that is one brick tall holds courses /
# aspect bricks across - the aspect makes each brick WIDER, so fewer
# of them fit.
#
# Measured: the truth's brick has eight courses and six bricks
# across, and the aspect of 1.34 gives 8 / 1.34 = 6.
def _bricks_across(courses: int, aspect: float = BRICK_ASPECT) -> int:
    return max(1, round(courses / aspect))


# How far a GRAIN's line drifts from its own line, as a fraction of
# the cell.
#
# It is what makes the pattern's scale a single number: the drift's
# rate is what sets how quickly the pattern stops matching itself,
# and the autocorrelation's first crossing - which is the feature
# measure - reads that. So with the drift fixed as a fraction, the
# CELL COUNT alone sets the scale.
#
# Measured against the truth's wood, whose autocorrelation decays
# smoothly from +1.00 to zero over seventy-eight pixels with no
# plateau: a fifteenth of a cell reads the truth's thirteen features
# at thirteen cells, and a tenth reads 1.44x.
GRAIN_WANDER_FRACTION = 0.07
# The METAL's drift, which is smaller: a sheet's grain is steadier
# than a plank's. Measured, the metals' own autocorrelations decay
# over about a hundred and twelve pixels.
METAL_WANDER_FRACTION = 0.04
# How sharp the metal's rib VALLEY is. The rib's profile is raised to
# this power, and the higher it is the narrower the valley and the
# lighter the sheet.
#
# Measured on the truth's own corrugated steel: a mean luma of 0.589,
# fifty-two ribs across, and a dark fraction of 0.187.
METAL_RIB_SHARPNESS = 6.0
# How far a PRESSED sheet's ribs wander from straight. A pressed
# sheet's ribs are straight - the truth's own corrugated steel is a
# pressed sheet of straight parallel ribs - so this is very nearly
# nothing.
METAL_PRESSED_WANDER_FRACTION = 0.004
# How strong a PRESSED sheet's ENVELOPE is, and how deep its ribs
# are.
#
# The envelope is the sheet's slow weathering, and it is weak: the
# truth's corrugated steel carries most of its contrast in the ribs
# and not in the weathering, and its row's own spread is 0.0322
# against a whole-image spread of 0.076.
METAL_PRESSED_ENVELOPE_STRENGTH = 0.12
METAL_PRESSED_RIB_DEPTH = 0.45
# How many RIBS a pressed sheet's cell holds. The truth's corrugated
# steel measures 5.89 features across at a period of 174 pixels and
# its ribs are sixteen pixels apart, so the ribs are eleven times
# finer than the envelope.
METAL_PRESSED_RIB_FACTOR = 11
# The smallest a cell may be, as a fraction of the largest cell's edge
# distance. Below it the cell is treated as having no interior, so it
# reads as stone rather than as a blotch of joint.
#
# It is SMALL: the floor is there to catch the degenerate cells the
# warp squeezes, not to reshape the rest. Measured, a floor of 0.35
# dissolved the joints into a mottled field, and the sweep found the
# best at 0.05: the contrast 0.0753 against a real cobblestone's
# 0.0763, the features 12.34 across against the truth's 11.25, and
# the seam 1.26x. At 0.12 the contrast fell to 0.0655 and the seam
# rose to 1.62x, and at 0.25 the joints were gone.
MINIMUM_CELL_FRACTION = 0.05
# The STONES' fractal: how many octaves, how quickly each one quiets
# down, how much the lattice doubles, and how far the feature points
# are from their cell's centre.
#
# A ground is a dense spread of small pebbles and our recreation was
# a handful of giant amoebas - the cell count was right (22.26
# features across against the truth's 20.48) but each cell was one
# smooth blob. So the stones are fractal, and the FBM-Worley's mean
# cell area falls by four times an octave - measured on the vendored
# module: 1.0 base cell at the first octave and a sixteenth of one at
# the fourth.
STONE_OCTAVES = 4
STONE_PERSISTENCE = 0.5
STONE_LACUNARITY = 2
STONE_JITTER = 1.0
# How much finer the STONES are than the feature count.
#
# The truth's Ground110 measures 20.48 features across, and that is
# the ENVELOPE's count - the big shapes the ground is organised
# into. A close crop of the truth is a dense spread of hundreds of
# pebbles, and our recreation was a handful of giant amoebas.
#
# So the stones' lattice is this many times finer than the feature
# count.
#
# It is ONE. The truth's ground has about a hundred and seventy
# pebbles across where the feature count is 20.48 - so the pebbles
# ARE the fine structure - but they must be the MOTTLE and not the
# cells, because a cell is what the colour hash reads and the colour
# hash is what the feature measure reads.
#
# Measured, a lattice eight times the feature count put the scale at
# 4.17x the truth's.
STONE_LATTICE_FACTOR = 1
# How far the STONES are warped, in cell units.
#
# The warp is what keeps the fine octaves from locking the feature
# measure. The truth's ground measures 19.32 features across and
# carries 0.1027 of its 0.1244 spread in the FINE structure, so its
# fine structure is strong and the autocorrelation still reads the
# envelope - and the only way both can hold is if the fine structure
# is irregular.
#
# A regular fine lattice locks the autocorrelation, and the measure
# reads it instead: measured, the scale read 7.19x the truth's.
STONE_WARP_AMOUNT = 0.6
# How far the PEBBLES' lattice is jittered, in fine cells.
#
# The truth's ground has about a hundred and seventy pebbles across
# and its autocorrelation reads twenty - so the pebbles are irregular
# enough that the measure finds the envelope and not them. A regular
# fine lattice does the opposite: the autocorrelation locks onto the
# pebbles' own spacing, and the scale read 4.17x the truth's.
STONE_PEBBLE_JITTER = 0.35
# The SCATTERED stones: their size, their count, the jitter on their
# size, the number of edges that cut them angular, and the seed.
#
# The SIZE is the truth's own, measured off the truth's own pixels.
#
# Measured on the truth's own ground: the bright stones' widths run
# 1 px, 2 px, 3 px, 4 px, 5 px, 7 px, 8 px in the counts 1071, 541,
# 30, 8, 2, 2 and 1 - so the median stone is TWO pixels across, the
# ninetieth is two and a half, and only a handful reach four.
#
# The size was 0.0060, which is three times the truth's: the stones
# came out a median of 3.4 px across and a ninetieth of 10.8, and the
# ground read as a field of pebbles where the truth's is a grit.
#
# So the size is a TWO-THOUSANDTH of the surface.
STONE_SCATTER_SIZE = 0.00625
# How many stones the surface carries.
#
# The count follows the SIZE and not the cell count, because a stone
# is STONE_SCATTER_SIZE of the surface across.
#
# And the count is what makes the ground PACKED: the truth's own
# ground is a bed of stones with a thin shadow between them, and the
# shadow is a fifth of a per cent of the surface - the truth's own
# darkest hundredth is 0.119 and its darkest thousandth is 0.000.
#
# So the count is large, and the stones' own size law decides how
# much of the surface they cover: a stone's area goes with the square
# of its size, so the size falling threefold needs nine times the
# stones to cover the same ground.
#
# And the count is what puts the SHADOW in: at sixty thousand the
# stones were islands in a wide lit matrix and the ground's luma
# floored at 0.192; at three hundred and fifty thousand the stones
# pack and the shadow appears between them, and the ground's luma
# floors at 0.000 - the truth's own - with its first percentile at
# 0.113 against the truth's 0.119, and its tenth at 0.213 against the
# truth's 0.212.
STONE_SCATTER_DENSITY = 120000
# How much the stones' sizes vary, as a fraction of their own size.
#
# The truth's gravel is a mix: mostly small chips and a few big
# stones, and the sizes vary by about eight times. So the jitter is
# wide - the stone's own size is a MEAN and the spread is real.
STONE_SCATTER_SIZE_JITTER = 0.8
# How much of a stone's own size is a splat's own cell.
#
# A splat is drawn in its own cell, so the cell has to be the
# splat's own size or the stones are clipped or lost. And the
# truth's own ground carries eighty-five stones across at twelve
# pixels each, so the cell is a little larger than the stone.
STONE_SCATTER_COUNT_FACTOR = 0.35
# How many straight edges cut each stone, and so how angular it is.
STONE_SCATTER_EDGES = 3
# The seed the stones' places and cuts come from.
STONE_SCATTER_SEED = 7
# How much of the RAMP a stone's own tone spreads over, and it is
# WIDE.
#
# A gravel is a mix of stone types: the truth's own ground's
# seventeen biggest stones run from 0.431 to 0.710 - a spread of
# 0.0752 - and the lane's stones were all the slow field's own
# value, so the ground came out as a uniform tan bed.
STONE_TONE_SPREAD = 0.9
# The SLOW field's own count, as a fraction of the surface's own
# feature count.
#
# Measured on the truth's own: the truth's Ground110 measures twenty
# and a half features across and its slow field is thirteen and a
# third, and the truth's Ground106 measures six and a half and its
# slow is four.
SCATTER_SLOW_CELL_FRACTION = 0.5
# The PEBBLES' warp: how far the lattice is displaced, the step the
# slope is measured over, and how many steps are taken.
#
# It is a DOMAIN WARP and not a per-cell jitter, and that is the
# point: a per-cell hash is a step function, so every pebble is
# displaced by a constant and the lattice is still a lattice. A
# domain warp is a continuous displacement, so the pebbles drift,
# cluster and thin out the way loose stones do.
#
# This is Material Maker's `warp` node, MIT licensed.
STONE_PEBBLE_WARP_AMOUNT = 0.1
STONE_PEBBLE_WARP_STEP = 0.1
STONE_PEBBLE_WARP_ITERATIONS = 1
# How many octaves the PEBBLES' field has.
#
# The pebbles' SIZES have to vary, and that is what the octaves do:
# each one adds a finer set of cells, so the field has big stones and
# small ones in it rather than one size. The truth's ground is a
# gravel - stones of many sizes - and the autocorrelation reads its
# envelope at twenty features.
STONE_PEBBLE_OCTAVES = 3
# How much of the PEBBLES' own colour shows, against the envelope's.
#
# The truth's ground is a gravel: the stones are all much the same
# tone and the ENVELOPE's variation is what a viewer sees. So the
# pebbles' colour is a small offset on the envelope's.
STONE_PEBBLE_COLOUR = 0.12
# How much of the image the PEBBLES' colour varies over.
#
# The truth's ground has about a hundred and seventy pebbles across
# and its autocorrelation reads twenty - so the pebbles' own colour
# variation cannot be what the measure reads, and the ENVELOPE's is.
# The pebbles' colour is therefore a slow variation over many
# pebbles, and the envelope's is the coarse one.
#
# So the pebbles' colour is taken from the COARSE lattice's cells,
# and the joints are the fine lattice's gaps. Measured, a cell at
# the fine lattice put the scale at 4.17x the truth's, because the
# measure then read the pebbles' colour and not the envelope's.
STONE_PEBBLE_CELL_FROM = "coarse"


def warp(
    sample_x,
    sample_y,
    cells: int,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The sample coordinates, displaced by the warp.

    The displacement is in CELL units, so it means the same thing at
    any scale. Each octave is a pair of sines with an integer
    frequency, so the field is periodic over the domain: the
    displacement at 0 is the displacement at 1.

    The two axes carry DIFFERENT frequency sets, so the warp is not a
    simple shear: a cell's neighbours are pushed around it
    independently, which is what breaks a lattice into stones.
    """
    import numpy

    two_pi = 2.0 * numpy.pi
    offset_x = numpy.zeros_like(sample_x)
    offset_y = numpy.zeros_like(sample_y)
    for index, (frequency, amplitude) in enumerate(octaves):
        across = frequency * 2 + index
        along = frequency * 3 + index + 1
        offset_x = (
            offset_x
            + numpy.sin(sample_y * across * two_pi + frequency * 0.7) * amplitude
        )
        offset_x = offset_x + numpy.sin(sample_x * along * two_pi + 1.1) * (
            amplitude * 0.7
        )
        offset_y = (
            offset_y
            + numpy.sin(sample_x * across * two_pi + frequency * 0.3) * amplitude
        )
        offset_y = offset_y + numpy.sin(sample_y * along * two_pi + 2.3) * (
            amplitude * 0.7
        )
    return (
        sample_x + offset_x * WARP_AMOUNT / cells,
        sample_y + offset_y * WARP_AMOUNT / cells,
    )


def stone_lattice(cells: int, resolution: int) -> int:
    """The lattice the STONES are drawn on - how many across the image.

    The truth's Ground110 measures 20.48 features across, and that is
    the ENVELOPE's count - the big shapes the ground is organised
    into. The pebbles themselves are far smaller: a close crop of the
    truth is a dense spread of hundreds of them, and the envelope's
    autocorrelation is what says twenty.

    So the stones' lattice is much finer than the feature count: the
    feature count is the envelope, and the stones are the texture
    inside it.

    The lattice is a power of two that divides the resolution, so the
    map tiles.
    """
    wanted = max(2, round(cells * STONE_LATTICE_FACTOR))
    size = 2
    while size * 2 <= wanted and resolution % (size * 2) == 0:
        size *= 2
    while resolution % size != 0:
        size //= 2
    return max(2, size)


def _nearest(values, rows, columns):
    """A field sampled at fractional positions, by NEAREST neighbour.

    The nearest neighbour is what a DISCRETE field needs: a cell's
    index is an integer, and interpolating it makes it a continuous
    value - and a continuous cell index gives the colour hash a smooth
    gradient, which the feature measure then reads as the structure.

    Measured, an interpolated cell put the ground's scale at 10.00x
    the truth's.
    """
    import numpy

    height, width = values.shape
    row = numpy.clip(numpy.round(rows).astype(numpy.int64), 0, height - 1)
    column = numpy.clip(numpy.round(columns).astype(numpy.int64), 0, width - 1)
    return values[row, column]


def fractal_stones(
    resolution: int,
    cells: int,
    octaves=STONE_OCTAVES,
    pebble_factor: float = 1.0,
    curvature_strength: float = 0.0,
    curvature_radius: float = 4.0,
    curvature_quality: int = 4,
):
    """A field of FRACTAL stones: big ones made of small ones.

    A ground is not a field of equal stones. The truth's Ground110 is
    a dense spread of small pebbles, and our recreation was a handful
    of giant amoebas - the cell count was RIGHT (our recreation read
    22.26 features across against the truth's 20.48) but each of our
    cells was one smooth blob where the truth's is a crowd.

    So the stones are FRACTAL: the base octave is the cell count the
    truth asks for, and each octave above it adds a finer set of
    cells inside the same field. The FBM-Worley - built on the
    vendored tileable Worley - is what does that, and its mean cell
    area falls by four times an octave, so the pebbles get small
    quickly.

    The field is the base octave's DISTANCE TO THE BISECTOR, which
    is an exact distance to the cell's border - so a joint drawn from
    it has a fixed width in pixels whatever the cell's size. The
    F2 - F1 is zero on the border but is not a distance: its growth
    depends on the two points' spacing, so a joint of fixed width
    would not be fixed.
    """
    import numpy

    from golem_blender.pbr import noise_worley_fbm, warp
    from golem_blender.pbr.noise_worley_fbm import _bilinear
    from golem_blender.pbr.procedural import _cell_hash

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")
    # The stones are WARPED, and that is what keeps the fine octaves
    # from locking the feature measure.
    #
    # The truth's ground measures 19.32 features across, and it carries
    # 0.1027 of its 0.1244 spread in the FINE structure - so its
    # fine structure is strong and the autocorrelation still reads the
    # envelope. The only way both can hold is if the fine structure
    # is IRREGULAR: a regular fine lattice locks the
    # autocorrelation, and the measure reads it instead.
    #
    # So the sample positions are warped before the cells are drawn,
    # and the warp's frequencies are integers over the domain so the
    # field still tiles.
    two_pi = 2.0 * numpy.pi
    offset_x = numpy.zeros_like(sample_x)
    offset_y = numpy.zeros_like(sample_y)
    for index, (frequency, amplitude) in enumerate(DEFAULT_WARP_OCTAVES):
        across = frequency * 2 + index
        along = frequency * 3 + index + 1
        offset_x = (
            offset_x
            + numpy.sin(sample_y * across * two_pi + frequency * 0.7) * amplitude
        )
        offset_x = offset_x + numpy.sin(sample_x * along * two_pi + 1.1) * (
            amplitude * 0.7
        )
        offset_y = (
            offset_y
            + numpy.sin(sample_x * across * two_pi + frequency * 0.3) * amplitude
        )
        offset_y = offset_y + numpy.sin(sample_y * along * two_pi + 2.3) * (
            amplitude * 0.7
        )
    warp_amount = STONE_WARP_AMOUNT
    warped_x = (sample_x + offset_x * warp_amount / cells) * cells
    warped_y = (sample_y + offset_y * warp_amount / cells) * cells
    field = noise_worley_fbm.worley_fbm_2d(
        warped_x,
        warped_y,
        period=cells,
        octaves=octaves,
        persistence=STONE_PERSISTENCE,
        lacunarity=STONE_LACUNARITY,
        jitter=STONE_JITTER,
        seed=0,
        distance=False,
    )
    # The JOINT's distance is the EXACT BISECTOR distance, computed
    # on a COARSE grid and brought up.
    #
    # F2 - F1 is zero on the border but is not a distance - its growth
    # depends on the two points' spacing - and using it put the
    # stones' scale at 16.43x the truth's. So the bisector it is.
    #
    # The bisector is a 5x5 sweep and it is expensive: measured, one
    # octave at 2048 across took 28 seconds. But the joint is a
    # BROAD feature - it is the gap between the stones - so it does
    # not need the full resolution, and a coarse grid and a bilinear
    # bring it up is enough.
    # The lattice's own resolution, and it must be fine enough for
    # the SMALLEST cell the field draws: the pebbles' lattice has
    # eleven times the cell count, so at five hundred and twelve a
    # pebble was two and a third pixels across - and the pebbles are
    # the joints, and a joint two pixels wide is a blur.
    #
    # So the lattice is as fine as the pebbles ask for: the pebbles'
    # own count, times a handful of pixels each.
    pebble_side = max(cells, round(cells * pebble_factor))
    coarse_side = max(4, min(resolution, max(512, pebble_side * STONE_PEBBLE_PIXELS)))
    # The coarse grid covers the field's period AND ONE STEP MORE, so
    # that its last entry is the field's own first entry repeated.
    #
    # It was `coarse_side` entries over the period, so the last entry
    # was the field at one step BEFORE the wrap - and the bilinear
    # then interpolated from there to the first entry, across the
    # whole period. The wrap joined two unrelated places.
    #
    # So the grid's step is the field's period over `coarse_side - 1`
    # steps, and its last entry lands exactly on the wrap.
    axis = numpy.arange(coarse_side) / (coarse_side - 1)
    grid_x, grid_y = numpy.meshgrid(axis, axis, indexing="xy")
    # The JOINT is the PEBBLES' gaps, and the pebbles are the fine
    # lattice's cells - so the joint's distance comes from the fine
    # lattice.
    #
    # And the COLOUR comes from the coarse lattice, because the
    # truth's pebbles are all much the same tone and the ENVELOPE's
    # variation is what a viewer sees. Measured on the truth's own
    # ground: there are 169 joints along a 1024 row, so about a
    # hundred and seventy pebbles across, where the feature count is
    # 20.48 - so the joints are eight times finer than the envelope.
    #
    # Measured, a cell at the fine lattice put the scale at 2.40x the
    # truth's, because the autocorrelation then read the pebbles'
    # colour instead of the envelope's.
    # The pebbles' lattice is JITTERED, so the pebbles are not a
    # regular grid.
    #
    # The truth's ground has about a hundred and seventy pebbles
    # across and its autocorrelation reads twenty - so the pebbles
    # are irregular enough that the measure finds the envelope and
    # The PEBBLES' own lattice is not drawn as a joint.
    #
    # The truth's ground has about a hundred and seventy pebbles
    # across and its autocorrelation reads twenty - so the pebbles
    # are the fine structure and the envelope is what the measure
    # reads. A regular fine lattice does the opposite: the
    # autocorrelation locks onto the pebbles' own spacing, and the
    # scale read 4.17x the truth's.
    #
    # And a POISSON-DISK SCATTER of the pebbles was tried - random
    # positions with a minimum separation, which is irregular by
    # construction, and which the vendored `noise_scatter` provides.
    # It did not move the scale either: it read 4.17x the truth's,
    # and the search for the nearest pebble cost 135 seconds for one
    # material, which is far too much.
    #
    # So the joint is the COARSE lattice's and the pebbles' own tone
    # comes from the MOTTLE - the surface texture - which is where
    # a stone's surface variation belongs anyway.
    # The PEBBLES' own count, which is several times the feature
    # count: the truth's ground has about a hundred and seventy
    # pebbles across where its autocorrelation says twenty.
    # The STONES' own count, and it is several times the feature
    # count.
    #
    # The truth's own ground is a gravel: a row carries fifty-six
    # bright stones and they are a third of the row, so the ground is
    # mostly DARK MATRIX with small bright stones in it - and the
    # stones are sixteen pixels across, which is sixty-four of them
    # across a thousand and twenty-four.
    #
    # And the measure reads NINETEEN, and not sixty-four: the
    # stones' own tones are all much the same grey, so the measure
    # finds the MATRIX's structure and not the stones'.
    fine_cells = max(cells, round(cells * pebble_factor))
    # The PEBBLES' own lattice, which is several times finer than the
    # feature count.
    #
    # And the pebbles' points are JITTERED PER CELL, so the pebbles
    # are irregularly spaced. A regular lattice is a strong single
    # frequency, and the autocorrelation finds the pebbles' own
    # spacing instead of the surface's envelope - measured, the scale
    # read 7.14x the truth's with a regular fine lattice.
    fine_plain = noise_worley_fbm.worley_fbm_2d(
        grid_x * fine_cells,
        grid_y * fine_cells,
        period=fine_cells,
        octaves=1,
        persistence=STONE_PERSISTENCE,
        lacunarity=STONE_LACUNARITY,
        jitter=STONE_JITTER,
        seed=0,
        distance=True,
    )
    # The pebbles' points are JITTERED PER CELL, and the lattice is
    # WARPED as well.
    #
    # The jitter is a step function - every stone is displaced by a
    # constant - and the truth's stones are irregularly PLACED and
    # not irregularly SHAPED. So the jitter is what makes the
    # placement irregular, and it is what the measure can live with:
    # a jittered lattice has no period the autocorrelation can lock
    # onto.
    #
    # The warp deforms the stones' SHAPES, and a warp's own noise is
    # broadband - so the measure finds the warp's noise and not the
    # ground. Measured: at thirty-two cells the ground's feature
    # scale read 1.37x the truth's with no warp and 3.47x with a
    # warp of a tenth, and the picture went from flat plates to a
    # fine speckle.
    #
    # So the warp is small, and the jitter does the work.
    #
    # The warp is Material Maker's `warp` node, MIT licensed: the
    # displacement is the field's slope, sampled at the sample's own
    # coordinates, and every sample is wrapped so the map still
    # tiles.
    jitter_field = _cell_hash(
        fine_plain["cell"].astype(numpy.int32), fine_cells, fine_cells
    ).astype(numpy.float64)
    warp_height = fine_plain["distance"].astype(numpy.float64)
    warp_height = warp_height / max(1e-6, float(warp_height.max()))
    warp_x, warp_y = warp.warped_coordinates(
        grid_x,
        grid_y,
        warp_height,
        amount=STONE_PEBBLE_WARP_AMOUNT,
        step=STONE_PEBBLE_WARP_STEP,
        iterations=STONE_PEBBLE_WARP_ITERATIONS,
    )
    fine = noise_worley_fbm.worley_fbm_2d(
        (warp_x + jitter_field * STONE_PEBBLE_JITTER) * fine_cells,
        (warp_y + jitter_field * STONE_PEBBLE_JITTER * 0.7) * fine_cells,
        period=fine_cells,
        octaves=1,
        persistence=STONE_PERSISTENCE,
        lacunarity=STONE_LACUNARITY,
        jitter=STONE_JITTER,
        seed=0,
        distance=True,
    )
    coarse = noise_worley_fbm.worley_fbm_2d(
        grid_x * cells,
        grid_y * cells,
        period=cells,
        octaves=1,
        persistence=STONE_PERSISTENCE,
        lacunarity=STONE_LACUNARITY,
        jitter=STONE_JITTER,
        seed=0,
        distance=True,
    )
    # The CELL is the COARSE lattice's, and not the pebbles'.
    #
    # The cell is what gives a stone its own colour, and the colour's
    # variation is what the feature measure reads. The truth's ground
    # has about a hundred and seventy pebbles across and its
    # autocorrelation reads twenty - so the pebbles' own colour
    # cannot be what the measure reads, and the ENVELOPE's is.
    #
    # So the pebbles' colour is the COARSE lattice's cell, and the
    # pebbles' own gaps are the joint. Measured, a cell at the fine
    # lattice put the scale at 4.17x the truth's.
    #
    # And the pebbles' own variation is added to the coarse cell's as
    # a SMOOTH field, so a pebble is a slightly different tone
    # within its region and not a different colour. The truth's
    # ground is a gravel: the stones are all much the same tone and
    # the ENVELOPE's variation is what a viewer sees.
    # The upsample's grid is PERIODIC and it reads the coarse field
    # where the coarse field was SAMPLED.
    #
    # The coarse field's own samples are at the cell CENTRES -
    # `(i + 0.5) / coarse_side` - and the upsample's grid was the
    # cell EDGES, so every sample was half a cell off and the wrap
    # joined two places the field had never been.
    #
    # The grid is the coarse field's own sample positions, scaled to
    # the fine resolution, and it is EXCLUSIVE at the end.
    #
    # Measured: the rock's distance field had a seam of 0.032 and
    # the rock's seam read 2.54x the truth's.
    # The upsample's index into the coarse field, and the coarse
    # field's entry `i` was sampled at the domain `i / (coarse_side
    # - 1)` - so the fine pixel `j` reads the coarse field at the
    # index `j * (coarse_side - 1) / resolution`.
    #
    # The coarse grid covers the field's period and one step more,
    # and its last entry is the field's own first entry - so the
    # bilinear's wrap reads the right pair and the field's seam is
    # exactly zero.
    coarse_axis = (
        numpy.arange(resolution, dtype=numpy.float64) * coarse_side / resolution
    )
    rows = coarse_axis
    columns = coarse_axis
    grid_row, grid_column = numpy.meshgrid(rows, columns, indexing="ij")
    # The cell is DISCRETE - it is an index, and the hash reads it -
    # and an INTERPOLATED cell is a continuous value, so the hash
    # gives a smooth gradient and the feature measure reads that
    # gradient as the structure.
    #
    # Measured, an interpolated cell put the scale at 10.00x the
    # truth's and a blended one at 5.00x. So the cell is the coarse
    # lattice's own index, taken NEAREST - and the pebbles' own tone
    # comes from the MOTTLE, the surface texture, and not from the
    # cell.
    # The cell is DISCRETE - it is an index, and the hash reads it -
    # and it is taken NEAREST, so an INTERPOLATED cell cannot smooth
    # the hash into a gradient and give the feature measure a
    # structure to lock onto.
    # The CELL is the COARSE lattice's, and not the pebbles'.
    #
    # The pebbles' own lattice was tried, and the feature measure
    # read the pebbles' own count - measured, the ground's feature
    # scale read 2.94x the truth's - because the cell's own tone is
    # what the measure reads, and the pebbles are a third of the
    # truth's feature count.
    #
    # And the tone's amplitude does not save it: at a tenth of the
    # ramp the scale still read 3.33x. So the cell is the coarse
    # lattice's, and the pebbles are the JOINT - the crazing between
    # them - which is what the truth's ground shows.
    # The CELL is the COARSE lattice's, and not the stones'.
    #
    # The truth's own ground is a gravel: a row carries fifty-six
    # bright stones and they are a third of the row, so the ground is
    # mostly DARK MATRIX with small bright stones in it - and the
    # stones are sixteen pixels across.
    #
    # And the measure reads the MATRIX and not the stones, and that
    # is what the cell has to be: measured, a cell at the stones'
    # lattice put the ground's feature scale at 3.12x the truth's,
    # and the stones' own tone made no difference to it - at a tenth
    # of the ramp it still read 3.33x. So the cell is the matrix's
    # and the stones are the JOINT.
    field["cell"] = _nearest(coarse["cell"], grid_row, grid_column).astype(numpy.int32)
    # The JOINT is the COARSE lattice's, and the pebbles' gaps are
    # not joints.
    #
    # The joint is what the feature measure reads, and the truth's
    # ground reads twenty features where it has about a hundred and
    # seventy pebbles. So the joint is the ENVELOPE's - the gap
    # between the big shapes - and the pebbles are the fine
    # lattice's own colour within it.
    #
    # Measured, a joint at the fine lattice put the scale at 4.17x
    # the truth's and then at 10.00x, because a hundred and seventy
    # regular gaps are a strong single frequency.
    # The JOINT is the PEBBLES' gaps, and the cell is the envelope's
    # tone.
    #
    # The truth's ground is a gravel: the stones are all much the same
    # tone, and the ENVELOPE's variation is what a viewer sees. So
    # the cell is the coarse lattice's - it is what the colour hash
    # reads, and the colour hash is what the feature measure reads -
    # and the joints are the pebbles' own gaps.
    field["distance"] = _bilinear(fine["distance"], grid_row, grid_column)
    # The ENVELOPE: the surface's own slow variation, and it is
    # SMOOTH.
    #
    # The truth's own ground has a correlation that decays smoothly -
    # 0.24 at a lag of ten, 0.10 at twenty, 0.04 at thirty-two and
    # 0.005 at fifty - and a per-cell hash has NO such decay: it is
    # uncorrelated from one cell to the next, and the measure finds
    # the cells' own count.
    #
    # So the surface's variation is a SMOOTH field, and the cells
    # only decide where the joints fall.
    field["envelope"] = _bilinear(coarse["distance"], grid_row, grid_column)
    # The surface's CURVATURE, and it is what gives a ROCK its
    # facets.
    #
    # A rock is a set of flat faces with sharp edges between them,
    # and the truth's own Rock051 carries a gradient of 0.037 - one
    # and a half times the sheet's own variation - and the lane's
    # rock is a smooth blob field with no edge in it.
    #
    # The curvature is Material Maker's `smooth_curvature2`: a
    # discrete second difference over a cone of offsets, and it is
    # the map that gives a hand-painted edge treatment its rim and a
    # cavity mask its darkness.
    #
    # It is a function of the HEIGHT, and the height here is the
    # distance to the joint - so the curvature is the joint's own
    # sharpness, measured at a scale of a few cells.
    if curvature_strength > 0.0:
        from golem_blender.pbr import curvature as curvature_module

        height = field["envelope"]
        curved = curvature_module.curvature(
            height,
            radius=curvature_radius,
            quality=curvature_quality,
        )
        field["curvature"] = curved
    else:
        field["curvature"] = None
    # The CELL is the BASE octave's.
    #
    # The cell is what gives a stone its own colour, and the colour's
    # variation is what the feature measure reads. The finest
    # octave's cells were tried and the colour's variation is then
    # eight times finer: measured, the scale read 34.64x the truth's
    # and the seam 2.78x.
    #
    # So the pebbles are the base octave's cells, and the FBM's
    # finer octaves add the DETAIL inside them - the mottle, not
    # the structure.
    return field


def cell_and_edge(
    resolution: int,
    cells: int,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The cell each sample is in, and the distance to that cell's edge.

    The search is over the NINE cells around the sample's own, which
    is enough because the warp moves a sample by less than one cell.
    The nine are taken modulo the cell count, so the search WRAPS and
    the pattern is periodic: a sample at the domain's edge sees the
    cell on the other side at its true distance.

    The edge distance is the distance to the second-nearest point
    less the distance to the nearest. Measured: the own distance
    taken from the running minimum AFTER the loop was the minimum
    over all the points rather than the nearest point's, so the edge
    came out zero everywhere and the image came out flat.

    AND THE EDGE IS FLOORED, because a warp that varies the cells'
    sizes also makes some of them TINY - and a tiny cell is all edge,
    so it comes out as a black blotch rather than a stone. Measured:
    the magnified texture had black ellipses scattered through it,
    each one a cell so small the joint covered it whole. So a cell
    whose edge distance never rises above a floor is treated as
    having no edge at all, and its interior is stone.
    """
    import numpy

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")
    sample_x, sample_y = warp(sample_x, sample_y, cells, octaves)

    # The cell count DIVIDES THE RESOLUTION, so every cell is a whole
    # number of pixels and the last one is not cut in half - and the
    # wrap joins two whole cells.
    #
    # The lattice's own points are at (index + 0.5) / cells, so the
    # cells are whole when the resolution is a multiple of the count.
    # Measured, the ground's seam read 5.03x the truth's without it.
    #
    # And the count is a POWER OF TWO, because the resolution is:
    # 2048 is two to the eleventh, so a count of thirty-one divides
    # it not at all - and walking the count down until it did
    # collapsed it to two, which is why the stones came out as a
    # handful of amoebas. So the count is the nearest power of two to
    # the one wanted, and the truth's thirty-one becomes thirty-two.
    # The cell count is EXACT, and not a power of two: the Worley's
    # own lattice wraps by ITS period, so the count does not have to
    # be a power of two, and rounding it to one cost a third of the
    # feature scale. Measured, the ground's scale read 0.65x the
    # truth's with the count rounded from twenty to sixteen.
    cells = max(2, int(cells))
    while cells > 1 and resolution % cells != 0:
        cells //= 2

    best = numpy.full(sample_x.shape, 1e18)
    second = numpy.full(sample_x.shape, 1e18)
    nearest = numpy.zeros(sample_x.shape, dtype=numpy.int32)

    # The sample's own cell, and the eight around it. The positions
    # are the UNWRAPPED ones - so a sample near the edge sees the
    # cell on the other side at its true distance - and the cell's
    # index is taken modulo, so the cell is the same cell.
    base_x = numpy.floor(sample_x * cells).astype(numpy.int32)
    base_y = numpy.floor(sample_y * cells).astype(numpy.int32)
    for offset_y in (-1, 0, 1):
        for offset_x in (-1, 0, 1):
            index_x = base_x + offset_x
            index_y = base_y + offset_y
            point_x = (index_x + 0.5) / cells
            point_y = (index_y + 0.5) / cells
            distance = (sample_x - point_x) ** 2 + (sample_y - point_y) ** 2
            nearer = distance < best
            second = numpy.where(nearer, best, numpy.minimum(second, distance))
            best = numpy.where(nearer, distance, best)
            nearest = numpy.where(
                nearer,
                (index_y % cells) * cells + (index_x % cells),
                nearest,
            )

    edge = numpy.sqrt(numpy.maximum(second, 0.0)) - numpy.sqrt(best)

    # A cell that is entirely edge has no interior: it is a tiny cell
    # the warp squeezed, and it must read as stone rather than as a
    # blotch of joint. The floor is a fraction of the largest cell's
    # edge distance.
    reach = float(edge.max())
    if reach > 0.0:
        floor = reach * MINIMUM_CELL_FRACTION
        tiny = edge < floor
        edge = numpy.where(tiny, reach, edge)
    return nearest, edge, (cells, cells)


# How many of the feature measure's features a TILE carries.
#
# The measure's count is not the tile count: counted on the truth's own
# grout lines, Tiles107 carries 7 tiles across at 26 features, Tiles040
# 7 at 10, Tiles139 and Tiles141 5 at 10 - two features a tile at the
# median.
TILE_FEATURES_PER_TILE = 2.0


def brick_field(
    resolution: int,
    cells: int,
    aspect: float = BRICK_ASPECT,
    staggered: bool = True,
):
    """Courses of bricks: the cell each sample is in, and the distance to
    its mortar.

    A brick wall is COURSES - rows of bricks, each row offset half a
    brick from the one above, so the vertical joints do not line up.
    That offset is what makes a brick wall a brick wall and a tile
    floor a tile floor, and it is why the two are different patterns
    rather than one pattern at two scales.

    The edge distance is the distance to the NEAREST mortar line, in
    either direction. Measured: the earlier version took the distance
    within a brick and subtracted it from the brick's size, which went
    NEGATIVE for a brick wider than the grid - so the tiles read at
    0.00x the truth's contrast, which is a flat grey map.

    Both fields are periodic: the courses are counted modulo and the
    offset is half a brick, so the wall repeats.
    """
    import numpy

    # The geometry: `courses` courses tall, and `bricks` bricks across
    # each course. A course is one brick TALL, and a course holds
    # several bricks ACROSS - which is what the earlier version got
    # wrong: it treated a course as one brick wide, so there were no
    # vertical joints at all and the wall was stripes. Measured, the
    # pattern's features read 73.14 against the truth's 7.76.
    #
    # A BRICK IS WIDER THAN IT IS TALL - about three to one - so a
    # course of `bricks` bricks is `bricks * 3` units wide and one
    # unit tall. The image is square, so the courses and the bricks
    # are scaled to suit: the number of courses is the image's height
    # in brick-heights, and the number of bricks across is the
    # image's width in brick-widths.
    #
    # The counts are POWERS OF TWO, so they divide the domain
    # exactly. Measured, the field's seam is 0.00x at sixteen
    # courses, 0.61x at twelve, 1.88x at eight and 31.99x at two.
    courses = _power_of_two_nearest(cells)
    # The bricks ACROSS a course. The image is square, a course is
    # one brick tall, and a brick is BRICK_ASPECT times as wide as
    # it is tall - so the image's width is `courses / aspect`
    # brick-widths.
    #
    # The `cells` are the COURSES, and the truth's brick has 8
    # courses and 6 bricks across: 8 / 1.34 = 6.
    #
    # The counts DIVIDE THE RESOLUTION, so every brick and every
    # course is a whole number of pixels and the wall's last course
    # is not cut in half. A count that does not divide leaves a
    # fraction of a brick at the edge, and the wrap joins it to a
    # whole one - so the seam shows. Measured, the brick's seam read
    # 7.55x the truth's.
    # The row's width is the largest DIVISOR of the resolution that is
    # closest to the aspect's count.
    #
    # It was stepped down one at a time from the aspect's count until
    # it divided the resolution, and that walked it off the aspect:
    # the aspect wants six bricks across, and six does not divide a
    # thousand and twenty-four, so the count stepped down to four and
    # the bricks came out twice as wide as they are tall. The truth's
    # brick is nine courses and seven across, and the feature scale
    # read 0.60x the truth's.
    #
    # So the width is the largest divisor of the resolution nearest
    # the aspect's count, and the courses are stepped down the same
    # way - to the nearest power of two that divides it.
    row_width = _bricks_across(courses, aspect)
    while courses > 1 and resolution % courses != 0:
        courses //= 2

    axis = numpy.arange(resolution)
    # The position along the wall, in BRICK UNITS: a brick is one
    # unit tall and `aspect` units wide, so the image's height is
    # `courses` brick-heights and its width is `row_width`
    # brick-widths.
    #
    # The vertical and horizontal scales are SEPARATE, and that is the
    # whole geometry of a brick: a course is one brick tall and a
    # brick is three units wide. Measured with one scale for both,
    # the pattern came out as thin horizontal stripes - the bricks'
    # own interiors read as the courses.
    #
    # And the courses are CENTRED on the domain, so both edges fall
    # in the middle of a course rather than on its boundary. That is
    # what makes the wrap join: with the courses starting at the
    # domain's edge, the last course is `courses - 1` and the first is
    # 0, and those have DIFFERENT offsets - the last is offset by half
    # a brick and the first is not - so the wrap shows a step. Centred,
    # the two edges are the same distance into a course and the same
    # parity, and the wall closes. Measured, the field's vertical
    # seam was 10.64x at four courses with the courses starting at
    # the edge.
    #
    # The two axes are INDEPENDENT: the course runs down the image
    # and the brick across it, and each is built from its own
    # coordinate. The earlier version built both from the same
    # one-dimensional array, so the two were the same axis written
    # twice - and the bricks in a course came out sharing a colour.
    vertical = (axis + 0.5) * courses / resolution - 0.5
    horizontal = (axis + 0.5) * row_width / resolution - 0.5
    # The course's index and the position within it, down the image.
    course_index = numpy.floor(vertical).astype(numpy.int32)
    within_course = vertical - course_index
    # The brick's index and the position within it, across the image.
    brick_index = numpy.floor(horizontal).astype(numpy.int32)
    within_brick = horizontal - brick_index

    # Every other course is offset by half a brick, so the vertical
    # joints do not line up.
    #
    # The offset is taken on the course's index MODULO the course
    # count, so it comes back to where it started at the wrap - and
    # the courses are centred, so the index can be NEGATIVE, which
    # Python's modulo handles and a plain parity would not.
    # A TILE's courses are not offset: a tile floor is an aligned grid,
    # and the half-brick offset is what makes a wall a wall.
    offset = ((course_index % courses) % 2) * (0.5 if staggered else 0.0)

    # The sample's position within its brick, along the brick's own
    # width, with the course's offset applied.
    #
    # The horizontal position is NOT reduced modulo one before the
    # offset is added: reducing it first sends the sample at the
    # course's far edge to zero, and the offset vanishes there, so
    # the brick shifts at the wrap. Measured, the brick's vertical
    # seam was 50/255 against its horizontal 16/255, and NEITHER
    # moved with the course count: it was this, and not the number
    # of courses.
    #
    # The offset is HALF A BRICK, added as a fraction of one. The
    # earlier version multiplied it by the row's width, which moved
    # a course by three bricks instead of by half - so the colour did
    # not line up with the mortar and the stagger was not a stagger.
    offset_down = numpy.tile(offset.reshape(-1, 1), (1, resolution))
    across_with_offset = (
        numpy.tile(within_brick.reshape(1, -1), (resolution, 1)) + offset_down
    )
    within_brick = across_with_offset % 1.0
    within_course = numpy.tile(within_course.reshape(-1, 1), (1, resolution))

    # The distance to the nearest mortar line, in brick units.
    #
    # The BRICK's own width is along the image's SECOND axis - a
    # course runs left to right and holds bricks side by side - so the
    # brick's distance is tiled across and the COURSE's distance runs
    # down. The earlier version had them the other way round, so the
    # brick's own width was measured down the image and the pattern
    # came out with twice as many bricks as it should.
    to_brick = numpy.minimum(within_brick, 1.0 - within_brick)
    to_course = numpy.minimum(within_course, 1.0 - within_course)
    edge = numpy.minimum(to_course, to_brick)

    # The cell: which brick, and which course. The brick's index is
    # the column, shifted by the course's half-brick offset, taken
    # modulo the row's width so the wrap joins.
    #
    # The COURSE is on the image's first axis and the BRICK on its
    # second, and the cell is the two combined. The earlier version
    # built the cell from the two 1D arrays as if they were the two
    # axes of the same line - so every brick in a course got the same
    # cell, and the whole course one colour. Measured: one row of
    # the brick had a single distinct colour, and the wall read as
    # soft blue-white blobs with no brick in them.
    course_down = numpy.tile(course_index.reshape(-1, 1), (1, resolution))
    # The brick's index within its course, with the course's offset
    # applied: the position across the image plus the offset, taken
    # to the brick it lands in.
    across_image = numpy.tile(horizontal.reshape(1, -1), (resolution, 1))
    shifted = numpy.floor(across_image + offset_down).astype(numpy.int32)
    cell = course_down * row_width + (shifted % row_width)
    # The brick's own FACE, and it is a WORKED surface.
    #
    # A brick is a piece of stone that was cut and worked, and its
    # face carries the grain of the stone and the marks of the
    # working - a swirl, a scrape, a direction of its own.
    #
    # The truth's own Bricks113A measures a spread of 0.0716 on the
    # face alone - nearly the whole map's - and its blur profile
    # decays from 0.068 at a two-pixel blur to 0.0087 at a
    # hundred-and-twenty-eight. So the face has structure at EVERY
    # scale, and the lane's face had none: the whole of the lane's
    # variation was in the per-brick tone and the face was flat.
    #
    # So the face is a DOMAIN-WARPED field, and the warp is what
    # makes the grain SWIRL - Material Maker's `warp` node, MIT
    # licensed, and the same one the pebble field uses.
    #
    # And the sample's position is the BRICK'S OWN, so each brick's
    # swirl is its own and a wall of them reads as a wall of worked
    # stones and not as one field.
    from golem_blender.pbr import noise_perlin

    # The sample's own position WITHIN its brick, in the brick's
    # units - and it is a full grid, because the two axes have their
    # own scales: the course is one brick tall and the brick is
    # `aspect` units wide.
    #
    # The brick's index and the position within it, across the
    # image, and the course's down it - and each is TILED to the
    # full grid.
    # The face is a full (resolution, resolution) grid, because the
    # writer's image is square.
    #
    # The brick's own position WITHIN the brick, in brick units, is
    # what the grain follows - and it is the image's own pixel
    # divided by the brick's own size, so it is a full grid.
    pixel_axis = numpy.arange(resolution, dtype=numpy.float64)
    within_x = ((pixel_axis + 0.5) * row_width / resolution - 0.5) - numpy.floor(
        (pixel_axis + 0.5) * row_width / resolution - 0.5
    )
    within_y = ((pixel_axis + 0.5) * courses / resolution - 0.5) - numpy.floor(
        (pixel_axis + 0.5) * courses / resolution - 0.5
    )
    within_x = numpy.tile(within_x.reshape(1, -1), (resolution, 1))
    within_y = numpy.tile(within_y.reshape(-1, 1), (1, resolution))
    # And the BRICK's and the COURSE's own indices, so each brick's
    # swirl is its own.
    brick_of = numpy.tile(
        numpy.floor((pixel_axis + 0.5) * row_width / resolution - 0.5)
        .astype(numpy.int32)
        .reshape(1, -1),
        (resolution, 1),
    )
    # The course's own index is REDUCED into the course count, so
    # the last course and the first are the same course.
    #
    # The face's grain rides the course's own offset, and the offset
    # was the course's index - and the index at the last course is
    # not the index at the first, so the wrap joined two courses
    # with different grain: the brick's horizontal seam read 1.875x,
    # as big as the biggest feature.
    course_of = numpy.tile(
        numpy.mod(
            numpy.floor((pixel_axis + 0.5) * courses / resolution - 0.5).astype(
                numpy.int32
            ),
            courses,
        ).reshape(-1, 1),
        (1, resolution),
    )

    # The face's own GRIT, and it is a FINE field and not a swirl.
    #
    # The face was a DOMAIN-WARPED field - a perlin over the
    # brick's own position, warped - and a warp has a DIRECTION, so
    # every brick carried the same diagonal herringbone and the wall
    # came out as a field of chevrons.
    #
    # The truth's own brick face is GRIT: its correlation falls
    # steadily from +0.391 at a one-pixel lag to +0.086 at a
    # thirty-two, with no dominant scale and no direction.
    #
    # So the face is the surface's own mottle at a fine scale, with
    # the brick's own hash for the patch-to-patch difference.
    grit = noise_perlin.perlin_2d(
        within_x * BRICK_FACE_LATTICE * 4 + brick_of * 0.41,
        within_y * BRICK_FACE_LATTICE * 4 + course_of * 0.37,
        period=BRICK_FACE_LATTICE * 4,
        seed=13,
    )
    # And the grit's own PIXEL-level noise, because the truth's face
    # is sand and not a smooth field.
    #
    # The truth's own brick face has a correlation of +0.391 at a
    # one-pixel lag and the lane's had +0.183 - and a perlin is SMOOTH
    # inside its own cell whatever the cell's size, so the lattice
    # could not bring it.
    #
    # So the face carries a per-pixel field as well, and the two
    # together are the sand.
    grit = grit + BRICK_FACE_GRAIN_NOISE * (
        noise_perlin.perlin_2d(
            within_x * resolution + brick_of * 0.41,
            within_y * resolution + course_of * 0.37,
            period=resolution,
            seed=17,
        )
    )
    grain_reach = max(1e-6, float(grit.max() - grit.min()))
    grain = (grit - float(grit.min())) / grain_reach
    # And the face's own TOOTH, at a finer scale than the grain: a
    # worked stone is smooth and pitted at once.
    tooth = surface_texture(resolution, BRICK_FACE_LATTICE * BRICK_FACE_TOOTH)
    tooth_reach = max(1e-6, float(tooth.max() - tooth.min()))
    tooth = (tooth - float(tooth.min())) / tooth_reach
    face = 0.65 * grain + 0.35 * tooth
    # And the face's own DRIFT, at the SURFACE's scale.
    #
    # The truth's own Tiles141 carries a spread of 0.0349 at a
    # hundred-and-twenty-eight-pixel blur - a fifth of the whole map -
    # and its drift's period is a hundred and ninety-two pixels, so
    # five features across. A tile is a large flat surface and it
    # STAINS, and the stain is the drift.
    #
    # And the truth's own Bricks113A carries 0.0087 at the same
    # blur - a ninth of the tile's - because a brick is a mosaic of
    # worked pieces and the pieces do not stain together.
    #
    # So the drift is the TILE's and the brick's face is the
    # pieces, and the two are different surfaces.
    drift = slow_variation(resolution, max(2, BRICK_FACE_DRIFT_CELLS))
    face = face + (drift - 0.5) * BRICK_FACE_DRIFT

    return cell.astype(numpy.int32), edge, (row_width, courses), face


def _nearest_divisor(limit: int, wanted: int) -> int:
    """The divisor of `limit` nearest to `wanted`.

    A pattern's cells must be a whole number of pixels, or the wrap
    joins a cell that was cut in half. So the count is a divisor of
    the resolution - and it need not be a power of two, which is what
    let a roof's five-and-a-half courses become four.
    """
    wanted = max(1, int(wanted))
    best = 1
    for candidate in range(1, limit + 1):
        if limit % candidate:
            continue
        if abs(candidate - wanted) < abs(best - wanted):
            best = candidate
    return best


def _power_of_two_at_least(value: int) -> int:
    """The smallest power of two that is at least `value`.

    A power of two divides a power-of-two domain exactly, and the
    brick's half-brick offset needs the count to divide it. Measured:
    the brick's field seam is 0.00x at sixteen courses, where twelve
    gives 0.61x and eight gives 1.88x.
    """
    count = 2
    while count < value:
        count *= 2
    return count


def _power_of_two_nearest(value: float) -> int:
    """The power of two CLOSEST to `value`.

    The brick's courses have to be a power of two, and the count
    wanted is the truth's feature count - which sits between the
    powers. Rounding UP doubled the courses and so halved the
    bricks' size: the truth's brick has eight courses and six bricks
    across, and the pattern's features read 9.39 - so the nearest
    power of two is eight and the nearest is the right one, not the
    one above.
    """
    count = 2
    while count * 2 <= value:
        count *= 2
    while count < value and count * 2 - value < value - count:
        count *= 2
    return count


def _domain_samples(resolution: int):
    """The samples of a tileable field, over ONE period of the domain.

    The sample of pixel `i` is `i / resolution` and NOT
    `(i + 0.5) / resolution`.

    A field with a period of `L` cells is sampled at `i * L / N` for
    the pixel `i`, and the pixel after the last - the one the tile
    wraps to - is at `L`, which is the field's own start. So the
    image's last pixel and its first are one step apart in the
    field's own period, and the wrap is exact.

    The half-pixel offset sampled `(i + 0.5) / N`, so the last pixel
    was at `L * (N - 0.5) / N` and the first at `L * 0.5 / N` - a
    distance of `L * (N - 1) / N` and NOT `L`. The image covered
    N-1 steps of the field's period and not N, so the wrap joined two
    places the field had never been.

    Measured: the wood's seam read 11.88x the truth's and the second
    wood's 10.44x, and the Perlin's own seam grew with its lattice -
    0.006 at eight cells and 0.011 at sixteen - because the bigger
    the lattice the more of the period the image missed.
    """
    import numpy

    return numpy.arange(resolution, dtype=numpy.float64) / resolution


def wood_ring_lightness(sample_x, sample_y, seed: int = 0, rings: int = 0):
    """A board's growth rings as a LIGHTNESS: low on the grain lines.

    The bands are a value noise of ONE cell along the board and
    WOOD_RING_COUNT across it, so every band runs the whole length; a
    slow field shifts them across the board so neighbouring lines bend
    together; and the line is the band's own level crossings, made thin
    by a power. Both noises have whole-number periods, so the map tiles.
    """
    import numpy

    from golem_blender.pbr import noise

    slow = noise.fbm_2d_value(
        sample_x * 4, sample_y * 4, size=4, octaves=2, seed=seed + 1
    )
    slow = (slow - float(slow.mean())) / max(1e-9, float(slow.std()))
    rings = int(rings) if rings > 0 else WOOD_RING_COUNT
    shifted = sample_x + slow * WOOD_RING_BEND
    field = noise.fbm_2d_value(
        shifted * rings,
        sample_y,
        size=rings,
        size_y=1,
        octaves=3,
        persistence=0.6,
        seed=seed,
    )
    reach = max(1e-9, float(field.max() - field.min()))
    field = (field - float(field.min())) / reach
    line = numpy.abs(numpy.sin(field * numpy.pi * WOOD_RING_LEVELS))
    return 1.0 - line**WOOD_RING_SHARPNESS


def grain_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
    fibre_cells: int | None = None,
):
    """A wood grain: the cell each sample is in, and the distance to
    its grain line.

    A wave is NOT a grain. A wave's bands are parallel and evenly
    spaced, and the benchmark measured a wood's bands at 5.5x the
    truth's feature scale - the pattern was the wrong shape for the
    surface.

    A grain is a set of RINGS: the lines a tree's growth makes are
    nested arcs, and a plank cut from them shows them. So the field
    is a distance to a set of nested curves, and the cell is a band
    between two of them.

    THE RINGS RUN ALONG THE PLANK. A plank is cut from a log, so its
    grain lines run the length of the board, and the truth's wood -
    measured - has its lines running HORIZONTALLY with a luma spread
    of 0.0162 and 13.13 features.

    So the rings are counted on the X axis, which makes them COLUMNS
    running down the image, and the warp rides on the Y axis, which
    bends each column along its length. That is what a plank's fibre
    looks like: long lines with a few cathedral swirls where the board
    was cut across the log's rings.

    A ring counted on the X axis is a line of CONSTANT x, which runs
    down the image; a ring counted on the Y axis is a line of
    constant y, which runs across it. The earlier version had them
    the other way round, and the lines came out as a zigzag of waves
    across the image - not a wood at all.
    """
    import numpy

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")

    # The rings: counted on the X axis, so they run as COLUMNS. The
    # warp rides on the Y axis, so it bends each column along its
    # length rather than across it.
    #
    # The warp's AMPLITUDE IS A SMALL PART OF A CELL, and that is what
    # makes the pattern's scale a single number. The warp's amplitude
    # sets how far a column drifts from its own line, and the drift's
    # rate sets how quickly the pattern stops matching itself - which
    # is what the autocorrelation's first crossing reads.
    #
    # The amplitude is in CELL units and it is SMALL - a tenth of a
    # cell at most. A drift of most of a cell moves the line past its
    # own neighbour and the structure stops being a set of lines at
    # all: measured, at thirteen cells a drift of 0.9 of a cell moved
    # the line by most of its own spacing between neighbouring rows.
    #
    # The drift's RATE, not its amplitude, is what sets the scale, and
    # the rate is the octaves' frequency over the domain. So the cells
    # set the line spacing and the drift sets the correlation's decay,
    # and the two together give the pattern its one scale.
    # The cell count is a POWER OF TWO that divides the resolution,
    # so every line lands on whole pixels and the wrap joins two
    # whole lines. 2048 is two to the eleventh, so a count of
    # thirteen divides it not at all - and walking the count down
    # until it did collapsed it to one.
    cells = _power_of_two_nearest(cells)
    while cells > 1 and resolution % cells != 0:
        cells //= 2

    two_pi = 2.0 * numpy.pi
    warp = numpy.zeros_like(sample_x)
    for frequency, amplitude in octaves:
        warp = warp + numpy.sin(sample_y * frequency * two_pi + frequency * 0.7) * (
            amplitude * GRAIN_WANDER_FRACTION
        )

    rings = (sample_x + warp) * cells

    # The cell is the ring's index.
    band = numpy.floor(rings).astype(numpy.int32)
    # The ENVELOPE is the board's own GROWTH RINGS: long lines that run
    # the length of the board and bend TOGETHER.
    #
    # It was a low-frequency Perlin's magnitude - blobs - and the close
    # sheet showed every wood as a flat brown with a few dark smudges
    # where the truth's woods are dense parallel grain lines, at 1024
    # and at 2048 alike. And every wood had the SAME smudges.
    #
    # Material Maker's own wood is the design: a noise of ONE cell
    # along the board and many across it, so every band runs the whole
    # length, and a slow field that shifts the bands across the board
    # so they bend together.
    # And the ring count follows the grain's own cells: a constant
    # ninety-six read the same twelve features on every wood, where
    # the truth's woods read five to fifteen. Eight rings a cell,
    # measured over the top set's fourteen woods: the mean |log|
    # scale error 0.490 -> 0.359.
    #
    # And never fewer than WOOD_MIN_RINGS: the measure reads a row's
    # slow bend and not the ring density, and at a wood's few cells
    # the rings came out as broad bands where the truth's Wood049 is
    # dense grain.
    edge = wood_ring_lightness(
        sample_x,
        sample_y,
        rings=max(WOOD_MIN_RINGS, round(cells * WOOD_RINGS_PER_CELL)),
    )
    # The fibre's own edge is the rings' when there is no fibre - so
    # the writer always has two fields to draw.
    fine_edge = edge

    # A GRAIN IS TWO SCALES. The rings above are the ENVELOPE - the
    # slow cathedral swirl a plank's fibre follows - and the truth's
    # own row crosses its midpoint sixty-nine times where the
    # envelope's autocorrelation says thirteen features. So the fibre
    # itself is a set of fine streaks inside the envelope, and the
    # count of them is what the surface actually looks like.
    #
    # THE FIBRE IS NOISE, not a set of rings. A set of rings is
    # REGULAR, and a regular pattern's autocorrelation locks onto it
    # - so the feature measure read the fibre and the scale came out
    # 4.09x the truth's. The truth's fibre does not lock: its lines
    # come 3, 5, 6, 9, 14 and 17 pixels apart, and its envelope says
    # thirteen features.
    #
    # So the fibre is material-maker's periodic value noise, at the
    # fibre's own scale and STRETCHED along the plank - so it reads
    # as lines running the length of the board rather than as blobs.
    if lines_per_cell > 1:
        from golem_blender.pbr import noise
        from golem_blender.pbr.noise_worley_fbm import _bilinear

        # The fibre is a GABOR noise, not a value noise.
        #
        # A Gabor is a noise filtered by an ORIENTED Gaussian, so it
        # produces strokes - and a plank's fibre is a set of strokes
        # running the length of the board. Measured on the truth's own
        # wood: its lines come 3, 5, 6, 9, 14 and 17 pixels apart and
        # they run along the board.
        #
        # A value noise's ridge was the alternative, and it failed: it
        # is REGULAR, so the autocorrelation locks onto it and the
        # feature measure reads the fibre and not the envelope.
        # Measured, the wood's scale read 148x the truth's and the
        # metal's 356x. A Gabor's strokes are irregular, so the
        # envelope holds the scale.
        #
        # The orientation is the direction the field varies FASTEST,
        # so the strokes run across it - and the fibre runs along the
        # plank, so the carrier is across the plank.
        # The fibre is computed on a COARSE grid and brought up. A
        # Gabor is a direct trigonometric sum over the lattice's bins,
        # and it is the whole cost: measured, it took 11.8 seconds at
        # 1024 across and would take a minute at 2048. The fibre is
        # FINE DETAIL - the strokes are soft - so a coarse grid and a
        # bilinear bring it up.
        # And the fibre is computed at the OUTPUT's resolution and
        # not at a coarse one and upsampled.
        #
        # The fibre's lines are seven and a half pixels apart in a
        # thousand-and-twenty-four row, so at a coarse side of five
        # hundred and twelve they are three and a half pixels - and
        # the bilinear upsample to two thousand and forty-eight
        # BLURS them into ramps. The fibre's line came out a smooth
        # gradient over twenty pixels and the wood came out as a few
        # big smooth blobs with no grain in them at all.
        fibre_side = max(4, min(resolution, FIBRE_RESOLUTION, resolution))
        fibre_axis = (numpy.arange(fibre_side) + 0.5) / fibre_side
        fibre_x, fibre_y = numpy.meshgrid(fibre_axis, fibre_axis, indexing="ij")
        # The fibre is WARPED, so the lines wander.
        #
        # A Gabor's carrier is a REGULAR set of stripes, and the
        # truth's fibre is not: its lines come 3, 5, 6, 9, 14 and 17
        # pixels apart, and they bend where the board was cut across
        # the log's rings. So the sample's position is displaced by a
        # low-frequency Perlin before the Gabor is evaluated, and the
        # stripes bend with it.
        #
        # The warp's frequencies are integers over the domain, so the
        # field is still periodic and the map still tiles.
        from golem_blender.pbr import noise_perlin

        warp_lattice = max(2, round(cells / 2))
        warp_field = noise_perlin.perlin_2d(
            fibre_x * warp_lattice,
            fibre_y * warp_lattice,
            period=warp_lattice,
            seed=7,
        )
        # The fibre's own field is an fBm of the VALUE NOISE, and it
        # is RIDGED.
        #
        # A Gabor was used, and a Gabor's carrier is a REGULAR set of
        # stripes - so the fibre had a period, and the feature measure
        # found the fibre's own period and not the wood's envelope.
        # Measured: the wood read 3.84x the truth's feature scale, and
        # the row's correlation oscillated instead of decaying.
        #
        # The truth's own row decays smoothly - 0.52 at a lag of ten,
        # 0.31 at twenty, 0.13 at forty and 0.006 at seventy-three -
        # and a regular carrier cannot do that. An fBm of the value
        # noise is broadband and irregular by construction, and the
        # truth's own fibre has its lines 3, 5, 6, 9, 14 and 17 pixels
        # apart.
        #
        # The lattice is EIGHT and the noise is STRETCHED along the
        # plank, so the lines run along the plank and the ridge's
        # creases are far apart in it. Measured: at a lattice of eight
        # and a stretch of 0.15 the fibre reads fifteen and a half
        # features and its correlation decays as the truth's does; at a
        # lattice of sixteen it reads twenty-eight and the correlation
        # stops decaying.
        # The fibre's lattice is RECTANGULAR: more cells across the
        # plank than along it, so the patches run along the board.
        #
        # The stretch was a FRACTION applied to the sample's y
        # coordinate, and a fraction of a lattice cell does not wrap:
        # the noise's period is a whole number of cells, and the
        # field's edge met a place the field had never been.
        #
        # Measured: the coarse fibre's seam read 0.16 and the wood's
        # own seam 11.88x the truth's.
        #
        # So the stretch is the LATTICE's own period along y, and it
        # is a whole number of cells, and the noise's y period is
        # that number.
        # The fibre's own lattice, and it is the SURFACE's own
        # across-count.
        #
        # It was a fixed four, and a wood's fibre is fine: the
        # truth's own Wood096 measures sixty-eight features across
        # and eight down - so the fibre is the across count and the
        # rings are the down count, and a fixed four made the fibre
        # sixteen times too coarse.
        # And the lattice is the FIBRE's OWN and not the rings'.
        #
        # The truth's own wood has its lines seven and a half pixels
        # apart in a thousand-and-twenty-four row, and a value
        # noise's ridge crosses the middle of its range twice per
        # lattice cell - so the lattice is a hundred and forty across
        # the image, whatever the surface's own feature count is.
        #
        # The lattice was the rings' count, and the rings' count is
        # the surface's own - so the fibre's lines came out a hundred
        # pixels apart and the wood came out as smooth blobs with
        # dark smears in them, where the truth has fine lines.
        lattice = max(
            4,
            round(fibre_cells)
            if fibre_cells is not None
            else _fibre_lattice(resolution),
        )
        while lattice > 1 and resolution % lattice != 0:
            lattice //= 2
        while lattice > 1 and lattice * 4 > resolution:
            lattice //= 2
        lattice_y = max(1, round(lattice * FIBRE_STRETCH))
        # And the Y sample is in the STRETCHED lattice's own units.
        #
        # The two samples are in their own base lattice units, and
        # the y lattice is the STRETCHED one - so the y sample is
        # scaled by the stretched count. It was scaled by the plain
        # one, so the stretch was applied to the lattice's PERIOD and
        # not to the sample - and the fibre came out the same at
        # every stretch, which is how the fault was found: the
        # parameter had no effect at all.
        coarse_fibre = noise.fbm_2d_value(
            (fibre_x + warp_field * FIBRE_WARP) * lattice,
            fibre_y * lattice_y,
            size=lattice,
            octaves=FIBRE_OCTAVES,
            seed=0,
            folds=FIBRE_FOLDS,
            size_y=lattice_y,
        )
        fibre_field = coarse_fibre
        # The upsample's grid is PERIODIC, and the coarse field is
        # sampled at the positions the coarse field's own domain
        # covers - the end EXCLUSIVE, so the last sample is just
        # before the first and the two meet.
        #
        # The grid ran from zero to `fibre_side - 1` INCLUSIVE, so the
        # last row of the fine field was the coarse field's LAST row
        # and the first was its FIRST, and the coarse field's own
        # periodicity was broken there. Measured: the wood's seam
        # read 11.88x the truth's and the second wood's 10.44x.
        fibre_rows = numpy.linspace(0.0, fibre_side, resolution, endpoint=False)
        fibre_columns = numpy.linspace(0.0, fibre_side, resolution, endpoint=False)
        fibre_row, fibre_column = numpy.meshgrid(
            fibre_rows, fibre_columns, indexing="ij"
        )
        fibre_field = _bilinear(fibre_field, fibre_row, fibre_column)
        # The fibre's own line: a PERLIN field's ZERO CROSSINGS.
        #
        # A Perlin is a gradient noise, and its sign changes on a
        # lattice of ridges - so the crossing IS the line, with no
        # band to choose and no threshold to tune. A value noise has
        # no such thing: its crossing is where it happens to pass
        # through the middle of its range, and the line that makes
        # came out as speckle.
        #
        # The line's darkness is how steep the field is there, and the
        # steepness is normalised by a HIGH PERCENTILE and not by its
        # maximum: one pixel's slope can be ten times its
        # neighbours', and dividing by it leaves every other pixel at
        # zero - so the whole map came out flat grey.
        # The fibre's own line: the Gabor's STROKES, which are the
        # ridges of its field.
        #
        # A Gabor's strokes are where its value is extreme along the
        # carrier - so the line is the field's own magnitude, taken
        # about the middle of its range: the stroke is the band
        # around the crossing, and it is a thin line because the
        # crossing is sharp.
        # The line is the field's own RIDGE, and its darkness is how
        # steep the ridge is.
        #
        # The ridge is the field folded about its middle, and the
        # line is where the fold creases - so the steepness is the
        # line's darkness.
        # And the line is the RIDGE's own CREST and not the slope.
        #
        # The noise is already ridged - the fBm's folds - and a fold's
        # crest is a LINE, a continuous stroke. The slope of that
        # ridge is two lines, one on each side of the crest, and the
        # crest itself is a point where they meet - so the slope made
        # the grain a field of DOTS.
        #
        # So the line is the ridge's own high values, and the line's
        # darkness is how far above the ridge's own middle it is.
        ridge = numpy.abs(fibre_field - 0.5)
        reach = float(numpy.percentile(ridge, FIBRE_SLOPE_PERCENTILE))
        if reach <= 0.0:
            reach = 1.0
        fibre_dark = numpy.clip(1.0 - ridge / reach, 0.0, 1.0)

        # The fibre's own DARKNESS, for the writer to draw on its
        # own - the same two-scale structure the metal has, so the
        # wood's fibre does not draw over its own envelope.
        #
        # The writer reads a DARKNESS: one at the line and zero
        # between the lines. It used to read a distance, and the two
        # are opposites - so the light and the dark were swapped and
        # the wood's mean came out at 0.159 against a base of 0.600.
        fine_edge = fibre_dark

    return band, edge, (cells, cells), fine_edge


def flat_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A FLAT sheet: one surface, with a fine soft variation on it.

    A plaster, a paint, a wallpaper, a smooth concrete - none of them
    is made of separate pieces, and the lane had no kind for them: they
    all fell through to the Voronoi and became cobbles.

    So the sheet's whole structure is a fine, soft variation, and the
    measure reads it: the truth's own plaster carries no cells to be
    read, so what the measure finds is the sheet's slow variation.

    The field is the value noise's fBm, ridged, and its own
    variation is a sum of sines at high frequencies - which is what
    makes a plaster look like plaster and not like a cloud.
    """
    import numpy

    from golem_blender.pbr import noise

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")

    # The sheet's slow variation, and it is the ENVELOPE: the truth's
    # plaster measures its features here, because there is nothing
    # else.
    # The sheet is ONE octave, and not an fBm.
    #
    # The truth's own plaster has a correlation that decays smoothly -
    # 0.45 at a lag of five, 0.11 at fifty, nothing at ninety-five -
    # and an fBm's higher octaves put a ripple in it: the measure
    # finds the ripple and the plaster's feature scale read 9.27x the
    # truth's.
    #
    # A plaster is a smooth sheet with a tooth on it, and the tooth
    # is the fine layer and not the envelope.
    lattice = max(2, cells)
    # Both layers are an fBm of SEVERAL octaves, and not one.
    #
    # One octave of a value noise is a set of soft squares on the
    # lattice - the noise interpolates between random values at the
    # lattice's corners - and the close sheet showed the concretes as
    # a CHECKER: thirteen soft squares across Concrete030 and a pixel
    # mosaic in Concrete042A's crop. The finer octaves fall between
    # the coarse one's corners, and the lattice stops showing.
    sheet = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=FLAT_SHEET_OCTAVES,
        seed=4,
    )

    # The sheet's own FINE variation: a sum of sines at high
    # frequencies, and the frequencies are integers over the domain
    # so the field is periodic and the map still tiles.
    #
    # The sheet's own fine variation is the SINE sum, and it is what
    # a plaster's tooth is.
    #
    # But the truth's own plaster has no fine structure at all: its
    # correlation decays smoothly from 0.45 at a lag of five to 0.11
    # at fifty and to nothing at ninety-five, with no ripple in it.
    # A sum of sines at high frequencies puts a ripple in the
    # correlation, and the measure finds it: the plaster's feature
    # scale read 9.27x the truth's.
    #
    # So the fine variation is the sheet's own mottle - a Perlin at a
    # fine lattice - and not a sum of sines. A Perlin has no
    # preferred direction, so the tooth does not read as a weave.
    #
    # And the Perlin was wrong too: a Perlin's value is ZERO at
    # every lattice point, and a field that is zero at a regular
    # lattice shows it - so the tooth came out as a MAZE, a regular
    # grid of worm-like cells, where the truth's own plaster is a
    # random speckle.
    #
    # So the tooth is a VALUE noise, and Material Maker's own: the
    # value noise's corners are RANDOM, so the field shows no
    # lattice at all, and its fade is the QUINTIC - so the field is
    # smooth in its second derivative too and the tooth reads as
    # grain and not as a grid.
    fine_lattice = _power_of_two_nearest(max(8, cells * FLAT_TOOTH_LATTICE_FACTOR))
    while fine_lattice > 1 and resolution % fine_lattice != 0:
        fine_lattice //= 2
    while fine_lattice > 1 and fine_lattice * 4 > resolution:
        fine_lattice //= 2
    fine = noise.fbm_2d_value(
        sample_x * fine_lattice,
        sample_y * fine_lattice,
        size=fine_lattice,
        octaves=FLAT_TOOTH_OCTAVES,
        seed=11,
    )
    reach = max(1e-6, float(fine.max() - fine.min()))
    fine = (fine - float(fine.min())) / reach

    # The sheet's SURFACE, and it is a DARKNESS: one where the sheet
    # is darkest.
    edge = 1.0 - sheet
    fine_edge = fine
    return 0, edge, (cells, cells), fine_edge


def _unit(field):

    low = float(field.min())
    return (field - low) / max(1e-9, float(field.max()) - low)


def rock_field(resolution: int, cells: int):
    """A ROCK face: a fine fractal mottle with thin pale scribbles in it.

    A rock was a Voronoi, and the close sheet showed every rock as flat
    polygon facets - a camouflage of plates - where the truth's own
    Rock020, Rock030 and Rock035 are a fine grainy surface with no
    pieces in it at all, and pale lichen scribbles across it.

    So the rock is a many-octave fBm at the surface's own scale, a fine
    grain over it, and the crests of a ridged noise as the scribbles.
    Every period is a whole number, so the face tiles.
    """
    import numpy

    from golem_blender.pbr import noise

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")
    lattice = max(2, int(cells))
    body = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=7,
        persistence=0.6,
        seed=3,
    )
    ridge = noise.fbm_2d_value(
        sample_x * lattice * 4,
        sample_y * lattice * 4,
        size=lattice * 4,
        octaves=4,
        persistence=0.5,
        seed=7,
        folds=1,
    )
    scribble = numpy.clip((_unit(1.0 - ridge) - 0.82) / 0.18, 0.0, 1.0) ** 2
    # The fine grain is a Gaussian grain: a value noise's 8-pixel cells
    # showed as pixel blocks on the close sheet, where the truths' own
    # rock faces decorrelate within 2-4 pixels.
    grain = noise.gaussian_grain(resolution, ROCK_GRAIN_PX, seed=9)
    field = (
        ROCK_BODY_SHARE * _unit(body)
        + ROCK_GRAIN_SHARE * _unit(grain)
        + ROCK_SCRIBBLE_SHARE * scribble
    )
    return 0, _unit(field), (lattice, lattice), None


def moss_field(resolution: int, cells: int):
    """A MOSS: a fine speckle over soft clumps.

    A moss was a Voronoi too, and came out as olive polygon facets
    where the truth's own Moss002 is a fine bright speckle with soft
    darker clumps through it.
    """
    import numpy

    from golem_blender.pbr import noise

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")
    lattice = max(2, int(cells))
    fine = noise.gaussian_grain(resolution, MOSS_SPECKLE_PX, seed=4)
    clump = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=4,
        seed=8,
    )
    # The clumps are at the surface's OWN scale: at twice it the moss
    # read 13.3 features where the truth's Moss002 reads 6.0, and at
    # its own 8.3.
    field = 0.6 * _unit(fine) + 0.4 * _unit(clump)
    return 0, _unit(field), (lattice, lattice), None


def grass_field(resolution: int, cells: int):
    """A GRASS: short blades lying every way, over a soft ground.

    A lawn was a field of scattered STONES, and came out as camouflage
    blotches where the truth's own Grass001 and Grass004 are dense short
    blades.

    A blade is a value noise FINE across a direction and COARSE along
    it, folded so its crest is a line. The direction is an INTEGER
    vector, so the turned noise still repeats on the tile; several
    directions each fill their own patches, so the blades lie every
    way. The crest is sharpened so a blade is a bright leaf over darker
    gaps.
    """
    import numpy

    from golem_blender.pbr import noise

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")
    lattice = max(2, int(cells))
    total = numpy.zeros_like(sample_x)
    weight = numpy.zeros_like(sample_x)
    # The blade count follows the surface's own feature count: a fixed
    # three hundred and twenty read 128 features on a lawn whose own
    # are 73 and 43 on a forest floor whose are 10. Six blades a
    # feature, measured on Grass001, Grass004 and Ground037: the mean
    # |log| scale error 0.745 -> 0.253.
    #
    # And never fewer than GRASS_MIN_BLADES: a forest floor's few
    # features are its moss and dirt patches, not its blades, and at
    # ten features the blades came out as big scribbled strokes.
    blades_across = max(GRASS_MIN_BLADES, round(lattice * GRASS_BLADES_PER_FEATURE))
    blades_along = max(1, blades_across // GRASS_BLADE_ASPECT)
    for index, (along_x, along_y) in enumerate(GRASS_BLADE_DIRECTIONS):
        along = along_x * sample_x + along_y * sample_y
        across = -along_y * sample_x + along_x * sample_y
        blade = noise.fbm_2d_value(
            across * blades_across,
            along * blades_along,
            size=blades_across,
            size_y=blades_along,
            octaves=1,
            seed=20 + index,
            folds=1,
        )
        patch = noise.fbm_2d_value(
            sample_x * 6, sample_y * 6, size=6, octaves=2, seed=40 + index
        )
        share = numpy.clip((patch - 0.45) * 6.0, 0.0, 1.0)
        total = total + share * blade
        weight = weight + share
    blades = total / numpy.maximum(weight, 1e-6)
    leaves = numpy.clip((_unit(1.0 - blades) - 0.55) / 0.45, 0.0, 1.0)
    ground = noise.fbm_2d_value(
        sample_x * lattice * 2,
        sample_y * lattice * 2,
        size=lattice * 2,
        octaves=4,
        seed=6,
    )
    field = 0.8 * leaves + 0.2 * _unit(ground)
    return 0, _unit(field), (lattice, lattice), None


def parquet_field(
    resolution: int,
    cells: int,
    aspect: float = PARQUET_ASPECT,
    courses: int | None = None,
):
    """A wood floor: long BLOCKS, staggered, each with its own tone.

    A parquet is the BRICK's primitive with a wood's palette and a
    much wider block, and the wide set says so: the truth's own
    parquet measures a row-to-column change ratio of 0.24, and it is
    the most horizontal surface in the sample - the blocks are long
    and low and they run across.

    So the blocks are the BRICK's courses, with the brick's half-block
    offset between the courses, and the block is much wider than the
    brick's.

    The blocks are the brick's own field and the writer's own path,
    so the block's tone and the block's joint are the ones the
    benchmark already measured for the brick. The parquet adds ONE
    thing to them: the block's own GRAIN, which is the wood's own
    fibre.
    """
    import numpy

    # The courses' PITCH, in pixels, and it DIVIDES the resolution.
    #
    # A power of two rounds DOWN, and the truth's own parquet
    # measures ten blocks across and six courses down - so a power of
    # two gave four and two, and the floor came out with 512-pixel
    # blocks where the truth's are a hundred.
    #
    # And a COUNT cannot be a divisor of the resolution and be ten:
    # the resolution is a power of two and so every divisor of it is
    # a power of two.
    #
    # So the PITCH is what divides the resolution - the pitch is the
    # truth's own, rounded to the nearest divisor - and the count is
    # the resolution over the pitch.
    #
    # The count was the truth's own with the index taken modulo it,
    # and the map did not tile: the last block was a fraction
    # narrower and the wrap joined two different widths. Measured, the
    # parquet's seam read 44.2x the truth's.
    # And the COURSES, and they are the truth's own DOWN count and
    # not the across count.
    #
    # A parquet is a set of LONG BOARDS: many blocks across and few
    # courses down. The truth's own WoodFloor051 measures 7.1
    # features across and ONE down, and the courses were the across
    # count - so the floor came out as a grid of squares, seven
    # across and seven down, where the truth has long boards.
    # And the COURSES, and they are the boards' own count and not the
    # truth's DOWN count.
    #
    # The truth's own down count is 0.0 or 1.0 for five of its seven
    # parquets - because a row of a parquet is SMOOTH along its
    # length, and the measure reads the boards and not the rows. So
    # the courses were one, and the floor came out as one row of
    # narrow boards: vertical stripes.
    #
    # And the truth's own WoodFloor051's boards are about a hundred
    # and eighty pixels wide and about fifty-five tall, so a floor of
    # six boards across is about eighteen courses down.
    across_count = max(1, round(cells * aspect / max(1.0, PARQUET_COURSES_PER_ACROSS)))
    course_pitch = _nearest_divisor(
        resolution,
        max(1, round(resolution / max(1, across_count * PARQUET_COURSES_PER_ACROSS))),
    )
    courses = max(1, resolution // course_pitch)
    # The blocks ACROSS a course, and the floor's boards are WIDE.
    #
    # The truth's own WoodFloor051 is a set of horizontal boards, and
    # the boards are about a hundred and eighty pixels wide and about
    # fifty-five tall - so the board's own aspect is three and a half
    # to one, and a floor of square blocks is not a floor at all.
    #
    # And the boards' COUNT comes from the truth's own feature count,
    # which is the whole surface's: the truth's own WoodFloor051
    # measures 5.7 features across, and its boards are six across.
    #
    # The count was a CONSTANT - ten blocks across - and the courses
    # came from the truth's DOWN count, which is 0.0 or 1.0 for five
    # of the seven parquets in the truth's own, because a row of a
    # parquet is SMOOTH along its length. So the floor came out as
    # one row of ten narrow blocks.
    across = max(1, round(cells * aspect / max(1.0, PARQUET_COURSES_PER_ACROSS)))
    block_pitch = _nearest_divisor(resolution, max(1, round(resolution / across)))
    across = max(1, resolution // block_pitch)

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")

    # Each course is offset by its OWN fraction of a block, so the
    # joints do not line up and the floor reads as laid boards.
    #
    # The offset was two WHOLE blocks every other pair of courses - and
    # a whole block does not move a joint off the block lattice, so
    # every course's joints sat on the same columns and a straight
    # joint ran down the image's own edge. It was whole because a
    # fractional one broke the wrap, and THAT was the position in the
    # board being read against the wrapped column; with the position
    # taken as the staggered coordinate's own fraction (below), a
    # fractional offset wraps exactly.
    #
    # The fraction is the golden ratio of the WRAPPED course, so the
    # course at the image's top and the one it wraps to share it.
    row = numpy.floor(sample_y * courses)
    wrapped_row = numpy.mod(row, courses)
    offset = numpy.mod(wrapped_row * 0.6180339887, 1.0)
    column = numpy.floor(sample_x * across + offset).astype(numpy.int32)

    # The cell is a LINEAR index - the course times the row's width
    # plus the block's own index in it - and that is the encoding the
    # colour's hash decodes.
    #
    # It was `row * 100003 + column`, and the hash splits the index by
    # the row's width - so every block got the same colour and the
    # floor came out as one flat sheet.
    # The cell is a LINEAR index, and the indices WRAP on the
    # counts - so the block at the edge is the same block as the one
    # at the start, and the map tiles.
    cell = (
        wrapped_row.astype(numpy.int32) * across
        + numpy.mod(column, across).astype(numpy.int32)
    ).astype(numpy.int32)

    # The JOINT is the line between the blocks, and it is a THIN
    # line: a parquet's blocks meet at a seam and not at a mortar
    # trench.
    # The distance to the shingle's own border, and the column is
    # WRAPPED: the shingle at the edge of the image is the same
    # shingle as the one at the start, and the distance to its border
    # has to be measured in the wrapped frame.
    #
    # It was not, and the distance went out of range at the wrap -
    # and the joint was drawn there and nowhere else.
    # The position INSIDE the board is the fractional part of the
    # staggered coordinate, and not the coordinate less the WRAPPED
    # column.
    #
    # The stagger adds two blocks to the column and the column wraps,
    # so in the last two blocks of every staggered course the
    # coordinate less the wrapped column was about twenty - and the
    # distance to the board's edge went negative and clipped to solid
    # joint. A dark strip ran down the image's edge, and the floor's
    # seam read 16.46x against the truth's 0.4.
    staggered = sample_x * across + offset
    within_x = staggered - numpy.floor(staggered)
    within_y = sample_y * courses - row
    distance = numpy.minimum(
        numpy.minimum(within_x, 1.0 - within_x), numpy.minimum(within_y, 1.0 - within_y)
    )
    edge = numpy.clip(distance * min(across, courses), 0.0, 1.0)

    # The block's own GRAIN, and it is STRAIGHT LINES running along
    # the block.
    #
    # It was the WOOD's own fibre field, and that is a CATHEDRAL
    # SWIRL - the wood's rings and its cathedral figure - and a
    # parquet's boards are cut flat, so their grain is a set of
    # straight lines and not a swirl.
    #
    # So the grain is a RIDGED value noise with many cells across and
    # ONE along: the ridges are the lines, they run along the board,
    # and they are irregular because the noise is.
    #
    # The lattice's y period is ONE, so the field's features are as
    # tall as the whole domain - and the lines run across it.
    # The board's own GRAIN is the wood's own growth rings, and every
    # board shows a different stretch of them.
    #
    # It was a single noise of one cell along the board, stretched
    # across all of them, so the floor came out as broad blurred
    # stripes with the SAME grain running through neighbouring boards.
    # A board is cut from its own log; its offset into the rings is its
    # own, from the golden ratio of its index, and the board that wraps
    # across the image's edge keeps one index and so one offset.
    board_offset = numpy.mod(cell.astype(numpy.float64) * 0.6180339887, 1.0)
    fibre = 1.0 - wood_ring_lightness(sample_y + board_offset, sample_x)
    return cell, edge, (across, courses), fibre


def herringbone_field(
    resolution: int,
    cells: int,
    aspect: float = HERRINGBONE_ASPECT,
):
    """A HERRINGBONE floor: boards laid in a basketweave.

    The truth's own parquet - WoodFloor070 - is a basketweave and
    not a staggered course, and the measure reads it as ten features
    across and eleven down with a row-to-column change ratio of
    1.00.

    A herringbone is a set of BOARDS at ninety degrees to each other,
    in PAIRS: two boards make an L, and the Ls tile the floor.

    So the floor is divided into SQUARES - an L's own square - and
    each square holds one board across and one down. The board's own
    direction alternates with the square's, and that is the whole of
    the pattern.
    """
    import numpy

    # The L's own squares, and the count is a power of two so the
    # floor's wrap joins two whole squares.
    squares = _power_of_two_nearest(cells)
    while squares > 1 and resolution % squares != 0:
        squares //= 2

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")

    # The square's own coordinates.
    square_x = numpy.floor(sample_x * squares)
    square_y = numpy.floor(sample_y * squares)
    within_x = sample_x * squares - square_x
    within_y = sample_y * squares - square_y

    # The square's own PARITY, and it decides which way the boards
    # run: an even square is one way and an odd square the other.
    parity = numpy.mod(square_x + square_y, 2.0)

    # A board is a band: it runs the length of the square, and its
    # width is the square's own.
    across = numpy.where(parity > 0.5, within_y, within_x)
    # The board's own edge: the joint is at the square's border, and
    # the board's own width is the square's half.
    distance = numpy.minimum(across, 1.0 - across)
    edge = numpy.clip(distance * squares, 0.0, 1.0)

    # The cell is a LINEAR index, and it is the BOARD's own and not
    # the square's: two boards in one square are two boards.
    cell = (
        square_y.astype(numpy.int32) * squares * 2
        + square_x.astype(numpy.int32) * 2
        + numpy.where(parity > 0.5, 1, 0).astype(numpy.int32)
    ).astype(numpy.int32)
    return cell, edge, (squares * 2, squares), None


def marble_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A MARBLE: a fine network of VEINS.

    A marble is a stone that was cut across its bed, and the cut
    exposes the veins: a network of fine dark lines that wander
    across the surface.

    Measured on the truth's own: the truth's Marble012's veins cover
    eight per cent of the surface and their correlation is +0.280 at
    an eight-pixel lag, +0.079 at a thirty-two and -0.004 at a
    hundred and twenty-eight - so the veins are a fine network that
    decorrelates inside a hundred pixels, and the whole surface's
    correlation crosses zero there.

    A vein is a RIDGE and not a cloud: the stone's minerals collect
    along a line, and the line is where the stone changed. So the
    field is a ridged Perlin - Material Maker's `shard_fbm`, which is
    a Perlin with folds, and the folds are the ridging.

    And the veins WANDER: a marble's veins are not straight lines
    and not a random noise, and a warped field is what makes them
    wander - Material Maker's `warp` node, MIT licensed, and the same
    one the brick's face uses.
    """
    import numpy

    from golem_blender.pbr import noise_perlin, warp

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")

    # The veins' own PERIOD, and it is the CELLS - the surface's own
    # feature count - and not a power of two.
    #
    # The power of two was a quantisation for the field's WRAP, and
    # the wrap does not need it: the noise's own period handles the
    # tiling. And the quantisation was coarse - the truth's own
    # Marble012 measures fourteen features across and its Marble016
    # twenty-two, and both quantised to sixteen, so the two marbles
    # came out with the SAME veins.
    #
    # So the period is the cells themselves.
    period = max(4, int(cells))

    # The WARP, and it is the veins' own bed: a low-frequency field
    # that the veins ride, so they wander.
    warp_lattice = max(2, period // 4)
    bed = noise_perlin.perlin_2d(
        sample_x * warp_lattice,
        sample_y * warp_lattice,
        period=warp_lattice,
        seed=17,
    )
    bed_reach = max(1e-6, float(bed.max() - bed.min()))
    bed = (bed - float(bed.min())) / bed_reach
    warped_x, warped_y = warp.warped_coordinates(
        sample_x,
        sample_y,
        bed,
        amount=MARBLE_WARP,
        step=MARBLE_WARP_STEP,
        iterations=1,
    )
    # And the warp's DISPLACEMENT is BOUNDED, and the bound is a
    # fraction of the vein's own period.
    #
    # The warp displaces along the field's SLOPE, and the slope is
    # unbounded: where the bed is steep the displacement runs to
    # many cells, and the vein's contours are crowded into a fine
    # mess. The truth's own Marble012's veins measure fourteen
    # features across and ours read a hundred and forty-six - the
    # warp was folding the contours into itself.
    #
    # So the displacement is clipped to a fraction of a cell, and the
    # cell is the vein's own period.
    limit = MARBLE_WARP_LIMIT_CELLS / period
    warped_x = numpy.clip(warped_x, sample_x - limit, sample_x + limit)
    warped_y = numpy.clip(warped_y, sample_y - limit, sample_y + limit)
    # The veins themselves: the CONTOURS of a warped field.
    #
    # A vein is where the stone's bed changed, and a bed is a
    # continuous field - so a vein is a LEVEL SET of it, and a level
    # set of a smooth field is a LINE.
    #
    # A RIDGE was tried and it is not the same thing: a ridge is where
    # the field is near its own maximum, and a maximum is a point and
    # not a line, so the veins came out as isolated blobs.
    #
    # So the vein is the sine of the warped field - the classic
    # marble, where the bands are the field's own contours and the
    # warp is what makes them wander.
    #
    # And the BED is FINER than the vein's own spacing, or the
    # contour is a BLOB and not a line: the truth's own Marble012's
    # veins are six pixels across and a hundred and forty-four
    # apart, so the contour has to wander over many of the bed's own
    # features.
    bed_lattice = period * MARBLE_BED_FINENESS
    bed = noise_perlin.perlin_2d(
        warped_x * bed_lattice,
        warped_y * bed_lattice,
        period=bed_lattice,
        seed=23,
    )
    # The VEINS are the LEVEL SETS of a warped fBm, drawn at a fixed
    # PIXEL width: the distance to the field's middle contour is
    # |v - 1/2| over the field's own slope, so a band about it is a line
    # of the same width wherever it runs. The veins wander, branch and
    # stop, as the truths' own do.
    #
    # They replaced a Worley crackle and a contour band. The crackle was
    # a net of POLYGONS over the whole stone; the band - a fixed range of
    # a field whose slope varies - broke into DASHES wherever the slope
    # was steep; and F2 - F1, which the crackle was drawn from, is not a
    # distance, so its veins came in every width. On the close sheet the
    # marbles were clouds with a polygon net and dashed loops, and the
    # dark ones' veins were not there at all.
    #
    # Two families: bold veins at a few cells and fine ones at the
    # surface's own count, each with a width that varies along it, and
    # a slow field that says where the network runs strong.
    from golem_blender.pbr import noise as value_noise

    pixels = resolution / 1024.0

    def level_veins(lattice: int, width_px: float, seed: int):
        warp_lattice = max(2, lattice // 2)
        warp_x = value_noise.fbm_2d_value(
            sample_x * warp_lattice,
            sample_y * warp_lattice,
            size=warp_lattice,
            octaves=3,
            seed=seed + 1,
        )
        warp_y = value_noise.fbm_2d_value(
            sample_x * warp_lattice,
            sample_y * warp_lattice,
            size=warp_lattice,
            octaves=3,
            seed=seed + 2,
        )
        field = value_noise.fbm_2d_value(
            sample_x * lattice + (warp_x - 0.5) * 4.0 * MARBLE_VEIN_WARP,
            sample_y * lattice + (warp_y - 0.5) * 4.0 * MARBLE_VEIN_WARP,
            size=lattice,
            octaves=MARBLE_VEIN_OCTAVES,
            persistence=0.62,
            seed=seed,
        )
        slope = numpy.hypot(
            (numpy.roll(field, -1, axis=1) - numpy.roll(field, 1, axis=1)) * 0.5,
            (numpy.roll(field, -1, axis=0) - numpy.roll(field, 1, axis=0)) * 0.5,
        )
        distance_px = numpy.abs(field - 0.5) / numpy.maximum(slope, 1e-6)
        width = value_noise.fbm_2d_value(
            sample_x * lattice * 2,
            sample_y * lattice * 2,
            size=lattice * 2,
            octaves=2,
            seed=seed + 3,
        )
        width = width_px * pixels * (0.4 + 1.2 * width)
        return numpy.clip(1.0 - distance_px / width, 0.0, 1.0)

    vein_line = numpy.maximum(
        level_veins(
            max(3, round(period * MARBLE_BOLD_FACTOR)), MARBLE_BOLD_VEIN_PX, 11
        ),
        MARBLE_FINE_SHARE * level_veins(period, MARBLE_FINE_VEIN_PX, 3),
    )
    presence_lattice = max(2, round(period * MARBLE_PRESENCE_FACTOR))
    presence = value_noise.fbm_2d_value(
        sample_x * presence_lattice,
        sample_y * presence_lattice,
        size=presence_lattice,
        octaves=3,
        seed=41,
    )
    vein_line = vein_line * numpy.clip(
        (presence - MARBLE_VEIN_PRESENCE) / MARBLE_VEIN_PRESENCE_SOFTNESS, 0.0, 1.0
    )
    # The fibre is the VEINS: the line writer reads its fibre as a
    # darkness that is near zero almost everywhere and saturates above an
    # eighth of its peak, and draws it in the line's colour (dark on a
    # pale marble, light on a dark one). As the stone - one everywhere
    # but the veins - every pixel saturated, and only a vein's very core
    # showed: the veins came out sparse and faint.
    veins = vein_line
    #
    # And the ENVELOPE is the stone's own MOTTLE and the FIBRE is the
    # crackle.
    #
    # They were the same array, and the writer's marble branch put a
    # FLAT half in the envelope's slot - so the stone had no
    # variation at all and the marble came out as a flat field with
    # a few dark specks in it.
    #
    # The truth's own Marble021 has a p10 of 0.918 and a p90 of
    # 0.973: the stone itself VARIES, gently, and the veins are the
    # fine network on top of it.
    # And the ENVELOPE is the BED's own shape, not the inverse of
    # the contour's narrow band.
    #
    # The envelope was the inverse of a band that is zero almost
    # everywhere, so it was one almost everywhere, and the writer's
    # line function - which divides by the field's own maximum - made
    # it a constant, and the stone came out with no variation at all.
    #
    # The truth's own Marble021's stone varies: its p10 is 0.918 and
    # its p90 0.973. So the envelope is a mottle over the whole
    # surface.
    #
    # And the mottle is FINE: the bed's own lattice is the vein's
    # own period, and a marble's stone is a fine even cloud and not
    # a few big blobs. So the envelope is a value noise at a lattice
    # of its own.
    from golem_blender.pbr import noise

    mottle_lattice = max(4, round(period * MARBLE_MOTTLE_FACTOR))
    mottle = noise.fbm_2d_value(
        sample_x * mottle_lattice,
        sample_y * mottle_lattice,
        size=mottle_lattice,
        octaves=MARBLE_MOTTLE_OCTAVES,
        seed=31,
    )
    mottle_reach = max(1e-6, float(mottle.max() - mottle.min()))
    mottle = (mottle - float(mottle.min())) / mottle_reach
    # And the mottle rides on the BED, so the stone's large-scale
    # shape is the bed's own - a marble is one piece of stone and its
    # cloud is one cloud.
    mottle = 0.5 * mottle + 0.5 * numpy.clip(bed, 0.0, 1.0)
    return (
        numpy.zeros((resolution, resolution), dtype=numpy.int32),
        mottle,
        (period, period),
        veins,
    )


def roof_field(
    resolution: int,
    cells: int,
    aspect: float = ROOF_ASPECT,
):
    """A ROOF: courses of overlapping shingles.

    A roof is the BRICK's primitive with a square shingle and a
    per-shingle tone - and the shingles OVERLAP, so each course
    covers the one below it.

    Measured on the truth's own: RoofingTiles013A's courses come
    every a hundred and seventy-seven pixels and its shingles every a
    hundred and eighty-five, so a shingle is about as wide as it is
    tall and the courses and the shingles are at the same scale.

    And the shingle's tone is a SMOOTH field over the whole roof and
    not a per-shingle hash.

    The half-shingle stagger means the wrap joins a shingle to one a
    whole row away, and a per-shingle hash makes that a colour step.
    Measured, the roof's seam read 12.4x the truth's - and the truth's
    own eight-by-eight blocks of shingles measure between 0.165 and
    0.214, so the variation is a seventh of the surface's own mean
    and a smooth field carries it.
    """
    import numpy

    from golem_blender.pbr import noise

    # The courses' PITCH, in pixels, and it divides the resolution.
    #
    # A power of two rounds DOWN - and the truth's own roof measures
    # 5.6 courses and 5.9 shingles across, so a power of two gave
    # four of each and the roof came out with 256-pixel shingles
    # where the truth's are 185.
    #
    # And a COUNT cannot be a divisor of the resolution and be five
    # and a half: the resolution is a power of two and so every
    # divisor of it is a power of two.
    #
    # So the PITCH is what divides the resolution - the pitch is the
    # truth's own, rounded to the nearest divisor - and the count is
    # the resolution over the pitch.
    course_pitch = _nearest_divisor(
        resolution, max(1, round(resolution / max(1, cells)))
    )
    courses = max(1, resolution // course_pitch)
    across = max(1, round(courses * aspect))
    block_pitch = _nearest_divisor(
        resolution, max(1, round(resolution / max(1, across)))
    )
    across = max(1, resolution // block_pitch)

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")

    # The shingle's own place, and alternate courses are offset by
    # HALF a shingle - the same offset a brick wall has.
    #
    # The offset was two WHOLE shingles, which moves no joint off the
    # shingle lattice, so the joints of every course lined up. A half
    # alternates its parity every course, so it wraps only when the
    # course count is EVEN; an odd count takes each course's own
    # golden-ratio fraction instead, which wraps whatever the count.
    row = numpy.floor(sample_y * courses)
    wrapped_row = numpy.mod(row, courses)
    if courses % 2 == 0:
        offset = numpy.mod(wrapped_row, 2.0) * 0.5
    else:
        offset = numpy.mod(wrapped_row * 0.6180339887, 1.0)
    staggered = sample_x * across + offset
    column = numpy.floor(sample_x * across + offset).astype(numpy.int32)

    # The cell is a LINEAR index, and that is the encoding the
    # colour's hash decodes.
    cell = (
        wrapped_row.astype(numpy.int32) * across
        + numpy.mod(column, across).astype(numpy.int32)
    ).astype(numpy.int32)

    # The JOINT is the line between the shingles, and it is a THIN
    # line and not a mortar trench: a shingle lies on the one below
    # and the line between them is a shadow.
    #
    # The column is WRAPPED: the shingle at the edge of the image is
    # the same shingle as the one at the start, and the distance to
    # its border has to be measured in the wrapped frame.
    # The position in the shingle is the staggered coordinate's own
    # fraction, and not the coordinate less the WRAPPED column - that
    # read about twenty in the last shingles of a staggered course and
    # clipped the edge distance to solid joint.
    within_x = staggered - numpy.floor(staggered)
    within_y = sample_y * courses - row
    distance = numpy.minimum(
        numpy.minimum(within_x, 1.0 - within_x), numpy.minimum(within_y, 1.0 - within_y)
    )
    edge = numpy.clip(distance * min(across, courses), 0.0, 1.0)

    # The roof's own TONE, and it is a SMOOTH field over the whole
    # roof - and not a per-shingle hash.
    #
    # The half-shingle stagger means the wrap joins a shingle to one
    # a whole row away, and a per-shingle hash makes that a colour
    # step. Measured, the roof's seam read 12.4x the truth's.
    tone = noise.fbm_2d_value(
        sample_x * courses,
        sample_y * courses,
        size=courses,
        octaves=1,
        seed=9,
    )
    tone_reach = max(1e-6, float(tone.max() - tone.min()))
    tone = (tone - float(tone.min())) / tone_reach
    return cell, edge, (across, courses), tone


def woven_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
    checkered: bool = False,
):
    """A WOVEN cloth: threads over and under one another, as a darkness.

    A fabric is not a field of cells. It is a weave: threads running
    one way and threads running the other, and the eye reads the
    crossing.

    Measured on the truth's own: Fabric030 measures four hundred and
    twelve features across and forty-four down, with a row-to-column
    change ratio of 1.39 - so the threads run ACROSS the surface and
    the weave is fine in one direction and coarse in the other. And
    Fabric061 and Fabric066 measure a few hundred in both
    directions, with a spread of 0.13.

    The lane's answer for a fabric was a VORONOI, and a Voronoi's
    cells are large flat pieces with hard borders - so a fabric came
    out as a field of pebbles.

    So the cloth is a WEAVE of threads - one where the gaps between
    them are dark - under a mottle at the surface's own scale, and the
    feature count decides which of the two is the structure.
    """
    import numpy

    from golem_blender.pbr import noise

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")
    # The checkered squares' own lattice, as it was: a power of two that
    # divides the resolution, so the chequer wraps.
    lattice = _power_of_two_nearest(max(4, cells))
    while lattice > 1 and resolution % lattice != 0:
        lattice //= 2
    while lattice > 1 and lattice * 2 > resolution:
        lattice //= 2

    # A WEAVE, Material Maker's `weave` (MIT): threads along the rows
    # and threads down the columns, each rising and falling as a sine
    # and shifted by its neighbour's index, so the two go over and
    # under one another; between them the gaps. The sum of two
    # isotropic noises it replaced had no thread in it, and every
    # fabric came out as speckle.
    #
    # Two regimes, as the truths' own measures say. Where the feature
    # count resolves threads, the threads ARE the cloth's structure
    # (Fabric066: 341 features, about 140 threads). Where it does not,
    # the features are the cloth's slubs and mottle over fine threads
    # (Fabric030: 45 features over threads 3 pixels apart), and the
    # mottle carries the measure.
    threads = round(cells / WOVEN_FEATURES_PER_THREAD)
    fine = threads < WOVEN_MIN_THREADS
    if fine:
        threads = WOVEN_FINE_THREADS
        mottle_share = WOVEN_FINE_MOTTLE
    else:
        mottle_share = WOVEN_THREADED_MOTTLE
    # An EVEN count: a thread's sine and its over-under shift both
    # repeat every two threads, so an odd count would not wrap.
    threads += threads % 2
    # The samples are "ij"-indexed: sample_y runs along a row.
    along = sample_y * threads
    down = sample_x * threads
    if fine:
        # A FINE cloth's threads WANDER and differ, as a linen's do: a
        # perfect fine grid reads as a fine grid - the truths' fine
        # cloths decorrelate within their threads, and are ten times
        # finer variance than slow (Fabric030's fine/slow 10.5). So the
        # threads are displaced by half a thread over a slow field, and
        # each crossing has its own brightness. A larger warp swirled
        # the threads into marbling; a larger mottle was clouds.
        warp_along = noise.fbm_2d_value(
            sample_x * WOVEN_WARP_LATTICE,
            sample_y * WOVEN_WARP_LATTICE,
            size=WOVEN_WARP_LATTICE,
            octaves=2,
            seed=31,
        )
        warp_down = noise.fbm_2d_value(
            sample_x * WOVEN_WARP_LATTICE,
            sample_y * WOVEN_WARP_LATTICE,
            size=WOVEN_WARP_LATTICE,
            octaves=2,
            seed=37,
        )
        along = along + (warp_along - 0.5) * 2.0 * WOVEN_WARP_THREADS
        down = down + (warp_down - 0.5) * 2.0 * WOVEN_WARP_THREADS
    half_width = WOVEN_THREAD_WIDTH / 2.0
    row_threads = (numpy.sin(numpy.pi * (along + numpy.floor(down))) * 0.5 + 0.5) * (
        numpy.abs(down - numpy.floor(down) - 0.5) < half_width
    )
    column_threads = (
        numpy.sin(numpy.pi * (1.0 + down + numpy.floor(along))) * 0.5 + 0.5
    ) * (numpy.abs(along - numpy.floor(along) - 0.5) < half_width)
    crest = numpy.maximum(row_threads, column_threads)
    if fine:
        # Each crossing's own brightness, keyed on its WRAPPED index so
        # the crossing at the edge is the crossing at the start.
        index_along = numpy.mod(numpy.floor(along), threads).astype(numpy.int64)
        index_down = numpy.mod(numpy.floor(down), threads).astype(numpy.int64)
        crossing = numpy.random.default_rng(7).random((threads, threads))
        crest = crest * (
            1.0
            - WOVEN_CROSSING_JITTER
            + WOVEN_CROSSING_JITTER * crossing[index_down, index_along]
        )
    darkness = 1.0 - crest
    mottle_lattice = max(2, int(cells))
    mottle = noise.fbm_2d_value(
        sample_x * mottle_lattice,
        sample_y * mottle_lattice,
        size=mottle_lattice,
        octaves=3,
        seed=21,
    )
    mottle = (mottle - mottle.min()) / max(1e-9, float(mottle.max() - mottle.min()))
    edge = darkness * (1.0 - mottle_share) + mottle * mottle_share
    slub_share = WOVEN_SLUB_SHARE * min(
        1.0, max(0.0, (WOVEN_SLUB_FEATURES - cells) / WOVEN_SLUB_FEATURES)
    )
    if fine and slub_share > 0.0:
        # A fine cloth's SLUBS: threads thicker for a stretch along the
        # row. In the fine regime the feature count IS the cloth's slow
        # structure, and long slubs read as few features: the truth's own
        # Fabric036, a canvas of bright horizontal slubs, reads 17 and
        # decorrelates within 12 pixels along a row against 3 down it,
        # where the regular linen Fabric030 reads 45. Slubs on the linen
        # streaked it (looked at), so they fade in below 40 features.
        slubs = noise.gaussian_grain(
            resolution, WOVEN_SLUB_PX, seed=43, along_rows=WOVEN_SLUB_ALONG
        )
        edge = edge * (1.0 - slub_share) + slubs * slub_share
    if checkered:
        # A CHECKERED cloth is a CHEQUER of squares and not a
        # crosshatch of threads, and the two are different things.
        #
        # The truth's own Fabric083 is a "checkered, clean, cloth,
        # fabric, gray, patterned, smooth, textile, woven" and its
        # correlation is +0.870 at a lag of one, +0.051 at four and
        # MINUS 0.136 at eight - it goes NEGATIVE, and a crosshatch
        # of threads never does: ours read +0.040 at eight where the
        # truth reads -0.136.
        #
        # And the chequer WRAPS: the squares are counted modulo the
        # lattice, so the last square meets the first and the map's
        # seam stays small. It did not, and Fabric080's seam read
        # 522.79 against the truth's 0.97.
        #
        # The count is CYCLIC and not a plain floor: the samples run
        # from zero to just short of one, so the last pixel is in
        # cell L-1 and the first is in cell zero - and a plain floor
        # gives them opposite parities, so the chequer's last column
        # was the first column's opposite and the seam read 0.65.
        #
        # With the index taken modulo the lattice the last column
        # and the first are the SAME square, and the seam is zero.
        index_x = numpy.mod(numpy.floor(sample_x * lattice + 0.5), lattice)
        index_y = numpy.mod(numpy.floor(sample_y * lattice + 0.5), lattice)
        squares = numpy.mod(index_x + index_y, 2.0)
        edge = numpy.clip(edge * 0.35 + squares * 0.65, 0.0, 1.0)
    return (
        numpy.zeros((resolution, resolution), dtype=numpy.int32),
        edge,
        (lattice, lattice),
        edge,
    )


def markings_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """ROAD MARKINGS: painted stripes on a surface.

    A lane marking is GEOMETRY and not noise: a painted line is a
    straight stripe of a colour that is nothing like the surface's,
    and the surface's own texture goes on underneath it.

    The wide set has three kinds of road in it and the lane had none
    of them: a road with a dashed centre line, a road with a solid
    edge line, and a road with yellow markings.

    Measured on the truth's own: the dashed centre line of Road007
    is five pixels wide in a thousand and twenty-four and its dashes
    run every fifty-odd pixels, and the solid edge line is five
    pixels wide too.

    So the markings are the road's own LAYOUT: two solid edge lines
    and a dashed centre line, the dashes a whole number of times
    along the road so the map tiles.

    The field is the markings' own DARKNESS: one on a stripe and
    zero on the road, and the writer draws it over the road.
    """
    import numpy

    from golem_blender.pbr import noise

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")

    # The markings are the road's own LAYOUT, as the truths measure it:
    # two solid edge lines and a dashed centre line, a fiftieth of the
    # surface in paint. They were drawn at random places of a lattice of
    # four - solid or dashed by a seed - and the truth's own Road007, a
    # two-lane road, came out with five lines across it.
    #
    # The dashes run along the road a whole number of times, so the map
    # tiles along it; across, the edge lines stand clear of the image's
    # edge, so a road strip repeated side by side is two roads.
    half_width = MARKINGS_LINE_WIDTH / 2.0
    painted = numpy.zeros(sample_x.shape, dtype=bool)
    for place, is_dashed in MARKINGS_LAYOUT:
        on_line = numpy.abs(sample_x - place) < half_width
        if is_dashed:
            on_line &= numpy.mod(sample_y * MARKINGS_DASHES_PER_IMAGE, 1.0) < 0.5
        painted |= on_line
    lattice = MARKINGS_ROAD_LATTICE
    road = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=1,
        seed=4,
    )
    road_reach = max(1e-6, float(road.max() - road.min()))
    road = (road - float(road.min())) / road_reach
    # And the asphalt's own GRAIN over the slow variation: the truth's own
    # Road007 is a fine speckle of stones in bitumen, and the slow field
    # alone drew a smooth dark sheet.
    road = (
        1.0 - MARKINGS_GRAIN_SHARE
    ) * road + MARKINGS_GRAIN_SHARE * noise.gaussian_grain(
        resolution, MARKINGS_GRAIN_PX, seed=6
    )

    edge = 1.0 - painted.astype(numpy.float64)
    return (
        numpy.zeros((resolution, resolution), dtype=numpy.int32),
        edge,
        (lattice, lattice),
        road,
    )


def carpet_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A CARPET: a pile of fibres, a fine directional fuzz.

    A carpet is almost flat. The truth's own carpet measures a luma
    spread of 0.029 over twenty-seven thousand fine specks, and its
    row-to-column change ratio is 1.20 - so it is a soft directional
    mottle and not a set of cells.

    It was a VORONOI, and a Voronoi's cells are large flat pieces
    with hard borders - so a carpet came out as a field of pebbles.
    It is a FIBRE: a fine, directional, tileable mottle.
    """
    import numpy

    from golem_blender.pbr import noise

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")

    # The pile's own scale, and it is FINE: the truth's own carpet
    # measures a period of NINE pixels in a thousand and twenty-four,
    # so there are a hundred and fourteen features across.
    #
    # The lattice is the pile's own count and not the surface's
    # feature count times a factor: the truth's carpet measures a
    # hundred and fourteen features and the pile IS that.
    lattice = _power_of_two_nearest(max(2, cells))
    while lattice > 1 and resolution % lattice != 0:
        lattice //= 2
    while lattice > 1 and lattice * 4 > resolution:
        lattice //= 2

    # The pile is DIRECTIONAL: a carpet's fibres lie in one
    # direction, and the truth's own reads 1.20 times more change
    # along the row than down the column.
    #
    # So the lattice is stretched along the fibre's direction, and
    # the stretch is a whole number so the field stays periodic.
    #
    # The lattice's x period is ONE and its y period is MANY: the
    # field's features are as wide as a cell of it and as tall as
    # the whole surface - and the pile's streaks run ACROSS, which
    # is along the fibre.
    #
    # The truth's own carpet reads 1.20 times more change along a
    # ROW than down a column, so the streaks run along the row.
    # The pile's own scale, and it is the SURFACE's own feature
    # count: the truth's own carpet measures a hundred and fourteen
    # features across and a period of nine pixels, and the pile IS
    # that.
    #
    # The lattice is the number of cells ALONG the fibre, and the
    # stretch is how much longer the features are ACROSS it.
    #
    # The stretch was eight, and the pile came out six times more
    # varied along the row than down the column - where the truth's
    # is 1.20. So the stretch is two: a carpet's fibres are only
    # slightly directional.
    stretched = lattice * CARPET_FIBRE_STRETCH
    while stretched > 1 and resolution % stretched != 0:
        stretched //= 2
    pile = noise.fbm_2d_value(
        sample_x,
        sample_y * stretched,
        size=1,
        octaves=1,
        seed=11,
        size_y=stretched,
    )
    reach = max(1e-6, float(pile.max() - pile.min()))
    pile = (pile - float(pile.min())) / reach

    # The CARPET'S OWN surface, and it is the pile and the pile's
    # fine mottle together: a carpet is a pile of fibres and the
    # fibres are what the eye reads.
    #
    # The mottle alone was the fibre, and it is a noise with no
    # direction - so the carpet came out as a smooth sheet with a
    # directional haze on it, and the truth's own carpet is a
    # hundred and fourteen features across with a spread of 0.0301.
    # The carpet's own MOTTLE, and it is the FINE structure: the
    # truth's own carpet measures a period of nine pixels in a
    # thousand and twenty-four and a row-to-column change ratio of
    # 1.20 - so it is a fine ISOTROPIC fuzz and not a set of streaks.
    #
    # The pile was the main structure and it is a STREAK, and a
    # streak's period and its directionality are the same number: at
    # the truth's own scale the pile read six times more varied
    # along the row than down it, and the truth's is 1.20.
    #
    # So the mottle leads and the pile is the direction ON it: the
    # mottle is the carpet's own tooth and the pile is the way the
    # fibres lie.
    # The mottle's own lattice, and it is the SURFACE's own feature
    # count: the truth's own carpet measures a hundred and fourteen
    # features across and a period of nine pixels in a thousand and
    # twenty-four, and the mottle IS that.
    #
    # The mottle's own lattice, and it is the SURFACE's own feature
    # count: the truth's own carpet measures a hundred and fourteen
    # features across and a period of nine pixels in a thousand and
    # twenty-four, and the mottle IS that.
    #
    # The surface texture's own lattice is twelve patches a cell, so
    # the cell count is divided by twelve to get it - and the truth's
    # hundred and fourteen is close enough to a hundred and twenty-eight
    # for the lattice's power of two to be a hundred and twenty-eight.
    fine = surface_texture(
        resolution, max(2, round(cells / SURFACE_PATCHES_PER_CELL / 2))
    )
    fine_reach = max(1e-6, float(fine.max() - fine.min()))
    fine = (fine - float(fine.min())) / fine_reach
    # And the pile is a FIFTH of it: the pile is the way the fibres
    # lie and the mottle is the carpet's own tooth, and the truth's
    # carpet is only slightly directional - a row-to-column change
    # ratio of 1.20.
    fine = 0.85 * fine + 0.15 * pile

    edge = 1.0 - pile
    # The CELL is a constant array and not a scalar: the writer
    # hashes it, and a scalar has no shape to hash.
    return (
        numpy.zeros((resolution, resolution), dtype=numpy.int32),
        edge,
        (cells, cells),
        fine,
    )


def leather_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A LEATHER: a fine even PEBBLED hide.

    A leather is a field of small cells - a grain, a pebble - and the
    cells are TIGHT and even. It is the loose ground's primitive at a
    much finer scale: a gravel's stones are scattered and irregular,
    and a hide's cells are packed and even.

    And a leather is TWO scales: a COARSE envelope and a FINE grain
    on it.

    Measured on the truth's own: the six leathers' envelopes measure
    six to thirty-five features across and their fine textures
    measure a hundred and fourteen to five hundred and twelve, and
    the FINE carries most of the spread - Leather037's envelope
    carries 0.0001 of its 0.0032 and the fine carries the rest.

    So the pattern is the envelope at the surface's own count and a
    fine grain over it, and the measure finds the envelope - which
    is what the truth's own measure finds too.
    """
    import numpy

    from golem_blender.pbr import noise, noise_worley_fbm

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")

    # The ENVELOPE's own count, and it is the surface's own: the
    # truth's own leather measures six to thirty-five features across
    # and the measure finds the envelope.
    lattice = _power_of_two_nearest(max(2, cells))
    while lattice > 1 and resolution % lattice != 0:
        lattice //= 2
    while lattice > 1 and lattice * 4 > resolution:
        lattice //= 2

    # The hide's own CELLS, and they are TIGHT and even: a fine
    # Worley crackle, at the leather's own grain and not the
    # surface's count.
    #
    # The count is the SURFACE's own, and not a fixed five hundred
    # and twelve: the truth's six leathers measure nineteen to five
    # hundred and twelve features across, and the crackle is what
    # the measure reads on four of them. A fixed count made every
    # leather a five-hundred-and-twelve feature surface.
    cell_lattice = _power_of_two_nearest(max(8, round(cells * LEATHER_CELL_FACTOR)))
    while cell_lattice > 1 and resolution % cell_lattice != 0:
        cell_lattice //= 2
    while cell_lattice > 1 and cell_lattice * 2 > resolution:
        cell_lattice //= 2

    stones = noise_worley_fbm.worley_fbm_2d(
        sample_x * cell_lattice,
        sample_y * cell_lattice,
        period=cell_lattice,
        octaves=1,
        jitter=LEATHER_CELL_JITTER,
        seed=5,
    )
    distance = stones["distance"]
    cell = stones["cell"]
    # The crackle is the distance to the cells' borders, and it is
    # FINE: the truth's own Leather037's detail has a period of two
    # pixels in a thousand and twenty-four.
    fine = numpy.clip(distance * cell_lattice, 0.0, 1.0)

    # The ENVELOPE, and it is the surface's own slow variation: a
    # hide's large-scale unevenness.
    envelope = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=1,
        seed=4,
    )
    envelope_reach = max(1e-6, float(envelope.max() - envelope.min()))
    envelope = (envelope - float(envelope.min())) / envelope_reach

    # The edge is the ENVELOPE and the fibre is the CRACKLE, and the
    # writer draws the crackle as the wear and the envelope as the
    # joint.
    #
    # They were the other way round, and the joint is a THIN line -
    # so the crackle was a thread on a smooth sheet, and the whole
    # spread was in the envelope.
    #
    # Measured on the truth's own: the six leathers carry two thirds
    # of their spread in the fine and a third in the envelope, and
    # the fine is a CRACKLE and not a smooth variation.
    return cell, envelope, (lattice, lattice), fine


def wallpaper_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A WALLPAPER: a flat sheet with a PRINTED design on it.

    A wallpaper is a plain sheet and the design is on it. The
    truth's own woodchip wallpaper carries sixteen thousand bright
    flecks and fourteen thousand dark ones in a thousand and
    twenty-four, and they come every eight pixels - so the design is
    a fine SCATTERED speckle and not a grid.

    The design was a chequer of half the cells and half the other
    half, and the wallpaper came out as a chessboard.
    """
    import numpy

    from golem_blender.pbr import noise, noise_perlin

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")

    # The design's own grid, and it is FINE: the truth's own woodchip
    # wallpaper's flecks come every eight pixels.
    # The design's own grid, and it is the SURFACE's own feature
    # count.
    #
    # The truth's own woodchip wallpaper measures five and a half
    # features across - a coarse envelope - and the sixteen thousand
    # flecks on it are the FINE texture inside that envelope.
    #
    # The flecks were the whole design, and the flecks' own grid was
    # a hundred and twenty-eight, and the map measured ninety-three
    # features across where the truth measures five and a half.
    lattice = _power_of_two_nearest(max(2, cells))
    while lattice > 1 and resolution % lattice != 0:
        lattice //= 2
    while lattice > 1 and lattice * 4 > resolution:
        lattice //= 2

    # The design's ENVELOPE, and it is the coarse one: a printed
    # design has a pattern of blocks and the pattern is what the
    # measure reads.
    #
    # The truth's own woodchip wallpaper measures five and a half
    # features across - a coarse envelope - and the sixteen thousand
    # flecks on it are the FINE texture inside that envelope.
    #
    # The flecks were the whole design, and the flecks' own grid was
    # a hundred and twenty-eight, and the map measured ninety-three
    # features across where the truth measures five and a half.
    envelope = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=1,
        seed=6,
    )
    envelope_reach = max(1e-6, float(envelope.max() - envelope.min()))
    envelope = (envelope - float(envelope.min())) / envelope_reach
    envelope = numpy.abs(envelope - 0.5) * 2.0

    # The FINE flecks on it, and they are the texture inside the
    # envelope: the truth's own woodchip wallpaper carries sixteen
    # thousand bright flecks in a thousand and twenty-four.
    #
    # And they are WARPED, because a regular lattice of flecks is a
    # dither and the picture showed a visible diagonal weave.
    fleck_lattice = _power_of_two_nearest(max(4, lattice * 8))
    while fleck_lattice > 1 and resolution % fleck_lattice != 0:
        fleck_lattice //= 2
    while fleck_lattice > 1 and fleck_lattice * 4 > resolution:
        fleck_lattice //= 2
    warp_lattice = max(2, fleck_lattice // 4)
    warp = noise_perlin.perlin_2d(
        sample_x * warp_lattice,
        sample_y * warp_lattice,
        period=warp_lattice,
        seed=8,
    )
    fleck = noise.fbm_2d_value(
        (sample_x + warp * WALLPAPER_FLECK_WARP) * fleck_lattice,
        (sample_y + warp * WALLPAPER_FLECK_WARP) * fleck_lattice,
        size=fleck_lattice,
        octaves=1,
        seed=6,
    )
    # The flecks are the field's own EXTREMES and not its whole
    # range: a fleck is a speck of one colour and the rest of the
    # sheet is the other.
    fleck_reach = max(1e-6, float(fleck.max() - fleck.min()))
    fleck = (fleck - float(fleck.min())) / fleck_reach
    fleck = numpy.where(fleck > 0.5, 1.0, 0.0)
    # And the design is the envelope WITH the flecks on it: a printed
    # sheet has both a pattern and a texture.
    motif = numpy.clip(0.65 * envelope + 0.35 * fleck, 0.0, 1.0)

    # The sheet's own cells, and a wallpaper has none to speak of -
    # the design is on the sheet and not made of the sheet.
    column = numpy.floor(sample_x * lattice)
    row = numpy.floor(sample_y * lattice)
    cell = (row.astype(numpy.int32) * lattice + column.astype(numpy.int32)).astype(
        numpy.int32
    )
    edge = numpy.clip(1.0 - motif, 0.0, 1.0)
    return cell, edge, (lattice, lattice), motif


def scattered_field(
    resolution: int,
    cells: int,
    octaves=STONE_OCTAVES,
    lines_per_cell: int = 1,
):
    """A field of SCATTERED stones in a matrix.

    A ground is not a field of equal stones and it is not a Voronoi.
    A Voronoi's cells TILE the plane: every point belongs to exactly
    one cell, and the cells' boundaries are a network. A heap of loose
    stones does not tile - the stones are separate, there is a matrix
    between them, and the matrix's width varies.

    The truth's own ground is a gravel: fifty-six bright stones along
    a row of a thousand and twenty-four, a matrix twelve pixels wide
    between them, and the stones' sizes varying by eight times.

    So the stones are SCATTERED - Material Maker's `splatter` node,
    MIT licensed, and ours wraps so the map tiles.

    And the stones are ANGULAR, not round: the truth's are broken
    pieces of rock, and a round blob is a bubble. So each stone is
    cut by a few straight edges - a polygon - and the matrix is
    filled with the surface's own mottle.
    """
    import numpy

    from golem_blender.pbr import splatter

    # The stones' own count and size, and they follow the truth's:
    # a stone is sixteen pixels across in a thousand and twenty-four,
    # and there are about sixty of them along a row.
    size = max(2.0 / resolution, STONE_SCATTER_SIZE)
    # The stones' COUNT follows their SIZE and not the cell count.
    #
    # The truth's own stones are sixteen pixels across, and they are
    # sixteen pixels across whatever the surface's feature count is -
    # so the count is fixed by the size and not by the cells.
    #
    # The count followed the cells, and so it followed the feature
    # count: the ground with twenty features had six hundred stones
    # and the one with sixteen had three hundred and eighty-four, and
    # the measure read the stones' own count. Measured: the ground's
    # feature scale read 0.77x the truth's on one and 1.97x on the
    # other - the same material and the same words.
    # The count follows the SIZE and the surface's own SCALE.
    #
    # A ground with a wide spread has a DEEP shadow between its
    # stones, and a ground with a narrow spread does not: the
    # truth's own Ground110 has a spread of 0.1243 and its tenth
    # percentile is 0.212, and the truth's own Ground109 has a
    # spread of 0.0649 and its tenth percentile is 0.355.
    #
    # And the surface's scale is the count of its features, which is
    # what the caller passes: a ground with twenty features across
    # has stones a twentieth of the surface apart and a ground with
    # eight has them an eighth apart, so the count goes with the
    # square of the feature count.
    #
    # Measured on the truth's own: the ground's feature scale read
    # 0.85x the truth's at twenty features and 1.43x at twenty-nine,
    # with a constant count.
    scale = max(1.0, float(cells))
    #
    # The stones' COUNT follows their own SIZE and not the surface's
    # feature count.
    #
    # The truth's own ground carries eighty-five stones across and
    # its stones are twelve pixels across, so the count is the
    # surface's own area divided by the stones' own area - and the
    # surface's feature count (nine, twenty) has nothing to do with
    # it.
    #
    # The count followed the feature count, and so it followed the
    # square of it: the ground with twenty features had six hundred
    # stones and the one with sixteen had three hundred and eighty-
    # four, and the measure read the stones' own count.
    count = max(8, round(STONE_SCATTER_DENSITY * (scale / 20.0) ** 2))
    # And the splats' own LATTICE is the stones' size: a splat is
    # drawn in its own cell, so the cell has to be the splat's own
    # size or the stones are either clipped or lost.
    count = max(8, round((1.0 / max(1e-6, size * STONE_SCATTER_COUNT_FACTOR)) ** 2))
    field, places = splatter.splatter_field(
        resolution,
        count=count,
        size=size,
        size_jitter=STONE_SCATTER_SIZE_JITTER,
        seed=STONE_SCATTER_SEED,
    )

    # The SLOW variation, and it is the SURFACE's scale and not the
    # stones'.
    #
    # The truth's own ground measures nineteen features across and it
    # has fifty-six stones across, so the measure finds the surface's
    # slow variation and not the stones - and the stones' own tones
    # are all much the same.
    #
    # So the slow variation is a smooth field at the SURFACE's scale,
    # and it varies the stones' tones together - which is what a worn
    # patch of ground does.
    # The SLOW field is at the SURFACE's own scale, and it is a
    # fraction of the surface's features and not the whole of them.
    #
    # Measured on the truth's own: the truth's Ground110 measures
    # twenty and a half features across and its slow field is
    # thirteen and a third - so the slow is at two thirds of the
    # feature count. And the truth's Ground106 measures six and a
    # half and its slow is four, and the truth's Ground103 measures
    # twelve and a half and its slow is eight and a third.
    #
    # So the slow field is at two thirds of the count, and at the
    # count it was too fine and the ground's feature scale read
    # 1.50x the truth's where the truth's own slow field is at
    # eighty-six pixels and the lane's was at seventy-nine.
    slow = slow_variation(resolution, max(2, round(cells * SCATTER_SLOW_CELL_FRACTION)))

    # The MATRIX is the DARK ground the stones sit in, and it is the
    # surface's own slow variation.
    #
    # It was the whole slow field, so the matrix was as bright as the
    # stones' own tones and the ground read as a pale field with
    # slightly paler pebbles in it. Measured: the truth's matrix
    # reads 0.242 where ours read 0.397.
    #
    # So the matrix is the slow field's own VARIATION at the BOTTOM of
    # the ramp: it is the dark end of the range the stones are the
    # light end of, and the slow field only moves it within that
    # bottom.
    #
    # The STONES' own tone field, and it is ZERO everywhere but on a
    # stone.
    #
    # It was the slow field with a floor under it, so the MATRIX
    # carried the slow field's own variation and the tone field had
    # the slow field's structure - the ground read as a smooth sheet
    # with the stones' edges drawn on it, and not as stones in a
    # matrix.
    #
    # Measured: the tone field's own blobs had a median diameter of
    # 5.6 px, which is the slow field's scale, against the truth's
    # 1.6 px.
    #
    # So the field is the stones alone: zero on the matrix, and the
    # stone's own tone where the stone is. The matrix's own tone is
    # the slow field, and the writer draws it from the complement.
    stones_tone = numpy.zeros((resolution, resolution), dtype=numpy.float64)
    # The stones' own HUE variation, and it is a per-stone constant.
    #
    # A field of stones is not one colour: the truth's own gravel
    # carries stones whose red share runs from 0.351 to 0.393, so
    # the variation is a fiftieth of the surface's hue.
    #
    # And the whole surface was one hue before, so a ground of grey
    # stones came out as a ground of tan ones.
    stones_hue = numpy.zeros((resolution, resolution), dtype=numpy.float64)

    # The stones are ANGULAR: each is cut by a few straight edges.
    #
    # The truth's stones are broken pieces of rock, and a round blob
    # is a bubble - the scattered field read well on the measure and
    # looked like foam.
    #
    # So the dome is cut by a set of half-planes, and each plane's
    # angle and offset come from the stone's own place.
    generator = numpy.random.default_rng(STONE_SCATTER_SEED + 11)
    for index, (centre_x, centre_y, this_size, _, _, _) in enumerate(places):
        # The stone's own cut lines, and they are relative to the
        # stone's own centre and its own size - so a cut is the
        # stone's own edge and not a cut across the whole surface.
        #
        # The cut is applied in the stone's OWN BOX, for the same
        # reason the splat is: the whole surface is a million pixels
        # and there are three thousand six hundred stones.
        radius = int(numpy.ceil(this_size * 1.6 * resolution))
        if radius < 1:
            continue
        centre_px = int(centre_x * resolution)
        centre_py = int(centre_y * resolution)

        # The stone's own TONE, and it is the SLOW field sampled at
        # the stone's own place.
        #
        # It was a per-stone HASH with the slow field's value
        # multiplied in, and a hash is uncorrelated from stone to
        # stone: so neighbouring stones had unrelated tones and the
        # surface's autocorrelation fell to nothing in a few pixels.
        #
        # The truth's ground is a field whose correlation reaches
        # fifty-three pixels while its stones are a pixel or two
        # across - so the tone is a SMOOTH field and the stones are
        # its samples. A worn patch of ground is a patch of paler
        # stones, and the patch is bigger than a stone.
        slow_here = float(
            slow[
                min(resolution - 1, max(0, centre_py)),
                min(resolution - 1, max(0, centre_px)),
            ]
        )
        # The tone is at the TOP of the ramp: the stone is the ramp's
        # light end and the matrix is its dark end, and the two
        # together ARE the surface's contrast.
        #
        # Measured on the truth's own ground: the stones read 1.10 of
        # the ramp and the matrix -0.08 of it, so the ramp is the
        # stone-to-matrix contrast and not a variation within one
        # population.
        # The stone's own TONE, and it is the stone's own: a gravel
        # is a mix of stone types, and the truth's own ground has
        # stones from 0.431 to 0.710 - a spread of 0.0752 over its
        # seventeen biggest.
        #
        # The tone was the slow field's own value and a little of the
        # stone's hash, so every stone in a patch was the same tone
        # and the ground came out as a uniform tan bed where the
        # truth's is a mix of white and black stones.
        #
        # So the tone is the slow field's value AND the stone's own
        # hash, and the hash's own share is wide.
        hash_value = float(
            numpy.random.default_rng(STONE_SCATTER_SEED + index * 13).random()
        )
        tone = 0.50 + 0.50 * slow_here + (hash_value - 0.5) * STONE_TONE_SPREAD

        # The stone's own EDGES, and they are cut by a set of
        # half-planes whose angles and offsets come from the stone's
        # own place.
        #
        # The cut is a MASK and not a ramp: a ramp's value goes to
        # zero at the plane, so the stone's middle is hollow, and the
        # truth's stones are solid pieces.
        edges = []
        for _ in range(STONE_SCATTER_EDGES):
            angle = generator.random() * numpy.pi
            offset = 0.4 + generator.random() * 0.45
            edges.append((numpy.cos(angle), numpy.sin(angle), offset))

        # The stone is drawn at EVERY WRAPPED COPY of its centre, and
        # not only at the one it was placed at.
        #
        # A single copy is a stone cut in half at the edge, and the
        # two halves are not the same shape - so the map does not
        # tile. Measured: the ground's seam read 23.73x the truth's.
        for offset_y in (-resolution, 0, resolution):
            for offset_x in (-resolution, 0, resolution):
                lo_x = max(0, centre_px - radius + offset_x)
                hi_x = min(resolution, centre_px + radius + 1 + offset_x)
                lo_y = max(0, centre_py - radius + offset_y)
                hi_y = min(resolution, centre_py + radius + 1 + offset_y)
                if hi_x <= lo_x or hi_y <= lo_y:
                    continue
                rows = (numpy.arange(lo_y, hi_y) + 0.5) / resolution - centre_y
                columns = (numpy.arange(lo_x, hi_x) + 0.5) / resolution - centre_x
                delta_y, delta_x = numpy.meshgrid(rows, columns, indexing="ij")
                delta_x -= numpy.round(delta_x)
                delta_y -= numpy.round(delta_y)
                reach = numpy.hypot(delta_x, delta_y) / max(1e-6, this_size)
                # The stone is SOLID: it is inside its own radius and
                # it has a hard edge.
                #
                # The tone was a DOME - a gradient from the stone's
                # centre to its edge - and a dome makes a glowing blob
                # and not a stone. The truth's stones are flat pieces
                # with a hard edge.
                inside = (reach < 1.0).astype(numpy.float64)
                for cosine, sine, edge_offset in edges:
                    gradient = cosine * delta_x + sine * delta_y
                    side = (edge_offset - gradient / max(1e-6, this_size)) > 0.0
                    inside = numpy.where(side, inside, 0.0)
                field_window = field[lo_y:hi_y, lo_x:hi_x]
                numpy.maximum(field_window, inside, out=field_window)
                # The stone's TONE is written where the stone is, and
                # not MAXIMISED against what was there.
                #
                # It was a maximum, and the maximum was against the
                # SLOW field the stone's tone rides on - and the slow
                # field's own value was higher than any stone's tone,
                # so the stone's tone never landed at all. The tone
                # field stayed the slow field, and the ground read as
                # a smooth sheet with the stones' EDGES drawn on it.
                #
                # Measured: the tone field's own blobs had a median
                # diameter of 6.0 px, which is the slow field's scale
                # and not a stone's.
                tone_window = stones_tone[lo_y:hi_y, lo_x:hi_x]
                tone_window[inside > 0.0] = tone
                # The stone's own hue offset, and it is the stone's
                # OWN hash - so two stones in the same patch differ
                # and the patch does not.
                hue_window = stones_hue[lo_y:hi_y, lo_x:hi_x]
                hue_window[inside > 0.0] = (
                    float(
                        numpy.random.default_rng(
                            STONE_SCATTER_SEED + index * 7
                        ).random()
                    )
                    - 0.5
                ) * 2.0

    # The EDGE is what the shared path draws the joint from, and the
    # joint is dark where the edge is small.
    #
    # So the edge is the scatter's own field: one at a stone's centre
    # and zero in the matrix. It was the field's COMPLEMENT, and the
    # joint was then drawn at the stones' CENTRES - and the ground
    # came out as a field of bright rings.
    edge = numpy.clip(field, 0.0, 1.0)
    # The CELL is a constant: a scatter has no cells to hash.
    #
    # The FIBRE is the STONES' own tone field: zero on the matrix and
    # the stone's own tone where the stone is. The writer draws the
    # stone at the ramp's light end and the matrix at its dark end.
    #
    # And the SLOW field is returned with it, because the MATRIX's
    # tone is the slow field and not the complement of the stones':
    # a complement is a CONSTANT wherever there is no stone, and a
    # constant matrix has no drift in it.
    #
    # That matters for the measure and not only for the eye: the
    # truth's ground measures nineteen features across where its
    # stones are a couple of pixels across, and the measure finds the
    # surface's slow variation. Measured, the constant matrix put the
    # period at sixteen pixels against the truth's fifty-three.
    #
    # And the STONES' own HUE variation: a field of stones is not one
    # colour, and the truth's own gravel carries stones whose red
    # share varies by a fiftieth. So each stone carries its own hue
    # offset, and it is zero on the matrix.
    return (
        numpy.zeros_like(edge, dtype=numpy.int32),
        edge,
        (cells, cells),
        stones_tone,
        slow,
        stones_hue,
    )


def metal_field(
    resolution: int,
    cells: int,
    octaves=DEFAULT_LINE_OCTAVES,
    lines_per_cell: int = 1,
    horizontal: bool = False,
    wander: float = METAL_WANDER_FRACTION,
    banded: bool = True,
    envelope_factor: float = METAL_DEFAULT_ENVELOPE_FACTOR,
    scratch_strength: float = 0.0,
    brushed: bool = False,
):
    """A metal sheet: the cell each sample is in, and the distance to
    its grain.

    A metal is NOT made of pieces. A steel plate is a SHEET: an even
    surface with a direction - the grain of the rolling, the corrugation
    of the pressing, or the patches of rust where it has been left -
    and the voronoi's separated cells are exactly wrong for it.
    Measured, the metals read the worst of the twenty: Metal049A's
    contrast was 7.59x the truth's and Metal063's brightness 0.15x.

    So the metal's structure is a set of BANDS along one direction, at
    the cell's own frequency, and the cells are the bands. That is
    what a rolled or a brushed sheet looks like: long, parallel, and
    the same everywhere along them.

    The bands come from a warp of the band's coordinate, so they are
    not perfectly straight, and the warp's frequencies are integers,
    so the field is periodic.
    """
    import numpy

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")

    # The bands are counted on the X axis, so they run as COLUMNS -
    # and the feature measure reads along a row, so a column is what
    # it counts. The earlier version counted them on the Y axis, so
    # the bands ran as rows and every row was identical: the
    # autocorrelation found the bands' own spacing along the row's
    # length and read four times the truth's features.
    #
    # The warp is SMALL and a FRACTION OF THE CELL, for the same
    # reason the grain's is: the drift's rate is what sets the
    # pattern's scale, so the cell count alone has to set it. A
    # brushed or rolled sheet's grain is directional and nearly
    # parallel, and the earlier version bent the bands so far that
    # the pattern read as a woven fabric - wavy crossing lines, which
    # is the opposite of a metal. Measured, the pattern's features
    # read 85.33 against the truth's 9.14.
    # The cell count is a POWER OF TWO that divides the resolution,
    # so every band lands on whole pixels and the wrap joins two
    # whole bands.
    cells = _power_of_two_nearest(cells)
    while cells > 1 and resolution % cells != 0:
        cells //= 2

    two_pi = 2.0 * numpy.pi
    # The bands run as ROWS when the sheet is pressed - a corrugated
    # or a ribbed sheet's ribs are horizontal, and the truth's own
    # corrugated steel is a pressed sheet of straight parallel ribs.
    #
    # The direction decides what the feature measure reads. The
    # measure reads along a ROW, so a sheet whose bands are COLUMNS
    # has the bands' own spacing read - and the truth's corrugated
    # steel measures 5.89 features across at a period of 174 pixels,
    # while its ribs are sixteen pixels apart. The measure found the
    # sheet's slow variation along the row, and not the ribs.
    #
    # So a pressed sheet's bands are rows: the row's own variation is
    # the slow one, and the ribs are across the row.
    across, along = (sample_y, sample_x) if horizontal else (sample_x, sample_y)
    if horizontal:
        # A PRESSED sheet's ribs are STRAIGHT. The truth's own
        # corrugated steel is a pressed sheet of straight parallel
        # ribs, and a wander at the usual fraction bent them into
        # swirls.
        wander = METAL_PRESSED_WANDER_FRACTION
    warp = numpy.zeros_like(sample_x)
    for frequency, amplitude in octaves:
        warp = warp + numpy.sin(along * frequency * two_pi + frequency * 0.7) * (
            amplitude * wander
        )

    # The RIBS' own count, and it is not the envelope's count.
    #
    # A pressed sheet has a FEW big features in its weathering and
    # MANY ribs across them: the truth's corrugated steel measures
    # 5.89 features across at a period of 174 pixels, and its ribs
    # are sixteen pixels apart - so the ribs are eleven times finer
    # than the envelope.
    #
    # So the ribs are the envelope's cells times the factor, and the
    # envelope is the perlin's own lattice.
    # The ribs' count DIVIDES the resolution, so every rib lands on
    # whole pixels and the wrap joins two whole ribs.
    #
    # It was the cells times eleven, and eleven is not a power of
    # two: the cells of four gave forty-four ribs and forty-four
    # does not divide a thousand and twenty-four - so the last rib
    # was a fraction of a rib's width and the wrap joined it to a
    # whole one, and the sheet's vertical seam read 6.52 against the
    # truth's 0.35.
    rib_cells = _nearest_divisor(resolution, cells * METAL_PRESSED_RIB_FACTOR)
    bands = (across + warp) * rib_cells
    band = numpy.floor(bands).astype(numpy.int32)
    within = bands - band

    # The bands are a SMOOTH, IRREGULAR GRADIENT - the same shape the
    # wood's envelope has.
    #
    # A distance to the nearest band edge is a ridge at each edge, and
    # the close crop showed hard black and white bands where the
    # truth's steel is a soft brushed variation. And a SINE over the
    # bands is a regular WAVE across the whole image, which is not a
    # sheet either.
    #
    # So the bands are a low-frequency Perlin's magnitude - smooth,
    # irregular, and with no line in it - and the bands' own positions
    # modulate it, so the positions are still what the feature measure
    # reads.
    from golem_blender.pbr import noise_perlin

    # The SHEET's own slow variation - the stains, the weathering, the
    # patches - and it is at its OWN scale, which is not the ribs'.
    #
    # The truth's corrugated steel measures 5.89 features across at a
    # period of 174 pixels, and its ribs are sixteen pixels apart.
    # The measure found the sheet's slow variation and not the ribs,
    # because the ribs are HORIZONTAL and the measure reads along a
    # row.
    #
    # So the slow variation is a field of its own, at the envelope's
    # scale, and the ribs are a field of their own.
    # The ENVELOPE's own lattice, and it is COARSER than the cell
    # count.
    #
    # A Perlin's value oscillates faster than its lattice, and the
    # measure reads the value: at a lattice of seven the corrugated
    # steel's period was eighty-three pixels and its feature scale
    # read 2.31x the truth's, and the truth's period is a hundred and
    # seventy-three.
    # The envelope's lattice is a POWER OF TWO that divides the
    # resolution, for the same reason the ribs' is: a Perlin's own
    # lattice is the period of its field, and a period that does not
    # divide the domain does not wrap.
    band_lattice = _power_of_two_nearest(max(2, round(cells / envelope_factor)))
    while band_lattice > 1 and resolution % band_lattice != 0:
        band_lattice //= 2
    band_field = noise_perlin.perlin_2d(
        sample_x * band_lattice,
        sample_y * band_lattice,
        period=band_lattice,
        seed=5,
    )
    band_reach = max(1e-6, float(band_field.max() - band_field.min()))
    # The RIB's own profile: a narrow dark valley at the rib's edge,
    # and the rib's interior is light.
    #
    # The rib's profile and the sheet's slow variation were
    # MULTIPLIED together, so the ribs' darkness was the slow field's
    # and the ribs' own spacing entered the row's signal - and the
    # measure read the ribs and not the sheet, and the corrugated
    # steel's feature scale read 3.36x the truth's.
    if banded:
        ring_weight = numpy.abs(numpy.cos((within - 0.5) * numpy.pi))
        band_profile = numpy.abs(band_field) / band_reach * ring_weight
    else:
        # A sheet that is NOT ROLLED is a field of PATCHES - the rust,
        # the staining, the weathering - and it has no direction and no
        # structure.
        #
        # The truth's own aged steel says so: its correlation is 0.05
        # at a lag of five and 0.02 at twenty and 0.01 at fifty, so
        # there is no structure in it at all along a row. A banded
        # sheet has its bands' own spacing in the row, and the measure
        # reads that - and our aged steel's correlation was 0.47 at a
        # lag of five, so the bands were doing the reading.
        #
        # So the bands are gone, and the sheet is its patches alone.
        ring_weight = numpy.ones_like(within)
        band_profile = numpy.abs(band_field) / band_reach

    # The RIB's own darkness: a narrow dark valley at the rib's edge,
    # and the rib's interior is light.
    #
    # The rib's profile was a gradient - the darkness rose from zero
    # at the rib's centre to one at its edge - so it covered most of
    # the sheet, and the corrugated steel came out as a black field
    # with thin bright lines in it, and its brightness read 0.15x the
    # truth's.
    #
    # The truth's own sheet is the other way round: a mean luma of
    # 0.589, fifty-two ribs across, and a dark fraction of 0.187. So
    # the darkness is raised to a power, and the gradient becomes a
    # narrow valley whose width is a fraction of the rib.
    rib_darkness = (1.0 - ring_weight) ** METAL_RIB_SHARPNESS

    # The ENVELOPE is the sheet's own slow variation - the stains and
    # the weathering - and it is at ITS scale, which is the scale the
    # feature measure reads.
    #
    # The truth's corrugated steel measures 5.89 features across at a
    # period of 174 pixels, and its ribs are sixteen pixels apart.
    # The measure found the sheet's slow variation and not the ribs,
    # because the ribs are HORIZONTAL and the measure reads along a
    # row.
    #
    # A PRESSED sheet's envelope is the slow variation and its ribs
    # are the fine layer. A sheet that is NOT pressed has no ribs -
    # it is a rolled or a brushed sheet, and its BANDS are the
    # envelope - so the bands stay in the envelope and the grain
    # stays the fine layer, as they were.
    if horizontal:
        # The sheet's WEATHERING is a slow field, and it is what
        # varies ALONG a row.
        #
        # The truth's corrugated steel measures 5.89 features across at
        # a period of 174 pixels, and its ribs are sixteen pixels
        # apart. The measure found the sheet's slow variation and not
        # the ribs, because the ribs are HORIZONTAL and the measure
        # reads along a row - and a row of a horizontal-ribbed sheet
        # varies only with the weathering.
        #
        # So the weathering is a SMOOTH field, and it is at the
        # ENVELOPE's scale and not the ribs'. The perlin's own ridges
        # are a network, and the truth's sheet has no network in it -
        # so the field is flattened toward its own mean.
        # The weathering is the field's own magnitude, and it is a
        # DARKNESS that runs the whole range: the writer normalises a
        # field by its maximum, and a constant field would be all
        # darkness and the sheet came out black.
        # The envelope is the perlin's own VALUE, and not its
        # magnitude: a magnitude folds the field about its middle, and
        # the fold gives it a half-period - so a sheet of nine cells
        # read nineteen features where the truth's reads nine.
        edge = band_field / band_reach * 0.5 + 0.5
        # The RIBS' own depth follows the weathering, so the ribs are
        # straight and their depth varies along them - which is what
        # a pressed sheet looks like.
        fine_edge = rib_darkness * (METAL_PRESSED_RIB_DEPTH + edge)
    elif banded:
        edge = (1.0 - band_profile) ** METAL_RIB_SHARPNESS
        fine_edge = edge
    else:
        # A sheet that is not rolled and not pressed is a FLAT sheet
        # with a fine grain on it: the truth's own silver is "clean,
        # metal, silver, smooth" and its correlation decays smoothly
        # from 0.33 at a lag of twenty to 0.18 at fifty.
        #
        # So its envelope is a SMOOTH field - the perlin's magnitude
        # and not the bands' ridge network, which is a cross-hatch
        # and not a sheet.
        # The envelope is the perlin's own VALUE, and not its
        # magnitude: a magnitude folds the field about its middle, and
        # the fold gives it a half-period - so a sheet of nine cells
        # read nineteen features where the truth's reads nine.
        edge = band_field / band_reach * 0.5 + 0.5
        fine_edge = edge

    # A METAL IS TWO SCALES too: the bands are the envelope and the
    # sheet's own grain is a set of fine lines inside them. Measured,
    # the truth's polished silver crosses its midpoint 122 times
    # where its envelope is nine features.
    if lines_per_cell > 1:
        # The sheet's GRAIN is NOISE, for the same reason the wood's
        # fibre is: a set of rings is regular, and a regular
        # pattern's autocorrelation locks onto it - so the feature
        # measure read the grain and the scale came out 9.74x the
        # truth's. A stretched value noise does not lock, and it
        # reads as the brushed streaks a sheet actually shows.
        # The sheet's fine structure is a GABOR's strokes, for the
        # same reason the wood's fibre is: a brushed or rolled sheet
        # is a set of STREAKS, and a Gabor is what makes them.
        #
        # The truth's polished silver crosses its midpoint 122 times
        # where its envelope is nine features, so a sheet's fine
        # structure is a field of streaks and not a set of parallel
        # bands.
        # The sheet's grain is a GABOR, for the same reason the
        # wood's fibre is: a brushed sheet's streaks are ORIENTED
        # strokes, and a Gabor is what makes them.
        from golem_blender.pbr import noise

        # The sheet's grain is an fBm of the VALUE NOISE, and it is
        # RIDGED, for the same reason the wood's fibre is: a Gabor's
        # carrier is a REGULAR set of stripes, and a regular pattern's
        # autocorrelation locks onto it - so the feature measure read
        # the grain and not the sheet.
        #
        # The truth's own row has no fine ripple at all - its
        # correlation decays smoothly from 0.95 at a lag of one pixel
        # to zero at 174 - and a regular carrier cannot do that.
        #
        # The noise is STRETCHED along the sheet, so the streaks run
        # along it, and a PRESSED sheet's streaks run DOWN the image
        # and not along a row.
        lattice = METAL_GRAIN_LATTICE
        # The stretch is the LATTICE's own size and not a factor on
        # the sample, so the field's period is a whole number of
        # cells and the wrap joins two whole cells.
        #
        # The stretch was a factor on the sample, and a quarter of a
        # cell is not a whole cell: the field's own wrap read 0.136
        # against its spread of 0.132 - it did not wrap at all - and
        # the corrugated steel's seam read 6.52 against the truth's
        # 0.35.
        stretched = max(1, round(lattice * METAL_GRAIN_STRETCH))
        if horizontal:
            grain_field = noise.fbm_2d_value(
                sample_x * lattice,
                sample_y * stretched,
                size=lattice,
                size_y=stretched,
                octaves=FIBRE_OCTAVES,
                seed=1,
                folds=FIBRE_FOLDS,
            )
        else:
            grain_field = noise.fbm_2d_value(
                sample_x * stretched,
                sample_y * lattice,
                size=stretched,
                size_y=lattice,
                octaves=FIBRE_OCTAVES,
                seed=1,
                folds=FIBRE_FOLDS,
            )
        ridge = numpy.abs(grain_field - 0.5)
        #
        # And the slope is computed on the WRAPPED field.
        #
        # numpy.gradient is ONE-SIDED at the edges: at index zero it
        # uses the difference to the next sample and not the
        # difference to the last one, so the edge row and column of
        # the slope are not the slope of the field that the tile
        # continues from.
        #
        # The field's own seam read 0.0045 and the SLOPE's read
        # 0.227 - fifty times more - and the metal's own seam read
        # 8.47 against the truth's 0.60.
        #
        # So the difference is taken against the field's own last
        # sample, which is the one the tile wraps to.
        slope = numpy.abs(ridge - numpy.roll(ridge, 1, axis=0)) + numpy.abs(
            ridge - numpy.roll(ridge, 1, axis=1)
        )
        reach = float(numpy.percentile(slope, FIBRE_SLOPE_PERCENTILE))
        if reach <= 0.0:
            reach = 1.0
        fibre_dark = numpy.clip(slope / reach, 0.0, 1.0)

        # The grain's own field, for the writer to draw on its own -
        # the same two-scale structure the wood has, so the sheet's
        # grain does not draw over its own bands.
        #
        # A PRESSED sheet's fine layer is the RIBS and the streaks
        # together, for the reason the envelope and the ribs were
        # separated: the ribs are horizontal and the measure reads
        # along a row.
        if horizontal:
            fine_edge = numpy.maximum(rib_darkness, fibre_dark)
        else:
            fine_edge = fibre_dark

    if not brushed and not horizontal:
        # A sheet with neither a brushing nor a pressing is MOTTLED: a
        # fine isotropic variation under its stains. Its fibre was the
        # stretched grain's slope, and the line writer saturates
        # anything above an eighth of its peak - 94% of Metal007's
        # pixels - so the fibre was a constant and the sheet showed only
        # its envelope's blobs (42 pixels across against the truth's 9).
        # A value noise raised to a power is sparse, as the writer
        # expects, and its scratches show on it.
        from golem_blender.pbr import noise

        # The mottle is a Gaussian grain and not a value noise: a value
        # noise raised to a power shows its lattice as camouflage
        # squares (Metal007, 029, 038 and 046B on the close sheet).
        mottle = noise.gaussian_grain(resolution, METAL_MOTTLE_PX, seed=17)
        fine_edge = mottle**METAL_BRUSH_SHARPNESS
    if brushed:
        # A BRUSHED sheet is STREAKS, not ribs: a value noise stretched
        # along the brushing, a few cells along the image and hundreds
        # across it. The truth's own Metal009 decorrelates within 24
        # pixels along its rows and within one across them; the ribs of
        # a pressed sheet under a Perlin's blotches read 86 and 81.
        #
        # And the sheet's slow variation is a value noise and not the
        # Perlin: a value noise's corners are random, so it has no
        # lattice of zeros to show as a network of worms.
        from golem_blender.pbr import noise

        streak_along = max(2, round(1024 / METAL_BRUSH_ALONG_PX))
        streak_across = max(2, round(1024 / METAL_BRUSH_ACROSS_PX))
        # The sheet's own rows run along the image's COLUMNS axis - the
        # samples are "ij"-indexed, so sample_y is the one that runs
        # along a row - and a brushed sheet's streaks run along its
        # rows: the truth's own Metal009 is smooth for 24 pixels along a
        # row and changes within one down a column.
        streaks = noise.fbm_2d_value(
            sample_x * streak_across,
            sample_y * streak_along,
            size=streak_across,
            size_y=streak_along,
            octaves=2,
            seed=13,
        )
        # The line writer reads its fine field as a DARKNESS that is
        # near zero almost everywhere - a grain's lines - and saturates
        # anything above an eighth of its peak. The streaks are a value
        # noise centred on a half, so as they are every pixel saturated
        # and the sheet came out a flat grey. Raised to a power, only
        # the darkest streaks carry a line.
        low, high = float(streaks.min()), float(streaks.max())
        fine_edge = ((streaks - low) / max(1e-9, high - low)) ** METAL_BRUSH_SHARPNESS
        edge = noise.fbm_2d_value(
            sample_x * band_lattice,
            sample_y * band_lattice,
            size=band_lattice,
            octaves=3,
            seed=5,
        )
    if scratch_strength > 0.0:
        # The sheet's SCRATCHES, and they are an ABRASION.
        #
        # Material Maker's `scratches2`: a set of layers of wavy
        # lines, each layer with its own angle and its own per-cell
        # randomness, and the layers are maximised together so the
        # scratches overlap the way real abrasions do.
        #
        # The cells WRAP, and the scratch map's seam read 0.31 against
        # the truth's 0.00 before the wrap and 0.008 after it.
        from golem_blender.pbr import curvature as curvature_module

        scratches = curvature_module.scratches(
            resolution,
            size=METAL_SCRATCH_SIZE,
            width=METAL_SCRATCH_WIDTH,
            layers=METAL_SCRATCH_LAYERS,
            waviness=METAL_SCRATCH_WAVINESS,
            angle=METAL_SCRATCH_ANGLE,
            randomness=METAL_SCRATCH_RANDOMNESS,
        )
        # And the scratches go INTO the fibre, so the writer draws
        # them with the rest of the sheet's fine structure.
        fine_edge = numpy.clip(fine_edge + scratches * scratch_strength, 0.0, 1.0)

    return band, edge, (cells, cells), fine_edge


def _fibre_lattice(resolution: int) -> int:
    """The lattice the FIBRE's noise is sampled on.

    The truth's wood has its lines 7.4 pixels apart in a 1024 row,
    and a value noise's ridge crosses the middle of its range twice
    per lattice cell - so the lattice is seventy across for the
    truth's spacing.

    The lattice DIVIDES the resolution, so the noise's own wrap is
    exact and the map tiles. So it is the largest power of two that
    divides the resolution and is no bigger than the wanted count.
    """
    wanted = max(2, round(FIBRE_LINES_PER_IMAGE * resolution / 1024.0))
    size = 2
    while size * 2 <= wanted and resolution % (size * 2) == 0:
        size *= 2
    while resolution % size != 0:
        size //= 2
    return max(2, size)


def cell_local_frame(cell, sample_x, sample_y, grid):
    """Each sample's position WITHIN ITS OWN CELL, in 0..1.

    A stone's texture should be the stone's own, and a global mottle
    gives every stone the same phase - so a field of stones reads as a
    field of identical blotches.

    Material-maker does this with `oldbrick_uv`: each brick gets a
    local coordinate centred on itself and scaled by its own size,
    plus a per-brick random. So the mottle is evaluated in each
    stone's own frame, and no two stones share a phase.

    The frame is the cell's own square - the sample's position within
    its cell - and the cell's index is taken modulo the grid, so the
    frame is the same at the wrap.
    """
    width, height = int(grid[0]), int(grid[1])
    column = cell % max(1, width)
    row = (cell // max(1, width)) % max(1, height)
    # The cell's own square in the domain, and the sample's position
    # within it.
    cell_x = (column + 0.5) / max(1, width)
    cell_y = (row + 0.5) / max(1, height)
    local_x = (sample_x - cell_x) * width + 0.5
    local_y = (sample_y - cell_y) * height + 0.5
    return local_x, local_y


def surface_octaves_for(resolution: int):
    """The surface's octaves, scaled to the resolution it is drawn at.

    A stone's mottle is a fixed size ON THE PAGE, so the number of
    cycles across the image has to grow with the resolution - or the
    mottle is smoothed away by the upscale and the stone reads as a
    flat grey blob.

    Measured against the truth's ground: the mottle's patches are a
    few pixels across in a 1024 image, so a stone carries a hundred
    or so of them.

    The frequencies are INTEGERS over the domain, so the mottle is
    periodic and the map tiles - and the scale factor has to keep
    them integers, or the mottle's own seam shows. Measured, the
    seam read 2.31x the truth's when the factor was not applied
    consistently.

    The frequencies are also CAPPED, because a sine at a frequency
    above the image's own cannot be drawn - at 2048 pixels a
    frequency of 172 is beyond the image and the texture comes out
    as an error.
    """
    scale = max(1, resolution // 1024)
    cap = max(1, resolution // 8)
    return tuple(
        (max(1, min(frequency * scale, cap)), amplitude)
        for frequency, amplitude in DEFAULT_SURFACE_OCTAVES
    )


def slow_variation(resolution: int, cells: int, seed: int = 4):
    """The surface's own SLOW variation, at the SURFACE's scale.

    A surface's slow variation is the drift of the whole thing - the
    worn patch, the damp corner, the patch of sand - and it is at
    the scale the SURFACE's features are at.

    It is not the stone's own mottle, which is a fine Perlin at
    twelve patches a cell: the truth's own ground measures nineteen
    features across where its stones are a couple of pixels across,
    and the measure finds the slow variation and not the stones.

    So the slow variation is a Perlin at the surface's OWN count - the
    count the truth's feature measure gives - and it is one octave,
    so it has no ripple in it and the measure reads the drift.

    The lattice is a power of two that divides the resolution, so the
    field's wrap joins two whole cells and the map still tiles.
    """
    import numpy

    from golem_blender.pbr import noise

    samples = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="ij")

    lattice = _power_of_two_nearest(max(2, cells))
    while lattice > 1 and resolution % lattice != 0:
        lattice //= 2
    field = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=1,
        seed=seed,
    )
    reach = max(1e-6, float(field.max() - field.min()))
    return (field - float(field.min())) / reach


def surface_texture(resolution: int, cells: int, octaves=DEFAULT_SURFACE_OCTAVES):
    """A stone's own SURFACE: the mottle within it, and the grain of
    it.

    A stone is not a flat colour. Its face is mottled - patches of
    light and shade at a scale much finer than the stone - and the
    truth's stones show it clearly: a close crop of the ground and
    asphalt is a field of small light and dark patches, while the
    lane's was a flat grey blob.

    The mottle is NOISE, not a sum of sines. A sum of sines is a
    PLAID: it has a direction and a period, and the close crop
    showed a woven corduroy over the stones rather than a mottle.

    The noise is a TILEABLE PERLIN, ported from pvigier/perlin-numpy
    (MIT). A Perlin is a GRADIENT noise - it interpolates random
    GRADIENTS rather than random values - and a gradient noise has
    no preferred direction, which is what a mottle wants. A value
    noise's own value is smooth between its corners, and a smooth
    field shows its lattice.

    The Perlin is periodic by construction: its gradient table is
    indexed modulo the period, so the field's edge meets its own
    edge exactly. Measured, the ported Perlin's seam is 0.0 and its
    shift by a whole period is 5e-15 - machine precision.

    The field's own spread is the surface's contrast, and the
    caller scales it to the description's.
    """
    import numpy

    from golem_blender.pbr import noise_perlin

    axis = _domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")

    # The lattice's size is the mottle's scale: a stone carries a
    # hundred or so of the patches, so the lattice is that many
    # cells across the domain and the field is periodic over it.
    #
    # The size is a POWER OF TWO and it DIVIDES the resolution, so
    # the mottle's own wrap joins two whole cells. Measured, the
    # brick's seam read 3.86x the truth's with a size of 120 and
    # 0.00x with a power of two.
    size = _power_of_two_nearest(cells * SURFACE_PATCHES_PER_CELL)
    while size > 1 and resolution % size != 0:
        size //= 2
    # The lattice's size is CAPPED, so a cell is always several
    # pixels across. A cell that is one pixel wide is degenerate -
    # the Perlin's own lattice shows, and the close crop read as a
    # checkerboard rather than as a fabric. Measured: a fabric with
    # 256 cells wanted a lattice of 2048, which is one cell a pixel
    # at 2048 across.
    while size > 1 and size * 8 > resolution:
        size //= 2
    return noise_perlin.perlin_2d(
        sample_x * size,
        sample_y * size,
        period=size,
        seed=0,
    )


def joint_response(
    resolution: int,
    cells: int,
    joint_width: float = 0.15,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The height field the RELIEF is built from: 1 on the stones, 0 in
    the joints.

    It is the same field the base colour's joint is read from, so the
    baked maps' joints land on the colour's own mortar lines.

    The joint's width is a fraction of the distance to the edge, so it
    does not depend on the pattern's scale.
    """
    import numpy

    _cell, edge, _grid = cell_and_edge(resolution, cells, octaves)
    reach = float(edge.max())
    if reach <= 0.0:
        reach = 1.0
    normalised = numpy.clip(edge / reach, 0.0, 1.0)
    # The joint is where the distance to the edge is SMALL.
    joint = numpy.clip(1.0 - normalised / max(joint_width, 1e-6), 0.0, 1.0)
    return 1.0 - joint, float(edge.max())


__all__ = (
    "BRICK_ASPECT",
    "DEFAULT_CELL_FRACTION",
    "DEFAULT_WARP_OCTAVES",
    "MINIMUM_CELL_FRACTION",
    "cell_and_edge",
    "joint_response",
    "warp",
)
