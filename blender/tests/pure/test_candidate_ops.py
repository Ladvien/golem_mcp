"""OT-12: the miner groups hatch calls by reason and by source shape,
ranks by frequency × gate-pass rate, measures the v12 hypothesis metric,
and refuses records it cannot mine."""

from __future__ import annotations

import datetime as _datetime

import pytest

from blended.evaluate.candidate_ops import (
    UnminableRecord,
    hatch_calls_per_gate_passing_brief,
    hatch_events_from_record,
    hatch_events_from_transcript,
    normalize_reason,
    render_report,
    source_shape,
)


def _event(reason: str, source: str, passed: bool | None, sha: str = "abc") -> dict:
    gates = (
        []
        if passed is None
        else [{"object_name": "X", "stage_reached": "done" if passed else "gate"}]
    )
    return {
        "schema_version": 2,
        "tool_name": "run_python",
        "arguments": {"source": source, "reason": reason},
        "ok": True,
        "stage_reached": "done",
        "wall_time_s": 0.1,
        "gates": gates,
        "images": [],
        "hatch_reason": reason,
        "source_sha256": sha,
        "refusal": "",
    }


def _op_event(name: str) -> dict:
    return {
        "schema_version": 2,
        "tool_name": name,
        "arguments": {},
        "ok": True,
        "stage_reached": "done",
        "wall_time_s": 0.1,
        "gates": [],
        "images": [],
        "hatch_reason": "",
        "source_sha256": "",
        "refusal": "",
    }


INSET = "import bmesh\nbm = bmesh.new()\nbmesh.ops.inset_region(bm, faces=bm.faces[:], thickness=0.01)\n"
INSET_OTHER_LITERALS = "import bmesh\nbm = bmesh.new()\nbmesh.ops.inset_region(bm, faces=list(bm.faces), thickness=0.02)\n"


def test_a_reason_is_one_spelling_and_a_shape_ignores_literals():
    assert normalize_reason("No op INSETS a face!") == normalize_reason(
        "no-op insets a face"
    )
    assert source_shape(INSET) == source_shape(INSET_OTHER_LITERALS)
    assert "bmesh.ops.inset_region" in source_shape(INSET)
    assert (
        source_shape("from blended.ops import add_box\nadd_box('A', 1, 1, 1)")
        == "add_box blended.ops:add_box"
    )
    assert source_shape("def (") == "<unparseable>"


def test_a_record_without_tool_events_is_refused_not_read_as_empty():
    with pytest.raises(UnminableRecord, match="predates OT-8"):
        hatch_events_from_record(
            {
                "iteration": 48,
                "brief_name": "planter_box",
                "tool_calls": ["run_python({})"],
            }
        )
    with pytest.raises(UnminableRecord, match="schema 1"):
        hatch_events_from_transcript(
            "chat.jsonl", [{"kind": "tool", "text": "run_python({})"}]
        )
    with pytest.raises(UnminableRecord, match="schema None"):
        hatch_events_from_record(
            {"iteration": 70, "tool_events": [{"tool_name": "run_python"}]}
        )


def test_the_ranking_is_frequency_times_gate_pass_rate():
    records = [
        {
            "iteration": 70,
            "brief_name": "planter_box",
            "form_gate_passed": True,
            "tool_events": [
                _op_event("add_box"),
                _event("no op insets a face", INSET, True),
                _event("no op insets a face", INSET_OTHER_LITERALS, True),
            ],
        },
        {
            "iteration": 71,
            "brief_name": "uv_crate",
            "form_gate_passed": True,
            "tool_events": [
                _event("no op insets a face", INSET, False),
                _event("measure a vertex", "print(1)", None),
                _event("measure a vertex", "print(2)", None),
            ],
        },
        {
            "iteration": 72,
            "brief_name": "ribbed_column",
            "form_gate_passed": False,
            "tool_events": [_op_event("add_lathe")],
        },
    ]
    report = render_report(records, {}, _datetime.date(2026, 9, 10))

    assert "# Candidate ops from the escape hatch — 2026-09-10" in report
    assert "- Hatch calls: 5 (3 gated, 2 gate-passing)" in report
    # inset: 3 calls, 3 gated, 2 passed -> 0.67 rate, score 2.00; measure: 2 calls, 0 gated -> score 0
    assert (
        "| 1 | no op insets a face | 3 | 3 | 0.67 | 2.00 | planter_box, uv_crate |"
        in report
    )
    assert "| 2 | measure a vertex | 2 | 0 | 0.00 | 0.00 | uv_crate |" in report
    assert "`bmesh.new bmesh.ops.inset_region`" in report
    # the v12 hypothesis metric: (2 + 3) / 2 gate-passing records
    per_brief, count = hatch_calls_per_gate_passing_brief(records)
    assert (per_brief, count) == (2.5, 2)
    assert "- 2.50 over 2 gate-passing record(s)" in report


def test_a_refused_hatch_call_is_not_a_vote():
    refused = dict(
        _event("no reason given", "pass", None), refusal="run_python refused: ..."
    )
    assert (
        hatch_events_from_record(
            {"iteration": 73, "tool_events": [refused, _op_event("add_box")]}
        )
        == []
    )
