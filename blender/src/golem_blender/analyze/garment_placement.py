"""Put a generated garment onto a body: quarter turn, one scale, one translation, then pleats.

Why this module exists: a TRELLIS-made garment arrives in an arbitrary pose and
an arbitrary orientation, and every number that matters afterwards — the
clearance, the weights, whether a fold reads — is measured on the garment
WHERE IT SITS. So the placement has to be arithmetic a test can pin, not a
button in a viewport.

Ported from `scripts/garment_fit.py` (`horizontal_extents`, `place`), which
measured the failure it guards against: a whole-band bounding box on a T-pose
body reads the ARM SPAN (1.70 m at shoulder height against a 0.31 m chest), and
a garment scaled to enclose that came out 0.94 m tall on a 1.7 m figure. The fix
is to slice the band and drop the anomalously wide slices, because limbs are
narrow in a slice and the torso is not.

Blender's frame (Z up), so `UP_AXIS = 2`; the script's glTF frame has it at 1.
"""

from __future__ import annotations

from dataclasses import dataclass

UP_AXIS = 2

# A band slice wider than this multiple of the band's median slice width is a
# LIMB crossing it, not the torso. Measured on the original script's
# `female_base_v5`: torso slices 0.27-0.35 m, shoulder slices 1.70 and 0.97.
ARM_SLICE_REJECT = 2.0

# Slices taken through a band before the wide ones are dropped. 24 over a
# 0.27 m torso band is an 11 mm slice — finer than any torso's change of
# section, and coarse enough that a single odd vertex cannot own a slice.
BAND_SLICE_COUNT = 24

# The fewest points a slice needs before its extents mean anything.
MINIMUM_POINTS_PER_SLICE = 3


@dataclass(frozen=True)
class HorizontalExtents:
    """A band's cross-section measured without its limbs.

    `width_m` is the WIDER of the two horizontal extents and `depth_m` the
    narrower, whatever world axes they happen to sit on — the names are the
    body's, not the scene's. `wide_axis` and `narrow_axis` say which world axes
    those were, and they are what the quarter turn compares.
    """

    depth_m: float
    width_m: float
    wide_axis: int
    narrow_axis: int


@dataclass(frozen=True)
class Placement:
    """What `place_garment` did, in numbers a test can assert."""

    quarter_turn: bool
    scale: float
    translation_m: tuple[float, float, float]
    band_m: tuple[float, float]
    body_depth_m: float
    body_width_m: float


def horizontal_extents(
    points, band_bottom_m: float, band_top_m: float
) -> HorizontalExtents:
    """Robust (depth, width) of the points in a vertical band, ignoring limbs.

    `points` is an (N, 3) array in world metres. Slices the band along the up
    axis, measures each slice's horizontal spans, and drops the slices more
    than `ARM_SLICE_REJECT` times the median width apart: those are the ones an
    arm crosses.
    """
    import numpy as np

    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must be (N, 3), got {points.shape}")
    horizontal_axes = [axis for axis in range(3) if axis != UP_AXIS]
    band = points[
        (points[:, UP_AXIS] >= band_bottom_m) & (points[:, UP_AXIS] <= band_top_m)
    ]
    if len(band) == 0:
        raise ValueError(
            f"no geometry between {band_bottom_m:.3f} and {band_top_m:.3f} m on "
            f"the up axis"
        )

    edges = np.linspace(band_bottom_m, band_top_m, BAND_SLICE_COUNT + 1)
    per_slice: list[list[float]] = []
    for index in range(BAND_SLICE_COUNT):
        inside = band[
            (band[:, UP_AXIS] >= edges[index]) & (band[:, UP_AXIS] < edges[index + 1])
        ]
        if len(inside) < MINIMUM_POINTS_PER_SLICE:
            continue
        per_slice.append(
            [
                float(inside[:, axis].max() - inside[:, axis].min())
                for axis in horizontal_axes
            ]
        )
    if not per_slice:
        per_slice = [
            [
                float(band[:, axis].max() - band[:, axis].min())
                for axis in horizontal_axes
            ]
        ]
    slices = np.array(per_slice)

    widest = slices.max(axis=1)
    kept = slices[widest <= ARM_SLICE_REJECT * np.median(widest)]
    if len(kept) == 0:
        kept = slices
    spans = {
        axis: float(kept[:, index].max()) for index, axis in enumerate(horizontal_axes)
    }
    wide_axis = max(spans, key=spans.get)
    narrow_axis = min(spans, key=spans.get)
    return HorizontalExtents(
        depth_m=spans[narrow_axis],
        width_m=spans[wide_axis],
        wide_axis=wide_axis,
        narrow_axis=narrow_axis,
    )


