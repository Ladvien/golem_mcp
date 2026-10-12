"""A turn stopped at a seam (the token budget, OT-17) leaves the
history consistent.

Consistency matters more than speed here: an OpenAI-protocol backend
(llama-swap, OpenRouter) rejects a conversation where an assistant
tool_call has no tool result, so a stop that just returned would
poison every later turn of the session.
"""

import dataclasses

from blended.agent.claude_code import TurnCost
from blended.agent.outcome import ToolOutcome

TWO_CALL_REPLY = {
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {
            "id": "call_1",
            "function": {"name": "run_python", "arguments": {"source": "a = 1"}},
        },
        {
            "id": "call_2",
            "function": {"name": "run_python", "arguments": {"source": "b = 2"}},
        },
    ],
}
ANSWER_REPLY = {"role": "assistant", "content": "done"}


class ScriptedClient:
    def __init__(self, replies):
        from blended.agent.loop import ModelConfig

        self.replies = list(replies)

        self.spent = TurnCost()
        self.config = dataclasses.replace(
            ModelConfig.from_environment(), model="scripted", vision_model=""
        )

    def chat(self, messages, tools=None):
        return self.replies.pop(0)


# --- the token budget (OT-17): the loop stops at the seam --------------------


class SpendingClient(ScriptedClient):
    """Bills a fixed number of tokens per chat call, like a real lane."""

    def __init__(self, replies, tokens_per_call: int):
        super().__init__(replies)
        self.tokens_per_call = tokens_per_call

    def chat(self, messages, tools=None):
        self.spent = self.spent.plus(
            TurnCost(api_calls=1, input_tokens=self.tokens_per_call)
        )
        return super().chat(messages, tools)


def test_the_turn_stops_at_the_seam_when_the_token_budget_is_exceeded(tmp_path):
    from blended.agent.loop import TOKEN_CAP_TOOL_RESULT, AgentSession

    session = AgentSession(
        client=SpendingClient(
            [TWO_CALL_REPLY, TWO_CALL_REPLY, ANSWER_REPLY], tokens_per_call=1_000
        ),
        maximum_turn_tokens=1_500,
    )
    executed = []

    def dispatch(tool_name, arguments, output_directory):
        executed.append(arguments["source"])
        return ToolOutcome("ok")

    session.dispatch = dispatch
    answer = session.send("build two things")

    # Reply 1 (1,000 tokens) ran both calls; reply 2 took the turn to
    # 2,000 > 1,500, so its calls were answered "not run" and the turn stopped.
    assert executed == ["a = 1", "b = 2"]
    assert (
        answer
        == "Stopped after 2,000 tokens in one turn (budget 1,500) without reaching an answer. Tell me how to narrow this."
    )
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert [m["content"] for m in tool_messages] == [
        "ok",
        "ok",
        TOKEN_CAP_TOOL_RESULT,
        TOKEN_CAP_TOOL_RESULT,
    ]


def test_an_answer_over_budget_is_still_returned(tmp_path):
    """The budget refuses MORE tool calls; a reply that already answers
    ends the turn whatever it cost."""
    from blended.agent.loop import AgentSession

    session = AgentSession(
        client=SpendingClient([ANSWER_REPLY], tokens_per_call=5_000),
        maximum_turn_tokens=100,
    )
    assert session.send("hi") == "done"


def test_the_budget_is_per_turn_not_per_session(tmp_path):
    from blended.agent.loop import AgentSession

    session = AgentSession(
        client=SpendingClient(
            [ANSWER_REPLY, TWO_CALL_REPLY, ANSWER_REPLY], tokens_per_call=900
        ),
        maximum_turn_tokens=1_000,
    )
    session.dispatch = lambda *a: ToolOutcome("ok")
    session.send("turn one")  # 900 spent for the session
    assert (
        session.send("turn two") == "done"
    )  # 900 this turn, under budget, so its calls ran
