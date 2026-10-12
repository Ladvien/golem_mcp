"""Drive `run_finetune_arm.py` over one arm's draws and the frozen instance list.

    .venv/bin/python scripts/sweep_finetune_arms.py --arm a2 --draws 0,1,2,3 \\
        --instances-file bench_sets/instances_holdout.txt \\
        --bench-root /Users/ladvien/3dcodebench

Serial and resumable, like `scripts/sweep_3dcode.py`: an instance that
already has a script is skipped unless `--overwrite`, and a single
completion is capped at `--timeout` seconds. One fresh Blender per
instance for the op-format arms (`--factory-startup`, empty scene — the
archived rolls' pattern); the raw arms need no bpy and run under the dev
venv.

Stops the whole sweep with LANE_EXHAUSTED_EXIT when the lane says it is
out of credits or its subscription window is closed: every later
completion would fail identically, and a partial arm with a recorded
reason is worth more than 80 rows of the same error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
RUNNER = REPOSITORY_ROOT / "scripts" / "run_finetune_arm.py"
DEV_PYTHON = REPOSITORY_ROOT / ".venv" / "bin" / "python"
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
# Both after the path bootstrap above: the pre-registered arm table, and
# ONE definition of "out of credits".
from finetune_decision_thresholds import (
    ARMS,
    DRAWS_SAMPLED,
    draw_sampling,
    model_directory,
)

from blended.agent.loop import exhausted_credits_error

# Same exit code and meaning as the production sweep's.
LANE_EXHAUSTED_EXIT = 3
# A single-shot completion is one model call plus, for the op arms, the
# dispatches it asked for. The production sweep allows 1500 s for a whole
# agentic run; the same ceiling here is generous on purpose, so a slow
# cold model load on a 7B F16 is not recorded as a hang.
COMPLETION_TIMEOUT_SECONDS = 1500
# `blender --python` exits 0 when the script RAISES unless told otherwise
# (measured 2026-10-07: `raise RuntimeError` -> exit 0 plain, 7 with the
# flag), which made a crashed op-arm completion look like a clean run.
BLENDER_SCRIPT_FAILURE_EXIT = 1
# The runner exited without writing the record it owes the arm.
OUTCOME_NO_RECORD = "ERR_NO_RECORD"
COMPLETIONS_ROOT = (
    REPOSITORY_ROOT / "docs" / "research" / "2026-09-19-finetune-decision" / "phaseB"
)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument(
        "--draws",
        default=",".join(str(draw) for draw in range(DRAWS_SAMPLED + 1)),
        help="comma-separated draw indices; 0 is the greedy draw",
    )
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--blender", default=DEFAULT_BLENDER)
    parser.add_argument("--timeout", type=int, default=COMPLETION_TIMEOUT_SECONDS)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--per-draw-files",
        action="store_true",
        help="write each draw to its own completions.k<draw>.jsonl. Set this "
        "when several draws of one arm run CONCURRENTLY: one appender per "
        "file, so a 4 KB record cannot interleave with another's.",
    )
    return parser.parse_args(argv)


def completions_path(arm: str, draw: int, per_draw: bool) -> Path:
    name = f"completions.k{draw}.jsonl" if per_draw else "completions.jsonl"
    return COMPLETIONS_ROOT / arm / name


def completion_command(arguments, draw: int, instance: str) -> list[str]:
    arm_format = ARMS[arguments.arm]["format"]
    runner_arguments = [
        "--arm",
        arguments.arm,
        "--format",
        arm_format,
        "--model",
        ARMS[arguments.arm]["model"],
        "--draw",
        str(draw),
        "--instance",
        instance,
        "--bench-root",
        arguments.bench_root,
        "--results-root",
        arguments.results_root,
        "--completions-out",
        str(completions_path(arguments.arm, draw, arguments.per_draw_files)),
    ]
    if arguments.overwrite:
        runner_arguments.append("--overwrite")
    if arm_format == "ops":
        return [
            arguments.blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            str(BLENDER_SCRIPT_FAILURE_EXIT),
            "--python",
            str(RUNNER),
            "--",
            *runner_arguments,
        ]
    return [str(DEV_PYTHON), str(RUNNER), *runner_arguments]


def matching_completions(
    arm: str, draw: int, instance: str, per_draw: bool
) -> list[dict]:
    """Every recorded completion for this (arm, draw, instance), oldest first."""
    path = completions_path(arm, draw, per_draw)
    if not path.exists():
        return []
    found: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if (
            record.get("draw") == draw
            and record.get("instance") == instance
            and record.get("arm") == arm
        ):
            found.append(record)
    return found


def completion_outcome(fresh: list[dict], returncode: int) -> tuple[dict, str]:
    """(the record THIS subprocess wrote, its outcome word).

    `fresh` is only what the subprocess appended. An older record for the
    same (draw, instance) is not evidence about this run: reading it
    would report a crashed re-run as whatever the previous run said.
    """
    if fresh:
        record = fresh[-1]
        return record, record.get("parse_result") or f"ERR_EXIT_{returncode}"
    return {}, f"ERR_EXIT_{returncode}" if returncode != 0 else OUTCOME_NO_RECORD


def write_timeout_completion(
    arguments, draw: int, instance: str, duration: float
) -> None:
    """The completion record a killed subprocess could not write itself.

    Carries the same keys the runner writes, so Phase B reads one shape,
    plus `synthesized_by` so a row that no model actually returned can
    never be mistaken for one that did.
    """
    temperature, seed = draw_sampling(draw)
    record = {
        "arm": arguments.arm,
        "format": ARMS[arguments.arm]["format"],
        "model": ARMS[arguments.arm]["model"],
        "draw": draw,
        "seed": seed,
        "temperature": temperature,
        "instance": instance,
        "system_prompt_sha256": "",
        "user_prompt_sha256": "",
        "raw_output": f"killed by the sweep after {duration:.1f}s",
        "wall_time_s": round(duration, 2),
        "finish_reason": "sweep_timeout",
        "parse_result": "ERR_TIMEOUT",
        "n_tool_calls": 0,
        "n_tool_calls_dispatched": 0,
        "n_ops": 0,
        "n_hatch": 0,
        "hatch_reasons": [],
        "script_chars": 0,
        "script_written": False,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "assembled_prompt_fingerprint": "",
        "tool_schemas_fingerprint": "",
        "synthesized_by": "sweep_finetune_arms.write_timeout_completion",
    }
    path = completions_path(arguments.arm, draw, arguments.per_draw_files)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def main(argv) -> int:
    arguments = parse_arguments(argv)
    draws = [int(part) for part in arguments.draws.split(",") if part.strip()]
    instances = [
        line.strip()
        for line in Path(arguments.instances_file).read_text().splitlines()
        if line.strip()
    ]
    if not instances:
        raise SystemExit(f"No instances in {arguments.instances_file}")
    print(
        f"Arm {arguments.arm} ({ARMS[arguments.arm]['model']}, "
        f"{ARMS[arguments.arm]['format']}): {len(draws)} draw(s) x "
        f"{len(instances)} instance(s), serial\n",
        flush=True,
    )

    results: Counter[str] = Counter()
    total = len(draws) * len(instances)
    position = 0
    bench_root = Path(arguments.bench_root).resolve()
    for draw in draws:
        model_dir = model_directory(arguments.arm, draw)
        for instance in instances:
            position += 1
            started = time.monotonic()
            print(f"=== [{position}/{total}] {model_dir}/{instance}", flush=True)
            script = (
                bench_root
                / arguments.results_root
                / model_dir
                / instance
                / f"{instance}.py"
            )
            if script.exists() and not arguments.overwrite:
                # The runner's own skip condition, decided here so a skip
                # is never confused with a crash that wrote no record.
                results["SKIPPED"] += 1
                print(f"[RESULT] {instance} SKIPPED", flush=True)
                continue
            recorded_before = len(
                matching_completions(
                    arguments.arm, draw, instance, arguments.per_draw_files
                )
            )
            try:
                completed = subprocess.run(
                    completion_command(arguments, draw, instance),
                    timeout=arguments.timeout,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                duration = time.monotonic() - started
                results["ERR_TIMEOUT"] += 1
                # A killed completion leaves NO record of its own, and a
                # silently missing row shrinks the arm's denominator —
                # which is the spec's `E5` (timeout/hang) counted as if
                # it never happened. Write the row here instead, marked
                # as synthesized by the sweep.
                write_timeout_completion(arguments, draw, instance, duration)
                print(
                    f"[RESULT] {instance} ERR_TIMEOUT {duration:.1f}s",
                    flush=True,
                )
                continue
            duration = time.monotonic() - started
            record, outcome = completion_outcome(
                matching_completions(
                    arguments.arm, draw, instance, arguments.per_draw_files
                )[recorded_before:],
                completed.returncode,
            )
            results[outcome] += 1
            print(f"[RESULT] {instance} {outcome} {duration:.1f}s", flush=True)
            if outcome in (
                "ERR_CONNECTION",
                "ERR_MODEL_CALL",
            ) and exhausted_credits_error(str(record.get("raw_output", ""))):
                print(
                    f"\n[SWEEP STOPPED] {instance}: the lane is exhausted — "
                    f"{str(record.get('raw_output'))[:200]}; "
                    f"{total - position} completion(s) not attempted",
                    flush=True,
                )
                _print_histogram(results)
                return LANE_EXHAUSTED_EXIT
            if outcome.startswith("ERR_EXIT_") or outcome == OUTCOME_NO_RECORD:
                print(completed.stdout[-2000:], flush=True)
                print(completed.stderr[-2000:], flush=True)
    _print_histogram(results)
    return 0


def _print_histogram(results: Counter) -> None:
    print("\n=== arm parse-result histogram ===")
    for outcome, count in results.most_common():
        print(f"  {outcome:<20} {count:>4}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
