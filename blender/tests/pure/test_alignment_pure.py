"""The pure half of a feature placement (issue #25): no bpy, no scene.

The vocabulary, the axis choice and the gap's SIGN are decisions, not
measurements, so they are testable without Blender — and they are where
a placement silently goes wrong. The app layer
(`tests/blender/test_alignment_ops.py`) measures the eight acceptance
conditions on real meshes; this layer pins the rules those
measurements rest on.
"""

from __future__ import annotations

import pytest

from golem_blender.ops import alignment
from golem_blender.ops._contract import changes_scene, facade_ops, is_gated
from golem_blender.ops.alignment import (
    FEATURE_KINDS,
    STAND_AGAINST_SIDES,
    TargetPlane,
    _feature_axis,
    _feature_kind,
    _gap_sign,
    _parse_target_plane,
    _resolve_axis,
    _shortest_axis,
)

# --- the vocabulary ------------------------------------------------------


@pytest.mark.parametrize(
    "feature,kind,axis",
    [
        ("min_x", "min", "x"),
        ("max_x", "max", "x"),
        ("min_y", "min", "y"),
        ("max_y", "max", "y"),
        ("min_z", "min", "z"),
        ("max_z", "max", "z"),
        ("center", "center", None),
    ],
)
def test_every_feature_splits_into_a_kind_and_an_axis(feature, kind, axis):
    assert _feature_kind(feature) == kind
    assert _feature_axis(feature) == axis


def test_the_feature_vocabulary_is_the_issues_seven_names():
    """The issue names exactly these; a new one is a new decision."""
    assert FEATURE_KINDS == (
        "min_x",
        "max_x",
        "min_y",
        "max_y",
        "min_z",
        "max_z",
        "center",
    )


def test_an_unknown_feature_is_refused_with_the_vocabulary():
    with pytest.raises(ValueError, match="outer_x"):
        _feature_kind("outer_x")


# --- the target plane ---------------------------------------------------


def test_the_issues_triple_and_the_dataclass_are_the_same_target():
    """`("plane", "y", 2.594)` (the issue's spelling) and
    `TargetPlane("y", 2.594)` must parse identically, or the two
    spellings would place differently."""
    from_triple = _parse_target_plane(("plane", "y", 2.594))
    from_dataclass = _parse_target_plane(TargetPlane(axis="y", coordinate_m=2.594))
    assert from_triple == from_dataclass == TargetPlane(axis="y", coordinate_m=2.594)


def test_a_feature_name_is_not_a_plane():
    assert _parse_target_plane("min_y") is None


@pytest.mark.parametrize(
    "malformed",
    [
        ("plane", "w", 1.0),  # no such axis
        ("plane", "y"),  # two items
        ("wall", "y", 1.0),  # wrong word
    ],
)
def test_a_malformed_plane_shape_is_a_value_error(malformed):
    with pytest.raises(ValueError):
        _parse_target_plane(malformed)


@pytest.mark.parametrize(
    "mistyped",
    [
        ("plane", "y", "2.594"),  # a coordinate is a number, not a string
        ("plane", "y", True),  # a bool is not a coordinate
    ],
)
def test_a_mistyped_plane_coordinate_is_a_type_error(mistyped):
    """A wrong TYPE is a type error, a wrong shape a value error — the
    distinction a caller's `except` clause depends on."""
    with pytest.raises(TypeError, match="coordinate"):
        _parse_target_plane(mistyped)


def test_a_non_plane_non_string_target_is_a_type_error():
    with pytest.raises(TypeError, match="target_feature"):
        _parse_target_plane(7)


# --- the axis ------------------------------------------------------------


def test_two_features_on_one_axis_agree():
    assert _resolve_axis("max_y", None, "min_y") == "y"
    assert _resolve_axis("min_x", None, "center") == "x"


def test_a_plane_names_its_own_axis():
    assert _resolve_axis("max_y", TargetPlane("y", 2.594), "min_y") == "y"
    assert _resolve_axis("center", TargetPlane("z", 0.0), "center") == "z"


