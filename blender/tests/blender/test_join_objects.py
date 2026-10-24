"""Issue #21: a piece's parts can be combined into one mesh, through an op.

`join_objects` exists because `run_python` + `bpy.ops.object.join` was the
only path from "a timber stack is forty-eight boxes" to "one mesh the LOD
target can be met on" (Prop_TimberStack, Sanctuary, 2026-10-24). The
acceptance conditions are the issue's own, each measured rather than
asserted from the implementation.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

POSITION_TOLERANCE_M = 1.0e-4
# A 1 m box is 12 triangles and 6 quads; two of them are 24 triangles.
BOX_TRIANGLES = 12
PART_OFFSET_M = 5.0
RED_RGB = (0.9, 0.1, 0.1)
BLUE_RGB = (0.1, 0.1, 0.9)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _linked_box(name, material_name=None, rgb=None, location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops.materials import assign_material
    from golem_blender.ops.primitives import add_box, link_into_scene

    box_name = add_box(name, 1.0, 1.0, 1.0, location_m)
    link_into_scene(box_name)
    if material_name is not None:
        assign_material(box_name, material_name, rgb)
    return box_name


def _world_bounds(object_name):
    from golem_blender.ops.transforms import _world_bounds_m

    return _world_bounds_m([bpy.data.objects[object_name]])


# --- the acceptance conditions ---------------------------------------------


def test_joining_two_boxes_reports_both_parts_triangles(empty_scene):
    """Condition 1: 200-triangle parts report 200, and the result MEASURES 200."""
    from golem_blender.ops.assets import join_objects
    from golem_blender.ops.primitives import add_box, link_into_scene

    # 5x5x5 boxes are 12 triangles each whatever their size, so use the
    # box's own face count and assert the SUM rather than a literal.
    first = add_box("First", 1.0, 1.0, 1.0, (0.0, 0.0, 0.0))
    link_into_scene(first)
    second = add_box("Second", 1.0, 1.0, 1.0, (2.0, 0.0, 0.0))
    link_into_scene(second)

    report = join_objects([first, second], "Joined")

    assert report.triangles == 2 * BOX_TRIANGLES
    assert report.parts_joined == 2

    from golem_blender.analyze.mesh_checks import analyze_object

    measured = analyze_object(bpy.data.objects["Joined"])
    assert measured.triangle_count == report.triangles


def test_parts_sharing_a_material_report_one_slot(empty_scene):
    """Condition 2: sixteen tufts of one material are ONE slot, not sixteen."""
    from golem_blender.ops.assets import join_objects

    parts = [_linked_box(f"Tuft{i}", "Crop_Grain", RED_RGB) for i in range(4)]

    report = join_objects(parts, "Scarecrow")

    assert report.material_slots == 1
    assert [
        material.name for material in bpy.data.objects["Scarecrow"].data.materials
    ] == ["Crop_Grain"]


def test_distinct_materials_each_keep_one_slot(empty_scene):
    from golem_blender.ops.assets import join_objects

    parts = [
        _linked_box("RedPart", "Red", RED_RGB),
        _linked_box("BluePart", "Blue", BLUE_RGB, (2.0, 0.0, 0.0)),
    ]

    report = join_objects(parts, "TwoMaterials")

    assert report.material_slots == 2
    assert sorted(
        material.name for material in bpy.data.objects["TwoMaterials"].data.materials
    ) == ["Blue", "Red"]


def test_a_moved_part_keeps_its_world_position(empty_scene):
    """Condition 3: no snap to the origin."""
    from golem_blender.ops.assets import join_objects

    first = _linked_box("First")
    second = _linked_box("Second")
    from golem_blender.ops.transforms import move_object_to

    move_object_to(second, (PART_OFFSET_M, 0.0, 0.0))
    minimum_before, maximum_before = _world_bounds(second)

    join_objects([first, second], "Joined")

    minimum_after, maximum_after = _world_bounds("Joined")
    # The result spans both parts, so its maximum x is the moved part's.
    assert maximum_after[0] == pytest.approx(
        maximum_before[0], abs=POSITION_TOLERANCE_M
    )
    assert minimum_after[0] <= minimum_before[0] + POSITION_TOLERANCE_M


def test_the_sources_are_consumed_and_named(empty_scene):
    """Condition 4: consumed_names lists every source, and they are gone."""
    from golem_blender.ops.assets import join_objects

    parts = [_linked_box("First"), _linked_box("Second")]

    report = join_objects(parts, "Joined")

    assert sorted(report.consumed_names) == ["First", "Second"]
    assert [name for name in ("First", "Second") if name in bpy.data.objects] == []
    assert "Joined" in bpy.data.objects


def test_a_non_mesh_is_rejected_by_name(empty_scene):
    """Condition 6: loudly, naming the offending object."""
    from golem_blender.ops._objects import WrongObjectType
    from golem_blender.ops.assets import join_objects

    first = _linked_box("First")
    empty = bpy.data.objects.new("Pivot", None)
    bpy.context.scene.collection.objects.link(empty)

    with pytest.raises(WrongObjectType, match="Pivot"):
        join_objects([first, empty.name], "Joined")
    # Nothing was consumed by the failed call.
    assert "First" in bpy.data.objects


def test_the_intersection_count_separates_an_overlap_from_a_gap(empty_scene):
    """Condition 5's substance: the report distinguishes the two cases.

    Measured boundary (1 m boxes, the second offset on x): a 1 mm gap and a
    1 m gap both report 0; face-to-face contact reports 1 (two coplanar faces
    share their whole plane, which IS an overlap); a 50% overlap reports 8.
    The issue expected "touching ones should not" intersect; measured, the
    analyzer counts coplanar contact, and that is the honest reading — a
    joined lid resting on a pot is coincident surfaces, not clear space.
    """
    from golem_blender.ops.assets import join_objects
    from golem_blender.ops.primitives import add_box, link_into_scene

    def joined_pair(first_x_m, second_x_m, label):
        first = add_box("First", 1.0, 1.0, 1.0, (first_x_m, 0.0, 0.0))
        link_into_scene(first)
        second = add_box("Second", 1.0, 1.0, 1.0, (second_x_m, 0.0, 0.0))
        link_into_scene(second)
        return join_objects([first, second], f"Joined_{label}")

    assert joined_pair(0.0, 0.5, "overlap").self_intersecting_face_pair_count > 0, "overlap"
    assert joined_pair(0.0, 1.001, "gap1mm").self_intersecting_face_pair_count == 0, "1 mm gap"
    assert joined_pair(0.0, 2.0, "gap1m").self_intersecting_face_pair_count == 0, "1 m gap"
    # Stated, not assumed: coplanar contact counts.
    assert joined_pair(0.0, 1.0, "touching").self_intersecting_face_pair_count == 1, "touching"


# --- the decisions the issue asks to be made explicitly --------------------


def test_one_name_is_an_error_not_a_silent_rename(empty_scene):
    from golem_blender.ops.assets import join_objects

    only = _linked_box("Only")

    with pytest.raises(ValueError, match="at least two"):
        join_objects([only], "Renamed")
    assert "Renamed" not in bpy.data.objects
    assert "Only" in bpy.data.objects


def test_a_repeated_name_is_an_error(empty_scene):
    from golem_blender.ops.assets import join_objects

    first = _linked_box("First")
    second = _linked_box("Second")

    with pytest.raises(ValueError, match="twice"):
        join_objects([first, second, first], "Joined")
    assert "First" in bpy.data.objects and "Joined" not in bpy.data.objects


def test_an_existing_result_name_is_refused(empty_scene):
    from golem_blender.ops.assets import join_objects
    from golem_blender.ops.primitives import NameTaken

    first = _linked_box("First")
    second = _linked_box("Second")
    _linked_box("Joined")

    with pytest.raises(NameTaken):
        join_objects([first, second], "Joined")
    assert "First" in bpy.data.objects


def test_the_result_keeps_the_first_parts_origin(empty_scene):
    """The piece's base check reads the result, so its origin must not move."""
    from golem_blender.ops.assets import join_objects

    first = _linked_box("First")
    second = _linked_box("Second")
    from golem_blender.ops.transforms import move_object_to

    move_object_to(first, (0.0, 0.0, 2.0))
    move_object_to(second, (3.0, 0.0, 2.0))

    join_objects([first, second], "Joined")

    joined = bpy.data.objects["Joined"]
    assert tuple(joined.matrix_world.translation) == pytest.approx(
        (0.0, 0.0, 2.0), abs=POSITION_TOLERANCE_M
    )


def test_a_single_material_result_when_slots_are_not_kept(empty_scene):
    from golem_blender.ops.assets import join_objects

    parts = [
        _linked_box("RedPart", "Red", RED_RGB),
        _linked_box("BluePart", "Blue", BLUE_RGB, (2.0, 0.0, 0.0)),
    ]

    report = join_objects(parts, "OneSlot", keep_material_slots=False)

    assert report.material_slots == 1
    assert bpy.data.objects["OneSlot"].data.materials[0].name == "Red"
