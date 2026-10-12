#!/usr/bin/env python3
"""Phase A — failure taxonomy of the archived 3DCodeBench rolls.

    .venv/bin/python scripts/finetune_phase_a.py \\
        --bench-root /Users/ladvien/3dcodebench

Answers the spec's Q1 (`docs/research/2026-09-19-finetune-decision-experiment.md`
§4): are this harness's failures syntactic/API ("how to say it") or
spatial/semantic ("what to build")? Fine-tuning reliably improves the
first and does not reliably improve the second, so `F_syntax` and
`F_geom` are what §3's rules 1-3 read.

No fresh roll is needed: the archive already holds far more than the
spec's `N >= 100` precondition. Every attempt is classified from
artifacts the rolls already carry —
`<inst>/renders/render_log.json` (the executability measurement, failure
included), `<inst>/.agent_meta.json` (what the agent lane did) and the
per-instance scores from `scripts/diagnose_3dcode.py --json` plus
`scripts/shape_error_decompose.py --json`.

Three decisions worth stating, because a different choice moves the
numbers:

* G1 vs G2 is decided by the METRIC DECOMPOSITION, not by a VLM. The
  decomposition is ground truth against the reference mesh and is
  reproducible; no §3 rule reads the interior split of `F_geom`. This is
  a stated deviation from spec §4, which proposed a VLM for all of
  G1-G3. G3 — "plausible, misses an explicit instruction constraint" —
  still needs the renders and the prompt, and that is the one judged
  sample (`--judge-sample`, default 0 here; run it explicitly).
* `INFRA` rows are excluded from BOTH the numerator and the denominator
  and listed separately. They are bake-environment artifacts, not model
  failures: a stale installed-addon import of the harness, a path inside
  Blender's application-support tree, a foreign absolute path.
* `E7` (an executed-path Python error matching none of E1-E4) counts
  inside `F_syntax`. The spec's enumeration has no bucket for it, and it
  is a code-writing failure — the class SFT on verified scripts
  addresses.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
from bench_thresholds import ORIENT_ARTIFACT_THRESHOLD
from finetune_decision_thresholds import (
    CD_PCA_PASS,
    DEGENERATE_CODE,
    EXCLUDED_CODES,
    GEOMETRY_CODES,
    INFRASTRUCTURE_CODE,
    INSTANCES_FILE,
    SYNTAX_CODES,
    UNSCORED_CODE,
    is_infrastructure,
)

HARNESS_DIR_PREFIX = "blended-"
# A dir with fewer attempts than this is a smoke run, not a roll.
MINIMUM_ATTEMPTS_PER_ROLL = 10
# Reported beside the harness rolls, never pooled with them: it is a
# third-party row and its one failure names a foreign absolute path.
THIRD_PARTY_DIRS = ("baseline-opus",)
ARCHIVED_DIAGNOSE_DIRECTORY = REPOSITORY_ROOT / "outputs" / "bench"
WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
PHASE_A_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseA"
)
# Half the excess over the pass bar: if perfect per-axis proportions
# recover at least this much, the shape class is right and the
# proportions are wrong, which is G2 rather than G1.
G2_ORACLE_RECOVERY_SHARE = 0.5

# --- Ordered error patterns, first match wins -----------------------------
#
# E1-E4 are the spec's own detections. E2 additionally accepts the
# benchmark's own `B5-API` verdict, so a Blender-4-vs-5 API drift that
# the bench already recognises cannot land in E7.
E1_PATTERNS = (re.compile(r"\b(SyntaxError|IndentationError|TabError)\b"),)
E2_PATTERNS = (
    re.compile(r"AttributeError:.*\bbpy\b"),
    re.compile(r"AttributeError: (?:BMeshOpsModule|Module)"),
    re.compile(r"unknown operator", re.IGNORECASE),
    re.compile(r"enum \".*\" not found"),
    re.compile(r"AttributeError:.*object has no attribute"),
    re.compile(r"ImportError: cannot import name"),
    re.compile(r"RuntimeError: Error: Node type \w+ undefined"),
)
E3_PATTERNS = (
    re.compile(r"\bTypeError\b"),
    re.compile(r"unexpected keyword"),
    re.compile(r"keyword \".*\" unrecognized"),
    re.compile(r"keyword \".*\" is invalid"),
)
E4_PATTERNS = (
    re.compile(r"poll\(\)"),
    re.compile(r"context is incorrect"),
    re.compile(r"execution context is supported"),
    re.compile(r"no active object", re.IGNORECASE),
    re.compile(r"(Object|Mode) is not in (Edit|Object) mode", re.IGNORECASE),
    re.compile(r"expected a \w+ type for parameter", re.IGNORECASE),
)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument(
        "--judge-sample",
        type=int,
        default=0,
        help="How many non-passing executed attempts to send to the eye for "
        "G3. 0 skips the judge; the taxonomy is complete without it and "
        "G3 only re-labels rows already inside F_geom.",
    )
    parser.add_argument("--refresh-scores", action="store_true")
    return parser.parse_args(argv)


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def instance_directories(model_root: Path) -> list[Path]:
    return sorted(
        directory
        for directory in model_root.iterdir()
        if directory.is_dir() and (directory / "renders" / "render_log.json").exists()
    )


def included_model_dirs(results_root: Path) -> tuple[list[str], list[str]]:
    """(harness rolls, third-party rows), each with enough attempts to count."""
    harness, third_party = [], []
    for directory in sorted(results_root.iterdir()):
        if not directory.is_dir():
            continue
        if len(instance_directories(directory)) < MINIMUM_ATTEMPTS_PER_ROLL:
            continue
        if directory.name in THIRD_PARTY_DIRS:
            third_party.append(directory.name)
        elif directory.name.startswith(HARNESS_DIR_PREFIX):
            harness.append(directory.name)
    return harness, third_party


def instances_file_for(model_root: Path, model_dir: str) -> Path:
    """The instance list this dir is scored on.

    The frozen holdout when the dir holds exactly it; otherwise the dir's
    own instances, written out — a dev roll is a different set and
    scoring it against the holdout would drop rows silently.
    """
    holdout = [
        line.strip()
        for line in (REPOSITORY_ROOT / INSTANCES_FILE).read_text().splitlines()
        if line.strip()
    ]
    present = [directory.name for directory in instance_directories(model_root)]
    if set(present) == set(holdout):
        return REPOSITORY_ROOT / INSTANCES_FILE
    WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = WORKING_DIRECTORY / f"instances_{model_dir}.txt"
    path.write_text("\n".join(sorted(present)) + "\n")
    return path


def scored_instances_file(
    bench_root: Path, model_root: Path, model_dir: str
) -> Path | None:
    """Instances with BOTH a reference and a generated GLB.

    `shape_error_decompose` treats a missing cloud as fatal, on purpose,
    so the oracle is asked only about attempts that produced a mesh.
    """
    usable = [
        directory.name
        for directory in instance_directories(model_root)
        if (directory / "glb" / f"{directory.name}.glb").exists()
        and (
            bench_root / "data" / directory.name / "glb" / f"{directory.name}.glb"
        ).exists()
    ]
    if not usable:
        return None
    WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = WORKING_DIRECTORY / f"decomposable_{model_dir}.txt"
    path.write_text("\n".join(sorted(usable)) + "\n")
    return path


def bench_python(bench_root: Path) -> Path:
    python = bench_root / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(f"no bench venv at {python}")
    return python


def run(command: list[str], cwd: Path | None = None) -> int:
    print(f"[phaseA] {' '.join(str(part) for part in command)}", flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def diagnose_rows(
    bench_root: Path,
    results_root_argument: str,
    model_root: Path,
    model_dir: str,
    refresh: bool,
) -> tuple[dict, str]:
    """Per-instance scores, from the archive when it has them."""
    archived = ARCHIVED_DIAGNOSE_DIRECTORY / f"diagnose_{model_dir}.json"
    if archived.exists() and not refresh:
        data = read_json(archived)
        if data:
            return (
                {row["instance"]: row for row in data["per_instance"]},
                "archived",
            )
    generated = WORKING_DIRECTORY / f"diagnose_{model_dir}.json"
    if not generated.exists() or refresh:
        WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
        code = run(
            [
                str(bench_python(bench_root)),
                str(REPOSITORY_ROOT / "scripts" / "diagnose_3dcode.py"),
                "--bench-root",
                str(bench_root),
                "--results-root",
                results_root_argument,
                "--model-dir",
                model_dir,
                "--instances-file",
                str(instances_file_for(model_root, model_dir)),
                "--out",
                str(WORKING_DIRECTORY / f"diagnose_{model_dir}.md"),
                "--json",
                str(generated),
            ],
            cwd=REPOSITORY_ROOT,
        )
        if code != 0:
            print(f"[phaseA] diagnose failed on {model_dir} (exit {code})", flush=True)
            return {}, "unscored"
    data = read_json(generated)
    return (
        {row["instance"]: row for row in data["per_instance"]} if data else {}
    ), "generated"


def decompose_rows(
    bench_root: Path,
    results_root_argument: str,
    model_root: Path,
    model_dir: str,
    refresh: bool,
) -> dict:
    """`cd_pca_aspect_oracle` per instance: the G1/G2 separator."""
    path = WORKING_DIRECTORY / f"decompose_{model_dir}.json"
    if not path.exists() or refresh:
        instances_file = scored_instances_file(bench_root, model_root, model_dir)
        if instances_file is None:
            return {}
        code = run(
            [
                str(bench_python(bench_root)),
                str(REPOSITORY_ROOT / "scripts" / "shape_error_decompose.py"),
                "--bench-root",
                str(bench_root),
                "--results-root",
                results_root_argument,
                "--model-dir",
                model_dir,
                "--instances-file",
                str(instances_file),
                "--out",
                str(WORKING_DIRECTORY / f"decompose_{model_dir}.md"),
                "--json",
                str(path),
            ],
            cwd=REPOSITORY_ROOT,
        )
        if code != 0:
            print(f"[phaseA] decompose failed on {model_dir} (exit {code})", flush=True)
            return {}
    data = read_json(path)
    return {row["instance"]: row for row in data["per_instance"]} if data else {}


def matches(patterns, text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


def classify(attempt: dict) -> str:
    """The spec's code for one attempt. Ordered; first match wins."""
    error = attempt["error_text"]
    if is_infrastructure(error) or is_infrastructure(attempt["agent_error"]):
        return INFRASTRUCTURE_CODE
    agent_status = attempt["agent_status"]
    if agent_status in ("ERR_MODEL_CALL", "ERR_CONNECTION", "ERR_NO_SCRIPT"):
        return "O2"
    render_status = attempt["render_status"]
    if render_status in ("ERR_TIMEOUT", "ERR_NOLOG", "MISSING"):
        return "E5"
    if render_status == "ERR_NO_MESH" or (
        render_status == "OK" and not attempt["n_meshes"]
    ):
        return DEGENERATE_CODE
    if render_status in ("ERR_EXEC", "ERR_PARSE"):
        if matches(E1_PATTERNS, error):
            return "E1"
        if attempt["b5_category"] == "B5-API" or matches(E2_PATTERNS, error):
            return "E2"
        if matches(E3_PATTERNS, error):
            return "E3"
        if matches(E4_PATTERNS, error) or attempt["b5_category"] == "CTX":
            return "E4"
        return "E7"
    if render_status != "OK":
        return "E5"
    # Executed and produced a mesh: the score decides.
    cd_pca = attempt["cd_pca"]
    if cd_pca is None:
        # Executed and left a mesh, but the roll carries no score for it.
        # Measured on `blended-deepseek-v4-pro-ops-roll1`: all 20 rows
        # have `cd_pca: null` in both the archived diagnose JSON and the
        # dir's own `_metrics/shape_chamfer.json`, because that roll is
        # the documented VOID one whose chain never ran the bench's bake
        # (BACKLOG.md, OT-9 roll 1). Re-baking it TODAY would not repair
        # the archive: the parity gate measured that a re-bake
        # reproduces the solid but not the tessellation, so a fresh
        # score would not be the score this roll would have had. So the
        # attempt is EXCLUDED and listed, in neither share — an analysis
        # gap, not a model failure and not an infrastructure failure.
        return UNSCORED_CODE
    if cd_pca <= CD_PCA_PASS:
        return "PASS"
    if attempt["delta_orient"] is not None and (
        attempt["delta_orient"] >= ORIENT_ARTIFACT_THRESHOLD
    ):
        return "G2"
    oracle = attempt["cd_pca_aspect_oracle"]
    if oracle is not None:
        excess = cd_pca - CD_PCA_PASS
        if excess > 0 and (cd_pca - oracle) >= G2_ORACLE_RECOVERY_SHARE * excess:
            return "G2"
    return "G1"


