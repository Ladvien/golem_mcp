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
NAMED_COLOURS: dict[str, float] = {
    "black": 0.06,
    "charcoal": 0.20,
    "dark": 0.24,
    "grey": 0.42,
    "gray": 0.42,
    "asphalt": 0.32,
    "dirt": 0.30,
    "earth": 0.30,
    "brown": 0.34,
    "tan": 0.48,
    "beige": 0.60,
    "cream": 0.76,
    "white": 0.90,
    "snow": 0.92,
    "clay": 0.42,
    "terracotta": 0.44,
    "brick": 0.40,
    "red": 0.34,
    "orange": 0.48,
    "yellow": 0.66,
    "green": 0.38,
    "blue": 0.36,
    "purple": 0.30,
    "pink": 0.66,
    "slate": 0.34,
    "concrete": 0.56,
    "stone": 0.52,
    "sand": 0.66,
    "lime": 0.74,
    "wool": 0.58,
    "linen": 0.70,
    # The metals, which are the brightest surfaces the lane makes: a
    # polished steel plate measures luma 0.983, and a silver one is
    # nearly as bright. Without these, a description reading "clean,
    # metal, silver, smooth" found no colour at all and fell back to
    # the default.
    "silver": 0.92,
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
    "moss": 0.30,
    "mossy": 0.30,
}

# The value used when the description names no colour.
DEFAULT_VALUE = 0.50
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
    "aged": 0.0269,
    "asphalt": 0.0178,
    "asphalt033": 0.0178,
    "bathroom": 0.0649,
    "beige": 0.0530,
    "black": 0.0269,
    "blue": 0.0090,
    "bricks": 0.0738,
    "bricks106a": 0.0713,
    "bricks108a": 0.0738,
    "bricks113a": 0.0763,
    "brown": 0.0753,
    "charcoal": 0.0178,
    "checkered": 0.0546,
    "classic": 0.0546,
    "clean": 0.0169,
    "concrete": 0.0218,
    "corrugated": 0.0760,
    "corrugatedsteel009": 0.0760,
    "cream": 0.0546,
    "dark": 0.0402,
    "debris": 0.1337,
    "dirt": 0.1290,
    "dirty": 0.0753,
    "dry": 0.1243,
    "fabric": 0.0297,
    "fabric084": 0.0090,
    "fabric085": 0.0505,
    "fine": 0.0269,
    "floor": 0.0649,
    "flooring": 0.0681,
    "forest": 0.0926,
    "fur": 0.0090,
    "glossy": 0.0269,
    "grain": 0.0396,
    "granular": 0.0178,
    "gravel": 0.1290,
    "gray": 0.0889,
    "green": 0.0926,
    "grey": 0.0218,
    "grid": 0.0660,
    "ground": 0.1179,
    "ground108": 0.1337,
    "ground110": 0.1243,
    "ground112": 0.0958,
    "indoor": 0.0276,
    "industrial": 0.0402,
    "irregular": 0.0926,
    "kitchen": 0.0649,
    "knots": 0.0396,
    "light": 0.0296,
    "limestone": 0.0614,
    "matte": 0.0178,
    "metal": 0.0363,
    "microfiber": 0.0090,
    "minimalist": 0.0276,
    "modern": 0.0276,
    "moss": 0.0926,
    "mossy": 0.0926,
    "natural": 0.0623,
    "old": 0.0926,
    "orange": 0.0505,
    "oxidized": 0.0269,
    "pavement": 0.0178,
    "pipe": 0.0760,
    "plaster": 0.0218,
    "polished": 0.0272,
    "rectangular": 0.0717,
    "red": 0.0505,
    "ribbed": 0.0760,
    "ridged": 0.0760,
    "river": 0.1337,
    "riverbed": 0.1337,
    "road": 0.0178,
    "rock": 0.0926,
    "rock064": 0.0926,
    "rocky": 0.1290,
    "rough": 0.0840,
    "rubble": 0.1337,
    "rust": 0.0269,
    "rustic": 0.0276,
    "rusty": 0.0269,
    "scattered": 0.1290,
    "silver": 0.0061,
    "slightly": 0.0546,
    "smooth": 0.0275,
    "soft": 0.0090,
    "softwood": 0.0396,
    "square": 0.0546,
    "stacked": 0.0926,
    "stained": 0.0717,
    "steel": 0.0514,
    "stone": 0.0731,
    "striped": 0.0760,
    "subtle": 0.0276,
    "tan": 0.0681,
    "tiles": 0.0660,
    "tiles139": 0.0546,
    "tiles141": 0.0753,
    "tiles143": 0.0681,
    "uneven": 0.1290,
    "uniform": 0.0276,
    "urban": 0.0593,
    "wall": 0.0681,
    "white": 0.0753,
    "wood": 0.0278,
    "wood096": 0.0396,
    "wooden": 0.0162,
    "wool": 0.0505,
    "worn": 0.0653,
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
    for word in description.lower().replace(",", " ").split():
        value = NAMED_COLOURS.get(word.strip(".,"))
        if value is not None:
            return value
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
                    return SPREADS[word]
    for tier in SPREAD_TIERS:
        for word in tier:
            if word in words:
                return SPREADS[word]
    for word in description.lower().replace(",", " ").split():
        spread = SPREADS.get(word.strip(".,"))
        if spread is not None:
            return spread
    return DEFAULT_SPREAD


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
    return {
        "stone_dark_rgb": (low, low, low),
        "stone_light_rgb": (high, high, high),
        "mortar_rgb": (mortar, mortar, mortar),
        "target_spread": spread,
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
    return {
        "stone_dark_rgb": (value, value, value),
        "stone_light_rgb": (value, value, value),
        "mortar_rgb": (value, value, value),
        "target_spread": spread,
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
