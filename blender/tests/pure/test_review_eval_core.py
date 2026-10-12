"""Regression tests for the eval_core review (2026-10-07).

Each test pins a MEASURED failure of the code before the fix; none of
them restates a constant or a docstring.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from blended.evaluate.acceptance import (
    AcceptanceReport,
    DimensionMeasurement,
    GroundContactMeasurement,
    PartReport,
    RefinementOutcome,
    signed_angle_difference_deg,
)
from blended.evaluate.briefs import (
    AssetBrief,
    DimensionSpec,
    GroundContactProbe,
    PartSpec,
    RefinementStep,
)
from blended.evaluate.examiner import (
    EXAMINED_VIEW_NAMES,
    GoldenReferenceMismatch,
    parse_tags,
    verify_golden_manifest,
)
from blended.evaluate.iteration_log import (
    IterationLog,
    IterationRecord,
    IterationVerdict,
    VerdictLog,
)

# --- examiner: a brace inside a JSON string is not an object boundary ----


@pytest.mark.parametrize(
    "reasoning",
    [
        "the handle {left} is gone }",  # balanced pair then a stray close
        "a { b",  # an open brace that never closes inside the string
    ],
)
def test_a_brace_inside_the_reasoning_string_does_not_reject_a_valid_reply(
    reasoning,
):
    reply = json.dumps({"reasoning": reasoning, "tags": ["missing_part"]})
    assert parse_tags(reply) == ("missing_part",)


def test_prose_before_the_object_still_parses():
    reply = 'Here you go: {"reasoning": "ok", "tags": ["no_deviation"]} done'
    assert parse_tags(reply) == ("no_deviation",)


# --- examiner: every examined view must be pinned by the manifest -------


def _golden_manifest(tmp_path: Path, pinned_views: tuple[str, ...]) -> Path:
    golden = tmp_path / "golden"
    golden.mkdir()
    hashes = {}
    for view in EXAMINED_VIEW_NAMES:
        (golden / f"{view}.png").write_bytes(f"bytes-{view}".encode())
    for view in pinned_views:
        hashes[view] = hashlib.sha256((golden / f"{view}.png").read_bytes()).hexdigest()
    (golden / "manifest.json").write_text(
        json.dumps({"brief": "b", "prompt_identity": "v1:x", "view_sha256": hashes})
    )
    return golden


def test_a_manifest_that_pins_every_examined_view_verifies(tmp_path):
    golden = _golden_manifest(tmp_path, EXAMINED_VIEW_NAMES)
    assert verify_golden_manifest(golden, "b") == "v1:x"


def test_a_view_the_manifest_does_not_pin_is_refused(tmp_path):
    # `bottom` is on disk and would be shown to the eye, but nothing
    # would notice if it drifted.
    pinned = tuple(view for view in EXAMINED_VIEW_NAMES if view != "bottom")
    golden = _golden_manifest(tmp_path, pinned)
    with pytest.raises(GoldenReferenceMismatch, match="bottom"):
        verify_golden_manifest(golden, "b")


# --- iteration log: a reloaded line has the declared tuple types --------


def test_a_reloaded_iteration_record_has_tuple_fields(tmp_path):
    log = IterationLog(tmp_path / "iterations.jsonl")
    log.append(
        IterationRecord(
            iteration=1,
            brief_name="planter_box",
            prompt_identity="v1:x",
            prompt_revision=1,
            started_at="2026-10-07T00:00:00+00:00",
            tool_calls=("run_python", "render_views"),
            structural_failures=("not manifold",),
            visual_deviations=("missing_feature",),
        )
    )
    (record,) = log.records()
    assert record.tool_calls == ("run_python", "render_views")
    assert record.structural_failures == ("not manifold",)
    assert record.visual_deviations == ("missing_feature",)
    # An older line with none of these still defaults to the empty tuple.
    assert record.form_failures == ()


def test_a_reloaded_verdict_has_tuple_view_tags(tmp_path):
    log = VerdictLog(tmp_path / "verdicts.jsonl")
    log.append(
        IterationVerdict(
            iteration=2,
            brief_name="planter_box",
            visual_inspected=True,
            visual_deviations=("material_missing",),
            examiner="m+examiner:abc",
            calibration_identity="cal",
            view_tags=(("front", ("material_missing",)), ("bottom", ())),
        )
    )
    (verdict,) = log.verdicts()
    assert verdict.view_tags == (("front", ("material_missing",)), ("bottom", ()))
    assert dict(verdict.view_tags)["bottom"] == ()


# --- acceptance: bearings are modulo 360 --------------------------------


def test_the_shortest_signed_turn_wraps_through_zero():
    assert signed_angle_difference_deg(0.2, 359.9) == pytest.approx(-0.3)
    assert signed_angle_difference_deg(359.9, 0.2) == pytest.approx(0.3)
    assert signed_angle_difference_deg(10.0, 10.0) == 0.0


FOOT_RADIUS_M = 0.14


def _contact(bearing_deg: float) -> GroundContactMeasurement:
    probe = GroundContactProbe(
        name="leg_0_sole",
        centre_xy_m=(FOOT_RADIUS_M, 0.0),
        why="leg 0",
        expected_radius_m=FOOT_RADIUS_M,
        expected_angle_deg=0.0,
    )
    return GroundContactMeasurement(
        probe=probe,
        contact_area_m2=1.0,
        rejected_face_count=0,
        worst_rejected_span_m=0.0,
        centroid_xy_m=(
            FOOT_RADIUS_M * math.cos(math.radians(bearing_deg)),
            FOOT_RADIUS_M * math.sin(math.radians(bearing_deg)),
        ),
    )


def _report(contact: GroundContactMeasurement) -> AcceptanceReport:
    return AcceptanceReport(
        brief_name="stool",
        part_reports=(
            PartReport(
                name="Stool",
                object_found=True,
                linked_into_scene=True,
                ground_contacts=(contact,),
            ),
        ),
    )


def test_a_foot_straddling_the_plus_x_axis_has_not_swung():
    """0.2 deg before and 359.9 deg after is a 0.3 deg move, not 359.7."""
    before = _report(_contact(0.2))
    after = _report(_contact(-0.1))
    assert after.ground_contacts[0].measured_angle_deg == pytest.approx(359.9)
    brief = AssetBrief(name="stool", prompt_text="", parts=(PartSpec(name="Stool"),))
    outcome = RefinementOutcome(
        step=RefinementStep(name="noop", instruction_text="", changed=(), why="why"),
        before=before,
        after=after,
    )
    assert outcome.preservation_failures(brief) == []


def test_a_foot_that_really_swung_is_still_reported():
    before = _report(_contact(0.2))
    after = _report(_contact(10.0))
    brief = AssetBrief(name="stool", prompt_text="", parts=(PartSpec(name="Stool"),))
    outcome = RefinementOutcome(
        step=RefinementStep(name="noop", instruction_text="", changed=(), why="why"),
        before=before,
        after=after,
    )
    (failure,) = outcome.preservation_failures(brief)
    assert "swung +9.8 deg" in failure


# --- acceptance: a missing part is never hidden behind another failure --


def test_the_summary_names_a_missing_part_even_when_another_part_failed_first():
    brief = AssetBrief(
        name="pair",
        prompt_text="",
        parts=(
            PartSpec(
                name="Body",
                dimensions=(DimensionSpec("width_x", "x", 0.5),),
            ),
            PartSpec(name="Lid"),
        ),
        require_material=False,
    )
    report = AcceptanceReport(
        brief_name="pair",
        part_reports=(
            PartReport(
                name="Body",
                object_found=True,
                linked_into_scene=True,
                dimensions=(
                    DimensionMeasurement(
                        spec=brief.parts[0].dimensions[0], measured_m=0.9
                    ),
                ),
            ),
            PartReport(name="Lid", object_found=False),
        ),
    )
    summary = report.summary(brief)
    assert "no object named 'Lid'" in summary
    assert "width_x" in summary
