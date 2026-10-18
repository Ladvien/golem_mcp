"""Rebuild the scene an iteration produced, from its own log.

    make replay ITERATION=10

The iteration log records every tool call in full — run_python sources
and op calls alike — so a scored run is reproducible: replaying it recreates the exact mesh, re-scores it
against the brief, and writes a .glb. A render answers questions a
single viewpoint can answer; a .glb answers the rest — measured
2026-08-22, the contact sheet's front view puts a stool's 120 and 240
degree legs at the same world x, so it cannot show leg spacing at all.
"""

import argparse
import os
import sys
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
os.chdir(REPOSITORY_ROOT)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from golem_blender.capture import CaptureSettings, capture_contact_sheet
    from golem_blender.evaluate.acceptance import evaluate_brief, refine_brief
    from golem_blender.evaluate.briefs import get_brief
    from golem_blender.evaluate.replay import load_record, replay_record, steps_applied
    from golem_blender.export.gltf import export_glb

    arguments = parse_arguments(argv)
    record = load_record(Path(arguments.log), arguments.iteration)
    brief = get_brief(record["brief_name"])

    bpy.ops.wm.read_factory_settings(use_empty=True)

    def announce(index, total, result):
        print(
            f"[replay] chunk {index}/{total}: {'ok' if result.ok else 'FAILED'}",
            flush=True,
        )

    built = replay_record(record, brief.part_names, on_chunk=announce)
    # The record's form_summary is the report scored against the brief
    # WITH the refinement steps the run actually executed applied — the
    # driver records the terminal state. Score the replay the same way,
    # or a run that ended at 0.55 m reads as a failure against the
    # 0.45 m brief. Which steps ran is recorded per step in
    # `refinement_locality`, so steps the run never executed are not
    # composed in.
    expected_brief = brief
    for step in steps_applied(record, brief):
        expected_brief = refine_brief(expected_brief, step)
    report = evaluate_brief(expected_brief)
    print(report.summary(expected_brief), flush=True)

    render_directory = Path(record["render_path"]).parent
    sheet = capture_contact_sheet(
        built[0],
        render_directory,
        settings=CaptureSettings(),
        extra_objects=tuple(built[1:]),
    )
    print(f"[replay] wrote {sheet}", flush=True)

    for built_object in built:
        destination = render_directory / f"{built_object.name}.glb"
        export_report = export_glb(
            built_object, destination, blend_path=destination.with_suffix(".blend")
        )
        print(
            f"[replay] wrote {destination} "
            f"({export_report.file_size_bytes} bytes), round trip "
            f"{'OK' if export_report.passes(brief.budget) else 'FAILED'}",
            flush=True,
        )
        for failure in export_report.round_trip_failures(brief.budget):
            print(f"   - {failure}", flush=True)
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from golem_blender.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
