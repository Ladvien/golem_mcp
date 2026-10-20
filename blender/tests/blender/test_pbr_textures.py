"""The PBR texture lane in a REAL Blender: the preview shows the texture.

The load-bearing check of the whole lane. Workbench reads only
``material.diffuse_color`` and never the shader graph, so a texture
reviewed through the existing contact sheet is reviewed BLIND. These
tests put a solid-red texture against a green ``diffuse_color`` and
assert that the EEVEE preview comes back RED, which is the difference
between a texture the agent can see and one it cannot.

They also pin the ORM routing: the AO channel is MULTIPLIED into the
base colour, not routed through an Ambient Occlusion node (that route
renders a neutral grey and discards the texture's colour).
"""

from __future__ import annotations

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

# The contradiction the tests use: a red TEXTURE on a green VIEWPORT
# colour. Whichever one the render shows tells us which the engine read.
TEXTURE_RGB = (1.0, 0.0, 0.0)
DIFFUSE_RGB = (0.0, 1.0, 0.0)
# The ORM: R = AO = 1.0 (no occlusion), G = roughness = 0.5, B = metallic = 0.
ORM_RGBA = (1.0, 0.5, 0.0, 1.0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _box(name: str = "Subject", size_m: float = 0.4):
    from golem_blender.ops.primitives import add_box, link_into_scene

    box_name = add_box(name, size_m, size_m, size_m)
    link_into_scene(box_name)
    return bpy.data.objects[box_name]


def _write_image(
    path: Path, rgba: tuple[float, float, float, float], size_px: int = 16
):
    """Write a solid-colour PNG through Blender's image API."""
    image = bpy.data.images.new(path.stem, size_px, size_px, alpha=False)
    image.colorspace_settings.name = "Non-Color"
    image.pixels = list(rgba) * (size_px * size_px)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def _read_pixels(path: Path):
    """The image's pixels as a numpy (h, w, 4) array."""
    import numpy

    image = bpy.data.images.load(str(path))
    try:
        flat = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(flat)
        return flat.reshape((-1, 4))
    finally:
        bpy.data.images.remove(image)


def _brightest(array):
    """The brightest pixel of the image, as a 3-tuple."""
    brightest_index = int(array[:, :3].max(axis=1).argmax())
    return tuple(float(value) for value in array[brightest_index, :3])


# --- the preview ------------------------------------------------------------


def test_the_preview_shows_the_texture_not_the_viewport_colour(empty_scene, tmp_path):
    """The EEVEE preview reads the shader graph, so it shows the RED texture."""
    from golem_blender.capture.texture_preview import render_texture_preview
    from golem_blender.ops.material_nodes import assign_image_texture_material

    box = _box()
    texture_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    assign_image_texture_material(box.name, "RedTex", texture_path)
    # The viewport colour contradicts the texture on purpose.
    box.data.materials[0].diffuse_color = (*DIFFUSE_RGB, 1.0)

    preview_path = render_texture_preview(
        box, tmp_path / "preview.png", resolution_px=64
    )
    red, green, blue = _brightest(_read_pixels(preview_path))

    assert red > green, (
        f"the preview is green (r={red:.3f} g={green:.3f}): it read "
        f"diffuse_color, not the texture"
    )
    assert red > blue
    assert red > 0.1, f"the preview is black (r={red:.3f}): no light reached it"


def test_the_preview_refuses_the_workbench_engine(empty_scene, tmp_path):
    """Workbench cannot show a texture, so the preview says so."""
    from golem_blender.capture.texture_preview import render_texture_preview

    box = _box()
    with pytest.raises(ValueError, match="Workbench"):
        render_texture_preview(
            box, tmp_path / "preview.png", engine="BLENDER_WORKBENCH"
        )


def test_the_preview_camera_aims_at_the_largest_face(empty_scene):
    """A flat slab's camera must look at its TOP, from above it.

    The camera used to aim down the object's WIDEST extent. A flat
    slab has two equal widest extents, so the camera landed edge-on to
    the surface and the preview showed a flat field.

    It also used to be placed on the NEGATIVE side of that face, so
    for a slab the camera ended up UNDER the floor looking up at the
    slab's underside — measured: a camera at z = -4.26 for a slab
    whose top is at z = 0.03.
    """
    from golem_blender.capture.texture_preview import _facing_direction

    box = _box(size_m=2.0)
    # A slab: wide in X and Y, thin in Z.
    for vertex in box.data.vertices:
        vertex.co.z = vertex.co.z * 0.05
    box.data.update()

    direction = _facing_direction(box)
    # The largest face spans X and Y, so the camera looks down Z — and
    # from ABOVE, on the positive side.
    assert abs(direction.z) == 1.0
    assert direction.z > 0.0, "the camera is on the underside of the slab"


def test_the_preview_leaves_the_scene_as_it_found_it(empty_scene, tmp_path):
    """The camera and the light are removed, and the engine is restored."""
    from golem_blender.capture.texture_preview import render_texture_preview

    box = _box()
    scene = bpy.context.scene
    previous_engine = scene.render.engine
    previous_objects = {obj.name for obj in scene.objects}

    render_texture_preview(box, tmp_path / "preview.png", resolution_px=32)

    assert scene.render.engine == previous_engine
    assert {obj.name for obj in scene.objects} == previous_objects


def test_the_contact_sheet_is_written_with_its_five_views(empty_scene, tmp_path):
    from golem_blender.capture.texture_preview import render_texture_contact_sheet

    box = _box()
    sheet_path = render_texture_contact_sheet(box, tmp_path / "sheet", resolution_px=32)

    assert sheet_path.is_file()
    for view_name in ("front", "right", "top", "bottom", "three_quarter"):
        assert (tmp_path / "sheet" / f"{view_name}.png").is_file()


# --- the ORM routing --------------------------------------------------------


def test_the_orm_ao_is_multiplied_into_the_base_colour(empty_scene, tmp_path):
    """The base colour survives the ORM: the AO multiplies, it does not replace."""
    from golem_blender.capture.texture_preview import render_texture_preview
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    box = _box()
    base_color_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    orm_path = _write_image(tmp_path / "orm.png", ORM_RGBA)
    assign_pbr_texture_set(box.name, "RedSet", base_color_path, orm_path)

    preview_path = render_texture_preview(
        box, tmp_path / "preview.png", resolution_px=64
    )
    red, green, blue = _brightest(_read_pixels(preview_path))

    assert red > green and red > blue, (
        f"the preview is not red-dominant (r={red:.3f} g={green:.3f} "
        f"b={blue:.3f}): the ORM's AO replaced the base colour"
    )


def test_the_report_says_what_the_graph_has_wired(empty_scene, tmp_path):
    from golem_blender.ops.pbr_textures import (
        assign_pbr_texture_set,
        pbr_texture_report,
    )

    box = _box()
    base_color_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    orm_path = _write_image(tmp_path / "orm.png", ORM_RGBA)
    assign_pbr_texture_set(box.name, "RedSet", base_color_path, orm_path)

    report = pbr_texture_report(box.name)

    assert report.material_name == "RedSet"
    assert report.base_color_linked is True
    assert report.metallic_linked is True
    assert report.roughness_linked is True
    assert report.ao_multiplied is True
    assert report.orm_channels == "R=ao,G=roughness,B=metallic"
    assert report.base_color_path.endswith("red.png")
    assert report.orm_path.endswith("orm.png")


def test_the_orm_is_loaded_as_non_color(empty_scene, tmp_path):
    """The ORM carries VALUES, so it must not be gamma-decoded on the way in.

    Loaded as sRGB, a roughness of 0.7 reaches the shader as
    0.7^(1/2.2) = 0.85 — the material is quietly wrong.
    """
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    box = _box()
    base_color_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    orm_path = _write_image(tmp_path / "orm.png", ORM_RGBA)
    assign_pbr_texture_set(box.name, "RedSet", base_color_path, orm_path)

    material = box.data.materials[0]
    orm_node = next(
        node
        for node in material.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage" and node.name == "blended_pbr_orm"
    )
    assert orm_node.image.colorspace_settings.name == "Non-Color"


def test_a_missing_map_is_refused_with_its_path(empty_scene, tmp_path):
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    box = _box()
    with pytest.raises(FileNotFoundError):
        assign_pbr_texture_set(box.name, "RedSet", tmp_path / "absent.png")


def test_reapplying_updates_the_material_instead_of_stacking_one(empty_scene, tmp_path):
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    box = _box()
    red_path = _write_image(tmp_path / "red.png", (*TEXTURE_RGB, 1.0))
    blue_path = _write_image(tmp_path / "blue.png", (0.0, 0.0, 1.0, 1.0))

    assign_pbr_texture_set(box.name, "Set", red_path)
    assign_pbr_texture_set(box.name, "Set", blue_path)

    assert len(box.data.materials) == 1
    assert len([m for m in bpy.data.materials if m.name == "Set"]) == 1
    image_nodes = [
        node
        for node in box.data.materials[0].node_tree.nodes
        if node.bl_idname == "ShaderNodeTexImage"
    ]
    assert len(image_nodes) == 1


# --- the bake ---------------------------------------------------------------


def test_baking_writes_an_orm_with_a_varying_occlusion_channel(empty_scene, tmp_path):
    from golem_blender.ops.pbr_bake import bake_orm_map
    from golem_blender.ops.uv import unwrap_uvs

    box = _box()
    unwrap_uvs(box.name)

    orm_path = Path(
        bake_orm_map(box.name, tmp_path / "T_Subject_ORM.png", resolution_px=128)
    )
    assert orm_path.is_file()

    array = _read_pixels(orm_path)
    assert array.shape[0] == 128 * 128
    # R is the baked occlusion: it VARIES over the mesh, or the bake did
    # nothing.
    distinct = {round(float(value), 3) for value in array[:, 0]}
    assert len(distinct) > 1, "the ORM's occlusion channel is constant"
    # G and B are the constants the op was given — the op's OWN
    # defaults, read from the module rather than written out here, so
    # a change to the default cannot leave this asserting a number
    # the op no longer uses.
    from golem_blender.ops.pbr_bake import DEFAULT_METALLIC, DEFAULT_ROUGHNESS

    assert all(abs(float(value) - DEFAULT_ROUGHNESS) < 0.02 for value in array[:, 1])
    assert all(abs(float(value) - DEFAULT_METALLIC) < 0.02 for value in array[:, 2])


def test_baking_a_normal_map_of_relief_produces_a_varying_map(empty_scene, tmp_path):
    """A SMOOTH SHADED mesh with relief bakes a varying normal map.

    The map records the difference between the shading normal and the
    face normal, so a FLAT SHADED mesh bakes a constant map — measured:
    1 distinct triple flat, 17 smooth, on the same bevelled box.
    """
    from golem_blender.ops.modifiers import add_bevel, apply_all_modifiers
    from golem_blender.ops.pbr_bake import bake_normal_map
    from golem_blender.ops.uv import unwrap_uvs

    box = _box()
    add_bevel(box.name, width_m=0.08, segment_count=3)
    apply_all_modifiers(box.name)
    unwrap_uvs(box.name, method="SMART_PROJECT")

    bpy.ops.object.select_all(action="DESELECT")
    box.select_set(True)
    bpy.context.view_layer.objects.active = box
    bpy.ops.object.shade_smooth()

    normal_path = Path(
        bake_normal_map(box.name, tmp_path / "T_Subject_Normal.png", resolution_px=128)
    )
    assert normal_path.is_file()

    array = _read_pixels(normal_path)
    triples = {
        (round(float(row[0]), 3), round(float(row[1]), 3), round(float(row[2]), 3))
        for row in array
    }
    assert len(triples) > 1, "the normal map is flat: the bake wrote nothing"
    # A tangent-space normal map's Z is above 0.5 everywhere.
    assert min(float(value) for value in array[:, 2]) > 0.5


def test_the_from_height_normal_map_holds_the_relief(empty_scene, tmp_path):
    """`from_height` must hold the SURFACE normal, and the bake must not.

    The bake stores a CURVATURE measure — the difference between the
    vertex normal and the face normal — so on a smooth relief it is
    nearly flat. `from_height` stores the surface normal itself, so
    it spans the full range. Measured on a cobblestone slab: the baked
    map's encoded X channel spans 0.482 to 0.518; the from-height one
    spans 0.388 to 0.965.
    """
    from golem_blender.ops.pbr_bake import bake_normal_map
    from golem_blender.ops.uv import unwrap_uvs

    box = _box()
    unwrap_uvs(box.name)
    # A relief slab: a step in the middle, so the surface has a face
    # that is not flat.
    for vertex in box.data.vertices:
        if vertex.co.x > 0.0:
            vertex.co.z += 0.05
    box.data.update()
    bpy.ops.object.select_all(action="DESELECT")
    box.select_set(True)
    bpy.context.view_layer.objects.active = box
    bpy.ops.object.shade_smooth()
    bpy.context.view_layer.update()

    from_height = _read_pixels(
        Path(
            bake_normal_map(
                box.name,
                tmp_path / "from_height.png",
                resolution_px=128,
                method="from_height",
            )
        )
    )
    baked = _read_pixels(
        Path(
            bake_normal_map(
                box.name, tmp_path / "bake.png", resolution_px=128, method="bake"
            )
        )
    )

    def span(array):
        return float(array[:, 0].max()) - float(array[:, 0].min())

    assert span(from_height) > span(baked) * 3.0, (
        f"the from-height map spans {span(from_height):.3f} and the baked one "
        f"{span(baked):.3f}: the surface normal is not being held"
    )


def test_an_unknown_normal_map_method_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.pbr_bake import bake_normal_map

    box = _box()
    with pytest.raises(ValueError, match="method"):
        bake_normal_map(
            box.name, tmp_path / "n.png", resolution_px=64, method="invented"
        )


def test_baking_a_mesh_with_no_uv_layer_names_the_op_to_call_first(
    empty_scene, tmp_path
):
    from golem_blender.ops.pbr_bake import bake_normal_map

    box = _box()
    assert not box.data.uv_layers

    with pytest.raises(ValueError, match="unwrap_uvs"):
        bake_normal_map(box.name, tmp_path / "T_Subject_Normal.png", resolution_px=64)


def test_the_bake_leaves_no_scratch_datablock_behind(empty_scene, tmp_path):
    """The bake's material, image and world are all gone afterwards.

    Only the NAMES are compared: pytest renders a failed assertion by
    repr'ing the values, and repr'ing a bpy struct crashes Blender 5.2
    (a segfault in pyrna_struct_repr), so a failure here would take the
    whole test run down instead of reporting.
    """
    from golem_blender.ops.pbr_bake import bake_orm_map
    from golem_blender.ops.uv import unwrap_uvs

    box = _box()
    unwrap_uvs(box.name)
    before_worlds = {world.name for world in bpy.data.worlds}
    before_images = {image.name for image in bpy.data.images}

    bake_orm_map(box.name, tmp_path / "T_Subject_ORM.png", resolution_px=64)

    material_names = [material.name for material in bpy.data.materials]
    assert not [name for name in material_names if name.startswith("blended_bake_")]
    assert {world.name for world in bpy.data.worlds} == before_worlds
    # Blender creates its own "Render Result" and "Viewer Node" images
    # during a render; those are Blender's, not the bake's.
    new_images = {image.name for image in bpy.data.images} - before_images
    assert not [
        name
        for name in new_images
        if not name.startswith(("Render Result", "Viewer Node"))
    ]


def test_the_bake_leaves_the_meshes_own_material_on_it(empty_scene, tmp_path):
    """A bake must not leave the asset wearing the scratch material."""
    from golem_blender.ops.materials import assign_material
    from golem_blender.ops.pbr_bake import bake_orm_map
    from golem_blender.ops.uv import unwrap_uvs

    box = _box()
    assign_material(box.name, "OwnMaterial", base_color_rgb=(0.2, 0.4, 0.6))
    unwrap_uvs(box.name)

    bake_orm_map(box.name, tmp_path / "T_Subject_ORM.png", resolution_px=64)

    assert [m.name for m in box.data.materials] == ["OwnMaterial"]
    assert not [m for m in bpy.data.materials if m.name.startswith("blended_bake_")]


def _multi_slot_asset(name: str = "Barrel"):
    """A mesh with THREE material slots and its faces split between them.

    A game asset is not the slab the lane builds: a barrel has a wood
    body, a metal band and a rope handle. The face split is what
    makes the test meaningful - a material assignment that is lost is
    not visible in the slot list alone.
    """
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.4, depth=1.2)
    barrel = bpy.context.active_object
    barrel.name = name
    mesh = barrel.data
    for material_name in ("Wood", "MetalBand", "Rope"):
        mesh.materials.append(bpy.data.materials.new(f"{name}_{material_name}"))
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = index % 3
    return barrel


