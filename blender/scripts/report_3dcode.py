"""Build the 3DCodeBench comparison table from scored result dirs.

    python3 scripts/report_3dcode.py --bench-root /Users/ladvien/3dcodebench \\
        --models blended-deepseek-v4-pro baseline-<model>

Reads only what 3DCodeBench's own scorers wrote (`_metrics/*.json`) plus
this harness's `.agent_meta.json`, and emits one markdown row per model.
It computes nothing: every number is copied from a scorer's output, so
the table cannot drift from the measurement.

The notes block is not decoration. A Chamfer number is meaningless
without the Blender build that baked both sides, the instance list it
was measured over, and the disclosed asymmetry between the two rows —
so those travel with the table, always.
"""

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"

NOTES_TEMPLATE = """\
## Notes

- **Blender build (every bake and render on both rows):** {blender_build}
- **Instance list:** `{instances_file}` ({instance_count} instances)
- **Reference meshes:** baked from the eval set's own ground-truth factory
  scripts with `core/export_glb.py` on the same Blender
  ({reference_ok}/{reference_total} baked; the rest are excluded from the
  instance list because an instance with no reference mesh cannot be
  Chamfer-scored).
- blended's emitted scripts carry a sys.path prelude making `blended.ops`
  importable; baseline scripts are pure bpy.
- Published leaderboard numbers are **not** comparable to this table: they were
  produced on Blender 5.0 on other hardware. Both rows here pass through the
  identical baker, renderer and scorers on this machine, which is what makes
  them comparable to each other.
- **`mean_duration_s` and `mean_turns` are NOT comparable across rows.**
  `exec_pass_rate` and the Chamfer columns are re-measured here on one
  machine, which is the whole point of the table. Cost is not: blended's
  durations were measured live on this machine against a cloud writer,
  while a baseline row's come from the published log's own `latency_s` and
  `num_turns`, recorded on the benchmark authors' hardware. Read those two
  columns per row, never as a delta.
- Image-grounded scorers (`image_similarity.py`, `shape_uni3d.py`) and
  `llm_judge/` need GPU weights (SigLIP-2 / DINOv3 / Uni3D) and are not part
  of this number.
"""


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument(
        "--instances-file",
        default="instances_v1.txt",
        help="Relative to --bench-root unless absolute.",
    )
    parser.add_argument("--blender", default=DEFAULT_BLENDER)
    parser.add_argument("--out", default="")
    return parser.parse_args(argv)


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def blender_build_string(blender: str) -> str:
    try:
        output = subprocess.run(
            [blender, "--version"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[0] if lines else "unavailable"


def reference_bake_counts(bench_root: Path) -> tuple[int, int]:
    ok = total = 0
    for log_path in (bench_root / "data").glob("*/glb/export_log.json"):
        record = load_json(log_path)
        if record is None:
            continue
        total += 1
        if record.get("status") == "OK":
            ok += 1
    return ok, total


def model_row(model_directory: Path) -> dict:
    executability = load_json(model_directory / "_metrics" / "executability.json") or {}
    chamfer = load_json(model_directory / "_metrics" / "shape_chamfer.json") or {}
    yawmin = chamfer.get("cd_yawmin") or {}

    durations: list[float] = []
    turns: list[int] = []
    for metadata_path in sorted(model_directory.glob("*/.agent_meta.json")):
        metadata = load_json(metadata_path) or {}
        if isinstance(metadata.get("duration_s"), (int, float)):
            durations.append(float(metadata["duration_s"]))
        if isinstance(metadata.get("num_turns"), int):
            turns.append(metadata["num_turns"])

    return {
        "model": model_directory.name,
        "n": executability.get("n_total"),
        "exec_pass_rate": executability.get("pass_rate"),
        "cd_yawmin_cond": yawmin.get("conditional_mean"),
        "cd_yawmin_pen": yawmin.get("penalized_mean"),
        "n_glb_ok": chamfer.get("n_ok"),
        "mean_duration_s": round(statistics.fmean(durations), 1) if durations else None,
        "mean_turns": round(statistics.fmean(turns), 1) if turns else None,
    }


def failure_section(model_directory: Path) -> list[str]:
    """Every non-passing instance, named, with the scorer's own fingerprint.

    Read out of `executability.json` rather than written by hand: a
    failure the table hides is a failure the next reader re-discovers.
    """
    executability = load_json(model_directory / "_metrics" / "executability.json") or {}
    failed = executability.get("failed_instances") or []
    if not failed:
        return [f"- **{model_directory.name}** — no failures."]
    lines = [
        f"- **{model_directory.name}** — {len(failed)} failed: "
        + ", ".join(f"`{name}`" for name in failed)
    ]
    lines.extend(
        f"  - ×{entry.get('count')} {entry.get('fingerprint')}"
        for entry in executability.get("top_errors") or []
    )
    return lines


# (key, header, decimal places). Precision is per column because a
# 4-decimal Chamfer distance is meaningful and a 4-decimal wall clock in
# seconds is noise dressed as rigour.
COLUMNS = [
    ("model", "model", 0),
    ("n", "n", 0),
    ("exec_pass_rate", "exec_pass_rate", 4),
    ("cd_yawmin_cond", "cd_yawmin_cond", 4),
    ("cd_yawmin_pen", "cd_yawmin_pen", 4),
    ("n_glb_ok", "n_glb_ok", 0),
    ("mean_duration_s", "mean_duration_s", 1),
    ("mean_turns", "mean_turns", 1),
]


def format_cell(value, places: int) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    results_root = bench_root / arguments.results_root

    instances_path = Path(arguments.instances_file)
    if not instances_path.is_absolute():
        instances_path = bench_root / instances_path
    instance_count = (
        len([line for line in instances_path.read_text().splitlines() if line.strip()])
        if instances_path.exists()
        else 0
    )

    rows = []
    for model in arguments.models:
        model_directory = results_root / model
        if not model_directory.exists():
            raise SystemExit(f"No such model dir: {model_directory}")
        rows.append(model_row(model_directory))

    reference_ok, reference_total = reference_bake_counts(bench_root)

    header = "| " + " | ".join(label for _, label, _p in COLUMNS) + " |"
    divider = "|" + "|".join("---" for _ in COLUMNS) + "|"
    body = [
        "| "
        + " | ".join(format_cell(row[key], places) for key, _label, places in COLUMNS)
        + " |"
        for row in rows
    ]

    document = "\n".join(
        [
            "# 3DCodeBench — blended vs baseline",
            "",
            "Executability and Chamfer distance, both produced by 3DCodeBench's own",
            "unmodified scorers on this machine over one frozen instance subset.",
            "",
            header,
            divider,
            *body,
            "",
            "## Failures",
            "",
            *[
                line
                for model in arguments.models
                for line in failure_section(results_root / model)
            ],
            "",
            NOTES_TEMPLATE.format(
                blender_build=blender_build_string(arguments.blender),
                instances_file=instances_path.name,
                instance_count=instance_count,
                reference_ok=reference_ok,
                reference_total=reference_total,
            ),
        ]
    )

    out_path = (
        Path(arguments.out).resolve()
        if arguments.out
        else results_root / "comparison.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document)
    print(document)
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
