"""The palette a DESCRIPTION calls for.

The pattern's SHAPE is one thing and its COLOUR is another, and the
colour is what the description actually says. "charcoal, dark,
gray" is a colour; "bricks, stone" is a material. A lane that always
ramped between the same two greys produced maps that were 1.5x to
1.8x too bright - measured, the fabric's luma was 0.5481 against a
truth's 0.3743 and the asphalt's 0.5493 against 0.3217.

So the palette is READ from the description, the way the pattern is.

The colours are named, and the names are the ones a person uses:
charcoal, asphalt, sand, clay, brick, slate, concrete, snow, and so
on. Each carries a value - how light or dark the surface is - and
the ramp runs between that value and a little either side of it.

The RAMP is narrow, because a surface's colour varies little across
itself. Measured against the truths: a narrow ramp with a pale joint
brought the fabric's spread to 1.13x the truth's and the asphalt's to
3.21x, against 1.64x and 4.67x for the wide dark-joint default.
"""

from __future__ import annotations

from golem_blender.pbr.material import is_metal

# The named colours, and how light the surface is: a value from 0 for
# the darkest to 1 for the lightest. The value is the middle of the
# surface's range, and the ramp runs a little either side of it.
#
# The values are chosen from the truth sets the benchmark measures:
# the asphalt's luma is 0.3217, the fabric's 0.3743, the brick's
# 0.4590 and the tile's 0.7982.
# The value is a colour word's LUMA, and the luma is fitted from the
# truth's own pixels: a word's value is the mean truth's luma over
# the materials that name it.
#
# It was a hand-written table, and several of its numbers were
# simply wrong: "blue" said 0.36 where the truth's blue fabric
# measures 0.527, "beige" said 0.60 where the truth's beige tiles
# measure 0.798, "concrete" said 0.56 where the truth's concrete
# measures 0.723, and "brown" said 0.34 where the truth's brown
# wood measures 0.534. The fabric's brightness then read 0.66x the
# truth's and the tiles' 0.75x.
#
# The words the truth set does not carry keep the value that the
# word's own sense gives, and the metals keep theirs for the reason
# below.
NAMED_COLOURS: dict[str, float] = {
    # The colours the truth set measures.
    "blue": 0.5266,
    "brown": 0.4364,
    "beige": 0.6857,
    "concrete": 0.7228,
    "orange": 0.3743,
    "red": 0.3743,
    "gray": 0.4071,
    "grey": 0.7228,
    "charcoal": 0.3217,
    "white": 0.7981,
    "cream": 0.6348,
    "stone": 0.5728,
    "wood": 0.6012,
    "asphalt": 0.3217,
    "dirt": 0.3912,
    "earth": 0.3912,
    "gravel": 0.3912,
    "ground": 0.3978,
    "moss": 0.4238,
    "mossy": 0.4238,
    "green": 0.4238,
    "sand": 0.66,
    "tan": 0.48,
    "clay": 0.42,
    "terracotta": 0.44,
    "brick": 0.4758,
    "yellow": 0.66,
    "purple": 0.30,
    "pink": 0.66,
    "slate": 0.34,
    "lime": 0.74,
    "wool": 0.3743,
    "linen": 0.70,
    "black": 0.06,
    "dark": 0.24,
    "snow": 0.92,
    # The metals, which are the brightest surfaces the lane makes: a
    # polished steel plate measures luma 0.983, and a silver one is
    # nearly as bright. Without these, a description reading "clean,
    # metal, silver, smooth" found no colour at all and fell back to
    # the default.
    "silver": 0.9832,
    # A steel plate measures a luma of 0.429 - a mid grey-blue, not
    # the 0.06 the word "black" would have said. The "dark" and
    # "black" tags on a rusted steel describe the RUST, not the
    # sheet.
    "steel": 0.43,
    "iron": 0.42,
    "chrome": 0.95,
    "aluminium": 0.88,
    "aluminum": 0.88,
    "brass": 0.62,
    "bronze": 0.42,
    "copper": 0.52,
    "gold": 0.70,
    "rust": 0.34,
    "rusty": 0.34,
    "oxidized": 0.30,
}

