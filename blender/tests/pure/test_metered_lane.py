"""OT-28: the metered lane tells the truth about itself.

A lane that charges money per call must be able to say two things the
harness could not say before: how wide the served model's context is,
and what a run has spent. Both are read from the provider — never
tabled, never assumed — and the second is what NFR-27's cap is built on.
"""

from __future__ import annotations

import contextlib
import io

import pytest

from blended.agent.loop import (
    BMB_ENDPOINT,
    LOCAL_ENDPOINT,
    MAXIMUM_RESERVED_COMPLETION_TOKENS,
    MAXIMUM_RUN_COST_USD,
    OPENROUTER_ENDPOINT,
    OPENROUTER_ENDPOINTS_PATH,
    OPENROUTER_PINNED_PROVIDER,
    RETRY_BACKOFF_SECONDS,
    ContextUndiscovered,
    ModelConfig,
    OllamaClient,
    RunCostExceeded,
    _turn_cost_from_body,
)

# Read from OpenRouter's catalogue 2026-09-10; the harness's metered
# writer and its own eye — tools, structured outputs, text and image.
METERED_MODEL = "deepseek/deepseek-v4.1-flash"
METERED_WINDOW = 1_048_576


def _urlopen_from(handler):
    """Turn a `(self, path, payload, timeout)` handler into a urlopen stand-in
    so a test can drive `_open`'s retry loop at the HTTP boundary.

    The handler runs when urlopen is CALLED, as the real one raises its
    HTTPError at call time and not on entering the response — that is
    the property the retry loop rests on (OT-35)."""

    def urlopen(request, timeout=None, context=None):
        import json as _json

        body = handler(None, request, None, timeout)
        return contextlib.closing(io.BytesIO(_json.dumps(body).encode()))

    return urlopen


def _metered_config(**overrides) -> ModelConfig:
    fields = {
        "model": METERED_MODEL,
        "endpoint": OPENROUTER_ENDPOINT,
        "vision_model": "",
        "api_key": "sk-or-test",
    }
    fields.update(overrides)
    return ModelConfig(**fields)


def _endpoints_path(model=METERED_MODEL) -> str:
    return OPENROUTER_ENDPOINTS_PATH.format(model=model)


def _catalogue(monkeypatch, entries, reply=None):
    """A fake OpenRouter answering the endpoints call and then chat."""
    calls = []

    def fake_request(self, path, payload, timeout_seconds):
        calls.append((path, payload))
        if path.startswith("/v1/models/"):
            return {"data": {"endpoints": entries}}
        return reply or {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 36, "completion_tokens": 17, "cost": 0.0000312},
        }

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    return calls


def test_the_window_comes_from_the_pinned_providers_endpoint(monkeypatch):
    # Two providers serve the id with DIFFERENT windows; the lane must
    # take its own provider's, not the id's best (measured 2026-09-10:
    # 262,144 to 1,048,576 across the eight serving this model).
    calls = _catalogue(
        monkeypatch,
        [
            {
                "tag": "someone-else",
                "provider_name": "Someone Else",
                "context_length": 262_144,
            },
            {
                "tag": OPENROUTER_PINNED_PROVIDER,
                "provider_name": "GMICloud",
                "context_length": METERED_WINDOW,
            },
        ],
    )
    client = OllamaClient(_metered_config())
    assert client.config.context_tokens is None

    status = client.check_connection()

    assert status.ok and f"OpenRouter -> {OPENROUTER_PINNED_PROVIDER}" in status.detail
    assert f"context {METERED_WINDOW:,}" in status.detail
    assert calls[0] == (
        _endpoints_path(),
        None,
    )  # the provider's endpoint before the ping
    assert client.config.context_tokens == METERED_WINDOW

    # And the request names that one provider, with no silent reroute.
    payload = client._chat_payload([{"role": "user", "content": "x"}])
    assert payload["provider"] == {
        "order": [OPENROUTER_PINNED_PROVIDER],
        "allow_fallbacks": False,
    }


def test_a_provider_that_does_not_serve_the_model_is_refused_with_those_that_do(
    monkeypatch,
):
    """Measured 2026-09-10: pinning `deepseek` — the model's own vendor —
    answered "0 endpoints out of 1 requested are available matching your
    guardrail restriction" per call. The lane must say so at the
    preflight, and say who is left."""
    _catalogue(
        monkeypatch,
        [
            {"tag": "gmicloud", "context_length": METERED_WINDOW},
            {"tag": "deepinfra", "context_length": METERED_WINDOW},
        ],
    )
    client = OllamaClient(_metered_config(openrouter_provider="deepseek"))

    status = client.check_connection()

    assert not status.ok
    assert "'deepseek' does not serve" in status.detail
    assert "deepinfra, gmicloud" in status.detail  # who is left, named


