"""The agent loop against real bpy, with a scripted model.

The model is stubbed so the LOOP is what's under test: does it dispatch
tools, attach rendered images, feed results back, and terminate.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

BUILD_SOURCE = """
from blended.ops import add_box, link_into_scene
crate = add_box("ChatCrate", 0.6, 0.6, 0.6)
link_into_scene(crate)
"""


class ScriptedClient:
    """Replays a fixed list of assistant messages.

    Configured single-model (no separate eye) so these tests exercise
    the direct image-attachment path; the writer/eye split has its own
    tests below.
    """

    def __init__(self, replies):
        import dataclasses

        from blended.agent import ModelConfig
        from blended.agent.claude_code import TurnCost

        self.replies = list(replies)
        self.seen_messages = []
        self.spent = TurnCost()
        self.config = dataclasses.replace(
            ModelConfig.from_environment(),
            model="vision-writer",
            vision_model="",
        )

    def chat(self, messages, tools=None):
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_loop_runs_a_tool_then_answers(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": BUILD_SOURCE,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "ChatCrate",
                            },
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Built ChatCrate — gate passed."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)

    answer = session.send("Make me a crate.")

    assert "gate passed" in answer
    assert "ChatCrate" in bpy.data.objects
    # The tool result was fed back to the model as a tool message.
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert (
        "GATE: PASS" in tool_messages[0]["content"]
        or "gate: PASS" in tool_messages[0]["content"]
    )


def test_render_result_attaches_an_image_the_model_can_see(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": BUILD_SOURCE,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "ChatCrate",
                            },
                        }
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "render_views",
                            "arguments": {"object_name": "ChatCrate"},
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Looks like a crate."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and show me.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    render_message = tool_messages[-1]
    assert "images" in render_message, "the model was told to look but got no image"
    assert len(render_message["images"]) == 1
    assert len(render_message["images"][0]) > 1000  # real base64 payload


def test_gate_failure_is_reported_to_the_model(empty_scene, tmp_path):
    from blended.agent import AgentSession

    open_box_source = """
