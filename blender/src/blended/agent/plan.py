"""The turn plan: a numbered list of natural-language steps the agent
declares before it touches the scene, shown to the user with a progress
bar that advances as the steps run.

This is the substrate for Decision D1 of the chat-UX overhaul. The
design follows Magentic-UI (DOI 10.48550/arXiv.2507.22358): the plan is
a sequence of short, user-readable steps shared between user and agent,
with a progress bar over the steps during execution. The plan is a
shared representation, NOT an approval gate — users approve ≈93 % of
permission prompts (DOI 10.48550/arxiv.2604.14228), so gating every
turn would rubber-stamp and add latency. The agent declares, the UI
shows, the user can interrupt; nothing waits for a click.

Why a plan is worth a tool call at all: a planner/actor/critic split
with the human standing over it as supervisor measurably improves
geometric accuracy, aesthetic quality and task completion on Blender
modelling tasks over a single-prompt agent (DOI
10.48550/arxiv.2601.05016). The plan surface is the part of that split
the user can actually supervise.

The module is pure Python — no bpy — so it tests in the venv without
Blender. The loop wires it into the tool dispatch and event channel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

# The tool the model calls to declare its plan. Lives in TOOL_SCHEMAS
# alongside the action tools; dispatched through the same channel.
PLAN_TOOL_NAME = "declare_plan"
# The optional argument every ACTION tool accepts: the 1-based index of
# the plan step this call belongs to. Carried on the tool call, not the
# plan, because a step may need several tool calls to complete.
PLAN_STEP_ARGUMENT = "plan_step"
# A plan longer than this is a plan the user cannot hold in their head.
# Magentic-UI's plans are short sequences; eight is the ceiling.
MAXIMUM_PLAN_STEPS = 8


class PlanArgumentError(ValueError):
    """A declare_plan / plan_step / plan-event payload is malformed.

    A ValueError subclass: every caller that catches ValueError keeps
    working, while the type check on model-supplied JSON (a wrong JSON
    type is a malformed value here, not a programmer's TypeError) is
    named instead of silenced.
    """


# The JSON-schema property every plan-requiring tool carries.
PLAN_STEP_SCHEMA = {
    "type": "integer",
    "description": "The 1-based plan step this call belongs to.",
}


def _scene_changing_op_names() -> tuple[str, ...]:
    from blended.ops._contract import changes_scene, facade_ops

    return tuple(name for name, function in facade_ops() if changes_scene(function))


# The tools that actually change the scene and therefore require a
# declared plan first: run_python, and every op tool not marked
# `@op(reads_only=True)` (OT-6). Lookups (search_ops, list_scene) and
# readers (rig_report, orientation_reading) are plan-free — a model
# orienting itself before planning should not be blocked.
PLAN_REQUIRED_TOOLS = ("run_python", *_scene_changing_op_names())
# What a plan-requiring tool call gets back when no plan was declared
# this turn. Returned as the tool result so the model can correct itself
# on its next turn without a special protocol — it just sees a refusal
# and declares a plan.
MISSING_PLAN_REFUSAL = (
    "No plan declared this turn. Call declare_plan with your numbered "
    "steps BEFORE any tool that changes the scene, then re-issue this "
    "call."
)

# JSON keys for the (kind, text) event channel — the plan event carries
# its state as a JSON string so the panel can decode it without parsing
# free text.
_PLAN_EVENT_STEPS_KEY = "steps"
_PLAN_EVENT_CURRENT_STEP_KEY = "current_step"


@dataclass(frozen=True)
class TurnPlan:
    """A plan for one turn: ordered steps and the step now running.

    ``current_step`` is 1-based; ``0`` means declared but not started.
    Frozen so a plan can be shared with the UI without defensive copies.
    """

    steps: tuple[str, ...]
    current_step: int = 0

    def progress_fraction(self) -> float:
        """How far through the plan we are, in ``0.0..1.0``.

        ``0.0`` when declared but not started; ``1.0`` once the last
        step is running. Clamped so a malformed ``current_step`` can
        never push the bar past full — the panel must not break on a
        model that reports step 9 of 3.
        """
        if not self.steps:
            return 0.0
        step = max(0, min(self.current_step, len(self.steps)))
        return step / len(self.steps)

    def with_step(self, index: int) -> TurnPlan:
        """Return a copy with ``current_step`` set, clamped into
        ``0..len(steps)``.

        Clamps rather than raising: a model that reports a wrong step
        index must not crash the panel. But ``progress_fraction`` stays
        in ``0.0..1.0`` regardless.
        """
        clamped = max(0, min(index, len(self.steps)))
        return replace(self, current_step=clamped)

    def status_text(self) -> str:
        """One-line status for the panel, e.g. ``step 2/3``.

        ``step 0/3`` means declared, not started.
        """
        return f"step {self.current_step}/{len(self.steps)}"


def parse_plan_arguments(arguments: dict) -> TurnPlan:
    """Build a ``TurnPlan`` from the ``declare_plan`` tool arguments.

    Raises ``PlanArgumentError`` (a ``ValueError``) on every malformed input — missing steps,
    a non-list, empty or whitespace-only step strings, and more than
    ``MAXIMUM_PLAN_STEPS`` steps. Never guesses, never truncates: a
    nine-step plan is a nine-step plan, not a silently-shortened eight.
    Step strings are stripped of surrounding whitespace.
    """
    if not isinstance(arguments, dict):
        raise PlanArgumentError(
            f"declare_plan arguments must be an object, got {type(arguments).__name__}"
        )
    raw_steps = arguments.get("steps")
    if raw_steps is None:
        raise PlanArgumentError("declare_plan requires a 'steps' array.")
    if not isinstance(raw_steps, list):
        raise PlanArgumentError(
            f"declare_plan 'steps' must be an array of strings, got "
            f"{type(raw_steps).__name__}"
        )
    if not raw_steps:
        raise PlanArgumentError("declare_plan 'steps' must not be empty.")
    if len(raw_steps) > MAXIMUM_PLAN_STEPS:
        raise PlanArgumentError(
            f"declare_plan has {len(raw_steps)} steps; the maximum is "
            f"{MAXIMUM_PLAN_STEPS}."
        )
    cleaned: list[str] = []
    for position, step in enumerate(raw_steps, start=1):
        if not isinstance(step, str):
            raise PlanArgumentError(
                f"declare_plan step {position} is not a string: {type(step).__name__}."
            )
        stripped = step.strip()
        if not stripped:
            raise PlanArgumentError(
                f"declare_plan step {position} is empty or whitespace-only."
            )
        cleaned.append(stripped)
    return TurnPlan(steps=tuple(cleaned))


def plan_step_of(arguments: dict) -> int | None:
    """Extract the ``plan_step`` argument from a tool call.

    Returns ``None`` when absent. Raises ``PlanArgumentError`` (a ``ValueError``) when the value
    is present but not a positive integer — an integer-valued string is
    accepted, because some lanes stringify tool arguments.
    """
    if not isinstance(arguments, dict):
        raise PlanArgumentError(
            f"tool arguments must be an object, got {type(arguments).__name__}"
        )
    if PLAN_STEP_ARGUMENT not in arguments:
        return None
    value = arguments[PLAN_STEP_ARGUMENT]
    if isinstance(value, bool):
        # bool is an int subclass in Python; a plan_step of True is a
        # bug, not step 1.
        raise PlanArgumentError(
            f"plan_step must be a positive integer, got bool {value!r}."
        )
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            raise PlanArgumentError(
                f"plan_step must be a positive integer, got {value!r}."
            )
    if not isinstance(value, int):
        raise PlanArgumentError(
            f"plan_step must be a positive integer, got "
            f"{type(value).__name__} {value!r}."
        )
    if value < 1:
        raise PlanArgumentError(
            f"plan_step must be a positive integer (1-based), got {value}."
        )
    return value


def plan_step_or_none(arguments: dict) -> int | None:
    """The call's plan_step for the record; a malformed one is None here.
    The loop reports it on the tool result where it reads the step."""
    try:
        return plan_step_of(arguments)
    except PlanArgumentError:
        return None


def plan_required_for(tool_name: str) -> bool:
    """True when ``tool_name`` changes the scene and requires a plan."""
    return tool_name in PLAN_REQUIRED_TOOLS


def encode_plan_event(plan: TurnPlan) -> str:
    """Serialize a plan to the JSON string carried on the ``plan`` event.

    Round-trips through ``decode_plan_event``.
    """
    return json.dumps(
        {
            _PLAN_EVENT_STEPS_KEY: list(plan.steps),
            _PLAN_EVENT_CURRENT_STEP_KEY: plan.current_step,
        }
    )


def decode_plan_event(text: str) -> TurnPlan:
    """Recover a ``TurnPlan`` from a ``plan`` event's text.

    Raises ``PlanArgumentError`` (a ``ValueError``) on malformed JSON, missing keys, or steps that
    fail the same validation ``parse_plan_arguments`` enforces.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise PlanArgumentError(
            f"plan event is not valid JSON: {error.msg}."
        ) from error
    if not isinstance(payload, dict):
        raise PlanArgumentError(
            f"plan event payload must be an object, got {type(payload).__name__}."
        )
    if _PLAN_EVENT_STEPS_KEY not in payload:
        raise PlanArgumentError(
            f"plan event payload missing '{_PLAN_EVENT_STEPS_KEY}'."
        )
    if _PLAN_EVENT_CURRENT_STEP_KEY not in payload:
        raise PlanArgumentError(
            f"plan event payload missing '{_PLAN_EVENT_CURRENT_STEP_KEY}'."
        )
    steps = payload[_PLAN_EVENT_STEPS_KEY]
    current_step = payload[_PLAN_EVENT_CURRENT_STEP_KEY]
    if not isinstance(steps, list):
        raise PlanArgumentError(
            f"plan event 'steps' must be an array, got {type(steps).__name__}."
        )
    if not all(isinstance(step, str) for step in steps):
        raise PlanArgumentError("plan event 'steps' must be an array of strings.")
    if not isinstance(current_step, int) or isinstance(current_step, bool):
        raise PlanArgumentError(
            f"plan event 'current_step' must be an integer, got "
            f"{type(current_step).__name__}."
        )
    # Re-parse through parse_plan_arguments so the decode path enforces
    # the same step-content rules (empty, too many) as the encode path.
    plan = parse_plan_arguments({_PLAN_EVENT_STEPS_KEY: steps})
    # current_step is clamped here, not validated against len(steps),
    # because with_step clamps on the way in and the round-trip must
    # preserve a clamped value exactly.
    return plan.with_step(current_step)
