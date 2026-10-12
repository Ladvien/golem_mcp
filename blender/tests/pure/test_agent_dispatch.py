"""The tool-dispatch seam: WHERE a tool call is executed.

`bpy` is main-thread only, but the agent loop runs on a worker thread
because a model call blocks for seconds to minutes. So the live-Blender
frontend has to move tool execution back to the main thread, and that
only works if the loop calls the dispatcher it was HANDED.

Regression: the seam used to be a monkeypatch on this module, while
`send` resolved `dispatch_tool` by local import — so the patch was
never seen, every tool call ran bpy on the worker thread, and Blender
segfaulted inside its own draw loop with nothing in any traceback.

These tests are deliberately in the pure layer: no bpy anywhere. If the
loop ever reaches for the real dispatcher again, `import bpy` fails
here and the test goes red — which is exactly the signal that was
missing when Blender was simply dying.
"""

import dataclasses
import json
import threading

import pytest

from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome

TOOL_CALL_REPLY = {
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {
            "function": {
                "name": "run_python",
                "arguments": {"source": "pass", "object_name": "Crate"},
            }
        }
    ],
}
ANSWER_REPLY = {"role": "assistant", "content": "Built Crate — gate passed."}


class ScriptedClient:
    """Replays fixed assistant messages so the LOOP is what's tested."""

    def __init__(self, replies):
        from blended.agent.loop import ModelConfig

        self.replies = list(replies)

        self.spent = TurnCost()
        self.seen_messages = []
        self.config = dataclasses.replace(
            ModelConfig.from_environment(), model="scripted", vision_model=""
        )

    def chat(self, messages, tools=None):
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


def _session(dispatch, output_directory):
    from blended.agent.loop import AgentSession

    return AgentSession(
        client=ScriptedClient([TOOL_CALL_REPLY, ANSWER_REPLY]),
        output_directory=output_directory,
        dispatch=dispatch,
    )


def test_the_injected_dispatcher_is_what_runs_the_tool(tmp_path):
    calls = []

    def recording_dispatch(tool_name, arguments, output_directory):
        calls.append((tool_name, arguments, output_directory))
        return ToolOutcome("GATE PASS")

    answer = _session(recording_dispatch, tmp_path).send("Make me a crate.")

    assert answer == "Built Crate — gate passed."
    assert [tool_name for tool_name, _, _ in calls] == ["run_python"]
    assert calls[0][1]["object_name"] == "Crate"
    # The session's own output directory, not the dispatcher's default.
    assert calls[0][2] == tmp_path


def test_a_turn_driven_off_the_main_thread_still_uses_the_injection(tmp_path):
    """The exact shape of the crash: the turn runs on a worker thread.

    The frontend's dispatcher is where the handoff back to the main
    thread lives, so it MUST be what gets called from there.
    """
    dispatching_threads = []

    def recording_dispatch(tool_name, arguments, output_directory):
        dispatching_threads.append(threading.current_thread())
        return ToolOutcome("GATE PASS")

    session = _session(recording_dispatch, tmp_path)
    worker = threading.Thread(target=lambda: session.send("Make me a crate."))
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "the turn never finished"
    assert dispatching_threads == [worker]


def test_the_default_dispatcher_runs_on_the_calling_thread():
    """Guards the dataclass trap: a function default must stay unbound.

    If `dispatch` were resolved as a class attribute it would bind as a
    method and be handed a phantom `self`.
    """
    from blended.agent.loop import AgentSession, dispatch_here

    assert AgentSession().dispatch is dispatch_here


def test_touching_bpy_off_the_main_thread_is_an_error_not_a_segfault():
    """The backstop under the seam, at the point bpy is reached."""
    from blended.agent.tools import dispatch_tool

    failures = []

    def call_from_worker():
        try:
            dispatch_tool("list_scene", {}, None)
        except BaseException as error:  # noqa: BLE001 — the assertion IS the error
            failures.append(error)

    worker = threading.Thread(target=call_from_worker, name="not-main")
    worker.start()
    worker.join(timeout=10)

    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeError)
    assert "not the main thread" in str(failures[0])


