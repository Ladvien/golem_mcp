"""Where F@0.05 is lost: the proportion headroom of finished bench rolls.

For every instance of every `--model-dir` this reads the generated and
reference GLBs, scores F@0.05 with the pieces `diagnose_3dcode.py` uses (the
scorer's sampling and unit-sphere normalisation, `best_pca_alignment`,
`fscore`) — except that each instance seeds its own `default_rng(SEED)`
instead of sharing the scorer's one stream across instances, so past the
first instance the clouds sampled are not the ones the panel's F column was scored on — then asks
one counterfactual: what would F@0.05 be if the
generated cloud had the reference's extents on every axis? The rescale
is per axis IN THE ALIGNED FRAME — the frame the metric is measured in —
which is what BEN-6c asked of the older world-axis oracle in
`shape_error_decompose.py`: an off-axis reference (Nautilus) no longer
turns a needle into a near-cube. The cloud is then re-normalised and
re-aligned, so the number is the metric's own answer and not a shortcut.

It also counts connected components and FLOATING components (a
component whose bounding box touches no other) on both sides, because
3DCodeBench's Finding 1 (DOI 10.48550/arXiv.2606.01057) names floating
and disconnected parts as the bottleneck once code compiles, and a claim
that it is or is not ours has to come from our own GLBs.

Read-only over `results/`; writes one JSON and one Markdown table.
Measured 2026-09-11 over 160 instance rolls: F 0.4531 -> 0.7017 under
the oracle, 0 floating components — the numbers this script must
reproduce (see tests/pure/test_bench_proportion_headroom.py for the
math on fixtures).

    python3 scripts/bench_proportion_headroom.py \
      --bench-root /Users/ladvien/3dcodebench \
      --model-dir blended-deepseek-v4-pro --model-dir ... \
      --instances-file bench_sets/instances_holdout.txt \
      --json outputs/bench/proportion_headroom.json \
      --out outputs/bench/proportion_headroom.md
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_surface_metrics import best_pca_alignment, fscore
from bench_thresholds import (
    COMPONENT_TOUCH_TOLERANCE_FRACTION,
    PAIRWISE_COMPONENT_LIMIT,
    PRIMARY_FSCORE_THRESHOLD,
    PROPORTION_EXTENT_PERCENTILES,
)

# The scorer's defaults, so every number here is comparable with the panel's.
N_POINTS = 8192
SEED = 0
# A rescale factor is never divided by a zero extent; a flat cloud on one
# axis is reported as it is rather than blown up.
MINIMUM_EXTENT = 1e-9


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--model-dir", action="append", required=True)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--json", default="", help="JSON rows; default none")
    parser.add_argument("--out", default="", help="Markdown path; default stdout")
    return parser.parse_args(argv)


def extents_at_percentiles(points, percentiles=PROPORTION_EXTENT_PERCENTILES):
    """Per-axis extent between the two percentiles, robust to a stray vertex."""
    low, high = (
        np.percentile(points, percentiles[0], axis=0),
        np.percentile(points, percentiles[1], axis=0),
    )
    return high - low


def oracle_rescaled(sc, reference_points, aligned_points):
    """The aligned cloud with the reference's extents on every axis,
    re-normalised to the unit sphere. Pure numpy; the caller re-aligns."""
    scale = extents_at_percentiles(reference_points) / np.maximum(
        extents_at_percentiles(aligned_points), MINIMUM_EXTENT
    )
    return sc.normalize_unit_sphere(aligned_points * scale)


def component_counts(mesh):
    """(components, floating) for one mesh; floating is -1 when the
    component count exceeds PAIRWISE_COMPONENT_LIMIT and was not tested."""
    parts = mesh.split(only_watertight=False)
    count = len(parts)
    if count <= 1:
        return 1, 0
    if count > PAIRWISE_COMPONENT_LIMIT:
        return count, -1
    low = np.array([part.bounds[0] for part in parts])
    high = np.array([part.bounds[1] for part in parts])
    tolerance = COMPONENT_TOUCH_TOLERANCE_FRACTION * float(mesh.extents.max())
    overlaps = np.all(high[:, None, :] + tolerance >= low[None, :, :], axis=2) & np.all(
        high[None, :, :] + tolerance >= low[:, None, :], axis=2
    )
    np.fill_diagonal(overlaps, False)
    return count, int((~overlaps.any(axis=1)).sum())


def axis_log2_errors(reference_points, aligned_points):
    """|log2(reference extent / generated extent)| per axis, axes ordered
    by the REFERENCE's extent descending: (largest, middle, smallest)."""
    reference_extents = extents_at_percentiles(reference_points)
    generated_extents = np.maximum(
        extents_at_percentiles(aligned_points), MINIMUM_EXTENT
    )
    order = np.argsort(-reference_extents)
    return np.abs(np.log2(reference_extents[order] / generated_extents[order]))


