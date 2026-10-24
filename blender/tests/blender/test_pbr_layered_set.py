"""A layered texture set: materials made from their descriptions, composed under masks.

The set is what the agent's layered-texture tool writes, so these read
it the way a consumer would: the written PNGs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

numpy = pytest.importorskip("numpy", reason="the layered set is NumPy")

import bpy

from golem_blender.pbr import paths, procedural
from golem_blender.pbr.layered_set import LayerSpecError, write_layered_texture_set
from golem_blender.pbr.palette import palette_for_description

RESOLUTION = 256
CELLS = 8
WALL = "red brick wall, old, weathered"
MOSS_IN_THE_JOINTS = {
    "description": "dark green moss",
    "mask": {"height": {"level": 0.4, "below": True, "softness": 0.3}},
}


def _pixels(path) -> numpy.ndarray:
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    return values.reshape((RESOLUTION, RESOLUTION, 4))[:, :, :3].astype(float)


def _greening(tmp_path: Path):
    """How much greener the moss made each pixel, and the wall's own geometry."""
    bare = write_layered_texture_set(
        tmp_path / "bare", "Wall", {"description": WALL}, [], CELLS, RESOLUTION
    )
    mossy = write_layered_texture_set(
        tmp_path / "mossy",
        "Wall",
        {"description": WALL},
        [MOSS_IN_THE_JOINTS],
        CELLS,
        RESOLUTION,
    )
    base = _pixels(bare["paths"]["base_color"])
    out = _pixels(mossy["paths"]["base_color"])
    joint = {}
    procedural.write_procedural_base_color(
        tmp_path / "geometry.png",
        kind="brick",
        scale_cells=CELLS,
        width_px=RESOLUTION,
        height_px=RESOLUTION,
        joint_height_out=joint,
        **palette_for_description(WALL, path="brick"),
    )
    greening = (out[:, :, 1] - out[:, :, 0]) - (base[:, :, 1] - base[:, :, 0])
    return greening, joint["height"], base.mean(axis=2)


def test_moss_laid_in_the_joints_grows_from_the_joints(tmp_path):
    greening, joint_height, _luma = _greening(tmp_path)
    near_the_joints = greening[joint_height < 0.2].mean()
    at_the_centres = greening[joint_height > 0.7].mean()
    assert near_the_joints > 3.0 * max(at_the_centres, 1e-3)


def test_moss_laid_in_the_joints_does_not_seek_out_the_dark_bricks(tmp_path):
    """A weathered wall's darker bricks are darker than its mortar.

    A height read from the colour called them low, and the moss
    smothered whole dark bricks: they took nearly three times the
    faces' average.
    """
    greening, joint_height, luma = _greening(tmp_path)
    faces = joint_height > 0.5
    darkest = faces & (luma < numpy.percentile(luma[faces], 25))
    # With flat-topped bricks no face may take moss at all - and the dark
    # ones then take exactly as little as the rest.
    assert greening[darkest].mean() <= 1.5 * greening[faces].mean() + 1e-3


def test_rust_laid_over_steel_is_orange_and_not_metal(tmp_path):
    written = write_layered_texture_set(
        tmp_path,
        "Rusty",
        {"description": "grey steel metal sheet"},
        [{"description": "rust", "mask": {"noise": {"cells": 3, "coverage": 0.5}}}],
        CELLS,
        RESOLUTION,
    )
    albedo = _pixels(written["paths"]["base_color"])
    orm = _pixels(written["paths"]["orm"])
    rusted = orm[:, :, 2] < 0.1
    bare = orm[:, :, 2] > 0.9
    assert 0.3 < rusted.mean() < 0.7
    red, green, blue = (albedo[rusted][:, channel].mean() for channel in range(3))
    assert red > green > blue
    assert orm[:, :, 1][rusted].mean() > orm[:, :, 1][bare].mean()


def test_the_set_tiles(tmp_path):
    written = write_layered_texture_set(
        tmp_path, "Wall", {"description": WALL}, [MOSS_IN_THE_JOINTS], CELLS, RESOLUTION
    )
    for key in ("base_color", "orm", "normal"):
        assert (
            paths.tile_seam_ratio(Path(written["paths"][key])) <= paths.TILE_SEAM_LIMIT
        )


def test_a_misspelt_mask_is_named_and_leaves_nothing_behind(tmp_path):
    with pytest.raises(LayerSpecError, match="heigth"):
        write_layered_texture_set(
            tmp_path,
            "Bad",
            {"description": WALL},
            [{"description": "moss", "mask": {"heigth": {"level": 0.4}}}],
            CELLS,
            RESOLUTION,
        )
    assert list(tmp_path.iterdir()) == []


