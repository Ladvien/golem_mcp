"""The procedural base colour: a surface's colour, computed.

The point of it is that it TILES. A generated map's seam is a
property of the SAMPLE - four generations of one prompt measured
1.38x, 1.57x, 1.10x and 1.38x the texture's largest ordinary
features - and a procedural map's is 0.025x, because the pattern is
evaluated on a wrapped lattice.

So the tests are about the seam, and about the one thing that can
break it: the camera. If the camera does not see the WHOLE plane,
the image is a cropping of the pattern, and a cropping's edge is not
the pattern's edge.
"""

from __future__ import annotations

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_the_procedural_colour_tiles(empty_scene, tmp_path):
    """Its edge meets its own edge, so the map can be repeated."""
    from golem_blender.pbr import paths as pbr_paths
    from golem_blender.pbr.procedural import write_procedural_base_color

    path = write_procedural_base_color(
        tmp_path / "T_Cobble_BaseColor.png",
        kind="voronoi",
        scale_cells=16.0,
        width_px=512,
        height_px=512,
    )

    ratio = pbr_paths.tile_seam_ratio(path)
    # The threshold is the reference's: ambientcg's own maps, which are
    # made to tile, measure 0.32x to 0.47x, and the generated map the
    # lane made measured 1.38x. The procedural map has to be in the
    # reference's range - it is periodic by construction, but the
    # pattern's warp is what makes the cells irregular, and the warp
    # is what puts a little back into the seam. Measured, 0.40x.
    assert ratio < 0.50, (
        f"the procedural colour's seam is {ratio:.3f}x the interior's largest "
        f"features, so it does not tile - the reference sets are at 0.32x "
        f"to 0.47x"
    )


def test_the_procedural_colour_fills_the_frame(empty_scene, tmp_path):
    """The image is the pattern, with no border round it.

    A border is not a border once it is in the texture: it is a seam
    that the map carries, and the map is supposed to tile.
    """
    import numpy

    from golem_blender.pbr.procedural import write_procedural_base_color

    path = write_procedural_base_color(
        tmp_path / "T_Cobble_BaseColor.png",
        kind="voronoi",
        scale_cells=16.0,
        width_px=512,
        height_px=512,
    )
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    luma = pixels.reshape((height, width, 4))[:, :, 0]

    # The plane fills the frame, so the corner and the middle of the
    # edge are the same KIND of thing: a stone's interior, or the
    # pattern's own variation. A border would make the corner flat.
    corner = float(luma[0, 0])
    edge_middle = float(luma[0, width // 2])
    assert abs(corner - edge_middle) < 0.15, (
        f"the corner is {corner:.3f} and the middle of the top edge is "
        f"{edge_middle:.3f}: the pattern does not fill the frame, so the "
        f"image has a border and the border is a seam"
    )


def test_the_procedural_colour_carries_a_joint_network(empty_scene, tmp_path):
    """The lane's relief builder has to find the joints in it.

    The ORM and the normal map are baked from a height field derived
    from the base colour, so a base colour with no joint network in it
    would bake to nothing.
    """
    import numpy

    from golem_blender.ops.relief import (
        JOINT_BLUR_CELLS,
        JOINT_DIP_GAIN,
        _box_blur,
    )
    from golem_blender.pbr.procedural import write_procedural_base_color

    path = write_procedural_base_color(
        tmp_path / "T_Cobble_BaseColor.png",
        kind="voronoi",
        scale_cells=16.0,
        width_px=512,
        height_px=512,
    )
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    luma = pixels.reshape((height, width, 4))[:, :, 0]

    cells = 64
    field = luma.reshape(cells, height // cells, cells, width // cells).mean(
        axis=(1, 3)
    )
    blurred = _box_blur(field, JOINT_BLUR_CELLS)
    joint = numpy.clip(blurred - field, 0.0, None)
    peak = float(joint.max())
    assert peak > 0.0, "the procedural colour has no joint network in it"
    dip = numpy.clip((joint / peak) * JOINT_DIP_GAIN, 0.0, 1.0)
    signal = 100.0 * float((dip > 0.05).mean())
    assert signal > 5.0, (
        f"the joint network carries signal on only {signal:.2f}% of the cells"
    )


def test_a_grey_surface_stays_grey_when_it_is_lightened(empty_scene, tmp_path):
    """The lift to the description's value keeps the surface's hue.

    The lift moved every pixel along that pixel's OWN colour over its
    luma, and a near-black pixel's ratio is quantisation noise: the
    grey cloth came out with pure red specks - a saturation of 1.0 on
    a palette whose own is 0.02.
    """
    import numpy

    from golem_blender.pbr.palette import palette_for_description
    from golem_blender.pbr.procedural import write_procedural_base_color

    palette = palette_for_description("fabric, rough", path="woven")
    path = write_procedural_base_color(
        tmp_path / "T_Cloth_BaseColor.png",
        kind="woven",
        scale_cells=40.0,
        width_px=256,
        height_px=256,
        **palette,
    )
    image = bpy.data.images.load(str(path))
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    rgb = pixels.reshape((height, width, 4))[:, :, :3]
    saturation = rgb.max(axis=2) - rgb.min(axis=2)
    assert float(saturation.max()) < 0.15, (
        f"a grey cloth carries a pixel of saturation {saturation.max():.2f}"
    )


@pytest.mark.parametrize("scale_cells", [4.0, 16.0])
def test_a_tile_floor_s_grout_is_a_hairline_whatever_the_tile_s_size(
    empty_scene, tmp_path, scale_cells
):
    """A tile's grout is a pixel or two wide, as the truths' own are.

    The grout was a fraction of the tile's half-width, so it grew with
    the tile: 15-27 pixels in 1024, soft, where the truths measure 1-4.
    """
    import numpy

    from golem_blender.pbr.palette import palette_for_description
    from golem_blender.pbr.procedural import write_procedural_base_color

    palette = palette_for_description("tiles, white", path="brick")
    path = write_procedural_base_color(
        tmp_path / "T_Tiles_BaseColor.png",
        kind="brick",
        scale_cells=scale_cells,
        width_px=1024,
        height_px=1024,
        **palette,
    )
    image = bpy.data.images.load(str(path))
    pixels = numpy.empty(1024 * 1024 * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    luma = pixels.reshape((1024, 1024, 4))[:, :, :3].mean(axis=2)
    profile = luma.mean(axis=0)
    floor = float(numpy.median(profile))
    grout = profile < floor - (floor - float(profile.min())) / 2
    runs, run = [], 0
    for in_grout in numpy.concatenate([grout, grout[:1]]):
        if in_grout:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    assert runs, "the tile floor carries no grout"
    assert max(runs) <= 4, f"the grout is {max(runs)} pixels wide in 1024"


def test_an_unknown_colour_kind_is_refused(empty_scene, tmp_path):
    """A misspelled kind names itself rather than writing nothing."""
    from golem_blender.pbr.procedural import write_procedural_base_color

    with pytest.raises(ValueError, match="Unknown procedural colour kind"):
        write_procedural_base_color(
            tmp_path / "T_Cobble_BaseColor.png", kind="voronoii"
        )
