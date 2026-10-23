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


def test_a_carpet_is_a_fine_pile_and_not_blobs(tmp_path):
    """The truths' carpets hold 81-93% of their variance finer than a 4 px
    blur; a Perlin at a lattice of two drew great blobs instead."""
    from golem_blender.pbr.layers import _wrapped_box_blur

    luma = _luma(tmp_path, "blue, carpet, dark, plain", 256.0)
    fine = luma - _wrapped_box_blur(luma, 4)
    assert float(fine.var()) / float(luma.var()) > 0.6


def test_a_cloth_carpet_is_streaked_and_a_plain_one_is_not(tmp_path):
    """The cloth carpets change half as fast along a row as down it (0.44,
    0.56); the plain ones about as fast (0.99, 1.20)."""

    def along_over_down(luma):
        return float(numpy.abs(numpy.diff(luma, axis=1)).mean()) / float(
            numpy.abs(numpy.diff(luma, axis=0)).mean()
        )

    cloth = along_over_down(
        _luma(tmp_path / "cloth", "blue, carpet, cloth, fabric", 32.0)
    )
    plain = along_over_down(
        _luma(tmp_path / "plain", "blue, carpet, dark, plain", 32.0)
    )
    assert cloth < 0.75
    assert plain > 0.85
