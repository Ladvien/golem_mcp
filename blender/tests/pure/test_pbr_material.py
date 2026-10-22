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

    The steel's own value is the mean over the UNCOATED materials
    that name it - the aged plate at 0.429, the corrugated one at
    0.508 and the scratched one at 0.380 - so it is 0.4390 and not
    the single plate's own.
    """
    from golem_blender.pbr.palette import value_for_description

    description = (
        "aged, black, brown, dark, fine, glossy, industrial, metal, "
        "oxidized, polished, rust, rusty, smooth, steel"
    )
    assert value_for_description(description) == pytest.approx(0.4390, abs=0.02)


def test_a_coated_metal_wears_the_coat_not_the_metal():
    """A metal under a coat of paint is the PAINT's colour.

    The truth's own Metal027 and Metal029 are "black, covered, metal,
    painted, powder, steel" and measure lumas of 0.180 and 0.128 -
    while the uncoated "black" metal Metal046B measures 0.246 and the
    uncoated steel measures 0.4390.

    So a coated metal reads its TONE, and the coat is read as a flat
    painted SURFACE - by the extreme words - and not as a metal.

    And a coat is DARKER than the bare surface it covers: a powder
    coat is a matte paint and a paint is a flat dielectric, and a
    dielectric black is darker than a reflective one. The truth's own
    two coated steels average 0.154, and that is the value.
    """
    from golem_blender.pbr.palette import value_for_description

    coated = "black, covered, metal, painted, powder, steel"
    assert value_for_description(coated) == pytest.approx(0.154, abs=0.01)
    # And the UNCOATED black metal is a different thing entirely.
    assert value_for_description("black, dark, dirty, metal") == pytest.approx(
        0.2463, abs=0.01
    )


def test_a_metal_measures_the_mean_of_the_colours_it_names():
    """A metal names SEVERAL of its own colours, and they are MEANED.

    The truth's own Metal009, Metal011 and Metal007 are all "silver,
    steel", and they measure 0.582, 0.627 and 0.611. The colour tier
    read "steel" first, which is 0.439 - a third of the truth's.

    So the metal's value is the mean of the colour words it names,
    and a SCRATCHED sheet is darker: the truth's own Metal038 - a
    "metal, scratched, steel" at 0.381 - is darker than its own
    "steel" of 0.439.
    """
    from golem_blender.pbr.palette import value_for_description

    silver_steel = "brushed, bumpy, metal, scratches, silver, steel"
    assert value_for_description(silver_steel) == pytest.approx(0.569, abs=0.01)
    # And the SAME words without the scratches are brighter.
    assert value_for_description("metal, silver, steel") == pytest.approx(
        0.711, abs=0.01
    )


def test_a_metals_own_colour_table_beats_the_general_one():
    """A metal's colour is fitted on metals, not on the general words.

    The truth's own Metal062C is a "damaged, dirty, metal, platinum"
    at a luma of 0.733, and the general table's "platinum" is 0.1435
    - a fifth of the truth's.
    """
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("damaged, dirty, metal, platinum") == pytest.approx(
        0.7327, abs=0.01
    )
    # And the truth's own Metal032 is a "grey, metal, smooth" at 0.527
    # where the general "grey" is 0.7228.
    assert value_for_description("grey, metal, smooth") == pytest.approx(
        0.5268, abs=0.01
    )


def test_every_roughness_tier_word_has_a_value():
    """A tier word with no value is a KeyError, and it was fifteen.

    The rule reads a description's words in TIERS, and a tier word
    that the value table did not carry raised - so a description
    naming "plank", "sand", "clay", "velvet" or "checkerboard"
    could not be answered for at all, and those are common words in
    the truth's own.
    """
    from golem_blender.pbr.material import (
        MATERIAL_TIERS,
        METAL_TIERS,
        ROUGHNESS,
        STRUCTURE_TIERS,
    )

    for tier in list(METAL_TIERS) + list(STRUCTURE_TIERS) + list(MATERIAL_TIERS):
        for word in tier:
            assert word in ROUGHNESS, f"{word!r} is in a tier and has no value"


def test_a_roughness_comes_from_the_words_and_not_a_constant():
    """A surface's roughness is a twenty-fivefold range and the words say.

    The truth's own roughness runs from 0.037 on a polished marble to
    0.919 on a cloth, and the ORM's roughness was a CONSTANT - 0.60
    for every material.

    Measured over the truth's own hundred and fifty-nine: the rule's
    mean error is 0.1136 and a constant's 0.1552.
    """
    from golem_blender.pbr.material import roughness_for_description

    assert roughness_for_description("cloth, fabric") > 0.7
    assert roughness_for_description("asphalt, road") > 0.6
    assert roughness_for_description("metal, steel") < 0.5
    # And a word with no value of its own still answers.
    assert 0.0 <= roughness_for_description("velvet, fabric") <= 1.0
    assert 0.0 <= roughness_for_description("planks, wood") <= 1.0


def test_a_wood_is_warm_and_a_wood_is_never_the_extreme_word():
    """A wood's HUE is its own, and its VALUE is its finish.

    Every one of the truth's own twenty-eight woods is warmer in red
    than in blue - from +0.074 on the darkest to +0.530 on the
    orange one - and the truth's own Wood028 is a "black, brown,
    clean, dark, fine, smooth, wood" at +0.088: a dark BROWN and not
    a black.

    So "black" must not win the hue over "wood", and the extreme
    words must not win the value either: the "black" extreme said
    0.064 and the truth is 0.135.
    """
    from golem_blender.pbr.palette import hue_for_description, value_for_description

    hue = hue_for_description("black, brown, clean, dark, fine, smooth, wood")
    assert hue[0] > hue[2], "a wood is warmer in red than in blue"
    # And the value is the wood's own finish and not the extreme.
    assert value_for_description("black, brown, clean, dark, fine, smooth, wood") == (
        pytest.approx(0.2351, abs=0.01)
    )
    # And an ORANGE wood is the orange's own.
    assert value_for_description("orange, plain, smooth, wood") == pytest.approx(
        0.5357, abs=0.01
    )


def test_a_black_is_three_blacks_and_the_words_choose():
    """A "black" is a reflective one, a smooth one or a textured one.

    The truth's own fifteen blacks split three ways, and the word
    "black" cannot tell them apart:

    - a REFLECTIVE black catches the light and is the lightest:
      the truth's own Metal046B is 0.2463 and its Marble016 0.2436;
    - a SMOOTH dielectric has nowhere to catch it and is the
      darkest: the truth's own Plastic006 is 0.0303 and its
      Leather026 0.0976;
    - a TEXTURED dielectric is in between: the truth's own
      Plastic012A is 0.1700.

    So the rule reads the surface's kind, and the three values are
    fitted on the truth's own.
    """
    from golem_blender.pbr.palette import value_for_description

    # A reflective black.
    assert value_for_description("black, dark, dirty, metal") == pytest.approx(
        0.2463, abs=0.01
    )
    # A smooth dielectric black.
    assert value_for_description("black, plastic, shiny, smooth") == pytest.approx(
        0.0640, abs=0.01
    )
    # A textured dielectric black.
    assert value_for_description("black, plastic") == pytest.approx(0.1705, abs=0.01)


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

    The table is fitted on all hundred and fifty-four materials of
    the three truth sets, and "dirt" now names eleven of them with a
    mean of 0.4458 - so the ground's own kind is read and the
    colour's word is not.
    """
    from golem_blender.pbr.palette import value_for_description

    assert value_for_description("brown, dirt, dry, gravel, gray, ground") == (
        pytest.approx(0.4458, abs=0.02)
    )


