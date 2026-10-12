"""The task loop with deterministic stand-in agents."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

GOOD_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene
widget = add_box("Widget", 0.5, 0.5, 0.5)
link_into_scene(widget)
"""

DISCONNECTED_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene
import bmesh, bpy
first = add_box("Widget", 0.5, 0.5, 0.5)
link_into_scene(first)
second = add_box("Far", 0.5, 0.5, 0.5, location_m=(3.0, 0.0, 0.0))
link_into_scene(second)
working = bmesh.new(); working.from_mesh(bpy.data.objects[first].data); working.from_mesh(bpy.data.objects[second].data)
working.to_mesh(bpy.data.objects[first].data); working.free()
"""


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_task_succeeds_first_round(empty_scene, tmp_path):
    from blended.harness import HarnessSettings
    from blended.task import AgentTask, run_agent_task

    task = AgentTask(object_name="Widget", description="Build a widget.")
    result = run_agent_task(
        task,
        write_code=lambda prompt: GOOD_SOURCE,
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert result.ok
    assert result.rounds_used == 1
    assert result.feedback_given == ()


def test_agent_recovers_using_gate_feedback(empty_scene, tmp_path):
    """The recovery path: round one fails the gate, the feedback names
    the cause, round two fixes it."""
    from blended.harness import HarnessSettings
    from blended.task import AgentTask, run_agent_task

    prompts_seen = []

    def write_code(prompt: str) -> str:
        prompts_seen.append(prompt)
        return DISCONNECTED_SOURCE if len(prompts_seen) == 1 else GOOD_SOURCE

    task = AgentTask(object_name="Widget", description="Build a widget.")
    result = run_agent_task(
        task, write_code, settings=HarnessSettings(output_directory=tmp_path)
    )

    assert result.ok
    assert result.rounds_used == 2
    # The second prompt was feedback, and it named the real cause.
    assert "components means your parts are not touching" in prompts_seen[1]


def test_task_escalates_after_the_cap(empty_scene, tmp_path):
    from blended.harness import HarnessSettings
    from blended.task import AgentTask, run_agent_task

    task = AgentTask(object_name="Widget", description="Build a widget.")
    result = run_agent_task(
        task,
        write_code=lambda prompt: DISCONNECTED_SOURCE,
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.rounds_used == 3
    assert "ESCALATE TO HUMAN" in result.summary()
    # A human gets a reviewable sheet with the escalation.
    assert result.final.contact_sheet_path.exists()
