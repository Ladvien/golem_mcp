"""A GRASS's blade pitch, measured on the field itself.

The truth's own three grasses - Ground037 (7.2 features across), Grass001
(34.1) and Grass004 (93.1) - put their fine power's peak at 13.1, 15.5 and
15.5 pixels at 1024 whatever their feature count is.

The lane drew six blades per FEATURE, so a forest floor's 9.8 features became
59 blades across instead of 71: its scale read 3.09x the truth's in the
benchmark and the issue names it "grass strokes three times the truth's
scale".
"""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the patterns are NumPy")

from golem_blender.pbr import pattern


def _box(field, radius):
    window = numpy.zeros_like(field)
    window[: radius + 1, : radius + 1] = 1.0
    window[-radius:, : radius + 1] = 1.0
    window[: radius + 1, -radius:] = 1.0
    window[-radius:, -radius:] = 1.0
    window /= window.sum()
    return numpy.real(numpy.fft.ifft2(numpy.fft.fft2(field) * numpy.fft.fft2(window)))


def _features(field) -> float:
    """The benchmark's own scale measure: the mean row autocorrelation's first
    zero crossing, in features across the image."""
    rows = field - field.mean(axis=1, keepdims=True)
    width = field.shape[1]
    correlation = numpy.zeros(width)
    for row in rows[:: max(1, field.shape[0] // 64)]:
        correlation += numpy.correlate(row, row, mode="full")[width - 1 :]
    correlation /= correlation[0]
    below = numpy.where(correlation < 0.0)[0]
    return width / (int(below[0]) if len(below) else width)


def _fine_peak_px(field, resolution: int) -> float:
    """The fine structure's dominant period, in pixels at a 1024 map."""
    fine = field - _box(field, 8)
    spectrum = numpy.abs(numpy.fft.fftshift(numpy.fft.fft2(fine))) ** 2
    rows, columns = spectrum.shape
    yy, xx = numpy.mgrid[0:rows, 0:columns]
    radius = numpy.hypot(yy - rows // 2, xx - columns // 2).astype(numpy.int32)
    sums = numpy.bincount(radius.ravel(), weights=spectrum.ravel())
    counts = numpy.bincount(radius.ravel())
    means = sums / numpy.maximum(counts, 1)
    peak = int(numpy.argmax(means[4:300])) + 4
    return (1024.0 / peak) * (resolution / 1024.0)


@pytest.mark.parametrize("cells", (10, 34, 93))
def test_a_grass_s_blade_pitch_is_the_truths_own(cells):
    """Ground037, Grass001 and Grass004 put their blades 13.1-15.5 pixels
    apart at 1024, at 7.2, 34.1 and 93.1 features across. The lane read
    twice that pitch, and the forest floor's scale read 3.09x its truth's."""
    _cell, field, _grid, _fibre = pattern.grass_field(1024, cells)
    peak = _fine_peak_px(field, 1024)
    assert 11.0 <= peak <= 21.0, f"the blades read {peak:.1f} px at {cells} cells"


def test_a_forest_floor_s_scale_is_not_three_times_the_truth_s():
    """The benchmark's own measure: Ground037 reads 7.2 features across, and
    the lane read 22.2 at ten cells - 3.09x its scale."""
    _cell, field, _grid, _fibre = pattern.grass_field(1024, 10)
    assert _features(field) / 7.21 < 1.6, _features(field)


def test_a_denser_lawn_carries_more_features_than_a_forest_floor():
    """The surface's own count is its PATCHES: Grass004 reads 93.1 features
    across where Ground037 reads 7.2, at the same blade pitch."""
    _cell, floor, _grid, _fibre = pattern.grass_field(1024, 10)
    _cell, lawn, _grid, _fibre = pattern.grass_field(1024, 93)
    assert _features(lawn) > _features(floor)


def test_a_forest_floor_is_patchier_than_a_dense_lawn():
    """The truth's own Ground037's broad 64-pixel blur carries 0.19 of its
    spread - moss and earth patches - Grass001's 0.09 and Grass004's 0.05."""
    _cell, floor, _grid, _fibre = pattern.grass_field(1024, 10)
    _cell, dense, _grid, _fibre = pattern.grass_field(1024, 93)
    floor_broad = float(_box(floor, 64).std()) / float(floor.std())
    dense_broad = float(_box(dense, 64).std()) / float(dense.std())
    assert floor_broad > dense_broad, (floor_broad, dense_broad)


def test_a_grass_field_still_tiles():
    """A blade is a turned value noise whose vectors are whole, so the field
    repeats on the tile."""
    _cell, field, _grid, _fibre = pattern.grass_field(256, 8)
    across = float(numpy.abs(numpy.diff(field, axis=1)).max())
    down = float(numpy.abs(numpy.diff(field, axis=0)).max())
    assert float(numpy.abs(field[:, 0] - field[:, -1]).max()) <= across
    assert float(numpy.abs(field[0] - field[-1]).max()) <= down


# The tile face's PITS, measured on the writer's own colour.
def _pits(field, sigma, tiles):
    """Discrete dark spots, 2..60 pixels, counted per tile - the truths' own
    measure. The grout network is one enormous region and is excluded."""
    mean, deviation = float(field.mean()), float(field.std())
    dark = field < mean - sigma * deviation
    reached = numpy.full(dark.shape, -1, dtype=numpy.int32)
    sizes, depths, index = [], [], 0
    rows, columns = dark.shape
    for start in numpy.argwhere(dark):
        row, column = int(start[0]), int(start[1])
        if reached[row, column] >= 0:
            continue
        stack = [(row, column)]
        reached[row, column] = index
        members = []
        while stack:
            at_row, at_column = stack.pop()
            members.append((at_row, at_column))
            for dy, dx in (
                (-1, -1),
                (-1, 0),
                (-1, 1),
                (0, -1),
                (0, 1),
                (1, -1),
                (1, 0),
                (1, 1),
            ):
                r, c = at_row + dy, at_column + dx
                if (
                    0 <= r < rows
                    and 0 <= c < columns
                    and dark[r, c]
                    and reached[r, c] < 0
                ):
                    reached[r, c] = index
                    stack.append((r, c))
        if 2 <= len(members) <= 60:
            sizes.append(len(members))
            depths.append(
                (mean - sum(float(field[r_, c_]) for r_, c_ in members) / len(members))
                / deviation
            )
        index += 1
    if not sizes:
        return 0.0, 0.0, 0.0, 0.0
    return (
        len(sizes) / (tiles * tiles),
        float(numpy.median(sizes)),
        float(numpy.median(depths)),
        100.0 * sum(sizes) / field.size,
    )


TILE_DESCRIPTION = (
    "bathroom, beige, dirty, floor, grid, kitchen, rectangular, rough, "
    "stained, stone, tiles, urban, white"
)


def _tile_luma(tmp_path):
    import bpy

    from golem_blender.pbr.palette import palette_for_description
    from golem_blender.pbr.patterns import pattern_for_description
    from golem_blender.pbr.procedural import write_procedural_base_color

    kind = pattern_for_description(TILE_DESCRIPTION)
    assert kind == "brick"
    path = write_procedural_base_color(
        tmp_path / "tiles.png",
        kind=kind,
        scale_cells=10.0,
        width_px=1024,
        height_px=1024,
        **palette_for_description(TILE_DESCRIPTION, path=kind),
    )
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    rgb = values.reshape((1024, 1024, 4))[:, :, :3].astype(float)
    return rgb @ numpy.array([0.2126, 0.7152, 0.0722])


def test_a_worn_stone_tile_s_face_is_pitted(tmp_path):
    """The truths' own Tiles139, 141, 143 and 144 put 37 to 47 pits on each
    tile, three to four pixels across and three and a half deviations deep,
    over 0.47-0.78% of the surface. The lane's faces carried none at all."""
    luma = _tile_luma(tmp_path)
    count, median, depth, coverage = _pits(luma, 3.0, 5)
    assert 30.0 <= count <= 80.0, count
    assert 3.0 <= median <= 7.0, median
    assert 3.2 <= depth <= 4.2, depth
    assert 0.35 <= coverage <= 1.0, coverage
