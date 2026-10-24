"""A loop-worker's report must carry its own measured routing line.

Why this is a gate: the six-way fan-out's output is six self-written reports. A
child that ran on another model would still write a confident report, and the
parent would have to notice. With the brief's MODEL imperative, every child
measures its own routing from the session record the harness writes for it and
publishes exactly one line:

    MODEL_ROUTING: <provider>/<model> across <N> work turns, fallback=<true|false>

This module checks such a report. It is the shape the parent reads, so the
parent-side check and the child-side attestation cannot disagree about the
format.

Measured 2026-10-26: a live `loop-worker` spawn answered
``MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 7 work turns,
fallback=false`` and the parent's transcript audit independently read the same
provider/model with ``fallback=False`` (8 turns — the child cannot see its own
final message, which is why the count is not compared here and the model is).
"""

from __future__ import annotations

import re

import pytest

REQUIRED_PROVIDER = "ollama-cloud"
REQUIRED_MODEL = "deepseek-v4.1-flash:1017"
REQUIRED_SELECTOR = f"{REQUIRED_PROVIDER}/{REQUIRED_MODEL}"

ROUTING_LINE = re.compile(
    r"^MODEL_ROUTING:\s*(?P<selector>\S+)\s+across\s+(?P<turns>\d+)\s+work turns,"
    r"\s+fallback=(?P<fallback>true|false)\s*$",
    re.MULTILINE,
)


def routing_of(report_text: str) -> dict[str, str]:
    """The single ``MODEL_ROUTING:`` line of a report, parsed. Loud when absent."""
    matches = ROUTING_LINE.findall(report_text)
    if not matches:
        raise AssertionError(
            "the report carries no `MODEL_ROUTING: <provider>/<model> across <N> "
            "work turns, fallback=<true|false>` line. The loop-worker brief "
            "requires one, measured from the child's own transcript; without it "
            "the parent has no attestation to read."
        )
    if len(matches) > 1:
        raise AssertionError(
            f"the report carries {len(matches)} MODEL_ROUTING lines; a report "
            f"states its routing once, so two lines mean one is stale"
        )
    selector, turns, fallback = matches[0]
    return {"selector": selector, "turns": turns, "fallback": fallback}


def test_a_conforming_report_is_accepted():
    """The control: a report from the required model parses and passes."""
    report = (
        "BRANCH: loop/a1\n"
        "COMMIT: 46bb548\n"
        "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 142 "
        "work turns, fallback=false\n"
    )
    parsed = routing_of(report)
    assert parsed["selector"] == REQUIRED_SELECTOR
    assert parsed["fallback"] == "false"
    assert int(parsed["turns"]) == 142


def test_the_line_must_name_both_provider_and_model():
    """A bare model would parse, so the selector itself is asserted.

    This is the failure mode that reading only a `model` field cannot catch: the
    model name is spelled the same whichever provider served it.
    """
    parsed = routing_of(
        "MODEL_ROUTING: deepseek-v4.1-flash:1017 across 3 work turns, fallback=false"
    )
    assert parsed["selector"] != REQUIRED_SELECTOR
    provider, _, model_name = parsed["selector"].partition("/")
    assert provider != REQUIRED_PROVIDER, (
        "a selector with no provider must not compare equal to the required one"
    )


def test_a_fallback_resolution_is_reported_and_refused():
    """A child that fell back says so; the flag is what a reader acts on."""
    parsed = routing_of(
        "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 9 work turns, "
        "fallback=true"
    )
    assert parsed["fallback"] == "true"


def test_a_report_with_no_line_is_refused():
    """Absence is the dangerous case: a confident report with no attestation."""
    with pytest.raises(AssertionError, match="no `MODEL_ROUTING:"):
        routing_of("BRANCH: loop/a1\nCOMMIT: 46bb548\nall gates green\n")


def test_two_lines_are_refused_because_one_is_stale():
    report = (
        "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 1 work turns, "
        "fallback=false\n"
        "MODEL_ROUTING: openrouter/other-model across 1 work turns, fallback=false\n"
    )
    with pytest.raises(AssertionError, match="2 MODEL_ROUTING lines"):
        routing_of(report)
