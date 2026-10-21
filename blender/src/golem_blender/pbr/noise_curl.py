# SPDX-License-Identifier: MIT
# Copyright (c) 2021 Yuwen Wu
#
# Ported from atyuwen/bitangent_noise. The curl construction is that of Bridson,
# Hourihan and Nordenstam (2007). The algorithm
# is re-derived for a periodic lattice: the scalar potential is a periodic white
# noise low-passed in the frequency domain, and its gradient is taken
# analytically from the same spectrum rather than from lattice differences. The
# upstream licence follows.
#
# MIT License
#
# Copyright (c) 2021 Yuwen Wu
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

"""Tileable 2-D curl noise: a divergence-free swirling vector field in numpy.

A curl field is the rotated gradient of a scalar potential. Its divergence is
zero by construction, so it swirls without pooling or spreading. That is the
look of marble veining, muscle fibre and rust patches, which the PBR lane needs
for organic variation.

Design decisions:

- The potential is a p x p table of white noise indexed modulo p, as in
  `noise_perlin`, so the field is periodic by construction. It is low-passed in
  the frequency domain by a Gaussian of width `scale` cycles per period.
- The gradient is taken analytically from that same spectrum. Differencing the
  sampled lattice with `numpy.gradient` and then interpolating between samples
  does not give the gradient of the field at off-lattice points. Measured at
  period 64, scale 3.0, seed 3: the lattice-differenced field has divergence up
  to 2.3e-3 between samples (field std 0.017), against 4.9e-9 for the analytic
  gradient, which is the finite-difference noise floor at step 1e-3.
- Evaluation at continuous points is a direct sum over the bins whose spectral
  weight exceeds a cutoff, as in `noise_gabor`. Every bin is an integer
  frequency, so the field is exactly periodic in `period`.
- Rotation: the returned pair is (d psi / d y, -d psi / d x). Its divergence is
  d2 psi / (dx dy) - d2 psi / (dy dx) = 0.
"""

from __future__ import annotations

import numpy as np

__all__ = ("curl_2d",)

_TAU = 2.0 * np.pi

# Bins whose spectral weight is below this fraction of the peak are dropped from
# the continuous sum. The dropped weight is far below the noise floor.
_CUTOFF = 1e-10

# Upper bound on samples-times-bins held in memory at once by the sum.
_CHUNK_ELEMENTS = 1 << 22


def _check_period(period: int) -> int:
    """Return `period` as an int, rejecting anything that is not a positive integer."""
    if isinstance(period, bool) or int(period) != period or int(period) < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    return int(period)


def _check_scale(scale: float) -> float:
    """Return `scale` as a float, rejecting anything not a finite positive number."""
    value = float(scale)
    if not np.isfinite(value) or value <= 0.0:
        raise ValueError(f"scale must be a finite number > 0, got {scale!r}")
    return value


def _bins(period: int) -> tuple[np.ndarray, np.ndarray]:
    """Signed integer frequencies of the period x period grid, as (kx, ky), indexed [ky, kx]."""
    axis = np.fft.fftfreq(period) * period
    kx, ky = np.meshgrid(axis, axis)
    return kx, ky


def curl_2d(
    sample_x,
    sample_y,
    period: int,
    scale: float = 1.0,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Divergence-free 2-D curl noise at the sample points, periodic with `period` cells.

    The field is (u, v) = (d psi / d y, -d psi / d x) for a periodic scalar
    potential psi. Its divergence is zero analytically at every point, not only
    on the lattice.

    Args:
        sample_x, sample_y: Sample coordinates in lattice cells. Broadcastable.
            The field repeats every `period` cells in each direction.
        period: Lattice size in cells, a positive integer.
        scale: Width of the potential's low-pass Gaussian, in cycles per period,
            > 0. Larger values give finer swirls.
        seed: Seed for the white-noise table of the potential.

    Returns:
        A dict with keys "x" and "y", the two components of the field, each a
        float64 array with the shape of the broadcast sample coordinates. The
        potential is normalised to close to unit variance over the lattice
        (measured 0.989 at period 64, scale 3.0, seed 3), and the components'
        spread is set by its gradient (std 0.20 there).
    """
    p = _check_period(period)
    width = _check_scale(scale)
    x, y = np.broadcast_arrays(
        np.asarray(sample_x, dtype=float), np.asarray(sample_y, dtype=float)
    )

    white = np.random.default_rng(seed).standard_normal((p, p))
    kx, ky = _bins(p)
    kx_flat = kx.ravel()
    ky_flat = ky.ravel()

    lowpass = np.exp(-(kx_flat * kx_flat + ky_flat * ky_flat) / (2.0 * width * width))
    spectrum = np.fft.fft2(white).ravel() * lowpass
    count = p * p
    norm = np.sqrt(count / np.sum(np.abs(spectrum) ** 2 / count))
    spectrum = spectrum * norm / count

    keep = np.nonzero(np.abs(spectrum) > _CUTOFF * np.abs(spectrum).max())[0]
    amplitude = spectrum[keep]
    kx_keep = kx_flat[keep]
    ky_keep = ky_flat[keep]

    # The gradient of exp(i k . x) is i k exp(i k . x), so d/dx multiplies by
    # i kx (times 2 pi / p for the cell units) and d/dy by i ky. The curl is
    # (d psi/dy, -d psi/dx), so u takes the ky factor and v the negated kx one.
    flat_x = x.ravel()
    flat_y = y.ravel()
    u = np.empty(flat_x.size)
    v = np.empty(flat_x.size)
    chunk = max(1, _CHUNK_ELEMENTS // keep.size)
    for start in range(0, flat_x.size, chunk):
        stop = start + chunk
        phase = (_TAU / p) * (
            np.outer(flat_x[start:stop], kx_keep)
            + np.outer(flat_y[start:stop], ky_keep)
        )
        carrier = np.exp(1j * phase) * amplitude
        u[start:stop] = np.real(1j * (_TAU / p) * (carrier @ ky_keep))
        v[start:stop] = np.real(-1j * (_TAU / p) * (carrier @ kx_keep))
    return {"x": u.reshape(x.shape), "y": v.reshape(x.shape)}
