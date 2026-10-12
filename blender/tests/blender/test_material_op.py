"""assign_material must produce a material the RENDER can show.

Measured 2026-08-22 (iteration 1): the agent set the Principled BSDF
base colour to terracotta, the Workbench render came back grey, the
vision model reported the discrepancy as a deviation, and the agent
spent tool calls chasing a defect that did not exist. Workbench reads
`material.diffuse_color`, never the shader graph.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TERRACOTTA_RGB = (0.72, 0.35, 0.22)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box():
    from blended.ops.primitives import add_box, link_into_scene

    box_name = add_box("Subject", 0.2, 0.2, 0.2)
    link_into_scene(box_name)
    return bpy.data.objects[box_name]


def test_assign_material_fills_one_slot(empty_scene):
    from blended.ops.materials import assign_material

    box = _box()
    assign_material(box.name, "Terracotta", TERRACOTTA_RGB)

    assert len(box.data.materials) == 1
    assert box.data.materials[0] is not None
    assert box.data.materials[0].name == "Terracotta"


def test_assign_material_sets_both_colour_fields(empty_scene):
    """The shader colour and the Workbench colour must not disagree."""
    from blended.ops.materials import assign_material

    box = _box()
    material_name = assign_material(box.name, "Terracotta", TERRACOTTA_RGB)

    material = bpy.data.materials[material_name]
    principled = material.node_tree.nodes["Principled BSDF"]
    shader_rgb = tuple(principled.inputs["Base Color"].default_value)[:3]
    viewport_rgb = tuple(material.diffuse_color)[:3]

    assert shader_rgb == pytest.approx(TERRACOTTA_RGB)
    assert viewport_rgb == pytest.approx(TERRACOTTA_RGB)


def test_a_shared_material_name_survives_reassignment(empty_scene):
    """A material name is a shared resource across parts.

    Measured 2026-08-22 (iteration 46): the agent assigned "CrateWood"
    to the crate body, then assigned the same name to the lid. The old
    remove-and-recreate left the body's slot dangling to None — the
    assembly failed the material gate with 0 assigned in 1 slot. The
    datablock must be reused, so every object referencing the name
    keeps its assignment."""
    from blended.ops.materials import assign_material
    from blended.ops.primitives import add_box, link_into_scene

    body = bpy.data.objects[add_box("Body", 0.5, 0.5, 0.4)]
    link_into_scene(body.name)
    lid = bpy.data.objects[add_box("Lid", 0.5, 0.5, 0.06)]
    link_into_scene(lid.name)

    assign_material(body.name, "CrateWood", TERRACOTTA_RGB)
    assign_material(lid.name, "CrateWood", TERRACOTTA_RGB)

    assert body.data.materials[0] is not None, "the body's slot dangled to None"
    assert lid.data.materials[0] is not None
    assert body.data.materials[0].name == "CrateWood"
    assert lid.data.materials[0] is body.data.materials[0], (
        "both parts must reference the SAME datablock"
    )
    assert len([m for m in bpy.data.materials if m.name == "CrateWood"]) == 1


def test_the_render_actually_shows_the_colour(empty_scene, tmp_path):
    """The assertion that closes the loop: pixels, not properties."""
    from blended.capture.views import capture_views
    from blended.ops.materials import assign_material

    box = _box()
    assign_material(box.name, "Terracotta", TERRACOTTA_RGB)
    paths = capture_views(box, tmp_path)

    image = bpy.data.images.load(str(paths["front"]))
    width, height = image.size
    pixels = list(image.pixels)
    centre_index = ((height // 2) * width + (width // 2)) * 4
    red, green, blue, alpha = pixels[centre_index : centre_index + 4]

    assert alpha == pytest.approx(1.0), "centre pixel is background, not the box"
    # Workbench applies studio lighting, so absolute values shift — but a
    # terracotta box must still be unmistakably redder than it is blue.
    assert red > blue, (
        f"render is not showing the material colour: {(red, green, blue)}"
    )
    assert red > green > blue
