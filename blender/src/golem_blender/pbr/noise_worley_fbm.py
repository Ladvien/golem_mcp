"""Fractal (fBm) Worley noise: stones made of smaller stones.

WHY. One Worley octave gives one size of cell. A ground of gravel is a dense
field of small pebbles, and the lane's single-octave Ground110 came out as a
handful of amoeba-shaped blobs: 22.26 features across against the truth's
20.48, so the COUNT was right and each cell was one big blob where the truth
has many small stones. A single octave cannot make a cell that contains
smaller cells. Summing octaves whose lattices are `lacunarity` times finer
does: octave k places its cells inside the octave k-1 cells' gaps, so the
joint pattern repeats at every scale.

DESIGN.
- Octave k has a lattice of `period * lacunarity**k` cells per axis, drawn
  by the vendored primitive `worley_2d` at sample coordinates scaled by
  `lacunarity**k`. Its size is an integer that is a multiple of `period`, so
  every octave is periodic with the same `period` and the whole field is.
- F1 and F2 are the octaves' values averaged with weights
  `persistence**k`, divided by the total weight. Each octave's distance is in
  that octave's OWN cell units, as material-maker's worley does. Converting
  them to base cells first would make the fine octaves contribute
  `lacunarity**-k` of the coarse one and vanish, so the fractal would be
  invisible in the distance field. The average (not a raw sum) keeps F1 in
  the range of one octave however many octaves are stacked.
- `cell` is the owning cell of the BASE octave, the coarse stones. The
  per-octave owners are returned as `cells` (shape (octaves, ...)) so the
  fine octaves can be inspected.
- `distance` is the exact distance from the sample to the nearest Voronoi
  joint of the base octave: the minimum over the nearest point's neighbours
  of `0.5 * (|r|^2 - |m|^2) / |r - m|` (m the nearest point, r a neighbour,
  both relative to the sample). A convex cell is the intersection of its
  half-planes, and a ball lies inside a half-plane exactly when its radius
  is within the distance to the bisector line, so this minimum is the
  distance to the cell's boundary. F2 - F1 is not a distance: it is zero on
  the bisector but its growth depends on the spacing of the two points, so a
  joint of fixed pixel width needs this value.

The bisector search is exact here, not an approximation. The sample's own
cell holds a feature point within sqrt(2) of the sample, and every point two
or more cells away is at least 2 cells away, so the nearest point lies in
the 5x5 cells around the sample. The same radius reaches every Voronoi
neighbour of the nearest point; the demo checks that a 7x7 search agrees to
1e-12 on the measured grid.

Inherited primitive: `worley_2d` searches only the 3x3 cells, so its F1 could
exceed the true nearest distance where the true nearest lies two cells away.
Measured: it never did. Over 2,000,000 uniform samples (1,000,000 each at
period 3 and period 8, jitter 1.0) its F1 matched the exact 5x5 nearest
distance to 1.1e-16, with zero misses. That is not a proof for every jitter
in [0, 1]; the 3x3 search is not a defect at the measured settings.

MEASURED (period 8, 4 octaves, persistence 0.5, lacunarity 2, seed 3): the
distinct owning cells per octave are 64, 256, 1024, 4096, and the mean cell
area in base-octave cells is 1.0000, 0.2500, 0.0625, 0.0156. Each octave's
area falls by lacunarity**2 = 4x, not by persistence**k = 0.5x: persistence
sets the octaves' amplitude, and the cell area is set by the lattice.

Feature points are drawn from the same table `worley_2d` draws
(`default_rng(seed).uniform(0, 1, (p, p, 2))`), which `_feature_table`
mirrors, because `worley_2d` returns no point positions. Measured: the
primitive's F1 and the mirror's exact nearest distance agree to 1.1e-16 on
2,000,000 samples, with no sample where the mirror finds a nearer point.

The dev venv has no numpy. This module imports numpy at top level, as
`noise_worley.py` does, so it imports in Blender and in the system Python,
not in the dev venv.
"""

from __future__ import annotations

import numpy as np

from golem_blender.pbr.noise_worley import worley_2d

__all__ = ("worley_fbm_2d",)

# The bisector search covers the 5x5 cells around the sample's cell (radius
# 2). The sample's own cell holds a point within sqrt(2), and any point two
# cells away is at least 2 away, so this radius contains the nearest point.
_SEARCH_RADIUS = 2

# Two feature points closer than this (squared) are the same point seen
# through two different copies of the table. Excluded from the neighbours.
_SAME_POINT_D2 = 1e-18


def _check_int(name: str, value, minimum: int) -> int:
    """Return `value` as an int, rejecting anything that is not an integer >= `minimum`."""
    if int(value) != value or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
    return int(value)


def _octave_seed(seed: int, octave: int) -> int:
    """The feature-table seed of one octave.

    Hashed from (seed, octave) so that neighbouring octaves and neighbouring
    seeds draw independent tables. Passing `seed + octave` would make octave 1
    of seed 0 the same table as octave 0 of seed 1.
    """
    state = np.random.SeedSequence([seed, octave]).generate_state(1)
    return int(state[0])


def _feature_table(period: int, seed: int) -> np.ndarray:
    """The (period, period, 2) jitter table `worley_2d` draws for this octave.

    Mirrors the table line in `noise_worley.worley_2d`. The demo checks it
    against the primitive's F1 at every sample.
    """
    return np.random.default_rng(seed).uniform(0.0, 1.0, size=(period, period, 2))


