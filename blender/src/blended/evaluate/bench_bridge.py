"""The bridge from a live session to 3DCodeBench's standalone script (OT-20).

3DCodeBench (DOI 10.48550/arXiv.2606.01057) scores a STANDALONE script:
it re-executes `<inst>/<inst>.py` from an empty scene in a bare Blender
and measures the mesh that comes out. The harness does not write
scripts — it drives a live `bpy` session through tool calls. The bridge
is that the calls ARE the script: every `run_python` chunk whose Python
ran, and every op-tool call that ran, emitted in order, is the program
the benchmark re-bakes.

Which calls count is a correctness question, and the answer is not "did
it succeed" but "what did the live scene end up holding". A call whose
Python ran and only the analyzer gate objected (`locate`, `gate`,
`export`) is INCLUDED, because that gate is this harness's standard, not
3DCodeBench's, and the geometry exists either way. Measured 2026-09-10:
the bridge that read only `run_python` chunks dropped 34 op calls on
Bottle and 37 on Pillar from what the bench re-baked.

A call that RAISED is included too when it changed the scene before it
raised (OT-31). Measured 2026-09-10 on OT-27's cloud roll 1: Spoon's
first chunk built the handle and then died on
`TypeError: create_uvsphere: keyword "diameter" is invalid`; the very
next `list_scene` reported `Spoon: 956 tris`, and every later call in
the recorded conversation was written against that object. Dropping the
chunk made the bake die with `UnknownObject: no object named 'Spoon'` —
the replay could not reproduce the run it was replaying. Such a call is
emitted inside a `try` that reports the same failure, because the chunk
is deterministic: re-running it in a fresh scene stops at the same
point, leaving the same partial geometry. A call that raised and changed
NOTHING stays out; including it would only guarantee a re-bake failure.

`changed_scene` is ground truth from `bpy.data`, taken by the recorder
either side of the dispatch, never inferred from the outcome — a gate
that shares a derivation with the thing it gates cannot fail.

An op call is emitted as `_op(name, {validated arguments})`, bound at
bake time through the same `bind_arguments` the loop used, so a
dataclass argument (`tuple[BoneSpec, ...]`, an `EdgeSelector`) is
rebuilt by one converter rather than rendered as Python source by a
second one. The re-bake therefore needs `blended` importable — the
disclosed deviation from the benchmark's pure-bpy convention that the
`sys.path` prelude already carries.

Pure: strings in, a string out.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from blended.stages import STAGE_DONE, STAGE_EXPORT, STAGE_GATE, STAGE_LOCATE

HATCH_TOOL_NAME = "run_python"
# A call whose Python ran: it reached the stage after execute, whatever
# the gate then said.
EXECUTED_STAGES = (STAGE_LOCATE, STAGE_GATE, STAGE_EXPORT, STAGE_DONE)
# The name the emitted script binds an op call through.
OP_HELPER_NAME = "_op"


@dataclass(frozen=True)
class RecordedCall:
    tool_name: str
    # Validated (bound, plan_step stripped, JSON form) for an op tool; as
    # given for run_python — `ToolOutcome.validated_arguments`.
    arguments: dict
    stage_reached: str
    # Did `bpy.data` differ either side of this call? Measured by the
    # recorder, not read off the outcome (OT-31). Defaults False so a
    # caller that cannot observe the scene keeps the old rule exactly.
    changed_scene: bool = False


def call_executed(call: RecordedCall) -> bool:
    """Its Python ran to the end, whatever the gate then said."""
    return call.stage_reached in EXECUTED_STAGES


def include_call(call: RecordedCall) -> bool:
    """What the bake must replay: everything that left the scene changed."""
    return call_executed(call) or call.changed_scene


def emits_geometry(tool_name: str) -> bool:
    """A run_python chunk or ANY facade op — the reader ops included, which
    replay as scene no-ops but are counted in `op_call_count`; the service
    tools (render, plan, list, ...) are not facade ops and are excluded."""
    from blended.agent.tools import OP_FUNCTIONS

    return tool_name == HATCH_TOOL_NAME or tool_name in OP_FUNCTIONS


def prelude(venv_site_packages: str, repository_src: str) -> str:
    """What the emitted script needs to stand alone in a bare Blender."""
    return (
        "import sys\n"
        f"sys.path.insert(0, {venv_site_packages!r})\n"
        f"sys.path.insert(0, {repository_src!r})\n"
        # The host Blender may have ALREADY imported a `blended` — the
        # installed blended_agent addon bundles a copy and loads it at
        # startup, and the bench bakes without --factory-startup.
        # Measured 2026-09-10: the smoke re-bake failed with
        # ModuleNotFoundError for blended.agent.op_call, a module that
        # existed on disk, because sys.modules held the addon's older
        # copy. Evict it, so the script imports the tree it names.
        "for _name in [n for n in sys.modules if n == 'blended' or n.startswith('blended.')]:\n"
        "    del sys.modules[_name]\n"
        "\n"
        "from blended.agent.op_call import bind_arguments as _bind\n"
        "from blended.agent.tools import OP_FUNCTIONS as _OPS\n"
        "\n"
        "\n"
        f"def {OP_HELPER_NAME}(name, arguments):\n"
        "    return _OPS[name](**_bind(name, _OPS[name], arguments))\n"
    )


def canonical_orientation_epilogue() -> str:
    """The deterministic orientation step appended to the emitted script.

    The benchmark's `chamfer_with_yaw` quotients out rotation about glTF
    Z only, so exactly one degree of freedom is penalised in full: which
    Blender axis lands on the depth axis (Blender Y). Measured over 145
    dev references, putting the MIDDLE extent there costs 0.0311 mean
    cd_yawmin against 0.0632 for the unconstrained choice this harness
    made through iter2 (`scripts/orientation_policy_sim.py`).

    It is an epilogue, not a prompt sentence, because the writer cannot
    verify it: the eye is measured at 0.20-0.40 sensitivity, in line with
    reported false-negative rates for imperfect visual verifiers
    (DOI 10.48550/arXiv.2606.15693), while raising a loop's deterministic
    verification ratio is the change BlenderGym measures as a consistent
    win (DOI 10.48550/arXiv.2504.01786). The iter2 alternative — a
    measured one-shot nudge in the tool result — fired 0/20 and is gone.

    Appended verbatim to the collected chunks, so the re-baked script
    ends in the same scene the live session ended in.
    """
    return (
        "\n# --- canonical orientation (harness epilogue) ---\n"
        "from blended.ops.canonical_orientation import "
        "apply_canonical_depth_axis\n"
        "\n"
        'print("canonical orientation:", apply_canonical_depth_axis())\n'
    )


@dataclass(frozen=True)
class StandaloneScript:
    text: str
    included_count: int
    excluded_count: int
    op_call_count: int


def standalone_script(
    calls: Sequence[RecordedCall], prelude_text: str, epilogue_text: str
) -> StandaloneScript:
    """The program the benchmark re-bakes, from the recorded call sequence."""
    geometry_calls = [call for call in calls if emits_geometry(call.tool_name)]
    included = [call for call in geometry_calls if include_call(call)]
    parts = [prelude_text]
    op_call_count = 0
    for index, call in enumerate(included, start=1):
        if call.tool_name == HATCH_TOOL_NAME:
            body = call.arguments["source"]
            label = f"chunk {index}"
        else:
            op_call_count += 1
            body = f"{OP_HELPER_NAME}({call.tool_name!r}, {call.arguments!r})"
            label = f"op {index}: {call.tool_name}"
        if call_executed(call):
            parts.append(f"\n# --- {label} ---\n{body}\n")
        else:
            # It raised in the run after changing the scene, so the
            # replay must make the same change and meet the same error.
            # The body goes in through exec(compile()) rather than being
            # indented into a try block: indenting rewrites the
            # continuation lines of a triple-quoted string.
            parts.append(
                f"\n# --- {label} (raised in the run after changing the "
                f"scene; reproduced) ---\n"
                f"try:\n"
                f'    exec(compile({body!r}, {label!r}, "exec"), globals())\n'
                f"except Exception as _error:\n"
                f"    print({f'[bridge] {label} raised as it did in the run: '!r} "
                f"+ repr(_error))\n"
            )
    if included:
        parts.append(epilogue_text)
    return StandaloneScript(
        text="".join(parts),
        included_count=len(included),
        excluded_count=len(geometry_calls) - len(included),
        op_call_count=op_call_count,
    )
