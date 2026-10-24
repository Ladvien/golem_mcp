"""The pattern a DESCRIPTION calls for.

The benchmark chose the pattern with a keyword guess, and it guessed
wrong for the materials it measured on: the two woods read at 5.5x
the truth's feature scale, because a wave's bands are parallel and
evenly spaced and a wood grain's are not.

So the choice is the lane's own rule, and it is tested here: the
STRUCTURE is read first - a "wood floor" is a wood floor, a "stone
tile" is a stone tile - and the material second.
"""

from __future__ import annotations

import pytest

from golem_blender.pbr.patterns import DEFAULT_PATTERN, pattern_for_description


@pytest.mark.parametrize(
    ("description", "expected"),
    (
        # A wood floor is a wood floor, not a floor of something else.
        ("beige, grain, knots, light, natural, smooth, softwood, wood", "grain"),
        ("clean, indoor, light, minimalist, modern, polished, rustic, wood", "grain"),
        # A stone tile is a tile, not a stone.
        (
            "bathroom, beige, dirty, floor, grid, kitchen, rectangular, rough, "
            "stained, stone, tiles, urban, white",
            "brick",
        ),
        # A brick wall is courses.
        ("bricks, stone", "brick"),
        # A cobblestone paving is SET stones, however it is laid - and a
        # printed design's word does not make it a wallpaper (the truth's
        # own PavingStones150 drew as flat grey).
        ("cobblestone, grey, pavement", "voronoi"),
        ("arches, cobble, cobblestone, floor, gray, patterned", "fan"),
        # And a cobblestone laid in ARCHES is a fan of setts
        # (PavingStones150, PavingStones151).
        ("arch, cobblestone, european, gray, mosaic, paving", "fan"),
        # Stacked stone is a dry wall of blocks, so a mossy one's moss can
        # lie in its joints (Rock064).
        ("forest, gray, irregular, natural, old, rock, rough, stacked, stone", "brick"),
        # A wool is knitted (Fabric085, Fabric019), but a wool carpet is a pile.
        ("fabric, orange, red, wool", "knit"),
        ("cloth, fabric, weave, white, wool, woven", "knit"),
        ("beige, carpet, fabric, floor, soft, white, wool", "carpet"),
        # Plank floors are boards whatever wood they are (Planks037A).
        ("floor, planks, wood", "parquet"),
        # Rubble is loose pieces whatever it was broken from (Ground107).
        ("brick, debris, dirt, fragments, ground, rough", "scattered"),
        # An irregular stone FLOOR is a crazy paving (Tiles130); an
        # irregular WALL is still courses (Bricks089, ashlar), a medieval
        # wall is coursed blocks (Bricks076A), and an irregular ROCK is a
        # rock face (Rock064) - "stone" alone is not masonry.
        ("broken, castle, floor, medieval, old, stone, tiles", "voronoi"),
        ("brick, bricks, dark, gray, random, stone, wall", "brick"),
        ("bricks, dirty, medieval, old", "brick"),
        ("irregular, moss, rock, stone", "rock"),
        ("medieval, oak, wood", "grain"),
        # An onyx and a travertine are BANDED layers, though they say
        # "marble" too (Onyx015, Travertine009); a marble is veined.
        ("marble, onyx, polished, smooth, stone, white", "banded"),
        ("beige, light, marble, stone, travertine, white", "banded"),
        ("black, marble, polished, stone", "marble"),
        # A bark is fissured plates though it says "wood" too (Bark015).
        ("bark, brown, forest, rough, tree, wood", "bark"),
        # An asphalt is an aggregate surface (as a Voronoi every road was
        # a camouflage of plates), and a "striped" road is painted - but
        # "striped" alone is not paint (a corrugated steel says it).
        ("asphalt, charcoal, dark, granular, road, urban", "asphalt"),
        ("asphalt, floor, grey, light, stone, street", "asphalt"),
        ("asphalt, gray, old, road, striped, worn, yellow", "markings"),
        ("corrugated, metal, steel, striped", "metal"),
        # A loose ground is SCATTERED stones and not a Voronoi: a
        # Voronoi's cells tile the plane and a heap of loose stones
        # does not. The truth's own ground is fifty-six bright stones
        # along a row of a thousand and twenty-four, a matrix twelve
        # pixels wide between them, and the stones' sizes varying by
        # eight times.
        ("brown, dirt, dry, gravel, ground, rocky, scattered", "scattered"),
        # A FABRIC is a WEAVE and not a Voronoi: the truths' own Fabric061
        # and Fabric066 are a mesh and a herringbone, threads crossing. (This
        # row was Fabric085, "fabric, orange, red, wool", read as a twill;
        # looked at closely it is a KNIT of chunky loops, and a wool now
        # routes to the knit - pinned below.)
        ("fabric, rough", "woven"),
        # Nothing that says: pieces, which is the commonest surface.
        ("something entirely unfamiliar", DEFAULT_PATTERN),
    ),
)
def test_the_description_chooses_the_pattern(description, expected):
    assert pattern_for_description(description) == expected


