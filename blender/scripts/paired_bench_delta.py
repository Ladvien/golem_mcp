#!/usr/bin/env python3
"""Is a 3DCodeBench candidate a REGRESSION against the roll that set the
guard — and could this benchmark even see the improvement being asked for?

`compare_3dcode_rolls.py` answers "how far apart do two rolls of the SAME
configuration land". This answers the two questions that decide a
contract:

1. **Regression test.** Pair every instance between one baseline roll and
   the candidate's rolls, then read the mean paired difference against its
   own standard error. The guard is the BASELINE'S OWN measured mean on
   the ranking metric, computed at run time — there is no literal guard
   in this file, because a guard quoted from one roll of an axis whose
   between-roll SD is 0.0072 is the minimum of the draws taken, not an
   expected value. On this benchmark the per-instance paired SD is ~0.10,
   so a 20-instance mean carries ~0.023 of standard error and any smaller
   "movement" is a coin flip being reported as a result.
2. **Resolvable effect.** Given that measured SD, how many instance-rolls
   would it take to resolve `TARGET_RELATIVE_IMPROVEMENT` of the guard at
   2 and 3 sigma? If the answer is "more rolls than anyone will run", the
   target is a property of the instrument, not of the harness.

The ranking metric, the minimum roll count and the relative target all
come from `bench_thresholds`, which `bench_panel.py` reads too: two files
disagreeing about what "better" means is how a coin flip gets promoted.
Consumes `diagnose_3dcode.py --json` files only — it recomputes nothing a
scorer has not already produced — and shares that loader plus the
instance-set intersection with `compare_3dcode_rolls.py`, so a set
disagreement is one hard failure in one place.

Pure stdlib, so it runs under a bare `python3`:

    python3 scripts/paired_bench_delta.py --label holdout_no_regression \
      --baseline outputs/bench/diagnose_blended-deepseek-v4-pro.json \
      --candidate outputs/bench/diagnose_...-chat1.json \
                  outputs/bench/diagnose_...-chat1-roll2.json \
      --instances-file bench_sets/instances_holdout.txt
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_thresholds import (  # the pre-registered ranking rule
    MINIMUM_INSTANCES_FOR_RANKING,
    MINIMUM_PAIRED_ROLLS,
    RANKING_METRIC,
    REGRESSION_SIGMA,
    REPORTED_METRICS,
    TARGET_RELATIVE_IMPROVEMENT,
    higher_is_better,
    worsening_sign,
)
from compare_3dcode_rolls import (  # shared loader + set intersection
    load_roll,
    shared_instances,
)

# The axis the verdict is written on, and the two reported beside it: a
# move in cd_yawmin with cd_pca flat means orientation, not shape. The
# choice lives in `bench_thresholds` because `bench_panel.py` ranks on
# the same axis, and two files disagreeing about what "better" means is
# how a coin flip gets promoted.
PRIMARY_METRIC = RANKING_METRIC
ORIENTATION_METRIC = "delta_orient"
# Every table here lists the ranking metric FIRST and the reported-only
# axes after it, in the same order `bench_panel.py` uses. Column order is
# the rule for a reader who skims one table.
REPORT_METRICS = (RANKING_METRIC,) + REPORTED_METRICS
# Sample sizes are quoted at both bars, because 2 sigma is the decision
# bar and 3 sigma is what a pinned, published number should clear.
RESOLUTION_SIGMA_LEVELS = (2.0, 3.0)
MOVERS_SHOWN = 10
# A paired difference has no spread below two instances, and a mean
# delta without its standard error is exactly the mistake this tool
# exists to prevent — so one instance is refused rather than reported.
MINIMUM_PAIRED_INSTANCES = 2
OUTPUT_DIRECTORY = Path("outputs/bench")


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        required=True,
        help="diagnose JSON of the roll that set the guard.",
    )
    parser.add_argument(
        "--candidate",
        nargs="+",
        required=True,
        help="One or more diagnose JSONs of the current "
        "configuration; their per-instance mean is the "
        "candidate.",
    )
    parser.add_argument(
        "--label", required=True, help="Comparison label, used in the output filename."
    )
    parser.add_argument(
        "--instances-file",
        default="",
        help="Restrict to this instance list; every listed "
        "instance must be scoreable in every roll.",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Markdown report path (default outputs/bench/paired_delta_<label>.md)",
    )
    return parser.parse_args(argv)


def instance_mean(rolls, instance, metric) -> float:
    """One instance's metric, averaged over the rolls of one configuration."""
    return statistics.fmean(roll["per_instance"][instance][metric] for roll in rolls)