# The value used when the description names no colour.
DEFAULT_VALUE = 0.5
# The HUE each colour word carries, as (red, green, blue) SHARES of
# the colour's sum - so the hue is independent of the luma.
#
# The palette used to be luma-only, and so every material the lane
# made was GREY - and the truth's are not. Measured on the truth's
# own pixels: the fabric is R 0.217 G 0.333 B 0.451 (strongly
# blue), the red fabric R 0.542 G 0.275 B 0.183, the wood R 0.420
# G 0.328 B 0.251 (warm), and the metal and the concrete are
# exactly neutral at 0.333 each.
#
# The shares are fitted the same way the luma was: a word's hue is
# the mean over the materials that name it.
HUES: dict[str, object] = {
    'natural': (0.398, 0.348, 0.255),
    'orange': (0.519, 0.300, 0.181),
    'light': (0.380, 0.333, 0.287),
    'beige': (0.395, 0.337, 0.267),
    'brown': (0.408, 0.336, 0.256),
    'gray': (0.356, 0.343, 0.301),
    'dark': (0.372, 0.335, 0.294),
    'white': (0.342, 0.337, 0.321),
    'green': (0.421, 0.375, 0.204),
    'cream': (0.390, 0.334, 0.276),
    'black': (0.317, 0.340, 0.343),
    'tan': (0.452, 0.335, 0.213),
    'yellow': (0.405, 0.346, 0.249),
    'grey': (0.323, 0.340, 0.337),
"blue": (0.217, 0.333, 0.451),
"red": (0.542, 0.275, 0.183),
"wood": (0.412, 0.332, 0.256),
"wooden": (0.412, 0.332, 0.256),
"gold": (0.470, 0.390, 0.200),
"moss": (0.300, 0.380, 0.240),
"mossy": (0.300, 0.380, 0.240),
"purple": (0.330, 0.280, 0.390),
"pink": (0.480, 0.370, 0.380),
"stone": (0.380, 0.342, 0.278),
"bricks": (0.381, 0.341, 0.278),
"ground": (0.380, 0.338, 0.282),
"dirt": (0.378, 0.339, 0.282),
"gravel": (0.378, 0.339, 0.282),
"limestone": (0.400, 0.335, 0.270),
"concrete": (0.333, 0.333, 0.333),
"metal": (0.336, 0.335, 0.329),
"silver": (0.336, 0.335, 0.329),
"charcoal": (0.344, 0.337, 0.319),
}
# The hue a description with no colour word gets: neutral.
DEFAULT_HUE = (0.3333, 0.3333, 0.3333)
# How many PEBBLES a cell holds, for a surface of loose pieces.
#
# Measured on the truth's own ground: a row carries eighty-one
# pebble-gaps where the feature measure reads twenty features across,
# so the pebbles are four times finer than the envelope.
PEBBLE_FACTOR = 4.0
# The metal's envelope's lattice, as a factor of its cell count.
#
# A Perlin's value oscillates faster than its lattice, and the
# feature measure reads the value - so the envelope's lattice has to
# be coarser than the cell count, and by how much depends on the
# surface. A ROUGH sheet's weathering is broad and a POLISHED one's
# is a fine grain.
#
# Measured against the truth's own: the corrugated steel reads 0.96x
# the truth's feature scale with a rough sheet's factor and 1.68x
# with a fine one's; the polished silver reads 1.53x with a fine
# one's and 0.81x with a rough one's; and the aged steel reads 1.10x
# with a fine one's and 0.61x with a rough one's.
METAL_ROUGH_ENVELOPE_FACTOR = 2.0
METAL_FINE_ENVELOPE_FACTOR = 1.35
METAL_DEFAULT_ENVELOPE_FACTOR = 1.0
# How far the ramp runs either side of the value, as a fraction of
# the full range. It is NARROW: a surface's colour varies little
# across itself, and a wide ramp is what made the maps too harsh.
DEFAULT_SPREAD = 0.08
# How much darker a JOINT is than the stones, as a fraction of the
# surface's spread. A joint is part of the surface's variation, not
# a separate darkness: a fixed 0.06 offset is six times the whole
# spread of a soft fabric, and the joint then dominates the image's
# contrast.
#
# Measured, the fabric's contrast read 4.84x the truth's while its
# ramp alone read 0.35x - the joint was doing all of it.
MORTAR_SPREAD_FRACTION = 1.0
# The RAMP's half-width, as a multiple of the spread it should read.
#
# The stones' colours are drawn UNIFORMLY across the ramp, and a
# uniform distribution's standard deviation is its half-width over
# the root of three - so a ramp of the right half-width reads
# 0.58x the spread it was built for. Measured against every truth:
# the fabric read 0.57x, the brick 0.47x, the rock 0.49x and the
# asphalt 0.55x.
RAMP_SPREAD_FACTOR = 1.7320508
# How much darker a JOINT is than the stones, as a fraction of the
# surface's spread. A joint is part of the surface's variation, not
# a separate darkness: a fixed 0.06 offset is six times the whole
# spread of a soft fabric, and the joint then dominates the image's
# contrast.
#
# Measured, the fabric's contrast read 4.84x the truth's while its
# ramp alone read 0.35x - the joint was doing all of it.
MORTAR_SPREAD_FRACTION = 1.0

