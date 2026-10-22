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
    ("bark", "grain"),
    ("brushed", "metal"),
    ("corrugated", "metal"),
    ("metal", "metal"),
    ("steel", "metal"),
    ("brick", "brick"),
    ("bricks", "brick"),
    ("tiles", "brick"),
    ("tile", "brick"),
    # A MARBLE is a STRUCTURE and not a material: the truth's own
    # Marble012 says "stone" as well as "marble", and "stone" is a
    # Voronoi - so the marble has to be read before it.
    #
    # And "veined" says the same thing without naming the stone.
    ("marble", "marble"),
    ("onyx", "marble"),
    ("travertine", "marble"),
    ("veined", "marble"),
)

# The FLAT surfaces: a sheet with no cells in it.
#
# The lane had no such a kind, so every smooth surface fell through
# to the Voronoi and became a field of cobbles - a plaster became
# pebbles.
#
# The words are read before the material's, and the STRUCTURE is
# read before both: a "stone tile" is a stone tile, and a "painted
# wall" is a painted wall.
_FLAT_PATTERNS = (
    ("plaster", "flat"),
    ("paint", "flat"),
    ("render", "flat"),
    ("stucco", "flat"),
    ("paper", "flat"),
    ("cardboard", "flat"),
    ("paperless", "flat"),
    # A CONCRETE is a SHEET and not a set of pieces.
    #
    # The truth's own Concrete048 measures seventy-nine features
    # across with a spread of 0.0280, and it is a fine even surface
    # - and the lane's answer for a concrete was a VORONOI, whose
    # cells are large flat pieces with hard borders. So a concrete
    # came out as a field of cobbles and its contrast read 2.58x the
    # truth's.
    ("concrete", "flat"),
    ("cement", "flat"),
)

# The material words, and the pattern each calls for. Everything that
# is not a course, a grain or a flat sheet is made of separate
# pieces.
# The kinds the lane had NO pattern for, and each is named by the
# word that names it.
#
# A PARQUET is a wood floor: long blocks laid in a staggered pattern,
# each block with its own tone. It is the BRICK's primitive with a
# wood's palette and a much wider block - the truth's own parquet
# measures a row-to-column change ratio of 0.24, and it is the most
# horizontal surface in the sample.
#
# A CARPET is a pile of fibres: a directional, very fine grain. The
# truth's own carpet measures 0.029 of spread over twenty-seven
# thousand fine specks - it is almost flat, and what it has is a
# directional fuzz.
#
# A LEATHER is a pebbled hide: a fine even grain of cells, and not
# stones. It is the loose ground's primitive at a much finer scale
# and with a much tighter packing.
#
# A WALLPAPER is a flat sheet with a PRINTED design on it, and the
# design is a set of flat blocks of colour - a chequer, a stripe, a
# motif. It is the FLAT sheet with the TILE's structure on it.
# The kinds a word names OUTRIGHT, and they are read before the
# structures.
#
# A "parquet" is a parquet and not a plank, and a "corrugated steel"
# is a pressed metal sheet and not a road with markings on it.
_SPECIFIC_KINDS = (
    ("parquet", "parquet"),
    ("carpet", "carpet"),
    ("leather", "leather"),
    ("wallpaper", "wallpaper"),
    ("herringbone", "herringbone"),
    ("basketweave", "herringbone"),
    ("roofing", "roof"),
    ("shingle", "roof"),
    ("woven", "woven"),
    ("weave", "woven"),
    ("textile", "woven"),
    ("cloth", "woven"),
    ("markings", "markings"),
)