import bmesh
import bpy
from blended.ops import add_box, link_into_scene
box = add_box("BadCrate", 0.5, 0.5, 0.5)
link_into_scene(box)
w = bmesh.new(); w.from_mesh(bpy.data.objects[box].data)
w.faces.ensure_lookup_table(); w.faces.remove(w.faces[0])
w.to_mesh(bpy.data.objects[box].data); w.free()
"""
    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": open_box_source,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "BadCrate",
                            },
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "The gate rejected it — it's open."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "boundary edges" in tool_messages[0]["content"]


def test_tool_exception_is_surfaced_not_swallowed(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "inspect_object",
                            "arguments": {"object_name": "DoesNotExist"},
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "That object isn't in the scene."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Inspect DoesNotExist.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "No object named" in tool_messages[0]["content"]


def test_runaway_tool_calling_is_capped(empty_scene, tmp_path):
    from blended.agent import AgentSession

    looping_reply = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": "list_scene", "arguments": {}}}],
    }
    client = ScriptedClient([looping_reply] * 30)
    session = AgentSession(
        client=client, output_directory=tmp_path, maximum_tool_calls_per_turn=4
    )
    answer = session.send("Loop forever.")
    assert "Stopped after 4 tool calls" in answer


def test_the_recorded_call_is_replayable(empty_scene, tmp_path):
    """A run you cannot replay is a run you cannot diagnose.

    Measured 2026-08-22 (iteration 5): the loop emitted the first 200
    characters of each call, so the iteration log held a preview of the
    run_python source that crashed and not the source itself.
    """
    from blended.agent import AgentSession

    long_source = BUILD_SOURCE + "\n# padding\n" + ("# " + "x" * 78 + "\n") * 6
    assert len(long_source) > 400
    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": long_source,
                                "reason": "test fixture: exercising the hatch",
                            },
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Built."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    recorded = []
    session.send(
        "Build it.",
        on_event=lambda kind, text: recorded.append(text) if kind == "tool" else None,
    )

    assert len(recorded) == 1
    assert long_source.strip().splitlines()[-1] in recorded[0]


def test_the_budget_counts_calls_not_messages(empty_scene, tmp_path):
    """One assistant message can carry several tool calls.

    Measured 2026-08-22 (iteration 4): the loop counted MESSAGES while
    its field, the driver's --max-tool-calls flag and its own exhaustion
    report all said CALLS, so a run that executed 20 calls reported
    "Stopped after 16 tool calls". The count is now what was executed.
    """
    from blended.agent import AgentSession

    three_calls_at_once = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "list_scene", "arguments": {}}} for _ in range(3)
        ],
    }
    client = ScriptedClient([three_calls_at_once] * 30)
    session = AgentSession(
        client=client, output_directory=tmp_path, maximum_tool_calls_per_turn=4
    )
    answer = session.send("Loop forever, three at a time.")

    executed = len([m for m in session.messages if m.get("role") == "tool"])
    # Two messages of three: the budget is checked between messages, and
    # a message's calls are never half-answered.
    assert executed == 6
    assert f"Stopped after {executed} tool calls" in answer
    assert "budget 4" in answer


def test_search_ops_finds_operations_without_guessing(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    _outcome = dispatch_tool("search_ops", {"query": "boolean"}, tmp_path)
    result_text, images = _outcome.text, list(_outcome.images)
    assert "boolean_union" in result_text
    assert images == []

    _outcome = dispatch_tool("search_ops", {"query": "zzzz"}, tmp_path)
    miss_text, _ = _outcome.text, list(_outcome.images)
    assert "No operation matches" in miss_text


def test_export_tool_verifies_the_written_file(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool
    from blended.builders import CrateBuilder, CrateParameters

    CrateBuilder(CrateParameters(name="ExportMe")).build()
    _outcome = dispatch_tool(
        "export_asset",
        {
            "object_name": "ExportMe",
            "path": str(tmp_path / "crate.glb"),
            "blend_path": str(tmp_path / "crate.blend"),
        },
        tmp_path,
    )
    result_text, _ = _outcome.text, list(_outcome.images)
    assert "Exported and verified" in result_text
    assert (tmp_path / "crate.glb").exists()
    assert (tmp_path / "crate.blend").exists()
    assert str(tmp_path / "crate.blend") in result_text


# --- the writer/eye split --------------------------------------------------


class TwoModelClient:
    """Records which model each call went to, so routing is verifiable."""

    def __init__(
        self, config, writer_replies, eye_reply="A wooden crate, evenly proportioned."
    ):
        self.config = config
        self.writer_replies = list(writer_replies)
        self.eye_reply = eye_reply
        self.calls: list[tuple[str, bool]] = []  # (model, had_images)
        # Part of the client contract since 2026-09-06: the eye folds
        # its usage back into the client that owns the run, so a double
        # that stands in for one has to carry the accumulator.
        from blended.agent.claude_code import TurnCost

        self.spent = TurnCost()

    def chat(self, messages, tools=None):
        had_images = any("images" in message for message in messages)
        self.calls.append((self.config.model, had_images))
        if self.config.model == "eye-model":
            return {"role": "assistant", "content": self.eye_reply}
        return self.writer_replies.pop(0)


def _split_config():
    import dataclasses

    from blended.agent import ModelConfig

    return dataclasses.replace(
        ModelConfig.from_environment(),
        model="writer-model",
        vision_model="eye-model",
    )


def test_writer_never_receives_raw_images(empty_scene, tmp_path, monkeypatch):
    """deepseek-v4-flash is text-only — handing it image bytes is a bug."""
    import blended.agent.loop as loop_module
    from blended.agent import AgentSession

    config = _split_config()
    client = TwoModelClient(
        config,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": BUILD_SOURCE,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "ChatCrate",
                            },
                        }
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "render_views",
                            "arguments": {
                                "object_name": "ChatCrate",
                                "look_for": "is it square?",
                            },
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Built and checked."},
        ],
    )
    # The eye builds its own client from the same config; point it here.
    monkeypatch.setattr(
        loop_module,
        "OllamaClient",
        lambda cfg: TwoModelClient(
            cfg, [], eye_reply="A cube-shaped crate, square in all views."
        ),
    )

    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and look at it.")

    # No message anywhere in the writer's history carries image data.
    assert not any("images" in message for message in session.messages), (
        "raw images leaked into a text-only writer's context"
    )
    # But the description DID reach it.
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "what the render shows" in tool_messages[-1]["content"]
    assert "square in all views" in tool_messages[-1]["content"]


def test_eye_failure_degrades_without_killing_the_turn(
    empty_scene, tmp_path, monkeypatch
):
    import blended.agent.loop as loop_module
    from blended.agent import AgentSession

    def exploding_client(cfg):
        raise RuntimeError("eye endpoint unreachable")

    config = _split_config()
    client = TwoModelClient(
        config,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": BUILD_SOURCE,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "ChatCrate",
                            },
                        }
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "render_views",
                            "arguments": {"object_name": "ChatCrate"},
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Gate passed; could not see the render."},
        ],
    )
    monkeypatch.setattr(loop_module, "OllamaClient", exploding_client)

    session = AgentSession(client=client, output_directory=tmp_path)
    answer = session.send("Make a crate and look at it.")

    assert answer  # the turn still completed
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "working blind" in tool_messages[-1]["content"]


def test_single_model_mode_still_attaches_images(empty_scene, tmp_path):
    """With a vision-capable writer and no separate eye, images go
    straight into the conversation as before."""
    import dataclasses

    from blended.agent import AgentSession, ModelConfig

    config = dataclasses.replace(
        ModelConfig.from_environment(), model="vision-writer", vision_model=""
    )
    client = TwoModelClient(
        config,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_python",
                            "arguments": {
                                "source": BUILD_SOURCE,
                                "reason": "test fixture: exercising the hatch",
                                "object_name": "ChatCrate",
                            },
                        }
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "render_views",
                            "arguments": {"object_name": "ChatCrate"},
                        }
                    }
                ],
            },
            {"role": "assistant", "content": "Looks right."},
        ],
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and look.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "images" in tool_messages[-1]


# Measured 2026-08-22: a cloud model proxied through a local daemon
# answered a one-token ping in 23.3 s from cold.
OBSERVED_COLD_START_SECONDS = 23.3


def test_preflight_timeout_allows_a_cold_start():
    """A preflight shorter than a cold start reports a working backend
    as dead, and the driver then refuses to score the run."""
    from blended.agent.loop import (
        PREFLIGHT_TIMEOUT_SECONDS,
        REQUEST_TIMEOUT_SECONDS,
    )

    assert PREFLIGHT_TIMEOUT_SECONDS > OBSERVED_COLD_START_SECONDS
    assert PREFLIGHT_TIMEOUT_SECONDS < REQUEST_TIMEOUT_SECONDS


# --- op tools (OT-4): a brief to gate-pass with no run_python at all ---------


def _op_call(tool_name: str, **arguments) -> dict:
    return {"function": {"name": tool_name, "arguments": arguments}}


PLANTER_OP_CALLS = [
    # The golden planter recipe (iteration 66), as op calls instead of
    # a chunk: outer box, inner cavity, drain cutter, two differences,
    # a material. Every number is the brief's.
    _op_call("add_box", name="PlanterBox", width_m=0.3, depth_m=0.2, height_m=0.25),
    _op_call("link_into_scene", object_name="PlanterBox"),
    _op_call(
        "add_box",
        name="InnerCavity",
        width_m=0.26,
        depth_m=0.16,
        height_m=0.28,
        location_m=[0.0, 0.0, 0.02],
    ),
    _op_call("link_into_scene", object_name="InnerCavity"),
    _op_call("boolean_difference", target_name="PlanterBox", cutter_name="InnerCavity"),
    _op_call(
        "add_cylinder",
        name="DrainCutter",
        radius_m=0.015,
        height_m=0.06,
        location_m=[0.0, 0.0, -0.01],
    ),
    _op_call("link_into_scene", object_name="DrainCutter"),
    _op_call("boolean_difference", target_name="PlanterBox", cutter_name="DrainCutter"),
    _op_call(
        "assign_material",
        object_name="PlanterBox",
        name="PlanterWood",
        base_color_rgb=[0.55, 0.35, 0.2],
        roughness=0.8,
    ),
]


def test_a_brief_reaches_gate_pass_with_op_tools_only(empty_scene, tmp_path):
    """OT-4's acceptance: the vocabulary alone builds a brief the form
    gate passes, and every op result speaks the stage vocabulary."""
    from blended.agent import AgentSession
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    client = ScriptedClient(
        [
            {"role": "assistant", "content": "", "tool_calls": PLANTER_OP_CALLS},
            {"role": "assistant", "content": "Built PlanterBox with op tools."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)

    answer = session.send("Build the planter.")

    assert "op tools" in answer
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert [m["tool_name"] for m in tool_messages] == [
        c["function"]["name"] for c in PLANTER_OP_CALLS
    ]
    for message in tool_messages:
        assert message["content"].startswith(f"OK: {message['tool_name']}"), message[
            "content"
        ]
    assert 'returned: "PlanterBox"' in tool_messages[0]["content"]
    # OT-5: every GATED op result carries the gate verdict; an ungated
    # constructor (unlinked intermediate) carries none, and the material
    # op returns a material name, so it is not gated either.
    for message in tool_messages:
        gated = message["tool_name"] in {"link_into_scene", "boolean_difference"}
        assert ("gate: PASS" in message["content"]) == gated, message["content"]
        assert ("orient:" in message["content"]) == gated, message["content"]

    brief = get_brief("planter_box")
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)
    assert sorted(o.name for o in bpy.context.scene.objects) == ["PlanterBox"]


def test_an_op_tool_failure_names_the_op_error_to_the_model(empty_scene, tmp_path):
    """An op's own exception (here: an unlinked boolean operand) comes back
    as a FAILED result at `execute`, not as a loop crash."""
    from blended.agent.tools import dispatch_tool

    for name in ("A", "B"):
        dispatch_tool(
            "add_box",
            {"name": name, "width_m": 0.1, "depth_m": 0.1, "height_m": 0.1},
            tmp_path,
        )
    union_result = dispatch_tool(
        "boolean_union", {"target_name": "A", "addend_name": "B"}, tmp_path
    ).text

    assert union_result.startswith("FAILED at execute: boolean_union")
    assert "UnlinkedOperand" in union_result


def test_an_unresolved_intermediate_blocks_the_answer_until_resolved(
    empty_scene, tmp_path
):
    """OT-5: add_box leaves an unlinked object; the answer is refused with
    the object named; removing it lets the same answer through."""
    from blended.agent import AgentSession

    answer = {"role": "assistant", "content": "Cutter made."}
    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    _op_call(
                        "add_box", name="Cutter", width_m=0.1, depth_m=0.1, height_m=0.1
                    )
                ],
            },
            answer,
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    _op_call("remove_object_and_mesh", object_name="Cutter")
                ],
            },
            answer,
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    events = []
    reply = session.send(
        "Make a cutter.", on_event=lambda kind, text: events.append((kind, text))
    )

    assert reply == "Cutter made."
    refusals = [text for kind, text in events if text.startswith("Cannot end the turn")]
    assert len(refusals) == 1 and "'Cutter' (from add_box)" in refusals[0]
    assert "Cutter" not in bpy.data.objects


def test_a_gated_op_on_a_missing_object_fails_at_execute(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    text = dispatch_tool("link_into_scene", {"object_name": "Ghost"}, tmp_path).text
    assert text.startswith("FAILED at execute: link_into_scene")
    assert "UnknownObject" in text


def test_a_gate_failure_on_an_op_result_is_reported_at_gate(empty_scene, tmp_path):
    """Two unconnected boxes unioned into one object: 2 components, FAIL at gate."""
    from blended.agent.tools import dispatch_tool

    for name, x in (("A", 0.0), ("B", 5.0)):
        dispatch_tool(
            "add_box",
            {
                "name": name,
                "width_m": 0.1,
                "depth_m": 0.1,
                "height_m": 0.1,
                "location_m": [x, 0.0, 0.0],
            },
            tmp_path,
        )
        dispatch_tool("link_into_scene", {"object_name": name}, tmp_path)
    text = dispatch_tool(
        "boolean_union", {"target_name": "A", "addend_name": "B"}, tmp_path
    ).text

    assert text.startswith("FAILED at gate: boolean_union"), text
    assert "gate: FAIL (24 tris, 2 components)" in text


def test_an_armature_is_gated_on_scene_state_only(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    text = dispatch_tool(
        "add_armature",
        {
            "name": "Rig",
            "bones": [{"name": "root", "head_m": [0, 0, 0], "tail_m": [0, 0, 0.5]}],
        },
        tmp_path,
    ).text
    assert text.startswith("OK: add_armature"), text
    assert "gate: scene state only (ARMATURE has no mesh to analyze)" in text


def test_an_action_op_accepts_plan_step_and_the_op_never_sees_it(empty_scene, tmp_path):
    """OT-6: plan_step rides on the call like on run_python; binding gets
    the op's own arguments only."""
    from blended.agent.tools import dispatch_tool

    text = dispatch_tool(
        "add_box",
        {
            "name": "Crate",
            "width_m": 0.5,
            "depth_m": 0.5,
            "height_m": 0.5,
            "plan_step": 1,
        },
        tmp_path,
    ).text
    assert text.startswith("OK: add_box"), text
    assert "Crate" in bpy.data.objects


