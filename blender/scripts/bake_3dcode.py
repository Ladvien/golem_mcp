"""Bake a model dir the bench's own way, then refuse to let it be scored
half-baked (OT-21).

    .venv/bin/python scripts/bake_3dcode.py --bench-root /Users/ladvien/3dcodebench \
        --model-dir blended-deepseek-v4-pro-ops-roll1

Runs 3DCodeBench's `core/render.py` (four reference views plus
`renders/render_log.json`, which `metrics/executability.py` reads) and
`core/export_glb.py` (`glb/<inst>.glb`, which `metrics/shape_chamfer.py`
reads) under the bench's own venv and Blender, for every instance that
has a generated script. Then it asserts every such instance carries both
artifacts and exits 2 naming the ones that do not. A scorer run on a dir
that fails this check reports 0/N with a fingerprint that reads like a
model failure — measured 2026-09-10 on OT-9's roll 1 ("no render_log.json"
x 20) — so the chain guards the scorers with this exit code.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
DEFAULT_RESULTS_ROOT = "results/text_to_3D_agent"
MISSING_ARTIFACTS_EXIT = 2


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--results-root", default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--blender", default=DEFAULT_BLENDER)
    parser.add_argument(
        "--overwrite", action="store_true", help="re-render existing logs"
    )
    return parser.parse_args(argv)


def bench_python(bench_root: Path) -> Path:
    python = bench_root / ".venv" / "bin" / "python"
    if not python.exists():
        raise SystemExit(
            f"no bench venv at {python}: the bench's scorers need their own environment"
        )
    return python


def run_orchestrator(bench_root: Path, script: str, arguments) -> int:
    command = [
        str(bench_python(bench_root)),
        str(bench_root / "core" / script),
        "--model",
        arguments.model_dir,
        "--results-root",
        str(bench_root / arguments.results_root),
        "--blender",
        arguments.blender,
    ]
    if arguments.overwrite:
        command.append(
            "--overwrite"
        )  # both orchestrators skip an existing log otherwise
    print(f"[bake] {script}: {' '.join(command[2:])}", flush=True)
    return subprocess.run(command, cwd=bench_root, check=False).returncode


def instance_directories(model_root: Path) -> list[Path]:
    return sorted(
        directory
        for directory in model_root.iterdir()
        if directory.is_dir() and (directory / f"{directory.name}.py").exists()
    )


def missing_artifacts(model_root: Path) -> dict[str, list[str]]:
    """What the scorers need and the bake did not leave.

    Every instance needs its render log: that log IS the executability
    measurement, failure included. A GLB is owed only where the log says
    the script executed (`OK`); a script that failed to execute has no
    mesh to export, and that absence is the benchmark's number, not a
    bake defect.
    """
    missing: dict[str, list[str]] = {}
    for directory in instance_directories(model_root):
        absent: list[str] = []
        log_path = directory / "renders" / "render_log.json"
        if not log_path.exists():
            absent.append("renders/render_log.json")
        elif json.loads(log_path.read_text()).get("status") == "OK":
            glb_path = directory / "glb" / f"{directory.name}.glb"
            if not glb_path.exists():
                absent.append(
                    f"glb/{directory.name}.glb (script executed, nothing exported)"
                )
        if absent:
            missing[directory.name] = absent
    return missing


def status_summary(model_root: Path) -> Counter:
    statuses: Counter = Counter()
    for directory in instance_directories(model_root):
        log_path = directory / "renders" / "render_log.json"
        if log_path.exists():
            statuses[json.loads(log_path.read_text()).get("status", "?")] += 1
        else:
            statuses["NO_LOG"] += 1
    return statuses


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    model_root = bench_root / arguments.results_root / arguments.model_dir
    if not model_root.exists():
        raise SystemExit(f"no model dir {model_root}")
    scripts = instance_directories(model_root)
    if not scripts:
        raise SystemExit(f"{model_root} holds no <inst>/<inst>.py to bake")
    print(f"[bake] {len(scripts)} instance script(s) under {model_root}", flush=True)
    for script in ("render.py", "export_glb.py"):
        code = run_orchestrator(bench_root, script, arguments)
        if code != 0:
            print(
                f"[bake] {script} exited {code}; checking artifacts anyway", flush=True
            )
    missing = missing_artifacts(model_root)
    print(f"[bake] render statuses: {dict(status_summary(model_root))}", flush=True)
    if missing:
        for name, absent in missing.items():
            print(f"[bake] MISSING {name}: {', '.join(absent)}", flush=True)
        print(
            f"[bake] {len(missing)} of {len(scripts)} instance(s) lack a bake artifact; "
            f"do not score this dir",
            flush=True,
        )
        return MISSING_ARTIFACTS_EXIT
    print(f"[bake] all {len(scripts)} instance(s) baked; safe to score", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
