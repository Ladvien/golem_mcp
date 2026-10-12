"""Pure layer: the visual gate's verdict logic, tested without numpy.

compare_view_arrays needs numpy (inside Blender); gate_failures and
load_thresholds are pure floats and JSON, so the verdict logic and the
uncalibrated refusal are testable in the pure tier.
"""

import pytest

from blended.evaluate.visual_diff import (
    ViewComparison,
    VisualGateNotCalibrated,
    VisualGateThresholds,
    gate_failures,
    load_thresholds,
)

THRESHOLDS = VisualGateThresholds(
    minimum_silhouette_iou=0.9900, maximum_shading_rmse=0.0400
)


def _comparison(view_name, iou=1.0, rmse=0.0):
    return ViewComparison(
        view_name=view_name,
        silhouette_iou=iou,
        shading_rmse=rmse,
        subject_pixel_fraction=0.4,
    )


def test_every_view_inside_thresholds_passes():
    comparisons = (
        _comparison("front", 0.995, 0.02),
        _comparison("top", 0.993, 0.01),
    )
    assert gate_failures(comparisons, THRESHOLDS) == []


def test_worst_view_is_named_when_outside():
    comparisons = (
        _comparison("front", 0.995, 0.02),
        _comparison("right", 0.97, 0.10),
    )
    failures = gate_failures(comparisons, THRESHOLDS)
    assert len(failures) == 2
    assert all("right" in failure for failure in failures)
    assert all("front" not in failure for failure in failures)


def test_silhouette_and_shading_are_independent_failures():
    failures = gate_failures((_comparison("top", iou=0.5, rmse=0.01),), THRESHOLDS)
    assert len(failures) == 1 and "silhouette" in failures[0]
    failures = gate_failures((_comparison("top", iou=1.0, rmse=0.5),), THRESHOLDS)
    assert len(failures) == 1 and "shading" in failures[0]


def test_gate_refuses_to_run_uncalibrated(tmp_path):
    missing = tmp_path / "no_such_calibration.json"
    with pytest.raises(VisualGateNotCalibrated):
        load_thresholds(missing)


def test_load_thresholds_reads_the_calibration_file(tmp_path):
    import json

    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "minimum_silhouette_iou": 0.9880,
                "maximum_shading_rmse": 0.0500,
            }
        ),
        encoding="utf-8",
    )
    thresholds = load_thresholds(calibration)
    assert thresholds.minimum_silhouette_iou == 0.9880
    assert thresholds.maximum_shading_rmse == 0.0500
