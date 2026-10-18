"""OT-50: every exported asset ships with its editable .blend.

The assertions read the written file through their own `libraries.load`
rather than through `save_blend`'s report, so a verification that shares a
derivation with the write cannot vouch for itself.
"""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
UNCOMPRESSED_MAGIC = b"BLEN"
SAVED_LOCATION_M = (1.25, -0.5, 0.75)
SAVED_ROTATION_Z_RAD = 0.5


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _triangles(mesh_object) -> int:
    return sum(len(polygon.vertices) - 2 for polygon in mesh_object.data.polygons)


def _build_three_objects():
    """Two objects to save, one bystander that must stay out of the file."""
    from golem_blender.builders import (
        BarrelBuilder,
        BarrelParameters,
        CrateBuilder,
        CrateParameters,
        PalletBuilder,
        PalletParameters,
    )

    crate = CrateBuilder(CrateParameters(name="SaveCrate")).build()
    barrel = BarrelBuilder(BarrelParameters(name="SaveBarrel")).build()
    PalletBuilder(PalletParameters(name="Bystander")).build()
    crate.location = SAVED_LOCATION_M
    crate.rotation_euler = (0.0, 0.0, SAVED_ROTATION_Z_RAD)
    bpy.context.view_layer.update()
    return crate, barrel


def _what_the_file_holds(blend_path: Path) -> dict:
    """Open the file as a linked library and report what is in it."""
    with bpy.data.libraries.load(str(blend_path), link=True) as (data_from, data_to):
        held = {
            "objects": sorted(data_from.objects),
            "scenes": list(data_from.scenes),
            "cameras": list(data_from.cameras),
            "materials": sorted(data_from.materials),
        }
        data_to.objects = list(data_from.objects)
    library = next(
        candidate
        for candidate in bpy.data.libraries
        if Path(bpy.path.abspath(candidate.filepath)).resolve() == blend_path.resolve()
    )
    held["triangles"] = {
        linked.name: _triangles(linked)
        for linked in bpy.data.objects
        if linked.library == library
    }
    held["transforms"] = {
        linked.name: (tuple(linked.location), tuple(linked.rotation_euler))
        for linked in bpy.data.objects
        if linked.library == library
    }
    held["material_slots"] = {
        linked.name: [
            slot.material.name if slot.material else None
            for slot in linked.material_slots
        ]
        for linked in bpy.data.objects
        if linked.library == library
    }
    bpy.data.libraries.remove(library)
    return held


def _session_snapshot() -> dict:
    return {
        "filepath": bpy.data.filepath,
        "current_scene": bpy.context.scene.name,
        "scenes": sorted(scene.name for scene in bpy.data.scenes),
        "collections": sorted(collection.name for collection in bpy.data.collections),
        "objects": sorted(scene_object.name for scene_object in bpy.data.objects),
        "meshes": sorted(mesh.name for mesh in bpy.data.meshes),
        "libraries": sorted(library.name for library in bpy.data.libraries),
        "users_collection": {
            scene_object.name: sorted(
                collection.name for collection in scene_object.users_collection
            )
            for scene_object in bpy.data.objects
        },
        "selected": sorted(
            scene_object.name
            for scene_object in bpy.context.view_layer.objects
            if scene_object.select_get()
        ),
        "active": getattr(bpy.context.view_layer.objects.active, "name", None),
    }


