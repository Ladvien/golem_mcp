"""`place_garment` on hand-built clouds whose answer is known by construction.

The clouds are the shape the function exists for: a T-posed torso with two long
arm bars, where a whole-band bounding box reads the arm span and the sliced
band does not.

In the Blender tier, not `tests/pure`: the arithmetic needs numpy, and this
repo's dev venv deliberately has none; `analyze/garment_placement.py` imports
it inside its functions exactly as `analyze/enclosure.py` does.
"""

import numpy as np
import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

from golem_blender.analyze.garment_placement import (
    UP_AXIS,
    apply_placement,
    horizontal_extents,
    place_garment,
    pleat_offsets,
)

# A torso 0.32 m along X and 0.28 m along Y, from the hips to the neck. The
# module calls the WIDER horizontal extent the width, so this torso's width is
# its X span and its depth the Y one.
TORSO_X_M = 0.32
TORSO_Y_M = 0.28
TORSO_BOTTOM_M = 0.90
TORSO_TOP_M = 1.45
# Two arm bars reaching out 0.85 m either side at shoulder height: the span a
# whole-band box would read.
ARM_SPAN_M = 0.85
ARM_THICKNESS_M = 0.09
SHOULDER_M = 1.40

BAND_BOTTOM_M = 1.00
BAND_TOP_M = 1.40


def _torso_with_arms() -> np.ndarray:
    """A T-posed body: a torso box plus two arm bars, as an (N, 3) cloud."""
    rng = np.random.default_rng(7)
    count = 4000
    torso = np.stack(
        [
            rng.uniform(-TORSO_X_M / 2, TORSO_X_M / 2, count),
            rng.uniform(-TORSO_Y_M / 2, TORSO_Y_M / 2, count),
            rng.uniform(TORSO_BOTTOM_M, TORSO_TOP_M, count),
        ],
        axis=1,
    )
    arms_per_side = 300
    arms = []
    for sign in (-1.0, 1.0):
        arms.append(
            np.stack(
                [
                    sign * rng.uniform(0.14, ARM_SPAN_M / 2, arms_per_side),
                    rng.uniform(-ARM_THICKNESS_M / 2, ARM_THICKNESS_M / 2, arms_per_side),
                    rng.uniform(SHOULDER_M - ARM_THICKNESS_M, SHOULDER_M + ARM_THICKNESS_M, arms_per_side),
                ],
                axis=1,
            )
        )
    return np.concatenate([torso, *arms])


def _garment(width_m: float, depth_m: float, height_m: float) -> np.ndarray:
    """An open elliptical tube of points, centred on the origin, standing on z=0."""
    rng = np.random.default_rng(11)
    count = 2000
    angle = rng.uniform(0.0, 2.0 * np.pi, count)
    radius = rng.uniform(0.85, 1.0, count)
    return np.stack(
        [
            radius * width_m / 2 * np.cos(angle),
            radius * depth_m / 2 * np.sin(angle),
            rng.uniform(0.0, height_m, count),
        ],
        axis=1,
    )


def test_a_t_posed_body_measures_its_torso_and_not_its_arm_span():
    body = _torso_with_arms()
    extents = horizontal_extents(body, BAND_BOTTOM_M, BAND_TOP_M)

    assert extents.width_m == pytest.approx(TORSO_X_M, abs=0.03)
    assert extents.depth_m == pytest.approx(TORSO_Y_M, abs=0.03)
    assert extents.wide_axis == 0, (
        f"the wide axis is {extents.wide_axis}; the torso is wider along X"
    )

    # The control: a whole-band box WOULD read the arms, so the slice-and-drop
    # is what produced the number above rather than a coincidence.
    band = body[(body[:, UP_AXIS] >= BAND_BOTTOM_M) & (body[:, UP_AXIS] <= BAND_TOP_M)]
    whole_band_span = float(band[:, 0].max() - band[:, 0].min())
    assert whole_band_span > 2 * extents.width_m, (
        f"the whole-band X span is {whole_band_span:.2f} m against a "
        f"{extents.width_m:.2f} m torso: this fixture does not exercise the guard"
    )