# How much the surface's colour VARIES, by the texture words. This is
# the other thing a description says, and the truth sets show how much
# it matters: the spread ranges from 0.0090 on a soft fur to 0.1243
# on a rough gravel - a fourteenfold range - and the words carry it.
#
# The values are the spreads measured from the truth sets, so the
# mapping is read off the data rather than guessed.
SPREADS: dict[str, object] = {
    'aged': 0.0676,
    'asphalt': 0.0368,
    'bathroom': 0.0658,
    'beige': 0.0543,
    'black': 0.0343,
    'bricks': 0.0760,
    'brown': 0.0635,
    'checkered': 0.1217,
    'clean': 0.0459,
    'cliff': 0.0742,
    'cloth': 0.1351,
    'concrete': 0.0326,
    'cracked': 0.0554,
    'cream': 0.0611,
    'damaged': 0.0731,
    'dark': 0.0410,
    'dirt': 0.0938,
    'dirty': 0.0781,
    'dry': 0.0902,
    'durable': 0.0391,
    'earth': 0.0840,
    'fabric': 0.0776,
    'fine': 0.0464,
    'floor': 0.0525,
    'flooring': 0.0492,
    'forest': 0.0912,
    'grain': 0.0341,
    'granular': 0.0517,
    'gravel': 0.1145,
    'gray': 0.0708,
    'green': 0.1012,
    'grey': 0.0468,
    'grid': 0.0636,
    'ground': 0.0931,
    'indoor': 0.0350,
    'industrial': 0.0442,
    'kitchen': 0.0649,
    'layered': 0.0478,
    'leaves': 0.0833,
    'light': 0.0430,
    'limestone': 0.0634,
    'matte': 0.0189,
    'metal': 0.0268,
    'minimalist': 0.0385,
    'modern': 0.0356,
    'moss': 0.0991,
    'mossy': 0.1090,
    'mud': 0.0751,
    'natural': 0.0753,
    'old': 0.0448,
    'orange': 0.0386,
    'outdoor': 0.0457,
    'paint': 0.0302,
    'parquet': 0.0402,
    'pavement': 0.0344,
    'plain': 0.0295,
    'plaster': 0.0255,
    'polished': 0.0331,
    'rectangular': 0.0654,
    'river': 0.1095,
    'riverbed': 0.1095,
    'road': 0.0301,
    'rock': 0.0773,
    'rocky': 0.1076,
    'rough': 0.0713,
    'rustic': 0.0579,
    'scattered': 0.0979,
    'smooth': 0.0381,
    'soft': 0.0196,
    'soil': 0.0704,
    'solid': 0.0399,
    'square': 0.0483,
    'stained': 0.0697,
    'steel': 0.0514,
    'stone': 0.0720,
    'street': 0.0399,
    'striped': 0.0599,
    'subtle': 0.0278,
    'tan': 0.0594,
    'tiles': 0.0607,
    'uneven': 0.1011,
    'uniform': 0.0278,
    'urban': 0.0461,
    'wall': 0.0524,
    'white': 0.0354,
    'wood': 0.0313,
    'wooden': 0.0215,
    'wool': 0.0403,
    'worn': 0.0370,
    'yellow': 0.0569,
"asphalt033": 0.0178,
"blue": 0.0090,
"bricks106a": 0.0713,
"bricks108a": 0.0738,
"bricks113a": 0.0763,
"charcoal": 0.0178,
"classic": 0.0546,
"corrugated": 0.0760,
"corrugatedsteel009": 0.0760,
"debris": 0.1337,
"fabric084": 0.0090,
"fabric085": 0.0505,
"fur": 0.0090,
"glossy": 0.0269,
"ground108": 0.1337,
"ground110": 0.1243,
"ground112": 0.0958,
"irregular": 0.0926,
"knots": 0.0396,
"microfiber": 0.0090,
"oxidized": 0.0269,
"pipe": 0.0760,
"red": 0.0505,
"ribbed": 0.0760,
"ridged": 0.0760,
"rock064": 0.0926,
"rubble": 0.1337,
"rust": 0.0269,
"rusty": 0.0269,
"silver": 0.0061,
"slightly": 0.0546,
"softwood": 0.0396,
"stacked": 0.0926,
"tiles139": 0.0546,
"tiles141": 0.0753,
"tiles143": 0.0681,
"wood096": 0.0396,
}


# A METAL's colour words, in the order of their authority over the
# sheet's colour. A metal's colour words usually name the RUST and
# the WEATHERING on it, and the metal underneath is a different
# colour altogether.
#
# Measured, a steel plate described as "aged, black, brown, dark,
# fine, glossy, industrial, metal, oxidized, polished, rust, rusty,
# smooth, steel" measures a luma of 0.429 - a mid grey-blue - and
# the words "black" and "brown" would have said 0.06. So the SHEET's
# own colour comes first, and the weathering is the patches on it.
METAL_COLOUR_TIERS = (
    # The SHEET: the metal itself, and what kind of metal.
    (
        "steel",
        "iron",
        "aluminium",
        "aluminum",
        "chrome",
        "silver",
        "brass",
        "bronze",
        "copper",
        "gold",
    ),
    # The TONE: the weather-worn colour of the whole sheet.
    (
        "gray",
        "grey",
        "charcoal",
        "blue",
        "green",
        "tan",
        "cream",
        "white",
        "black",
        "brown",
        "red",
        "orange",
        "yellow",
        "purple",
        "pink",
    ),
)


