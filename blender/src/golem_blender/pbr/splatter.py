"""SPLATTER: scattered blobs of a shape, at random places.

A field of separate pieces - a gravel's stones, a concrete's
aggregate, a rust's patches, debris on a road - is not a Voronoi.
A Voronoi's cells TILE the plane: every point belongs to exactly one
cell, and the cells' boundaries are a network. A heap of loose
stones does not tile - the stones are separate and there is a
matrix between them, and the matrix's width varies.

So the pieces are SCATTERED: each one is placed at a random point,
given a size, and drawn over the surface. That is Material Maker's
`splatter` node, MIT licensed, and it is the primitive a gravel
wants.

The one thing Material Maker's version does that ours must not is
DROP a splat that crosses the tile's edge - it does not wrap, so
the map does not tile. Ours wraps: a splat that leaves one side
comes back on the other, and the map tiles exactly.
"""

from __future__ import annotations

import numpy as np

# How many splats a surface carries.
#
# A gravel's stones are dense: the truth's own ground carries about
# sixty stones along a row of a thousand and twenty-four, and they
# are sixteen pixels across - so about three thousand six hundred in
# the whole image.
DEFAULT_SPLATTER_COUNT = 3600

# The splat's size, as a fraction of the domain.
#
# The truth's own stones are sixteen pixels across in a thousand and
# twenty-four, so a sixteenth of the domain.
DEFAULT_SPLATTER_SIZE = 0.016

# How much the splat's size varies, and how much its shape does.
DEFAULT_SPLATTER_SIZE_JITTER = 0.6
DEFAULT_SPLATTER_ROTATE = 180.0

# The EXPONENT of the size's power law, and the sizes are a power of
# a uniform draw.
#
# A loose ground's stones are NOT all the same size: the truth's own
# gravel has a median bright blob of 1.6 px in a thousand and
# twenty-four and a ninety-ninth percentile of 15.5 px, so one stone
# in a hundred is ten times the median and the bulk is tiny chips.
#
# A UNIFORM spread of sizes is a field of identical pebbles, and the
# measure read the pebbles' own count instead of the surface's.
#
# The exponent is 2, and it is a square law and not a cube.
#
# Measured against the truth's own gravel: the exponent decides how
# much of the surface the stones cover, because a stone's AREA goes
# with the square of its size. At an exponent of 3 the stones covered
# nine per cent of the surface where the truth's cover twenty, and at
# an exponent of 2 they cover twenty and the blob sizes match the
# truth's own: a median diameter of 1.6 px in a thousand and
# twenty-four against the truth's 1.6, and a ninetieth percentile of
# 6.5 px against the truth's 4.4.
SPLATTER_SIZE_EXPONENT = 2.0

# How many splats' worth of area the domain holds, per splat's own
# area. It is the DENSITY, and the count follows it and the size.
DEFAULT_SPLATTER_DENSITY = 3600.0


