"""LAYERED materials: whole materials composed under masks.

A compound texture - moss in a brick wall's joints, rust in a steel
sheet's dents, dust on the tops of cobbles - is not one pattern. It
is a BASE material with other materials laid over it, each where a
MASK says, and every channel follows the same mask: the moss is green
where it is AND rough where it is AND raised where it is.

Material Maker composes this way (MIT, RodZill4): `blend2.mmg` takes N
layers, each with its own float mask and amount, `a = amount * mask`;
and the masks come from the HEIGHT (its `mwf_*` nodes), from NOISE
(`dirt.mmg`: a shape, an fbm, a colourise) and from CURVATURE
(`edge_detect` into `smooth_curvature`).

Everything here is NumPy on arrays, so it runs inside Blender (which
has no Pillow) and outside it. Every mask is built from periodic
fields, so a composite of tileable materials tiles.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy


@dataclass
class MaterialMaps:
    """One material's maps, all at one resolution.

    `albedo` is (H, W, 3) in 0..1; `roughness`, `metallic` and `height`
    are (H, W) in 0..1, or a single number for a uniform channel.
    """

    albedo: numpy.ndarray
    roughness: numpy.ndarray
    metallic: numpy.ndarray
    height: numpy.ndarray

    def __post_init__(self) -> None:
        if self.albedo.ndim != 3 or self.albedo.shape[2] != 3:
            raise ValueError(f"albedo must be (H, W, 3), got {self.albedo.shape}")
        shape = self.albedo.shape[:2]
        for name in ("roughness", "metallic", "height"):
            value = getattr(self, name)
            if numpy.ndim(value) == 0:
                setattr(self, name, numpy.full(shape, float(value)))
            elif numpy.shape(value) != shape:
                raise ValueError(
                    f"{name} must be {shape} like the albedo, got {numpy.shape(value)}"
                )


@dataclass
class Layer:
    """A material laid over the base where `mask` is one.

    `thickness` is how much the layer RAISES the surface where it lies,
    in the height map's own units: moss and dust sit on a wall, a stain
    is in it.
    """

    maps: MaterialMaps
    mask: numpy.ndarray
    amount: float = 1.0
    thickness: float = 0.0


def _smooth_step(
    edge_low: float, edge_high: float, field: numpy.ndarray
) -> numpy.ndarray:
    span = max(1e-9, edge_high - edge_low)
    t = numpy.clip((field - edge_low) / span, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _normalised(field: numpy.ndarray) -> numpy.ndarray:
    low = float(field.min())
    reach = max(1e-9, float(field.max()) - low)
    return (field - low) / reach


def height_mask(
    height: numpy.ndarray,
    level: float,
    softness: float = 0.1,
    below: bool = True,
) -> numpy.ndarray:
    """Where the surface is LOW (`below`) or HIGH, as a soft 0..1 mask.

    Low is where moss, dirt and water collect - a wall's joints, a
    floor's cracks - and high is where wear and dust show. The level is
    in the height's own normalised range, so 0.3 is the lowest three
    tenths whatever the height map's units.
    """
    normalised = _normalised(height)
    half = max(1e-6, softness) * 0.5
    mask = _smooth_step(level - half, level + half, normalised)
    return 1.0 - mask if below else mask


def noise_mask(
    resolution: int,
    cells: int,
    coverage: float,
    softness: float = 0.08,
    seed: int = 0,
    octaves: int = 4,
) -> numpy.ndarray:
    """Patches covering about `coverage` of the surface.

    Material Maker's `dirt` is a shape put through an fBm and a
    colourise; here the fBm is thresholded at its own quantile, so the
    share it covers is the share asked for and not a guess at the
    noise's distribution. The noise's periods are whole numbers, so the
    mask tiles.
    """
    from golem_blender.pbr import noise, pattern

    if not 0.0 <= coverage <= 1.0:
        raise ValueError(f"coverage must be in 0..1, got {coverage}")
    axis = pattern._domain_samples(resolution)
    sample_x, sample_y = numpy.meshgrid(axis, axis, indexing="ij")
    lattice = max(2, int(cells))
    field = noise.fbm_2d_value(
        sample_x * lattice,
        sample_y * lattice,
        size=lattice,
        octaves=octaves,
        seed=seed,
    )
    if coverage <= 0.0:
        return numpy.zeros_like(field)
    if coverage >= 1.0:
        return numpy.ones_like(field)
    threshold = float(numpy.quantile(field, 1.0 - coverage))
    reach = max(1e-9, float(field.max() - field.min()))
    half = softness * reach * 0.5
    return _smooth_step(threshold - half, threshold + half, field)


def cavity_mask(
    height: numpy.ndarray, radius_px: int = 4, gain: float = 1.0
) -> numpy.ndarray:
    """Where the surface is LOWER than its own neighbourhood: the cavities.

    A dent, a joint and a crack are lower than what is around them,
    whatever their absolute height - so a cavity is the neighbourhood's
    mean less the height, clipped at zero. The neighbourhood WRAPS, so
    a cavity at the map's edge is measured against the other side.
    """
    blurred = _wrapped_box_blur(height, radius_px)
    cavity = numpy.clip(blurred - height, 0.0, None)
    reach = max(1e-9, float(numpy.percentile(cavity, 99.0)))
    return numpy.clip(cavity / reach * gain, 0.0, 1.0)


def _wrapped_box_blur(field: numpy.ndarray, radius: int) -> numpy.ndarray:
    radius = max(1, int(radius))
    out = field.astype(numpy.float64)
    for axis in (0, 1):
        total = numpy.zeros_like(out)
        for shift in range(-radius, radius + 1):
            total += numpy.roll(out, shift, axis=axis)
        out = total / (2 * radius + 1)
    return out


def combine_masks(*masks: numpy.ndarray, mode: str = "multiply") -> numpy.ndarray:
    """Masks combined: `multiply` keeps where ALL say yes, `max` where ANY does."""
    if not masks:
        raise ValueError("combine_masks needs at least one mask")
    if mode == "multiply":
        out = numpy.ones_like(masks[0], dtype=numpy.float64)
        for mask in masks:
            out = out * mask
        return out
    if mode == "max":
        out = numpy.zeros_like(masks[0], dtype=numpy.float64)
        for mask in masks:
            out = numpy.maximum(out, mask)
        return out
    raise ValueError(f"Unknown mask mode {mode!r}; use 'multiply' or 'max'")


def composite(base: MaterialMaps, layers: list[Layer]) -> MaterialMaps:
    """The base with every layer laid over it, in order.

    Every channel follows the same mask - Material Maker's `blend2`,
    `a = amount * mask` - so a layer is one material where it lies and
    not a tint. The height RISES by the layer's thickness where it
    lies, so a normal and an AO baked from it see the moss as moss.
    """
    shape = base.albedo.shape[:2]
    albedo = base.albedo.astype(numpy.float64)
    roughness = base.roughness.astype(numpy.float64)
    metallic = base.metallic.astype(numpy.float64)
    height = base.height.astype(numpy.float64)
    for index, layer in enumerate(layers):
        if layer.mask.shape != shape:
            raise ValueError(
                f"layer {index}'s mask is {layer.mask.shape}, the base is {shape}"
            )
        if layer.maps.albedo.shape[:2] != shape:
            raise ValueError(
                f"layer {index}'s maps are {layer.maps.albedo.shape[:2]}, "
                f"the base is {shape}"
            )
        weight = numpy.clip(layer.mask * float(layer.amount), 0.0, 1.0)
        albedo = (
            albedo * (1.0 - weight[:, :, None]) + layer.maps.albedo * weight[:, :, None]
        )
        roughness = roughness * (1.0 - weight) + layer.maps.roughness * weight
        metallic = metallic * (1.0 - weight) + layer.maps.metallic * weight
        raised = height + float(layer.thickness) * (0.5 + 0.5 * layer.maps.height)
        height = height * (1.0 - weight) + raised * weight
    return MaterialMaps(
        albedo=numpy.clip(albedo, 0.0, 1.0),
        roughness=numpy.clip(roughness, 0.0, 1.0),
        metallic=numpy.clip(metallic, 0.0, 1.0),
        height=height,
    )


__all__ = (
    "Layer",
    "MaterialMaps",
    "cavity_mask",
    "combine_masks",
    "composite",
    "height_mask",
    "noise_mask",
)
