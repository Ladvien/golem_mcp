"""Making a GENERATED map tile, by material-maker's method.

A generated map does not tile: its seam is a property of the sample,
not of the size, so four generations of one prompt measured 1.38x,
1.57x, 1.10x and 1.38x the texture's largest ordinary features.

The method is material-maker's `make_tileable`: three copies of the
map - at the offset, at half the tile and at a quarter of it -
blended with radial weights that put the blend where the seam is.

These tests are about the trade, because there is one: the seam
falls, and the map moves.
"""

from __future__ import annotations

import numpy
import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

from golem_blender.pbr.tileable import DEFAULT_WIDTH, tileable


def _image(resolution: int = 64, seed: int = 7):
    """A deterministic image with a seam, so the blend has something
    to fix."""
    rows = numpy.arange(resolution).reshape(-1, 1)
    columns = numpy.arange(resolution).reshape(1, -1)
    # A gradient, so the two ends of the tile differ - which is what
    # a seam is.
    values = (rows + columns) % 17
    values = values / 16.0
    image = numpy.empty((resolution, resolution, 4), dtype=numpy.float32)
    image[:, :, 0] = values
    image[:, :, 1] = values * 0.8
    image[:, :, 2] = values * 0.6
    image[:, :, 3] = 1.0
    return image


def _seam(image):
    """The difference between the last column and the first, against
    the interior's largest steps."""
    seam = float(numpy.abs(image[:, -1] - image[:, 0]).mean())
    inner = numpy.abs(image[:, :-1] - image[:, 1:])
    baseline = float(numpy.percentile(inner, 95))
    return seam / baseline if baseline else float("inf")


def test_the_blend_hides_the_seam():
    """The point of the method: the seam falls."""
    image = _image()
    before = _seam(image)
    after = _seam(tileable(image, DEFAULT_WIDTH))
    assert after < before * 0.5, (
        f"the blend left the seam at {after:.3f}x where it was {before:.3f}x"
    )


def test_the_blend_moves_the_image():
    """And the cost: the map is not the map it was.

    A blend that did not move anything would not be hiding a seam -
    it would be doing nothing - so the change has to be visible.
    """
    image = _image()
    blended = tileable(image, DEFAULT_WIDTH)
    assert not numpy.array_equal(blended, image), (
        "the blend left the image untouched, so it cannot have hidden anything"
    )


def test_a_narrower_blend_keeps_more_of_the_image():
    """The width is a trade, and the trade is measured.

    The seam is nearly flat past a narrow width - measured, 0.304x at
    0.01 and 0.296x at 0.08 - so the WIDTH only costs fidelity. The
    narrower blend keeps more of the original.
    """
    image = _image()
    narrow = tileable(image, 0.01)
    wide = tileable(image, 0.08)
    narrow_difference = float(numpy.abs(narrow - image).mean())
    wide_difference = float(numpy.abs(wide - image).mean())
    assert narrow_difference < wide_difference, (
        f"the narrow blend changed the image by {narrow_difference:.4f} and "
        f"the wide one by {wide_difference:.4f}"
    )
