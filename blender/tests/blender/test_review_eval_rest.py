"""The visual gate's pixel comparison, measured against hand-computed
answers, and its refusal of a frame with no pixels at all (review of
`blended.evaluate.visual_diff`)."""

import math

import pytest

numpy = pytest.importorskip("numpy", reason="requires Blender's bundled numpy")

from blended.evaluate.visual_diff import EmptyFrame, compare_view_arrays

pytestmark = pytest.mark.blender

SIZE_PX = 64
SQUARE_PX = 32
# Golden subject: rows/cols [16, 48). Candidate subject: rows [16, 48),
# cols [32, 64) — it overlaps the golden on a 32 x 16 strip.
GOLDEN_FIRST_PX = 16
CANDIDATE_FIRST_COLUMN_PX = 32
IOU_TOLERANCE = 1.0e-9
# The arrays are float32, so the RMSE carries ~1e-7 of rounding.
RMSE_TOLERANCE = 1.0e-6


def _frame(first_row_px: int, first_column_px: int):
    array = numpy.zeros((SIZE_PX, SIZE_PX, 4), dtype=numpy.float32)
    array[..., 3] = 1.0
    array[
        first_row_px : first_row_px + SQUARE_PX,
        first_column_px : first_column_px + SQUARE_PX,
        :3,
    ] = 1.0
    return array


def test_a_shifted_square_scores_the_hand_computed_iou_and_rmse():
    golden = _frame(GOLDEN_FIRST_PX, GOLDEN_FIRST_PX)
    candidate = _frame(GOLDEN_FIRST_PX, CANDIDATE_FIRST_COLUMN_PX)
    comparison = compare_view_arrays("front", golden, candidate)
    # intersection 32*16 = 512 px; union 1024 + 1024 - 512 = 1536 px.
    assert comparison.silhouette_iou == pytest.approx(512 / 1536, abs=IOU_TOLERANCE)
    assert comparison.subject_pixel_fraction == pytest.approx(1536 / SIZE_PX**2)
    # Only the 1024 px that belong to exactly one subject differ, by 1.0
    # on each RGB channel: mean square over the union = 1024 / 1536.
    assert comparison.shading_rmse == pytest.approx(
        math.sqrt(1024 / 1536), abs=RMSE_TOLERANCE
    )


def test_a_zero_pixel_frame_is_refused_by_name_not_by_an_index_error():
    empty = numpy.zeros((0, 0, 4), dtype=numpy.float32)
    with pytest.raises(EmptyFrame, match="front"):
        compare_view_arrays("front", empty, empty)


def test_two_frames_with_no_subject_do_not_score_a_perfect_match():
    blank = _frame(0, 0)
    blank[..., :3] = 0.0
    with pytest.raises(EmptyFrame):
        compare_view_arrays("front", blank, blank)


def test_a_size_mismatch_is_refused():
    golden = _frame(GOLDEN_FIRST_PX, GOLDEN_FIRST_PX)
    candidate = numpy.zeros((SIZE_PX // 2, SIZE_PX, 4), dtype=numpy.float32)
    with pytest.raises(ValueError, match="differ in size"):
        compare_view_arrays("front", golden, candidate)