def test_the_value_follows_the_material_s_kind():
    """A surface's KIND says how light it is, and its colour only
    when the kind is a generic one.

    The truth's two fabrics are 0.527 and 0.374 - the blue one and
    the orange one - so a "fabric" on its own says a thing's kind and
    not its colour, and the colour is what tells them apart. The
    truth's bricks are 0.459, 0.485 and 0.483: all the same, so
    their kind decides and their "natural" and "stone" words do not.

    Measured against the truth's own seventy, the rule as fitted has
    a mean error of 0.047 - and the colour's word alone has 0.158.

    The numbers are fitted on the WIDE sample - seventy real
    ambientcg sets over sixteen kinds - and not on the twenty
    hand-picked ones, because a fit against twenty materials is a fit
    against twenty materials. The fitter is
    `scripts/benchmarks/fit_palette.py`.
    """
    from golem_blender.pbr.palette import value_for_description

    # The blue fabric: the colour says 0.5266 and the kind 0.5240.
    assert value_for_description("blue, fabric, fur, microfiber, soft") == (
        pytest.approx(0.5266, abs=0.01)
    )
    # The orange one: the colour says 0.3743 and the kind 0.5240,
    # and the truth's own Fabric085 measures 0.374.
    #
    # The DARKEST colour named wins, and not the first one: a
    # description that says "orange, red" means a red-orange, and the
    # truth's own orange wool is 0.374 and the "orange" word's fitted
    # value is 0.4331.
    assert value_for_description("fabric, orange, red, wool") == (
        pytest.approx(0.3743, abs=0.01)
    )
    # The bricks: their kind says 0.4604 and their colour 0.4790.
    assert value_for_description("bricks, bricks113a, natural, stone") == (
        pytest.approx(0.4604, abs=0.01)
    )
    # The wood: its COLOUR says 0.5338, and the wood's own fitted
    # value says 0.4587 - and the truth's own Wood094 is a brown one
    # at 0.534.
    #
    # A wood's brightness is carried by its colour and not by its
    # kind: the truth's own four woods measure 0.633, 0.217, 0.541
    # and 0.649, and the words that tell them apart are "beige,
    # light" and "brown, espresso".
    assert value_for_description("brown, smooth, wood, wooden") == (
        pytest.approx(0.5338, abs=0.01)
    )


