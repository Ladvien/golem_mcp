#!/usr/bin/env python3
"""The 3DCodeBench verdict as a PANEL, under a pre-registered rule.

Neither existing generator answers this. `compare_3dcode_rolls.py` answers
"what is the noise band per metric" for one configuration;
`paired_bench_delta.py` answers "is this candidate a regression against a
named baseline". Neither puts the axes side by side with an executability
gate and a written ranking rule, which is what a decision needs.

The rule is pre-registered in `bench_thresholds`, not chosen here, and it
is chosen BEFORE the next experiment on purpose. Since OT-36 the ranking
axis is F-score at `PRIMARY_FSCORE_THRESHOLD` (higher is better; see
`bench_thresholds` for the DOI and the measurement); the Chamfer history
below is why `cd_pca` rather than `cd_yawmin` is the Chamfer axis still
reported beside it. Measured over the six surviving 20-instance rolls:

    axis          mean     between-roll SD   SE of a 20-mean
    cd_yawmin     0.0769   0.0072            0.0090
    cd_pca        0.0252   0.0022            0.0018
    delta_orient  0.0517   0.0061            0.0082

`delta_orient = cd_yawmin - cd_pca` by construction
(`scripts/diagnose_3dcode.py`), and it carries 89% of cd_yawmin's
between-roll variance while being 33% of its mean. So ranking on
cd_yawmin ranks a per-instance orientation coin flip: a 15% shape gain is
2.1 sigma on cd_pca and 0.4 sigma on cd_yawmin. cd_yawmin stays on every
panel — it is the scorer's own number — but it does not rank.

Pure stdlib, so it runs under a bare `python3`:

    python3 scripts/bench_panel.py \
      --group "deepseek-v10=outputs/bench/diagnose_a.json,...json" \
      --reported-roll outputs/bench/diagnose_short.json \
      --out docs/2026-09-06-bench-panel-preregistration.md
"""

import argparse
import math
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
from compare_3dcode_rolls import load_roll, shared_instances

# Ranking metric first, then the reported-only axes: column order is the
# rule, so a reader who only looks at the table still reads it correctly.
PANEL_METRICS = (RANKING_METRIC,) + REPORTED_METRICS
# A status the benchmark's own runner considers a completed attempt.
EXECUTABLE_STATUS_PREFIX = "OK"
# Image similarity is absent for two INDEPENDENT reasons, and the panel
# states both: "the meshes are gone" would be false — every model_dir
# resolves with its glb/ present, and the reference GLBs survive too.
NOT_MEASURED_IMAGE_SIMILARITY = (
    (
        "`3dcodebench/metrics/image_similarity.py` needs `torch` and "
        "`transformers`, and neither is installed in "
        "`/Users/ladvien/3dcodebench/.venv` or `/Users/ladvien/blended/.venv`."
    ),
    (
        "No reference images exist to compare against: there is no "
        "`data/<instance>/images/` directory in the benchmark checkout, so "
        "the metric has no second operand even with the packages installed."
    ),
)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        action="append",
        required=True,
        help="LABEL=path1,path2,... — one configuration's rolls. Repeatable.",
    )
    parser.add_argument(
        "--reported-roll",
        action="append",
        default=[],
        help="A roll listed on the panel but belonging to no group: it is "
        "reported and never ranked. Repeatable.",
    )
    parser.add_argument(
        "--instances-file",
        default="",
        help="The frozen set, reported for its size only; the comparison "
        "set comes from the rolls themselves.",
    )
    parser.add_argument("--out", default="", help="Markdown path; default is stdout.")
    return parser.parse_args(argv)


def load_group(specification: str) -> dict:
    """`LABEL=path,path,...` into a group of loaded rolls."""
    if "=" not in specification:
        raise SystemExit(
            f"--group needs LABEL=path1,path2,...; got {specification!r} with no '='"
        )
    label, _, joined = specification.partition("=")
    label = label.strip()
    if not label:
        raise SystemExit(f"--group {specification!r} has an empty label")
    paths = [part.strip() for part in joined.split(",") if part.strip()]
    if not paths:
        raise SystemExit(f"--group {label} names no diagnose JSON")
    return {"label": label, "rolls": [load_json(path) for path in paths]}


