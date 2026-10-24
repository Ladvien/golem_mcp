"""A GRASS's blades are at one pitch, whatever the surface's patches are.

The truth's own three grasses - Ground037 (a damp forest floor, 7.2 features
across), Grass001 (a mown lawn, 34.1) and Grass004 (a dense lawn, 93.1) - put
their blades 13.1 to 15.5 pixels apart at 1024 whatever their feature count
is. The lane drew six blades per FEATURE, so a forest floor's 9.8 features
became 59 blades across instead of 71: its scale read 3.09x the truth's in
the benchmark.

So the pitch is one number and the surface's own count is its patches. These
are the PURE assertions on the numbers the field is driven by; the measured
pixel proof is tests/blender/test_pbr_grass.py.
"""

from __future__ import annotations

from golem_blender.pbr.pattern import (
    GRASS_BLADE_ASPECT,
    GRASS_BLADE_DIRECTIONS,
    GRASS_BLADE_PIXELS,
    GRASS_GROUND_SHARE,
    GRASS_LEAF_SHARE,
    GRASS_TOOTH_SHARE,
)


def test_the_blade_pitch_is_the_truths_own_and_not_a_fraction_of_the_features():
    """The truths' own three grasses put their fine power's peak at 13.1,
    15.5 and 15.5 pixels at 1024. A pitch that followed the feature count
    would be 128 pixels on a forest floor's 9.8 features."""
    assert 12.0 <= GRASS_BLADE_PIXELS <= 16.5, GRASS_BLADE_PIXELS


def test_a_blade_is_longer_than_it_is_wide():
    """A blade is a stroke: the lane's is five times as long as it is wide,
    which is what makes the crest a line and not a patch."""
    assert 3 <= GRASS_BLADE_ASPECT <= 8, GRASS_BLADE_ASPECT


def test_the_blades_lie_every_way():
    """Every vector is WHOLE, so a blade turned along it still repeats on the
    tile, and several directions each fill their own patches."""
    assert len(GRASS_BLADE_DIRECTIONS) >= 4
    assert all(
        isinstance(x, int) and isinstance(y, int) for x, y in GRASS_BLADE_DIRECTIONS
    )
    assert len(set(GRASS_BLADE_DIRECTIONS)) == len(GRASS_BLADE_DIRECTIONS)


def test_the_field_mixes_blades_a_tooth_and_the_surface_s_own_ground():
    """The blades carry the pitch, the tooth the fine structure the measure
    reads, and the ground the patches: the three shares are the fit's, and
    none of them is the whole field."""
    shares = (GRASS_LEAF_SHARE, GRASS_TOOTH_SHARE, GRASS_GROUND_SHARE)
    assert all(0.0 < share < 0.7 for share in shares), shares
    assert abs(sum(shares) - 1.0) < 1e-9, shares
