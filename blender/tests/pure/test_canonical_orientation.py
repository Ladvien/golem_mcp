"""The depth-axis orientation rule, measured as behavior.

The scored degree of freedom is which Blender axis lands on the depth
axis (Blender Y = glTF Z after `export_yup`), because the benchmark's
`chamfer_with_yaw` quotients out rotation about glTF Z only. The policy
measured over 145 dev references is "middle extent on the depth axis"
(mean cd_yawmin 0.0311 vs 0.0632 unconstrained — see
`scripts/orientation_policy_sim.py`).

Every assertion here is about the RESULT of applying the returned Euler
to an extent triple, never about the Euler's literal numbers: the
contract is where the middle extent ends up.
"""

import math

import pytest

from blended.ops.canonical_orientation import (
    DEGENERATE_EXTENT_M,
    DEPTH_AXIS_EXTENT_RANK,
    DEPTH_AXIS_INDEX,
    canonical_depth_axis_rotation_euler_rad,
    depth_axis_extent_rank,
    depth_axis_holds_middle_extent,
    middle_extent_m,
    orientation_reading,
)

QUARTER_TURN_RAD = math.pi / 2.0
DISTINCT_EXTENTS_M = (2.0, 1.0, 0.1)
EXTENT_TOLERANCE_M = 1e-12


def rotated_extents_m(extents_m, euler_rad):
    """Extents after a 90-degree-multiple XYZ Euler, by axis permutation.

    A quarter turn about Z swaps the X and Y extents; a quarter turn about
    X swaps Y and Z. Only those two (and identity) are legal outputs, so
    anything else is a contract violation, not a case to support.
    """
    x_rad, y_rad, z_rad = euler_rad
    assert y_rad == 0.0, f"no rotation about Y is ever needed: {euler_rad}"
    extent_x_m, extent_y_m, extent_z_m = extents_m
    if euler_rad == (0.0, 0.0, 0.0):
        return (extent_x_m, extent_y_m, extent_z_m)
    if x_rad == 0.0 and z_rad == pytest.approx(QUARTER_TURN_RAD):
        return (extent_y_m, extent_x_m, extent_z_m)
    if z_rad == 0.0 and x_rad == pytest.approx(QUARTER_TURN_RAD):
        return (extent_x_m, extent_z_m, extent_y_m)
    raise AssertionError(f"not a single quarter turn: {euler_rad}")


def permutations_of(extents_m):
    """Every ordering of three extents, as (x, y, z) triples."""
    first, second, third = extents_m
    return [
        (first, second, third),
        (first, third, second),
        (second, first, third),
        (second, third, first),
        (third, first, second),
        (third, second, first),
    ]


@pytest.mark.parametrize("extents_m", permutations_of(DISTINCT_EXTENTS_M))
def test_every_ordering_puts_the_middle_extent_on_the_depth_axis(extents_m):
    euler_rad = canonical_depth_axis_rotation_euler_rad(*extents_m)
    after_m = rotated_extents_m(extents_m, euler_rad)
    assert after_m[DEPTH_AXIS_INDEX] == pytest.approx(
        middle_extent_m(extents_m), abs=EXTENT_TOLERANCE_M
    )
    assert sorted(after_m) == sorted(extents_m), "a turn cannot resize anything"
    assert depth_axis_holds_middle_extent(after_m)


def test_the_anchor_case_turns_about_x():
    """X longest, Y thinnest: the middle 1.0 must come from Z onto Y."""
    euler_rad = canonical_depth_axis_rotation_euler_rad(2.0, 0.1, 1.0)
    assert euler_rad == (QUARTER_TURN_RAD, 0.0, 0.0)
    assert rotated_extents_m((2.0, 0.1, 1.0), euler_rad) == (2.0, 1.0, 0.1)


