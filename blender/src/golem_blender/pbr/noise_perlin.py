# SPDX-License-Identifier: MIT
# Copyright (c) 2019 Pierre Vigier
#
# Ported from pvigier/perlin-numpy, perlin_numpy/perlin2d.py
# (generate_perlin_noise_2d and its interpolant). The algorithm is re-derived
# for a periodic lattice rather than copied; the upstream licence follows.
#
# MIT License
#
# Copyright (c) 2019 Pierre Vigier
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

"""Tileable 2-D Perlin gradient noise in numpy.

Ported from pvigier/perlin-numpy (MIT). The upstream builds a gradient grid of
res+1 nodes and repeats its last row and column to make the field tile. That
ties the period to how the grid was built, so the caller has to pick a
resolution that divides the domain. Here the gradient table is exactly
`period` x `period` and every lattice index is taken modulo `period`, so the
period is an explicit argument: value(x) == value(x + period) for any sample
coordinates, not only for a grid that happened to be built to match.

The quintic fade 6t^5 - 15t^4 + 10t^3 is kept from upstream. Its first and
second derivatives vanish at each lattice line, so the bilinear blend has no
crease there. A smoothstep (3t^2 - 2t^3) has a zero first derivative but a
non-zero second one, and that leaves a visible ridge along every lattice line.
"""

from __future__ import annotations

import numpy as np

__all__ = ("perlin_2d",)

_SQRT2 = float(np.sqrt(2.0))


def _check_period(period: int) -> int:
    """Return `period` as an int, rejecting anything that is not a positive integer."""
    if int(period) != period or period < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    return int(period)


def _quintic(t: np.ndarray) -> np.ndarray:
    """Quintic fade curve 6t^5 - 15t^4 + 10t^3, with zero first and second derivatives at 0 and 1."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def perlin_2d(
    sample_x, sample_y, period: int, seed: int = 0, period_y: int | None = None
) -> np.ndarray:
    """Perlin noise at the sample points, periodic with `period` lattice cells.

    Sample coordinates are in lattice units: one unit is one gradient cell.
    The field satisfies value(x, y) == value(x + period, y) and
    value(x, y) == value(x, y + period) exactly, because every lattice index
    is taken modulo `period`. Zero at every lattice point; roughly in [-1, 1].

    `period_y` is the period along Y, and it defaults to `period`. A
    RECTANGULAR period makes the field's features long in one axis and
    flat in the other - a wood's envelope is that, because the truth's
    own wood has its figure horizontal.

    Args:
        sample_x: x coordinates in lattice units (any broadcastable shape).
        sample_y: y coordinates in lattice units, broadcastable with sample_x.
        period: positive integer lattice period along X.
        seed: seed for the gradient table; the same seed gives the same field.
        period_y: positive integer lattice period along Y; defaults to `period`.

    Returns:
        Noise values with the broadcast shape of sample_x and sample_y.
    """
    p = _check_period(period)
    p_y = _check_period(period_y if period_y is not None else period)
    x, y = np.broadcast_arrays(
        np.asarray(sample_x, dtype=np.float64),
        np.asarray(sample_y, dtype=np.float64),
    )
    angles = np.random.default_rng(seed).uniform(0.0, 2.0 * np.pi, size=(p_y, p))
    grads = np.stack((np.cos(angles), np.sin(angles)), axis=-1)

    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = x - x0
    fy = y - y0

    def corner(dx: int, dy: int) -> np.ndarray:
        """Dot product of the corner's gradient with the offset from that corner."""
        g = grads[(y0 + dy) % p_y, (x0 + dx) % p]
        return g[..., 0] * (fx - dx) + g[..., 1] * (fy - dy)

    u = _quintic(fx)
    v = _quintic(fy)
    top = corner(0, 0) + (corner(1, 0) - corner(0, 0)) * u
    bottom = corner(0, 1) + (corner(1, 1) - corner(0, 1)) * u
    return _SQRT2 * (top + (bottom - top) * v)
