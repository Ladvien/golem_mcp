"""OT-16: the gate-failure cap — three consecutive failures on one object
stop the turn with a contact sheet; a pass resets the count. Pure: fake
dispatchers and a scripted client."""

from __future__ import annotations

import dataclasses

from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome
from blended.stages import STAGE_DONE, STAGE_GATE


def _client(replies):
    from blended.agent.loop import ModelConfig

    class Scripted:
        def __init__(self):
            self.replies = list(replies)
            self.spent = TurnCost()
            self.config = dataclasses.replace(
                ModelConfig.from_environment(), model="scripted", vision_model=""
            )

        def chat(self, messages, tools=None):
            return self.replies.pop(0)

    return Scripted()


def _call(tool_name, call_id, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": call_id, "function": {"name": tool_name, "arguments": arguments}}
        ],
    }


ANSWER = {"role": "assistant", "content": "Done."}


def _failing_gate(object_name: str) -> ToolOutcome:
    return ToolOutcome(
        f"FAILED at gate: build {object_name}",
        ok=False,
        stage_reached=STAGE_GATE,
        gates=(
            {
                "object_name": object_name,
                "stage_reached": STAGE_GATE,
                "gate_failures": ["2 components"],
            },
        ),
    )


def _passing_gate(object_name: str) -> ToolOutcome:
    return ToolOutcome(
        f"OK: build {object_name}",
        ok=True,
        stage_reached=STAGE_DONE,
        gates=(
            {
                "object_name": object_name,
                "stage_reached": STAGE_DONE,
                "gate_failures": [],
            },
        ),
    )


def test_three_consecutive_gate_failures_stop_the_turn_with_a_sheet(tmp_path):
    from blended.agent.loop import (
        GATE_CAP_TOOL_RESULT,
        MAXIMUM_GATE_FAILURES_PER_OBJECT,
        AgentSession,
    )

    assert MAXIMUM_GATE_FAILURES_PER_OBJECT == 3
    dispatched = []
    sheet = tmp_path / "Bad_sheet.png"

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append(tool_name)
        if tool_name == "render_views":
            return ToolOutcome("Rendered Bad.", images=(sheet,))
        return _failing_gate("Bad")

    replies = [_call("build", f"c{i}", name="Bad") for i in range(1, 6)] + [ANSWER]
    session = AgentSession(
        client=_client(replies), output_directory=tmp_path, dispatch=dispatch
    )
    events = []
    answer = session.send("build it", on_event=lambda k, t: events.append((k, t)))

    assert answer.startswith("Stopped: 'Bad' failed the gate 3 times in a row (cap 3)")
    assert "2 components" in answer
    assert dispatched == ["build", "build", "build", "render_views"]
    assert [t for k, t in events if k == "render"] == [str(sheet)]
    # History stays consistent: every issued call has a result, none says "not run" here
    # because each reply carried a single call that did run.
    assert all(
        m["content"] != GATE_CAP_TOOL_RESULT
        for m in session.messages
        if m.get("role") == "tool"
    )


def test_a_passing_verdict_resets_the_count(tmp_path):
    from blended.agent.loop import AgentSession

    verdicts = iter(
        [
            _failing_gate("Bad"),
            _failing_gate("Bad"),
            _passing_gate("Bad"),
            _failing_gate("Bad"),
            _failing_gate("Bad"),
        ]
    )
    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append(tool_name)
        return next(verdicts)

    replies = [_call("build", f"c{i}", name="Bad") for i in range(1, 6)] + [ANSWER]
    session = AgentSession(
        client=_client(replies), output_directory=tmp_path, dispatch=dispatch
    )
    answer = session.send("build it")

    assert answer == "Done."
    assert dispatched == ["build"] * 5


def test_queued_calls_after_the_cap_get_a_not_run_result(tmp_path):
    """A reply carrying several calls: the cap fires on the second, the
    third is answered 'not run' so the protocol stays consistent."""
    from blended.agent.loop import GATE_CAP_TOOL_RESULT, AgentSession

    def dispatch(tool_name, arguments, output_directory):
        if tool_name == "render_views":
            return ToolOutcome("Rendered Bad.")
        return _failing_gate("Bad")

    three_calls = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"m{i}", "function": {"name": "build", "arguments": {"name": "Bad"}}}
            for i in range(3)
        ],
    }
    replies = [_call("build", "c0", name="Bad"), three_calls, ANSWER]
    session = AgentSession(
        client=_client(replies),
        output_directory=tmp_path,
        dispatch=dispatch,
        maximum_gate_failures_per_object=3,
    )
    session.send("build it")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c0", "m0", "m1", "m2"]
    assert tool_messages[-1]["content"] == GATE_CAP_TOOL_RESULT


# --- withheld tools (OT-11) --------------------------------------------------


def test_a_disabled_tool_is_neither_offered_nor_dispatched(tmp_path):
    from blended.agent.loop import DISABLED_TOOL_REFUSAL, AgentSession
    from blended.agent.tool_event import TOOL_EVENT_KIND, decode_tool_event

    offered = []

    class Recording:
        def __init__(self, replies):
            self.replies = list(replies)
            self.spent = TurnCost()
            from blended.agent.loop import ModelConfig

            self.config = dataclasses.replace(
                ModelConfig.from_environment(), model="scripted", vision_model=""
            )

        def chat(self, messages, tools=None):
            offered.append([tool["function"]["name"] for tool in tools])
            return self.replies.pop(0)

    dispatched = []
    session = AgentSession(
        client=Recording(
            [_call("run_python", "h1", source="pass", reason="x"), ANSWER]
        ),
        output_directory=tmp_path,
        dispatch=lambda name, *a: dispatched.append(name) or ToolOutcome("ok"),
        disabled_tools=frozenset({"run_python"}),
    )
    events = []
    session.send("build", on_event=lambda k, t: events.append((k, t)))

    assert "run_python" not in offered[0] and "add_box" in offered[0]
    assert dispatched == []
    refusal = DISABLED_TOOL_REFUSAL.format(tool_name="run_python")
    assert [t for k, t in events if k == "result"] == [refusal]
    [event] = [decode_tool_event(t) for k, t in events if k == TOOL_EVENT_KIND]
    assert event.refusal == refusal and not event.ok
