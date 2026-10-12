#!/usr/bin/env python3
"""Phase B — assemble the arm funnel, the four deltas, and the fired rule.

    .venv/bin/python scripts/finetune_phase_b.py \\
        --bench-root /Users/ladvien/3dcodebench

Reads what the arms and the scorers already wrote — never re-runs
inference — and produces:

  phaseB/<arm>/executions.jsonl  one row per completion: render status,
                                 error, mesh count, latency, GLB path and
                                 the Phase-A failure code
  phaseB/scores.csv              one row per completion, every metric
  phaseB/summary.md              the funnel, the rates, the deltas and
                                 the §3 rule that fired

The failure code comes from `scripts/finetune_phase_a.classify`,
IMPORTED, not reimplemented: Phase A and Phase B disagreeing about what
an `E2` is would make `F_syntax` and the arm histograms incomparable,
which is the one thing the spec's §3 needs them to be.

Rates are over ALL completions per arm (`COMPLETIONS_PER_ARM`), not over
tasks — a task that passes on one draw and fails on another is exactly
the variance the four draws exist to measure.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from finetune_decision_thresholds import (
    ARMS,
    CD_PCA_PASS,
    COMPLETIONS_PER_ARM,
    DELTA_FACADE_MINIMUM_PP,
    DELTA_SIZE_MAXIMUM_PP,
    DELTA_TUNE_MINIMUM_PP,
    DRAWS_SAMPLED,
    EXCLUDED_CODES,
    F_GEOM_DO_NOT_TUNE,
    F_SYNTAX_MINIMUM,
    GEOMETRY_CODES,
    GREEDY_SEED,
    INFRASTRUCTURE_CODE,
    SERVED_PRECISION,
    SYNTAX_CODES,
    model_directory,
)
from finetune_phase_a import baked_call_counts, classify

PHASE_B_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseB"
)
WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
PHASE_A_MEASURED = WORKING_DIRECTORY / "phase_a_measured.json"
# An arm whose executability is below this has no usable floor to subtract
# from: a difference between two such arms is a couple of completions wide.
FLOORED_EXECUTABILITY_MAXIMUM = 0.05

# How a completion that never reached a script maps into the spec's own
# codes. Pre-registered vocabulary, one mapping, so the arm histogram and
# Phase A's histogram are the same alphabet.
PARSE_RESULT_CODES = {
    "NO_CODE": "O2",  # empty or prose-only reply
    "NO_TOOL_CALLS": "O2",  # tool calls, none of them geometry
    "SYNTAX_ERROR": "E1",  # the reply's Python does not parse
    "UNKNOWN_TOOL": "O1",  # a name that was never offered
    "ARGUMENT_ERROR": "O1",  # malformed or refused arguments
    # The spec's E5: "timeout, hang, or crash". Here it is the SWEEP's
    # own wall-clock cap, not the bake's, and the row is synthesized by
    # `sweep_finetune_arms.write_timeout_completion`.
    "ERR_TIMEOUT": "E5",
    "ERR_CONNECTION": INFRASTRUCTURE_CODE,
    "ERR_MODEL_CALL": INFRASTRUCTURE_CODE,
}


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument(
        "--arms",
        default=",".join(sorted(ARMS)),
        help="comma-separated arms to assemble; an arm with no completions "
        "is reported as not run rather than skipped silently",
    )
    return parser.parse_args(argv)


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def completions(arm: str) -> list[dict]:
    """Every recorded completion for the arm, last per (draw, instance).

    Reads `completions.jsonl` AND any `completions.k<draw>.jsonl`: draws
    that ran concurrently write one file each so their records cannot
    interleave mid-line. "Last" is FILE-NAME order, then line order: a
    record carries no timestamp, so a (draw, instance) recorded in two
    files resolves to the later-sorting name, not the later run.
    """
    directory = PHASE_B_DIRECTORY / arm
    if not directory.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(directory.glob("completions*.jsonl")):
        rows.extend(
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        )
    # The last row per (draw, instance): a re-run with --overwrite
    # appends, and the arm is what the latest attempt says.
    newest: dict[tuple[int, str], dict] = {}
    for row in rows:
        newest[(row["draw"], row["instance"])] = row
    return [newest[key] for key in sorted(newest)]


def diagnose_for(model_dir: str) -> dict:
    for directory in (WORKING_DIRECTORY, REPOSITORY_ROOT / "outputs" / "bench"):
        data = read_json(directory / f"diagnose_{model_dir}.json")
        if data:
            return {row["instance"]: row for row in data["per_instance"]}
    return {}


def decompose_for(model_dir: str) -> dict:
    data = read_json(WORKING_DIRECTORY / f"decompose_{model_dir}.json")
    return {row["instance"]: row for row in data["per_instance"]} if data else {}


def execution_row(
    bench_root: Path, results_root: str, completion: dict, bench_taxonomy
) -> dict:
    model_dir = model_directory(completion["arm"], completion["draw"])
    instance_root = bench_root / results_root / model_dir / completion["instance"]
    # A completion that wrote no script owns no bake artifacts: whatever sits
    # in its directory is a stale leftover of an earlier `--overwrite` run,
    # and reading it would score a reply that never produced that mesh.
    script_written = bool(completion["script_written"])
    log = (
        (read_json(instance_root / "renders" / "render_log.json") or {})
        if script_written
        else {}
    )
    glb_path = instance_root / "glb" / f"{completion['instance']}.glb"
    # What the score actually saw, off the baked script's labels. NOT the
    # completion record's `n_ops`/`n_hatch`: `n_ops` is
    # `StandaloneScript.op_call_count`, which counts the READER ops as
    # geometry-emitting, and `n_hatch` counts every DISPATCHED chunk
    # whether or not the bake collected it (hatch_mechanism.md, 2026-09-19).
    baked = (
        baked_call_counts(instance_root / f"{completion['instance']}.py")
        if script_written
        else {"baked_chunks": 0, "baked_scene_ops": 0}
    )
    error_text = str(log.get("error") or "")
    return {
        "arm": completion["arm"],
        "draw": completion["draw"],
        "instance": completion["instance"],
        "model_dir": model_dir,
        "parse_result": completion["parse_result"],
        "script_written": completion["script_written"],
        "render_status": log.get(
            "status", "MISSING" if script_written else "NO_SCRIPT"
        ),
        "error_text": error_text,
        "error_fingerprint": bench_taxonomy.fingerprint(error_text),
        "b5_category": bench_taxonomy.categorize(error_text) if error_text else "",
        "n_meshes": log.get("n_meshes") or 0,
        "latency_s": log.get("latency_s"),
        "glb_path": str(glb_path) if script_written and glb_path.exists() else "",
        "renders_directory": str(instance_root / "renders"),
        "baked_chunks": baked["baked_chunks"],
        "baked_scene_ops": baked["baked_scene_ops"],
    }


def coded_row(execution: dict, completion: dict, score: dict, oracle: dict) -> dict:
    """One completion, scored and coded the Phase-A way."""
    row = dict(execution)
    row.update(
        {
            "seed": completion["seed"],
            "temperature": completion["temperature"],
            "model": completion["model"],
            "format": completion["format"],
            "wall_time_s": completion["wall_time_s"],
            "prompt_tokens": completion["prompt_tokens"],
            "completion_tokens": completion["completion_tokens"],
            "n_tool_calls": completion["n_tool_calls"],
            "cd_pca": score.get("cd_pca"),
            "cd_yawmin": score.get("cd_yawmin"),
            "delta_orient": score.get("delta_orient"),
            "fscore_005": score.get("fscore_005"),
            "cd_pca_aspect_oracle": oracle.get("cd_pca_aspect_oracle"),
        }
    )
    if completion["parse_result"] in PARSE_RESULT_CODES:
        row["code"] = PARSE_RESULT_CODES[completion["parse_result"]]
        return row
    # The completion produced a script, so the bake and the score decide.
    row["code"] = classify(
        {
            "error_text": row["error_text"],
            "agent_error": "",
            "agent_status": "",
            "render_status": row["render_status"],
            "b5_category": row["b5_category"],
            "n_meshes": row["n_meshes"],
            "cd_pca": row["cd_pca"],
            "delta_orient": row["delta_orient"],
            "cd_pca_aspect_oracle": row["cd_pca_aspect_oracle"],
        }
    )
    return row


def conforms_to_schema(row: dict) -> bool:
    """Stage 1 of the spec's funnel: "output parsed as a valid op sequence
    (A1/A2) or valid Python (A3-A5)".

    DEFINITIONAL CORRECTION, made after the first A2 completions came
    back and stated here rather than buried: stage 1 asks whether the
    OUTPUT PARSED, not whether it survived dispatch. A reply carrying
    well-formed tool calls that name real tools is a valid op sequence
    even when an op then refuses its arguments — measured on A2,
    45 of 54 completions were exactly that (`boolean_union` against an
    object the reply never created, `solver: "LAPACK"`). Counting those
    as stage-1 failures hid the whole class at the wrong stage, and the
    spec's own reason for a funnel is that "a model that fails at stage
    2 and a model that fails at stage 4 need different fixes". No §3
    rule reads stage 1: Δ_tune and Δ_facade read executability, Δ_size
    reads the cd_pca pass rate.
    """
    if row["format"] == "raw":
        return bool(row["script_written"])
    return (row["n_tool_calls"] or 0) >= 1 and row["parse_result"] in (
        "OK",
        "ARGUMENT_ERROR",
    )


def clustered_interval(rows: list[dict], predicate) -> dict:
    """A rate with its INSTANCE-CLUSTERED 95% interval.

    The four draws of one instance answer the same prompt, so they are
    not four independent trials: the effective sample size is nearer the
    20 instances than the 80 completions. The interval is therefore the
    normal approximation on the 20 per-instance means —
    `1.96 * sd(instance means) / sqrt(n instances)` — which is the
    cluster-robust standard error for a clustered proportion.

    This is a DIFFERENT quantity from the parity gate's ~3e-4 cd_pca
    noise floor, and conflating them was a real error in the first draft
    of this report: the noise floor is what a RE-BAKE perturbs (metric
    precision), and says nothing about how far a 20-instance rate would
    move on another 20 instances.
    """
    by_instance: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_instance[row["instance"]].append(row)
    means = [
        sum(1.0 for row in instance_rows if predicate(row)) / len(instance_rows)
        for instance_rows in by_instance.values()
    ]
    if len(means) < 2:
        return {
            "rate": (means[0] if means else None),
            "se": None,
            "low": None,
            "high": None,
            "clusters": len(means),
        }
    rate = sum(means) / len(means)
    standard_error = statistics.stdev(means) / (len(means) ** 0.5)
    half_width = 1.96 * standard_error
    return {
        "rate": rate,
        "se": standard_error,
        "low": max(0.0, rate - half_width),
        "high": min(1.0, rate + half_width),
        "half_width": half_width,
        "clusters": len(means),
    }


def _passed(row: dict) -> bool:
    """THE stage-4 pass: executed, left a mesh, and cd_pca on the bar.

    One definition for the funnel, pass@k and the clustered interval, so
    a stale score on a row whose bake no longer executed cannot count in
    one place and not another.
    """
    return (
        row["render_status"] == "OK"
        and row["n_meshes"] > 0
        and row["cd_pca"] is not None
        and row["cd_pca"] <= CD_PCA_PASS
    )


def _executed(row: dict) -> bool:
    return row["render_status"] == "OK"


def funnel(rows: list[dict]) -> dict:
    """The spec's four stages, each over every completion of the arm."""
    total = len(rows)
    conforming = [row for row in rows if conforms_to_schema(row)]
    # The stage between conformance and execution: a dispatched op
    # sequence that left at least one geometry-emitting call for the
    # bake. A raw arm's script IS this stage, so the two coincide there.
    emitted = [row for row in rows if row["script_written"]]
    executed = [row for row in emitted if row["render_status"] == "OK"]
    non_degenerate = [row for row in executed if row["n_meshes"] > 0]
    passing = [row for row in non_degenerate if _passed(row)]
    scored = [row["cd_pca"] for row in non_degenerate if row["cd_pca"] is not None]
    fscores = [
        row["fscore_005"] for row in non_degenerate if row["fscore_005"] is not None
    ]
    times = [row["wall_time_s"] for row in rows if row["wall_time_s"]]
    return {
        "completions": total,
        "schema_conforming": len(conforming),
        "script_emitted": len(emitted),
        "executed": len(executed),
        "non_degenerate": len(non_degenerate),
        "cd_pca_passing": len(passing),
        "schema_conformance_rate": _rate(len(conforming), total),
        "script_emitted_rate": _rate(len(emitted), total),
        "executability_rate": _rate(len(executed), total),
        "non_degenerate_rate": _rate(len(non_degenerate), total),
        "cd_pca_pass_rate": _rate(len(passing), total),
        "cd_pca_median": statistics.median(scored) if scored else None,
        "cd_pca_iqr": _iqr(scored),
        "fscore_005_median": statistics.median(fscores) if fscores else None,
        "wall_time_p50": _percentile(times, 50),
        "wall_time_p95": _percentile(times, 95),
        "prompt_tokens_total": sum(row["prompt_tokens"] or 0 for row in rows),
        "completion_tokens_total": sum(row["completion_tokens"] or 0 for row in rows),
        "wall_time_total_s": sum(times),
        "codes": dict(Counter(row["code"] for row in rows).most_common()),
        "hatch_calls": sum(row["baked_chunks"] for row in rows),
        "op_calls": sum(row["baked_scene_ops"] for row in rows),
        # Spec §5.3 metric 8, which the first draft omitted entirely:
        # what one PASSING asset cost. A rate says nothing about whether
        # a lane is worth calling, and the cost per pass is the only
        # number on which a cheap-and-often lane can beat an expensive
        # one.
        "tokens_per_passing": (
            (
                sum(row["prompt_tokens"] or 0 for row in rows)
                + sum(row["completion_tokens"] or 0 for row in rows)
            )
            / len(passing)
            if passing
            else None
        ),
        "wall_time_per_passing_s": (sum(times) / len(passing)) if passing else None,
        "completion_tokens_per_passing": (
            sum(row["completion_tokens"] or 0 for row in rows) / len(passing)
            if passing
            else None
        ),
        # Instance-clustered 95% intervals: the honest uncertainty on a
        # 20-instance rate, which is NOT the parity gate's noise floor.
        "executability_interval": clustered_interval(rows, _executed),
        "cd_pca_pass_interval": clustered_interval(rows, _passed),
    }


