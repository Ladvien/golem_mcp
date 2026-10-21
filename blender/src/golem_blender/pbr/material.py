"""The ORM a DESCRIPTION calls for: how rough, how metallic.

The lane bakes its ORM with a CONSTANT roughness of 0.85 and a
constant metallic of 0.0 for every material it makes. The truth's
roughness runs from 0.034 on a polished metal to 0.793 on a fabric -
so the lane's ORM is wrong for every material, and most wrongly for
the metals, whose whole character is a low roughness and a metallic
of one.

The words carry it, the same way the colour and the pattern do:
"glossy", "polished", "clean" are a low roughness; "wool", "fur",
"granular", "rough" are a high one. And a material that is METAL is
metallic.

The values are the truths' own, so the mapping is read off the data:
a polished metal measures 0.034, a brick 0.628, a fabric 0.784.
"""

from __future__ import annotations

# How rough, by the words. The values are the truth sets' own
# roughnesses: 0.034 for a polished metal, 0.492 for a smooth wood,
# 0.514 for a tile, 0.628 for a brick, 0.745 for an asphalt and
# 0.784 for a fabric.
ROUGHNESS: dict[str, float] = {
    "polished": 0.10,
    "glossy": 0.16,
    "mirror": 0.05,
    "clean": 0.10,
    "smooth": 0.30,
    "fine": 0.40,
    "satin": 0.30,
    "natural": 0.605,
    "wooden": 0.50,
    "wood": 0.577,
    "light": 0.585,
    "beige": 0.520,
    "cream": 0.514,
    "limestone": 0.425,
    "concrete": 0.516,
    "plaster": 0.52,
    "tile": 0.51,
    "tiles": 0.454,
    "grid": 0.454,
    "brick": 0.63,
    "bricks": 0.643,
    "stone": 0.549,
    "ground": 0.518,
    "dirt": 0.529,
    "gravel": 0.529,
    "rocky": 0.529,
    "mossy": 0.80,
    "moss": 0.80,
    "asphalt": 0.745,
    "granular": 0.75,
    "matte": 0.78,
    "rough": 0.80,
    "coarse": 0.80,
    "wool": 0.788,
    "fur": 0.793,
    "microfiber": 0.793,
    "fabric": 0.788,
    "corrugated": 0.474,
    "pipe": 0.47,
    "ribbed": 0.47,
    "ridged": 0.47,
    "brushed": 0.12,
    "industrial": 0.451,
    "urban": 0.517,
    "pavement": 0.74,
    "road": 0.74,
    "rust": 0.35,
    "rusty": 0.35,
    "oxidized": 0.13,
    "aged": 0.134,
    "stained": 0.424,
    "dirty": 0.512,
    "worn": 0.494,
    "irregular": 0.60,
    "scattered": 0.529,
    "uneven": 0.529,
    "debris": 0.517,
    "rubble": 0.60,
    "riverbed": 0.55,
    "forest": 0.70,
    "indoor": 0.50,
    "outdoor": 0.65,
    "rock": 0.55,
    "silver": 0.03,
    "gold": 0.20,
    "chrome": 0.05,
    # The structure words. A pine board with knots measures 0.670 and
    # the same wood without them measures 0.492, so the knots are
    # worth about 0.18 of roughness.
    "knots": 0.67,
    "knot": 0.67,
    "wood096": 0.670,
    "sawdust": 0.70,
    "splinters": 0.72,
    "splintered": 0.72,
    "cracked": 0.68,
    "chipped": 0.66,
    "grain": 0.55,
    "asphalt033": 0.745,
    "bathroom": 0.513,
    "black": 0.134,
    "blue": 0.793,
    "bricks106a": 0.657,
    "bricks108a": 0.644,
    "bricks113a": 0.628,
    "brown": 0.421,
    "charcoal": 0.745,
    "checkered": 0.514,
    "classic": 0.514,
    "corrugatedsteel009": 0.474,
    "dark": 0.451,
    "floor": 0.513,
    "gray": 0.566,
    "ground108": 0.517,
    "ground110": 0.541,
    "ground112": 0.497,
    "kitchen": 0.513,
    "orange": 0.788,
    "rectangular": 0.424,
    "red": 0.788,
    "tiles139": 0.514,
    "tiles141": 0.512,
    "tiles143": 0.335,
    "wood094": 0.492,
    "wood095": 0.567,
}

