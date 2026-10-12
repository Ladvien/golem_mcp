"""The Claude Code lane: transcript folding, the constrained tool-call
envelope, routing, and a full transport round trip against a FAKE
`claude` binary.

The round-trip tests exec a real subprocess, but it is a stub script
that replays canned stream-json — so the whole lane (argv, stdin frame,
frame parsing, error paths, cancel) is covered without a network call,
a token, or the real CLI installed. `scripts/provider_smoke.py` is what
exercises the live binary.
"""

import json
import stat
from pathlib import Path

import pytest

from blended.agent.claude_code import (
    ASSISTANT_LABEL,
    CLAUDE_CODE_DEFAULT_EFFORT,
    CLAUDE_CODE_ENDPOINT,
    CLAUDE_CODE_INSTALL_HINT,
    CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS,
    CONTINUATION_CUE,
    IMAGE_PLACEHOLDER_TOKEN,
    TOOL_CALL_ID_PREFIX,
    TOOL_PROTOCOL_NOTE,
    USER_LABEL,
    ClaudeCodeTransport,
    assistant_message_from_envelope,
    envelope_schema,
    is_claude_code_model,
    model_alias,
    parse_rate_limit,
    render_call,
    resolve_binary,
)
from blended.agent.loop import (
    API_KEY_ENVIRONMENT_VARIABLE,
    BIG_ENDPOINT,
    LOCAL_ENDPOINT,
    ModelConfig,
    OllamaClient,
    _image_placeholders,
    _implied_api_key,
    _implied_endpoint,
)
from blended.agent.tools import TOOL_SCHEMAS

WRITER_MODEL = "claude-code:sonnet"
EYE_MODEL = "claude-code:haiku"
CLOUD_EYE_MODEL = "kimi-k2.7-code:cloud"
FIRST_IMAGE = "Zmlyc3Q="
SECOND_IMAGE = "c2Vjb25k"


# --- transcript folding -------------------------------------------------


def test_the_whole_conversation_folds_into_one_user_frame():
    """One user frame is one billed turn (measured), so N messages must
    still produce exactly one."""
    system_prompt, frame = render_call(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "make a crate"},
            {"role": "assistant", "content": "on it"},
            {"role": "tool", "content": "GATE PASS", "tool_name": "run_python"},
        ]
    )
    assert system_prompt == "system rules"
    assert frame["type"] == "user"
    assert frame["message"]["role"] == "user"
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == ["text"]


def test_the_fold_keeps_roles_and_order_legible():
    _, frame = render_call(
        [
            {"role": "user", "content": "make a crate"},
            {
                "role": "assistant",
                "content": "building",
                "tool_calls": [
                    {
                        "id": "x",
                        "function": {
                            "name": "run_python",
                            "arguments": {"source": "print(1)"},
                        },
                    }
                ],
            },
            {"role": "tool", "content": "GATE PASS", "tool_name": "run_python"},
            {"role": "user", "content": "now add a lid"},
        ]
    )
    text = frame["message"]["content"][0]["text"]
    positions = [
        text.index(USER_LABEL),
        text.index(ASSISTANT_LABEL),
        text.index("[assistant tool call: run_python]"),
        text.index("[tool result: run_python]"),
        text.index("now add a lid"),
        text.index(CONTINUATION_CUE),
    ]
    assert positions == sorted(positions)
    # The arguments have to be readable as data, not prose.
    assert json.dumps({"source": "print(1)"}) in text


def test_a_string_arguments_payload_survives_the_fold():
    """An OpenAI-lane history can carry arguments as a JSON string."""
    _, frame = render_call(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "x",
                        "function": {
                            "name": "run_python",
                            "arguments": '{"source": "print(2)"}',
                        },
                    }
                ],
            }
        ]
    )
    assert "print(2)" in frame["message"]["content"][0]["text"]


def test_images_land_at_their_placeholder_positions():
    """`Image 1` must point at image 1: the eye's prompt numbers them."""
    _, frame = render_call(
        [
            {
                "role": "user",
                "content": _image_placeholders(2) + "compare these",
                "images": [FIRST_IMAGE, SECOND_IMAGE],
            }
        ]
    )
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == [
        "text",
        "image",
        "text",
        "image",
        "text",
    ]
    assert "Image 1" in blocks[0]["text"]
    assert blocks[1]["source"]["data"] == FIRST_IMAGE
    assert "Image 2" in blocks[2]["text"]
    assert blocks[3]["source"]["data"] == SECOND_IMAGE
    assert "compare these" in blocks[4]["text"]
    # The placeholder token itself must not survive: the real image did.
    assert IMAGE_PLACEHOLDER_TOKEN not in "".join(
        block.get("text", "") for block in blocks
    )


