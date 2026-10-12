"""Prove the scorer reads the SCRIPT, not the path that produced it.

    .venv/bin/python scripts/finetune_parity_gate.py \\
        --bench-root /Users/ladvien/3dcodebench

Spec §5.2 / §9 of the fine-tune decision experiment asks for a validated
raw-bpy execution adapter before any arm burns inference: without it the
raw arms (A3-A5) are not comparable to the op arms (A1-A2) and the whole
experiment is void. There is no adapter to build — `scripts/bake_3dcode.py`
bakes any `<model-dir>/<inst>/<inst>.py` through the bench's own
`core/render.py` + `core/export_glb.py`, whichever path wrote that file —
so what remains to prove is a round trip. This gate makes TWO
measurements, because the first attempt at one collapsed them and failed
for a reason that had nothing to do with the layout:

  STAGE 1, exact. The same baked artifacts (`<inst>.py`,
  `renders/render_log.json`, `glb/<inst>.glb`) are copied into two
  differently-named model dirs and scored by the bench's own scorers.
  Every metric must agree to `PARITY_TOLERANCE` (1e-9, the tolerance
  `scripts/shape_error_decompose.py` already uses for scorer parity).
  This is the spec's claim — "reaches the identical scoring function" —
  and it is exactly testable.

  STAGE 2, measured. The same SCRIPTS are baked twice, fresh, into two
  more dirs. Measured 2026-09-19 on three archived instances: the bake
  is geometrically reproducible and combinatorially not — the solid is
  identical (volume equal to ~1e-17 relative) while the triangle order,
  and for a script that applies boolean modifiers the whole internal
  tessellation, differs run to run. The bench samples 8,192 points from
  that triangulation with a fixed seed, so cd_pca moves ~3.5e-4 between
  two bakes of one script. The gate therefore asserts the SOLID
  (`SOLID_VOLUME_RELATIVE_TOLERANCE`) and REPORTS the cd_pca spread as
  the pipeline's own noise floor, which is the number every later delta
  has to clear.

Exits non-zero if stage 1 disagrees anywhere, or if a re-bake changes the
solid: either would mean the arms are not scored by the same instrument.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
from finetune_decision_thresholds import (
    INSTANCES_FILE,
    SOLID_VOLUME_RELATIVE_TOLERANCE,
)

# Two dirs per stage, differing only in name: that difference is what
# stage 1 proves the scorer cannot see.
SCORER_PARITY_DIRS = ("ft-parity-score-a", "ft-parity-score-b")
BAKE_PARITY_DIRS = ("ft-parity-bake-a", "ft-parity-bake-b")
# An archived roll of the frozen holdout with per-instance scores already
# recorded by `scripts/diagnose_3dcode.py --json`.
SOURCE_MODEL_DIR = "blended-deepseek-v4-pro-disclosed2-roll3"
SOURCE_DIAGNOSE_JSON = (
    REPOSITORY_ROOT / "outputs" / "bench" / f"diagnose_{SOURCE_MODEL_DIR}.json"
)
PARITY_INSTANCE_COUNT = 3
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "outputs" / "finetune_decision"
OUTPUT_JSON = OUTPUT_DIRECTORY / "parity_gate.json"
DEFAULT_RESULTS_ROOT = "results/text_to_3D_agent"
COMPARED_METRICS = ("cd_pca", "cd_yawmin", "delta_orient", "fscore_005")
MISMATCH_EXIT = 4
# Floor under the volume scale of a relative difference, so two empty
# solids divide by this instead of by zero.
VOLUME_SCALE_FLOOR_M3 = 1e-12


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--instances", type=int, default=PARITY_INSTANCE_COUNT)
    return parser.parse_args(argv)


def parity_tolerance() -> float:
    """`shape_error_decompose.PARITY_TOLERANCE`, read from that module's text.

    Not imported: that module needs numpy and the bench's own venv, and
    this gate runs under the dev venv. Read, never re-typed, so the two
    cannot drift.
    """
    source = (REPOSITORY_ROOT / "scripts" / "shape_error_decompose.py").read_text()
    for line in source.splitlines():
        if line.startswith("PARITY_TOLERANCE"):
            return float(line.split("=", 1)[1].split("#", 1)[0].strip())
    raise SystemExit("scripts/shape_error_decompose.py holds no PARITY_TOLERANCE")


def archived_rows() -> dict[str, dict]:
    if not SOURCE_DIAGNOSE_JSON.exists():
        raise SystemExit(f"no archived scores at {SOURCE_DIAGNOSE_JSON}")
    data = json.loads(SOURCE_DIAGNOSE_JSON.read_text())
    return {row["instance"]: row for row in data["per_instance"]}


def run(command: list[str], cwd: Path | None = None) -> int:
    print(f"[parity] {' '.join(str(part) for part in command)}", flush=True)
    return subprocess.run(command, cwd=cwd, check=False).returncode


def chosen_instances(
    source_root: Path, rows: dict[str, dict], wanted: int
) -> list[str]:
    instances = [
        line.strip()
        for line in (REPOSITORY_ROOT / INSTANCES_FILE).read_text().splitlines()
        if line.strip()
    ]
    scored = [
        instance
        for instance in instances
        if instance in rows
        and rows[instance].get("cd_pca") is not None
        and (source_root / instance / f"{instance}.py").exists()
        and (source_root / instance / "glb" / f"{instance}.glb").exists()
    ][:wanted]
    if len(scored) < wanted:
        raise SystemExit(
            f"only {len(scored)} archived instance(s) carry a script, a GLB and a cd_pca"
        )
    return scored


def stage_artifacts(
    source_root: Path, target_root: Path, instances: list[str], with_bake_output: bool
) -> None:
    """Copy the archived inputs into a fresh model dir.

    `with_bake_output` also copies the render log and the GLB — i.e. the
    dir arrives already baked, which is what makes stage 1 a pure scorer
    comparison with nothing re-executed.
    """
    if target_root.exists():
        shutil.rmtree(target_root)
    for instance in instances:
        destination = target_root / instance
        destination.mkdir(parents=True)
        shutil.copyfile(
            source_root / instance / f"{instance}.py", destination / f"{instance}.py"
        )
        if not with_bake_output:
            continue
        (destination / "renders").mkdir()
        shutil.copyfile(
            source_root / instance / "renders" / "render_log.json",
            destination / "renders" / "render_log.json",
        )
        (destination / "glb").mkdir()
        shutil.copyfile(
            source_root / instance / "glb" / f"{instance}.glb",
            destination / "glb" / f"{instance}.glb",
        )


def score(
    bench_root: Path, results_root: str, model_dir: str, instances_file: Path
) -> dict:
    """Run the bench's own scorers plus diagnose, and return the rows."""
    bench_python = bench_root / ".venv" / "bin" / "python"
    absolute_results = bench_root / results_root
    for scorer in ("executability.py", "shape_chamfer.py"):
        code = run(
            [
                str(bench_python),
                str(bench_root / "metrics" / scorer),
                "--model",
                model_dir,
                "--results-root",
                str(absolute_results),
            ],
            cwd=bench_root,
        )
        if code != 0:
            raise SystemExit(f"{scorer} exited {code} on {model_dir}")
    diagnose_json = OUTPUT_DIRECTORY / f"diagnose_{model_dir}.json"
    code = run(
        [
            str(bench_python),
            str(REPOSITORY_ROOT / "scripts" / "diagnose_3dcode.py"),
            "--bench-root",
            str(bench_root),
            "--results-root",
            results_root,
            "--model-dir",
            model_dir,
            "--instances-file",
            str(instances_file),
            "--out",
            str(OUTPUT_DIRECTORY / f"diagnose_{model_dir}.md"),
            "--json",
            str(diagnose_json),
        ],
        cwd=REPOSITORY_ROOT,
    )
    if code != 0:
        raise SystemExit(f"diagnose_3dcode exited {code} on {model_dir}")
    return {
        row["instance"]: row
        for row in json.loads(diagnose_json.read_text())["per_instance"]
    }