def set_mean(rolls, instances, metric) -> float:
    return statistics.fmean(
        instance_mean(rolls, instance, metric) for instance in instances
    )


def paired_delta(baseline_rolls, candidate_rolls, instances, metric) -> dict:
    """Candidate minus baseline, paired per instance.

    Pairing is the whole point: the same 20 prompts carry wildly different
    difficulty (0.008 to 0.29 on this set), so an unpaired comparison of
    two means buries the difference under between-instance variance that
    cancels exactly when instances are paired.
    """
    if len(instances) < MINIMUM_PAIRED_INSTANCES:
        raise ValueError(
            f"a paired difference needs at least "
            f"{MINIMUM_PAIRED_INSTANCES} instances to carry a standard "
            f"error; got {len(instances)}"
        )
    # Signed so that POSITIVE IS WORSE whichever way the metric points:
    # F-score rises when a candidate improves, Chamfer falls, and the
    # sign lives in `bench_thresholds` so this file and the panel cannot
    # disagree about what "better" means.
    sign = worsening_sign(metric)
    deltas = [
        sign
        * (
            instance_mean(candidate_rolls, instance, metric)
            - instance_mean(baseline_rolls, instance, metric)
        )
        for instance in instances
    ]
    mean_delta = statistics.fmean(deltas)
    paired_stdev = statistics.stdev(deltas)
    standard_error = paired_stdev / len(deltas) ** 0.5
    return {
        "metric": metric,
        "deltas": deltas,
        "mean_delta": mean_delta,
        "paired_stdev": paired_stdev,
        "standard_error": standard_error,
        "sigma": abs(mean_delta) / standard_error if standard_error else 0.0,
        "worse_count": sum(1 for delta in deltas if delta > 0),
        "better_count": sum(1 for delta in deltas if delta < 0),
        "regression": mean_delta > REGRESSION_SIGMA * standard_error,
    }


def instance_rolls_for_resolution(paired_stdev, effect, sigma) -> float:
    """How many instance-rolls resolve `effect` at `sigma`.

    Inverts SE = SD/sqrt(n): n = (sigma * SD / effect)^2. Quoted in
    instance-rolls because that is the unit that costs wall-clock —
    doubling the instance count and doubling the roll count buy the same
    resolution.
    """
    if effect <= 0:
        raise ValueError("effect must be positive to be resolvable")
    return (sigma * paired_stdev / effect) ** 2


def movers(baseline_rolls, candidate_rolls, instances, metric) -> list[dict]:
    """Per-instance deltas, biggest absolute movement first.

    Each row carries the BASELINE's own orientation error, because that is
    what distinguishes "the candidate broke this instance" from "the
    baseline happened to land this one in the reference's yaw".
    """
    rows = []
    for instance in instances:
        baseline_value = instance_mean(baseline_rolls, instance, metric)
        candidate_value = instance_mean(candidate_rolls, instance, metric)
        rows.append(
            {
                "instance": instance,
                "baseline": baseline_value,
                "candidate": candidate_value,
                "delta": candidate_value - baseline_value,
                "baseline_delta_orient": instance_mean(
                    baseline_rolls, instance, ORIENTATION_METRIC
                ),
            }
        )
    rows.sort(key=lambda row: abs(row["delta"]), reverse=True)
    return rows