def test_tool_result_images_without_placeholders_still_arrive():
    """A message carrying images but no `[img]` must not lose them.

    `AgentSession` places a placeholder per image on every path now
    (`loop.deliver_images`), so this is the fallback: any caller that
    attaches images to bare text gets them appended after the text
    rather than dropped."""
    _, frame = render_call(
        [
            {
                "role": "tool",
                "content": "rendered 1 view",
                "tool_name": "render_views",
                "images": [FIRST_IMAGE],
            }
        ]
    )
    blocks = frame["message"]["content"]
    assert [block["type"] for block in blocks] == ["text", "image", "text"]
    assert blocks[1]["source"]["data"] == FIRST_IMAGE


def test_no_empty_text_blocks_are_emitted():
    """The API rejects an empty text block, and an empty assistant turn
    with only tool calls is normal."""
    _, frame = render_call([{"role": "user", "content": "", "images": [FIRST_IMAGE]}])
    for block in frame["message"]["content"]:
        if block["type"] == "text":
            assert block["text"].strip()


def test_several_system_messages_join_into_one_prompt():
    system_prompt, _ = render_call(
        [
            {"role": "system", "content": "first"},
            {"role": "system", "content": "second"},
            {"role": "user", "content": "go"},
        ]
    )
    assert system_prompt == "first\n\nsecond"


# --- the constrained envelope -------------------------------------------


def test_the_envelope_pins_each_tool_to_its_own_arguments():
    schema = envelope_schema(TOOL_SCHEMAS)
    variants = schema["properties"]["tool_calls"]["items"]["oneOf"]
    assert len(variants) == len(TOOL_SCHEMAS)
    by_name = {variant["properties"]["name"]["const"]: variant for variant in variants}
    for tool in TOOL_SCHEMAS:
        function_block = tool["function"]
        variant = by_name[function_block["name"]]
        assert variant["properties"]["arguments"] == function_block["parameters"]
        # Without the description the model names tools it knows nothing
        # about and calls none of them (measured 2026-09-05).
        assert variant["description"] == function_block["description"]
    assert schema["required"] == ["message", "tool_calls"]


def test_the_envelope_becomes_the_assistant_dict_the_loop_consumes():
    message = assistant_message_from_envelope(
        {
            "message": "building it",
            "tool_calls": [
                {"name": "run_python", "arguments": {"source": "print(1)"}},
                {"name": "inspect_object", "arguments": {"object_name": "Crate"}},
            ],
        },
        thinking="considered",
    )
    assert message["role"] == "assistant"
    assert message["content"] == "building it"
    assert message["thinking"] == "considered"
    names = [call["function"]["name"] for call in message["tool_calls"]]
    assert names == ["run_python", "inspect_object"]
    assert message["tool_calls"][0]["function"]["arguments"] == {"source": "print(1)"}
    identifiers = [call["id"] for call in message["tool_calls"]]
    assert all(identifier.startswith(TOOL_CALL_ID_PREFIX) for identifier in identifiers)
    # Ids must be unique ACROSS turns too: `_cancel_turn` matches
    # results to calls by id, and a per-turn counter would collide.
    second = assistant_message_from_envelope(
        {"message": "", "tool_calls": [{"name": "list_scene", "arguments": {}}]}
    )
    assert second["tool_calls"][0]["id"] not in identifiers


def test_an_answering_turn_carries_no_tool_calls():
    message = assistant_message_from_envelope({"message": "done", "tool_calls": []})
    assert message["tool_calls"] == []
    assert "thinking" not in message


# --- routing ------------------------------------------------------------


def test_a_claude_code_id_implies_the_cli_and_no_credential():
    assert is_claude_code_model(WRITER_MODEL)
    assert not is_claude_code_model("kimi-k2.7-code:cloud")
    assert model_alias(WRITER_MODEL) == "sonnet"
    assert _implied_endpoint(WRITER_MODEL) == CLAUDE_CODE_ENDPOINT
    assert _implied_api_key(WRITER_MODEL, "an-ollama-key") == ""


