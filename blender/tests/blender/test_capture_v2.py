"""Inspection v2: contact sheets and X-ray capture.

Measured through Blender's own image API rather than Pillow. Blender
bundles numpy and not Pillow, so a test that needs Pillow to READ the
output cannot run in the environment the product actually ships into —
which is how these tests came to be skipped everywhere at once.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _image_size_px(image_path):
    """Read a PNG's dimensions through Blender's image API.

    Deliberately NOT the compositor's own loader: measuring an artifact
    with the code that wrote it only proves that code agrees with
    itself.
    """
    loaded_image = bpy.data.images.load(str(image_path))
    try:
        return tuple(loaded_image.size)
    finally:
        bpy.data.images.remove(loaded_image)


def _image_luminance(image_path):
    """Load a PNG as a (height, width) array of averaged RGB, 0.0-1.0."""
    import numpy

    loaded_image = bpy.data.images.load(str(image_path))
    try:
        width_px, height_px = loaded_image.size
        flat_pixels = numpy.empty(width_px * height_px * 4, dtype=numpy.float32)
        loaded_image.pixels.foreach_get(flat_pixels)
    finally:
        bpy.data.images.remove(loaded_image)
    return flat_pixels.reshape((height_px, width_px, 4))[:, :, :3].mean(axis=2)


def test_contact_sheet_tiles_every_view(empty_scene, tmp_path):
    from blended.analyze import analyze_object
    from blended.builders import CrateBuilder, CrateParameters
    from blended.capture import capture_contact_sheet

    crate_object = CrateBuilder(CrateParameters()).build()
    report = analyze_object(crate_object)
    sheet_path = capture_contact_sheet(crate_object, tmp_path, report=report)

    assert sheet_path.exists()
    sheet_width_px, sheet_height_px = _image_size_px(sheet_path)
    view_width_px, view_height_px = _image_size_px(tmp_path / "front.png")
    # 2x2 grid: the sheet is materially larger than any single view.
    assert sheet_width_px > view_width_px * 1.5
    assert sheet_height_px > view_height_px * 1.5


def test_xray_reveals_hidden_geometry(empty_scene, tmp_path):
    """A fully enclosed inner box must change the rendered pixels only
    when X-ray is on."""
    import numpy

    from blended.capture import CaptureSettings, capture_views
    from blended.ops import add_box, link_into_scene

    outer_box = bpy.data.objects[add_box("OuterShell", 1.0, 1.0, 1.0)]
    link_into_scene(outer_box.name)
    inner_box = bpy.data.objects[
        add_box("HiddenInner", 0.4, 0.4, 0.4, location_m=(0.0, 0.0, 0.3))
    ]
    link_into_scene(inner_box.name)

    plain_paths = capture_views(outer_box, tmp_path / "plain")
    xray_paths = capture_views(outer_box, tmp_path / "xray", CaptureSettings(xray=True))

    plain_luminance = _image_luminance(plain_paths["three_quarter"])
    xray_luminance = _image_luminance(xray_paths["three_quarter"])

    # Luminance is 0.0-1.0 here, not 0-255: the old Pillow threshold of
    # 8/255 becomes ~0.03.
    CHANGED_PIXEL_THRESHOLD = 0.03
    MINIMUM_CHANGED_PIXELS = 500
    changed_pixel_count = (
        numpy.abs(plain_luminance - xray_luminance) > CHANGED_PIXEL_THRESHOLD
    ).sum()
    assert changed_pixel_count > MINIMUM_CHANGED_PIXELS


def test_numpy_compositor_tiles_views_into_one_sheet(empty_scene, tmp_path):
    """The Pillow-free path must produce a real sheet, since Blender
    bundles numpy but not Pillow. This is the path production uses."""
    from blended.builders import CrateBuilder, CrateParameters
    from blended.capture import capture_views
    from blended.capture.compose import compose_grid_numpy

    crate_object = CrateBuilder(CrateParameters()).build()
    view_paths = capture_views(crate_object, tmp_path)
    sheet_path = compose_grid_numpy(view_paths, tmp_path / "numpy_sheet.png")

    assert sheet_path.exists()
    sheet_width_px, sheet_height_px = _image_size_px(sheet_path)
    view_width_px, view_height_px = _image_size_px(view_paths["front"])
    assert sheet_width_px > view_width_px * 1.5
    assert sheet_height_px > view_height_px * 1.5


def test_contact_sheet_composes_without_pillow(empty_scene, tmp_path, monkeypatch):
    """Forced down the Pillow-free branch even on a box that has Pillow."""
    import blended.capture.compose as compose_module
    from blended.builders import CrateBuilder, CrateParameters
    from blended.capture import capture_contact_sheet

    numpy_sheet_paths = []
    real_compose_grid_numpy = compose_module.compose_grid_numpy

    def spy_compose_grid_numpy(view_paths, output_path):
        numpy_sheet_paths.append(output_path)
        return real_compose_grid_numpy(view_paths, output_path)

    monkeypatch.setattr(compose_module, "pillow_available", lambda: False)
    monkeypatch.setattr(compose_module, "compose_grid_numpy", spy_compose_grid_numpy)
    crate_object = CrateBuilder(CrateParameters()).build()
    sheet_path = capture_contact_sheet(crate_object, tmp_path)
    assert numpy_sheet_paths == [sheet_path], "the Pillow-free numpy branch did not run"
    assert sheet_path.exists()
    assert sheet_path.stat().st_size > 0


def test_the_sheet_can_see_underneath(empty_scene, tmp_path):
    """A view nobody asserts is a view that can silently disappear.

    Measured 2026-08-22 (iterations 10 and 11): for a three-legged
    stool, `top` is blind to the legs — the seat covers them — and
    `front` projects the 120 and 240 degree legs to the same world x, so
    they overlap. Neither can answer "are the legs evenly spaced". Only
    a view from below has no occluder.
    """
    from blended.capture.views import ORTHOGRAPHIC_VIEWS, VIEW_DIRECTIONS

    assert VIEW_DIRECTIONS["bottom"] == (0.0, 0.0, -1.0)
    assert "bottom" in ORTHOGRAPHIC_VIEWS
    assert VIEW_DIRECTIONS["bottom"] != VIEW_DIRECTIONS["top"]


def test_every_named_view_is_actually_rendered(empty_scene, tmp_path):
    from blended.capture.views import VIEW_DIRECTIONS, capture_views
    from blended.ops.primitives import add_box, link_into_scene

    box = bpy.data.objects[add_box("ViewBox", 0.4, 0.3, 0.2)]
    link_into_scene(box.name)
    view_paths = capture_views(box, tmp_path)

    assert set(view_paths) == set(VIEW_DIRECTIONS)
    for name, path in view_paths.items():
        assert path.exists(), name
        assert path.stat().st_size > 0, name
