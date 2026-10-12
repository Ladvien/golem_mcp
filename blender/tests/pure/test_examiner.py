"""Pure layer: the structured examiner, with a stub eye (no network).

The examiner is the instrument that replaces the human verdict in the
convergence loop, so its tests pin the three failure modes that would
silently corrupt the loop if they regressed:

- Defect 1's exact shape: a denial ("I don't see any missing...") must
  score as NO deviation, not as a sighting — the old scorer counted it
  as both (see mistake memory
  "the-eye-scorer-counted-a-denial-as-a-sighting").
- Order-consistency: a tag seen in only one image order is dropped
  (MT-bench position-bias mitigation, 10.48550/arXiv.2306.05685).
- The closed vocabulary: a tag outside the list, or prose instead of
  JSON, is a loud failure, never a best-effort guess.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from blended.evaluate.examiner import (
    CANNOT_TELL_TAG,
    Calibration,
    ExaminerReplyUnparseable,
    GoldenReferenceMismatch,
    GoldenViewMissing,
    UnknownDeviationTag,
    examine_asset,
    examiner_identity,
    parse_tags,
)

VIEWS = ("front", "right", "top", "bottom", "three_quarter")
NO_DEVIATION = '{"reasoning": "Same asset.", "tags": ["no_deviation"]}'


def _write_png(path: Path, payload: bytes = b"png-bytes") -> Path:
    path.write_bytes(payload)
    return path


def _golden_directory(base: Path, brief_name: str = "three_leg_stool") -> Path:
    golden = base / "golden"
    golden.mkdir()
    manifest = {
        "brief": brief_name,
        "iteration": 47,
        "revision": 10,
        "prompt_identity": "v10:b6627b38f4c1",
        "blender_series": "5.2",
        "captured_at": "2026-08-22T00:00:00+00:00",
    }
    (golden / "manifest.json").write_text(json.dumps(manifest))
    for view in VIEWS:
        _write_png(golden / f"{view}.png")
    manifest["view_sha256"] = {
        view: hashlib.sha256((golden / f"{view}.png").read_bytes()).hexdigest()
        for view in VIEWS
    }
    (golden / "manifest.json").write_text(json.dumps(manifest))
    return golden


def _render_directory(base: Path) -> Path:
    renders = base / "renders"
    renders.mkdir()
    for view in VIEWS:
        _write_png(renders / f"{view}.png")
    return renders


@dataclass
class StubEye:
    """One canned reply per describe call, in call order."""

    replies: list[str]

    def describe(self, image_paths, question="", prompt=""):
        return self.replies.pop(0)


class _Brief:
    name = "three_leg_stool"


def _clean_replies(extra: list[str]) -> list[str]:
    """The nine no_deviation replies for the other views, plus `extra`
    for the first view's two orders."""
    return extra + [NO_DEVIATION] * 8


def test_a_denial_is_not_a_deviation(tmp_path):
    """Defect 1's guard: 'I don't see any missing, misplaced, floating,
    or duplicated parts' scored as a false positive in the old scorer.
    The closed-vocabulary reply with no_deviation must yield zero
    deviations."""
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        (
            '{"reasoning": "I don\'t see any missing, misplaced, floating, or '
            'duplicated parts.", "tags": ["no_deviation"]}'
        ),
        NO_DEVIATION,
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ()
    assert verdict.abstained is False
    assert not replies, "the stub must have answered every call"


def test_a_tag_seen_in_one_order_only_is_dropped(tmp_path):
    """Position-bias mitigation: offset_part seen in one order and
    no_deviation in the other must NOT survive the intersection."""
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        '{"reasoning": "seat shifted", "tags": ["offset_part"]}',
        NO_DEVIATION,
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ()
    assert verdict.views[0].reference_first_tags == ("offset_part",)


