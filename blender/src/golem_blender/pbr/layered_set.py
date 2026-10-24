"""A LAYERED texture set: a base material with others laid over it, written as one set.

Each material - the base and every layer - is made from its DESCRIPTION
through the same two calls the benchmark scores (the pattern and the
palette), so a layer is the lane's own best guess at that material and
not a flat tint. The materials are then composed under masks
(`pbr.layers`, Material Maker's `blend2`), and the result is written as
the lane's own set: `T_<Name>_BaseColor.png`, `T_<Name>_ORM.png` (AO,
roughness, metallic) and `T_<Name>_Normal.png`.

A layer's mask is built from up to three sources, combined as the
layer asks:

- ``height``: where the surface built so far is low (moss and dirt in
  a wall's joints) or high (dust and wear on the tops);
- ``noise``: patches covering a share of the surface;
- ``cavity``: where the surface is lower than its neighbourhood (rust
  in dents and scratches).

Every material is tileable and every mask is periodic, so the set
tiles. A JOINTED material's height (a brick wall, a paving, a parquet, a
roof) is its pattern's own joint field, so a layer laid in the joints
lands in the joints whatever each piece's tone; every other
material's height is its own relief, related to its colour and skewed as
its kind's truths are (_relief_height).

The written HEIGHT map is a displacement map, and its RANGE follows the
set's kind: the truths' own displacement maps do not all span 0..1 (a
metal's spans a tenth of the surface, a rubble's two thirds), and a
displacement shader reads the map's values as depth, so one fixed range
gave every material the same relief (KIND_HEIGHT_RANGE). The NORMAL map
is not affected - it is scaled to the kind's measured tilt.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# How much a material's luma is smoothed before it is read as height.
HEIGHT_BLUR_PX = 2
# A non-jointed kind's HEIGHT: its correlation with the albedo's luma and
# its skew, the medians of the kind's truths over the four sets (kinds
# with three or more): the truths' displacement is nearly independent of
# their colour.
KIND_HEIGHT = {
    "flat": (-0.06, -0.31),
    # A grain's and a marble's height FOLLOW their lines - the truths' own
    # median |r| is 0.58 and 0.65 - but which way splits (ten woods' dark
    # lines stand proud and eight's are sunk); the median r of -0.13 drew a
    # relief unrelated to the grain (Wood048, looked at). So the majority's
    # sign at the median strength.
    "grain": (-0.58, -0.08),
    "metal": (0.04, -0.02),
    "scattered": (0.20, 0.41),
    "woven": (0.23, 0.11),
    "knit": (0.23, 0.11),
    "asphalt": (0.01, -1.30),
    "rock": (-0.03, -0.51),
    "leather": (-0.10, -0.52),
    "marble": (0.65, -1.49),
    "carpet": (0.72, -0.16),
    "markings": (0.71, 2.47),
    "grass": (0.21, 0.51),
}
DEFAULT_HEIGHT = (0.0, -0.3)
# A kind's DISPLACEMENT RANGE: the lowest and highest value its truths'
# own displacement map carries, so the written Height spans what the
# material's displacement does and a parallax or a displacement shader
# gets the DEPTH the material actually has. It was always 0..1, which
# gave a sheet of steel the relief of a gravel: measured on the
# `ambientcg` set, our written height spanned 0.52-0.99 for every kind
# while its truths span 0.00 for a flat steel (Metal049A) to 0.86 for a
# pressed sheet (CorrugatedSteel009).
#
# Measured over all four truth sets (159 distinct materials, each asset's
# own `displacement.png`/`.jpg` at the 1st and 99th percentile so one
# blown pixel cannot set the range): the MEDIAN of each kind's own
# (p1, p99), and the kind is the one `pattern_for_description` assigns
# the asset's tags. A kind with fewer than HEIGHT_RANGE_MINIMUM_TRUTHS
# truths is not fitted - its own two or three assets would say more
# about them than about the kind - and falls back to 0..1
# (DEFAULT_HEIGHT_RANGE), which is also reported so a consumer can tell
# a measurement from a fallback.
KIND_HEIGHT_RANGE: dict[str, tuple[float, float]] = {
    "asphalt": (0.495, 0.764),
    "brick": (0.205, 0.830),  # walls and tile floors: the same kind here
    "carpet": (0.276, 0.741),
    "flat": (0.408, 0.820),
    "grain": (0.294, 0.678),
    "grass": (0.122, 0.737),
    "leather": (0.206, 0.814),
    "marble": (0.537, 0.976),
    "markings": (0.314, 0.859),
    "metal": (0.435, 0.571),  # the flattest kind
    "parquet": (0.506, 0.918),
    "rock": (0.159, 0.916),  # the widest
    "roof": (0.259, 0.937),
    "scattered": (0.216, 0.749),
    "woven": (0.188, 0.698),
}
# How many truths each fitted range was measured over, so a range is
# never used on fewer than HEIGHT_RANGE_MINIMUM_TRUTHS and the counts
# are checkable against the truth sets rather than living in a comment.
KIND_HEIGHT_RANGE_TRUTHS: dict[str, int] = {
    "asphalt": 8,
    "brick": 24,
    "carpet": 4,
    "flat": 21,
    "grain": 18,
    "grass": 3,
    "leather": 6,
    "marble": 5,
    "markings": 3,
    "metal": 18,
    "parquet": 9,
    "rock": 7,
    "roof": 3,
    "scattered": 11,
    "woven": 7,
}
# A kind with no fitted range - banded, bark, fan, knit, moss, voronoi,
# wallpaper (one or two truths each) - keeps the old 0..1.
DEFAULT_HEIGHT_RANGE = (0.0, 1.0)
# The least truths a kind needs before its range is a measurement of the
# KIND and not of the two assets that happen to be in it.
HEIGHT_RANGE_MINIMUM_TRUTHS = 3
# The independent relief: a feature spans this many sigmas of its broad
# grain, and the broad grain's share of the relief (the rest a quarter of
# its size).
RELIEF_FEATURE_SIGMAS = 3.3
RELIEF_BROAD_SHARE = 0.7
# A set's AMBIENT OCCLUSION: its mean and its spread by kind, the medians
# of the truths that ship an AO (kinds with three or more), and the cavity
# radius it is read from.
KIND_AO = {
    "brick": (0.857, 0.099),
    "scattered": (0.858, 0.096),
    "flat": (0.930, 0.039),
    "asphalt": (0.814, 0.056),
    "woven": (0.789, 0.050),
    "parquet": (0.983, 0.030),
    "rock": (0.914, 0.073),
    "roof": (0.810, 0.117),
}
DEFAULT_AO = (0.882, 0.082)
AO_CAVITY_PX = 6
# A kind's SURFACE, measured on the truths' own maps across the four
# sets (159 materials, the median of each kind): how far its normals tilt
# from flat (mean degrees), how much its roughness varies (standard
# deviation), how its roughness follows its albedo's luma (the
# correlation - a lighter grain is rougher, a lighter metal smoother) and
# how it follows the truth's own HEIGHT (its displacement map): mostly
# negatively, the joints, grooves and pits the roughest - a leather -0.86,
# a wood -0.64, a brick -0.36 - and a roof's and a moss's tops the
# roughest. The height correlation is the stronger (median |r| 0.48
# against the luma's 0.37), and without it the roughness had no structure:
# a brick wall's mortar was no rougher than its bricks (looked at).
#
# One fixed normal strength gave a polished marble 9.5 degrees of relief
# against the truths' 0.4, a metal 12.2 against 1.9 and a roof 9.9
# against 22.8; and a constant roughness gave every map a spread of zero
# where the truths' run from 0.015 to 0.076.
KIND_SURFACE: dict[str, tuple[float, float, float, float]] = {
    "brick": (8.5, 0.061, 0.02, -0.36),
    "flat": (5.4, 0.037, 0.05, -0.13),
    "grain": (5.3, 0.042, 0.26, -0.64),
    "metal": (0.7, 0.031, -0.20, 0.0),
    "voronoi": (8.9, 0.059, 0.03, -0.24),
    "fan": (8.9, 0.059, 0.03, -0.24),
    # The truth's own Bark015.
    # A knit's measured surface is a weave's (two knits, too few to fit).
    "knit": (15.7, 0.032, 0.0, -0.44),
    "bark": (16.0, 0.044, -0.15, -0.58),
    "scattered": (13.0, 0.075, 0.10, -0.25),
    "woven": (15.7, 0.032, 0.0, -0.44),
    "rock": (16.9, 0.065, 0.24, -0.35),
    "parquet": (2.6, 0.026, -0.21, -0.49),
    "herringbone": (2.6, 0.026, -0.21, -0.49),
    "marble": (0.4, 0.018, -0.17, -0.27),
    # A banded stone is polished like a marble.
    "banded": (0.4, 0.018, -0.17, -0.27),
    "leather": (4.4, 0.050, 0.17, -0.86),
    "carpet": (19.2, 0.041, -0.49, -0.89),
    "grass": (20.7, 0.076, 0.06, 0.48),
    "wallpaper": (5.0, 0.015, -0.02, -0.3),
    "roof": (21.4, 0.076, 0.28, 0.76),
    "markings": (4.1, 0.056, -0.72, -0.54),
    "moss": (29.1, 0.054, 0.49, 0.76),
    # The truths' ten asphalts and roads (Road007, painted, apart).
    "asphalt": (9.3, 0.059, 0.03, -0.20),
}
DEFAULT_SURFACE = (8.0, 0.045, 0.0, -0.3)
# A TILE floor (the brick kind, unstaggered) is flat where a brick wall
# is not: the truths' own eleven tiles tilt 1.0 degree (median) against
# fourteen brick walls' 8.5; their grout is the roughest part (luma -0.66,
# height -0.35: Tiles107's grout rough around a glossy glaze).
TILE_SURFACE = (1.0, 0.055, -0.66, -0.35)
# A SMOOTH finish is flatter than its kind: the truths' 52 descriptions
# with a smooth word tilt 0.68x their kind's median. Where a kind has
# three truths or more on each side, its own two medians (smooth, other) -
# a smooth wood tilts 2.9 degrees and a rough one 16.0.
SMOOTH_WORDS = frozenset(
    ("smooth", "polished", "glossy", "shiny", "clean", "reflective", "plain")
)
SMOOTH_NORMAL_RATIO = 0.68
KIND_SMOOTH_NORMAL: dict[str, tuple[float, float]] = {
    "grain": (2.9, 16.0),
    "flat": (4.6, 5.8),
    "metal": (0.4, 0.9),
    "parquet": (1.2, 3.3),
    "herringbone": (1.2, 3.3),
    "woven": (9.6, 15.8),
}
# A PRESSED metal is ribbed relief, not a flat sheet: the truth's own
# CorrugatedSteel009 tilts 20.7 degrees where the smooth metals tilt 0.7.
PRESSED_METAL_NORMAL_DEG = 20.7
PRESSED_METAL_WORDS = frozenset(("corrugated", "ribbed", "ridged", "pipe"))
# A SMOOTH PLASTIC is moulded glass-smooth: the truths' own smooth plastics
# (Plastic010, Plastic006) tilt 0.5 and 0.7 degrees, where a smooth flat
# sheet's median is 4.6 - and their textured plastics 4.4.
PLASTIC_WORDS = frozenset(
    ("plastic", "acrylic", "vinyl", "pvc", "melamine", "laminate")
)
SMOOTH_PLASTIC_NORMAL_DEG = 0.6
# A jointed piece rises out of its joint over this share of its own
# half-width, and keeps this much of a dome on its flat top.
JOINT_BEVEL = 0.25
JOINT_DOME = 0.1
# The roughness's own grain, where it does not follow the albedo.
ROUGHNESS_GRAIN_PX = 3.0
# What the mask may be built from, and how masks combine.
MASK_SOURCES = ("height", "noise", "cavity")
MASK_COMBINE_MODES = ("multiply", "max")


# OVERLAYS a description can name on a base material, and how each is laid.
#
# The truths' own mossy rocks (Rock063, Rock064) are grey rock with moss in
# its hollows and joints, and their rusted metals (Metal053C, Metal063) are
# a sheet with rust in patches - and one pattern for the whole description
# drew a uniform olive rock ("green" tinted every stone) and a grey metal
# with white blobs. So the overlay's words leave the base's description
# (with the colour they bring) and become a layer of their own.
#
# Moss lies LOW, within broad patches; rust lies in patches with hard
# edges, heavy only where the words say the metal is RUSTED or DAMAGED -
# the truth's own Metal063 says "rust, rusty" of a polished steel with
# faint stains.
MOSS_WORDS = frozenset(("moss", "mossy", "lichen", "overgrown"))
MOSS_COLOUR_WORDS = frozenset(("green",))
RUST_WORDS = frozenset(("rust", "rusty", "rusted", "corroded", "oxidized"))
HEAVY_RUST_WORDS = frozenset(("rusted", "damaged", "corroded", "weathered"))
MOSS_LAYER = {
    "description": "green moss, mossy",
    "mask": {
        "height": {"level": 0.55, "below": True, "softness": 0.3},
        "noise": {"cells": 5, "coverage": 0.7, "softness": 0.25, "seed": 3},
        "combine": "multiply",
    },
    "amount": 0.9,
    "thickness": 0.08,
}
# Rust in patches with hard edges, a dozen across. Heavy rust takes about
# half the sheet; light rust is faint stains. (Cut by the metal's own
# cavities the patches became a worm maze, and "bright" moss turned beige -
# looked at.)
RUST_HEAVY = {"coverage": 0.45, "amount": 1.0}
RUST_LIGHT = {"coverage": 0.12, "amount": 0.4}


def compose_from_description(base: dict) -> tuple[dict, list[dict]]:
    """The base and the layers a description's own words call for.

    A base that names no overlay - or whose overlay IS the material (a
    moss, a grass), or rust on something that is not a metal - is itself
    and no layers.
    """
    from golem_blender.pbr.material import is_metal
    from golem_blender.pbr.patterns import pattern_for_description

    description = str(base.get("description", ""))
    words = [word.strip(".,") for word in description.lower().replace(",", " ").split()]
    present = set(words)
    layers: list[dict] = []
    strip: set[str] = set()
    if present & MOSS_WORDS:
        rest = [word for word in words if word not in MOSS_WORDS | MOSS_COLOUR_WORDS]
        if rest and pattern_for_description(", ".join(rest)) not in ("moss", "grass"):
            strip |= MOSS_WORDS | MOSS_COLOUR_WORDS
            layers.append(dict(MOSS_LAYER))
    if present & RUST_WORDS:
        rest = [word for word in words if word not in RUST_WORDS]
        if rest and is_metal(", ".join(rest)):
            strip |= RUST_WORDS
            weight = RUST_HEAVY if present & HEAVY_RUST_WORDS else RUST_LIGHT
            layers.append(
                {
                    "description": "dark orange brown rust, rusty, rough",
                    "mask": {
                        "noise": {
                            "cells": 12,
                            "coverage": weight["coverage"],
                            "softness": 0.05,
                            "seed": 5,
                        }
                    },
                    "amount": weight["amount"],
                    "thickness": 0.04,
                }
            )
    if not layers:
        return base, []
    composed = dict(base)
    composed["description"] = ", ".join(word for word in words if word not in strip)
    if not base.get("kind"):
        composed["kind"] = pattern_for_description(composed["description"])
    return composed, layers


class LayerSpecError(ValueError):
    """A layer's specification cannot be built; the message names the field."""