def score_instance(sc, reference_glb: Path, generated_glb: Path) -> dict | None:
    rng = np.random.default_rng(SEED)
    reference = sc.load_mesh_points(reference_glb, N_POINTS, rng)
    generated = sc.load_mesh_points(generated_glb, N_POINTS, rng)
    if reference is None or generated is None:
        return None
    reference = sc.normalize_unit_sphere(reference)
    generated = sc.normalize_unit_sphere(generated)
    rotation, _ = best_pca_alignment(sc, reference, generated)
    aligned = generated @ rotation.T
    value, precision, recall = fscore(reference, aligned, PRIMARY_FSCORE_THRESHOLD)
    rescaled = oracle_rescaled(sc, reference, aligned)
    rotation_2, _ = best_pca_alignment(sc, reference, rescaled)
    oracle_value, _, _ = fscore(
        reference, rescaled @ rotation_2.T, PRIMARY_FSCORE_THRESHOLD
    )
    errors = axis_log2_errors(reference, aligned)
    components_generated, floating_generated = component_counts(
        trimesh.load(generated_glb, force="mesh")
    )
    components_reference, floating_reference = component_counts(
        trimesh.load(reference_glb, force="mesh")
    )
    return {
        "fscore": float(value),
        "precision": float(precision),
        "recall": float(recall),
        "fscore_oracle_proportions": float(oracle_value),
        "headroom": float(oracle_value - value),
        "log2_error_largest": float(errors[0]),
        "log2_error_middle": float(errors[1]),
        "log2_error_smallest": float(errors[2]),
        "components_generated": components_generated,
        "floating_generated": floating_generated,
        "components_reference": components_reference,
        "floating_reference": floating_reference,
    }


def mean_of(group: list[dict], key: str) -> float:
    return float(np.mean([r[key] for r in group]))


def render_markdown(rows: list[dict]) -> str:
    if not rows:
        return "no instances scored\n"
    values = np.array([[r["fscore"], r["fscore_oracle_proportions"]] for r in rows])
    floating = sum(1 for r in rows if r["floating_generated"] > 0)
    lines = [
        f"# Proportion headroom under F@{PRIMARY_FSCORE_THRESHOLD:.2f}",
        "",
        f"- instance rolls scored: {len(rows)}",
        f"- mean F as scored: {values[:, 0].mean():.4f}",
        f"- mean F under oracle proportions: {values[:, 1].mean():.4f}",
        f"- headroom: {values[:, 1].mean() - values[:, 0].mean():+.4f}",
        f"- generated assets with a floating component: {floating} of {len(rows)}",
        "",
        "| instance | rolls | F | F oracle | headroom | log2 err L | M | S |",
        "|---|---|---|---|---|---|---|---|",
    ]
    by_instance: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_instance[row["instance"]].append(row)
    ordered = sorted(
        by_instance.items(), key=lambda item: -np.mean([r["headroom"] for r in item[1]])
    )
    for instance, group in ordered:
        mean = functools.partial(mean_of, group)
        lines.append(
            f"| {instance} | {len(group)} | {mean('fscore'):.3f} | "
            f"{mean('fscore_oracle_proportions'):.3f} | {mean('headroom'):+.3f} | "
            f"{mean('log2_error_largest'):.2f} | {mean('log2_error_middle'):.2f} | "
            f"{mean('log2_error_smallest'):.2f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    sys.path.insert(0, str(bench_root / "metrics"))
    import shape_chamfer as sc  # the scorer itself — replication, not reimplementation

    instances = Path(arguments.instances_file).read_text().split()
    rows = []
    for model_dir in arguments.model_dir:
        root = bench_root / arguments.results_root / model_dir
        for instance in instances:
            generated_glb = root / instance / "glb" / f"{instance}.glb"
            reference_glb = bench_root / "data" / instance / "glb" / f"{instance}.glb"
            if not generated_glb.exists():
                continue
            row = score_instance(sc, reference_glb, generated_glb)
            if row is None:
                continue
            row.update({"model_dir": model_dir, "instance": instance})
            rows.append(row)
            print(
                f"{model_dir} {instance}: F={row['fscore']:.3f} oracle={row['fscore_oracle_proportions']:.3f} "
                f"floating={row['floating_generated']}",
                flush=True,
            )
    if arguments.json:
        Path(arguments.json).write_text(json.dumps(rows, indent=1))
    report = render_markdown(rows)
    if arguments.out:
        Path(arguments.out).write_text(report)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
