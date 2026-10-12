"""The turn-plan protocol: a plan declared before scene changes, shown
to the user with a progress bar, refuse-without-plan enforcement, and
the three new event kinds (plan, step, render) on the existing
``(kind, text)`` channel.

Decision D1 of the chat-UX overhaul. The plan is a shared representation
between user and agent, not an approval gate (DOI
10.48550/arXiv.2507.22358 — shared editable plan + progress bar; DOI
10.48550/arxiv.2604.14228 — ≈93 % of permission prompts are approved).

The test uses a scripted client (no network) and binds ONE live module
object — ``from blended.agent import loop as live_loop`` — for both the
monkeypatch target and construction.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from blended.agent import loop as live_loop
from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome
from blended.agent.plan import (
    MAXIMUM_PLAN_STEPS,
    MISSING_PLAN_REFUSAL,
    TurnPlan,
    decode_plan_event,
    encode_plan_event,
    parse_plan_arguments,
    plan_required_for,
    plan_step_of,
)

# ---------------------------------------------------------------------------
# Scripted client — copies the established pattern from test_turn_token_budget.
# ---------------------------------------------------------------------------


class ScriptedClient:
    def __init__(self, replies, vision_model=""):
        self.replies = list(replies)
        self.spent = TurnCost()
        self.config = dataclasses.replace(
            live_loop.ModelConfig.from_environment(),
            model="scripted",
            vision_model=vision_model,
        )

    def chat(self, messages, tools=None):
        return self.replies.pop(0)


def _tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def _assistant(*tool_calls, content="", thinking=None):
    message = {"role": "assistant", "content": content, "tool_calls": list(tool_calls)}
    if thinking is not None:
        message["thinking"] = thinking
    return message


PLAN_REPLY = _assistant(
    _tool_call(
        "c1", "declare_plan", {"steps": ["Build the base", "Add the lid", "Export"]}
    ),
)
RUN_PYTHON_REPLY = _assistant(
    _tool_call("c2", "run_python", {"source": "a = 1", "plan_step": 1}),
)
ANSWER_REPLY = {"role": "assistant", "content": "done"}


# ---------------------------------------------------------------------------
# parse_plan_arguments — validation
# ---------------------------------------------------------------------------


def test_parse_plan_arguments_strips_step_strings():
    plan = parse_plan_arguments({"steps": ["  build  ", " export  "]})
    assert plan.steps == ("build", "export")


def test_parse_plan_arguments_rejects_empty_list():
    with pytest.raises(ValueError, match="empty"):
        parse_plan_arguments({"steps": []})


def test_parse_plan_arguments_rejects_too_many_steps():
    with pytest.raises(ValueError, match=str(MAXIMUM_PLAN_STEPS)):
        parse_plan_arguments(
            {"steps": [f"step {i}" for i in range(MAXIMUM_PLAN_STEPS + 1)]}
        )


def test_parse_plan_arguments_rejects_blank_step():
    with pytest.raises(ValueError, match="empty or whitespace"):
        parse_plan_arguments({"steps": ["build", "   ", "export"]})


def test_parse_plan_arguments_rejects_non_list():
    with pytest.raises(ValueError, match="array"):
        parse_plan_arguments({"steps": "build, export"})


def test_parse_plan_arguments_rejects_missing_steps():
    with pytest.raises(ValueError, match="steps"):
        parse_plan_arguments({})


def test_parse_plan_arguments_rejects_non_string_step():
    with pytest.raises(ValueError, match="not a string"):
        parse_plan_arguments({"steps": ["build", 42]})


# ---------------------------------------------------------------------------
# plan_step_of
# ---------------------------------------------------------------------------


def test_plan_step_of_returns_none_when_absent():
    assert plan_step_of({"source": "pass"}) is None


def test_plan_step_of_accepts_integer_string():
    assert plan_step_of({"plan_step": "3"}) == 3


def test_plan_step_of_accepts_integer():
    assert plan_step_of({"plan_step": 2}) == 2


def test_plan_step_of_rejects_zero():
    with pytest.raises(ValueError, match="positive"):
        plan_step_of({"plan_step": 0})


def test_plan_step_of_rejects_non_integer_string():
    with pytest.raises(ValueError, match="positive integer"):
        plan_step_of({"plan_step": "abc"})


def test_plan_step_of_rejects_bool():
    with pytest.raises(ValueError, match="bool"):
        plan_step_of({"plan_step": True})


# ---------------------------------------------------------------------------
# TurnPlan behaviour
# ---------------------------------------------------------------------------


def test_progress_fraction_starts_at_zero():
    plan = TurnPlan(steps=("a", "b", "c"))
    assert plan.progress_fraction() == 0.0


def test_progress_fraction_advances():
    plan = TurnPlan(steps=("a", "b", "c"), current_step=2)
    assert plan.status_text() == "step 2/3"
    assert pytest.approx(plan.progress_fraction()) == 2 / 3


def test_with_step_clamps_high():
    plan = TurnPlan(steps=("a", "b", "c"))
    clamped = plan.with_step(99)
    assert clamped.current_step == 3
    assert clamped.progress_fraction() <= 1.0


def test_with_step_clamps_negative():
    plan = TurnPlan(steps=("a", "b", "c"))
    clamped = plan.with_step(-5)
    assert clamped.current_step == 0
    assert clamped.progress_fraction() == 0.0


def test_with_step_progress_is_monotonic():
    plan = TurnPlan(steps=("a", "b", "c"))
    fractions = [plan.with_step(i).progress_fraction() for i in range(4)]
    assert fractions == sorted(fractions)


# ---------------------------------------------------------------------------
# encode / decode round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_round_trips():
    plan = TurnPlan(steps=("build", "export"), current_step=1)
    decoded = decode_plan_event(encode_plan_event(plan))
    assert decoded.steps == plan.steps
    assert decoded.current_step == plan.current_step


def test_decode_rejects_malformed_json():
    with pytest.raises(ValueError, match="JSON"):
        decode_plan_event("not json{")


def test_decode_rejects_missing_steps_key():
    with pytest.raises(ValueError, match="steps"):
        decode_plan_event(json.dumps({"current_step": 1}))


# ---------------------------------------------------------------------------
# plan_required_for
# ---------------------------------------------------------------------------


def test_plan_required_for_run_python():
    assert plan_required_for("run_python") is True


def test_plan_required_for_list_scene():
    assert plan_required_for("list_scene") is False


def test_plan_required_for_search_ops():
    assert plan_required_for("search_ops") is False


# ---------------------------------------------------------------------------
# Loop integration: require_plan enforcement
# ---------------------------------------------------------------------------


def test_require_plan_refuses_run_python_without_plan(tmp_path):
    """With require_plan=True, run_python before a plan is NOT executed:
    the dispatch spy records nothing, the model gets
    MISSING_PLAN_REFUSAL as the tool result, and a follow-up that
    declares a plan then executes."""
    replies = [
        _assistant(_tool_call("c1", "run_python", {"source": "a = 1"})),
        PLAN_REPLY,
        RUN_PYTHON_REPLY,
        ANSWER_REPLY,
    ]
    session = live_loop.AgentSession(
        client=ScriptedClient(replies),
        require_plan=True,
    )
    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append((tool_name, arguments))
        return ToolOutcome("ok")

    session.dispatch = dispatch
    events = []
    answer = session.send("build it", on_event=lambda k, t: events.append((k, t)))
    assert answer == "done"  # the conversation ran to the scripted final answer
    # The first run_python was refused — dispatch was never called for it.
    # declare_plan IS dispatched (it goes through the same channel), so
    # filter to the action tool.
    run_python_calls = [c for c in dispatched if c[0] == "run_python"]
    assert len(run_python_calls) == 1
    # The refusal was emitted as a result event and recorded in history.
    result_events = [
        t for k, t in events if k == "result" and t == MISSING_PLAN_REFUSAL
    ]
    assert len(result_events) == 1
    # The plan was declared and a plan event was emitted.
    plan_events = [t for k, t in events if k == "plan"]
    assert len(plan_events) == 1
    decoded = decode_plan_event(plan_events[0])
    assert decoded.steps == ("Build the base", "Add the lid", "Export")


def test_require_plan_false_executes_immediately(tmp_path):
    """With require_plan=False, the same conversation runs run_python
    immediately — the batch contract is untouched."""
    replies = [
        RUN_PYTHON_REPLY,
        ANSWER_REPLY,
    ]
    session = live_loop.AgentSession(
        client=ScriptedClient(replies),
        require_plan=False,
    )
    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append((tool_name, arguments))
        return ToolOutcome("ok")

    session.dispatch = dispatch
    answer = session.send("build it")

    assert answer == "done"
    assert len(dispatched) == 1
    assert dispatched[0][0] == "run_python"
    # No plan event was emitted.
    # (No on_event callback, so nothing to check — but dispatch proves
    # the tool ran.)


def test_plan_step_emits_step_event_and_advances_progress(tmp_path):
    """A declared plan emits one plan event; a later call with plan_step
    emits a step event and moves progress_fraction monotonically."""
    step2_reply = _assistant(
        _tool_call("c3", "run_python", {"source": "b = 2", "plan_step": 2}),
    )
    replies = [PLAN_REPLY, step2_reply, ANSWER_REPLY]
    session = live_loop.AgentSession(
        client=ScriptedClient(replies),
        require_plan=True,
    )

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome("ok")

    session.dispatch = dispatch
    events = []
    session.send("build it", on_event=lambda k, t: events.append((k, t)))

    plan_events = [t for k, t in events if k == "plan"]
    assert len(plan_events) == 1
    decoded = decode_plan_event(plan_events[0])
    assert decoded.current_step == 0  # declared, not started

    step_events = [t for k, t in events if k == "step"]
    assert len(step_events) == 1
    assert step_events[0] == "2"


def test_render_event_emitted_before_vision(tmp_path, monkeypatch):
    """A tool returning image paths emits a render event carrying the
    path, ordered before the vision event. Requires a separate-eye
    config so the vision event fires at all."""
    render_path = tmp_path / "sheet.png"
    render_path.write_bytes(b"\x89PNG fake")
    render_reply = _assistant(
        _tool_call("c4", "render_views", {"object_name": "Cube"}),
    )
    replies = [render_reply, ANSWER_REPLY]
    client = ScriptedClient(replies, vision_model="qwen3-vl")
    session = live_loop.AgentSession(client=client)

    # Fake the vision describer so no network call is made.
    class FakeDescriber:
        def __init__(self, *args, **kwargs):
            pass

        def describe(self, image_paths, look_for=""):
            return "a cube from several angles"

    monkeypatch.setattr(live_loop, "VisionDescriber", FakeDescriber)

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome("rendered", (render_path,))

    session.dispatch = dispatch
    events = []
    session.send("render it", on_event=lambda k, t: events.append((k, t)))

    kinds = [k for k, _ in events]
    assert "render" in kinds
    assert "vision" in kinds
    render_idx = kinds.index("render")
    vision_idx = kinds.index("vision")
    assert render_idx < vision_idx
    render_events = [t for k, t in events if k == "render"]
    assert render_events == [str(render_path)]


def test_render_event_emitted_in_images_to_writer_config(tmp_path):
    """In the images-to-writer config (no separate eye), the render
    event is still emitted — the panel shows the render either way."""
    render_path = tmp_path / "sheet.png"
    render_path.write_bytes(b"\x89PNG fake")
    render_reply = _assistant(
        _tool_call("c5", "render_views", {"object_name": "Cube"}),
    )
    replies = [render_reply, ANSWER_REPLY]
    # vision_model="" → uses_separate_eye is False
    session = live_loop.AgentSession(client=ScriptedClient(replies))

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome("rendered", (render_path,))

    session.dispatch = dispatch
    events = []
    session.send("render it", on_event=lambda k, t: events.append((k, t)))

    render_events = [t for k, t in events if k == "render"]
    assert render_events == [str(render_path)]
    # No vision event in this config.
    assert "vision" not in [k for k, _ in events]


# ---------------------------------------------------------------------------
# Tool-level refusal text names the problem
# ---------------------------------------------------------------------------


def test_dispatch_tool_declare_plan_returns_failure_for_empty_list():
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool("declare_plan", {"steps": []})
    result = outcome.text
    assert outcome.images == ()
    assert "FAILED" in result
    assert "empty" in result


def test_dispatch_tool_declare_plan_returns_failure_for_too_many():
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool(
        "declare_plan", {"steps": [f"s{i}" for i in range(MAXIMUM_PLAN_STEPS + 1)]}
    )
    result = outcome.text
    assert outcome.images == ()
    assert "FAILED" in result
    assert str(MAXIMUM_PLAN_STEPS) in result


def test_dispatch_tool_declare_plan_returns_failure_for_blank_step():
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool("declare_plan", {"steps": ["build", "   "]})
    result = outcome.text
    assert outcome.images == ()
    assert "FAILED" in result
    assert "empty or whitespace" in result


def test_dispatch_tool_declare_plan_echoes_steps():
    from blended.agent.tools import dispatch_tool

    outcome = dispatch_tool("declare_plan", {"steps": ["build", "export"]})
    result = outcome.text
    assert outcome.images == ()
    assert "1. build" in result
    assert "2. export" in result


# --- op tools (OT-6): plan-required like run_python, plan_step honoured ---


def test_plan_required_tools_are_run_python_and_every_scene_changing_op():
    from blended.agent.plan import PLAN_REQUIRED_TOOLS
    from blended.ops._contract import changes_scene, facade_ops

    assert PLAN_REQUIRED_TOOLS[0] == "run_python"
    assert set(PLAN_REQUIRED_TOOLS[1:]) == {
        name for name, f in facade_ops() if changes_scene(f)
    }
    assert "add_box" in PLAN_REQUIRED_TOOLS and "rig_report" not in PLAN_REQUIRED_TOOLS


def test_an_op_tool_without_a_plan_is_refused_with_the_same_text(tmp_path):
    add_box = _tool_call(
        "o1",
        "add_box",
        {"name": "Crate", "width_m": 0.5, "depth_m": 0.5, "height_m": 0.5},
    )
    replies = [_assistant(add_box), PLAN_REPLY, _assistant(add_box), ANSWER_REPLY]
    session = live_loop.AgentSession(client=ScriptedClient(replies), require_plan=True)
    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append(tool_name)
        return ToolOutcome("ok")

    session.dispatch = dispatch
    events = []
    session.send("build it", on_event=lambda k, t: events.append((k, t)))

    assert dispatched == [
        "declare_plan",
        "add_box",
    ]  # the first add_box never reached dispatch
    assert [t for k, t in events if k == "result" and t == MISSING_PLAN_REFUSAL] == [
        MISSING_PLAN_REFUSAL
    ]


def test_a_reader_op_needs_no_plan(tmp_path):
    replies = [
        _assistant(_tool_call("r1", "rig_report", {"armature_name": "Rig"})),
        ANSWER_REPLY,
    ]
    session = live_loop.AgentSession(client=ScriptedClient(replies), require_plan=True)
    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append(tool_name)
        return ToolOutcome("ok")

    session.dispatch = dispatch
    session.send("check the rig")

    assert dispatched == ["rig_report"]


def test_an_op_tool_call_with_plan_step_reports_progress(tmp_path):
    step_reply = _assistant(
        _tool_call("o2", "link_into_scene", {"object_name": "Crate", "plan_step": 3}),
    )
    session = live_loop.AgentSession(
        client=ScriptedClient([PLAN_REPLY, step_reply, ANSWER_REPLY]), require_plan=True
    )
    seen_arguments = []

    def dispatch(tool_name, arguments, output_directory):
        seen_arguments.append(arguments)
        return ToolOutcome("ok")

    session.dispatch = dispatch
    events = []
    session.send("build it", on_event=lambda k, t: events.append((k, t)))

    assert [t for k, t in events if k == "step"] == ["3"]
    # The loop hands the call through untouched; dispatch_tool strips plan_step before binding.
    assert seen_arguments[-1] == {"object_name": "Crate", "plan_step": 3}


def test_dispatch_strips_plan_step_before_binding():
    """plan_step is the harness's argument: the op never sees it, and a
    reader called with it is not refused as 'unknown parameter'."""
    from blended.agent.tools import dispatch_tool

    text = dispatch_tool(
        "middle_extent_m", {"extents_m": [0.3, 0.2, 0.25], "plan_step": 2}, None
    ).text
    assert text.startswith("OK: middle_extent_m"), text
