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
# And a black REFLECTIVE surface is a different black from a black
# dielectric one, and the words cannot tell them apart.
#
# A black METAL is a mirror of a dark room and a black ASPHALT is a
# dark road under a bright sky, and both of them CATCH the light and
# so both of them are much lighter than the black they are named
# after. A black PLASTIC or a black LEATHER is the colour itself, and
# it is much darker.
#
# Measured on the truth's own fifteen blacks: the reflective ones -
# the metals and the asphalts - average 0.2499 and the dielectric
# ones - the plastics, the leathers, the rocks and the tiles -
# average 0.1401.
#
# So a reflective black has its own value, and it is the higher one.
EXTREME_REFLECTIVE_VALUES: dict[str, float] = {
    "black": 0.2499,
}
# And a black SMOOTH surface is darker than a black TEXTURED one, and
# the reason is physical: a rough surface catches the light in its
# own texture and a smooth one has nowhere to catch it.
#
# Measured on the truth's own seven dielectric blacks: the smooth
# ones average 0.0640 - the truth's own Plastic006 at 0.0303 and its
# Leather026 at 0.0976 - and the textured ones average 0.1705, a
# factor of 2.7 between them.
#
# So a black dielectric is 0.0640 when it is smooth and 0.1705 when
# it is not, and the truth's own Plastic006 read 7.02x the truth's
# brightness before the split.
EXTREME_SMOOTH_VALUES: dict[str, float] = {
    "black": 0.0640,
}
EXTREME_TEXTURED_VALUES: dict[str, float] = {
    "black": 0.1705,
}
# The words that name a SMOOTH surface.
EXTREME_SMOOTH_WORDS = frozenset(
    {
        "smooth",
        "shiny",
        "polished",
        "clean",
        "glossy",
        "mirror",
        "flat",
        "new",
    }
)
# The words that name a REFLECTIVE surface: a metal, and a road.
#
# A "black" thing with any of these is a mirror of a dark room and
# not a black colour.
EXTREME_REFLECTIVE_WORDS = frozenset(
    {
        "metal",
        "steel",
        "iron",
        "asphalt",
        "road",
        "pavement",
        "street",
        "tarmac",
        "chrome",
        "silver",
        "gold",
        "copper",
        "bronze",
        "brass",
        # "reflective" and "glossy" say the surface REFLECTS, and a
        # surface that reflects catches the light and is lighter
        # than its colour. The truth's own Marble016 is a "black,
        # marble, reflective, shiny" at 0.2436 - a dark stone with a
        # polished face, and not a black colour.
        "reflective",
        "glossy",
        "polished",
        "mirror",
    }
)
# And the DARKEST of them wins, so a "black, dark" thing is very
# dark and a "light, white" thing is very light.
EXTREME_LIGHT_WORDS = ("black", "white", "dark", "light")
# The extremes that point the DARK way.
EXTREME_DARK_WORDS = frozenset({"black", "dark"})
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
#
# And they are fitted on the EIGHTY-SEVEN wide materials and not on
# the twenty hand-picked ones: fourteen of the words were off by more
# than three hundredths on the wide set, and "beige" - which names
# fourteen of the eighty-seven - was 0.09 off and a quarter too grey,
# so every material that says "beige" came out a pale grey where the
# truth's is a warm tan.
#
# The biggest was "dark": the lane said 0.555, 0.344, 0.101 - a
# saturated orange - and the truth's own fifteen dark materials
# average 0.370, 0.326, 0.303, which is a near neutral. A dark thing
# is dark and not orange.
#
# The leave-one-out refit - each material's own value left out of
# its word's mean before the word is read - gives a mean error of
# 0.0559 against the in-sample 0.0552, so the fit is not seeing
# itself. The mean error fell from 0.0570 and the worst from 0.4198
# to 0.3399.
HUES: dict[str, tuple[float, float, float]] = {
    "rough": (0.3788, 0.3435, 0.2777),
    "stone": (0.3802, 0.3443, 0.2755),
    "smooth": (0.3802, 0.3317, 0.2881),
    "natural": (0.4062, 0.347, 0.2467),
    "gray": (0.3589, 0.3431, 0.2981),
    "beige": (0.4091, 0.3391, 0.2518),
    "brown": (0.4245, 0.3323, 0.2432),
    "urban": (0.3538, 0.3369, 0.3092),
    "dark": (0.3665, 0.331, 0.3025),
    "old": (0.368, 0.3416, 0.2903),
    "metal": (0.3371, 0.335, 0.3279),
    "floor": (0.405, 0.3388, 0.2561),
    "modern": (0.3865, 0.3357, 0.2778),
    "outdoor": (0.3632, 0.3462, 0.2906),
    "black": (0.3297, 0.3345, 0.3358),
    "clean": (0.4106, 0.3303, 0.2591),
    "wood": (0.4517, 0.335, 0.2133),
    "ground": (0.3918, 0.3438, 0.2644),
    "industrial": (0.3494, 0.3369, 0.3136),
    "tiles": (0.3975, 0.3301, 0.2724),
    "white": (0.3413, 0.3354, 0.3233),
    "bricks": (0.3881, 0.3424, 0.2695),
    "fabric": (0.3493, 0.3237, 0.327),
    "layered": (0.3716, 0.3502, 0.2782),
    "pavement": (0.3475, 0.3389, 0.3136),
    "rustic": (0.4233, 0.3498, 0.2268),
    "asphalt": (0.3428, 0.3379, 0.3193),
    "damaged": (0.3714, 0.3471, 0.2816),
    "worn": (0.3454, 0.3365, 0.3181),
    "light": (0.3857, 0.3341, 0.2802),
    "polished": (0.4113, 0.3334, 0.2553),
    "road": (0.3436, 0.3383, 0.3181),
    "street": (0.3416, 0.3371, 0.3212),
    "dirt": (0.3928, 0.3417, 0.2654),
    "grey": (0.3243, 0.3381, 0.3376),
    "grid": (0.3973, 0.3345, 0.2682),
    "dirty": (0.3784, 0.3502, 0.2714),
    "aged": (0.4035, 0.3508, 0.2457),
    "concrete": (0.3487, 0.3374, 0.3139),
    "cracked": (0.3638, 0.3538, 0.2825),
    "rectangular": (0.4068, 0.3343, 0.2589),
    "rock": (0.3615, 0.3647, 0.2738),
    "scattered": (0.3958, 0.3406, 0.2636),
    "steel": (0.3301, 0.3341, 0.3358),
    "uneven": (0.3929, 0.3402, 0.267),
    "wall": (0.3725, 0.3396, 0.2879),
    "fine": (0.4093, 0.3304, 0.2603),
    "green": (0.4012, 0.3778, 0.221),
    "bathroom": (0.363, 0.3329, 0.3041),
    "cliff": (0.3509, 0.3637, 0.2854),
    "forest": (0.4107, 0.3606, 0.2287),
    "indoor": (0.411, 0.3266, 0.2624),
    "iron": (0.3417, 0.3331, 0.3252),
    "leather": (0.4535, 0.3114, 0.2351),
    "parquet": (0.5085, 0.3393, 0.1522),
    "plaster": (0.3357, 0.3349, 0.3294),
    "striped": (0.3509, 0.3401, 0.309),
    "checkered": (0.3633, 0.3231, 0.3136),
    "cloth": (0.3186, 0.3328, 0.3486),
    "dry": (0.4065, 0.344, 0.2494),
    "flooring": (0.4412, 0.3321, 0.2268),
    "gravel": (0.3698, 0.3392, 0.291),
    "kitchen": (0.355, 0.3326, 0.3124),
    "limestone": (0.3926, 0.3344, 0.273),
    "minimalist": (0.4058, 0.3351, 0.2591),
    "painted": (0.3476, 0.3361, 0.3163),
    "planks": (0.4681, 0.3378, 0.1941),
    "red": (0.4536, 0.3012, 0.2452),
    "rocky": (0.3811, 0.3404, 0.2784),
    "scratched": (0.3386, 0.3372, 0.3242),
    "stained": (0.3699, 0.3336, 0.2965),
    "blue": (0.2353, 0.3303, 0.4344),
    "carpet": (0.3086, 0.3367, 0.3547),
    "eroded": (0.4206, 0.3755, 0.2038),
    "glossy": (0.3355, 0.3336, 0.3309),
    "granular": (0.3588, 0.3416, 0.2996),
    "marble": (0.3417, 0.3347, 0.3236),
    "medieval": (0.3853, 0.3511, 0.2636),
    "mossy": (0.4133, 0.3852, 0.2015),
    "orange": (0.5384, 0.2931, 0.1685),
    "patterned": (0.3595, 0.3224, 0.3182),
    "plain": (0.3432, 0.3297, 0.3271),
    "plastic": (0.3216, 0.3298, 0.3486),
    "soft": (0.2965, 0.3267, 0.3769),
    "stones": (0.384, 0.335, 0.281),
    "subtle": (0.4158, 0.3332, 0.251),
    "tan": (0.4519, 0.3353, 0.2129),
    "uniform": (0.4158, 0.3332, 0.251),
    "wooden": (0.4389, 0.3315, 0.2296),
    "beach": (0.3887, 0.3458, 0.2655),
    "brick": (0.3936, 0.339, 0.2674),
    "clay": (0.4333, 0.3041, 0.2626),
    "cream": (0.3857, 0.3343, 0.2799),
    "debris": (0.3862, 0.3393, 0.2745),
    "earth": (0.4009, 0.3527, 0.2464),
    "grain": (0.3878, 0.3299, 0.2823),
    "hardwood": (0.5121, 0.3362, 0.1517),
    "matte": (0.3526, 0.339, 0.3084),
    "moss": (0.3934, 0.3718, 0.2348),
    "mud": (0.396, 0.3426, 0.2614),
    "oxidized": (0.3385, 0.3353, 0.3262),
    "paint": (0.3362, 0.3365, 0.3273),
    "pattern": (0.3456, 0.3373, 0.3171),
    "river": (0.3944, 0.3419, 0.2637),
    "riverbed": (0.3944, 0.3419, 0.2637),
    "roof": (0.4333, 0.3041, 0.2626),
    "roofing": (0.4333, 0.3041, 0.2626),
    "rubble": (0.3862, 0.3393, 0.2745),
    "rust": (0.3385, 0.3353, 0.3262),
    "rusty": (0.3385, 0.3353, 0.3262),
    "sand": (0.3887, 0.3458, 0.2655),
    "soil": (0.4003, 0.3411, 0.2587),
    "square": (0.3619, 0.3338, 0.3043),
    "textile": (0.3541, 0.3156, 0.3303),
    "tiling": (0.4333, 0.3041, 0.2626),
    "wool": (0.4835, 0.2981, 0.2184),
    "woven": (0.3541, 0.3156, 0.3303),
    "yellow": (0.4036, 0.347, 0.2494),
    "arches": (0.3687, 0.3397, 0.2915),
    "broken": (0.3628, 0.3486, 0.2886),
    "charcoal": (0.3594, 0.3419, 0.2987),
    "classic": (0.3771, 0.3343, 0.2886),
    "cobblestone": (0.3687, 0.3397, 0.2915),
    "corrugated": (0.3343, 0.3335, 0.3322),
    "covered": (0.3138, 0.3325, 0.3537),
    "durable": (0.3524, 0.3399, 0.3077),
    "elegant": (0.3625, 0.3238, 0.3137),
    "fur": (0.2165, 0.3329, 0.4505),
    "golden": (0.5008, 0.3361, 0.1631),
    "irregular": (0.3931, 0.3679, 0.239),
    "knots": (0.3825, 0.3352, 0.2822),
    "leaves": (0.4374, 0.3453, 0.2173),
    "microfiber": (0.2165, 0.3329, 0.4505),
    "organic": (0.3948, 0.3508, 0.2544),
    "paving": (0.3687, 0.3397, 0.2915),
    "pipe": (0.3343, 0.3335, 0.3322),
    "powder": (0.3138, 0.3325, 0.3537),
    "ribbed": (0.3343, 0.3335, 0.3322),
    "ridged": (0.3343, 0.3335, 0.3322),
    "sandstone": (0.5008, 0.3361, 0.1631),
    "shiny": (0.304, 0.3286, 0.3674),
    "silver": (0.3363, 0.335, 0.3287),
    "slightly": (0.3771, 0.3343, 0.2886),
    "softwood": (0.3825, 0.3352, 0.2822),
    "solid": (0.3524, 0.3379, 0.3097),
    "stacked": (0.3931, 0.3679, 0.239),
    "tree": (0.3528, 0.3654, 0.2817),
    "accumulation": (0.3804, 0.3442, 0.2755),
    "arch": (0.3618, 0.337, 0.3013),
    "autumn": (0.4645, 0.3508, 0.1847),
    "bark": (0.4092, 0.3575, 0.2334),
    "bright": (0.4438, 0.3459, 0.2103),
    "castle": (0.3866, 0.36, 0.2534),
    "cave": (0.2221, 0.3653, 0.4127),
    "center": (0.3369, 0.3361, 0.327),
    "christmas": (0.2965, 0.3734, 0.3301),
    "clothing": (0.3858, 0.2961, 0.3181),
    "coastal": (0.3804, 0.3442, 0.2755),
    "cobalt": (0.3323, 0.3352, 0.3326),
    "cobble": (0.3757, 0.3425, 0.2818),
    "construction": (0.3657, 0.3428, 0.2915),
    "corroded": (0.3499, 0.3327, 0.3174),
    "cotton": (0.3858, 0.2961, 0.3181),
    "cover": (0.4645, 0.3508, 0.1847),
    "damp": (0.3942, 0.3795, 0.2263),
    "dashed": (0.3369, 0.3361, 0.327),
    "desert": (0.3804, 0.3442, 0.2755),
    "design": (0.2965, 0.3734, 0.3301),
    "deteriorated": (0.3446, 0.3397, 0.3158),
    "dune": (0.3804, 0.3442, 0.2755),
    "earthy": (0.3804, 0.3442, 0.2755),
    "espresso": (0.3984, 0.3192, 0.2824),
    "european": (0.3618, 0.337, 0.3013),
    "factory": (0.4127, 0.3284, 0.2589),
    "fallen": (0.4645, 0.3508, 0.1847),
    "fragments": (0.3859, 0.3321, 0.2821),
    "furniture": (0.3984, 0.3192, 0.2824),
    "gold": (0.3986, 0.3562, 0.2452),
    "grained": (0.3358, 0.3384, 0.3258),
    "grass": (0.3942, 0.3795, 0.2263),
    "gritty": (0.3804, 0.3442, 0.2755),
    "hard": (0.361, 0.3384, 0.3006),
    "historic": (0.3757, 0.3425, 0.2818),
    "impure": (0.3303, 0.335, 0.3347),
    "interior": (0.3984, 0.3192, 0.2824),
    "lane": (0.3369, 0.3361, 0.327),
    "large": (0.4184, 0.3445, 0.2371),
    "line": (0.3369, 0.3361, 0.327),
    "markings": (0.3369, 0.3361, 0.327),
    "mosaic": (0.3618, 0.337, 0.3013),
    "mountain": (0.3571, 0.3469, 0.296),
    "muddy": (0.4103, 0.3398, 0.2499),
    "neutral": (0.3657, 0.3428, 0.2915),
    "onyx": (0.3378, 0.3334, 0.3288),
    "ornament": (0.2965, 0.3734, 0.3301),
    "overgrown": (0.3942, 0.3795, 0.2263),
    "patches": (0.3369, 0.3361, 0.327),
    "path": (0.3859, 0.3321, 0.2821),
    "pathway": (0.3358, 0.3384, 0.3258),
    "pebbles": (0.3923, 0.3446, 0.263),
    "pedestrian": (0.3618, 0.337, 0.3013),
    "plaid": (0.3858, 0.2961, 0.3181),
    "plank": (0.4173, 0.3306, 0.2521),
    "plastisol": (0.3333, 0.3333, 0.3333),
    "platinum": (0.3463, 0.3347, 0.319),
    "printed": (0.3333, 0.3333, 0.3333),
    "random": (0.3822, 0.3566, 0.2612),
    "reflective": (0.3294, 0.3373, 0.3333),
    "rusted": (0.3967, 0.3264, 0.2768),
    "sbsar": (0.4742, 0.3026, 0.2232),
    "smudge": (0.3589, 0.3468, 0.2943),
    "spotted": (0.4029, 0.3345, 0.2626),
    "staggered": (0.4173, 0.3306, 0.2521),
    "stitched": (0.4073, 0.3083, 0.2844),
    "stucco": (0.3391, 0.3331, 0.3278),
    "suede": (0.4438, 0.3459, 0.2103),
    "surface": (0.3391, 0.3331, 0.3278),
    "travertine": (0.3729, 0.3397, 0.2874),
    "two": (0.3369, 0.3361, 0.327),
    "veined": (0.3266, 0.3285, 0.3449),
    "wallpaper": (0.3348, 0.3363, 0.3289),
    "windy": (0.3804, 0.3442, 0.2755),
    "woodchip": (0.3348, 0.3363, 0.3289),
    "woodland": (0.3942, 0.3795, 0.2263),
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
    "rough": 0.0685,
    "stone": 0.0757,
    "smooth": 0.0422,
    "natural": 0.0692,
    "gray": 0.0746,
    "beige": 0.0568,
    "brown": 0.0606,
    "urban": 0.049,
    "dark": 0.0437,
    "old": 0.0663,
    "metal": 0.0369,
    "floor": 0.057,
    "modern": 0.0445,
    "outdoor": 0.0479,
    "black": 0.0317,
    "clean": 0.0541,
    "wood": 0.0394,
    "ground": 0.0825,
    "industrial": 0.0463,
    "tiles": 0.0548,
    "white": 0.0364,
    "bricks": 0.0833,
    "fabric": 0.0886,
    "layered": 0.0511,
    "pavement": 0.0331,
    "rustic": 0.0535,
    "asphalt": 0.0324,
    "damaged": 0.0758,
    "worn": 0.0384,
    "light": 0.0373,
    "polished": 0.0385,
    "road": 0.0287,
    "street": 0.0414,
    "dirt": 0.0841,
    "grey": 0.0463,
    "grid": 0.0674,
    "dirty": 0.1017,
    "aged": 0.0591,
    "concrete": 0.0337,
    "cracked": 0.0521,
    "rectangular": 0.0652,
    "rock": 0.0852,
    "scattered": 0.1021,
    "steel": 0.0354,
    "uneven": 0.1,
    "wall": 0.0737,
    "fine": 0.0329,
    "green": 0.0921,
    "bathroom": 0.0655,
    "cliff": 0.0828,
    "forest": 0.094,
    "indoor": 0.0614,
    "iron": 0.0442,
    "leather": 0.0238,
    "parquet": 0.0445,
    "plaster": 0.0228,
    "striped": 0.0657,
    "checkered": 0.139,
    "cloth": 0.1245,
    "dry": 0.0925,
    "flooring": 0.0533,
    "gravel": 0.1203,
    "kitchen": 0.0651,
    "limestone": 0.0626,
    "minimalist": 0.0341,
    "painted": 0.0207,
    "planks": 0.0558,
    "red": 0.1037,
    "rocky": 0.1162,
    "scratched": 0.0252,
    "stained": 0.0705,
    "blue": 0.0452,
    "carpet": 0.0767,
    "eroded": 0.0833,
    "glossy": 0.0366,
    "granular": 0.0339,
    "marble": 0.0643,
    "medieval": 0.0975,
    "mossy": 0.109,
    "orange": 0.037,
    "patterned": 0.1613,
    "plain": 0.0505,
    "plastic": 0.0076,
    "soft": 0.0641,
    "stones": 0.0951,
    "subtle": 0.0277,
    "tan": 0.0594,
    "uniform": 0.0277,
    "wooden": 0.0415,
    "beach": 0.0248,
    "brick": 0.1098,
    "clay": 0.0192,
    "cream": 0.0589,
    "debris": 0.1123,
    "earth": 0.084,
    "grain": 0.036,
    "hardwood": 0.0388,
    "matte": 0.0185,
    "moss": 0.0969,
    "mud": 0.0623,
    "oxidized": 0.0269,
    "paint": 0.0244,
    "pattern": 0.0912,
    "river": 0.1176,
    "riverbed": 0.1176,
    "roof": 0.0192,
    "roofing": 0.0192,
    "rubble": 0.1123,
    "rust": 0.0269,
    "rusty": 0.0269,
    "sand": 0.0248,
    "soil": 0.0704,
    "square": 0.0504,
    "textile": 0.1952,
    "tiling": 0.0192,
    "wool": 0.0437,
    "woven": 0.1952,
    "yellow": 0.0456,
    "arches": 0.0853,
    "broken": 0.0666,
    "charcoal": 0.0178,
    "classic": 0.0546,
    "cobblestone": 0.0853,
    "corrugated": 0.076,
    "covered": 0.0174,
    "durable": 0.0391,
    "elegant": 0.0472,
    "fur": 0.009,
    "golden": 0.0507,
    "irregular": 0.0926,
    "knots": 0.0396,
    "leaves": 0.0833,
    "microfiber": 0.009,
    "organic": 0.0607,
    "paving": 0.0853,
    "pipe": 0.076,
    "powder": 0.0174,
    "ribbed": 0.076,
    "ridged": 0.076,
    "sandstone": 0.0507,
    "shiny": 0.0528,
    "silver": 0.0061,
    "slightly": 0.0546,
    "softwood": 0.0396,
    "solid": 0.0399,
    "stacked": 0.0926,
    "tree": 0.0645,
    "accumulation": 0.0145,
    "arch": 0.1112,
    "autumn": 0.0812,
    "bark": 0.1069,
    "bright": 0.0174,
    "castle": 0.0857,
    "cave": 0.0628,
    "center": 0.0714,
    "christmas": 0.022,
    "clothing": 0.2082,
    "coastal": 0.0145,
    "cobalt": 0.0183,
    "cobble": 0.0594,
    "construction": 0.0599,
    "corroded": 0.0656,
    "cotton": 0.2082,
    "cover": 0.0812,
    "damp": 0.1056,
    "dashed": 0.0714,
    "desert": 0.0145,
    "design": 0.022,
    "deteriorated": 0.0313,
    "dune": 0.0145,
    "earthy": 0.0145,
    "espresso": 0.0286,
    "european": 0.1112,
    "factory": 0.1399,
    "fallen": 0.0812,
    "fragments": 0.0697,
    "furniture": 0.0286,
    "gold": 0.0064,
    "grained": 0.0856,
    "grass": 0.1056,
    "gritty": 0.0145,
    "hard": 0.0281,
    "historic": 0.0594,
    "impure": 0.039,
    "interior": 0.0286,
    "lane": 0.0714,
    "large": 0.107,
    "line": 0.0714,
    "markings": 0.0714,
    "mosaic": 0.1112,
    "mountain": 0.0944,
    "muddy": 0.0853,
    "neutral": 0.0599,
    "onyx": 0.067,
    "ornament": 0.022,
    "overgrown": 0.1056,
    "patches": 0.0714,
    "path": 0.0697,
    "pathway": 0.0856,
    "pebbles": 0.0649,
    "pedestrian": 0.1112,
    "plaid": 0.2082,
    "plank": 0.0495,
    "plastisol": 0.0032,
    "platinum": 0.1435,
    "printed": 0.0032,
    "random": 0.1198,
    "reflective": 0.0912,
    "rusted": 0.1361,
    "sbsar": 0.0256,
    "smudge": 0.114,
    "spotted": 0.0676,
    "staggered": 0.0495,
    "stitched": 0.0636,
    "stucco": 0.0199,
    "suede": 0.0174,
    "surface": 0.0199,
    "travertine": 0.0332,
    "two": 0.0714,
    "veined": 0.0658,
    "wallpaper": 0.0072,
    "windy": 0.0145,
    "woodchip": 0.0072,
    "woodland": 0.1056,
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
        "platinum",
        "titanium",
        "zinc",
        "lead",
        "nickel",
        "pewter",
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

# A metal that is COATED carries a LAYER, and the layer's colour is
# the one a person sees - the metal underneath is hidden.
#
# This is the exception to the rule above, and the truth's own says
# so: the "aged, black, brown, dark, fine, glossy, industrial, metal,
# oxidized, polished, rust, rusty, smooth, steel" plate measures a
# luma of 0.429 - a mid grey-blue - and "black" would have said
# 0.06, because the black is the RUST and the sheet is under it.
#
# But a "black, covered, metal, painted, powder, steel" plate
# measures 0.180 and 0.128, and there the black is the PAINT and the
# steel is under IT. The words that say so are "painted", "covered"
# and "powder" - a coat that HIDES the metal.
#
# So a coated metal takes its TONE word and an uncoated one its
# SHEET word, and the truth's own "steel" alone runs from 0.128 to
# 0.508 over five metals - the word says little on its own.
METAL_COATING_WORDS = frozenset(
    {
        "painted",
        "paint",
        "covered",
        "powder",
        "coated",
        "enamel",
        "lacquer",
        "galvanized",
    }
)

# A METAL's own colour, fitted on the truth's own metals and not on
# the general table.
#
# The general table says what a colour word means on a CONCRETE or a
# ROCK, and a metal is a different thing: the truth's own Metal062C
# is a "damaged, dirty, metal, platinum" at a luma of 0.733, and the
# general table's "platinum" is 0.1435 - a fifth of the truth's.
# And the truth's Metal032 is a "grey, metal, smooth" at 0.527 where
# the general "grey" is 0.7228.
#
# So the metals get their own table, and it is fitted on the truth's
# own seventeen:
#
#     "steel" 0.4390  n=3  0.429, 0.508, 0.380
#     "iron"  0.7108  n=5  0.745, 0.726, 0.556, 0.749, 0.777
#     "silver" 0.9836, "gold" 0.8916, "platinum" 0.7327
#     "black" 0.2463, "grey" 0.5268
#
# The COATED metals are not in it: their colour is the coat's and
# their words name the coat.
# The words that say a metal's sheet is SCRATCHED, and how much
# darker a scratched sheet is.
#
# Measured on the truth's own: Metal038 is a "metal, scratched,
# steel" at a luma of 0.381, and its own "steel" is 0.439 - so a
# scratched sheet is about four fifths of a plain one. The scratches
# catch the light and scatter it.
METAL_SCRATCH_WORDS = frozenset({"scratch", "scratches", "scratched", "abrasion"})
METAL_SCRATCH_DARKENING = 0.8

# The words that name the WEATHERING on a metal's sheet - the rust
# and the grime - and not the sheet's own colour.
#
# They are PATCHES on the metal and not its colour, and the truth's
# own aged plate says so: a steel plate described as "aged, black,
# brown, dark, fine, glossy, industrial, metal, oxidized, polished,
# rust, rusty, smooth, steel" measures a luma of 0.429, and the mean
# of its own "steel" and its own "black" would be 0.343.
#
# So the weathering words are left out of the mean, and the sheet's
# own colour decides.
METAL_WEATHERING_WORDS = frozenset(
    {
        "rust",
        "rusty",
        "rusted",
        "oxidized",
        "oxidised",
        "aged",
        "weathered",
        "dirty",
        "grime",
        "grimy",
        "tarnished",
        "corroded",
        "worn",
    }
)

# The colour words that name a weathering's own darkness, and not the
# sheet's colour.
METAL_WEATHERING_COLOURS = frozenset({"black", "brown"})

# How much darker a coated metal is than the bare surface under it.
#
# The truth's own two powder-coated steels measure 0.179 and 0.129 -
# a mean of 0.154 - against the bare black metal's 0.246 and the
# general black extreme's 0.211. A powder coat is a matte paint and
# a paint is a flat dielectric surface, and a dielectric black is
# darker than a reflective one.
METAL_COAT_DARKENING = 0.73

METAL_COLOURS: dict[str, float] = {
    "black": 0.2463,
    "gold": 0.8916,
    "grey": 0.5268,
    "iron": 0.7108,
    "platinum": 0.7327,
    "silver": 0.9836,
    "steel": 0.4390,
}


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
    "rough": 0.4643,
    "stone": 0.5097,
    "smooth": 0.5366,
    "natural": 0.4904,
    "gray": 0.3878,
    "beige": 0.5683,
    "brown": 0.399,
    "urban": 0.4204,
    "dark": 0.3,
    "old": 0.3966,
    "metal": 0.5912,
    "floor": 0.4952,
    "modern": 0.4756,
    "outdoor": 0.3958,
    "black": 0.2274,
    "clean": 0.5854,
    "wood": 0.4482,
    "ground": 0.4636,
    "industrial": 0.4115,
    "tiles": 0.5574,
    "white": 0.7847,
    "bricks": 0.4563,
    "fabric": 0.481,
    "layered": 0.3862,
    "pavement": 0.2995,
    "rustic": 0.4377,
    "asphalt": 0.2833,
    "damaged": 0.3834,
    "worn": 0.3497,
    "light": 0.6564,
    "polished": 0.4883,
    "road": 0.2677,
    "street": 0.2896,
    "dirt": 0.4458,
    "grey": 0.5308,
    "grid": 0.6007,
    "dirty": 0.5394,
    "aged": 0.4478,
    "concrete": 0.5886,
    "cracked": 0.303,
    "rectangular": 0.6128,
    "rock": 0.3741,
    "scattered": 0.4172,
    "steel": 0.3741,
    "uneven": 0.4112,
    "wall": 0.6462,
    "fine": 0.4981,
    "green": 0.5178,
    "bathroom": 0.7122,
    "cliff": 0.3576,
    "forest": 0.4543,
    "indoor": 0.5959,
    "iron": 0.716,
    "leather": 0.3234,
    "parquet": 0.3484,
    "plaster": 0.7519,
    "striped": 0.3914,
    "checkered": 0.528,
    "cloth": 0.3699,
    "dry": 0.4028,
    "flooring": 0.499,
    "gravel": 0.3971,
    "kitchen": 0.7095,
    "limestone": 0.6894,
    "minimalist": 0.6108,
    "painted": 0.4197,
    "planks": 0.3988,
    "red": 0.4469,
    "rocky": 0.4007,
    "scratched": 0.2825,
    "stained": 0.6694,
    "blue": 0.3813,
    "carpet": 0.3997,
    "eroded": 0.5148,
    "glossy": 0.4925,
    "granular": 0.4478,
    "marble": 0.6318,
    "medieval": 0.5126,
    "mossy": 0.441,
    "orange": 0.4331,
    "patterned": 0.4547,
    "plain": 0.4052,
    "plastic": 0.4427,
    "soft": 0.5752,
    "stones": 0.4535,
    "subtle": 0.6302,
    "tan": 0.5703,
    "uniform": 0.6302,
    "wooden": 0.5411,
    "beach": 0.6345,
    "brick": 0.4656,
    "clay": 0.3384,
    "cream": 0.6652,
    "debris": 0.4489,
    "earth": 0.4582,
    "grain": 0.4909,
    "hardwood": 0.2244,
    "matte": 0.4912,
    "moss": 0.4703,
    "mud": 0.4603,
    "oxidized": 0.4295,
    "paint": 0.7451,
    "pattern": 0.7349,
    "river": 0.4137,
    "riverbed": 0.4137,
    "roof": 0.3384,
    "roofing": 0.3384,
    "rubble": 0.4489,
    "rust": 0.4295,
    "rusty": 0.4295,
    "sand": 0.6345,
    "soil": 0.4165,
    "square": 0.4935,
    "textile": 0.4568,
    "tiling": 0.3384,
    "wool": 0.4802,
    "woven": 0.4568,
    "yellow": 0.4482,
    "arches": 0.4418,
    "broken": 0.6459,
    "charcoal": 0.3217,
    "classic": 0.6348,
    "cobblestone": 0.4418,
    "corrugated": 0.5078,
    "covered": 0.1542,
    "durable": 0.3931,
    "elegant": 0.4478,
    "fur": 0.5266,
    "golden": 0.4148,
    "irregular": 0.4238,
    "knots": 0.6294,
    "leaves": 0.4181,
    "microfiber": 0.5266,
    "organic": 0.6031,
    "paving": 0.4418,
    "pipe": 0.5078,
    "powder": 0.1542,
    "ribbed": 0.5078,
    "ridged": 0.5078,
    "sandstone": 0.4148,
    "shiny": 0.1372,
    "silver": 0.9832,
    "slightly": 0.6348,
    "softwood": 0.6294,
    "solid": 0.6817,
    "stacked": 0.4238,
    "tree": 0.6662,
    "accumulation": 0.7274,
    "arch": 0.4355,
    "autumn": 0.4438,
    "bark": 0.4788,
    "bright": 0.794,
    "castle": 0.5486,
    "cave": 0.0943,
    "center": 0.3085,
    "christmas": 0.8537,
    "clothing": 0.5555,
    "coastal": 0.7274,
    "cobalt": 0.7594,
    "cobble": 0.4482,
    "construction": 0.533,
    "corroded": 0.2994,
    "cotton": 0.5555,
    "cover": 0.4438,
    "damp": 0.5635,
    "dashed": 0.3085,
    "desert": 0.7274,
    "design": 0.8537,
    "deteriorated": 0.2703,
    "dune": 0.7274,
    "earthy": 0.7274,
    "espresso": 0.214,
    "european": 0.4355,
    "factory": 0.4322,
    "fallen": 0.4438,
    "fragments": 0.4981,
    "furniture": 0.214,
    "gold": 0.8935,
    "grained": 0.4204,
    "grass": 0.5635,
    "gritty": 0.7274,
    "hard": 0.5995,
    "historic": 0.4482,
    "impure": 0.7508,
    "interior": 0.214,
    "lane": 0.3085,
    "large": 0.6099,
    "line": 0.3085,
    "markings": 0.3085,
    "mosaic": 0.4355,
    "mountain": 0.4461,
    "muddy": 0.3925,
    "neutral": 0.533,
    "onyx": 0.7963,
    "ornament": 0.8537,
    "overgrown": 0.5635,
    "patches": 0.3085,
    "path": 0.4981,
    "pathway": 0.4204,
    "pebbles": 0.4384,
    "pedestrian": 0.4355,
    "plaid": 0.5555,
    "plank": 0.4993,
    "plastisol": 0.7921,
    "platinum": 0.7323,
    "printed": 0.7921,
    "random": 0.4665,
    "reflective": 0.2444,
    "rusted": 0.5498,
    "sbsar": 0.3945,
    "smudge": 0.4348,
    "spotted": 0.726,
    "staggered": 0.4993,
    "stitched": 0.1338,
    "stucco": 0.8303,
    "suede": 0.794,
    "surface": 0.8303,
    "travertine": 0.8051,
    "two": 0.3085,
    "veined": 0.6816,
    "wallpaper": 0.8787,
    "windy": 0.7274,
    "woodchip": 0.8787,
    "woodland": 0.5635,
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
    {
        "fabric",
        "stone",
        "metal",
        "wool",
        "carpet",
        "leather",
        "parquet",
        "wood",
        # And a BRICK is a SHAPE and not a colour.
        #
        # The truth's own twelve bricks split by their words: the
        # eight that say "natural, stone" are a warm tan - a hue of
        # 0.40, 0.34, 0.25 - and the one that says "white" is a
        # neutral 0.341, 0.332, 0.326, which is "white"'s own hue
        # to three decimal places.
        #
        # So a brick wears the colour the description gives it, and
        # "bricks" says what KIND of thing it is and not what colour
        # it is - the same rule as a wood and a fabric.
        "brick",
        "bricks",
    }
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
        words = _words_of(description)
        if words & METAL_COATING_WORDS:
            # A COATED metal wears the coat, so the TONE comes first.
            #
            # And the coat's colour is a PAINT's colour, and a paint
            # is a flat SURFACE and not a metal: the coat is read by
            # the general surface rule, the EXTREMES first.
            #
            # The truth's own Metal027 and Metal029 are "black,
            # covered, metal, painted, powder, steel" at lumas of
            # 0.180 and 0.128. The general "black" of 0.06 is a
            # black surface, and the extreme "black" of 0.211 is
            # fitted on the truth's own eighteen black materials -
            # and 0.211 is nearer both of them.
            extreme = [
                EXTREME_VALUES[word] for word in EXTREME_LIGHT_WORDS if word in words
            ]
            if extreme:
                # And a COAT is DARKER than the bare surface it
                # covers: a powder coat is a matte paint and a paint
                # is a flat dielectric, and the truth's own two
                # powder-coated steels measure 0.179 and 0.129
                # against the bare black metal's 0.246.
                return min(extreme) * METAL_COAT_DARKENING
            tone = METAL_COLOUR_TIERS[1]
            for word in tone:
                if word in words:
                    return NAMED_COLOURS.get(word, METAL_COLOURS[word])
        # And a metal names SEVERAL of its own colours, and they are
        # MEANED and not taken in the tier's order.
        #
        # The truth's own Metal009, Metal011 and Metal007 are all
        # "silver, steel" - and the tier's order read "steel" first,
        # which is 0.439, while the truth's own three measure 0.582,
        # 0.627 and 0.611. The mean of "silver" and "steel" is 0.711
        # and the scratches bring it down to 0.569, and that is the
        # truth's within two per cent.
        #
        # Measured over the truth's own twenty metals: the mean
        # relative error is 0.076 against the tier's first-match,
        # and the worst is 0.39 against 0.53.
        # And a weathered metal's DARK colour words are the
        # weathering's own - a rusted plate's "black" is the rust.
        #
        # The truth's own aged plate is "aged, black, brown, dark,
        # fine, glossy, industrial, metal, oxidized, polished, rust,
        # rusty, smooth, steel" at a luma of 0.429, and the mean of
        # its "steel" and its "black" would be 0.343 - so the
        # weathering's own dark words are left out with it.
        weathering = bool(words & METAL_WEATHERING_WORDS)
        named = [
            METAL_COLOURS[word]
            for word in words
            if word in METAL_COLOURS
            and not weathering
            or (
                word in METAL_COLOURS
                and word not in METAL_WEATHERING_COLOURS
                and weathering
            )
        ]
        if named:
            value = sum(named) / len(named)
            # And a SCRATCHED sheet is DARKER: the scratches catch
            # the light and scatter it, and the truth's own
            # Metal038 - a "metal, scratched, steel" at 0.381 - is
            # darker than its own "steel" of 0.439.
            if words & METAL_SCRATCH_WORDS:
                value *= METAL_SCRATCH_DARKENING
            return value
        for tier in METAL_COLOUR_TIERS:
            for word in tier:
                if word in words:
                    return METAL_COLOURS.get(word, NAMED_COLOURS.get(word))
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
    # And a WOOD is never the extreme word's value.
    #
    # The truth's own Wood028 is a "black, brown, clean, dark, fine,
    # smooth, wood" at a luma of 0.135 - a dark BROWN - and the
    # "black" extreme said 0.064.
    #
    # And every one of the truth's own twenty-eight woods is warm and
    # most are dark, so the extreme words are the wrong rule for a
    # wood: the wood's own FINISH says which.
    words = _words_of(description)
    if words & {"wood", "wooden", "timber"}:
        for tier in WOOD_VALUE_TIERS:
            finish_words = [word for word in tier if word in words]
            if not finish_words:
                continue
            own = WOOD_VALUES.get(finish_words[0])
            if own is not None:
                return own
    extreme = [EXTREME_VALUES[word] for word in EXTREME_LIGHT_WORDS if word in words]
    if extreme:
        # And a REFLECTIVE black is a different black, and it is
        # lighter: a black metal mirrors a dark room and a black
        # asphalt is a dark road under a bright sky.
        #
        # The truth's own fifteen blacks split in two: the reflective
        # ones average 0.2499 and the dielectric ones 0.1401, and
        # Plastic006 - a black plastic at 0.030 - read 7.02x the
        # truth's brightness.
        words = _words_of(description)
        if words & EXTREME_REFLECTIVE_WORDS:
            reflective = [
                EXTREME_REFLECTIVE_VALUES[word]
                for word in EXTREME_LIGHT_WORDS
                if word in words and word in EXTREME_REFLECTIVE_VALUES
            ]
            if reflective:
                return min(reflective)
        # And a SMOOTH dielectric black is darker than a textured
        # one: a rough surface catches the light in its own texture
        # and a smooth one has nowhere to catch it.
        smooth = [
            EXTREME_SMOOTH_VALUES[word]
            for word in EXTREME_LIGHT_WORDS
            if word in words and word in EXTREME_SMOOTH_VALUES
        ]
        if smooth and words & EXTREME_SMOOTH_WORDS:
            return min(smooth)
        textured = [
            EXTREME_TEXTURED_VALUES[word]
            for word in EXTREME_LIGHT_WORDS
            if word in words and word in EXTREME_TEXTURED_VALUES
        ]
        if textured:
            return min(textured)
        # And the extreme that points the SAME WAY as the description
        # wins.
        #
        # The rule was "the darkest of them wins", and it is right
        # for a "black, dark" thing. But the truth's own materials
        # never carry a dark word and a light word together - not one
        # of the twenty-nine in the four sets - so the extremes only
        # ever point one way.
        #
        # And when they point the LIGHT way, the BRIGHTEST of them
        # wins: the truth's own Bricks060 is a "brick, bricks,
        # bright, light, wall, white" at a luma of 0.846, and its
        # Travertine009 is a "light, white" at 0.805 - both of them
        # brighter than "white" alone is.
        #
        # Measured over the truth's own: the materials that name
        # "white" and no dark word average 0.735, and the two that
        # name "light" as well are the brightest of them.
        if words & EXTREME_DARK_WORDS:
            return min(extreme)
        return max(extreme)
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

# A METAL's own spread, fitted WITHIN the metals and not over every
# material.
#
# A metal's FINISH is its character - a smooth one is flat and an
# abraded one is not - and the general table cannot say that, because
# "smooth" names thirty-nine materials of which only eight are
# metals, and the other thirty-one carry the general spread of
# 0.0422.
#
# Measured on the truth's own twenty-one metals: "clean" averages
# 0.0075, "smooth" 0.0153, "powder" 0.0174, "fine" and "polished"
# and "glossy" 0.0269, "rough" 0.0637, "corrugated" and "ribbed" and
# "worn" 0.0760, and "rusted" 0.1361.
#
# And the KIND is fitted the same way: "silver" 0.0061, "gold"
# 0.0064, "cobalt" 0.0183, "steel" 0.0354, "iron" 0.0442 and
# "platinum" 0.1435.
METAL_SPREADS: dict[str, float] = {
    "clean": 0.0076,
    "smooth": 0.0106,
    "powder": 0.0174,
    "covered": 0.0154,
    "painted": 0.0154,
    "scratched": 0.0273,
    "bumpy": 0.0273,
    "brushed": 0.0202,
    "fine": 0.0265,
    "polished": 0.0265,
    "glossy": 0.0265,
    "aged": 0.0265,
    "rust": 0.0265,
    "rusty": 0.0265,
    "oxidized": 0.0269,
    "rough": 0.0576,
    "corrugated": 0.0760,
    "ribbed": 0.0760,
    "ridged": 0.0760,
    "worn": 0.0760,
    "pipe": 0.0760,
    "rusted": 0.1361,
    "old": 0.1361,
    "damaged": 0.1398,
    "impure": 0.0390,
    "silver": 0.0220,
    "gold": 0.0164,
    "cobalt": 0.0183,
    "platinum": 0.1426,
    "steel": 0.0294,
    "iron": 0.0451,
    "metal": 0.0341,
}

# And which of the METAL's tiers is the FINISH's, and the rest are
# the structures.
#
# It was the index four, and a new tier was added to the structures
# and the index moved - so the KIND's tier was read before the
# finish's, and a smooth iron read as the iron's spread.
METAL_SPREAD_FINISH_TIER = 5

METAL_SPREAD_TIERS = (
    ("corrugated", "ribbed", "ridged", "pipe"),
    # And a BRUSHED sheet is its own tier: it was in the corrugated
    # one, and the truth's own two brushed metals measure 0.0192 and
    # 0.0213 against the corrugated sheet's 0.0762 - so a brushed
    # sheet's spread read 3.8x the truth's.
    ("brushed", "scratched", "bumpy"),
    (
        "oxidized",
        "aged",
        "rusty",
        "rust",
        "rusted",
        "worn",
        "rough",
        "coarse",
        "matte",
        "damaged",
        "scratched",
        "dirty",
        "impure",
    ),
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

# A LEATHER's FINISH, and its spread, and the tables are fitted on
# the truth's own six leathers.
#
# The truth's own six leathers' spreads run from 0.0032 to 0.0630 - a
# twentyfold range - and the material's own word says 0.0238, which
# is a mean of nothing in particular.
#
# But the FINISH says which one:
#
#     "brown, clean, dark, leather"                  0.0032
#     "black, dark, leather, smooth"                 0.0115
#     "bright, fine, leather, light, rough, suede"   0.0160
#     "brown, fine, leather, orange, smooth"         0.0198
#     "brown, dark, leather"                         0.0279
#     "black, brown, dark, leather, stitched"        0.0630
#
# So the finish decides, and the material's own word decides only
# when no finish is named - the same rule the metal's has.
LEATHER_SPREADS: dict[str, float] = {
    "stitched": 0.0630,
    "seam": 0.0630,
    "quilted": 0.0630,
    "suede": 0.0160,
    "rough": 0.0160,
    "orange": 0.0198,
    "brown": 0.0279,
    "smooth": 0.0115,
    "clean": 0.0032,
    "fine": 0.0160,
    "leather": 0.0238,
    "hide": 0.0238,
}

# The tiers, and the ORDER matters: the specific finishes first.
# A FABRIC's FINISH, and its spread, and the tables are fitted on
# the truth's own thirteen fabrics.
#
# The truth's own fabrics' spreads run from 0.0032 to 0.1986 - a
# sixtyfold range - and the material's own word said 0.1245, a mean
# of nothing in particular.
#
# But the FINISH says which:
#
#     "printed" 0.0032   "soft" 0.0090   "white, wool" 0.0295
#     "clean, smooth" 0.0347   "wool" 0.0508   "weave" 0.0529
#     "grey" 0.0815   "dirty" 0.1134   "rough" 0.1282
#     "checkered" 0.1877
#
# So the finish decides first, and the material's own word decides
# when no finish is named - the same rule the metal's and the
# leather's have.
FABRIC_SPREADS: dict[str, float] = {
    "printed": 0.0032,
    "plastisol": 0.0032,
    "soft": 0.0090,
    "fur": 0.0090,
    "microfiber": 0.0090,
    "white": 0.0295,
    "wool": 0.0508,
    "clean": 0.0347,
    "smooth": 0.0347,
    "weave": 0.0529,
    "woven": 0.0529,
    "grey": 0.0815,
    "gray": 0.0815,
    "dirty": 0.1134,
    "smudge": 0.1134,
    "rough": 0.1282,
    "checkered": 0.1877,
    "chequered": 0.1877,
    "patterned": 0.1877,
    "fabric": 0.0815,
    "cloth": 0.0815,
    "textile": 0.0815,
    "cotton": 0.1877,
}

# The tiers, and the ORDER matters: the specific finishes first.
FABRIC_SPREAD_TIERS = (
    ("printed", "plastisol"),
    ("soft", "fur", "microfiber"),
    ("checkered", "chequered", "patterned", "cotton"),
    ("rough", "dirty", "smudge"),
    ("clean", "smooth"),
    ("wool", "weave", "woven", "white"),
    ("grey", "gray"),
)

# A WOOD's own VALUE, and the tables are fitted on the truth's own
# twenty-eight woods.
#
# The truth's own woods' lumas run from 0.140 to 0.679 and the
# material's own word said 0.6012 - a mean of nothing in particular,
# and the wrong end of it.
#
# But the FINISH says which: the dark ones 0.2351, the espresso one
# 0.2174, the orange ones 0.5357, the light ones 0.5753, the bare
# brown ones 0.3184 and the wood's own mean 0.3966.
#
# And the EXTREME words are the wrong rule for a wood: the truth's
# own Wood028 is a "black, brown, clean, dark, fine, smooth, wood" at
# 0.135 - a dark brown, and the "black" extreme said 0.064.
WOOD_VALUES: dict[str, float] = {
    "espresso": 0.2174,
    "dark": 0.2351,
    "black": 0.2351,
    "brown": 0.3184,
    "fine": 0.3139,
    "parquet": 0.3716,
    "floor": 0.3571,
    "planks": 0.3877,
    "wood": 0.3886,
    "smooth": 0.4094,
    "grain": 0.4190,
    "beige": 0.4988,
    "plank": 0.5053,
    "orange": 0.5357,
    "light": 0.5753,
    "wooden": 0.5338,
    "knots": 0.6328,
}

# The tiers, and the ORDER matters: the finish first, and the
# colour's own value beats a weak finish.
#
# And the ORDER matters, and the COLOUR's tier comes before the
# finish's: the truth's own WoodFloor070 is a "beige, brown, clean,
# floor, hardwood, modern, natural, old, polished, wood" at 0.235, and
# a "beige" finish would have said 0.4988.
#
# Measured on the truth's own twenty-eight woods, the mean error is
# 0.0866 with this order and 0.1487 with the wood's own mean alone.
WOOD_VALUE_TIERS = (
    ("espresso", "dark", "black"),
    ("light", "orange", "beige"),
    ("knots", "grain"),
    ("wooden", "wood"),
    ("fine", "smooth", "plank", "planks", "parquet", "floor"),
)

LEATHER_SPREAD_TIERS = (
    ("stitched", "seam", "quilted"),
    ("suede", "rough", "coarse", "scuffed"),
    # "clean" is a STRONG finish and it beats the colour: the
    # truth's own "brown, clean, dark, leather" measures 0.0032.
    ("clean",),
    # The COLOUR, and it beats a weak finish: the truth's own
    # "brown, fine, leather, orange, smooth" measures 0.0198, and
    # its "smooth" would have said 0.0115.
    #
    # And the colours have their OWN values and not one value
    # between them: the truth's bare "brown, dark, leather" measures
    # 0.0279 and its orange one 0.0198.
    ("orange", "brown", "tan", "red"),
    ("smooth", "polished", "shiny"),
    ("fine",),
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

# How many materials in the wide truth set each SPREAD word names.
#
# The count is the word's SPECIFICITY: the words that name FEW
# materials say exactly how much the surface varies, and the general
# ones are a mean of nothing in particular.
#
# "roof" names three and its spread is 0.0192 - the truth's own
# RoofingTiles012A to within a thousandth - and "tiles" names eleven
# at a mean of 0.0494. So a "clay, roof, roofing, tiles, tiling"
# thing is a ROOF, and reading "tiles" first gave the roof a tile's
# spread: 0.0529 against a truth's 0.0149, three and a half times.
#
# And "leather" names six whose spreads run from 0.0031 to 0.0636 -
# a twentyfold range - while "stitched" names ONE and says exactly.
#
# Fitted against the eighty-seven, the most specific word wins and
# the mean error fell from 0.0151 to 0.0126 and the median from
# 0.0090 to 0.0064. The leave-one-out count gives the same numbers,
# so it is not the fit seeing itself.
SPREAD_SPREAD_WORD_COUNTS: dict[str, int] = {
    "rough": 49,
    "stone": 40,
    "smooth": 39,
    "natural": 35,
    "gray": 33,
    "beige": 28,
    "brown": 27,
    "urban": 24,
    "dark": 23,
    "old": 22,
    "metal": 21,
    "floor": 20,
    "modern": 20,
    "outdoor": 19,
    "black": 18,
    "clean": 18,
    "wood": 18,
    "ground": 17,
    "industrial": 17,
    "tiles": 16,
    "white": 15,
    "bricks": 14,
    "fabric": 14,
    "layered": 14,
    "pavement": 14,
    "rustic": 14,
    "asphalt": 13,
    "damaged": 13,
    "worn": 13,
    "light": 12,
    "polished": 12,
    "road": 12,
    "street": 12,
    "dirt": 11,
    "grey": 11,
    "grid": 11,
    "dirty": 10,
    "aged": 9,
    "concrete": 9,
    "cracked": 8,
    "rectangular": 8,
    "rock": 8,
    "scattered": 8,
    "steel": 8,
    "uneven": 8,
    "wall": 8,
    "fine": 7,
    "green": 7,
    "bathroom": 6,
    "cliff": 6,
    "forest": 6,
    "indoor": 6,
    "iron": 6,
    "leather": 6,
    "parquet": 6,
    "plaster": 6,
    "striped": 6,
    "checkered": 5,
    "cloth": 5,
    "dry": 5,
    "flooring": 5,
    "gravel": 5,
    "kitchen": 5,
    "limestone": 5,
    "minimalist": 5,
    "painted": 5,
    "planks": 5,
    "red": 5,
    "rocky": 5,
    "scratched": 5,
    "stained": 5,
    "blue": 4,
    "carpet": 4,
    "eroded": 4,
    "glossy": 4,
    "granular": 4,
    "marble": 4,
    "medieval": 4,
    "mossy": 4,
    "orange": 4,
    "patterned": 4,
    "plain": 4,
    "plastic": 4,
    "soft": 4,
    "stones": 4,
    "subtle": 4,
    "tan": 4,
    "uniform": 4,
    "wooden": 4,
    "beach": 3,
    "brick": 3,
    "clay": 3,
    "cream": 3,
    "debris": 3,
    "earth": 3,
    "grain": 3,
    "hardwood": 3,
    "matte": 3,
    "moss": 3,
    "mud": 3,
    "oxidized": 3,
    "paint": 3,
    "pattern": 3,
    "river": 3,
    "riverbed": 3,
    "roof": 3,
    "roofing": 3,
    "rubble": 3,
    "rust": 3,
    "rusty": 3,
    "sand": 3,
    "soil": 3,
    "square": 3,
    "textile": 3,
    "tiling": 3,
    "wool": 3,
    "woven": 3,
    "yellow": 3,
    "arches": 2,
    "broken": 2,
    "charcoal": 2,
    "classic": 2,
    "cobblestone": 2,
    "corrugated": 2,
    "covered": 2,
    "durable": 2,
    "elegant": 2,
    "fur": 2,
    "golden": 2,
    "irregular": 2,
    "knots": 2,
    "leaves": 2,
    "microfiber": 2,
    "organic": 2,
    "paving": 2,
    "pipe": 2,
    "powder": 2,
    "ribbed": 2,
    "ridged": 2,
    "sandstone": 2,
    "shiny": 2,
    "silver": 2,
    "slightly": 2,
    "softwood": 2,
    "solid": 2,
    "stacked": 2,
    "tree": 2,
    "accumulation": 1,
    "arch": 1,
    "autumn": 1,
    "bark": 1,
    "bright": 1,
    "castle": 1,
    "cave": 1,
    "center": 1,
    "christmas": 1,
    "clothing": 1,
    "coastal": 1,
    "cobalt": 1,
    "cobble": 1,
    "construction": 1,
    "corroded": 1,
    "cotton": 1,
    "cover": 1,
    "damp": 1,
    "dashed": 1,
    "desert": 1,
    "design": 1,
    "deteriorated": 1,
    "dune": 1,
    "earthy": 1,
    "espresso": 1,
    "european": 1,
    "factory": 1,
    "fallen": 1,
    "fragments": 1,
    "furniture": 1,
    "gold": 1,
    "grained": 1,
    "grass": 1,
    "gritty": 1,
    "hard": 1,
    "historic": 1,
    "impure": 1,
    "interior": 1,
    "lane": 1,
    "large": 1,
    "line": 1,
    "markings": 1,
    "mosaic": 1,
    "mountain": 1,
    "muddy": 1,
    "neutral": 1,
    "onyx": 1,
    "ornament": 1,
    "overgrown": 1,
    "patches": 1,
    "path": 1,
    "pathway": 1,
    "pebbles": 1,
    "pedestrian": 1,
    "plaid": 1,
    "plank": 1,
    "plastisol": 1,
    "platinum": 1,
    "printed": 1,
    "random": 1,
    "reflective": 1,
    "rusted": 1,
    "sbsar": 1,
    "smudge": 1,
    "spotted": 1,
    "staggered": 1,
    "stitched": 1,
    "stucco": 1,
    "suede": 1,
    "surface": 1,
    "travertine": 1,
    "two": 1,
    "veined": 1,
    "wallpaper": 1,
    "windy": 1,
    "woodchip": 1,
    "woodland": 1,
}

METAL_SPREAD_WORD_COUNTS: dict[str, int] = {
    "cobalt": 1,
    "corrugated": 1,
    "gold": 1,
    "iron": 1,
    "oxidized": 1,
    "pipe": 1,
    "ribbed": 1,
    "ridged": 1,
    "rust": 1,
    "rusty": 1,
    "silver": 1,
    "matte": 2,
    "steel": 2,
    "aged": 4,
    "fine": 5,
    "polished": 5,
    "worn": 6,
    "black": 8,
    "metal": 8,
    "grey": 9,
    "clean": 11,
    "gray": 16,
    "smooth": 22,
    "rough": 27,
    "aluminium": 0,
    "aluminum": 0,
    "brass": 0,
    "bronze": 0,
    "brushed": 0,
    "chrome": 0,
    "coarse": 0,
    "copper": 0,
    "mirror": 0,
    "satin": 0,
}


# The METAL's own words are counted with the general ones, because a
# metal's description carries the general words too - and the counts
# are the truth's own for them.
#
# So the general table below holds every word the spread rule reads,
# metal or not. Fitted against the eighty-seven, the merged table
# gives a mean error of 0.0124 and a median of 0.0055, against 0.0134
# and 0.0068 for the metal's own table alone.
SPREAD_SPREAD_WORD_COUNTS.update(
    {
        word: count
        for word, count in METAL_SPREAD_WORD_COUNTS.items()
        if word not in SPREAD_SPREAD_WORD_COUNTS
    }
)

# The words that name a PATTERN and not a texture, and they say
# nothing about how much the surface varies.
#
# A "checkered" thing is a checkerboard and a "grid" thing is a grid,
# and both are a STRUCTURE - the lane draws the pattern from them
# elsewhere. So they are not spread authorities, and the truth's own
# Tiles139 is a "bathroom, beige, checkered, classic, cream, floor,
# grid, kitchen, limestone" at a spread of 0.0546, which is a tile's
# own spread and not the checkerboard's.
SPREAD_PATTERN_WORDS = frozenset({"checkered", "grid"})

# How much each SPREAD word's own materials DISAGREE with each
# other, as the spread of their measured spreads.
#
# A word that names few materials is specific - and a word whose
# materials all agree is a MEASUREMENT. "granular" names two: the
# truth's own Asphalt033 at a spread of 0.0178 and its Gravel043 at
# 0.0856, so the two disagree by 0.0678 and the word says nothing
# about either.
#
# So a MODIFIER whose own materials disagree loses to a MATERIAL
# that agrees. Measured on the truth's own eighty-seven: the mean
# error fell from 0.0126 to 0.0123 and the median from 0.0064 to
# 0.0055, and the limit is stable from 0.02 to 0.06 - so it is not
# the fit seeing itself.
SPREAD_WORD_DISAGREEMENT: dict[str, float] = {
    "aged": 0.0985,
    "aluminium": 0.0,
    "aluminum": 0.0,
    "asphalt": 0.0589,
    "black": 0.0522,
    "brass": 0.0,
    "brick": 0.0,
    "bricks": 0.0118,
    "bronze": 0.0,
    "brushed": 0.0,
    "carpet": 0.0839,
    "checkered": 0.1341,
    "chrome": 0.0,
    "clay": 0.0107,
    "clean": 0.1857,
    "cloth": 0.1393,
    "coarse": 0.0,
    "cobalt": 0.0,
    "concrete": 0.0382,
    "copper": 0.0,
    "corrugated": 0.0,
    "debris": 0.0,
    "dirt": 0.0727,
    "dirty": 0.0918,
    "fabric": 0.1856,
    "fine": 0.0682,
    "fur": 0.0,
    "gold": 0.0,
    "grain": 0.011,
    "granular": 0.0677,
    "gravel": 0.0481,
    "gray": 0.171,
    "grey": 0.0685,
    "grid": 0.0246,
    "ground": 0.0727,
    "hide": 0.0,
    "industrial": 0.0677,
    "iron": 0.0,
    "knots": 0.0,
    "leather": 0.0604,
    "light": 0.0593,
    "limestone": 0.0135,
    "linen": 0.0,
    "matte": 0.0021,
    "metal": 0.0699,
    "microfiber": 0.0,
    "minimalist": 0.0324,
    "mirror": 0.0,
    "modern": 0.0531,
    "moss": 0.0131,
    "mossy": 0.0328,
    "natural": 0.0978,
    "oxidized": 0.0,
    "parquet": 0.0222,
    "pavement": 0.0535,
    "pipe": 0.0,
    "plank": 0.0,
    "planks": 0.0222,
    "plaster": 0.0346,
    "polished": 0.0226,
    "ribbed": 0.0,
    "ridged": 0.0,
    "riverbed": 0.0483,
    "road": 0.0535,
    "rock": 0.0824,
    "rocky": 0.0687,
    "roof": 0.0107,
    "roofing": 0.0107,
    "rough": 0.1163,
    "rubble": 0.0,
    "rug": 0.0,
    "rust": 0.0,
    "rusty": 0.0,
    "sand": 0.0,
    "satin": 0.0,
    "scattered": 0.0687,
    "shingle": 0.0,
    "silver": 0.0,
    "slate": 0.0,
    "smooth": 0.1826,
    "soft": 0.0211,
    "softwood": 0.0,
    "soil": 0.0243,
    "stained": 0.0097,
    "steel": 0.0491,
    "stone": 0.0973,
    "subtle": 0.0005,
    "terracotta": 0.0,
    "textile": 0.0,
    "tile": 0.0,
    "tiles": 0.0604,
    "tiling": 0.0107,
    "timber": 0.0,
    "uneven": 0.0727,
    "uniform": 0.0005,
    "urban": 0.0582,
    "velvet": 0.0,
    "wallpaper": 0.0,
    "weathered": 0.0,
    "weave": 0.0,
    "wood": 0.0368,
    "woodchip": 0.0,
    "wooden": 0.0106,
    "wool": 0.0204,
    "worn": 0.0577,
    "woven": 0.0,
}

# The MATERIAL's own words, and they are the ones that beat an
# unreliable modifier.
SPREAD_MATERIAL_WORDS = frozenset(
    (
        "aged",
        "aluminium",
        "aluminum",
        "asphalt",
        "black",
        "brass",
        "bricks",
        "bronze",
        "brushed",
        "carpet",
        "chrome",
        "clean",
        "cloth",
        "coarse",
        "cobalt",
        "concrete",
        "copper",
        "corrugated",
        "fine",
        "gold",
        "gray",
        "grey",
        "hide",
        "iron",
        "leather",
        "matte",
        "metal",
        "mirror",
        "oxidized",
        "parquet",
        "pavement",
        "pipe",
        "plank",
        "planks",
        "polished",
        "ribbed",
        "ridged",
        "roof",
        "roofing",
        "rough",
        "rug",
        "rust",
        "rusty",
        "satin",
        "shingle",
        "silver",
        "smooth",
        "steel",
        "textile",
        "tiles",
        "tiling",
        "wallpaper",
        "weave",
        "woodchip",
        "worn",
        "woven",
        # And the GROUND's own kinds, which are its material as much
        # as a leather is a leather's.
        #
        # The truth's own Ground109 is a "beige, brown, dirt, dry,
        # ground, mud, natural, pebbles, rocky, rough, scattered" at
        # a spread of 0.0649, and "rocky" - which names three
        # materials whose spreads run from 0.0649 to 0.1337 - said
        # 0.1162. But "soil" is in the description too, and it names
        # three that AGREE - 0.0649, 0.0853 and 0.061 - and it says
        # 0.0704.
        #
        # And the truth's own Gravel043 is a "fine, grained,
        # granular, gravel, gray, ground, industrial, natural,
        # pathway" at a spread of 0.0856, and "granular" - which
        # names two that disagree by 0.0677 - said 0.0404, while
        # "gravel" beside it says 0.1145.
        #
        # So a ground's own kind beats an unreliable modifier, and
        # the mean error fell from 0.0124 to 0.0115.
        "debris",
        "dirt",
        "gravel",
        "ground",
        "rubble",
        "sand",
        "soil",
    )
)

# And the disagreement a modifier must not exceed to be trusted.
SPREAD_DISAGREEMENT_LIMIT = 0.04

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
# The words that name a PATCHWORK of colours, and the patchwork
# varies its hue more than a family does.
#
# A LEAF MAT is a patchwork, and so is a MOSSY ROCK: the truth's own
# Rock064 is a grey stone with green MOSS on it, and its green share
# has a standard deviation of 0.0336 - five times the lane's 0.0019.
#
# And the moss is a PATCH and not a tint: the truth's own ground
# says "forest" and carries stones whose red share varies by 0.0119
# - LESS than the gravel's - and "forest" is where the leaves are and
# not a mat of them. So "forest" is NOT a patchwork word and "moss"
# is.
HUE_VARIATION_TIERS = (
    ("leaves", "fallen", "autumn", "foliage"),
    ("moss", "mossy", "lichen", "lichen"),
)


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
    "scratches": 0.6,
    "eroded": 0.5,
    "worn": 0.35,
    "abraded": 0.5,
    "scuffed": 0.4,
    "scratch": 0.6,
    # And the truth's own metals say "bumpy" and "brushed" and
    # "scratches", and the words were not in the table - so a
    # scratched sheet's scratches were not drawn at all.
    "bumpy": 0.45,
    "brushed": 0.4,
    "bump": 0.45,
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
    #
    # And the tile's drift is 0.20, and not the 0.85 it was: the
    # drift is the stain, and the stain's SHARE of the surface's
    # variation is what the measure reads.
    #
    # At 0.85 the tile's autocorrelation stayed at +0.88 at a
    # thirty-two-pixel lag and +0.45 at a two-hundred-and-fifty-six
    # one, and the feature measure read 4.8 features across against
    # the truth's 9.8 - because the drift is a SLOW field and it
    # swamped the grid.
    #
    # The truth's own Tiles141 reads +0.192 at a thirty-two-pixel
    # lag and crosses zero at a hundred and twenty-eight, and it
    # measures 9.8 features across. At 0.20 the lane reads 9.0.
    "tiles": 0.20,
    "tile": 0.20,
    "ceramic": 0.20,
    "porcelain": 0.20,
    "plaster": 0.30,
    "concrete": 0.25,
    "bricks": 0.05,
    "brick": 0.05,
    "stone": 0.12,
    "rock": 0.08,
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
    "wool": (0.4544, 0.3097, 0.2359),
    "fabric": (0.347, 0.326, 0.327),
    "wood": (0.4582, 0.3326, 0.2092),
    "ground": (0.3927, 0.3452, 0.2621),
    "scattered": (0.397, 0.342, 0.261),
    "rocky": (0.381, 0.340, 0.278),
    "gravel": (0.370, 0.339, 0.291),
    "dirt": (0.388, 0.340, 0.272),
    "pavement": (0.348, 0.339, 0.313),
    "asphalt": (0.344, 0.338, 0.318),
    "tiles": (0.391, 0.328, 0.282),
    "soil": (0.400, 0.341, 0.259),
    "mud": (0.401, 0.342, 0.256),
    "moss": (0.3936, 0.3737, 0.2327),
    "rock": (0.351, 0.359, 0.289),
    "mossy": (0.4133, 0.3852, 0.2015),
    "earth": (0.401, 0.353, 0.246),
    "leaves": (0.437, 0.345, 0.217),
    "limestone": (0.393, 0.334, 0.273),
    "steel": (0.336, 0.334, 0.329),
    "metal": (0.338, 0.336, 0.325),
    "wooden": (0.4585, 0.3265, 0.2149),
    "parquet": (0.496, 0.338, 0.165),
    "plank": (0.417, 0.331, 0.252),
    "concrete": (0.3496, 0.3377, 0.3127),
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


# How many materials in the wide truth set each HUE word names, and
# the count is the word's SPECIFICITY.
#
# The words that name FEW materials say exactly what colour they are,
# and the general ones are a mean of nothing in particular.
#
# Measured on the truth's own: the truth's ScatteredLeaves009 is an
# "autumn, brown, cover, dry, fallen, forest, green, ground, leaves,
# natural, rough, scattered, uneven" and its hue is 0.466, 0.353,
# 0.181 - the hue of LEAVES - and "ground" is the first material word
# the description names and it says 0.389, 0.343, 0.267.
MATERIAL_WORD_COUNTS: dict[str, int] = {
    "asphalt": 7,
    "beige": 14,
    "black": 8,
    "blue": 3,
    "bricks": 8,
    "bright": 1,
    "brown": 16,
    "carpet": 4,
    "charcoal": 1,
    "clay": 3,
    "cloth": 4,
    "cobalt": 1,
    "concrete": 6,
    "cream": 2,
    "dark": 15,
    "dirt": 5,
    "earth": 3,
    "espresso": 1,
    "fabric": 10,
    "gold": 1,
    "grass": 1,
    "gravel": 3,
    "gray": 16,
    "green": 4,
    "grey": 9,
    "ground": 9,
    "iron": 1,
    "leather": 6,
    "leaves": 2,
    "light": 6,
    "limestone": 3,
    "marble": 0,
    "metal": 8,
    "moss": 2,
    "mossy": 2,
    "mud": 2,
    "natural": 20,
    "orange": 3,
    "paint": 2,
    "parquet": 5,
    "pavement": 7,
    "pink": 0,
    "plank": 1,
    "planks": 4,
    "plaster": 4,
    "purple": 0,
    "red": 1,
    "rock": 6,
    "rocky": 3,
    "roof": 3,
    "roofing": 3,
    "rust": 1,
    "rusty": 1,
    "sand": 0,
    "sandstone": 1,
    "scattered": 5,
    "silver": 1,
    "soil": 3,
    "steel": 2,
    "stone": 23,
    "stucco": 1,
    "tan": 2,
    "textile": 1,
    "tiles": 11,
    "wallpaper": 1,
    "white": 8,
    "wood": 11,
    "woodchip": 1,
    "wooden": 2,
    "wool": 2,
    "woven": 1,
    "yellow": 2,
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
    #
    # And the material's word is the MOST SPECIFIC of them, and not
    # the first the description names - the same rule the spread
    # reads by.
    #
    # The truth's own ScatteredLeaves009 is an "autumn, brown, cover,
    # dry, fallen, forest, green, ground, leaves, natural, rough,
    # scattered, uneven" and its hue is 0.466, 0.353, 0.181 - a warm
    # brown, the hue of LEAVES. And "ground" is the first material
    # word the description names, and it says 0.389, 0.343, 0.267.
    #
    # And "leaves" names two materials and "ground" names nine, so
    # the leaves' hue is the more specific and the more right.
    #
    # Measured on the truth's own eighty-seven, the mean hue error
    # fell from 0.0747 to 0.0724 and the median from 0.0386 to
    # 0.0317.
    named = [
        word.strip(".,")
        for word in words
        if MATERIAL_HUES.get(word.strip(".,")) is not None
        and word.strip(".,") not in GENERIC_MATERIALS
    ]
    # And a COLOUR word beats the material's word when it names
    # FEWER materials - the same specificity rule, read across the
    # two tables.
    #
    # The truth's own Tiles141 is a "bathroom, beige, dirty, floor,
    # grid, kitchen, rectangular, rough, stained, stone, tiles, urban,
    # white" and its hue is 0.347, 0.333, 0.320 - a near neutral.
    # And "tiles" names eleven materials at a mean of 0.395, 0.326,
    # 0.279, and "white" names eight at 0.342, 0.337, 0.321.
    #
    # So the white tile is white and not a tan tile, and the more
    # specific colour says so.
    #
    # Measured on the truth's own eighty-seven, the mean hue error
    # fell from 0.0552 to 0.0513, the median from 0.0365 to 0.0300,
    # and the worst from 0.3399 to 0.2763.
    colours = [
        word.strip(".,") for word in words if HUES.get(word.strip(".,")) is not None
    ]
    # And a WOOD is never the colour word's hue.
    #
    # A wood is always WARM: every one of the truth's own twenty-seven
    # woods is warmer in red than in blue, from +0.074 on the darkest
    # to +0.530 on the orange one - and the truth's own Wood028 is a
    # "black, brown, clean, dark, fine, smooth, wood" at +0.088, a
    # dark BROWN and not a black.
    #
    # So the "black" word beat the "wood" one on specificity - black
    # names eighteen materials and wood twenty-seven - and the wood
    # came out a neutral grey, which no wood in the truth's own is.
    #
    # So a wood's hue is its own material's hue, and the colour word
    # is the fallback.
    if "wood" in words or "wooden" in words:
        return MATERIAL_HUES["wood"]
    if colours and named:
        colour_counts = min(MATERIAL_WORD_COUNTS.get(word, 99) for word in colours)
        material_counts = min(MATERIAL_WORD_COUNTS.get(word, 99) for word in named)
        if colour_counts < material_counts:
            colours.sort(key=lambda word: (MATERIAL_WORD_COUNTS.get(word, 99), word))
            return HUES[colours[0]]
    if named:
        named.sort(key=lambda word: (MATERIAL_WORD_COUNTS.get(word, 99), word))
        return MATERIAL_HUES[named[0]]
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
    # The words that name a SPREAD, and the most specific of them
    # wins.
    #
    # A word that names FEW materials says exactly how much the
    # surface varies, and a word that names many is a mean of nothing
    # in particular. "roof" names three and its spread is 0.0192 -
    # the truth's own RoofingTiles012A to within a thousandth - and
    # "tiles" names eleven at a mean of 0.0494, so a "clay, roof,
    # roofing, tiles, tiling" thing is a ROOF.
    #
    # And the words that name a PATTERN and not a texture are not
    # authorities at all: a "checkered" thing is a checkerboard and a
    # "grid" thing is a grid, and the lane draws the pattern from
    # them elsewhere.
    #
    # Fitted against the truth's own eighty-seven, the mean error
    # fell from 0.0151 to 0.0126 and the median from 0.0090 to
    # 0.0064. The leave-one-out count gives the same numbers, so it
    # is not the fit seeing itself.
    #
    # And the METAL's words are in the same table, because a metal's
    # description carries the general words too - a "corrugated, dark,
    # gray, industrial, metal, pipe, ribbed, ridged, steel" says
    # "gray" and "industrial" as well as its own words, and the
    # general counts are the truth's own for them.
    named = [
        word
        for word in words
        if word in SPREAD_SPREAD_WORD_COUNTS and word not in SPREAD_PATTERN_WORDS
    ]
    # A METAL's own spread is fitted WITHIN the metals, and the
    # general table cannot say it.
    #
    # "smooth" names thirty-nine materials and only eight of them are
    # metals, and the general spread of 0.0422 is the other
    # thirty-one. A metal's FINISH is its character - a smooth one is
    # flat and an abraded one is not.
    #
    # The truth's own Metal052A is an "iron, metal, smooth" at a
    # spread of 0.0105, and "iron" alone averages 0.0442 over six
    # metals whose spreads run from 0.0105 to 0.1361.
    #
    # Measured on the truth's own twenty-one metals, the metal's own
    # table gives a mean error of 0.0117 against the general table's
    # 0.0190.
    if is_metal(description):
        # The FINISH decides first, and the kind second.
        #
        # A metal's finish is its character - a smooth one is flat
        # and an abraded one is not - and the truth's own Metal052A is
        # an "iron, metal, smooth" at a spread of 0.0105 while "iron"
        # alone averages 0.0442 over six metals whose spreads run from
        # 0.0105 to 0.1361.
        #
        # So the finish's tier is read before the kind's, and the
        # kind decides only when no finish is named.
        # And the tiers are read by ROLE and not by index: the
        # finish's tier is METAL_SPREAD_FINISH_TIER and the rest are
        # the structures, and a new tier was added to the structures
        # and the index silently moved - so the KIND's tier was read
        # before the finish's and a smooth iron read as the iron's
        # spread and not the smooth one's.
        for tier in (
            METAL_SPREAD_TIERS[METAL_SPREAD_FINISH_TIER],
            *(
                tier
                for i, tier in enumerate(METAL_SPREAD_TIERS)
                if i != METAL_SPREAD_FINISH_TIER
            ),
        ):
            metal_words = [word for word in tier if word in words]
            if not metal_words:
                continue
            metal_words.sort(
                key=lambda word: (METAL_SPECIFICITY.get(word, 99), tier.index(word))
            )
            own = METAL_SPREADS.get(metal_words[0])
            if own is not None:
                return own
    if words & {"fabric", "cloth", "textile", "woven", "weave", "wool"}:
        # A FABRIC's FINISH is its character, the same way a metal's
        # and a leather's are.
        #
        # The truth's own thirteen fabrics' spreads run from 0.0032 to
        # 0.1986 - a sixtyfold range - and the material's own word
        # said 0.1245, a mean of nothing in particular.
        for tier in FABRIC_SPREAD_TIERS:
            finish_words = [word for word in tier if word in words]
            if not finish_words:
                continue
            own = FABRIC_SPREADS.get(finish_words[0])
            if own is not None:
                return own
    if "leather" in words or "hide" in words:
        # A LEATHER's FINISH is its character, the same way a metal's
        # is.
        #
        # The truth's own six leathers' spreads run from 0.0032 to
        # 0.0630 - a twentyfold range - and the material's own word
        # says 0.0238, a mean of nothing in particular.
        #
        # But the FINISH says which: the clean leather is 0.0032, the
        # smooth ones 0.0115 and 0.0198, the suede 0.0160, the
        # stitched 0.0630, and the bare one 0.0279.
        #
        # So the finish decides first, and the material's own word
        # decides when no finish is named.
        for tier in LEATHER_SPREAD_TIERS:
            finish_words = [word for word in tier if word in words]
            if not finish_words:
                continue
            own = LEATHER_SPREADS.get(finish_words[0])
            if own is not None:
                return own
    if named:
        named.sort(key=lambda word: (SPREAD_SPREAD_WORD_COUNTS.get(word, 99), word))
        best = named[0]
        # And a MODIFIER whose own materials DISAGREE loses to a
        # MATERIAL that agrees.
        #
        # "granular" names two materials and the two disagree: the
        # truth's own Asphalt033 at a spread of 0.0178 and its
        # Gravel043 at 0.0856. So the word says nothing about
        # either, and the "asphalt" beside it says 0.0178.
        if best not in SPREAD_MATERIAL_WORDS and (
            SPREAD_WORD_DISAGREEMENT.get(best, 0.0) > SPREAD_DISAGREEMENT_LIMIT
        ):
            materials = [word for word in named if word in SPREAD_MATERIAL_WORDS]
            if materials:
                materials.sort(
                    key=lambda word: (
                        SPREAD_WORD_DISAGREEMENT.get(word, 0.0),
                        SPREAD_SPREAD_WORD_COUNTS.get(word, 99),
                    )
                )
                if SPREAD_WORD_DISAGREEMENT.get(
                    materials[0], 0.0
                ) < SPREAD_WORD_DISAGREEMENT.get(best, 0.0):
                    return _spread_of(materials[0])
        return _spread_of(best)
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
    # And a BRUSHED sheet's streaks run along the sheet.
    #
    # The truth's own brushed steel and silver both have their
    # high-frequency structure HORIZONTAL - a down period of four to
    # ten pixels against an across period of twenty-three to a
    # hundred and sixty-four - and the measure reads along a row, so
    # a sheet whose grain runs along the row is the sheet whose
    # streaks the measure sees.
    #
    # Measured, a brushed sheet's scale error was 4.63 with the
    # streaks across the row and 3.49 with them along it.
    words = set(description.lower().replace(",", " ").split())
    return bool(
        words & {"corrugated", "ribbed", "ridged", "striped", "pipe", "brushed"}
    )


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


def _is_rock(description: str) -> bool:
    """Whether the description names a ROCK and not a surface.

    A rock's joint is a CRACK - a shadow, and the ramp's own floor -
    and a cobble's joint is a filled one: pale sand between the
    stones.

    Measured on the truth's own: the truth's Rock064's cracks read a
    luma of 0.336 where its ramp's dark end is 0.324, and the truth's
    own Asphalt033's reads 0.302 where its value is 0.321.
    """
    words = set(description.lower().replace(",", " ").split())
    return bool(words & {"rock", "cliff", "boulder", "stone", "canyon"})


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
    # A ROCK's joint is a CRACK and not a filled one, and a crack is
    # a SHADOW: it is the ramp's own DARK end and not a third of the
    # spread below the value.
    #
    # Measured on the truth's own: the truth's Rock064's cracks read
    # a luma of 0.336 where the surface's value is 0.420 and its
    # ramp's dark end is 0.324 - so the crack is the ramp's floor.
    # And the truth's own Bricks113A's mortar reads 0.427 where its
    # value is 0.460 - so a BRICK's grout is a filled joint just below
    # the surface, and it is not a crack.
    #
    # At a joint just below the value the rock came out as a mosaic
    # of flat cells with PALE edges - the opposite of a crack.
    if path == "voronoi" and _is_rock(description):
        mortar = low
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