def _set_channels(tmp_path: Path, description: str, cells: float = 8.0):
    written = write_layered_texture_set(
        tmp_path, "Set", {"description": description}, [], cells, RESOLUTION
    )
    orm = _pixels(written["paths"]["orm"])
    normal = _pixels(written["paths"]["normal"]) * 2.0 - 1.0
    tilt = numpy.degrees(
        numpy.arccos(
            numpy.clip(normal[:, :, 2] / numpy.linalg.norm(normal, axis=2), -1, 1)
        )
    )
    return orm, tilt


def test_a_brick_wall_s_bricks_are_flat_topped(tmp_path):
    """The joint distance peaked every brick in its middle - a normal map of
    four-sided pyramids. The truths' bricks are flat with the mortar
    recessed, so most of a wall's normals point straight out."""
    _orm, tilt = _set_channels(tmp_path, WALL)
    assert float((tilt < 1.0).mean()) > 0.4


def test_a_brick_wall_s_joints_are_rougher_than_its_faces(tmp_path):
    """The truths' roughness follows their height - the joints roughest
    (a brick wall -0.36) - and a constant roughness gave mortar and brick
    the same."""
    orm, _tilt = _set_channels(tmp_path, WALL)
    joint = {}
    procedural.write_procedural_base_color(
        tmp_path / "geometry.png",
        kind="brick",
        scale_cells=8.0,
        width_px=RESOLUTION,
        height_px=RESOLUTION,
        joint_height_out=joint,
        **palette_for_description(WALL, path="brick"),
    )
    roughness = orm[:, :, 1]
    assert (
        roughness[joint["height"] < 0.1].mean()
        > roughness[joint["height"] > 0.5].mean() + 0.01
    )


def test_a_polished_marble_is_far_flatter_than_a_rough_rock(tmp_path):
    """One normal strength gave a polished marble 9.5 degrees of relief
    against its truths' 0.4, and a rock less than its truths' 17."""
    _orm, marble = _set_channels(tmp_path / "marble", "white marble, polished, smooth")
    _orm, rock = _set_channels(tmp_path / "rock", "grey cliff rock, rough")
    assert float(marble.mean()) < 2.0
    assert float(rock.mean()) > 10.0


def test_an_ashlar_wall_lays_blocks_of_unequal_length_and_still_tiles():
    """The truths' natural-stone walls (Bricks106A-113A) lay long and short
    blocks side by side, and every course was one length. The joints move
    by a wrapped hash, so the wall still tiles: its seam is one interior
    step, no more."""
    from golem_blender.pbr import pattern

    cell, edge, _grid, _face = pattern.brick_field(512, 8, ashlar=True)
    lengths = []
    for row in range(32, 512, 64):
        joints = numpy.flatnonzero(numpy.diff(cell[row]) != 0)
        lengths.extend(numpy.diff(joints).tolist())
    lengths = numpy.asarray(lengths, dtype=float)
    assert lengths.std() / lengths.mean() > 0.15
    step = float(numpy.abs(numpy.diff(edge, axis=1)).max())
    assert float(numpy.abs(edge[:, 0] - edge[:, -1]).max()) <= step + 1e-9
    assert float(numpy.abs(edge[0] - edge[-1]).max()) <= step + 1e-9


def test_a_rusted_iron_with_no_layers_composes_its_rust(tmp_path):
    """With no layers given, the base's own words compose them: a rusted
    iron comes out with rust on it, where one pattern drew a grey sheet."""
    written = write_layered_texture_set(
        tmp_path,
        "Set",
        {"description": "damaged, iron, metal, old, rusted"},
        [],
        8.0,
        RESOLUTION,
    )
    albedo = _pixels(written["paths"]["base_color"])
    rusty = (albedo[:, :, 0] - albedo[:, :, 2]) > 0.12
    assert float(rusty.mean()) > 0.2
    assert "metal" in written["kinds"] and len(written["kinds"]) == 2


def test_a_moss_layer_does_not_raise_its_rock_s_relief(tmp_path):
    """The truths' mossy rocks tilt as a rock does (Rock064 15.4 degrees,
    a rock 16.9); weighting the set's strength by the moss's coverage drew
    its own 29 degrees in - 22.4."""
    _orm, mossy = _set_channels(tmp_path / "mossy", "gray, mossy, rock, rough")
    _orm, bare = _set_channels(tmp_path / "bare", "gray, rock, rough")
    assert float(mossy.mean()) < 1.15 * float(bare.mean())


