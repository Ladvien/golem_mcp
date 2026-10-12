"""The walking skeleton: build -> analyze -> capture, end to end."""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_pinned_blender_series(empty_scene):
    from blended.version import assert_supported_blender

    running_series = assert_supported_blender()
    assert len(running_series) == 2


def test_crate_builds_and_passes_the_gate(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import CrateBuilder, CrateParameters

    crate_object = CrateBuilder(CrateParameters()).build()

    report = analyze_object(crate_object)
    failures = report.failures(MeshBudget())
    assert failures == [], f"analyzer failures: {failures}; report={report}"
    # The bevel must have produced real geometry: more than a cube's 12 tris.
    assert report.triangle_count > 12


def test_analyzer_can_fail_on_seeded_defect(empty_scene):
    """The gate must be able to fail — a gate that cannot fail is not a gate."""
    from blended.analyze import MeshBudget, analyze_object
    from blended.ops.primitives import add_box, link_into_scene

    open_box = bpy.data.objects[
        add_box("OpenBox", width_m=1.0, depth_m=1.0, height_m=1.0)
    ]
    link_into_scene(open_box.name)
    # Seed a defect: delete one face -> boundary edges appear.
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(open_box.data)
    working_mesh.faces.ensure_lookup_table()
    working_mesh.faces.remove(working_mesh.faces[0])
    working_mesh.to_mesh(open_box.data)
    working_mesh.free()

    report = analyze_object(open_box)
    assert report.boundary_edge_count > 0
    assert not report.passes(MeshBudget())


def test_capture_renders_all_four_views(empty_scene, tmp_path):
    from blended.builders import CrateBuilder, CrateParameters
    from blended.capture import capture_views
    from blended.capture.views import VIEW_DIRECTIONS

    crate_object = CrateBuilder(CrateParameters()).build()
    captured = capture_views(crate_object, tmp_path)

    assert set(captured) == set(VIEW_DIRECTIONS)
    for view_name, image_path in captured.items():
        assert Path(image_path).exists(), f"missing render for {view_name}"
        assert Path(image_path).stat().st_size > 0


def test_add_box_is_idempotent_by_name(empty_scene):
    """Rebuilding under the same name replaces, never creates '.001'."""
    from blended.ops.primitives import add_box, link_into_scene

    first_box = add_box("SameName", width_m=1.0, depth_m=1.0, height_m=1.0)
    link_into_scene(first_box)
    second_box_name = add_box("SameName", width_m=2.0, depth_m=2.0, height_m=2.0)
    link_into_scene(second_box_name)

    matching_names = [
        scene_object.name
        for scene_object in bpy.data.objects
        if scene_object.name.startswith("SameName")
    ]
    assert matching_names == ["SameName"], matching_names
    assert (
        bpy.data.objects[second_box_name].dimensions.x > 1.5
    )  # it is the NEW box that survived
