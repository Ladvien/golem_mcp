"""OT-13: the three ops the escape-hatch mining asked for, each with the
fixture that trips its validation (GATE-18 discipline applied to ops)."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

BOX_EDGE_COUNT = 12
TOP_FACE_EDGE_COUNT = 4


@pytest.fixture()
def two_boxes():
    from blended.ops import add_box, link_into_scene

    bpy.ops.wm.read_factory_settings(use_empty=True)
    for name, x in (("Seat", 0.0), ("Other", 3.0)):
        add_box(name, 0.4, 0.4, 0.04, location_m=(x, 0.0, 0.41))
        link_into_scene(name)
    yield


def test_rename_object_renames_object_and_data(two_boxes):
    from blended.ops import rename_object

    assert rename_object("Seat", "Stool") == "Stool"
    assert "Stool" in bpy.data.objects and "Seat" not in bpy.data.objects
    assert bpy.data.objects["Stool"].data.name == "Stool"
    assert rename_object("Stool", "Stool") == "Stool"  # idempotent on its own name


def test_rename_object_refuses_a_taken_name_instead_of_minting_dot_001(two_boxes):
    from blended.ops import NameTaken, rename_object

    with pytest.raises(NameTaken, match="already exists"):
        rename_object("Seat", "Other")
    assert "Other.001" not in bpy.data.objects
    with pytest.raises(ValueError, match="non-empty"):
        rename_object("Seat", "  ")


def test_world_bounds_reads_the_placed_box(two_boxes):
    from blended.ops import move_object_to, world_bounds

    bounds = world_bounds("Seat")
    assert bounds["min_m"] == pytest.approx([-0.2, -0.2, 0.41], abs=1e-6)
    assert bounds["max_m"] == pytest.approx([0.2, 0.2, 0.45], abs=1e-6)
    assert bounds["extents_m"] == pytest.approx([0.4, 0.4, 0.04], abs=1e-6)
    move_object_to("Seat", (1.0, 0.0, 0.0))
    assert world_bounds("Seat")["min_m"][0] == pytest.approx(
        0.8, abs=1e-6
    )  # this frame's box, not the last one's


def test_mark_uv_seams_by_selector_and_refuses_an_empty_selection(two_boxes):
    from blended.ops import EdgeSelector, NoEdgesSelected, mark_uv_seams

    assert (
        mark_uv_seams(
            "Seat", EdgeSelector(kind="dihedral_angle", minimum_dihedral_angle_deg=60.0)
        )
        == "Seat"
    )
    seat = bpy.data.objects["Seat"]
    assert sum(1 for edge in seat.data.edges if edge.use_seam) == BOX_EDGE_COUNT
    with pytest.raises(NoEdgesSelected):
        mark_uv_seams(
            "Other",
            EdgeSelector(kind="vertex_group", vertex_group_pattern="nothing_.*"),
        )
    assert not any(edge.use_seam for edge in bpy.data.objects["Other"].data.edges)


def test_the_three_ops_dispatch_as_tools(two_boxes, tmp_path):
    from blended.agent.tools import dispatch_tool

    renamed = dispatch_tool(
        "rename_object", {"object_name": "Seat", "new_name": "Stool"}, tmp_path
    )
    assert renamed.ok and "gate: PASS" in renamed.text, renamed.text
    bounds = dispatch_tool("world_bounds", {"object_name": "Stool"}, tmp_path)
    assert bounds.ok and '"extents_m"' in bounds.text
    seams = dispatch_tool(
        "mark_uv_seams", {"object_name": "Stool", "edges": {"kind": "all"}}, tmp_path
    )
    assert seams.ok and "gate: PASS" in seams.text, seams.text
