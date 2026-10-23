"""A surface's fine grain has no axis, and it tiles.

A value noise's cells are squares, and raised to a power to make a
sparse field its shapes line up with the image's axes: the close sheet
showed camouflage squares on a metal's mottle. (Its pixel blocks on a
rock's grain were looked at, not measured: they carry no axis bias at
1024 that a gradient or a spectrum separates.)
"""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")

# For an isotropic field the gradient's mean(gx^2 gy^2) / mean((gx^2 +
# gy^2)^2) is 1/8; gradients along the axes push it down. The old metal
# mottle read 0.091, the Gaussian grain's 0.119.
AXIS_FREE = 0.117


def _axis_ratio(field) -> float:
    gx = numpy.roll(field, -1, axis=1) - field
    gy = numpy.roll(field, -1, axis=0) - field
    return float((gx**2 * gy**2).mean() / ((gx**2 + gy**2) ** 2).mean())


def test_a_plain_metal_sheet_s_mottle_has_no_axis():
    from golem_blender.pbr import pattern

    # A plain sheet's variation - its cloud, grain, tooth and specks - is
    # its envelope; its fine layer is the scratches alone.
    _band, edge, _grid, _fine = pattern.metal_field(
        1024, 10, lines_per_cell=8, horizontal=False, banded=False
    )
    assert _axis_ratio(edge) > AXIS_FREE


def test_the_grain_tiles():
    from golem_blender.pbr.noise import gaussian_grain

    grain = gaussian_grain(512, 2.0, seed=3)
    for axis in (0, 1):
        rows = numpy.moveaxis(grain, axis, 0)
        seam = float(numpy.abs(rows[0] - rows[-1]).mean())
        interior = numpy.abs(numpy.diff(rows, axis=0)).mean(axis=1)
        assert seam <= float(interior.max())
