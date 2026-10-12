"""The OpenAI-protocol lane (llama-swap on bmb and on big): wire shape
and the tool-call round trip.

llama-swap exposes /v1/chat/completions, not Ollama's /api/chat, so a
client pointed at BMB_ENDPOINT must translate messages, tools, and the
assistant reply — including the tool_call ids that an OpenAI backend
requires on the result messages. All assertions happen at the _request
boundary, the same interception point the vision-transport tests use.
"""

import io
import urllib.error
from dataclasses import replace

import pytest

from blended.agent.loop import (
    BIG_ENDPOINT,
    BMB_ENDPOINT,
    ModelConfig,
    OllamaClient,
)

TOOL_CALL_ID = "call_abc123"


@pytest.fixture(autouse=True)
def isolated_lane_environment(monkeypatch):
    """Config construction reads ~/.blended/bmb_api_key for bmb models,
    and OLLAMA_HOST overrides every model's implied server. These tests
    must pass on a machine with either set and never touch the real key.
    Tests that care set them again."""
    monkeypatch.setattr("blended.agent.loop._read_bmb_api_key", lambda: "a" * 64)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)


@pytest.fixture
def openai_payloads(monkeypatch):
    """Capture OpenAI-protocol payloads; return canned assistant
    messages with tool calls."""
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append((path, payload))
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": TOOL_CALL_ID,
                                "type": "function",
                                "function": {
                                    "name": "run_python",
                                    "arguments": '{"source": "print(1)"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    return payloads


def _bmb_client():
    return OllamaClient(
        ModelConfig.from_environment(model="qwen3.8-27b", endpoint=BMB_ENDPOINT)
    )


def test_bmb_endpoint_uses_the_openai_path_and_wire_shape(openai_payloads):
    client = _bmb_client()
    reply = client.chat(
        [
            {"role": "system", "content": "build"},
            {"role": "user", "content": "make a crate"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_python",
                    "description": "execute",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    path, payload = openai_payloads[0]
    assert path == "/v1/chat/completions"
    assert payload["model"] == "qwen3.8-27b"
    assert payload["messages"] == [
        {"role": "system", "content": "build"},
        {"role": "user", "content": "make a crate"},
    ]
    assert payload["tools"][0]["function"]["name"] == "run_python"
    assert "options" not in payload  # OpenAI payload has no Ollama options
    assert payload["max_tokens"] == 16384

    assert reply["tool_calls"][0]["id"] == TOOL_CALL_ID
    assert reply["tool_calls"][0]["function"]["name"] == "run_python"
    assert reply["tool_calls"][0]["function"]["arguments"] == '{"source": "print(1)"}'


def test_a_llama_swap_turn_gets_the_long_ceiling_and_the_cloud_keeps_the_short_one(
    monkeypatch,
):
    """The 300 s cloud ceiling killed bmb's 27B mid-generation: its
    first planter_box turn took 353.7 s and 3880 mostly-thinking
    completion tokens before returning a valid tool call (measured
    twice, 2026-09-03). `chat` must hand `_request` the ceiling the
    LANE needs, not one constant for every server."""
    from blended.agent import loop as live_loop

    timeouts: list[int] = []

    def capture(self, path, payload, timeout_seconds):
        timeouts.append(timeout_seconds)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture)
    monkeypatch.setattr(live_loop, "_read_bmb_api_key", lambda: "a" * 64)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    for model in ("qwen3.8-27b", "qwen3-vl"):
        client = live_loop.OllamaClient(
            live_loop.ModelConfig.from_environment(model=model)
        )
        assert client.config.uses_openai_protocol
        client.chat([{"role": "user", "content": "ping"}])

    def capture_ollama(self, path, payload, timeout_seconds):
        timeouts.append(timeout_seconds)
        return {"message": {"role": "assistant", "content": "ok"}}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture_ollama)
    cloud = live_loop.OllamaClient(
        # The Ollama lane sends num_ctx, which the daemon tells it (OT-27);
        # this test is about the wall clock, so the window is given.
        live_loop.ModelConfig.from_environment(
            model="deepseek-v4-pro:cloud", context_length=1_048_576
        )
    )
    cloud.chat([{"role": "user", "content": "ping"}])

    assert timeouts == [
        live_loop.LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS,
        live_loop.LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS,
        live_loop.REQUEST_TIMEOUT_SECONDS,
    ]
    # The preflight ceiling stays short: a dead server is still
    # diagnosed, never waited on for 15 minutes.
    assert (
        live_loop.PREFLIGHT_TIMEOUT_SECONDS
        < live_loop.REQUEST_TIMEOUT_SECONDS
        < live_loop.LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS
    )


def test_tool_result_round_trip_carries_the_call_id(openai_payloads):
    client = _bmb_client()
    client.chat(
        [
            {"role": "user", "content": "go"},
            {
                "role": "tool",
                "content": "GATE: PASS",
                "tool_name": "run_python",
                "tool_call_id": TOOL_CALL_ID,
            },
        ]
    )
    _, payload = openai_payloads[0]
    tool_messages = [m for m in payload["messages"] if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == TOOL_CALL_ID
    assert tool_messages[0]["content"] == "GATE: PASS"
    # The Ollama-only keys must not leak onto the OpenAI wire.
    assert "tool_name" not in tool_messages[0]


def test_images_travel_as_openai_image_url_parts(monkeypatch, tmp_path):
    """The bmb lane is the eye lane for qwen3.8 too: an Ollama `images`
    field must become OpenAI image_url content parts, not be dropped."""
    from blended.agent.loop import _encode_images

    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append(payload)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I see a crate.",
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = OllamaClient(
        ModelConfig.from_environment(model="qwen3.8-27b", endpoint=BMB_ENDPOINT)
    )
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.write_bytes(b"png")
    second.write_bytes(b"png")
    reply = client.chat(
        [
            {
                "role": "user",
                "content": "What do you see?",
                "images": _encode_images([first, second]),
            }
        ]
    )
    assert reply["content"] == "I see a crate."
    message = payloads[0]["messages"][0]
    assert isinstance(message["content"], list)
    parts = message["content"]
    assert parts[0] == {"type": "text", "text": "What do you see?"}
    assert all(part["type"] == "image_url" for part in parts[1:])
    assert len(parts) == 3
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_ollama_endpoint_keeps_the_ollama_wire_shape(monkeypatch):
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append((path, payload))
        return {"message": {"role": "assistant", "content": "ok"}}

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = OllamaClient(
        ModelConfig.from_environment(
            model="deepseek-v4-pro:cloud", context_length=1_048_576
        )
    )
    client.chat([{"role": "user", "content": "hi"}])

    path, payload = payloads[0]
    assert path == "/api/chat"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert "options" in payload  # Ollama options stay on the Ollama wire


def test_a_pinned_seed_reaches_both_wires_and_an_unset_one_is_not_sent():
    """A controlled experiment needs the seed ON THE WIRE; an ordinary run
    must keep the server's random default.

    Sending `seed: null` would pin llama-server to seed 0 on some builds
    and make every ordinary turn silently deterministic, so "unset" has
    to mean absent, not null. Both lanes carry it in their own place:
    top level on the OpenAI wire, inside `options` on the Ollama one."""
    openai_lane = OllamaClient(
        ModelConfig.from_environment(model="qwen2.5-coder-7b-instruct", seed=7)
    )
    payload = openai_lane._chat_payload([{"role": "user", "content": "hi"}])
    assert payload["seed"] == 7

    ollama_lane = OllamaClient(
        ModelConfig.from_environment(
            model="deepseek-v4-pro:cloud", seed=7, context_length=8_192
        )
    )
    assert (
        ollama_lane._chat_payload([{"role": "user", "content": "hi"}])["options"][
            "seed"
        ]
        == 7
    )

    unset_openai = OllamaClient(
        ModelConfig.from_environment(model="qwen2.5-coder-7b-instruct")
    )
    assert "seed" not in unset_openai._chat_payload([{"role": "user", "content": "hi"}])
    unset_ollama = OllamaClient(
        ModelConfig.from_environment(
            model="deepseek-v4-pro:cloud", context_length=8_192
        )
    )
    options = unset_ollama._chat_payload([{"role": "user", "content": "hi"}])["options"]
    assert "seed" not in options


def test_the_default_endpoint_does_not_override_the_model_pin():
    """The addon always passes preferences.endpoint, and every fresh
    install and saved preference holds the default localhost value.
    That legacy default must count as UNSET — a saved preference must
    not override the model the user just picked (measured: qwen3.8-27b was
    sent to the Ollama daemon and 404'd)."""
    config = ModelConfig.from_environment(
        model="qwen3.8-27b", endpoint="http://localhost:11434"
    )
    assert config.endpoint == BMB_ENDPOINT
    # An EXPLICIT different endpoint still wins.
    explicit = ModelConfig.from_environment(
        model="qwen3.8-27b", endpoint="http://192.168.1.50:1234"
    )
    assert explicit.endpoint == "http://192.168.1.50:1234"


def test_gpt_oss_20b_is_a_bmb_model():
    """gpt-oss-20b-heretic:latest 404'd because NOTHING serves it. The
    real id on bmb's llama-swap is gpt-oss-20b (live /v1/models) and it
    must route to the bmb lane, not the local daemon."""
    writer = ModelConfig.from_environment(model="gpt-oss-20b")
    assert writer.endpoint == BMB_ENDPOINT
    assert writer.uses_openai_protocol
    # As an eye it rides the bmb lane too.
    eye = ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="gpt-oss-20b"
    ).eye_config()
    assert eye.endpoint == BMB_ENDPOINT


def test_the_bmb_key_file_feeds_bmb_models_only(monkeypatch):
    """A bmb model with no api_key reads the key file. Non-bmb models
    must NEVER read it (the Ollama env key is the wrong credential for
    llama-swap and vice versa)."""
    fake_bmb_key = "c" * 64
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr("blended.agent.loop._read_bmb_api_key", lambda: fake_bmb_key)

    bmb_config = ModelConfig.from_environment(model="qwen3.8-27b", api_key="")
    assert bmb_config.api_key == fake_bmb_key

    # The patched file would put its key here if this lane read it.
    ollama_config = ModelConfig.from_environment(
        model="deepseek-v4-pro:cloud", api_key=""
    )
    assert ollama_config.api_key == ""


def test_the_eye_rides_the_daemon_when_the_writer_rides_bmb(monkeypatch):
    """A cloud eye does not live on bmb: when the writer is on bmb and
    the eye is a non-bmb model, the eye's config must point at the
    Ollama daemon. (The qwen3.8 eye, by contrast, rides bmb — see
    test_the_qwen3_8_eye_rides_the_bmb_lane.)

    The cloud eye is named here rather than inherited from the default:
    the default eye is `claude-code:sonnet`, which has a server of its
    own, so borrowing it would test a different rule than the one this
    docstring claims.
    """
    writer = ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="kimi-k2.7-code:cloud"
    )
    eye = writer.eye_config()
    assert eye.endpoint == "http://localhost:11434"
    assert eye.model == "kimi-k2.7-code:cloud"
    # The vision describer follows the same rule: its call lands on the
    # daemon, not on the writer's bmb endpoint.
    from blended.agent import loop as live_loop

    captured: list[tuple[str, str]] = []

    def capture(self, path, payload, timeout_seconds):
        captured.append((self.config.endpoint, self.config.model))
        return {"message": {"role": "assistant", "content": "a render"}}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture)
    # The Ollama wire needs a window, which preflight discovers in real runs.
    sighted_writer = replace(writer, eye_context_length=8_192)
    describer = live_loop.VisionDescriber(
        live_loop.OllamaClient(sighted_writer), writer.vision_model
    )
    assert describer.describe([]) == "a render"
    assert captured == [("http://localhost:11434", "kimi-k2.7-code:cloud")]


