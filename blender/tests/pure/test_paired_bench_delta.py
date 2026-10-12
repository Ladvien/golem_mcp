"""The bench regression test's own statistics.

`scripts/paired_bench_delta.py` is what decides whether a 3DCodeBench
candidate regressed against the roll that set the guard, and whether the
contract's target is resolvable at all. Those numbers are load-bearing —
they are the difference between "this change helped" and "this change
landed inside a coin flip" — so the arithmetic is pinned here on data
whose answers can be checked by hand.

The tool lives in `scripts/` and is deliberately stdlib-only (it runs
under the benchmark's own venv and under a bare `python3`), so it is
imported by path rather than as a `blended.*` module.
"""

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import paired_bench_delta as tool


def write_roll(path: Path, model_dir: str, values: dict) -> Path:
    """A diagnose JSON with `{instance: (cd_yawmin, cd_pca, delta_orient)}`.

    The F-score columns the panel ranks on since OT-36 are derived from
    cd_pca (`1 - 10 * cd_pca`) so that "better Chamfer" and "better
    F-score" agree in every existing case and the arithmetic these tests
    pin — which was written on cd_pca — reads through unchanged on the
    registered axis in its own direction.
    """
    path.write_text(
        json.dumps(
            {
                "model_dir": model_dir,
                "per_instance": [
                    {
                        "instance": instance,
                        "cd_yawmin": yawmin,
                        "cd_pca": pca,
                        "delta_orient": orient,
                        "fscore_005": 1.0 - 10.0 * pca,
                        "precision_005": 1.0 - 10.0 * pca,
                        "recall_005": 1.0 - 10.0 * pca,
                    }
                    for instance, (yawmin, pca, orient) in values.items()
                ],
            }
        )
    )
    return path


def load(path: Path) -> list[dict]:
    return tool.load_rolls([path])


