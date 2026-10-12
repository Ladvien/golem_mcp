#!/usr/bin/env python3
"""Per-instance 3DCodeBench chamfer diagnostic for one blended model row.

Replicates the scorer's numbers by IMPORTING its own functions
(<bench>/metrics/shape_chamfer.py) rather than reimplementing them, adds a
diagnostic-only `cd_pca` (best alignment over the 24-rotation PCA frame ->
covers pitch/roll/axis swaps the yaw-only scorer cannot see), and reports the
per-instance gap `Δ_orient = cd_yawmin - cd_pca`, and — since OT-36 — the
F-score, precision and recall at `PRIMARY_FSCORE_THRESHOLD` on the same
aligned cloud (`bench_surface_metrics`, DOI 10.1109/cvpr.2019.00352), which
is what `bench_panel.py` ranks on:

    ≈ 0            -> true shape mismatch (orientation is not the problem)
    >= 0.02        -> orientation artifact (shape is fine, placement is not)

Runs under the bench venv (needs trimesh + numpy + scipy; no Blender).

    /Users/ladvien/3dcodebench/.venv/bin/python scripts/diagnose_3dcode.py \
        --bench-root /Users/ladvien/3dcodebench \
        --model-dir blended-deepseek-v4-pro \
        --instances-file /Users/ladvien/3dcodebench/instances_v1.txt \
        --out docs/research/3dcodebench/3dcode_diagnose_v1.md

The script asserts, before any data is trusted, that its per-instance
cd_yawmin matches <model_dir>/_metrics/shape_chamfer.json for every instance
present in both, and runs an in-memory self-test of cd_pca (non-zero exit on
failure).
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_surface_metrics import (  # ONE alignment search, ONE F-score (OT-36)
    best_pca_alignment,
    cd_pca,
    surface_columns,
)
from bench_thresholds import (  # shared, stdlib-only
    ORIENT_ARTIFACT_THRESHOLD,
    PRIMARY_FSCORE_THRESHOLD,
    RANKING_METRIC,
    REPORTED_METRICS,
)

# Every metric a diagnose row carries and the panel may rank or report.
ROW_METRICS = (RANKING_METRIC,) + REPORTED_METRICS

DIAGNOSTIC_N_POINTS = 8192  # scorer default --n-points
DIAGNOSTIC_SEED = 0  # scorer default --seed
THIN_RATIO = 0.3  # min_extent/max_extent below this -> flat
ORIENT_WORDS = ("standing", "vertical", "flat", "horizontal", "upright", "facing")
QUANTITY_RE = re.compile(r"\d")


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
        "--instances-file", required=True, help="Frozen instance list for the report"
    )
    parser.add_argument("--out", required=True, help="Markdown report path")
    parser.add_argument(
        "--json", default="", help="Also write per-instance rows as JSON."
    )
    return parser.parse_args(argv)


def self_test(sc):
    """Assert cd_pca is frame alignment, not a no-op. Non-zero exit on fail.

    Shape: two icospheres along one axis (asymmetric, elongated). Rotating
    that shape 90 deg about Y is exactly what the yaw-only scorer cannot
    absorb: cd_yawmin must blow up while cd_pca recovers the identity.
    """
    import trimesh

    body = trimesh.creation.icosphere(subdivisions=3, radius=0.22)
    lobe = trimesh.creation.icosphere(subdivisions=3, radius=0.22)
    lobe.apply_translation([0.0, 0.0, 1.35])
    shape = trimesh.util.concatenate([body, lobe])

    sample, _ = trimesh.sample.sample_surface(shape, DIAGNOSTIC_N_POINTS, seed=7)
    pts = sc.normalize_unit_sphere(np.asarray(sample, dtype=np.float64))

    cos, sin = np.cos(np.pi / 2), np.sin(np.pi / 2)
    rot_y = np.array([[cos, 0.0, sin], [0.0, 1.0, 0.0], [-sin, 0.0, cos]])
    rotated = pts @ rot_y.T
    rotated = sc.normalize_unit_sphere(rotated)

    identity_ok = cd_pca(sc, pts, pts) < 1e-6
    recovery_ok = cd_pca(sc, pts, rotated) < 1e-6
    _, yaw_min, _, _ = sc.chamfer_with_yaw(pts, rotated)
    blindspot_ok = yaw_min > 0.5

    print(
        f"self-test: cd_pca(S,S)={cd_pca(sc, pts, pts):.3e} "
        f"cd_pca(S,Ry90 S)={cd_pca(sc, pts, rotated):.3e} "
        f"cd_yawmin(S,Ry90 S)={yaw_min:.4f}"
    )
    checks = (
        ("cd_pca(S, S) < 1e-6", identity_ok),
        ("cd_pca(S, Ry90(S)) < 1e-6", recovery_ok),
        ("cd_yawmin(S, Ry90(S)) > 0.5", blindspot_ok),
    )
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    return all(ok for _, ok in checks)


def brief_anatomy(text):
    """Word count, quantitative-spec and orientation-vocabulary flags."""
    words = text.split()
    return {
        "words": len(words),
        "quantitative": bool(QUANTITY_RE.search(text)),
        "orientation": tuple(w for w in ORIENT_WORDS if w in text.lower()),
    }


def agent_meta(directory):
    path = directory / ".agent_meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def dominant_factor(delta_orient, anatomy):
    """Mechanical classification of where an instance's chamfer comes from."""
    if delta_orient >= ORIENT_ARTIFACT_THRESHOLD:
        return "orientation-artifact"
    if not anatomy["quantitative"] and not anatomy["orientation"]:
        return "brief-ambiguity"
    return "shape-mismatch"


