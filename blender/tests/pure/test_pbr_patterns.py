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
        # Separate rounded pieces.
        ("cobblestone, grey, pavement", "scattered"),
        ("asphalt, charcoal, dark, granular, road, urban", "voronoi"),
        # A loose ground is SCATTERED stones and not a Voronoi: a
        # Voronoi's cells tile the plane and a heap of loose stones
        # does not. The truth's own ground is fifty-six bright stones
        # along a row of a thousand and twenty-four, a matrix twelve
        # pixels wide between them, and the stones' sizes varying by
        # eight times.
        ("brown, dirt, dry, gravel, ground, rocky, scattered", "scattered"),
        # A FABRIC is a WEAVE and not a Voronoi: the truth's own
        # Fabric085 is a "fabric, orange, red, wool" and it is a
        # TWILL - threads crossing - and its neighbours Fabric061 and
        # Fabric066 are a mesh and a herringbone. A Voronoi is a set of
        # cells with joints between them.
        ("fabric, orange, red, wool", "woven"),
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