def place_garment(
    garment_points, body_points, band_bottom_m: float, band_top_m: float
) -> Placement:
    """Yaw the garment a quarter turn if its wide axis disagrees, scale it to span the band, centre it.

    The rules, in order:

      1. A QUARTER TURN about the up axis when the garment's wide horizontal
         axis differs from the body band's. A tunic made front-to-back reads
         sideways until it is turned.
      2. A UNIFORM SCALE so the garment's height spans the band exactly. The
         garment's own proportions decide its girth: TRELLIS normalises by the
         largest dimension, so a garment that is 0.7 wide per 1.0 tall really is
         that shape, and scaling on height gets the girth right for free.
         Scaling to ENCLOSE the body instead does not — measured in the original
         script: the band's widest slice includes the deltoids, and matching
         that made a corset 0.94 m tall on a 1.7 m body.
      3. A TRANSLATION putting the garment's centre on the band's centre
         vertically and on the body band's centre horizontally.

    Returns what it did; `apply_placement` performs it.
    """
    import numpy as np

    garment_points = np.asarray(garment_points, dtype=float)
    body_points = np.asarray(body_points, dtype=float)
    if band_top_m <= band_bottom_m:
        raise ValueError(
            f"band_top_m ({band_top_m}) must be above band_bottom_m ({band_bottom_m})"
        )
    if len(garment_points) == 0:
        raise ValueError("garment_points is empty")

    body_extents = horizontal_extents(body_points, band_bottom_m, band_top_m)
    garment_height_m = float(
        garment_points[:, UP_AXIS].max() - garment_points[:, UP_AXIS].min()
    )
    if garment_height_m <= 0.0:
        raise ValueError(
            "the garment has no extent on the up axis, so it cannot be scaled to span a band"
        )
    garment_extents = horizontal_extents(
        garment_points,
        float(garment_points[:, UP_AXIS].min()),
        float(garment_points[:, UP_AXIS].max()),
    )
    quarter_turn = garment_extents.wide_axis != body_extents.wide_axis

    scale = (band_top_m - band_bottom_m) / garment_height_m
    # The garment's centre after the turn and the scale, before the move.
    garment_min = garment_points.min(axis=0)
    garment_max = garment_points.max(axis=0)
    garment_centre = _turned_centre((garment_min + garment_max) / 2.0, quarter_turn)
    body_band = body_points[
        (body_points[:, UP_AXIS] >= band_bottom_m)
        & (body_points[:, UP_AXIS] <= band_top_m)
    ]
    horizontal_axes = [axis for axis in range(3) if axis != UP_AXIS]
    target = np.zeros(3, dtype=float)
    target[UP_AXIS] = (band_bottom_m + band_top_m) / 2.0
    for axis in horizontal_axes:
        target[axis] = (body_band[:, axis].min() + body_band[:, axis].max()) / 2.0
    translation = target - garment_centre * scale
    return Placement(
        quarter_turn=quarter_turn,
        scale=scale,
        translation_m=tuple(float(x) for x in translation),
        band_m=(float(band_bottom_m), float(band_top_m)),
        body_depth_m=body_extents.depth_m,
        body_width_m=body_extents.width_m,
    )


def _turned_centre(centre, quarter_turn: bool):
    """Where the centre lands after the quarter turn, which is about the ORIGIN.

    The turn is `(x, y) -> (-y, x)`, so the centre moves unless it is on the up
    axis. A translation computed from the unturned centre lands the garment
    off-centre by exactly the turn's own displacement — measured on a
    garment centred at (0.3, 0.1): 0.32 m off the body band's centre.
    """
    import numpy as np

    turned = np.asarray(centre, dtype=float).copy()
    if quarter_turn:
        horizontal_axes = [axis for axis in range(3) if axis != UP_AXIS]
        first, second = horizontal_axes
        turned[first] = -float(centre[second])
        turned[second] = float(centre[first])
    return turned


def apply_placement(points, placement: Placement):
    """The turned, scaled, translated points of `place_garment`'s decision."""
    import numpy as np

    points = np.asarray(points, dtype=float)
    turned = points.copy()
    if placement.quarter_turn:
        # Exactly 90 degrees about the up axis: (x, y) -> (-y, x). No sin/cos,
        # so there is no rounding to disagree about.
        horizontal_axes = [axis for axis in range(3) if axis != UP_AXIS]
        first, second = horizontal_axes
        turned[:, first] = -points[:, second]
        turned[:, second] = points[:, first]
    return turned * placement.scale + np.asarray(placement.translation_m, dtype=float)


def pleat_offsets(
    points, axis_xy_m, band_bottom_m, band_top_m, fold_count: int, fold_depth_m: float
):
    """A radial outward displacement that deepens toward the hem.

    `depth * max(0, sin(fold_count * theta)) * ramp`, where theta is the angle
    about the vertical axis through `axis_xy_m` and

        ramp = clip((band_top - z) / (band_top - band_bottom), 0, 1)

    so the pleats are ZERO at the collar and their full depth at the hem — which
    is what a pleat does: a gathered skirt is flat at the waist and folded where
    the cloth has room.
    """
    import numpy as np

    points = np.asarray(points, dtype=float)
    if fold_count < 0:
        raise ValueError(f"fold_count must be 0 or more, got {fold_count}")
    if fold_depth_m < 0.0:
        raise ValueError(f"fold_depth_m must be 0 or more, got {fold_depth_m}")
    offsets = np.zeros_like(points)
    if fold_count == 0 or fold_depth_m == 0.0:
        return offsets
    if band_top_m <= band_bottom_m:
        raise ValueError(
            f"band_top_m ({band_top_m}) must be above band_bottom_m ({band_bottom_m})"
        )

    horizontal_axes = [axis for axis in range(3) if axis != UP_AXIS]
    dx = points[:, horizontal_axes[0]] - axis_xy_m[0]
    dy = points[:, horizontal_axes[1]] - axis_xy_m[1]
    radii = np.hypot(dx, dy)
    safe_radii = np.where(radii > 0.0, radii, 1.0)
    theta = np.arctan2(dy, dx)
    ramp = np.clip(
        (band_top_m - points[:, UP_AXIS]) / (band_top_m - band_bottom_m), 0.0, 1.0
    )
    depth = fold_depth_m * np.maximum(0.0, np.sin(fold_count * theta)) * ramp
    offsets[:, horizontal_axes[0]] = np.where(radii > 0.0, depth * dx / safe_radii, 0.0)
    offsets[:, horizontal_axes[1]] = np.where(radii > 0.0, depth * dy / safe_radii, 0.0)
    return offsets