def test_the_structure_is_read_before_the_material():
    """A "wood floor" is a wood floor, not a floor of wood pieces.

    The order matters: the material words are checked second, so a
    description that names both picks the structure.
    """
    assert pattern_for_description("wood, floor, tiles") == "grain"
    assert pattern_for_description("stone, tile") == "brick"


def test_a_coated_metal_is_its_coat_and_a_bare_one_is_a_sheet():
    """A powder-coated steel is a flat sheet of paint; a scratched one is a
    metal sheet. As a metal, the coated truths took a metal's mottle and
    their contrast read 1.90x and 1.52x the truth's."""
    assert (
        pattern_for_description("black, covered, metal, painted, powder, steel")
        == "flat"
    )
    assert pattern_for_description("metal, scratched, steel") == "metal"
    assert pattern_for_description("dark, painted, wood") == "grain"


def test_bare_rust_and_dust_are_films_and_a_rusty_steel_is_a_sheet():
    assert pattern_for_description("rust, rusty, orange brown") == "flat"
    assert pattern_for_description("pale grey dust") == "flat"
    assert pattern_for_description("aged, rusty, steel") == "metal"


def test_a_direction_word_turns_the_grain_and_not_the_pattern():
    """A board's grain runs ACROSS the image unless the words say otherwise.

    Twenty of the truth's twenty-seven woods run across and the five that
    run down name no direction at all, so a direction word is the only
    thing that can ask for the other one - and a user writes it: "vertical
    oak" is a panelled door, not a floor.

    It is a DIRECTION and never a structure: the same description chooses
    the same pattern either way, and only the grain's way changes. A word
    that leaked into the pattern choice would turn "vertical wood" into a
    different material.
    """
    from golem_blender.pbr.patterns import is_vertical

    assert not is_vertical("beige, grain, knots, light, natural, smooth, wood")
    for description in (
        "beige, grain, knots, vertical, wood",
        "beige, grain, knots, vertically, wood",
        "VERTICAL, oak",
        "oak, vertical",
    ):
        assert is_vertical(description), description


def test_a_direction_word_leaves_the_pattern_and_the_palette_alone():
    """Only the grain's way moves; nothing else about the surface does."""
    from golem_blender.pbr.palette import (
        line_palette_for_description,
        palette_for_description,
    )

    flat = "beige, grain, knots, light, natural, smooth, softwood, wood"
    turned = f"{flat}, vertical"

    # The same kind, and the same colours: a direction is not a material.
    assert pattern_for_description(flat) == pattern_for_description(turned) == "grain"
    for builder, path in (
        (line_palette_for_description, "grain"),
        (palette_for_description, "grain"),
    ):
        plain = builder(flat, path=path)
        upright = builder(turned, path=path)
        assert upright.pop("vertical") is True
        assert plain.pop("vertical") is False
        assert upright == plain
    # And a horizontal board is what the pattern already does, so it needs
    # no word: only "vertical" is read.
    assert (
        line_palette_for_description(f"{flat}, horizontal", path="grain")["vertical"]
        is False
    )
