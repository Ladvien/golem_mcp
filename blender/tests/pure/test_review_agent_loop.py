"""Regressions for the agent-loop review (2026-10-07): each test fails on
the behaviour it pins and was measured against the pre-fix `loop.py`.
Pure: scripted clients and stubbed transports, no Blender, no network."""

from __future__ import annotations

import dataclasses
import json

import pytest

from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome
from blended.stages import STAGE_GATE

LIST_SCENE_TOOL = {
    "type": "function",
    "function": {
        "name": "list_scene",
        "description": "d",
        "parameters": {"type": "object", "properties": {}},
    },
}


def _constrained_client(monkeypatch, content: str):
    from blended.agent.loop import ModelConfig, OllamaClient

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    config = ModelConfig.from_environment(model="blenderllm")
    client = OllamaClient(config)
    body = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    monkeypatch.setattr(client, "_request", lambda path, payload, timeout: body)
    return client


def test_a_bare_tool_call_object_is_not_mistaken_for_the_envelope(monkeypatch):
    """ISSUES M2: a JSON object that is not the envelope was decoded to
    content="" / tool_calls=[] and the model's text was erased."""
    raw = '{"name": "list_scene", "arguments": {}}'
    client = _constrained_client(monkeypatch, raw)
    message = client.chat([{"role": "user", "content": "go"}], [LIST_SCENE_TOOL])
    assert message["content"] == raw
    assert message["tool_calls"] == []


def test_a_real_envelope_is_still_decoded_into_tool_calls(monkeypatch):
    envelope = {
        "message": "hi",
        "tool_calls": [{"name": "list_scene", "arguments": {}}],
    }
    client = _constrained_client(monkeypatch, json.dumps(envelope))
    message = client.chat([{"role": "user", "content": "go"}], [LIST_SCENE_TOOL])
    assert message["content"] == "hi"
    assert [call["function"]["name"] for call in message["tool_calls"]] == [
        "list_scene"
    ]


def test_a_toolless_reply_on_the_constrained_lane_is_plain_text(monkeypatch):
    """No tools means no response_format was sent, so the reply is not an
    envelope even when its text happens to look like one."""
    from blended.agent.loop import ModelConfig

    client = _constrained_client(monkeypatch, '{"message": "hi", "tool_calls": []}')
    assert "response_format" not in client._chat_payload(
        [{"role": "user", "content": "x"}], None
    )
    assert ModelConfig.from_environment(model="blenderllm").constrains_tool_calls
    message = client.chat([{"role": "user", "content": "go"}], None)
    assert message["content"] == '{"message": "hi", "tool_calls": []}'


def test_the_local_llama_server_gets_the_long_ceiling(monkeypatch):
    """ISSUES M3: the lane fell back to the 300 s cloud ceiling."""
    from blended.agent import loop

    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    for model in loop.LOCAL_LLAMA_SERVER_MODEL_IDS:
        config = loop.ModelConfig.from_environment(model=model)
        assert config.request_timeout_seconds == loop.LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS
    cloud = loop.ModelConfig.from_environment(model="deepseek-v4-pro:cloud")
    assert cloud.request_timeout_seconds == loop.REQUEST_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "spelling", ["http://127.0.0.1:8091/", "http://127.0.0.1:8091/v1"]
)
def test_constrained_lane_matches_by_containment_like_the_protocol_check(spelling):
    """ISSUES Mi1: a trailing slash took the OpenAI wire but sent wire
    `tools` to a model that cannot emit them."""
    from blended.agent.loop import ModelConfig

    config = ModelConfig(model="blenderllm", endpoint=spelling)
    assert config.uses_openai_protocol
    assert config.constrains_tool_calls


def _scripted(replies):
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


def _call_reply(tool_name: str, arguments, call_id: str = "c0") -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": call_id, "function": {"name": tool_name, "arguments": arguments}}
        ],
    }


ANSWER = {"role": "assistant", "content": "Done."}