def baked_call_counts(script_path: Path) -> dict:
    """What the bridge collected, read off the baked script's labels.

    `standalone_script` writes `# --- chunk N ---` for a hatch call and
    `# --- op N: name ---` for a facade op (both gain a
    "raised in the run after changing the scene" suffix when the call
    raised after mutating the scene, so the patterns are prefix-only).
    """
    if not script_path.exists():
        return {"baked_chunks": 0, "baked_scene_ops": 0, "baked_reader_ops": 0}
    from blended.ops._contract import changes_scene, facade_ops

    scene = {name for name, function in facade_ops() if changes_scene(function)}
    text = script_path.read_text(errors="replace")
    names = re.findall(r"^# --- op \d+: ([a-z_0-9]+)", text, flags=re.MULTILINE)
    return {
        "baked_chunks": len(re.findall(r"^# --- chunk \d+", text, flags=re.MULTILINE)),
        "baked_scene_ops": sum(1 for name in names if name in scene),
        "baked_reader_ops": sum(1 for name in names if name not in scene),
    }


def collect(bench_root: Path, results_root_argument: str, refresh: bool) -> list[dict]:
    results_root = bench_root / results_root_argument
    harness, third_party = included_model_dirs(results_root)
    print(
        f"[phaseA] {len(harness)} harness roll(s), "
        f"{len(third_party)} third-party row(s)",
        flush=True,
    )
    sys.path.insert(0, str(bench_root / "metrics"))
    import failure_taxonomy as bench_taxonomy  # the bench's own instrument

    attempts: list[dict] = []
    for model_dir in harness + third_party:
        model_root = results_root / model_dir
        scores, provenance = diagnose_rows(
            bench_root, results_root_argument, model_root, model_dir, refresh
        )
        oracles = decompose_rows(
            bench_root, results_root_argument, model_root, model_dir, refresh
        )
        for directory in instance_directories(model_root):
            instance = directory.name
            log = read_json(directory / "renders" / "render_log.json") or {}
            meta = read_json(directory / ".agent_meta.json") or {}
            score = scores.get(instance, {})
            oracle = oracles.get(instance, {})
            error_text = str(log.get("error") or "")
            attempt = {
                "model_dir": model_dir,
                "instance": instance,
                "third_party": model_dir in third_party,
                "score_provenance": provenance,
                "writer": meta.get("writer") or meta.get("model") or "",
                "render_status": log.get("status", "MISSING"),
                "agent_status": meta.get("status", ""),
                "agent_error": str(meta.get("error") or ""),
                "error_text": error_text,
                "error_fingerprint": bench_taxonomy.fingerprint(error_text),
                "b5_category": (
                    bench_taxonomy.categorize(error_text) if error_text else ""
                ),
                "n_meshes": log.get("n_meshes") or 0,
                "latency_s": log.get("latency_s"),
                "cd_pca": score.get("cd_pca"),
                "cd_yawmin": score.get("cd_yawmin"),
                "delta_orient": score.get("delta_orient"),
                "fscore_005": score.get("fscore_005"),
                "cd_pca_aspect_oracle": oracle.get("cd_pca_aspect_oracle"),
                "num_turns": meta.get("num_turns"),
                "duration_s": meta.get("duration_s"),
                # Ground truth for what the score saw, and whether this
                # roll's bridge could record an op at all.
                "bake_records_ops": "n_op_calls_included" in meta,
                **baked_call_counts(directory / f"{instance}.py"),
            }
            attempt["code"] = classify(attempt)
            attempts.append(attempt)
    return attempts


