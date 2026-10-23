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


def _runs(mask_line):
    """The lengths of the True runs along a line."""
    padded = numpy.concatenate(([False], mask_line, [False]))
    changes = numpy.flatnonzero(numpy.diff(padded.astype(int)))
    return changes[1::2] - changes[::2]


def test_a_board_s_end_is_as_sharp_as_its_sides():
    """The distance to a board's end was a fraction of its LENGTH, so the
    joint falloff smeared every end over forty pixels while the sides
    stayed sharp."""
    from golem_blender.pbr import pattern

    _cell, edge, (_across, courses), _fibre = pattern.parquet_field(512, 6)
    course = 512 // courses
    soft = edge < 0.5
    end_widths = _runs(soft[course // 2])
    side_widths = _runs(soft[:, 7])
    assert float(numpy.median(end_widths)) <= 1.5 * float(numpy.median(side_widths))


def test_planks_are_long_boards_and_a_parquet_is_blocks():
    """The plank truths run their boards four to eight times as long as
    wide (Planks037A, Planks039, WoodFloor043); a parquet's blocks three."""
    from golem_blender.pbr import pattern

    def aspect(long_boards):
        cell, _edge, _grid, _fibre = pattern.parquet_field(
            512, 6, long_boards=long_boards
        )
        along = float(
            numpy.median(_runs(numpy.diff(cell, axis=1, prepend=-1)[100] == 0))
        )
        down = float(
            numpy.median(_runs(numpy.diff(cell, axis=0, prepend=-1)[:, 100] == 0))
        )
        return along / down

    assert aspect(True) >= 6.0
    assert 2.5 <= aspect(False) <= 4.5


def test_an_onyx_is_banded_layers_and_not_veins(tmp_path):
    """The truths' onyx and travertine are layers across the stone; as
    marbles they were veins on a mottle, and the profile down the image
    carried almost none of the picture."""
    luma = _luma(tmp_path, "marble, onyx, polished, smooth, stone, white", 8.0)
    profile = luma.mean(axis=1) - luma.mean()
    assert float(profile.std()) > 0.5 * float(luma.std())


def test_a_roof_s_shingle_edges_are_shadows(tmp_path):
    """The roof field is the distance to a shingle's edge, and the shadow
    was laid where it was LARGE: every shingle's middle shaded and a bright
    frame round each one."""
    from golem_blender.pbr import pattern

    luma = _luma(tmp_path, "clay, roof, roofing, tiles, tiling", 6.0)
    _cell, edge, _grid, _tone = pattern.roof_field(RESOLUTION, 6)
    assert float(luma[edge < 0.05].mean()) < float(luma[edge > 0.5].mean())


def test_a_concrete_shows_no_lattice(tmp_path):
    """The flat sheet was a value noise, and its lattice showed as squares
    in the concretes' and plasters' crops. A quintic value noise's slope
    across is ZERO along every lattice column - every octave's at the
    coarse ones - so the mean slope per column dips there; a grain with no
    lattice has no such columns."""
    from golem_blender.pbr import pattern

    _cell, edge, _grid, _tooth = pattern.flat_field(RESOLUTION, 16)
    slope = numpy.abs(numpy.roll(edge, -1, axis=1) - numpy.roll(edge, 1, axis=1))
    columns = slope.mean(axis=0)
    assert float(columns.min()) > 0.5 * float(numpy.median(columns))


def test_a_surface_s_slow_drift_shows_no_lattice():
    """The slow drift - the stain across a tiled floor, a brick face's
    drift - was one value-noise octave, and its lattice showed as soft
    squares across the tiles: its slope across vanished on every lattice
    column."""
    from golem_blender.pbr import pattern

    drift = pattern.slow_variation(RESOLUTION, 8)
    slope = numpy.abs(numpy.roll(drift, -1, axis=1) - numpy.roll(drift, 1, axis=1))
    columns = slope.mean(axis=0)
    assert float(columns.min()) > 0.4 * float(numpy.median(columns))


def test_a_fan_paving_tiles():
    """The fans are disks on a staggered lattice that divides the image, so
    the step across the wrap is the step one fan further in - the same
    place in the pattern."""
    from golem_blender.pbr import pattern

    _cell, edge, _grid, _fibre = pattern.fan_field(RESOLUTION, 80)
    fan = RESOLUTION // 8
    wrap = float(numpy.abs(edge[:, 0] - edge[:, -1]).mean())
    inside = float(numpy.abs(edge[:, fan] - edge[:, fan - 1]).mean())
    assert abs(wrap - inside) <= 0.1 * inside
    wrap = float(numpy.abs(edge[0] - edge[-1]).mean())
    inside = float(numpy.abs(edge[2 * fan] - edge[2 * fan - 1]).mean())
    assert abs(wrap - inside) <= 0.1 * inside


def test_a_bark_s_fissures_run_down_the_trunk(tmp_path):
    """The truth's own Bark015 is long vertical ridges and fissures; as a
    board's grain it ran ACROSS the image."""
    luma = _luma(tmp_path, "bark, brown, forest, rough, tree, wood", 12.0)
    along_row = float(numpy.abs(numpy.diff(luma, axis=1)).mean())
    down_column = float(numpy.abs(numpy.diff(luma, axis=0)).mean())
    assert along_row > 1.3 * down_column


def _gaussian(field, sigma):
    """A wrapped Gaussian blur through the FFT."""
    size = field.shape[0]
    frequency = numpy.fft.fftfreq(size)
    kernel = numpy.exp(-2.0 * (numpy.pi * sigma) ** 2 * frequency**2)
    return numpy.real(
        numpy.fft.ifft2(numpy.fft.fft2(field) * kernel[:, None] * kernel[None, :])
    )


def test_a_plain_metal_sheet_is_not_a_two_tone_camouflage(tmp_path):
    """A plain sheet's mottle raised to a power was two-tone blobs over the
    whole sheet - a camouflage (looked at). Its middle scales' variation
    measured a bimodality of 0.66 on every plain metal, where the truths'
    plain sheets measure 0.20-0.42."""
    luma = _luma(tmp_path, "metal, scratched, steel", 16.0)
    band = _gaussian(luma, 1.5 * RESOLUTION / 1024) - _gaussian(
        luma, 8.0 * RESOLUTION / 1024
    )
    standard = (band - band.mean()) / band.std()
    skew = float((standard**3).mean())
    kurtosis = float((standard**4).mean())
    assert (skew * skew + 1.0) / kurtosis < 0.5


def test_a_brick_wall_s_mortar_is_a_band_and_not_a_cushion(tmp_path):
    """The joint's falloff was a ramp across the mortar's whole width -
    darkest on the joint's line and fading into the face - so every block
    shaded into its rim like a cushion. A wall's mortar is a BAND: flat
    across its inner part, its edge soft only where it meets the stone."""
    description = "brick, bricks, natural, stone, wall"
    kind = pattern_for_description(description)
    joint = {}
    path = write_procedural_base_color(
        tmp_path / "wall.png",
        kind=kind,
        scale_cells=8.0,
        width_px=RESOLUTION,
        height_px=RESOLUTION,
        joint_height_out=joint,
        **palette_for_description(description, path=kind),
    )
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    rgb = values.reshape((RESOLUTION, RESOLUTION, 4))[:, :, :3].astype(float)
    luma = (rgb @ numpy.array([0.2126, 0.7152, 0.0722])).ravel()
    distance = joint["height"].ravel()
    edges = numpy.linspace(0.0, 0.5, 51)
    which = numpy.digitize(distance, edges) - 1
    profile = numpy.array(
        [
            luma[which == i].mean() if (which == i).any() else numpy.nan
            for i in range(50)
        ]
    )
    face = float(numpy.nanmedian(profile[25:]))
    mortar = float(profile[0])
    contrast = abs(face - mortar)
    # Where the mortar ends: the first distance whose luma is within a
    # tenth of the contrast of the face's.
    end = int(numpy.argmax(numpy.abs(profile - face) < 0.1 * contrast))
    inner = profile[: max(2, end // 2)]
    assert float(numpy.nanmax(inner) - numpy.nanmin(inner)) < 0.25 * contrast


@pytest.mark.parametrize(
    ("description", "grout_darker"),
    [("tiles, white", True), ("black, square, stone, tiles", False)],
)
def test_a_tile_floor_s_grout_is_a_mid_tone(tmp_path, description, grout_darker):
    """The truths' light tiles have darker grout and their dark ones paler
    (Tiles107 against Tiles138, 140); the grout was the tiles' colour less
    a spread, so a black floor's grout was blacker still."""
    luma = _luma(tmp_path, description, 8.0)
    rows = luma.mean(axis=1) - float(numpy.median(luma))
    if grout_darker:
        assert -float(rows.min()) > float(rows.max())
    else:
        assert float(rows.max()) > -float(rows.min())


def test_a_rock_face_is_broad_tone_and_not_a_speckle(tmp_path):
    """Its layers were mixed by their ranges, so the fine grain took the
    variance: the truths' rock faces hold a median 0.30 of it above eight
    pixels and ours held 0.17 - a salt-and-pepper speckle."""
    luma = _luma(tmp_path, "cliff, grey, rock", 12.0)
    coarse = _gaussian(luma, 8.0 * RESOLUTION / 1024)
    assert float(coarse.var()) / float(luma.var()) > 0.25
