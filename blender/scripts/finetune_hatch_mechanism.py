#!/usr/bin/env python3
"""Why the archive's geometry goes through the hatch — measured, not guessed.

    .venv/bin/python scripts/finetune_hatch_mechanism.py \\
        --bench-root /Users/ladvien/3dcodebench

`REPORT.md` §4d reported a 95.1% hatch share on passing archived
attempts and left the mechanism open with two named axes. This script
answers the open question from artifacts already on disk — no roll, no
bake — and it kills one proposed mechanism outright.

THE PROPOSED MECHANISM. "An op call that errors teaches the agent,
within the same run, that `run_python` is the reliable path; once it
switches it never switches back." That predicts two things: op-call
error rates materially HIGHER in the multi-turn archive than in the
single-shot A1 arm, and, inside a run, the first chunk FOLLOWING the
first op failure. Both are checkable here.

THREE INSTRUMENTS, and the difference between them is the finding:

* `<inst>/.agent_transcript.txt` carries schema-2 `--- tool_event ---`
  blocks: one per DISPATCHED tool call, in order, with `ok`,
  `tool_name` and `offered_tools_fingerprint`. This is what the agent
  did.
* `<inst>/<inst>.py` is the BAKED script: `# --- chunk N ---` and
  `# --- op N: name ---` labels are exactly what the bridge collected
  (`blended.evaluate.bench_bridge.standalone_script`). This is what the
  score saw.
* `<inst>/.agent_meta.json` carries `n_chunks_included` and
  `n_op_calls_included`, which phase A used. Both are biased, measured
  here: `n_op_calls_included` counts the 14 READER ops as
  geometry-emitting, because `emits_geometry` is "hatch or any facade
  op", and `n_chunks_included` is the label COUNTER, which advances on
  op calls too.

A roll whose meta carries no `n_op_calls_included` key at all predates
op collection in the bridge: its baked script cannot contain an op
call however many the agent made, so its 100% hatch share is an
instrument reading, not agent behaviour. Those rolls are partitioned
out rather than averaged in.

Pure measurement: artifacts in, one JSON and one markdown out.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from finetune_decision_thresholds import EXCLUDED_CODES, model_directory
from finetune_phase_a import PHASE_A_DIRECTORY, WORKING_DIRECTORY, included_model_dirs
from finetune_phase_b import completions

from blended.agent.tool_disclosure import core_ops, offered_tools
from blended.agent.tool_schemas import tool_schemas_fingerprint
from blended.agent.tools import SERVICE_TOOL_NAMES, TOOL_SCHEMAS
from blended.evaluate.bench_bridge import HATCH_TOOL_NAME
from blended.ops._contract import changes_scene, facade_ops

MEASURED_PATH = WORKING_DIRECTORY / "hatch_mechanism.json"
SUMMARY_PATH = PHASE_A_DIRECTORY / "hatch_mechanism.md"
# The arm whose single-shot op usage is the contrast case: same bench,
# same instances, one turn, all 56 schemas offered.
SINGLE_SHOT_ARM = "a1"
# A transcript block header, e.g. `--- tool_event ---`.
BLOCK_PATTERN = re.compile(r"^--- (\w+) ---$", re.MULTILINE)
CHUNK_LABEL_PATTERN = re.compile(r"^# --- chunk \d+", re.MULTILINE)
OP_LABEL_PATTERN = re.compile(r"^# --- op \d+: ([a-z_0-9]+)", re.MULTILINE)
# The key whose ABSENCE means the bridge of that era collected no op
# calls at all, so the attempt's 100% hatch share is an artifact.
OP_COLLECTION_KEY = "n_op_calls_included"
# A probe that returns one identical value for every input is broken,
# not evidence of a uniform world: the scan refuses to report unless
# op usage VARIES across rolls.
MINIMUM_ROLLS_WITH_OPS = 2


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    return parser.parse_args(argv)


def scene_changing_ops() -> frozenset[str]:
    return frozenset(name for name, function in facade_ops() if changes_scene(function))


def reader_op_names() -> frozenset[str]:
    return frozenset(
        name for name, function in facade_ops() if not changes_scene(function)
    )


def transcript_events(path: Path) -> list[dict]:
    """The ordered schema-2 tool events of one attempt.

    A block that does not parse is returned as `{"_unparsed": ...}` and
    counted by the caller: a silently dropped event would move every
    ordering conclusion below.
    """
    parts = BLOCK_PATTERN.split(path.read_text(errors="replace"))
    events: list[dict] = []
    for index in range(1, len(parts) - 1, 2):
        if parts[index] != "tool_event":
            continue
        body = parts[index + 1].strip()
        try:
            events.append(json.loads(body))
        except json.JSONDecodeError:
            events.append({"_unparsed": body[:200]})
    return events


def baked_labels(path: Path) -> tuple[list[str], int]:
    """(op names, chunk count) the bridge actually collected."""
    if not path.exists():
        return [], 0
    text = path.read_text(errors="replace")
    return OP_LABEL_PATTERN.findall(text), len(CHUNK_LABEL_PATTERN.findall(text))


def scan_attempt(
    directory: Path, scene_ops: frozenset[str], readers: frozenset[str]
) -> dict | None:
    """One archived attempt, through all three instruments."""
    meta_path = directory / ".agent_meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    transcript = directory / ".agent_transcript.txt"
    events = transcript_events(transcript) if transcript.exists() else []
    baked_ops, baked_chunks = baked_labels(directory / f"{directory.name}.py")
    row = {
        "model_dir": directory.parent.name,
        "instance": directory.name,
        "writer": meta.get("writer") or meta.get("model") or "",
        "num_turns": meta.get("num_turns"),
        "bake_records_ops": OP_COLLECTION_KEY in meta,
        "meta_chunks_included": meta.get("n_chunks_included"),
        "meta_ops_included": meta.get(OP_COLLECTION_KEY),
        "baked_chunks": baked_chunks,
        "baked_scene_ops": sum(1 for name in baked_ops if name in scene_ops),
        "baked_reader_ops": sum(1 for name in baked_ops if name in readers),
        "events": len(events),
        "unparsed_events": sum(1 for event in events if "_unparsed" in event),
        "offered_fingerprints": sorted(
            {
                event.get("offered_tools_fingerprint")
                for event in events
                if event.get("offered_tools_fingerprint")
            }
        ),
        "dispatched_scene_ops": 0,
        "dispatched_scene_op_failures": 0,
        "dispatched_chunks": 0,
        "dispatched_chunk_failures": 0,
        "first_scene_op_index": None,
        "first_scene_op_failure_index": None,
        "first_chunk_index": None,
    }
    for index, event in enumerate(events, start=1):
        name = event.get("tool_name", "")
        ok = bool(event.get("ok"))
        if name == HATCH_TOOL_NAME:
            row["dispatched_chunks"] += 1
            row["dispatched_chunk_failures"] += 0 if ok else 1
            if row["first_chunk_index"] is None:
                row["first_chunk_index"] = index
        elif name in scene_ops:
            row["dispatched_scene_ops"] += 1
            if row["first_scene_op_index"] is None:
                row["first_scene_op_index"] = index
            if not ok:
                row["dispatched_scene_op_failures"] += 1
                if row["first_scene_op_failure_index"] is None:
                    row["first_scene_op_failure_index"] = index
    return row


def archive_rows(bench_root: Path, results_root: str, scene_ops, readers) -> list[dict]:
    root = bench_root / results_root
    harness, _third_party = included_model_dirs(root)
    rows = []
    for model_dir in harness:
        for directory in sorted(p for p in (root / model_dir).iterdir() if p.is_dir()):
            row = scan_attempt(directory, scene_ops, readers)
            if row:
                rows.append(row)
    return rows


def single_shot_rows(
    bench_root: Path, results_root: str, scene_ops, readers
) -> list[dict]:
    """A1's completions, through the same two instruments.

    A1 has no tool-event log — it is one reply, dispatched here — so its
    "attempted" side is the reply's own `tool_calls` and its "collected"
    side is the baked script. That pair is the instrument the archive is
    compared on, so both sides measure the same thing.
    """
    rows = []
    for record in completions(SINGLE_SHOT_ARM):
        reply = (
            json.loads(record["raw_output"])
            if record["raw_output"].startswith("{")
            else {}
        )
        names = [
            call.get("function", {}).get("name", "")
            for call in reply.get("tool_calls", [])
        ]
        arm_directory = (
            bench_root
            / results_root
            / model_directory(SINGLE_SHOT_ARM, record["draw"])
            / record["instance"]
        )
        baked_ops, baked_chunks = baked_labels(
            arm_directory / f"{record['instance']}.py"
        )
        first_scene = next(
            (i for i, name in enumerate(names, start=1) if name in scene_ops), None
        )
        first_chunk = next(
            (i for i, name in enumerate(names, start=1) if name == HATCH_TOOL_NAME),
            None,
        )
        rows.append(
            {
                "instance": record["instance"],
                "draw": record["draw"],
                "dispatched_scene_ops": sum(1 for name in names if name in scene_ops),
                "dispatched_readers": sum(1 for name in names if name in readers),
                "dispatched_chunks": sum(
                    1 for name in names if name == HATCH_TOOL_NAME
                ),
                "baked_scene_ops": sum(1 for name in baked_ops if name in scene_ops),
                "baked_reader_ops": sum(1 for name in baked_ops if name in readers),
                "baked_chunks": baked_chunks,
                "first_scene_op_index": first_scene,
                "first_chunk_index": first_chunk,
            }
        )
    return rows


def _share(numerator: int, denominator: int):
    return (numerator / denominator) if denominator else None


def geometry_split(rows: list[dict], chunk_key: str, op_key: str) -> dict:
    chunks = sum(row[chunk_key] or 0 for row in rows)
    ops = sum(row[op_key] or 0 for row in rows)
    return {
        "attempts": len(rows),
        "chunks": chunks,
        "scene_ops": ops,
        "hatch_share": _share(chunks, chunks + ops),
        "op_share": _share(ops, chunks + ops),
        "attempts_using_any_scene_op": sum(1 for row in rows if (row[op_key] or 0) > 0),
    }


def drop_rate(rows: list[dict], dispatched_key: str, baked_key: str) -> dict:
    """Dispatched calls that never reached the baked script.

    The one instrument both regimes share. A call that errored, or that
    neither executed nor changed the scene, is not collected
    (`bench_bridge.include_call`), so dispatched-minus-baked IS the
    failure count on the side the score sees.
    """
    dispatched = sum(row[dispatched_key] or 0 for row in rows)
    baked = sum(row[baked_key] or 0 for row in rows)
    return {
        "dispatched": dispatched,
        "baked": baked,
        "dropped": dispatched - baked,
        "drop_rate": _share(dispatched - baked, dispatched),
    }


def abandonment(rows: list[dict]) -> dict:
    """Did the switch to chunks FOLLOW a failed op call, or precede it?"""
    instrumented = [row for row in rows if row["events"]]
    chunk_using = [row for row in instrumented if row["dispatched_chunks"]]
    with_failure = [row for row in chunk_using if row["dispatched_scene_op_failures"]]
    failure_first = [
        row
        for row in with_failure
        if row["first_scene_op_failure_index"] < row["first_chunk_index"]
    ]
    first_call = Counter()
    for row in instrumented:
        op_index, chunk_index = row["first_scene_op_index"], row["first_chunk_index"]
        if op_index is None and chunk_index is None:
            first_call["neither"] += 1
        elif chunk_index is None:
            first_call["op"] += 1
        elif op_index is None or chunk_index < op_index:
            first_call["chunk"] += 1
        else:
            first_call["op"] += 1
    return {
        "instrumented_attempts": len(instrumented),
        "chunk_using_attempts": len(chunk_using),
        "chunk_using_with_any_op_failure": len(with_failure),
        "failure_before_first_chunk": len(failure_first),
        "failure_after_first_chunk": len(with_failure) - len(failure_first),
        "chunk_using_that_never_called_a_scene_op": sum(
            1 for row in chunk_using if row["dispatched_scene_ops"] == 0
        ),
        "first_geometry_call": dict(first_call),
        "first_geometry_call_is_chunk_share": _share(
            first_call["chunk"], len(instrumented)
        ),
        "scene_op_failure_rate_ok_flag": _share(
            sum(row["dispatched_scene_op_failures"] for row in instrumented),
            sum(row["dispatched_scene_ops"] for row in instrumented),
        ),
        "chunk_failure_rate_ok_flag": _share(
            sum(row["dispatched_chunk_failures"] for row in instrumented),
            sum(row["dispatched_chunks"] for row in instrumented),
        ),
    }


def disclosure_table(rows: list[dict], disclosed_fingerprint: str) -> dict:
    """Baked op share per roll, with the tool set that roll offered."""
    per_roll: dict[str, dict] = {}
    for row in rows:
        entry = per_roll.setdefault(
            row["model_dir"],
            {
                "attempts": 0,
                "baked_chunks": 0,
                "baked_scene_ops": 0,
                "dispatched_chunks": 0,
                "dispatched_scene_ops": 0,
                "instrumented": 0,
                "bake_records_ops": 0,
                "fingerprints": set(),
                "writer": row["writer"],
            },
        )
        entry["attempts"] += 1
        entry["baked_chunks"] += row["baked_chunks"]
        entry["baked_scene_ops"] += row["baked_scene_ops"]
        entry["dispatched_chunks"] += row["dispatched_chunks"]
        entry["dispatched_scene_ops"] += row["dispatched_scene_ops"]
        entry["instrumented"] += 1 if row["events"] else 0
        entry["bake_records_ops"] += 1 if row["bake_records_ops"] else 0
        entry["fingerprints"].update(row["offered_fingerprints"])
    table = {}
    for name, entry in per_roll.items():
        fingerprints = sorted(entry.pop("fingerprints"))
        table[name] = {
            **entry,
            "offered_fingerprints": fingerprints,
            "offered_disclosed_set": disclosed_fingerprint in fingerprints,
            "baked_op_share": _share(
                entry["baked_scene_ops"],
                entry["baked_scene_ops"] + entry["baked_chunks"],
            ),
            "dispatched_op_share": _share(
                entry["dispatched_scene_ops"],
                entry["dispatched_scene_ops"] + entry["dispatched_chunks"],
            ),
        }
    return table


def pass_labels() -> dict[tuple[str, str], str]:
    """Phase A's per-attempt code, so the split is the published one."""
    path = PHASE_A_DIRECTORY / "taxonomy.csv"
    if not path.exists():
        raise SystemExit(f"run scripts/finetune_phase_a.py first: no {path}")
    with path.open() as handle:
        return {
            (row["model_dir"], row["instance"]): row["code"]
            for row in csv.DictReader(handle)
            if row["third_party"] == "False"
        }


