"""The visual gate: a calibrated, deterministic pixel comparison
against the pinned golden references.

The examiner is the only visual instrument, and eye_calibration.json
records it below the sensitivity floor — so no machine visual verdict
is licensed today. The pixel gate is a different instrument: it cannot
judge whether an asset matches a brief, but it can prove a render did
or did not move against the reference that was already pinned by a
human. Every brief has five pinned views and a manifest naming the
iteration that produced them.

scp's gate is the model, with two deliberate differences: their renders
set film_transparent so alpha IS the silhouette, while blended's
captures are opaque 512x512 Workbench renders — changing capture
settings would invalidate every pinned view_sha256, which only a human
may re-mint. So the silhouette is derived by background keying, and the
thresholds are measured by scripts/calibrate_visual_gate.py, never
hardcoded here.

Thresholds come from the calibration file. `load_thresholds` raises
VisualGateNotCalibrated when it is absent: an uncalibrated gate that
silently passed everything would be the quiet-mismatch failure this
module exists to make loud.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# A pixel belongs to the subject when it differs from the golden
# corners' median background by more than this per channel.
SILHOUETTE_BACKGROUND_EPSILON = 0.02
# Below this subject fraction the frame is empty (or the camera missed);
# above this the background keyed (scp measured 266,600 subject pixels
# for a floor leak against 98,141 for a real character).
MINIMUM_SUBJECT_FRACTION = 0.005
MAXIMUM_SUBJECT_FRACTION = 0.90

CALIBRATION_PATH = Path("_evaluate/visual_gate_calibration.json")


class VisualGateNotCalibrated(Exception):
    """No calibration file exists, so the gate may not judge."""


class EmptyFrame(Exception):
    """A view carried no subject pixels (or too many) to compare."""


@dataclass(frozen=True)
class ViewComparison:
    view_name: str
    silhouette_iou: float
    shading_rmse: float
    subject_pixel_fraction: float


@dataclass(frozen=True)
class VisualGateThresholds:
    minimum_silhouette_iou: float
    maximum_shading_rmse: float


def _background_rgb(golden_array):
    """Per-channel median of the four corner pixels of the golden."""
    import numpy

    corners = (
        golden_array[0, 0],
        golden_array[0, -1],
        golden_array[-1, 0],
        golden_array[-1, -1],
    )
    return tuple(
        float(numpy.median([corner[channel] for corner in corners]))
        for channel in range(3)
    )


def _subject_mask(array, background_rgb):
    """True where a pixel differs from the background by more than
    epsilon on any RGB channel."""
    import numpy

    differences = numpy.abs(array[:, :, :3] - numpy.asarray(background_rgb))
    return numpy.any(differences > SILHOUETTE_BACKGROUND_EPSILON, axis=2)


def compare_view_arrays(view_name, golden_array, candidate_array) -> ViewComparison:
    """Compare two (h, w, 4) arrays in Blender's bottom-up orientation.

    Both arrays must be the same size; the background is keyed from the
    GOLDEN's corners so a candidate that changes the backdrop cannot
    move the silhouette.
    """
    import numpy

    golden_shape = golden_array.shape[:2]
    candidate_shape = candidate_array.shape[:2]
    if golden_shape != candidate_shape:
        raise ValueError(
            f"{view_name}: golden {golden_shape} and candidate "
            f"{candidate_shape} differ in size"
        )
    if golden_array.size == 0:
        raise EmptyFrame(f"{view_name}: the golden and candidate frames have no pixels")

    background_rgb = _background_rgb(golden_array)
    golden_mask = _subject_mask(golden_array, background_rgb)
    candidate_mask = _subject_mask(candidate_array, background_rgb)
    union = golden_mask | candidate_mask
    intersection = golden_mask & candidate_mask
    pixel_count = union.size
    union_count = int(union.sum())
    if union_count == 0:
        raise EmptyFrame(
            f"{view_name}: no subject pixels in either frame — an empty "
            f"frame must not score a perfect match"
        )
    subject_fraction = union_count / pixel_count
    if not (MINIMUM_SUBJECT_FRACTION <= subject_fraction <= MAXIMUM_SUBJECT_FRACTION):
        raise EmptyFrame(
            f"{view_name}: subject pixel fraction {subject_fraction:.4f} "
            f"outside [{MINIMUM_SUBJECT_FRACTION}, {MAXIMUM_SUBJECT_FRACTION}] "
            f"— the frame is empty or the background leaked in"
        )
    silhouette_iou = float(intersection.sum() / union_count)
    squared = numpy.square(golden_array[:, :, :3] - candidate_array[:, :, :3])
    shading_rmse = float(numpy.sqrt(numpy.mean(squared[union])))
    return ViewComparison(
        view_name=view_name,
        silhouette_iou=silhouette_iou,
        shading_rmse=shading_rmse,
        subject_pixel_fraction=subject_fraction,
    )


def compare_view_files(
    view_name, golden_path: Path, candidate_path: Path
) -> ViewComparison:
    """Load two PNGs through Blender's image API and compare them."""
    from blended.capture.compose import load_image_as_array

    golden_array = load_image_as_array(golden_path)
    try:
        candidate_array = load_image_as_array(candidate_path)
        try:
            return compare_view_arrays(view_name, golden_array, candidate_array)
        finally:
            del candidate_array
    finally:
        del golden_array


def load_thresholds(path: Path = CALIBRATION_PATH) -> VisualGateThresholds:
    """Read the measured thresholds; refuse to guess when absent."""
    path = Path(path)
    if not path.exists():
        raise VisualGateNotCalibrated(
            f"no calibration file at {path} — run "
            f"`make calibrate-visual-gate REVISION=10` before trusting the gate"
        )
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    return VisualGateThresholds(
        minimum_silhouette_iou=payload["minimum_silhouette_iou"],
        maximum_shading_rmse=payload["maximum_shading_rmse"],
    )


def gate_failures(comparisons, thresholds: VisualGateThresholds) -> list[str]:
    """Verdict logic on pure floats: no numpy, so the pure tier can test
    it without adding a dependency."""
    found: list[str] = []
    for comparison in comparisons:
        if comparison.silhouette_iou < thresholds.minimum_silhouette_iou:
            found.append(
                f"{comparison.view_name}: silhouette IoU "
                f"{comparison.silhouette_iou:.4f} below "
                f"{thresholds.minimum_silhouette_iou:.4f} (the render moved)"
            )
        if comparison.shading_rmse > thresholds.maximum_shading_rmse:
            found.append(
                f"{comparison.view_name}: shading RMSE "
                f"{comparison.shading_rmse:.4f} above "
                f"{thresholds.maximum_shading_rmse:.4f} (the render moved)"
            )
    return found