def test_a_provider_entry_without_a_window_is_refused(monkeypatch):
    _catalogue(monkeypatch, [{"tag": OPENROUTER_PINNED_PROVIDER, "context_length": 0}])
    client = OllamaClient(_metered_config())
    with pytest.raises(ContextUndiscovered, match="context_length"):
        client.discover_context()


def test_the_price_is_asked_for_on_this_lane_and_on_no_other():
    metered = OllamaClient(_metered_config())._chat_payload(
        [{"role": "user", "content": "x"}]
    )
    assert metered["usage"] == {"include": True}

    llama_swap = OllamaClient(
        ModelConfig(
            model="qwen3.8-27b", endpoint=BMB_ENDPOINT, vision_model="", api_key="k"
        )
    )._chat_payload([{"role": "user", "content": "x"}])
    assert "usage" not in llama_swap  # our own hardware charges nothing

    daemon = OllamaClient(
        ModelConfig(
            model="anything",
            endpoint=LOCAL_ENDPOINT,
            vision_model="",
            context_length=32_768,
        )
    )._chat_payload([{"role": "user", "content": "x"}])
    assert "usage" not in daemon


def test_cost_comes_off_the_usage_object_and_stays_zero_where_none_is_reported():
    # OpenRouter, with the extension: a real measured reply (2026-09-10).
    priced = _turn_cost_from_body(
        {"usage": {"prompt_tokens": 36, "completion_tokens": 17, "cost": 0.0000312}}
    )
    assert priced.cost_usd == pytest.approx(0.0000312)
    assert priced.input_tokens == 36 and priced.output_tokens == 17

    # llama-swap fills in usage but never a price: zero means "charged
    # nothing", not "unknown".
    free = _turn_cost_from_body(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    )
    assert free.cost_usd == 0.0 and free.input_tokens == 100

    # The Ollama wire reports neither shape.
    ollama = _turn_cost_from_body({"prompt_eval_count": 7, "eval_count": 3})
    assert ollama.cost_usd == 0.0 and ollama.output_tokens == 3


def test_the_cache_split_and_the_thinking_share_are_read_too():
    """A real usage object from this lane (2026-09-10). `prompt_tokens`
    is the whole prompt side and the details are subsets of it, so the
    three token fields must still add up to what was billed — otherwise
    OT-26's cache-read fraction divides by an invented number."""
    cost = _turn_cost_from_body(
        {
            "usage": {
                "prompt_tokens": 34,
                "completion_tokens": 29,
                "cost": 2.662e-05,
                "prompt_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 4},
                "completion_tokens_details": {"reasoning_tokens": 24},
            }
        }
    )
    assert cost.billed_input_tokens == 34  # the provider's own number, unchanged
    assert (
        cost.input_tokens == 20
        and cost.cache_read_tokens == 10
        and cost.cache_write_tokens == 4
    )
    assert cost.reasoning_tokens == 24 and cost.output_tokens == 29
    assert "(24 reasoning)" in cost.summary()

    # A lane that reports no details: everything fresh, nothing thought.
    plain = _turn_cost_from_body(
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    )
    assert plain.input_tokens == 100 and plain.cache_read_tokens == 0
    assert plain.reasoning_tokens == 0 and "reasoning" not in plain.summary()


def test_a_metered_run_stops_at_its_cap_with_both_numbers_named(monkeypatch):
    expensive = {
        "choices": [{"message": {"role": "assistant", "content": "..."}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1000, "cost": 0.2},
    }
    _catalogue(
        monkeypatch,
        [{"tag": OPENROUTER_PINNED_PROVIDER, "context_length": METERED_WINDOW}],
        reply=expensive,
    )
    client = OllamaClient(_metered_config(maximum_run_cost_usd=0.30))
    client.check_connection()

    client.chat([{"role": "user", "content": "one"}])  # $0.20, under the cap
    assert client.spent.cost_usd == pytest.approx(0.2)

    with pytest.raises(RunCostExceeded) as refusal:
        client.chat([{"role": "user", "content": "two"}])  # $0.40, over it
    message = str(refusal.value)
    assert "$0.4000" in message and "$0.3000" in message and "NFR-27" in message
    assert METERED_MODEL in message


def test_only_a_metered_lane_is_capped(monkeypatch):
    """bmb's llama-swap bills nothing per call, so a long run there is
    not a spending accident and must never be stopped as one."""

    def fake_request(self, path, payload, timeout_seconds):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            # Big, but inside bmb's 65,536 window: this test is about
            # money, and a prompt over the window is a different error.
            "usage": {"prompt_tokens": 60_000, "completion_tokens": 5000},
        }

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    client = OllamaClient(
        ModelConfig(
            model="qwen3.8-27b",
            endpoint=BMB_ENDPOINT,
            vision_model="",
            api_key="k",
            maximum_run_cost_usd=0.01,
        )
    )
    assert not client.config.is_metered
    client.chat([{"role": "user", "content": "x"}])
    assert client.spent.cost_usd == 0.0


