"""OT-14: each selector kind resolves against one fixture mesh.

The fixture is a 1 m box with the TOP face on material slot 1 and its
four top vertices in a vertex group named `top_ring`; every kind of
selector has one unambiguous answer on it, and the counts below are the
box's own (12 edges, 6 faces, 8 vertices).
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

BOX_EDGE_COUNT = 12
BOX_FACE_COUNT = 6
BOX_VERTEX_COUNT = 8
TOP_RING_VERTEX_COUNT = 4
TOP_FACE_EDGE_COUNT = 4
TOP_SLOT_INDEX = 1


@pytest.fixture()
def box_with_top_marked():
    from blended.ops import add_box, assign_material, link_into_scene

    bpy.ops.wm.read_factory_settings(use_empty=True)
    add_box("Fixture", 1.0, 1.0, 1.0)
    link_into_scene("Fixture")
    assign_material("Fixture", "Base", base_color_rgb=(0.5, 0.5, 0.5))
    fixture = bpy.data.objects["Fixture"]
    top_material = bpy.data.materials.new("Top")
    fixture.data.materials.append(top_material)
    top_face = max(fixture.data.polygons, key=lambda polygon: polygon.center.z)
    top_face.material_index = TOP_SLOT_INDEX
    group = fixture.vertex_groups.new(name="top_ring")
    top_vertices = [v.index for v in fixture.data.vertices if v.co.z > 0.5]
    assert len(top_vertices) == TOP_RING_VERTEX_COUNT
    group.add(top_vertices, 1.0, "REPLACE")
    yield "Fixture"


def test_edge_selectors_resolve_each_kind(box_with_top_marked):
    from blended.ops import EdgeSelector, select_edges

    assert (
        len(select_edges(box_with_top_marked, EdgeSelector(kind="all")))
        == BOX_EDGE_COUNT
    )
    # Every box edge is a 90 degree crease.
    assert (
        len(
            select_edges(
                box_with_top_marked,
                EdgeSelector(kind="dihedral_angle", minimum_dihedral_angle_deg=60.0),
            )
        )
        == BOX_EDGE_COUNT
    )
    assert (
        select_edges(
            box_with_top_marked,
            EdgeSelector(kind="dihedral_angle", minimum_dihedral_angle_deg=120.0),
        )
        == ()
    )
    assert (
        len(
            select_edges(
                box_with_top_marked,
                EdgeSelector(kind="material_slot", material_slot_index=TOP_SLOT_INDEX),
            )
        )
        == TOP_FACE_EDGE_COUNT
    )
    assert (
        len(
            select_edges(
                box_with_top_marked,
                EdgeSelector(kind="vertex_group", vertex_group_pattern="top_.*"),
            )
        )
        == TOP_FACE_EDGE_COUNT
    )
    assert (
        select_edges(
            box_with_top_marked,
            EdgeSelector(kind="vertex_group", vertex_group_pattern="bottom_.*"),
        )
        == ()
    )


def test_face_selectors_resolve_each_kind(box_with_top_marked):
    from blended.ops import FaceSelector, select_faces

    fixture = bpy.data.objects[box_with_top_marked]
    top = max(fixture.data.polygons, key=lambda polygon: polygon.center.z).index
    assert (
        len(select_faces(box_with_top_marked, FaceSelector(kind="all")))
        == BOX_FACE_COUNT
    )
    assert select_faces(
        box_with_top_marked, FaceSelector(kind="axis_normal", axis="+z")
    ) == (top,)
    assert (
        len(
            select_faces(
                box_with_top_marked, FaceSelector(kind="axis_normal", axis="-z")
            )
        )
        == 1
    )
    assert select_faces(
        box_with_top_marked,
        FaceSelector(kind="material_slot", material_slot_index=TOP_SLOT_INDEX),
    ) == (top,)
    assert select_faces(
        box_with_top_marked,
        FaceSelector(kind="vertex_group", vertex_group_pattern="top_ring"),
    ) == (top,)


def test_vertex_selectors_resolve_each_kind(box_with_top_marked):
    from blended.ops import VertexSelector, select_vertices

    assert (
        len(select_vertices(box_with_top_marked, VertexSelector(kind="all")))
        == BOX_VERTEX_COUNT
    )
    assert (
        len(
            select_vertices(
                box_with_top_marked,
                VertexSelector(kind="vertex_group", vertex_group_pattern="top_ring"),
            )
        )
        == TOP_RING_VERTEX_COUNT
    )
    assert (
        len(
            select_vertices(
                box_with_top_marked,
                VertexSelector(kind="height_range", z_min_m=0.9, z_max_m=1.1),
            )
        )
        == TOP_RING_VERTEX_COUNT
    )
    assert (
        select_vertices(
            box_with_top_marked,
            VertexSelector(kind="height_range", z_min_m=5.0, z_max_m=6.0),
        )
        == ()
    )


def test_weights_take_a_selector_not_indices(box_with_top_marked):
    """The one existing subset op switches from indices to a selector (OT-14)."""
    from blended.ops import VertexSelector, assign_vertex_group_weights, weight_report

    assign_vertex_group_weights(
        box_with_top_marked,
        "lift",
        0.75,
        VertexSelector(kind="height_range", z_min_m=0.9, z_max_m=1.1),
    )
    fixture = bpy.data.objects[box_with_top_marked]
    lift = fixture.vertex_groups["lift"]
    weighted = [
        v.index
        for v in fixture.data.vertices
        if any(g.group == lift.index for g in v.groups)
    ]
    assert len(weighted) == TOP_RING_VERTEX_COUNT
    assert weight_report(box_with_top_marked) is not None


def test_a_selector_dispatches_as_a_tool_argument(box_with_top_marked, tmp_path):
    """The selector round-trips through the tool surface: JSON in, enum
    validated, dataclass bound, indices out."""
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool(
        "select_faces",
        {
            "object_name": box_with_top_marked,
            "selector": {"kind": "axis_normal", "axis": "+z"},
        },
        tmp_path,
    )
    assert outcome.ok and "returned: [" in outcome.text
    bad = dispatch_tool(
        "select_faces",
        {"object_name": box_with_top_marked, "selector": {"kind": "by_colour"}},
        tmp_path,
    )
    assert not bad.ok and "ArgumentError" in bad.text and "kind" in bad.text