def test_a_garment_whose_wide_axis_is_y_gets_a_quarter_turn():
    body = _torso_with_arms()
    # Wide along Y (the body's NARROW axis), so it must be turned. `_garment`
    # lays `width_m` along X, so the turned cloud is the one to hand over.
    unturned = _garment(width_m=0.40, depth_m=0.26, height_m=1.0)
    garment = np.stack([-unturned[:, 1], unturned[:, 0], unturned[:, 2]], axis=1)
    placement = place_garment(garment, body, BAND_BOTTOM_M, BAND_TOP_M)

    assert placement.quarter_turn is True
    placed = apply_placement(garment, placement)
    placed_extents = horizontal_extents(
        placed, placement.band_m[0], placement.band_m[1]
    )
    body_extents = horizontal_extents(body, BAND_BOTTOM_M, BAND_TOP_M)
    assert placed_extents.wide_axis == body_extents.wide_axis, (
        "after the turn the garment's wide axis still disagrees with the body's"
    )


def test_a_garment_already_aligned_is_not_turned():
    body = _torso_with_arms()
    # `_garment` is wide along X, which is the body band's wide axis too.
    garment = _garment(width_m=0.40, depth_m=0.26, height_m=1.0)
    placement = place_garment(garment, body, BAND_BOTTOM_M, BAND_TOP_M)

    assert placement.quarter_turn is False


def test_after_placement_the_garment_spans_the_band_exactly():
    body = _torso_with_arms()
    garment = _garment(width_m=0.40, depth_m=0.20, height_m=1.0)
    placement = place_garment(garment, body, BAND_BOTTOM_M, BAND_TOP_M)
    placed = apply_placement(garment, placement)

    span = float(placed[:, UP_AXIS].max() - placed[:, UP_AXIS].min())
    assert span == pytest.approx(BAND_TOP_M - BAND_BOTTOM_M, abs=1e-9)
    # And its centre sits on the band's centre, which is where a garment is worn.
    centre_z = (placed[:, UP_AXIS].max() + placed[:, UP_AXIS].min()) / 2.0
    assert centre_z == pytest.approx((BAND_BOTTOM_M + BAND_TOP_M) / 2.0, abs=1e-9)


def _pleat_ring(around: int = 720, rings: int = 21, radius_m: float = 0.2) -> np.ndarray:
    """A deterministic open ring whose angles land exactly on a pleat's peaks and troughs.

    A random cloud samples sin(fold_count * theta) wherever it happens to,
    which is why it never reaches the full depth: measured on 2000 random
    points the deepest hem pleat was 0.0160 against the 0.02 asked for. This
    fixture samples every half degree, so sin(8*theta) hits ±1 exactly.
    """
    angles = np.linspace(0.0, 2.0 * np.pi, around, endpoint=False)
    heights = np.linspace(0.0, 1.0, rings)
    return np.array(
        [
            (radius_m * np.cos(angle), radius_m * np.sin(angle), height)
            for height in heights
            for angle in angles
        ]
    )


def test_pleats_are_zero_at_the_collar_and_deepest_at_the_hem():
    garment = _pleat_ring()
    centre_xy = (0.0, 0.0)
    offsets = pleat_offsets(
        garment,
        centre_xy,
        band_bottom_m=0.0,
        band_top_m=1.0,
        fold_count=8,
        fold_depth_m=0.02,
    )
    radii = np.hypot(offsets[:, 0], offsets[:, 1])
    heights = garment[:, UP_AXIS]

    at_hem = radii[heights <= heights.min() + 1e-9]
    at_collar = radii[heights >= heights.max() - 1e-9]
    assert at_collar.max() == pytest.approx(0.0, abs=1e-12)
    assert at_hem.max() == pytest.approx(0.02, abs=1e-3), (
        f"the hem's deepest pleat is {at_hem.max():.4f} m, not the 0.02 m asked for"
    )
    # Every pleat pushes OUTWARD, never in.
    radial_direction = garment[:, :2] / np.linalg.norm(garment[:, :2], axis=1, keepdims=True)
    assert float((offsets[:, :2] * radial_direction).sum(axis=1).min()) >= -1e-15


def test_no_folds_means_no_offsets():
    garment = _garment(width_m=0.40, depth_m=0.20, height_m=1.0)
    assert not pleat_offsets(garment, (0.0, 0.0), 0.0, 1.0, 0, 0.0).any()
    with pytest.raises(ValueError, match="fold_count must be 0 or more"):
        pleat_offsets(garment, (0.0, 0.0), 0.0, 1.0, -1, 0.02)


def test_a_band_with_no_geometry_in_it_is_refused():
    with pytest.raises(ValueError, match="no geometry between"):
        horizontal_extents(
            np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]), 2.0, 3.0
        )
