#!/usr/bin/env python3
"""Bake and score one arm's four model dirs, the way the archive was scored.

    .venv/bin/python scripts/score_finetune_arm.py --arm a5 \\
        --bench-root /Users/ladvien/3dcodebench

Runs, per draw, exactly the chain the bench's own rolls use:

  1. `scripts/bake_3dcode.py`           -> renders/render_log.json + glb/
  2. `metrics/executability.py`         -> the bench's own executability
  3. `metrics/shape_chamfer.py`         -> the bench's own chamfer
  4. `scripts/diagnose_3dcode.py --json`-> per-instance cd_pca + F@0.05
  5. `scripts/shape_error_decompose.py --json` -> cd_pca_aspect_oracle,
                                            the G1/G2 separator

Step 1 exits 2 when an instance lacks a render log or an owed GLB, and
this driver then refuses to score that dir — a scorer run on a
half-baked dir reports 0/N with a fingerprint that reads like a model
failure (`bake_3dcode.py`'s own docstring records the roll where that
happened). Step 5 is skipped for a dir where nothing executed, because
the decomposition treats a missing cloud as fatal on purpose.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
from finetune_decision_thresholds import ARMS, DRAWS_SAMPLED, model_directory

WORKING_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
DEV_PYTHON = REPOSITORY_ROOT / ".venv" / "bin" / "python"
BAKE_MISSING_ARTIFACTS_EXIT = 2


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--arm", required=True, choices=sorted(ARMS))
    parser.add_argument(
        "--draws", default=",".join(str(draw) for draw in range(DRAWS_SAMPLED + 1))
    )
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    return parser.parse_args(argv)


def run(command: list[str], cwd: Path | None = None) -> int:
    print(f"[score] {' '.join(str(part) for part in command)}", flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def executed_instances(model_root: Path) -> list[str]:
    """Instances whose script ran AND left a GLB — what step 5 can read."""
    found = []
    for directory in sorted(model_root.iterdir()):
        if not directory.is_dir():
            continue
        glb = directory / "glb" / f"{directory.name}.glb"
        if glb.exists() and glb.stat().st_size > 0:
            found.append(directory.name)
    return found


def instances_present(model_root: Path) -> list[str]:
    return sorted(
        directory.name
        for directory in model_root.iterdir()
        if directory.is_dir() and (directory / f"{directory.name}.py").exists()
    )


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    results_root = bench_root / arguments.results_root
    bench_python = bench_root / ".venv" / "bin" / "python"
    WORKING_DIRECTORY.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    for draw in [int(part) for part in arguments.draws.split(",") if part.strip()]:
        model_dir = model_directory(arguments.arm, draw)
        model_root = results_root / model_dir
        if not model_root.is_dir():
            print(f"[score] {model_dir}: no dir, nothing generated", flush=True)
            continue
        present = instances_present(model_root)
        if not present:
            print(f"[score] {model_dir}: no scripts to bake", flush=True)
            continue
        print(f"[score] {model_dir}: {len(present)} script(s)", flush=True)

        code = run(
            [
                str(DEV_PYTHON),
                str(REPOSITORY_ROOT / "scripts" / "bake_3dcode.py"),
                "--bench-root",
                str(bench_root),
                "--model-dir",
                model_dir,
                "--results-root",
                arguments.results_root,
            ]
        )
        if code == BAKE_MISSING_ARTIFACTS_EXIT:
            failures.append(f"{model_dir}: bake left an instance without artifacts")
            continue
        if code != 0:
            failures.append(f"{model_dir}: bake exited {code}")
            continue

        for scorer in ("executability.py", "shape_chamfer.py"):
            code = run(
                [
                    str(bench_python),
                    str(bench_root / "metrics" / scorer),
                    "--model",
                    model_dir,
                    "--results-root",
                    str(results_root),
                ],
                cwd=bench_root,
            )
            if code != 0:
                failures.append(f"{model_dir}: {scorer} exited {code}")

        # The instance list is the dir's OWN scripts: a completion that
        # produced no script is a recorded parse failure, not a scoring
        # gap, and asking the diagnostic about it would be asking about
        # a file that does not exist.
        instances_file = WORKING_DIRECTORY / f"instances_{model_dir}.txt"
        instances_file.write_text("\n".join(present) + "\n")
        code = run(
            [
                str(bench_python),
                str(REPOSITORY_ROOT / "scripts" / "diagnose_3dcode.py"),
                "--bench-root",
                str(bench_root),
                "--results-root",
                arguments.results_root,
                "--model-dir",
                model_dir,
                "--instances-file",
                str(instances_file),
                "--out",
                str(WORKING_DIRECTORY / f"diagnose_{model_dir}.md"),
                "--json",
                str(WORKING_DIRECTORY / f"diagnose_{model_dir}.json"),
            ],
            cwd=REPOSITORY_ROOT,
        )
        if code != 0:
            failures.append(f"{model_dir}: diagnose exited {code}")

        executed = [
            instance
            for instance in executed_instances(model_root)
            if (bench_root / "data" / instance / "glb" / f"{instance}.glb").exists()
        ]
        if not executed:
            print(
                f"[score] {model_dir}: nothing executed, no decomposition", flush=True
            )
            continue
        decomposable = WORKING_DIRECTORY / f"decomposable_{model_dir}.txt"
        decomposable.write_text("\n".join(executed) + "\n")
        code = run(
            [
                str(bench_python),
                str(REPOSITORY_ROOT / "scripts" / "shape_error_decompose.py"),
                "--bench-root",
                str(bench_root),
                "--results-root",
                arguments.results_root,
                "--model-dir",
                model_dir,
                "--instances-file",
                str(decomposable),
                "--out",
                str(WORKING_DIRECTORY / f"decompose_{model_dir}.md"),
                "--json",
                str(WORKING_DIRECTORY / f"decompose_{model_dir}.json"),
            ],
            cwd=REPOSITORY_ROOT,
        )
        if code != 0:
            failures.append(f"{model_dir}: decompose exited {code}")

    summary = {"arm": arguments.arm, "failures": failures}
    (WORKING_DIRECTORY / f"score_{arguments.arm}.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    if failures:
        for failure in failures:
            print(f"[score] FAILED {failure}", flush=True)
        return 1
    print(f"[score] arm {arguments.arm}: every dir baked and scored", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
