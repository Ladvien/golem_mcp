#!/usr/bin/env python3
"""Decompose a blended model row's 3DCodeBench chamfer into its components.

Answers one question before any live model time is spent: how much of a
model row's `cd_yawmin` is orientation, how much is proportion (aspect
ratio), and how much is form that neither of those can reach.

    cd_yawmin  = cd_pca + Δ_orient                     (orientation split)
    cd_pca     = proportion_headroom + form_residual   (shape split)

`cd_pca` is the chamfer after the generated cloud is rotated by the best of
the 24 proper rotations mapping its PCA frame onto the reference's, so
orientation is quotiented out. `form_residual` is `cd_pca` measured again
after the generated cloud's extent *ratios* have been forced onto the
reference's own — an oracle no writer could beat — and the difference
between the two is the proportion headroom.

Two details decide every number this script prints; both were established
by measurement (2026-09-03) and are pinned here so the arithmetic cannot
drift:

1. **The target ratios come from the reference cloud's WORLD-axis extents**
   (its glTF bounding box: `sorted(ptp)` descending, as `mid/max, min/max`),
   not from its PCA-basis extents. World-axis ratios are the quantity a
   writer could actually author, and they are what the recorded holdout
   aspect means (reference mid/max 0.578, generated 0.560, mean paired error
   0.195) were measured in. Using PCA-basis targets instead flattens a coil
   into the reference's inertia-frame slab and collapses the oracle to a
   degenerate 0.0098 mean on this holdout — the report prints that variant's
   mean too, labelled, so the two can never be confused again.
2. **After rescaling the axes, both clouds MUST go back through the scorer's
   `normalize_unit_sphere`.** Rescaling per-axis without re-normalising
   leaves the generated cloud shrunk inside the unit sphere and absorbs part
   of the alignment into the scale, which understates the residual.

Replication, not reimplementation: the metric comes from the benchmark's
own `metrics/shape_chamfer.py`, and the rotation helpers from
`scripts/bench_surface_metrics.py`. Sampling follows the scorer exactly — one
`default_rng(0)` shared across instances, reference cloud sampled before
the generated one, 8192 points, both clouds unit-sphere normalised. Any
other ordering silently changes every number.

Runs under the bench venv (needs trimesh/scipy/numpy):

    /Users/ladvien/3dcodebench/.venv/bin/python scripts/shape_error_decompose.py \
      --bench-root /Users/ladvien/3dcodebench \
      --model-dir blended-deepseek-v4-pro-iter3 \
      --instances-file bench_sets/instances_holdout.txt
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_surface_metrics import best_pca_alignment, pca_frame  # helpers, reused

DECOMPOSE_N_POINTS = 8192  # scorer parity (--n-points default)
DECOMPOSE_SEED = 0  # scorer parity (--seed default)
PARITY_TOLERANCE = 1e-9  # cd_yawmin must match the scorer exactly
DEGENERATE_EXTENT = 1e-9  # below this an axis cannot be rescaled
ASPECT_PRIOR_BRIEF_ADJECTIVE = 0.0567  # dev-fitted, measured 2026-09-03
ASPECT_PRIOR_DEV_MEDIAN = 0.0511  # no adjectives, measured 2026-09-03
WRITER_MEASURED_CD_PCA = 0.0273  # iter3 holdout, measured 2026-09-03


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench-root",
        required=True,
        help="3DCodeBench checkout (holds data/ and metrics/)",
    )
    parser.add_argument(
        "--results-root",
        default="results/text_to_3D_agent",
        help="Results root under --bench-root (relative or absolute).",
    )
    parser.add_argument(
        "--model-dir", required=True, help="Model row name under --results-root"
    )
    parser.add_argument(
        "--instances-file",
        required=True,
        help="Frozen instance list for the decomposition",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Markdown report path (default "
        "outputs/bench/shape_error_decompose_"
        "<model-dir>.md)",
    )
    parser.add_argument(
        "--json",
        default="",
        help="Also write the per-instance rows as JSON (the "
        "`per_instance` of diagnose_3dcode.py --json, without its "
        "`means` block; the means stay in the Markdown). "
        "The fine-tune decision experiment's Phase A "
        "reads cd_pca_aspect_oracle per instance to "
        "separate G1 from G2, and Markdown is not a "
        "data path.",
    )
    return parser.parse_args(argv)


def read_instances(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def aspect_ratios(points) -> tuple[float, float]:
    """(mid/max, min/max) of the cloud's axis-aligned extents."""
    extents = np.sort(np.ptp(points, axis=0))[::-1]
    largest = float(extents[0])
    if largest < DEGENERATE_EXTENT:
        raise SystemExit("degenerate cloud: largest extent is zero")
    return float(extents[1] / largest), float(extents[2] / largest)