def test_the_file_reopens_with_exactly_the_named_objects(empty_scene, tmp_path):
    from golem_blender.export import save_blend
    from golem_blender.ops import assign_material

    crate, barrel = _build_three_objects()
    assign_material(crate.name, "SaveWood", (0.6, 0.4, 0.2))
    blend_path = tmp_path / "deep" / "pieces.blend"

    report = save_blend([crate.name, barrel.name], blend_path)

    assert blend_path.exists()
    assert report.blend_path == blend_path
    assert report.file_size_bytes == blend_path.stat().st_size > 0
    assert report.object_names == ("SaveCrate", "SaveBarrel")
    # Compressed: not the plain "BLENDER" header.
    assert blend_path.read_bytes()[:4] == ZSTD_MAGIC

    held = _what_the_file_holds(blend_path)
    assert held["objects"] == ["SaveBarrel", "SaveCrate"]
    assert len(held["scenes"]) == 1
    assert held["cameras"] == []
    assert held["materials"] == ["SaveWood"]
    assert held["triangles"] == {
        "SaveCrate": _triangles(crate),
        "SaveBarrel": _triangles(barrel),
    }
    assert held["triangles"] == report.triangle_counts
    assert held["material_slots"]["SaveCrate"] == ["SaveWood"]
    assert held["material_slots"]["SaveBarrel"] == [
        slot.material.name if slot.material else None
        for slot in barrel.material_slots
    ]
    saved_location_m, saved_rotation_rad = held["transforms"]["SaveCrate"]
    assert saved_location_m == pytest.approx(SAVED_LOCATION_M)
    assert saved_rotation_rad[2] == pytest.approx(SAVED_ROTATION_Z_RAD)


def test_the_session_is_unchanged_by_the_save(empty_scene, tmp_path):
    from golem_blender.export import save_blend

    crate, barrel = _build_three_objects()
    for scene_object in bpy.context.view_layer.objects:
        scene_object.select_set(scene_object.name == "Bystander")
    bpy.context.view_layer.objects.active = bpy.data.objects["Bystander"]
    before = _session_snapshot()
    assert before["filepath"] == ""

    save_blend([crate.name, barrel.name], tmp_path / "pieces.blend")

    assert _session_snapshot() == before
    # The objects are still where they were, with their data.
    assert bpy.context.scene.objects["SaveCrate"] is crate
    assert crate.location[:] == pytest.approx(SAVED_LOCATION_M)


def test_a_path_not_ending_in_blend_raises_and_writes_nothing(empty_scene, tmp_path):
    from golem_blender.export import BlendSaveError, save_blend

    crate, _ = _build_three_objects()
    before = _session_snapshot()
    for bad_name in ("pieces.glb", "pieces", "pieces.blend1"):
        with pytest.raises(BlendSaveError, match=r"\.blend"):
            save_blend([crate.name], tmp_path / bad_name)
    assert list(tmp_path.iterdir()) == []
    assert _session_snapshot() == before


def test_a_missing_object_fails_loudly_and_writes_nothing(empty_scene, tmp_path):
    """The negative control: the check can fail."""
    from golem_blender.export import BlendSaveError, save_blend

    crate, _ = _build_three_objects()
    before = _session_snapshot()
    with pytest.raises(BlendSaveError, match="NoSuchObject"):
        save_blend([crate.name, "NoSuchObject"], tmp_path / "pieces.blend")
    assert not (tmp_path / "pieces.blend").exists()
    assert _session_snapshot() == before


def test_a_dependency_pulled_into_the_file_fails_loudly(empty_scene, tmp_path):
    """A parent the caller did not name rides into the file as a dependency;
    the file then holds more than the named objects, and that is refused,
    with the bad file deleted and the session unchanged."""
    from golem_blender.export import BlendSaveError, save_blend

    crate, barrel = _build_three_objects()
    barrel.parent = crate
    before = _session_snapshot()
    with pytest.raises(BlendSaveError, match="SaveCrate"):
        save_blend([barrel.name], tmp_path / "pieces.blend")
    assert not (tmp_path / "pieces.blend").exists()
    assert _session_snapshot() == before


def test_a_triangle_mismatch_in_the_written_file_fails_and_deletes_it(
    empty_scene, tmp_path, monkeypatch
):
    """Negative control for the count check: a re-read that disagrees with
    the live object is an error, not a warning."""
    from golem_blender.export import BlendSaveError, blend, save_blend

    crate, _ = _build_three_objects()
    real_reread = blend._reread_triangle_counts

    def reread_with_one_triangle_missing(destination, names):
        counts = real_reread(destination, names)
        return {name: count - 1 for name, count in counts.items()}

    monkeypatch.setattr(blend, "_reread_triangle_counts", reread_with_one_triangle_missing)
    with pytest.raises(BlendSaveError, match="triangles"):
        save_blend([crate.name], tmp_path / "pieces.blend")
    assert not (tmp_path / "pieces.blend").exists()