def assert_probe_varies(rolls: dict) -> None:
    """A probe with one value for every roll is broken, not uniform."""
    with_ops = [
        name for name, entry in rolls.items() if (entry["baked_scene_ops"] or 0) > 0
    ]
    if len(with_ops) < MINIMUM_ROLLS_WITH_OPS:
        raise SystemExit(
            f"op usage does not vary across rolls ({len(with_ops)} roll(s) with a "
            f"baked op call): the label parse is broken, not the archive uniform"
        )


def assert_hypothesis_refuted(
    archive_drop: dict, single_drop: dict, mechanism: dict
) -> None:
    """Section 2 of the summary states that BOTH predictions fail; check it.

    The prose is fixed text, so a changed archive must not silently print
    a refutation the numbers no longer support. Prediction 1: the archive
    drops a HIGHER share of scene-op calls than A1. Prediction 2: an op
    failure precedes the first chunk more often than not.
    """
    archive_rate = archive_drop["scene_ops"]["drop_rate"]
    single_rate = single_drop["scene_ops"]["drop_rate"]
    if archive_rate is None or single_rate is None:
        raise SystemExit("op drop rate unmeasured: cannot state the mechanism result")
    if archive_rate > single_rate:
        raise SystemExit(
            f"archive drops {archive_rate:.3f} of scene ops against A1's "
            f"{single_rate:.3f}: the summary's 'both predictions fail' is false"
        )
    if (
        mechanism["failure_before_first_chunk"]
        >= mechanism["failure_after_first_chunk"]
    ):
        raise SystemExit(
            f"{mechanism['failure_before_first_chunk']} op failures preceded the "
            f"first chunk against {mechanism['failure_after_first_chunk']} after "
            f"it: the summary's 'both predictions fail' is false"
        )


