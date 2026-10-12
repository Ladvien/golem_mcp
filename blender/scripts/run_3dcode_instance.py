"""Run ONE 3DCodeBench instance through the agent, inside a real Blender.

    blender --background --factory-startup \\
        --python scripts/run_3dcode_instance.py -- \\
        --instance ArmChair_seed0 --bench-root /Users/ladvien/3dcodebench

3DCodeBench (DOI 10.48550/arXiv.2606.01057) scores a STANDALONE script: it re-executes `<inst>/<inst>.py`
from an empty scene in a bare Blender and measures the mesh that comes
out. This harness does not write scripts — it drives a live `bpy`
session through `run_python` chunks. The bridge is that the chunks ARE
the script: concatenating the chunks whose Python actually executed
yields exactly the artifact the benchmark re-bakes.

Which calls count is a correctness question, not a convenience one (see
evaluate/bench_bridge.py, which now owns the rule and the assembly). A
chunk whose Python raised must be excluded (including it guarantees a
re-bake failure and understates the harness); a chunk whose Python ran
and only blended's own analyzer gate objected must be INCLUDED, because
that gate is this harness's standard, not 3DCodeBench's, and the
geometry exists either way. The three accepted result prefixes below are
read off `src/blended/agent/tools.py` and `HarnessResult.summary()`.

Nothing here writes to `_evaluate/` — a benchmark run must never enter
the canonical convergence evidence.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(f"No .venv under {REPOSITORY_ROOT}.")
    return candidates[-1]


sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT))
os.chdir(REPOSITORY_ROOT)

# The task text is `blended.evaluate.bench_task_prompt.OPS_TASK_TEMPLATE`:
# one definition. The production runner sends it as is. The fine-tune
# decision experiment's raw-bpy arms send `RAW_TASK_TEMPLATE`, which is it
# with `CHUNK_RULE` removed; its op arms send
# `SINGLE_SHOT_OPS_TASK_TEMPLATE`, which is it plus `SINGLE_SHOT_RULE`.

PROMPT_FILENAMES = {
    "description": "prompt_description.txt",
    "instruction": "prompt_instruction.txt",
}


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--results-root", default="results/text_to_3D_agent")
    parser.add_argument("--model-dir", default="blended-deepseek-v4-pro")
    parser.add_argument(
        "--prompt-variant",
        choices=("description", "instruction"),
        default="description",
    )
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument(
        "--reference-images-root",
        default="",
        help="<root>/<inst>/images/Image_0{05,15,25,35}.png: the bench's image-to-3D "
        "track. All four views must exist or the instance is refused before any "
        "model call (blended.evaluate.bench_reference_views).",
    )
    parser.add_argument("--max-tool-calls", type=int, default=24)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.loop import (
        AgentSession,
        ModelConfig,
        OllamaClient,
        dispatch_here,
    )
    from blended.capture.reference_photo import normalize_reference_photo
    from blended.evaluate.bench_bridge import (
        RecordedCall,
        canonical_orientation_epilogue,
        prelude,
        standalone_script,
    )
    from blended.evaluate.bench_reference_views import reference_view_paths
    from blended.evaluate.bench_task_prompt import OPS_TASK_TEMPLATE
    from blended.ops.canonical_orientation import apply_canonical_depth_axis
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    # The image-to-3D track (DOI 10.48550/arXiv.2606.01057): the four
    # reference views ride the task message as reference images and the
    # eye reads them for the writer. Resolved BEFORE the scene, the
    # connection or any model call, and never defaulted: an instance run
    # without its views beside instances run with them is a different
    # experiment scored as the same one.
    reference_views: tuple[Path, ...] = ()
    if arguments.reference_images_root:
        reference_views = reference_view_paths(
            Path(arguments.reference_images_root), arguments.instance
        )
    task_metadata = {
        "task": "image_to_3d" if reference_views else "text_to_3d",
        "reference_views": [str(path) for path in reference_views],
    }

    bench_root = Path(arguments.bench_root).resolve()
    prompt_path = (
        bench_root
        / "data"
        / arguments.instance
        / PROMPT_FILENAMES[arguments.prompt_variant]
    )
    if not prompt_path.exists():
        print(f"[ERR] missing {prompt_path}", flush=True)
        return 1
    description = prompt_path.read_text().strip()

    work_directory = (
        bench_root / arguments.results_root / arguments.model_dir / arguments.instance
    )
    work_directory.mkdir(parents=True, exist_ok=True)
    script_path = work_directory / f"{arguments.instance}.py"
    metadata_path = work_directory / ".agent_meta.json"
    if script_path.exists() and not arguments.overwrite:
        print(f"[SKIP] {arguments.instance}", flush=True)
        return 0

    # A fresh, empty scene: the benchmark re-bakes from empty, so the run
    # must not be able to lean on a default cube.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))

    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        metadata_path.write_text(
            json.dumps(
                {
                    "instance": arguments.instance,
                    **task_metadata,
                    "model": client.config.model,
                    "status": "ERR_CONNECTION",
                    "error": status.detail,
                },
                indent=2,
            )
        )
        return 1

    # The system prompt is NOT overridden: AgentSession.__post_init__
    # seeds the pinned working agreement when `messages` is empty, and
    # that prompt is precisely what is under test here.
    # Every dispatched call, as the bridge needs it (OT-20): the tool, its
    # VALIDATED arguments when the tool validated them, and the stage its
    # Python reached — the fact the inclusion rule reads.
    recorded: list[RecordedCall] = []

    def scene_signature():
        """Ground truth from `bpy.data`, not from the outcome: what the
        scene holds, including objects never linked. A name alone is not
        enough — a boolean rewrites a mesh in place — so the vertex count
        rides along (OT-31)."""
        return tuple(
            sorted(
                (
                    obj.name,
                    len(obj.data.vertices)
                    if getattr(obj.data, "vertices", None) is not None
                    else -1,
                )
                for obj in bpy.data.objects
            )
        )

    def recording_dispatch(tool_name, arguments_dict, output_directory):
        before = scene_signature()
        outcome = dispatch_here(tool_name, arguments_dict, output_directory)
        recorded.append(
            RecordedCall(
                tool_name=tool_name,
                arguments=(
                    outcome.validated_arguments
                    if outcome.validated_arguments is not None
                    else arguments_dict
                ),
                stage_reached=outcome.stage_reached,
                # A call that raised PART WAY still changed the scene the
                # rest of the conversation was written against, and the
                # bake has to reproduce that (OT-31).
                changed_scene=scene_signature() != before,
            )
        )
        return outcome

    session = AgentSession(
        client=client,
        output_directory=work_directory / "_agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        dispatch=recording_dispatch,
    )

    transcript_path = work_directory / ".agent_transcript.txt"
    transcript: list[str] = []

    def on_event(kind: str, text: str) -> None:
        transcript.append(f"--- {kind} ---\n{text}")
        preview = text if len(text) <= 400 else text[:400] + " ..."
        print(f"[{kind}] {preview}", flush=True)

    task_text = OPS_TASK_TEMPLATE.format(description=description)
    # Re-encoded through the one reference-image path the chat UI uses
    # (size-capped PNGs under the run's own directory), so a bench view
    # and a user's photograph reach the writer the same way.
    normalized_views = tuple(
        normalize_reference_photo(view, work_directory / "_agent")
        for view in reference_views
    )
    print(f"[instance] {arguments.instance}", flush=True)
    started = time.monotonic()
    try:
        session.send(task_text, on_event=on_event, reference_images=normalized_views)
    except RuntimeError as model_error:
        # The transport died mid-run (measured: an Ollama cloud 502 with
        # "no route to host"). That is an INVALID run, not a modeling
        # failure, so no `<inst>.py` is written: the sweep's skip logic
        # keys on that file, and emitting a partial script here would
        # bake an infrastructure hiccup into the harness's score and
        # make the instance permanently un-rerunnable. Record the reason
        # and leave the instance re-runnable.
        duration_seconds = round(time.monotonic() - started, 2)
        transcript_path.write_text("\n\n".join(transcript))
        metadata_path.write_text(
            json.dumps(
                {
                    "instance": arguments.instance,
                    **task_metadata,
                    "model": client.config.model,
                    "status": "ERR_MODEL_CALL",
                    "duration_s": duration_seconds,
                    "num_turns": len(recorded),
                    "error": str(model_error)[:1000],
                },
                indent=2,
            )
        )
        print(f"[ERR_MODEL_CALL] {arguments.instance} {model_error}", flush=True)
        return 1
    duration_seconds = round(time.monotonic() - started, 2)
    transcript_path.write_text("\n\n".join(transcript))

    script = standalone_script(
        recorded,
        prelude(str(venv_site_packages()), str(REPOSITORY_ROOT / "src")),
        canonical_orientation_epilogue(),
    )
    included = script.included_count

    # The scored orientation, applied deterministically to the live scene
    # so the meta record matches what the emitted script will produce on
    # re-bake. No try/except: an object that cannot be oriented is a
    # broken run, and a silent skip here would score as a shape error.
    canonical_orientation = apply_canonical_depth_axis() if included else None

    script_text = script.text
    script_path.write_text(script_text)

    metadata_path.write_text(
        json.dumps(
            {
                "instance": arguments.instance,
                **task_metadata,
                "model": client.config.model,
                "status": "OK_AGENT_DONE" if included else "ERR_NO_SCRIPT",
                "duration_s": duration_seconds,
                "code_chars": len(script_text),
                "num_turns": len(recorded),
                # Calls that emit geometry (run_python chunks AND op calls).
                "n_chunks_included": script.included_count,
                "n_chunks_excluded": script.excluded_count,
                "n_op_calls_included": script.op_call_count,
                "canonical_orientation": canonical_orientation,
                "max_tool_calls": arguments.max_tool_calls,
                "writer": client.config.model,
                "eye": client.config.vision_model,
                "prompt_variant": arguments.prompt_variant,
            },
            indent=2,
        )
    )
    print(
        f"[{'OK_AGENT_DONE' if included else 'ERR_NO_SCRIPT'}] {arguments.instance} "
        f"calls={script.included_count}/{len(recorded)} "
        f"(ops {script.op_call_count}) {duration_seconds}s",
        flush=True,
    )
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from blended.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
