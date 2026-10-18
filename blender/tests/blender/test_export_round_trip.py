"""The export gate against real geometry and a real file on disk."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_pallet_round_trips_clean(empty_scene, tmp_path):
    from golem_blender.builders import PalletBuilder, PalletParameters
    from golem_blender.export import export_glb

    pallet_object = PalletBuilder(PalletParameters()).build()
    export_report = export_glb(
        pallet_object, tmp_path / "pallet.glb", blend_path=tmp_path / "pallet.blend"
    )

    failures = export_report.round_trip_failures()
    assert failures == [], failures
    assert export_report.export_path.exists()
    assert export_report.file_size_bytes > 0
    # The re-import check object cleaned itself up.
    assert not any(
        "_reimport_check" in scene_object.name
        for scene_object in bpy.context.scene.objects
    )


def test_barrel_round_trips_clean(empty_scene, tmp_path):
    from golem_blender.builders import BarrelBuilder, BarrelParameters
    from golem_blender.export import export_glb

    barrel_object = BarrelBuilder(BarrelParameters()).build()
    export_report = export_glb(
        barrel_object, tmp_path / "barrel.glb", blend_path=tmp_path / "barrel.blend"
    )
    assert export_report.round_trip_failures() == []


def test_defective_mesh_is_flagged_before_export(empty_scene, tmp_path):
    """Exporting an open mesh is allowed but LOUD: the round-trip report
    leads with the pre-export gate failure."""
    import bmesh

    from golem_blender.export import export_glb
    from golem_blender.ops import add_box, link_into_scene

    open_box = bpy.data.objects[add_box("OpenExport", 1.0, 1.0, 1.0)]
    link_into_scene(open_box.name)
    working_mesh = bmesh.new()
    working_mesh.from_mesh(open_box.data)
    working_mesh.faces.ensure_lookup_table()
    working_mesh.faces.remove(working_mesh.faces[0])
    working_mesh.to_mesh(open_box.data)
    working_mesh.free()

    export_report = export_glb(
        open_box, tmp_path / "open.glb", blend_path=tmp_path / "open.blend"
    )
    failures = export_report.round_trip_failures()
    assert any("BEFORE export" in failure for failure in failures)