def render_summary(measured: dict) -> str:
    archive = measured["archive"]
    single = measured["single_shot"]
    mechanism = measured["mechanism"]
    lines = [
        "# The hatch share, its instrument, and why the facade is abandoned",
        "",
        (
            "Every number here is read from artifacts already on disk: the "
            "schema-2 `tool_event` blocks in `<inst>/.agent_transcript.txt`, "
            "the `# --- chunk N ---` / `# --- op N: name ---` labels in the "
            "baked `<inst>/<inst>.py`, and `<inst>/.agent_meta.json`. No roll "
            "and no re-bake."
        ),
        "",
        "## 1. The published hatch share is partly an instrument reading",
        "",
        (
            f"{archive['bake_cannot_record_ops']['attempts']} of "
            f"{archive['labelled_attempts']} "
            f"harness attempts come from rolls whose `.agent_meta.json` carries "
            f"no `{OP_COLLECTION_KEY}` key at all: that era's bridge collected "
            f"`run_python` and nothing else, so those attempts CANNOT show an op "
            f"call however many the agent made. Measured directly on "
            f"`{mechanism['collection_artifact_example']['model_dir']}/"
            f"{mechanism['collection_artifact_example']['instance']}`: "
            f"{mechanism['collection_artifact_example']['dispatched_scene_ops']} "
            f"scene-changing op calls dispatched, every one `ok`, and "
            f"{mechanism['collection_artifact_example']['baked_scene_ops']} op "
            f"labels in the baked script."
        ),
        "",
        "| corpus | attempts | chunks | scene ops | hatch share | attempts using an op |",
        "|---|---|---|---|---|---|",
    ]
    for label, block in (
        ("all rolls, passing", archive["all_rolls"]["passing"]),
        ("all rolls, failing", archive["all_rolls"]["failing"]),
        ("op-collecting rolls, passing", archive["bake_records_ops"]["passing"]),
        ("op-collecting rolls, failing", archive["bake_records_ops"]["failing"]),
    ):
        lines.append(
            f"| {label} | {block['attempts']} | {block['chunks']} | "
            f"{block['scene_ops']} | {_percent(block['hatch_share'])} | "
            f"{block['attempts_using_any_scene_op']} |"
        )
    lines += [
        "",
        (
            "Two further biases in the published counts, both from "
            '`bench_bridge`: `emits_geometry` is "hatch or any facade op", so '
            f"`{OP_COLLECTION_KEY}` counts READER ops "
            f"({archive['baked_reader_ops']} of them across the archive) as "
            "geometry-emitting, and `n_chunks_included` is the label counter, "
            "which advances on op calls too."
        ),
        "",
        "## 2. Op-failure feedback is NOT the mechanism",
        "",
        (
            "The hypothesis: an op call that errors teaches the agent, inside "
            "the run, that `run_python` is the reliable path. It predicts a "
            "higher op failure rate in the multi-turn archive than in "
            "single-shot A1, and a first chunk that FOLLOWS the first op "
            "failure. Both predictions fail."
        ),
        "",
        (
            f"The archive column below is the "
            f"{archive['drop']['attempts']} instrumented attempts whose bake "
            f"COULD collect an op call; pooling the pre-collection rolls in "
            f"would read their instrument blindness as agent failure."
        ),
        "",
        "| quantity | archive (multi-turn) | A1 (single-shot) |",
        "|---|---|---|",
        (
            f"| scene-op calls dispatched | "
            f"{archive['drop']['scene_ops']['dispatched']} | "
            f"{single['drop']['scene_ops']['dispatched']} |"
        ),
        (
            f"| ... never collected by the bake | "
            f"{_percent(archive['drop']['scene_ops']['drop_rate'])} | "
            f"{_percent(single['drop']['scene_ops']['drop_rate'])} |"
        ),
        (
            f"| chunks dispatched | {archive['drop']['chunks']['dispatched']} | "
            f"{single['drop']['chunks']['dispatched']} |"
        ),
        (
            f"| ... never collected by the bake | "
            f"{_percent(archive['drop']['chunks']['drop_rate'])} | "
            f"{_percent(single['drop']['chunks']['drop_rate'])} |"
        ),
        "",
        (
            f"The op path is no less reliable in the archive than in A1. "
            f"Ordering kills the hypothesis outright: of "
            f"{mechanism['chunk_using_attempts']} instrumented attempts that "
            f"used a chunk, "
            f"{mechanism['chunk_using_that_never_called_a_scene_op']} never "
            f"called a scene-changing op at all, and of the "
            f"{mechanism['chunk_using_with_any_op_failure']} that did see an op "
            f"fail, only {mechanism['failure_before_first_chunk']} failed BEFORE "
            f"the first chunk — {mechanism['failure_after_first_chunk']} had "
            f"already switched. "
            f"{_percent(mechanism['first_geometry_call_is_chunk_share'])} of "
            f"instrumented attempts made a chunk their FIRST geometry-emitting "
            f"call. The facade is not abandoned after it breaks; it is never "
            f"entered."
        ),
        "",
        "## 3. What does separate the rolls: the offered set",
        "",
        "| roll | writer | attempts | instrumented | disclosed set | baked op share | dispatched op share |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, entry in sorted(
        measured["per_roll"].items(),
        key=lambda item: -(item[1]["baked_op_share"] or 0.0),
    ):
        lines.append(
            f"| {name} | {entry['writer'] or '—'} | {entry['attempts']} | "
            f"{entry['instrumented']} | {'yes' if entry['offered_disclosed_set'] else 'no'} | "
            f"{_percent(entry['baked_op_share'])} | "
            f"{_percent(entry['dispatched_op_share'])} |"
        )
    lines += [
        "",
        (
            f"Every roll that offered the disclosed set "
            f"(`{measured['disclosed_fingerprint']}`, the "
            f"{measured['disclosed_tool_count']}-of-"
            f"{measured['all_tool_count']} set production offers today) bakes a "
            f"nonzero op share; every roll that predates op collection bakes "
            f"zero, and for the rolls with no tool events at all the "
            f'distinction between "did not call" and "was not recorded" is '
            f"not measurable. A1, single-shot with all "
            f"{measured['all_tool_count']} schemas offered, baked "
            f"{_percent(single['baked']['op_share'])} ops."
        ),
        "",
    ]
    return "\n".join(lines)


