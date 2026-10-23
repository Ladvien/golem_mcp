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

# The words that say a metal is under a COAT, and so is the coat's flat
# sheet and not a metal's own surface.
COATING_WORDS = frozenset(("powder", "coated", "painted", "enamel", "lacquered"))

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
    # An ONYX and a TRAVERTINE are BANDED - layers, not veins: the
    # truths' own Onyx015 and Travertine009 also say "marble" and as
    # marbles they came out veined (looked at). Read before "marble".
    ("onyx", "banded"),
    ("travertine", "banded"),
    ("marble", "marble"),
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
    # A PLASTIC is a MOULDED surface, and a moulded surface is
    # smooth.
    #
    # The truth's own plastics are the flattest materials in the
    # sample: Plastic010 measures a spread of 0.0021 and
    # Plastic013A 0.0071, and their correlations never cross zero -
    # they are featureless.
    #
    # So a plastic was a VORONOI - a field of cobbles - where the
    # truth has a smooth sheet, and Plastic006's brightness read
    # 7.02x the truth's.
    ("plastic", "flat"),
    ("abs", "flat"),
    ("acrylic", "flat"),
    ("vinyl", "flat"),
    ("pvc", "flat"),
    ("melamine", "flat"),
    ("laminate", "flat"),
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
    # A GRASS is blades, whatever ground it grows on: the truth's own
    # Grass001, Grass004 and the overgrown Ground037 all say "ground"
    # too, and a ground is a field of stones.
    ("grass", "grass"),
    ("lawn", "grass"),
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
    # A PLANK floor is boards, whatever wood it is: the truth's own
    # Planks037A is "floor, planks, wood", and "wood" - a structure -
    # took it as one plain grain with no boards in it.
    ("planks", "parquet"),
    # RUBBLE is loose pieces, whatever they were broken from: the
    # truth's own Ground107 is "brick, debris, dirt, fragments, ground,
    # ..." and "brick" - a structure - drew it as an orange brick wall.
    ("rubble", "scattered"),
    ("debris", "scattered"),
    ("fragments", "scattered"),
    # A COBBLESTONE paving is set stones, however it is laid: the
    # truth's own PavingStones150 is "arches, ..., cobble, cobblestone,
    # ..., patterned" and "patterned" - a printed design's word - drew it
    # as a flat grey wallpaper.
    ("cobblestone", "voronoi"),
    ("cobble", "voronoi"),
)

# IRREGULAR masonry. A "castle" floor of broken stone tiles is the
# truth's own Tiles130, a CRAZY PAVING of stones of every size laid
# without courses - a Voronoi - and as tiles it was a regular grid. An
# irregular WALL is still courses: the truth's own "random ... stone,
# wall" (Bricks089) is rubble in rough rows with a pale mortar - ashlar
# bricks (palette.brick_is_ashlar, is_mortared_wall) - and as Voronoi
# stones it was a scribble of pale joints through black (looked at).
# ("medieval" is not such a word: the truth's own medieval Bricks076A is
# coursed blocks.) The words count only beside a LAID masonry word: a
# "medieval" plank floor is boards, and an "irregular rock, stone" is the
# truth's own Rock064, a rock face - "stone" alone is not masonry.
IRREGULAR_WORDS = frozenset(("random", "castle", "irregular"))
MASONRY_WORDS = frozenset(("brick", "bricks", "tile", "tiles", "wall"))
ROAD_WORDS = frozenset(("road", "street", "asphalt", "highway"))
# An asphalt's WEAR and its CRACKS. Every worn truth road says "worn",
# "old" or "damaged" and carries broad patches; the two plain asphalts
# (Asphalt033, Asphalt031) say none of them and are aggregate alone.
ASPHALT_WEAR_WORDS = frozenset(
    ("worn", "old", "damaged", "aged", "deteriorated", "weathered")
)
CRACK_WORDS = frozenset(("cracked", "cracks", "cracking"))


def asphalt_is_worn(description: str) -> bool:
    """Whether an asphalt is a worn road, with broad patches in it."""
    return bool(set(description.lower().replace(",", " ").split()) & ASPHALT_WEAR_WORDS)