def test_two_features_on_different_axes_are_refused():
    """No single translation puts an x face on a y face, so the op says
    so rather than silently picking one."""
    with pytest.raises(ValueError, match="different axes"):
        _resolve_axis("max_x", None, "min_y")
    with pytest.raises(ValueError, match="different axes"):
        _resolve_axis("max_y", TargetPlane("z", 0.0), "min_y")


def test_a_centre_to_centre_alignment_names_no_axis():
    assert _resolve_axis("center", None, "center") is None


def test_the_shortest_move_wins_and_ties_break_on_axis_order():
    assert _shortest_axis((0.0, 3.0, 0.5)) == "z"
    assert _shortest_axis((-2.0, 0.1, 1.0)) == "y"
    # Equal magnitudes: x, then y, then z — a defined answer, so a
    # centre-to-centre call is repeatable.
    assert _shortest_axis((1.0, 1.0, 1.0)) == "x"
    assert _shortest_axis((0.0, 2.0, 2.0)) == "y"


def test_an_axis_already_aligned_is_not_the_one_chosen():
    """A zero move achieves nothing, so it is never the shortest move.

    Measured need: an exact feature placement leaves ~1.4e-7 m of
    float32 residual on an axis it just aligned. Choosing that axis
    would report an alignment that translated nothing and leave the
    real one unmade.
    """
    assert _shortest_axis((1.0e-7, 3.0, 0.5)) == "z"
    assert _shortest_axis((0.0, -2.0, 1.0e-8)) == "y"


def test_features_that_already_agree_give_a_defined_axis_and_a_zero_move():
    """Every axis aligned is not an error: the features ARE aligned."""
    assert _shortest_axis((0.0, 0.0, 0.0)) == "x"


# --- the gap's sign -----------------------------------------------------


def test_a_positive_gap_stands_the_object_off_the_target():
    """`min` against `max`: the object is on the target's positive side,
    so standing off moves it further positive."""
    assert _gap_sign("min", "max") == 1.0


def test_a_maximum_face_against_a_minimum_face_stands_off_negatively():
    """`max_y` against `min_y` (the pier on the wall's near face): the
    object is on the target's negative side, so 2 mm of stand-off moves
    it 2 mm negative. Getting this sign backwards is what makes a gap
    overlap the target."""
    assert _gap_sign("max", "min") == -1.0
    assert _gap_sign("max", "plane") == -1.0


def test_a_centre_gap_and_a_same_side_gap_are_positive():
    assert _gap_sign("center", "center") == 1.0
    assert _gap_sign("min", "min") == 1.0
    assert _gap_sign("max", "max") == 1.0
    assert _gap_sign("min", "plane") == 1.0


# --- the sides ---------------------------------------------------------


def test_stand_againsts_four_sides_meet_the_opposite_wall_face():
    """`"+x"` is the object's own `max_x` face, meeting the wall's
    `min_x` — the issue's condition 3, as a table."""
    assert STAND_AGAINST_SIDES == ("+x", "-x", "+y", "-y")
    assert alignment.SIDE_OBJECT_FEATURE["+x"] == "max_x"
    assert alignment.SIDE_TARGET_FEATURE["+x"] == "min_x"
    assert alignment.SIDE_OBJECT_FEATURE["-x"] == "min_x"
    assert alignment.SIDE_TARGET_FEATURE["-x"] == "max_x"
    assert alignment.SIDE_OBJECT_FEATURE["+y"] == "max_y"
    assert alignment.SIDE_TARGET_FEATURE["+y"] == "min_y"
    assert alignment.SIDE_OBJECT_FEATURE["-y"] == "min_y"
    assert alignment.SIDE_TARGET_FEATURE["-y"] == "max_y"
    for side, axis in alignment.SIDE_AXIS.items():
        assert alignment.SIDE_OBJECT_FEATURE[side].endswith(axis), side
        assert alignment.SIDE_TARGET_FEATURE[side].endswith(axis), side


# --- the facade ---------------------------------------------------------


def test_the_three_placement_ops_are_scene_changers_and_gated():
    """Condition 8, at the layer that can see it without Blender. A
    placement changes the scene (so it needs a declared plan) and its
    report names the object it moved (so the gate measures it)."""
    ops = dict(facade_ops())
    for name in ("align_to", "stand_against", "span_between"):
        function = ops[name]
        assert is_gated(function), name
        assert changes_scene(function), name
