"""Regression tests for the harness_core review (2026-10-07). Needs bpy."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_chunk_calling_sys_exit_is_reported_in_process(empty_scene):
    from blended.run.executor import run_source_in_process

    result = run_source_in_process("import sys\nsys.exit(3)")
    assert not result.ok
    assert result.error_type == "SystemExit"
