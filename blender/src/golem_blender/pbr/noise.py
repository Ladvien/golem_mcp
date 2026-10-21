"""A periodic value-noise fBm, ported from material-maker.

The lane's "mottle" was a sum of sines, and a sum of sines is a
PLAID: it has a direction and a period, and a close crop of it
reads as corduroy rather than as stone. Measured on the truth's
ground, the lane's stones were flat grey blobs with a woven
texture over them, and the truth's are a field of small light and
dark patches with no direction at all.

Material-maker's value noise is what a mottle wants: a lattice of
random values, bilinearly interpolated with the QUINTIC fade, and
the lattice WRAPS so the field is periodic. The port is from
material-maker's `fbm4.mmg` / `value_noise_2d`:

- the lattice's corners are hashed from the cell's own index, taken
  modulo the lattice's size, so the lattice wraps;
- each corner's value is remapped through a sine to spread it;
- the interpolation is bilinear with the quintic fade
  `t = f^3 (6 f^2 - 15 f + 10)`, which has zero first AND second
  derivatives at the cell's edge - so the field has no crease where
  the cells meet;
- the fBm sums the octaves, each with a smaller amplitude and a
  finer lattice.

The hash is the lane's own `_cell_hash`, which is already keyed on
the wrapped position - so the wrap is correct by construction.
"""

from __future__ import annotations

import math


# The fade, as a polynomial: `t^3 (6 t^2 - 15 t + 10)`.
def _quintic(fraction):
    """The quintic fade, `t^3 (6 t^2 - 15 t + 10)`.

    Its first AND second derivatives are zero at 0 and at 1, so the
    interpolated field has no crease where two lattice cells meet -
    which is the whole point of the fade over a plain smoothstep.
    """
    return fraction**3 * (6.0 * fraction**2 - 15.0 * fraction + 10.0)


def _hash01(ix, iy, size, seed):
    """A lattice corner's value, in 0..1.

    The corner's index is taken MODULO the lattice's size, so the
    lattice WRAPS: the corner at the far edge is the same corner as
    the one at the near edge, and the field is periodic.
    """
    import numpy

    wrapped_x = (ix % size).astype(numpy.float64)
    wrapped_y = (iy % size).astype(numpy.float64)
    # The same hash the lane's cell colours use: a function of the
    # POSITION, not of the index, so the wrap is exact.
    values = wrapped_y * 31.0 + wrapped_x * 17.0 + float(seed) * 7.13
    hashed = numpy.sin(values * 12.9898 + 78.233) * 43758.5453
    hashed = hashed - numpy.floor(hashed)
    # The remap material-maker uses: a sine spreads the values so
    # they are not clumped at the ends.
    remapped = numpy.sin(hashed * 2.0 * math.pi + math.pi) / 2.0 + 0.5
    return remapped


def value_noise_2d(sample_x, sample_y, size: int, seed: int = 0):
    """The value noise at a sample, over a lattice of `size` cells.

    The lattice WRAPS at `size`, so the field is periodic over the
    domain and the map tiles.
    """
    import numpy

    base_x = numpy.floor(sample_x).astype(numpy.int32)
    base_y = numpy.floor(sample_y).astype(numpy.int32)
    fraction_x = sample_x - base_x
    fraction_y = sample_y - base_y

    fade_x = _quintic(fraction_x)
    fade_y = _quintic(fraction_y)

    corner_00 = _hash01(base_x, base_y, size, seed)
    corner_10 = _hash01(base_x + 1, base_y, size, seed)
    corner_01 = _hash01(base_x, base_y + 1, size, seed)
    corner_11 = _hash01(base_x + 1, base_y + 1, size, seed)

    top = corner_00 + (corner_10 - corner_00) * fade_x
    bottom = corner_01 + (corner_11 - corner_01) * fade_x
    return top + (bottom - top) * fade_y


def fbm_2d_value(
    sample_x,
    sample_y,
    size: int = 4,
    octaves: int = 4,
    persistence: float = 0.5,
    lacunarity: int = 2,
    seed: int = 0,
):
    """The fBm of the value noise, in 0..1.

    Each octave is finer and quieter: the lattice's size doubles and
    its amplitude halves, so the sum is dominated by the coarse
    structure - which is what a surface's mottle is.

    The lattice's size is always a power of two, so the wrap is
    exact: a size of 4 doubled four times is 64, and every octave's
    lattice divides the domain.
    """
    import numpy

    value = numpy.zeros_like(sample_x, dtype=numpy.float64)
    norm = numpy.zeros_like(sample_x, dtype=numpy.float64)
    amplitude = 1.0
    lattice = size
    for octave in range(octaves):
        value = (
            value
            + value_noise_2d(
                sample_x * lattice, sample_y * lattice, lattice, seed + octave
            )
            * amplitude
        )
        norm = norm + amplitude
        amplitude *= persistence
        lattice *= lacunarity
    return value / numpy.maximum(norm, 1e-9)


__all__ = (
    "fbm_2d_value",
    "value_noise_2d",
)