def _percent(value) -> str:
    return "—" if value is None else f"{100.0 * value:.1f}%"


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    scene_ops, readers = scene_changing_ops(), reader_op_names()
    disclosed_fingerprint = tool_schemas_fingerprint(
        offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
    )

    rows = archive_rows(bench_root, arguments.results_root, scene_ops, readers)
    unparsed = sum(row["unparsed_events"] for row in rows)
    if unparsed:
        raise SystemExit(f"{unparsed} transcript tool_event block(s) did not parse")
    codes = pass_labels()
    for row in rows:
        row["code"] = codes.get((row["model_dir"], row["instance"]), "")
    labelled = [row for row in rows if row["code"]]
    recording = [row for row in labelled if row["bake_records_ops"]]
    blind = [row for row in labelled if not row["bake_records_ops"]]

    def split(subset):
        return {
            "passing": geometry_split(
                [row for row in subset if row["code"] == "PASS"],
                "baked_chunks",
                "baked_scene_ops",
            ),
            "failing": geometry_split(
                [
                    row
                    for row in subset
                    if row["code"] != "PASS" and row["code"] not in EXCLUDED_CODES
                ],
                "baked_chunks",
                "baked_scene_ops",
            ),
        }

    instrumented = [row for row in rows if row["events"]]
    # A drop rate is only readable where the bake COULD collect an op:
    # pooling the pre-collection rolls in would score their 100%
    # instrument blindness as agent failure, which is the exact error
    # this script exists to expose.
    drop_readable = [row for row in instrumented if row["bake_records_ops"]]
    artifact_example = max(
        (
            row
            for row in rows
            if not row["bake_records_ops"] and row["dispatched_scene_ops"]
        ),
        key=lambda row: row["dispatched_scene_ops"],
    )
    single = single_shot_rows(bench_root, arguments.results_root, scene_ops, readers)
    per_roll = disclosure_table(rows, disclosed_fingerprint)
    assert_probe_varies(per_roll)

    measured = {
        "disclosed_fingerprint": disclosed_fingerprint,
        "disclosed_tool_count": len(
            offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
        ),
        "all_tool_count": len(TOOL_SCHEMAS),
        "archive": {
            "attempts": len(rows),
            "labelled_attempts": len(labelled),
            "instrumented_attempts": len(instrumented),
            "baked_reader_ops": sum(row["baked_reader_ops"] for row in rows),
            "all_rolls": split(labelled),
            "bake_records_ops": split(recording),
            "bake_cannot_record_ops": {
                "attempts": len(blind),
                **split(blind),
            },
            "drop": {
                "attempts": len(drop_readable),
                "scene_ops": drop_rate(
                    drop_readable, "dispatched_scene_ops", "baked_scene_ops"
                ),
                "chunks": drop_rate(drop_readable, "dispatched_chunks", "baked_chunks"),
            },
        },
        "single_shot": {
            "arm": SINGLE_SHOT_ARM,
            "completions": len(single),
            "drop": {
                "scene_ops": drop_rate(
                    single, "dispatched_scene_ops", "baked_scene_ops"
                ),
                "chunks": drop_rate(single, "dispatched_chunks", "baked_chunks"),
            },
            "baked": geometry_split(single, "baked_chunks", "baked_scene_ops"),
            "dispatched": geometry_split(
                single, "dispatched_chunks", "dispatched_scene_ops"
            ),
            "first_geometry_call": {
                "chunk": sum(
                    1
                    for row in single
                    if row["first_chunk_index"] is not None
                    and (
                        row["first_scene_op_index"] is None
                        or row["first_chunk_index"] < row["first_scene_op_index"]
                    )
                ),
                "op": sum(
                    1
                    for row in single
                    if row["first_scene_op_index"] is not None
                    and (
                        row["first_chunk_index"] is None
                        or row["first_scene_op_index"] < row["first_chunk_index"]
                    )
                ),
            },
        },
        "mechanism": {
            **abandonment(rows),
            "collection_artifact_example": {
                "model_dir": artifact_example["model_dir"],
                "instance": artifact_example["instance"],
                "dispatched_scene_ops": artifact_example["dispatched_scene_ops"],
                "dispatched_scene_op_failures": artifact_example[
                    "dispatched_scene_op_failures"
                ],
                "baked_scene_ops": artifact_example["baked_scene_ops"],
            },
        },
        "per_roll": per_roll,
    }
    assert_hypothesis_refuted(
        measured["archive"]["drop"],
        measured["single_shot"]["drop"],
        measured["mechanism"],
    )

    WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    MEASURED_PATH.write_text(json.dumps(measured, indent=2) + "\n")
    PHASE_A_DIRECTORY.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(render_summary(measured))
    print(f"[hatch] wrote {MEASURED_PATH} and {SUMMARY_PATH}", flush=True)
    print(
        f"[hatch] op drop rate archive "
        f"{_percent(measured['archive']['drop']['scene_ops']['drop_rate'])} vs A1 "
        f"{_percent(measured['single_shot']['drop']['scene_ops']['drop_rate'])}; "
        f"first geometry call is a chunk in "
        f"{_percent(measured['mechanism']['first_geometry_call_is_chunk_share'])} "
        f"of instrumented attempts",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
