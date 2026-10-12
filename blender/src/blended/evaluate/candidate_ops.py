"""Mine the escape hatch for the ops it is asking for (OT-12).

Every `run_python` call carries a `reason` (OT-7) and, in the v2 tool
event (OT-8), whether the object it built passed the gate. A reason is
a vote for an op that does not exist; a reason that keeps passing the
gate is a vote for an op that WORKS as raw bpy and only needs a name.
This module groups hatch events two ways — by normalized reason and by
the SHAPE of the source (the API it called, not the literals it used) —
and ranks each group by frequency × gate-pass rate.

Self-checking: a record with no `tool_events` predates OT-8 and cannot
be mined; it is refused by iteration number rather than read as "no
hatch calls". Pure: JSON in, Markdown out.
"""

from __future__ import annotations

import ast
import builtins
import datetime as _datetime
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from blended.agent.tool_event import TOOL_EVENT_KIND, TOOL_EVENT_SCHEMA_VERSION
from blended.stages import STAGE_DONE

HATCH_TOOL_NAME = "run_python"
_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
# The names a source shape is made of: every dotted call target and
# every op imported from the facade. Literals, variable names and
# comments are not part of the shape.
_FACADE_PREFIX = "blended.ops"
_BUILTIN_NAMES = frozenset(dir(builtins))


class UnminableRecord(ValueError):
    """A record without structured tool events (pre-OT-8)."""


def normalize_reason(reason: str) -> str:
    """One spelling per intent: lowercase, punctuation to spaces, collapsed."""
    return " ".join(token for token in _WORD_PATTERN.split(reason.lower()) if token)


