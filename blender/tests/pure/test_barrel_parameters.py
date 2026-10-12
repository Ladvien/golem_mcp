"""Pure layer: barrel parameters and the bulge math, no bpy."""

import pytest

from blended.builders.barrel import BarrelParameters


def test_default_parameters_validate():
    BarrelParameters().validate()


def test_straight_cylinder_allowed_bulge_below_one_rejected():
    BarrelParameters(bulge_factor=1.0).validate()
    with pytest.raises(ValueError):
        BarrelParameters(bulge_factor=0.9).validate()


def test_radius_peaks_at_mid_height():
    parameters = BarrelParameters()
    end_radius = parameters.radius_at_height(0.0)
    middle_radius = parameters.radius_at_height(parameters.height_m / 2.0)
    assert middle_radius > end_radius
    assert end_radius == pytest.approx(parameters.end_radius_m)
    assert middle_radius == pytest.approx(
        parameters.end_radius_m * parameters.bulge_factor
    )
