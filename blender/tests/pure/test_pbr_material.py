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
    """A clean silver is the brightest surface the lane makes.

    The truth's own Metal049A measures a luma of 0.9832, and the
    table said 0.92 - so the silver came out dimmer than the truth
    it was measured from.
    """
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("clean, metal, silver, smooth") == pytest.approx(
        0.9832, abs=0.01
    )


def test_a_non_metal_s_colour_is_unchanged():
    """Only a metal gets the tiered reading.

    The truth's own Ground110 measures a luma of 0.358, and the
    ground's three truths - 0.358, 0.411 and 0.424 - average
    0.3978; the table's 0.34 said "brown" and the ground is a
    gravel, and the words are alphabetical so the ground's own kind
    decides.
    """
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("brown, dirt, dry, gravel, gray, ground") == (
        pytest.approx(0.3912, abs=0.02)
    )


def test_the_value_follows_the_material_s_kind():
    """A surface's KIND says how light it is, and its colour only
    when the kind is a generic one.

    The truth's two fabrics are 0.527 and 0.374 - the blue one and
    the orange one - so a "fabric" on its own says a thing's kind and
    not its colour, and the colour is what tells them apart. The
    truth's bricks are 0.459, 0.485 and 0.483: all the same, so
    their kind decides and their "natural" and "stone" words do not.

    Measured against the truth's own twenty, the rule as fitted has
    a mean error of 0.047 - and the colour's word alone has 0.158.
    """
    from golem_blender.pbr.palette import value_for_description

    # The blue fabric: the colour says 0.5266 and the kind 0.4504.
    assert value_for_description("blue, fabric, fur, microfiber, soft") == (
        pytest.approx(0.5266, abs=0.01)
    )
    # The orange one: the colour says 0.3743 and the kind 0.4504.
    assert value_for_description("fabric, orange, red, wool") == (
        pytest.approx(0.3743, abs=0.01)
    )
    # The bricks: their kind says 0.4758 and their colour 0.5366.
    assert value_for_description("bricks, bricks113a, natural, stone") == (
        pytest.approx(0.4758, abs=0.01)
    )
    # The wood: its kind says 0.6012 and its colour 0.4364.
    assert value_for_description("brown, smooth, wood, wooden") == (
        pytest.approx(0.6012, abs=0.01)
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


def test_the_stone_ramp_reads_the_spread_it_was_built_for():
    """The stones' colours are drawn UNIFORMLY across the ramp, and a
    uniform distribution's standard deviation is its half-width over
    the root of three.

    So a ramp of the right half-width reads 0.58x the spread it was
    built for, and the ramp is widened by the root of three to
    compensate. Measured against every truth: the fabric read 0.57x,
    the brick 0.47x, the rock 0.49x and the asphalt 0.55x.
    """
    import random
    import statistics

    from golem_blender.pbr.palette import RAMP_SPREAD_FACTOR

    spread = 0.05
    half_width = spread * RAMP_SPREAD_FACTOR
    generator = random.Random(0)
    drawn = [generator.uniform(-half_width, half_width) for _ in range(20000)]
    assert statistics.pstdev(drawn) == pytest.approx(spread, rel=0.05)


def test_the_joint_is_as_dark_as_the_surface_varies():
    """A joint is part of the surface's variation, not a separate
    darkness. A fixed 0.06 offset is six times the whole spread of a
    soft fabric."""
    from golem_blender.pbr.palette import (
        palette_for_description,
        spread_for_description,
    )

    def luma(rgb: tuple[float, float, float]) -> float:
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]

    palette = palette_for_description("blue, fabric, fur, microfiber, soft")
    spread = spread_for_description("blue, fabric, fur, microfiber, soft")
    # The mortar is the value less the SPREAD, so the joint is as
    # dark as the surface varies and no darker. The ramp's own dark
    # end is further out, because the ramp is widened to compensate
    # for the uniform draw.
    #
    # The measure is the LUMA, not a channel: the palette is
    # chromatic now, and the channels are not the luma - a blue
    # fabric's red channel is 0.24 while its luma is 0.33.
    value = (luma(palette["stone_dark_rgb"]) + luma(palette["stone_light_rgb"])) / 2.0
    assert luma(palette["mortar_rgb"]) == pytest.approx(value - spread, abs=1e-6)