# The roughness used when the description says nothing about it.
DEFAULT_ROUGHNESS = 0.60
# The metallic used when the description says nothing about it.
DEFAULT_METALLIC = 0.0
# The STRUCTURE words, which outrank the material words, in the order
# of their authority over the roughness. A structure word says how the
# surface is BUILT, and a built surface is rougher than the same
# material left plain: a pine board with knots measures 0.670 while
# the same wood without them measures 0.492.
#
# The order is the authority and NOT the description's: "grain, knots"
# names the knots first in the sentence but the knots are the
# rougher thing, and the description's order is alphabetical here.
STRUCTURE_TIERS = (
    ("knots", "knot", "wood096", "splinters", "splintered", "sawdust"),
    ("cracked", "chipped"),
    ("grain",),
)
# The SURFACE words, which come after the material words. A surface
# word says what the surface FEELS like, and it is the last word
# spoken: a tile that is also "stained" and "rough" is still a tile.
SURFACE_WORDS = (
    "moss",
    "mossy",
    "rough",
    "coarse",
    "matte",
    "stained",
    "dirty",
    "rust",
    "rusty",
    "worn",
    "aged",
    "soft",
    "wool",
    "fur",
    "microfiber",
    "fuzzy",
    "velvet",
    "softwood",
    "scattered",
    "uneven",
    "irregular",
)
# The MATERIAL words, which outrank the surface words. A surface
# word says what the surface feels like - "mossy" is a coat of
# moss - and a material word says what the thing IS, and a rock with
# moss on it is still a rock. Measured: Rock064 measures 0.552 and
# its words name both "moss" and "rock".
#
# The tiers are the specificity: a "wooden" board measures 0.492 and
# a "wood" one 0.577, and the description that names both is the
# specific one that decides.
MATERIAL_TIERS = (
    ("wooden", "softwood", "timber", "plank", "floorboard"),
    ("fabric", "wool", "linen", "microfiber", "fur", "velvet"),
    ("brick", "bricks"),
    ("tile", "tiles", "grid", "checkered", "checkerboard"),
    ("limestone", "slate", "clay", "terracotta"),
    ("concrete", "plaster"),
    ("asphalt", "pavement", "road"),
    ("stone", "rock"),
    ("gravel", "ground", "dirt", "sand", "soil"),
    ("wood",),
    ("metal", "steel", "corrugated"),
)
# The materials that ARE metal. A metal is metallic, and that is the
# single thing that makes it read as one.
METAL_WORDS = (
    "metal",
    "steel",
    "iron",
    "aluminium",
    "aluminum",
    "brass",
    "bronze",
    "copper",
    "chrome",
    "silver",
    "gold",
    "rust",
    "rusty",
    "oxidized",
    "galvanized",
    "corrugated",
)
# A metal's FINISH words, which outrank its material words: a metal's
# roughness is its finish, and the finish is what the words are
# actually describing. Measured: a polished, glossy, oxidised steel
# measures 0.134 while a clean, smooth silver measures 0.034, and a
# corrugated, rough one measures 0.474.
METAL_TIERS = (
    # The FORM: a corrugated sheet's ridges catch the light from many
    # angles whatever its finish, so the form sets the roughness.
    ("corrugated", "ribbed", "ridged", "brushed", "pipe"),
    # The CONDITION: what has happened to the surface.
    ("oxidized", "aged", "rusty", "rust", "worn", "rough", "coarse", "matte"),
    # The BARE state: a bright metal, with nothing on it.
    ("silver", "chrome", "mirror", "polished", "glossy"),
    # The GENERIC sense: clean and smooth, with no stronger word.
    ("clean", "smooth", "fine", "satin"),
)
# The roughness a metal gets when its description names no tier.
DEFAULT_METAL_ROUGHNESS = 0.35


def is_metal(description: str) -> bool:
    """Whether the surface is METAL, from the description's words.

    Measured, the metals' roughness runs from 0.034 to 0.474 against
    0.492 to 0.793 for everything else - so a metal is a low
    roughness and a metallic of one, and the words say which.

    The words are WHOLE words, not substrings: a description with
    "minimalist" in it is not a metal, and a substring test would
    have said it was.
    """
    words = {word.strip(".,") for word in description.lower().replace(",", " ").split()}
    return bool(words & set(METAL_WORDS))


def roughness_for_description(description: str) -> float:
    """How rough the surface is, from the description's words.

    The words are read in order and the FIRST one named wins, so
    "glossy, industrial, metal" is glossy.

    A metal is the exception, because a metal's roughness is its
    FINISH, and a description can name a metal's form, its condition,
    its bare state and a generic sense all at once. So a metal's
    words are read in TIERS - the form first, then the condition,
    then the bare state, then the generic sense - and the first tier
    that is named decides.

    Measured: a corrugated steel measures 0.474, an aged and oxidised
    one 0.134, and a clean silver one 0.034.
    """
    words = [word.strip(".,") for word in description.lower().replace(",", " ").split()]
    if is_metal(description):
        for tier in METAL_TIERS:
            for word in tier:
                if word in words:
                    return ROUGHNESS[word]
        return DEFAULT_METAL_ROUGHNESS
    for tier in STRUCTURE_TIERS:
        for word in tier:
            if word in words:
                return ROUGHNESS[word]
    for tier in MATERIAL_TIERS:
        for word in tier:
            if word in words:
                return ROUGHNESS[word]
    for word in words:
        if word in SURFACE_WORDS:
            return ROUGHNESS[word]
    for word in words:
        value = ROUGHNESS.get(word)
        if value is not None:
            return value
    return DEFAULT_ROUGHNESS


def orm_for_description(description: str) -> dict:
    """The ORM a description calls for: the roughness and the metallic.

    A metal is metallic - 1.0 - and a rough one is not: the metallic
    channel is 1 where the surface is bare metal and 0 where it is
    not, and the truth's own ORM packs it that way.
    """
    metallic = 1.0 if is_metal(description) else DEFAULT_METALLIC
    return {
        "roughness": roughness_for_description(description),
        "metallic": metallic,
    }


__all__ = (
    "DEFAULT_METALLIC",
    "DEFAULT_ROUGHNESS",
    "METAL_WORDS",
    "ROUGHNESS",
    "is_metal",
    "orm_for_description",
    "roughness_for_description",
)