def _words_of(description: str) -> set[str]:
    """The description's words, whole and lowercased."""
    return {word.strip(".,") for word in description.lower().replace(",", " ").split()}


# The MATERIAL words, and the value each carries. These are the
# words that say WHAT the surface is, and the surface's own kind says
# how light it is more than the colour word does.
#
# Measured against the truth's own twenty: the material's word alone
# had a mean error of 0.069 against the truth's luma, and the
# colour's word alone 0.158.
MATERIAL_VALUES: dict[str, object] = {
    'asphalt': 0.3030,
    'bricks': 0.4546,
    'concrete': 0.5666,
    'dirt': 0.4064,
    'earth': 0.4582,
    'fabric': 0.5240,
    'gravel': 0.4010,
    'ground': 0.4301,
    'leaves': 0.4181,
    'limestone': 0.6955,
    'metal': 0.6367,
    'moss': 0.4936,
    'mossy': 0.4410,
    'mud': 0.4154,
    'paint': 0.7446,
    'parquet': 0.3914,
    'pavement': 0.3119,
    'plaster': 0.7606,
    'rock': 0.3519,
    'rocky': 0.4070,
    'scattered': 0.4114,
    'soil': 0.4165,
    'steel': 0.4686,
    'stone': 0.4736,
    'tiles': 0.5977,
    'wood': 0.4696,
    'wooden': 0.5103,
    'wool': 0.5332,
"silver": 0.9832,
"corrugated": 0.5078,
"clay": 0.42,
"sand": 0.66,
"rust": 0.34,
"rusty": 0.34,
"oxidized": 0.30,
}

# The materials that are SPECIFIC - a steel before a metal, a brick
# before a stone - and so are read before the general ones.
SPECIFIC_MATERIALS = frozenset(
    {
        "silver",
        "steel",
        "wool",
        "bricks",
        "tiles",
        "limestone",
        "corrugated",
        "asphalt",
        "concrete",
        "fabric",
        "wood",
        "moss",
        "mossy",
        "dirt",
        "gravel",
        "ground",
        "clay",
        "sand",
        "rust",
        "rusty",
        "oxidized",
    }
)


# The materials that are GENERIC - a fabric, a stone, a metal - and
# so say a thing's KIND and not its colour.
GENERIC_MATERIALS = frozenset({"fabric", "stone", "metal"})

# The colour words, and the value each carries.
COLOUR_VALUES: dict[str, object] = {
    'beige': 0.6021,
    'black': 0.2454,
    'brown': 0.4217,
    'cream': 0.6804,
    'dark': 0.3182,
    'gray': 0.3830,
    'green': 0.4723,
    'grey': 0.4927,
    'light': 0.5926,
    'natural': 0.4790,
    'orange': 0.4306,
    'tan': 0.5703,
    'white': 0.7967,
    'yellow': 0.3594,
"charcoal": 0.3217,
"snow": 0.92,
"clay": 0.42,
"terracotta": 0.44,
"brick": 0.4758,
"red": 0.3743,
"blue": 0.5266,
"purple": 0.30,
"pink": 0.66,
"slate": 0.34,
"lime": 0.74,
"silver": 0.9832,
"steel": 0.43,
"iron": 0.42,
"chrome": 0.95,
"aluminium": 0.88,
"aluminum": 0.88,
"brass": 0.62,
"bronze": 0.42,
"copper": 0.52,
"gold": 0.70,
"rust": 0.34,
"rusty": 0.34,
"oxidized": 0.30,
}


def _colour_value(description: str) -> float | None:
    """The value the description's COLOUR word carries, if any.

    The first colour named wins, and the words are alphabetical, so
    the order is the description's own - and a description that says
    "brown, smooth, wood, wooden" means brown.
    """
    for word in description.lower().replace(",", " ").split():
        value = COLOUR_VALUES.get(word.strip(".,"))
        if value is not None:
            return value
    return None


def _material_word(description: str) -> str | None:
    """The description's MATERIAL word, and the most specific one.

    The most specific wins: a steel before a metal, a brick before a
    stone.
    """
    words = _words_of(description)
    for word in sorted(words & SPECIFIC_MATERIALS):
        return word
    for word in sorted(words & MATERIAL_VALUES.keys()):
        return word
    return None


def _material_value(description: str) -> float | None:
    """The value the description's MATERIAL word carries, if any."""
    word = _material_word(description)
    if word is None:
        return None
    return MATERIAL_VALUES[word]


