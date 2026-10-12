"""OT-8 / CNV-11: a scored iteration replays from an op-call sequence
with no run_python present, through the same binding and gate the loop
used, and the service tools that change nothing are skipped."""

import json

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


def _recorded(tool_name: str, **arguments) -> str:
    return f"{tool_name}({json.dumps(arguments)})"


PLANTER_RECORD = {
    "iteration": 999,
    "brief_name": "planter_box",
    "refinement_locality": [],
    "tool_calls": [
        _recorded("declare_plan", steps=["build", "hollow", "drain", "material"]),
        _recorded(
            "add_box",
            name="PlanterBox",
            width_m=0.3,
            depth_m=0.2,
            height_m=0.25,
            plan_step=1,
        ),
        _recorded("link_into_scene", object_name="PlanterBox", plan_step=1),
        _recorded(
            "add_box",
            name="InnerCavity",
            width_m=0.26,
            depth_m=0.16,
            height_m=0.28,
            location_m=[0.0, 0.0, 0.02],
            plan_step=2,
        ),
        _recorded("link_into_scene", object_name="InnerCavity", plan_step=2),
        _recorded(
            "boolean_difference",
            target_name="PlanterBox",
            cutter_name="InnerCavity",
            plan_step=2,
        ),
        _recorded("inspect_object", object_name="PlanterBox"),
        _recorded(
            "add_cylinder",
            name="DrainCutter",
            radius_m=0.015,
            height_m=0.06,
            location_m=[0.0, 0.0, -0.01],
            plan_step=3,
        ),
        _recorded("link_into_scene", object_name="DrainCutter", plan_step=3),
        _recorded(
            "boolean_difference",
            target_name="PlanterBox",
            cutter_name="DrainCutter",
            plan_step=3,
        ),
        _recorded(
            "assign_material",
            object_name="PlanterBox",
            name="PlanterWood",
            base_color_rgb=[0.55, 0.35, 0.2],
            roughness=0.8,
            plan_step=4,
        ),
        _recorded("render_views", object_name="PlanterBox"),
    ],
}


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_an_op_call_sequence_replays_to_a_scored_pass(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import calls_from, replay_record, sources_from

    assert sources_from(PLANTER_RECORD) == []  # no run_python anywhere
    assert len(calls_from(PLANTER_RECORD)) == 12
    replayed = []
    built = replay_record(
        PLANTER_RECORD,
        ("PlanterBox",),
        on_chunk=lambda i, n, r: replayed.append((i, n, r.ok)),
    )

    assert [index for index, _, _ in replayed] == list(
        range(1, 10)
    )  # 12 calls, 3 skipped
    assert {total for _, total, _ in replayed} == {9}
    assert all(ok for _, _, ok in replayed)
    assert [obj.name for obj in built] == ["PlanterBox"]
    brief = get_brief("planter_box")
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)


def test_a_replay_that_builds_nothing_is_loud(empty_scene):
    from blended.evaluate.replay import ReplayProducedNothing, replay_record

    record = {"tool_calls": [_recorded("list_scene")], "refinement_locality": []}
    with pytest.raises(ReplayProducedNothing):
        replay_record(record, ("PlanterBox",))
