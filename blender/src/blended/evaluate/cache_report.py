"""Cache-read fraction per run (OT-26).

On lanes with prefix caching the prompt side of a turn is billed three
ways: fresh `input_tokens`, `cache_read_tokens` (0.1x) and
`cache_write_tokens` (1.25x). The fraction read from cache is the
measure of how much of every call was already there — the number that
falls when something volatile lands ahead of the static prefix. The
records carry the three counts (`IterationRecord`); the fraction is
DERIVED by `TurnCost.cache_read_fraction`'s one function, never stored
beside them.
"""

from __future__ import annotations

from dataclasses import dataclass

from blended.agent.claude_code import NoBilledInput, cache_read_fraction

__all__ = [
    "NoBilledInput",
    "RunCacheRow",
    "cache_read_fraction",
    "cache_rows",
    "paired_by_brief",
    "render_pairs",
    "render_rows",
]


@dataclass(frozen=True)
class RunCacheRow:
    iteration: int
    brief_name: str
    writer_model: str
    offered_tools_fingerprint: str
    api_calls: int
    billed_input_tokens: int
    cache_write_tokens: int
    cache_read_fraction: float

    @property
    def tokens_per_call(self) -> float:
        return self.billed_input_tokens / self.api_calls if self.api_calls else 0.0

    @property
    def cache_writes_per_call(self) -> float:
        """What each call re-wrote at 1.25x: the number a volatile prefix
        inflates, independent of how big the static part is."""
        return self.cache_write_tokens / self.api_calls if self.api_calls else 0.0


def cache_rows(records) -> list[RunCacheRow]:
    """One row per record that recorded its spend; rows from before the
    accounting existed (all-zero counts) are skipped, not zeroed."""
    rows = []
    for record in records:
        billed = (
            record.input_tokens + record.cache_read_tokens + record.cache_write_tokens
        )
        if billed <= 0:
            continue
        rows.append(
            RunCacheRow(
                iteration=record.iteration,
                brief_name=record.brief_name,
                writer_model=record.writer_model,
                offered_tools_fingerprint=record.offered_tools_fingerprint,
                api_calls=record.api_calls,
                billed_input_tokens=billed,
                cache_write_tokens=record.cache_write_tokens,
                cache_read_fraction=cache_read_fraction(
                    record.input_tokens,
                    record.cache_read_tokens,
                    record.cache_write_tokens,
                ),
            )
        )
    return rows


def paired_by_brief(
    before: list[RunCacheRow], after: list[RunCacheRow]
) -> list[tuple[RunCacheRow, RunCacheRow]]:
    """The LATEST run of each brief on each side, for briefs on both sides."""
    latest_before = {
        row.brief_name: row for row in sorted(before, key=lambda r: r.iteration)
    }
    latest_after = {
        row.brief_name: row for row in sorted(after, key=lambda r: r.iteration)
    }
    return [
        (latest_before[name], latest_after[name])
        for name in sorted(latest_before)
        if name in latest_after
    ]


def render_rows(rows: list[RunCacheRow]) -> str:
    lines = [
        "| iteration | brief | writer | offered | api calls | billed input | tokens/call | writes/call | cache read |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.iteration} | {row.brief_name} | {row.writer_model} | {row.offered_tools_fingerprint or '(whole set)'} | {row.api_calls} | {row.billed_input_tokens:,} | {row.tokens_per_call:,.0f} | {row.cache_writes_per_call:,.0f} | {row.cache_read_fraction:.3f} |"
        )
    return "\n".join(lines)


def render_pairs(pairs: list[tuple[RunCacheRow, RunCacheRow]]) -> str:
    if not pairs:
        return "no brief has a run on both sides"
    lines = [
        "| brief | cache read before (iteration) | after (iteration) | delta | writes/call before | after | delta |",
        "|---|---|---|---|---|---|---|",
    ]
    deltas = []
    write_deltas = []
    for before, after in pairs:
        delta = after.cache_read_fraction - before.cache_read_fraction
        write_delta = after.cache_writes_per_call - before.cache_writes_per_call
        deltas.append(delta)
        write_deltas.append(write_delta)
        lines.append(
            f"| {before.brief_name} | {before.cache_read_fraction:.3f} ({before.iteration}) | {after.cache_read_fraction:.3f} ({after.iteration}) | {delta:+.3f} "
            f"| {before.cache_writes_per_call:,.0f} | {after.cache_writes_per_call:,.0f} | {write_delta:+,.0f} |"
        )
    mean = sum(deltas) / len(deltas)
    mean_write = sum(write_deltas) / len(write_deltas)
    lines.append(
        f"\nmean cache-read delta {mean:+.3f} over {len(pairs)} paired brief(s); fell on {sum(1 for d in deltas if d < 0)}; "
        f"mean writes/call delta {mean_write:+,.0f}; rose on {sum(1 for d in write_deltas if d > 0)}"
    )
    return "\n".join(lines)
