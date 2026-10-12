"""Regression tests for the scripts_misc review fixes (pure helpers only).

Each test drives a script's own helper against measured input and asserts
the behavior the fix introduced; none restates a constant.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPOSITORY_ROOT / "scripts"


def _load_script(name: str, monkeypatch: pytest.MonkeyPatch):
    """Import scripts/<name>.py without running it as __main__.

    pin_revision and converge_auto `os.chdir` to the repository root at
    import; monkeypatch.chdir first so teardown restores the real cwd.
    """
    monkeypatch.chdir(REPOSITORY_ROOT)
    module_name = f"scripts_misc_{name}"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass resolves its module through sys.modules at class creation.
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


# --- provider_smoke: a typo in --only must not run zero lanes ---------------


def test_provider_smoke_rejects_an_unknown_lane(monkeypatch):
    smoke = _load_script("provider_smoke", monkeypatch)
    with pytest.raises(SystemExit) as refused:
        smoke.parse_lanes("big,claude_code")  # underscore: a typo for claude-code
    assert "claude_code" in str(refused.value)


def test_provider_smoke_rejects_an_empty_lane_list(monkeypatch):
    smoke = _load_script("provider_smoke", monkeypatch)
    with pytest.raises(SystemExit):
        smoke.parse_lanes(" , ")


def test_provider_smoke_keeps_the_named_lanes_in_order(monkeypatch):
    smoke = _load_script("provider_smoke", monkeypatch)
    assert smoke.parse_lanes("claude-code, big") == ["claude-code", "big"]


# --- converge_auto: a crashed run must not read as an older run's record ----


def _record(iteration: int, brief_name: str):
    return SimpleNamespace(iteration=iteration, brief_name=brief_name)


def test_record_for_run_is_none_when_only_an_older_run_of_the_brief_exists(monkeypatch):
    converge = _load_script("converge_auto", monkeypatch)
    records = [_record(7, "planter_box"), _record(8, "uv_crate")]
    # iteration 9 of planter_box crashed before it wrote a record: the
    # newest planter_box record is iteration 7, which is not this run.
    assert converge.record_for_run(records, 9, "planter_box") is None
    assert converge.record_for_run(records, 8, "planter_box") is None


def test_record_for_run_finds_the_exact_run(monkeypatch):
    converge = _load_script("converge_auto", monkeypatch)
    wanted = _record(9, "planter_box")
    records = [_record(9, "uv_crate"), wanted, _record(10, "planter_box")]
    assert converge.record_for_run(records, 9, "planter_box") is wanted


# --- pin_revision: never pin an unnamed model, never skip a rewrite ---------


def test_replace_runs_rewrites_the_real_registry_block(monkeypatch):
    pin = _load_script("pin_revision", monkeypatch)
    text = (
        REPOSITORY_ROOT / "src" / "blended" / "agent" / "prompt_versions.py"
    ).read_text(encoding="utf-8")
    rewritten = pin._replace_runs(text, [(901, "alpha"), (902, "beta")])
    block = rewritten.split("CONVERGENCE_RUNS = ", 1)[1].split("\n)\n", 1)[0] + "\n)"
    assert ast.literal_eval(block) == ((901, "alpha"), (902, "beta"))
    assert rewritten.count("CONVERGENCE_RUNS = (") == 1


def test_replace_runs_refuses_a_registry_without_the_block(monkeypatch):
    pin = _load_script("pin_revision", monkeypatch)
    with pytest.raises(pin.PinRefused):
        pin._replace_runs("PINNED_PROMPT_REVISION = 10\n", [(1, "alpha")])


def test_replace_assignment_does_not_read_backslashes_as_escapes(monkeypatch):
    pin = _load_script("pin_revision", monkeypatch)
    out = pin._replace_assignment('X = "old"\n', "X", r'"a\1b"')
    assert out == 'X = "a\\1b"\n'


def test_pin_refuses_a_proposal_that_names_no_writer_model(monkeypatch, tmp_path):
    pin = _load_script("pin_revision", monkeypatch)
    from blended.agent.prompt_versions import PINNED_PROMPT_REVISION, get_revision

    # Work on a copy: if the refusal ever regressed, main would rewrite
    # the registry, and that must hit the scratch copy, not the source.
    registry_copy = tmp_path / "prompt_versions.py"
    shutil.copy(pin.REGISTRY_PATH, registry_copy)
    before = registry_copy.read_text(encoding="utf-8")
    monkeypatch.setattr(pin, "REGISTRY_PATH", registry_copy)
    monkeypatch.setattr(pin, "PINNED_IDENTITY_PATH", tmp_path / "pinned_identity.txt")

    revision = get_revision(PINNED_PROMPT_REVISION)
    proposal = {
        "revision": revision.revision,
        "prompt_identity": revision.identity,
        "runs": [[1, "planter_box"]],
        "examiner_identity": "e",
        "calibration_identity": "c",
        "writer_model": "",  # converge_auto's value when the runs mixed writers
        "vision_model": "claude-code:sonnet",
        "tool_call_budget": 24,
        "proposed_at": "2026-01-01T00:00:00+00:00",
    }
    proposal_path = tmp_path / "pin_proposal.json"
    proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    with pytest.raises(pin.PinRefused) as refused:
        pin.main(
            [
                "--revision",
                str(revision.revision),
                "--proposal",
                str(proposal_path),
                "--skip-golden-views",
            ]
        )
    assert "writer_model" in str(refused.value)
    assert registry_copy.read_text(encoding="utf-8") == before
    assert not (tmp_path / "pinned_identity.txt").exists()