def _feature_points(cell_x, cell_y, table: np.ndarray, jitter: float):
    """Absolute feature-point positions of the cells (cell_x, cell_y).

    The cell indices are unwrapped integers: the table is looked up modulo its
    size, but the position keeps the unwrapped cell, so a copy of a point one
    period away is at its true distance from the sample.
    """
    period = table.shape[0]
    u = table[cell_y % period, cell_x % period]
    px = cell_x + 0.5 + (u[..., 0] - 0.5) * jitter
    py = cell_y + 0.5 + (u[..., 1] - 0.5) * jitter
    return px, py


def _bisector_distance(x, y, period: int, jitter: float, seed: int) -> np.ndarray:
    """Exact distance from each sample to the nearest Voronoi joint, in cells.

    Finds the nearest feature point over the 5x5 cells around the sample,
    then takes the minimum bisector distance over the 5x5 cells around that
    point. Both searches read the same table, so the result is periodic with
    `period`.
    """
    table = _feature_table(period, seed)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    radius = _SEARCH_RADIUS

    best_d2 = np.full(x.shape, np.inf)
    best_cx = np.zeros(x.shape, dtype=np.int64)
    best_cy = np.zeros(x.shape, dtype=np.int64)
    best_px = np.zeros(x.shape)
    best_py = np.zeros(x.shape)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            cx = x0 + dx
            cy = y0 + dy
            px, py = _feature_points(cx, cy, table, jitter)
            d2 = (px - x) ** 2 + (py - y) ** 2
            nearer = d2 < best_d2
            best_d2 = np.where(nearer, d2, best_d2)
            best_cx = np.where(nearer, cx, best_cx)
            best_cy = np.where(nearer, cy, best_cy)
            best_px = np.where(nearer, px, best_px)
            best_py = np.where(nearer, py, best_py)

    # The nearest point m, relative to the sample.
    mx = best_px - x
    my = best_py - y
    m2 = mx * mx + my * my

    distance = np.full(x.shape, np.inf)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            qx, qy = _feature_points(best_cx + dx, best_cy + dy, table, jitter)
            # The neighbour r, relative to the sample.
            rx = qx - x
            ry = qy - y
            gap2 = (rx - mx) ** 2 + (ry - my) ** 2
            is_other = gap2 > _SAME_POINT_D2
            gap = np.sqrt(np.where(is_other, gap2, 1.0))
            bisector = 0.5 * ((rx * rx + ry * ry) - m2) / gap
            distance = np.where(is_other, np.minimum(distance, bisector), distance)

    # Floating-point round-off can leave a value a hair below zero on the joint.
    return np.maximum(distance, 0.0)


def worley_fbm_2d(
    sample_x,
    sample_y,
    period: int,
    octaves: int = 4,
    persistence: float = 0.5,
    lacunarity: int = 2,
    jitter: float = 1.0,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    """Fractal Worley noise at the sample points, periodic with `period` base cells.

    Sample coordinates are in BASE lattice units: one unit is one base cell.
    Octave k is `worley_2d` at `sample * lacunarity**k` with a lattice of
    `period * lacunarity**k` cells, so every octave, and the whole field, is
    periodic: value(x) == value(x + period) for x and y.

    Args:
        sample_x: x coordinates in base cells (any broadcastable shape).
        sample_y: y coordinates in base cells, broadcastable with sample_x.
        period: positive integer period of the base octave, in base cells.
        octaves: number of octaves, at least 1.
        persistence: amplitude ratio between successive octaves, >= 0. Weights
            each octave's F1 and F2 by `persistence**k`.
        lacunarity: integer frequency ratio between successive octaves, >= 2.
            Each octave's lattice is this many times finer per axis.
        jitter: how far a feature point may move from its cell centre, in
            [0, 1]. Passed to every octave.
        seed: non-negative integer seed. Each octave draws its own table from
            (seed, octave).

    Returns:
        A dict with:
            "F1": weighted mean over octaves of the nearest-point distance, in
                each octave's own cell units.
            "F2": likewise for the second-nearest distance.
            "cell": flat index (y * period + x) of the base octave's owning
                cell, after the wrap.
            "cells": array of shape (octaves, ...) with each octave's owning
                cell index, in that octave's own lattice.
            "distance": exact distance from the sample to the nearest joint of
                the base octave, in base cells.
        Each value has the broadcast shape of sample_x and sample_y.
    """
    base = _check_int("period", period, 1)
    count = _check_int("octaves", octaves, 1)
    ratio = _check_int("lacunarity", lacunarity, 2)
    seed_int = _check_int("seed", seed, 0)
    if not 0.0 <= jitter <= 1.0:
        raise ValueError(f"jitter must lie in [0, 1], got {jitter!r}")
    if persistence < 0.0:
        raise ValueError(f"persistence must be >= 0, got {persistence!r}")

    x, y = np.broadcast_arrays(
        np.asarray(sample_x, dtype=np.float64),
        np.asarray(sample_y, dtype=np.float64),
    )
    weights = float(persistence) ** np.arange(count, dtype=np.float64)
    total = float(weights.sum())

    f1 = np.zeros(x.shape)
    f2 = np.zeros(x.shape)
    cells = []
    for octave in range(count):
        scale = ratio**octave
        result = worley_2d(
            x * scale,
            y * scale,
            base * scale,
            jitter=jitter,
            seed=_octave_seed(seed_int, octave),
        )
        f1 += weights[octave] * result["F1"]
        f2 += weights[octave] * result["F2"]
        cells.append(result["cell"])

    return {
        "F1": f1 / total,
        "F2": f2 / total,
        "cell": cells[0],
        "cells": np.stack(cells),
        "distance": _bisector_distance(x, y, base, jitter, _octave_seed(seed_int, 0)),
    }
