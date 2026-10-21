"""The ORM a description calls for.

The lane bakes its ORM with a CONSTANT roughness of 0.85 and a
constant metallic of 0.0 for every material it makes. The truth's
roughness runs from 0.034 on a polished metal to 0.793 on a fabric,
so the ORM was wrong for every material the lane made.

These tests pin the behaviour that fixed it: the roughness follows
the description's words, a metal is metallic, and the words are read
in their order of authority rather than the description's order.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from golem_blender.pbr.material import (
    is_metal,
    orm_for_description,
    roughness_for_description,
)


def test_a_metal_is_metallic():
    """A metal's metallic channel is 1, and that is what makes it metal."""
    assert orm_for_description("clean, metal, silver, smooth")["metallic"] == 1.0
    assert orm_for_description("aged, rusty, oxidized, steel")["metallic"] == 1.0


def test_everything_else_is_not_metallic():
    assert orm_for_description("brown, dirt, dry, gravel, ground")["metallic"] == 0.0
    assert orm_for_description("beige, grain, knots, wood")["metallic"] == 0.0


def test_the_metal_words_are_whole_words():
    """A description with 'minimalist' in it is not a metal.

    A substring test read 'minimalist' as 'metal' and made a wooden
    floor metallic.
    """
    assert not is_metal("beige, clean, indoor, light, minimalist, wood")
    assert is_metal("corrugated, dark, gray, industrial, metal, steel")


def test_a_polished_metal_is_glossy():
    """The truth's polished, oxidised steel measures 0.134."""
    description = (
        "aged, black, brown, dark, fine, glossy, industrial, metal, "
        "oxidized, polished, rust, rusty, smooth, steel"
    )
    assert roughness_for_description(description) == pytest.approx(0.13, abs=0.02)


def test_a_clean_silver_metal_is_the_smoothest():
    """The truth's clean silver measures 0.034."""
    assert roughness_for_description("clean, metal, silver, smooth") == pytest.approx(
        0.03, abs=0.02
    )


def test_a_corrugated_metal_is_rough():
    """The truth's corrugated steel measures 0.474."""
    description = (
        "corrugated, dark, gray, industrial, metal, pipe, ribbed, ridged, "
        "rough, steel, striped, urban, worn"
    )
    assert roughness_for_description(description) == pytest.approx(0.47, abs=0.02)


def test_a_metal_s_finish_outranks_its_material_word():
    """A metal's roughness is its finish, not its first word.

    'aged' would have said 0.45, and the truth says 0.134.
    """
    assert roughness_for_description("aged, metal, steel") == pytest.approx(
        0.13, abs=0.02
    )


def test_a_material_word_outranks_a_surface_word():
    """A rock with moss on it is still a rock. The truth measures 0.552."""
    description = (
        "forest, gray, green, irregular, moss, mossy, natural, rock, rough, stone"
    )
    assert roughness_for_description(description) == pytest.approx(0.55, abs=0.03)


def test_a_structure_word_outranks_its_material_word():
    """A pine board with knots measures 0.670; the same wood without
    them measures 0.492. The knots decide."""
    with_knots = "beige, grain, knots, light, natural, smooth, softwood, wood"
    without = "brown, smooth, wood, wooden"
    assert roughness_for_description(with_knots) == pytest.approx(0.67, abs=0.02)
    assert roughness_for_description(without) == pytest.approx(0.49, abs=0.03)


def test_the_words_are_read_in_authority_not_in_the_description_s_order():
    """'grain, knots' names the knots first in the sentence, and the
    knots are the rougher thing, so the knots decide."""
    description = "beige, grain, knots, light, natural, smooth, softwood, wood"
    assert roughness_for_description(description) > roughness_for_description(
        "beige, grain, light, natural, smooth, softwood, wood"
    )


def test_a_fabric_is_rough_and_an_asphalt_is_rough():
    """The truth's fabrics measure 0.784 and 0.793, and its asphalt
    0.745."""
    assert roughness_for_description("fabric, orange, red, wool") == pytest.approx(
        0.78, abs=0.03
    )
    assert roughness_for_description("asphalt, charcoal, dark, granular, gray") == (
        pytest.approx(0.75, abs=0.03)
    )


def test_a_description_with_nothing_sayable_gets_the_default():
    assert roughness_for_description("zzz qqq") == pytest.approx(0.60)


def test_a_metal_s_colour_comes_from_the_sheet_not_the_rust():
    """A metal's colour words name the rust on it, not the metal.

    Measured, the steel plate reads a luma of 0.429 - a mid grey-blue
    - and the words "black" and "brown" would have said 0.06.
    """
    from golem_blender.pbr.palette import value_for_description

    description = (
        "aged, black, brown, dark, fine, glossy, industrial, metal, "
        "oxidized, polished, rust, rusty, smooth, steel"
    )
    assert value_for_description(description) == pytest.approx(0.43, abs=0.02)


def test_a_clean_silver_metal_is_bright():
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("clean, metal, silver, smooth") == pytest.approx(
        0.92, abs=0.05
    )


def test_a_non_metal_s_colour_is_unchanged():
    """Only a metal gets the tiered reading."""
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("brown, dirt, dry, gravel, gray, ground") == (
        pytest.approx(0.34, abs=0.02)
    )


def test_a_description_s_word_order_does_not_decide_the_spread():
    """A description's words are alphabetical, so the first one says
    nothing about how much the surface varies.

    The fabric's truth measures a spread of 0.0090 and its first
    word is "blue"; the mossy rock's measures 0.0926 and its "rough"
    comes late. The material's own words decide.
    """
    from golem_blender.pbr.palette import spread_for_description

    fabric = "blue, fabric, fur, microfiber, soft"
    rock = "forest, gray, green, irregular, moss, mossy, natural, old, rock, rough, stacked, stone"
    assert spread_for_description(fabric) == pytest.approx(0.0090, abs=0.002)
    assert spread_for_description(rock) == pytest.approx(0.0926, abs=0.004)


def test_the_spreads_are_the_truths_own():
    """Every spread is a truth's own measured value."""
    from golem_blender.pbr.palette import spread_for_description

    cases = {
        "fabric, orange, red, wool": 0.0505,
        "asphalt, charcoal, dark, granular, gray, industrial, matte, pavement, road, rough, urban": 0.0178,
        "concrete, grey, light, plaster, smooth": 0.0218,
        "brown, debris, dirt, gravel, gray, ground, river, riverbed, rocky, rough, rubble, scattered, uneven": 0.1290,
    }
    for description, expected in cases.items():
        assert spread_for_description(description) == pytest.approx(expected, abs=0.004)
