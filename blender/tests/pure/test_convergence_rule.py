"""Pure layer: the convergence rule, executed against the real logs.

The predecessor of `converged_suite_cycles` was never executable: it
grouped briefs by iteration NUMBER while the protocol runs one brief
per iteration, so on iterations 47-51 — the cycle that earned the v10
pin — it returned 0, and nothing in the repo ever called it to notice.
These tests read the in-repo logs, which are the evidence the pin rests
on, so the rule is measured against the history it describes.
"""

from dataclasses import replace
from pathlib import Path

from blended.agent import prompt_versions
from blended.evaluate.briefs import BRIEFS
from blended.evaluate.iteration_log import (
    IterationLog,
    IterationRecord,
    IterationVerdict,
    VerdictLog,
    clean_cycle_for_identity,
    converged_suite_cycles,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ITERATION_LOG = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"
VERDICT_LOG = REPOSITORY_ROOT / "_evaluate" / "verdicts.jsonl"
PINNED_IDENTITY = "v10:b6627b38f4c1"


def test_the_v10_cycle_is_one_converged_cycle():
    """Iterations 47-51: one clean run per brief, consecutive, no prompt
    change between them. That IS the rule the v10 pin claims to have
    met, so the rule must say so.

    Evaluated over the history that PRODUCED the pin, not over the whole
    log. `converged_suite_cycles` reports TRAILING cycles, so a later
    convergence attempt legitimately becomes the newest cycle and this
    assertion would go red for the honest reason that someone tried the
    next revision (measured 2026-09-05, when the v11 attempt on the
    Claude Code lane halted). The claim being pinned here is about the
    v10 cycle's own evidence, so the slice is part of the claim.
    """
    last_pinned_iteration = max(
        iteration for iteration, _ in prompt_versions.CONVERGENCE_RUNS
    )
    records = [
        record
        for record in IterationLog(ITERATION_LOG).records()
        if record.iteration <= last_pinned_iteration
    ]
    verdicts = VerdictLog(VERDICT_LOG).verdicts()

    cycles, identity = converged_suite_cycles(records, tuple(sorted(BRIEFS)), verdicts)

    assert cycles >= 1, (
        "the recorded v10 cycle (iterations 47-51) must count as converged"
    )
    assert identity == PINNED_IDENTITY


def _clean_record(iteration: int, brief_name: str, identity: str) -> IterationRecord:
    return IterationRecord(
        iteration=iteration,
        brief_name=brief_name,
        prompt_identity=identity,
        prompt_revision=10,
        started_at="2026-08-22T00:00:00+00:00",
        structural_gate_passed=True,
        form_gate_passed=True,
        refinement_gate_passed=True,
    )


def _clean_verdict(iteration: int, brief_name: str) -> IterationVerdict:
    return IterationVerdict(
        iteration=iteration,
        brief_name=brief_name,
        visual_inspected=True,
    )


def test_a_cycle_that_mixes_prompt_identities_is_not_a_cycle():
    """A cycle spanning two identities would attribute one claim to two
    texts."""
    names = ("alpha", "beta", "gamma")
    identities = (
        "v10:b6627b38f4c1",
        "v10:b6627b38f4c1",
        "v11:0000deadbeef",
    )
    records = [
        _clean_record(iteration, name, identity)
        for iteration, (name, identity) in enumerate(zip(names, identities), start=1)
    ]
    verdicts = [
        _clean_verdict(iteration, name) for iteration, name in enumerate(names, start=1)
    ]

    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_an_abstention_is_not_a_clean_cycle():
    """An instrument that could not answer has not signed anything off."""
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            examiner="m+examiner:abc",
            abstained=True,
            calibration_identity="0123456789ab",
        ),
        _clean_verdict(2, "beta"),
    ]

    cycles, _ = converged_suite_cycles(records, names, verdicts)
    assert cycles == 0


def test_a_deviation_is_not_a_clean_cycle():
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            visual_deviations=("missing_part",),
        ),
        _clean_verdict(2, "beta"),
    ]

    # A cycle that is not converged reports no identity: the count is
    # the claim, and there is no converged cycle to name.
    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_an_unexamined_run_is_not_a_clean_cycle():
    """A run nobody examined is a pass with no evidence, not a pass."""
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [_clean_verdict(1, "alpha")]

    assert converged_suite_cycles(records, names, verdicts) == (0, "")


def test_a_prompt_change_ends_the_cycle_it_appears_in():
    names = ("alpha", "beta")
    records = [_clean_record(1, "alpha", "v10:x"), _clean_record(2, "beta", "v10:x")]
    verdicts = [
        IterationVerdict(
            iteration=1,
            brief_name="alpha",
            visual_inspected=True,
            prompt_change="v10 -> v11: one sentence",
        ),
        _clean_verdict(2, "beta"),
    ]

    cycles, _ = converged_suite_cycles(records, names, verdicts)
    assert cycles == 0


def test_two_clean_cycles_count_as_two():
    names = ("alpha", "beta")
    records = [
        _clean_record(1, "alpha", "v10:x"),
        _clean_record(2, "beta", "v10:x"),
        _clean_record(3, "alpha", "v10:x"),
        _clean_record(4, "beta", "v10:x"),
    ]
    verdicts = [
        _clean_verdict(1, "alpha"),
        _clean_verdict(2, "beta"),
        _clean_verdict(3, "alpha"),
        _clean_verdict(4, "beta"),
    ]

    assert converged_suite_cycles(records, names, verdicts) == (2, "v10:x")


