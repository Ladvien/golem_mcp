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
    "cobalt": 0.7594,
    "gold": 0.8935,
    "iron": 0.7450,
    "rust": 0.4295,
    "silver": 0.9832,
    "steel": 0.4686,
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
    "chrome": 0.95,
    "aluminium": 0.88,
    "aluminum": 0.88,
    "brass": 0.62,
    "bronze": 0.42,
    "copper": 0.52,
    "rusty": 0.34,
    "oxidized": 0.30,
}

# The value used when the description names no colour.
DEFAULT_VALUE = 0.5

# The EXTREME lightness words, and what each says on its own.
#
# These four are about HOW LIGHT the thing is and about nothing else,
# so they are read before the material's word - and the material's
# word says only what KIND of thing it is.
#
# Measured on the truth's own eighty-seven: the truth's Rock035 is a
# "black, cave, cliff, grey, rock, stone" at a luma of 0.094, and
# "black" names eight materials in the set whose lumas run from
# 0.094 to 0.429 - a mean of 0.213. And "white" names eight whose
# lumas run from 0.692 to 0.972 - a mean of 0.797. "dark" names
# fifteen at a mean of 0.266 and "light" six at a mean of 0.626.
EXTREME_VALUES: dict[str, float] = {
    "black": 0.211,
    "white": 0.797,
    "dark": 0.266,
    "light": 0.626,
}
# And the DARKEST of them wins, so a "black, dark" thing is very
# dark and a "light, white" thing is very light.
EXTREME_LIGHT_WORDS = ("black", "white", "dark", "light")
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
HUES: dict[str, tuple[float, float, float]] = {
    "natural": (0.389, 0.342, 0.268),
    "blue": (0.217, 0.333, 0.451),
    "brown": (0.420, 0.328, 0.251),
    "silver": (0.336, 0.335, 0.329),
    "dark": (0.555, 0.344, 0.101),
    "white": (0.336, 0.335, 0.329),
    "gold": (0.399, 0.356, 0.245),
    "black": (0.331, 0.333, 0.336),
    "grey": (0.316, 0.333, 0.351),
    "cobalt": (0.332, 0.335, 0.333),
    "gray": (0.342, 0.329, 0.328),
    "beige": (0.359, 0.347, 0.294),
    "orange": (0.538, 0.293, 0.169),
    "red": (0.542, 0.275, 0.183),
    "light": (0.388, 0.334, 0.277),
    "charcoal": (0.359, 0.342, 0.299),
    "green": (0.416, 0.374, 0.211),
    "cream": (0.386, 0.334, 0.280),
    "rust": (0.338, 0.335, 0.326),
    "rusty": (0.338, 0.335, 0.326),
    "tan": (0.436, 0.335, 0.229),
    "yellow": (0.405, 0.346, 0.249),
    "espresso": (0.398, 0.319, 0.282),
    "bright": (0.444, 0.346, 0.210),
    "wood": (0.412, 0.332, 0.256),
    "wooden": (0.412, 0.332, 0.256),
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
SPREADS: dict[str, float] = {
    "cobalt": 0.0183,
    "gold": 0.0064,
    "iron": 0.0341,
    "rust": 0.0269,
    "silver": 0.0061,
    "steel": 0.0514,
    "aged": 0.0595,
    "asphalt": 0.0344,
    "autumn": 0.0812,
    "bathroom": 0.0655,
    "beige": 0.0566,
    "black": 0.0342,
    "blue": 0.0452,
    "bricks": 0.0754,
    "bright": 0.0174,
    "broken": 0.0475,
    "brown": 0.0579,
    "carpet": 0.0767,
    "cave": 0.0628,
    "center": 0.0714,
    "charcoal": 0.0178,
    "checkered": 0.0994,
    "classic": 0.0546,
    "clay": 0.0192,
    "clean": 0.0380,
    "cliff": 0.0742,
    "cloth": 0.1084,
    "concrete": 0.0310,
    "construction": 0.0599,
    "corroded": 0.0656,
    "corrugated": 0.0760,
    "cover": 0.0812,
    "cracked": 0.0554,
    "cream": 0.0589,
    "damaged": 0.0731,
    "damp": 0.1056,
    "dark": 0.0421,
    "dashed": 0.0714,
    "debris": 0.1337,
    "dirt": 0.1039,
    "dirty": 0.0847,
    "dry": 0.0987,
    "durable": 0.0391,
    "earth": 0.0840,
    "elegant": 0.0286,
    "eroded": 0.1254,
    "espresso": 0.0286,
    "fabric": 0.0703,
    "fallen": 0.0812,
    "fine": 0.0339,
    "floor": 0.0559,
    "flooring": 0.0539,
    "forest": 0.0915,
    "fur": 0.0090,
    "furniture": 0.0286,
    "glossy": 0.0269,
    "golden": 0.0507,
    "grain": 0.0360,
    "grained": 0.0856,
    "granular": 0.0404,
    "grass": 0.1056,
    "gravel": 0.1203,
    "gray": 0.0751,
    "green": 0.0995,
    "grey": 0.0443,
    "grid": 0.0644,
    "ground": 0.0993,
    "hard": 0.0281,
    "hardwood": 0.0363,
    "indoor": 0.0332,
    "industrial": 0.0432,
    "interior": 0.0286,
    "irregular": 0.0926,
    "kitchen": 0.0649,
    "knots": 0.0396,
    "lane": 0.0714,
    "layered": 0.0478,
    "leather": 0.0238,
    "leaves": 0.0833,
    "light": 0.0357,
    "limestone": 0.0626,
    "line": 0.0714,
    "markings": 0.0714,
    "matte": 0.0185,
    "metal": 0.0294,
    "microfiber": 0.0090,
    "minimalist": 0.0358,
    "modern": 0.0356,
    "moss": 0.0969,
    "mossy": 0.1035,
    "mountain": 0.0944,
    "mud": 0.0751,
    "muddy": 0.0853,
    "natural": 0.0708,
    "neutral": 0.0599,
    "old": 0.0501,
    "orange": 0.0370,
    "outdoor": 0.0457,
    "overgrown": 0.1056,
    "oxidized": 0.0269,
    "paint": 0.0302,
    "painted": 0.0129,
    "parquet": 0.0447,
    "patches": 0.0714,
    "pathway": 0.0856,
    "patterned": 0.1888,
    "pavement": 0.0323,
    "pebbles": 0.0649,
    "pipe": 0.0760,
    "plain": 0.0505,
    "plank": 0.0495,
    "planks": 0.0430,
    "plaster": 0.0248,
    "plastisol": 0.0032,
    "polished": 0.0330,
    "printed": 0.0032,
    "rectangular": 0.0672,
    "red": 0.0505,
    "ribbed": 0.0760,
    "ridged": 0.0760,
    "river": 0.1176,
    "riverbed": 0.1176,
    "road": 0.0284,
    "rock": 0.0795,
    "rocky": 0.1162,
    "roof": 0.0192,
    "roofing": 0.0192,
    "rough": 0.0723,
    "rubble": 0.1337,
    "rustic": 0.0490,
    "rusty": 0.0269,
    "sandstone": 0.0507,
    "sbsar": 0.0256,
    "scattered": 0.1068,
    "scratched": 0.0207,
    "slightly": 0.0546,
    "smooth": 0.0342,
    "smudge": 0.1140,
    "soft": 0.0160,
    "softwood": 0.0396,
    "soil": 0.0704,
    "solid": 0.0399,
    "spotted": 0.0676,
    "square": 0.0504,
    "stacked": 0.0926,
    "staggered": 0.0495,
    "stained": 0.0705,
    "stitched": 0.0636,
    "stone": 0.0723,
    "street": 0.0399,
    "striped": 0.0640,
    "stucco": 0.0199,
    "subtle": 0.0277,
    "suede": 0.0174,
    "surface": 0.0199,
    "tan": 0.0623,
    "textile": 0.1888,
    "tiles": 0.0529,
    "tiling": 0.0192,
    "two": 0.0714,
    "uneven": 0.1104,
    "uniform": 0.0277,
    "urban": 0.0494,
    "wall": 0.0550,
    "wallpaper": 0.0072,
    "white": 0.0398,
    "wood": 0.0348,
    "woodchip": 0.0072,
    "wooden": 0.0197,
    "woodland": 0.1056,
    "wool": 0.0437,
    "worn": 0.0441,
    "woven": 0.1888,
    "yellow": 0.0569,
    "asphalt033": 0.0178,
    "bricks106a": 0.0713,
    "bricks108a": 0.0738,
    "bricks113a": 0.0763,
    "corrugatedsteel009": 0.0760,
    "fabric084": 0.0090,
    "fabric085": 0.0505,
    "ground108": 0.1337,
    "ground110": 0.1243,
    "ground112": 0.0958,
    "rock064": 0.0926,
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
MATERIAL_VALUES: dict[str, float] = {
    "asphalt": 0.3054,
    "bricks": 0.4604,
    "carpet": 0.3997,
    "clay": 0.3384,
    "cloth": 0.3604,
    "concrete": 0.5889,
    "dirt": 0.4021,
    "earth": 0.4582,
    "fabric": 0.4809,
    "grass": 0.5635,
    "gravel": 0.3971,
    "ground": 0.4220,
    "iron": 0.7450,
    "leather": 0.3234,
    "leaves": 0.4181,
    "limestone": 0.6894,
    "metal": 0.6376,
    "moss": 0.4703,
    "mossy": 0.4352,
    "mud": 0.4154,
    "paint": 0.7446,
    "parquet": 0.3722,
    "pavement": 0.3131,
    "plank": 0.4993,
    "planks": 0.3461,
    "plaster": 0.7530,
    "rock": 0.3621,
    "rocky": 0.4007,
    "roof": 0.3384,
    "roofing": 0.3384,
    "sandstone": 0.4148,
    "scattered": 0.4057,
    "soil": 0.4165,
    "steel": 0.4686,
    "stone": 0.4967,
    "stucco": 0.8303,
    "textile": 0.4075,
    "tiles": 0.5682,
    "wallpaper": 0.8787,
    "wood": 0.4587,
    "woodchip": 0.8787,
    "wooden": 0.5182,
    "wool": 0.4802,
    "woven": 0.4075,
    "silver": 0.9832,
    "corrugated": 0.5078,
    "sand": 0.66,
    "rust": 0.34,
    "rusty": 0.34,
    "oxidized": 0.30,
}

# The materials that are SPECIFIC - a steel before a metal, a brick
# before a stone - and so are read before the general ones.
# The MATERIAL tiers, and the most specific first.
#
# A carpet is a carpet and not a fabric; a parquet is a parquet and
# not a wood; a leather is a leather and not a fabric; a wallpaper is
# a wallpaper and not a paper.
#
# The most specific material was found by taking the ALPHABETICALLY
# first, and that is not the most specific - a "beige, carpet,
# fabric, floor, soft, white, wool" found "fabric" and not "carpet",
# and the lane's kind for a carpet took a fabric's colour.
MATERIAL_TIERS = (
    (
        "carpet",
        "rug",
        "leather",
        "hide",
        "parquet",
        "wallpaper",
        "woodchip",
        "roof",
        "roofing",
        "shingle",
        "herringbone",
        "basketweave",
    ),
    (
        "wool",
        "bricks",
        "tiles",
        "tiling",
        "limestone",
        "corrugated",
        "asphalt",
        "concrete",
        "woven",
        "weave",
        "textile",
        "cloth",
    ),
    ("silver", "steel", "fabric", "wood", "moss", "mossy", "dirt", "gravel", "ground"),
    ("clay", "sand", "rust", "rusty", "oxidized"),
)
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
# The GENERIC materials, and they let the COLOUR decide.
#
# A generic material says what a thing is MADE OF and not what it
# looks like: a "fabric" on its own is a thing's kind, and the
# truth's two fabrics are 0.374 and 0.527 - the orange one and the
# blue one - so the colour is what tells them apart.
#
# A WOOL is the same: it names a fibre and not a colour, and the
# truth's own orange wool is 0.374 where the wool's own fitted
# value says 0.533.
#
# And a WOOD is the same: the truth's own four woods measure 0.633,
# 0.217, 0.541 and 0.649 - a pale one, a dark one, a mid one and a
# pale one - and the words that tell them apart are "beige, light"
# and "brown, espresso". A wood's own fitted value is 0.4587 and it
# is none of them.
GENERIC_MATERIALS = frozenset(
    {"fabric", "stone", "metal", "wool", "carpet", "leather", "parquet", "wood"}
)

# How many materials each colour word names, and a word that names
# FEW is a SPECIFIC one.
#
# The wide set's "beige" names fourteen materials and their lumas run
# from 0.360 to 0.798 - so its value is a mean of nothing in
# particular. And "espresso" names ONE - a dark hardwood floor at
# 0.214 - and it says exactly how dark.
#
# So the words that name few materials win, and the general ones are
# the fallback. The counts are the fitter's own.
# How specific a colour word has to be to win outright.
#
# A word that names at most this many materials is SPECIFIC and its
# own value says exactly how dark the thing is. A word that names
# more is a GENERAL one, and the DARKEST colour named wins instead:
# a "blue, dark" thing is a dark blue.
#
# The limit is ONE: "blue" names three materials and their lumas run
# from 0.229 to 0.527, so its own value says nothing about how dark
# a blue is - and the truth's own Carpet012 is a "blue, carpet, dark,
# plain" that measures 0.229.
#
# "espresso" names one and it is 0.214, and the truth's own brown
# hardwood floor is 0.214 - and the word wins outright.
COLOUR_SPECIFICITY_LIMIT = 1

COLOUR_SPECIFICITY: dict[str, int] = {
    "espresso": 1,
    "cobalt": 1,
    "gold": 2,
    "cream": 2,
    "silver": 3,
    "blue": 3,
    "light": 6,
    "beige": 14,
    "brown": 16,
    "black": 8,
    "white": 8,
    "gray": 16,
    "grey": 9,
    "natural": 20,
    "dark": 15,
}

# The colour words, and the value each carries.
COLOUR_VALUES: dict[str, float] = {
    "beige": 0.4348,
    "black": 0.2107,
    "blue": 0.5266,
    "brown": 0.5338,
    "cobalt": 0.7594,
    "dark": 0.2835,
    "gold": 0.8935,
    "gray": 0.3928,
    "grey": 0.4046,
    "natural": 0.4604,
    "silver": 0.9832,
    "white": 0.8167,
    "bright": 0.7940,
    "charcoal": 0.3217,
    "cream": 0.6652,
    "espresso": 0.2140,
    "green": 0.4626,
    "light": 0.6389,
    "orange": 0.4331,
    "red": 0.3743,
    "rust": 0.4295,
    "rusty": 0.4295,
    "tan": 0.6221,
    "yellow": 0.3594,
    "snow": 0.92,
    "clay": 0.42,
    "terracotta": 0.44,
    "brick": 0.4758,
    "purple": 0.30,
    "pink": 0.66,
    "slate": 0.34,
    "lime": 0.74,
    "steel": 0.43,
    "iron": 0.42,
    "chrome": 0.95,
    "aluminium": 0.88,
    "aluminum": 0.88,
    "brass": 0.62,
    "bronze": 0.42,
    "copper": 0.52,
    "oxidized": 0.30,
}


def _colour_value(description: str) -> float | None:
    """The value the description's COLOUR word carries, if any.

    The words are alphabetical, so the order is the description's own
    - and a description that says "brown, smooth, wood, wooden"
    means brown.

    And a SPECIFIC colour wins over a general one. "beige" names
    fourteen materials in the wide set and their lumas run from 0.360
    to 0.798, so its own value is a mean of nothing in particular;
    and "espresso" names ONE - a dark hardwood floor at 0.214 - and
    it says exactly how dark.

    So the words that name FEW materials win, and the general ones
    are the fallback.
    """
    words = [word.strip(".,") for word in description.lower().replace(",", " ").split()]
    named = [word for word in words if word in COLOUR_VALUES]
    if not named:
        return None
    # The DARKEST colour wins, and not the most specific one.
    #
    # A description that says "blue, dark" means a DARK blue, and
    # the truth's own Carpet012 is a dark blue at 0.229 while the
    # "blue" word says 0.5266 and the "dark" word says 0.2835.
    #
    # So among the colours named, the one with the lowest value is
    # the one that reads: a "dark, blue" thing is darker than a
    # "blue" thing.
    #
    # And a SPECIFIC colour still wins when the general one is
    # DARKER: "espresso" names ONE and says 0.214, and a "brown,
    # espresso" thing is a dark brown and not a mid one.
    named.sort(key=lambda word: (COLOUR_SPECIFICITY.get(word, 99), words.index(word)))
    most_specific = named[0]
    if COLOUR_SPECIFICITY.get(most_specific, 99) <= COLOUR_SPECIFICITY_LIMIT:
        return COLOUR_VALUES[most_specific]
    named.sort(key=lambda word: (COLOUR_VALUES.get(word, 1.0), words.index(word)))
    return COLOUR_VALUES[named[0]]


def _material_word(description: str) -> str | None:
    """The description's MATERIAL word, and the most specific one.

    The most specific wins: a steel before a metal, a brick before a
    stone.
    """
    words = _words_of(description)
    # The TIERS are read first: the most specific material decides.
    #
    # And a tier word with no fitted VALUE is not a material the
    # palette knows - so a "wallpaper, woodchip" found "wallpaper" in
    # the tier and the lookup raised a KeyError on it.
    #
    # So the tier is only read for the words the table carries, and
    # the tiers and the table stay in step.
    for tier in MATERIAL_TIERS:
        for word in tier:
            if word in words and word in MATERIAL_VALUES:
                return word
    for word in sorted(words & SPECIFIC_MATERIALS):
        if word in MATERIAL_VALUES:
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
    # The EXTREME words are DIRECT statements about how light the
    # thing is, and they come before the material's word.
    #
    # The material's word says what KIND of thing it is, and the
    # word "tiles" names eight materials in the wide set whose lumas
    # run from 0.211 to 0.972 - so the kind says nothing about how
    # light it is. But "black" and "white" and "dark" and "light"
    # are about the lightness and about nothing else.
    #
    # Measured on the truth's own eighty-seven: the truth's Rock035
    # is a "black, cave, cliff, grey, rock, stone" at a luma of
    # 0.094, and the material's word "rock" said 0.362 - so the
    # rock's own value was four times the truth's. And the truth's
    # own Tiles138 is a "black, square, stone, tiles" at 0.211 where
    # the material's word said 0.568.
    #
    # So the extreme words are read first, and the DARKEST of them
    # wins: a "black, dark" thing is very dark and a "light, white"
    # thing is very light. Fitted against the eighty-seven, the mean
    # error fell from 0.0790 to 0.0624 and the worst from 0.4035 to
    # 0.2418.
    extreme = [
        EXTREME_VALUES[word]
        for word in EXTREME_LIGHT_WORDS
        if word in _words_of(description)
    ]
    if extreme:
        return min(extreme)
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
# How many materials each METAL word names, and the fewest wins.
#
# The truth's own gold is one material and the truth's own silver is
# one, and their spreads are 0.0064 and 0.0061 - and "metal" names
# eight and its spread is 0.0294.
METAL_SPECIFICITY: dict[str, int] = {
    "gold": 1,
    "silver": 1,
    "cobalt": 1,
    "iron": 1,
    "gray": 9,
    "grey": 9,
    "black": 8,
    "brass": 1,
    "copper": 1,
    "bronze": 1,
    "chrome": 1,
    "aluminium": 1,
    "aluminum": 1,
    "corrugated": 1,
    "ribbed": 1,
    "ridged": 1,
    "brushed": 1,
    "pipe": 1,
    "polished": 5,
    "fine": 5,
    "satin": 2,
    "clean": 11,
    "smooth": 22,
    "metal": 8,
    "steel": 3,
    "worn": 6,
    "aged": 4,
    "rusty": 2,
    "rust": 3,
    "rough": 26,
    "matte": 2,
    "glossy": 2,
    "mirror": 1,
}

METAL_SPREAD_TIERS = (
    ("corrugated", "ribbed", "ridged", "brushed", "pipe"),
    ("oxidized", "aged", "rusty", "rust", "worn", "rough", "coarse", "matte"),
    # The METAL, and it comes before the finish.
    #
    # The metal's word is the SPECIFIC one: "gold" names one material
    # in the wide set and its spread measures 0.0064, and "silver"
    # names one at 0.0061 - and the truth's own Metal048A is a
    # "clean, gold, metal, smooth" that measures 0.0056.
    #
    # The finish words are the general ones: "clean" names eleven
    # materials and their spreads run from 0.0031 to 0.1888, and
    # "smooth" names twenty-two. So their means are means of nothing
    # in particular.
    # The COLOUR, and it is its own tier and it comes FIRST: a grey
    # metal is a grey metal and not a generic one.
    #
    # The truth's own Metal032 is a "grey, metal, smooth" that
    # measures a spread of 0.0131, and "metal" names eight materials
    # and its spread is 0.0294 - so the generic word was twice the
    # truth's.
    ("gray", "grey", "black"),
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
        "silver",
        "cobalt",
        "rust",
    ),
    ("clean", "smooth", "fine", "satin", "polished", "mirror", "chrome"),
)
# How many materials each SPREAD word names, and a word that names
# FEW is a specific one.
#
# The wide set's "leather" names six materials and their spreads run
# from 0.0031 to 0.0636 - a twentyfold range - so its value is a
# mean of nothing in particular. And "stitched" names ONE.
#
# The counts are the fitter's own.
SPREAD_SPECIFICITY: dict[str, int] = {
    "stitched": 1,
    "suede": 1,
    "bright": 1,
    "roof": 3,
    "roofing": 3,
    "tiling": 3,
    "clay": 3,
    "leather": 6,
    "hide": 1,
    "carpet": 3,
    "rug": 1,
    "parquet": 4,
    "wallpaper": 1,
    "woodchip": 1,
    "roof": 3,
    "roofing": 3,
    "shingle": 3,
    "herringbone": 1,
    "basketweave": 1,
    "woven": 2,
    "weave": 1,
    "textile": 2,
    "cloth": 4,
    "linen": 1,
    "microfiber": 1,
    "velvet": 1,
    "fur": 3,
}

SPREAD_TIERS = (
    # The MATERIAL's own word, and it is its own tier and it comes
    # FIRST.
    #
    # A material's own word says more about how much it varies than
    # the general words do: a "clean" thing can be a leather at 0.0031
    # of spread or a checkered cloth at 0.1888 - a sixtyfold range -
    # and the leather's own word says 0.0238.
    #
    # So the material's word is read first, and the general words -
    # "clean", "smooth", "fine" - are the fallback.
    (
        "leather",
        "hide",
        "carpet",
        "rug",
        "parquet",
        "wallpaper",
        "woodchip",
        "woven",
        "weave",
        "textile",
        "cloth",
        "concrete",
        "asphalt",
        "pavement",
        "bricks",
        "tiles",
        "planks",
        "plank",
    ),
    # The ROOF, and it is its own tier: a roof's own word says more
    # about how much it varies than the "tiles" it is made of.
    #
    # The truth's own three roofs measure spreads of 0.0169, 0.0257
    # and 0.0149, and the "tiles" word says 0.0529 over eleven
    # materials.
    ("roof", "roofing", "tiling", "shingle"),
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


# The HUE's own variation, and it is a MATERIAL's word.
#
# A field of stones is not one colour: the truth's own gravel carries
# stones whose red share varies by 0.0153, and its fallen leaves
# vary by 0.0223 - a mat of MANY colours and not one colour in many
# shades.
#
# So the variation is the material's word: a leaf mat is a patchwork
# and a gravel is a family.
# The DEFAULT hue's variation, and it is the gravel's own.
#
# Measured on the truth's own gravel: the stones' red share runs
# from 0.351 to 0.393, so the variation is a fiftieth of the hue.
SCATTER_HUE_VARIATION = 0.10
HUE_VARIATION_TIERS = (("leaves", "fallen", "autumn", "foliage"),)


def hue_variation_for_description(description: str) -> float:
    """How much a stone's HUE varies from the surface's own.

    The default is the gravel's own - 0.0153 in the red share - and a
    material that is a PATCHWORK of colours varies more.

    And only a LEAF MAT is a patchwork: a "forest" is where the
    leaves are and not a mat of them, and the truth's own Ground106
    says "forest" and carries stones whose red share varies by
    0.0119 - LESS than the gravel's - against the fallen leaves'
    0.0223.
    """
    words = set(description.lower().replace(",", " ").split())
    for tier in HUE_VARIATION_TIERS:
        for word in tier:
            if word in words:
                return SCATTER_HUE_VARIATION * 1.5
    return SCATTER_HUE_VARIATION


# How much a ROCK's CURVATURE carries, and it is the ROCK's word and
# not a general one.
#
# The curvature is what gives a rock its FACETS - the sharp edges
# between flat faces - and the truth's own Rock051 carries a gradient
# of 0.037, one and a half times the sheet's own variation, where
# the lane's rock is a smooth blob field with no edge in it.
#
# So a rock asks for the curvature and nothing else does.
CURVATURE_STRENGTHS: dict[str, float] = {
    "rock": 1.2,
    "rocky": 1.0,
    "cliff": 1.2,
    "cave": 1.0,
    "stone": 0.7,
    "bricks": 0.5,
    "concrete": 0.35,
}


# How much a surface's SCRATCHES carry, and it is the word that says
# there are any.
#
# Material Maker's `scratches2` - a set of layers of wavy lines,
# each layer with its own angle and its own per-cell randomness, and
# the layers maximised together so the scratches overlap the way real
# abrasions do.
#
# The truth's own "scratched" material measures a spread of 0.0207
# and its "eroded" one 0.1254, and a sheet with no word saying it
# is scratched has none.
SCRATCH_STRENGTHS: dict[str, float] = {
    "scratched": 0.6,
    "eroded": 0.5,
    "worn": 0.35,
    "abraded": 0.5,
    "scuffed": 0.4,
    "scratch": 0.6,
}


# How much a BRICK's own FACE carries, and a TILE's face is flat.
#
# A brick is a piece of stone that was cut and worked, and its face
# carries the grain of the stone and the marks of the working. A
# TILE is glazed and flat, and the truth's own Tiles141 keeps 0.0349
# of its spread at a hundred-and-twenty-eight-pixel blur - its
# variation is a slow drift and not a face.
#
# Measured on the truth's own: the brick's blur profile runs 0.0682,
# 0.0561, 0.0349 and 0.0087, and the tile's 0.0556, 0.0445, 0.0334
# and 0.0349.
BRICK_FACE_STRENGTHS: dict[str, float] = {
    # The SPECIFIC kinds are read first, and the generic ones after.
    # The truth's own Tiles141 is tagged with BOTH "stone" and
    # "tiles", and the word "stone" is the generic one - so a table
    # that reads "stone" first gave the tile a brick's worked face
    # and the wall came out as a chequerboard of swirls.
    "tiles": 0.06,
    "tile": 0.06,
    "ceramic": 0.06,
    "porcelain": 0.06,
    "glazed": 0.05,
    "bricks": 0.85,
    "brick": 0.85,
    "concrete": 0.20,
    "plaster": 0.12,
    "stone": 0.55,
    "rock": 0.5,
}

# How much a surface's SLOW DRIFT carries, and it is a TILE's and not
# a BRICK's.
#
# A tile is a large flat surface and it STAINS, and the stain is
# the drift: the truth's own Tiles141 carries a spread of 0.0349 at
# a hundred-and-twenty-eight-pixel blur - a fifth of the whole map -
# and its drift's period is a hundred and ninety-two pixels.
#
# And a brick is a mosaic of worked pieces and the pieces do not
# stain together: the truth's own Bricks113A carries 0.0087 at the
# same blur, a ninth of the tile's.
DRIFT_STRENGTHS: dict[str, float] = {
    # The SPECIFIC kinds first, and the generic ones after - the same
    # rule the pattern's own routing uses.
    "tiles": 0.85,
    "tile": 0.85,
    "ceramic": 0.85,
    "porcelain": 0.85,
    "plaster": 0.65,
    "concrete": 0.5,
    "bricks": 0.10,
    "brick": 0.10,
    "stone": 0.25,
    "rock": 0.15,
}


def drift_strength_for_description(description: str) -> float:
    """How much the surface's SLOW DRIFT carries, from its words."""
    words = set(description.lower().replace(",", " ").split())
    for word, strength in DRIFT_STRENGTHS.items():
        if word in words:
            return strength
    return 0.0


def brick_face_strength_for_description(description: str) -> float:
    """How much a brick's own FACE carries, from its words."""
    words = set(description.lower().replace(",", " ").split())
    for word, strength in BRICK_FACE_STRENGTHS.items():
        if word in words:
            return strength
    return 0.0


def scratch_strength_for_description(description: str) -> float:
    """How much the surface's SCRATCHES carry, from its words."""
    words = set(description.lower().replace(",", " ").split())
    for word, strength in SCRATCH_STRENGTHS.items():
        if word in words:
            return strength
    return 0.0


def curvature_strength_for_description(description: str) -> float:
    """How much the surface's CURVATURE carries, from its words.

    The curvature is Material Maker's `smooth_curvature2` - a
    discrete second difference over a cone of offsets - and it is the
    map that gives a hand-painted edge treatment its rim and a cavity
    mask its darkness. A rock is a set of flat faces with sharp edges
    between them, and it is what the curvature is for.
    """
    words = set(description.lower().replace(",", " ").split())
    for word, strength in CURVATURE_STRENGTHS.items():
        if word in words:
            return strength
    return 0.0


def _paint_colour(description: str) -> tuple[float, float, float]:
    """The colour a ROAD MARKING is painted in.

    A marking is not the road's colour. The truth's own Road007 is a
    pale white line on a luma of 0.309 and Road008A is a yellow one,
    and the description says which: "white" says white and "yellow"
    says yellow.

    And the paint is WORN, and the wear is the road's own age: the
    truth's own Road007's white line measures a luma of 0.533 and
    its Road008A's yellow one 0.377, and a fresh white is 0.80.

    So the paint is the colour word's own value - the yellow is 0.76
    and the white 0.82 - and the WEAR brings it down to what the
    truth's own line measures.
    """
    words = set(description.lower().replace(",", " ").split())
    # The paint's WEAR, and it is the road's own age.
    #
    # Measured on the truth's own: Road007's white line measures a
    # luma of 0.683 and Road012A's measures 0.301 - a road's paint
    # is as worn as the road is old.
    #
    # And the words say it: Road007 is a "smooth, street, urban" one
    # and Road012A a "rough, worn, old" one.
    wear = 1.0
    if words & {
        "worn",
        "old",
        "aged",
        "weathered",
        "faded",
        "rough",
        "cracked",
        "damaged",
    }:
        wear = 0.45
    if "yellow" in words:
        # The truth's own Road008A's yellow line measures R 0.548
        # G 0.431 B 0.082 - a deep yellow and not a pale one - and
        # the road is an "old, worn" one and the paint is not.
        #
        # A yellow line keeps its colour where a white one goes grey
        # with the road, so the wear is the WHITE paint's and not the
        # yellow's.
        return (0.548, 0.431, 0.082)
    if "white" in words:
        # The truth's own Road007's white line measures R 0.682
        # G 0.685 B 0.664 - a GREY white, because a painted line on
        # a road is a worn one.
        return (0.682 * wear, 0.685 * wear, 0.664 * wear)
    # A road with no colour word: the paint is white, and a white
    # line on a road is a worn one.
    return (0.682 * wear, 0.685 * wear, 0.664 * wear)


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
MATERIAL_HUES: dict[str, tuple[float, float, float]] = {
    "stone": (0.377, 0.344, 0.279),
    "bricks": (0.389, 0.342, 0.268),
    "wool": (0.484, 0.298, 0.218),
    "fabric": (0.347, 0.326, 0.327),
    "wood": (0.448, 0.332, 0.219),
    "ground": (0.389, 0.343, 0.267),
    "scattered": (0.397, 0.342, 0.261),
    "rocky": (0.381, 0.340, 0.278),
    "gravel": (0.370, 0.339, 0.291),
    "dirt": (0.388, 0.340, 0.272),
    "pavement": (0.348, 0.339, 0.313),
    "asphalt": (0.344, 0.338, 0.318),
    "tiles": (0.391, 0.328, 0.282),
    "soil": (0.400, 0.341, 0.259),
    "mud": (0.401, 0.342, 0.256),
    "moss": (0.393, 0.372, 0.235),
    "rock": (0.351, 0.359, 0.289),
    "mossy": (0.407, 0.379, 0.214),
    "earth": (0.401, 0.353, 0.246),
    "leaves": (0.437, 0.345, 0.217),
    "limestone": (0.393, 0.334, 0.273),
    "steel": (0.336, 0.334, 0.329),
    "metal": (0.338, 0.336, 0.325),
    "wooden": (0.446, 0.327, 0.227),
    "parquet": (0.496, 0.338, 0.165),
    "plank": (0.417, 0.331, 0.252),
    "concrete": (0.347, 0.337, 0.316),
    "plaster": (0.336, 0.335, 0.329),
    "iron": (0.333, 0.334, 0.333),
    "grass": (0.394, 0.379, 0.226),
    "planks": (0.481, 0.336, 0.183),
    "carpet": (0.309, 0.337, 0.355),
    "stucco": (0.339, 0.333, 0.328),
    "sandstone": (0.501, 0.336, 0.163),
    "paint": (0.337, 0.337, 0.326),
    "textile": (0.338, 0.325, 0.336),
    "woven": (0.338, 0.325, 0.336),
    "cloth": (0.314, 0.335, 0.352),
    "leather": (0.454, 0.311, 0.235),
    "clay": (0.433, 0.304, 0.263),
    "roofing": (0.433, 0.304, 0.263),
    "roof": (0.433, 0.304, 0.263),
    "wallpaper": (0.335, 0.336, 0.329),
    "woodchip": (0.335, 0.336, 0.329),
    "marble": (0.347, 0.333, 0.320),
    "silver": (0.336, 0.335, 0.329),
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
            # The tier's own MOST SPECIFIC word, and not its first.
            #
            # The tier read "metal" before "gold", and "metal" names
            # eight materials and its spread is 0.0294 - while "gold"
            # names ONE and its spread is 0.0064, which is the
            # truth's own Metal048A to within a thousandth.
            #
            # So the tier is read by the word's own SPECIFICITY: the
            # fewest materials, and the first of those in the
            # description's own order.
            named = [word for word in tier if word in words]
            if named:
                named.sort(
                    key=lambda word: (METAL_SPECIFICITY.get(word, 99), tier.index(word))
                )
                return _spread_of(named[0])
    for tier in SPREAD_TIERS:
        for word in tier:
            if word in words:
                return _spread_of(word)
    # The words that are not in a tier, and the MOST SPECIFIC of them
    # wins.
    #
    # "leather" names six materials in the wide set and their spreads
    # run from 0.0031 to 0.0636 - a twentyfold range - so its own
    # value is a mean of nothing in particular. And "stitched" names
    # ONE, and it says exactly how much the surface varies.
    #
    # So the words that name few materials win, and the general ones
    # are the fallback.
    named = [
        word.strip(".,")
        for word in description.lower().replace(",", " ").split()
        if word.strip(".,") in SPREADS
    ]
    if named:
        named = [(word, index) for index, word in enumerate(named)]
        named.sort(key=lambda pair: (SPREAD_SPECIFICITY.get(pair[0], 99), pair[1]))
        return _spread_of(named[0][0])
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
    # A ROLLED or a BRUSHED sheet has a direction, and a sheet with
    # NO word saying so does not.
    #
    # The rule was "banded unless the words say otherwise", and the
    # words rarely do - so a "cobalt, metal" and an "iron, metal"
    # came out banded, and the truth's own are SMOOTH sheets: their
    # row-to-column change ratio is 1.00 and 1.13 where ours came
    # out at 0.52.
    #
    # Measured, the truth's own gold measures a ratio of 1.04 and its
    # grey one 1.00 - and a banded sheet's ratio is nowhere near
    # one.
    #
    # So a sheet is banded only when its words say it was rolled or
    # brushed, and it is a field of patches otherwise.
    return bool(words & {"brushed", "rolled", "rolling", "satin", "hairline"})


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
        # The PAINT's colour, and it is not the surface's colour: a
        # lane marking is white or yellow on a grey road, and the
        # truth's own Road007 is a pale line on a luma of 0.309 and
        # Road008A is a yellow one.
        "paint_rgb": _paint_colour(description),
        # And how much the surface's CURVATURE carries.
        "curvature_strength": curvature_strength_for_description(description),
        # And how much the surface's SCRATCHES carry.
        "scratch_strength": scratch_strength_for_description(description),
        # And how much a BRICK's own FACE carries.
        "brick_face_strength": brick_face_strength_for_description(description),
        # And how much the surface's SLOW DRIFT carries.
        "drift_strength": drift_strength_for_description(description),
        # And how much a STONE's hue varies from the surface's own.
        "hue_variation": hue_variation_for_description(description),
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
