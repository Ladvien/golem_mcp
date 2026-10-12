"""The bench panel's ranking rule, and its refusals.

The panel exists because three change classes were each judged on a
single roll of `cd_yawmin` and each measured flat. So the tests that
matter here are the ones that fail when the rule is quietly relaxed: the
column order, the roll-count floor, the instance-count floor, and the
lexicographic executability rule actually being APPLIED rather than
described in prose nobody executes.
"""

import json
import math
import sys
from pathlib import Path

import pytest

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import bench_panel as tool

FROZEN_INSTANCES = tuple(f"I{index:02d}" for index in range(20))


def write_roll(
    path: Path,
    model_dir: str,
    values: dict,
    status: str = "OK_AGENT_DONE",
    statuses: dict | None = None,
) -> Path:
    """A diagnose JSON with `{instance: (cd_yawmin, cd_pca, delta_orient,
    fscore_005)}`; precision and recall are set equal to the F-score so a
    synthetic row carries every panel column."""
    statuses = statuses or {}
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
                        "fscore_005": f_score,
                        "precision_005": f_score,
                        "recall_005": f_score,
                        "status": statuses.get(instance, status),
                        "num_turns": 20,
                        "duration_s": 300.0,
                    }
                    for instance, (yawmin, pca, orient, f_score) in values.items()
                ],
            }
        )
    )
    return path


# A synthetic roll's F-score, derived from its cd_pca so that a roll with
# the better Chamfer also has the better F-score: every test that ranks
# by "pca" is then ranking by the registered axis in the registered
# direction, and one that wants the two to DISAGREE says so explicitly.
def f_from_pca(pca: float) -> float:
    return 1.0 - 10.0 * pca


def flat_values(pca: float, instances=FROZEN_INSTANCES) -> dict:
    """Every instance identical, so a group's spread comes only from the
    differences the test introduces on purpose."""
    return {
        instance: (pca + 0.05, pca, 0.05, f_from_pca(pca)) for instance in instances
    }


def group_of(tmp_path: Path, label: str, pcas, statuses=None) -> str:
    paths = []
    for index, pca in enumerate(pcas):
        paths.append(
            str(
                write_roll(
                    tmp_path / f"{label}_{index}.json",
                    f"{label}_roll{index}",
                    flat_values(pca),
                    statuses=statuses,
                )
            )
        )
    return f"{label}=" + ",".join(paths)


def render(tmp_path: Path, *specifications, reported=()) -> str:
    argv = []
    for specification in specifications:
        argv += ["--group", specification]
    for path in reported:
        argv += ["--reported-roll", str(path)]
    arguments = tool.parse_arguments(argv)
    groups = [tool.load_group(spec) for spec in arguments.group]
    tool.refuse_unrankable_groups(groups)
    reported_rolls = [tool.load_json(path) for path in arguments.reported_roll]
    return tool.render_panel(groups, reported_rolls, arguments, None)


def test_the_rolls_table_puts_the_ranking_metric_before_the_reported_one(
    tmp_path,
):
    """Column order IS the rule for a reader who skims one table."""
    panel = render(tmp_path, group_of(tmp_path, "g", [0.02, 0.03, 0.04]))
    header = next(line for line in panel.splitlines() if line.startswith("| roll |"))
    assert header.index("fscore_005") < header.index("cd_pca")
    assert header.index("cd_pca") < header.index("cd_yawmin")
    assert "cd_pca (reported)" in header
    assert "cd_yawmin (reported)" in header
    assert "delta_orient (reported)" in header
    assert "fscore_005 (reported)" not in header


def test_the_ranking_axis_is_f_score_and_higher_ranks_first(tmp_path):
    """OT-36. Registered by OT-33 for the next roll set: F@0.05 ranks,
    higher is better (DOI 10.1109/cvpr.2019.00352). `low_f` has the better
    Chamfer on every roll and the worse F-score; the panel must rank
    `high_f` first, and the rule line must say which way is better."""
    high_f = {instance: (0.10, 0.05, 0.05, 0.80) for instance in FROZEN_INSTANCES}
    low_f = {instance: (0.06, 0.01, 0.05, 0.40) for instance in FROZEN_INSTANCES}
    paths = {}
    for label, values in (("high_f", high_f), ("low_f", low_f)):
        paths[label] = ",".join(
            str(
                write_roll(
                    tmp_path / f"{label}_{index}.json", f"{label}_roll{index}", values
                )
            )
            for index in range(3)
        )
    panel = render(tmp_path, f"high_f={paths['high_f']}", f"low_f={paths['low_f']}")
    assert tool.RANKING_METRIC == "fscore_005"
    assert "higher is better" in panel
    body = panel.split("## Groups")[1].split("## Power")[0]
    rows = [line for line in body.splitlines() if line.startswith(("| 1 |", "| 2 |"))]
    assert rows[0].startswith("| 1 | high_f |"), rows
    assert rows[1].startswith("| 2 | low_f |"), rows


