"""The agent-computer interface: the tools the model can actually call.

SWE-agent's measured result — a purpose-built ACI beat a bare shell
18.0% vs 11.0% on the same model — plus its ablations, shape every
choice here:

* A too-large observation window cost MORE than a too-small one
  (-5.3pp vs -3.7pp), so every tool bounds its output.
* Iterative search was WORSE than no search at all (-6.0pp), so
  `search_ops` returns one ranked page and never paginates.
* Guardrails that prevent a bad edit beat recovery after one, because a
  single failed edit drops the next success rate from 90.5% to 57.2% —
  so `run_python` reports the gate verdict with every run rather than
  letting the agent proceed on an unmeasured mesh.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from golem_blender.agent.outcome import ToolOutcome
from golem_blender.agent.plan import (
    MAXIMUM_PLAN_STEPS,
    PLAN_STEP_ARGUMENT,
    PLAN_STEP_SCHEMA,
    parse_plan_arguments,
)
from golem_blender.stages import STAGE_DONE, STAGE_EXECUTE, STAGE_EXPORT, STAGE_LOCATE

# Bounded observation windows.
MAXIMUM_SCENE_OBJECTS_LISTED = 40
MAXIMUM_SEARCH_RESULTS = 8
# Anything that is not a letter or a digit is a word separator, so an
# underscore in `assign_material` and a space in 'assign material' are
# the same thing to a searcher.
_SEARCH_WORD_PATTERN = re.compile(r"[^a-z0-9]+")
MAXIMUM_TRACEBACK_CHARACTERS = 1500

# The hatch's price of admission (OT-7): a run_python call with no
# reason is refused at the door, before bpy, so the vocabulary's gaps
# are always named and never silent.
RUN_PYTHON_REASON_REFUSAL = (
    "run_python refused: `reason` is required and must name what the op "
    "tools could not express (e.g. 'no op insets a face'). Build with the "
    "op tools first; use run_python only for what they cannot do."
)
SOURCE_DIGEST_CHARACTERS = 12

# The SERVICE tools: hand-written, because each is a harness capability
# (execute, measure, render, search, list, export, plan) rather than a
# facade op. The op tools below are generated (OT-3).
SERVICE_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "ESCAPE HATCH: execute a Python chunk in the live Blender "
                "session for what the op tools cannot express, then measure "
                "the named object against the analyzer gate. Returns "
                "execution status, anything the chunk PRINTED, any traceback "
                "with known API-drift fixes attached, and the full gate "
                "report. print() is how you ask the scene a question — print "
                "the value you want to check and read it back here. Build "
                "with the op tools first; every call here must name in "
                "`reason` the operation that was missing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Python source. `golem_blender.ops` is importable.",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "What the op vocabulary could not express — the "
                            "operation that was missing, in one sentence. Read "
                            "and counted: every run_python call is a vote for "
                            "a new op."
                        ),
                    },
                    "object_name": {
                        "type": "string",
                        "description": (
                            "Name of the object to gate after the chunk runs. "
                            "Omit to run the chunk without gating."
                        ),
                    },
                    "plan_step": {
                        "type": "integer",
                        "description": (
                            "The 1-based plan step this call belongs to. "
                            "Set this when you execute a step of the plan "
                            "you declared with declare_plan, so the UI "
                            "advances the progress bar."
                        ),
                    },
                },
                "required": ["source", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_object",
            "description": (
                "Measure an existing object without rebuilding it. Returns "
                "the full analyzer report: triangles, components, manifold "
                "status, self-intersections, normals, UVs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "plan_step": PLAN_STEP_SCHEMA,
                },
                "required": ["object_name"],
            },
        },
    },
    # The domain lanes' self-verifier. Voyager's ablation measured
    # self-verification as the single largest component (−73% without
    # it, DOI 10.48550/arXiv.2305.16291); a rig or an action that the
    # writer cannot measure would be the one thing it never verifies.
    {
        "type": "function",
        "function": {
            "name": "inspect_domain",
            "description": (
                "Measure the non-mesh state of an object: its rig (armature "
                "bones and bound meshes), its vertex-group weights, its "
                "animation (action, fcurves, keyframes, frame range), or "
                "its material node tree. Read this back after rigging, "
                "weighting, keyframing or texturing to verify what you did, "
                "the way inspect_object verifies geometry."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": (
                            "The armature for `rig`; the mesh for `weights` and "
                            "`material`; either for `animation`."
                        ),
                    },
                    "domain": {
                        "type": "string",
                        "enum": ["rig", "weights", "animation", "material"],
                    },
                    "plan_step": PLAN_STEP_SCHEMA,
                },
                "required": ["object_name", "domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "render_views",
            "description": (
                "Render an object from front, right, top and three-quarter "
                "into one contact sheet. If you cannot see images yourself, "
                "a vision model describes the render back to you in words. "
                "Use `look_for` to aim that description at a specific "
                "question. Use X-ray to look through geometry when debugging "
                "overlaps or hidden parts. Always look before declaring done."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "xray": {
                        "type": "boolean",
                        "description": (
                            "Semi-transparent shading — reveals interpenetration "
                            "and hidden interior geometry."
                        ),
                    },
                    "cull": {
                        "type": "boolean",
                        "description": (
                            "Hide back faces as the game does (bevy_gltf draws "
                            "a non-doubleSided glTF with cull_mode Back). "
                            "Default true; false shows both sides."
                        ),
                    },
                    "look_for": {
                        "type": "string",
                        "description": (
                            "What you specifically want checked in the render, "
                            "e.g. 'are all four legs the same length?' or 'is "
                            "the drainage hole open?'. Aims the description at "
                            "your actual question."
                        ),
                    },
                    "plan_step": PLAN_STEP_SCHEMA,
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_ops",
            "description": (
                "Find harness operations by keyword. Use this before "
                "guessing a signature. Returns the closest matches with "
                "their exact signatures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Words to match, in any order: 'boolean union', "
                            "'assign material', 'unwrap', 'snap ground'. "
                            "Every word must appear, so fewer words match "
                            "more broadly."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scene",
            "description": (
                "List mesh objects currently in the scene with their triangle "
                "counts and dimensions. Bounded — use it to orient, not to "
                "search."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_asset",
            "description": (
                "Export an object to .glb and VERIFY it by re-importing the "
                "written file and re-measuring, and save its editable .blend "
                "source at blend_path (REQUIRED: an asset without its .blend "
                "is not done). Only call this on a mesh that already passes "
                "the gate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "path": {"type": "string", "description": "Output .glb path."},
                    "blend_path": {
                        "type": "string",
                        "description": (
                            "Absolute path ending in .blend where the object's "
                            "editable source is saved."
                        ),
                    },
                    "plan_step": PLAN_STEP_SCHEMA,
                },
                "required": ["object_name", "path", "blend_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_blend",
            "description": (
                "Save the named objects, or a defined PIECE, as an editable "
                ".blend (one scene, exactly those objects with their mesh and "
                "material data and transforms) and VERIFY it by re-reading the "
                "written file. Use it for pieces exported some other way, such "
                "as several objects in one .glb; export_asset already saves its "
                "own. `define_piece` names a set once, then `piece` saves it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "object_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": (
                            "The objects to save. Give this OR `piece`, not both."
                        ),
                    },
                    "piece": {
                        "type": "string",
                        "description": (
                            "A piece defined by define_piece: its whole set is "
                            "saved. Give this OR `object_names`, not both."
                        ),
                    },
                    "blend_path": {
                        "type": "string",
                        "description": "Absolute path ending in .blend.",
                    },
                    "plan_step": PLAN_STEP_SCHEMA,
                },
                "required": ["blend_path"],
            },
        },
    },
    # The plan tool — Decision D1 of the chat-UX overhaul. The agent
    # declares a numbered plan before it changes the scene; the UI shows
    # it and advances a progress bar through it. The plan is a shared
    # representation, not an approval gate (DOI 10.48550/arXiv.2507.22358
    # shared editable plan + progress bar; DOI 10.48550/arxiv.2604.14228
    # ~93 % of permission prompts are approved, so no approval click).
    {
        "type": "function",
        "function": {
            "name": "declare_plan",
            "description": (
                "Declare your plan as a numbered list of short, "
                "user-readable steps. Call this FIRST, once per turn, "
                "before any tool that changes the scene. The steps are "
                "shown to the user verbatim. Keep each step to one line "
                f"and at most {MAXIMUM_PLAN_STEPS} steps. After declaring, "
                "execute the steps in order, setting plan_step on each "
                "action call to the 1-based step it belongs to."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "The numbered plan steps, in execution order. "
                            "Each step is a short natural-language "
                            "description of what you will do."
                        ),
                    },
                },
                "required": ["steps"],
            },
        },
    },
]


from golem_blender.agent.tool_schemas import (
    build_tool_schemas,
    tool_schemas_fingerprint,
)
from golem_blender.manifest import OP_MODULE_NAMES
from golem_blender.ops._contract import facade_ops
from golem_blender.plugins import op_plugins

# One generated tool per facade op (OT-3): introspected, never written.
OP_TOOL_SCHEMAS = build_tool_schemas()


def _assert_tool_names_disjoint(service: list[dict], generated: list[dict]) -> None:
    """A facade op named like a service tool would shadow it silently."""
    collisions = {tool["function"]["name"] for tool in service} & {
        tool["function"]["name"] for tool in generated
    }
    if collisions:
        raise ImportError(
            f"facade op(s) collide with service tool name(s): {sorted(collisions)}"
        )


_assert_tool_names_disjoint(SERVICE_TOOL_SCHEMAS, OP_TOOL_SCHEMAS)

# What the model can call: the service tools plus every facade op.
TOOL_SCHEMAS = SERVICE_TOOL_SCHEMAS + OP_TOOL_SCHEMAS
# The dispatch tables (OT-4): a service tool name reaches its branch in
# `dispatch_tool`; an op tool name reaches its facade function through
# `op_call.call_op`; any other name is refused at the door.
SERVICE_TOOL_NAMES = frozenset(
    tool["function"]["name"] for tool in SERVICE_TOOL_SCHEMAS
)


def _facade_op_functions() -> dict[str, Callable[..., Any]]:
    """Every facade op by name; a non-callable export fails at import,
    not at the first call the model makes."""
    functions: dict[str, Callable[..., Any]] = {}
    for op_name, function in facade_ops():
        if not callable(function):
            raise TypeError(f"facade op {op_name!r} is not callable: {function!r}")
        functions[op_name] = function
    return functions


OP_FUNCTIONS = _facade_op_functions()
# Fingerprint of that set, pinned beside the assembled-prompt fingerprint
# and written into every iteration record (PRM-7 discipline for tools).
TOOL_SCHEMAS_FINGERPRINT = tool_schemas_fingerprint(TOOL_SCHEMAS)


def search_ops(query: str) -> ToolOutcome:
    """Find op tools by keyword; each hit carries its generated schema (OT-15).

    Match WORDS, not the raw string. Measured 2026-08-22 (iteration 4):
    3 of 16 turns were spent on 'boolean union', 'material assign' and
    'assign material', all answered "No operation matches" — while
    `boolean_union` and `assign_material` both exist. A whole-string test
    cannot span the underscore, and cannot survive word order.
    Punctuation is flattened on both sides so `_` and ` ` are the same
    character to a searcher.

    Each hit is the tool's name, its one-line summary and its parameters
    schema as compact JSON: a small model needs the argument SHAPE at the
    moment of use, not a signature string to re-parse (AGT-18). One ranked
    page, capped at MAXIMUM_SEARCH_RESULTS, never paginated.
    """
    query_tokens = [
        token for token in _SEARCH_WORD_PATTERN.split(query.lower()) if token
    ]
    if not query_tokens:
        return ToolOutcome(
            f"Query {query!r} contains no searchable words. Search for an "
            f"operation by name or purpose, e.g. 'boolean union' or 'assign material'.",
            ok=False,
        )
    # Ranked: a tool whose NAME carries every query word outranks one
    # that only mentions them in its description, shorter names first
    # among those (assign_material before assign_image_texture_material
    # for 'assign material'); facade order breaks the remaining ties.
    ranked: list[tuple[int, int, int, str]] = []
    for position, tool in enumerate(OP_TOOL_SCHEMAS):
        function_block = tool["function"]
        name = function_block["name"]
        module_name = OP_FUNCTIONS[name].__module__.rsplit(".", 1)[-1]
        haystack = _SEARCH_WORD_PATTERN.sub(
            " ", f"{module_name} {name} {function_block['description']}".lower()
        )
        if not all(token in haystack for token in query_tokens):
            continue
        name_words = _SEARCH_WORD_PATTERN.sub(" ", name.lower())
        in_name = 0 if all(token in name_words for token in query_tokens) else 1
        ranked.append(
            (
                in_name,
                len(name),
                position,
                (
                    f"{name}: {function_block['description']}\n"
                    f"    schema: {json.dumps(function_block['parameters'], separators=(',', ':'))}"
                ),
            )
        )
    hits = [line for _, _, _, line in sorted(ranked)]
    if not hits:
        return ToolOutcome(
            f"No operation matches all of {query_tokens}. Available modules: "
            f"{', '.join([*OP_MODULE_NAMES, *(plugin.module_name for plugin in op_plugins())])}.",
            ok=False,
        )
    return ToolOutcome("\n".join(hits[:MAXIMUM_SEARCH_RESULTS]))


def _report_to_dict(report) -> dict:
    from dataclasses import asdict

    return asdict(report)


# The ops that SET the working scene, so they must run outside the context that
# makes it current: `use_scene` reads and writes the selection, and
# `list_scenes`/`hold_view` report and set the state it is derived from.
SCENE_SELECTION_TOOLS = frozenset({"use_scene", "list_scenes", "hold_view"})


def dispatch_tool(
    tool_name: str,
    arguments: dict,
    output_directory: Path = Path("_renders/agent"),
) -> ToolOutcome:
    """Execute one tool call.

    The outcome carries the text the model reads, the images to attach
    to its next message (a contact sheet the model cannot see is
    worthless), and the scene effects the loop's ledger needs (OT-5).

    MAIN THREAD ONLY. Everything below touches bpy.
    """
    # Touching bpy off the main thread does not raise. Blender corrupts
    # quietly and segfaults later, usually inside its own draw loop,
    # with nothing in any traceback pointing back here. So say it out
    # loud: a catchable error the agent loop reports as a tool failure
    # beats a dead application every time.
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            f"dispatch_tool({tool_name!r}) ran on thread "
            f"{threading.current_thread().name!r}, not the main thread. "
            f"bpy is not thread-safe. Frontends must pass a main-thread "
            f"dispatcher: AgentSession(dispatch=...)."
        )
    # The plan tool is pure — it touches no bpy, so handle it before
    # the bpy import to keep it testable without Blender. The model
    # sees its own plan echoed back as the tool result.
    if tool_name == "declare_plan":
        try:
            plan = parse_plan_arguments(arguments)
        except ValueError as error:
            return ToolOutcome(f"FAILED: {error}", ok=False)
        numbered = "\n".join(
            f"  {index}. {step}" for index, step in enumerate(plan.steps, start=1)
        )
        return ToolOutcome(f"Plan declared:\n{numbered}")

    # An op tool (OT-4): bound, run, gated (OT-5) and reported by
    # op_call; the op body is what reaches bpy, so this branch too stays
    # above the import.
    op_function = OP_FUNCTIONS.get(tool_name)
    if op_function is not None:
        from golem_blender import scene_target
        from golem_blender.agent.op_call import call_op, json_returned
        from golem_blender.harness import gate_verdict_json

        # plan_step is the harness's argument (AGT-7), not the op's.
        op_arguments = {
            key: value for key, value in arguments.items() if key != PLAN_STEP_ARGUMENT
        }
        # Every op runs inside the session's WORKING SCENE. The gate, the boolean
        # operand check and `link_into_scene` resolve through `bpy.context.scene`,
        # so without this a session that selected a background scene would have
        # its booleans made in the user's — silently, and in the wrong place.
        # The three scene ops are exempt: they are how the working scene is set.
        if tool_name in SCENE_SELECTION_TOOLS:
            result = call_op(tool_name, op_function, op_arguments)
        else:
            try:
                with scene_target.working_scene_context():
                    result = call_op(tool_name, op_function, op_arguments)
            except scene_target.WorkingSceneMissing as error:
                # A missing working scene is a FAILED CALL, not a crash: the
                # model reads the reason and re-selects, instead of the loop
                # dying on a traceback it cannot act on.
                return ToolOutcome(f"FAILED at execute: {error}", ok=False)
        # A call the binder rejected bound nothing: record what the
        # model sent (plan_step stripped), not an empty dict, so the
        # miner can see WHAT was refused.
        validated_arguments = (
            {
                name: json_returned(value)
                for name, value in result.bound_arguments.items()
            }
            if result.bound_arguments
            else op_arguments
        )
        return ToolOutcome(
            text=result.summary(MAXIMUM_TRACEBACK_CHARACTERS),
            ok=result.ok,
            stage_reached=result.stage_reached,
            validated_arguments=validated_arguments,
            gates=tuple(gate_verdict_json(gate) for gate in result.gates),
            intermediates_created=result.intermediates_created,
            intermediates_resolved=result.intermediates_resolved,
        )
    # Refused at the door, before bpy: a name that is neither a service
    # tool nor a facade op has no schema and was never offered.
    if tool_name not in SERVICE_TOOL_NAMES:
        return ToolOutcome(f"Unknown tool: {tool_name}", ok=False)
    # search_ops reads the schemas, not the scene: pure, above bpy.
    if tool_name == "search_ops":
        return search_ops(arguments["query"])
    if tool_name == "run_python":
        reason = arguments.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            return ToolOutcome(
                RUN_PYTHON_REASON_REFUSAL, ok=False, stage_reached=STAGE_EXECUTE
            )
        outcome = _dispatch_service_tool(tool_name, arguments, output_directory)
        return dataclasses.replace(
            outcome,
            hatch_reason=reason.strip(),
            source_sha256=hashlib.sha256(
                str(arguments.get("source", "")).encode("utf-8")
            ).hexdigest()[:SOURCE_DIGEST_CHARACTERS],
        )
    return _dispatch_service_tool(tool_name, arguments, output_directory)


def _required_blend_path(arguments: dict) -> tuple[Path, str]:
    """The `blend_path` of an export or save call, or the refusal text.

    Pure (no bpy). Every exported asset ships with its .blend (OT-50), so
    a missing, relative or non-.blend path fails the call instead of
    defaulting to somewhere the caller never chose.
    """
    raw_path = arguments.get("blend_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return Path(), (
            "blend_path is REQUIRED: every exported asset ships with its "
            ".blend source, so give an absolute path ending in .blend."
        )
    blend_path = Path(raw_path)
    if not blend_path.is_absolute() or blend_path.suffix != ".blend":
        return Path(), (
            f"blend_path must be an absolute path ending in .blend, got "
            f"{raw_path!r}; the .blend source is required for every export."
        )
    return blend_path, ""


def _dispatch_service_tool(
    tool_name: str, arguments: dict, output_directory: Path
) -> ToolOutcome:
    """The service tools' branches."""
    import bpy

    from golem_blender.analyze import MeshBudget, analyze_object

    output_directory = Path(output_directory)

    def failed(text: str, stage: str = STAGE_EXECUTE) -> ToolOutcome:
        return ToolOutcome(
            text, ok=False, stage_reached=stage, validated_arguments=arguments
        )

    def done(
        text: str, images: tuple[Path, ...] = (), stage: str = "", **fields
    ) -> ToolOutcome:
        return ToolOutcome(
            text,
            images,
            ok=True,
            stage_reached=stage,
            validated_arguments=arguments,
            **fields,
        )

    if tool_name == "run_python":
        from golem_blender.harness import (
            HarnessSettings,
            harness_result_gate_json,
            run_chunk,
        )
        from golem_blender.run.executor import run_source_in_process

        source_code = arguments["source"]
        object_name = arguments.get("object_name")
        if not object_name:
            run_result = run_source_in_process(source_code, "<chat>")
            if run_result.ok:
                printed = (
                    f"\nprinted:\n{run_result.stdout_text}"
                    if run_result.stdout_text
                    else "\n(nothing printed)"
                )
                return done(
                    f"Executed OK in {run_result.duration_s:.2f}s.{printed}",
                    stage=STAGE_DONE,
                )
            drift_notes = "".join(
                f"\n  KNOWN TRAP [{entry.symbol}]: {entry.fix}"
                for entry in run_result.matched_drift
            )
            printed = (
                f"\nprinted before failing:\n{run_result.stdout_text}"
                if run_result.stdout_text
                else ""
            )
            return failed(
                f"FAILED: {run_result.error_type}: {run_result.error_message}\n"
                f"{run_result.traceback_text[:MAXIMUM_TRACEBACK_CHARACTERS]}"
                f"{printed}{drift_notes}"
            )
        harness_result = run_chunk(
            source_code,
            object_name=object_name,
            settings=HarnessSettings(output_directory=output_directory),
            chunk_label="chat",
        )
        images = (
            (harness_result.contact_sheet_path,)
            if harness_result.contact_sheet_path is not None
            else ()
        )
        gates = (
            (harness_result_gate_json(harness_result),)
            if harness_result.stage_reached != STAGE_EXECUTE
            else ()
        )
        return ToolOutcome(
            harness_result.summary(),
            images,
            ok=harness_result.ok,
            stage_reached=harness_result.stage_reached,
            validated_arguments=arguments,
            gates=gates,
        )

    if tool_name == "inspect_object":
        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return failed(f"No object named {object_name!r} in the scene.")
        report = analyze_object(blender_object)
        failures = list(report.failures(MeshBudget()))
        # The same blind spots `run_chunk` had: flawless geometry the
        # user cannot see (unlinked, excluded collection, hidden,
        # hide_render) or cannot use (collapsed or non-finite object
        # transform) passes every mesh check. ONE shared rule, because
        # this tool is what the writer uses to check its own work and it
        # must not disagree with the gate.
        from golem_blender.harness import scene_state_failure

        unusable = scene_state_failure(blender_object)
        if unusable:
            failures.append(unusable)
        verdict = "PASS" if not failures else "FAIL: " + "; ".join(failures)
        # The same shared text function `HarnessResult.summary()` uses,
        # over the same world-box measurement the gate and
        # `apply_canonical_depth_axis` read (OT-34), so the tool the
        # writer checks its own work with cannot disagree with the gate
        # about where the extents landed.
        from golem_blender.ops.canonical_orientation import orientation_reading
        from golem_blender.ops.transforms import _world_extents_m

        reading = orientation_reading(
            tuple(float(extent) for extent in _world_extents_m([blender_object]))
        )
        return done(
            f"GATE {verdict}\n{reading}\n{json.dumps(_report_to_dict(report), indent=1)}"
        )

    if tool_name == "inspect_domain":
        object_name = arguments["object_name"]
        domain = arguments["domain"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return failed(f"No object named {object_name!r} in the scene.")
        if domain == "rig":
            from golem_blender.ops import rig_report

            if blender_object.type != "ARMATURE":
                return failed(
                    f"{object_name!r} is a {blender_object.type}, not an ARMATURE."
                )
            report = rig_report(object_name)
        elif domain == "weights":
            from golem_blender.ops import weight_report

            if blender_object.type != "MESH":
                return failed(
                    f"{object_name!r} is a {blender_object.type}, not a MESH."
                )
            report = weight_report(object_name)
        elif domain == "animation":
            from golem_blender.ops import animation_report

            report = animation_report(object_name)
        elif domain == "material":
            from golem_blender.ops import material_report

            if blender_object.type != "MESH":
                return failed(
                    f"{object_name!r} is a {blender_object.type}, not a MESH."
                )
            report = material_report(object_name)
        else:
            return failed(f"Unknown domain {domain!r}.")
        return done(
            f"{domain} report for {object_name}:\n{json.dumps(_report_to_dict(report), indent=1)}"
        )

    if tool_name == "render_views":
        from golem_blender.capture import CaptureSettings, capture_contact_sheet

        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return failed(f"No object named {object_name!r} in the scene.")
        report = analyze_object(blender_object)
        xray = bool(arguments.get("xray", False))
        cull = bool(arguments.get("cull", True))
        sheet_path = capture_contact_sheet(
            blender_object,
            output_directory,
            settings=CaptureSettings(xray=xray, cull_backfaces=cull),
            report=report,
        )
        return done(
            f"Rendered {object_name} ({'x-ray' if xray else 'solid'}, "
            f"{'culled' if cull else 'double-sided'}). "
            f"Look at the attached contact sheet.",
            (sheet_path,),
        )

    if tool_name == "list_scene":
        mesh_objects = [
            scene_object
            for scene_object in bpy.context.scene.objects
            if scene_object.type == "MESH"
        ]
        if not mesh_objects:
            return done("Scene is empty (no mesh objects).")
        from golem_blender.ops.transforms import _world_extents_m

        lines = []
        for scene_object in mesh_objects[:MAXIMUM_SCENE_OBJECTS_LISTED]:
            triangle_count = sum(
                len(polygon.vertices) - 2 for polygon in scene_object.data.polygons
            )
            # World extents, not `dimensions` (OT-34): the writer reads
            # this list to decide which axis holds which extent.
            extent_x_m, extent_y_m, extent_z_m = _world_extents_m([scene_object])
            lines.append(
                f"{scene_object.name}: {triangle_count} tris, "
                f"{extent_x_m:.3f} x {extent_y_m:.3f} x {extent_z_m:.3f} m"
            )
        if len(mesh_objects) > MAXIMUM_SCENE_OBJECTS_LISTED:
            lines.append(
                f"... and {len(mesh_objects) - MAXIMUM_SCENE_OBJECTS_LISTED} more"
            )
        return done("\n".join(lines))

    if tool_name == "export_asset":
        from golem_blender.export import BlendSaveError, export_glb

        blend_path, refusal = _required_blend_path(arguments)
        if refusal:
            return failed(refusal, STAGE_EXPORT)
        object_name = arguments["object_name"]
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            return failed(
                f"No object named {object_name!r} in the scene.", STAGE_LOCATE
            )
        try:
            export_report = export_glb(
                blender_object, Path(arguments["path"]), blend_path=blend_path
            )
        except BlendSaveError as error:
            return failed(f"EXPORT FAILED, the .blend source: {error}", STAGE_EXPORT)
        failures = export_report.round_trip_failures()
        if failures:
            return failed(
                "EXPORT VERIFICATION FAILED:\n" + "\n".join(failures), STAGE_EXPORT
            )
        return done(
            f"Exported and verified: {export_report.export_path} "
            f"({export_report.file_size_bytes} bytes, "
            f"{export_report.reimported_welded.triangle_count} tris round-tripped); "
            f"saved and re-read the .blend source {export_report.blend.blend_path} "
            f"({export_report.blend.file_size_bytes} bytes, "
            f"{export_report.blend.triangle_counts[object_name]} tris).",
            stage=STAGE_DONE,
        )

    if tool_name == "save_blend":
        from golem_blender.export import BlendSaveError, save_blend

        blend_path, refusal = _required_blend_path(arguments)
        if refusal:
            return failed(refusal, STAGE_EXPORT)
        object_names = arguments.get("object_names")
        piece = arguments.get("piece")
        if piece is not None:
            if not isinstance(piece, str) or not piece.strip():
                return failed(
                    "piece must be a non-empty piece name (define_piece it first).",
                    STAGE_LOCATE,
                )
            if object_names is not None:
                return failed(
                    "give object_names or piece, not both: a piece already names "
                    "its objects.",
                    STAGE_LOCATE,
                )
            try:
                blend_report = save_blend(None, blend_path, piece=piece.strip())
            except BlendSaveError as error:
                return failed(f"SAVE BLEND FAILED: {error}", STAGE_EXPORT)
        else:
            if (
                not isinstance(object_names, list)
                or not object_names
                or not all(isinstance(name, str) for name in object_names)
            ):
                return failed(
                    "object_names must be a non-empty list of object names, or "
                    "give `piece`.",
                    STAGE_LOCATE,
                )
            try:
                blend_report = save_blend(object_names, blend_path)
            except BlendSaveError as error:
                return failed(f"SAVE BLEND FAILED: {error}", STAGE_EXPORT)
        return done(
            f"Saved and re-read the .blend source {blend_report.blend_path} "
            f"({blend_report.file_size_bytes} bytes): "
            + ", ".join(
                f"{name} {blend_report.triangle_counts[name]} tris"
                for name in blend_report.object_names
            )
            + ".",
            stage=STAGE_DONE,
        )

    raise AssertionError(
        f"service tool {tool_name!r} has a schema but no dispatch branch"
    )
