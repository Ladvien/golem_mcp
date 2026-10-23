"""An asphalt: a fine aggregate, worn patches and pale cracks - not polygon plates.

The maps are built the way the agent's tool builds them, from the words.
"""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")

import bpy

from golem_blender.pbr.palette import palette_for_description
from golem_blender.pbr.patterns import pattern_for_description
from golem_blender.pbr.procedural import write_procedural_base_color

RESOLUTION = 512
GRANULAR = "asphalt, charcoal, dark, granular, gray, matte, pavement, road"
CRACKED = "asphalt, black, cracked, gray, old, pavement, road, rough, worn"
UNCRACKED = "asphalt, black, gray, old, pavement, road, rough, worn"


def _luma(tmp_path, description: str, cells: float = 30.0):
    kind = pattern_for_description(description)
    path = write_procedural_base_color(
        tmp_path / "asphalt.png",
        kind=kind,
        scale_cells=cells,
        width_px=RESOLUTION,
        height_px=RESOLUTION,
        **palette_for_description(description, path=kind),
    )
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    rgb = values.reshape((RESOLUTION, RESOLUTION, 4))[:, :, :3].astype(float)
    return rgb @ numpy.array([0.2126, 0.7152, 0.0722])


def test_a_plain_asphalt_is_a_fine_aggregate_and_not_plates(tmp_path):
    """The truth's own Asphalt033 has 86% of its variance finer than a
    4-pixel blur; as Voronoi plates nearly all of it was in the plates."""
    from golem_blender.pbr.layers import _wrapped_box_blur

    luma = _luma(tmp_path, GRANULAR)
    fine = luma - _wrapped_box_blur(luma, 4)
    assert float(fine.var()) / float(luma.var()) > 0.6


def test_a_cracked_road_has_pale_cracks_and_an_uncracked_one_none(tmp_path):
    """The truths' cracked roads (Road012B, Road015C) carry thin cracks
    PALER than the surface; the same road without the word has none."""

    def pale_tail(luma):
        spread = float(luma.std())
        return float((luma > luma.mean() + 4.0 * spread).mean())

    cracked = pale_tail(_luma(tmp_path / "cracked", CRACKED))
    plain = pale_tail(_luma(tmp_path / "plain", UNCRACKED))
    assert cracked > 0.002
    assert cracked > 10.0 * plain


def test_the_cracks_tile(tmp_path):
    """The cracks' distance is computed on a coarse grid and brought up by
    a wrapped read: across the wrap the field steps no more than inside."""
    from golem_blender.pbr import pattern

    _cell, field, _grid, _fibre = pattern.asphalt_field(
        2048, 30, worn=True, cracked=True
    )
    inside = float(numpy.abs(numpy.diff(field, axis=1)).max())
    assert float(numpy.abs(field[:, 0] - field[:, -1]).max()) <= inside
    inside = float(numpy.abs(numpy.diff(field, axis=0)).max())
    assert float(numpy.abs(field[0] - field[-1]).max()) <= inside


def test_a_painted_road_s_surface_is_the_description_s_value(tmp_path):
    """The painted road was drawn at the palette ramp's DARK end and never
    shifted - the truth's own Road007 read 0.51x its brightness. Its
    unpainted surface is the description's value."""
    description = "asphalt, center, dark, dashed, gray, lane, line, markings, road"
    luma = _luma(tmp_path, description, cells=73.0)
    target = palette_for_description(description, path="markings")["target_value"]
    road = luma[luma < numpy.percentile(luma, 95)]
    assert abs(float(road.mean()) / target - 1.0) < 0.12
