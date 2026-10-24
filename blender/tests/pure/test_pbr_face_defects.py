"""A light asphalt is not a dark one, and a tile face is pitted.

The truths' own eight asphalt-kind materials split by lightness: a dark
asphalt is a binder with dark chips and its surface is even (Asphalt033's
cv 0.055), a light one is pale chips standing out of it (Asphalt031's cv
0.163) - and the lane carried one flat spread for both, so Asphalt031's
contrast read 0.36x its truth's in the benchmark.

And the truths' own four tiled floors (Tiles139, 141, 143, 144) carry 37 to
47 pits on each tile, three to four pixels across and three and a half
deviations deep; the lane's faces carried none, because a tooth is an
isotropic grain and a grain has no spots.

These are the PURE assertions: the numbers the writer is driven by. The
measured pixel proof lives in the benchmark (see the round's plan and the
close sheets); numpy is not in this tier.
"""

from __future__ import annotations

from golem_blender.pbr.palette import (
    ASPHALT_DARK_CV,
    ASPHALT_LIGHT_CV,
    palette_for_description,
    spread_for_description,
)
from golem_blender.pbr.procedural import (
    TILE_PIT_DEPTH,
    TILE_PIT_PITCH_PX,
    TILE_PIT_WIDTH_PX,
    TILE_STAIN_SHARE,
    TILE_TOOTH_SHARE,
)

LIGHT_ASPHALT = "asphalt, floor, grey, light, stone, street"
DARK_ASPHALT = "asphalt, charcoal, dark, granular, gray, industrial, pavement, road"
WEATHERED = (
    "asphalt, damaged, dark, gray, industrial, layered, modern, old, "
    "outdoor, pavement, road, rough, street, urban, worn"
)


def test_a_light_asphalt_varies_more_than_a_dark_one():
    """Asphalt031 is a "light" asphalt at a cv of 0.163 and Asphalt033 a
    dark one at 0.055. One flat 0.028 read Asphalt031's contrast 0.36x its
    truth's, the issue's first defect."""
    light = spread_for_description(LIGHT_ASPHALT)
    dark = spread_for_description(DARK_ASPHALT)
    assert light > 1.5 * dark, (light, dark)
    assert ASPHALT_LIGHT_CV > 1.5 * ASPHALT_DARK_CV


def test_a_light_asphalt_s_spread_is_its_truth_s_own_contrast():
    """Asphalt031's own luma spread is 0.0768 at a value of 0.626, and the
    fitted coefficient times the description's value reads 0.102 - within
    a third of the truth's, where the flat 0.028 read 0.36x it."""
    spread = spread_for_description(LIGHT_ASPHALT)
    value = palette_for_description(LIGHT_ASPHALT, path="asphalt")["target_value"]
    assert abs(spread / value - ASPHALT_LIGHT_CV) < 1e-9
    assert 0.9 <= spread / 0.0768 <= 1.4, spread


def test_a_dark_asphalt_stays_even():
    """A dark asphalt's surface is even - Asphalt033's spread is 0.0178 -
    and the fix must not lift it: Road014A read 1.37x the truth's before
    and 1.19x after."""
    spread = spread_for_description(DARK_ASPHALT)
    assert 0.020 <= spread <= 0.030, spread
    assert 0.020 <= spread_for_description(WEATHERED) <= 0.030


def test_the_pits_are_spots_of_a_fitting_size_and_sparseness():
    """The truths' pits are three to four pixels across at 1024 at 37 to 47
    to a five-by-five tile floor, which is a pit some thirty pixels apart:
    a pitch of twenty-eight and a width of eight puts one in each cell of a
    thirty-seven-across lattice."""
    assert 20.0 <= TILE_PIT_PITCH_PX <= 40.0, TILE_PIT_PITCH_PX
    assert 4.0 <= TILE_PIT_WIDTH_PX <= 12.0, TILE_PIT_WIDTH_PX
    pits_across = round(1024.0 / TILE_PIT_PITCH_PX)
    per_tile = (pits_across / 5.0) ** 2
    assert 30.0 <= per_tile <= 70.0, per_tile


def test_a_pit_is_three_and_a_half_deviations_deep():
    """The truths' pits sit 3.45-3.75 deviations below their face's mean,
    measured on the 2.2-sigma dark tail. The writer's depth is 4.6
    deviations of the SPREAD, which the threshold sees as 3.5."""
    assert 3.5 <= TILE_PIT_DEPTH <= 5.5, TILE_PIT_DEPTH


def test_the_face_carries_a_stain_and_a_tooth():
    """Tiles141 carries 0.30 of its spread at a sixty-four-pixel blur (the
    stain) and 0.55 finer than two pixels (the tooth), where the lane's
    face carried 0.13 and 0.67 - too fine and too flat."""
    assert 0.0 < TILE_STAIN_SHARE < 0.1, TILE_STAIN_SHARE
    assert 0.0 < TILE_TOOTH_SHARE < 0.1, TILE_TOOTH_SHARE