def _faces_per_slot(mesh) -> dict[int, int]:
    tally: dict[int, int] = {}
    for polygon in mesh.polygons:
        tally[polygon.material_index] = tally.get(polygon.material_index, 0) + 1
    return tally


def test_applying_a_set_leaves_the_assets_other_material_slots_alone(
    empty_scene, tmp_path
):
    """The lane must not destroy a multi-slot asset's setup.

    It used to clear the slots and append one, which took a
    three-slot barrel with its faces split 12/11/11 and left one slot
    with all 34 faces on it. The face-to-material mapping was gone.
    """
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    barrel = _multi_slot_asset()
    before = _faces_per_slot(barrel.data)
    base = _write_image(tmp_path / "T_Set_BaseColor.png", (*TEXTURE_RGB, 1.0))

    assign_pbr_texture_set(barrel.name, "CobbleBarrel", base)

    assert [m.name for m in barrel.data.materials] == [
        "Barrel_Wood",
        "Barrel_MetalBand",
        "Barrel_Rope",
        "CobbleBarrel",
    ]
    after = _faces_per_slot(barrel.data)
    for slot, count in before.items():
        assert after.get(slot) == count, (
            f"the faces on slot {slot} moved: {before} became {after}"
        )


def test_a_face_selector_moves_the_chosen_faces_onto_the_new_material(
    empty_scene, tmp_path
):
    """The texture has to land on FACES, or it is on a slot nothing uses."""
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set
    from golem_blender.ops.selectors import FaceSelector

    barrel = _multi_slot_asset()
    before = _faces_per_slot(barrel.data)
    base = _write_image(tmp_path / "T_Set_BaseColor.png", (*TEXTURE_RGB, 1.0))

    assign_pbr_texture_set(
        barrel.name,
        "CobbleBarrel",
        base,
        faces=FaceSelector(kind="material_slot", material_slot_index=1),
    )

    after = _faces_per_slot(barrel.data)
    cobble_slot = next(
        index
        for index, material in enumerate(barrel.data.materials)
        if material and material.name == "CobbleBarrel"
    )
    assert after[cobble_slot] == before[1], (
        f"the selected faces did not move onto the new material: {before} "
        f"became {after}"
    )
    assert after[0] == before[0], "the other slots' faces moved"


