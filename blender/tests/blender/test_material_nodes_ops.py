"""Procedural and image-texture material ops: node graph + Workbench render.

The shader graph must actually drive the render, and a re-run must not
stack duplicate nodes — the agent-computer-interface contract for
texture materials.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

COLOR_A_RGB = (0.9, 0.1, 0.1)
COLOR_B_RGB = (0.1, 0.1, 0.9)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box():
    from blended.ops.primitives import add_box, link_into_scene

    box_name = add_box("Subject", 0.2, 0.2, 0.2)
    link_into_scene(box_name)
    return bpy.data.objects[box_name]


def _save_test_png(path, width_px=64, height_px=64, fill_rgb=(0.9, 0.2, 0.3)):
    """Write a small solid-colour PNG via bpy.data.images and save_render."""
    image = bpy.data.images.new("test_tex", width_px, height_px)
    r, g, b = fill_rgb
    pixels = [r, g, b, 1.0] * (width_px * height_px)
    image.pixels = pixels
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    return path


# ── procedural ───────────────────────────────────────────────────────


def test_noise_procedural_links_base_color_and_reports(empty_scene):
    from blended.ops.material_nodes import (
        assign_procedural_material,
        material_report,
    )

    box = _box()
    assign_procedural_material(box.name, "ProcNoise", "noise", color_a_rgb=COLOR_A_RGB)

    report = material_report(box.name)
    assert report.base_color_linked is True
    assert "ShaderNodeTexNoise" in report.node_type_counts
    assert "noise" in report.texture_kinds


def test_procedural_fills_exactly_one_slot(empty_scene):
    from blended.ops.material_nodes import assign_procedural_material

    box = _box()
    assign_procedural_material(box.name, "ProcNoise", "noise")

    assert len(box.data.materials) == 1
    assert box.data.materials[0] is not None
    assert box.data.materials[0].name == "ProcNoise"


def test_rerun_does_not_duplicate_nodes_or_materials(empty_scene):
    from blended.ops.material_nodes import assign_procedural_material

    box = _box()
    assign_procedural_material(box.name, "ProcNoise", "noise")
    assign_procedural_material(box.name, "ProcNoise", "noise")

    assert len([m for m in bpy.data.materials if m.name == "ProcNoise"]) == 1
    mat = box.data.materials[0]
    noise_nodes = [
        n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeTexNoise"
    ]
    assert len(noise_nodes) == 1, "re-run must not stack duplicate texture nodes"


def test_unknown_kind_raises_value_error(empty_scene):
    from blended.ops.material_nodes import assign_procedural_material

    box = _box()
    with pytest.raises(ValueError):
        assign_procedural_material(box.name, "BadKind", "voronoi")


# ── image texture ────────────────────────────────────────────────────


def test_image_texture_material_reports_path(empty_scene, tmp_path):
    from blended.ops.material_nodes import (
        assign_image_texture_material,
        material_report,
    )

    png_path = tmp_path / "test_tile.png"
    _save_test_png(png_path)

    box = _box()
    assign_image_texture_material(box.name, "ImgMat", png_path)

    report = material_report(box.name)
    assert "ShaderNodeTexImage" in report.node_type_counts
    assert len(report.image_paths) == 1
    assert (
        str(png_path) in report.image_paths[0]
        or "test_tile.png" in report.image_paths[0]
    )


def test_image_texture_missing_file_raises(empty_scene, tmp_path):
    from blended.ops.material_nodes import assign_image_texture_material

    box = _box()
    with pytest.raises(FileNotFoundError):
        assign_image_texture_material(
            box.name, "Missing", tmp_path / "no_such_file.png"
        )


# ── Workbench render ─────────────────────────────────────────────────


def test_checker_render_is_not_grey(empty_scene, tmp_path):
    """A checker with red/blue must show colour in a Workbench render,
    not grey — proving the diffuse_color sync makes Workbench honour the
    material (the shader graph alone would not)."""
    from blended.capture.views import capture_views
    from blended.ops.material_nodes import assign_procedural_material

    box = _box()
    assign_procedural_material(
        box.name, "Checker", "checker", color_a_rgb=COLOR_A_RGB, color_b_rgb=COLOR_B_RGB
    )

    paths = capture_views(box, tmp_path)
    image = bpy.data.images.load(str(paths["front"]))
    width, height = image.size
    pixels = list(image.pixels)
    centre_index = ((height // 2) * width + (width // 2)) * 4
    red, green, blue, alpha = pixels[centre_index : centre_index + 4]

    assert alpha == pytest.approx(1.0), "centre pixel is background, not the box"
    # color_a is predominantly red; the centre pixel must carry more red
    # than green (grey would be roughly equal).
    assert red > green, (
        f"render is grey, not showing checker colour: {(red, green, blue)}"
    )
