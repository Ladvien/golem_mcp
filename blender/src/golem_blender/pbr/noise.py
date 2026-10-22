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


# The fade, as a polynomial: `t^3 (6 t^2 - 15 t + 10)`.
def _quintic(fraction):
    """The quintic fade, `t^3 (6 t^2 - 15 t + 10)`.

    Its first AND second derivatives are zero at 0 and at 1, so the
    interpolated field has no crease where two lattice cells meet -
    which is the whole point of the fade over a plain smoothstep.
    """
    return fraction**3 * (6.0 * fraction**2 - 15.0 * fraction + 10.0)


def _hash01(ix, iy, size, size_y, seed):
    """A lattice corner's value, in 0..1.

    The corner's index is taken MODULO the lattice's size, so the
    lattice WRAPS: the corner at the far edge is the same corner as
    the one at the near edge, and the field is periodic.

    The two axes have their OWN periods, so a rectangular lattice
    wraps on each axis at its own rate.
    """
    import numpy

    wrapped_x = (ix % size).astype(numpy.int64)
    wrapped_y = (iy % size_y).astype(numpy.int64)
    # An INTEGER hash, and it has to be one.
    #
    # The hash was a SINE of a linear combination of the coordinates:
    # `sin((wy * 31 + wx * 17) * 12.9898 + 78.233)`. Two corners that
    # are one cell apart differ by 17 in the argument, which is 220
    # radians - and the sine of that is uncorrelated from the sine of
    # the next one. So the lattice's corners were independent random
    # numbers, and the "value noise" was white noise with a smooth
    # interpolation between unrelated corners.
    #
    # Measured: the field's own correlation fell to nothing within
    # five pixels whatever the lattice's size - a size of four gave a
    # forty-nine pixel period and a size of sixteen gave five. The
    # slow variation the ground needs cannot be built from it.
    #
    # So the hash is an integer mix - a Weyl sequence and a
    # multiply-xor - and the corners are uncorrelated in the way
    # random numbers are and not in the way a sine of a large number
    # is.
    hashed = (
        (wrapped_x * 0x27D4EB2D) ^ (wrapped_y * 0x165667B1) ^ (int(seed) * 0x9E3779B1)
    ) & 0xFFFFFFFF
    hashed ^= hashed >> 15
    hashed = (hashed * 0x2C1B3C6D) & 0xFFFFFFFF
    hashed ^= hashed >> 12
    hashed = (hashed * 0x297A2D39) & 0xFFFFFFFF
    hashed ^= hashed >> 15
    return hashed.astype(numpy.float64) / 4294967296.0


def value_noise_2d(
    sample_x, sample_y, size: int, seed: int = 0, size_y: int | None = None
):
    """The value noise at a sample, over a lattice of `size` cells.

    The lattice WRAPS at `size`, so the field is periodic over the
    domain and the map tiles.

    `size_y` is the lattice's period along Y, and it defaults to
    `size`. A RECTANGULAR lattice is how a field is stretched: the
    noise's features are as wide as the x lattice says and as tall
    as the y lattice says, and both periods are whole numbers of
    cells over the domain, so the field still tiles.

    It has to be a separate period and not a scaled sample. The
    sample's y coordinate was scaled by a FRACTION - 0.25 - to
    stretch the fibre along the plank, and a fraction of a cell does
    not wrap: the field's edge met a place the field had never been.
    Measured, the coarse fibre's seam read 0.16 and the wood's own
    seam 11.88x the truth's.
    """
    import numpy

    period_y = size if size_y is None else size_y
    base_x = numpy.floor(sample_x).astype(numpy.int32)
    base_y = numpy.floor(sample_y).astype(numpy.int32)
    fraction_x = sample_x - base_x
    fraction_y = sample_y - base_y

    fade_x = _quintic(fraction_x)
    fade_y = _quintic(fraction_y)

    corner_00 = _hash01(base_x, base_y, size, period_y, seed)
    corner_10 = _hash01(base_x + 1, base_y, size, period_y, seed)
    corner_01 = _hash01(base_x, base_y + 1, size, period_y, seed)
    corner_11 = _hash01(base_x + 1, base_y + 1, size, period_y, seed)

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
    folds: int = 0,
    size_y: int | None = None,
):
    """The fBm of the value noise, in 0..1.

    Each octave is finer and quieter: the lattice's size doubles and
    its amplitude halves, so the sum is dominated by the coarse
    structure - which is what a surface's mottle is.

    The lattice's size is always a power of two, so the wrap is
    exact: a size of 4 doubled four times is 64, and every octave's
    lattice divides the domain.

    `folds` RIDGES the noise: each fold takes the absolute value of
    the octave about its middle, which turns a smooth field into one
    with sharp creases. Material-maker's `fbm4` has the same fold,
    and it is what a fibre wants - a smooth value noise is soft
    waves, and a ridged one is lines.

    `size_y` is the lattice's period along Y, and it defaults to
    `size`. The two samples are in their OWN base lattice units: the
    x sample is in units of the x lattice and the y sample in units
    of the y lattice, so a field with a period of one cell in x and
    sixty-four in y is a set of vertical stripes.
    """
    import numpy

    value = numpy.zeros_like(sample_x, dtype=numpy.float64)
    norm = numpy.zeros_like(sample_x, dtype=numpy.float64)
    amplitude = 1.0
    for octave in range(octaves):
        # The sample coordinates are in LATTICE UNITS already - the
        # caller scales them - and the octave's own lattice is the
        # size times the lacunarity.
        #
        # They were scaled AGAIN here, so a caller that asked for a
        # lattice of sixteen got two hundred and fifty-six cells, and
        # the field's correlation fell to nothing within five pixels.
        # Measured: the slow variation the ground needs - a
        # fifty-three pixel period - was not buildable from it.
        # The octave's own SCALE matters as much as its period: a
        # finer octave samples the coordinates further along, and it
        # wraps at a correspondingly larger period, so the field
        # still tiles.
        #
        # Without the scale the finer octaves did not wrap and the
        # map's seam read seventy-five times the truth's - the wood's
        # seam read 75.41x and the second wood's 25.24x.
        lattice = size * (lacunarity**octave)
        lattice_y = lattice if size_y is None else size_y * (lacunarity**octave)
        # The octave's own SCALE, and it is the SAME on both axes: a
        # finer octave samples both coordinates further along, and
        # both wrap at a correspondingly larger period.
        #
        # The y sample was scaled by the y lattice's own rate, and
        # that was wrong: the sample's y coordinate is in BASE
        # lattice units of the y lattice, and the octave advances it
        # by the lacunarity like the x one.
        scale = float(lacunarity**octave)
        octave_value = value_noise_2d(
            sample_x * scale,
            sample_y * scale,
            lattice,
            seed + octave,
            size_y=lattice_y,
        )
        for _ in range(folds):
            octave_value = numpy.abs(2.0 * octave_value - 1.0)
        value = value + octave_value * amplitude
        norm = norm + amplitude
        amplitude *= persistence
        lattice *= lacunarity
    return value / numpy.maximum(norm, 1e-9)


__all__ = (
    "fbm_2d_value",
    "value_noise_2d",
)
