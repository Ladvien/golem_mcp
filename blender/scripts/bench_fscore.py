#!/usr/bin/env python3
"""F-score beside Chamfer, and an audit of the references themselves.

WHY THIS EXISTS. Chamfer distance is a poor discriminator of shape.
Tatarchenko, Richter, Ranftl, Li, Koltun & Brox, "What Do Single-View 3D
Reconstruction Networks Learn?", CVPR 2019 (DOI 10.1109/cvpr.2019.00352)
showed that under CD and IoU, pure retrieval and classification baselines
are statistically indistinguishable from methods that claim to
reconstruct: the metrics are dominated by category-level priors, so a
mean shape of the right category scores well. Their recommendation is
F-score at a distance threshold, which separates *surface agreement* from
*being the average object*.

This repo's own numbers fit that thesis and are why the tool was written
(measured 2026-09-10 on the OT-27 holdout rolls):

  * forcing the reference's exact aspect ratios onto our meshes — an
    oracle no writer could beat — moves mean cd_pca only 0.0270 -> 0.0227,
    so proportion is nearly worthless as a lever;
  * the orientation term is at the holdout's documented floor of 0.0590
    (see docs/2026-09-04-chat-harness-plan.md P8a), which is a property of
    the references, not of our placement;
  * Nautilus_seed0 scores WORST of twenty while rendering as a proper
    spiral shell, against a reference that renders as a thin needle.

So before any more model time is spent on the remaining form residual,
the instrument is checked. Two outputs:

1. F-score, precision and recall per instance at several thresholds.
   Precision is "of the surface we made, how much belongs"; recall is "of
   the surface that should be there, how much did we make". CD folds
   those into one number, which is exactly why it cannot say whether a
   model invented surface or missed it.

2. A reference audit. A reference that is degenerate makes its instance
   unscoreable, and that must be reported rather than silently averaged
   into a mean that then ranks configurations.

The scorer's own sampling, normalisation and KD-trees are imported from
<bench>/metrics/shape_chamfer.py rather than reimplemented, exactly as
scripts/diagnose_3dcode.py does, so these numbers sit in the same space
as the ones the panel already reports.

Runs under the bench venv (trimesh + numpy + scipy; no Blender):

    /Users/ladvien/3dcodebench/.venv/bin/python scripts/bench_fscore.py \\
        --bench-root /Users/ladvien/3dcodebench \\
        --model-dir blended-deepseek-v4-pro-disclosed-roll1 \\
        --instances-file bench_sets/instances_holdout.txt
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_surface_metrics import (  # ONE alignment search, ONE F-score (OT-36)
    FSCORE_THRESHOLDS,
    PRIMARY_FSCORE_THRESHOLD,
    best_pca_alignment,
    fscore,
)

# The scorer's defaults, so every number here is comparable with the
# panel's. Both are the shape_chamfer.py argparse defaults.
N_POINTS = 8192
SEED = 0

# Thresholds live in `bench_thresholds.FSCORE_THRESHOLDS`, chosen A PRIORI
# before any of them was read; `PRIMARY_FSCORE_THRESHOLD` is the one the
# panel ranks on. Re-choosing after the fact is selection on the test set
# (DOI 10.48550/arXiv.2507.02554, quoted in ops/canonical_orientation.py).
PRIMARY_THRESHOLD = PRIMARY_FSCORE_THRESHOLD

# A reference is flagged thin when its smallest extent IN ITS OWN FRAME
# is this fraction of its largest. Own frame, not world axes: measured
# 2026-09-10, Nautilus_seed0's reference reads [1, 0.977, 0.898] on world
# axes — near-cubic, apparently healthy — and [1, 0.224, 0.074] in its
# own frame, because it is a needle lying along the bounding box's
# diagonal. A world-axis test misses exactly the object it must catch.
DEGENERATE_EXTENT_RATIO = 0.10
MINIMUM_PLAUSIBLE_FACES = 12
# World and own-frame mid/max ratios differing by more than this mean the
# reference is posed off-axis, which matters beyond this report: the
# proportion oracle in scripts/shape_error_decompose.py takes its targets
# from WORLD-axis extents, so for such a reference it instructs a writer
# to build a near-cube to match a needle. Nautilus is the proof — its
# "oracle" cd_pca is 0.1858 against an actual 0.0679, i.e. the oracle
# makes it worse, which a true oracle cannot do.
OFF_AXIS_RATIO_DISAGREEMENT = 0.15
# The audit samples the reference to find its own frame; the scorer's
# count is overkill for a ratio, and this keeps the audit fast.
AUDIT_SAMPLE_POINTS = 4096


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--out", default="", help="Markdown path; default stdout")
    parser.add_argument("--json", default="", help="optional JSON sidecar")
    return parser.parse_args(argv)


def own_frame_extents(mesh):
    """Extents along the mesh's OWN principal axes, largest first.

    A world-axis bounding box describes the axes, not the object: a
    needle lying along the box diagonal has a near-cubic box. Every
    degeneracy question here is about the object.
    """
    try:
        points, _ = trimesh.sample.sample_surface(mesh, AUDIT_SAMPLE_POINTS, seed=SEED)
    except Exception:  # noqa: BLE001 — an unsampleable reference is the finding
        return None
    points = np.asarray(points, dtype=np.float64)
    points = points - points.mean(axis=0)
    _, _, principal_axes = np.linalg.svd(points, full_matrices=False)
    spans = np.ptp(points @ principal_axes.T, axis=0)
    return tuple(sorted((float(span) for span in spans), reverse=True))


def reference_audit(glb_path):
    """What the reference actually is, so a broken one can be named.

    Reported, never used to drop an instance here: a mean that quietly
    omits its hardest rows is a worse lie than one that includes a bad
    reference and says so.
    """
    if not glb_path.exists():
        return {"present": False}
    try:
        mesh = trimesh.load(glb_path, force="mesh")
    except Exception as error:  # noqa: BLE001 — a broken reference is the finding
        return {"present": True, "loadable": False, "error": str(error)[:120]}
    if mesh is None or mesh.is_empty or mesh.faces is None or len(mesh.faces) == 0:
        return {"present": True, "loadable": False, "error": "empty mesh"}
    extents = sorted((float(value) for value in mesh.extents), reverse=True)
    largest, middle, smallest = extents
    own = own_frame_extents(mesh)
    flags = []
    if own is None:
        flags.append("could not be sampled")
        own_ratios = None
    else:
        own_ratios = (round(own[1] / own[0], 3), round(own[2] / own[0], 3))
        if own_ratios[1] < DEGENERATE_EXTENT_RATIO:
            flags.append(f"thin in its own frame: min/max {own_ratios[1]}")
        world_mid = middle / largest if largest else 0.0
        if abs(world_mid - own_ratios[0]) > OFF_AXIS_RATIO_DISAGREEMENT:
            flags.append(
                f"posed off-axis: world mid/max {world_mid:.3f} vs own {own_ratios[0]}"
            )
    if len(mesh.faces) < MINIMUM_PLAUSIBLE_FACES:
        flags.append(f"only {len(mesh.faces)} face(s)")
    if not mesh.is_watertight:
        flags.append("not watertight")
    return {
        "present": True,
        "loadable": True,
        "faces": len(mesh.faces),
        "vertices": len(mesh.vertices),
        "extents_m": [round(value, 4) for value in extents],
        "aspect_mid_over_max": round(middle / largest, 3) if largest else None,
        "aspect_min_over_max": round(smallest / largest, 3) if largest else None,
        "own_frame_mid_over_max": own_ratios[0] if own_ratios else None,
        "own_frame_min_over_max": own_ratios[1] if own_ratios else None,
        "flags": flags,
    }


def render_report(model_dir_name, rows, audit_rows) -> str:
    scored = [row for row in rows if row.get("fscore") is not None]
    lines = [
        f"# F-score and reference audit — {model_dir_name}",
        "",
        (
            f"{len(scored)} of {len(rows)} instances scored; {N_POINTS} points, "
            f"seed {SEED}; thresholds as a fraction of the unit-sphere radius; "
            f"ranked on F@{PRIMARY_THRESHOLD} (chosen a priori)."
        ),
        "",
        (
            "Chamfer distance ranks category priors rather than surface agreement "
            "(DOI 10.1109/cvpr.2019.00352); precision and recall separate surface "
            "we invented from surface we missed, which CD folds into one number."
        ),
        "",
        f"## Per instance (sorted by F@{PRIMARY_THRESHOLD:.2f} ascending — worst first)",
        "",
        (
            "| instance | cd_pca | F@0.01 | F@0.02 | F@0.05 | F@0.10 "
            "| precision@0.05 | recall@0.05 |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in sorted(scored, key=lambda item: item["fscore"][PRIMARY_THRESHOLD]):
        fs = row["fscore"]
        lines.append(
            f"| {row['instance']} | {row['cd_pca']:.4f} | "
            + " | ".join(f"{fs[threshold]:.3f}" for threshold in FSCORE_THRESHOLDS)
            + f" | {row['precision'][PRIMARY_THRESHOLD]:.3f} "
            f"| {row['recall'][PRIMARY_THRESHOLD]:.3f} |"
        )
    for row in rows:
        if row.get("fscore") is None:
            lines.append(f"| {row['instance']} | — | — | — | — | — | — | — |")
    if scored:
        lines += [
            "",
            "## Means",
            "",
            "| threshold | F-score | precision | recall |",
            "|---|---|---|---|",
        ]
        for threshold in FSCORE_THRESHOLDS:
            lines.append(
                f"| {threshold:.2f} | "
                f"{np.mean([r['fscore'][threshold] for r in scored]):.4f} | "
                f"{np.mean([r['precision'][threshold] for r in scored]):.4f} | "
                f"{np.mean([r['recall'][threshold] for r in scored]):.4f} |"
            )
        lines.append("")
        lines.append(
            f"mean cd_pca over the same rows = "
            f"{np.mean([r['cd_pca'] for r in scored]):.4f}"
        )

    flagged = [
        (name, audit)
        for name, audit in audit_rows.items()
        if not audit.get("loadable", False) or audit.get("flags")
    ]
    lines += ["", "## Reference audit", ""]
    if not flagged:
        lines.append("Every reference loads, is watertight and has no degenerate axis.")
    else:
        lines.append(
            "A flagged reference makes its instance's score a statement about "
            "the reference, not about the candidate."
        )
        lines += [
            "",
            (
                "| instance | faces | world mid/max, min/max "
                "| own-frame mid/max, min/max | flags |"
            ),
            "|---|---|---|---|---|",
        ]
        for name, audit in sorted(flagged):
            if not audit.get("loadable", False):
                lines.append(f"| {name} | — | — | — | {audit.get('error', 'absent')} |")
                continue
            lines.append(
                f"| {name} | {audit['faces']} | "
                f"{audit['aspect_mid_over_max']}, {audit['aspect_min_over_max']} | "
                f"{audit['own_frame_mid_over_max']}, {audit['own_frame_min_over_max']} | "
                f"{'; '.join(audit['flags'])} |"
            )
    return "\n".join(lines) + "\n"


def self_test(sc) -> bool:
    """Two properties, both of which have already been wrong once.

    1. F(S, S) = 1 at the tightest threshold. A metric that cannot score a
       cloud against itself is measuring nothing.
    2. `own_frame_extents` sees a needle lying along the bounding box's
       diagonal. The first version of this audit used `mesh.extents` and
       reported Nautilus_seed0's reference as near-cubic (0.977, 0.898)
       when it is a needle at 0.074 — a world-axis box describes the axes,
       not the object, and it missed exactly the instance it existed to
       catch. Non-zero exit rather than a wrong report.
    """
    probe, _ = trimesh.sample.sample_surface(
        trimesh.creation.icosphere(subdivisions=3), 2048, seed=SEED
    )
    probe = sc.normalize_unit_sphere(np.asarray(probe, dtype=np.float64))
    identity, _, _ = fscore(probe, probe, min(FSCORE_THRESHOLDS))

    # A long thin box, then rotated so no world axis follows it.
    needle = trimesh.creation.box(extents=(1.0, 0.05, 0.05))
    world_aligned = own_frame_extents(needle)
    diagonal = needle.copy()
    diagonal.apply_transform(
        trimesh.transformations.rotation_matrix(np.radians(45), (0.0, 0.0, 1.0))
    )
    diagonal.apply_transform(
        trimesh.transformations.rotation_matrix(np.radians(35.264), (1.0, 0.0, 0.0))
    )
    own = own_frame_extents(diagonal)
    axis_aligned_ratio = min(diagonal.extents) / max(diagonal.extents)
    own_ratio = own[2] / own[0]
    unrotated_ratio = world_aligned[2] / world_aligned[0]

    checks = (
        ("F(S, S) = 1 at the tightest threshold", identity >= 1.0 - 1e-9),
        (
            "the needle's own frame survives rotation",
            abs(own_ratio - unrotated_ratio) < 0.01,
        ),
        (
            "a world-axis box would NOT have seen it",
            axis_aligned_ratio > own_ratio * 2.0,
        ),
    )
    print(
        f"self-test: F(S,S)={identity:.6f} needle own min/max={own_ratio:.3f} "
        f"world min/max={axis_aligned_ratio:.3f}",
        flush=True,
    )
    for label, passed in checks:
        if not passed:
            print(f"self-test FAILED: {label}", file=sys.stderr, flush=True)
    return all(passed for _, passed in checks)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root)
    metrics_dir = bench_root / "metrics"
    if not metrics_dir.is_dir():
        raise SystemExit(f"No metrics dir under {bench_root}")
    sys.path.insert(0, str(metrics_dir))
    import shape_chamfer as sc  # the scorer itself — replication, not reimplementation

    results_root = Path(arguments.results_root)
    if not results_root.is_absolute():
        results_root = bench_root / results_root
    model_dir = results_root / arguments.model_dir
    data_root = bench_root / "data"
    instances = [
        line.strip()
        for line in Path(arguments.instances_file).read_text().splitlines()
        if line.strip()
    ]

    if not self_test(sc):
        raise SystemExit("self-test FAILED — refusing to emit a report")

    rng = np.random.default_rng(SEED)
    rows = []
    audit_rows = {}
    for instance in instances:
        audit_rows[instance] = reference_audit(
            data_root / instance / "glb" / f"{instance}.glb"
        )
        row = {
            "instance": instance,
            "fscore": None,
            "precision": None,
            "recall": None,
            "cd_pca": None,
        }
        reference_points = sc.load_mesh_points(
            data_root / instance / "glb" / f"{instance}.glb", N_POINTS, rng
        )
        generated_points = sc.load_mesh_points(
            model_dir / instance / "glb" / f"{instance}.glb", N_POINTS, rng
        )
        if reference_points is None or generated_points is None:
            rows.append(row)
            continue
        reference_points = sc.normalize_unit_sphere(reference_points)
        generated_points = sc.normalize_unit_sphere(generated_points)
        # Orientation is quotiented out by the same search diagnose_3dcode.py
        # uses, so F-score and cd_pca answer the same question about the
        # same pose: is the SHAPE right, given the best frame alignment.
        best_rotation, best_distance = best_pca_alignment(
            sc, reference_points, generated_points
        )
        aligned = generated_points @ best_rotation.T
        row["cd_pca"] = best_distance
        row["fscore"], row["precision"], row["recall"] = {}, {}, {}
        for threshold in FSCORE_THRESHOLDS:
            value, precision, recall = fscore(reference_points, aligned, threshold)
            row["fscore"][threshold] = value
            row["precision"][threshold] = precision
            row["recall"][threshold] = recall
        rows.append(row)
        print(
            f"  {instance:<26} cd_pca {row['cd_pca']:.4f}  "
            f"F@{PRIMARY_THRESHOLD} {row['fscore'][PRIMARY_THRESHOLD]:.3f}",
            flush=True,
        )

    report = render_report(arguments.model_dir, rows, audit_rows)
    if arguments.out:
        Path(arguments.out).write_text(report)
        print(f"wrote {arguments.out}")
    else:
        print(report)
    if arguments.json:
        Path(arguments.json).write_text(
            json.dumps(
                {
                    "model_dir": arguments.model_dir,
                    "n_points": N_POINTS,
                    "seed": SEED,
                    "primary_threshold": PRIMARY_THRESHOLD,
                    "per_instance": [{k: v for k, v in row.items()} for row in rows],
                    "reference_audit": audit_rows,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
        print(f"wrote {arguments.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
