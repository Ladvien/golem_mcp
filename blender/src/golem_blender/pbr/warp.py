"""DOMAIN WARPING: displacing the sample coordinates along a field.

A noise field sampled at the sample's own coordinates is a noise
field. A field sampled at coordinates that have been DISPLACED along
another field's slope is something else - the structure bends, the
direction changes, and the result reads as a material rather than as
noise.

That is the difference between our ground reading as a plate of
cracked mud and the truth's reading as a gravel, and between our
wood's fibre reading as regular streaks and the truth's reading as
the grain of a board cut across a log.

The warp is what makes organic material organic.

The design is Material Maker's - the `warp` and `multi_warp2` nodes,
MIT licensed - and the two ideas are:

- the DISPLACEMENT is the SLOPE of a height field, sampled at the
  sample's own coordinates: the structure is pushed downhill, so a
  ridge becomes a flow and a valley becomes a gather;
- the displacement can be applied REPEATEDLY, so the sample walks
  along the field rather than taking one step: that is
  `multi_warp2`'s streamline advection, and it is what makes the
  result read as a *flow* and not as a bend.

And the property that matters most here is TILEABILITY: the map has
to tile, and a warp that displaces the coordinates across the
domain boundary breaks the tile. So every sample is wrapped, and
the height field is periodic with the domain - which every one of
our noise fields already is.
"""

from __future__ import annotations

import numpy as np

# How far the warp displaces the coordinates, as a fraction of the
# domain.
#
# It is a domain fraction and not a cell fraction, because the
# displacement is the field's SLOPE - which is already in the field's
# own units - and the amount is what scales it.
#
# Material Maker's own default is 0.1 with a step of 0.1 in UV.
DEFAULT_WARP_AMOUNT = 0.1

# The step the slope is measured over, as a fraction of the domain.
#
# It is a tenth of the domain, which is Material Maker's own default
# and which is coarse: a finer step gives a sharper flow.
DEFAULT_WARP_STEP = 0.1

# How many times the displacement is applied.
#
# ONE is a single step. More is a streamline: the sample walks along
# the field, and the result reads as a flow.
DEFAULT_WARP_ITERATIONS = 1

# How much each step is scaled by, and how the steps share the
# displacement.
#
# Material Maker's `multi_warp2` scales the step by intensity squared
# and divides by the iteration count, so the TOTAL displacement is
# the same however many steps it is taken in - and so a streamline
# of sixty steps goes as far as one step would.
DEFAULT_WARP_INTENSITY = 4.0
DEFAULT_WARP_QUALITY = 15.0


def _sample(field: np.ndarray, uv_x: np.ndarray, uv_y: np.ndarray):
    """The field at the sample points, bilinearly and wrapped.

    The coordinates are in the domain's own fractions, and they are
    wrapped, so the field's own periodicity is what the wrap follows
    and the map still tiles.
    """
    height, width = field.shape
    x = np.mod(uv_x, 1.0) * width
    y = np.mod(uv_y, 1.0) * height
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = (x0 + 1) % width
    y1 = (y0 + 1) % height
    fx = x - x0
    fy = y - y0
    top = field[y0, x0] * (1.0 - fx) + field[y0, x1] * fx
    bottom = field[y1, x0] * (1.0 - fx) + field[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


def warped_coordinates(
    uv_x: np.ndarray,
    uv_y: np.ndarray,
    height: np.ndarray,
    amount: float = DEFAULT_WARP_AMOUNT,
    step: float = DEFAULT_WARP_STEP,
    iterations: int = DEFAULT_WARP_ITERATIONS,
    intensity: float = DEFAULT_WARP_INTENSITY,
    quality: float = DEFAULT_WARP_QUALITY,
):
    """The sample coordinates, displaced along a height field's slope.

    `uv_x` and `uv_y` are the coordinates in the domain's own
    fractions, and `height` is the field whose slope the
    displacement follows.

    `amount` scales the displacement and `step` is the baseline the
    slope is measured over - a tenth of the domain, which is Material
    Maker's own default.

    `iterations` is how many steps are taken. One is a single bend;
    more is a streamline, and each step is scaled by the intensity
    squared and divided by the iteration count, so the TOTAL
    displacement is the same however many steps it is taken in.
    """
    if amount <= 0.0 or iterations <= 0:
        return uv_x, uv_y

    # The height field is sampled in the DOMAIN's fractions, so it is
    # resampled onto the coordinates the warp is walking over.
    def at(x: np.ndarray, y: np.ndarray):
        return _sample(height, x, y)

    x = uv_x
    y = uv_y
    # The step is scaled so the TOTAL displacement is the same however
    # many steps it is taken in - and Material Maker's `multi_warp2`
    # divides by the QUALITY and not by the iteration count, so a
    # streamline of sixty steps goes as far as one step would.
    #
    # Without the quality the displacement was sixteen times too
    # strong: the ground's stones were smeared into a fine speckle,
    # and the feature scale read 26x the truth's where it read 1.37x
    # with no warp at all.
    scale = amount * intensity * intensity / (iterations * quality)
    for _ in range(iterations):
        value = at(x, y)
        slope_x = (at(x + step, y) - value) * 2.0
        slope_y = (at(x, y + step) - value) * 2.0
        x = x + slope_x * scale
        y = y + slope_y * scale
    return x, y


def warp_field(
    field: np.ndarray,
    height: np.ndarray,
    amount: float = DEFAULT_WARP_AMOUNT,
    step: float = DEFAULT_WARP_STEP,
    iterations: int = DEFAULT_WARP_ITERATIONS,
    intensity: float = DEFAULT_WARP_INTENSITY,
    quality: float = DEFAULT_WARP_QUALITY,
) -> np.ndarray:
    """A field, resampled at WARPED coordinates.

    This is the form the lane wants: a field is computed once and
    then read through a warp, so the warp bends whatever the field
    is - a Voronoi's cells, a Perlin's ridges, a fibre's strokes.

    The resampling is BILINEAR, and it is the one place the lane
    loses a little sharpness: a bicubic would keep more of it, at
    four times the cost.
    """
    if amount <= 0.0 or iterations <= 0:
        return field

    height_, width_ = field.shape
    axis_x = (np.arange(width_) + 0.5) / width_
    axis_y = (np.arange(height_) + 0.5) / height_
    uv_x, uv_y = np.meshgrid(axis_x, axis_y)
    warped_x, warped_y = warped_coordinates(
        uv_x,
        uv_y,
        height,
        amount=amount,
        step=step,
        iterations=iterations,
        intensity=intensity,
        quality=quality,
    )
    return _sample(field, warped_x, warped_y)


__all__ = (
    "DEFAULT_WARP_AMOUNT",
    "DEFAULT_WARP_INTENSITY",
    "DEFAULT_WARP_ITERATIONS",
    "DEFAULT_WARP_QUALITY",
    "DEFAULT_WARP_STEP",
    "warp_field",
    "warped_coordinates",
)
