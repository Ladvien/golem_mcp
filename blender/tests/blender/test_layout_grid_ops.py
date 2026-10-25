"""Several separate models laid out in one grid, measured in Blender.

`grid_array` copies ONE object into ONE mesh; these tests are the other
question — N models that must stay separate and stay pieces. Each
acceptance below is measured on the scene after the call (re-measured
world boxes, world matrices), not asserted from the arithmetic: the
arithmetic is `tests/pure/test_layout_grid.py`.

The `empty_scene` fixture is `test_pieces.py`'s, because the piece
registry is session state and a name left over from another test would
answer for it.
"""

import dataclasses

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

# A micrometre: far under any modelling tolerance, and the precision the
# viewport signatures round to.
POSITION_TOLERANCE_M = 1.0e-6


@pytest.fixture()
def empty_scene():
    """A clean scene AND a clean piece registry."""
    from golem_blender.ops import pieces

    bpy.ops.wm.read_factory_settings(use_empty=True)
    pieces._PIECES.clear()
    yield
    pieces._PIECES.clear()


def _linked_box(name, size_m=(1.0, 1.0, 1.0), location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops import add_box, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    return box_name


def _box(bounds_min_m, bounds_max_m, name) -> None:
    from golem_blender.ops import add_box, link_into_scene

    box_name = add_box(
        name,
        bounds_max_m[0] - bounds_min_m[0],
        bounds_max_m[1] - bounds_min_m[1],
        bounds_max_m[2] - bounds_min_m[2],
        (
            (bounds_min_m[0] + bounds_max_m[0]) / 2.0,
            (bounds_min_m[1] + bounds_max_m[1]) / 2.0,
            bounds_min_m[2],
        ),
    )
    link_into_scene(box_name)


def _world_box(name):
    from golem_blender.ops.transforms import _world_bounds_m

    return _world_bounds_m([bpy.data.objects[name]])


# --- 1. the grid is a grid -------------------------------------------------


def test_four_boxes_at_the_origin_are_laid_out_in_two_by_two(empty_scene):
    """The case this op exists for: before it, all four sat at the origin and
    the viewport showed one box."""
    from golem_blender.ops import lay_out_grid

    names = [_linked_box(f"Model{i}") for i in range(4)]

    report = lay_out_grid(item_names=names)

    assert (report.item_count, report.column_count, report.row_count) == (4, 2, 2)
    assert [cell.item_name for cell in report.cells] == names
    assert [(cell.column, cell.row) for cell in report.cells] == [
        (0, 0),
        (1, 0),
        (0, 1),
        (1, 1),
    ]
    # Nothing overlaps, and everything is grounded.
    boxes = [(cell.bounds_min_m, cell.bounds_max_m) for cell in report.cells]
    for index, (minimum, maximum) in enumerate(boxes):
        assert minimum[2] == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
        for other_index, (other_minimum, other_maximum) in enumerate(boxes):
            if other_index == index:
                continue
            overlaps = all(
                minimum[axis] < other_maximum[axis] - POSITION_TOLERANCE_M
                and other_minimum[axis] < maximum[axis] - POSITION_TOLERANCE_M
                for axis in range(3)
            )
            assert not overlaps, f"cells {index} and {other_index} overlap"


def test_the_report_is_the_scene_not_the_arithmetic(empty_scene):
    """Each cell's box is re-measured after the move, so it must equal what
    Blender reads for the object now."""
    from golem_blender.ops import lay_out_grid

    first = _linked_box("MeasuredA", (0.5, 0.5, 2.0))
    second = _linked_box("MeasuredB")

    report = lay_out_grid(item_names=[first, second])

    for cell in report.cells:
        minimum, maximum = _world_box(cell.object_names[0])
        assert cell.bounds_min_m == pytest.approx(minimum)
        assert cell.bounds_max_m == pytest.approx(maximum)


# --- 2. a piece is one cell ------------------------------------------------


def test_a_prefix_group_is_one_cell_and_keeps_its_shape(empty_scene):
    """`Post__Wood` at z 0 with `Post__Iron` stacked on it is one post: splitting
    it across two cells would show two half-posts."""
    from golem_blender.ops import lay_out_grid

    _linked_box("Post__Wood", (0.3, 0.3, 1.0), (0.0, 0.0, 0.0))
    _linked_box("Post__Iron", (0.3, 0.3, 1.0), (0.0, 0.0, 1.0))
    before = {
        name: bpy.data.objects[name].matrix_world.copy()
        for name in ("Post__Wood", "Post__Iron")
    }

    report = lay_out_grid(item_names=["Post__Wood", "Post__Iron"])

    assert report.item_count == 1
    assert report.cells[0].item_name == "Post"
    assert report.cells[0].object_names == ("Post__Iron", "Post__Wood")
    offset_before = before["Post__Iron"].translation - before["Post__Wood"].translation
    offset_after = (
        bpy.data.objects["Post__Iron"].matrix_world.translation
        - bpy.data.objects["Post__Wood"].matrix_world.translation
    )
    assert tuple(offset_after) == pytest.approx(tuple(offset_before))


def test_a_bare_prefix_moves_the_whole_piece(empty_scene):
    """The same post named by its bare prefix: this is how a shelf moves one
    approved kitbash piece without listing its material objects."""
    from golem_blender.ops import lay_out_grid

    _linked_box("Prop__Wood", (0.3, 0.3, 1.0))
    _linked_box("Prop__Iron", (0.3, 0.3, 1.0), (0.0, 0.0, 1.0))

    report = lay_out_grid(item_names=["Prop"])

    assert report.item_count == 1
    assert report.cells[0].object_names == ("Prop__Iron", "Prop__Wood")
    assert report.cells[0].bounds_min_m[2] == pytest.approx(
        0.0, abs=POSITION_TOLERANCE_M
    )


def test_an_unlisted_sibling_does_not_join_a_listed_object(empty_scene):
    """A prefix group is what the CALLER listed, not every `__` sibling that
    happens to exist: otherwise laying out `Post__Wood` would silently drag in
    a part the caller was inspecting separately."""
    from golem_blender.ops import lay_out_grid

    listed = _linked_box("Post__Wood", (0.3, 0.3, 1.0))
    unlisted = _linked_box("Post__Iron", (0.3, 0.3, 1.0))
    before = bpy.data.objects[unlisted].matrix_world.copy()

    report = lay_out_grid(item_names=[listed])

    assert report.cells[0].object_names == (listed,)
    assert tuple(bpy.data.objects[unlisted].matrix_world.translation) == pytest.approx(
        tuple(before.translation)
    )


def test_a_defined_piece_moves_as_one_cell(empty_scene):
    from golem_blender.ops import define_piece, lay_out_grid

    base = _linked_box("LampBase", (0.4, 0.4, 0.2))
    shade = _linked_box("LampShade", (0.6, 0.6, 0.4), (0.0, 0.0, 0.2))
    define_piece("Lamp", [base, shade])
    other = _linked_box("Box")

    report = lay_out_grid(item_names=["Lamp", "Box"])

    assert report.item_count == 2
    assert report.cells[0].item_name == "Lamp"
    assert report.cells[0].object_names == ("LampBase", "LampShade")
    assert report.cells[1].object_names == (other,)
    # The piece kept its own shape: the shade is still above the base.
    assert _world_box(shade)[0][2] == pytest.approx(
        _world_box(base)[1][2], abs=POSITION_TOLERANCE_M
    )


# --- 3. clear of everything else, or told where to be ----------------------


def test_the_grid_defaults_to_clear_of_another_model_in_the_scene(empty_scene):
    """A building at the origin: the shelf must not be laid out inside it."""
    from golem_blender.ops import lay_out_grid

    _box((-4.3, -4.443, 0.0), (4.3, 3.3, 3.0), "Building")
    names = [_linked_box(f"Shelf{i}") for i in range(3)]

    report = lay_out_grid(item_names=names)

    for cell in report.cells:
        assert cell.bounds_min_m[0] > 4.3
    assert report.overlaps_with == ()


def test_a_forced_origin_that_overlaps_is_reported_not_refused(empty_scene):
    """The caller asked for that origin; the op's job is to say what it costs."""
    from golem_blender.ops import lay_out_grid

    _box((-4.3, -4.443, 0.0), (4.3, 3.3, 3.0), "Building")
    names = [_linked_box(f"Shelf{i}") for i in range(3)]

    report = lay_out_grid(item_names=names, origin_m=(0.0, 0.0, 0.0))

    assert report.overlaps_with == ("Building",)


def test_a_scene_holding_only_the_layout_has_nothing_to_overlap(empty_scene):
    from golem_blender.ops import lay_out_grid

    report = lay_out_grid(item_names=[_linked_box("Only")])

    assert report.overlaps_with == ()
    assert report.origin_m == pytest.approx((0.0, 0.0, 0.0))


# --- 4. a refusal leaves the scene untouched -------------------------------


def test_a_missing_name_moves_nothing(empty_scene):
    from golem_blender.ops import lay_out_grid
    from golem_blender.ops._objects import UnknownObject

    present = _linked_box("Present")
    before = bpy.data.objects[present].matrix_world.copy()

    with pytest.raises(UnknownObject, match="Ghost"):
        lay_out_grid(item_names=[present, "Ghost"])

    assert bpy.data.objects[present].matrix_world == before


def test_an_unlinked_object_is_refused_before_anything_moves(empty_scene):
    """`add_box` returns exactly such an intermediate, and an unlinked object is
    invisible to a render: laying it out would move nothing anyone can see."""
    from golem_blender.ops import add_box, lay_out_grid

    linked = _linked_box("Linked")
    before = bpy.data.objects[linked].matrix_world.copy()
    unlinked = add_box("Unlinked", 1.0, 1.0, 1.0)

    with pytest.raises(ValueError, match="not linked into the scene"):
        lay_out_grid(item_names=[linked, unlinked])

    assert bpy.data.objects[linked].matrix_world == before


def test_one_object_in_two_items_is_refused(empty_scene):
    """A listed object that is also a member of a listed piece."""
    from golem_blender.ops import define_piece, lay_out_grid

    base = _linked_box("LampBase", (0.4, 0.4, 0.2))
    shade = _linked_box("LampShade", (0.6, 0.6, 0.4), (0.0, 0.0, 0.2))
    define_piece("Lamp", [base, shade])

    with pytest.raises(ValueError, match="two items|already an item"):
        lay_out_grid(item_names=["Lamp", base])


def test_an_item_with_no_mesh_is_refused(empty_scene):
    from golem_blender.ops import BoneSpec, add_armature, lay_out_grid

    armature_name = add_armature(
        "Lone__rig", (BoneSpec("root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.5)),)
    )

    with pytest.raises(ValueError, match="no MESH members"):
        lay_out_grid(item_names=[armature_name])


# --- 5. the roots move, the children follow -------------------------------


def test_a_child_of_an_unlisted_empty_lands_in_its_cell(empty_scene):
    """The child's `.location` is parent-relative, so a move that wrote it would
    land somewhere the arithmetic never asked for — and the empty, which the
    caller did not list, must not move at all."""
    from golem_blender.ops import lay_out_grid

    empty = bpy.data.objects.new("Holder", None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = (3.0, -2.0, 0.0)
    child = _linked_box("Held__Box", (0.5, 0.5, 1.0))
    bpy.data.objects[child].parent = empty
    bpy.context.view_layer.update()
    empty_before = empty.matrix_world.copy()

    report = lay_out_grid(item_names=[child], origin_m=(0.0, 0.0, 0.0), gap_m=0.0)

    cell = report.cells[0]
    assert tuple(empty.matrix_world.translation) == pytest.approx(
        tuple(empty_before.translation)
    )
    minimum, maximum = _world_box(child)
    assert tuple(minimum) == pytest.approx(cell.bounds_min_m)
    assert tuple(maximum) == pytest.approx(cell.bounds_max_m)
    # The cell is centred on the origin, grounded at 0.
    assert (minimum[0] + maximum[0]) / 2.0 == pytest.approx(
        0.0, abs=POSITION_TOLERANCE_M
    )
    assert minimum[2] == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)


def test_the_report_serialises_as_a_tool_result(empty_scene):
    """The report travels through `op_call`'s generic dataclass path; a field
    that cannot become JSON would fail at the tool boundary, not here."""
    from golem_blender.agent.op_call import json_returned
    from golem_blender.ops import lay_out_grid

    report = lay_out_grid(item_names=[_linked_box("SerialA"), _linked_box("SerialB")])

    returned = json_returned(report)
    assert returned["item_count"] == 2
    assert len(returned["cells"]) == 2
    assert set(returned["cells"][0]) == {
        field.name for field in dataclasses.fields(type(report.cells[0]))
    }