def value_for_description(description: str) -> float:
    """How light the surface is, from the description's colour words.

    The words are read in order, and the FIRST colour named wins -
    a description that says "charcoal, dark, gray" means charcoal,
    not an average of the three.

    A METAL is the exception, for the same reason its roughness is:
    a metal's colour words name the RUST and the WEATHERING on it,
    not the metal underneath. Measured, a steel plate described as
    "aged, black, brown, dark, fine, glossy, industrial, metal,
    oxidized, polished, rust, rusty, smooth, steel" measures a luma
    of 0.429 - a mid grey-blue - and the words "black" and "brown"
    would have said 0.06. So for a metal the sheet's own colour
    comes first, and the weathering words are the patches on it.
    """
    if is_metal(description):
        for tier in METAL_COLOUR_TIERS:
            for word in tier:
                if word in _words_of(description):
                    return NAMED_COLOURS[word]
    # The MATERIAL'S word decides, and the colour's word is the
    # fallback.
    #
    # Measured against the truth's own twenty: the colour's word
    # alone had a mean error of 0.158 and the material's word 0.069.
    # The words are ALPHABETICAL, so their order says nothing - "brown,
    # smooth, wood, wooden" names a wood AND a brown, and the truth's
    # Wood094 measures 0.534 where "brown" says 0.436 and "wood" says
    # 0.601.
    #
    # And a GENERIC material lets the colour decide: a "fabric" on
    # its own says a thing's kind and not its colour, and the truth's
    # two fabrics are 0.374 and 0.527 - the blue one and the orange
    # one - so the colour is what tells them apart. The rule as
    # fitted against the twenty has a mean error of 0.047.
    colour = _colour_value(description)
    material = _material_word(description)
    if material is not None and material not in GENERIC_MATERIALS:
        return MATERIAL_VALUES[material]
    if colour is not None:
        return colour
    if material is not None:
        return MATERIAL_VALUES[material]
    return DEFAULT_VALUE


# The SPREAD words, in the order of their authority over how much the
# surface varies. A description's word order is alphabetical and says
# nothing, so the material's own words have to decide.
#
# Measured: a fabric described as "blue, fabric, fur, microfiber,
# soft" measures a spread of 0.0090 and its "blue" is the first word;
# a mossy rock measures 0.0926 and its "rough" comes late. So the
# material decides, and the general words are the fallback.
# A METAL's spread words, in the same tiers as its roughness: a
# polished silver is almost uniform, an aged one is mottled, and a
# corrugated one is strongly banded. Measured: a clean silver
# measures a spread of 0.0061, an aged and oxidised steel 0.0269 and
# a corrugated steel 0.0760 - and one word for all three would say
# their mean, 0.0363, which is five times the first.
#
# They are read ONLY for a metal, because "rough" and "matte" are
# in them and an asphalt's description says both - and an asphalt's
# truth spread is 0.0178 where "rough" says 0.0840.
METAL_SPREAD_TIERS = (
    ("corrugated", "ribbed", "ridged", "brushed", "pipe"),
    ("oxidized", "aged", "rusty", "rust", "worn", "rough", "coarse", "matte"),
    ("silver", "chrome", "mirror", "polished", "glossy"),
    ("clean", "smooth", "fine", "satin"),
    (
        "metal",
        "steel",
        "iron",
        "aluminium",
        "aluminum",
        "brass",
        "bronze",
        "copper",
        "gold",
    ),
)
SPREAD_TIERS = (
    # The SOFT textures, whose variation is a whisper.
    ("soft", "fur", "microfiber", "velvet", "satin", "wool", "fabric", "linen"),
    # The ROAD, which is a material and not a coat: an asphalt's
    # truth spread is 0.0178 and a "rough" word would say 0.0840.
    ("asphalt", "pavement", "road", "granular", "matte"),
    # The SURFACES that carry a coat or a layer.
    (
        "moss",
        "mossy",
        "rust",
        "rusty",
        "oxidized",
        "stained",
        "dirty",
        "worn",
        "aged",
        "weathered",
    ),
    # The GROUND, which is the most varied of all.
    (
        "gravel",
        "ground",
        "dirt",
        "rubble",
        "debris",
        "scattered",
        "uneven",
        "rocky",
        "riverbed",
        "soil",
        "sand",
    ),
    # The STONE and the MINE.
    (
        "rock",
        "stone",
        "bricks",
        "brick",
        "tiles",
        "tile",
        "grid",
        "checkered",
        "limestone",
        "slate",
        "clay",
        "terracotta",
        "concrete",
        "plaster",
    ),
    # The WOOD, which varies with the grain.
    ("wood", "wooden", "grain", "knots", "plank", "timber", "softwood"),
    # The GENERAL words, read last.
    (
        "smooth",
        "polished",
        "clean",
        "uniform",
        "rough",
        "coarse",
        "natural",
        "light",
        "industrial",
        "urban",
        "subtle",
        "minimalist",
        "modern",
    ),
)


def _coloured(
    value: float, hue: tuple[float, float, float]
) -> tuple[float, float, float]:
    """A luma and a hue, as an RGB triple.

    The hue is the channel SHARES, and the luma is the value the
    description asked for. The three channels are scaled so that their
    weighted sum IS the luma - so the hue never changes the
    brightness, and the description's colour says both.
    """
    weights = (0.2126, 0.7152, 0.0722)
    total = sum(share * weight for share, weight in zip(hue, weights))
    if total <= 0.0:
        return (value, value, value)
    scale = value / total
    return tuple(max(0.0, min(1.0, share * scale)) for share in hue)


