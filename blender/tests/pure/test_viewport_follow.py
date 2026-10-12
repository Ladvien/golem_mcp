"""Which objects the MCP bridge frames after a scene-changing call.

The framing itself needs a GUI Blender: `make test-viewport-gui`.
"""

from blended.agent.outcome import ToolOutcome
from blended.viewport_follow import frame_target_names


def _gate(object_name: str) -> dict:
    return {"object_name": object_name}


def test_gated_op_frames_its_gated_object_once() -> None:
    outcome = ToolOutcome(
        "ok", gates=(_gate("Crate"),), intermediates_resolved=("Crate",)
    )
    assert frame_target_names(outcome) == ("Crate",)


def test_boolean_names_target_and_cutter_in_order() -> None:
    # The consumed cutter is listed; Blender drops it as not in the scene.
    outcome = ToolOutcome(
        "ok", gates=(_gate("Planter"),), intermediates_resolved=("Planter", "Hole")
    )
    assert frame_target_names(outcome) == ("Planter", "Hole")


def test_run_python_frames_only_its_gated_object() -> None:
    assert frame_target_names(ToolOutcome("ok", gates=(_gate("Stool"),))) == ("Stool",)


def test_a_gate_without_an_object_names_nothing() -> None:
    assert frame_target_names(ToolOutcome("ok", gates=(_gate(""),))) == ()


def test_failed_call_still_names_what_it_touched() -> None:
    # The user should see a failure too: the scene may already have changed.
    outcome = ToolOutcome("FAILED", ok=False, intermediates_resolved=("Leg",))
    assert frame_target_names(outcome) == ("Leg",)


def test_unlinked_constructor_result_is_named_for_blender_to_filter() -> None:
    # add_box's `name` parameter: the box is not in the scene until
    # link_into_scene, and frame_in_viewports says so instead of failing.
    outcome = ToolOutcome(
        "ok", intermediates_created=("Box",), intermediates_resolved=("Box",)
    )
    assert frame_target_names(outcome) == ("Box",)


def test_the_viewport_line_names_a_few_objects_then_counts_the_rest():
    """A call that changed two hundred objects must not answer with two hundred names."""
    from blended.viewport_follow import MAXIMUM_NAMES_ON_LINE, _framed_line

    names = tuple(f"Part{index}" for index in range(MAXIMUM_NAMES_ON_LINE + 5))

    line = _framed_line(names, 2)

    assert line == (
        "viewport: framed "
        + ", ".join(names[:MAXIMUM_NAMES_ON_LINE])
        + " and 5 more in 2 3D viewport(s)"
    )
    assert _framed_line(("Crate",), 1) == "viewport: framed Crate in 1 3D viewport(s)"