def solid_volumes(
    bench_root: Path, results_root: str, model_dir: str, instances: list[str]
) -> dict:
    """Mesh volume per instance, read with the scorer's own trimesh."""
    probe = (
        "import json, sys, trimesh\n"
        "root, model, names = sys.argv[1], sys.argv[2], sys.argv[3:]\n"
        "out = {}\n"
        "for name in names:\n"
        "    mesh = trimesh.load(f'{root}/{model}/{name}/glb/{name}.glb', force='mesh')\n"
        "    out[name] = {'volume': float(mesh.volume), 'vertices': int(len(mesh.vertices)),\n"
        "                 'faces': int(len(mesh.faces))}\n"
        "print(json.dumps(out))\n"
    )
    completed = subprocess.run(
        [
            str(bench_root / ".venv" / "bin" / "python"),
            "-c",
            probe,
            str(bench_root / results_root),
            model_dir,
            *instances,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"volume probe failed on {model_dir}: {completed.stderr[-800:]}"
        )
    return json.loads(completed.stdout)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    results_root = bench_root / arguments.results_root
    source_root = results_root / SOURCE_MODEL_DIR
    rows = archived_rows()
    instances = chosen_instances(source_root, rows, arguments.instances)
    tolerance = parity_tolerance()

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    instances_file = OUTPUT_DIRECTORY / "parity_instances.txt"
    instances_file.write_text("\n".join(instances) + "\n")

    # --- Stage 1: the same artifacts, two model-dir names -----------------
    scored: dict[str, dict] = {}
    for model_dir in SCORER_PARITY_DIRS:
        stage_artifacts(source_root, results_root / model_dir, instances, True)
        scored[model_dir] = score(
            bench_root, arguments.results_root, model_dir, instances_file
        )
    stage_one = []
    stage_one_failed = []
    left, right = SCORER_PARITY_DIRS
    for instance in instances:
        row = {"instance": instance}
        for metric in COMPARED_METRICS:
            a = scored[left][instance][metric]
            b = scored[right][instance][metric]
            row[metric] = {
                left: a,
                right: b,
                "abs_difference": abs(a - b),
                "within_tolerance": abs(a - b) <= tolerance,
            }
            # `not <=`, never `>`: a NaN metric is within nobody's tolerance
            # and must fail the gate rather than compare False both ways.
            if not row[metric]["within_tolerance"]:
                stage_one_failed.append(f"{instance}.{metric}")
        # The archived score for the same artifacts, as a third witness.
        row["cd_pca_archived"] = rows[instance]["cd_pca"]
        row["cd_pca_archived_matches"] = (
            abs(rows[instance]["cd_pca"] - scored[left][instance]["cd_pca"])
            <= tolerance
        )
        if not row["cd_pca_archived_matches"]:
            stage_one_failed.append(f"{instance}.cd_pca_vs_archive")
        stage_one.append(row)

    # --- Stage 2: the same scripts, two fresh bakes ------------------------
    baked: dict[str, dict] = {}
    volumes: dict[str, dict] = {}
    for model_dir in BAKE_PARITY_DIRS:
        stage_artifacts(source_root, results_root / model_dir, instances, False)
        bake = run(
            [
                str(REPOSITORY_ROOT / ".venv" / "bin" / "python"),
                str(REPOSITORY_ROOT / "scripts" / "bake_3dcode.py"),
                "--bench-root",
                str(bench_root),
                "--model-dir",
                model_dir,
                "--results-root",
                arguments.results_root,
            ]
        )
        if bake != 0:
            raise SystemExit(f"bake exited {bake}: do not score {model_dir}")
        baked[model_dir] = score(
            bench_root, arguments.results_root, model_dir, instances_file
        )
        volumes[model_dir] = solid_volumes(
            bench_root, arguments.results_root, model_dir, instances
        )
    stage_two = []
    stage_two_failed = []
    left, right = BAKE_PARITY_DIRS
    for instance in instances:
        volume_a = volumes[left][instance]["volume"]
        volume_b = volumes[right][instance]["volume"]
        scale = max(abs(volume_a), abs(volume_b), VOLUME_SCALE_FLOOR_M3)
        relative = abs(volume_a - volume_b) / scale
        row = {
            "instance": instance,
            "volume": {
                left: volume_a,
                right: volume_b,
                "relative_difference": relative,
            },
            "vertices": [
                volumes[left][instance]["vertices"],
                volumes[right][instance]["vertices"],
            ],
            "faces": [
                volumes[left][instance]["faces"],
                volumes[right][instance]["faces"],
            ],
            "solid_reproduced": relative <= SOLID_VOLUME_RELATIVE_TOLERANCE,
        }
        for metric in COMPARED_METRICS:
            a = baked[left][instance][metric]
            b = baked[right][instance][metric]
            row[metric] = {left: a, right: b, "abs_difference": abs(a - b)}
        if not row["solid_reproduced"]:
            stage_two_failed.append(instance)
        stage_two.append(row)

    noise_floor = {
        metric: max(row[metric]["abs_difference"] for row in stage_two)
        for metric in COMPARED_METRICS
    }
    result = {
        "source_model_dir": SOURCE_MODEL_DIR,
        "instances": instances,
        "parity_tolerance": tolerance,
        "solid_volume_relative_tolerance": SOLID_VOLUME_RELATIVE_TOLERANCE,
        "stage_1_scorer_parity": {
            "model_dirs": list(SCORER_PARITY_DIRS),
            "rows": stage_one,
            "passed": not stage_one_failed,
            "failed": stage_one_failed,
        },
        "stage_2_bake_reproducibility": {
            "model_dirs": list(BAKE_PARITY_DIRS),
            "rows": stage_two,
            "solid_reproduced_everywhere": not stage_two_failed,
            "failed": stage_two_failed,
            "measured_noise_floor": noise_floor,
        },
        "passed": not stage_one_failed and not stage_two_failed,
    }
    OUTPUT_JSON.write_text(json.dumps(result, indent=2) + "\n")

    print("\n[parity] stage 1 — same artifacts, two model-dir names", flush=True)
    for row in stage_one:
        marks = " ".join(
            f"{metric}:{'OK' if row[metric]['within_tolerance'] else 'MISMATCH'}"
            for metric in COMPARED_METRICS
        )
        print(
            f"[parity]   {row['instance']:<26} {marks} "
            f"archive:{'OK' if row['cd_pca_archived_matches'] else 'MISMATCH'}",
            flush=True,
        )
    print("\n[parity] stage 2 — same scripts, two fresh bakes", flush=True)
    for row in stage_two:
        print(
            f"[parity]   {row['instance']:<26} volume Δrel "
            f"{row['volume']['relative_difference']:.2e} "
            f"{'SAME SOLID' if row['solid_reproduced'] else 'DIFFERENT SOLID'}; "
            f"verts {row['vertices']}, faces {row['faces']}; "
            f"cd_pca Δ {row['cd_pca']['abs_difference']:.2e}",
            flush=True,
        )
    print(
        "\n[parity] measured noise floor (max |Δ| over a re-bake): "
        + ", ".join(f"{metric} {value:.2e}" for metric, value in noise_floor.items()),
        flush=True,
    )
    print(f"[parity] wrote {OUTPUT_JSON}", flush=True)
    if stage_one_failed or stage_two_failed:
        print(
            f"[parity] FAILED — stage 1: {stage_one_failed or 'ok'}; "
            f"stage 2 solids: {stage_two_failed or 'ok'}",
            flush=True,
        )
        return MISMATCH_EXIT
    print(
        "[parity] PASSED: the scorer cannot see which path wrote the script, "
        "and a re-bake reproduces the solid",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
