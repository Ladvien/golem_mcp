"""Headless chat end-to-end: six user asks, one real writer, hard asserts.

    make chat-e2e
    make chat-e2e ARGS="--only rig,animation"
    make chat-e2e ARGS="--no-hatch"      # run_python withheld entirely (OT-11)

With --no-hatch, run_python is not offered to the writer and is refused
if called anyway; a scenario that then fails, or that reached for the
hatch, is listed at the end as MISSING-OP EVIDENCE for OT-12.

Each scenario starts from an EMPTY scene and a FRESH AgentSession
(prompt revision `--revision`, default the v12 candidate: op tools first,
run_python as the escape hatch), sends the user's words through
`AgentSession.send`, then measures the scene with the same reports
`inspect_domain` gives the writer. A scenario passes only when every
assertion holds; the script exits 0 only when every scenario passes.
Transcripts land under outputs/chat_e2e/<stamp>/.

Runs inside `blender --background`: bpy is on the main thread, so
`dispatch_here` (the AgentSession default) is the right dispatcher.

The writer and eye default to `ModelConfig`'s defaults, the
subscription-covered Claude Code lane (`claude-code:sonnet`, which looks
at its own renders); the OpenRouter lane is metered and never used here.
Another lane is selected with `--model` / `--vision-model`; an empty
`--vision-model ''` means the writer looks at its own renders. Measured
2026-09-05 on the Claude Code lane: 6/6 scenarios in 2 m 53 s, 18 tool
calls.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    """The dev venv's site-packages: jinja2 lives there, not in Blender."""
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)

OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "chat_e2e"
# v12: the op-tools-first candidate (OT-7). v11 remains runnable with --revision 11.
DEFAULT_PROMPT_REVISION = 12
# One extra failed chunk over the converged mesh budget: a rig or an
# animation is two builds (mesh, then the domain) in one turn.
MAXIMUM_TOOL_CALLS_PER_TURN = 36

DIMENSION_TOLERANCE_M = 0.02
GROUND_TOLERANCE_M = 0.005

CRATE_SIZE_M = (0.6, 0.4, 0.5)
BODY_SIZE_M = (0.3, 0.3, 1.5)
SPINE_BONE_COUNT = 5
TOP_GROUP_THRESHOLD_M = 1.0
CUBE_SIZE_M = 0.5
ANIMATION_FRAME_RANGE = (1, 48)
ANIMATION_TRAVEL_X_M = 2.0
LOCATION_CHANNEL_COUNT = 3
TILE_SIZE_M = (1.0, 1.0, 0.1)
POST_SIZE_M = (0.2, 0.2, 1.0)
POST_TALLER_FACTOR = 2.0


@dataclass(frozen=True)
class Scenario:
    name: str
    prompts: tuple[str, ...]
    check: Callable[[], list[str]]  # returns failures; empty = pass


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    tool_calls: int = 0
    # run_python calls the writer attempted (OT-11): dispatched or refused.
    hatch_attempts: int = 0
    answers: list[str] = field(default_factory=list)
    error: str = ""


# --- assertion helpers -----------------------------------------------------


def _object(name: str, expected_type: str):
    import bpy

    found = bpy.data.objects.get(name)
    if found is None:
        raise AssertionError(f"no object named {name!r} in the scene")
    if found.type != expected_type:
        raise AssertionError(f"{name!r} is a {found.type}, expected {expected_type}")
    return found


def _check_dimensions(obj, expected_m: tuple[float, float, float]) -> list[str]:
    failures = []
    for axis, (measured, expected) in enumerate(zip(obj.dimensions, expected_m)):
        if abs(measured - expected) > DIMENSION_TOLERANCE_M:
            failures.append(
                f"{obj.name} dimension {'xyz'[axis]} = {measured:.3f} m, "
                f"expected {expected:.3f} ± {DIMENSION_TOLERANCE_M}"
            )
    return failures


def _check_on_ground(obj) -> list[str]:
    lowest_z = min((obj.matrix_world @ v.co).z for v in obj.data.vertices)
    if abs(lowest_z) > GROUND_TOLERANCE_M:
        return [
            f"{obj.name} lowest vertex z = {lowest_z:.4f} m, expected 0 ± {GROUND_TOLERANCE_M}"
        ]
    return []


def _check_gate(obj) -> list[str]:
    from blended.analyze import MeshBudget, analyze_object

    return [f"{obj.name} gate: {f}" for f in analyze_object(obj).failures(MeshBudget())]


