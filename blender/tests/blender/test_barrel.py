"""BarrelBuilder end to end through the gate."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_barrel_passes_the_gate(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import BarrelBuilder, BarrelParameters

    barrel_object = BarrelBuilder(BarrelParameters()).build()
    report = analyze_object(barrel_object)
    failures = report.failures(MeshBudget())
    assert failures == [], f"analyzer failures: {failures}; report={report}"
    # Hoops were unioned in, not left as separate objects.
    assert report.connected_component_count == 1
    assert not any(
        scene_object.name.startswith("Barrel_hoop") for scene_object in bpy.data.objects
    )


def test_barrel_widest_at_the_middle(empty_scene):
    """The bulge is real geometry: mid-height extent beats end extent."""
    from blended.builders import BarrelBuilder, BarrelParameters

    parameters = BarrelParameters()
    barrel_object = BarrelBuilder(parameters).build()
    vertex_coordinates = [vertex.co for vertex in barrel_object.data.vertices]

    END_BAND_M = 0.02
    MIDDLE_BAND_M = 0.05
    end_band_radius = max(
        (coordinate.x**2 + coordinate.y**2) ** 0.5
        for coordinate in vertex_coordinates
        if coordinate.z < END_BAND_M
    )
    middle_band_radius = max(
        (coordinate.x**2 + coordinate.y**2) ** 0.5
        for coordinate in vertex_coordinates
        if abs(coordinate.z - parameters.height_m / 2.0) < MIDDLE_BAND_M
    )
    assert middle_band_radius > end_band_radius * 1.1
