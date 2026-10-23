"""A carpet without a seam, and a pressed sheet whose ribs are its picture."""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")

import bpy

from golem_blender.pbr.palette import palette_for_description
from golem_blender.pbr.patterns import pattern_for_description
from golem_blender.pbr.procedural import write_procedural_base_color

RESOLUTION = 512


def _luma(tmp_path, description: str, cells: float):
    kind = pattern_for_description(description)
    path = write_procedural_base_color(
        tmp_path / "map.png",
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


def test_a_carpet_has_no_seam_down_it(tmp_path):
    """The carpet's field varies across the image only, and the joint
    falloff thresholded it into one hairline the map's full height - a
    crease in the column profile a hundred times its neighbours'."""
    luma = _luma(tmp_path, "beige, carpet, cloth, dirty, fabric, floor, smudge", 15.0)
    crease = numpy.abs(numpy.diff(luma.mean(axis=0), n=2))
    assert float(crease.max()) < 20.0 * float(numpy.median(crease)) + 1e-6


def test_a_pressed_sheet_is_its_ribs(tmp_path):
    """The truth's corrugated steel has its ribs as the strongest period of
    its profile; drawn as lines the ribs drowned in the grain, or ran down
    the image, and the profile's strongest period was the weathering's."""
    luma = _luma(tmp_path, "corrugated, galvanised, metal, ribbed, sheet, steel", 6.0)
    profile = luma.mean(axis=1) - luma.mean()
    spectrum = numpy.abs(numpy.fft.rfft(profile))
    spectrum[:4] = 0.0
    period = RESOLUTION / int(numpy.argmax(spectrum))
    assert period < RESOLUTION / 8
    assert float(profile.std()) > 0.5 * float(luma.std())
