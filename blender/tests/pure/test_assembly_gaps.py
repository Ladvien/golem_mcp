"""`_box_gap_m`: the lower bound on how far two parts stand apart.

The separation check in `assembly_report` decides an under-measured pair from
these boxes, so the arithmetic has to be right in all four cases: apart on one
axis, apart diagonally, touching, and overlapping.
"""

import pytest


def _bounds(minimum, maximum):
    return ([float(value) for value in minimum], [float(value) for value in maximum])


def test_a_gap_on_one_axis_is_that_gap_where_the_other_axes_overlap():
    """The measured case: an inner corner 0.323 m clear of its wall."""
    from golem_blender.ops.assembly import _box_gap_m

    first = _bounds((0.0, 0.0, 0.0), (4.0, 0.3, 3.0))
    second = _bounds((4.323, 0.0, 0.0), (4.623, 1.0, 3.0))

    assert _box_gap_m(first, second) == pytest.approx(0.323, abs=1.0e-9)


def test_a_diagonal_gap_is_the_euclidean_distance():
    from golem_blender.ops.assembly import _box_gap_m

    first = _bounds((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    second = _bounds((1.3, 1.4, 0.0), (2.0, 2.0, 1.0))

    assert _box_gap_m(first, second) == pytest.approx(0.5, abs=1.0e-9)


def test_touching_faces_are_zero_apart():
    from golem_blender.ops.assembly import _box_gap_m

    first = _bounds((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    second = _bounds((1.0, 0.0, 0.0), (2.0, 1.0, 1.0))

    assert _box_gap_m(first, second) == 0.0


def test_overlapping_boxes_are_zero_apart_never_negative():
    from golem_blender.ops.assembly import _box_gap_m

    first = _bounds((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    second = _bounds((0.5, 0.5, 0.5), (1.5, 1.5, 1.5))

    assert _box_gap_m(first, second) == 0.0
