"""Executor: structured traceback capture + drift matching, in-process."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


def test_successful_run():
    from blended.run import run_source_in_process

    result = run_source_in_process("import bpy\nx = 1 + 1\n")
    assert result.ok
    assert result.blender_version


def test_failure_captures_traceback():
    from blended.run import run_source_in_process

    result = run_source_in_process("raise RuntimeError('deliberate')")
    assert not result.ok
    assert result.error_type == "RuntimeError"
    assert "deliberate" in result.traceback_text


def test_drift_catalog_matches_in_failure():
    from blended.run import run_source_in_process

    source_using_removed_api = (
        "import bpy\nmesh = bpy.data.meshes.new('m')\nmesh.use_auto_smooth = True\n"
    )
    result = run_source_in_process(source_using_removed_api)
    assert not result.ok
    assert any("use_auto_smooth" in entry.symbol for entry in result.matched_drift), (
        f"drift not matched; traceback: {result.traceback_text}"
    )
