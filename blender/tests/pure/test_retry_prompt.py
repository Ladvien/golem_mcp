"""Pure layer: prompt building needs no bpy."""

from blended.drift.catalog import DRIFT_ENTRIES
from blended.run.executor import RunResult
from blended.run.retry import build_retry_prompt


def _failed_result_with_drift() -> RunResult:
    auto_smooth_entry = next(
        entry for entry in DRIFT_ENTRIES if "use_auto_smooth" in entry.symbol
    )
    return RunResult(
        ok=False,
        duration_s=0.01,
        error_type="AttributeError",
        error_message="'Mesh' object has no attribute 'use_auto_smooth'",
        traceback_text="AttributeError: 'Mesh' object has no attribute 'use_auto_smooth'",
        matched_drift=(auto_smooth_entry,),
    )


def test_prompt_contains_source_traceback_and_drift_fix():
    prompt = build_retry_prompt(
        "mesh.use_auto_smooth = True", _failed_result_with_drift()
    )
    assert "mesh.use_auto_smooth = True" in prompt
    assert "AttributeError" in prompt
    assert "known API drift" in prompt
    assert "smooth-by-angle" in prompt  # the fix text travels with the prompt


def test_prompt_omits_drift_section_when_nothing_matched():
    clean_failure = RunResult(
        ok=False,
        duration_s=0.01,
        error_type="ValueError",
        error_message="boom",
        traceback_text="ValueError: boom",
    )
    prompt = build_retry_prompt("raise ValueError('boom')", clean_failure)
    assert "known API drift" not in prompt
