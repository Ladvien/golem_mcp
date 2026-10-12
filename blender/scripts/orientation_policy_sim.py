#!/usr/bin/env python3
"""Measure which depth-axis convention a shape-perfect generation should use.

3DCodeBench's scorer quotients out part of orientation and penalises the
rest in full. `metrics/shape_chamfer.py:126 chamfer_with_yaw` minimises over
4 rotations about the GLB file's Z axis, and `core/export_glb.py:102`
exports with `export_yup=True`, so

    glTF X = Blender X      glTF Y = Blender Z (up)      glTF Z = -Blender Y

The yaw group therefore mixes width with height and leaves ONE penalised
degree of freedom: which Blender axis ends up on the depth axis (Blender
+/-Y). This script measures the policy that minimises the expected penalty
of that single choice.

Method: take each DEV reference cloud as its own shape-perfect generation,
rotate it by the minimal proper signed permutation that puts a chosen
extent RANK on the depth axis, and score it with the benchmark's own
`chamfer_with_yaw`. A policy's mean is then the chamfer a generation with
zero shape error would still pay for orientation alone.

The dev/holdout split exists because selecting a policy on the set you
report inflates the reported score by 9-13% (MLE-bench,
DOI 10.48550/arXiv.2507.02554). Deterministic geometric verification
rather than more model turns follows BlenderGym's verification-ratio
result (DOI 10.48550/arXiv.2504.01786).

Needs trimesh/scipy/numpy, so run it under the BENCH venv:

    /Users/ladvien/3dcodebench/.venv/bin/python scripts/orientation_policy_sim.py \\
        --bench-root /Users/ladvien/3dcodebench \\
        --out outputs/bench/orientation_policy_sim.md

`--generated-model <dir>` switches to the audit mode Step 6 needs: report
the depth-axis extent rank of every GENERATED glb under
`<bench-root>/results/text_to_3D_agent/<dir>`, i.e. did the rule survive
the glTF export.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_surface_metrics import signed_permutations  # the shared rotation helpers

SIMULATION_N_POINTS = 4096  # cheaper than the scorer's 8192; ranks and
# policy means are stable at this density
SIMULATION_SEED = 0
SIMULATION_TOLERANCE = 0.005  # drift allowed against the pinned mean
PINNED_RANK1_MEAN = 0.0311  # measured 2026-09-03 over 145 dev refs
POLICY_RANKS = (0, 1, 2)  # 0 = largest extent on depth axis
DEPTH_AXIS_GLTF_INDEX = 2  # glTF Z = -Blender Y; the penalised DOF
UNIFORM_RANDOM_POLICY_WEIGHT = 1.0 / len(POLICY_RANKS)
ANISOTROPY_BANDS = ((0.0, 0.3), (0.3, 0.6), (0.6, 1.01))
EXACT_HIT_TOLERANCE = 1e-9
POLICY_MEAN_MARGIN = 0.02  # required win over unconstrained choice
AUDIT_TIE_TOLERANCE = 0.02  # audit mode: a depth extent within 2% of
# the middle one makes the rank arbitrary
# and the policy immaterial

PROPER_PERMUTATIONS = tuple(
    matrix for matrix in signed_permutations() if np.linalg.det(matrix) > 0.0
)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bench-root",
        required=True,
        help="3DCodeBench checkout (holds data/ and metrics/)",
    )
    parser.add_argument(
        "--instances-file",
        default="bench_sets/instances_dev_all.txt",
        help="Instance list the policy is measured over",
    )
    parser.add_argument(
        "--holdout-file",
        default="bench_sets/instances_holdout.txt",
        help="Holdout list, reported as a histogram only",
    )
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument(
        "--generated-model",
        default="",
        help="Audit mode: model dir whose generated GLBs are "
        "checked for depth-axis rank instead",
    )
    parser.add_argument("--out", default="outputs/bench/orientation_policy_sim.md")
    return parser.parse_args(argv)


def read_instances(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def sampled_points(glb_path: Path):
    """Surface-sample a GLB the way the scorer does, or None."""
    if not glb_path.exists():
        return None
    try:
        mesh = trimesh.load(glb_path, force="mesh")
    except Exception:  # noqa: BLE001 — an unloadable GLB is reported as unavailable by the callers
        return None
    if mesh.is_empty or mesh.faces is None or len(mesh.faces) == 0:
        return None
    points, _ = trimesh.sample.sample_surface(
        mesh, SIMULATION_N_POINTS, seed=SIMULATION_SEED
    )
    return np.asarray(points, dtype=np.float64)


def extents_of(points):
    return np.ptp(points, axis=0)


def extent_rank_of_depth_axis(points) -> int:
    """Rank (0 = largest) of the depth-axis extent among the three extents.

    Stable argsort, so equal extents rank by axis index and the answer is
    deterministic.
    """
    order = np.argsort(-extents_of(points), kind="stable")
    return int(np.flatnonzero(order == DEPTH_AXIS_GLTF_INDEX)[0])


def depth_axis_policy_rotation(points, policy_rank: int):
    """Minimal proper signed permutation putting `policy_rank` on depth.

    Minimal = largest trace among the candidates, i.e. the smallest
    rotation angle; the enumeration order of `signed_permutations` breaks
    remaining ties, so the choice is deterministic.
    """
    order = np.argsort(-extents_of(points), kind="stable")
    source_axis = int(order[policy_rank])
    candidates = [
        matrix
        for matrix in PROPER_PERMUTATIONS
        if matrix[DEPTH_AXIS_GLTF_INDEX, source_axis] != 0.0
    ]
    if not candidates:
        raise SystemExit("no proper permutation reaches the depth axis")
    return max(candidates, key=lambda matrix: float(np.trace(matrix)))


def band_label(low: float, high: float) -> str:
    return f"{low:.1f}-{min(high, 1.0):.1f}"


def simulate(sc, data_root: Path, instances: list[str]) -> list[dict]:
    """Per-instance policy scores over the reference clouds themselves."""
    rows = []
    for instance in instances:
        points = sampled_points(data_root / instance / "glb" / f"{instance}.glb")
        if points is None:
            raise SystemExit(f"reference cloud unavailable for {instance}")
        reference = sc.normalize_unit_sphere(points)
        extents = extents_of(reference)
        row = {
            "instance": instance,
            "reference_depth_rank": extent_rank_of_depth_axis(reference),
            "anisotropy": float(extents.min() / extents.max()),
            "scores": {},
        }
        for policy_rank in POLICY_RANKS:
            rotation = depth_axis_policy_rotation(reference, policy_rank)
            generated = sc.normalize_unit_sphere(reference @ rotation.T)
            row["scores"][policy_rank] = sc.chamfer_with_yaw(reference, generated)[1]
        rows.append(row)
    return rows


def policy_summary(rows: list[dict], policy_rank: int) -> dict:
    values = np.array([row["scores"][policy_rank] for row in rows])
    return {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "exact_hits": int((values <= EXACT_HIT_TOLERANCE).sum()),
        "count": int(values.size),
    }


def depth_rank_histogram(sc, data_root: Path, instances: list[str]) -> list[int]:
    histogram = [0, 0, 0]
    for instance in instances:
        points = sampled_points(data_root / instance / "glb" / f"{instance}.glb")
        if points is None:
            raise SystemExit(f"reference cloud unavailable for {instance}")
        histogram[extent_rank_of_depth_axis(sc.normalize_unit_sphere(points))] += 1
    return histogram


def audit_generated(sc, model_root: Path, instances: list[str]) -> int:
    """Step-6 acceptance 2: did the depth-axis rule survive glTF export?

    A depth extent within AUDIT_TIE_TOLERANCE of the middle extent counts
    as satisfied: for a near-isotropic object the RANK is arbitrary while
    the policy's actual claim — the depth axis carries a middle-valued
    extent — still holds, and the score cannot tell the difference.
    """
    off_policy = []
    missing = []
    for instance in instances:
        glb = model_root / instance / "glb" / f"{instance}.glb"
        points = sampled_points(glb)
        if points is None:
            missing.append(instance)
            continue
        normalized = sc.normalize_unit_sphere(points)
        rank = extent_rank_of_depth_axis(normalized)
        extents = extents_of(normalized)
        middle = float(np.sort(extents)[1])
        gap = abs(float(extents[DEPTH_AXIS_GLTF_INDEX]) - middle) / float(extents.max())
        satisfied = rank == 1 or gap <= AUDIT_TIE_TOLERANCE
        marker = "ok" if rank == 1 else ("tie" if satisfied else "OFF-POLICY")
        print(
            f"{instance:32s} depth_rank={rank} gap={gap:.4f} "
            f"extents=({extents[0]:.4f}, {extents[1]:.4f}, {extents[2]:.4f}) "
            f"{marker}"
        )
        if not satisfied:
            off_policy.append(instance)
    print(
        f"depth axis carries the middle extent: "
        f"{len(instances) - len(off_policy) - len(missing)}/{len(instances)}"
    )
    if missing:
        print(f"MISSING GLB: {missing}", file=sys.stderr)
    if off_policy:
        print(f"OFF-POLICY: {off_policy}", file=sys.stderr)
    return 1 if (off_policy or missing) else 0


def render_report(
    rows, summaries, uniform_mean, dev_histogram, holdout_histogram, instances_file
) -> str:
    lines = [
        "# Depth-axis orientation policy simulation",
        "",
        (
            f"Dev instances: {len(rows)} (`{instances_file}`). Each reference "
            "cloud is used as its own shape-perfect generation, rotated so a "
            "chosen extent rank lands on the depth axis (glTF Z = -Blender Y), "
            "then scored with the benchmark's own `chamfer_with_yaw`."
        ),
        "",
        (
            f"Sampling: {SIMULATION_N_POINTS} surface points, seed "
            f"{SIMULATION_SEED}, `normalize_unit_sphere` from the scorer."
        ),
        "",
        "| depth-axis policy | mean cd_yawmin | median | exact hits |",
        "|---|---|---|---|",
    ]
    names = {
        0: "rank 0 - largest extent on depth",
        1: "rank 1 - middle extent on depth",
        2: "rank 2 - smallest extent on depth",
    }
    for policy_rank in POLICY_RANKS:
        summary = summaries[policy_rank]
        lines.append(
            f"| {names[policy_rank]} | {summary['mean']:.4f} | "
            f"{summary['median']:.4f} | {summary['exact_hits']}/{summary['count']} |"
        )
    lines.append(f"| uniform-random (unconstrained) | {uniform_mean:.4f} | - | - |")
    lines += [
        "",
        "## By anisotropy min(extent)/max(extent)",
        "",
        "| band | n | rank 0 | rank 1 | rank 2 |",
        "|---|---|---|---|---|",
    ]
    for low, high in ANISOTROPY_BANDS:
        band_rows = [row for row in rows if low <= row["anisotropy"] < high]
        if not band_rows:
            continue
        cells = [
            f"{policy_summary(band_rows, rank)['mean']:.4f}" for rank in POLICY_RANKS
        ]
        lines.append(
            f"| {band_label(low, high)} | {len(band_rows)} | "
            + " | ".join(cells)
            + " |"
        )
    lines += [
        "",
        "## Reference depth-axis extent rank",
        "",
        "| set | rank 0 (largest) | rank 1 (middle) | rank 2 (smallest) |",
        "|---|---|---|---|",
        f"| dev ({sum(dev_histogram)}) | "
        + " | ".join(str(count) for count in dev_histogram)
        + " |",
        f"| holdout ({sum(holdout_histogram)}) | "
        + " | ".join(str(count) for count in holdout_histogram)
        + " |",
        "",
        (
            "There is no fixed facing convention to copy: the reference depth "
            "rank is near-uniform. Rank 1 wins for two independent reasons - "
            "it is the mode of that distribution, and its two possible "
            "mistakes are middle<->largest and middle<->smallest, so it never "
            "pays the largest<->smallest swap."
        ),
        "",
        (
            "Non-determinism of a single roll is a first-order validity threat "
            "(DOI 10.1145/3697010): this simulation is deterministic, and the "
            "live confirmation on the holdout is pre-registered, single-shot, "
            "and never re-tuned (DOI 10.48550/arXiv.2507.02554)."
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
    import shape_chamfer as sc  # the scorer itself - replication, not reim.

    data_root = bench_root / "data"
    instances = read_instances(Path(arguments.instances_file))

    if arguments.generated_model:
        results_root = Path(arguments.results_root)
        if not results_root.is_absolute():
            results_root = bench_root / results_root
        return audit_generated(sc, results_root / arguments.generated_model, instances)

    rows = simulate(sc, data_root, instances)
    summaries = {rank: policy_summary(rows, rank) for rank in POLICY_RANKS}
    uniform_mean = sum(
        summaries[rank]["mean"] * UNIFORM_RANDOM_POLICY_WEIGHT for rank in POLICY_RANKS
    )
    dev_histogram = [0, 0, 0]
    for row in rows:
        dev_histogram[row["reference_depth_rank"]] += 1
    holdout_histogram = depth_rank_histogram(
        sc, data_root, read_instances(Path(arguments.holdout_file))
    )

    report = render_report(
        rows,
        summaries,
        uniform_mean,
        dev_histogram,
        holdout_histogram,
        arguments.instances_file,
    )
    out_path = Path(arguments.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(report)

    best_rank = min(POLICY_RANKS, key=lambda rank: summaries[rank]["mean"])
    if best_rank != 1:
        raise SystemExit(
            f"argmin policy is rank {best_rank}, not rank 1 - re-derive "
            "DEPTH_AXIS_EXTENT_RANK before proceeding"
        )
    if summaries[1]["mean"] > uniform_mean - POLICY_MEAN_MARGIN:
        raise SystemExit(
            f"rank 1 mean {summaries[1]['mean']:.4f} does not beat the "
            f"unconstrained mean {uniform_mean:.4f} by "
            f"{POLICY_MEAN_MARGIN}"
        )
    drift = abs(summaries[1]["mean"] - PINNED_RANK1_MEAN)
    if drift > SIMULATION_TOLERANCE:
        raise SystemExit(
            f"rank 1 mean {summaries[1]['mean']:.4f} drifted {drift:.4f} from "
            f"the pinned {PINNED_RANK1_MEAN} - the bake set moved"
        )
    print(
        f"OK rank1_mean={summaries[1]['mean']:.4f} "
        f"uniform={uniform_mean:.4f} drift={drift:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