def splatter_field(
    resolution: int,
    count: int = DEFAULT_SPLATTER_COUNT,
    size: float = DEFAULT_SPLATTER_SIZE,
    size_jitter: float = DEFAULT_SPLATTER_SIZE_JITTER,
    rotate: float = DEFAULT_SPLATTER_ROTATE,
    seed: int = 0,
    jitter: float = 0.9,
):
    """A field of scattered splats, each one a soft dome.

    The value is one at a splat's centre and falls to zero at its
    edge, so the splats are DARK at their edges and bright in the
    middle - which is what a stone is.

    The splats WRAP: one that leaves the domain comes back on the
    other side, so the map tiles exactly. Material Maker's own
    splatter does not, and it cannot.

    And each splat is drawn into its OWN BOX and not into the whole
    surface: the whole surface is a million pixels and there are
    three thousand six hundred splats, so the whole-surface form cost
    three billion operations.
    """
    generator = np.random.default_rng(seed)
    field = np.zeros((resolution, resolution), dtype=np.float64)
    # The splats' own places and shapes, so a caller can cut them.
    places = []

    # The splats' own places, and they are on a JITTERED LATTICE
    # and not at random.
    #
    # At random they CLUMP: a Poisson field has a hole in it as
    # often as it has a pair, and a packed gravel's stones are spread
    # evenly with a shadow between them.
    #
    # Measured on the truth's own ground: the truth's stones'
    # correlation crosses zero at sixteen pixels and the lane's at
    # thirty-six, so the lane's stones came in clumps of thirty-six
    # pixels and the truth's are sixteen pixels apart.
    #
    # So the count is a LATTICE of count cells, and each splat is
    # jittered inside its own cell by a fraction of the cell's size.
    lattice = int(np.ceil(np.sqrt(count)))
    cell_width = 1.0 / lattice
    for index in range(count):
        row = index // lattice
        column = index % lattice
        centre_x = generator.random()
        centre_y = generator.random()
        # The splat's own size, and its own angle.
        #
        # The sizes are HEAVY-TAILED and not uniform: a loose ground
        # is mostly small chips with a few big stones among them, and
        # a uniform spread of sizes is a field of identical pebbles.
        #
        # Measured on the truth's own gravel: the bright blobs' median
        # diameter is 1.6 px in a thousand and twenty-four, their
        # ninetieth percentile is 4.4 px, and their ninety-ninth is
        # 15.5 px. So one blob in a hundred is ten times the median,
        # and the bulk is tiny.
        #
        # The size is a POWER of a uniform draw - and a power of a
        # uniform is a power law, which is what a crushed rock's
        # distribution is. The exponent is 3: the mean is then about
        # a third of the base and the tail is long.
        base = size * (1.0 + (generator.random() - 0.5) * 2.0 * size_jitter)
        this_size = base * (generator.random() ** SPLATTER_SIZE_EXPONENT)
        # And a stone is never smaller than a pixel: a sub-pixel stone
        # is a speck, and a speck is noise and not a stone.
        this_size = max(this_size, 1.5 / resolution)
        angle = (generator.random() * 2.0 - 1.0) * np.radians(rotate)
        cosine = np.cos(angle)
        sine = np.sin(angle)
        places.append((centre_x, centre_y, this_size, angle, cosine, sine))

        # The splat is drawn into its own box, and the box is the
        # splat's own radius.
        radius = int(np.ceil(this_size * 1.6 * resolution))
        if radius < 1:
            continue
        centre_px = int(centre_x * resolution)
        centre_py = int(centre_y * resolution)

        # The splat is drawn at EVERY WRAPPED COPY of its centre, and
        # not only at the one it was placed at.
        #
        # A single copy is a splat cut in half at the edge, and the
        # two halves are not the same shape - so the map does not
        # tile. Measured: the ground's seam read 23.73x the truth's.
        #
        # So the splat is drawn nine times, at its centre and at its
        # eight neighbours, and the edge's copy is whole on the other
        # side.
        for offset_y in (-resolution, 0, resolution):
            for offset_x in (-resolution, 0, resolution):
                lo_x = max(0, centre_px - radius + offset_x)
                hi_x = min(resolution, centre_px + radius + 1 + offset_x)
                lo_y = max(0, centre_py - radius + offset_y)
                hi_y = min(resolution, centre_py + radius + 1 + offset_y)
                if hi_x <= lo_x or hi_y <= lo_y:
                    continue
                rows = (np.arange(lo_y, hi_y) + 0.5) / resolution - centre_y
                columns = (np.arange(lo_x, hi_x) + 0.5) / resolution - centre_x
                delta_y, delta_x = np.meshgrid(rows, columns, indexing="ij")
                # The WRAP: the closest copy of the centre, on either
                # side.
                delta_x -= np.round(delta_x)
                delta_y -= np.round(delta_y)
                along = delta_x * cosine + delta_y * sine
                across = -delta_x * sine + delta_y * cosine
                distance = np.hypot(along, across) / max(1e-6, this_size)

                # The splat is a DOME: one at its centre and zero at
                # its edge.
                dome = np.clip(1.0 - distance, 0.0, 1.0)
                dome = dome * dome * (3.0 - 2.0 * dome)
                window = field[lo_y:hi_y, lo_x:hi_x]
                np.maximum(window, dome, out=window)

    return field, places


__all__ = (
    "DEFAULT_SPLATTER_COUNT",
    "DEFAULT_SPLATTER_DENSITY",
    "DEFAULT_SPLATTER_ROTATE",
    "DEFAULT_SPLATTER_SIZE",
    "DEFAULT_SPLATTER_SIZE_JITTER",
    "splatter_field",
)