def load_json(path: str) -> dict:
    json_path = Path(path)
    if not json_path.exists():
        raise SystemExit(f"No such diagnose JSON: {json_path}")
    return load_roll(json_path)


def executability(roll: dict) -> tuple[int, int]:
    """(attempts the runner completed, attempts made).

    Counted over every row, not over the scoreable ones: a run that
    produced no mesh has no metrics, so dividing by the scored rows would
    hide exactly the failure this column exists to show.
    """
    rows = roll["rows"]
    executed = sum(
        1
        for row in rows
        if str(row.get("status", "")).startswith(EXECUTABLE_STATUS_PREFIX)
    )
    return executed, len(rows)


def is_rankable(roll: dict) -> bool:
    """A roll ranks only when it attempted the whole frozen set, executed
    ALL of it, and every attempt scored.

    §P8a (docs/2026-09-04-chat-harness-plan.md): "executability 20/20 on
    every roll". Until OT-36 this checked only the scored-row count, so a
    19/20 roll whose failure happened to leave a scoreable mesh would have
    ranked; and the rule the panel enforced was weaker than the rule the
    pre-registration stated. Measured 2026-09-11: OT-27's disclosed rolls
    came back 18/20, 18/20 and 13/20, and the set is void under this rule.
    """
    executed, attempted = executability(roll)
    return (
        attempted >= MINIMUM_INSTANCES_FOR_RANKING
        and executed == attempted
        and len(roll["per_instance"]) == attempted
    )


def ranked_key(mean: float) -> float:
    """Lower is better in ranking space, whichever way the metric points."""
    return worsening_sign(RANKING_METRIC) * mean


def roll_mean(roll: dict, instances, metric: str) -> float:
    return statistics.fmean(
        roll["per_instance"][instance][metric] for instance in instances
    )


def roll_run_columns(roll: dict) -> dict:
    """Turns and seconds per instance, averaged over the rows that carry
    them. Absent in a synthetic roll, so they are optional, never faked."""
    turns = [
        row["num_turns"] for row in roll["rows"] if row.get("num_turns") is not None
    ]
    seconds = [
        row["duration_s"] for row in roll["rows"] if row.get("duration_s") is not None
    ]
    return {
        "turns": statistics.fmean(turns) if turns else None,
        "seconds": statistics.fmean(seconds) if seconds else None,
    }


def group_statistics(group: dict, instances) -> dict:
    """Every number the panel prints for one group, and nothing derived
    twice.

    The standard error is the ROLL-NOISE one: for each instance, the SD of
    its value across the group's rolls; averaged over instances and
    divided by sqrt(instances), that is the SE of a single roll's set
    mean, and dividing again by sqrt(rolls) gives the SE of the group's
    mean. Measured on the six surviving rolls it reproduces the observed
    between-roll SD (cd_yawmin 0.0090 predicted vs 0.0072 observed;
    cd_pca 0.0018 vs 0.0022), which is the cross-check that licenses it.

    VISIBILITY IS JUDGED AT THE FLOOR, not at this group's roll count.
    The question a pre-registration answers is "will this instrument see
    a target-sized improvement in the NEXT candidate", and the next
    candidate is required to have exactly MINIMUM_PAIRED_ROLLS rolls, not
    however many an incumbent happens to have accumulated. Judging at
    six rolls flatters the instrument: on cd_yawmin the same 15% target
    reads visible at 6 rolls (0.0115 vs 0.0073), barely visible at 3
    (0.0115 vs 0.0104) and invisible at 1 (0.0115 vs 0.0180). The floor
    is the only one of the three a future candidate is bound by.
    """
    rolls = [roll for roll in group["rolls"] if is_rankable(roll)]
    executed = sum(executability(roll)[0] for roll in group["rolls"])
    attempted = sum(executability(roll)[1] for roll in group["rolls"])
    axes = {}
    for metric in PANEL_METRICS:
        roll_means = [roll_mean(roll, instances, metric) for roll in rolls]
        per_instance_values = [
            [roll["per_instance"][instance][metric] for roll in rolls]
            for instance in instances
        ]
        instance_sds = [statistics.stdev(values) for values in per_instance_values]
        spans = [max(values) - min(values) for values in per_instance_values]
        standard_error_one_roll = statistics.fmean(instance_sds) / math.sqrt(
            len(instances)
        )
        standard_error = standard_error_one_roll / math.sqrt(len(rolls))
        standard_error_at_floor = standard_error_one_roll / math.sqrt(
            MINIMUM_PAIRED_ROLLS
        )
        mean = statistics.fmean(roll_means)
        target_effect = TARGET_RELATIVE_IMPROVEMENT * mean
        detectable = REGRESSION_SIGMA * standard_error_at_floor
        axes[metric] = {
            "mean": mean,
            "roll_means": roll_means,
            "between_roll_stdev": (
                statistics.stdev(roll_means) if len(roll_means) > 1 else 0.0
            ),
            "median_instance_span": statistics.median(spans),
            "mean_instance_stdev": statistics.fmean(instance_sds),
            "standard_error_one_roll": standard_error_one_roll,
            "standard_error": standard_error,
            "standard_error_at_floor": standard_error_at_floor,
            "target_effect": target_effect,
            "detectable_effect": detectable,
            "margin": target_effect / detectable if detectable else 0.0,
            "visible": target_effect >= detectable,
        }
    return {
        "label": group["label"],
        "rankable_rolls": rolls,
        "all_rolls": group["rolls"],
        "executed": executed,
        "attempted": attempted,
        "executability": executed / attempted if attempted else 0.0,
        "axes": axes,
    }