def test_a_consistent_worsening_is_a_regression(tmp_path):
    """Four instances, each 0.05 worse: zero paired spread, so the
    difference is real however small it is."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {
                "A": (0.10, 0.10, 0.0),
                "B": (0.20, 0.20, 0.0),
                "C": (0.30, 0.30, 0.0),
                "D": (0.40, 0.40, 0.0),
            },
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json",
            "cand",
            {
                "A": (0.15, 0.10, 0.0),
                "B": (0.25, 0.20, 0.0),
                "C": (0.35, 0.30, 0.0),
                "D": (0.45, 0.40, 0.0),
            },
        )
    )
    instances = ["A", "B", "C", "D"]
    result = tool.paired_delta(baseline, candidate, instances, "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.05)
    assert result["paired_stdev"] == pytest.approx(0.0)
    assert result["worse_count"] == 4
    assert result["better_count"] == 0
    assert result["regression"] is True
    # Shape did not move: that is what separates orientation from geometry.
    shape = tool.paired_delta(baseline, candidate, instances, "cd_pca")
    assert shape["mean_delta"] == pytest.approx(0.0)
    assert shape["regression"] is False


def test_a_reshuffle_of_coin_flips_is_not_a_regression(tmp_path):
    """Two instances broken, two fixed, by the same amount: the mean is
    zero and the paired SD is large — the exact shape of this benchmark's
    orientation flips."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {
                "A": (0.01, 0.01, 0.00),
                "B": (0.01, 0.01, 0.00),
                "C": (0.21, 0.01, 0.20),
                "D": (0.21, 0.01, 0.20),
            },
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json",
            "cand",
            {
                "A": (0.21, 0.01, 0.20),
                "B": (0.21, 0.01, 0.20),
                "C": (0.01, 0.01, 0.00),
                "D": (0.01, 0.01, 0.00),
            },
        )
    )
    instances = ["A", "B", "C", "D"]
    result = tool.paired_delta(baseline, candidate, instances, "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.0)
    assert result["paired_stdev"] > 0.2
    assert result["worse_count"] == 2 and result["better_count"] == 2
    assert result["regression"] is False
    # And the movers table must name the baseline's own orientation error,
    # which is how "the candidate broke it" is told apart from "the
    # baseline got lucky".
    rows = tool.movers(baseline, candidate, instances, "cd_yawmin")
    by_instance = {row["instance"]: row for row in rows}
    assert by_instance["A"]["baseline_delta_orient"] == pytest.approx(0.0)
    assert by_instance["C"]["baseline_delta_orient"] == pytest.approx(0.20)


def test_several_candidate_rolls_average_per_instance(tmp_path):
    """A multi-roll candidate is the per-instance mean, not a pooled
    mean of means over different instances."""
    baseline = load(
        write_roll(
            tmp_path / "base.json",
            "base",
            {"A": (0.10, 0.05, 0.05), "B": (0.10, 0.05, 0.05)},
        )
    )
    first = write_roll(
        tmp_path / "c1.json", "c1", {"A": (0.20, 0.05, 0.15), "B": (0.10, 0.05, 0.05)}
    )
    second = write_roll(
        tmp_path / "c2.json", "c2", {"A": (0.40, 0.05, 0.35), "B": (0.10, 0.05, 0.05)}
    )
    candidate = tool.load_rolls([first, second])
    assert tool.instance_mean(candidate, "A", "cd_yawmin") == pytest.approx(0.30)
    result = tool.paired_delta(baseline, candidate, ["A", "B"], "cd_yawmin")
    assert result["mean_delta"] == pytest.approx(0.10)
    assert result["worse_count"] == 1 and result["better_count"] == 0


def test_one_instance_is_refused_rather_than_reported(tmp_path):
    """A mean delta with no standard error is the mistake this tool
    exists to prevent."""
    roll = load(write_roll(tmp_path / "one.json", "one", {"A": (0.1, 0.1, 0.0)}))
    with pytest.raises(ValueError, match="at least"):
        tool.paired_delta(roll, roll, ["A"], "cd_yawmin")


def test_disagreeing_instance_sets_fail_loudly(tmp_path):
    """A mean over different instance sets is not a comparison."""
    from compare_3dcode_rolls import shared_instances

    baseline = load(
        write_roll(
            tmp_path / "base.json", "base", {"A": (0.1, 0.1, 0.0), "B": (0.2, 0.2, 0.0)}
        )
    )
    candidate = load(
        write_roll(
            tmp_path / "cand.json", "cand", {"A": (0.1, 0.1, 0.0), "C": (0.2, 0.2, 0.0)}
        )
    )
    with pytest.raises(SystemExit):
        shared_instances(baseline + candidate, None)


def test_a_missing_diagnose_file_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        tool.load_rolls([tmp_path / "absent.json"])


def test_the_ranking_metric_is_f_score_at_the_registered_threshold():
    """OT-36: F@0.05 ranks, higher is better; cd_pca and cd_yawmin are
    reported beside it and rank nothing.

    Registered by OT-33 before any roll was ranked on it: CD ranks
    category priors (DOI 10.1109/cvpr.2019.00352), and on the two
    disclosed rolls in hand the two metrics disagreed about which roll
    was better (cd_pca 0.0270 vs 0.0289; F@0.05 0.4060 vs 0.4454).
    """
    assert tool.PRIMARY_METRIC == "fscore_005"
    assert tool.RANKING_METRIC == "fscore_005"
    assert tool.higher_is_better(tool.RANKING_METRIC)
    assert tool.worsening_sign(tool.RANKING_METRIC) == -1
    assert tool.worsening_sign("cd_pca") == 1
    assert "cd_pca" in tool.REPORTED_METRICS
    assert "cd_yawmin" in tool.REPORTED_METRICS


def test_a_falling_f_score_is_a_regression_and_a_rising_one_is_not(tmp_path):
    """The sign convention, applied: on the ranking axis a candidate whose
    F-score fell on every instance regresses; one whose F-score rose does
    not, even though its Chamfer rows are identical to the baseline's."""
    baseline = load(
        write_roll(
            tmp_path / "b.json", "b", {f"I{n}": (0.10, 0.03, 0.07) for n in range(4)}
        )
    )
    fell = load(
        write_roll(
            tmp_path / "f.json", "f", {f"I{n}": (0.10, 0.05, 0.05) for n in range(4)}
        )
    )
    rose = load(
        write_roll(
            tmp_path / "r.json", "r", {f"I{n}": (0.10, 0.01, 0.09) for n in range(4)}
        )
    )
    instances = [f"I{n}" for n in range(4)]
    worse = tool.paired_delta(baseline, fell, instances, tool.RANKING_METRIC)
    better = tool.paired_delta(baseline, rose, instances, tool.RANKING_METRIC)
    assert worse["mean_delta"] > 0 and worse["worse_count"] == 4
    assert better["mean_delta"] < 0 and better["better_count"] == 4


def test_the_target_is_a_fraction_of_the_baselines_own_mean(tmp_path):
    """No literal guard survives: it is measured, not quoted.

    The retired pair (0.0706 guard, 0.060 target) came from a single
    roll of an axis whose between-roll SD is 0.0072, so the guard was
    the minimum of six draws being read as an expected value. Re-pinning
    the test to new literals would pin the same mistake.
    """
    assert not hasattr(tool, "CONTRACT_GUARD_CD_YAWMIN")
    assert not hasattr(tool, "CONTRACT_TARGET_CD_YAWMIN")
    arguments = tool.parse_arguments(
        ["--baseline", "b.json", "--candidate", "c.json", "--label", "x"]
    )
    assert not hasattr(arguments, "guard")
    assert not hasattr(arguments, "target")

    baseline = load(
        write_roll(
            tmp_path / "baseline.json",
            "baseline",
            {
                "A": (0.10, 0.02, 0.08),
                "B": (0.20, 0.06, 0.14),
                "C": (0.30, 0.04, 0.26),
                "D": (0.40, 0.08, 0.32),
            },
        )
    )
    instances = ["A", "B", "C", "D"]
    guard = tool.set_mean(baseline, instances, tool.RANKING_METRIC)
    assert guard == pytest.approx(0.5)  # F = 1 - 10 * mean cd_pca of 0.05
    report = tool.render_report(
        baseline,
        baseline,
        instances,
        tool.parse_arguments(
            ["--baseline", "b.json", "--candidate", "c.json", "--label", "x"]
        ),
    )
    # Higher is better on the registered axis, so the target sits ABOVE
    # the guard by the relative improvement.
    expected_target = guard * (1.0 + tool.TARGET_RELATIVE_IMPROVEMENT)
    assert f"{expected_target:.4f}" in report
    assert f"{guard * tool.TARGET_RELATIVE_IMPROVEMENT:.4f}" in report


def test_a_two_roll_candidate_is_refused(tmp_path):
    """A candidate is a mean over at least MINIMUM_PAIRED_ROLLS rolls."""
    rolls = [
        load(
            write_roll(
                tmp_path / f"roll{index}.json",
                f"roll{index}",
                {f"I{n:02d}": (0.07, 0.02, 0.05) for n in range(20)},
            )
        )[0]
        for index in range(2)
    ]
    with pytest.raises(SystemExit) as raised:
        tool.refuse_underpowered(rolls)
    assert "MINIMUM_PAIRED_ROLLS" in str(raised.value)


def test_a_short_roll_inside_a_candidate_is_refused_by_name(tmp_path):
    """A roll that did not cover the frozen set is not comparable."""
    full = {f"I{n:02d}": (0.07, 0.02, 0.05) for n in range(20)}
    rolls = [
        load(write_roll(tmp_path / "a.json", "full_a", full))[0],
        load(write_roll(tmp_path / "b.json", "full_b", full))[0],
        load(
            write_roll(
                tmp_path / "c.json",
                "three_instance_roll",
                {
                    "I00": (0.07, 0.02, 0.05),
                    "I01": (0.07, 0.02, 0.05),
                    "I02": (0.07, 0.02, 0.05),
                },
            )
        )[0],
    ]
    with pytest.raises(SystemExit) as raised:
        tool.refuse_underpowered(rolls)
    message = str(raised.value)
    assert "three_instance_roll" in message
    assert "MINIMUM_INSTANCES_FOR_RANKING" in message
