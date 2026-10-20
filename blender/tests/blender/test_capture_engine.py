"""The ORDINARY inspection path must show a texture.

`render_views` is the tool every agent uses to look at an asset it has
just built. If it renders in Workbench, a textured asset shows NO
texture at all — Workbench reads only `material.diffuse_color` and
never the shader graph — so the agent that applied a texture and then
inspected it would see the texture missing and look for a bug that is
not there.

So the capture picks the engine by what the object carries: an object
with an IMAGE texture is rendered shader-accurately, and one without
keeps the fast Workbench path.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TEXTURE_RGB = (1.0, 0.0, 0.0)
DIFFUSE_RGB = (0.0, 1.0, 0.0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box():
    from golem_blender.ops.primitives import add_box, link_into_scene

    name = add_box("Subject", 0.4, 0.4, 0.4)
    link_into_scene(name)
    return bpy.data.objects[name]


def _write_image(path, rgba, size_px=16):
    image = bpy.data.images.new(path.stem, size_px, size_px, alpha=False)
    image.pixels = list(rgba) * (size_px * size_px)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def _read(path):
    import numpy

    image = bpy.data.images.load(str(path))
    try:
        flat = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(flat)
        return flat.reshape((-1, 4))
    finally:
        bpy.data.images.remove(image)


def test_a_textured_object_is_captured_shader_accurately(empty_scene, tmp_path):
    """The capture sheet must show the texture, not the viewport colour."""
    from golem_blender.capture.views import CaptureSettings, capture_views
    from golem_blender.ops.material_nodes import assign_image_texture_material

    box = _box()
    texture_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    assign_image_texture_material(box.name, "RedTex", texture_path)
    box.data.materials[0].diffuse_color = (*DIFFUSE_RGB, 1.0)

    paths = capture_views(
        box, tmp_path / "sheet", settings=CaptureSettings(resolution_px=64)
    )

    array = _read(paths["front"])
    brightest = array[int(array[:, :3].max(axis=1).argmax()), :3]
    red, green, blue = (float(value) for value in brightest)

    assert red > green, (
        f"the capture is green (r={red:.3f} g={green:.3f}): it read "
        f"diffuse_color, so the texture is invisible"
    )
    assert red > blue


def test_an_untextured_object_keeps_the_fast_path(empty_scene, tmp_path):
    """No texture means no reason to pay for the shader-accurate engine."""
    from golem_blender.capture.views import CaptureSettings, capture_views
    from golem_blender.ops.materials import assign_material

    box = _box()
    assign_material(box.name, "Plain", base_color_rgb=(0.6, 0.2, 0.2))

    paths = capture_views(
        box, tmp_path / "sheet", settings=CaptureSettings(resolution_px=64)
    )
    assert paths["front"].is_file()


def test_the_capture_restores_the_engine(empty_scene, tmp_path):
    """The scene must not be left in the engine the capture chose."""
    from golem_blender.capture.views import CaptureSettings, capture_views
    from golem_blender.ops.material_nodes import assign_image_texture_material

    box = _box()
    texture_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    assign_image_texture_material(box.name, "RedTex", texture_path)

    scene = bpy.context.scene
    before = scene.render.engine
    capture_views(box, tmp_path / "sheet", settings=CaptureSettings(resolution_px=64))
    assert scene.render.engine == before