def render_report(baseline_rolls, candidate_rolls, instances, arguments) -> str:
    primary = paired_delta(baseline_rolls, candidate_rolls, instances, PRIMARY_METRIC)
    # The guard is the BASELINE'S OWN MEASURED MEAN, computed here, and
    # the target is a fraction of it. The retired literals (0.0706 guard,
    # 0.060 target on cd_yawmin) came from a single roll of an axis whose
    # between-roll SD is 0.0072, so the guard was the minimum of six
    # draws being quoted as an expected value. A relative target moves
    # with the incumbent and cannot go stale.
    guard = set_mean(baseline_rolls, instances, PRIMARY_METRIC)
    effect = guard * TARGET_RELATIVE_IMPROVEMENT
    target = guard + effect if higher_is_better(PRIMARY_METRIC) else guard - effect
    baseline_names = [roll["model_dir"] for roll in baseline_rolls]
    candidate_names = [roll["model_dir"] for roll in candidate_rolls]
    scope = (
        f"the {len(instances)} instances named in `{arguments.instances_file}`"
        if arguments.instances_file
        else f"{len(instances)} shared instances"
    )
    verdict = "REGRESSION" if primary["regression"] else "no regression detected"
    lines = [
        f"# Paired bench delta — {arguments.label}",
        "",
        (
            f"Baseline `{', '.join(baseline_names)}` against candidate "
            f"`{', '.join(candidate_names)}` over {scope}. Every value read "
            f"from `diagnose_3dcode.py --json`; nothing rescored."
        ),
        "",
        (
            f"**Verdict: {verdict}** at {REGRESSION_SIGMA:.0f} sigma "
            f"one-sided on {PRIMARY_METRIC}."
        ),
        "",
        "## Set means",
        "",
        "| metric | baseline | candidate | delta |",
        "|---|---|---|---|",
    ]
    for metric in REPORT_METRICS:
        baseline_value = set_mean(baseline_rolls, instances, metric)
        candidate_value = set_mean(candidate_rolls, instances, metric)
        lines.append(
            f"| {metric} | {baseline_value:.4f} | {candidate_value:.4f} "
            f"| {candidate_value - baseline_value:+.4f} |"
        )
    lines += [
        "",
        "## Paired difference, per metric",
        "",
        (
            "| metric | mean delta (+ is worse) | paired SD | SE of the mean "
            "| sigma | worse/better |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for metric in REPORT_METRICS:
        statistics_row = paired_delta(
            baseline_rolls, candidate_rolls, instances, metric
        )
        lines.append(
            f"| {metric} | {statistics_row['mean_delta']:+.4f} "
            f"| {statistics_row['paired_stdev']:.4f} "
            f"| {statistics_row['standard_error']:.4f} "
            f"| {statistics_row['sigma']:.2f} "
            f"| {statistics_row['worse_count']}/"
            f"{statistics_row['better_count']} |"
        )
    lines += [
        "",
        f"## Biggest movers on {PRIMARY_METRIC}",
        "",
        ("| instance | baseline | candidate | delta | baseline delta_orient |"),
        "|---|---|---|---|---|",
    ]
    for row in movers(baseline_rolls, candidate_rolls, instances, PRIMARY_METRIC)[
        :MOVERS_SHOWN
    ]:
        lines.append(
            f"| {row['instance']} | {row['baseline']:.4f} "
            f"| {row['candidate']:.4f} | {row['delta']:+.4f} "
            f"| {row['baseline_delta_orient']:+.4f} |"
        )
    lines += [
        "",
        "## Could this benchmark see the target?",
        "",
        (
            f"The guard is the baseline's own measured mean on "
            f"`{PRIMARY_METRIC}`, {guard:.4f}, and the target is "
            f"{TARGET_RELATIVE_IMPROVEMENT:.0%} better than it, {target:.4f} "
            f"— an effect of {effect:.4f} against a measured paired SD of "
            f"{primary['paired_stdev']:.4f}. Neither number is a literal in "
            f"this file: a guard quoted from one roll of a noisy axis is the "
            f"minimum of the draws taken, not an expected value."
        ),
        "",
        "| requirement | instance-rolls | rolls of this set |",
        "|---|---|---|",
    ]
    for sigma in RESOLUTION_SIGMA_LEVELS:
        needed = instance_rolls_for_resolution(primary["paired_stdev"], effect, sigma)
        lines.append(
            f"| resolve {effect:.4f} at {sigma:.0f} sigma | {needed:.0f} "
            f"| {needed / len(instances):.0f} |"
        )
    # A zero standard error is a real measurement, not a division to be
    # guarded away: it means every instance moved by the same amount, so
    # the pairing removed all spread. Say that instead of crashing.
    resolution = (
        f"the target effect is "
        f"{effect / primary['standard_error']:.2f} sigma — anything under "
        f"{REGRESSION_SIGMA:.0f} is unresolvable here"
        if primary["standard_error"]
        else "the paired difference has no spread at all, so any effect "
        "this set can produce is resolvable"
    )
    lines += [
        "",
        (
            f"At the current {len(instances)} instances and "
            f"{len(candidate_rolls)} candidate roll(s), the standard error is "
            f"{primary['standard_error']:.4f}, so {resolution}."
        ),
        "",
    ]
    return "\n".join(lines)


def load_rolls(paths) -> list[dict]:
    rolls = []
    for path in paths:
        json_path = Path(path)
        if not json_path.exists():
            raise SystemExit(f"No such diagnose JSON: {json_path}")
        rolls.append(load_roll(json_path))
    return rolls


def requested_instances(instances_file: str):
    if not instances_file:
        return None
    path = Path(instances_file)
    if not path.exists():
        raise SystemExit(f"No such instance list: {path}")
    requested = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if not requested:
        raise SystemExit(f"Empty instance list: {path}")
    return requested


def refuse_underpowered(candidate_rolls) -> None:
    """A candidate that cannot be ranked is refused, not reported.

    Two ways to be unrankable, both fatal: too few rolls to average the
    per-instance orientation coin flip out, or a roll that did not cover
    the frozen set, which makes its mean incomparable to the others.
    """
    if len(candidate_rolls) < MINIMUM_PAIRED_ROLLS:
        raise SystemExit(
            f"a candidate is a mean over at least {MINIMUM_PAIRED_ROLLS} "
            f"paired rolls (MINIMUM_PAIRED_ROLLS); got "
            f"{len(candidate_rolls)}. A single-roll candidate was how "
            f"three change classes each measured flat."
        )
    for roll in candidate_rolls:
        covered = len(roll["per_instance"])
        if covered < MINIMUM_INSTANCES_FOR_RANKING:
            raise SystemExit(
                f"roll {roll['model_dir']} ({roll['path']}) scores "
                f"{covered} instances; ranking needs "
                f"{MINIMUM_INSTANCES_FOR_RANKING} "
                f"(MINIMUM_INSTANCES_FOR_RANKING)"
            )


def main(argv) -> int:
    arguments = parse_arguments(argv)
    baseline_rolls = load_rolls([arguments.baseline])
    candidate_rolls = load_rolls(arguments.candidate)
    refuse_underpowered(candidate_rolls)
    instances = shared_instances(
        baseline_rolls + candidate_rolls,
        requested_instances(arguments.instances_file),
    )
    if len(instances) < MINIMUM_PAIRED_INSTANCES:
        raise SystemExit(
            f"only {len(instances)} instance(s) scoreable in every roll; "
            f"a paired comparison needs {MINIMUM_PAIRED_INSTANCES}"
        )

    out_path = (
        Path(arguments.out)
        if arguments.out
        else OUTPUT_DIRECTORY / f"paired_delta_{arguments.label}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_report(baseline_rolls, candidate_rolls, instances, arguments)
    )
    print(f"wrote {out_path}")

    primary = paired_delta(baseline_rolls, candidate_rolls, instances, PRIMARY_METRIC)
    guard = set_mean(baseline_rolls, instances, PRIMARY_METRIC)
    print(
        f"{PRIMARY_METRIC}: baseline {guard:.4f} -> candidate "
        f"{set_mean(candidate_rolls, instances, PRIMARY_METRIC):.4f}"
    )
    print(
        f"paired mean delta {primary['mean_delta']:+.4f}  "
        f"SD {primary['paired_stdev']:.4f}  "
        f"SE {primary['standard_error']:.4f}  "
        f"{primary['sigma']:.2f} sigma  "
        f"worse/better {primary['worse_count']}/{primary['better_count']}"
    )
    print("REGRESSION" if primary["regression"] else "no regression detected")
    effect = guard * TARGET_RELATIVE_IMPROVEMENT
    for sigma in RESOLUTION_SIGMA_LEVELS:
        needed = instance_rolls_for_resolution(primary["paired_stdev"], effect, sigma)
        print(
            f"resolving {effect:.4f} at {sigma:.0f} sigma needs "
            f"{needed:.0f} instance-rolls "
            f"({needed / len(instances):.0f} rolls of {len(instances)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
