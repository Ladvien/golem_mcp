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
# A gravel's stones are dense: the truth's own ground carries
# fifty-six bright stones along a row of a thousand and twenty-four,
# which is about sixty across the width, and a thousand and twenty-four
# by a thousand and twenty-four is about six hundred in the whole
# image.
DEFAULT_SPLATTER_COUNT = 600

# The splat's size, as a fraction of the domain.
#
# The truth's own stones are sixteen pixels across in a thousand and
# twenty-four, so a sixteenth of the domain.
DEFAULT_SPLATTER_SIZE = 0.016

# How much the splat's size varies, and how much its shape does.
DEFAULT_SPLATTER_SIZE_JITTER = 0.6
DEFAULT_SPLATTER_ROTATE = 180.0


def splatter_field(
    resolution: int,
    count: int = DEFAULT_SPLATTER_COUNT,
    size: float = DEFAULT_SPLATTER_SIZE,
    size_jitter: float = DEFAULT_SPLATTER_SIZE_JITTER,
    rotate: float = DEFAULT_SPLATTER_ROTATE,
    seed: int = 0,
) -> np.ndarray:
    """A field of scattered splats, each one a soft dome.

    The value is one at a splat's centre and falls to zero at its
    edge, so the splats are DARK at their edges and bright in the
    middle - which is what a stone is.

    The splats WRAP: one that leaves the domain comes back on the
    other side, so the map tiles exactly. Material Maker's own
    splatter does not, and it cannot.
    """
    axis = (np.arange(resolution) + 0.5) / resolution
    sample_x, sample_y = np.meshgrid(axis, axis, indexing="ij")

    generator = np.random.default_rng(seed)
    field = np.zeros((resolution, resolution), dtype=np.float64)

    for _ in range(count):
        centre_x = generator.random()
        centre_y = generator.random()
        # The splat's own size, and its own angle.
        this_size = size * (1.0 + (generator.random() - 0.5) * 2.0 * size_jitter)
        angle = (generator.random() * 2.0 - 1.0) * np.radians(rotate)
        cosine = np.cos(angle)
        sine = np.sin(angle)

        # The distance to the splat's centre, with the splat's own
        # axes - so it is an ellipse and not a circle.
        delta_x = sample_x - centre_x
        delta_y = sample_y - centre_y
        # The WRAP: the closest copy of the centre, on either side.
        delta_x -= np.round(delta_x)
        delta_y -= np.round(delta_y)
        along = delta_x * cosine + delta_y * sine
        across = -delta_x * sine + delta_y * cosine
        distance = np.hypot(along, across) / max(1e-6, this_size)

        # The splat is a DOME: one at its centre and zero at its edge.
        dome = np.clip(1.0 - distance, 0.0, 1.0)
        field = np.maximum(field, dome * dome * (3.0 - 2.0 * dome))

    return field


__all__ = (
    "DEFAULT_SPLATTER_COUNT",
    "DEFAULT_SPLATTER_ROTATE",
    "DEFAULT_SPLATTER_SIZE",
    "DEFAULT_SPLATTER_SIZE_JITTER",
    "splatter_field",
)
