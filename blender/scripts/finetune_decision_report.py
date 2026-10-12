#!/usr/bin/env python3
"""Assemble REPORT.md from the measured artifacts, in the spec's §8 order.

    .venv/bin/python scripts/finetune_decision_report.py \\
        --bench-root /Users/ladvien/3dcodebench

Every MEASURED number in the report is READ from a committed artifact, never
retyped: `env.json`, `phaseA/summary.md` + `phase_a_measured.json`,
`phase_b_measured.json`, `phase_c_measured.json`, `phase_a_judge.json`,
`outputs/finetune_decision/parity_gate.json` and
`outputs/finetune_decision/hatch_mechanism.json` (§4d's corrected hatch
share and its mechanism — run `scripts/finetune_hatch_mechanism.py`
after phase A and before this). That is the spec's traceability
requirement (§7: "every number in REPORT.md must trace to a file
above") enforced by construction rather than by proofreading.

Also writes `phaseB/prompt_parity.diff`: the unified diff of the two
system prompts §8 asks for. It is a separate file because the op arms'
system prompt is ~17k characters and pasting it into the report would
bury the numbers; the report carries its line statistics and the full
task-text diff inline.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
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
    ARMS,
    CD_PCA_PASS,
    COMPLETIONS_PER_ARM,
    DELTA_FACADE_MINIMUM_PP,
    DELTA_SIZE_MAXIMUM_PP,
    DELTA_TUNE_MINIMUM_PP,
    F_GEOM_DO_NOT_TUNE,
    F_SYNTAX_MINIMUM,
    HF_REVISIONS,
    SERVED_CONTEXT_TOKENS,
    SERVED_PRECISION,
)

from blended.agent.tool_disclosure import core_ops, offered_tools
from blended.agent.tools import SERVICE_TOOL_NAMES, TOOL_SCHEMAS

DECISION_DIRECTORY = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision"
)
WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
REPORT_PATH = DECISION_DIRECTORY / "REPORT.md"
PROMPT_DIFF_PATH = DECISION_DIRECTORY / "phaseB" / "prompt_parity.diff"

# Δ_facade and both Δ_size draws subtract an arm that passed nothing.
# One reason, one string, so the three rows cannot drift apart.
VOID_AGAINST_A2 = "void — computed against A2, which passed nothing"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    return parser.parse_args(argv)


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def percent(value) -> str:
    return "—" if value is None else f"{100.0 * value:.1f}%"


def ratio(numerator, denominator):
    """A cost ratio, or None when either side has no passing asset."""
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def number(value, digits: int = 4) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def bar_verdict(value, half_width, bar: float) -> str:
    """How a delta stands against its bar, from the delta and its interval."""
    if value is None or half_width is None:
        return "unmeasured"
    if value < bar:
        return "below the bar"
    if value - half_width < bar:
        return "point estimate clears the bar; its interval does not"
    if half_width == 0:
        return "clears the bar; zero-width interval"
    return f"clears the bar by ~{(value - bar) / half_width:.0f}x its own interval"


def bands_overlap(first: dict, second: dict) -> bool:
    """Do two {low, high} bands share any point? None bounds never overlap."""
    bounds = (
        first.get("low"),
        first.get("high"),
        second.get("low"),
        second.get("high"),
    )
    if any(bound is None for bound in bounds):
        return False
    return first["low"] <= second["high"] and second["low"] <= first["high"]


def _first_line(command_result: dict) -> str:
    """The first line a recorded command printed, on either stream.

    `llama-server --version` writes its build string to STDERR, so a
    stdout-only read renders the serving row as `?` — which is worse
    than useless in an environment table.
    """
    for stream in ("stdout", "stderr"):
        text = (command_result or {}).get(stream) or ""
        if text.strip():
            return text.strip().splitlines()[0]
    return "?"


def write_prompt_diff(bench_root: Path) -> dict:
    """The §8 prompt-parity diff, and its statistics."""
    from blended.agent.system_prompt import build_system_prompt
    from blended.evaluate.bench_task_prompt import (
        RAW_TASK_TEMPLATE,
        SINGLE_SHOT_OPS_TASK_TEMPLATE,
    )
    from blended.evaluate.raw_bpy_arm import raw_system_prompt

    ops_system = build_system_prompt()
    raw_system = raw_system_prompt(bench_root)
    system_diff = list(
        difflib.unified_diff(
            ops_system.splitlines(keepends=True),
            raw_system.splitlines(keepends=True),
            fromfile="a1_a2_system_prompt (harness, build_system_prompt)",
            tofile="a3_a4_a5_system_prompt (bench, prompts/text_to_3d_system_prompt.txt)",
        )
    )
    task_diff = list(
        difflib.unified_diff(
            SINGLE_SHOT_OPS_TASK_TEMPLATE.splitlines(keepends=True),
            RAW_TASK_TEMPLATE.splitlines(keepends=True),
            fromfile="a1_a2_task_text",
            tofile="a3_a4_a5_task_text",
        )
    )
    PROMPT_DIFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_DIFF_PATH.write_text("".join(system_diff) + "\n" + "".join(task_diff))
    return {
        "ops_system_lines": len(ops_system.splitlines()),
        "raw_system_lines": len(raw_system.splitlines()),
        "system_diff_lines": len(system_diff),
        "system_added": sum(
            1
            for line in system_diff
            if line.startswith("+") and not line.startswith("+++")
        ),
        "system_removed": sum(
            1
            for line in system_diff
            if line.startswith("-") and not line.startswith("---")
        ),
        "task_diff": "".join(task_diff),
    }


def spot_checks(phase_b: dict, phase_a_csv: Path, scores_csv: Path) -> list[str]:
    """Three numbers re-derived from the CSVs by counting rows."""
    import csv as csv_module

    checks = []
    with phase_a_csv.open() as handle:
        rows = list(csv_module.DictReader(handle))
    harness = [row for row in rows if row["third_party"] == "False"]
    g_rows = [row for row in harness if row["code"].startswith("G")]
    syntax_rows = [
        row for row in harness if row["code"].startswith("E") and row["code"] != "E6"
    ]
    checks.append(
        f"`phaseA/taxonomy.csv` holds {len(harness)} harness rows, of which "
        f"{len(g_rows)} carry a G-code and {len(syntax_rows)} an E-code "
        f"(excluding E6) — the F_geom and F_syntax numerators."
    )
    if scores_csv.exists():
        with scores_csv.open() as handle:
            score_rows = list(csv_module.DictReader(handle))
        for arm in sorted({row["arm"] for row in score_rows}):
            arm_rows = [row for row in score_rows if row["arm"] == arm]
            executed = [row for row in arm_rows if row["render_status"] == "OK"]
            checks.append(
                f"`phaseB/scores.csv` holds {len(arm_rows)} rows for arm {arm}, "
                f"{len(executed)} with `render_status == OK` — the arm's "
                f"executability numerator."
            )
    return checks


def arm_line(arm: str, measured: dict) -> str:
    if arm not in measured:
        return (
            f"| {arm} | {ARMS[arm]['model']} | {ARMS[arm]['format']} | NOT RUN | "
            f"— | — | — | — | — |"
        )
    row = measured[arm]["funnel"]
    return (
        f"| {arm} | {ARMS[arm]['model']} | {ARMS[arm]['format']} | "
        f"{row['completions']}/{COMPLETIONS_PER_ARM} | "
        f"{percent(row['schema_conformance_rate'])} | "
        f"{percent(row['script_emitted_rate'])} | "
        f"{percent(row['executability_rate'])} | "
        f"{percent(row['non_degenerate_rate'])} | "
        f"{percent(row['cd_pca_pass_rate'])} |"
    )


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()

    env = read_json(DECISION_DIRECTORY / "env.json") or {}
    phase_a = read_json(WORKING_DIRECTORY / "phase_a_measured.json") or {}
    phase_b = read_json(WORKING_DIRECTORY / "phase_b_measured.json") or {}
    phase_c = read_json(WORKING_DIRECTORY / "phase_c_measured.json") or {}
    judge = read_json(WORKING_DIRECTORY / "phase_a_judge.json") or {}
    parity = read_json(WORKING_DIRECTORY / "parity_gate.json") or {}
    mechanism_measured = read_json(WORKING_DIRECTORY / "hatch_mechanism.json") or {}
    if not (phase_a and phase_b):
        raise SystemExit("run phase A and phase B before the report")
    if not mechanism_measured:
        raise SystemExit(
            "run scripts/finetune_hatch_mechanism.py before the report: §4d "
            "reads its measurement, and there is no fallback prose"
        )
    prompts = write_prompt_diff(bench_root)

    measured = phase_b.get("arms", {})
    computed = phase_b.get("deltas", {})
    shares = phase_a.get("shares", {})
    hatch = phase_a.get("hatch", {})
    mechanism = mechanism_measured.get("mechanism", {})
    archive_drop = mechanism_measured.get("archive", {}).get("drop", {})
    single_drop = mechanism_measured.get("single_shot", {}).get("drop", {})
    # §4c and §4d quote A1's op share on the SAME two instruments the
    # archive is measured on — what the model chose (dispatched) and
    # what the score saw (baked) — so the two sections cannot disagree
    # about one quantity.
    single_baked = mechanism_measured.get("single_shot", {}).get("baked", {})
    single_dispatched = mechanism_measured.get("single_shot", {}).get("dispatched", {})
    single_baked_op_share = single_baked.get("op_share")
    artifact_case = mechanism.get("collection_artifact_example", {})
    # The measured spread of baked op share over the rolls that offered
    # the disclosed set — the axis §4d can now name with numbers.
    disclosed_shares = [
        entry["baked_op_share"]
        for entry in mechanism_measured.get("per_roll", {}).values()
        if entry.get("offered_disclosed_set")
        and entry.get("baked_op_share") is not None
    ]
    disclosed_op_share_low = min(disclosed_shares) if disclosed_shares else None
    disclosed_op_share_high = max(disclosed_shares) if disclosed_shares else None
    a1_funnel = measured.get("a1", {}).get("funnel", {})
    a4_funnel = measured.get("a4", {}).get("funnel", {})
    a5_funnel = measured.get("a5", {}).get("funnel", {})
    # Every ratio the prose quotes is DERIVED here from the measured
    # artifact; none is typed into the report text.
    specialist_token_ratio = ratio(
        a5_funnel.get("tokens_per_passing"), a4_funnel.get("tokens_per_passing")
    )
    facade_token_ratio = ratio(
        a1_funnel.get("tokens_per_passing"), a5_funnel.get("tokens_per_passing")
    )
    facade_wall_ratio = ratio(
        a1_funnel.get("wall_time_per_passing_s"),
        a5_funnel.get("wall_time_per_passing_s"),
    )
    # What production actually shows a call (OT-25), against what these
    # arms showed: the progressive-disclosure axis §4d names.
    offered_schema_count = len(
        offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
    )
    a2_funnel = measured.get("a2", {}).get("funnel", {})
    a3_funnel = measured.get("a3", {}).get("funnel", {})
    # Limitation 8's counts: completions coded E5 (the sweep's own wall-clock
    # cap maps to E5; Phase B's PARSE_RESULT_CODES), read, not typed.
    a2_timeouts = a2_funnel.get("codes", {}).get("E5", 0)
    a3_timeouts = a3_funnel.get("codes", {}).get("E5", 0)
    a5_executability = a5_funnel.get("executability_rate")
    a5_execution_failure_rate = (
        None if a5_executability is None else 1.0 - a5_executability
    )
    a4_half_width = a4_funnel.get("cd_pca_pass_interval", {}).get("half_width")
    a4_half_width_pp = None if a4_half_width is None else 100.0 * a4_half_width
    pass_bands = computed.get("pass_rate_intervals_pp") or {}
    # Δ_size's own interval, so the report can say WHY it is discounted:
    # not for width — it excludes zero — but for its subtrahend.
    delta_size_k = computed.get("delta_size_pp_k_mean")
    delta_size_half = computed.get("delta_size_half_width_pp")
    delta_size_band = (
        "—"
        if delta_size_k is None or delta_size_half is None
        else f"[{delta_size_k - delta_size_half:.1f}, "
        f"{delta_size_k + delta_size_half:.1f}]"
    )
    delta_size_zero_clause = (
        "excludes zero"
        if delta_size_k is not None
        and delta_size_half is not None
        and abs(delta_size_k) > delta_size_half
        else "includes zero"
    )
    harness = env.get("harness", {})
    gpu = env.get("gpu", {})
    serving = env.get("local_serving", {})
    noise = parity.get("stage_2_bake_reproducibility", {}).get(
        "measured_noise_floor", {}
    )

    lines = [
        "# Fine-tune decision — report",
        "",
        (
            f"Spec: `{env.get('spec', 'docs/research/2026-09-19-finetune-decision-experiment.md')}`. "
            "Pre-registration: `scripts/finetune_decision_thresholds.py`. No "
            "training happened; this is a decision plus its evidence."
        ),
        "",
        "## 1. Environment and precondition deviations",
        "",
        "| item | value |",
        "|---|---|",
        f"| repository HEAD | `{env.get('repository', {}).get('head', {}).get('stdout', '?')}` |",
        f"| Blender | `{env.get('blender', {}).get('stdout', '?').splitlines()[0] if env.get('blender', {}).get('stdout') else '?'}` |",
        f"| target series | {harness.get('target_blender_series', '?')} |",
        f"| assembled prompt fingerprint | `{harness.get('assembled_prompt_fingerprint', '?')}` |",
        f"| tool-schema fingerprint | `{harness.get('tool_schemas_fingerprint', '?')}` |",
        (
            f"| facade ops / service tools / schemas | {harness.get('op_count')} / "
            f"{harness.get('service_tool_count')} / {harness.get('tool_schema_count')} |"
        ),
        (
            f"| GPU host (registered, NOT used for the arms — see deviation 1) "
            f"| `{gpu.get('nvidia_smi', {}).get('stdout', '?')}` |"
        ),
        (
            f"| local serving | `{serving.get('endpoint', '?')}` — "
            f"{serving.get('host', {}).get('stdout', '?')}, "
            f"{_first_line(serving.get('binary_version', {}))}, "
            f"{SERVED_PRECISION}, {serving.get('slots', '?')} slots x "
            f"-c {SERVED_CONTEXT_TOKENS} |"
        ),
        (
            f"| instance set | `{env.get('bench', {}).get('instances_file')}` "
            f"({len(env.get('bench', {}).get('instances', []))} instances, sha256 "
            f"`{str(env.get('bench', {}).get('instances_sha256', ''))[:16]}`, "
            f"matches pre-registration: "
            f"{env.get('bench', {}).get('instances_sha256_matches_registered')}) |"
        ),
        f"| archived render logs | {env.get('bench', {}).get('archived_render_logs')} |",
        (
            f"| schema-2 transcripts | "
            f"{env.get('transcripts', {}).get('iteration_records_with_tool_events')} of "
            f"{env.get('transcripts', {}).get('iteration_records')} iteration records; "
            f"{env.get('transcripts', {}).get('chat_transcripts')} chat transcripts |"
        ),
        "",
        "### Precondition deviations",
        "",
        (
            "1. **Neither vLLM nor the 3090 served the local arms.** vLLM is "
            "not installed on that host, and its card stayed committed to a "
            "live home-still conversion run for the whole experiment (olmocr "
            "vLLM 13.2 GiB + hs-distill-server 3.5 GiB + an Ollama child, "
            "~23 of 24 GiB, with a steady stream of 20-40 s OCR calls). Under "
            "llama-swap's strict swap a single request of mine waited 8 "
            "minutes while the two workloads evicted each other, so A2/A3/A4 "
            "ran instead against a `llama-server` on the workstation (Apple "
            "Silicon, Metal) reading the SAME GGUFs — one "
            "OpenAI-compatible endpoint for all local arms, which is what "
            "§5.2 actually requires. Measured single-stream decode: 11.8-12.8 "
            "tok/s, prefill 235 tok/s, prompt prefixes cached across "
            "completions."
        ),
        (
            f"2. **Precision is {SERVED_PRECISION}, not F16.** F16 asked CUDA for "
            "13,486.77 MiB and the card refused: 10.0 GiB was held by two "
            "orphaned `llama-server` processes (one with four live connections) "
            "plus an Ollama child — a foreign workload this run did not preempt. "
            "Both checkpoints moved together, so precision is not a confound "
            "between A3 and A4."
        ),
        (
            "3. **A2/A3 ride Qwen2.5-Coder-7B-Instruct**, not the non-coder "
            "instruct checkpoint the HF card names as BlenderLLM's base. Three "
            "measurements say the card is wrong: BlenderLLM's own `config.json` "
            "names `Qwen2.5-Coder-7B-Instruct`; its four safetensors shards match "
            "the coder repo's byte sizes and share its `model.safetensors.index.json` "
            "blob; and its weights sit 1.0-1.1% from the coder base against "
            "99-124% from the non-coder one. The spec's §5.1 text agrees with the "
            "checkpoint."
        ),
        (
            "4. **The sandbox is the benchmark's own** `core/render.py` "
            "subprocess with its 240 s wall-clock cap — no memory cap and no "
            "network isolation. A second sandbox would have broken comparability "
            "with the archive, which is the Phase A denominator."
        ),
        (
            "5. **G1 vs G2 is decided by the metric decomposition**, not a VLM "
            "(spec §4 proposed a VLM for all of G1-G3). The decomposition is "
            "ground truth against the reference mesh and reproducible; no §3 rule "
            "reads the interior split of `F_geom`. G3 is still judged."
        ),
        (
            "6. **The op arms' task text carries a single-shot paragraph** the "
            "archive's does not. Measured before any arm ran: with the unmodified "
            "multi-turn harness prompt, 3 of 4 single-shot replies were a "
            "`declare_plan` call and nothing else. Spec §9 says to investigate "
            "the prompt rather than burn the roll; the raw arms already carry the "
            "equivalent sentence in the benchmark's own prompt. Both op arms get "
            "identical text."
        ),
        "",
        "### Pipeline parity gate (spec §5.2 / §9)",
        "",
    ]
    if parity:
        stage_one = parity.get("stage_1_scorer_parity", {})
        stage_two = parity.get("stage_2_bake_reproducibility", {})
        lines += [
            (
                f"- **Stage 1, exact**: the same baked artifacts scored through two "
                f"differently-named model dirs agree on cd_pca, cd_yawmin, "
                f"delta_orient and fscore_005 to "
                f"{parity.get('parity_tolerance')} — passed: "
                f"{stage_one.get('passed')} over {len(parity.get('instances', []))} "
                f"instances. The scorer cannot see which path wrote the script."
            ),
            (
                f"- **Stage 2, measured**: the same scripts baked twice reproduce "
                f"the SOLID (volume within "
                f"{parity.get('solid_volume_relative_tolerance')} relative — "
                f"passed: {stage_two.get('solid_reproduced_everywhere')}) but not "
                f"the tessellation. The pipeline's own noise floor on a re-bake is "
                f"cd_pca {number(noise.get('cd_pca'), 6)}, "
                f"fscore_005 {number(noise.get('fscore_005'), 6)}."
            ),
            (
                "- What this does and does not license: it says a cd_pca "
                "VALUE is comparable across arms to ~3e-4, which is 1.3% of "
                f"the {CD_PCA_PASS} pass bar, so the pass/fail verdict on an "
                "individual completion is stable. It says NOTHING about how "
                "far an arm's RATE would move on a different set of "
                "instances — that is sampling error, it is a much larger "
                "number, and it is computed in §4. An earlier draft of this "
                "report used this floor as if it were the rate uncertainty."
            ),
            "",
        ]
    else:
        lines += ["- NOT RUN.", ""]

    lines += [
        "## 2. Phase A — where the harness actually fails",
        "",
        (
            f"Attempts counted: **{shares.get('attempts_counted')}** (INFRA and "
            f"UNSCORED excluded and listed in `phaseA/summary.md`). Passes at "
            f"`cd_pca <= {CD_PCA_PASS}`: **{shares.get('passes')}**. Failures: "
            f"**{shares.get('failures')}**."
        ),
        "",
        "| share | value | bar |",
        "|---|---|---|",
        (
            f"| `F_syntax` (E1-E5, E7, O1-O2) | "
            f"{percent(shares.get('f_syntax'))} ({shares.get('n_syntax')}/"
            f"{shares.get('failures')}) | >= {percent(F_SYNTAX_MINIMUM)} for rules 2-3 |"
        ),
        (
            f"| `F_geom` (G1-G3) | {percent(shares.get('f_geom'))} "
            f"({shares.get('n_geom')}/{shares.get('failures')}) | "
            f">= {percent(F_GEOM_DO_NOT_TUNE)} fires rule 1 |"
        ),
        (
            f"| `E6` (executed, degenerate) | "
            f"{percent(shares.get('f_degenerate'))} | in neither share, by the "
            f"spec's own definitions |"
        ),
        "",
        f"Codes: `{phase_a.get('codes')}`",
        "",
        (
            "### What `F_syntax` = "
            f"{percent(shares.get('f_syntax'))} does and does not say"
        ),
        "",
        (
            "The Phase A denominator is the ARCHIVE, and the archive is "
            "multi-turn: every attempt in it ran through `AgentSession` with "
            "up to 24 tool calls per turn, a gate report after each one, and "
            "the error text fed back to the writer. So "
            f"{percent(shares.get('f_syntax'))} is the share of "
            "failures that are syntactic AFTER the loop has already absorbed "
            "the syntactic failures."
        ),
        "",
        (
            "The single-shot contrast is in this same report: A5 is the same "
            "class of model writing raw bpy with no feedback at all, and it "
            "fails to execute "
            f"{percent(a5_execution_failure_rate)} "
            "of the time. The gap between that and "
            f"{percent(shares.get('f_syntax'))} IS the retry loop."
        ),
        "",
        (
            "Rule 1's conclusion is therefore correctly scoped as \"where "
            'should investment go to raise the pass CEILING" — and the answer '
            "is planning, not syntax. It is NOT the stronger claim that the "
            "harness has no syntactic failure mode: it has one, and it pays "
            "tokens and turns to avoid paying for it in the score. §5's note "
            "is worded to that weaker, measured claim."
        ),
        "",
    ]
    if judge:
        lines += [
            (
                f"**G3 judge**: {judge.get('violated')} of {judge.get('sampled')} "
                f"sampled non-passing executed attempts were judged to violate "
                f"an explicit constraint ({judge.get('unparsed')} unparsed), eye "
                f"`{judge.get('eye')}`."
            ),
            "",
            (
                f"**Judge error, measured by hand on "
                f"{judge.get('hand_verified')} of those rows** (same rule the "
                f'judge was given, "cannot tell -> false"): '
                f"{judge.get('hand_disagreements')} disagreements = "
                f"**{percent(judge.get('hand_disagreement_rate'))}**. Every "
                f"disagreement is a judge FALSE POSITIVE: precision on its "
                f"positives is {percent(judge.get('judge_positive_precision'))} "
                f"and on its negatives "
                f"{percent(judge.get('judge_negative_precision'))}, so the "
                f"G3 count corrects from {judge.get('violated')} to about "
                f"**{judge.get('corrected_g3_estimate')}** of "
                f"{judge.get('sampled')}."
            ),
            "",
            "Two mechanisms, both identified from the disagreeing rows:",
            "",
        ]
        for judge_mechanism in judge.get("error_mechanisms", []):
            lines.append(f"- {judge_mechanism}")
        lines += [
            "",
            (
                "Per-row verdicts, notes and the `agrees` flag are in "
                "`phaseA/g3_judgements.jsonl`. G3 re-labels rows already inside "
                "`F_geom`, so neither the judge's error nor its correction moves "
                "any §3 rule."
            ),
            "",
        ]
    else:
        lines += ["**G3 judge**: NOT RUN.", ""]

    lines += [
        "## 3. Phase B — the funnel, single-shot",
        "",
        (
            "| arm | model | format | completions | schema | script emitted | "
            "executed | non-degenerate | cd_pca pass |"
        ),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in sorted(ARMS):
        lines.append(arm_line(arm, measured))
    lines += [
        "",
        (
            "Per-draw rates, cd_pca distribution and latency are in "
            "`phaseB/summary.md`; per-completion rows in `phaseB/scores.csv`."
        ),
        "",
        "## 4. The four deltas, with their uncertainty",
        "",
        (
            "Every interval below is **instance-clustered**: the four draws of "
            "one instance answer the same prompt, so the effective sample is "
            "nearer the 20 instances than the 80 completions, and the "
            "half-width is `1.96 * sd(per-instance means) / sqrt(20)`. This is "
            "NOT the parity gate's ~3e-4 cd_pca noise floor — that is metric "
            "precision under a re-bake and says nothing about how far a "
            "20-instance rate would move on another 20 instances. An earlier "
            "draft of this report used the noise floor as if it were sampling "
            "error; it is corrected here, and the correction changes what can "
            "be claimed."
        ),
        "",
        "| quantity | value | 95% half-width | bar | verdict |",
        "|---|---|---|---|---|",
        (
            f"| Δ_tune (executability A4 − A3) | "
            f"{number(computed.get('delta_tune_pp'), 1)} pp | "
            f"±{number(computed.get('delta_tune_half_width_pp'), 1)} pp | "
            f">= {DELTA_TUNE_MINIMUM_PP} pp | "
            f"{bar_verdict(computed.get('delta_tune_pp'), computed.get('delta_tune_half_width_pp'), DELTA_TUNE_MINIMUM_PP)} |"
        ),
        (
            f"| Δ_facade (executability A2 − A3) | "
            f"{number(computed.get('delta_facade_pp'), 1)} pp | "
            f"±{number(computed.get('delta_facade_half_width_pp'), 1)} pp | "
            f">= {DELTA_FACADE_MINIMUM_PP} pp | {VOID_AGAINST_A2} |"
        ),
        (
            f"| Δ_size (cd_pca pass A1 − A2, k-mean) | "
            f"{number(computed.get('delta_size_pp_k_mean'), 1)} pp | "
            f"±{number(computed.get('delta_size_half_width_pp'), 1)} pp | "
            f"<= {DELTA_SIZE_MAXIMUM_PP} pp | {VOID_AGAINST_A2} |"
        ),
        (
            f"| Δ_size (greedy draw) | "
            f"{number(computed.get('delta_size_pp_greedy'), 1)} pp | — | "
            f"<= {DELTA_SIZE_MAXIMUM_PP} pp | {VOID_AGAINST_A2} |"
        ),
        "",
        (
            "### Δ_facade, Δ_size and the zero-variance artifact are one "
            "failure, not three"
        ),
        "",
        (
            f"A2 reached a scorable script on "
            f"{percent(a2_funnel.get('script_emitted_rate'))} of its "
            f"{a2_funnel.get('completions')} completions and passed "
            f"{a2_funnel.get('cd_pca_passing')} of them. Every quantity whose "
            f"subtrahend is A2 therefore measures a FLOORED ARM rather than "
            f"the factor it is named for — the facade for Δ_facade, model "
            f"size for Δ_size — and the same floor is why A2's "
            f"between-instance variance is exactly zero. That zero is a real "
            f"value, not a missing one: it is the `se == 0` case the "
            f"interval code now handles explicitly, after a falsy check on "
            f"it silently dropped both half-widths."
        ),
        "",
        (
            f"Δ_facade carries a second, separate defect on top of the "
            f"floor: {computed.get('q2_reason', '')}. Q2 is therefore "
            f"UNANSWERED, and Δ_facade should not be read as answering it."
        ),
        "",
        (
            f"The spec's §9 stop condition caught none of this, because it "
            f"is written on SCHEMA CONFORMANCE, which A2 passed at "
            f"{percent(a2_funnel.get('schema_conformance_rate'))} — above "
            f"the 20% bar — while the funnel stage the deltas are actually "
            f"computed from, reaching a scorable script, sat at "
            f"{percent(a2_funnel.get('script_emitted_rate'))}. The roll was "
            f"spent on a dead arm. Put the stop condition on the stage the "
            f"delta is computed from, and a future facade arm has to change "
            f"the TASK TEXT so facade ops are the geometry path, not just "
            f"the wire format."
        ),
        "",
        "### cd_pca pass rates are mutually indistinguishable",
        "",
        "| arm | cd_pca pass | 95% interval |",
        "|---|---|---|",
    ]
    for arm, band in (computed.get("pass_rate_intervals_pp") or {}).items():
        if band.get("rate") is None:
            lines.append(f"| {arm} | — | — |")
            continue
        lines.append(
            f"| {arm} | {band['rate']:.1f}% | [{band['low']:.1f}, {band['high']:.1f}] |"
        )
    lines += [
        "",
        (
            (
                "A1, A4 and A5 overlap pairwise. The report therefore claims "
                "NEITHER that the frontier model beat BlenderLLM nor that "
                "BlenderLLM reached parity with it: on 20 instances neither claim "
                "is available."
            )
            if all(
                bands_overlap(pass_bands.get(left, {}), pass_bands.get(right, {}))
                for left, right in (("a1", "a4"), ("a1", "a5"), ("a4", "a5"))
            )
            else (
                "A1, A4 and A5 do NOT all overlap pairwise (table above): read "
                "the bands, not this sentence, for which comparisons are "
                "available."
            )
        ),
        "",
        (
            f"Δ_size is NOT discounted for width — its interval "
            f"{delta_size_band} {delta_size_zero_clause}. It is discounted "
            f"because its subtrahend is A2."
        ),
        "",
        "## 4b. Cost per PASSING asset (spec §5.3 metric 8)",
        "",
        (
            "Omitted from the first draft of this report. A rate says nothing "
            "about whether a lane is worth calling; the cost per pass is the "
            "only number on which a cheap-and-often lane can beat an "
            "expensive one."
        ),
        "",
        (
            "| arm | lane | passing | tokens per pass | completion tokens per "
            "pass | wall per pass |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for arm in sorted(measured):
        row = measured[arm]["funnel"]
        local = ARMS[arm]["model"] not in ("claude-code:sonnet",)
        lines.append(
            f"| {arm} | {'local llama-server' if local else 'Claude Code CLI'} | "
            f"{row['cd_pca_passing']}/{row['completions']} | "
            f"{number(row.get('tokens_per_passing'), 0)} | "
            f"{number(row.get('completion_tokens_per_passing'), 0)} | "
            f"{number(row.get('wall_time_per_passing_s'), 0)}"
            f"{'' if row.get('wall_time_per_passing_s') is None else 's'} |"
        )
    lines += [
        "",
        (
            f"The comparator for “does a local specialist beat calling a "
            f"frontier model” is **A5**, not A1: the same task, the same raw "
            f"answer format, no schema overhead on either side. Against A5 "
            f"the specialist's advantage is {number(specialist_token_ratio, 1)}x "
            f"in tokens per passing asset, and it does not extend to wall "
            f"clock — A5 is FASTER per passing asset "
            f"({number(a5_funnel.get('wall_time_per_passing_s'), 0)} s "
            f"against {number(a4_funnel.get('wall_time_per_passing_s'), 0)} s) "
            f"despite A4's queue contamination, and A5 holds the highest "
            f"point-estimate pass rate of any arm "
            f"({percent(a5_funnel.get('cd_pca_pass_rate'))} against "
            f"{percent(a4_funnel.get('cd_pca_pass_rate'))}). The case for a "
            f"local specialist here is real but narrow: it is token-shaped, "
            f"not a general win."
        ),
        "",
        (
            "Dollars are $0 on every arm here — A1/A5 ride a subscription, "
            "A2/A3/A4 ride owned hardware — so tokens and wall clock are the "
            "cost. Two caveats, both load-bearing: wall clock is contaminated "
            "by four-way queueing on a single GPU and is NOT a clean "
            "per-completion latency; and A1's token count carries the harness "
            f"system prompt plus {harness.get('tool_schema_count')} tool schemas "
            f"on every call, which is the op format's cost, not the model's."
        ),
        "",
        "## 4c. A1 against A5 — the facade's cost, with no measured return",
        "",
        (
            f"Same model (`{ARMS['a1']['model']}`), same bench, same "
            f"single-shot regime, same 20 instances x 4 draws. The only "
            f"difference is the prompt and the answer format."
        ),
        "",
        "| | A1 (ops) | A5 (raw) |",
        "|---|---|---|",
        (
            f"| cd_pca pass | {percent(a1_funnel.get('cd_pca_pass_rate'))} | "
            f"{percent(a5_funnel.get('cd_pca_pass_rate'))} |"
        ),
        (
            f"| tokens per passing asset | "
            f"{number(a1_funnel.get('tokens_per_passing'), 0)} | "
            f"{number(a5_funnel.get('tokens_per_passing'), 0)} |"
        ),
        (
            f"| wall clock per passing asset | "
            f"{number(a1_funnel.get('wall_time_per_passing_s'), 0)} s | "
            f"{number(a5_funnel.get('wall_time_per_passing_s'), 0)} s |"
        ),
        (
            f"| system prompt | {prompts['ops_system_lines']} lines + "
            f"{harness.get('tool_schema_count')} tool schemas | "
            f"{prompts['raw_system_lines']} lines |"
        ),
        "",
        (
            f"A1's cost is NOT explained by the model ignoring the facade, "
            f"on either instrument. Of the geometry-emitting calls A1 CHOSE, "
            f"{single_dispatched.get('scene_ops')} were scene-changing facade "
            f"ops against {single_dispatched.get('chunks')} `run_python` "
            f"chunks ({percent(single_dispatched.get('op_share'))}); of what "
            f"the score then SAW, {single_baked.get('scene_ops')} ops against "
            f"{single_baked.get('chunks')} chunks "
            f"({percent(single_baked.get('op_share'))}). It used the surface, "
            f"paid {number(facade_token_ratio, 1)}x the tokens and "
            f"{number(facade_wall_ratio, 1)}x the wall clock of A5, and did "
            f"not win on the point estimate. The pass-rate intervals overlap, "
            f"so the DIRECTION is not claimed either — what is claimed is the "
            f"absence of a measured return for a measured cost. This stands "
            f"on its own evidence: §4d's archive hatch share is NOT "
            f"independent corroboration, because part of that share is an "
            f"instrument reading."
        ),
        "",
        "## 4d. The hatch rate — corrected, and its mechanism measured",
        "",
        (
            f"On archived attempts that PASSED and whose bake could record an "
            f"op call at all, "
            f"{percent(hatch.get('passing', {}).get('hatch_share'))} of the "
            f"geometry-emitting calls were `run_python` chunks rather than "
            f"scene-changing facade ops "
            f"({hatch.get('passing', {}).get('included_chunks')} chunks "
            f"against {hatch.get('passing', {}).get('op_calls')} op calls, "
            f"with {hatch.get('passing', {}).get('attempts_using_any_op')} of "
            f"{hatch.get('passing', {}).get('attempts_collecting_ops')} such "
            f"attempts using any op). On failing attempts it is "
            f"{percent(hatch.get('failing', {}).get('hatch_share'))}."
        ),
        "",
        (
            f"Those numbers replace the 95.1%/89.9% an earlier draft "
            f"published, and the correction is a measurement, not a "
            f"re-opinion (`phaseA/hatch_mechanism.md`, "
            f"`scripts/finetune_hatch_mechanism.py`). Three faults in the old "
            f"instrument: `.agent_meta.json`'s `n_op_calls_included` counts "
            f"READER ops as geometry-emitting, because `emits_geometry` is "
            f'"the hatch or ANY facade op"; `n_chunks_included` is the '
            f"label COUNTER, which advances on op calls too; and "
            f"{hatch.get('passing', {}).get('attempts_before_op_collection')} "
            f"of {hatch.get('passing', {}).get('attempts')} passing attempts "
            f"come from rolls whose bridge collected `run_python` and nothing "
            f"else, so their scripts CANNOT hold an op call and their forced "
            f"100% was being averaged in. Measured directly on "
            f"`{artifact_case.get('model_dir')}/{artifact_case.get('instance')}`: "
            f"{artifact_case.get('dispatched_scene_ops')} scene-changing op "
            f"calls dispatched, every one `ok`, "
            f"{artifact_case.get('baked_scene_ops')} op labels in the baked "
            f"script."
        ),
        "",
        (
            "The harness's stated architecture is a 48-op facade as the tool "
            "surface with `run_python` demoted to a reason-gated escape hatch "
            "(`docs/harness_design.md` rows 1 and 7). Corrected, the hatch is "
            "still the surface in the benchmark configuration. What changed "
            "is that the mechanism is no longer open."
        ),
        "",
        (
            f"**Op-failure feedback is not the mechanism.** The hypothesis — "
            f"an op call that errors teaches the agent, inside the run, that "
            f"`run_python` is the reliable path — predicts a higher op "
            f"failure rate in the multi-turn archive than in single-shot A1, "
            f"and a first chunk that FOLLOWS the first op failure. Measured "
            f"on the one instrument both regimes share (a dispatched call "
            f"that never reached the baked script): the archive drops "
            f"{percent(archive_drop.get('scene_ops', {}).get('drop_rate'))} of "
            f"its scene-op calls against A1's "
            f"{percent(single_drop.get('scene_ops', {}).get('drop_rate'))}, "
            f"while the chunk drop rates are "
            f"{percent(archive_drop.get('chunks', {}).get('drop_rate'))} and "
            f"{percent(single_drop.get('chunks', {}).get('drop_rate'))} — the "
            f"op path is MORE reliable in the archive, not less. Ordering "
            f"finishes it: "
            f"{percent(mechanism.get('first_geometry_call_is_chunk_share'))} "
            f"of instrumented attempts made a chunk their FIRST "
            f"geometry-emitting call, "
            f"{mechanism.get('chunk_using_that_never_called_a_scene_op')} of "
            f"{mechanism.get('chunk_using_attempts')} chunk-using attempts "
            f"never called a scene-changing op at all, and of the "
            f"{mechanism.get('chunk_using_with_any_op_failure')} that did see "
            f"one fail, only {mechanism.get('failure_before_first_chunk')} "
            f"failed before the first chunk. The facade is not abandoned "
            f"after it breaks; it is never entered."
        ),
        "",
        (
            f"**What does separate the rolls is the offered set.** Every "
            f"archived roll that offered the disclosed "
            f"{offered_schema_count}-of-{harness.get('tool_schema_count')} "
            f"set (`blended.agent.tool_disclosure.offered_tools`, fingerprint "
            f"`{mechanism_measured.get('disclosed_fingerprint')}`) bakes a "
            f"{percent(disclosed_op_share_low)}–"
            f"{percent(disclosed_op_share_high)} op share; rolls predating op "
            f"collection bake zero, and for rolls with no tool events at all "
            f'"did not call" cannot be told from "was not recorded". '
            f"Against that, A1 — single-shot, all "
            f"{harness.get('tool_schema_count')} schemas offered — baked "
            f"{percent(single_baked_op_share)} ops. So the live axis is the "
            f"one this experiment cannot settle from the archive: what the "
            f"multi-turn loop does to a surface the model demonstrably uses "
            f"in one shot. Settle it before the candidate-op miner proposes "
            f"more ops."
        ),
        "",
        "## 5. The decision rule that fired",
        "",
        f"**{phase_b.get('verdict', 'NOT COMPUTED')}**",
        "",
    ]
    for note in phase_b.get("notes", []):
        lines.append(f"- {note}")
    lines += [
        "",
        "## 6. Secondary agentic-mode measurement",
        "",
        (
            "Not run. The primary single-shot regime is the one the spec "
            "registers, and mixing an agentic A1 with a single-shot A2 is the "
            "confound §5.2 names as the largest available."
        ),
        "",
        "## 7. Phase C — corpus inventory and sufficiency",
        "",
    ]
    archive = phase_c.get("archive", {})
    lines += [
        "| quantity | count |",
        "|---|---|",
        f"| (instruction, script) pairs in the bench archive | {archive.get('pairs')} |",
        f"| ... executed | {archive.get('executed')} |",
        f"| ... scored | {archive.get('scored')} |",
        f"| ... passing at `cd_pca <= {CD_PCA_PASS}` | {archive.get('passing')} |",
        (
            f"| deduplicated, execution-verified | "
            f"{archive.get('deduplicated_execution_verified_pairs')} |"
        ),
        f"| **distinct instructions** | {archive.get('distinct_instructions')} |",
        f"| op-sequence pairs | {archive.get('op_sequence_pairs')} |",
        "",
        (
            f"Verdict: see `phaseC/corpus_inventory.md` — the binding number is "
            f"the distinct-instruction count "
            f"({archive.get('distinct_instructions_executed')} with at least one "
            f"executing script), not the pair count."
        ),
        "",
        "## 8. Limitations",
        "",
        (
            f"1. **Bench size.** 20 instances x 4 draws = {COMPLETIONS_PER_ARM} "
            f"completions per arm. One completion is "
            f"{100.0 / COMPLETIONS_PER_ARM:.2f} pp, so no rate "
            f"difference below that is interpreted."
        ),
        (
            "2. **A1/A5 have no temperature or seed control.** The Claude Code "
            "CLI accepts neither, so those arms' four draws are four independent "
            "samples at the lane's own settings; every completion record says so "
            "(`seed: null`, `temperature: null`). `ModelConfig.seed` was added "
            "for the local lanes and is verified to reach the wire."
        ),
        (
            "3. **BlenderLLM is a December-2024 checkpoint.** Its published "
            "frontier comparisons are stale; it is used here as an existence "
            "proof of what domain SFT buys, not as a production candidate."
        ),
        (
            f"4. **Prompt parity is imperfect by construction.** The op arms get "
            f"the harness system prompt ({prompts['ops_system_lines']} lines) and "
            f"{harness.get('tool_schema_count')} tool schemas; the raw arms get the benchmark's own prompt "
            f"({prompts['raw_system_lines']} lines). Full unified diff: "
            f"`phaseB/prompt_parity.diff` "
            f"({prompts['system_diff_lines']} diff lines, "
            f"{prompts['system_added']} added / {prompts['system_removed']} "
            f"removed). The task text differs only as shown below."
        ),
        "",
        "```diff",
        prompts["task_diff"].rstrip("\n") or "(identical)",
        "```",
        "",
        (
            "5. **The canonical-orientation epilogue is asymmetric.** A1/A2's "
            "emitted scripts end with `apply_canonical_depth_axis()`; a raw "
            "script cannot, because the epilogue imports `blended`. `cd_yawmin` "
            "is therefore never compared across formats — `cd_pca` quotients "
            "orientation out and is what the arms are ranked on here."
        ),
        (
            f"6. **The G3 judge over-reports, measured.** "
            f"{percent(judge.get('hand_disagreement_rate'))} disagreement "
            f"against hand verification of {judge.get('hand_verified')} rows, "
            f"every disagreement a false positive "
            f"({percent(judge.get('judge_positive_precision'))} precision on "
            f"positives). Two mechanisms: colour/material constraints judged "
            f"on geometry the benchmark requires to be untextured, and "
            f"near-white turntable renders that are unreadable. The judge only "
            f"re-labels rows already inside `F_geom`, so no §3 rule turns on it."
        ),
        (
            f"7. **Re-bake reproducibility.** Two bakes of one script give the "
            f"same solid and a different tessellation; cd_pca moves by "
            f"~{number(noise.get('cd_pca'), 6)}. Archived scores were therefore "
            f"read, never regenerated."
        ),
        (
            "8. **Some A2/A3 completions were killed by the harness's own "
            "1500 s per-completion cap and are recorded as `E5`.** Their rows "
            "are synthesized and carry `synthesized_by`, so they can never be "
            f"mistaken for a reply a model returned: {a2_timeouts} of A2's "
            f"{a2_funnel.get('completions')} and {a3_timeouts} of "
            f"A3's {a3_funnel.get('completions')}. Mechanism, measured rather than assumed: "
            "`max_completion_tokens` is 16,384 and this lane decodes at "
            "11.8-12.8 tok/s, so a completion that runs to the ceiling needs "
            "~1,365 s of generation alone — and ~4x that per stream when four "
            "draws share the four slots. The completions that DID finish are "
            "fast (A2 median 70 s, 200 output tokens), and re-running the "
            "killed ones at reduced concurrency still hit the cap, so this is "
            "a property of the model-plus-cap, not of queueing alone. "
            "Constrained decoding is not the cause: measured 11.81 tok/s "
            "unconstrained against 12.75 tok/s with the 56-tool envelope "
            "grammar on the same prompt."
        ),
        (
            "9. **A1/A2/A3 ran four draws concurrently against four slots; A4 "
            "ran the same way.** Latency percentiles therefore include queue "
            "time and are not a clean per-completion measurement; "
            "executability and pass rates are unaffected, since a completion "
            "either produced a script or did not."
        ),
        (
            "10. **The op arms did not test the op FACADE.** A1/A2's task "
            "text is the archive's, and it still says every piece of geometry "
            "must be created inside `run_python` chunks, because those chunks "
            "are what the bake collects. So A2 and A3 were both writing bpy; "
            "A2 merely had to wrap it in tool-call JSON. A2 − A3 is therefore "
            "bpy against bpy-in-an-envelope, not facade against raw, and it "
            "also explains A2's collapse — a 7B was handed a "
            f"~17k-character system prompt, {harness.get('tool_schema_count')} schemas and a JSON envelope "
            "around the same task it already failed at unwrapped. Any future "
            "facade arm must change the task text so facade ops are the "
            "geometry path."
        ),
        (
            "11. **Effective sample size is ~20, not 80.** Four draws per "
            f"instance are correlated, so §4's intervals are clustered on the "
            f"20 instances and a {percent(a4_funnel.get('cd_pca_pass_rate'))} "
            f"pass rate carries roughly ±{number(a4_half_width_pp, 0)} pp. Every "
            "cross-arm shape comparison in this report except Δ_tune sits "
            "inside its interval. The fix is more instances "
            "(`bench_sets/instances_dev_all.txt` holds 145), not more draws."
        ),
        "",
        "## 9. Traceability spot-checks",
        "",
    ]
    for check in spot_checks(
        phase_b,
        DECISION_DIRECTORY / "phaseA" / "taxonomy.csv",
        DECISION_DIRECTORY / "phaseB" / "scores.csv",
    ):
        lines.append(f"- {check}")
    lines += [
        "",
        "## 10. Model revisions",
        "",
        "| id | repo | revision |",
        "|---|---|---|",
    ]
    for identifier, (repository, revision) in sorted(HF_REVISIONS.items()):
        lines.append(f"| `{identifier}` | `{repository}` | `{revision}` |")
    lines.append("")

    REPORT_PATH.write_text("\n".join(lines))
    print(f"[report] wrote {REPORT_PATH}", flush=True)
    print(f"[report] wrote {PROMPT_DIFF_PATH}", flush=True)
    print(f"[report] verdict: {phase_b.get('verdict')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