def test_the_main_thread_reaches_bpy(monkeypatch):
    """The guard must not be the reason nothing ever runs.

    Called on the main thread it falls through to the real body, whose
    first act is `import bpy` — absent in the pure layer, which is the
    observable proof that the guard let it past.
    """
    from blended.agent.tools import dispatch_tool

    with pytest.raises(ModuleNotFoundError, match="bpy"):
        dispatch_tool("list_scene", {}, None)


def test_iteration_record_carries_the_models_that_ran():
    """A prompt is tuned against a model, not in the abstract.

    v1-v5 were scored against deepseek-v4-flash; comparing a later run
    on a different writer without recording which one would attribute a
    model change to the prompt.
    """
    from blended.evaluate.iteration_log import IterationRecord

    record = IterationRecord(
        iteration=1,
        brief_name="three_leg_stool",
        prompt_identity="v5:6eadb9526276",
        prompt_revision=5,
        started_at="2026-08-22T00:00:00+00:00",
        writer_model="deepseek-v4-pro:cloud",
        vision_model="minimax-m3:cloud",
    )
    assert record.writer_model == "deepseek-v4-pro:cloud"
    assert record.vision_model == "minimax-m3:cloud"


def test_a_rebuilt_refinement_does_not_count_as_passed():
    """The refinement turn is a gate, not a bonus.

    A run whose follow-up instruction triggered a full rebuild can still
    satisfy the brief — that is exactly why preservation is measured
    against the BEFORE values rather than against the spec — so the
    iteration must not read as clean.
    """
    from blended.evaluate.iteration_log import IterationRecord

    base = {
        "iteration": 1,
        "brief_name": "three_leg_stool",
        "prompt_identity": "v6:deadbeef",
        "prompt_revision": 6,
        "started_at": "2026-08-22T00:00:00+00:00",
        "structural_gate_passed": True,
        "form_gate_passed": True,
        "visual_inspected": True,
    }
    assert IterationRecord(**base).passed
    assert not IterationRecord(
        **base,
        refinement_gate_passed=False,
        refinement_failures=("seat_diameter_x moved +0.0180 m",),
    ).passed


# --- op tools (OT-4, AGT-21): a facade op called as a tool -------------------
#
# `middle_extent_m` is a facade op with no bpy in its body, so the WHOLE
# path — door check, binding, capture, stage — runs in the pure layer.


def test_an_op_tool_call_binds_runs_and_reports_done():
    from blended.agent.op_call import call_op
    from blended.agent.tools import OP_FUNCTIONS, dispatch_tool
    from blended.stages import STAGE_DONE

    outcome = dispatch_tool("middle_extent_m", {"extents_m": [0.3, 0.2, 0.25]}, None)

    assert outcome.text.startswith("OK: middle_extent_m")
    assert "returned: 0.25" in outcome.text
    assert outcome.images == ()
    result = call_op(
        "middle_extent_m",
        OP_FUNCTIONS["middle_extent_m"],
        {"extents_m": [0.3, 0.2, 0.25]},
    )
    assert result.ok and result.stage_reached == STAGE_DONE
    assert result.bound_arguments == {"extents_m": (0.3, 0.2, 0.25)}


def test_an_unregistered_tool_is_refused_at_the_door_without_bpy():
    """Neither a service tool nor a facade op: refused before `import bpy`,
    which is what makes this assertion possible in the pure layer."""
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool("add_boxx", {"name": "Crate"}, None)
    assert outcome.text == "Unknown tool: add_boxx" and outcome.ok is False


def test_a_mistyped_argument_fails_at_execute_with_the_cause_and_no_traceback():
    from blended.agent.tools import dispatch_tool

    text = dispatch_tool("middle_extent_m", {"extents_m": "big"}, None).text

    assert text.startswith("FAILED at execute: middle_extent_m")
    assert "ArgumentError" in text and "expected an array" in text
    assert "Traceback" not in text