def test_an_incomplete_trailing_cycle_does_not_count():
    """Four of five briefs run is not a suite cycle."""
    names = ("alpha", "beta")
    records = [
        _clean_record(1, "alpha", "v10:x"),
        _clean_record(2, "beta", "v10:x"),
        _clean_record(3, "alpha", "v10:x"),
    ]
    verdicts = [
        _clean_verdict(1, "alpha"),
        _clean_verdict(2, "beta"),
        _clean_verdict(3, "alpha"),
    ]

    # The newest complete cycle is (3:alpha, 2:beta) — the partial
    # trailing run of alpha is absorbed into it, and 1:alpha is left
    # over as an incomplete cycle that is never counted.
    assert converged_suite_cycles(records, names, verdicts) == (1, "v10:x")


def test_only_runs_that_executed_a_revision_may_mint_its_reference():
    """The rule that broke the pin loop's ability to advance.

    `pin_golden_views` used to source its runs from
    `CONVERGENCE_RUNS` — the PINNED revision's runs — and then refuse
    them for having executed the pinned text. That can only ever
    succeed for the revision already pinned, so a candidate could
    never be given a reference and could never be pinned. The source
    must be the log, scoped to the identity being stamped.
    """
    names = ("alpha", "beta")
    candidate, incumbent = "v11:new", "v10:old"
    stale = _clean_record(1, "alpha", incumbent)
    early = _clean_record(2, "alpha", candidate)
    newest = _clean_record(4, "alpha", candidate)
    other_brief = _clean_record(3, "beta", candidate)
    failed = IterationRecord(
        iteration=5,
        brief_name="beta",
        prompt_identity=candidate,
        prompt_revision=11,
        started_at="2026-09-05T00:00:00+00:00",
        structural_gate_passed=True,
        form_gate_passed=False,
        refinement_gate_passed=True,
    )
    records = [stale, early, newest, other_brief, failed]

    chosen = clean_cycle_for_identity(records, names, candidate)
    # Newest clean run per brief AT THIS IDENTITY: iteration 4 for
    # alpha (not 2, and never 1, which ran the incumbent text), and 3
    # for beta — 5 is newer but failed a deterministic gate, and a
    # reference minted from a failing run would pin the defect.
    assert chosen == {"alpha": 4, "beta": 3}

    # The incumbent's own reference is still mintable from its own runs.
    assert clean_cycle_for_identity(records, names, incumbent) == {"alpha": 1}

    # A revision nothing ran gets nothing — the caller refuses loudly
    # rather than stamping someone else's geometry with its name.
    assert clean_cycle_for_identity(records, names, "v12:absent") == {}


def test_the_preflight_refuses_an_examiner_that_flags_clean_runs(monkeypatch):
    """The route, not just the number.

    `Calibration.problems()` reporting a cross-run miss is worth
    nothing if the loop's preflight does not consult it. Measured
    2026-09-06: with cross-run specificity 0.75 on disk,
    `converge_auto.py` printed "PREFLIGHT REFUSED … cross-run control
    specificity 0.75 < 1.0" and exited 2 without spending a token.
    This pins that wiring so a future licence field cannot be added to
    `problems()` and silently bypass the gate.
    """
    import importlib.util
    import sys
    from types import SimpleNamespace

    from blended.evaluate import examiner as examiner_module

    specification = importlib.util.spec_from_file_location(
        "converge_auto_under_test",
        Path(__file__).resolve().parents[2] / "scripts" / "converge_auto.py",
    )
    module = importlib.util.module_from_spec(specification)
    monkeypatch.setitem(sys.modules, specification.name, module)
    specification.loader.exec_module(module)

    unlicensed = examiner_module.Calibration(
        examiner_identity="eye+examiner:deadbeef1234",
        vision_model="eye",
        recorded_at="2026-09-06T00:00:00+00:00",
        view_names=examiner_module.EXAMINED_VIEW_NAMES,
        sensitivity=1.0,
        control_specificity=1.0,
        cross_run_control_specificity=0.75,
    )
    monkeypatch.setattr(examiner_module, "load_calibration", lambda *a, **k: unlicensed)
    monkeypatch.setattr(
        examiner_module, "examiner_identity", lambda model: unlicensed.examiner_identity
    )
    # Everything else the preflight touches, stubbed to "fine": the
    # examiner licence must be the ONLY reason it refuses here.
    monkeypatch.setattr(
        module,
        "_client",
        lambda *a, **k: SimpleNamespace(
            config=SimpleNamespace(
                vision_model="eye",
                eye_config=lambda: SimpleNamespace(vision_model="eye"),
            ),
            check_connection=lambda: SimpleNamespace(ok=True, detail=""),
        ),
    )
    monkeypatch.setattr(examiner_module, "verify_golden_manifest", lambda *a: "v11:x")

    arguments = SimpleNamespace(
        revision=prompt_versions.latest_revision().revision,
        model="writer",
        vision_model="eye",
    )
    problems = module.preflight(arguments, ())
    cross_run = [p for p in problems if "cross-run control specificity" in p]
    assert cross_run, problems
    assert cross_run[0].startswith("examiner: ")

    # Non-vacuity: the SAME preflight, the same stubs, a licensed
    # cross-run number — and the refusal disappears. Without this the
    # test would still pass if the preflight refused for any reason at
    # all.
    licensed = replace(unlicensed, cross_run_control_specificity=1.0)
    monkeypatch.setattr(examiner_module, "load_calibration", lambda *a, **k: licensed)
    assert not [
        problem
        for problem in module.preflight(arguments, ())
        if "cross-run control specificity" in problem
    ]
