"""OT-8: the structured tool record round-trips, and the loop emits one
per call — dispatched or refused. Pure: fake dispatchers."""

from __future__ import annotations

import dataclasses

import pytest

from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome
from blended.agent.tool_event import (
    TOOL_EVENT_KIND,
    TOOL_EVENT_SCHEMA_VERSION,
    ToolEvent,
    decode_tool_event,
    encode_tool_event,
)
from blended.stages import STAGE_DONE


def test_a_tool_event_round_trips_through_json():
    event = ToolEvent(
        tool_name="add_box",
        arguments={
            "name": "Crate",
            "width_m": 0.5,
            "depth_m": 0.5,
            "height_m": 0.5,
            "location_m": [0.0, 0.0, 0.0],
        },
        ok=True,
        stage_reached=STAGE_DONE,
        wall_time_s=0.0123,
        plan_step=2,
        gates=(
            {
                "object_name": "Crate",
                "stage_reached": "done",
                "report": {"triangle_count": 12},
            },
        ),
        images=("/tmp/sheet.png",),
    )
    assert decode_tool_event(encode_tool_event(event)) == event
    assert event.schema_version == TOOL_EVENT_SCHEMA_VERSION == 2


def test_a_v1_payload_is_refused_not_misread():
    with pytest.raises(ValueError, match="schema None, expected 2"):
        decode_tool_event('{"tool_name": "run_python", "arguments": {}}')


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


def _call(tool_name, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": tool_name, "arguments": arguments}}],
    }


ANSWER = {"role": "assistant", "content": "Done."}


def test_the_loop_emits_one_structured_event_per_dispatched_call(tmp_path):
    from blended.agent.loop import AgentSession

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome(
            "OK: add_box",
            ok=True,
            stage_reached=STAGE_DONE,
            validated_arguments={
                "name": "Crate",
                "width_m": 0.5,
                "depth_m": 0.5,
                "height_m": 0.5,
            },
            gates=({"object_name": "Crate", "stage_reached": "done"},),
            hatch_reason="",
        )

    session = AgentSession(
        client=_client(
            [
                _call(
                    "add_box",
                    name="Crate",
                    width_m=0.5,
                    depth_m=0.5,
                    height_m=0.5,
                    plan_step=1,
                ),
                ANSWER,
            ]
        ),
        output_directory=tmp_path,
        dispatch=dispatch,
    )
    events = []
    session.send("build", on_event=lambda kind, text: events.append((kind, text)))

    structured = [
        decode_tool_event(text) for kind, text in events if kind == TOOL_EVENT_KIND
    ]
    assert len(structured) == 1
    event = structured[0]
    assert (
        event.tool_name == "add_box" and event.ok and event.stage_reached == STAGE_DONE
    )
    assert event.arguments == {
        "name": "Crate",
        "width_m": 0.5,
        "depth_m": 0.5,
        "height_m": 0.5,
    }  # validated, plan_step stripped
    assert event.plan_step == 1
    assert event.gates == ({"object_name": "Crate", "stage_reached": "done"},)
    assert event.wall_time_s >= 0.0 and event.refusal == ""
    # Ordered after the text the model reads.
    kinds = [kind for kind, _ in events]
    assert kinds.index("result") < kinds.index(TOOL_EVENT_KIND)


def test_a_refused_call_is_recorded_as_refused(tmp_path):
    from blended.agent.loop import AgentSession
    from blended.agent.plan import MISSING_PLAN_REFUSAL

    session = AgentSession(
        client=_client(
            [
                _call("add_box", name="Crate", width_m=0.5, depth_m=0.5, height_m=0.5),
                ANSWER,
            ]
        ),
        output_directory=tmp_path,
        dispatch=lambda *a: ToolOutcome("never"),
        require_plan=True,
    )
    events = []
    session.send("build", on_event=lambda kind, text: events.append((kind, text)))

    [event] = [
        decode_tool_event(text) for kind, text in events if kind == TOOL_EVENT_KIND
    ]
    assert (
        not event.ok
        and event.refusal == MISSING_PLAN_REFUSAL
        and event.stage_reached == ""
    )


def test_the_hatch_record_carries_reason_and_hash(tmp_path):
    from blended.agent.loop import AgentSession

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome(
            "Executed OK",
            ok=True,
            stage_reached=STAGE_DONE,
            validated_arguments=arguments,
            hatch_reason="no op insets a face",
            source_sha256="abc123abc123",
        )

    session = AgentSession(
        client=_client(
            [_call("run_python", source="pass", reason="no op insets a face"), ANSWER]
        ),
        output_directory=tmp_path,
        dispatch=dispatch,
    )
    events = []
    session.send("build", on_event=lambda kind, text: events.append((kind, text)))
    [event] = [
        decode_tool_event(text) for kind, text in events if kind == TOOL_EVENT_KIND
    ]
    assert (
        event.hatch_reason == "no op insets a face"
        and event.source_sha256 == "abc123abc123"
    )