def test_reasoning_content_maps_to_thinking(monkeypatch):
    def capture(self, path, payload, timeout_seconds):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning_content": "think step by step",
                    }
                }
            ]
        }

    monkeypatch.setattr(OllamaClient, "_request", capture)
    client = _bmb_client()
    reply = client.chat([{"role": "user", "content": "hi"}])
    assert reply["content"] == "final answer"
    assert reply["thinking"] == "think step by step"


def test_the_qwen3_8_eye_rides_the_bmb_lane(monkeypatch):
    """Picking the bmb model as the eye routes it to bmb's OpenAI lane —
    the same server that serves the writer — so one local model covers
    text and vision. This is the replacement for the qwen3.5:27b local
    vision slot (never installed, 16 GiB pull, no disk room)."""
    writer = ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="qwen3.8-27b"
    )
    eye = writer.eye_config()
    assert eye.endpoint == BMB_ENDPOINT
    assert eye.model == "qwen3.8-27b"
    assert eye.uses_openai_protocol
    # The describer routes the same way: a cloud writer's describer call
    # leaves the daemon for bmb.
    from blended.agent import loop as live_loop

    captured: list[str] = []

    def capture(self, path, payload, timeout_seconds):
        captured.append(self.config.endpoint)
        return {"choices": [{"message": {"role": "assistant", "content": "a crate"}}]}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture)
    cloud_writer = ModelConfig.from_environment(
        model="deepseek-v4-pro:cloud", vision_model="qwen3.8-27b", context_length=8_192
    )
    assert cloud_writer.endpoint != BMB_ENDPOINT
    describer = live_loop.VisionDescriber(OllamaClient(cloud_writer), "qwen3.8-27b")
    assert describer.describe([]) == "a crate"
    assert captured == [BMB_ENDPOINT]