def _collect(*checks: Callable[[], list[str]]) -> list[str]:
    failures: list[str] = []
    for check in checks:
        try:
            failures.extend(check())
        except AssertionError as error:
            failures.append(str(error))
    return failures


# --- scenarios ---------------------------------------------------------------


def check_object() -> list[str]:
    def run():
        crate = _object("Crate", "MESH")
        return (
            _check_dimensions(crate, CRATE_SIZE_M)
            + _check_on_ground(crate)
            + _check_gate(crate)
        )

    return _collect(run)


def _bone_backed_groups(mesh_object, report) -> list[str]:
    """Vertex groups that name a bone of the deforming armature AND
    carry weight — the only groups that move anything."""
    from blended.ops.weights import deforming_bone_names

    return [
        name
        for name in deforming_bone_names(mesh_object.name)
        if report.nonzero_weight_counts.get(name, 0) > 0
    ]


def check_rig() -> list[str]:
    from blended.ops import rig_report, weight_report

    def run():
        body = _object("Body", "MESH")
        spine = _object("Spine", "ARMATURE")
        rig = rig_report(spine.name)
        weights = weight_report(body.name)
        failures = _check_dimensions(body, BODY_SIZE_M)
        if rig.bone_count < SPINE_BONE_COUNT:
            failures.append(
                f"Spine has {rig.bone_count} bones, expected ≥ {SPINE_BONE_COUNT}"
            )
        if "Body" not in rig.bound_mesh_names:
            failures.append(
                f"Body is not bound to Spine (bound: {rig.bound_mesh_names})"
            )
        # A disabled Armature modifier looks like a finished rig and
        # deforms nothing, so "bound" must mean "deforming".
        if rig.disabled_modifier_mesh_names:
            failures.append(
                f"armature modifier disabled on "
                f"{list(rig.disabled_modifier_mesh_names)} — the rig deforms nothing"
            )
        if not any(count > 0 for count in weights.nonzero_weight_counts.values()):
            failures.append("Body has no vertex group with non-zero weights")
        # Criterion (c) is "non-zero weights on >= 1 BONE", so what has
        # to hold is that a bone-named group carries weight — NOT that
        # every group names a bone. A mesh may legitimately carry
        # utility groups (masks, selections); the `weights` scenario is
        # even told to make one called Top. Asserting the stricter
        # version failed that scenario on instructed, correct work.
        if not _bone_backed_groups(body, weights):
            failures.append(
                f"no bone-named vertex group carries weight "
                f"(groups {list(weights.group_names)})"
            )
        return failures

    return _collect(run)


def check_weights() -> list[str]:
    from blended.ops import weight_report

    def run():
        body = _object("Body", "MESH")
        report = weight_report(body.name)
        failures = []
        top_count = report.nonzero_weight_counts.get("Top", 0)
        expected_top = sum(
            1
            for v in body.data.vertices
            if (body.matrix_world @ v.co).z > TOP_GROUP_THRESHOLD_M
        )
        if top_count == 0:
            failures.append(
                f"vertex group 'Top' has no non-zero weights (groups: {report.group_names})"
            )
        elif top_count != expected_top:
            failures.append(
                f"'Top' weights {top_count} vertices, expected {expected_top} above {TOP_GROUP_THRESHOLD_M} m"
            )
        if report.unweighted_vertex_count != 0:
            failures.append(
                f"{report.unweighted_vertex_count} vertices carry no weight at all"
            )
        if not _bone_backed_groups(body, report):
            failures.append(
                f"no bone-named vertex group carries weight "
                f"(groups {list(report.group_names)})"
            )
        return failures

    return _collect(run)