def test_an_ashlar_wall_tiles_in_its_colour_too(tmp_path):
    """The brick face's grit was laid on the unshifted brick grid, so in an
    ashlar block it changed mid-block - and at the wrap: the wall's step
    across the wrap read 8.26 against its interior columns' 99th
    percentile of 5.91 (at 1024)."""
    size = 1024
    description = "bricks, natural, stone"
    path = procedural.write_procedural_base_color(
        tmp_path / "ashlar.png",
        kind="brick",
        scale_cells=10.0,
        width_px=size,
        height_px=size,
        **palette_for_description(description, path="brick"),
    )
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        values = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(values)
    finally:
        bpy.data.images.remove(image)
    luma = values.reshape((size, size, 4))[:, :, :3].mean(axis=2)
    wrap = float(numpy.abs(luma[:, 0] - luma[:, -1]).mean())
    columns = numpy.abs(numpy.diff(luma, axis=1)).mean(axis=0)
    assert wrap <= float(numpy.percentile(columns, 99))


def test_a_smooth_plastic_is_far_flatter_than_a_plaster(tmp_path):
    """The truths' smooth plastics tilt 0.5-0.7 degrees; as a smooth flat
    sheet they took 4.6."""
    _orm, plastic = _set_channels(tmp_path / "plastic", "plastic, smooth, white")
    _orm, plaster = _set_channels(tmp_path / "plaster", "plaster, rough, white, wall")
    assert float(plastic.mean()) < 1.5
    assert float(plaster.mean()) > 3.0


def test_a_brick_wall_s_height_map_sets_its_joints_low(tmp_path):
    """The set writes the height its normal was made from, 0 the lowest: a
    wall is mostly flat faces with narrow joints sunk into them, so its
    height skews LOW - inverted, the joints would stand proud."""
    written = write_layered_texture_set(
        tmp_path, "Set", {"description": WALL}, [], 8.0, RESOLUTION
    )
    height = _pixels(written["paths"]["height"])[:, :, 0]
    standard = (height - height.mean()) / height.std()
    assert float((standard**3).mean()) < -0.5


def _height_and_luma(tmp_path: Path, description: str):
    written = write_layered_texture_set(
        tmp_path, "Set", {"description": description}, [], 12.0, RESOLUTION
    )
    height = _pixels(written["paths"]["height"])[:, :, 0]
    albedo = _pixels(written["paths"]["base_color"])
    luma = albedo @ numpy.array([0.2126, 0.7152, 0.0722])
    return height, luma


def test_a_plaster_s_relief_is_not_its_colour(tmp_path):
    """The height was the albedo's luma (r 0.75-0.94 for every kind) where
    the truths' displacement is nearly independent of the colour - a flat
    sheet's median r is -0.06 - so the normal map repeated the colour."""
    height, luma = _height_and_luma(tmp_path, "clean, plaster, white")
    assert abs(float(numpy.corrcoef(height.ravel(), luma.ravel())[0, 1])) < 0.4


def test_an_asphalt_s_relief_skews_low(tmp_path):
    """An asphalt's surface is a plane with pits in it: the truths' skew is
    -1.30, and the luma's skew was about nothing."""
    height, _luma = _height_and_luma(tmp_path, "asphalt, gray, road")
    standard = (height - height.mean()) / height.std()
    assert float((standard**3).mean()) < -0.8


def test_a_set_s_occlusion_is_as_dark_and_as_varied_as_its_kind_s(tmp_path):
    """The AO was one less 0.6 of the cavity mask, so every set's AO read a
    spread of about 0.14 and a mean of 0.91, where a parquet's truths read
    0.030 and 0.983 and an asphalt's 0.056 and 0.814."""
    floor = write_layered_texture_set(
        tmp_path / "floor",
        "Set",
        {"description": "floor, parquet, planks, wood"},
        [],
        8.0,
        RESOLUTION,
    )
    road = write_layered_texture_set(
        tmp_path / "road",
        "Set",
        {"description": "asphalt, gray, road"},
        [],
        8.0,
        RESOLUTION,
    )
    floor_ao = _pixels(floor["paths"]["orm"])[:, :, 0]
    road_ao = _pixels(road["paths"]["orm"])[:, :, 0]
    assert float(floor_ao.std()) < 0.06
    assert float(road_ao.mean()) < float(floor_ao.mean()) - 0.1


# --- the height map's RANGE follows its kind --------------------------------
#
# A displacement shader reads the Height map's own values as depth, so a
# map that always spans 0..1 gives every material the same relief. The
# truths' own displacement maps do not: measured over the four benchmark
# sets, a metal's spans 0.135 at the median and a rock's 0.757. So the
# written Height is placed in the kind's measured range, and the metadata
# says which range it is in.

ASPHALT = "asphalt, gray, road"
GRAVEL = "gravel, ground, stones"


