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
        ("cobblestone, grey, pavement", "voronoi"),
        ("asphalt, charcoal, dark, granular, road, urban", "voronoi"),
        ("brown, dirt, dry, gravel, ground, rocky, scattered", "voronoi"),
        ("fabric, orange, red, wool", "voronoi"),
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
