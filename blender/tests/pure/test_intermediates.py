"""OT-5: the per-turn ledger of unlinked intermediates, and the loop's
refusal to end a turn while one is unresolved. Pure: fake dispatchers."""

from __future__ import annotations

import dataclasses

from blended.agent.claude_code import TurnCost
from blended.agent.intermediates import (
    UNRESOLVED_INTERMEDIATES_REFUSAL,
    IntermediateLedger,
)
from blended.agent.outcome import ToolOutcome


def test_the_ledger_debits_before_it_credits():
    ledger = IntermediateLedger()
    ledger.record(
        "add_box",
        ToolOutcome(
            "OK", intermediates_resolved=("Cutter",), intermediates_created=("Cutter",)
        ),
    )
    assert ledger.pending == {"Cutter": "add_box"}
    # A rebuild by the same name resolves the old entry and re-creates it.
    ledger.record(
        "add_box",
        ToolOutcome(
            "OK", intermediates_resolved=("Cutter",), intermediates_created=("Cutter",)
        ),
    )
    assert ledger.pending == {"Cutter": "add_box"}
    ledger.record(
        "boolean_difference",
        ToolOutcome("OK", intermediates_resolved=("Body", "Cutter")),
    )
    assert ledger.pending == {}
    assert ledger.refusal() == ""


def test_the_refusal_names_every_pending_intermediate_and_its_creator():
    ledger = IntermediateLedger()
    ledger.record("add_box", ToolOutcome("OK", intermediates_created=("A",)))
    ledger.record("add_cylinder", ToolOutcome("OK", intermediates_created=("B",)))
    refusal = ledger.refusal()
    assert refusal == UNRESOLVED_INTERMEDIATES_REFUSAL.format(
        pending="'A' (from add_box), 'B' (from add_cylinder)"
    )


def _client(replies):
    from blended.agent.loop import ModelConfig

    class Scripted:
        def __init__(self):
            self.replies = list(replies)
            self.spent = TurnCost()
            self.config = dataclasses.replace(
                ModelConfig.from_environment(), model="scripted", vision_model=""
            )

        def chat(self, messages, tools=None):
            return self.replies.pop(0)

    return Scripted()


def _call(tool_name, **arguments):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": tool_name, "arguments": arguments}}],
    }


def test_the_loop_refuses_an_answer_while_an_intermediate_is_pending(tmp_path):
    """add_box (ungated) then an answer: refused, the model resolves it
    with remove_object_and_mesh, then the same answer is accepted."""
    from blended.agent.loop import AgentSession

    def dispatch(tool_name, arguments, output_directory):
        if tool_name == "add_box":
            return ToolOutcome(
                "OK: add_box",
                intermediates_resolved=(arguments["name"],),
                intermediates_created=(arguments["name"],),
            )
        if tool_name == "remove_object_and_mesh":
            return ToolOutcome(
                "OK: remove_object_and_mesh",
                intermediates_resolved=(arguments["object_name"],),
            )
        raise AssertionError(tool_name)

    answer_reply = {"role": "assistant", "content": "Done."}
    session = AgentSession(
        client=_client(
            [
                _call("add_box", name="Cutter", width_m=0.1, depth_m=0.1, height_m=0.1),
                answer_reply,
                _call("remove_object_and_mesh", object_name="Cutter"),
                answer_reply,
            ]
        ),
        output_directory=tmp_path,
        dispatch=dispatch,
    )
    events = []
    answer = session.send(
        "Make a cutter.", on_event=lambda kind, text: events.append((kind, text))
    )

    assert answer == "Done."
    refusals = [
        text
        for kind, text in events
        if kind == "result" and text.startswith("Cannot end the turn")
    ]
    assert len(refusals) == 1 and "'Cutter' (from add_box)" in refusals[0]
    # The refusal reached the model as the next user message, in order.
    roles = [m["role"] for m in session.messages]
    assert roles == [
        "system",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert session.messages[5]["content"] == refusals[0]


def test_a_refusal_counts_against_the_budget_so_a_stubborn_model_terminates(tmp_path):
    from blended.agent.loop import AgentSession

    def dispatch(tool_name, arguments, output_directory):
        return ToolOutcome("OK: add_box", intermediates_created=("Cutter",))

    answer_reply = {"role": "assistant", "content": "Done."}
    session = AgentSession(
        client=_client(
            [_call("add_box", name="Cutter", width_m=0.1, depth_m=0.1, height_m=0.1)]
            + [answer_reply] * 10
        ),
        output_directory=tmp_path,
        dispatch=dispatch,
        maximum_tool_calls_per_turn=3,
    )
    answer = session.send("Make a cutter.")
    assert answer.startswith("Stopped after 3 tool calls")