# The GLBs are glTF (Y-up): glTF X = Blender X, glTF Y = Blender Z (up),
# glTF Z = -Blender Y (depth). The label names both frames so a "majority
# thin axis" is never read in the wrong one.
AXIS_NAMES = (
    "glTF X (Blender X)",
    "glTF Y (Blender Z, up)",
    "glTF Z (Blender -Y, depth)",
)


def reference_thin_axis_histogram(sc, data_root, instances):
    """Thin-axis histogram over the benchmark's own baked reference GLBs.

    For every reference with min extent < 0.3 x max extent, which axis
    attains the minimum. Informs the task-brief placement clause; never read
    by any scorer.
    """
    import trimesh

    histogram = {axis: 0 for axis in AXIS_NAMES}
    thin = 0
    total = 0
    for instance in instances:
        glb = data_root / instance / "glb" / f"{instance}.glb"
        if not glb.exists():
            continue
        points, _ = trimesh.sample.sample_surface(
            trimesh.load(glb, force="mesh"), 2048, seed=0
        )
        extents = np.ptp(np.asarray(points), axis=0)
        total += 1
        smallest = float(extents.min())
        if smallest < THIN_RATIO * float(extents.max()):
            thin += 1
            histogram[AXIS_NAMES[int(np.argmin(extents))]] += 1
    return {"total": total, "thin": thin, "axes": histogram}


def instance_geometry(glb_path, sc):
    """World-space extents / thinness / centroid, or None."""
    if not glb_path.exists():
        return None
    try:
        mesh = trimesh.load(glb_path, force="mesh")
    except Exception:  # noqa: BLE001 — an unloadable GLB is reported as unscoreable
        return None
    if mesh.is_empty or mesh.faces is None or len(mesh.faces) == 0:
        return None
    extents = np.asarray(mesh.extents, dtype=np.float64)
    return {
        "extents": extents,
        "thinness": float(extents.min() / extents.max()) if extents.max() else 1.0,
        "centroid": np.asarray(mesh.centroid, dtype=np.float64),
    }


