"""Issue #22's layouts, as the tool surface and the argument door see them.

The Blender layer (`tests/blender/test_array_ops.py`) measures the geometry.
This layer is what runs everywhere: the three ops are on the facade, each is an
ACTION tool (a scene change, so it carries `plan_step`), each is gated and
carries its report, and the arguments the schema offers are the arguments the
binding accepts.

A count below 1 and a repeating axis at zero pitch are refused BEFORE the op
touches bpy, so the refusal is testable with no Blender — which is the point:
the loud message arrives before a partial mesh can be left in the scene.
"""

from __future__ import annotations

import typing

import pytest

import golem_blender.ops as ops_facade
from golem_blender.agent.op_call import ArgumentError, bind_arguments
from golem_blender.agent.tool_schemas import op_tool_schema
from golem_blender.ops._contract import GATE_TARGET_FIELD, changes_scene, is_gated

ARRAY_OPS = ("grid_array", "path_array", "radial_array")


@pytest.mark.parametrize("op_name", ARRAY_OPS)
def test_each_layout_is_a_gated_action_tool_carrying_its_report(op_name):
    function = getattr(ops_facade, op_name)

    assert changes_scene(function), f"{op_name} changes the scene, so it needs a plan"
    assert is_gated(function), f"{op_name} returns a report naming its object"
    # The gate finds the object through the report's own field (OT-5).
    report_type = typing.get_type_hints(function)["return"]
    assert report_type is ops_facade.ArrayReport
    assert GATE_TARGET_FIELD in report_type.__dataclass_fields__


def test_the_grid_schema_takes_a_per_axis_count_and_spacing():
    properties = op_tool_schema("grid_array", ops_facade.grid_array)["function"][
        "parameters"
    ]["properties"]

    assert properties["counts"] == {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 3,
        "maxItems": 3,
    }
    assert properties["spacing_m"] == {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
    }


def test_the_ring_schema_defaults_a_plain_ring():
    properties = op_tool_schema("radial_array", ops_facade.radial_array)["function"][
        "parameters"
    ]["properties"]

    assert properties["turn_rad"]["default"] == 0.0
    assert properties["start_bearing_rad"]["default"] == 0.0


def test_the_path_schema_takes_a_list_of_points():
    properties = op_tool_schema("path_array", ops_facade.path_array)["function"][
        "parameters"
    ]["properties"]

    assert properties["points_m"] == {
        "type": "array",
        "items": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 3,
            "maxItems": 3,
        },
    }


def test_the_binding_reads_json_points_into_tuples():
    """JSON has no tuples: the binding is what turns three numbers into a point."""
    arguments = bind_arguments(
        "path_array",
        ops_facade.path_array,
        {"object_name": "Rung", "points_m": [[0, 0, 1], [1, 0, 1]]},
    )

    assert arguments["points_m"] == [(0.0, 0.0, 1.0), (1.0, 0.0, 1.0)]


def test_a_grid_axis_with_no_copy_is_refused_before_bpy():
    with pytest.raises(ValueError, match=r"counts\[1\] is 0"):
        ops_facade.grid_array("Stake", counts=(2, 0, 1), spacing_m=(1.0, 1.0, 1.0))


def test_a_zero_pitch_on_a_repeating_axis_is_refused_before_bpy():
    with pytest.raises(ValueError, match=r"spacing_m\[0\] is 0"):
        ops_facade.grid_array("Stake", counts=(2, 1, 1), spacing_m=(0.0, 1.0, 1.0))


def test_a_ring_with_no_copy_is_refused_before_bpy():
    with pytest.raises(ValueError, match="count must be at least 1"):
        ops_facade.radial_array("Stone", count=0, radius_m=1.0)


def test_an_empty_path_is_refused_before_bpy():
    with pytest.raises(ValueError, match="points_m is empty"):
        ops_facade.path_array("Rung", [])


def test_a_short_point_is_refused_before_bpy():
    with pytest.raises(ValueError, match="3 coordinates"):
        ops_facade.path_array("Rung", [(0.0, 0.0)])


def test_a_wrong_arity_grid_is_refused_before_bpy():
    with pytest.raises(ValueError, match="exactly 3 values"):
        ops_facade.grid_array("Stake", counts=(2, 1), spacing_m=(1.0, 1.0))


def test_the_binding_rejects_a_point_that_is_not_three_numbers():
    with pytest.raises(ArgumentError, match=r"points_m\[0\]"):
        bind_arguments(
            "path_array",
            ops_facade.path_array,
            {"object_name": "Rung", "points_m": [[0, 0]]},
        )


def test_the_tool_path_gates_the_report_object():
    """The dispatcher must find the object in the REPORT, not iterate it.

    `join_objects` crashed its first live call doing exactly that
    (`TypeError: 'JoinReport' object is not iterable`), so the same door is
    checked for `ArrayReport` here rather than discovered again in a session.
    """
    from golem_blender.agent.op_call import _returned_object_names

    report = ops_facade.ArrayReport(
        object_name="Stake",
        copies=6,
        skipped_point_count=0,
        triangle_count_before=12,
        triangle_count=72,
        material_slots=1,
        connected_component_count=6,
        copy_origins_m=((0.0, 0.0, 0.0),),
        overlapping_copy_pair_count=0,
        self_intersecting_face_pair_count=0,
        below_ground_copy_count=0,
        bounds_min_m=(0.0, 0.0, 0.0),
        bounds_max_m=(1.0, 1.0, 1.0),
    )

    for op_name in ARRAY_OPS:
        function = getattr(ops_facade, op_name)
        assert _returned_object_names(function, report) == ("Stake",), op_name