def test_the_lane_is_neither_ollama_nor_openai_and_gets_its_own_ceiling():
    config = ModelConfig.from_environment(model=WRITER_MODEL, vision_model="")
    assert config.uses_claude_code
    assert not config.uses_openai_protocol
    assert not config.is_openrouter
    assert config.api_key == ""
    assert config.request_timeout_seconds == CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS
    assert config.claude_code_effort == CLAUDE_CODE_DEFAULT_EFFORT


def test_a_cloud_eye_beside_a_cli_writer_falls_back_to_the_daemon(monkeypatch):
    """The CLI serves only its own ids, so a cloud eye must not inherit
    it — and must still get the Ollama credential."""
    monkeypatch.setenv(API_KEY_ENVIRONMENT_VARIABLE, "ollama-key")
    eye = ModelConfig.from_environment(
        model=WRITER_MODEL, vision_model=CLOUD_EYE_MODEL
    ).eye_config()
    assert eye.endpoint == LOCAL_ENDPOINT
    assert eye.api_key == "ollama-key"
    assert not eye.uses_claude_code


def test_a_cli_eye_beside_a_llama_swap_writer_rides_the_cli(monkeypatch):
    monkeypatch.setenv(API_KEY_ENVIRONMENT_VARIABLE, "ollama-key")
    eye = ModelConfig.from_environment(
        model="qwen3-vl", endpoint=BIG_ENDPOINT, vision_model=EYE_MODEL
    ).eye_config()
    assert eye.endpoint == CLAUDE_CODE_ENDPOINT
    assert eye.uses_claude_code
    # The CLI owns its auth; no harness credential may ride to it.
    assert eye.api_key == ""


# --- argv ---------------------------------------------------------------


def test_the_command_disables_every_built_in_capability(fake_binary):
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_binary))
    arguments = transport.command("system rules", TOOL_SCHEMAS)
    assert arguments[0] == str(fake_binary)
    for flag in (
        "--print",
        "--tools",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--safe-mode",
        "--no-session-persistence",
        "--include-partial-messages",
    ):
        assert flag in arguments
    assert arguments[arguments.index("--tools") + 1] == ""
    assert arguments[arguments.index("--model") + 1] == "sonnet"
    assert arguments[arguments.index("--effort") + 1] == CLAUDE_CODE_DEFAULT_EFFORT
    schema = json.loads(arguments[arguments.index("--json-schema") + 1])
    assert schema == envelope_schema(TOOL_SCHEMAS)
    # The schema is useless on its own: Claude Code is itself an agent
    # harness, so a model reading "you have these tools" emits a NATIVE
    # tool call, which `--tools ""` refuses. The note that redirects it
    # to the envelope must ship with the schema, never apart from it.
    system_prompt = arguments[arguments.index("--system-prompt") + 1]
    assert system_prompt.startswith("system rules")
    assert TOOL_PROTOCOL_NOTE in system_prompt
    # Stateless: Claude Code's own session store would be a second
    # source of truth beside AgentSession.messages.
    assert "--resume" not in arguments
    assert "--session-id" not in arguments


def test_a_toolless_call_sends_neither_schema_nor_protocol_note(fake_binary):
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_binary))
    arguments = transport.command("system rules", None)
    assert "--json-schema" not in arguments
    assert TOOL_PROTOCOL_NOTE not in arguments[arguments.index("--system-prompt") + 1]


def test_an_unknown_effort_is_refused():
    with pytest.raises(ValueError, match="effort"):
        ClaudeCodeTransport(WRITER_MODEL, effort="turbo")


def test_a_missing_binary_names_the_fix(tmp_path):
    with pytest.raises(RuntimeError) as error:
        resolve_binary(str(tmp_path / "nope"))
    assert CLAUDE_CODE_INSTALL_HINT in str(error.value)


# --- the round trip, against a stub binary ------------------------------

FAKE_BINARY_SOURCE = '''#!/usr/bin/env python3
"""A stand-in for `claude`: replays canned frames, records its input."""
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
if "auth" in sys.argv:
    sys.stdout.write(json.dumps(json.load(open(os.path.join(here, "auth.json")))))
    sys.exit(0)
open(os.path.join(here, "argv.json"), "w").write(json.dumps(sys.argv[1:]))
open(os.path.join(here, "stdin.txt"), "w").write(sys.stdin.read())
delay = float(os.environ.get("FAKE_CLAUDE_DELAY_SECONDS", "0"))
if delay:
    time.sleep(delay)
for line in open(os.path.join(here, "frames.jsonl")):
    sys.stdout.write(line)
    sys.stdout.flush()
'''