def _height_span(path) -> float:
    """The written height's 1st-to-99th percentile span, as a shader reads it."""
    height = _pixels(path)[:, :, 0]
    return float(numpy.percentile(height, 99) - numpy.percentile(height, 1))


def test_an_asphalt_s_height_range_is_narrower_than_a_gravel_s(tmp_path):
    """The truths' asphalts span 0.269 at the median and their rubble
    (scattered: gravel, ground, stones) 0.533.

    Written at 0..1 for every kind, ours spanned 0.52-0.99 whatever the
    material - a sheet of steel with a gravel's relief.
    """
    asphalt = write_layered_texture_set(
        tmp_path / "asphalt", "Set", {"description": ASPHALT}, [], 8.0, RESOLUTION
    )
    gravel = write_layered_texture_set(
        tmp_path / "gravel", "Set", {"description": GRAVEL}, [], 8.0, RESOLUTION
    )
    asphalt_span = _height_span(asphalt["paths"]["height"])
    gravel_span = _height_span(gravel["paths"]["height"])
    assert asphalt_span < gravel_span, (
        f"the asphalt's height spans {asphalt_span:.3f} and the gravel's "
        f"{gravel_span:.3f}: every kind is written at the same depth"
    )


def test_the_written_height_spans_its_kinds_measured_range(tmp_path):
    """The map's own low and high, checked against the table.

    A range that names 0.435..0.571 must produce a map whose lowest
    value is 0.435 and whose highest is 0.571, or the metadata is
    describing a map nobody wrote. (One PNG quantum is 1/255, so the
    tolerance is two of them.)
    """
    from golem_blender.pbr.layered_set import height_range_for

    for name, description, kind in (
        ("metal", "galvanised, metal, sheet, steel", "metal"),
        ("rock", "cliff, grey, rock", "rock"),
    ):
        written = write_layered_texture_set(
            tmp_path / name, "Set", {"description": description}, [], 8.0, RESOLUTION
        )
        height = _pixels(written["paths"]["height"])[:, :, 0]
        low, high = height_range_for(kind)
        assert abs(float(height.min()) - low) <= 2.0 / 255.0, (
            f"{kind}: the height's lowest is {height.min():.3f}, the measured "
            f"range's {low:.3f}"
        )
        assert abs(float(height.max()) - high) <= 2.0 / 255.0, (
            f"{kind}: the height's highest is {height.max():.3f}, the measured "
            f"range's {high:.3f}"
        )


def test_the_normal_map_is_unchanged_by_the_height_range(tmp_path):
    """The normal is scaled to the kind's measured TILT, not to the range.

    The issue says so, and it is the reason the range can move at all:
    if the normal were made from the ranged height, narrowing a metal's
    Height would flatten its relief with it. So the same kind's normal
    must read the same tilt whether its width range is narrow (metal) or
    wide (rock) - measured over the truths' own medians, a metal tilts
    0.7 degrees and a rock 16.9.
    """
    written = write_layered_texture_set(
        tmp_path,
        "Set",
        {"description": "galvanised, metal, sheet, steel"},
        [],
        8.0,
        RESOLUTION,
    )
    normal = _pixels(written["paths"]["normal"]) * 2.0 - 1.0
    tilt = numpy.degrees(
        numpy.arccos(
            numpy.clip(normal[:, :, 2] / numpy.linalg.norm(normal, axis=2), -1, 1)
        )
    )
    # A metal's truths tilt 0.7 degrees. Scaled to its NARROW height range
    # the relief would read far flatter still; scaled to the tilt it is
    # the measured 0.7 either way.
    assert abs(float(tilt.mean()) - 0.7) < 0.4
    # The written Height, meanwhile, spans the metal's narrow range.
    assert _height_span(written["paths"]["height"]) < 0.2


def test_the_set_reports_the_height_range_it_wrote(tmp_path):
    """A consumer sets its displacement scale from the metadata."""
    measured = write_layered_texture_set(
        tmp_path / "measured", "Set", {"description": ASPHALT}, [], 8.0, RESOLUTION
    )
    assert measured["height_range"] == [0.495, 0.764]
    assert measured["height_range_kind"] == "asphalt"
    assert measured["height_range_is_measured"] is True

    # A kind with fewer than three truths is not fitted, and says so.
    unfitted = write_layered_texture_set(
        tmp_path / "unfitted",
        "Set",
        {"description": "dark, brown, bark"},
        [],
        8.0,
        RESOLUTION,
    )
    assert unfitted["height_range"] == [0.0, 1.0]
    assert unfitted["height_range_kind"] == "bark"
    assert unfitted["height_range_is_measured"] is False
