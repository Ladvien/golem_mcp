"""OT-25: the core op set is derived from gate-passing runs and pinned;
the offered set is service tools + readers + core; its fingerprint moves
when it changes."""

from __future__ import annotations

import json
from pathlib import Path

from blended.agent.tool_disclosure import (
    MINIMUM_BRIEFS_USING_OP,
    core_ops,
    derive_core_ops,
    offered_fingerprint,
    offered_tools,
    reader_ops,
    write_core_module,
)
from blended.agent.tools import (
    SERVICE_TOOL_NAMES,
    TOOL_SCHEMAS,
    TOOL_SCHEMAS_FINGERPRINT,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _record(brief, passed, *events):
    return {
        "brief_name": brief,
        "form_gate_passed": passed,
        "tool_events": [{"tool_name": n, "ok": ok} for n, ok in events],
    }


def test_the_core_is_scene_changing_ops_used_in_enough_passing_briefs():
    assert MINIMUM_BRIEFS_USING_OP == 2
    records = [
        _record(
            "a", True, ("add_box", True), ("rig_report", True), ("boolean_union", True)
        ),
        _record("b", True, ("add_box", True), ("boolean_union", False)),
        _record(
            "c", False, ("boolean_union", True), ("add_lathe", True)
        ),  # failed the gate: no vote
        _record("d", True, ("add_lathe", True)),
    ]
    assert derive_core_ops(records) == (
        "add_box",
    )  # boolean_union: one passing brief succeeded; rig_report: a reader


def test_the_generated_module_equals_the_derivation_from_the_real_log():
    records = [
        json.loads(l)
        for l in (REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl")
        .read_text()
        .splitlines()
        if l.strip()
    ]
    assert core_ops() == derive_core_ops(records)


def test_the_offered_set_is_service_readers_and_core_and_is_fingerprinted():
    core = ("add_box", "link_into_scene")
    offered = offered_tools(TOOL_SCHEMAS, core, SERVICE_TOOL_NAMES)
    names = [t["function"]["name"] for t in offered]
    assert set(names) == set(SERVICE_TOOL_NAMES) | set(reader_ops()) | set(core)
    assert "boolean_union" not in names and "search_ops" in names
    assert offered_fingerprint(offered) != TOOL_SCHEMAS_FINGERPRINT
    assert offered_fingerprint(offered) == offered_fingerprint(
        offered_tools(TOOL_SCHEMAS, core, SERVICE_TOOL_NAMES)
    )


def test_the_generated_module_round_trips(tmp_path):
    write_core_module(
        ("add_box", "link_into_scene"),
        {"add_box": 3, "link_into_scene": 5},
        tmp_path / "core_tools.py",
    )
    namespace: dict = {}
    exec((tmp_path / "core_tools.py").read_text(), namespace)  # noqa: S102 - the generated module is the artifact under test
    assert namespace["CORE_OPS"] == ("add_box", "link_into_scene")
    assert "GENERATED" in (tmp_path / "core_tools.py").read_text()


# --- the loop offers the disclosed set and records what it offered ---

from blended.agent.outcome import ToolOutcome
from blended.agent.tool_event import TOOL_EVENT_KIND, decode_tool_event
from blended.stages import STAGE_DONE


class _RecordingClient:
    """Replays assistant messages and records the TOOLS each call showed."""

    def __init__(self, replies):
        import dataclasses

        from blended.agent.claude_code import TurnCost
        from blended.agent.loop import ModelConfig

        self.replies = list(replies)
        self.spent = TurnCost()
        self.seen_tools = []
        self.config = dataclasses.replace(
            ModelConfig.from_environment(), model="scripted", vision_model=""
        )

    def chat(self, messages, tools=None):
        self.seen_tools.append([t["function"]["name"] for t in tools])
        return self.replies.pop(0)


def _call(name, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


def _ok(name, **validated):
    return ToolOutcome(
        f"OK: {name}", ok=True, stage_reached=STAGE_DONE, validated_arguments=validated
    )


def test_the_client_is_shown_service_readers_and_core_and_nothing_else(tmp_path):
    from blended.agent.loop import AgentSession

    client = _RecordingClient([{"role": "assistant", "content": "nothing to build"}])
    session = AgentSession(
        client=client, output_directory=tmp_path, dispatch=lambda *a: _ok("x")
    )
    session.send("hello")

    (shown,) = client.seen_tools
    assert set(shown) == set(SERVICE_TOOL_NAMES) | set(reader_ops()) | set(core_ops())
    assert len(shown) < len(TOOL_SCHEMAS)
    assert (
        "boolean_union" not in shown and "search_ops" in shown
    )  # undisclosed; the way to find it
    assert session.offered_tools_fingerprint() == offered_fingerprint(
        session.offered_tools()
    )


def test_a_withheld_tool_leaves_the_offered_set_too(tmp_path):
    from blended.agent.loop import AgentSession

    client = _RecordingClient([{"role": "assistant", "content": "ok"}])
    session = AgentSession(
        client=client,
        output_directory=tmp_path,
        dispatch=lambda *a: _ok("x"),
        disabled_tools=frozenset({"run_python"}),
    )
    session.send("hello")
    assert "run_python" not in client.seen_tools[0]
    assert (
        session.offered_tools_fingerprint()
        != AgentSession(
            client=client, output_directory=tmp_path, dispatch=lambda *a: _ok("x")
        ).offered_tools_fingerprint()
    )


def test_an_undisclosed_op_dispatches_by_name_after_search_ops(tmp_path):
    """The offered schemas shrink; the door does not. A model that found
    `boolean_union` through search_ops calls it like any other op."""
    from blended.agent.loop import AgentSession

    dispatched = []

    def dispatch(tool_name, arguments, output_directory):
        dispatched.append(tool_name)
        if tool_name == "search_ops":
            return _ok("search_ops", query="union")
        return _ok(tool_name, **arguments)

    client = _RecordingClient(
        [
            _call("search_ops", query="union"),
            _call("boolean_union", target_name="A", addend_name="B", plan_step=1),
            {"role": "assistant", "content": "Joined A and B."},
        ]
    )
    session = AgentSession(client=client, output_directory=tmp_path, dispatch=dispatch)
    events = []
    session.send("join them", on_event=lambda kind, text: events.append((kind, text)))

    assert dispatched == ["search_ops", "boolean_union"]
    assert all("boolean_union" not in shown for shown in client.seen_tools)
    structured = [
        decode_tool_event(text) for kind, text in events if kind == TOOL_EVENT_KIND
    ]
    assert [e.tool_name for e in structured] == ["search_ops", "boolean_union"]
    # Every event names the set the model was SHOWN, so a record from
    # this surface is distinguishable from one made on the whole set.
    assert {e.offered_tools_fingerprint for e in structured} == {
        session.offered_tools_fingerprint()
    }
    assert (
        structured[0].offered_tools_fingerprint.startswith("t:")
        and structured[0].offered_tools_fingerprint != TOOL_SCHEMAS_FINGERPRINT
    )


def test_the_cli_envelope_admits_an_undisclosed_op_by_name():
    from blended.agent.claude_code import envelope_schema
    from blended.agent.tools import OP_FUNCTIONS

    offered = offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
    variants = envelope_schema(offered)["properties"]["tool_calls"]["items"]["oneOf"]
    pinned = [v for v in variants if "const" in v["properties"]["name"]]
    (catch_all,) = [v for v in variants if "enum" in v["properties"]["name"]]
    assert len(pinned) == len(offered)
    offered_names = {t["function"]["name"] for t in offered}
    assert (
        set(catch_all["properties"]["name"]["enum"])
        == set(OP_FUNCTIONS) - offered_names
    )
    assert catch_all["properties"]["arguments"] == {"type": "object"}
    # The whole set needs no catch-all: nothing is undisclosed.
    whole = envelope_schema(TOOL_SCHEMAS)["properties"]["tool_calls"]["items"]["oneOf"]
    assert len(whole) == len(TOOL_SCHEMAS)
