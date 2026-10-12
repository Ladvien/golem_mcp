"""Rotation and placement must be in the whitelisted vocabulary.

Measured 2026-08-22 (iteration 3, three_leg_stool): the vocabulary had
no rotate op, so an agent building splayed legs spent three search_ops
calls and a dir() probe discovering that, then improvised. These ops
close the hole and bake in the depsgraph refresh that the stale
matrix_world trap requires.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

from mathutils import Vector

pytestmark = pytest.mark.blender

QUARTER_TURN_RAD = math.pi / 2.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _tall_box():
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("Subject", 0.1, 0.1, 1.0)
    link_into_scene(box)
    return box


def test_rotation_reaches_matrix_world_immediately(empty_scene):
    """The whole point: no caller should have to know about the depsgraph."""
    from blended.ops.transforms import rotate_object_euler

    box = _tall_box()
    rotate_object_euler(box, y_rad=QUARTER_TURN_RAD)
    box_obj = bpy.data.objects[box]
    assert box_obj.matrix_world.to_euler().y == pytest.approx(QUARTER_TURN_RAD)

    # A box 1.0 m tall on Z, tipped a quarter turn about Y, occupies 1.0 m
    # on X in the WORLD. Note object.dimensions still reports (0.1, 0.1,
    # 1.0): it is the local bounding box times scale and ignores rotation
    # entirely. Measure world extents, or measure the wrong thing.
    world_x = [
        (box_obj.matrix_world @ Vector(corner)).x for corner in box_obj.bound_box
    ]
    assert max(world_x) - min(world_x) == pytest.approx(1.0, abs=1e-5)
    assert box_obj.dimensions.x == pytest.approx(0.1, abs=1e-5), (
        "object.dimensions is expected to IGNORE rotation; if this ever "
        "changes, the drift catalog entry is stale"
    )


def test_rotation_is_set_not_accumulated(empty_scene):
    """Re-running a chunk must not spin the object twice."""
    from blended.ops.transforms import rotate_object_euler

    box = _tall_box()
    rotate_object_euler(box, y_rad=QUARTER_TURN_RAD)
    rotate_object_euler(box, y_rad=QUARTER_TURN_RAD)

    assert bpy.data.objects[box].matrix_world.to_euler().y == pytest.approx(
        QUARTER_TURN_RAD
    )


def test_rotation_survives_apply_object_transform(empty_scene):
    """The historical failure: rotation set, transform applied, vertices
    untouched because matrix_world was still stale."""
    from blended.ops.transforms import apply_object_transform, rotate_object_euler

    box = _tall_box()
    rotate_object_euler(box, y_rad=QUARTER_TURN_RAD)
    apply_object_transform(box)

    box_obj = bpy.data.objects[box]
    extent_x = max(v.co.x for v in box_obj.data.vertices) - min(
        v.co.x for v in box_obj.data.vertices
    )
    assert extent_x == pytest.approx(1.0, abs=1e-5), (
        "rotation was not baked into the mesh — matrix_world was stale"
    )


def test_move_object_to_reaches_matrix_world_immediately(empty_scene):
    from blended.ops.transforms import move_object_to

    box = _tall_box()
    move_object_to(box, (0.25, -0.5, 0.75))

    assert tuple(bpy.data.objects[box].matrix_world.translation) == pytest.approx(
        (0.25, -0.5, 0.75)
    )


def test_both_ops_are_discoverable_through_search(empty_scene, tmp_path):
    """A whitelisted op nobody can find is not whitelisted."""
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool(
        "search_ops", {"query": "rotate"}, output_directory=tmp_path
    )
    text, _ = _outcome.text, list(_outcome.images)
    assert "rotate_object_euler" in text


# The exact queries iteration 4 sent, with the answer each one deserved.
# Every one of these came back "No operation matches" and cost a turn.
MULTI_WORD_SEARCHES_FROM_ITERATION_4 = (
    ("boolean union", "boolean_union"),
    ("material assign", "assign_material"),
    ("assign material", "assign_material"),
)


@pytest.mark.parametrize(
    ("query", "expected_operation"), MULTI_WORD_SEARCHES_FROM_ITERATION_4
)
def test_multi_word_search_finds_the_op(
    empty_scene, tmp_path, query, expected_operation
):
    """Word order and underscores must not hide an operation.

    Measured 2026-08-22 (iteration 4): the agent spent 3 of its 16 turns
    on these three queries. All three ops existed; the matcher tested the
    query as one substring, so it could not span the underscore in
    `boolean_union` and could not survive reversed word order.
    """
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool("search_ops", {"query": query}, output_directory=tmp_path)
    text, _ = _outcome.text, list(_outcome.images)
    assert expected_operation in text, text


def test_search_still_narrows(empty_scene, tmp_path):
    """Matching words must not turn every query into a catalogue dump:
    every word has to appear, so more words match fewer ops."""
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool(
        "search_ops", {"query": "object"}, output_directory=tmp_path
    )
    broad, _ = _outcome.text, list(_outcome.images)
    _outcome = dispatch_tool(
        "search_ops", {"query": "rotate object euler"}, output_directory=tmp_path
    )
    narrow, _ = _outcome.text, list(_outcome.images)
    assert "rotate_object_euler" in narrow
    # One `schema:` line per hit (OT-15).
    assert narrow.count("    schema: ") < broad.count("    schema: ")


def test_a_query_with_no_words_is_refused(empty_scene, tmp_path):
    """Splitting on punctuation makes an all-punctuation query empty, and
    `all()` of an empty list is True — which would silently match every
    op in the manifest. It is refused instead."""
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool("search_ops", {"query": "???"}, output_directory=tmp_path)
    text, _ = _outcome.text, list(_outcome.images)
    assert "no searchable words" in text
    assert "blended.ops." not in text