def test_the_cap_is_derived_from_the_heaviest_measured_run():
    """iteration 88 (three_leg_stool, the heaviest run on the disclosed
    surface): 1,353,594 billed input + 24,615 output tokens. Through the
    provider this lane can actually reach ($0.30/M and $1.20/M) that run
    costs $0.436, and the cap must clear it with room.

    The wrong number is pinned here too: at DeepSeek's own $0.15/$0.60
    the same run is $0.218 and a $0.50 cap looks generous, but that
    endpoint is excluded by the account's guardrail — a cap derived from
    a price the lane cannot reach would sit at 1.15x the heaviest
    legitimate brief.
    """
    reachable = 1_353_594 * 0.30 / 1e6 + 24_615 * 1.20 / 1e6
    unreachable = 1_353_594 * 0.15 / 1e6 + 24_615 * 0.60 / 1e6
    assert reachable == pytest.approx(0.4357, abs=1e-4)
    assert unreachable == pytest.approx(0.2178, abs=1e-4)
    assert MAXIMUM_RUN_COST_USD == 1.00
    assert MAXIMUM_RUN_COST_USD > 2 * reachable * 0.99  # ~2.3x the heaviest run


# --- a gateway saying "not now" is retried, bounded, then loud (OT-32) ---


def test_a_rate_limited_call_is_retried_then_succeeds(monkeypatch):
    """Measured 2026-09-10: five converge briefs in a row died on upstream
    429s within ~2 minutes, a probe minutes later passed 12 of 12, and a
    later chain lost 3 of 5 the same way. The windows are short and
    intermittent, so the same request sent again rides them out."""
    import urllib.error

    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    attempts = {"n": 0}

    def flaky(self, path, payload, timeout_seconds):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise urllib.error.HTTPError(
                path, 429, "Too Many Requests", {}, io.BytesIO(b"rate limited")
            )
        return {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(flaky)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    body = client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert body["choices"][0]["message"]["content"] == "pong"
    assert waits == list(RETRY_BACKOFF_SECONDS[:2])  # the measured backoff, in order
    assert client.spent.retried_calls == 2
    assert "2 retried" in client.spent.summary()


def test_a_permanent_error_is_not_retried(monkeypatch):
    """400 means the request is wrong and 404 means the id is; sending
    either again only wastes the window. The HTTP 400 that cost three
    chain re-runs today was our own malformed history, not a rate limit."""
    import urllib.error

    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    calls = {"n": 0}

    def refuses(self, path, payload, timeout_seconds):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            path, 400, "Bad Request", {}, io.BytesIO(b"malformed")
        )

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(refuses)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    with pytest.raises(urllib.error.HTTPError) as raised:
        client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert raised.value.code == 400
    assert calls["n"] == 1 and waits == [] and client.spent.retried_calls == 0


def test_a_window_that_never_lifts_fails_loudly(monkeypatch):
    import urllib.error

    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    calls = {"n": 0}

    def always_limited(self, path, payload, timeout_seconds):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            path, 503, "Service Unavailable", {}, io.BytesIO(b"down")
        )

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(always_limited)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    with pytest.raises(urllib.error.HTTPError) as raised:
        client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert raised.value.code == 503
    # Bounded: one attempt per backoff step, plus the first.
    assert calls["n"] == len(RETRY_BACKOFF_SECONDS) + 1
    assert waits == list(RETRY_BACKOFF_SECONDS)
    assert sum(RETRY_BACKOFF_SECONDS) == 155  # the measured budget


def test_an_exhausted_credit_lane_is_not_retried(monkeypatch):
    """Measured 2026-09-11 (OT-37, third set): from 15:20 CDT Ollama cloud
    answered every call 429 with "usage credits auto reload monthly max
    reached", six instances in a row each burned the full backoff, and
    the roll went on. That 429 is not "not now" — nothing but the user
    adding credits changes it — so it is raised at once with its body."""
    import urllib.error

    from blended.agent.loop import EXHAUSTED_CREDITS_SIGNATURE, exhausted_credits_error

    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    calls = {"n": 0}
    body = b'{"error":"usage credits auto reload monthly max reached, increase your monthly max"}'

    def out_of_credits(self, path, payload, timeout_seconds):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            path, 429, "Too Many Requests", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(out_of_credits)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    with pytest.raises(urllib.error.HTTPError) as raised:
        client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert raised.value.code == 429
    assert calls["n"] == 1 and waits == [] and client.spent.retried_calls == 0
    # The body was read to decide; it is handed on so the caller can say why.
    assert EXHAUSTED_CREDITS_SIGNATURE in raised.value.read().decode("utf-8")
    assert exhausted_credits_error(body.decode("utf-8"))
    assert not exhausted_credits_error("rate limited")


