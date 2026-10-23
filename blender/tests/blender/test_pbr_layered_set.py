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