def test_a_tag_consistent_across_orders_is_reported(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        '{"reasoning": "leg missing", "tags": ["missing_part"]}',
        '{"reasoning": "leg missing", "tags": ["missing_part"]}',
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.deviations == ("missing_part",)


def test_unknown_tag_raises():
    with pytest.raises(UnknownDeviationTag):
        parse_tags('{"reasoning": "r", "tags": ["invented_tag"]}')


def test_prose_reply_raises():
    with pytest.raises(ExaminerReplyUnparseable):
        parse_tags("The asset looks fine, no problems at all.")


def test_missing_reasoning_raises():
    with pytest.raises(ExaminerReplyUnparseable):
        parse_tags('{"tags": ["no_deviation"]}')


def test_cannot_tell_sets_abstained(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    replies = [
        f'{{"reasoning": "cannot judge", "tags": ["{CANNOT_TELL_TAG}"]}}',
        f'{{"reasoning": "cannot judge", "tags": ["{CANNOT_TELL_TAG}"]}}',
    ] + [NO_DEVIATION] * 8
    verdict = examine_asset(StubEye(replies), golden, renders, _Brief(), "stub-model")
    assert verdict.abstained is True
    assert verdict.deviations == ()


def test_missing_golden_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (golden / "bottom.png").unlink()
    with pytest.raises(GoldenViewMissing):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_missing_test_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (renders / "top.png").unlink()
    with pytest.raises(GoldenViewMissing):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_wrong_brief_golden_raises(tmp_path):
    golden = _golden_directory(tmp_path, brief_name="planter_box")
    renders = _render_directory(tmp_path)
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_drifted_golden_view_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    renders = _render_directory(tmp_path)
    (golden / "front.png").write_bytes(b"different-bytes")
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_missing_manifest_raises(tmp_path):
    golden = _golden_directory(tmp_path)
    (golden / "manifest.json").unlink()
    renders = _render_directory(tmp_path)
    with pytest.raises(GoldenReferenceMismatch):
        examine_asset(StubEye([]), golden, renders, _Brief(), "stub-model")


def test_examiner_identity_changes_with_the_model():
    assert examiner_identity("model-a") != examiner_identity("model-b")
    assert examiner_identity("minimax-m3:cloud").startswith(
        "minimax-m3:cloud+examiner:"
    )


def test_calibration_problems_are_loud():
    calibration = Calibration(
        examiner_identity="some-model+examiner:deadbeef",
        vision_model="some-model",
        recorded_at="2026-08-22T00:00:00+00:00",
        view_names=("front",),
        sensitivity=0.4,
        control_specificity=1.0,
    )
    problems = calibration.problems("other-model+examiner:cafebabe")
    assert any("calibration is for" in problem for problem in problems)
    assert any("sensitivity" in problem for problem in problems)

    clean = Calibration(
        examiner_identity="m+examiner:abc",
        vision_model="m",
        recorded_at="2026-08-22T00:00:00+00:00",
        view_names=("front",),
        sensitivity=1.0,
        control_specificity=1.0,
    )
    assert clean.problems("m+examiner:abc") == []


def test_missing_calibration_file_is_a_problem(tmp_path):
    calibration = Calibration.missing()
    assert calibration.problems("anything") != []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MEASURED, not broken: cross-run control specificity is 0.75 "
        "(3/4) against a required 1.0, so this examiner is NOT "
        "licensed for the regime the loop uses and converge_auto "
        "correctly refuses to gate on it. B2' (restricting the eye to "
        "vision-only defects) moved the number from 0.50 to 0.75 and "
        "did not reach the threshold: the residual leak is geometric "
        "variation the brief leaves free — the exemplar stool's legs "
        "are roughly seat-thickness in diameter, the clean candidate's "
        "are 15-20% of seat diameter with a visible gap at the rear "
        "leg junction, both gate-clean. Remove this marker when the "
        "Phase B decision lands "
        "(docs/2026-09-06-token-budget-plan.md)."
    ),
)
def test_the_shipped_eye_holds_the_licence_in_the_repository():
    """The default eye must be the one the calibration file licenses.

    The licence is identity-bound, so changing the default eye without
    re-running `make calibrate-eye` does not fail loudly — it makes
    every machine verdict refuse at preflight, which reads as "the
    harness is broken" rather than "the eye was swapped". Shipping an
    eye the repository cannot license is the failure this pins.
    """
    from blended.agent.loop import ModelConfig
    from blended.evaluate.examiner import load_calibration

    shipped_eye = ModelConfig().vision_model
    calibration = load_calibration()
    assert calibration.problems(examiner_identity(shipped_eye)) == [], (
        f"the shipped eye {shipped_eye!r} is not the one "
        f"_evaluate/eye_calibration.json licenses "
        f"({calibration.examiner_identity!r}) — re-run "
        f"`make calibrate-eye` for the new eye, or ship the calibrated one"
    )


def test_the_licence_identity_still_matches_the_shipped_eye():
    """The eye and its licence must at least be the same instrument.

    Separated from the threshold check above so the two failures cannot
    be confused: a THRESHOLD miss is a measurement about the eye's
    reliability, while an IDENTITY mismatch means nobody measured THIS
    eye at all. The second is always a bug.
    """
    from blended.agent.loop import ModelConfig
    from blended.evaluate.examiner import load_calibration

    calibration = load_calibration()
    assert not calibration.absent
    assert calibration.examiner_identity == examiner_identity(
        ModelConfig().vision_model
    ), "the calibration on disk is for a different eye or a different prompt"


