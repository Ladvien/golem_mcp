"""import_glb_piece, import_generated_asset and duplicate_object against a real .glb.

Each test builds its fixture in the scene, exports it with Blender's own glTF
exporter, removes the originals, and imports the file back: the ops are
judged against a file, not against the objects that made it.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

POSITION_TOLERANCE_M = 1.0e-4
BASE_TOLERANCE_M = 1.0e-6
RED_RGB = (0.9, 0.1, 0.1)
BLUE_RGB = (0.1, 0.1, 0.9)
GOLD_RGB = (0.9, 0.7, 0.1)
GENERATED_HEIGHT_M = 0.5
GENERATED_TRIANGLE_BUDGET = 200
# 256 segments make a ~1020-triangle cylinder, several times the budget above.
GENERATED_SEGMENT_COUNT = 256


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _export_and_remove(tmp_path, object_names, file_name):
    """Export the named objects to one .glb, remove them, return the file's path."""
    from golem_blender.ops.primitives import remove_object_and_mesh

    for scene_object in bpy.data.objects:
        scene_object.select_set(scene_object.name in object_names)
    bpy.context.view_layer.objects.active = bpy.data.objects[object_names[0]]
    glb_path = tmp_path / file_name
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path), export_format="GLB", use_selection=True
    )
    for object_name in object_names:
        remove_object_and_mesh(object_name)
    # The fixture's materials outlive its objects as orphans; left in place the
    # import would name its own materials "Red.001" instead of "Red".
    for material in list(bpy.data.materials):
        if material.users == 0:
            bpy.data.materials.remove(material)
    return glb_path


def _linked_box(name, width_m, depth_m, height_m, location_m, material_name, rgb):
    from golem_blender.ops.materials import assign_material
    from golem_blender.ops.primitives import add_box, link_into_scene

    box_name = add_box(name, width_m, depth_m, height_m, location_m)
    link_into_scene(box_name)
    assign_material(box_name, material_name, rgb)
    return box_name


def test_pack_piece_keeps_its_materials_and_its_pivot(empty_scene, tmp_path):
    from golem_blender.ops.assets import import_glb_piece
    from golem_blender.ops.primitives import NameTaken
    from golem_blender.ops.transforms import _world_bounds_m

    # Two objects, not a boolean: a boolean keeps only the target's slots.
    # The body's minimum corner is the origin, so the file's pivot is that corner.
    body = _linked_box("PieceBody", 2.0, 1.0, 1.0, (1.0, 0.5, 0.0), "Red", RED_RGB)
    trim = _linked_box("PieceTrim", 0.2, 1.0, 0.2, (2.2, 0.5, 0.0), "Blue", BLUE_RGB)
    exported_minimum, exported_maximum = _world_bounds_m(
        [bpy.data.objects[body], bpy.data.objects[trim]]
    )
    glb_path = _export_and_remove(tmp_path, [body, trim], "piece.glb")

    report = import_glb_piece(str(glb_path), "Piece")

    assert sorted(report.material_names) == ["Blue", "Red"]
    assert report.bounds_min_m == pytest.approx(
        exported_minimum, abs=POSITION_TOLERANCE_M
    )
    assert report.bounds_max_m == pytest.approx(
        exported_maximum, abs=POSITION_TOLERANCE_M
    )
    assert report.extents_m == pytest.approx(
        [hi - lo for lo, hi in zip(exported_minimum, exported_maximum)],
        abs=POSITION_TOLERANCE_M,
    )
    assert report.triangle_count == report.triangle_count_before == 24
    assert report.scale == 1.0
    assert report.source_glb == str(glb_path)

    # Each face still wears the material of the part it came from.
    imported = bpy.data.objects["Piece"]
    slot_names = [slot.material.name for slot in imported.material_slots]
    faces_per_material = {name: 0 for name in slot_names}
    for polygon in imported.data.polygons:
        faces_per_material[slot_names[polygon.material_index]] += 1
    assert faces_per_material == {"Red": 12, "Blue": 12}

    with pytest.raises(NameTaken):
        import_glb_piece(str(glb_path), "Piece")


def test_a_missing_glb_is_a_file_not_found(empty_scene, tmp_path):
    from golem_blender.ops.assets import import_glb_piece

    with pytest.raises(FileNotFoundError):
        import_glb_piece(str(tmp_path / "absent.glb"), "Piece")