def rescale_to_aspect(sc, reference_local, generated_local, target) -> float:
    """Chamfer after forcing `target` extent ratios onto the generated cloud.

    Keeps the generated cloud's largest extent, sets its second-largest to
    `largest * target[0]` and its smallest to `largest * target[1]`, scaling
    each axis about the cloud's own mean; then re-normalises BOTH clouds to
    the unit sphere before scoring. The re-normalisation is load-bearing —
    see the module docstring.
    """
    extents = np.ptp(generated_local, axis=0)
    order = np.argsort(-extents, kind="stable")
    largest = float(extents[order[0]])
    if largest < DEGENERATE_EXTENT:
        raise SystemExit("degenerate cloud: largest extent is zero")
    wanted = np.array(extents, dtype=np.float64)
    wanted[order[1]] = largest * target[0]
    wanted[order[2]] = largest * target[1]
    factors = np.ones(3, dtype=np.float64)
    for axis in range(3):
        if extents[axis] < DEGENERATE_EXTENT:
            continue
        factors[axis] = wanted[axis] / extents[axis]
    center = generated_local.mean(axis=0, keepdims=True)
    rescaled = (generated_local - center) * factors
    rescaled = rescaled + reference_local.mean(axis=0, keepdims=True)
    return sc.chamfer_squared(
        sc.normalize_unit_sphere(reference_local), sc.normalize_unit_sphere(rescaled)
    )


def decompose(
    sc, data_root: Path, model_root: Path, instances: list[str]
) -> list[dict]:
    """One row per instance. A missing cloud is fatal, never dropped."""
    rng = np.random.default_rng(DECOMPOSE_SEED)
    rows = []
    for instance in instances:
        reference_glb = data_root / instance / "glb" / f"{instance}.glb"
        generated_glb = model_root / instance / "glb" / f"{instance}.glb"
        for path in (reference_glb, generated_glb):
            if not path.exists() or path.stat().st_size == 0:
                raise SystemExit(
                    f"{instance}: missing or empty GLB at {path} — a "
                    f"decomposition with dropped rows reports a wrong mean"
                )
        reference = sc.load_mesh_points(reference_glb, DECOMPOSE_N_POINTS, rng)
        generated = sc.load_mesh_points(generated_glb, DECOMPOSE_N_POINTS, rng)
        for name, cloud in (("reference", reference), ("generated", generated)):
            if cloud is None:
                raise SystemExit(f"{instance}: {name} GLB did not surface-sample")
        reference = sc.normalize_unit_sphere(reference)
        generated = sc.normalize_unit_sphere(generated)

        cd_yawmin = float(sc.chamfer_with_yaw(reference, generated)[1])
        rotation, cd_pca_value = best_pca_alignment(sc, reference, generated)
        if rotation is None:
            raise SystemExit(f"{instance}: no proper rotation aligned the PCA frames")
        aligned = generated @ rotation.T

        reference_frame = pca_frame(reference)
        reference_local = reference @ reference_frame
        generated_local = aligned @ reference_frame
        # World-axis (glTF bounding-box) ratios: the writer-actionable
        # proportions, and the pinned oracle target — see detail 1 above.
        aspect_ref = aspect_ratios(reference)
        aspect_gen = aspect_ratios(generated)
        oracle = rescale_to_aspect(sc, reference_local, generated_local, aspect_ref)
        # The discredited alternative, reported so it stays distinguishable.
        oracle_pca_target = rescale_to_aspect(
            sc, reference_local, generated_local, aspect_ratios(reference_local)
        )

        rows.append(
            {
                "instance": instance,
                "cd_yawmin": cd_yawmin,
                "cd_pca": cd_pca_value,
                "delta_orient": cd_yawmin - cd_pca_value,
                "cd_pca_aspect_oracle": float(oracle),
                "cd_pca_aspect_oracle_pca_target": float(oracle_pca_target),
                "aspect_ref": aspect_ref,
                "aspect_gen": aspect_gen,
            }
        )
    return rows


