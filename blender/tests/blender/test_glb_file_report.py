"""The shipped .glb, judged on its own bytes.

The re-import is not the artifact: the exporter bakes modifiers, so
scene counts describe geometry that never shipped (scp measured a "5k"
tier shipping 9,488 triangles). `ExportReport.file_report` parses the
file with stdlib only — no Blender — and the round-trip gate now also
asserts the file's own numbers.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_file_and_welded_reimport_agree(empty_scene, tmp_path):
    from blended.builders import PalletBuilder, PalletParameters
    from blended.export import export_glb

    pallet_object = PalletBuilder(PalletParameters()).build()
    export_report = export_glb(
        pallet_object, tmp_path / "pallet.glb", blend_path=tmp_path / "pallet.blend"
    )

    failures = export_report.round_trip_failures()
    assert failures == [], failures

    file_report = export_report.file_report
    assert file_report is not None
    assert file_report.triangle_count == export_report.pre_export.triangle_count
    assert (
        file_report.welded_boundary_edge_count
        == export_report.reimported_welded.boundary_edge_count
    )
    assert file_report.root_node_names == [pallet_object.name]
    assert file_report.inverted_facet_count == 0
    assert all(mesh.has_normals for mesh in file_report.meshes.values()), (
        "the shipped file must carry NORMAL accessors"
    )
