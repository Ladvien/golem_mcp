"""Pure layer: CrateParameters must validate without bpy installed."""

import pytest

from blended.builders.crate import CrateParameters


def test_default_parameters_validate():
    CrateParameters().validate()


def test_zero_dimension_rejected():
    with pytest.raises(ValueError):
        CrateParameters(width_m=0.0).validate()


def test_oversized_bevel_rejected():
    with pytest.raises(ValueError):
        CrateParameters(bevel_width_m=0.5).validate()


def test_zero_segment_bevel_rejected():
    with pytest.raises(ValueError):
        CrateParameters(bevel_segment_count=0).validate()