def test_unknown_and_missing_parameters_are_named():
    from blended.agent.op_call import ArgumentError, bind_arguments
    from blended.agent.tools import OP_FUNCTIONS

    with pytest.raises(ArgumentError, match=r"unknown parameter\(s\) \['widht_m'\]"):
        bind_arguments(
            "add_box",
            OP_FUNCTIONS["add_box"],
            {"name": "Crate", "widht_m": 0.5, "depth_m": 0.5, "height_m": 0.5},
        )
    with pytest.raises(
        ArgumentError, match=r"missing required parameter\(s\) \['height_m'\]"
    ):
        bind_arguments(
            "add_box",
            OP_FUNCTIONS["add_box"],
            {"name": "Crate", "width_m": 0.5, "depth_m": 0.5},
        )


def test_arguments_are_converted_to_the_signature_types():
    """JSON in, the op's own types out — the same hints the schema came from."""
    from pathlib import Path

    from blended.agent.op_call import bind_arguments
    from blended.agent.tools import OP_FUNCTIONS
    from blended.ops import BoneSpec, SplayedLegSpec

    leg = bind_arguments(
        "add_splayed_leg",
        OP_FUNCTIONS["add_splayed_leg"],
        {
            "name": "Leg",
            "spec": {
                "foot_radius_m": 0.14,
                "foot_bearing_deg": 0,
                "top_radius_m": 0.1,
                "top_z_m": 0.4,
                "leg_radius_m": 0.02,
            },
        },
    )
    assert isinstance(leg["spec"], SplayedLegSpec)
    assert leg["spec"].foot_bearing_deg == 0.0 and isinstance(
        leg["spec"].foot_bearing_deg, float
    )

    armature = bind_arguments(
        "add_armature",
        OP_FUNCTIONS["add_armature"],
        {
            "name": "Rig",
            "bones": [{"name": "root", "head_m": [0, 0, 0], "tail_m": [0, 0, 0.5]}],
        },
    )
    assert armature["bones"] == (
        BoneSpec(name="root", head_m=(0.0, 0.0, 0.0), tail_m=(0.0, 0.0, 0.5)),
    )

    textured = bind_arguments(
        "assign_image_texture_material",
        OP_FUNCTIONS["assign_image_texture_material"],
        {"object_name": "Crate", "name": "Wood", "image_path": "textures/wood.png"},
    )
    assert textured["image_path"] == Path("textures/wood.png")

    keyed = bind_arguments(
        "keyframe_object_transform",
        OP_FUNCTIONS["keyframe_object_transform"],
        {"object_name": "Crate", "frame": 1, "location_m": None, "scale": [1, 1, 1]},
    )
    assert keyed["location_m"] is None and keyed["scale"] == (1.0, 1.0, 1.0)


def test_binding_is_strict_about_json_types():
    from blended.agent.op_call import ArgumentError, convert_argument
    from blended.ops import SplayedLegSpec

    with pytest.raises(ArgumentError, match="expected an integer"):
        convert_argument(int, True, "x.count")
    with pytest.raises(ArgumentError, match="expected a number"):
        convert_argument(float, "0.5", "x.width_m")
    with pytest.raises(ArgumentError, match="exactly 3 items"):
        convert_argument(tuple[float, float, float], [0.0, 0.0], "x.location_m")
    with pytest.raises(ArgumentError, match=r"unknown field\(s\) \['radius'\]"):
        convert_argument(SplayedLegSpec, {"radius": 1.0}, "x.spec")


def test_an_op_that_raises_is_a_failed_call_with_its_type_and_traceback():
    from blended.agent.op_call import call_op
    from blended.stages import STAGE_EXECUTE

    def exploding_op(width_m: float) -> str:
        """Always raises."""
        raise ValueError("the operand is unlinked")

    result = call_op("exploding_op", exploding_op, {"width_m": 0.5})
    text = result.summary(1500)

    assert not result.ok and result.stage_reached == STAGE_EXECUTE
    assert "FAILED at execute: exploding_op" in text
    assert "ValueError: the operand is unlinked" in text
    assert "Traceback" in text