_COURSE_PATTERNS = (
    ("parquet", "parquet"),
    ("planks", "parquet"),
    ("plank", "parquet"),
    ("carpet", "carpet"),
    ("rug", "carpet"),
    ("leather", "leather"),
    ("hide", "leather"),
    ("wallpaper", "wallpaper"),
    ("wall paper", "wallpaper"),
    ("printed", "wallpaper"),
    ("patterned", "wallpaper"),
    ("herringbone", "herringbone"),
    ("basketweave", "herringbone"),
    ("roofing", "roof"),
    ("shingle", "roof"),
    ("roof", "roof"),
    ("woven", "woven"),
    ("weave", "woven"),
    ("textile", "woven"),
    ("cloth", "woven"),
    ("microfiber", "woven"),
    ("markings", "markings"),
    ("lane", "markings"),
    ("dashed", "markings"),
)

_MATERIAL_PATTERNS = (
    # The LOOSE grounds are SCATTERED stones and not a Voronoi.
    #
    # A Voronoi's cells tile the plane, and a heap of loose stones
    # does not: the truth's own ground is fifty-six bright stones
    # along a row of a thousand and twenty-four, a matrix twelve
    # pixels wide between them, and the stones' sizes varying by
    # eight times.
    ("cobble", "scattered"),
    ("cobblestone", "scattered"),
    ("gravel", "scattered"),
    ("ground", "scattered"),
    ("dirt", "scattered"),
    ("earth", "scattered"),
    ("rubble", "scattered"),
    ("debris", "scattered"),
    ("scattered", "scattered"),
    ("stone", "voronoi"),
    ("rock", "voronoi"),
    ("sand", "voronoi"),
    ("asphalt", "voronoi"),
    ("concrete", "voronoi"),
    # A FABRIC is a WEAVE and not a Voronoi.
    #
    # The truth's own Fabric085 is a "fabric, orange, red, wool" at
    # a hundred and thirteen features across, and it is a TWILL - a
    # diagonal weave - and its neighbours Fabric061 and Fabric066 are
    # a mesh and a herringbone. A Voronoi is a set of cells with
    # joints between them, and a weave is threads crossing: the
    # fabric's feature scale read 0.78x the truth's and the round's
    # own words are that a fabric is a weave.
    #
    # And a WOOL is a weave too, and a FUR is a pile - and a pile is
    # a carpet's kind.
    ("fabric", "woven"),
    ("wool", "woven"),
    ("fur", "carpet"),
    # A MOSAIC is a BRICK: the truth's own mosaic tiles are square
    # and their grout is a joint, and the marble's own is a network of
    # veins.
    ("mosaic", "brick"),
    ("paving", "scattered"),
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
    # The words are WHOLE words.
    #
    # They were a substring test, and "corrugated" contains "rug" -
    # so the truth's own corrugated steel came out as a CARPET.
    words = set(description.lower().replace(",", " ").split())
    # The SPECIFIC kinds are read first: a "parquet floor" is a
    # parquet and not a plank, and a "carpet" is a carpet and not a
    # fabric.
    #
    # The structures were read first and they took the word "wood" and
    # the word "plank" - so a parquet floor, which is a wood floor
    # laid in blocks, came out as a plain grain, and the truth's own
    # parquet measures a row-to-column change ratio of 0.24 while a
    # grain is nowhere near that.
    # The SPECIFIC kinds are read first, and the structures after.
    #
    # The course kinds were read first, and they took the word
    # "striped" - so the truth's own corrugated steel, which is a
    # pressed metal sheet, came out as a road with markings on it.
    #
    # And the structures were read first, and they took the word
    # "plank" - so a parquet floor, which is a wood floor laid in
    # blocks, came out as a plain grain, and the truth's own parquet
    # measures a row-to-column change ratio of 0.24 while a grain is
    # nowhere near that.
    #
    # So the two are read in two passes: the course kinds' SPECIFIC
    # words - the ones that name a kind outright - and then the
    # structures, and then the course kinds' general words.
    for word, pattern in _SPECIFIC_KINDS:
        if word in words:
            return pattern
    for word, pattern in _STRUCTURE_PATTERNS:
        if word in words:
            return pattern
    for word, pattern in _COURSE_PATTERNS:
        if word in words:
            return pattern
    for word, pattern in _FLAT_PATTERNS:
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