def test_a_roll_that_failed_one_instance_cannot_rank(tmp_path):
    """§P8a: executability 20/20 on EVERY roll. A roll with 20 scored rows
    and one failed status must be refused by name with its executability,
    even though its row count clears the instance floor."""
    one_failed = {FROZEN_INSTANCES[0]: "ERR_MODEL_CALL"}
    paths = [
        str(write_roll(tmp_path / "a.json", "whole_a", flat_values(0.02))),
        str(write_roll(tmp_path / "b.json", "whole_b", flat_values(0.03))),
        str(
            write_roll(
                tmp_path / "c.json", "one_short", flat_values(0.04), statuses=one_failed
            )
        ),
    ]
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, "g=" + ",".join(paths))
    message = str(raised.value)
    assert "one_short" in message
    assert "executability 19/20" in message


def test_a_two_roll_group_is_refused(tmp_path):
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, group_of(tmp_path, "g", [0.02, 0.03]))
    assert "MINIMUM_PAIRED_ROLLS" in str(raised.value)


def test_a_short_roll_inside_a_ranking_group_is_refused_by_name(tmp_path):
    """Three rolls, one of which covers three instances: the group has two
    rankable rolls, and the refusal names the roll that is not one."""
    paths = [
        str(write_roll(tmp_path / "a.json", "full_a", flat_values(0.02))),
        str(write_roll(tmp_path / "b.json", "full_b", flat_values(0.03))),
        str(
            write_roll(
                tmp_path / "c.json",
                "three_instance_roll",
                flat_values(0.04, FROZEN_INSTANCES[:3]),
            )
        ),
    ]
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, "g=" + ",".join(paths))
    message = str(raised.value)
    assert "three_instance_roll" in message
    assert "3 instances scored" in message
    assert "MINIMUM_PAIRED_ROLLS" in message


def test_a_group_without_an_equals_sign_is_refused(tmp_path):
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, "no-equals-sign")
    assert "no '='" in str(raised.value)


def test_a_missing_diagnose_file_is_refused(tmp_path):
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, f"g={tmp_path / 'absent.json'}")
    assert "No such diagnose JSON" in str(raised.value)


def test_rolls_disagreeing_on_their_instance_sets_are_refused(tmp_path):
    shifted = FROZEN_INSTANCES[:19] + ("EXTRA",)
    paths = [
        str(write_roll(tmp_path / "a.json", "roll_a", flat_values(0.02))),
        str(write_roll(tmp_path / "b.json", "roll_b", flat_values(0.03))),
        str(
            write_roll(
                tmp_path / "c.json",
                "odd_one_out",
                flat_values(0.04, shifted),
            )
        ),
    ]
    with pytest.raises(SystemExit) as raised:
        render(tmp_path, "g=" + ",".join(paths))
    assert "disagree on their instance sets" in str(raised.value)


def test_the_group_standard_error_falls_as_the_square_root_of_the_rolls(
    tmp_path,
):
    """SE(N rolls) = SE(one roll) / sqrt(N), exactly.

    This is the whole reason MINIMUM_PAIRED_ROLLS is 3: averaging rolls
    is the only lever that touches roll noise, and the panel has to
    report the reduction it actually bought.
    """
    specification = group_of(tmp_path, "g", [0.020, 0.025, 0.030])
    group = tool.load_group(specification)
    instances = tool.group_instances(group)
    statistics_row = tool.group_statistics(group, instances)
    axis = statistics_row["axes"][tool.RANKING_METRIC]
    assert axis["standard_error"] == pytest.approx(
        axis["standard_error_one_roll"] / math.sqrt(3), abs=1e-9
    )


def test_a_worse_executability_cannot_rank_first(tmp_path):
    """The lexicographic rule, applied rather than described — and since
    OT-36 applied at the roll: a group with a failed instance on any roll
    is not ranked lower, it is refused, because §P8a requires 20/20 on
    every roll. `broken` has the better F-score on every roll and fails
    four instances per roll; the refusal names each roll with its
    executability, and `whole` alone renders.
    """
    failing = {instance: "FAIL_NO_MESH" for instance in FROZEN_INSTANCES[:4]}
    with pytest.raises(SystemExit) as raised:
        render(
            tmp_path,
            group_of(tmp_path, "whole", [0.030, 0.031, 0.032]),
            group_of(tmp_path, "broken", [0.010, 0.011, 0.012], statuses=failing),
        )
    message = str(raised.value)
    assert "group broken has 0 rankable roll(s)" in message
    assert message.count("executability 16/20") == 3
    panel = render(tmp_path, group_of(tmp_path, "whole", [0.030, 0.031, 0.032]))
    body = panel.split("## Groups")[1].split("## Power")[0]
    assert "| 1 | whole |" in body
    assert "| 60/60 |" in body


