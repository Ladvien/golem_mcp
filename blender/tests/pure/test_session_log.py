"""Pure layer: the logger needs no bpy.

Covers both append-only logs: the run session log, and the verdict log
whose rows now name their AUTHOR. A machine verdict that reads like a
human sign-off would destroy the distinction the pin rests on, so the
authorship rules are asserted here.
"""

import pytest

from blended.drift.catalog import DRIFT_ENTRIES
from blended.evaluate.iteration_log import (
    HUMAN_EXAMINER,
    InvalidVerdict,
    IterationVerdict,
    VerdictLog,
)
from blended.run.executor import RunResult
from blended.run.session_log import SessionLog


def _failed_result() -> RunResult:
    entry = next(
        catalog_entry
        for catalog_entry in DRIFT_ENTRIES
        if "use_auto_smooth" in catalog_entry.symbol
    )
    return RunResult(
        ok=False,
        duration_s=0.5,
        blender_version="5.0.1",
        error_type="AttributeError",
        error_message="no attribute 'use_auto_smooth'",
        traceback_text="...",
        matched_drift=(entry,),
    )


def test_records_append_and_read_back(tmp_path):
    session_log = SessionLog(tmp_path / "session.jsonl")
    session_log.record_attempt("crate", "print(1)", _failed_result(), 0)
    session_log.record_attempt(
        "crate", "print(2)", RunResult(ok=True, duration_s=0.1), 1
    )

    records = session_log.read_records()
    assert len(records) == 2
    assert records[0]["ok"] is False
    assert records[0]["matched_drift"] == ["bpy.types.Mesh.use_auto_smooth"]
    assert records[1]["ok"] is True
    assert records[1]["attempt_index"] == 1
    # Different sources hash differently — the log can distinguish chunks.
    assert records[0]["source_sha256"] != records[1]["source_sha256"]


def test_read_on_missing_file_is_empty(tmp_path):
    assert SessionLog(tmp_path / "absent.jsonl").read_records() == []


def test_a_verdict_line_without_an_examiner_field_loads_as_human(tmp_path):
    """Every verdict line written before authorship existed is a human
    sign-off, and must keep loading as one."""
    log_path = tmp_path / "verdicts.jsonl"
    log_path.write_text(
        '{"iteration": 47, "brief_name": "three_leg_stool", '
        '"visual_inspected": true, "visual_deviations": [], '
        '"classification": "", "hypothesis": "", "prompt_change": "", '
        '"notes": "human verified"}\n',
        encoding="utf-8",
    )

    (verdict,) = VerdictLog(log_path).verdicts()

    assert verdict.examiner == HUMAN_EXAMINER
    assert verdict.abstained is False
    assert verdict.calibration_identity == ""


def test_a_machine_verdict_without_its_calibration_is_not_a_verdict():
    with pytest.raises(InvalidVerdict):
        IterationVerdict(
            iteration=52,
            brief_name="planter_box",
            visual_inspected=True,
            examiner="minimax-m3:cloud+examiner:ab12cd34ef56",
        )


def test_a_machine_verdict_round_trips_with_its_author(tmp_path):
    log = VerdictLog(tmp_path / "verdicts.jsonl")
    log.append(
        IterationVerdict(
            iteration=52,
            brief_name="planter_box",
            visual_inspected=True,
            visual_deviations=("missing_feature",),
            examiner="minimax-m3:cloud+examiner:ab12cd34ef56",
            abstained=False,
            calibration_identity="0123456789ab",
        )
    )

    (verdict,) = log.verdicts()

    assert verdict.examiner == "minimax-m3:cloud+examiner:ab12cd34ef56"
    assert verdict.calibration_identity == "0123456789ab"
    assert verdict.visual_deviations == ("missing_feature",)


def test_an_empty_examiner_is_refused():
    with pytest.raises(InvalidVerdict):
        IterationVerdict(
            iteration=52,
            brief_name="planter_box",
            visual_inspected=True,
            examiner="  ",
        )