def source_shape(source: str) -> str:
    """The API a chunk calls, as a sorted, de-duplicated key.

    `bmesh.ops.inset_region(...)` and `bmesh.ops.inset_region(bm, faces=...)`
    have one shape; so do two chunks that both import `boolean_union`
    from the facade. A chunk that will not parse has the shape
    `<unparseable>` — still a group, never a crash.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "<unparseable>"
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            # A builtin (`list`, `print`, `round`) is not API; the shape
            # is what the chunk asked BLENDER or the facade to do.
            if dotted and dotted not in _BUILTIN_NAMES:
                names.add(dotted)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith(_FACADE_PREFIX)
        ):
            names.update(f"{_FACADE_PREFIX}:{alias.name}" for alias in node.names)
    return " ".join(sorted(names)) or "<no calls>"


def _dotted_name(node) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


@dataclass
class HatchEvent:
    iteration: int | str  # iteration number, or a transcript name
    brief_name: str
    reason: str
    source_sha256: str
    source: str
    gated: bool
    passed: bool
    wall_time_s: float


@dataclass
class Candidate:
    key: str
    events: list[HatchEvent] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.events)

    @property
    def gated_count(self) -> int:
        return sum(1 for event in self.events if event.gated)

    @property
    def gate_pass_rate(self) -> float:
        gated = [event for event in self.events if event.gated]
        return sum(1 for event in gated if event.passed) / len(gated) if gated else 0.0

    @property
    def score(self) -> float:
        return self.count * self.gate_pass_rate


def hatch_events_from_record(record: dict) -> list[HatchEvent]:
    """The run_python events of one iteration record, or UnminableRecord."""
    events = record.get("tool_events")
    if not events:
        raise UnminableRecord(
            f"iteration {record.get('iteration')!r} ({record.get('brief_name')!r}) has no "
            f"tool_events: it predates OT-8 and cannot be mined"
        )
    return [
        _hatch_event(record.get("iteration"), record.get("brief_name", ""), event)
        for event in events
        if event.get("tool_name") == HATCH_TOOL_NAME and not event.get("refusal")
    ]


def hatch_events_from_transcript(name: str, rows: list[dict]) -> list[HatchEvent]:
    """The run_python events of one chat transcript (JSONL rows, schema 2)."""
    tool_rows = [row for row in rows if row.get("kind") == TOOL_EVENT_KIND]
    if not tool_rows:
        raise UnminableRecord(
            f"transcript {name!r} has no {TOOL_EVENT_KIND} rows: schema 1, cannot be mined"
        )
    return [
        _hatch_event(name, "", row["data"])
        for row in tool_rows
        if row["data"].get("tool_name") == HATCH_TOOL_NAME
        and not row["data"].get("refusal")
    ]


def _hatch_event(iteration, brief_name: str, event: dict) -> HatchEvent:
    if event.get("schema_version") != TOOL_EVENT_SCHEMA_VERSION:
        raise UnminableRecord(
            f"tool event schema {event.get('schema_version')!r} in {iteration!r}, "
            f"expected {TOOL_EVENT_SCHEMA_VERSION}"
        )
    gates = event.get("gates") or ()
    return HatchEvent(
        iteration=iteration,
        brief_name=brief_name,
        reason=event.get("hatch_reason", ""),
        source_sha256=event.get("source_sha256", ""),
        source=str(event.get("arguments", {}).get("source", "")),
        gated=bool(gates),
        passed=bool(gates)
        and all(gate.get("stage_reached") == STAGE_DONE for gate in gates),
        wall_time_s=float(event.get("wall_time_s", 0.0)),
    )


def group_candidates(events: list[HatchEvent], key) -> list[Candidate]:
    groups: dict[str, Candidate] = defaultdict(lambda: Candidate(key=""))
    for event in events:
        group_key = key(event)
        groups[group_key].key = group_key
        groups[group_key].events.append(event)
    return sorted(
        groups.values(),
        key=lambda candidate: (-candidate.score, -candidate.count, candidate.key),
    )


def hatch_calls_per_gate_passing_brief(records: list[dict]) -> tuple[float | None, int]:
    """The OT-7 hypothesis metric: mean run_python calls over records whose
    form gate passed, and how many such records there were. None when none."""
    passing = [record for record in records if record.get("form_gate_passed")]
    if not passing:
        return None, 0
    counts = [len(hatch_events_from_record(record)) for record in passing]
    return sum(counts) / len(counts), len(counts)


def render_report(
    records: list[dict],
    transcript_events: dict[str, list[HatchEvent]],
    today: _datetime.date,
) -> str:
    events: list[HatchEvent] = []
    for record in records:
        events.extend(hatch_events_from_record(record))
    for transcript in transcript_events.values():
        events.extend(transcript)
    by_reason = group_candidates(
        events, lambda event: normalize_reason(event.reason) or "<no reason>"
    )
    by_shape = group_candidates(events, lambda event: source_shape(event.source))
    per_brief, passing_count = hatch_calls_per_gate_passing_brief(records)
    iterations = sorted({record["iteration"] for record in records})
    lines = [
        f"# Candidate ops from the escape hatch — {today.isoformat()}",
        "",
        "Every `run_python` call is a vote for an op that does not exist (OT-12). Groups are",
        "ranked by frequency × gate-pass rate: a reason that keeps passing the gate as raw",
        "bpy is an op that works and only needs a name; one that keeps failing is a problem",
        "the vocabulary should solve differently.",
        "",
        "## Inputs",
        "",
        f"- Iteration records: {len(records)} ({iterations[0]}–{iterations[-1]})"
        if records
        else "- Iteration records: 0",
        f"- Chat transcripts: {len(transcript_events)}",
        (
            f"- Hatch calls: {len(events)} ({sum(1 for e in events if e.gated)} gated, "
            f"{sum(1 for e in events if e.passed)} gate-passing)"
        ),
        "",
        "## Hatch calls per gate-passing brief (the v12 hypothesis, OT-7)",
        "",
        (
            f"- {per_brief:.2f} over {passing_count} gate-passing record(s); the hypothesis is "
            f"< 1.0 on the five briefs within three paired rolls."
            if per_brief is not None
            else "- no gate-passing records among the inputs"
        ),
        "",
        "## By reason",
        "",
        "| rank | reason (normalized) | calls | gated | gate-pass rate | score | briefs |",
        "|---|---|---|---|---|---|---|",
    ]
    for rank, candidate in enumerate(by_reason, 1):
        briefs = ", ".join(
            sorted({f"{e.brief_name or e.iteration}" for e in candidate.events})
        )
        lines.append(
            f"| {rank} | {candidate.key} | {candidate.count} | {candidate.gated_count} | "
            f"{candidate.gate_pass_rate:.2f} | {candidate.score:.2f} | {briefs} |"
        )
    lines += [
        "",
        "## By source shape",
        "",
        "| rank | shape (API called) | calls | gated | gate-pass rate | score | example hash |",
        "|---|---|---|---|---|---|---|",
    ]
    for rank, candidate in enumerate(by_shape, 1):
        example = candidate.events[0].source_sha256 or "-"
        lines.append(
            f"| {rank} | `{candidate.key}` | {candidate.count} | {candidate.gated_count} | "
            f"{candidate.gate_pass_rate:.2f} | {candidate.score:.2f} | `{example}` |"
        )
    lines.append("")
    return "\n".join(lines)


def load_records(log_path: Path, from_iteration: int | None) -> list[dict]:
    import json

    records = [
        json.loads(line)
        for line in Path(log_path).read_text().splitlines()
        if line.strip()
    ]
    if from_iteration is not None:
        records = [
            record for record in records if record["iteration"] >= from_iteration
        ]
    return records