def check_animation() -> list[str]:
    import bpy

    from blended.ops import animation_report

    def run():
        cube = _object("Cube", "MESH")
        report = animation_report(cube.name)
        failures = []
        if (report.frame_start, report.frame_end) != ANIMATION_FRAME_RANGE:
            failures.append(
                f"frame range {report.frame_start}-{report.frame_end}, expected {ANIMATION_FRAME_RANGE}"
            )
        if report.keyframe_count < 2 * LOCATION_CHANNEL_COUNT:
            failures.append(
                f"{report.keyframe_count} keyframes, expected ≥ {2 * LOCATION_CHANNEL_COUNT}"
            )
        if not any("location" in path for path in report.animated_data_paths):
            failures.append(
                f"no location channel animated: {report.animated_data_paths}"
            )
        if report.muted_fcurve_count:
            failures.append(
                f"{report.muted_fcurve_count} of {report.fcurve_count} fcurves "
                f"are muted — the keyframes exist and animate nothing"
            )
        if report.keyframes_outside_frame_range_count:
            failures.append(
                f"{report.keyframes_outside_frame_range_count} keyframes fall "
                f"outside {ANIMATION_FRAME_RANGE} and never play"
            )
        bpy.context.scene.frame_set(ANIMATION_FRAME_RANGE[1])
        end_x = cube.matrix_world.translation.x
        if abs(end_x - ANIMATION_TRAVEL_X_M) > DIMENSION_TOLERANCE_M:
            failures.append(
                f"at frame {ANIMATION_FRAME_RANGE[1]} x = {end_x:.3f}, expected {ANIMATION_TRAVEL_X_M}"
            )
        return failures

    return _collect(run)


def check_material() -> list[str]:
    from blended.ops import material_report

    def run():
        tile = _object("Tile", "MESH")
        report = material_report(tile.name)
        failures = _check_dimensions(tile, TILE_SIZE_M)
        if not report.base_color_linked:
            failures.append("Tile's Base Color is not driven by a node")
        if "ShaderNodeTexChecker" not in report.node_type_counts:
            failures.append(f"no checker node: {report.node_type_counts}")
        return failures

    return _collect(run)


def check_iterative() -> list[str]:
    def run():
        post = _object("Post", "MESH")
        taller = (POST_SIZE_M[0], POST_SIZE_M[1], POST_SIZE_M[2] * POST_TALLER_FACTOR)
        return (
            _check_dimensions(post, taller) + _check_on_ground(post) + _check_gate(post)
        )

    return _collect(run)


SCENARIOS = (
    Scenario(
        "object",
        (
            (
                "Build a wooden crate named Crate: 0.6 m wide (x), 0.4 m deep (y), "
                "0.5 m tall (z), standing on the floor at the origin."
            ),
        ),
        check_object,
    ),
    Scenario(
        "rig",
        (
            (
                "Build a box named Body, 0.3 x 0.3 x 1.5 m, standing on the floor, "
                "then rig it with a vertical 5-bone spine armature named Spine "
                "running from the floor to the top, bound with automatic weights."
            ),
        ),
        check_rig,
    ),
    Scenario(
        "weights",
        (
            (
                "Build a box named Body, 0.3 x 0.3 x 1.5 m standing on the floor, "
                "and rig it to a 2-bone vertical armature named Spine with automatic "
                "weights. Then weight-paint: create a vertex group named Top holding "
                "weight 1.0 on exactly the vertices above z = 1.0 m."
            ),
        ),
        check_weights,
    ),
    Scenario(
        "animation",
        (
            (
                "Build a 0.5 m cube named Cube standing on the floor. Set the frame "
                "range to 1-48 and animate it sliding along +x: keyframe its location "
                "at the origin on frame 1 and at x = 2.0 m on frame 48."
            ),
        ),
        check_animation,
    ),
    Scenario(
        "material",
        (
            (
                "Build a floor tile named Tile, 1.0 x 1.0 x 0.1 m on the floor, and "
                "give it a procedural checker material named Tiles."
            ),
        ),
        check_material,
    ),
    Scenario(
        "iterative",
        (
            "Build a square post named Post, 0.2 x 0.2 x 1.0 m, standing on the floor.",
            "Make Post twice as tall. Keep its footprint exactly as it is.",
        ),
        check_iterative,
    ),
)


# --- driver ------------------------------------------------------------------


