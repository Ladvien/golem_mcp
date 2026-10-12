"""print() must reach the agent.

Measured 2026-08-22 (iteration 1, planter_box, prompt v1): the agent had
no way to read a value out of the scene, because run_python discarded
stdout and returned only "Executed OK". It responded by raising
RuntimeError with the value in the message — smuggling observations out
through the traceback, one wasted tool call per value, each one landing
in its context as a FAILURE.

That is an agent-computer-interface defect, not a prompt defect, so the
fix is code and these are the assertions that keep it fixed.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_stdout_is_captured_on_success(empty_scene):
    from blended.run.executor import run_source_in_process

    result = run_source_in_process("print('triangles=124')")
    assert result.ok
    assert result.stdout_text == "triangles=124"
    assert "triangles=124" in result.summary()


def test_stdout_is_captured_even_when_the_chunk_raises(empty_scene):
    """The values printed before a failure are the diagnosis."""
    from blended.run.executor import run_source_in_process

    result = run_source_in_process("print('reached step 2')\nraise ValueError('boom')")
    assert not result.ok
    assert result.stdout_text == "reached step 2"
    assert "reached step 2" in result.summary()


def test_stdout_window_is_bounded_and_keeps_the_tail(empty_scene):
    from blended.run.executor import MAXIMUM_STDOUT_CHARACTERS, run_source_in_process

    result = run_source_in_process(
        f"print('x' * {MAXIMUM_STDOUT_CHARACTERS * 2})\nprint('CONCLUSION')"
    )
    assert result.ok
    assert "CONCLUSION" in result.stdout_text
    assert "earlier characters dropped" in result.stdout_text
    assert len(result.stdout_text) < MAXIMUM_STDOUT_CHARACTERS * 2


def test_run_python_tool_returns_printed_output(empty_scene, tmp_path):
    """The channel has to survive all the way to the tool result the
    model actually reads."""
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool(
        "run_python",
        {
            "source": "print('component_count=1')",
            "reason": "test fixture: exercising the hatch",
        },
        output_directory=tmp_path,
    )
    text, images = _outcome.text, list(_outcome.images)
    assert "component_count=1" in text
    assert images == []


def test_run_python_tool_says_so_when_nothing_was_printed(empty_scene, tmp_path):
    """Silence must be explicit, or the agent cannot tell 'printed
    nothing' from 'printing does not work here'."""
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool(
        "run_python",
        {"source": "value = 1 + 1", "reason": "test fixture: exercising the hatch"},
        output_directory=tmp_path,
    )
    text, _ = _outcome.text, list(_outcome.images)
    assert "(nothing printed)" in text


def test_gated_run_python_also_carries_printed_output(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    source = (
        "import bpy\n"
        "from blended.ops.primitives import add_box, link_into_scene\n"
        "box = add_box('Probe', 0.1, 0.1, 0.1)\n"
        "link_into_scene(box)\n"
        "print('vertices=%d' % len(bpy.data.objects[box].data.vertices))\n"
    )
    _outcome = dispatch_tool(
        "run_python",
        {
            "source": source,
            "object_name": "Probe",
            "reason": "test fixture: exercising the hatch",
        },
        output_directory=tmp_path,
    )
    text, _images = _outcome.text, list(_outcome.images)
    assert "vertices=8" in text