def pass_rates(rows: list[dict]) -> dict:
    """pass@1, pass@3 and the greedy draw, on the cd_pca bar."""
    sampled = [row for row in rows if row["draw"] != 0]
    greedy = [row for row in rows if row["draw"] == 0]
    by_instance: dict[str, list[dict]] = defaultdict(list)
    for row in sampled:
        by_instance[row["instance"]].append(row)
    any_of_k = [
        1.0 if any(_passed(row) for row in instance_rows) else 0.0
        for instance_rows in by_instance.values()
    ]
    return {
        "pass_at_1": _rate(sum(1 for row in sampled if _passed(row)), len(sampled)),
        "pass_at_3": (sum(any_of_k) / len(any_of_k)) if any_of_k else None,
        "greedy_pass_rate": _rate(
            sum(1 for row in greedy if _passed(row)), len(greedy)
        ),
        "sampled_completions": len(sampled),
        "greedy_completions": len(greedy),
        "executability_sampled": _rate(
            sum(1 for row in sampled if row["render_status"] == "OK"), len(sampled)
        ),
        "executability_greedy": _rate(
            sum(1 for row in greedy if row["render_status"] == "OK"), len(greedy)
        ),
    }


def _rate(numerator: int, denominator: int):
    return (numerator / denominator) if denominator else None


