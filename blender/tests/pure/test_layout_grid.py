"""The grid arithmetic behind `lay_out_grid`, tested with no Blender.

Two decisions live here, and both are arithmetic rather than bpy calls:
one UNIFORM cell size (so the grid reads like a contact sheet instead of
each model hugging its neighbour), and where cell (0, 0) sits when the
caller names no origin — just past every other mesh on +X, so a shelf
never lands inside the model under test.

The op's own scene effects are measured in `tests/blender/
test_layout_grid_ops.py`; what is testable everywhere is here, because a
wrong cell size or a wrong row-major order is a bug the grid shares with
nothing in bpy.
"""

from __future__ import annotations

import pytest

from golem_blender.ops.layout import _auto_origin_m, _grid_cells

GAP_M = 0.5
ORIGIN_M = (0.0, 0.0, 0.0)


def test_auto_columns_square_the_grid_and_one_cell_size_fits_the_widest():
    """Five 1 m footprints: ceil(sqrt(5)) = 3 columns, so 2 rows. The cell is
    the largest footprint plus the gap, for EVERY item — the point of a
    uniform cell is that the columns line up."""
    columns, rows, cell_m, centres_m = _grid_cells(
        [(1.0, 1.0)] * 5, GAP_M, None, ORIGIN_M
    )

    assert (columns, rows) == (3, 2)
    assert cell_m == (1.5, 1.5)
    assert len(centres_m) == 5
    # Row-major: item 4 is column 1 of row 1.
    assert centres_m[4] == pytest.approx((1.5, 1.5, 0.0))
    assert centres_m[0] == pytest.approx((0.0, 0.0, 0.0))
    assert centres_m[2] == pytest.approx((3.0, 0.0, 0.0))


def test_the_cell_is_the_widest_footprint_on_each_axis_separately():
    """A long thin item widens the columns and not the rows."""
    _, _, cell_m, _ = _grid_cells([(1.0, 1.0), (3.0, 0.5)], GAP_M, None, ORIGIN_M)

    assert cell_m == pytest.approx((3.5, 1.5))


def test_a_column_count_wider_than_the_items_gives_one_row():
    columns, rows, _, _ = _grid_cells([(1.0, 1.0)] * 3, GAP_M, 4, ORIGIN_M)

    assert (columns, rows) == (3, 1)


def test_the_origin_carries_into_every_centre():
    """A caller placing the shelf clear of the model under test names the
    origin once; every cell offsets from it, on all three axes."""
    _, _, _, centres_m = _grid_cells(
        [(1.0, 1.0)] * 2, GAP_M, None, (5.55, -3.693, 0.25)
    )

    assert centres_m[0] == pytest.approx((5.55, -3.693, 0.25))
    assert centres_m[1] == pytest.approx((7.05, -3.693, 0.25))


def test_a_negative_gap_an_empty_set_and_a_column_count_below_one_are_refused():
    with pytest.raises(ValueError, match="gap_m"):
        _grid_cells([(1.0, 1.0)], -0.1, None, ORIGIN_M)
    with pytest.raises(ValueError, match="empty"):
        _grid_cells([], GAP_M, None, ORIGIN_M)
    with pytest.raises(ValueError, match="column_count"):
        _grid_cells([(1.0, 1.0)] * 3, GAP_M, 0, ORIGIN_M)


def test_no_other_mesh_puts_the_grid_at_the_world_origin():
    """Nothing else in the scene: the grid is the scene."""
    assert _auto_origin_m(None, (1.5, 1.5), GAP_M) == (0.0, 0.0, 0.0)


def test_the_grid_starts_just_past_the_others_on_x_and_centred_on_their_y():
    """Measured against the shelf this replaces: the pieces must not be laid
    out on top of the model under test, which sits around the origin."""
    others_bounds_m = ([-4.3, -4.443, 0.0], [4.3, 3.3, 3.0])

    origin_m = _auto_origin_m(others_bounds_m, (1.5, 1.5), GAP_M)

    # max x + the gap to the others + half a cell to cell (0, 0)'s centre.
    assert origin_m == pytest.approx((4.3 + GAP_M + 0.75, -4.443 + 0.75, 0.0))