def refuse_unrankable_groups(groups) -> None:
    """A group that cannot be ranked is refused, not silently reported."""
    for group in groups:
        rankable = [roll for roll in group["rolls"] if is_rankable(roll)]
        if len(rankable) < MINIMUM_PAIRED_ROLLS:
            short = []
            for roll in group["rolls"]:
                if is_rankable(roll):
                    continue
                executed, attempted = executability(roll)
                short.append(
                    f"{roll['model_dir']} ({len(roll['per_instance'])} "
                    f"instances scored, executability {executed}/{attempted})"
                )
            raise SystemExit(
                f"group {group['label']} has {len(rankable)} rankable "
                f"roll(s); ranking needs {MINIMUM_PAIRED_ROLLS} "
                f"(MINIMUM_PAIRED_ROLLS)."
                + (f" Not rankable: {', '.join(short)}." if short else "")
            )


def group_instances(group: dict) -> list[str]:
    """The group's comparison set, or a hard failure naming the offender.

    Only the rankable rolls have to agree: a 3-instance roll passed for
    reporting is not part of any mean, so demanding it match would refuse
    the very thing the panel is asked to show.
    """
    rankable = [roll for roll in group["rolls"] if is_rankable(roll)]
    sets = [set(roll["per_instance"]) for roll in rankable]
    if len(set(map(frozenset, sets))) > 1:
        shared = set.intersection(*sets)
        for roll in rankable:
            extra = sorted(set(roll["per_instance"]) - shared)
            if extra:
                print(
                    f"INSTANCE SET MISMATCH in group {group['label']}: "
                    f"{roll['model_dir']} carries {len(extra)} instance(s) "
                    f"the others do not: {', '.join(extra)}",
                    file=sys.stderr,
                )
        raise SystemExit(
            f"rolls in group {group['label']} disagree on their instance "
            f"sets; a mean over different sets is not a comparison"
        )
    return shared_instances(rankable, None)