def test_the_401_hint_names_the_bmb_key_for_openai_lanes(monkeypatch):
    """A 401 on the bmb lane must say 'paste the llama-swap key', not
    'run ollama signin' — the two lanes authenticate differently.

    The config is built DIRECTLY (not via from_environment) so the
    test cannot be polluted by the real key file or a shell env key
    from another test's environment.
    """

    def forbidden(self, path, payload, timeout_seconds):
        raise urllib.error.HTTPError(path, 401, "unauthorized", None, None)

    monkeypatch.setattr(OllamaClient, "_request", forbidden)
    client = OllamaClient(
        ModelConfig(model="qwen3.8-27b", endpoint=BMB_ENDPOINT, api_key="")
    )
    status = client.check_connection()
    assert not status.ok
    assert "llama-swap" in status.detail and ".api-key" in status.detail
    assert "ollama signin" not in status.detail


def test_the_local_eye_rides_bigs_llama_swap(monkeypatch):
    """qwen3-vl lives on big's llama-swap, not on this machine —
    mac_air's daemon reports zero models, so routing the local eye to
    LOCAL_ENDPOINT 404'd with "model not found" (measured 2026-08-25,
    the failure this lane exists to fix). The eye must reroute itself
    while the cloud writer stays on the daemon that proxies cloud."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    writer = ModelConfig.from_environment(
        model="deepseek-v4-pro:cloud",
        endpoint="http://localhost:11434",
        vision_model="qwen3-vl",
    )
    assert writer.endpoint == "http://localhost:11434"
    eye = writer.eye_config()
    assert eye.endpoint == BIG_ENDPOINT
    assert eye.model == "qwen3-vl"
    assert eye.uses_openai_protocol  # big's llama-swap speaks OpenAI
    # As a writer the same id routes there too.
    assert ModelConfig.from_environment(model="qwen3-vl").endpoint == BIG_ENDPOINT
    # The describer uses the same rule, not a second copy of it. The
    # class and the patch target come from one module object, so the
    # patched _request is the one that runs and nothing reaches big.
    from blended.agent import loop as live_loop

    captured: list[str] = []

    def capture(self, path, payload, timeout_seconds):
        captured.append(self.config.endpoint)
        # big's lane is OpenAI-shaped, so the reply must be too — the
        # eye reads choices[0].message there, not `message`.
        return {"choices": [{"message": {"role": "assistant", "content": "a render"}}]}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture)
    describer = live_loop.VisionDescriber(live_loop.OllamaClient(writer), "qwen3-vl")
    assert describer.describe([]) == "a render"
    assert captured == [BIG_ENDPOINT]


def test_the_local_qwen_pair_splits_across_two_hosts(monkeypatch):
    """writer on bmb, eye on big — and each gets its OWN credential:
    bmb 401s without its key file, big's llama-swap has no apiKeys
    list and must never receive one."""
    # Bind ONE module object for the patch AND the construction, so the
    # fake key file is the one the constructor reads.
    from blended.agent import loop as live_loop

    monkeypatch.setattr(live_loop, "_read_bmb_api_key", lambda: "a" * 64)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    writer = live_loop.ModelConfig.from_environment(
        model="qwen3.8-27b", vision_model="qwen3-vl"
    )
    assert writer.endpoint == BMB_ENDPOINT
    assert writer.api_key == "a" * 64
    eye = writer.eye_config()
    assert eye.endpoint == BIG_ENDPOINT
    assert eye.model == "qwen3-vl"
    assert eye.uses_openai_protocol
    assert eye.api_key == ""


def test_a_cloud_writers_key_never_rides_to_a_llama_swap_eye(monkeypatch):
    """The eye's credential follows the eye's SERVER. A cloud writer's
    Ollama key sent to bmb 401s, and bmb's key has no business on
    big."""
    from blended.agent import loop as live_loop

    monkeypatch.setenv("OLLAMA_API_KEY", "cloud-key")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(live_loop, "_read_bmb_api_key", lambda: "b" * 64)

    def eye_for(vision_model):
        return live_loop.ModelConfig.from_environment(
            model="deepseek-v4-pro:cloud", vision_model=vision_model
        ).eye_config()

    assert eye_for("qwen3.8-27b").api_key == "b" * 64
    assert eye_for("qwen3-vl").api_key == ""
    # A cloud eye still gets the environment credential.
    assert eye_for("kimi-k2.7-code:cloud").api_key == "cloud-key"


def test_a_404_hint_names_the_missing_model_not_the_api_key(monkeypatch):
    """A signed-in daemon needs no key, so keying the hint off an empty
    api_key printed "No OLLAMA_API_KEY" over a 404 and sent a real
    debugging session chasing auth that was already fine (measured
    2026-08-25). The hint must follow the observed status code."""

    def missing(self, path, payload, timeout_seconds):
        raise urllib.error.HTTPError(
            path, 404, "not found", None, io.BytesIO(b'{"error":"model not found"}')
        )

    monkeypatch.setattr(OllamaClient, "_request", missing)
    status = OllamaClient(ModelConfig(model="qwen3-vl", api_key="")).check_connection()
    assert not status.ok
    assert "Nothing at http://localhost:11434 serves" in status.detail
    assert BIG_ENDPOINT in status.detail
    assert "OLLAMA_API_KEY" not in status.detail
    # The printed probe follows the lane's protocol: that config sits on
    # the local Ollama daemon, so /api/tags — but the same model on big
    # is an OpenAI lane, where /api/tags does not exist.
    assert "/api/tags" in status.detail
    on_big = OllamaClient(
        ModelConfig(model="qwen3-vl", endpoint=BIG_ENDPOINT, api_key="")
    ).check_connection()
    assert not on_big.ok
    assert "/v1/models" in on_big.detail
    assert "/api/tags" not in on_big.detail


def test_a_connection_refused_carries_no_auth_advice(monkeypatch):
    """A dead daemon is not an auth problem either: only 401/403 earns
    the key hint."""

    def refused(self, path, payload, timeout_seconds):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(OllamaClient, "_request", refused)
    status = OllamaClient(
        ModelConfig(model="deepseek-v4-pro:cloud", api_key="")
    ).check_connection()
    assert not status.ok
    assert "Connection refused" in status.detail
    assert "OLLAMA_API_KEY" not in status.detail


def test_a_vendor_slash_model_rides_openrouter_with_its_own_key(monkeypatch, tmp_path):
    """`vendor/model` is OpenRouter's id shape and nothing else's. The
    lane is OpenAI wire, keeps the CLOUD timeout (a dead gateway must be
    reported, not waited on for 900 s), reads its own key file — in
    either the bare or the `OPENROUTER_API_KEY=` form — and never the
    Ollama env key."""
    from blended.agent import loop as live_loop

    key_file = tmp_path / "openrouter_api_key"
    key_file.write_text("OPENROUTER_API_KEY=sk-or-v1-deadbeef\n")
    monkeypatch.setattr(live_loop, "OPENROUTER_API_KEY_FILE", key_file)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-key-must-not-leak")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    config = live_loop.ModelConfig.from_environment(model="qwen/qwen3-vl-8b-instruct")
    assert config.endpoint == live_loop.OPENROUTER_ENDPOINT
    assert config.uses_openai_protocol
    assert config.api_key == "sk-or-v1-deadbeef"
    assert config.request_timeout_seconds == live_loop.REQUEST_TIMEOUT_SECONDS

    key_file.write_text("sk-or-v1-bare\n")
    assert live_loop._read_openrouter_api_key() == "sk-or-v1-bare"

    key_file.write_text("not-a-key\n")
    with pytest.raises(RuntimeError):
        live_loop._read_openrouter_api_key()

    # A cloud eye beside an OpenRouter writer rides the daemon with the
    # env key; an OpenRouter eye beside a cloud writer rides OpenRouter.
    key_file.write_text("sk-or-v1-eye\n")
    writer = live_loop.ModelConfig.from_environment(
        model="qwen/qwen3-vl-8b-instruct", vision_model="kimi-k2.7-code:cloud"
    )
    assert writer.eye_config().endpoint == live_loop.LOCAL_ENDPOINT
    assert writer.eye_config().api_key == "ollama-key-must-not-leak"
    cloud_writer = live_loop.ModelConfig.from_environment(
        model="deepseek-v4-pro:cloud", vision_model="qwen/qwen3-vl-8b-instruct"
    )
    assert cloud_writer.eye_config().endpoint == live_loop.OPENROUTER_ENDPOINT
    assert cloud_writer.eye_config().api_key == "sk-or-v1-eye"


def test_the_completion_cap_is_per_config_so_a_metered_lane_can_bound_spend(
    monkeypatch,
):
    from blended.agent import loop as live_loop

    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    monkeypatch.setattr(live_loop.OllamaClient, "_request", capture)
    client = live_loop.OllamaClient(
        live_loop.ModelConfig(
            model="qwen/qwen3-vl-8b-instruct",
            endpoint=live_loop.OPENROUTER_ENDPOINT,
            api_key="sk-or-v1-x",
            max_completion_tokens=64,
        )
    )
    client.chat([{"role": "user", "content": "ping"}])
    assert payloads[0]["max_tokens"] == 64


def test_the_assistant_tool_calls_travel_with_their_results():
    """The history must show the model its OWN calls, not only answers.

    `_to_openai_messages` dropped `tool_calls`, so every tool message
    answered a `tool_call_id` that appeared nowhere in the request. bmb's
    llama-swap and Ollama's cloud tolerated it; a strict upstream
    returned HTTP 400 on the SECOND call of every converge run — the
    first, carrying no tool result yet, always succeeded (measured
    2026-09-10: five briefs, five identical failures). The protocol also
    wants `arguments` as a JSON string, not the dict the loop keeps.
    """
    import json as _json

    from blended.agent.loop import _to_openai_messages

    converted = _to_openai_messages(
        [
            {"role": "user", "content": "build"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "add_box",
                            "arguments": {"name": "Crate", "width_m": 0.5},
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_name": "add_box",
                "tool_call_id": "call_1",
                "content": "OK: add_box",
            },
        ]
    )
    assistant, tool_result = converted[1], converted[2]
    (call,) = assistant["tool_calls"]
    assert call["id"] == "call_1" and call["type"] == "function"
    assert call["function"]["name"] == "add_box"
    assert _json.loads(call["function"]["arguments"]) == {
        "name": "Crate",
        "width_m": 0.5,
    }
    # Every tool result answers a call that is actually in the request.
    assert tool_result["tool_call_id"] == call["id"]

    # A string already in protocol shape is passed through untouched.
    (passthrough,) = _to_openai_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "b", "function": {"name": "f", "arguments": '{"a":1}'}}
                ],
            }
        ]
    )[0]["tool_calls"]
    assert passthrough["function"]["arguments"] == '{"a":1}'

    # An assistant turn that made no calls carries no empty key.
    assert (
        "tool_calls"
        not in _to_openai_messages([{"role": "assistant", "content": "done"}])[0]
    )
