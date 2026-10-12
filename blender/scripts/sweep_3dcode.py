"""Drive `run_3dcode_instance.py` over a frozen 3DCodeBench instance list.

    make bench-3dcode
    make bench-3dcode INSTANCES=/Users/ladvien/3dcodebench/instances_v1.txt

Host-side, one Blender subprocess per instance, SERIAL. Serial is not a
simplification: each run drives a cloud writer and a live `bpy` session,
so parallelism would multiply quota pressure and contend for the same
GPU-backed renderer with nothing gained but a shorter wall clock on a
run that is already dominated by model latency.

Resumable by construction — the per-instance runner skips an instance
that already has a `<inst>.py` unless `--overwrite` is passed — so a
mid-sweep quota stall is recovered by re-running the same command.
"""

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
RUNNER = REPOSITORY_ROOT / "scripts" / "run_3dcode_instance.py"
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
from blended.agent.loop import (
    exhausted_credits_error,  # ONE definition of "out of credits"
)

# The sweep's own exit code for a lane that cannot answer until the user
# acts: every later instance would fail identically, so the roll stops
# here and the chain log says why. Measured 2026-09-11: six instances,
# ~5 min of backoff each, on a lane out of cloud credits.
LANE_EXHAUSTED_EXIT = 3
SWEEP_TIMEOUT_SECONDS = 1500  # 1.28x the measured worst instance
# (Oven_seed0, 1167 s) — see --timeout


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--model-dir", default="blended-deepseek-v4-pro")
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument(
        "--reference-images-root",
        default="",
        help="passed through to the runner: the image-to-3D track",
    )
    parser.add_argument(
        "--prompt-variant",
        choices=("description", "instruction"),
        default="description",
    )
    parser.add_argument("--max-tool-calls", type=int, default=24)
    parser.add_argument(
        "--timeout",
        type=int,
        default=SWEEP_TIMEOUT_SECONDS,
        help=f"Per-instance seconds (default "
        f"{SWEEP_TIMEOUT_SECONDS}). Measured iter3 "
        f"holdout durations: mean 408 s, worst "
        f"Oven_seed0 1167 s, TableCoral_seed0 919 s, "
        f"CeilingClassicLamp_seed0 893 s; FoodBox_seed0 "
        f"hit a 1200 s cap and then finished in 703 s "
        f"on a direct re-run, so a tighter cap injects "
        f"retries instead of catching hangs.",
    )
    parser.add_argument("--blender", default=DEFAULT_BLENDER)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def instance_command(arguments, instance: str) -> list[str]:
    command = [
        arguments.blender,
        "--background",
        "--factory-startup",
        "--python",
        str(RUNNER),
        "--",
        "--instance",
        instance,
        "--bench-root",
        arguments.bench_root,
        "--results-root",
        arguments.results_root,
        "--model-dir",
        arguments.model_dir,
        "--prompt-variant",
        arguments.prompt_variant,
        "--max-tool-calls",
        str(arguments.max_tool_calls),
    ]
    if arguments.model:
        command += ["--model", arguments.model]
    if arguments.vision_model:
        command += ["--vision-model", arguments.vision_model]
    if arguments.reference_images_root:
        command += ["--reference-images-root", arguments.reference_images_root]
    if arguments.overwrite:
        command += ["--overwrite"]
    return command


def work_directory(arguments, instance: str) -> Path:
    return (
        Path(arguments.bench_root)
        / arguments.results_root
        / arguments.model_dir
        / instance
    )


def read_error(directory: Path) -> str:
    metadata_path = directory / ".agent_meta.json"
    if not metadata_path.exists():
        return ""
    try:
        return str(json.loads(metadata_path.read_text()).get("error", "") or "")
    except json.JSONDecodeError:
        return ""


def read_status(directory: Path) -> str:
    metadata_path = directory / ".agent_meta.json"
    if not metadata_path.exists():
        return "NO_META"
    try:
        return json.loads(metadata_path.read_text()).get("status", "?")
    except json.JSONDecodeError:
        return "BAD_META"


def main(argv) -> int:
    arguments = parse_arguments(argv)
    instances = [
        line.strip()
        for line in Path(arguments.instances_file).read_text().splitlines()
        if line.strip()
    ]
    if not instances:
        raise SystemExit(f"No instances in {arguments.instances_file}")

    print(
        f"Sweep: {len(instances)} instances -> "
        f"{arguments.results_root}/{arguments.model_dir} "
        f"(timeout={arguments.timeout}s, serial)\n",
        flush=True,
    )

    statuses: Counter[str] = Counter()
    for position, instance in enumerate(instances, start=1):
        directory = work_directory(arguments, instance)
        started = time.monotonic()
        print(f"=== [{position}/{len(instances)}] {instance}", flush=True)
        try:
            completed = subprocess.run(
                instance_command(arguments, instance),
                timeout=arguments.timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - started
            directory.mkdir(parents=True, exist_ok=True)
            (directory / ".agent_meta.json").write_text(
                json.dumps(
                    {
                        "instance": instance,
                        "task": "text_to_3d",
                        "model": arguments.model,
                        "status": "ERR_TIMEOUT",
                        "duration_s": round(duration, 2),
                        "error": f"exceeded {arguments.timeout}s",
                    },
                    indent=2,
                )
            )
            statuses["ERR_TIMEOUT"] += 1
            print(f"[STATUS] {instance} ERR_TIMEOUT {duration:.1f}s", flush=True)
            continue

        duration = time.monotonic() - started
        if directory.exists():
            (directory / ".blender_stdout.txt").write_text(
                completed.stdout + "\n--- stderr ---\n" + completed.stderr
            )
        status = read_status(directory)
        if completed.returncode != 0 and status in ("NO_META", "?"):
            status = f"ERR_EXIT_{completed.returncode}"
        statuses[status] += 1
        print(f"[STATUS] {instance} {status} {duration:.1f}s", flush=True)
        if status.startswith("ERR_") and exhausted_credits_error(read_error(directory)):
            print(
                f"\n[SWEEP STOPPED] {instance}: the lane is out of credits — "
                f"{read_error(directory)[:160]}; {len(instances) - position} instance(s) "
                f"not attempted (re-run the sweep once credits are restored)",
                flush=True,
            )
            _print_histogram(statuses)
            return LANE_EXHAUSTED_EXIT

    _print_histogram(statuses)
    return 0


def _print_histogram(statuses: Counter) -> None:
    print("\n=== sweep status histogram ===")
    for status, count in statuses.most_common():
        print(f"  {status:<16} {count:>4}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
