"""A REGENERATED texture must not be read stale.

The texture lane regenerates at the same path every iteration, and
`bpy.data.images.load(path, check_existing=True)` returns the
datablock Blender already holds for that path — with its OLD pixels.
Measured: a map written red, then regenerated blue at the same path,
was read back RED, and the agent saw no change and reported success.

So the ops that load a texture reload the pixels from disk, and this
test pins that.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _write(path, rgba, size_px=16):
    """Write a solid-colour PNG."""
    image = bpy.data.images.new(path.stem, size_px, size_px, alpha=False)
    image.pixels = list(rgba) * (size_px * size_px)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def _mean(image):
    """The mean colour of a loaded image."""
    import numpy

    flat = numpy.empty(len(image.pixels), dtype=numpy.float32)
    image.pixels.foreach_get(flat)
    array = flat.reshape((-1, 4))
    return [round(float(v), 3) for v in array[:, :3].mean(axis=0).tolist()]


def test_the_loader_sees_a_regenerated_file(empty_scene, tmp_path):
    """The loader must read the pixels on disk NOW."""
    import numpy

    from golem_blender.ops._image_loading import load_image

    path = tmp_path / "map.png"
    _write(path, RED)

    first = load_image(path)
    assert _mean(first) == [1.0, 0.0, 0.0]
    bpy.data.images.remove(first)

    # The file is regenerated at the SAME path.
    _write(path, BLUE)

    second = load_image(path)
    try:
        pixels = numpy.array(second.pixels[:4], dtype=float)
        assert pixels[2] > 0.9, (
            f"the loader read {pixels[:3]} from a file that is now blue: the "
            f"datablock was stale"
        )
    finally:
        bpy.data.images.remove(second)


def test_assigning_a_regenerated_texture_shows_the_new_pixels(empty_scene, tmp_path):
    """The op must not put the OLD map on the object."""
    from golem_blender.ops.material_nodes import assign_image_texture_material
    from golem_blender.ops.primitives import add_box, link_into_scene

    name = add_box("Subject", 0.4, 0.4, 0.4)
    link_into_scene(name)
    box = bpy.data.objects[name]

    path = _write(tmp_path / "map.png", RED)
    assign_image_texture_material(name, "Tex", path)
    first = [round(float(v), 3) for v in box.data.materials[0].diffuse_color[:3]]
    assert first == [1.0, 0.0, 0.0]

    # The same path, new content, and the op is called again.
    _write(path, BLUE)
    assign_image_texture_material(name, "Tex", path)
    second = [round(float(v), 3) for v in box.data.materials[0].diffuse_color[:3]]
    assert second == [0.0, 0.0, 1.0], (
        f"the material still shows {second}: the image datablock was stale"
    )