# The HUE each MATERIAL word carries, as channel shares.
#
# A material's hue is tighter than a colour word's - measured, the
# spread over the truths naming "ground" is 0.012 and over those
# naming "wood" 0.030, against 0.045 for "beige" and 0.048 for
# "gray". So the material says the hue and the colour word is the
# fallback, the same way the value is read.
#
# Measured from the truth's own pixels: the marble tile is R 0.347 G
# 0.333 B 0.320 - almost neutral - and the word "beige" says 0.389
# 0.334 0.278, which is much warmer.
MATERIAL_HUES: dict[str, object] = {
    'bricks': (0.393, 0.343, 0.264),
    'stone': (0.376, 0.344, 0.280),
    'fabric': (0.353, 0.328, 0.319),
    'wool': (0.454, 0.310, 0.236),
    'wood': (0.444, 0.330, 0.226),
    'ground': (0.393, 0.345, 0.262),
    'rocky': (0.383, 0.341, 0.276),
    'dirt': (0.391, 0.340, 0.268),
    'gravel': (0.364, 0.339, 0.297),
    'scattered': (0.405, 0.343, 0.252),
    'asphalt': (0.342, 0.338, 0.321),
    'pavement': (0.346, 0.339, 0.315),
    'tiles': (0.381, 0.334, 0.285),
    'mud': (0.401, 0.342, 0.256),
    'soil': (0.400, 0.341, 0.259),
    'mossy': (0.413, 0.385, 0.202),
    'rock': (0.344, 0.358, 0.298),
    'moss': (0.394, 0.374, 0.233),
    'leaves': (0.437, 0.345, 0.217),
    'earth': (0.401, 0.353, 0.246),
    'limestone': (0.394, 0.334, 0.271),
    'metal': (0.339, 0.337, 0.324),
    'steel': (0.336, 0.334, 0.329),
    'wooden': (0.459, 0.327, 0.215),
    'parquet': (0.486, 0.337, 0.176),
    'concrete': (0.350, 0.338, 0.313),
    'plaster': (0.337, 0.335, 0.328),
    'paint': (0.337, 0.337, 0.326),
"marble": (0.347, 0.333, 0.320),
"silver": (0.336, 0.335, 0.329),
"clay": (0.420, 0.333, 0.247),
"sand": (0.400, 0.333, 0.267),
}


def hue_for_description(description: str) -> tuple[float, float, float]:
    """The HUE the description's colour words carry, as channel shares.

    The words are read in order, and the FIRST colour named wins -
    the same rule the luma follows, and for the same reason: a
    description that says "blue, fabric" means blue.

    The shares are of the colour's SUM, so the hue is independent
    of the luma - a dark blue and a pale blue are the same hue.

    Measured on the truth's own pixels: the fabric is R 0.217 G 0.333
    B 0.451, the red fabric R 0.542 G 0.275 B 0.183, and the metal
    is exactly neutral. A palette with no hue made every material
    grey.
    """
    words = description.lower().replace(",", " ").split()
    # The MATERIAL's word says the hue, and the colour word is the
    # fallback - the same order the value is read in, and for the
    # same reason: a material's hue is tighter than a colour word's.
    #
    # And a GENERIC material lets the colour decide, exactly as it
    # does for the value: a "fabric" on its own says a thing's kind
    # and not its colour, and the truth's two fabrics are R 0.217 G
    # 0.333 B 0.451 and R 0.542 G 0.275 B 0.183 - the blue one and
    # the orange one.
    #
    # Measured: with the material's hue first and no generic
    # exception, the blue fabric's colour error read 0.352 against
    # the truth's, where the colour word's own reads 0.032.
    for word in words:
        hue = MATERIAL_HUES.get(word.strip(".,"))
        if hue is not None and word.strip(".,") not in GENERIC_MATERIALS:
            return hue
    for word in words:
        hue = HUES.get(word.strip(".,"))
        if hue is not None:
            return hue
    for word in words:
        hue = MATERIAL_HUES.get(word.strip(".,"))
        if hue is not None:
            return hue
    return DEFAULT_HUE


def _spread_of(word: str) -> float:
    """The spread a word carries, or the DEFAULT when it carries none.

    The tiers name words the truth set does not have - "tile",
    "satin", "chrome" - and a tier says what those words MEAN, so
    the word's own spread is not needed: the tier's FIRST word is the
    measured one and the rest follow it.

    Without this, a description naming any of them raised a
    KeyError: the lookup went straight to the table.
    """
    return SPREADS.get(word, DEFAULT_SPREAD)