# --- the gate-failure cap (OT-16) ------------------------------------------

TWO_ISLANDS_SOURCE = """
from blended.ops import add_box, link_into_scene, linear_array
add_box("Bad", 0.1, 0.1, 0.1)
link_into_scene("Bad")
linear_array("Bad", 2, (1.0, 0.0, 0.0))
"""


def test_a_builder_that_always_fails_the_gate_trips_the_cap(empty_scene, tmp_path):
    """OT-16: an applied array is two islands until something bridges
    them, so this chunk fails the gate every time. After the cap the
    turn stops with a contact sheet instead of spending the budget."""
    from blended.agent import AgentSession
    from blended.agent.loop import MAXIMUM_GATE_FAILURES_PER_OBJECT

    failing_call = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "function": {
                    "name": "run_python",
                    "arguments": {
                        "source": TWO_ISLANDS_SOURCE,
                        "object_name": "Bad",
                        "reason": "test fixture: a builder that cannot pass",
                    },
                }
            }
        ],
    }
    client = ScriptedClient(
        [failing_call] * 6 + [{"role": "assistant", "content": "Built."}]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    events = []
    answer = session.send(
        "Build it.", on_event=lambda kind, text: events.append((kind, text))
    )

    assert answer.startswith(
        f"Stopped: 'Bad' failed the gate {MAXIMUM_GATE_FAILURES_PER_OBJECT} times in a row"
    )
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert len(tool_messages) == MAXIMUM_GATE_FAILURES_PER_OBJECT
    assert all("FAILED at gate" in m["content"] for m in tool_messages)
    renders = [text for kind, text in events if kind == "render"]
    assert renders and renders[-1].endswith("Bad_sheet.png")


def test_an_undisclosed_op_found_by_search_ops_runs_through_the_real_dispatcher(
    empty_scene, tmp_path
):
    """OT-25: the model is shown the core set only; `boolean_union` is
    not in it. Searching for it and then calling it by name binds, runs
    and gates like a disclosed op — the door never shrank."""
    from blended.agent import AgentSession

    client = ScriptedClient(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    _op_call(
                        "add_box", name="Left", width_m=0.2, depth_m=0.2, height_m=0.2
                    ),
                    _op_call("link_into_scene", object_name="Left"),
                    _op_call(
                        "add_box",
                        name="Right",
                        width_m=0.2,
                        depth_m=0.2,
                        height_m=0.2,
                        location_m=[0.15, 0.0, 0.0],
                    ),
                    _op_call("link_into_scene", object_name="Right"),
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [_op_call("search_ops", query="boolean union")],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    _op_call("boolean_union", target_name="Left", addend_name="Right")
                ],
            },
            {"role": "assistant", "content": "Joined Left and Right."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path)
    offered = {t["function"]["name"] for t in session.offered_tools()}
    assert "boolean_union" not in offered and "search_ops" in offered

    answer = session.send("Join the two boxes.")

    assert "Joined" in answer
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    search, union = tool_messages[-2], tool_messages[-1]
    assert (
        search["tool_name"] == "search_ops" and "boolean_union: " in search["content"]
    )
    assert union["tool_name"] == "boolean_union" and union["content"].startswith(
        "OK: boolean_union"
    ), union["content"]
    assert "gate: PASS" in union["content"]
    assert sorted(o.name for o in bpy.context.scene.objects) == ["Left"]