def run_scenario(
    scenario: Scenario,
    revision: int,
    output_directory: Path,
    overrides: dict,
    disabled_tools: frozenset[str] = frozenset(),
) -> ScenarioResult:
    import bpy

    from blended.agent.loop import AgentSession, ModelConfig, OllamaClient
    from blended.agent.system_prompt import build_system_prompt
    from blended.agent.tool_event import TOOL_EVENT_KIND

    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = ScenarioResult(name=scenario.name, passed=False)
    transcript_path = output_directory / f"{scenario.name}.jsonl"

    def on_event(kind: str, text: str) -> None:
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": kind, "text": text}) + "\n")
        if kind == "tool":
            result.tool_calls += 1
            if text.startswith("run_python("):
                result.hatch_attempts += 1
        if kind == TOOL_EVENT_KIND:
            return  # the structured copy of the pair just printed
        preview = text if len(text) <= 300 else text[:300] + " ..."
        print(f"[{scenario.name}] [{kind}] {preview}", flush=True)

    session = AgentSession(
        client=OllamaClient(ModelConfig.from_environment(**overrides)),
        output_directory=output_directory / scenario.name,
        maximum_tool_calls_per_turn=MAXIMUM_TOOL_CALLS_PER_TURN,
        messages=[
            {"role": "system", "content": build_system_prompt(revision=revision)}
        ],
        # This gate stands in for the live UI, so it holds the UI's
        # contract: a turn that changes the scene declares its plan
        # first. The 3DCodeBench batch driver deliberately does not —
        # see AgentSession.require_plan.
        require_plan=True,
        disabled_tools=disabled_tools,
    )
    try:
        for prompt in scenario.prompts:
            print(f"[{scenario.name}] [user] {prompt}", flush=True)
            result.answers.append(session.send(prompt, on_event=on_event))
        bpy.context.view_layer.update()
        result.failures = scenario.check()
        result.passed = not result.failures
    except Exception:  # noqa: BLE001 — recorded as the scenario's finding
        result.error = traceback.format_exc()[-1500:]
    return result


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--only", default="", help="comma-separated scenario names")
    parser.add_argument("--revision", type=int, default=DEFAULT_PROMPT_REVISION)
    parser.add_argument("--model", default="")
    # `None` means "leave the config default"; an explicit empty string
    # means "no separate eye — the writer looks at its own renders",
    # which is exactly how a vision-capable writer runs.
    parser.add_argument("--vision-model", default=None)
    parser.add_argument(
        "--no-hatch",
        action="store_true",
        help="withhold run_python entirely; the op vocabulary has to carry every scenario (OT-11)",
    )
    return parser.parse_args(argv)


def main(argv) -> int:
    arguments = parse_arguments(argv)
    wanted = {name.strip() for name in arguments.only.split(",") if name.strip()}
    scenarios = [s for s in SCENARIOS if not wanted or s.name in wanted]
    unknown = wanted - {s.name for s in SCENARIOS}
    if unknown:
        raise SystemExit(f"unknown scenarios: {sorted(unknown)}")

    overrides: dict = {}
    if arguments.model:
        overrides["model"] = arguments.model
    if arguments.vision_model is not None:
        overrides["vision_model"] = arguments.vision_model

    stamp = _datetime.datetime.now(_datetime.UTC).strftime("%Y%m%d-%H%M%S")
    output_directory = OUTPUT_ROOT / stamp
    output_directory.mkdir(parents=True, exist_ok=True)

    disabled_tools = frozenset({"run_python"}) if arguments.no_hatch else frozenset()
    results = [
        run_scenario(s, arguments.revision, output_directory, overrides, disabled_tools)
        for s in scenarios
    ]

    summary = {
        "revision": arguments.revision,
        "no_hatch": arguments.no_hatch,
        "results": [r.__dict__ for r in results],
    }
    (output_directory / "summary.json").write_text(json.dumps(summary, indent=1))
    print("\n=== chat E2E ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(
            f"{status} {r.name:<10} {r.tool_calls:>3} tool calls, {r.hatch_attempts} hatch"
        )
        for failure in r.failures:
            print(f"      - {failure}")
        if r.error:
            print(f"      ! {r.error.strip().splitlines()[-1]}")
    passed = sum(r.passed for r in results)
    print(f"{passed}/{len(results)} scenarios passed — {output_directory}")
    # OT-11: the scenarios the vocabulary did not carry. Under --no-hatch
    # a failure IS the evidence; with the hatch offered, an attempt is.
    needing_hatch = [
        r for r in results if r.hatch_attempts or (arguments.no_hatch and not r.passed)
    ]
    if needing_hatch:
        print(
            "MISSING-OP EVIDENCE (for OT-12): "
            + ", ".join(
                f"{r.name} ({r.hatch_attempts} hatch attempt(s), {'PASS' if r.passed else 'FAIL'})"
                for r in needing_hatch
            )
        )
    else:
        print(
            "MISSING-OP EVIDENCE (for OT-12): none — every scenario built on op tools alone"
        )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    extra = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    # Blender exits 0 on an uncaught Python exception, so a run that
    # died would read as a success (OT-32).
    from blended.run.script_exit import run_script_main

    raise SystemExit(run_script_main(main, extra))