def main(argv) -> int:
    args = parse_arguments(argv)

    bench_root = Path(args.bench_root).resolve()
    metrics_dir = bench_root / "metrics"
    if not metrics_dir.is_dir():
        raise SystemExit(f"No metrics dir under {bench_root}")
    sys.path.insert(0, str(metrics_dir))
    import shape_chamfer as sc  # the scorer itself — replication, not reim.

    results_root = Path(args.results_root)
    if not results_root.is_absolute():
        results_root = bench_root / results_root
    model_dir = results_root / args.model_dir
    data_root = bench_root / "data"

    instances = [
        line.strip()
        for line in Path(args.instances_file).read_text().splitlines()
        if line.strip()
    ]

    # ---- self-test BEFORE any reported data is trusted -----------------
    if not self_test(sc):
        raise SystemExit("self-test FAILED — refusing to emit a report")

    # ---- load the scorer's own per-instance numbers --------------------
    metrics_path = model_dir / "_metrics" / "shape_chamfer.json"
    scored = {}
    if metrics_path.exists():
        for row in json.loads(metrics_path.read_text())["per_instance"]:
            scored[row["instance"]] = row

    # ---- replicate cd per instance (scorer's RNG stream: seed 0, ref
    # sampled first, then gen, one rng.integers draw per sample call) -----
    rng = np.random.default_rng(DIAGNOSTIC_SEED)
    rows = []
    mismatched = []
    for instance in instances:
        meta = agent_meta(model_dir / instance) or {}
        anatomy = brief_anatomy(
            (data_root / instance / "prompt_description.txt").read_text()
            if (data_root / instance / "prompt_description.txt").exists()
            else ""
        )
        ref_geo = instance_geometry(
            data_root / instance / "glb" / f"{instance}.glb", sc
        )
        gen_geo = instance_geometry(
            model_dir / instance / "glb" / f"{instance}.glb", sc
        )

        row = {
            "instance": instance,
            "cd_yawmin": None,
            "cd_yawmin_scored": (scored.get(instance) or {}).get("cd_yawmin"),
            "cd_pca": None,
            "delta_orient": None,
            **{
                metric: None
                for metric in ROW_METRICS
                if metric not in ("cd_yawmin", "cd_pca", "delta_orient")
            },
            "thin_gen": gen_geo["thinness"] if gen_geo else None,
            "thin_ref": ref_geo["thinness"] if ref_geo else None,
            "anatomy": anatomy,
            "status": meta.get("status"),
            "num_turns": meta.get("num_turns"),
            "max_tool_calls": meta.get("max_tool_calls"),
            "duration_s": meta.get("duration_s"),
            "code_chars": meta.get("code_chars"),
            "n_chunks_included": meta.get("n_chunks_included"),
            "n_chunks_excluded": meta.get("n_chunks_excluded"),
        }

        if ref_geo is None or gen_geo is None:
            rows.append(row)
            continue

        ref_pts = sc.load_mesh_points(
            data_root / instance / "glb" / f"{instance}.glb", DIAGNOSTIC_N_POINTS, rng
        )
        gen_pts = sc.load_mesh_points(
            model_dir / instance / "glb" / f"{instance}.glb", DIAGNOSTIC_N_POINTS, rng
        )
        if ref_pts is None or gen_pts is None:
            rows.append(row)
            continue

        ref_pts = sc.normalize_unit_sphere(ref_pts)
        gen_pts = sc.normalize_unit_sphere(gen_pts)
        _, cd_yaw_min, _, _ = sc.chamfer_with_yaw(ref_pts, gen_pts)
        rotation, cd_pca_value = best_pca_alignment(sc, ref_pts, gen_pts)

        row["cd_yawmin"] = cd_yaw_min
        row["cd_pca"] = cd_pca_value
        row["delta_orient"] = cd_yaw_min - cd_pca_value
        # F-score, precision and recall on the SAME aligned cloud cd_pca
        # was measured on (OT-36): the ranking axis and the reported
        # Chamfer answer one question about one pose.
        row.update(
            surface_columns(ref_pts, gen_pts @ rotation.T, PRIMARY_FSCORE_THRESHOLD)
        )
        scored_value = row["cd_yawmin_scored"]
        if scored_value is not None and abs(scored_value - cd_yaw_min) > 1e-9:
            mismatched.append((instance, scored_value, cd_yaw_min))
        rows.append(row)

    if mismatched:
        for instance, expected, got in mismatched:
            print(
                f"REPLICATION MISMATCH {instance}: "
                f"scorer={expected!r} replicate={got!r}",
                file=sys.stderr,
            )
        raise SystemExit("cd_yawmin does not reproduce the scorer's output")
    replicated = sum(
        1
        for r in rows
        if r["cd_yawmin_scored"] is not None and r["cd_yawmin"] is not None
    )
    print(
        f"replication: {replicated}/{len(instances)} instances match "
        f"the scorer's per-instance cd_yawmin exactly"
    )

    # ---- benchmark placement prior -------------------------------------
    prior = reference_thin_axis_histogram(sc, data_root, instances)

    # ---- report ---------------------------------------------------------
    report_order = sorted(
        (r for r in rows if r["cd_yawmin"] is not None),
        key=lambda r: r["cd_yawmin"],
        reverse=True,
    )
    report_order += [r for r in rows if r["cd_yawmin"] is None]

    lines = [
        f"# 3DCodeBench diagnostic — {args.model_dir}",
        "",
        (
            f"Replication: `{sc.__file__}` imported unmodified; "
            f"{replicated} instance cd_yawmin values asserted equal to "
            f"`_metrics/shape_chamfer.json`."
        ),
        "",
        "## Per-instance (sorted by cd_yawmin descending)",
        "",
        (
            f"| instance | {RANKING_METRIC} | cd_yawmin | cd_pca | Δ_orient | verdict "
            "| thin_gen | thin_ref | brief(words/quant/orient) | turns | dur_s |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report_order:
        if r["cd_yawmin"] is None:
            lines.append(
                f"| {r['instance']} | — | — | — | — | unscoreable | "
                f"{r['thin_gen']} | {r['thin_ref']} | "
                f"{r['anatomy']['words']}/"
                f"{'q' if r['anatomy']['quantitative'] else '-'}/"
                f"{''.join(w[:3] for w in r['anatomy']['orientation']) or '-'}"
                f" | {r['num_turns']} | {r['duration_s']} |"
            )
            continue
        verdict = dominant_factor(r["delta_orient"], r["anatomy"])
        lines.append(
            f"| {r['instance']} | {r[RANKING_METRIC]:.4f} | "
            f"{r['cd_yawmin']:.4f} | {r['cd_pca']:.4f} | "
            f"{r['delta_orient']:+.4f} | {verdict} | "
            f"{r['thin_gen']:.2f} | {r['thin_ref']:.2f} | "
            f"{r['anatomy']['words']}/"
            f"{'q' if r['anatomy']['quantitative'] else '-'}/"
            f"{''.join(w[:3] for w in r['anatomy']['orientation']) or '-'}"
            f" | {r['num_turns']} | {r['duration_s']} |"
        )

    artifact_rows = [
        r
        for r in report_order
        if r["delta_orient"] is not None
        and r["delta_orient"] >= ORIENT_ARTIFACT_THRESHOLD
    ]
    lines += [
        "",
        f"Orientation artifacts (Δ_orient >= {ORIENT_ARTIFACT_THRESHOLD}): "
        f"{len(artifact_rows)} — "
        + (
            ", ".join(
                f"{r['instance']} (Δ={r['delta_orient']:+.3f})" for r in artifact_rows
            )
            or "none"
        ),
        "",
        (
            f"## Reference thin-axis prior ({prior['total']} baked refs, "
            f"{prior['thin']} thin at <{THIN_RATIO:.1f} max-extent)"
        ),
        "",
    ]
    if prior["thin"]:
        axis_lines = ", ".join(
            f"{axis}: {count} ({100.0 * count / prior['thin']:.0f}%)"
            for axis, count in prior["axes"].items()
        )
        lines.append(axis_lines)
        majority = max(prior["axes"], key=prior["axes"].get)
        if prior["axes"][majority] * 2 > prior["thin"]:
            lines.append(f"Majority thin axis: **{majority}**")
        else:
            lines.append("No majority thin axis (>50% of thin references).")
    else:
        lines.append("No thin references in this subset.")

    turns = [r["num_turns"] for r in rows if r["num_turns"] is not None]
    caps = {r["max_tool_calls"] for r in rows if r["max_tool_calls"]}
    durations = [r["duration_s"] for r in rows if r["duration_s"]]
    lines += [
        "",
        "## Budget",
        "",
        f"- instances with meta: {len(turns)}/{len(instances)}",
        f"- tool-call cap(s) seen: {sorted(caps) or '—'}",
        # A model dir with no `.agent_meta.json` at all is legitimate:
        # the raw-bpy arms of the fine-tune decision experiment write a
        # script and nothing else. An empty list is reported as such,
        # never divided by.
        (f"- turns: mean {sum(turns) / len(turns):.1f}")
        if turns
        else "- turns: — (no meta)",
        (
            f"- max turns: {max(turns) if turns else '—'}"
            f", turns>=20: {sum(1 for t in turns if t >= 20)}"
        ),
        (f"- excluded chunks: {sum(r['n_chunks_excluded'] or 0 for r in rows)} total"),
        (f"- mean duration: {sum(durations) / len(durations):.1f}s")
        if durations
        else "- mean duration: —",
        "",
        "## Self-test",
        "",
        (
            "cd_pca(S,S) < 1e-6; cd_pca(S, Ry90(S)) < 1e-6; "
            "cd_yawmin(S, Ry90(S)) > 0.5 — all asserted before this report was "
            "written."
        ),
    ]

    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")

    if args.json:
        scoreable = [r for r in rows if r["cd_yawmin"] is not None]
        document = {
            "model_dir": args.model_dir,
            "instances_file": args.instances_file,
            "n_points": DIAGNOSTIC_N_POINTS,
            "seed": DIAGNOSTIC_SEED,
            "per_instance": [
                {
                    "instance": r["instance"],
                    **{metric: r[metric] for metric in ROW_METRICS},
                    "status": r["status"],
                    "num_turns": r["num_turns"],
                    "duration_s": r["duration_s"],
                }
                for r in rows
            ],
            "means": {
                key: (
                    sum(r[key] for r in scoreable) / len(scoreable)
                    if scoreable
                    else None
                )
                for key in ROW_METRICS
            }
            | {"n": len(scoreable)},
        }
        Path(args.json).write_text(json.dumps(document, indent=2) + "\n")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
