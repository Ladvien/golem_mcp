# SPDX-License-Identifier: MIT
# Copyright (c) 2013 Victor Shepardson
#
# Ported from victor-shepardson/webgl-gabor-noise (the Gabor kernel of
# Lagae, Lefebvre, Drettakis and Dutre, 2009). The algorithm is re-derived for
# a periodic lattice rather than copied: upstream sums sparse Poisson impulses
# in space, which is not periodic, so the white noise here is a periodic table
# filtered by the kernel's Fourier transform instead. The upstream licence
# follows.
#
# MIT License
#
# Copyright (c) 2013 Victor Shepardson
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Tileable 2-D Gabor noise: oriented strokes in numpy.

A Gabor kernel is a Gaussian envelope times a cosine carrier. Convolving white
noise with it gives a field whose energy sits in a narrow band of spatial
frequencies, so the field looks like a set of oriented strokes. That is the
look of a wood grain's fibre and of brushed metal, which the PBR lane needs.

Design decisions:

- The white noise is a p x p table indexed modulo p, as in `noise_perlin`, so
  the field is periodic by construction.
- The convolution is done in the frequency domain: one forward FFT of the
  table, a multiply by the kernel's Fourier transform, and an inverse
  transform. The kernel's transform is a pair of Gaussians at +/- the carrier
  frequency. Its width across the carrier is fixed, which sets the stroke
  length; its width along the carrier scales with `frequency`, which keeps a
  fixed number of carrier cycles inside each envelope.
- The inverse transform is evaluated at arbitrary continuous sample points as a
  direct sum over the bins where the kernel is above a cutoff of 1e-10 of its
  peak. An inverse FFT only yields the lattice values, and the samples are not
  on the lattice. The sum is the same transform written out, exact for the
  band-limited field, and every bin in the sum is an integer frequency, so the
  field is exactly periodic in `period`.
- Orientation is the direction of the carrier, the direction the field varies
  fastest. The strokes run at `orientation + pi/2`. The kernel is symmetric
  under a half turn, so orientations differing by pi give the same field.
"""

from __future__ import annotations

import numpy as np

__all__ = ("gabor_2d",)

_TAU = 2.0 * np.pi

# Bins whose kernel value is below this fraction of the peak are dropped from
# the continuous sum. The dropped weight is far below the noise floor.
_CUTOFF = 1e-10

# Bandwidth across the carrier, in cycles per period. A narrow band across the
# carrier makes each stroke long and thin.
_STROKE_SIGMA = 0.5

# Bandwidth along the carrier as a fraction of the frequency, with a floor so
# the kernel stays sampled by at least a bin at low frequency.
_RADIAL_FRACTION = 0.25
_RADIAL_FLOOR = 0.5

# Upper bound on samples-times-bins held in memory at once by the sum.
_CHUNK_ELEMENTS = 1 << 22


def _check_period(period: int) -> int:
    """Return `period` as an int, rejecting anything that is not a positive integer."""
    if isinstance(period, bool) or int(period) != period or int(period) < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    return int(period)


def _check_frequency(frequency: float) -> float:
    """Return `frequency` as a float, rejecting anything negative or not finite."""
    value = float(frequency)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError(f"frequency must be a finite number >= 0, got {frequency!r}")
    return value


def _bins(period: int) -> tuple[np.ndarray, np.ndarray]:
    """Signed integer frequencies of the period x period grid, as (kx, ky), indexed [ky, kx]."""
    axis = np.fft.fftfreq(period) * period
    kx, ky = np.meshgrid(axis, axis)
    return kx, ky


def _wrap(distance: np.ndarray, period: int) -> np.ndarray:
    """The minimum-image distance on the frequency torus, so a kernel centred near an edge wraps."""
    return distance - period * np.round(distance / period)


def _kernel(period: int, orientation: float, frequency: float) -> np.ndarray:
    """The Gabor kernel's Fourier transform on the bin grid, indexed [ky, kx].

    A pair of anisotropic Gaussians sits at +/- the carrier. Each is measured in
    a frame aligned to the carrier: `along` runs with the carrier, `across` runs
    perpendicular to it, which is the stroke direction.
    """
    kx, ky = _bins(period)
    ux, uy = np.cos(orientation), np.sin(orientation)
    vx, vy = -uy, ux
    sigma_along = max(_RADIAL_FRACTION * frequency, _RADIAL_FLOOR)
    kernel = np.zeros((period, period))
    for sign in (1.0, -1.0):
        dx = _wrap(kx - sign * frequency * ux, period)
        dy = _wrap(ky - sign * frequency * uy, period)
        along = dx * ux + dy * uy
        across = dx * vx + dy * vy
        kernel += np.exp(
            -0.5 * ((along / sigma_along) ** 2 + (across / _STROKE_SIGMA) ** 2)
        )
    return kernel


def gabor_2d(
    sample_x,
    sample_y,
    period: int,
    orientation: float = 0.0,
    frequency: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Tileable Gabor noise at the sample points, periodic with `period` lattice cells.

    Args:
        sample_x, sample_y: Sample coordinates in lattice cells. Broadcastable.
            The field repeats every `period` cells in each direction.
        period: Lattice size in cells, a positive integer.
        orientation: Direction of the carrier in radians, the direction the
            field varies fastest. Strokes run at `orientation + pi/2`. Taken
            modulo pi.
        frequency: Carrier frequency in cycles per period, >= 0. The carrier
            wavelength is `period / frequency` cells.
        seed: Seed for the white-noise table.

    Returns:
        A float64 array with the shape of the broadcast sample coordinates,
        with unit variance over the lattice in expectation.
    """
    p = _check_period(period)
    freq = _check_frequency(frequency)
    theta = float(orientation)
    x, y = np.broadcast_arrays(
        np.asarray(sample_x, dtype=float), np.asarray(sample_y, dtype=float)
    )

    white = np.random.default_rng(seed).standard_normal((p, p))
    spectrum = np.fft.fft2(white).ravel()
    kernel = _kernel(p, theta, freq).ravel()

    count = p * p
    norm = np.sqrt(count / np.sum(kernel * kernel))
    keep = np.nonzero(kernel > _CUTOFF * kernel.max())[0]
    amplitude = spectrum[keep] * kernel[keep] * (norm / count)

    kx, ky = _bins(p)
    kx_keep = kx.ravel()[keep]
    ky_keep = ky.ravel()[keep]

    flat_x = x.ravel()
    flat_y = y.ravel()
    out = np.empty(flat_x.size)
    chunk = max(1, _CHUNK_ELEMENTS // keep.size)
    for start in range(0, flat_x.size, chunk):
        stop = start + chunk
        phase = (_TAU / p) * (
            np.outer(flat_x[start:stop], kx_keep)
            + np.outer(flat_y[start:stop], ky_keep)
        )
        out[start:stop] = np.real(np.exp(1j * phase) @ amplitude)
    return out.reshape(x.shape)