def shares(attempts: list[dict]) -> dict:
    """`F_syntax` and `F_geom` over FAILURES, INFRA excluded entirely."""
    counted = [
        attempt
        for attempt in attempts
        if not attempt["third_party"] and attempt["code"] not in EXCLUDED_CODES
    ]
    failures = [attempt for attempt in counted if attempt["code"] != "PASS"]
    syntax = [attempt for attempt in failures if attempt["code"] in SYNTAX_CODES]
    geometry = [attempt for attempt in failures if attempt["code"] in GEOMETRY_CODES]
    degenerate = [attempt for attempt in failures if attempt["code"] == DEGENERATE_CODE]
    total = len(failures)
    return {
        "attempts_counted": len(counted),
        "passes": len(counted) - total,
        "failures": total,
        "n_syntax": len(syntax),
        "n_geom": len(geometry),
        "n_degenerate": len(degenerate),
        "f_syntax": (len(syntax) / total) if total else None,
        "f_geom": (len(geometry) / total) if total else None,
        "f_degenerate": (len(degenerate) / total) if total else None,
    }


def hatch_table(attempts: list[dict]) -> dict:
    """Op calls against `run_python` chunks, from the BAKED script.

    Not from `.agent_meta.json`, and the difference is large enough to
    change the finding (measured 2026-09-19,
    `scripts/finetune_hatch_mechanism.py`). `emits_geometry` is "the
    hatch or ANY facade op", so `n_op_calls_included` counts the 14
    reader ops as geometry-emitting, and `n_chunks_included` is the
    label COUNTER, which advances on op calls too. The baked script's
    own `# --- chunk N ---` and `# --- op N: name ---` labels are what
    the score actually saw.

    A roll whose meta carries no `n_op_calls_included` key predates op
    collection in the bridge: its script CANNOT hold an op call however
    many the agent made (measured: ops-roll1/Tap_seed0 dispatched 13
    scene-changing ops, all `ok`, and baked none). Those attempts are
    reported separately instead of being averaged in at a forced 100%.
    """
    table = {}
    for label, rows in (
        (
            "passing",
            [a for a in attempts if a["code"] == "PASS" and not a["third_party"]],
        ),
        (
            "failing",
            [
                a
                for a in attempts
                if a["code"] not in ("PASS", *EXCLUDED_CODES) and not a["third_party"]
            ],
        ),
    ):
        recording = [row for row in rows if row["bake_records_ops"]]
        chunks = sum(row["baked_chunks"] or 0 for row in recording)
        ops = sum(row["baked_scene_ops"] or 0 for row in recording)
        blind = [row for row in rows if not row["bake_records_ops"]]
        table[label] = {
            "attempts": len(rows),
            "attempts_collecting_ops": len(recording),
            "attempts_before_op_collection": len(blind),
            "chunks_before_op_collection": sum(
                row["baked_chunks"] or 0 for row in blind
            ),
            "included_chunks": chunks,
            "op_calls": ops,
            "reader_op_calls": sum(row["baked_reader_ops"] or 0 for row in recording),
            "attempts_using_any_op": sum(
                1 for row in recording if (row["baked_scene_ops"] or 0) > 0
            ),
            "hatch_share": (chunks / (chunks + ops)) if (chunks + ops) else None,
        }
    return table