def _result_frame(**overrides) -> dict:
    frame = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"message":"on it","tool_calls":[]}',
        "structured_output": {
            "message": "on it",
            "tool_calls": [{"name": "run_python", "arguments": {"source": "print(1)"}}],
        },
    }
    frame.update(overrides)
    return frame


RATE_LIMIT_FRAME = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "resetsAt": 1788634200,
        "unifiedWindows": {
            "five_hour": {"utilization": 0.25},
            "seven_day": {"utilization": 0.5},
        },
    },
}


@pytest.fixture
def fake_binary(tmp_path):
    """An executable stub whose canned frames a test can rewrite."""
    binary = tmp_path / "claude"
    binary.write_text(FAKE_BINARY_SOURCE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "auth.json").write_text(
        json.dumps(
            {
                "loggedIn": True,
                "authMethod": "claude.ai",
                "subscriptionType": "max",
            }
        )
    )
    _write_frames(binary, [RATE_LIMIT_FRAME, _result_frame()])
    return binary


def _write_frames(binary: Path, frames: list[dict]) -> None:
    (binary.parent / "frames.jsonl").write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames)
    )


def _transport(binary: Path, **overrides) -> ClaudeCodeTransport:
    return ClaudeCodeTransport(WRITER_MODEL, binary_path=str(binary), **overrides)


def test_the_round_trip_yields_a_schema_constrained_tool_call(fake_binary):
    transport = _transport(fake_binary)
    message = transport.chat(
        [
            {"role": "system", "content": "system rules"},
            {"role": "user", "content": "make a crate"},
        ],
        TOOL_SCHEMAS,
    )
    assert message["content"] == "on it"
    assert message["tool_calls"][0]["function"]["name"] == "run_python"
    # Exactly one user frame reached the CLI.
    sent = (fake_binary.parent / "stdin.txt").read_text().strip().splitlines()
    assert len(sent) == 1
    assert json.loads(sent[0])["type"] == "user"
    assert transport.last_rate_limit.five_hour_utilization == 0.25


def test_a_toolless_round_trip_returns_the_plain_text_result(fake_binary):
    _write_frames(
        fake_binary,
        [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "weighing it"},
                        {"type": "text", "text": "a red cube"},
                    ]
                },
            },
            _result_frame(result="a red cube", structured_output=None),
        ],
    )
    message = _transport(fake_binary).chat(
        [{"role": "user", "content": "describe this"}]
    )
    assert message["content"] == "a red cube"
    assert message["thinking"] == "weighing it"
    assert message["tool_calls"] == []


def test_an_error_result_is_reported_loudly(fake_binary):
    _write_frames(
        fake_binary,
        [
            RATE_LIMIT_FRAME,
            _result_frame(
                subtype="error_during_execution", is_error=True, result="upstream 529"
            ),
        ],
    )
    with pytest.raises(RuntimeError) as error:
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)
    detail = str(error.value)
    assert "error_during_execution" in detail
    assert "upstream 529" in detail
    # The window numbers travel with the failure: overage is rejected on
    # this account, so a limit hit is a hard stop the user must see.
    assert "5h window" in detail


def test_a_missing_envelope_names_the_stale_cli(fake_binary):
    _write_frames(fake_binary, [_result_frame(structured_output=None)])
    with pytest.raises(RuntimeError, match="claude update"):
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)


def test_no_result_frame_is_an_error_not_an_empty_answer(fake_binary):
    _write_frames(fake_binary, [RATE_LIMIT_FRAME])
    with pytest.raises(RuntimeError, match="no result frame"):
        _transport(fake_binary).chat([{"role": "user", "content": "go"}], TOOL_SCHEMAS)


