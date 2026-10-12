"""PalletBuilder: the array -> union -> single-solid flow."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_pallet_passes_the_gate_as_one_solid(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import PalletBuilder, PalletParameters

    pallet_object = PalletBuilder(PalletParameters()).build()
    report = analyze_object(pallet_object)
    failures = report.failures(MeshBudget())
    assert failures == [], f"analyzer failures: {failures}; report={report}"
    assert report.connected_component_count == 1


def test_pallet_dimensions_match_parameters(empty_scene):
    from blended.builders import PalletBuilder, PalletParameters

    DIMENSION_TOLERANCE_M = 1.0e-4
    parameters = PalletParameters()
    pallet_object = PalletBuilder(parameters).build()
    bpy.context.view_layer.update()

    assert abs(pallet_object.dimensions.x - parameters.length_m) < DIMENSION_TOLERANCE_M
    assert abs(pallet_object.dimensions.y - parameters.width_m) < DIMENSION_TOLERANCE_M
    assert (
        abs(pallet_object.dimensions.z - parameters.total_height_m)
        < DIMENSION_TOLERANCE_M
    )


def test_array_intermediate_is_multi_component_by_design(empty_scene):
    """Document the honest intermediate: an applied array alone is N
    islands — only the union step earns the single-component verdict."""
    from blended.analyze import analyze_object
    from blended.ops import add_box, link_into_scene
    from blended.ops.arrays import linear_array

    board_name = add_box("LoneBoards", 0.1, 0.5, 0.02)
    link_into_scene(board_name)
    linear_array(board_name, count=4, offset_m=(0.2, 0.0, 0.0))
    report = analyze_object(bpy.data.objects[board_name])
    assert report.connected_component_count == 4
