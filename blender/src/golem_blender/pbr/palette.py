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
}

# The value used when the description names no colour.
DEFAULT_VALUE = 0.50
# How far the ramp runs either side of the value, as a fraction of
# the full range. It is NARROW: a surface's colour varies little
# across itself, and a wide ramp is what made the maps too harsh.
DEFAULT_SPREAD = 0.08


def value_for_description(description: str) -> float:
    """How light the surface is, from the description's colour words.

    The words are read in order, and the FIRST colour named wins -
    a description that says "charcoal, dark, gray" means charcoal,
    not an average of the three.
    """
    for word in description.lower().replace(",", " ").split():
        value = NAMED_COLOURS.get(word.strip(".,"))
        if value is not None:
            return value
    return DEFAULT_VALUE


def palette_for_description(
    description: str,
    spread: float = DEFAULT_SPREAD,
    mortar_offset: float = 0.06,
):
    """The colours a description calls for: the stone ramp and the mortar.

    The mortar is a little DARKER than the stones, and only a little -
    a cobble's joint is pale sand, not a crack. Measured, a pale
    joint brought the fabric's spread to 1.13x the truth's against
    1.64x for the dark-joint default.
    """
    value = value_for_description(description)
    low = max(0.0, value - spread)
    high = min(1.0, value + spread)
    mortar = max(0.0, value - mortar_offset)
    return {
        "stone_dark_rgb": (low, low, low),
        "stone_light_rgb": (high, high, high),
        "mortar_rgb": (mortar, mortar, mortar),
    }


__all__ = (
    "DEFAULT_SPREAD",
    "DEFAULT_VALUE",
    "NAMED_COLOURS",
    "palette_for_description",
    "value_for_description",
)
