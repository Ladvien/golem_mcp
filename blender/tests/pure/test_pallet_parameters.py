"""Pure layer: pallet parameters, no bpy."""

import pytest

from blended.builders.pallet import PalletParameters


def test_default_parameters_validate():
    PalletParameters().validate()


def test_boards_must_fit_along_length():
    with pytest.raises(ValueError):
        PalletParameters(deck_board_count=10, deck_board_width_m=0.14).validate()


def test_pitch_places_first_and_last_boards_at_ends():
    parameters = PalletParameters()
    last_board_center_x_m = (
        -parameters.length_m / 2.0
        + parameters.deck_board_width_m / 2.0
        + parameters.deck_board_pitch_m * (parameters.deck_board_count - 1)
    )
    expected_last_center_x_m = (
        parameters.length_m / 2.0 - parameters.deck_board_width_m / 2.0
    )
    assert last_board_center_x_m == pytest.approx(expected_last_center_x_m)