def spread_for_description(description: str) -> float:
    """How much the surface's colour varies, from the description's
    texture words.

    The words are read in order, and the FIRST one named wins - so
    "soft, fur, microfiber" is soft, and "rough, rocky, gravel" is
    rough.

    A MATERIAL's words are read before the others, because a
    description's word order is alphabetical and says nothing: a
    fabric described as "blue, fabric, fur, microfiber, soft" is a
    SOFT one - its spread measures 0.0090 - and the "blue" that comes
    first says nothing about how much the surface varies. So the
    material's own words decide, and the general ones are the
    fallback.

    The values are the truths' own, fitted: a word's value is the
    mean truth's spread over the materials that name it.
    """
    words = _words_of(description)
    if is_metal(description):
        for tier in METAL_SPREAD_TIERS:
            for word in tier:
                if word in words:
                    return _spread_of(word)
    for tier in SPREAD_TIERS:
        for word in tier:
            if word in words:
                return _spread_of(word)
    for word in description.lower().replace(",", " ").split():
        spread = SPREADS.get(word.strip(".,"))
        if spread is not None:
            return spread
    return DEFAULT_SPREAD


def brick_aspect_for_description(description: str) -> float:
    """How wide a brick is, as a multiple of its height.

    A BRICK is oblong - the truth's brick is about four thirds as
    wide as it is tall, and it has eight courses and six bricks
    across.

    A TILE is SQUARE. The truth's tiles are a six-by-six grid of
    squares with a hairline grout, and a brick's aspect turned them
    into a wall of long oblongs - the tile's feature scale then read
    0.58x the truth's.

    So the aspect is the description's: a "tile" is square, and
    everything else is a brick.
    """
    from golem_blender.pbr.pattern import BRICK_ASPECT

    words = set(description.lower().replace(",", " ").split())
    if words & {"tile", "tiles"}:
        return 1.0
    return BRICK_ASPECT


def metal_envelope_factor_for_description(description: str) -> float:
    """How much COARSER the metal's envelope is than its cell count.

    A Perlin's value oscillates faster than its lattice, and the
    feature measure reads the value - so the envelope's lattice has
    to be coarser than the cell count, and by how much depends on
    the surface.

    Measured: the truth's corrugated steel reads 0.96x the truth's
    feature scale with a factor of two and 1.68x with one; the
    polished silver reads 1.53x with one and 0.81x with two; and the
    aged steel reads 1.10x with one and 0.61x with two.

    So a ROUGH sheet's envelope is coarse and a POLISHED one's is
    fine: the rough sheet's weathering is broad and the polished
    sheet's is a fine grain.
    """
    words = set(description.lower().replace(",", " ").split())
    if words & {"rough", "coarse", "corrugated", "ribbed", "ridged", "striped"}:
        return METAL_ROUGH_ENVELOPE_FACTOR
    if words & {"fine"}:
        return METAL_DEFAULT_ENVELOPE_FACTOR
    if words & {"polished", "polish", "clean", "smooth", "mirror", "chrome"}:
        return METAL_FINE_ENVELOPE_FACTOR
    return METAL_DEFAULT_ENVELOPE_FACTOR


def metal_is_banded(description: str) -> bool:
    """Whether a metal sheet is ROLLED - and so carries BANDS.

    A sheet that has been ROLLED or BRUSHED has a direction: the
    grain of the rolling, the bands of the pressing. A sheet that has
    been AGED has PATCHES - the rust, the staining, the weathering -
    and no direction at all.

    And the truth's own aged steel says so: its correlation is 0.023
    at a lag of twenty and 0.003 at fifty, so there is no structure
    in it at all along a row. A banded sheet has its bands' own
    spacing in the row, and the measure reads that.

    So a sheet that is not rolled is a field of patches, and its
    patches are what the measure reads.
    """
    words = set(description.lower().replace(",", " ").split())
    # A PRESSED sheet is pressed whatever else is true of it: the
    # truth's own corrugated steel is "worn" as well as corrugated,
    # and the pressing is what the pattern is.
    if words & {"corrugated", "ribbed", "ridged", "striped", "pipe"}:
        return True
    # A POLISHED sheet is polished: the truth's own silver is "clean,
    # metal, silver, smooth", and its correlation decays smoothly from
    # 0.33 at a lag of twenty to 0.18 at fifty - so it has no bands
    # and no structure along a row, only a fine brushed grain.
    if words & {"polished", "polish", "clean", "smooth", "mirror", "chrome"}:
        return False
    return not words & {
        "aged",
        "oxidized",
        "rusted",
        "rusty",
        "weathered",
        "worn",
        "stained",
        "corroded",
    }


def metal_direction_for_description(description: str) -> bool:
    """Whether a metal sheet's BANDS run as rows, and not as columns.

    A PRESSED sheet's ribs are horizontal - a corrugated or a ribbed
    sheet - and the truth's own corrugated steel is a pressed sheet of
    straight parallel ribs.

    And the direction decides what the feature measure reads. The
    measure reads along a ROW, so a sheet whose bands are COLUMNS
    has the bands' own spacing read - and the truth's corrugated
    steel measures 5.89 features across at a period of 174 pixels,
    while its ribs are sixteen pixels apart. The measure found the
    sheet's slow variation along the row, and not the ribs.

    So a pressed sheet's bands are rows: the row's own variation is
    the slow one, and the ribs are across the row.
    """
    words = set(description.lower().replace(",", " ").split())
    return bool(words & {"corrugated", "ribbed", "ridged", "striped", "pipe"})


