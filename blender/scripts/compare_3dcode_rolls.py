#!/usr/bin/env python3
"""Turn repeated 3DCodeBench rolls of one configuration into a noise band.

Consumes the JSON files written by `scripts/diagnose_3dcode.py --json` — it
computes nothing a scorer has not already produced — and answers the only
question that makes a harness iteration decidable: how far apart do two
rolls of the *same* configuration land?

Headline output, per metric: the standard deviation and the range of the
per-roll instance-set means. A future iteration's target must clear the
measured floor by at least that SD, or the result is unreadable.

Instances are intersected across the input files: a mean computed over
different instance sets is not a noise measurement, so a disagreement is a
hard failure rather than a silent re-base.

Pure stdlib (no numpy, no trimesh), so it runs under a bare `python3`:

    python3 scripts/compare_3dcode_rolls.py --label iter3_3rolls \
      --json outputs/bench/diagnose_a.json outputs/bench/diagnose_b.json
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_thresholds import (  # shared, stdlib-only
    ORIENT_ARTIFACT_THRESHOLD,
    RANKING_METRIC,
    REPORTED_METRICS,
)

# Every metric the panel ranks or reports, ranking axis first. A row that
# lacks any of them is unscoreable for the panel, and a diagnose JSON
# written before OT-36 (no F-score columns) has to be re-diagnosed — the
# GLBs are retained for exactly that (BEN-9).
NOISE_METRICS = (RANKING_METRIC,) + REPORTED_METRICS
MINIMUM_ROLLS = 2  # a paired difference needs two rolls; an
# SD of the roll means needs three
OUTPUT_DIRECTORY = Path("outputs/bench")


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        nargs="+",
        required=True,
        help="Two or more diagnose_3dcode --json files, in roll order.",
    )
    parser.add_argument(
        "--label", required=True, help="Comparison label, used in the output filename."
    )
    parser.add_argument(
        "--out",
        default="",
        help="Markdown report path (default outputs/bench/roll_noise_<label>.md)",
    )
    parser.add_argument(
        "--instances-file",
        default="",
        help="Restrict the comparison to this instance list. "
        "Required when the rolls were diagnosed over "
        "different lists (e.g. a 20-instance roll "
        "against 3-instance repeats); every listed "
        "instance must be scoreable in every roll.",
    )
    return parser.parse_args(argv)


def load_roll(path: Path) -> dict:
    """One roll: its model dir, its scoreable metrics, and its raw rows.

    `per_instance` holds only rows a scorer produced every metric for,
    because a mean over partially-scored rows is not a mean. `rows` keeps
    EVERY row, including the unscoreable ones: executability is a
    property of the whole attempt set, and reading it from `per_instance`
    would silently divide by the instances that scored — the one subset
    guaranteed to look healthy.
    """
    document = json.loads(path.read_text())
    per_instance = {}
    for row in document["per_instance"]:
        if any(row.get(metric) is None for metric in NOISE_METRICS):
            continue
        per_instance[row["instance"]] = {
            metric: float(row[metric]) for metric in NOISE_METRICS
        }
    return {
        "path": str(path),
        "model_dir": document.get("model_dir", path.stem),
        "instances_file": document.get("instances_file", ""),
        "per_instance": per_instance,
        "rows": tuple(document["per_instance"]),
    }


def shared_instances(rolls: list[dict], requested: list[str] | None) -> list[str]:
    """The comparison set, or a hard failure naming every disagreement.

    Without `requested` the rolls must agree exactly: a mean computed over
    different instance sets is not a noise measurement. With `requested` the
    caller has named the set on purpose, and every roll must cover it.
    """
    sets = [set(roll["per_instance"]) for roll in rolls]
    if requested is not None:
        wanted = set(requested)
        uncovered = [
            instance for instance in requested if any(instance not in s for s in sets)
        ]
        if uncovered:
            for instance in uncovered:
                absent = [
                    roll["model_dir"]
                    for roll in rolls
                    if instance not in roll["per_instance"]
                ]
                print(
                    f"REQUESTED INSTANCE UNSCOREABLE {instance}: absent "
                    f"from {', '.join(absent)}",
                    file=sys.stderr,
                )
            raise SystemExit(
                "the requested instance list is not scoreable in every roll"
            )
        return sorted(wanted)
    shared = set.intersection(*sets)
    union = set.union(*sets)
    missing = union - shared
    if missing:
        for instance in sorted(missing):
            absent = [
                roll["model_dir"]
                for roll in rolls
                if instance not in roll["per_instance"]
            ]
            print(
                f"INSTANCE SET MISMATCH {instance}: scoreable in "
                f"{len(rolls) - len(absent)}/{len(rolls)} rolls, absent "
                f"from {', '.join(absent)}",
                file=sys.stderr,
            )
        print(
            f"shared instances: {len(shared)}; excluded: {len(missing)}",
            file=sys.stderr,
        )
        raise SystemExit(
            "rolls disagree on their instance sets — pass "
            "--instances-file to compare a named shared set"
        )
    return sorted(shared)


def per_instance_statistics(rolls, instances, metric) -> list[dict]:
    rows = []
    for instance in instances:
        values = [roll["per_instance"][instance][metric] for roll in rolls]
        rows.append(
            {
                "instance": instance,
                "values": values,
                "mean": statistics.fmean(values),
                "stdev": statistics.stdev(values),
                "range": max(values) - min(values),
            }
        )
    return rows


def roll_mean_statistics(rolls, instances, metric) -> dict:
    """Per-roll instance-set mean, plus the SD and range of those means.

    `statistics.stdev` is the sample SD, so it is defined from two rolls on
    (where it degenerates to range/sqrt(2) and carries one degree of
    freedom); three rolls is the first honest spread.
    """
    means = [
        statistics.fmean(
            roll["per_instance"][instance][metric] for instance in instances
        )
        for roll in rolls
    ]
    return {
        "means": means,
        "stdev": statistics.stdev(means),
        "range": max(means) - min(means),
    }


def render_report(rolls, instances, label, instances_file) -> str:
    roll_names = [roll["model_dir"] for roll in rolls]
    scope = (
        f"the {len(instances)} instances named in `{instances_file}`"
        if instances_file
        else f"{len(instances)} shared instances"
    )
    lines = [
        f"# Roll-to-roll noise — {label}",
        "",
        (
            f"{len(rolls)} rolls of one configuration over {scope}; every value "
            f"read from `diagnose_3dcode.py --json` output, nothing "
            f"recomputed."
        ),
        "",
        "Rolls, in order:",
        "",
    ]
    lines += [f"- `{roll['model_dir']}` — `{roll['path']}`" for roll in rolls]

    summary = {}
    for metric in NOISE_METRICS:
        rows = per_instance_statistics(rolls, instances, metric)
        summary[metric] = roll_mean_statistics(rolls, instances, metric)
        unstable = [row for row in rows if row["range"] >= ORIENT_ARTIFACT_THRESHOLD]
        lines += [
            "",
            f"## {metric}",
            "",
            "| instance | " + " | ".join(roll_names) + " | mean | SD | range |",
            "|---" * (len(roll_names) + 4) + "|",
        ]
        for row in sorted(rows, key=lambda r: r["range"], reverse=True):
            lines.append(
                f"| {row['instance']} | "
                + " | ".join(f"{value:.4f}" for value in row["values"])
                + f" | {row['mean']:.4f} | {row['stdev']:.4f} "
                f"| {row['range']:.4f} |"
            )
        lines += [
            "",
            (
                f"Instances whose across-roll range reaches "
                f"{ORIENT_ARTIFACT_THRESHOLD}: {len(unstable)}/{len(instances)}"
                + (
                    " — "
                    + ", ".join(
                        f"{row['instance']} ({row['range']:.4f})" for row in unstable
                    )
                    if unstable
                    else ""
                )
            ),
        ]

    lines += [
        "",
        "## Roll means",
        "",
        "| metric | " + " | ".join(roll_names) + " | SD of roll means "
        "| range of roll means |",
        "|---" * (len(roll_names) + 3) + "|",
    ]
    for metric in NOISE_METRICS:
        stats = summary[metric]
        lines.append(
            f"| {metric} | "
            + " | ".join(f"{value:.4f}" for value in stats["means"])
            + f" | {stats['stdev']:.4f} | {stats['range']:.4f} |"
        )

    lines.append("")
    for metric in NOISE_METRICS:
        stats = summary[metric]
        lines.append(
            f"noise band for the {len(instances)}-instance mean of "
            f"{metric}: SD {stats['stdev']:.4f}, range "
            f"{stats['range']:.4f} over {len(rolls)} rolls of an identical "
            f"configuration"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    if len(arguments.json) < MINIMUM_ROLLS:
        raise SystemExit(
            f"need at least {MINIMUM_ROLLS} --json files to "
            f"measure noise, got {len(arguments.json)}"
        )

    rolls = []
    for path in arguments.json:
        json_path = Path(path)
        if not json_path.exists():
            raise SystemExit(f"No such diagnose JSON: {json_path}")
        rolls.append(load_roll(json_path))

    requested = None
    if arguments.instances_file:
        requested_path = Path(arguments.instances_file)
        if not requested_path.exists():
            raise SystemExit(f"No such instance list: {requested_path}")
        requested = [
            line.strip()
            for line in requested_path.read_text().splitlines()
            if line.strip()
        ]
        if not requested:
            raise SystemExit(f"Empty instance list: {requested_path}")
    instances = shared_instances(rolls, requested)
    if not instances:
        raise SystemExit("no instance is scoreable in every roll")

    out_path = (
        Path(arguments.out)
        if arguments.out
        else OUTPUT_DIRECTORY / f"roll_noise_{arguments.label}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_report(rolls, instances, arguments.label, arguments.instances_file)
    )
    print(f"wrote {out_path}")
    for metric in NOISE_METRICS:
        stats = roll_mean_statistics(rolls, instances, metric)
        print(
            f"{metric}: roll means "
            + ", ".join(f"{value:.4f}" for value in stats["means"])
            + f"  SD {stats['stdev']:.4f}  range {stats['range']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