def test_a_line_pattern_is_drawn_both_ways_about_its_base():
    """A line pattern's surface is drawn LIGHTER and DARKER than its
    base, and not only darker.

    The blend was one-sided - the base colour where the darkness was
    zero and the line colour elsewhere - and the darkness's mean was
    0.657, so the base was reachable in NO part of the image: the
    whole surface was drawn in the line colour, which is the base
    darkened, and the wood came out at 0.73x the truth's brightness.

    The truth's own wood is the other way round: its p5 is 0.604 and
    its p95 is 0.690 around a mean of 0.649, so the base colour is
    the wood's median and the surface is drawn both ways about it.
    """
    from golem_blender.pbr.procedural import LINE_LIGHT_FRACTION

    assert LINE_LIGHT_FRACTION > 0.0


def test_a_pressed_sheet_s_ribs_run_as_rows():
    """A PRESSED sheet's ribs are horizontal, and a sheet that is not
    pressed keeps its bands as columns.

    The direction decides what the feature measure reads. The measure
    reads along a ROW, and the truth's corrugated steel measures 5.89
    features across at a period of 174 pixels while its ribs are
    sixteen pixels apart - the measure found the sheet's slow
    variation and not the ribs, because the ribs are horizontal.

    A sheet that is NOT pressed - a rolled or a brushed one - has no
    ribs at all: its bands are its own direction, and they stay.
    """
    from golem_blender.pbr.palette import metal_direction_for_description

    pressed = "corrugated, dark, gray, industrial, metal, pipe, ribbed, ridged, rough, steel, striped, urban, worn"
    assert metal_direction_for_description(pressed) is True
    rolled = "aged, black, brown, dark, fine, glossy, industrial, metal, oxidized, polished, rust, rusty, smooth, steel"
    assert metal_direction_for_description(rolled) is False


def test_a_description_s_word_order_does_not_decide_the_spread():
    """A description's words are alphabetical, so the first one says
    nothing about how much the surface varies.

    The fabric's truth measures a spread of 0.0090 and its first
    word is "blue"; the mossy rock's measures 0.0926 and its "rough"
    comes late. The material's own words decide.

    The rule is the word that names the FEWEST materials - the most
    specific - and not the tier's order. "fur" names ONE material in
    the wide set and its spread is the truth's own 0.0090; "fabric"
    names ten whose spreads run from 0.0032 to 0.1888.

    The numbers are fitted on the WIDE sample - eighty-seven real
    ambientcg sets - and not on the twenty hand-picked ones, because
    a fit against twenty materials is a fit against twenty materials.
    The fitter is `scripts/benchmarks/fit_palette.py`.
    """
    from golem_blender.pbr.palette import spread_for_description

    fabric = "blue, fabric, fur, microfiber, soft"
    rock = "forest, gray, green, irregular, moss, mossy, natural, old, rock, rough, stacked, stone"
    # The truth's own Fabric084 measures 0.0090 and its Rock064
    # measures 0.0926, and the table is fitted on all hundred and
    # fifty-four materials of the three truth sets.
    assert spread_for_description(fabric) == pytest.approx(0.0090, abs=0.002)
    assert spread_for_description(rock) == pytest.approx(0.0926, abs=0.004)


def test_the_spreads_are_the_truths_own():
    """Every spread is a truth's own measured value.

    The expectations are the truth's OWN measured spreads, and not
    the rule's own output: the truth's own Fabric085 is 0.0505, the
    truth's own Asphalt033 is 0.0178, the truth's own Concrete034
    is 0.0218 and the truth's own Ground108 is 0.1337.

    The numbers are fitted on ALL THREE sets - a hundred and fifty-four
    real ambientcg materials - and not on the twenty hand-picked
    ones, because a fit against twenty materials is a fit against
    twenty materials. The fitter is
    `scripts/benchmarks/refit_palette_tables.py`.
    """
    from golem_blender.pbr.palette import spread_for_description

    cases = {
        "fabric, orange, red, wool": 0.0508,
        "asphalt, charcoal, dark, granular, gray, industrial, matte, pavement, road, rough, urban": 0.0178,
        "concrete, grey, light, plaster, smooth": 0.0228,
        # The ground's own spread is the one the words cannot say:
        # "dirt" now names eleven materials whose spreads run from
        # 0.061 to 0.134, and the truth's own Ground108 is 0.1337.
        "brown, debris, dirt, gravel, gray, ground, river, riverbed, rocky, rough, rubble, scattered, uneven": 0.1123,
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