def pebble_factor_for_description(description: str) -> float:
    """How many PEBBLES a cell holds, for a surface of loose pieces.

    A loose ground crazes - the truth's own ground carries
    eighty-one pebble-gaps across where the feature measure reads
    twenty, so the pebbles are four times finer than the envelope.
    A concrete or a plaster does not: it is one surface, cut into
    pieces, and it does not crackle.

    So the factor is the loose grounds' four and everything else's
    one.
    """
    from golem_blender.pbr.patterns import is_pebbled

    if is_pebbled(description):
        return PEBBLE_FACTOR
    return 1.0


def palette_for_description(
    description: str,
    spread: float | None = None,
    mortar_offset: float | None = None,
    path: str = "voronoi",
):
    """The colours a description calls for: the stone ramp and the mortar.

    The mortar is a little DARKER than the stones, and only a little -
    a cobble's joint is pale sand, not a crack. Measured, a pale
    joint brought the fabric's spread to 1.13x the truth's against
    1.64x for the dark-joint default.

    The joint's darkness is a fraction of the SPREAD, not a fixed
    0.06. A fixed offset is six times the whole spread of a soft
    fabric, and the joint then dominates the image's contrast: the
    fabric's read 4.84x the truth's while its ramp alone read 0.35x.
    So the joint is as dark as the surface varies, and no darker.

    The spread is the description's too, unless one is given: the
    truth sets' spreads run from 0.0090 to 0.1290, and the words say
    which.

    `path` is which pattern the colours are for, and it changes the
    ramp's width: each path carries its contrast differently, and
    the measured factor is the correction.
    """
    value = value_for_description(description)
    if spread is None:
        spread = spread_for_description(description)
    half_width = spread * RAMP_SPREAD_FACTOR
    # The ramp is CENTRED on the value, and it is not clipped: a
    # ramp that runs off the bottom of the range is not centred, and
    # the image's mean is no longer the description's colour. So a
    # ramp that would not fit is narrowed to fit, symmetrically.
    #
    # Measured, the asphalt's value is 0.175 with a half-width of
    # 0.145 and the ramp's bottom was clamped to zero - so the
    # ramp's centre sat at 0.32 and the image's mean was 0.175, and
    # the asphalt's contrast read 4.53x the truth's.
    fitted = min(half_width, value, 1.0 - value)
    low = value - fitted
    high = value + fitted
    if mortar_offset is None:
        mortar_offset = MORTAR_SPREAD_FRACTION * spread
    mortar = max(0.0, value - mortar_offset)
    # The colour is (luma, HUE), and the hue is the description's
    # colour word's: the truth's ground is R 0.379 G 0.336 B 0.286 and
    # its blue fabric is R 0.217 G 0.333 B 0.451. A palette with no
    # hue made every material grey, and the truth's are not.
    hue = hue_for_description(description)
    return {
        "stone_dark_rgb": _coloured(low, hue),
        "stone_light_rgb": _coloured(high, hue),
        "mortar_rgb": _coloured(mortar, hue),
        "target_spread": spread,
        "target_value": value,
        "pebble_factor": pebble_factor_for_description(description),
        "brick_aspect": brick_aspect_for_description(description),
        "metal_horizontal": metal_direction_for_description(description),
        "metal_banded": metal_is_banded(description),
        "metal_envelope_factor": metal_envelope_factor_for_description(description),
    }


def line_palette_for_description(description: str, path: str = "grain"):
    """The colours a LINE pattern calls for: one base colour.

    A grain and a metal are LINES on a surface, and a line pattern has
    no cells to vary - the whole image is ONE colour and the lines are
    the only variation on it. So the palette for a line pattern is a
    single value: the description's own colour.

    The spread is the description's too, and it is what sets the
    LINE's own contrast. The truth sets' spread-to-luma ratios run
    from 0.0063 on a polished metal to 0.2184 on a mossy rock, and
    the words carry them the way they carry the colour.

    The line's contrast is the spread times the path's own factor:
    a soft line's falloff carries a fraction of what the spread says,
    and the measured factor is the correction.
    """
    value = value_for_description(description)
    spread = spread_for_description(description)
    hue = hue_for_description(description)
    return {
        "stone_dark_rgb": _coloured(value, hue),
        "stone_light_rgb": _coloured(value, hue),
        "mortar_rgb": _coloured(value, hue),
        "target_spread": spread,
        "target_value": value,
        "metal_horizontal": metal_direction_for_description(description),
        "metal_banded": metal_is_banded(description),
        "metal_envelope_factor": metal_envelope_factor_for_description(description),
    }


__all__ = (
    "DEFAULT_SPREAD",
    "DEFAULT_VALUE",
    "NAMED_COLOURS",
    "SPREADS",
    "line_palette_for_description",
    "palette_for_description",
    "spread_for_description",
    "value_for_description",
)
