"""The hatch share is read off the baked script's labels, so the label
format is a contract between two modules.

`REPORT.md` §4d published 95.1% for two roll-years because the number was
taken from `.agent_meta.json`: `n_op_calls_included` counts the 14 reader
ops as geometry-emitting (`emits_geometry` is "the hatch or ANY facade
op") and `n_chunks_included` is the label COUNTER, which advances on op
calls too. The measurement now parses `standalone_script`'s own
`# --- chunk N ---` and `# --- op N: name ---` labels, which is ground
truth for what the score saw — and a silent drift in that format would
re-publish a false 100% hatch share rather than fail. This pins the round
trip: what the bridge writes is exactly what the two measurement scripts
recover.

Pure: a recorded call sequence in, counts out. No bpy, no bench.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from blended.evaluate.bench_bridge import RecordedCall, prelude, standalone_script
from blended.stages import STAGE_DONE, STAGE_EXECUTE

SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import finetune_hatch_mechanism as mechanism
from finetune_phase_a import baked_call_counts

PRELUDE = prelude("/venv/site-packages", "/repo/src")
EPILOGUE = "\n# --- epilogue ---\nprint('done')\n"
# One of each kind the bake can emit: a scene-changing op, a hatch chunk,
# a READER op (which meta miscounted as geometry), and a scene-changing op
# that raised AFTER mutating the scene, whose label carries a suffix.
CALLS = (
    RecordedCall("add_box", {"name": "A"}, STAGE_DONE),
    RecordedCall("run_python", {"source": "a = 1", "reason": "r"}, STAGE_DONE),
    RecordedCall("world_bounds", {}, STAGE_DONE),
    RecordedCall(
        "boolean_union",
        {"target_name": "A", "addend_name": "B"},
        STAGE_EXECUTE,
        changed_scene=True,
    ),
    RecordedCall("run_python", {"source": "b = 2", "reason": "r"}, STAGE_DONE),
)


def _write_script(tmp_path: Path) -> Path:
    script = standalone_script(list(CALLS), PRELUDE, EPILOGUE)
    path = tmp_path / "Instance_seed0.py"
    path.write_text(script.text)
    return path


def test_baked_labels_recover_every_call_the_bridge_wrote(tmp_path):
    path = _write_script(tmp_path)
    ops, chunks = mechanism.baked_labels(path)
    # The op that raised after changing the scene is INCLUDED by the
    # bridge (its label gains a suffix) and must still be counted.
    assert ops == ["add_box", "world_bounds", "boolean_union"]
    assert chunks == 2


def test_reader_ops_are_not_counted_as_geometry(tmp_path):
    path = _write_script(tmp_path)
    counts = baked_call_counts(path)
    assert counts == {"baked_chunks": 2, "baked_scene_ops": 2, "baked_reader_ops": 1}


def test_a_missing_script_reads_as_zero_not_as_a_crash(tmp_path):
    absent = tmp_path / "NeverBaked_seed0.py"
    assert mechanism.baked_labels(absent) == ([], 0)
    assert baked_call_counts(absent) == {
        "baked_chunks": 0,
        "baked_scene_ops": 0,
        "baked_reader_ops": 0,
    }


def test_drop_rate_is_dispatched_minus_baked():
    """The one instrument the archive and the single-shot arm share."""
    rows = [
        {"dispatched": 10, "baked": 7},
        {"dispatched": 0, "baked": 0},
    ]
    assert mechanism.drop_rate(rows, "dispatched", "baked") == {
        "dispatched": 10,
        "baked": 7,
        "dropped": 3,
        "drop_rate": 0.3,
    }
    empty = mechanism.drop_rate([], "dispatched", "baked")
    assert empty["drop_rate"] is None


def test_a_uniform_probe_is_refused_rather_than_reported():
    """N rolls with one identical value means the parse broke."""
    rolls = {"roll-a": {"baked_scene_ops": 0}, "roll-b": {"baked_scene_ops": 0}}
    with pytest.raises(SystemExit):
        mechanism.assert_probe_varies(rolls)
    rolls["roll-a"]["baked_scene_ops"] = 3
    with pytest.raises(SystemExit):
        mechanism.assert_probe_varies(rolls)
    rolls["roll-b"]["baked_scene_ops"] = 1
    mechanism.assert_probe_varies(rolls)