def test_the_report_reads_the_material_that_carries_the_set(empty_scene, tmp_path):
    """On a multi-slot asset the report must not read slot zero.

    Slot zero is often something else entirely - a wood body that was
    there first - and reading it says the set was never applied.
    """
    from golem_blender.ops.pbr_textures import (
        assign_pbr_texture_set,
        pbr_texture_report,
    )

    barrel = _multi_slot_asset()
    base = _write_image(tmp_path / "T_Set_BaseColor.png", (*TEXTURE_RGB, 1.0))
    orm = _write_image(tmp_path / "T_Set_ORM.png", ORM_RGBA)

    assign_pbr_texture_set(barrel.name, "CobbleBarrel", base, orm)

    report = pbr_texture_report(barrel.name)
    assert report.material_name == "CobbleBarrel", (
        f"the report read {report.material_name!r}, not the material that "
        f"carries the set"
    )
    assert report.ao_multiplied


def test_the_report_survives_a_base_colour_with_no_orm(empty_scene, tmp_path):
    """A base colour on its own is a first-class case, not a crash.

    The report read the base colour's path by asking a NODE for its
    links, which only a SOCKET has, so it raised AttributeError
    whenever the base colour was wired directly with no ORM to
    multiply into it.
    """
    from golem_blender.ops.pbr_textures import (
        assign_pbr_texture_set,
        pbr_texture_report,
    )

    box = _box()
    base = _write_image(tmp_path / "T_Set_BaseColor.png", (*TEXTURE_RGB, 1.0))

    assign_pbr_texture_set(box.name, "PlainSet", base)

    report = pbr_texture_report(box.name)
    assert report.base_color_linked
    assert report.base_color_path.endswith("T_Set_BaseColor.png")
    assert not report.ao_multiplied


def test_a_second_material_on_a_single_material_mesh_is_what_the_mesh_shows(
    empty_scene, tmp_path
):
    """Applying a texture must make the object SHOW it.

    Preserving the other slots must not leave the new material on a
    slot nothing points at. This is the case the round-9 fix broke:
    the mesh had one slot, the new material became the second, and
    the faces stayed on the first - so the texture was invisible and
    the render came back with the OLD material.
    """
    from golem_blender.ops.pbr_textures import assign_pbr_texture_set

    box = _box()
    base = _write_image(tmp_path / "T_Set_BaseColor.png", (*TEXTURE_RGB, 1.0))

    assign_pbr_texture_set(box.name, "FirstSet", base)
    assign_pbr_texture_set(box.name, "SecondSet", base)

    used = {polygon.material_index for polygon in box.data.polygons}
    assert len(used) == 1, f"the faces are split across slots {used}"
    slot = used.pop()
    assert box.data.materials[slot].name == "SecondSet", (
        f"the mesh shows {box.data.materials[slot].name!r}, not the material "
        f"that was just applied"
    )