def _iqr(values: list[float]):
    if len(values) < 4:
        return None
    ordered = sorted(values)
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
    return [quartiles[0], quartiles[2]]


def _percentile(values: list[float], percentile: int):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100.0) * (len(ordered) - 1)))
    return ordered[index]


def _percentage_points(higher, lower):
    if higher is None or lower is None:
        return None
    return 100.0 * (higher - lower)


def failure_class_shares(codes: dict) -> dict:
    """Syntactic and geometric share of an arm's FAILURES, from its codes.

    The failures are every completion that is neither a pass nor an
    excluded outcome, the same denominator Phase A's `shares` uses, so an
    arm's shares and the archive's are the same quantity.
    """
    failures = {
        code: count
        for code, count in codes.items()
        if code != "PASS" and code not in EXCLUDED_CODES
    }
    total = sum(failures.values())
    return {
        "failures": total,
        "syntax": _rate(
            sum(count for code, count in failures.items() if code in SYNTAX_CODES),
            total,
        ),
        "geometry": _rate(
            sum(count for code, count in failures.items() if code in GEOMETRY_CODES),
            total,
        ),
    }


def deltas(measured: dict) -> dict:
    """The spec's four quantities, in percentage points."""

    def rate(arm: str, key: str):
        return measured.get(arm, {}).get("funnel", {}).get(key)

    def sampled_rate(arm: str, key: str):
        return measured.get(arm, {}).get("rates", {}).get(key)

    delta_size_k = _percentage_points(
        sampled_rate("a1", "pass_at_1"), sampled_rate("a2", "pass_at_1")
    )
    delta_size_greedy = _percentage_points(
        sampled_rate("a1", "greedy_pass_rate"), sampled_rate("a2", "greedy_pass_rate")
    )
    agreement = (
        None
        if delta_size_k is None or delta_size_greedy is None
        else (
            (delta_size_k <= DELTA_SIZE_MAXIMUM_PP)
            == (delta_size_greedy <= DELTA_SIZE_MAXIMUM_PP)
        )
    )

    def interval(arm: str, key: str) -> dict:
        return measured.get(arm, {}).get("funnel", {}).get(key) or {}

    def difference_half_width(left: dict, right: dict):
        """95% half-width on a DIFFERENCE of two clustered rates."""
        # `se == 0` is a REAL value, not a missing one: an arm that
        # passed nothing on every instance has zero between-instance
        # variance, and treating that as absent silently dropped the
        # half-width on Δ_facade and Δ_size.
        if left.get("se") is None or right.get("se") is None:
            return None
        return 1.96 * ((left["se"] ** 2 + right["se"] ** 2) ** 0.5) * 100.0

    executability = {arm: interval(arm, "executability_interval") for arm in measured}
    passing = {arm: interval(arm, "cd_pca_pass_interval") for arm in measured}
    # Δ_facade is NOT a measurement of the spec's Q2, and saying so is
    # not hedging, for two separable reasons. The first is shared with
    # Δ_size and is carried by `a2_floored` below, stated once: A2
    # passed nothing. The second is specific to Q2 and is carried by
    # `q2_reason`: the op arms' task text still carries the archive's
    # `run_python` bullet, so A2 was emitting bpy inside a tool-call
    # envelope rather than driving the 48-op facade, and A2 - A3
    # therefore compares bpy with bpy-plus-an-envelope.
    facade_arms_floored = (
        rate("a2", "executability_rate") or 0.0
    ) < FLOORED_EXECUTABILITY_MAXIMUM and (
        rate("a3", "executability_rate") or 0.0
    ) < FLOORED_EXECUTABILITY_MAXIMUM
    # A2 passed 0 of 80 at cd_pca. Every quantity whose subtrahend is A2
    # therefore measures a floored arm, not the factor it is named for —
    # and the same floor is why A2's between-instance variance is exactly
    # zero, the `se == 0` case `difference_half_width` handles above.
    a2_floored = (rate("a2", "cd_pca_pass_rate") or 0.0) == 0.0
    return {
        "delta_tune_pp": _percentage_points(
            rate("a4", "executability_rate"), rate("a3", "executability_rate")
        ),
        "delta_tune_half_width_pp": difference_half_width(
            executability.get("a4", {}), executability.get("a3", {})
        ),
        "delta_facade_pp": _percentage_points(
            rate("a2", "executability_rate"), rate("a3", "executability_rate")
        ),
        "delta_facade_half_width_pp": difference_half_width(
            executability.get("a2", {}), executability.get("a3", {})
        ),
        "delta_facade_arms_floored": facade_arms_floored,
        "a5_executability_rate": rate("a5", "executability_rate"),
        "failure_class_shares": {
            arm: failure_class_shares(measured[arm]["funnel"]["codes"])
            for arm in ("a3", "a4")
            if arm in measured
        },
        "a2_floored": a2_floored,
        "void_against_a2": (
            ["delta_facade_pp", "delta_size_pp_k_mean", "delta_size_pp_greedy"]
            if a2_floored
            else []
        ),
        "q2_answered": False,
        "q2_reason": (
            "the op arms' task text still mandates that geometry be built "
            "inside `run_python` chunks, so A2 exercised bpy-in-an-envelope "
            "rather than the 48-op facade"
        ),
        "delta_size_pp_k_mean": delta_size_k,
        "delta_size_pp_greedy": delta_size_greedy,
        "delta_size_agrees": agreement,
        "delta_size_half_width_pp": difference_half_width(
            passing.get("a1", {}), passing.get("a2", {})
        ),
        "pass_rate_intervals_pp": {
            arm: {
                "rate": (
                    None
                    if passing[arm].get("rate") is None
                    else 100.0 * passing[arm]["rate"]
                ),
                "low": (
                    None
                    if passing[arm].get("low") is None
                    else 100.0 * passing[arm]["low"]
                ),
                "high": (
                    None
                    if passing[arm].get("high") is None
                    else 100.0 * passing[arm]["high"]
                ),
            }
            for arm in sorted(measured)
        },
    }


