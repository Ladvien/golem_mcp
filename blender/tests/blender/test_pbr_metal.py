"""A metal sheet's own structure: its brushing and its scratches."""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")
bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


def _correlation_length(rows) -> int:
    """The lag at which the rows' own correlation falls below a half."""
    width = rows.shape[1]
    centred = rows - rows.mean(axis=1, keepdims=True)
    total = numpy.zeros(width)
    for row in centred[::4]:
        total += numpy.correlate(row, row, mode="full")[width - 1 :]
    total /= total[0]
    below = numpy.nonzero(total < 0.5)[0]
    return int(below[0]) if len(below) else width


def test_a_brushed_sheet_is_streaked_along_its_rows(tmp_path):
    """The truth's own Metal009 is smooth for 24 pixels along a row and
    changes within one down a column; the lane drew a brushed sheet as a
    pressed one's ribs under blotches, 86 and 81 pixels both ways."""
    from golem_blender.pbr.palette import palette_for_description
    from golem_blender.pbr.procedural import write_procedural_base_color

    description = "brushed, metal, silver, steel"
    path = write_procedural_base_color(
        tmp_path / "T_Brushed_BaseColor.png",
        kind="metal",
        scale_cells=8.0,
        width_px=512,
        height_px=512,
        **palette_for_description(description, path="metal"),
    )
    image = bpy.data.images.load(str(path))
    pixels = numpy.empty(512 * 512 * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    bpy.data.images.remove(image)
    luma = pixels.reshape((512, 512, 4))[:, :, :3].mean(axis=2)
    along_rows = _correlation_length(luma)
    down_columns = _correlation_length(luma.T)
    assert along_rows >= 2 * down_columns, (along_rows, down_columns)


def test_the_scratches_do_not_repeat_at_their_cells_period():
    """Each cell holds ITS OWN scratch.

    The port wrapped the cell's frame per cell, so every cell carried
    every cell's scratch and the map was the same one cell over.
    """
    from golem_blender.pbr.curvature import scratches

    resolution, size = 256, 0.25
    field = scratches(resolution, size=size, width=0.1, layers=4)
    one_cell = round(resolution * size)
    shifted = numpy.roll(field, one_cell, axis=0)
    same = numpy.corrcoef(field.ravel(), shifted.ravel())[0, 1]
    assert same < 0.5, f"the scratch map one cell over correlates {same:.2f}"


@pytest.mark.parametrize("seed", range(5))
def test_the_scratches_tile(seed):
    """The step across the wrap is an ordinary step: no larger than the
    largest between two neighbouring rows inside the map. One row pair
    of a sparse field is noisy - across twenty seeds the seam's rank
    among the interior steps averages a half - so the bound is the
    largest, which a broken wrap would stand far above."""
    from golem_blender.pbr.curvature import scratches

    field = scratches(256, size=0.25, width=0.1, layers=4, seed=seed)
    for axis in (0, 1):
        rows = numpy.moveaxis(field, axis, 0)
        seam = float(numpy.abs(rows[0] - rows[-1]).mean())
        interior = numpy.abs(numpy.diff(rows, axis=0)).mean(axis=1)
        assert seam <= float(interior.max()), (axis, seam, float(interior.max()))