def test_generated_asset_is_sized_grounded_centred_and_decimated(empty_scene, tmp_path):
    from golem_blender.ops.assets import import_generated_asset
    from golem_blender.ops.materials import assign_material
    from golem_blender.ops.primitives import add_cylinder, link_into_scene

    cylinder = add_cylinder(
        "Source", 0.2, 1.0, GENERATED_SEGMENT_COUNT, location_m=(3.0, 4.0, 5.0)
    )
    link_into_scene(cylinder)
    assign_material(cylinder, "Gold", GOLD_RGB)
    glb_path = _export_and_remove(tmp_path, [cylinder], "generated.glb")

    report = import_generated_asset(
        str(glb_path),
        "Generated",
        height_m=GENERATED_HEIGHT_M,
        triangle_count=GENERATED_TRIANGLE_BUDGET,
    )

    assert report.extents_m[2] == pytest.approx(
        GENERATED_HEIGHT_M, abs=POSITION_TOLERANCE_M
    )
    assert report.bounds_min_m[2] == pytest.approx(0.0, abs=BASE_TOLERANCE_M)
    centre_x_m = (report.bounds_min_m[0] + report.bounds_max_m[0]) / 2
    centre_y_m = (report.bounds_min_m[1] + report.bounds_max_m[1]) / 2
    assert centre_x_m == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
    assert centre_y_m == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
    assert report.triangle_count <= GENERATED_TRIANGLE_BUDGET
    assert report.triangle_count_before > GENERATED_TRIANGLE_BUDGET
    assert report.material_names == ("Gold",)
    assert report.scale == pytest.approx(GENERATED_HEIGHT_M, rel=0.05)


def test_generated_asset_reads_big_paths_through_the_mac_mount(
    empty_scene, tmp_path, monkeypatch
):
    from golem_blender.kitbash import paths
    from golem_blender.ops.assets import import_generated_asset
    from golem_blender.ops.primitives import add_box, link_into_scene

    box = add_box("Source", 1.0, 1.0, 2.0)
    link_into_scene(box)
    glb_path = _export_and_remove(tmp_path, [box], "asset.glb")
    monkeypatch.setattr(paths, "CODEX_ROOT_MAC", tmp_path)
    monkeypatch.setattr(paths, "CODEX_ROOT_ON_BIG", "/mnt/fake_codex")

    report = import_generated_asset(
        "/mnt/fake_codex/asset.glb", "Generated", height_m=1.0, triangle_count=100
    )

    assert report.source_glb == str(glb_path)
    assert report.extents_m[2] == pytest.approx(1.0, abs=POSITION_TOLERANCE_M)


def test_generated_asset_rejects_a_height_that_is_not_positive(empty_scene, tmp_path):
    from golem_blender.ops.assets import import_generated_asset

    with pytest.raises(ValueError):
        import_generated_asset(str(tmp_path / "unused.glb"), "Generated", height_m=0.0)
    assert "Generated" not in bpy.data.objects


def test_duplicate_has_its_own_mesh_and_the_requested_pose(empty_scene):
    from mathutils import Matrix

    from golem_blender.ops.assets import duplicate_object
    from golem_blender.ops.primitives import NameTaken

    original = bpy.data.objects[
        _linked_box("Original", 2.0, 1.0, 1.0, (0.0, 0.0, 0.0), "Red", RED_RGB)
    ]
    vertices_before = [tuple(vertex.co) for vertex in original.data.vertices]

    report = duplicate_object("Original", "Copy", (3.0, 0.0, 0.0), math.pi / 2)

    copy = bpy.data.objects["Copy"]
    assert report.object_name == "Copy"
    assert report.source_glb == ""
    assert tuple(copy.location) == (3.0, 0.0, 0.0)
    assert copy.rotation_euler.z == pytest.approx(math.pi / 2)
    # A 2 x 1 x 1 box turned a quarter about Z occupies 1 x 2 x 1.
    assert report.extents_m == pytest.approx((1.0, 2.0, 1.0), abs=POSITION_TOLERANCE_M)
    assert report.material_names == ("Red",)
    assert copy.data is not original.data
    assert copy.data.materials[0] is original.data.materials[0]
    assert copy.users_collection == original.users_collection

    copy.data.transform(Matrix.Translation((1.0, 1.0, 1.0)))
    assert [tuple(vertex.co) for vertex in original.data.vertices] == vertices_before

    with pytest.raises(NameTaken):
        duplicate_object("Original", "Copy")
