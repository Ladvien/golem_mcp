"""Rebuild a scored iteration from its own recorded calls.

The iteration log stores every tool call in full — each run_python
source and, since OT-8, each op call with its arguments — so a scored
run is reproducible without a model, a network, or a lucky generation.
Verified 2026-08-22: replaying iterations 10 and 11 reproduced their
acceptance reports number for number.

This is what a golden snapshot is checked against. Re-importing the
exported .glb would NOT do: `ingest.import_glb` normalizes what it
reads — it recentres on its bounding-box centre and re-grounds — which is
right for an arbitrary generated asset and wrong for evidence, because
it moves the very placement the snapshot exists to pin.

MAIN THREAD ONLY: executes chunks against the live scene.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# A recorded call is the text the loop emitted: `name({json arguments})`.
_CALL_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)\((?P<arguments>.*)\)$", re.DOTALL
)


class IterationNotFound(KeyError):
    """No such iteration in the log. There is no nearest match."""


class ReplayProducedNothing(RuntimeError):
    """The replayed chunks did not leave the brief's object behind."""


def load_record(log_path: Path, iteration: int) -> dict:
    records = [json.loads(line) for line in Path(log_path).read_text().splitlines()]
    matching = [record for record in records if record["iteration"] == iteration]
    if not matching:
        available = sorted({record["iteration"] for record in records})
        raise IterationNotFound(
            f"No iteration {iteration} in {log_path}. Recorded: {available}."
        )
    return matching[-1]


def calls_from(record: dict) -> list[tuple[str, dict]]:
    """Every recorded tool call of one record, in order: (name, arguments)."""
    calls: list[tuple[str, dict]] = []
    for call in record["tool_calls"]:
        match = _CALL_PATTERN.match(call)
        if match is None:
            raise ValueError(f"unreadable recorded call: {call[:80]!r}")
        calls.append((match.group("name"), json.loads(match.group("arguments"))))
    return calls


def sources_from(record: dict) -> list[str]:
    """The run_python sources of one record, in the order they ran."""
    return [
        arguments["source"]
        for name, arguments in calls_from(record)
        if name == "run_python"
    ]


def steps_applied(record: dict, brief) -> list:
    """The refinement steps the run actually executed, in order.

    A record carries one `LOCALITY <step_name>: ...` line per executed
    step, so which steps ran is recorded, not assumed. Replay and the
    golden tests score the terminal asset against the brief composed
    from exactly these steps — a record from before the suite gained
    steps must not be graded against steps it never ran.
    """
    executed = {
        line.split(":", 1)[0].removeprefix("LOCALITY ").strip()
        for line in record.get("refinement_locality", ())
    }
    return [step for step in brief.refinements if step.name in executed]


def replay_record(record: dict, object_names: tuple[str, ...], on_chunk=None):
    """Re-run a record's scene-changing calls into the current scene,
    return its objects.

    run_python calls re-execute their recorded source; op-tool calls
    (OT-8) re-bind and re-run through `call_op`, the same path the loop
    took, with the harness's plan_step stripped; the service tools that
    change nothing (inspect, render, search, list, plan) are skipped.
    Returns the objects in `object_names` order, so a multi-part brief
    comes back the way the brief names its parts. Calls that failed in
    the original run fail here too; that is the point of a faithful
    replay, and the objects are what is judged.
    """
    import bpy

    from blended.agent.op_call import OpCallResult, call_op
    from blended.agent.plan import PLAN_STEP_ARGUMENT
    from blended.agent.tools import OP_FUNCTIONS
    from blended.run.executor import RunResult, run_source_in_process

    calls = [
        (name, arguments)
        for name, arguments in calls_from(record)
        if name == "run_python" or name in OP_FUNCTIONS
    ]
    result: RunResult | OpCallResult
    for index, (name, arguments) in enumerate(calls, 1):
        if name == "run_python":
            result = run_source_in_process(arguments["source"])
        else:
            op_arguments = {
                key: value
                for key, value in arguments.items()
                if key != PLAN_STEP_ARGUMENT
            }
            op_function = OP_FUNCTIONS[name]
            if not callable(op_function):
                raise TypeError(
                    f"OP_FUNCTIONS[{name!r}] is not callable: {op_function!r}"
                )
            result = call_op(name, op_function, op_arguments)
        if on_chunk is not None:
            on_chunk(index, len(calls), result)
    bpy.context.view_layer.update()
    rebuilt = []
    for object_name in object_names:
        rebuilt_object = bpy.data.objects.get(object_name)
        if rebuilt_object is None:
            raise ReplayProducedNothing(
                f"replaying {len(calls)} call(s) left no object named "
                f"{object_name!r} — the log is not reproducible"
            )
        rebuilt.append(rebuilt_object)
    return rebuilt