def test_a_returned_report_is_rendered_as_json():
    from blended.agent.op_call import json_returned
    from blended.ops import BoneSpec

    assert json_returned(
        BoneSpec(name="root", head_m=(0.0, 0.0, 0.0), tail_m=(0.0, 0.0, 0.5))
    ) == {
        "name": "root",
        "head_m": [0.0, 0.0, 0.0],
        "tail_m": [0.0, 0.0, 0.5],
        "parent_name": "",
        "connected": False,
    }
    with pytest.raises(TypeError, match="no JSON form"):
        json_returned(object())


def test_an_op_tool_off_the_main_thread_is_refused_like_any_tool():
    from blended.agent.tools import dispatch_tool

    failures = []

    def call_from_worker():
        try:
            dispatch_tool("middle_extent_m", {"extents_m": [1.0, 2.0, 3.0]}, None)
        except BaseException as error:  # noqa: BLE001 — the assertion IS the error
            failures.append(error)

    worker = threading.Thread(target=call_from_worker, name="not-main")
    worker.start()
    worker.join(timeout=10)

    assert len(failures) == 1 and "not the main thread" in str(failures[0])


# --- the escape hatch (OT-7) ------------------------------------------------


def test_run_python_without_a_reason_is_refused_before_bpy():
    from blended.agent.tools import RUN_PYTHON_REASON_REFUSAL, dispatch_tool

    for arguments in (
        {"source": "pass"},
        {"source": "pass", "reason": ""},
        {"source": "pass", "reason": "   "},
        {"source": "pass", "reason": 3},
    ):
        assert (
            dispatch_tool("run_python", arguments, None).text
            == RUN_PYTHON_REASON_REFUSAL
        ), arguments


def test_run_python_with_a_reason_reaches_bpy():
    """The refusal is the only pure-layer stop; a reasoned call proceeds
    to the body, whose first act is `import bpy` — absent here."""
    from blended.agent.tools import dispatch_tool

    with pytest.raises(ModuleNotFoundError, match="bpy"):
        dispatch_tool(
            "run_python", {"source": "pass", "reason": "no op does this"}, None
        )


def test_the_run_python_schema_requires_the_reason():
    from blended.agent.tools import SERVICE_TOOL_SCHEMAS

    run_python = next(
        t["function"]
        for t in SERVICE_TOOL_SCHEMAS
        if t["function"]["name"] == "run_python"
    )
    assert run_python["parameters"]["required"] == ["source", "reason"]
    assert run_python["description"].startswith("ESCAPE HATCH")


# --- search_ops (OT-15): schema-driven, pure -----------------------------------


def test_search_ops_returns_each_hit_with_its_generated_schema():
    from blended.agent.tools import (
        MAXIMUM_SEARCH_RESULTS,
        OP_TOOL_SCHEMAS,
        dispatch_tool,
    )

    outcome = dispatch_tool("search_ops", {"query": "boolean union"}, None)

    assert outcome.ok
    union = next(
        t["function"]
        for t in OP_TOOL_SCHEMAS
        if t["function"]["name"] == "boolean_union"
    )
    assert outcome.text.startswith("boolean_union: ")
    assert (
        "schema: " + json.dumps(union["parameters"], separators=(",", ":"))
        in outcome.text
    )
    # One ranked page, never more than the cap.
    broad = dispatch_tool("search_ops", {"query": "object"}, None)
    assert broad.text.count("\n    schema: ") <= MAXIMUM_SEARCH_RESULTS


def test_search_ops_spans_the_underscore_and_word_order():
    from blended.agent.tools import dispatch_tool

    for query in ("assign material", "material assign", "assign_material"):
        assert dispatch_tool("search_ops", {"query": query}, None).text.startswith(
            "assign_material: "
        ), query
    miss = dispatch_tool("search_ops", {"query": "teleport"}, None)
    assert not miss.ok and miss.text.startswith("No operation matches")
    assert not dispatch_tool("search_ops", {"query": "???"}, None).ok