def test_a_short_roll_can_be_reported_without_being_ranked(tmp_path):
    """A roll below the instance floor is listed and excluded from means."""
    short = write_roll(
        tmp_path / "short.json",
        "twelve_instance_sweep",
        flat_values(0.40, FROZEN_INSTANCES[:12]),
    )
    panel = render(
        tmp_path,
        group_of(tmp_path, "g", [0.020, 0.021, 0.022]),
        reported=[short],
    )
    rolls = panel.split("## Rolls")[1].split("## Groups")[0]
    assert "twelve_instance_sweep (not ranked)" in rolls
    groups = panel.split("## Groups")[1].split("## Power")[0]
    assert "0.4000" not in groups


def test_the_power_block_names_the_axis_the_target_is_visible_on(tmp_path):
    """A target below the detectable effect must say so, in numbers."""
    specification = group_of(tmp_path, "g", [0.020, 0.025, 0.030])
    group = tool.load_group(specification)
    instances = tool.group_instances(group)
    statistics_row = tool.group_statistics(group, instances)
    lines = tool.render_power([statistics_row])
    verdicts = [line for line in lines if line.startswith("- `")]
    assert len(verdicts) == len(tool.PANEL_METRICS)
    for line in verdicts:
        assert "**visible**" in line or "**below the instrument's resolution**" in line
        assert "0.0" in line  # both numbers are printed, never just a word


def test_visibility_is_judged_at_the_roll_floor_not_at_the_group_size(
    tmp_path,
):
    """Six accumulated rolls must not flatter the instrument.

    A pre-registration answers "will this see a target-sized improvement
    in the NEXT candidate", and the next candidate is bound by
    MINIMUM_PAIRED_ROLLS. Measured on the real rolls, cd_yawmin's 15%
    target reads visible at six rolls (0.0115 vs 0.0073), barely visible
    at three (0.0115 vs 0.0104) and invisible at one (0.0115 vs 0.0180) —
    so which N the verdict uses decides the answer.
    """
    six = [0.020, 0.022, 0.024, 0.026, 0.028, 0.030]
    group = tool.load_group(group_of(tmp_path, "g", six))
    instances = tool.group_instances(group)
    row = tool.group_statistics(group, instances)
    axis = row["axes"][tool.RANKING_METRIC]

    assert len(row["rankable_rolls"]) == 6
    assert axis["standard_error"] == pytest.approx(
        axis["standard_error_one_roll"] / math.sqrt(6), abs=1e-12
    )
    assert axis["standard_error_at_floor"] == pytest.approx(
        axis["standard_error_one_roll"] / math.sqrt(tool.MINIMUM_PAIRED_ROLLS),
        abs=1e-12,
    )
    # The verdict's denominator is the floor, so it is STRICTLY LARGER
    # than the group's own SE whenever the group has more rolls.
    assert axis["detectable_effect"] == pytest.approx(
        tool.REGRESSION_SIGMA * axis["standard_error_at_floor"], abs=1e-12
    )
    assert axis["detectable_effect"] > tool.REGRESSION_SIGMA * (axis["standard_error"])


def test_the_not_measured_section_names_image_similarity_and_both_reasons(
    tmp_path,
):
    panel = render(tmp_path, group_of(tmp_path, "g", [0.02, 0.03, 0.04]))
    section = panel.split("## Not measured")[1]
    assert "Image similarity" in section
    assert "torch" in section and "transformers" in section
    assert "data/<instance>/images/" in section
    # And it must not claim the meshes are gone, which was the first
    # explanation offered and is false.
    assert "NOT gone" in section
    assert "glb/" in section and "renders/" in section


def test_executability_counts_unscoreable_rows(tmp_path):
    """A run that produced no mesh has no metrics, so counting over the
    SCORED rows would divide by the one subset guaranteed to look
    healthy."""
    values = dict(flat_values(0.02))
    path = write_roll(tmp_path / "partial.json", "partial", values)
    document = json.loads(path.read_text())
    document["per_instance"].append(
        {
            "instance": "I99",
            "cd_yawmin": None,
            "cd_pca": None,
            "delta_orient": None,
            "fscore_005": None,
            "precision_005": None,
            "recall_005": None,
            "status": "FAIL_NO_MESH",
            "num_turns": 24,
            "duration_s": 700.0,
        }
    )
    path.write_text(json.dumps(document))
    roll = tool.load_json(str(path))
    assert len(roll["per_instance"]) == 20
    assert tool.executability(roll) == (20, 21)