# --- the transport saying "not now" is the same case (OT-37, roll 2) ---


def test_a_socket_timeout_on_open_is_retried_then_succeeds(monkeypatch):
    """Measured 2026-09-11: four of twenty first calls in one bench roll
    died with a raw `TimeoutError: timed out` from `_read_status` —
    no status line in 300 s on a lane that generates a worst legal
    reply in ~85 s — and were raised with zero retries because the
    retry caught HTTPError alone. The roll finished 16/20; the set was
    void. A stalled connection is "not now" exactly as a 503 is."""
    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    attempts = {"n": 0}

    def stalls_twice(self, path, payload, timeout_seconds):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise TimeoutError("timed out")
        return {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(stalls_twice)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    body = client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert body["choices"][0]["message"]["content"] == "pong"
    assert waits == list(RETRY_BACKOFF_SECONDS[:2])
    assert client.spent.retried_calls == 2  # costed, like every retry


def test_a_connection_that_never_answers_fails_loudly(monkeypatch):
    """The same bound as a window that never lifts: one attempt per
    backoff step plus the first, then the error as it stands — a
    `URLError` here, the shape urlopen gives a refused connection."""
    import urllib.error

    waits = []
    monkeypatch.setattr("blended.agent.loop.time.sleep", lambda s: waits.append(s))
    calls = {"n": 0}

    def refused(self, path, payload, timeout_seconds):
        calls["n"] += 1
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(
        OllamaClient, "_build_request", lambda self, path, payload: path
    )
    monkeypatch.setattr(
        "blended.agent.loop.urllib.request.urlopen", _urlopen_from(refused)
    )
    client = OllamaClient(_metered_config(context_length=METERED_WINDOW))

    with pytest.raises(urllib.error.URLError):
        client._request("/v1/chat/completions", {"model": "m"}, 60)

    assert calls["n"] == len(RETRY_BACKOFF_SECONDS) + 1
    assert waits == list(RETRY_BACKOFF_SECONDS)
    assert client.spent.retried_calls == len(RETRY_BACKOFF_SECONDS)


def test_the_completion_reservation_comes_from_the_provider_bounded(monkeypatch):
    """Measured 2026-09-10: the 16,384 default — set for bmb's 27B, where
    4,096 starved it — cut a uv_crate turn on this model, which spends
    79-88 % of its completion tokens reasoning. The provider states what
    it will generate, so take that, bounded: reserving its full 943,717
    would leave ~105k of a 1,048,576 window for the prompt and refuse
    every real conversation."""
    _catalogue(
        monkeypatch,
        [
            {
                "tag": OPENROUTER_PINNED_PROVIDER,
                "context_length": METERED_WINDOW,
                "max_completion_tokens": 943_717,
            }
        ],
    )
    client = OllamaClient(_metered_config(max_completion_tokens=16_384))
    client.check_connection()

    assert (
        client.config.max_completion_tokens
        == MAXIMUM_RESERVED_COMPLETION_TOKENS
        == 65_536
    )
    assert (
        MAXIMUM_RESERVED_COMPLETION_TOKENS == 4 * 16_384
    )  # 4x the ceiling measured to cut
    assert (
        MAXIMUM_RESERVED_COMPLETION_TOKENS < METERED_WINDOW * 0.07
    )  # the prompt keeps the window

    # A provider that publishes a SMALLER ceiling than the bound is believed.
    _catalogue(
        monkeypatch,
        [
            {
                "tag": OPENROUTER_PINNED_PROVIDER,
                "context_length": METERED_WINDOW,
                "max_completion_tokens": 8_192,
            }
        ],
    )
    modest = OllamaClient(_metered_config(max_completion_tokens=16_384))
    modest.check_connection()
    assert modest.config.max_completion_tokens == 8_192

    # A provider that publishes none leaves the configured value alone.
    _catalogue(
        monkeypatch,
        [{"tag": OPENROUTER_PINNED_PROVIDER, "context_length": METERED_WINDOW}],
    )
    silent = OllamaClient(_metered_config(max_completion_tokens=16_384))
    silent.check_connection()
    assert silent.config.max_completion_tokens == 16_384
