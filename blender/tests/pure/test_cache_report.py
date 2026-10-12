"""OT-26: the cache-read fraction is derived from the record's three
counts in one place, and the paired comparison pairs each brief's latest
run on each side."""

import pytest

from blended.evaluate.cache_report import (
    NoBilledInput,
    RunCacheRow,
    cache_read_fraction,
    cache_rows,
    paired_by_brief,
    render_pairs,
    render_rows,
)
from blended.evaluate.iteration_log import IterationRecord


def _record(iteration, brief, **spend):
    return IterationRecord(
        iteration=iteration,
        brief_name=brief,
        prompt_identity="v1:x",
        prompt_revision=1,
        started_at="2026-09-10T00:00:00",
        writer_model="claude-code:sonnet",
        **spend,
    )


def test_the_fraction_is_reads_over_everything_billed_on_the_prompt_side():
    assert cache_read_fraction(
        input_tokens=26, cache_read_tokens=338_421, cache_write_tokens=44_976
    ) == pytest.approx(0.8826, abs=1e-4)  # iteration 74
    with pytest.raises(NoBilledInput):
        cache_read_fraction(0, 0, 0)


def test_rows_skip_records_from_before_the_accounting_existed():
    rows = cache_rows(
        [
            _record(1, "crate"),
            _record(
                2,
                "crate",
                api_calls=2,
                input_tokens=10,
                cache_read_tokens=90,
                cache_write_tokens=0,
            ),
        ]
    )
    assert [r.iteration for r in rows] == [2]
    assert (
        rows[0].cache_read_fraction == 0.9
        and rows[0].tokens_per_call == 50.0
        and rows[0].cache_writes_per_call == 0.0
    )


def test_pairs_take_each_briefs_latest_run_on_each_side():
    def row(iteration, brief, fraction):
        return RunCacheRow(iteration, brief, "m", "t:x", 2, 100, 20, fraction)

    before = [row(1, "crate", 0.80), row(2, "crate", 0.85), row(3, "stool", 0.70)]
    after = [row(5, "crate", 0.90), row(6, "column", 0.95)]
    pairs = paired_by_brief(before, after)
    assert [(b.iteration, a.iteration) for b, a in pairs] == [(2, 5)]
    text = render_pairs(pairs)
    assert (
        "| crate | 0.850 (2) | 0.900 (5) | +0.050 | 10 | 10 | +0 |" in text
        and "fell on 0" in text
        and "rose on 0" in text
    )
    assert render_pairs([]) == "no brief has a run on both sides"
    assert "| 2 | crate |" in render_rows(before)


def test_turn_cost_reports_the_same_fraction_in_its_summary():
    from blended.agent.claude_code import TurnCost

    spent = TurnCost(
        api_calls=14,
        input_tokens=22,
        cache_read_tokens=197_377,
        cache_write_tokens=52_266,
        output_tokens=4_454,
        cost_usd=0.32,
    )  # iteration 87
    assert spent.cache_read_fraction == cache_read_fraction(22, 197_377, 52_266)
    assert "(197,377 cached, 79%)" in spent.summary()
    assert (
        "cached)" in TurnCost().summary()
    )  # nothing billed yet: no fraction shown, no crash
    with pytest.raises(NoBilledInput):
        _ = TurnCost().cache_read_fraction