@pytest.mark.parametrize("raw_arguments", ['{"source": "x = ', "[1, 2]", "null", None])
def test_malformed_arguments_are_refused_not_raised(tmp_path, raw_arguments):
    """The OpenAI wire hands arguments over as the model's own JSON string.
    A truncated one raised JSONDecodeError out of send() and stranded the
    assistant message's call with no result."""
    from blended.agent.loop import AgentSession

    dispatched = []
    session = AgentSession(
        client=_scripted([_call_reply("run_python", raw_arguments), ANSWER]),
        output_directory=tmp_path,
        dispatch=lambda *a: dispatched.append(a) or ToolOutcome("ran"),
    )
    events = []
    answer = session.send("go", on_event=lambda kind, text: events.append((kind, text)))

    assert answer == "Done."
    assert dispatched == []
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["c0"]
    assert "was not run" in tool_messages[0]["content"]
    refused = [json.loads(text) for kind, text in events if kind == "tool_event"]
    assert len(refused) == 1 and refused[0]["ok"] is False and refused[0]["refusal"]


def test_arguments_sent_as_a_json_string_still_dispatch(tmp_path):
    from blended.agent.loop import AgentSession

    seen = []

    def dispatch(tool_name, arguments, output_directory):
        seen.append(arguments)
        return ToolOutcome("ran")

    session = AgentSession(
        client=_scripted([_call_reply("run_python", '{"source": "pass"}'), ANSWER]),
        output_directory=tmp_path,
        dispatch=dispatch,
    )
    assert session.send("go") == "Done."
    assert seen == [{"source": "pass"}]


def test_a_malformed_plan_step_is_reported_after_the_tool_ran(tmp_path):
    """plan_step_of raised ValueError out of send() AFTER the tool ran and
    before its result was appended."""
    from blended.agent.loop import AgentSession

    session = AgentSession(
        client=_scripted(
            [
                _call_reply("inspect_object", {"object_name": "X", "plan_step": "abc"}),
                ANSWER,
            ]
        ),
        output_directory=tmp_path,
        dispatch=lambda *a: ToolOutcome("inspected"),
    )
    assert session.send("go") == "Done."
    tool_message = next(m for m in session.messages if m.get("role") == "tool")
    assert tool_message["content"].startswith("inspected")
    assert "plan_step ignored" in tool_message["content"]


def test_the_gate_cap_answers_queued_calls_before_it_renders(tmp_path):
    """A render_views dispatch that raises at the cap must not leave the
    assistant's queued calls without results."""
    from blended.agent.loop import GATE_CAP_TOOL_RESULT, AgentSession

    failing = ToolOutcome(
        "FAILED",
        ok=False,
        stage_reached=STAGE_GATE,
        gates=(
            {"object_name": "Bad", "stage_reached": STAGE_GATE, "gate_failures": ["x"]},
        ),
    )

    def dispatch(tool_name, arguments, output_directory):
        if tool_name == "render_views":
            raise RuntimeError("render died")
        return failing

    queued = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"m{i}", "function": {"name": "build", "arguments": {"name": "Bad"}}}
            for i in range(3)
        ],
    }
    session = AgentSession(
        client=_scripted([queued, ANSWER]),
        output_directory=tmp_path,
        dispatch=dispatch,
        maximum_gate_failures_per_object=2,
    )
    with pytest.raises(RuntimeError, match="render died"):
        session.send("go")
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_messages] == ["m0", "m1", "m2"]
    assert tool_messages[-1]["content"] == GATE_CAP_TOOL_RESULT


def test_an_eye_call_that_fails_after_billing_still_counts_against_the_run(
    monkeypatch, tmp_path
):
    """The eye's spend was folded into the run's record only on success, so
    a reply cut after it was billed escaped the NFR-27 cap."""
    from blended.agent.context_preflight import ReplyTruncated
    from blended.agent.loop import ModelConfig, OllamaClient, VisionDescriber

    truncated_body = {
        "choices": [{"message": {"content": "cut"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 7},
    }
    monkeypatch.setattr(
        OllamaClient, "_request", lambda self, path, payload, timeout: truncated_body
    )
    writer = OllamaClient(
        ModelConfig(
            model="qwen3.8-27b",
            endpoint="http://192.168.1.233:9292",
            api_key="k",
            vision_model="qwen3-vl",
        )
    )
    image = tmp_path / "render.png"
    image.write_bytes(b"\x89PNG")
    with pytest.raises(ReplyTruncated):
        VisionDescriber(writer, "qwen3-vl").describe([image])
    assert writer.spent.api_calls == 1
    assert writer.spent.output_tokens == 7