def fired_rule(phase_a: dict, computed: dict) -> tuple[str, list[str]]:
    """Which §3 rule fires, applied in the spec's order."""
    notes: list[str] = []
    f_geom = phase_a["shares"]["f_geom"]
    f_syntax = phase_a["shares"]["f_syntax"]
    delta_tune = computed["delta_tune_pp"]
    delta_facade = computed["delta_facade_pp"]
    delta_size_k = computed["delta_size_pp_k_mean"]

    a2_floored = bool(computed.get("a2_floored"))
    if a2_floored:
        # One reason, said once: A2 passed nothing, so neither rule's
        # input is a measurement of the factor it names. The threshold
        # comparisons are unchanged — both rules stay un-fired — but
        # "does not fire" would credit a number that does not exist.
        notes.append(
            "Rules 4 and 5 are VOID rather than un-fired-on-the-evidence: "
            "Δ_facade and Δ_size are both computed against A2, which passed "
            "nothing, so each subtraction measures a floored arm instead of "
            "the facade or model size. Neither rule's §3 threshold comparison "
            "changes; only what the number is allowed to mean does."
        )
    else:
        if delta_facade is not None and delta_facade >= DELTA_FACADE_MINIMUM_PP:
            notes.append(
                f"Rule 4 also fires: Δ_facade = {delta_facade:.1f} pp >= "
                f"{DELTA_FACADE_MINIMUM_PP} pp, so the facade is carrying the "
                f"work and a fine-tune's target should be op-call sequences, "
                f"not raw bpy."
            )
        if (
            computed["delta_size_agrees"]
            and delta_size_k is not None
            and (delta_size_k <= DELTA_SIZE_MAXIMUM_PP)
        ):
            notes.append(
                f"Rule 5 also fires: Δ_size = {delta_size_k:.1f} pp <= "
                f"{DELTA_SIZE_MAXIMUM_PP} pp on both the k-mean and the greedy "
                f"draw — a small model is already close to the frontier path "
                f"here."
            )
        elif computed["delta_size_agrees"] is False:
            notes.append(
                "Rule 5 is INCONCLUSIVE: the k-mean and the greedy draw "
                "disagree about whether Δ_size clears the bar, and A1/A2 ride "
                "lanes with different sampling control."
            )
    if (
        delta_tune is not None
        and delta_tune >= DELTA_TUNE_MINIMUM_PP
        and f_syntax is not None
        and f_syntax < F_SYNTAX_MINIMUM
    ):
        a5_failure = (
            None
            if computed.get("a5_executability_rate") is None
            else 1.0 - computed["a5_executability_rate"]
        )
        class_shares = computed.get("failure_class_shares", {})
        notes.append(
            f"Δ_tune = {delta_tune:.1f} pp clears rule 2's "
            f"{DELTA_TUNE_MINIMUM_PP} pp bar, and rule 2 STILL CANNOT FIRE, "
            f"because it is conjoined with F_syntax >= "
            f"{100.0 * F_SYNTAX_MINIMUM:.0f}% and F_syntax measured "
            f"{100.0 * f_syntax:.1f}%. The careful statement, not the "
            f"flattering one: domain SFT fixes the class a 7B fails in, and "
            f"the archive does not fail in that class BECAUSE IT PAYS A RETRY "
            f"LOOP TO AVOID IT. The Phase A denominator is multi-turn with "
            f"error feedback; single-shot A5 — frontier model, raw bpy, no "
            f"feedback — fails to execute {_percent(a5_failure)} of the time "
            f"against the archive's {100.0 * f_syntax:.1f}%. So the harness "
            f"HAS a syntactic failure mode and spends tokens and turns "
            f"instead of score on it. What the arm codes do show is the "
            f"regime SFT buys: "
            f"{_percent(class_shares.get('a3', {}).get('syntax'))} of the "
            f"untuned base's (A3) failures are syntactic "
            f"({', '.join(SYNTAX_CODES)}), against "
            f"{_percent(class_shares.get('a4', {}).get('geometry'))} of the "
            f"fine-tune's (A4) that are geometric "
            f"({', '.join(GEOMETRY_CODES)})."
        )

    if f_geom is not None and f_geom >= F_GEOM_DO_NOT_TUNE:
        return (
            (
                f"Rule 1 fires: F_geom = {100.0 * f_geom:.1f}% >= "
                f"{100.0 * F_GEOM_DO_NOT_TUNE:.0f}% -> DO NOT FINE-TUNE. The "
                f"failures are planning failures; invest in decomposition, "
                f"reference-image grounding and the multi-angle visual inspection "
                f"loop instead."
            ),
            notes,
        )
    if f_syntax is not None and f_syntax >= F_SYNTAX_MINIMUM:
        if delta_tune is None:
            return (
                (
                    f"Rules 2 and 3 CANNOT FIRE: F_syntax = "
                    f"{100.0 * f_syntax:.1f}% clears the bar but Δ_tune is "
                    f"unmeasured."
                ),
                notes,
            )
        if delta_tune >= DELTA_TUNE_MINIMUM_PP:
            return (
                (
                    f"Rule 2 fires: F_syntax = {100.0 * f_syntax:.1f}% and "
                    f"Δ_tune = {delta_tune:.1f} pp -> FINE-TUNE IS JUSTIFIED."
                ),
                notes,
            )
        return (
            (
                f"Rule 3 fires: F_syntax = {100.0 * f_syntax:.1f}% and Δ_tune = "
                f"{delta_tune:.1f} pp < {DELTA_TUNE_MINIMUM_PP} pp -> DO NOT "
                f"FINE-TUNE YET."
            ),
            notes,
        )
    return (
        (
            f"No rule 1-3 fires: F_geom = {_percent(f_geom)} and F_syntax = "
            f"{_percent(f_syntax)}. Report as INCONCLUSIVE and enlarge N."
        ),
        notes,
    )


