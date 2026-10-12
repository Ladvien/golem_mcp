#!/usr/bin/env python3
"""Phase C — is a fine-tune even POSSIBLE without new data collection?

    .venv/bin/python scripts/finetune_phase_c.py \\
        --bench-root /Users/ladvien/3dcodebench

Spec §6 of `docs/research/2026-09-19-finetune-decision-experiment.md`:
count what a first SFT run would actually have to train on, from what
this repository already holds. Cheap, runs beside the arms, and it
decides whether the blocker is training or data generation.

Four sources, each counted on its own terms:

* **The benchmark archive** is the real corpus: every archived attempt is
  an (instruction -> script) pair whose instruction is the bench's own
  `data/<inst>/prompt_description.txt` and whose script is the emitted
  `<inst>/<inst>.py`, with an execution status and — where it executed —
  a `cd_pca`. The binding number is NOT the attempt count but the count
  of DISTINCT instructions: the frozen holdout's 20 prompts recur across
  every roll, so 300 attempts can carry 20 instructions.
* **Op-sequence pairs**, which rule 4 of §3 would make the training
  target: recoverable only from attempts whose BAKED script carries
  `# --- op N: name ---` labels for scene-changing ops. Counted off the
  script, never from `.agent_meta.json`: its `n_op_calls_included`
  counts the reader ops as geometry-emitting, and its key is absent on
  rolls whose bridge collected no op calls at all
  (`scripts/finetune_hatch_mechanism.py`).
* **`_evaluate/iterations.jsonl`**, the convergence loop's own records:
  only those carrying schema-2 `tool_events` are minable, and
  `blended.agent.tool_event.decode_tool_event` refuses any other
  version rather than guessing.
* **`logs/chat-*.jsonl`**, the chat transcripts, read through
  `blended.evaluate.candidate_ops.hatch_events_from_transcript` — the
  same reader `scripts/mine_candidate_ops.py` drives, not a second copy.

Plus the op-coverage histogram over all `OP_FUNCTIONS`: an op that never
appears cannot be learned from this corpus, whatever its size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"no dev venv under {REPOSITORY_ROOT / '.venv'}")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from finetune_decision_thresholds import (
    CD_PCA_PASS,
    SFT_PAIRS_COMFORTABLE,
    SFT_PAIRS_MINIMUM,
)
from finetune_phase_a import baked_call_counts

PHASE_C_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseC"
)
WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
ITERATIONS_LOG = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"
TRANSCRIPT_GLOB = "chat-*.jsonl"
# An op seen fewer times than this cannot carry its own behaviour into a
# fine-tune: the reference point is BlendNet's per-operation coverage
# (arXiv:2412.14203, DOI 10.48550/arXiv.2412.14203), and 20 is the
# spec's own "appears fewer than 20 times" line.
OP_COVERAGE_THIN = 20


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    return parser.parse_args(argv)


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def archive_pairs(bench_root: Path, results_root_argument: str) -> dict:
    """Every (instruction -> script) pair the bench archive holds."""
    results_root = bench_root / results_root_argument
    pairs = []
    for model_root in sorted(results_root.iterdir()):
        if not model_root.is_dir() or model_root.name.startswith("ft-"):
            continue
        for directory in sorted(model_root.iterdir()):
            if not directory.is_dir():
                continue
            instance = directory.name
            script_path = directory / f"{instance}.py"
            prompt_path = bench_root / "data" / instance / "prompt_description.txt"
            if not script_path.exists() or not prompt_path.exists():
                continue
            log = read_json(directory / "renders" / "render_log.json") or {}
            meta = read_json(directory / ".agent_meta.json") or {}
            script_text = script_path.read_text()
            pairs.append(
                {
                    "model_dir": model_root.name,
                    "instance": instance,
                    "script_sha256": hashlib.sha256(script_text.encode()).hexdigest(),
                    "script_chars": len(script_text),
                    "render_status": log.get("status", "MISSING"),
                    "has_glb": (directory / "glb" / f"{instance}.glb").exists(),
                    "bake_records_ops": "n_op_calls_included" in meta,
                    **baked_call_counts(script_path),
                    "writer": meta.get("writer") or meta.get("model") or "",
                }
            )
    scores = load_archived_scores()
    for pair in pairs:
        pair["cd_pca"] = scores.get((pair["model_dir"], pair["instance"]))
    return {"pairs": pairs}


def load_archived_scores() -> dict:
    """(model_dir, instance) -> cd_pca, from every archived diagnose JSON."""
    scores: dict[tuple[str, str], float] = {}
    for directory in (REPOSITORY_ROOT / "outputs" / "bench", WORKING_DIRECTORY):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("diagnose_*.json")):
            data = read_json(path)
            if not data:
                continue
            model_dir = data.get("model_dir", "")
            for row in data.get("per_instance", []):
                if row.get("cd_pca") is not None:
                    scores[(model_dir, row["instance"])] = row["cd_pca"]
    return scores


def summarise_pairs(pairs: list[dict]) -> dict:
    executed = [pair for pair in pairs if pair["render_status"] == "OK"]
    scored = [pair for pair in pairs if pair["cd_pca"] is not None]
    passing = [pair for pair in scored if pair["cd_pca"] <= CD_PCA_PASS]
    deduplicated = {(pair["instance"], pair["script_sha256"]) for pair in pairs}
    verified_dedup = {(pair["instance"], pair["script_sha256"]) for pair in executed}
    return {
        "pairs": len(pairs),
        "executed": len(executed),
        "scored": len(scored),
        "passing": len(passing),
        "deduplicated_pairs": len(deduplicated),
        "deduplicated_execution_verified_pairs": len(verified_dedup),
        "distinct_instructions": len({pair["instance"] for pair in pairs}),
        "distinct_instructions_executed": len({pair["instance"] for pair in executed}),
        "op_sequence_pairs": sum(
            1
            for pair in pairs
            if pair["bake_records_ops"] and pair["baked_scene_ops"] > 0
        ),
        "scene_op_calls_baked": sum(
            pair["baked_scene_ops"] for pair in pairs if pair["bake_records_ops"]
        ),
        "chunks_baked": sum(
            pair["baked_chunks"] for pair in pairs if pair["bake_records_ops"]
        ),
        "pairs_before_op_collection": sum(
            1 for pair in pairs if not pair["bake_records_ops"]
        ),
        "writers": dict(Counter(pair["writer"] for pair in pairs if pair["writer"])),
    }


def iteration_records() -> dict:
    """What the convergence log holds, and how much of it is minable."""
    from blended.agent.tool_event import (
        TOOL_EVENT_SCHEMA_VERSION,
        decode_tool_event,
    )

    if not ITERATIONS_LOG.exists():
        return {"records": 0, "with_tool_events": 0, "decodable_events": 0}
    records = [
        json.loads(line)
        for line in ITERATIONS_LOG.read_text().splitlines()
        if line.strip()
    ]
    with_events = [record for record in records if record.get("tool_events")]
    decodable = 0
    refused = 0
    tools = Counter()
    for record in with_events:
        for event in record["tool_events"]:
            try:
                decoded = decode_tool_event(json.dumps(event))
            except ValueError:
                refused += 1
                continue
            decodable += 1
            tools[decoded.tool_name] += 1
    return {
        "schema_version": TOOL_EVENT_SCHEMA_VERSION,
        "records": len(records),
        "with_tool_events": len(with_events),
        "decodable_events": decodable,
        "refused_events": refused,
        "tool_histogram": dict(tools.most_common()),
        "scored_success_records": sum(
            1
            for record in records
            if record.get("structural_ok") and record.get("form_ok")
        ),
    }


def transcript_hatches() -> dict:
    """Hatch invocations in the chat transcripts, grouped by reason."""
    from blended.evaluate.candidate_ops import (
        UnminableRecord,
        hatch_events_from_transcript,
        normalize_reason,
    )

    log_directory = REPOSITORY_ROOT / "logs"
    if not log_directory.is_dir():
        return {"transcripts": 0, "minable": 0, "events": 0, "reasons": {}}
    paths = sorted(log_directory.glob(TRANSCRIPT_GLOB))
    minable = 0
    events = []
    for path in paths:
        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        try:
            found = hatch_events_from_transcript(path.name, rows)
        except UnminableRecord:
            continue
        minable += 1
        events.extend(found)
    return {
        "transcripts": len(paths),
        "minable": minable,
        "events": len(events),
        "reasons": dict(
            Counter(normalize_reason(event.reason) for event in events).most_common(15)
        ),
    }


def op_coverage(iterations: dict, scripts: dict) -> dict:
    """How much of the 48-op facade this corpus actually exercises.

    The corpus is both halves counted on their own terms: the decoded
    tool events of the convergence log, and the ops the archived scripts
    call (`op_calls_in_scripts`, read off the emitted text).
    """
    from blended.agent.tools import OP_FUNCTIONS

    seen = Counter()
    for histogram in (iterations.get("tool_histogram", {}), scripts["histogram"]):
        for name, count in histogram.items():
            if name in OP_FUNCTIONS:
                seen[name] += count
    return {
        "ops_total": len(OP_FUNCTIONS),
        "ops_seen": len([name for name in OP_FUNCTIONS if seen.get(name)]),
        "ops_thin": len(
            [name for name in OP_FUNCTIONS if 0 < seen.get(name, 0) < OP_COVERAGE_THIN]
        ),
        "ops_unseen": sorted(name for name in OP_FUNCTIONS if not seen.get(name)),
        "histogram": dict(seen.most_common()),
    }


def op_calls_in_scripts(bench_root: Path, results_root_argument: str) -> dict:
    """Which ops the archived SCRIPTS call, read from the emitted text.

    The bridge writes every op call as `_op('<name>', {...})`, so the
    scripts themselves are the ground truth for op coverage in the
    benchmark corpus — `.agent_meta.json` only counts them.
    """
    from blended.agent.tools import OP_FUNCTIONS
    from blended.evaluate.bench_bridge import OP_HELPER_NAME

    results_root = bench_root / results_root_argument
    seen = Counter()
    attempts_with_ops = 0
    for model_root in sorted(results_root.iterdir()):
        if not model_root.is_dir() or model_root.name.startswith("ft-"):
            continue
        for directory in sorted(model_root.iterdir()):
            script_path = directory / f"{directory.name}.py"
            if not script_path.is_file():
                continue
            text = script_path.read_text()
            found = Counter()
            for name in OP_FUNCTIONS:
                needle = f"{OP_HELPER_NAME}({name!r},"
                count = text.count(needle)
                if count:
                    found[name] += count
            if found:
                attempts_with_ops += 1
                seen.update(found)
    return {
        "attempts_with_op_calls": attempts_with_ops,
        "op_calls": sum(seen.values()),
        "ops_seen": len(seen),
        "histogram": dict(seen.most_common()),
    }


def verdict(measured: dict) -> tuple[str, str]:
    """(one-word verdict, the sentence the report prints.)"""
    usable = measured["archive"]["deduplicated_execution_verified_pairs"]
    instructions = measured["archive"]["distinct_instructions_executed"]
    if usable >= SFT_PAIRS_MINIMUM and instructions >= SFT_PAIRS_MINIMUM:
        return "sufficient", (
            f"{usable} deduplicated execution-verified pairs over "
            f"{instructions} distinct instructions clears the "
            f"{SFT_PAIRS_MINIMUM}-{SFT_PAIRS_COMFORTABLE} a first SFT run needs."
        )
    shortfall = SFT_PAIRS_MINIMUM / max(instructions, 1)
    return "insufficient", (
        f"{usable} deduplicated execution-verified pairs, but only "
        f"{instructions} DISTINCT instructions — {shortfall:.0f}x short of the "
        f"{SFT_PAIRS_MINIMUM} a first SFT run needs, and duplicate "
        f"instructions do not add information. The blocker is data "
        f"GENERATION, not training."
    )


def render_report(measured: dict) -> str:
    archive = measured["archive"]
    iterations = measured["iterations"]
    transcripts = measured["transcripts"]
    scripts = measured["op_calls_in_scripts"]
    coverage = measured["op_coverage"]
    label, sentence = verdict(measured)
    lines = [
        "# Phase C — training-corpus inventory",
        "",
        f"**Data-sufficiency verdict: {label.upper()}.** {sentence}",
        "",
        "## The benchmark archive as an instruction -> script corpus",
        "",
        "| quantity | count |",
        "|---|---|",
        f"| (instruction, script) pairs | {archive['pairs']} |",
        f"| ... that executed (`render_log.status == OK`) | {archive['executed']} |",
        f"| ... that carry a `cd_pca` | {archive['scored']} |",
        f"| ... that pass at `cd_pca <= {CD_PCA_PASS}` | {archive['passing']} |",
        (
            f"| deduplicated on (instance, sha256(script)) | "
            f"{archive['deduplicated_pairs']} |"
        ),
        (
            f"| ... and execution-verified | "
            f"{archive['deduplicated_execution_verified_pairs']} |"
        ),
        f"| **distinct instructions** | {archive['distinct_instructions']} |",
        (
            f"| ... with at least one executing script | "
            f"{archive['distinct_instructions_executed']} |"
        ),
        "",
        (
            "The distinct-instruction row is the binding one: the frozen "
            "holdout is 20 prompts and every roll answers the same 20, so "
            "pair counts grow without adding instructions."
        ),
        "",
        "## Op-sequence pairs (the target rule 4 would name)",
        "",
        (
            f"- attempts whose emitted script calls any facade op (reader "
            f"ops included): **{scripts['attempts_with_op_calls']}**"
        ),
        f"- op calls in those scripts: **{scripts['op_calls']}**",
        (
            f"- distinct ops exercised: **{scripts['ops_seen']}** of "
            f"{coverage['ops_total']}"
        ),
        (
            f"- baked `run_python` chunks against baked scene-changing op "
            f"calls, over the pairs whose bridge could record an op: "
            f"**{archive['chunks_baked']}** against "
            f"**{archive['scene_op_calls_baked']}**; "
            f"{archive['pairs_before_op_collection']} earlier pairs come from "
            f"a bridge that collected no op calls, so their chunk counts are "
            f"not comparable"
        ),
        "",
        "## Convergence log (`_evaluate/iterations.jsonl`)",
        "",
        f"- records: **{iterations['records']}**",
        (
            f"- records carrying schema-{iterations.get('schema_version')} "
            f"`tool_events`: **{iterations['with_tool_events']}**"
        ),
        (
            f"- decodable tool events: **{iterations['decodable_events']}** "
            f"({iterations['refused_events']} refused by `decode_tool_event`)"
        ),
        (
            f"- records with structural and form gates green: "
            f"**{iterations['scored_success_records']}**"
        ),
        "",
        "## Chat transcripts (`logs/chat-*.jsonl`)",
        "",
        f"- transcripts: **{transcripts['transcripts']}**",
        f"- minable (schema-2 tool-event rows): **{transcripts['minable']}**",
        f"- hatch invocations: **{transcripts['events']}**",
        "",
        "Top hatch reasons, normalised:",
        "",
        "| reason | invocations |",
        "|---|---|",
    ]
    for reason, count in transcripts["reasons"].items():
        lines.append(f"| {reason or '(none given)'} | {count} |")
    lines += [
        "",
        "## Op coverage over the whole facade",
        "",
        f"- ops in the facade: **{coverage['ops_total']}**",
        (
            f"- ops appearing anywhere in the archived scripts or the "
            f"convergence log: **{coverage['ops_seen']}**"
        ),
        (
            f"- ops appearing fewer than {OP_COVERAGE_THIN} times: "
            f"**{coverage['ops_thin']}**"
        ),
        f"- ops never appearing: **{len(coverage['ops_unseen'])}**",
        "",
        "Ops the corpus never exercises, and therefore cannot teach:",
        "",
        "```",
        ", ".join(coverage["ops_unseen"]) or "(none)",
        "```",
        "",
        "## Reference point",
        "",
        (
            "BlendNet: 8,000 instruction->script pairs (2,000 "
            "human-annotated, 6,000 model-validated); the BlenderLLM "
            "self-improvement rounds used ~2,000 samples each "
            "(arXiv:2412.14203, DOI 10.48550/arXiv.2412.14203). A usable "
            f"first SFT run needs roughly {SFT_PAIRS_MINIMUM}-"
            f"{SFT_PAIRS_COMFORTABLE} deduplicated, execution-verified pairs."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    pairs = archive_pairs(bench_root, arguments.results_root)["pairs"]
    iterations = iteration_records()
    scripts_measured = op_calls_in_scripts(bench_root, arguments.results_root)
    measured = {
        "archive": summarise_pairs(pairs),
        "iterations": iterations,
        "transcripts": transcript_hatches(),
        "op_calls_in_scripts": scripts_measured,
        "op_coverage": op_coverage(iterations, scripts_measured),
    }
    PHASE_C_DIRECTORY.mkdir(parents=True, exist_ok=True)
    WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (PHASE_C_DIRECTORY / "corpus_inventory.md").write_text(render_report(measured))
    (WORKING_DIRECTORY / "phase_c_measured.json").write_text(
        json.dumps(measured, indent=2) + "\n"
    )
    label, sentence = verdict(measured)
    print(f"[phaseC] verdict: {label} — {sentence}", flush=True)
    print(f"[phaseC] wrote {PHASE_C_DIRECTORY / 'corpus_inventory.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