def test_a_triple_already_middle_on_depth_is_left_alone():
    assert canonical_depth_axis_rotation_euler_rad(2.0, 1.0, 0.1) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "extents_m",
    [(1.0, 1.0, 2.0), (2.0, 1.0, 1.0), (1.0, 2.0, 1.0), (1.0, 1.0, 1.0)],
)
def test_ties_are_deterministic_and_settle_after_one_call(extents_m):
    euler_rad = canonical_depth_axis_rotation_euler_rad(*extents_m)
    assert euler_rad == canonical_depth_axis_rotation_euler_rad(*extents_m)
    after_m = rotated_extents_m(extents_m, euler_rad)
    assert depth_axis_holds_middle_extent(after_m)
    # Applying the rule to its own output must be a no-op — the property
    # the emitted script's epilogue depends on when a run is re-baked.
    assert canonical_depth_axis_rotation_euler_rad(*after_m) == (0.0, 0.0, 0.0)


def test_a_cube_needs_no_rotation():
    assert canonical_depth_axis_rotation_euler_rad(1.0, 1.0, 1.0) == (0.0, 0.0, 0.0)


def test_degenerate_extents_are_a_failure_not_a_default():
    with pytest.raises(ValueError):
        canonical_depth_axis_rotation_euler_rad(0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        canonical_depth_axis_rotation_euler_rad(
            DEGENERATE_EXTENT_M / 2.0, 0.0, DEGENERATE_EXTENT_M / 2.0
        )


def test_negative_extents_are_rejected():
    with pytest.raises(ValueError):
        canonical_depth_axis_rotation_euler_rad(1.0, -1.0, 2.0)


def test_reported_rank_counts_strictly_larger_extents():
    assert depth_axis_extent_rank((2.0, 1.0, 0.1)) == DEPTH_AXIS_EXTENT_RANK
    assert depth_axis_extent_rank((0.1, 2.0, 1.0)) == 0
    assert depth_axis_extent_rank((2.0, 0.1, 1.0)) == 2


def test_the_middle_extent_is_the_median_value():
    assert middle_extent_m((0.1, 2.0, 1.0)) == 1.0
    assert middle_extent_m((1.0, 1.0, 2.0)) == 1.0


def test_the_reading_names_the_axis_holding_the_middle_extent():
    """The fact the writer could not see: which axis holds which extent.

    0.6 is the middle value of (0.9, 0.3, 0.6) and it sits on z, while
    the canonical depth axis is y — so the reading has to name both, or
    it tells the writer nothing it can act on.
    """
    reading = orientation_reading((0.9, 0.3, 0.6))
    assert reading == (
        "extents x 0.9000 y 0.3000 z 0.6000 m; "
        "middle extent on z, canonical depth axis is y"
    )


def test_the_reading_marks_an_already_canonical_object():
    """Middle extent 0.6 already on y: no axis to move to."""
    assert orientation_reading((0.9, 0.6, 0.3)) == (
        "extents x 0.9000 y 0.6000 z 0.3000 m; middle extent on y (canonical)"
    )


def test_the_reading_agrees_with_the_rotation_about_the_source_axis():
    """A reading that named a different axis than the rotation uses would
    be worse than no reading: the writer would move the wrong extent."""
    for extents_m in [
        (0.9, 0.3, 0.6),
        (0.3, 0.9, 0.6),
        (0.6, 0.3, 0.9),
        (2.0, 0.5, 1.0),
        (1.0, 2.0, 0.5),
        (0.5, 1.0, 2.0),
    ]:
        reading = orientation_reading(extents_m)
        rotation = canonical_depth_axis_rotation_euler_rad(*extents_m)
        already_canonical = rotation == (0.0, 0.0, 0.0)
        assert ("(canonical)" in reading) is already_canonical, (
            extents_m,
            reading,
            rotation,
        )


def test_the_reading_is_fixed_at_four_decimals():
    """Not cosmetic: 0.30001 and 0.3 are the same placement decision, and
    a full-precision float would make two identical situations read as
    different facts."""
    assert "y 0.3000 " in orientation_reading((0.9, 0.30001234, 0.6))
    assert "x 12.3457 " in orientation_reading((12.345678, 0.3, 0.6))
