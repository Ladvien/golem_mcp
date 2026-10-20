"""OT-3: the op tools are generated from the facade, and the set is pinned.

The hand-written service tools stay hand-written; every op tool is
introspected from a facade signature the OPS-21 contract guarantees.
Adding an op adds a tool, the parameters ARE the signature, every
numeric quantity carries a unit in its name, and the whole set the model
can call is fingerprinted like the assembled prompt (PRM-7) so a schema
change is visible in the iteration log.

Pure: no Blender.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import re
from pathlib import Path

import pytest

import golem_blender.ops as ops_facade
from golem_blender.agent import tool_schemas as generator
from golem_blender.agent.plan import PLAN_STEP_ARGUMENT, PLAN_STEP_SCHEMA
from golem_blender.agent.tools import (
    OP_TOOL_SCHEMAS,
    SERVICE_TOOL_SCHEMAS,
    TOOL_SCHEMAS,
    TOOL_SCHEMAS_FINGERPRINT,
)
from golem_blender.ops._contract import (
    UNIT_SUFFIXES,
    UNITLESS_NUMERIC_NAMES,
    ContractViolation,
    changes_scene,
    facade_ops,
    is_gated,
    returns_object_names,
)

PINNED_TOOL_SCHEMAS_FINGERPRINT_PATH = (
    Path(__file__).resolve().parents[2]
    / "_evaluate"
    / "golden"
    / "pinned_tool_schemas_fingerprint.txt"
)
_FINGERPRINT_PATTERN = re.compile(r"^t:[0-9a-f]{12}$")
NUMERIC_JSON_TYPES = {"number", "integer"}


def _op_tool(name: str) -> dict:
    return next(tool for tool in OP_TOOL_SCHEMAS if tool["function"]["name"] == name)


# --- a synthetic op, injected into the facade for one test ---------------


def _synthetic_op(object_name: str, lift_m: float, count: int = 2) -> str:
    """Lift the named object, count times.

    Longer explanation the schema must not carry.
    """
    return object_name


def _live_facade():
    """The facade module `facade_ops()` will see NOW. Resolved at call time
    because a dev-reload test elsewhere in the suite replaces the module
    object, and a patch on the collected-time import would miss it."""
    return importlib.import_module("golem_blender.ops")


@pytest.fixture()
def facade_with_synthetic_op(monkeypatch):
    facade = _live_facade()
    monkeypatch.setattr(facade, "_synthetic_op", _synthetic_op, raising=False)
    monkeypatch.setattr(facade, "__all__", [*facade.__all__, "_synthetic_op"])
    yield "_synthetic_op"


# --- the set ---------------------------------------------------------------


def test_tool_schemas_is_the_service_tools_plus_every_facade_op():
    assert TOOL_SCHEMAS == SERVICE_TOOL_SCHEMAS + OP_TOOL_SCHEMAS
    op_tool_names = [tool["function"]["name"] for tool in OP_TOOL_SCHEMAS]
    assert op_tool_names == [name for name, _ in facade_ops()]


def test_service_and_op_tool_names_are_disjoint():
    service = {tool["function"]["name"] for tool in SERVICE_TOOL_SCHEMAS}
    ops = {tool["function"]["name"] for tool in OP_TOOL_SCHEMAS}
    assert not service & ops


def test_adding_an_op_to_the_facade_adds_a_tool(facade_with_synthetic_op):
    before = {tool["function"]["name"] for tool in OP_TOOL_SCHEMAS}
    after = {tool["function"]["name"] for tool in generator.build_tool_schemas()}
    assert after - before == {facade_with_synthetic_op}


def test_a_contract_violation_refuses_the_whole_set(monkeypatch):
    def bad_op(blender_object, width: float):
        """Takes an object, not a name."""

    facade = _live_facade()
    monkeypatch.setattr(facade, "bad_op", bad_op, raising=False)
    monkeypatch.setattr(facade, "__all__", [*facade.__all__, "bad_op"])
    with pytest.raises(ContractViolation, match="bad_op"):
        generator.build_tool_schemas()


# --- each tool IS its signature --------------------------------------------


@pytest.mark.parametrize(
    "op_name,function", facade_ops(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_the_parameter_set_equals_the_signature(op_name, function):
    parameters = _op_tool(op_name)["function"]["parameters"]
    signature = inspect.signature(function)
    # plan_step is the harness's (OT-6): present on every scene-changing
    # op tool, absent from readers, never part of the signature.
    own_properties = [
        name for name in parameters["properties"] if name != PLAN_STEP_ARGUMENT
    ]
    assert own_properties == list(signature.parameters)
    assert (PLAN_STEP_ARGUMENT in parameters["properties"]) == changes_scene(function)
    assert PLAN_STEP_ARGUMENT not in parameters["required"]
    assert parameters["required"] == [
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty
    ]
    assert parameters["additionalProperties"] is False
    for name, parameter in signature.parameters.items():
        has_default = parameter.default is not inspect.Parameter.empty
        assert ("default" in parameters["properties"][name]) == has_default, name


@pytest.mark.parametrize(
    "op_name,function", facade_ops(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_every_numeric_parameter_carries_a_unit_in_its_name(op_name, function):
    properties = _op_tool(op_name)["function"]["parameters"]["properties"]
    for name, property_schema in properties.items():
        if name == PLAN_STEP_ARGUMENT:  # the harness's index, not a quantity
            continue
        if property_schema.get("type") not in NUMERIC_JSON_TYPES:
            continue
        assert name.endswith(UNIT_SUFFIXES) or name in UNITLESS_NUMERIC_NAMES, (
            f"{op_name}.{name} is numeric and carries no unit suffix"
        )


@pytest.mark.parametrize(
    "op_name,function", facade_ops(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_the_description_is_the_summary_and_the_return(op_name, function):
    description = _op_tool(op_name)["function"]["description"]
    summary = (inspect.getdoc(function) or "").split("\n", 1)[0].strip()
    assert description.startswith(summary)
    assert f"Returns {inspect.signature(function).return_annotation}." in description
    # OT-5: the gating marker is part of what the model reads, and only
    # an op whose return names an object carries one.
    if returns_object_names(function):
        expected = (
            generator.GATED_DESCRIPTION
            if is_gated(function)
            else generator.UNGATED_DESCRIPTION
        )
        assert description.endswith(expected), op_name
    else:
        assert generator.GATED_DESCRIPTION not in description
        assert generator.UNGATED_DESCRIPTION not in description


# --- the type mapping, case by case ------------------------------------------


def test_fixed_tuples_become_bounded_arrays():
    location = _op_tool("add_box")["function"]["parameters"]["properties"]["location_m"]
    assert location == {
        "type": "array",
        "items": {"type": "number"},
        "minItems": 3,
        "maxItems": 3,
        "default": [0.0, 0.0, 0.0],
    }


def test_optional_parameters_admit_null():
    rotation = _op_tool("keyframe_object_transform")["function"]["parameters"][
        "properties"
    ]["rotation_euler_deg"]
    assert rotation["anyOf"][1] == {"type": "null"}
    assert rotation["default"] is None


def test_a_config_dataclass_becomes_an_object_with_its_required_fields():
    spec = _op_tool("add_splayed_leg")["function"]["parameters"]["properties"]["spec"]
    assert spec["type"] == "object"
    assert spec["additionalProperties"] is False
    assert spec["required"] == [
        f.name
        for f in dataclasses.fields(ops_facade.SplayedLegSpec)
        if f.default is dataclasses.MISSING
    ]
    assert (
        spec["properties"]["segment_count"]["default"]
        == ops_facade.SplayedLegSpec.segment_count
    )


def test_a_tuple_of_dataclasses_becomes_an_array_of_objects():
    bones = _op_tool("add_armature")["function"]["parameters"]["properties"]["bones"]
    assert bones["type"] == "array"
    assert bones["items"]["type"] == "object"
    assert bones["items"]["required"] == ["name", "head_m", "tail_m"]


def test_an_unmappable_annotation_is_loud():
    with pytest.raises(generator.UnsupportedAnnotation):
        generator.json_schema_for_type(dict[str, int])
    with pytest.raises(generator.UnsupportedAnnotation):
        generator.json_schema_for_type(tuple[float, str])


# --- the fingerprint -----------------------------------------------------------


def test_the_fingerprint_has_its_own_prefix_and_width():
    assert _FINGERPRINT_PATTERN.match(TOOL_SCHEMAS_FINGERPRINT), (
        TOOL_SCHEMAS_FINGERPRINT
    )


def test_the_fingerprint_moves_when_a_schema_moves():
    changed = [dict(tool) for tool in TOOL_SCHEMAS]
    changed[0] = {
        **changed[0],
        "function": {**changed[0]["function"], "description": "moved"},
    }
    assert generator.tool_schemas_fingerprint(changed) != TOOL_SCHEMAS_FINGERPRINT


def test_the_tool_set_has_not_drifted():
    """Mirror of the assembled-prompt pin: the tools the model can call."""
    assert PINNED_TOOL_SCHEMAS_FINGERPRINT_PATH.exists(), (
        f"no {PINNED_TOOL_SCHEMAS_FINGERPRINT_PATH}: write it from "
        f"`tool_schemas_fingerprint()`'s own output, never by hand"
    )
    recorded = PINNED_TOOL_SCHEMAS_FINGERPRINT_PATH.read_text(encoding="utf-8").strip()
    assert TOOL_SCHEMAS_FINGERPRINT == recorded, (
        f"the tools the model can call changed: {recorded} -> "
        f"{TOOL_SCHEMAS_FINGERPRINT}. A facade signature, a docstring summary "
        f"or a service tool moved. If intended, update "
        f"{PINNED_TOOL_SCHEMAS_FINGERPRINT_PATH.name} in the same commit."
    )


def test_the_four_unlinked_constructors_are_the_only_ungated_object_returners():
    """Measured set (OT-5): add_box, add_cylinder, add_lathe and
    add_relief_slab return an object nothing has linked yet. Every other
    op whose return names an object is gated. A new ungated op must be
    added here on purpose."""
    ungated = sorted(
        name
        for name, function in facade_ops()
        if returns_object_names(function) and not is_gated(function)
    )
    assert ungated == ["add_box", "add_cylinder", "add_lathe", "add_relief_slab"]
    assert not returns_object_names(
        ops_facade.assign_material
    )  # a material name, not an object
    assert not returns_object_names(ops_facade.orientation_reading)  # prose
    assert is_gated(ops_facade.link_into_scene) and is_gated(ops_facade.boolean_union)


def test_the_readers_are_the_only_plan_free_op_tools():
    """Measured set (OT-6): reports, readings and pure computations."""
    readers = sorted(
        name for name, function in facade_ops() if not changes_scene(function)
    )
    assert readers == [
        "animation_report",
        "body_capsules_report",
        "canonical_depth_axis_rotation_euler_rad",
        "clip_self_intersection_report",
        "deforming_bone_names",
        "depth_axis_extent_rank",
        "depth_axis_holds_middle_extent",
        "material_report",
        "middle_extent_m",
        "orientation_reading",
        "pbr_texture_report",
        "relief_slab_report",
        "rig_report",
        "select_edges",
        "select_faces",
        "select_vertices",
        "weight_report",
        "world_bounds",
    ]
    assert (
        _op_tool("add_box")["function"]["parameters"]["properties"][PLAN_STEP_ARGUMENT]
        == PLAN_STEP_SCHEMA
    )


# --- selectors (OT-14): an enum of kinds, round-tripped -----------------------


def test_a_selector_round_trips_as_an_object_with_an_enum_of_kinds():
    from golem_blender.agent.op_call import ArgumentError, convert_argument
    from golem_blender.ops.selectors import EDGE_SELECTOR_KINDS, EdgeSelector

    schema = generator.json_schema_for_type(EdgeSelector)
    assert schema["type"] == "object"
    assert schema["properties"]["kind"] == {
        "type": "string",
        "enum": list(EDGE_SELECTOR_KINDS),
    }
    assert schema["required"] == ["kind"]
    assert schema["properties"]["minimum_dihedral_angle_deg"]["default"] == 30.0

    bound = convert_argument(
        EdgeSelector, {"kind": "material_slot", "material_slot_index": 1}, "x.edges"
    )
    assert bound == EdgeSelector(kind="material_slot", material_slot_index=1)
    with pytest.raises(ArgumentError, match="kind"):
        convert_argument(EdgeSelector, {"kind": "by_colour"}, "x.edges")


def test_the_select_ops_are_readers_with_selector_parameters():
    for name in ("select_edges", "select_faces", "select_vertices"):
        tool = _op_tool(name)["function"]
        assert tool["parameters"]["properties"]["selector"]["properties"]["kind"][
            "enum"
        ]
        assert PLAN_STEP_ARGUMENT not in tool["parameters"]["properties"]  # a reader