def is_cracked(description: str) -> bool:
    """Whether the description says the surface is cracked."""
    return bool(set(description.lower().replace(",", " ").split()) & CRACK_WORDS)


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
    #
    # And a PAVING is NOT a loose ground. The truth's own
    # PavingStones151 is an "arch, arches, beige, cobblestone,
    # european, gray, grid, mosaic, old, ..." and it measures
    # seventy-three features across with a spread of 0.1117 - a TIGHT
    # SET of set stones, laid in a pattern, and not a heap.
    #
    # So "grid" and "mosaic" decide, and they are read before the
    # loose grounds: a thing that is laid in a grid is a grid
    # whatever it is made of.
    ("grid", "voronoi"),
    ("mosaic", "voronoi"),
    # A SAND is a SMOOTH surface and not a field of grains.
    #
    # The truth's own Ground093C is an "accumulation, beach, beige,
    # coastal, desert, dune, earthy, eroded, ..." and it measures
    # 7.6 features across with a spread of 0.0148 - a BEACH, and a
    # beach is smooth.
    #
    # So a sand is the FLAT sheet, and the sand's own words come
    # before the loose grounds' - a "dune" is a smooth drift and not
    # a heap of gravel, and a beach that says "gravel" says it of
    # the stones at its edge.
    ("sand", "flat"),
    ("dune", "flat"),
    ("beach", "flat"),
    ("gravel", "scattered"),
    ("ground", "scattered"),
    ("dirt", "scattered"),
    ("earth", "scattered"),
    ("rubble", "scattered"),
    ("debris", "scattered"),
    ("scattered", "scattered"),
    # A ROCK face is a fine fractal surface and not a set of pieces:
    # as a Voronoi every rock came out as flat polygon facets. It is
    # read before "stone", which a cliff's description often adds.
    # And a MOSS is a speckle; a mossy rock is a rock, so the moss is
    # read after it.
    # An ASPHALT is an aggregate surface and not a set of pieces: as a
    # Voronoi every road was a camouflage of polygon plates. It is read
    # before "stone", which the truth's own Asphalt031 also says.
    ("asphalt", "asphalt"),
    ("rock", "rock"),
    ("cliff", "rock"),
    ("moss", "moss"),
    ("stone", "voronoi"),
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
    ("paving", "voronoi"),
    ("metal", "voronoi"),
    # RUST on its own is a mottled crust, not a set of stones; it is
    # read LAST, so a rusty steel is still the steel's own pattern.
    ("rust", "flat"),
    ("rusty", "flat"),
    # And DUST and GRIME are films, read last for the same reason: as a
    # layer over a floor, "pale grey dust" was a set of grey stones.
    ("dust", "flat"),
    ("dusty", "flat"),
    ("grime", "flat"),
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
    # A COATED metal is its coat: a powder-coated or painted steel is a
    # flat sheet of paint, and the truth's own Metal027 and Metal029 are
    # a uniform dark navy. As a metal sheet they took a metal's mottle
    # and envelope, and their contrast read 1.90x and 1.52x the truth's.
    from golem_blender.pbr.material import is_metal

    if is_metal(description) and words & COATING_WORDS:
        return "flat"
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
    if words & IRREGULAR_WORDS and words & MASONRY_WORDS and "wall" not in words:
        return "voronoi"
    # A "striped" ROAD is painted: the truths' own Road008A and Road008B
    # say "striped" for their yellow dashes and edge lines, and as plain
    # asphalt Road008A took the paint's "yellow" as the whole surface's
    # colour. "striped" alone is not paint - a corrugated steel says it.
    if "striped" in words and words & ROAD_WORDS:
        return "markings"
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


def is_checkered(description: str) -> bool:
    """Whether a woven cloth is a CHEQUER of squares and not threads.

    A CHECKERED fabric is a grid of alternating squares, and the two
    are different things: a crosshatch of threads has a correlation
    that never goes negative, and a chequer's does.

    Measured on the truth's own Fabric083 - a "checkered, clean,
    cloth, fabric, gray, patterned, smooth, textile, woven" - the
    correlation is +0.870 at a lag of one, +0.051 at four and MINUS
    0.136 at eight. Ours read +0.040 at eight, where the truth
    reads -0.136.
    """
    words = set(description.lower().replace(",", " ").split())
    return bool(words & {"checkered", "chequered", "checkerboard", "gingham"})


# How STONY a loose ground is, from its words. The truths' soils (Ground103
# "dirt, earth, soil"; Ground106 "dirt, earth, mud, muddy, leaves") are
# smooth ground with a few small stones, and drawn at the gravels' density
# they were heaps of big stones (looked at); their gravels (Gravel043,
# Ground108 "debris, gravel, rocky, rubble", Ground110) are packed. A
# "riverbed" is not stony by itself: Ground106 says it of muddy soil.
STONY_WORDS = frozenset(
    (
        "gravel",
        "pebbles",
        "pebble",
        "rocky",
        "rubble",
        "stones",
        "stony",
        "debris",
    )
)
SOIL_WORDS = frozenset(
    ("soil", "mud", "muddy", "earth", "sand", "sandy", "loam", "clay")
)
SOIL_STONE_DENSITY = 0.35


def stone_density_for_description(description: str) -> float:
    """How many of a loose ground's stones are there, as a share of a gravel's."""
    words = set(description.lower().replace(",", " ").split())
    if words & STONY_WORDS:
        return 1.0
    if words & SOIL_WORDS:
        return SOIL_STONE_DENSITY
    return 1.0


def has_long_boards(description: str) -> bool:
    """Whether a wood floor is laid in long PLANKS or boards.

    "plank" alone is not: the truth's own WoodFloor051 says it of boards
    three and a half times as long as they are wide.
    """
    return bool(
        set(description.lower().replace(",", " ").split()) & {"planks", "boards"}
    )


def carpet_is_streaked(description: str) -> bool:
    """Whether a carpet is a CLOTH, its fibre lying along the rows."""
    return bool(
        set(description.lower().replace(",", " ").split()) & {"cloth", "fabric"}
    )


def is_mortared_wall(description: str) -> bool:
    """Whether the description is an IRREGULAR stone WALL laid in mortar.

    The truth's own random stone wall, Bricks089, has its joints PALER
    than its stones (luma 0.515 against 0.455 over the lowest fifth of its
    height) and a fifth of its surface wide; an irregular FLOOR's joints
    are cracks (Tiles130: 0.484 against 0.564), the rock's rule.
    """
    words = set(description.lower().replace(",", " ").split())
    return bool(words & IRREGULAR_WORDS) and "wall" in words


__all__ = (
    "DEFAULT_PATTERN",
    "asphalt_is_worn",
    "carpet_is_streaked",
    "has_long_boards",
    "is_checkered",
    "is_cracked",
    "is_mortared_wall",
    "is_pebbled",
    "pattern_for_description",
    "stone_density_for_description",
)
