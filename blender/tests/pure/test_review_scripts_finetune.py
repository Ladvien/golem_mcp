"""Regression tests for the 2026-10-07 review of the fine-tune decision scripts.

Each test asserts the behaviour of a path that was wrong:

* Phase B counted op/chunk usage from the completion record's own counters
  (`n_ops` counts READER ops; `n_hatch` counts chunks DISPATCHED) instead of
  the baked script's labels, defined "passed" three different ways, and read
  stale bake artifacts for a completion that wrote no script.
* A hardcoded "18.8%" and "G1-G2" sat in a generated note.
* Phase C counted op-sequence pairs from `.agent_meta.json` and its op
  coverage ignored the archived scripts it had just counted.
* The sweep reported a crashed re-run as whatever the PREVIOUS run recorded.
* The G3 judge truncated hand-verified rows on a re-run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import finetune_decision_report as report
import finetune_hatch_mechanism as mechanism
import finetune_phase_a_judge as judge
import finetune_phase_b as phase_b
import finetune_phase_c as phase_c
import sweep_finetune_arms as sweep
from finetune_decision_thresholds import CD_PCA_PASS

PASSING_CD_PCA = CD_PCA_PASS / 2


class _Taxonomy:
    """The two bench functions Phase B calls, reduced to identity."""

    @staticmethod
    def fingerprint(text: str) -> str:
        return text[:20]

    @staticmethod
    def categorize(text: str) -> str:
        return "OTHER"


def _row(**overrides) -> dict:
    row = {
        "arm": "a1",
        "draw": 1,
        "instance": "Inst_seed0",
        "format": "ops",
        "parse_result": "OK",
        "script_written": True,
        "render_status": "OK",
        "n_meshes": 1,
        "cd_pca": PASSING_CD_PCA,
        "fscore_005": 0.5,
        "wall_time_s": 10.0,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "n_tool_calls": 3,
        "code": "PASS",
        "baked_chunks": 0,
        "baked_scene_ops": 0,
    }
    row.update(overrides)
    return row


# --- Phase B --------------------------------------------------------------


def test_funnel_hatch_and_op_calls_come_from_baked_labels_not_record_counters():
    # `n_ops`/`n_hatch` carry the record's own (biased) counters and must be
    # ignored: 9 and 9 here, against 3 baked chunks and 2 baked scene ops.
    rows = [_row(n_ops=9, n_hatch=9, baked_chunks=3, baked_scene_ops=2)]
    funnel = phase_b.funnel(rows)
    assert funnel["hatch_calls"] == 3
    assert funnel["op_calls"] == 2


def test_a_stale_score_on_a_row_that_did_not_execute_is_not_a_pass_anywhere():
    # cd_pca is on the bar, but the bake did not execute (a stale diagnose
    # row from an earlier run). The funnel, pass@k and the clustered
    # interval must all agree it is not a pass.
    rows = [_row(render_status="NO_SCRIPT", script_written=False)]
    funnel = phase_b.funnel(rows)
    rates = phase_b.pass_rates(rows)
    assert funnel["cd_pca_passing"] == 0
    assert funnel["cd_pca_pass_rate"] == 0.0
    assert rates["pass_at_1"] == 0.0
    assert phase_b.clustered_interval(rows, phase_b._passed)["rate"] == 0.0


def test_a_passing_executed_row_is_a_pass_in_all_three_places():
    rows = [_row()]
    assert phase_b.funnel(rows)["cd_pca_passing"] == 1
    assert phase_b.pass_rates(rows)["pass_at_1"] == 1.0
    assert phase_b.clustered_interval(rows, phase_b._passed)["rate"] == 1.0


def test_execution_row_reads_baked_labels_for_a_written_script(tmp_path):
    instance_root = tmp_path / "res" / "ft-a1-k1" / "Inst_seed0"
    (instance_root / "renders").mkdir(parents=True)
    (instance_root / "renders" / "render_log.json").write_text(
        json.dumps({"status": "OK", "n_meshes": 2})
    )
    (instance_root / "Inst_seed0.py").write_text(
        "# --- chunk 1 ---\na = 1\n"
        "# --- op 2: add_box ---\n_op('add_box', {})\n"
        "# --- op 3: world_bounds ---\n_op('world_bounds', {})\n"
    )
    completion = {
        "arm": "a1",
        "draw": 1,
        "instance": "Inst_seed0",
        "parse_result": "OK",
        "script_written": True,
    }
    row = phase_b.execution_row(tmp_path, "res", completion, _Taxonomy)
    assert row["render_status"] == "OK"
    assert row["n_meshes"] == 2
    assert row["baked_chunks"] == 1
    assert row["baked_scene_ops"] == 1  # the reader op is not counted


def test_execution_row_ignores_stale_artifacts_when_no_script_was_written(tmp_path):
    instance_root = tmp_path / "res" / "ft-a1-k1" / "Inst_seed0"
    (instance_root / "renders").mkdir(parents=True)
    (instance_root / "glb").mkdir()
    (instance_root / "renders" / "render_log.json").write_text(
        json.dumps({"status": "OK", "n_meshes": 2})
    )
    (instance_root / "glb" / "Inst_seed0.glb").write_bytes(b"glb")
    (instance_root / "Inst_seed0.py").write_text("# --- chunk 1 ---\na = 1\n")
    completion = {
        "arm": "a1",
        "draw": 1,
        "instance": "Inst_seed0",
        "parse_result": "NO_TOOL_CALLS",
        "script_written": False,
    }
    row = phase_b.execution_row(tmp_path, "res", completion, _Taxonomy)
    assert row["render_status"] == "NO_SCRIPT"
    assert row["n_meshes"] == 0
    assert row["glb_path"] == ""
    assert row["baked_chunks"] == 0


def _measured(executability: dict[str, float], codes: dict[str, dict]) -> dict:
    """Just the keys `deltas` reads, one arm per entry."""
    measured = {}
    for arm, rate in executability.items():
        measured[arm] = {
            "funnel": {
                "executability_rate": rate,
                "cd_pca_pass_rate": 0.0 if arm == "a2" else 0.4,
                "executability_interval": {"rate": rate, "se": 0.0},
                "cd_pca_pass_interval": {"rate": 0.4, "se": 0.0},
                "codes": codes.get(arm, {}),
            },
            "rates": {"pass_at_1": 0.4, "greedy_pass_rate": 0.4},
        }
    return measured


def test_zero_standard_error_is_a_real_half_width_not_a_missing_one():
    measured = _measured({"a2": 0.0, "a3": 0.0, "a4": 1.0, "a5": 0.75, "a1": 0.8}, {})
    computed = phase_b.deltas(measured)
    assert computed["delta_facade_half_width_pp"] == 0.0
    assert computed["delta_tune_half_width_pp"] == 0.0


def test_failure_class_shares_exclude_passes_and_excluded_codes():
    shares = phase_b.failure_class_shares(
        {"PASS": 10, "INFRA": 3, "UNSCORED": 2, "E7": 6, "E3": 2, "G1": 2}
    )
    assert shares == {"failures": 10, "syntax": 0.8, "geometry": 0.2}
    assert phase_b.failure_class_shares({"PASS": 4}) == {
        "failures": 0,
        "syntax": None,
        "geometry": None,
    }


def test_rule_two_note_quotes_the_measured_a5_rate_and_class_shares():
    measured = _measured(
        {"a1": 0.8, "a2": 0.0, "a3": 0.1, "a4": 0.9, "a5": 0.6},
        {"a3": {"E7": 9, "PASS": 1}, "a4": {"G2": 2, "E3": 2, "PASS": 4}},
    )
    computed = phase_b.deltas(measured)
    assert computed["a5_executability_rate"] == 0.6
    phase_a = {"shares": {"f_geom": 0.1, "f_syntax": 0.02}}
    _verdict, notes = phase_b.fired_rule(phase_a, computed)
    joined = " ".join(notes)
    assert "fails to execute 40.0% of the time" in joined  # 1 - 0.6, not a typed 18.8%
    assert "18.8%" not in joined
    assert "100.0% of the untuned base's (A3) failures are syntactic" in joined
    assert "50.0% of the fine-tune's (A4) that are geometric" in joined


# --- Phase C --------------------------------------------------------------


def _archive_instance(
    bench_root: Path, model_dir: str, meta: dict, script_text: str
) -> None:
    instance = "Inst_seed0"
    directory = bench_root / "res" / model_dir / instance
    (directory / "renders").mkdir(parents=True)
    (directory / "renders" / "render_log.json").write_text(json.dumps({"status": "OK"}))
    (directory / ".agent_meta.json").write_text(json.dumps(meta))
    (directory / f"{instance}.py").write_text(script_text)
    prompt = bench_root / "data" / instance
    prompt.mkdir(parents=True, exist_ok=True)
    (prompt / "prompt_description.txt").write_text("a thing")


def test_phase_c_counts_ops_off_the_baked_script_not_the_meta_counters(tmp_path):
    # Meta claims 9 ops and 9 chunks; the script holds 1 chunk, 1 scene op and
    # 1 reader op. A second roll's meta has no `n_op_calls_included` key at all:
    # its bridge could not collect an op, so it is counted apart, not averaged in.
    labels = (
        "# --- chunk 1 ---\na = 1\n"
        "# --- op 2: add_box ---\n_op('add_box', {})\n"
        "# --- op 3: world_bounds ---\n_op('world_bounds', {})\n"
    )
    _archive_instance(
        tmp_path,
        "blended-collecting",
        {"n_op_calls_included": 9, "n_chunks_included": 9},
        labels,
    )
    _archive_instance(
        tmp_path,
        "blended-blind",
        {"n_chunks_included": 9},
        "# --- chunk 1 ---\na = 1\n",
    )
    pairs = phase_c.archive_pairs(tmp_path, "res")["pairs"]
    summary = phase_c.summarise_pairs(pairs)
    assert summary["op_sequence_pairs"] == 1
    assert summary["scene_op_calls_baked"] == 1
    assert summary["chunks_baked"] == 1
    assert summary["pairs_before_op_collection"] == 1


def test_phase_c_op_coverage_merges_the_archived_script_histogram():
    coverage = phase_c.op_coverage(
        {"tool_histogram": {"add_box": 1}},
        {"histogram": {"add_box": 1, "link_into_scene": 50, "not_an_op": 99}},
    )
    assert coverage["histogram"] == {"link_into_scene": 50, "add_box": 2}
    assert "link_into_scene" not in coverage["ops_unseen"]
    assert coverage["ops_seen"] == 2
    assert coverage["ops_thin"] == 1  # add_box, seen 2 < the thin line


# --- Hatch mechanism -------------------------------------------------------


def _drop(rate):
    return {"scene_ops": {"drop_rate": rate}}


def test_mechanism_summary_refuses_to_print_a_refutation_the_numbers_do_not_support():
    ok = {"failure_before_first_chunk": 2, "failure_after_first_chunk": 9}
    mechanism.assert_hypothesis_refuted(_drop(0.07), _drop(0.26), ok)
    with pytest.raises(SystemExit, match="both predictions fail"):
        mechanism.assert_hypothesis_refuted(_drop(0.40), _drop(0.26), ok)
    with pytest.raises(SystemExit, match="both predictions fail"):
        mechanism.assert_hypothesis_refuted(
            _drop(0.07),
            _drop(0.26),
            {"failure_before_first_chunk": 9, "failure_after_first_chunk": 2},
        )
    with pytest.raises(SystemExit, match="unmeasured"):
        mechanism.assert_hypothesis_refuted(_drop(None), _drop(0.26), ok)


# --- Sweep ----------------------------------------------------------------


def _record(arm: str, draw: int, instance: str, parse_result: str) -> dict:
    return {
        "arm": arm,
        "draw": draw,
        "instance": instance,
        "parse_result": parse_result,
    }


def test_sweep_reads_only_records_the_subprocess_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "COMPLETIONS_ROOT", tmp_path)
    path = sweep.completions_path("a4", 2, per_draw=True)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_record("a4", 2, "Inst_seed0", "OK"))
        + "\n"
        + json.dumps(_record("a4", 2, "Other_seed0", "NO_CODE"))
        + "\n"
        + json.dumps(_record("a4", 1, "Inst_seed0", "NO_CODE"))
        + "\n"
    )
    before = sweep.matching_completions("a4", 2, "Inst_seed0", True)
    assert [record["parse_result"] for record in before] == ["OK"]
    # The re-run crashed: nothing appended. The old "OK" must not be reported.
    after = sweep.matching_completions("a4", 2, "Inst_seed0", True)[len(before) :]
    assert sweep.completion_outcome(after, 1) == ({}, "ERR_EXIT_1")
    assert sweep.completion_outcome(after, 0) == ({}, sweep.OUTCOME_NO_RECORD)
    with path.open("a") as handle:
        handle.write(json.dumps(_record("a4", 2, "Inst_seed0", "SYNTAX_ERROR")) + "\n")
    fresh = sweep.matching_completions("a4", 2, "Inst_seed0", True)[len(before) :]
    record, outcome = sweep.completion_outcome(fresh, 0)
    assert outcome == "SYNTAX_ERROR"
    assert record["parse_result"] == "SYNTAX_ERROR"


def test_blender_ops_command_turns_a_script_exception_into_a_nonzero_exit(tmp_path):
    arguments = type(
        "Arguments",
        (),
        {
            "arm": "a1",
            "bench_root": str(tmp_path),
            "results_root": "res",
            "per_draw_files": False,
            "overwrite": False,
            "blender": "/b/Blender",
        },
    )()
    command = sweep.completion_command(arguments, 1, "Inst_seed0")
    flag = command.index("--python-exit-code")
    assert command[flag + 1] != "0"
    assert flag < command.index("--python")


# --- G3 judge -------------------------------------------------------------


def test_judge_refuses_to_truncate_hand_verified_rows(tmp_path):
    path = tmp_path / "g3_judgements.jsonl"
    judge.refuse_to_overwrite_hand_verification(path)  # absent: fine
    path.write_text(
        json.dumps({"instance": "A", "hand_verified": False})
        + "\n"
        + json.dumps({"instance": "B"})
        + "\n"
    )
    judge.refuse_to_overwrite_hand_verification(path)  # nothing verified: fine
    path.write_text(
        json.dumps({"instance": "A", "hand_verified": False})
        + "\n"
        + json.dumps({"instance": "B", "hand_verified": True, "agrees": False})
        + "\n"
    )
    with pytest.raises(SystemExit, match="1 hand-verified"):
        judge.refuse_to_overwrite_hand_verification(path)


# --- Report ---------------------------------------------------------------


def test_bar_verdict_is_derived_from_the_delta_and_its_interval():
    assert (
        report.bar_verdict(96.2, 5.48, 15.0)
        == "clears the bar by ~15x its own interval"
    )
    assert report.bar_verdict(20.0, 8.0, 15.0) == (
        "point estimate clears the bar; its interval does not"
    )
    assert report.bar_verdict(10.0, 1.0, 15.0) == "below the bar"
    assert report.bar_verdict(30.0, 0.0, 15.0) == "clears the bar; zero-width interval"
    assert report.bar_verdict(None, 1.0, 15.0) == "unmeasured"


def test_bands_overlap_only_when_they_share_a_point_and_are_measured():
    assert report.bands_overlap(
        {"low": 25.8, "high": 59.2}, {"low": 25.7, "high": 64.3}
    )
    assert not report.bands_overlap(
        {"low": 0.0, "high": 10.0}, {"low": 20.0, "high": 30.0}
    )
    assert not report.bands_overlap(
        {"low": None, "high": None}, {"low": 0.0, "high": 1.0}
    )