CSV_COLUMNS = (
    "model_dir",
    "instance",
    "writer",
    "render_status",
    "agent_status",
    "code",
    "b5_category",
    "error_fingerprint",
    "cd_pca",
    "cd_yawmin",
    "delta_orient",
    "fscore_005",
    "cd_pca_aspect_oracle",
    "baked_scene_ops",
    "baked_chunks",
    "score_provenance",
    "third_party",
    "excluded_reason",
)


def write_csv(attempts: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for attempt in attempts:
            row = {column: attempt.get(column, "") for column in CSV_COLUMNS}
            if attempt["code"] == INFRASTRUCTURE_CODE:
                reason = (
                    attempt["error_fingerprint"][:120] or attempt["agent_error"][:120]
                )
            elif attempt["code"] == UNSCORED_CODE:
                reason = "executed, but this roll carries no cd_pca"
            elif attempt["third_party"]:
                reason = "third-party row"
            else:
                reason = ""
            row["excluded_reason"] = reason
            writer.writerow(row)


def render_summary(attempts: list[dict], measured: dict) -> str:
    harness = [a for a in attempts if not a["third_party"]]
    third_party = [a for a in attempts if a["third_party"]]
    codes = Counter(a["code"] for a in harness)
    primary = [a for a in harness if a["score_provenance"] == "archived"]
    lines = [
        "# Phase A — failure taxonomy of the archived rolls",
        "",
        (
            f"Attempts with a render log: **{len(harness)}** across "
            f"{len({a['model_dir'] for a in harness})} harness roll(s); "
            f"{len(third_party)} third-party attempt(s) reported separately "
            f"and never pooled."
        ),
        "",
        (
            f"Denominators: *primary* = attempts whose per-instance scores "
            f"were already archived by an earlier `diagnose_3dcode.py --json` "
            f"run ({len(primary)} attempts, "
            f"{len({a['model_dir'] for a in primary})} rolls); *secondary* = "
            f"every included attempt ({len(harness)})."
        ),
        "",
        "## Codes",
        "",
        "| code | attempts | share of failures |",
        "|---|---|---|",
    ]
    failures = measured["failures"]
    for code, count in sorted(codes.items(), key=lambda item: (-item[1], item[0])):
        share = (
            "—"
            if code in ("PASS", *EXCLUDED_CODES) or not failures
            else (f"{100.0 * count / failures:.1f}%")
        )
        lines.append(f"| {code} | {count} | {share} |")
    lines += [
        "",
        "## The two shares §3 reads",
        "",
        (
            f"- attempts counted (INFRA and UNSCORED excluded): "
            f"**{measured['attempts_counted']}**"
        ),
        f"- passes (`cd_pca <= {CD_PCA_PASS}`): **{measured['passes']}**",
        f"- failures: **{measured['failures']}**",
        (
            f"- `F_syntax` = {measured['n_syntax']}/{measured['failures']} = "
            f"**{_percent(measured['f_syntax'])}** (E1-E5, E7, O1-O2)"
        ),
        (
            f"- `F_geom` = {measured['n_geom']}/{measured['failures']} = "
            f"**{_percent(measured['f_geom'])}** (G1-G3)"
        ),
        (
            f"- `E6` (executed, degenerate) = {measured['n_degenerate']}/"
            f"{measured['failures']} = {_percent(measured['f_degenerate'])} — "
            f"in neither share by the spec's own definitions, so the two do "
            f"not sum to 100%."
        ),
        "",
        "## Excluded, in neither share",
        "",
        (
            "Two exclusions, both pre-registered before the shares were "
            "read: `INFRA` is a bake-environment artifact matched on the "
            "error text, `UNSCORED` is an attempt that executed and left a "
            "mesh for which its roll carries no `cd_pca`."
        ),
        "",
    ]
    excluded = [a for a in attempts if a["code"] in EXCLUDED_CODES]
    if excluded:
        lines += ["| code | roll | instance | reason |", "|---|---|---|---|"]
        for attempt in excluded:
            reason = (
                attempt["error_fingerprint"][:100]
                or attempt["agent_error"][:100]
                or "executed, but this roll carries no cd_pca"
            )
            lines.append(
                f"| {attempt['code']} | {attempt['model_dir']} | "
                f"{attempt['instance']} | `{reason}` |"
            )
    else:
        lines.append("None.")
    lines += [
        "",
        "## Hatch accounting",
        "",
        (
            "Counted off the BAKED script's labels, not `.agent_meta.json` — "
            "meta counts reader ops as geometry-emitting and numbers chunks "
            "with a counter that advances on op calls. Rolls predating op "
            "collection in the bridge are excluded from the share and shown "
            "in their own columns: their scripts cannot hold an op call, so "
            "their 100% is the instrument, not the agent "
            "(`phaseA/hatch_mechanism.md`)."
        ),
        "",
        (
            "| rows | attempts | collecting ops | baked run_python chunks | "
            "scene-changing op calls | reader op calls | attempts using any op "
            "| hatch share | pre-collection attempts (chunks) |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for label, row in hatch_table(attempts).items():
        lines.append(
            f"| {label} | {row['attempts']} | {row['attempts_collecting_ops']} | "
            f"{row['included_chunks']} | {row['op_calls']} | "
            f"{row['reader_op_calls']} | {row['attempts_using_any_op']} | "
            f"{_percent(row['hatch_share'])} | "
            f"{row['attempts_before_op_collection']} "
            f"({row['chunks_before_op_collection']}) |"
        )
    lines += [
        "",
        "## Cross-tab against the benchmark's own categoriser",
        "",
        (
            "`metrics/failure_taxonomy.categorize` on the same error text — "
            "an external instrument, not a second copy of the rules above."
        ),
        "",
        "| code | B5-API | BMSH | CTX | OTHER | (no error text) |",
        "|---|---|---|---|---|---|",
    ]
    families = ("B5-API", "BMSH", "CTX", "OTHER", "")
    for code in sorted({a["code"] for a in harness}):
        counts = Counter(a["b5_category"] for a in harness if a["code"] == code)
        cells = " | ".join(str(counts.get(family, 0)) for family in families)
        lines.append(f"| {code} | {cells} |")
    lines += [
        "",
        "## Third-party row, reported separately",
        "",
    ]
    if third_party:
        third_party_codes = Counter(a["code"] for a in third_party)
        lines.append(f"`baseline-opus`: {dict(third_party_codes)}")
    else:
        lines.append("None included.")
    lines.append("")
    return "\n".join(lines)


def _percent(value) -> str:
    return "—" if value is None else f"{100.0 * value:.1f}%"


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    attempts = collect(bench_root, arguments.results_root, arguments.refresh_scores)
    if not attempts:
        raise SystemExit("no attempts collected")
    measured = shares(attempts)
    write_csv(attempts, PHASE_A_DIRECTORY / "taxonomy.csv")
    (PHASE_A_DIRECTORY / "summary.md").write_text(render_summary(attempts, measured))
    (WORKING_DIRECTORY / "phase_a_measured.json").write_text(
        json.dumps(
            {
                "shares": measured,
                "codes": dict(
                    Counter(a["code"] for a in attempts if not a["third_party"])
                ),
                "hatch": hatch_table(attempts),
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"[phaseA] {measured['attempts_counted']} counted, "
        f"{measured['failures']} failures; F_syntax={_percent(measured['f_syntax'])} "
        f"F_geom={_percent(measured['f_geom'])}",
        flush=True,
    )
    print(f"[phaseA] wrote {PHASE_A_DIRECTORY / 'taxonomy.csv'}", flush=True)
    print(f"[phaseA] wrote {PHASE_A_DIRECTORY / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
