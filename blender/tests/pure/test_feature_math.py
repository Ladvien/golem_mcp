"""The three measurements a long assembly call needs: a plane, a side, a progress file.

Every case here is arithmetic or file I/O, so it runs without Blender. The
Blender-side behaviour (a real box probed with real rays) is
`tests/blender/test_measure_feature.py`.

Measured need, 2026-10-24: a 77-part bakery's `export_assembly` outlived the
client's socket timeout, and the pieces that keep that from happening again are
tested here — a deadline that stops asking, a progress file the bridge can read
mid-call, and the two geometry helpers `measure_feature` decides with.
"""

import json
import math
import time

import pytest

from golem_blender.ops.features import (
    SideDepth,
    _deepest_side,
    _facing_side,
    _fit_plane,
    _slope_deg,
)
from golem_blender.run import call_context

TOLERANCE = 1.0e-3


# --- _fit_plane ----------------------------------------------------------------


def test_a_fit_of_z_equals_half_x_reads_the_pitch_it_has():
    """Points on z = 0.5x: the plane's pitch is atan(0.5) = 26.565 degrees."""
    points = [
        (x_m, y_m, 0.5 * x_m) for x_m in (0.0, 1.0, 2.0, 3.0) for y_m in (0.0, 1.0, 2.0)
    ]

    centroid, normal, residual_m, maximum_residual_m = _fit_plane(points)

    assert _slope_deg(normal) == pytest.approx(
        math.degrees(math.atan(0.5)), abs=TOLERANCE
    )
    assert residual_m == pytest.approx(0.0, abs=1.0e-9)
    assert maximum_residual_m == pytest.approx(0.0, abs=1.0e-9)
    assert centroid[2] == pytest.approx(0.5 * centroid[0], abs=TOLERANCE)


def test_one_point_off_the_plane_is_the_maximum_residual_and_not_the_rms():
    """A single stray vertex must show up in the MAX, and stay visible in the RMS."""
    points = [
        (x_m, y_m, 0.0) for x_m in (0.0, 1.0, 2.0, 3.0) for y_m in (0.0, 1.0, 2.0)
    ] + [(1.0, 1.0, 0.1)]

    _centroid, normal, residual_m, maximum_residual_m = _fit_plane(points)

    assert maximum_residual_m > residual_m > 0.0
    # The fit tips slightly towards the stray point, so the pitch is small but
    # non-zero: the assertion is on the ORDER, not on a fitted constant.
    assert _slope_deg(normal) < 5.0


def test_fewer_than_three_points_are_refused_because_no_plane_is_defined():
    """Two points define a line: a fitted plane would be a guess dressed as a measure."""
    with pytest.raises(ValueError, match="at least 3 points"):
        _fit_plane([(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])


# --- side choice ---------------------------------------------------------------


def _side_depth(side: str, mean_depth_m: float) -> SideDepth:
    return SideDepth(
        side=side,
        normal=(0.0, 0.0, 0.0),
        mean_depth_m=mean_depth_m,
        maximum_depth_m=mean_depth_m,
        through_fraction=0.0,
        box_depth_m=1.0,
    )


def test_the_deepest_side_picks_the_largest_and_ties_go_in_side_order():
    rows = [_side_depth("front", 0.2), _side_depth("back", 0.9)]

    assert _deepest_side(rows) == "back"
    # Both read the same depth: the FIRST in INTERACTION_SIDES order wins, so
    # the answer does not depend on dictionary or list accident.
    tied = [_side_depth("front", 0.5), _side_depth("back", 0.5)]
    assert _deepest_side(tied) == "front"
    assert _deepest_side([]) == ""


def test_the_facing_side_picks_the_most_aligned_and_ties_go_in_side_order():
    alignments = [("front", -1.0), ("back", 1.0), ("left", 0.0)]

    assert _facing_side(alignments) == "back"
    tied = [("front", 0.7), ("back", 0.7)]
    assert _facing_side(tied) == "front"
    assert _facing_side([]) == ""


# --- the progress file and the deadline ----------------------------------------


def test_report_progress_outside_a_call_writes_nothing(tmp_path):
    """No context, no file: a reader must never find a progress file from nowhere."""
    call_context.report_progress("pair check", 1, 2)

    assert not (tmp_path / call_context.PROGRESS_FILE_NAME).exists()
    assert call_context.current_context() is None


def test_report_progress_inside_a_call_writes_where_it_has_got_to(tmp_path):
    with call_context.call_context(tmp_path, "export_assembly"):
        call_context.report_progress("part gate", 3, 5)

        written = json.loads(
            (tmp_path / call_context.PROGRESS_FILE_NAME).read_text(encoding="utf-8")
        )
        assert written["tool"] == "export_assembly"
        assert written["stage"] == "part gate"
        assert written["part"] == 3
        assert written["of"] == 5

    assert call_context.current_context() is None


def test_the_progress_write_is_throttled_except_when_a_stage_finishes(tmp_path):
    """A tight loop must not write on every iteration; a finished stage always writes."""
    path = tmp_path / call_context.PROGRESS_FILE_NAME
    with call_context.call_context(tmp_path, "export_assembly"):
        call_context.report_progress("part gate", 0, 5)
        first = json.loads(path.read_text(encoding="utf-8"))
        assert first["part"] == 0

        # Immediately afterwards: inside the throttle window, so nothing is written.
        call_context.report_progress("part gate", 1, 5)
        assert json.loads(path.read_text(encoding="utf-8"))["part"] == 0

        # The last iteration is taken anyway, because a stage's completion is the
        # one message a reader must not miss.
        call_context.report_progress("part gate", 5, 5)
        assert json.loads(path.read_text(encoding="utf-8"))["part"] == 5


def test_a_context_may_outlive_a_throttled_call_and_still_write(tmp_path):
    """The throttle resets per call, so a second call reports immediately."""
    path = tmp_path / call_context.PROGRESS_FILE_NAME
    with call_context.call_context(tmp_path, "export_assembly"):
        call_context.report_progress("part gate", 1, 5)
        assert json.loads(path.read_text(encoding="utf-8"))["part"] == 1

    with call_context.call_context(tmp_path, "assembly_report"):
        call_context.report_progress("pair check", 7, 9)
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["part"] == 7
        assert written["tool"] == "assembly_report"


def test_a_deadline_expires_and_reports_what_is_left():
    assert not call_context.Deadline(60.0).expired()

    spent = call_context.Deadline(1.0e-6)
    time.sleep(0.002)
    assert spent.expired()
    assert spent.remaining_s() == pytest.approx(0.0)
    assert spent.elapsed_s() > 0.0
