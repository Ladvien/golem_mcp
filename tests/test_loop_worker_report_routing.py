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


def _load_audit_module():
    """Import `scripts/audit_task_child_models.py` by path.

    `scripts/` is not a package and the root suite's `pythonpath` is only
    `["src"]`, so `import scripts.audit_task_child_models` fails under
    `make test-golem`. Loading by path keeps the test honest about the script's
    real location without adding a package marker to a bin-style directory.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "audit_task_child_models.py"
    spec = importlib.util.spec_from_file_location("_audit_task_child_models", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the audit's SWEEP must not narrow ------------------------------------


def test_the_audit_sweeps_every_child_and_not_a_name_pattern(tmp_path):
    """A default sweep that matched only `loop-a*` covered 6 of 17 children.

    Measured 2026-10-26: the session held 17 child transcripts (`loop-a1..6`,
    `conc-a1..6`, four probes and a self-attest) while the default run reported
    PASS having read only the six `loop-a*`. A narrow default is the worst kind
    of audit bug: it prints PASS for a population it never looked at. This test
    pins the sweep to every child transcript in the directory.
    """
    audit_main = _load_audit_module().main

    for stem in ("loop-a1", "conc-a1", "probe-x", "self-attest"):
        (tmp_path / f"{stem}.jsonl").write_text(
            '{"type":"session_init","resolvedModel":'
            '"ollama-cloud/deepseek-v4.1-flash:1017"}\n'
            '{"type":"model_change","model":'
            '"ollama-cloud/deepseek-v4.1-flash:1017",'
            '"resolvedModelIsFallback":false}\n'
            '{"type":"message","message":{"role":"assistant",'
            '"provider":"ollama-cloud","model":"deepseek-v4.1-flash:1017"}}\n'
        )
    # The parent session's own transcript is not a child and must be skipped.
    (tmp_path / "2026-10-24T20-06-15-291Z_parent.jsonl").write_text("{}\n")

    code = audit_main(["--dir", str(tmp_path), "--json"])
    assert code == 0, "a directory of conforming children must pass"

    names = {path.stem for path in tmp_path.glob("*.jsonl")}
    assert {"loop-a1", "conc-a1", "probe-x", "self-attest"} <= names


def test_an_off_pin_child_fails_the_default_sweep(tmp_path, capsys):
    """Drift anywhere in the directory fails, not just drift in `loop-a*`."""
    audit_main = _load_audit_module().main

    good = (
        '{"type":"session_init","resolvedModel":'
        '"ollama-cloud/deepseek-v4.1-flash:1017"}\n'
        '{"type":"message","message":{"role":"assistant",'
        '"provider":"ollama-cloud","model":"deepseek-v4.1-flash:1017"}}\n'
    )
    drifted = (
        '{"type":"session_init","resolvedModel":"anthropic/claude-sonnet-5-5"}\n'
        '{"type":"message","message":{"role":"assistant",'
        '"provider":"anthropic","model":"claude-sonnet-5-5"}}\n'
    )
    (tmp_path / "loop-a1.jsonl").write_text(good)
    (tmp_path / "conc-a9.jsonl").write_text(drifted)

    assert audit_main(["--dir", str(tmp_path)]) == 1
    assert "conc-a9" in capsys.readouterr().out


def test_a_deliberate_discriminator_can_be_excused_but_is_named(tmp_path, capsys):
    """The only legal off-pin child is one spawned on purpose to prove routing."""
    audit_main = _load_audit_module().main

    (tmp_path / "probe-retired.jsonl").write_text(
        '{"type":"session_init","resolvedModel":'
        '"ollama-cloud/deepseek-v4-flash"}\n'
        '{"type":"message","message":{"role":"assistant",'
        '"provider":"ollama-cloud","model":"deepseek-v4-flash"}}\n'
    )

    assert audit_main(["--dir", str(tmp_path)]) == 1
    assert audit_main(
        ["--dir", str(tmp_path), "--allow-off-pin", "probe-retired"]
    ) == 0
    output = capsys.readouterr().out
    assert "NOTE excused as a deliberate discriminator: probe-retired" in output


def assert_report_complies(report_text: str) -> dict[str, str]:
    """The parent's acceptance predicate: one line, right selector, no fallback.

    Separated from the parser because parsing and ACCEPTING are different
    questions, and conflating them is how a sloppy attestation passes. Measured
    2026-10-26: a live `task` child reported
    ``ollama-cloud/deepseek-v4.1-flash`` — the required provider and model but
    WITHOUT the ``:1017`` tag — while its transcript said
    ``ollama-cloud/deepseek-v4.1-flash:1017`` on all 9 work turns. Routing was
    correct; the attestation was not. A gate that accepted the untagged string
    would let a genuinely different model tag through beside it.
    """
    parsed = routing_of(report_text)
    if parsed["selector"] != REQUIRED_SELECTOR:
        raise AssertionError(
            f"the report attests {parsed['selector']!r}, not the required "
            f"{REQUIRED_SELECTOR!r}. The provider AND the model tag are part of "
            f"the requirement: `deepseek-v4.1-flash` and "
            f"`deepseek-v4.1-flash:1017` are different models."
        )
    if parsed["fallback"] != "false":
        raise AssertionError(
            f"the report attests fallback={parsed['fallback']}; a child that "
            f"resolved through a fallback did not run on the required model"
        )
    return parsed


def test_a_wrong_model_tag_is_refused_even_when_the_provider_is_right():
    """The real sloppy line from this run: right provider, missing `:1017`."""
    untagged = (
        "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash across 9 work turns, "
        "fallback=false"
    )
    # It PARSES ...
    assert routing_of(untagged)["selector"] == "ollama-cloud/deepseek-v4.1-flash"
    # ... and must still be REFUSED.
    with pytest.raises(AssertionError, match="different models"):
        assert_report_complies(untagged)


def test_a_true_fallback_is_refused_by_the_acceptance_predicate():
    with pytest.raises(AssertionError, match="did not run on the required model"):
        assert_report_complies(
            "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 3 "
            "work turns, fallback=true"
        )


def test_a_fully_conforming_report_is_accepted():
    parsed = assert_report_complies(
        "MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 142 "
        "work turns, fallback=false"
    )
    assert parsed["selector"] == REQUIRED_SELECTOR