def render_rule(instances_file: str, frozen_size) -> list[str]:
    frozen = (
        f" The frozen set named in `{instances_file}` holds {frozen_size} instances."
        if instances_file
        else ""
    )
    return [
        "## Pre-registered rule",
        "",
        (
            f"Ranking is on **`{RANKING_METRIC}`** alone "
            f"({'higher' if higher_is_better(RANKING_METRIC) else 'lower'} is "
            f"better). `{'`, `'.join(REPORTED_METRICS)}` are reported on every "
            f"panel and rank nothing."
        ),
        "",
        (
            f"**Executability is lexicographically first.** A group whose "
            f"executability is below another's cannot rank better, however "
            f"good its `{RANKING_METRIC}` is: a configuration that declines "
            f"to produce a mesh scores nothing on the instances it skipped, "
            f"so a shape mean is only comparable between groups that "
            f"attempted the same work."
        ),
        "",
        (
            f"A candidate is a mean over at least **{MINIMUM_PAIRED_ROLLS} "
            f"paired rolls** of the same instance set, each attempting at "
            f"least **{MINIMUM_INSTANCES_FOR_RANKING} instances** and "
            f"executing **all of them** (§P8a). A roll below that instance "
            f"count, or with any failed instance, is reported and never "
            f"ranked.{frozen}"
        ),
        "",
        (
            f"The target is **relative**: "
            f"{TARGET_RELATIVE_IMPROVEMENT:.0%} better than the incumbent's "
            f"own measured mean, so it moves with the incumbent instead of "
            f"being a literal that goes stale. A regression is a one-sided "
            f"move of more than **{REGRESSION_SIGMA:.0f} sigma** on the "
            f"ranking metric's standard error."
        ),
        "",
    ]


def render_rolls(rows) -> list[str]:
    header = (
        "| roll | n | exec_ok | "
        + " | ".join(
            metric if metric == RANKING_METRIC else f"{metric} (reported)"
            for metric in PANEL_METRICS
        )
        + " | turns | sec/inst |"
    )
    lines = ["## Rolls", "", header, "|" + "---|" * (5 + len(PANEL_METRICS))]
    lines.extend(rows)
    lines.append("")
    return lines


def roll_row(roll: dict, instances) -> str:
    executed, attempted = executability(roll)
    run = roll_run_columns(roll)
    name = roll["model_dir"]
    if not is_rankable(roll):
        name = f"{name} (not ranked)"
        scope = sorted(roll["per_instance"])
    else:
        scope = instances
    cells = [
        f"{roll_mean(roll, scope, metric):.4f}" if scope else "—"
        for metric in PANEL_METRICS
    ]
    turns = f"{run['turns']:.1f}" if run["turns"] is not None else "—"
    seconds = f"{run['seconds']:.0f}" if run["seconds"] is not None else "—"
    return (
        f"| {name} | {len(roll['per_instance'])} | "
        f"{executed}/{attempted} | " + " | ".join(cells) + f" | {turns} | {seconds} |"
    )


def render_groups(statistics_rows) -> list[str]:
    """Groups in RANKED order: executability first, then the ranking
    metric in its own direction. The order is the rule being applied, not
    described."""
    ranked = sorted(
        statistics_rows,
        key=lambda row: (
            -row["executability"],
            ranked_key(row["axes"][RANKING_METRIC]["mean"]),
        ),
    )
    lines = [
        "## Groups",
        "",
        (
            "| rank | group | rolls | exec | "
            + " | ".join(PANEL_METRICS)
            + f" | SE({RANKING_METRIC}) |"
        ),
        "|" + "---|" * (5 + len(PANEL_METRICS)),
    ]
    for position, row in enumerate(ranked, 1):
        cells = " | ".join(
            f"{row['axes'][metric]['mean']:.4f}" for metric in PANEL_METRICS
        )
        lines.append(
            f"| {position} | {row['label']} | {len(row['rankable_rolls'])} | "
            f"{row['executed']}/{row['attempted']} | {cells} | "
            f"{row['axes'][RANKING_METRIC]['standard_error']:.4f} |"
        )
    lines.append("")
    return lines