def test_a_hung_turn_hits_the_ceiling(fake_binary, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_DELAY_SECONDS", "5")
    with pytest.raises(RuntimeError, match="did not answer within"):
        _transport(fake_binary, timeout_seconds=1).chat(
            [{"role": "user", "content": "go"}], TOOL_SCHEMAS
        )


def test_the_preflight_checks_auth_before_it_spends_a_token(fake_binary):
    ok, detail = _transport(fake_binary).check_connection(TOOL_SCHEMAS)
    assert ok
    assert "claude.ai" in detail and "max" in detail
    assert "5h window" in detail


def test_a_signed_out_cli_fails_the_preflight(fake_binary):
    (fake_binary.parent / "auth.json").write_text(json.dumps({"loggedIn": False}))
    ok, detail = _transport(fake_binary).check_connection(TOOL_SCHEMAS)
    assert not ok
    assert "claude auth login" in detail


def test_the_client_routes_a_claude_id_through_the_transport(fake_binary):
    """The lane is reachable the same way every other lane is: build a
    config, build the client, call chat."""
    client = OllamaClient(
        ModelConfig.from_environment(
            model=WRITER_MODEL,
            vision_model="",
            claude_code_binary_path=str(fake_binary),
        )
    )
    message = client.chat([{"role": "user", "content": "make a crate"}], TOOL_SCHEMAS)
    assert message["tool_calls"][0]["function"]["name"] == "run_python"
    argv = json.loads((fake_binary.parent / "argv.json").read_text())
    assert "--safe-mode" in argv


def test_the_rate_limit_summary_reads_as_percentages():
    snapshot = parse_rate_limit(RATE_LIMIT_FRAME)
    assert snapshot.allowed
    assert snapshot.resets_at_epoch_seconds == 1788634200
    assert snapshot.summary() == "limits 25% of the 5h window, 50% of the 7d window"
    exhausted = parse_rate_limit(
        {"rate_limit_info": {"status": "rejected", "unifiedWindows": {}}}
    )
    assert not exhausted.allowed
    assert "rejected" in exhausted.summary()


# --- token economics ----------------------------------------------------


def test_a_growing_transcript_keeps_the_previous_turn_as_its_prefix():
    """The property prompt caching depends on, pinned.

    Measured 2026-09-06: a byte-identical prefix reads at 0.1x while a
    changed one re-writes at 1.25x — 12,241 tokens cost $0.0507 cold
    and $0.0043 warm, an 11.8x swing. The cache hits only because
    `render_call` folds append-only, so turn N+1's wire bytes start
    with turn N's. Pruning history, summarising early turns or moving
    an image would silently forfeit that, and this is the test that
    would fail.
    """
    first_turn = [
        {"role": "system", "content": "the working agreement"},
        {"role": "user", "content": "make a crate"},
    ]
    second_turn = first_turn + [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "function": {"name": "run_python", "arguments": {}}}
            ],
        },
        {
            "role": "tool",
            "tool_name": "run_python",
            "tool_call_id": "a",
            "content": "built Crate",
        },
        {"role": "user", "content": "now bevel it"},
    ]
    first_system, first_frame = render_call(first_turn)
    second_system, second_frame = render_call(second_turn)

    assert first_system == second_system, "the system prompt must not move"
    first_text = first_frame["message"]["content"][0]["text"]
    second_text = second_frame["message"]["content"][0]["text"]
    # The cue closes each fold, so the shared part is everything before
    # it — which is what the cache matches on.
    shared = first_text[: first_text.index(CONTINUATION_CUE)]
    assert second_text.startswith(shared)


def test_the_system_prompt_is_byte_stable_across_builds():
    """A volatile system prompt would re-write the whole cached prefix.

    Nothing in it may vary per call: no timestamp, no counter, no live
    scene state. Measured cost of getting this wrong: the 12,241-token
    prefix moves from a 0.1x read to a 1.25x write on every turn.
    """
    from blended.agent.system_prompt import build_system_prompt

    assert build_system_prompt() == build_system_prompt()


def test_one_harness_turn_reports_every_api_call_it_made():
    """A turn is not a call: the CLI runs the model again to conform to
    `--json-schema`, measured at 2-3 calls per turn on 2026-09-06.

    A cost record that assumed one call per turn would under-report the
    single largest inefficiency in the loop by half.
    """
    from blended.agent.claude_code import parse_turn_cost

    cost = parse_turn_cost(
        {
            "usage": {
                "input_tokens": 2,
                "cache_read_input_tokens": 25_092,
                "cache_creation_input_tokens": 755,
                "output_tokens": 856,
            },
            "total_cost_usd": 0.0178,
        },
        api_calls=2,
    )
    assert cost.api_calls == 2
    assert cost.billed_input_tokens == 25_849
    assert cost.plus(cost).billed_input_tokens == 51_698
    assert cost.plus(cost).api_calls == 4
    assert "2 api call(s)" in cost.summary()