def assert_scorer_parity(rows: list[dict], model_root: Path) -> int:
    """cd_yawmin must equal the scorer's own per-instance value."""
    metrics_path = model_root / "_metrics" / "shape_chamfer.json"
    if not metrics_path.exists():
        raise SystemExit(
            f"No scorer output at {metrics_path} — score the "
            f"model row before decomposing it"
        )
    scored = {
        row["instance"]: row.get("cd_yawmin")
        for row in json.loads(metrics_path.read_text())["per_instance"]
    }
    mismatched = []
    checked = 0
    for row in rows:
        expected = scored.get(row["instance"])
        if expected is None:
            continue
        checked += 1
        if abs(expected - row["cd_yawmin"]) > PARITY_TOLERANCE:
            mismatched.append((row["instance"], expected, row["cd_yawmin"]))
    if mismatched:
        for instance, expected, got in mismatched:
            print(
                f"PARITY MISMATCH {instance}: scorer={expected!r} replicate={got!r}",
                file=sys.stderr,
            )
        raise SystemExit("cd_yawmin does not reproduce the scorer's output")
    return checked


def mean_of(rows: list[dict], key: str) -> float:
    return float(sum(row[key] for row in rows) / len(rows))


def render_report(
    rows: list[dict], model_dir: str, instances_file: str, checked: int
) -> str:
    mean_yawmin = mean_of(rows, "cd_yawmin")
    mean_pca = mean_of(rows, "cd_pca")
    mean_orient = mean_of(rows, "delta_orient")
    mean_oracle = mean_of(rows, "cd_pca_aspect_oracle")
    mean_oracle_pca_target = mean_of(rows, "cd_pca_aspect_oracle_pca_target")
    headroom = mean_pca - mean_oracle
    reachable = mean_oracle + mean_orient

    lines = [
        f"# Shape-error decomposition — {model_dir}",
        "",
        (
            f"Instances: `{instances_file}` ({len(rows)}); "
            f"{DECOMPOSE_N_POINTS} points, seed {DECOMPOSE_SEED}, reference "
            f"sampled first; {checked} `cd_yawmin` values asserted equal to "
            f"`_metrics/shape_chamfer.json` within {PARITY_TOLERANCE:g}."
        ),
        "",
        "## Per-instance (sorted by cd_pca descending)",
        "",
        (
            "| instance | cd_yawmin | cd_pca | Δ_orient | cd_pca oracle "
            "proportions | oracle (PCA-basis target) | aspect_ref (mid/max, "
            "min/max) | aspect_gen |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: r["cd_pca"], reverse=True):
        lines.append(
            f"| {row['instance']} | {row['cd_yawmin']:.4f} | "
            f"{row['cd_pca']:.4f} | {row['delta_orient']:+.4f} | "
            f"{row['cd_pca_aspect_oracle']:.4f} | "
            f"{row['cd_pca_aspect_oracle_pca_target']:.4f} | "
            f"{row['aspect_ref'][0]:.3f}, {row['aspect_ref'][1]:.3f} | "
            f"{row['aspect_gen'][0]:.3f}, {row['aspect_gen'][1]:.3f} |"
        )

    lines += [
        "",
        "## Headroom",
        "",
        f"- mean cd_yawmin = {mean_yawmin:.4f}",
        f"- mean cd_pca = {mean_pca:.4f}",
        f"- mean Δ_orient = {mean_orient:.4f}",
        f"- mean cd_pca under oracle proportions = {mean_oracle:.4f}",
        (f"- proportion headroom = mean cd_pca - mean oracle = {headroom:.4f}"),
        f"- form residual = mean oracle = {mean_oracle:.4f}",
        (
            f"- (for contrast only) mean cd_pca under oracle proportions taken "
            f"in the reference's PCA basis instead of its world bounding box = "
            f"{mean_oracle_pca_target:.4f} — a degenerate flattening, not the "
            f"writer-actionable quantity; never quote this as the ceiling"
        ),
        "",
        (
            f"minimum reachable mean cd_yawmin with oracle proportions and "
            f"unchanged orientation = {reachable:.4f}; any target below this "
            f"is unreachable by shape work alone"
        ),
        "",
        (
            "## Proportion PRIORS are a closed question under cd_pca; "
            "proportion itself is not, under F@0.05"
        ),
        "",
        (
            f"A brief-adjective aspect prior fitted on the 145-instance dev "
            f"split scores {ASPECT_PRIOR_BRIEF_ADJECTIVE:.4f} mean cd_pca on "
            f"this holdout and the dev-median prior (no adjectives) "
            f"{ASPECT_PRIOR_DEV_MEDIAN:.4f}, both far worse than the "
            f"{WRITER_MEASURED_CD_PCA:.4f} the writer already achieves "
            f"unaided, so a GLOBAL proportion rule has nothing to correct, "
            f"and under cd_pca the per-instance oracle buys only "
            f"{headroom:.4f}."
        ),
        "",
        (
            "Falsified in part on 2026-09-11, when the ranking axis was "
            "F@0.05 (OT-36): `scripts/bench_proportion_headroom.py` measured "
            "the same per-instance oracle — per axis in the ALIGNED frame, "
            "which is BEN-6c's fix — over 160 instance rolls of this holdout "
            "at F 0.4531 -> 0.7017, +0.2486. Chamfer averaged a miss that a "
            "0.05 threshold counts whole. The 'bias ~ 0' reading above was "
            "true of the DISTRIBUTION and false of the INSTANCE: the same "
            "instance is wrong the same way in all eight rolls (Jar 2x too "
            "wide, DoorCasing 8x too thin, Pillar 3x too fat), on the middle "
            "and thin axes only. A prior still cannot fix that; a per-instance "
            "commitment the gate can measure is the open question, and the "
            "proportion contract (docs/2026-09-06-bench-panel-preregistration.md) "
            "is its pre-registered test."
        ),
        "",
    ]
    return "\n".join(lines)


def main(argv) -> int:
    arguments = parse_arguments(argv)

    bench_root = Path(arguments.bench_root).resolve()
    metrics_dir = bench_root / "metrics"
    if not metrics_dir.is_dir():
        raise SystemExit(f"No metrics dir under {bench_root}")
    sys.path.insert(0, str(metrics_dir))
    import shape_chamfer as sc  # the scorer itself — replication, not reim.

    results_root = Path(arguments.results_root)
    if not results_root.is_absolute():
        results_root = bench_root / results_root
    model_root = results_root / arguments.model_dir
    if not model_root.is_dir():
        raise SystemExit(f"No such model dir: {model_root}")
    data_root = bench_root / "data"

    instances = read_instances(Path(arguments.instances_file))
    if not instances:
        raise SystemExit(f"No instances in {arguments.instances_file}")

    rows = decompose(sc, data_root, model_root, instances)
    checked = assert_scorer_parity(rows, model_root)
    print(
        f"parity: {checked}/{len(rows)} instances match the scorer's "
        f"per-instance cd_yawmin exactly"
    )

    out_path = (
        Path(arguments.out)
        if arguments.out
        else Path("outputs/bench") / f"shape_error_decompose_{arguments.model_dir}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_report(rows, arguments.model_dir, arguments.instances_file, checked)
    )
    print(f"wrote {out_path}")
    if arguments.json:
        json_path = Path(arguments.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(
                {
                    "model_dir": arguments.model_dir,
                    "instances_file": arguments.instances_file,
                    "n_points": DECOMPOSE_N_POINTS,
                    "seed": DECOMPOSE_SEED,
                    "parity_checked": checked,
                    "per_instance": rows,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"wrote {json_path}")
    print(
        f"mean cd_pca {mean_of(rows, 'cd_pca'):.4f}  "
        f"mean Δ_orient {mean_of(rows, 'delta_orient'):.4f}  "
        f"mean oracle {mean_of(rows, 'cd_pca_aspect_oracle'):.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
