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
material's height is its albedo's smoothed luma.
"""

from __future__ import annotations

from pathlib import Path

# How much a material's luma is smoothed before it is read as height.
HEIGHT_BLUR_PX = 2
# How dark the deepest cavity is in the AO channel.
AO_STRENGTH = 0.6
# The normal map's strength: the height's gradient times this.
NORMAL_STRENGTH = 6.0
# What the mask may be built from, and how masks combine.
MASK_SOURCES = ("height", "noise", "cavity")
MASK_COMBINE_MODES = ("multiply", "max")


class LayerSpecError(ValueError):
    """A layer's specification cannot be built; the message names the field."""


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
    from golem_blender.pbr.material import is_metal, roughness_for_description
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
        # whatever each piece's tone.
        height = joint["height"]
    else:
        # Every other kind's height is its luma: a grain's lines, a
        # rock's pits and a flat sheet's mottle are darker than what is
        # around them.
        luma = (
            0.2126 * albedo[:, :, 0]
            + 0.7152 * albedo[:, :, 1]
            + 0.0722 * albedo[:, :, 2]
        )
        height = layers._normalised(layers._wrapped_box_blur(luma, HEIGHT_BLUR_PX))
    return (
        layers.MaterialMaps(
            albedo=albedo,
            roughness=roughness_for_description(description),
            metallic=1.0 if is_metal(description) else 0.0,
            height=height,
        ),
        chosen_kind,
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


def _normal_map(height, strength: float):
    """A tangent-space normal from the height, with WRAPPED differences."""
    import numpy

    dx = (numpy.roll(height, -1, axis=1) - numpy.roll(height, 1, axis=1)) * 0.5
    dy = (numpy.roll(height, -1, axis=0) - numpy.roll(height, 1, axis=0)) * 0.5
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

    Returns the written paths and the kinds the descriptions chose.
    """
    import numpy

    from golem_blender.pbr import layers, paths
    from golem_blender.pbr.procedural import _write_image

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    scratch_dir = directory / f".{texture_name}_layers"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    try:
        composed, kinds = _compose(
            base, layer_specs, scale_cells, resolution, scratch_dir
        )
    finally:
        # The scratch materials go whether the set was composed or not.
        for scratch in scratch_dir.glob("*.png"):
            scratch.unlink()
        scratch_dir.rmdir()

    height = layers._normalised(composed.height)
    ambient = 1.0 - AO_STRENGTH * layers.cavity_mask(height, radius_px=6)
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
            _normal_map(height, NORMAL_STRENGTH),
        ),
    }
    return {
        "paths": {key: str(value) for key, value in written.items()},
        "kinds": kinds,
    }


def _compose(
    base: dict,
    layer_specs: list[dict],
    scale_cells: float,
    resolution: int,
    scratch_dir: Path,
):
    """The base material with every layer composited over it, and the kinds chosen."""
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
    return composed, kinds


__all__ = (
    "MASK_COMBINE_MODES",
    "MASK_SOURCES",
    "LayerSpecError",
    "write_layered_texture_set",
)