def height_range_for(kind: str) -> tuple[float, float]:
    """The displacement range the written Height map spans for `kind`.

    A kind measured over HEIGHT_RANGE_MINIMUM_TRUTHS or more truths gets
    its own range; every other kind - an unknown one, or one with too
    few truths to fit - gets 0..1, the forcing this replaced, so the
    caller can always read the map the same way and
    ``height_range_is_measured`` says which it got.
    """
    if not height_range_is_measured(kind):
        return DEFAULT_HEIGHT_RANGE
    return KIND_HEIGHT_RANGE[kind]


def height_range_is_measured(kind: str) -> bool:
    """Whether `kind`'s displacement range is fitted from enough truths."""
    if kind not in KIND_HEIGHT_RANGE:
        return False
    return KIND_HEIGHT_RANGE_TRUTHS.get(kind, 0) >= HEIGHT_RANGE_MINIMUM_TRUTHS


def _height_in_range(height, kind: str):
    """The 0..1 height placed in `kind`'s measured displacement range.

    The height arrives normalised (``_relief_height`` and the joint
    field both return 0..1), and a displacement shader reads the MAP's
    own values as depth: a steel sheet whose truths span 0.135 must be
    written narrower than a rubble whose truths span 0.757, or every
    material is given the same depth. The normal map is NOT made from
    this - it is scaled by the kind's measured tilt instead, so the
    relief's angle is unchanged by the range.
    """
    low, high = height_range_for(kind)
    return low + (high - low) * height