def test_the_open_file_of_the_session_is_never_overwritten(empty_scene, tmp_path):
    from golem_blender.export import BlendSaveError, save_blend

    crate, _ = _build_three_objects()
    open_file = tmp_path / "open.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(open_file))
    size_before = open_file.stat().st_size
    with pytest.raises(BlendSaveError, match="open file"):
        save_blend([crate.name], open_file)
    assert open_file.stat().st_size == size_before


def test_export_glb_requires_a_blend_path_and_ships_both_files(empty_scene, tmp_path):
    from golem_blender.export import export_glb

    crate, _ = _build_three_objects()
    with pytest.raises(TypeError, match="blend_path"):
        export_glb(crate, tmp_path / "crate.glb")
    assert list(tmp_path.iterdir()) == []

    report = export_glb(
        crate, tmp_path / "crate.glb", blend_path=tmp_path / "crate.blend"
    )
    assert (tmp_path / "crate.glb").exists()
    assert report.blend is not None
    assert report.blend.blend_path == tmp_path / "crate.blend"
    held = _what_the_file_holds(tmp_path / "crate.blend")
    assert held["objects"] == ["SaveCrate"]
    assert held["triangles"]["SaveCrate"] == report.pre_export.triangle_count


def test_export_glb_with_a_bad_blend_path_writes_no_glb(empty_scene, tmp_path):
    from golem_blender.export import BlendSaveError, export_glb

    crate, _ = _build_three_objects()
    with pytest.raises(BlendSaveError, match=r"\.blend"):
        export_glb(crate, tmp_path / "crate.glb", blend_path=tmp_path / "crate.glb2")
    assert list(tmp_path.iterdir()) == []


def test_export_asset_fails_without_blend_path_and_writes_both_files_with_it(
    empty_scene, tmp_path
):
    from golem_blender.agent.tools import dispatch_tool

    _build_three_objects()
    glb_path = tmp_path / "barrel.glb"
    blend_path = tmp_path / "barrel.blend"

    for arguments in (
        {"object_name": "SaveBarrel", "path": str(glb_path)},
        {
            "object_name": "SaveBarrel",
            "path": str(glb_path),
            "blend_path": "barrel.blend",
        },
        {
            "object_name": "SaveBarrel",
            "path": str(glb_path),
            "blend_path": str(tmp_path / "barrel.glb2"),
        },
    ):
        outcome = dispatch_tool("export_asset", arguments, tmp_path)
        assert not outcome.ok, outcome.text
        assert ".blend" in outcome.text
    assert list(tmp_path.iterdir()) == []

    outcome = dispatch_tool(
        "export_asset",
        {
            "object_name": "SaveBarrel",
            "path": str(glb_path),
            "blend_path": str(blend_path),
        },
        tmp_path,
    )
    assert outcome.ok, outcome.text
    assert str(glb_path) in outcome.text and str(blend_path) in outcome.text
    assert glb_path.exists() and blend_path.exists()
    assert _what_the_file_holds(blend_path)["objects"] == ["SaveBarrel"]


def test_the_save_blend_tool_saves_several_objects_and_refuses_the_rest(
    empty_scene, tmp_path
):
    from golem_blender.agent.tools import dispatch_tool

    _build_three_objects()
    blend_path = tmp_path / "both.blend"

    refused = [
        {"object_names": ["SaveCrate", "SaveBarrel"]},
        {"object_names": ["SaveCrate"], "blend_path": "both.blend"},
        {"object_names": [], "blend_path": str(blend_path)},
        {"object_names": "SaveCrate", "blend_path": str(blend_path)},
        {"object_names": ["SaveCrate", "Ghost"], "blend_path": str(blend_path)},
    ]
    for arguments in refused:
        outcome = dispatch_tool("save_blend", arguments, tmp_path)
        assert not outcome.ok, (arguments, outcome.text)
    assert list(tmp_path.iterdir()) == []

    outcome = dispatch_tool(
        "save_blend",
        {"object_names": ["SaveCrate", "SaveBarrel"], "blend_path": str(blend_path)},
        tmp_path,
    )
    assert outcome.ok, outcome.text
    assert str(blend_path) in outcome.text
    assert _what_the_file_holds(blend_path)["objects"] == ["SaveBarrel", "SaveCrate"]
