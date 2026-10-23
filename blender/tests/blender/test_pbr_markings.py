"""A road's markings: the layout the truths' own roads carry."""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")


def test_a_road_carries_two_solid_edge_lines_and_a_dashed_centre_line():
    """The truths' roads carry three markings across: two solid edge lines
    and a dashed centre one. They were drawn at random places of a lattice
    of four, and the truth's own two-lane Road007 came out with five lines."""
    from golem_blender.pbr import pattern

    _cell, edge, _grid, _road = pattern.markings_field(512, 8)
    painted = edge < 0.5
    column_share = painted.mean(axis=0)
    lines, run = [], []
    for column, share in enumerate(column_share):
        if share > 0.0:
            run.append(share)
        elif run:
            lines.append((column - len(run), float(numpy.mean(run))))
            run = []
    if run:
        lines.append((512 - len(run), float(numpy.mean(run))))
    assert len(lines) == 3, lines
    (left, left_share), (middle, middle_share), (right, right_share) = lines
    assert left_share > 0.95 and right_share > 0.95
    assert 0.3 < middle_share < 0.7
    assert left < middle < right
