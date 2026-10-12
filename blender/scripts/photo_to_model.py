"""Photo in, model out: one turn, one photograph, one built asset.

    make photo-to-model ARGS="--photo path/to/thing.jpg"
    make photo-to-model ARGS="--photo thing.jpg --prompt 'Build this as a
        low-poly prop.' --model deepseek-v4-pro:cloud
        --vision-model kimi-k2.7-code:cloud"

The picture, not the prompt, carries the shape: the default prompt says
only "this object", so whatever the writer builds it built from pixels.
The writer never sees the photo itself: the separate eye reads it and the
writer gets that reading (`ModelConfig.describe_routing`). The default
config (`claude-code:sonnet` as both writer and eye) has NO separate eye,
so a bare run exits 2: name an eye that is not the writer. The proof is
the contact sheet this prints at the end.

Runs inside `blender --background`: bpy is on the main thread, so
`dispatch_here` — the AgentSession default — is the right dispatcher.

There is no DIMENSIONAL acceptance spec: a photograph carries no
dimensions, so the structural gate is REPORTED, not enforced. What the
lane now does have is a COMPARATIVE one — the examiner reads the
photograph against the three-quarter render in both orders and keeps
only the deviations that survive the swap, and a surviving deviation
exits non-zero. Three hard failures: building nothing at all, a turn
that raised (including an eye that could not read the photograph, which
is fatal here because the prompt names no shape), and a surviving
deviation. Abstention is recorded, never a failure. The gate needs an
eye that is not the writer, so `--vision-model ''` exits 2 before any
Blender work.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import sys
import traceback
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

# Never `_evaluate/`: tests/pure/test_convergence_rule.py reads the logs
# there, and a photo run is not an evaluation record.
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "photo_to_model"
DEFAULT_PROMPT_REVISION = 11
# Same ceiling as the chat gate: one extra failed chunk over the
# converged mesh budget.
MAXIMUM_TOOL_CALLS_PER_TURN = 36
# What the user says when the photo is doing the talking. It names no
# shape, no part and no dimension on purpose — anything the built model
# gets right about the object came from the picture.
DEFAULT_PROMPT = (
    "Build this object as a clean, low-poly game asset. Match the shape "
    "and proportions in the photo."
)
EVENT_PREVIEW_CHARACTERS = 300
# The photograph IS the specification, so it is the reference view.
# examine_view runs the position-swapped double pass and keeps only the
# tags that survive the swap, which is the whole reason it can be
# pointed at two arbitrary images.
EXAMINER_VIEW_NAME = "three_quarter"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--photo", required=True, help="the reference photograph")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--revision", type=int, default=DEFAULT_PROMPT_REVISION)
    parser.add_argument("--model", default="")
    # `None` means "leave the config default". An explicit empty string
    # or an eye equal to the writer means "no separate eye", which the
    # reference-photo gate refuses (exit 2).
    parser.add_argument("--vision-model", default=None)
    parser.add_argument(
        "--max-tool-calls", type=int, default=MAXIMUM_TOOL_CALLS_PER_TURN
    )
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.loop import (
        AgentSession,
        EyeUnreachable,
        ModelConfig,
        OllamaClient,
        VisionDescriber,
    )
    from blended.agent.system_prompt import build_system_prompt
    from blended.analyze import MeshBudget, analyze_object
    from blended.capture import CaptureSettings, capture_contact_sheet
    from blended.capture.reference_photo import normalize_reference_photo
    from blended.evaluate.examiner import (
        CANNOT_TELL_TAG,
        HALTING_DEVIATION_TAGS,
        examine_view,
    )
    from blended.export.gltf import export_glb

    arguments = parse_arguments(argv)
    overrides: dict = {}
    if arguments.model:
        overrides["model"] = arguments.model
    if arguments.vision_model is not None:
        overrides["vision_model"] = arguments.vision_model

    stamp = _datetime.datetime.now(_datetime.UTC).strftime("%Y%m%d-%H%M%S")
    output_directory = OUTPUT_ROOT / stamp
    output_directory.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    reference = normalize_reference_photo(
        Path(arguments.photo).resolve(), output_directory
    )
    print(f"[photo] {arguments.photo} -> {reference}", flush=True)

    transcript_path = output_directory / "transcript.jsonl"
    tool_call_count = 0

    def on_event(kind: str, text: str) -> None:
        nonlocal tool_call_count
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"kind": kind, "text": text}) + "\n")
        if kind == "tool":
            tool_call_count += 1
        preview = (
            text
            if len(text) <= EVENT_PREVIEW_CHARACTERS
            else text[:EVENT_PREVIEW_CHARACTERS] + " ..."
        )
        print(f"[{kind}] {preview}", flush=True)

    config = ModelConfig.from_environment(**overrides)
    # The gate at the end compares the PHOTOGRAPH against a render, and
    # `examine_view` needs an eye that is not the writer: a writer
    # grading its own build against the picture it was given is the
    # "critique held both the evidence and the verdict" failure this
    # repository has already paid for once. Refused before any Blender
    # work, so a run that cannot be graded does not cost a build.
    if not config.uses_separate_eye:
        print(
            "[FAIL] the reference-photo gate needs a separate eye: pass --vision-model",
            flush=True,
        )
        return 2
    client = OllamaClient(config)
    session = AgentSession(
        client=client,
        output_directory=output_directory / "agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        messages=[
            {
                "role": "system",
                "content": build_system_prompt(revision=arguments.revision),
            }
        ],
        # This driver stands in for the live UI, so it holds the UI's
        # contract: a turn that changes the scene declares its plan first.
        require_plan=True,
    )

    summary: dict = {
        "photo": str(Path(arguments.photo).resolve()),
        "normalized_photo": str(reference),
        "prompt": arguments.prompt,
        "writer_model": config.model,
        "vision_model": config.vision_model,
        "objects": [],
        "structural_failures": {},
        "sheet": "",
        "glb": [],
        "answer": "",
        "error": "",
        "eye_reachable": True,
        "photo_gate_deviations": [],
        "photo_gate_abstained": False,
        "photo_gate_reasoning": "",
    }

    def write_summary() -> None:
        """Every exit past the turn leaves a record.

        The no-mesh path used to return 1 with no summary at all, which
        is exactly the path an unreachable eye now takes — so the run
        with the most to explain was the one that explained nothing.
        """
        summary["tool_calls"] = tool_call_count
        (output_directory / "summary.json").write_text(json.dumps(summary, indent=1))

    print(f"[user] {arguments.prompt}", flush=True)
    answer = ""
    error = ""
    try:
        answer = session.send(
            arguments.prompt, on_event=on_event, reference_images=(reference,)
        )
    except EyeUnreachable:
        # Structural, not a traceback grep: `deliver_images` is fatal on
        # the reference-photo path precisely so this is distinguishable.
        summary["eye_reachable"] = False
        error = traceback.format_exc()[-1500:]
        print(f"[FAIL] the eye could not read the photograph:\n{error}", flush=True)
    except Exception:  # noqa: BLE001 — recorded as the run's finding
        error = traceback.format_exc()[-1500:]
        print(f"[FAIL] the turn raised:\n{error}", flush=True)
    summary["answer"] = answer
    summary["error"] = error

    bpy.context.view_layer.update()
    built = [
        scene_object
        for scene_object in bpy.context.scene.objects
        if scene_object.type == "MESH"
    ]
    if not built:
        print("[FAIL] the agent created no mesh", flush=True)
        write_summary()
        return 1

    # Reported, not enforced: a photograph carries no acceptance spec.
    budget = MeshBudget()
    structural_failures: dict[str, list[str]] = {}
    for scene_object in built:
        failures = analyze_object(scene_object).failures(budget)
        structural_failures[scene_object.name] = failures
        verdict = "OK" if not failures else f"{len(failures)} findings"
        print(f"[gate] {scene_object.name}: {verdict}", flush=True)
        for failure in failures:
            print(f"   - {failure}", flush=True)

    sheet = capture_contact_sheet(
        built[0],
        output_directory,
        settings=CaptureSettings(),
        extra_objects=tuple(built[1:]),
    )
    exported: list[str] = []
    for scene_object in built:
        destination = output_directory / f"{scene_object.name}.glb"
        export_report = export_glb(
            scene_object, destination, blend_path=destination.with_suffix(".blend")
        )
        exported.append(str(destination))
        print(
            f"[export] {destination} ({export_report.file_size_bytes} bytes)",
            flush=True,
        )

    # THE ACCEPTANCE SPEC THIS LANE DID NOT HAVE. The photograph is the
    # reference and the three-quarter render is the candidate;
    # `examine_view` runs both orders and keeps only the tags that
    # survive the swap, so a position-biased answer cannot decide the
    # run. A renamed capture convention must fail loud rather than skip
    # the gate, so a missing view raises instead of shrugging.
    test_view = output_directory / f"{EXAMINER_VIEW_NAME}.png"
    if not test_view.exists():
        raise FileNotFoundError(
            f"no {test_view}: capture_views writes one PNG per "
            f"VIEW_DIRECTIONS entry, so the examiner's view name and the "
            f"capture convention have drifted apart"
        )
    verdict = examine_view(
        VisionDescriber(client, config.vision_model),
        golden_view=reference,
        test_view=test_view,
        view_name=EXAMINER_VIEW_NAME,
    )
    photo_gate_deviations = tuple(
        tag for tag in verdict.order_consistent_tags if tag in HALTING_DEVIATION_TAGS
    )
    abstained = CANNOT_TELL_TAG in verdict.order_consistent_tags
    for tag in photo_gate_deviations:
        print(f"[photo-gate] surviving deviation: {tag}", flush=True)
    if abstained:
        # Recorded, never a failure — the examiner's semantics
        # everywhere else in this repository.
        print("[photo-gate] the examiner abstained", flush=True)
    if not photo_gate_deviations and not abstained:
        print("[photo-gate] no surviving deviation", flush=True)

    summary["objects"] = [scene_object.name for scene_object in built]
    summary["structural_failures"] = structural_failures
    summary["sheet"] = str(sheet)
    summary["glb"] = exported
    summary["photo_gate_deviations"] = list(photo_gate_deviations)
    summary["photo_gate_abstained"] = abstained
    summary["photo_gate_reasoning"] = verdict.reference_first_reasoning
    write_summary()
    print(f"[sheet] {sheet}", flush=True)
    if error:
        # A turn that RAISED is a failed run, not a run with a note. The
        # unreachable eye now lands here, because `deliver_images` is
        # fatal on the reference-photo path.
        return 1
    if photo_gate_deviations:
        return 1
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    # Blender exits 0 on an uncaught Python exception, so a run that
    # died would read as a success (OT-32).
    from blended.run.script_exit import run_script_main

    raise SystemExit(run_script_main(main, argv))
