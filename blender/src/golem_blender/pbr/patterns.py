"""Which pattern a DESCRIPTION calls for.

The benchmark chose the pattern with a keyword guess - "wood" in the
words meant a wave, "tile" meant a brick - and it guessed wrong for
the materials it was measured on: the two woods read at 5.5x the
truth's feature scale, because a wave's bands are parallel and
evenly spaced and a wood grain's are not.

So the choice is made from the description's MATERIAL and the
surface's STRUCTURE, and each pattern is chosen for a reason:

- "voronoi" for anything made of separate rounded pieces - cobbles,
  gravel, ground, asphalt, a fabric's pile. A Voronoi cell is a
  piece, and the domain warp makes the pieces rounded and uneven.
- "brick" for COURSES - a brick wall, a tile floor. The courses are
  offset half a brick every other row, which is what makes a brick
  wall a brick wall and a tile floor a tile floor.
- "grain" for a WOOD's rings - the nested curves a tree's growth
  makes, which a plank cut from them shows.

The words are matched against the description, and the order matters:
a "wood" floor is a wood floor, and a "stone" tile is a stone tile,
so the STRUCTURE is read first and the material second.
"""

from __future__ import annotations

# The structure words, and the pattern each calls for. Read first: a
# "wood floor" is a wood floor, and a "stone tile" is a stone tile.
#
# The order is the specificity: a GRAIN is a structure, and a course
# of tiles is a structure, but a surface that is both - "wood, floor,
# tiles" - is a wooden floor, and a word that names a material's
# STRUCTURE (a grain) is more specific than one that names a layout
# (tiles).
_STRUCTURE_PATTERNS = (
    ("grain", "grain"),
    ("plank", "grain"),
    ("timber", "grain"),
    ("wood", "grain"),
    ("brushed", "metal"),
    ("corrugated", "metal"),
    ("metal", "metal"),
    ("steel", "metal"),
    ("brick", "brick"),
    ("tiles", "brick"),
    ("tile", "brick"),
)

# The material words, and the pattern each calls for. Everything that
# is not a course or a grain is made of separate pieces.
_MATERIAL_PATTERNS = (
    ("cobble", "voronoi"),
    ("cobblestone", "voronoi"),
    ("stone", "voronoi"),
    ("rock", "voronoi"),
    ("gravel", "voronoi"),
    ("ground", "voronoi"),
    ("dirt", "voronoi"),
    ("earth", "voronoi"),
    ("sand", "voronoi"),
    ("asphalt", "voronoi"),
    ("concrete", "voronoi"),
    ("plaster", "voronoi"),
    ("fabric", "voronoi"),
    ("wool", "voronoi"),
    ("fur", "voronoi"),
    ("leather", "voronoi"),
    ("metal", "voronoi"),
)

# What a surface that matches nothing is assumed to be.
DEFAULT_PATTERN = "voronoi"


def pattern_for_description(description: str) -> str:
    """The pattern a description calls for.

    `description` is the material's own words - "bricks, stone",
    "beige, grain, knots, wood" - and the order the words are read in
    is the order the decision is made in: the structure first, then
    the material.
    """
    words = description.lower()
    for word, pattern in _STRUCTURE_PATTERNS:
        if word in words:
            return pattern
    for word, pattern in _MATERIAL_PATTERNS:
        if word in words:
            return pattern
    return DEFAULT_PATTERN


# The words whose surface is made of SMALL, LOOSE PIECES - gravel,
# dirt, rubble, sand - as against a surface that is one solid thing
# cut into pieces.
#
# A loose ground is a PEBBLE field: the truth's own ground carries
# eighty-one pebble-gaps across where the feature measure reads
# twenty, so the pebbles are four times finer than the envelope. A
# concrete or a plaster is not - it is one surface, and it does not
# crackle.
#
# So the crazing is the loose grounds' and not the solid ones'.
_PEBBLED_WORDS = (
    "gravel",
    "dirt",
    "ground",
    "earth",
    "rubble",
    "debris",
    "sand",
    "pebble",
    "cobble",
    "cobblestone",
    "scattered",
    "rocky",
    "riverbed",
)


def is_pebbled(description: str) -> bool:
    """Whether the description names a surface of SMALL, LOOSE PIECES.

    A loose ground crazes - the truth's own ground is a field of
    pebbles with a dark matrix between them - and a solid surface
    does not: the truth's tiles are flat squares with a thin grout
    line, and the truth's concrete is a plain sheet.
    """
    # The words are matched WHOLE: "dirty" contains "dirt", and a
    # dirty tile floor is a tile floor and not a ground.
    words = set(description.lower().replace(",", " ").split())
    return any(word in words for word in _PEBBLED_WORDS)


__all__ = (
    "DEFAULT_PATTERN",
    "is_pebbled",
    "pattern_for_description",
)
