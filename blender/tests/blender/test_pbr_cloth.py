"""A fine cloth's slubs: streaks along the row on a slubbed canvas, none on a linen."""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")


def _correlation_length(rows, level: float = 0.2) -> int:
    width = rows.shape[1]
    centred = rows - rows.mean(axis=1, keepdims=True)
    total = numpy.zeros(width)
    for row in centred[::4]:
        total += numpy.correlate(row, row, mode="full")[width - 1 :]
    total /= total[0]
    below = numpy.nonzero(total < level)[0]
    return int(below[0]) if len(below) else width


def _anisotropy(cells: int) -> float:
    from golem_blender.pbr import pattern

    _cell, field, _grid, _fibre = pattern.woven_field(512, cells)
    return _correlation_length(field) / max(1, _correlation_length(field.T))


def test_a_cloth_of_few_features_is_slubbed_along_its_rows():
    """The truth's own Fabric036, 17 features, decorrelates within 12
    pixels along a row against 3 down it; the weave under an isotropic
    mottle read the same both ways."""
    assert _anisotropy(17) >= 2.0


def test_a_fine_linen_is_not_streaked():
    """The truth's own Fabric030, 45 features, is a regular linen: slubs
    on it streaked it like a brushed metal."""
    assert _anisotropy(45) < 1.5
