"""Agent-directed feedback: pure logic, no bpy."""

from blended.analyze.mesh_checks import MeshReport
from blended.harness import HarnessResult
from blended.task import AgentTask, build_gate_feedback

TASK = AgentTask(object_name="Widget", description="Build a widget.")


def _report(**overrides):
    base = {
        "object_name": "Widget",
        "triangle_count": 100,
        "non_manifold_edge_count": 0,
        "boundary_edge_count": 0,
        "zero_area_face_count": 0,
        "non_finite_coordinate_count": 0,
        "connected_component_count": 1,
        "duplicate_vertex_pair_count": 0,
        "self_intersecting_face_pair_count": 0,
        "flipped_normal_triangle_count": 0,
    }
    base.update(overrides)
    return MeshReport(**base)


def test_disconnected_parts_get_the_union_hint():
    result = HarnessResult(
        ok=False,
        stage_reached="gate",
        object_name="Widget",
        report=_report(connected_component_count=4),
        gate_failures=("4 disconnected components (budget 1)",),
    )
    feedback = build_gate_feedback(result, TASK)
    assert "4 components means your parts are not touching" in feedback
    assert "boolean_union" in feedback
    assert "No markdown fences" in feedback


def test_open_mesh_gets_the_watertight_hint():
    result = HarnessResult(
        ok=False,
        stage_reached="gate",
        object_name="Widget",
        report=_report(boundary_edge_count=12),
        gate_failures=("12 boundary edges (open mesh)",),
    )
    assert "not watertight" in build_gate_feedback(result, TASK)


def test_missing_object_names_the_expected_name():
    result = HarnessResult(
        ok=False,
        stage_reached="locate",
        object_name="Widget",
        execution_summary="ran fine",
    )
    feedback = build_gate_feedback(result, TASK)
    assert "`Widget`" in feedback


def test_execution_failure_forwards_the_detail():
    result = HarnessResult(
        ok=False,
        stage_reached="execute",
        execution_summary="AttributeError: no attribute 'use_auto_smooth'",
    )
    assert "use_auto_smooth" in build_gate_feedback(result, TASK)


def test_brief_carries_task_and_budget():
    task = AgentTask(
        object_name="Chair",
        description="Build a chair.",
        requirements=("four legs",),
    )
    brief = task.brief()
    assert "Build a chair." in brief
    assert "`Chair`" in brief
    assert "four legs" in brief
    assert "capability manifest" in brief  # manifest is included


def test_structural_failure_feedback_can_carry_the_manifest():
    """Feedback naming ops the agent was never told about is useless."""
    result = HarnessResult(
        ok=False,
        stage_reached="gate",
        object_name="Widget",
        report=_report(
            connected_component_count=7, self_intersecting_face_pair_count=305
        ),
        gate_failures=("7 disconnected components (budget 1)",),
    )
    without = build_gate_feedback(result, TASK)
    assert "boolean_union" in without  # names the fix
    assert "add_box(" not in without  # but not where it lives

    with_manifest = build_gate_feedback(result, TASK, include_manifest=True)
    assert "add_box(" in with_manifest  # now the agent can find it
    assert "capability manifest" in with_manifest
