"""Pure layer: the ProTeGi prompt search, without a model.

The model calls (`textual_gradient`, `propose_bodies`) are one-line
wrappers over `client.chat`; what needs guarding is the part that
WRITES: a candidate is admissible only if it obeys the repo's own
discipline, and a write that would break the registry must leave the
package byte-identical to how it started.
"""

import shutil
from pathlib import Path

import pytest

from blended.agent import prompt_search, prompt_versions

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKAGE = REPOSITORY_ROOT / "src" / "blended"


def _package_copy(tmp_path: Path) -> Path:
    """A throwaway copy of the whole package, importable in a subprocess."""
    destination = tmp_path / "src" / "blended"
    shutil.copytree(
        SOURCE_PACKAGE,
        destination,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return destination / "agent"


def _latest_body() -> str:
    return prompt_versions.latest_revision().body


def test_a_two_hunk_candidate_is_inadmissible():
    body = _latest_body()
    lines = body.splitlines(keepends=True)
    # Two separate insertions: the LL3M one-element rule's exact failure.
    candidate = (
        "".join(lines[:5])
        + "An inserted sentence near the top.\n"
        + "".join(lines[5:20])
        + "Another inserted sentence far below.\n"
        + "".join(lines[20:])
    )

    reason = prompt_search.admissible(body, candidate, set())

    assert "2 separate places" in reason


def test_a_byte_identical_candidate_is_inadmissible():
    body = _latest_body()

    assert "identical" in prompt_search.admissible(body, body, set())


def test_an_empty_candidate_is_inadmissible():
    assert prompt_search.admissible(_latest_body(), "   \n", set()) == (
        "candidate is empty"
    )


def test_a_one_hunk_candidate_is_admissible():
    body = _latest_body()
    lines = body.splitlines(keepends=True)
    candidate = "".join(lines[:5]) + "One inserted sentence.\n" + "".join(lines[5:])

    assert prompt_search.admissible(body, candidate, set()) == ""


def test_a_previously_rejected_hunk_is_never_re_proposed():
    """The catastrophic-forgetting guard: a hunk that regressed a brief
    must not come back in a later round OR a later session."""
    body = _latest_body()
    lines = body.splitlines(keepends=True)
    candidate = "".join(lines[:5]) + "One inserted sentence.\n" + "".join(lines[5:])
    hunk = prompt_versions.changed_hunks(body, candidate)[0]

    reason = prompt_search.admissible(body, candidate, {hunk})

    assert "rejected in an earlier round" in reason


def test_rejected_hunks_round_trip(tmp_path):
    path = tmp_path / "rejected_hunks.jsonl"
    prompt_search.record_rejection(
        "insert lines 38-38 -> 38-46", "regressed uv_crate", "uv_crate", path
    )
    prompt_search.record_rejection(
        "replace lines 1-2 -> 1-3", "regressed planter_box", "planter_box", path
    )

    assert prompt_search.load_rejected_hunks(path) == {
        "insert lines 38-38 -> 38-46",
        "replace lines 1-2 -> 1-3",
    }


def test_load_rejected_hunks_on_a_missing_file_is_empty(tmp_path):
    assert prompt_search.load_rejected_hunks(tmp_path / "absent.jsonl") == set()


def test_write_revision_produces_a_healthy_registry(tmp_path):
    package = _package_copy(tmp_path)
    body = _latest_body()
    lines = body.splitlines(keepends=True)
    candidate = (
        "".join(lines[:5]) + "One inserted sentence, measured.\n" + "".join(lines[5:])
    )
    expected_revision = prompt_versions.latest_revision().revision + 1

    revision = prompt_search.write_revision(
        candidate,
        "Added one sentence about measuring the named numbers.",
        "Changed X because Y; expect Z.",
        package,
    )

    assert revision == expected_revision
    template = package / "prompts" / f"working_agreement_v{revision}.md.j2"
    assert template.read_text(encoding="utf-8") == candidate
    # The registry the write produced must be healthy on its own terms.
    assert prompt_search._probe_registry(package)["problems"] == []
    assert prompt_search._probe_registry(package)["latest"] == revision
    # The pin and the active revision are NOT moved by a candidate.
    registry = (package / "prompt_versions.py").read_text(encoding="utf-8")
    assert (
        f"PINNED_PROMPT_REVISION = {prompt_versions.PINNED_PROMPT_REVISION}" in registry
    )
    assert "ACTIVE_PROMPT_REVISION = PINNED_PROMPT_REVISION" in registry


def test_a_two_hunk_write_leaves_the_package_untouched(tmp_path):
    """The rollback path: a refused candidate must not leave half an
    edit behind, or the next session starts from a broken registry."""
    package = _package_copy(tmp_path)
    registry_path = package / "prompt_versions.py"
    before = registry_path.read_text(encoding="utf-8")
    templates_before = sorted(path.name for path in (package / "prompts").iterdir())

    body = _latest_body()
    lines = body.splitlines(keepends=True)
    two_hunks = (
        "".join(lines[:5])
        + "First insertion.\n"
        + "".join(lines[5:20])
        + "Second insertion.\n"
        + "".join(lines[20:])
    )

    with pytest.raises(prompt_search.RevisionRejected):
        prompt_search.write_revision(two_hunks, "two places", "expect nothing", package)

    assert registry_path.read_text(encoding="utf-8") == before
    assert sorted(path.name for path in (package / "prompts").iterdir()) == (
        templates_before
    )


def test_record_outcome_fills_the_pending_entry(tmp_path):
    package = _package_copy(tmp_path)
    body = _latest_body()
    lines = body.splitlines(keepends=True)
    candidate = "".join(lines[:5]) + "One inserted sentence.\n" + "".join(lines[5:])
    revision = prompt_search.write_revision(
        candidate, "one sentence", "expect Z", package
    )

    prompt_search.record_outcome(
        revision, "CONFIRMED: uv_crate 3 form failures -> 0.", package
    )

    registry = (package / "prompt_versions.py").read_text(encoding="utf-8")
    assert "CONFIRMED: uv_crate 3 form failures" in registry
    assert prompt_search._probe_registry(package)["problems"] == []


def test_record_outcome_on_a_filled_entry_raises(tmp_path):
    package = _package_copy(tmp_path)

    with pytest.raises(prompt_search.RevisionRejected):
        prompt_search.record_outcome(1, "already measured", package)


def test_gate_evidence_quotes_only_measurements():
    """The gradient must never see the examiner's tags: correction on an
    unverified judgement degrades (10.48550/arXiv.2310.01798)."""
    from blended.evaluate.iteration_log import IterationRecord

    failing = IterationRecord(
        iteration=31,
        brief_name="ribbed_column",
        prompt_identity="v9:abc",
        prompt_revision=9,
        started_at="2026-08-22T00:00:00+00:00",
        tool_calls=("run_python({})", "run_python({})"),
        agent_final_text="Built the column.",
        structural_gate_passed=True,
        form_failures=("rib_crest_is_solid at radius 0.09 read empty",),
        visual_deviations=("no ribs visible at all",),
    )
    passing = IterationRecord(
        iteration=32,
        brief_name="planter_box",
        prompt_identity="v9:abc",
        prompt_revision=9,
        started_at="2026-08-22T00:00:00+00:00",
        structural_gate_passed=True,
        form_gate_passed=True,
    )

    evidence = prompt_search.gate_evidence([failing, passing])

    assert "rib_crest_is_solid at radius 0.09 read empty" in evidence
    assert "ribbed_column" in evidence
    assert "tool calls: 2" in evidence
    # A passing brief contributes no error rows.
    assert "planter_box" not in evidence
    # The examiner's judgement is deliberately absent.
    assert "no ribs visible at all" not in evidence