def test_a_licence_measured_on_identical_images_does_not_cover_a_fresh_run():
    """Cross-run specificity is reported, and a miss disqualifies.

    The same-run controls compare a run against the reference minted
    from ITSELF, so `control_specificity` 1.00 measures "stays quiet
    when shown the same image twice". The loop only ever compares a
    FRESH run against an exemplar. Measured 2026-09-05: planter_box
    iteration 62 was flagged `material_missing` against an exemplar
    minted from its own lane's clean iteration 57, so the false-alarm
    rate in the used regime is not zero and must be licensed
    separately.
    """
    from blended.evaluate.examiner import (
        CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY,
        Calibration,
    )

    identity = "claude-code:sonnet+examiner:60a9920cb938"
    perfect_same_run = Calibration(
        examiner_identity=identity,
        vision_model="claude-code:sonnet",
        recorded_at="2026-09-05T00:00:00+00:00",
        view_names=("front",),
        sensitivity=0.8,
        control_specificity=1.0,
    )
    # Not measured yet is NOT a failure: the shipped licence predates
    # the measurement and the log is append-only.
    assert perfect_same_run.cross_run_control_specificity is None
    assert perfect_same_run.problems(identity) == []

    flags_clean_runs = replace(
        perfect_same_run,
        cross_run_control_specificity=CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY - 0.25,
    )
    problems = flags_clean_runs.problems(identity)
    assert len(problems) == 1
    assert "cross-run control specificity" in problems[0]
    assert "only regime the loop uses" in problems[0]

    licensed = replace(
        perfect_same_run,
        cross_run_control_specificity=CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY,
    )
    assert licensed.problems(identity) == []


def test_a_verdict_records_which_view_earned_its_tags():
    """Per-view tags, because a view that never tags is two calls for
    nothing.

    Examination is the loop's largest token consumer (10 eye calls per
    brief against 26 for the whole build, measured 2026-09-06), and the
    aggregate deviation list cannot say which of the five views paid
    for itself.
    """
    from blended.evaluate.iteration_log import IterationVerdict

    verdict = IterationVerdict(
        iteration=900,
        brief_name="planter_box",
        visual_inspected=True,
        visual_deviations=("material_missing",),
        examiner="claude-code:sonnet+examiner:60a9920cb938",
        calibration_identity="9bcc4d728d0d",
        view_tags=(
            ("front", ("material_missing",)),
            ("bottom", ()),
        ),
    )
    assert dict(verdict.view_tags)["bottom"] == ()
    assert dict(verdict.view_tags)["front"] == ("material_missing",)
    # An older row carries none, and that must not read as "no tags".
    older = IterationVerdict(
        iteration=1, brief_name="planter_box", visual_inspected=True
    )
    assert older.view_tags == ()


def test_a_tag_a_gate_owns_is_recorded_but_never_halts():
    """B2': the eye judges only what a measurement cannot see.

    Measured 2026-09-06: cross-run control specificity was 0.50 and
    BOTH false alarms were TRUE observations of variation the brief
    leaves free (planter_box exemplar base colour (0.45, 0.28, 0.15) vs
    the flagged clean candidate's (0.35, 0.22, 0.12), identical
    dimensions). `wrong_proportion` is owned by the form gate and
    `material_missing` by the material gate, so they are advisory
    evidence and cannot halt a cycle.
    """
    from blended.evaluate.examiner import (
        DEVIATION_TAGS,
        HALTING_DEVIATION_TAGS,
        MEASURED_DEVIATION_TAGS,
        AssetVerdict,
        ViewVerdict,
    )

    assert set(MEASURED_DEVIATION_TAGS) == {"wrong_proportion", "material_missing"}
    assert not set(HALTING_DEVIATION_TAGS) & set(MEASURED_DEVIATION_TAGS)
    # Every tag is accounted for: the split partitions the vocabulary,
    # so no tag can go missing when one moves.
    assert set(HALTING_DEVIATION_TAGS) | set(MEASURED_DEVIATION_TAGS) == set(
        DEVIATION_TAGS
    )
    # A defect no measurement models keeps its authority.
    assert "missing_feature" in HALTING_DEVIATION_TAGS

    verdict = AssetVerdict(
        brief_name="planter_box",
        examiner_identity="eye+examiner:abc123456789",
        golden_identity="v11:d90e5ee9e59d",
        views=(
            ViewVerdict(
                view_name="front",
                reference_first_tags=("material_missing", "missing_part"),
                test_first_tags=("material_missing", "missing_part"),
                order_consistent_tags=("material_missing", "missing_part"),
                reference_first_reasoning="",
                test_first_reasoning="",
            ),
        ),
        deviations=("missing_part",),
        abstained=False,
        measured_property_reports=("material_missing",),
    )
    assert verdict.deviations == ("missing_part",)
    assert verdict.measured_property_reports == ("material_missing",)
    assert "advisory (a gate owns these)" in verdict.summary()
