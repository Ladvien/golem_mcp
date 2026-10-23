"""A loose ground: distinct stones on a gritty soil, not a camouflage of flakes."""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")

import bpy

from golem_blender.pbr.palette import palette_for_description
from golem_blender.pbr.procedural import write_procedural_base_color

RESOLUTION = 512
GROUND = "brown, debris, dirt, gravel, gray, ground, rocky, rough, scattered"


def test_a_ground_s_stones_are_distinct_with_soil_between_them():
    """Two hundred thousand splats overlapped into flakes, and the writer
    blended every pixel half stone and half soil: no stone stood out. The
    stones now cover part of the ground, and a pixel is stone or soil."""
    from golem_blender.pbr import pattern

    _cell, mask, _grid, _tone, _slow, _hue = pattern.scattered_field(RESOLUTION, 16)
    assert 0.2 < float(mask.mean()) < 0.8
    # A stone's one-pixel rim is neither; at 512 px the rims of the small
    # stones are about a seventh of the ground.
    assert float(((mask > 0.95) | (mask < 0.05)).mean()) > 0.75


def test_a_ground_s_soil_is_gritty(tmp_path):
    """The soil's grit sat near one half and clipped at one: the gaps
    between the stones were a smooth sheet. Its fine grain is a real share
    of the ground's own variation."""
    from golem_blender.pbr import pattern
    from golem_blender.pbr.layers import _wrapped_box_blur

    path = write_procedural_base_color(
        tmp_path / "ground.png",
        kind="scattered",
        scale_cells=16,
        width_px=RESOLUTION,
        height_px=RESOLUTION,
        **palette_for_description(GROUND, path="scattered"),
    )
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    luma = values.reshape((RESOLUTION, RESOLUTION, 4))[:, :, :3] @ numpy.array(
        [0.2126, 0.7152, 0.0722]
    )
    _cell, mask, _grid, _tone, _slow, _hue = pattern.scattered_field(RESOLUTION, 16)
    soil = mask < 0.05
    fine = luma - _wrapped_box_blur(luma, 2)
    assert float(fine[soil].std()) > 0.25 * float(luma.std())


def test_a_soil_has_far_fewer_stones_than_a_gravel():
    """The truths' soils (Ground103 "dirt, earth, soil", Ground106 "mud,
    muddy") are smooth ground with a few small stones; drawn at a gravel's
    density they were heaps of big stones."""
    from golem_blender.pbr import pattern
    from golem_blender.pbr.palette import palette_for_description

    def cover(description):
        density = palette_for_description(description, path="scattered")[
            "stone_density"
        ]
        _cell, mask, _grid, _tone, _slow, _hue = pattern.scattered_field(
            RESOLUTION, 16, density=density
        )
        return float(mask.mean())

    assert cover("brown, dirt, earth, ground, soil") < 0.5 * cover(
        "dirt, gravel, ground, rocky"
    )