def render_power(statistics_rows) -> list[str]:
    lines = [
        "## Power",
        "",
        (
            f"The detectable effect is quoted at the RULE'S FLOOR of "
            f"{MINIMUM_PAIRED_ROLLS} rolls, not at the roll count an "
            f"incumbent happens to have: a future candidate is bound by the "
            f"floor, so a verdict computed on six accumulated rolls would "
            f"promise resolution nobody has to buy. The group's own SE is "
            f"printed beside it."
        ),
        "",
    ]
    for row in statistics_rows:
        rolls = len(row["rankable_rolls"])
        lines += [
            f"### {row['label']} — {rolls} ranking-eligible rolls",
            "",
            (
                "| axis | mean | median per-instance span | mean per-instance "
                "SD | SE of a 20-mean | SE of the "
                f"{rolls}-roll mean | SE at the {MINIMUM_PAIRED_ROLLS}-roll "
                f"floor | target ({TARGET_RELATIVE_IMPROVEMENT:.0%}) "
                f"| detectable at {REGRESSION_SIGMA:.0f}σ | margin |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for metric in PANEL_METRICS:
            axis = row["axes"][metric]
            lines.append(
                f"| {metric} | {axis['mean']:.4f} "
                f"| {axis['median_instance_span']:.4f} "
                f"| {axis['mean_instance_stdev']:.4f} "
                f"| {axis['standard_error_one_roll']:.4f} "
                f"| {axis['standard_error']:.4f} "
                f"| {axis['standard_error_at_floor']:.4f} "
                f"| {axis['target_effect']:.4f} "
                f"| {axis['detectable_effect']:.4f} "
                f"| {axis['margin']:.2f}x |"
            )
        lines.append("")
        for metric in PANEL_METRICS:
            axis = row["axes"][metric]
            if axis["visible"]:
                lines.append(
                    f"- `{metric}`: **visible** — a "
                    f"{TARGET_RELATIVE_IMPROVEMENT:.0%} improvement is "
                    f"{axis['target_effect']:.4f}, at or above the "
                    f"{REGRESSION_SIGMA:.0f}σ detectable effect of "
                    f"{axis['detectable_effect']:.4f} "
                    f"({axis['margin']:.2f}x)."
                )
            else:
                lines.append(
                    f"- `{metric}`: **below the instrument's resolution** — "
                    f"a {TARGET_RELATIVE_IMPROVEMENT:.0%} improvement is "
                    f"{axis['target_effect']:.4f} against a "
                    f"{REGRESSION_SIGMA:.0f}σ detectable effect of "
                    f"{axis['detectable_effect']:.4f} "
                    f"({axis['margin']:.2f}x)."
                )
        lines.append("")
    return lines


def render_not_measured() -> list[str]:
    lines = [
        "## Not measured",
        "",
        "**Image similarity.** Absent for two independent reasons:",
        "",
    ]
    lines += [
        f"{index}. {reason}"
        for index, reason in enumerate(NOT_MEASURED_IMAGE_SIMILARITY, 1)
    ]
    lines += [
        "",
        (
            "The generated meshes are NOT gone: every `model_dir` above "
            "resolves with its `glb/<instance>.glb` present, and the reference "
            "GLBs survive under `data/<instance>/glb/`. So the axis is missing "
            "its packages and its reference images, not its geometry."
        ),
        "",
        (
            "**Requirement on the next roll:** retain `glb/` and `renders/`. "
            "With both kept, image similarity can be added to this panel "
            "without re-running a single instance; discard them and the axis "
            "costs a full sweep to recover."
        ),
        "",
    ]
    return lines


def render_panel(groups, reported_rolls, arguments, frozen_size) -> str:
    statistics_rows = []
    roll_rows = []
    for group in groups:
        instances = group_instances(group)
        statistics_rows.append(group_statistics(group, instances))
        for roll in group["rolls"]:
            roll_rows.append(roll_row(roll, instances))
    for roll in reported_rolls:
        roll_rows.append(roll_row(roll, sorted(roll["per_instance"])))

    labels = ", ".join(group["label"] for group in groups)
    lines = [f"# Bench panel — {labels}", ""]
    lines += render_rule(arguments.instances_file, frozen_size)
    lines += render_rolls(roll_rows)
    lines += render_groups(statistics_rows)
    lines += render_power(statistics_rows)
    lines += render_not_measured()
    return "\n".join(lines)


def frozen_set_size(instances_file: str):
    if not instances_file:
        return None
    path = Path(instances_file)
    if not path.exists():
        raise SystemExit(f"No such instance list: {path}")
    return len([line for line in path.read_text().splitlines() if line.strip()])


def main(argv) -> int:
    arguments = parse_arguments(argv)
    groups = [load_group(specification) for specification in arguments.group]
    refuse_unrankable_groups(groups)
    reported_rolls = [load_json(path) for path in arguments.reported_roll]
    panel = render_panel(
        groups,
        reported_rolls,
        arguments,
        frozen_set_size(arguments.instances_file),
    )
    if arguments.out:
        out_path = Path(arguments.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(panel)
        print(f"wrote {out_path}")
    else:
        print(panel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
