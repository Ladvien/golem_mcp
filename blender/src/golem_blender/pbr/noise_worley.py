# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Tim Pyrkov
#
# Ported from timpyrkov/pythonworley, pythonworley/worley.py
# (_make_centers, calc_worley and worley). The algorithm is re-derived for a
# modular feature-point table rather than copied; the upstream licence follows.
#
# MIT License
#
# Copyright (c) 2023 Tim Pyrkov
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

"""Seamless tileable Worley (cellular) noise in numpy.

Ported from timpyrkov/pythonworley (MIT). Upstream pads its random
feature-point grid by one period on each side and copies the edge cells, so
the field is continuous across the wrap. It then sorts the distances to the
3x3 neighbourhood of each sample. This port keeps that construction but draws
feature points from a `period` x `period` table indexed modulo `period`. The
pattern then repeats exactly every `period` cells by construction, with no
padding step that could fall out of sync.

Each cell holds one feature point at (cell + 0.5 + (u - 0.5) * jitter), with u
uniform per cell. jitter 1.0 reproduces upstream, where the point is anywhere
in its cell. jitter 0.0 puts every point at its cell centre, a square lattice.
Only the 3x3 neighbourhood is searched, which is the same approximation
upstream makes: a point two cells away can be nearer than the second-nearest
candidate only in rare cases.
"""

from __future__ import annotations

import numpy as np

__all__ = ("worley_2d",)


def _check_period(period: int) -> int:
    """Return `period` as an int, rejecting anything that is not a positive integer."""
    if int(period) != period or period < 1:
        raise ValueError(f"period must be a positive integer, got {period!r}")
    return int(period)


def worley_2d(
    sample_x,
    sample_y,
    period: int,
    jitter: float = 1.0,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Worley noise at the sample points, periodic with `period` lattice cells.

    Sample coordinates are in lattice units: one unit is one cell. The field
    satisfies F1(x, y) == F1(x + period, y) and F2 likewise, and the same for
    y, because feature-point positions are shifted by whole periods and their
    table entries are looked up modulo `period`.

    Args:
        sample_x: x coordinates in lattice units (any broadcastable shape).
        sample_y: y coordinates in lattice units, broadcastable with sample_x.
        period: positive integer period along both axes, in cells.
        jitter: how far a feature point may move from its cell centre, in
            [0, 1]. 1.0 places it anywhere in its cell; 0.0 at the centre.
        seed: seed for the feature-point table; the same seed gives the same field.

    Returns:
        A dict with:
            "F1": distance to the nearest feature point.
            "F2": distance to the second-nearest feature point.
            "cell": flat index (y * period + x) of the cell that owns the
                nearest feature point, after the modulo wrap.
        Each value has the broadcast shape of sample_x and sample_y.
    """
    p = _check_period(period)
    if not 0.0 <= jitter <= 1.0:
        raise ValueError(f"jitter must lie in [0, 1], got {jitter!r}")
    x, y = np.broadcast_arrays(
        np.asarray(sample_x, dtype=np.float64),
        np.asarray(sample_y, dtype=np.float64),
    )
    table = np.random.default_rng(seed).uniform(0.0, 1.0, size=(p, p, 2))

    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    f1 = np.full(x.shape, np.inf)
    f2 = np.full(x.shape, np.inf)
    cell = np.zeros(x.shape, dtype=np.int64)

    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cx = x0 + dx
            cy = y0 + dy
            wx = cx % p
            wy = cy % p
            u = table[wy, wx]
            px = cx + 0.5 + (u[..., 0] - 0.5) * jitter
            py = cy + 0.5 + (u[..., 1] - 0.5) * jitter
            d = np.hypot(px - x, py - y)
            nearer = d < f1
            f2 = np.where(nearer, f1, np.minimum(f2, d))
            cell = np.where(nearer, wy * p + wx, cell)
            f1 = np.minimum(f1, d)

    return {"F1": f1, "F2": f2, "cell": cell}