def _height_range_source(kind: str) -> str:
    """Where the kind's displacement range came from, for the set's metadata."""
    if height_range_is_measured(kind):
        return (
            f"the median of {kind}'s own truths' displacement maps at their 1st "
            "and 99th percentile, over the four benchmark sets "
            "(ambientcg, ambientcg_wide, ambientcg_popular, ambientcg_top)"
        )
    return (
        f"no fitted range for {kind!r} (fewer than "
        f"{HEIGHT_RANGE_MINIMUM_TRUTHS} truths), so the height keeps 0..1"
    )


def _material_maps(
    description: str,
    kind: str,
    scale_cells: float,
    resolution: int,
    scratch_dir: Path,
    name: str,
):
    """One material's maps, made from its description."""
    import numpy

    from golem_blender.ops._image_loading import load_image
    from golem_blender.pbr import layers
    from golem_blender.pbr.material import is_metal
    from golem_blender.pbr.palette import palette_for_description
    from golem_blender.pbr.patterns import pattern_for_description
    from golem_blender.pbr.procedural import write_procedural_base_color

    if not description.strip():
        raise LayerSpecError(f"{name}: a material needs a description")
    chosen_kind = kind or pattern_for_description(description)
    palette = palette_for_description(description, path=chosen_kind)
    joint = {}
    path = write_procedural_base_color(
        scratch_dir / f"{name}.png",
        kind=chosen_kind,
        scale_cells=scale_cells,
        width_px=resolution,
        height_px=resolution,
        joint_height_out=joint,
        **palette,
    )
    image = load_image(path)
    try:
        pixels = numpy.empty(resolution * resolution * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
    finally:
        import bpy

        bpy.data.images.remove(image)
    albedo = pixels.reshape((resolution, resolution, 4))[:, :, :3].astype(numpy.float64)
    if "height" in joint:
        # A JOINTED kind's height is its own geometry: the joints low
        # whatever each piece's tone - and each piece FLAT-TOPPED, rising
        # out of its joint over a bevel. The distance to the joint itself
        # peaked every brick in its middle, and the normal map was a field
        # of four-sided pyramids (looked at) where the truths' bricks are
        # flat with the mortar recessed.
        distance = joint["height"]
        rise = numpy.clip(distance / JOINT_BEVEL, 0.0, 1.0)
        height = (
            rise * rise * (3.0 - 2.0 * rise) * (1.0 - JOINT_DOME)
            + distance * JOINT_DOME
        )
    else:
        luma = (
            0.2126 * albedo[:, :, 0]
            + 0.7152 * albedo[:, :, 1]
            + 0.0722 * albedo[:, :, 2]
        )
        height = _relief_height(
            layers._wrapped_box_blur(luma, HEIGHT_BLUR_PX),
            chosen_kind,
            scale_cells,
            resolution,
        )
    return (
        layers.MaterialMaps(
            albedo=albedo,
            roughness=_roughness_map(
                description, chosen_kind, albedo, height, "height" in joint, resolution
            ),
            metallic=1.0 if is_metal(description) else 0.0,
            height=height,
        ),
        chosen_kind,
    )


def _ambient_occlusion(height, kind: str):
    """The occlusion: the height's cavities, as dark and as varied as the
    kind's truths' own AO maps.

    It was one less 0.6 of the cavity mask, so every set's AO spread was
    about 0.14 whatever it was - the truths' run from 0.030 on a parquet to
    0.117 on a roof (median 0.082) - and its mean 0.91 where an asphalt's
    is 0.81 and a parquet's 0.98: the AO's spread error read 0.80. So the
    cavities are standardised and placed at the kind's measured mean and
    spread (kinds with three or more truths that ship an AO), deeper
    cavities darker.
    """
    import numpy

    from golem_blender.pbr import layers

    mean, spread = KIND_AO.get(kind, DEFAULT_AO)
    cavity = layers.cavity_mask(height, radius_px=AO_CAVITY_PX)
    deviation = float(cavity.std())
    if deviation < 1e-9:
        return numpy.full_like(height, mean)
    standard = (cavity - float(cavity.mean())) / deviation
    return numpy.clip(mean - spread * standard, 0.0, 1.0)


def _relief_height(luma, kind: str, scale_cells: float, resolution: int):
    """A non-jointed kind's height: its own relief, as related to its colour
    and as skewed as the kind's truths are, 0 the lowest.

    It was the albedo's smoothed luma, so its correlation with the colour
    was 0.75-0.94 for every kind, where the truths' displacements are
    nearly independent of their colour (medians: a flat sheet -0.06, a
    grain -0.13, a metal 0.04, a rock -0.03) - the normal map repeated the
    colour, and the score's height-luma error was 0.67. So the height is
    the luma at the kind's measured correlation and an independent relief
    for the rest, at the surface's own scale, and an exponential bend
    gives it the kind's measured skew (an asphalt's pits skew it low, a
    gravel's stones high).
    """
    import math

    import numpy

    from golem_blender.pbr import layers
    from golem_blender.pbr.noise import gaussian_grain

    correlation, skew = KIND_HEIGHT.get(kind, DEFAULT_HEIGHT)

    def standardised(field):
        deviation = float(field.std())
        return (field - float(field.mean())) / max(1e-12, deviation)

    sigma = 1024.0 / (max(2.0, float(scale_cells)) * RELIEF_FEATURE_SIGMAS)
    relief = standardised(
        RELIEF_BROAD_SHARE**0.5
        * standardised(gaussian_grain(resolution, sigma, seed=61))
        + (1.0 - RELIEF_BROAD_SHARE) ** 0.5
        * standardised(gaussian_grain(resolution, sigma / 4.0, seed=62))
    )
    height = (
        correlation * standardised(luma)
        + math.sqrt(max(0.0, 1.0 - correlation * correlation)) * relief
    )

    def skew_of(field):
        z = standardised(field)
        return float((z**3).mean())

    def bent(rate):
        if abs(rate) < 1e-6:
            return height
        return numpy.expm1(rate * height) / rate

    low, high = -3.0, 3.0
    for _ in range(40):
        middle = 0.5 * (low + high)
        if skew_of(bent(middle)) < skew:
            low = middle
        else:
            high = middle
    return layers._normalised(bent(0.5 * (low + high)))


def surface_of(description: str, kind: str) -> tuple[float, float, float, float]:
    """The kind's measured normal strength, roughness spread and its luma and
    height correlations,
    refined by the words: a tile floor, a pressed metal, a smooth finish."""
    from golem_blender.pbr.palette import brick_staggered_for_description

    words = set(description.lower().replace(",", " ").split())
    if kind == "brick" and not brick_staggered_for_description(description):
        normal_deg, spread, correlation, height_correlation = TILE_SURFACE
    else:
        normal_deg, spread, correlation, height_correlation = KIND_SURFACE.get(
            kind, DEFAULT_SURFACE
        )
    smooth = bool(words & SMOOTH_WORDS)
    if kind in KIND_SMOOTH_NORMAL:
        normal_deg = KIND_SMOOTH_NORMAL[kind][0 if smooth else 1]
    elif smooth:
        normal_deg *= SMOOTH_NORMAL_RATIO
    if kind == "metal" and words & PRESSED_METAL_WORDS:
        normal_deg = PRESSED_METAL_NORMAL_DEG
    if smooth and words & PLASTIC_WORDS:
        normal_deg = SMOOTH_PLASTIC_NORMAL_DEG
    return normal_deg, spread, correlation, height_correlation


def _roughness_map(
    description: str, kind: str, albedo, height, jointed: bool, resolution: int
):
    """The description's roughness, varying as the kind's truths vary.

    The mean is the words' own (roughness_for_description); the spread is
    the kind's, and it follows the HEIGHT and, for a jointed kind - whose
    height is its geometry and not its colour - the albedo's luma too, at
    the kind's measured correlations. What they do not explain is a grain
    of its own.
    """
    import numpy

    from golem_blender.pbr.material import roughness_for_description
    from golem_blender.pbr.noise import gaussian_grain

    _normal_deg, spread, luma_correlation, height_correlation = surface_of(
        description, kind
    )
    luma = (
        0.2126 * albedo[:, :, 0] + 0.7152 * albedo[:, :, 1] + 0.0722 * albedo[:, :, 2]
    )

    def standardised(field):
        deviation = float(field.std())
        return (
            (field - float(field.mean())) / deviation
            if deviation > 1e-9
            else field * 0.0
        )

    weight_luma = luma_correlation if jointed else 0.0
    explained = min(0.95, height_correlation**2 + weight_luma**2)
    grain = standardised(gaussian_grain(resolution, ROUGHNESS_GRAIN_PX, seed=53))
    variation = (
        height_correlation * standardised(height)
        + weight_luma * standardised(luma)
        + (1.0 - explained) ** 0.5 * grain
    )
    return numpy.clip(
        roughness_for_description(description) + spread * variation, 0.0, 1.0
    )


def _mask(spec: dict, height, resolution: int, name: str):
    from golem_blender.pbr import layers

    unknown = set(spec) - set(MASK_SOURCES) - {"combine"}
    if unknown:
        raise LayerSpecError(
            f"{name}: unknown mask field(s) {sorted(unknown)}; use {MASK_SOURCES} "
            "and 'combine'"
        )
    combine = spec.get("combine", "multiply")
    if combine not in MASK_COMBINE_MODES:
        raise LayerSpecError(
            f"{name}: mask combine must be one of {MASK_COMBINE_MODES}"
        )
    masks = []
    if "height" in spec:
        part = spec["height"]
        masks.append(
            layers.height_mask(
                height,
                level=float(part.get("level", 0.35)),
                softness=float(part.get("softness", 0.2)),
                below=bool(part.get("below", True)),
            )
        )
    if "noise" in spec:
        part = spec["noise"]
        masks.append(
            layers.noise_mask(
                resolution,
                cells=int(part.get("cells", 6)),
                coverage=float(part.get("coverage", 0.4)),
                softness=float(part.get("softness", 0.2)),
                seed=int(part.get("seed", 0)),
            )
        )
    if "cavity" in spec:
        part = spec["cavity"]
        masks.append(
            layers.cavity_mask(
                height,
                radius_px=int(part.get("radius_px", 8)),
                gain=float(part.get("gain", 1.0)),
            )
        )
    if not masks:
        raise LayerSpecError(f"{name}: a layer's mask needs one of {MASK_SOURCES}")
    return layers.combine_masks(*masks, mode=combine)


def _normal_map(height, target_deg: float):
    """A tangent-space normal from the height, with WRAPPED differences,
    scaled so its normals tilt `target_deg` from flat on average - the
    strength the material's own kind measures on the truths."""
    import numpy

    dx = (numpy.roll(height, -1, axis=1) - numpy.roll(height, 1, axis=1)) * 0.5
    dy = (numpy.roll(height, -1, axis=0) - numpy.roll(height, 1, axis=0)) * 0.5
    slope = numpy.hypot(dx, dy)[::4, ::4]
    target = numpy.radians(max(0.01, float(target_deg)))
    low, high = 1e-3, 1e5
    for _ in range(40):
        strength = (low * high) ** 0.5
        if float(numpy.arctan(strength * slope).mean()) < target:
            low = strength
        else:
            high = strength
    strength = (low * high) ** 0.5
    normal = numpy.stack(
        (-dx * strength, -dy * strength, numpy.ones_like(height)), axis=2
    )
    normal /= numpy.linalg.norm(normal, axis=2, keepdims=True)
    return normal * 0.5 + 0.5


def write_layered_texture_set(
    directory: Path,
    texture_name: str,
    base: dict,
    layer_specs: list[dict],
    scale_cells: float = 16.0,
    resolution: int = 2048,
) -> dict:
    """Write a base material with layers over it as one texture set.

    `base` and every layer spec carry a "description" and may carry a
    "kind" and their own "scale_cells". A layer spec also carries a
    "mask" (see the module's docstring), an "amount" (0..1, default 1)
    and a "thickness" (how much it raises the surface, default 0.1).

    With no layers, the base's own words compose them: a "mossy rock" is
    a rock with moss in its hollows, a "rusted iron" a metal with rust in
    patches (compose_from_description).

    Returns the written paths and the kinds the descriptions chose.
    """
    import numpy

    from golem_blender.pbr import layers, paths
    from golem_blender.pbr.procedural import _write_image

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    scratch_dir = directory / f".{texture_name}_layers"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    if not layer_specs:
        base, layer_specs = compose_from_description(base)
    try:
        composed, kinds, normal_deg = _compose(
            base, layer_specs, scale_cells, resolution, scratch_dir
        )
    finally:
        # The scratch materials go whether the set was composed or not -
        # the whole directory, which this call made: on a network share
        # macOS writes a "._name" sidecar beside each file, a glob finds it,
        # and it is gone by the time it is unlinked.
        shutil.rmtree(scratch_dir, ignore_errors=True)

    height = layers._normalised(composed.height)
    # The set's kind is its BASE's: a layer of moss or rust lies ON the
    # base's surface, so it takes the base's displacement range as it
    # takes the base's normal strength.
    set_kind = kinds[0] if kinds else ""
    # The NORMAL map is made from the normalised height, unchanged:
    # _normal_map measures its own slope and scales that to the kind's
    # measured tilt, so the range must not reach it - only the written
    # Height, which a displacement shader reads as DEPTH.
    normal = _normal_map(height, normal_deg)
    written_height = _height_in_range(height, set_kind)
    ambient = _ambient_occlusion(height, set_kind)
    orm = numpy.stack((ambient, composed.roughness, composed.metallic), axis=2)
    written = {
        "base_color": _write_image(
            directory / paths.base_color_file_name(texture_name),
            resolution,
            resolution,
            resolution,
            composed.albedo,
        ),
        "orm": _write_image(
            directory / paths.orm_file_name(texture_name),
            resolution,
            resolution,
            resolution,
            orm,
        ),
        "normal": _write_image(
            directory / paths.normal_file_name(texture_name),
            resolution,
            resolution,
            resolution,
            normal,
        ),
        # The height the normal and the AO were made from, placed in the
        # kind's measured displacement range - a parallax or a
        # displacement reads it as depth, so a steel sheet's is narrow
        # and a rubble's wide.
        "height": _write_image(
            directory / paths.height_file_name(texture_name),
            resolution,
            resolution,
            resolution,
            written_height[:, :, None],
        ),
    }
    height_range = list(height_range_for(set_kind))
    height_range_is_fitted = height_range_is_measured(set_kind)
    # What the Height map's values MEAN, written BESIDE the map: its
    # pixels cannot say which range they are in, and the export's
    # metadata carries this on so the set is usable on its own.
    height_metadata_path = directory / paths.height_metadata_file_name(texture_name)
    height_metadata_path.write_text(
        json.dumps(
            {
                "map": paths.height_file_name(texture_name),
                "range": height_range,
                "kind": set_kind,
                "is_measured": height_range_is_fitted,
                "source": _height_range_source(set_kind),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "paths": {key: str(value) for key, value in written.items()},
        "kinds": kinds,
        "height_range": height_range,
        "height_range_kind": set_kind,
        "height_range_is_measured": height_range_is_fitted,
        "height_metadata": str(height_metadata_path),
    }


def _compose(
    base: dict,
    layer_specs: list[dict],
    scale_cells: float,
    resolution: int,
    scratch_dir: Path,
):
    """The base material with every layer composited over it, the kinds chosen,
    and the set's normal strength in degrees."""
    from golem_blender.pbr import layers

    composed, base_kind = _material_maps(
        str(base.get("description", "")),
        str(base.get("kind", "")),
        float(base.get("scale_cells", scale_cells)),
        resolution,
        scratch_dir,
        "base",
    )
    kinds = [base_kind]
    # The set's normal strength is its BASE's: a layer of moss or rust lies
    # on the base's relief. Weighted by the layers' coverage it took the
    # moss's own 29 degrees and the rust's 5.4 - the truths' mossy Rock063
    # and Rock064 tilt 8.2 and 15.4 (a rock 16.9) and their rusted Metal053C
    # 0.6 (a metal 0.4), and the weighting drew 22.8, 22.4 and 3.1.
    base_description = str(base.get("description", ""))
    normal_deg = surface_of(base_description, base_kind)[0]
    for index, spec in enumerate(layer_specs):
        name = f"layer {index}"
        if "mask" not in spec:
            raise LayerSpecError(f"{name}: a layer needs a mask")
        maps, kind = _material_maps(
            str(spec.get("description", "")),
            str(spec.get("kind", "")),
            float(spec.get("scale_cells", scale_cells)),
            resolution,
            scratch_dir,
            f"layer{index}",
        )
        kinds.append(kind)
        mask = _mask(dict(spec["mask"]), composed.height, resolution, name)
        composed = layers.composite(
            composed,
            [
                layers.Layer(
                    maps=maps,
                    mask=mask,
                    amount=float(spec.get("amount", 1.0)),
                    thickness=float(spec.get("thickness", 0.1)),
                )
            ],
        )
    return composed, kinds, normal_deg


__all__ = (
    "DEFAULT_HEIGHT_RANGE",
    "HEIGHT_RANGE_MINIMUM_TRUTHS",
    "KIND_HEIGHT_RANGE",
    "KIND_HEIGHT_RANGE_TRUTHS",
    "MASK_COMBINE_MODES",
    "MASK_SOURCES",
    "LayerSpecError",
    "height_range_for",
    "height_range_is_measured",
    "write_layered_texture_set",
)