def _percent(value) -> str:
    return "—" if value is None else f"{100.0 * value:.1f}%"


def _number(value, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


CSV_COLUMNS = (
    "arm",
    "format",
    "model",
    "draw",
    "seed",
    "temperature",
    "instance",
    "parse_result",
    "script_written",
    "render_status",
    "code",
    "n_meshes",
    "cd_pca",
    "cd_yawmin",
    "delta_orient",
    "fscore_005",
    "n_tool_calls",
    "baked_scene_ops",
    "baked_chunks",
    "wall_time_s",
    "prompt_tokens",
    "completion_tokens",
    "glb_path",
    "renders_directory",
    "error_fingerprint",
)


def render_summary(
    measured: dict, computed: dict, phase_a: dict, verdict: str, notes: list[str]
) -> str:
    lines = [
        "# Phase B — the five arms, single-shot",
        "",
        "## The rule that fired",
        "",
        f"**{verdict}**",
        "",
    ]
    for note in notes:
        lines.append(f"- {note}")
    lines += [
        "",
        "## Funnel, every completion of every arm",
        "",
        (
            "Rates are over all completions attempted for the arm, the spec's "
            f"denominator being {COMPLETIONS_PER_ARM} (20 instances x 4 draws)."
        ),
        "",
        (
            "| arm | model | format | completions | schema | script emitted | "
            "executed | non-degenerate | cd_pca pass |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in sorted(measured):
        row = measured[arm]["funnel"]
        lines.append(
            f"| {arm} | {ARMS[arm]['model']} | {ARMS[arm]['format']} | "
            f"{row['completions']} | {_percent(row['schema_conformance_rate'])} | "
            f"{_percent(row['script_emitted_rate'])} | "
            f"{_percent(row['executability_rate'])} | "
            f"{_percent(row['non_degenerate_rate'])} | "
            f"{_percent(row['cd_pca_pass_rate'])} |"
        )
    lines += [
        "",
        (
            "| arm | pass@1 | pass@3 | greedy | cd_pca median | cd_pca IQR | "
            "F@0.05 median | wall p50 | wall p95 |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in sorted(measured):
        row = measured[arm]["funnel"]
        rates = measured[arm]["rates"]
        iqr = row["cd_pca_iqr"]
        lines.append(
            f"| {arm} | {_percent(rates['pass_at_1'])} | "
            f"{_percent(rates['pass_at_3'])} | "
            f"{_percent(rates['greedy_pass_rate'])} | "
            f"{_number(row['cd_pca_median'])} | "
            f"{('—' if iqr is None else f'{iqr[0]:.4f}-{iqr[1]:.4f}')} | "
            f"{_number(row['fscore_005_median'])} | "
            f"{_number(row['wall_time_p50'], 1)}s | "
            f"{_number(row['wall_time_p95'], 1)}s |"
        )
    lines += ["", "## Failure codes per arm", "", "| arm | codes |", "|---|---|"]
    for arm in sorted(measured):
        lines.append(f"| {arm} | {measured[arm]['funnel']['codes']} |")
    lines += [
        "",
        "## The four deltas",
        "",
        "| quantity | definition | value | bar |",
        "|---|---|---|---|",
        (
            f"| Δ_tune | executability A4 − A3 | "
            f"{_number(computed['delta_tune_pp'], 1)} pp | "
            f">= {DELTA_TUNE_MINIMUM_PP} pp |"
        ),
        (
            f"| Δ_facade | executability A2 − A3 | "
            f"{_number(computed['delta_facade_pp'], 1)} pp | "
            f">= {DELTA_FACADE_MINIMUM_PP} pp |"
        ),
        (
            f"| Δ_size (k-mean) | cd_pca pass A1 − A2 | "
            f"{_number(computed['delta_size_pp_k_mean'], 1)} pp | "
            f"<= {DELTA_SIZE_MAXIMUM_PP} pp |"
        ),
        (
            f"| Δ_size (greedy) | cd_pca pass A1 − A2 | "
            f"{_number(computed['delta_size_pp_greedy'], 1)} pp | "
            f"<= {DELTA_SIZE_MAXIMUM_PP} pp |"
        ),
        "",
        (
            f"- hatch rate, archived rolls (Phase A, passing attempts): "
            f"{_percent(phase_a['hatch']['passing']['hatch_share'])}"
        ),
        (
            f"- hatch rate, archived rolls (Phase A, failing attempts): "
            f"{_percent(phase_a['hatch']['failing']['hatch_share'])}"
        ),
    ]
    for arm in sorted(measured):
        row = measured[arm]["funnel"]
        if ARMS[arm]["format"] != "ops":
            continue
        total = row["hatch_calls"] + row["op_calls"]
        lines.append(
            f"- hatch rate, arm {arm} single-shot: "
            f"{_percent(_rate(row['hatch_calls'], total))} "
            f"({row['hatch_calls']} baked chunks against {row['op_calls']} "
            f"baked scene-changing op calls)"
        )
    lines += [
        "",
        "## Cost",
        "",
        "| arm | lane | money | GPU seconds | prompt tokens | completion tokens |",
        "|---|---|---|---|---|---|",
    ]
    for arm in sorted(measured):
        row = measured[arm]["funnel"]
        local = ARMS[arm]["model"] not in ("claude-code:sonnet",)
        lines.append(
            f"| {arm} | {'big llama-swap (' + SERVED_PRECISION + ')' if local else 'Claude Code CLI'} | "
            f"$0 | {_number(row['wall_time_total_s'], 0) if local else '—'} | "
            f"{row['prompt_tokens_total']} | {row['completion_tokens_total']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    sys.path.insert(0, str(bench_root / "metrics"))
    import failure_taxonomy as bench_taxonomy

    phase_a = read_json(PHASE_A_MEASURED)
    if not phase_a:
        raise SystemExit(
            f"run scripts/finetune_phase_a.py first: no {PHASE_A_MEASURED}"
        )

    wanted = [arm for arm in arguments.arms.split(",") if arm.strip()]
    measured: dict[str, dict] = {}
    all_rows: list[dict] = []
    for arm in wanted:
        rows = completions(arm)
        if not rows:
            print(f"[phaseB] arm {arm}: NOT RUN (no completions recorded)", flush=True)
            continue
        scores_by_dir = {
            draw: diagnose_for(model_directory(arm, draw))
            for draw in {row["draw"] for row in rows}
        }
        oracles_by_dir = {
            draw: decompose_for(model_directory(arm, draw))
            for draw in {row["draw"] for row in rows}
        }
        coded = []
        executions_path = PHASE_B_DIRECTORY / arm / "executions.jsonl"
        executions_path.parent.mkdir(parents=True, exist_ok=True)
        with executions_path.open("w") as handle:
            for completion in rows:
                execution = execution_row(
                    bench_root, arguments.results_root, completion, bench_taxonomy
                )
                row = coded_row(
                    execution,
                    completion,
                    scores_by_dir[completion["draw"]].get(completion["instance"], {}),
                    oracles_by_dir[completion["draw"]].get(completion["instance"], {}),
                )
                handle.write(json.dumps(execution) + "\n")
                coded.append(row)
        measured[arm] = {"funnel": funnel(coded), "rates": pass_rates(coded)}
        all_rows.extend(coded)
        print(
            (
                f"[phaseB] arm {arm}: {len(coded)} completion(s), "
                f"schema {_percent(measured[arm]['funnel']['schema_conformance_rate'])}, "
                f"exec {_percent(measured[arm]['funnel']['executability_rate'])}, "
                f"pass {_percent(measured[arm]['funnel']['cd_pca_pass_rate'])}"
            ),
            flush=True,
        )

    scores_path = PHASE_B_DIRECTORY / "scores.csv"
    with scores_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})

    computed = deltas(measured)
    verdict, notes = fired_rule(phase_a, computed)
    (PHASE_B_DIRECTORY / "summary.md").write_text(
        render_summary(measured, computed, phase_a, verdict, notes)
    )
    (WORKING_DIRECTORY / "phase_b_measured.json").write_text(
        json.dumps(
            {
                "arms": measured,
                "deltas": computed,
                "verdict": verdict,
                "notes": notes,
                "greedy_seed": GREEDY_SEED,
                "draws_sampled": DRAWS_SAMPLED,
            },
            indent=2,
        )
        + "\n"
    )
    print(flush=True)
    print(f"[phaseB] {verdict}", flush=True)
    for note in notes:
        print(f"[phaseB] {note}", flush=True)
    print(
        f"[phaseB] wrote {scores_path} and {PHASE_B_DIRECTORY / 'summary.md'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
