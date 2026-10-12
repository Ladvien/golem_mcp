"""Pin per-view golden renders for the converged runs of a revision.

    make pin-golden-views REVISION=10

Writes `_evaluate/golden/<brief>_v<revision>/` — five views per brief,
plus a manifest that makes a mismatched reference impossible:

    {"brief": ..., "iteration": ..., "revision": ...,
     "prompt_identity": ..., "blender_series": ...,
     "captured_at": ..., "view_sha256": {...}}

The examiner verifies the manifest before every comparison, because a
stale or wrong-brief reference is a correctness bug: RESP measured an
irrelevant reference is WORSE than no reference at all (−0.23 F1 for
Qwen3-VL-8B, 10.48550/arXiv.2604.11082).

The source is the recorded run, replayed — NOT the exported .glb:
`evaluate/replay.py`'s docstring records that `ingest.import_glb`
recentres and re-grounds, which would move the very placement the
snapshot exists to pin.

Runs under `blender --background --factory-startup`.
"""

import argparse
import datetime as _datetime
import hashlib
import json
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
sys.path.insert(0, str(REPOSITORY_ROOT))
os.chdir(REPOSITORY_ROOT)

GOLDEN_ROOT = REPOSITORY_ROOT / "_evaluate" / "golden"


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.prompt_versions import get_revision
    from blended.capture import CaptureSettings, capture_views
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import load_record, replay_record
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    revision = get_revision(arguments.revision)
    from blended.evaluate.briefs import BRIEFS
    from blended.evaluate.iteration_log import (
        IterationLog,
        clean_cycle_for_identity,
    )

    brief_names = tuple(sorted(BRIEFS))
    converging_runs = clean_cycle_for_identity(
        IterationLog(Path(arguments.log)).records(), brief_names, revision.identity
    )
    missing_briefs = sorted(set(brief_names) - set(converging_runs))
    if missing_briefs:
        raise SystemExit(
            f"no clean run of {revision.identity} for {missing_briefs} in "
            f"{arguments.log}: a reference may only be minted from runs that "
            f"EXECUTED the revision being stamped. Run the suite at this "
            f"revision first (scripts/run_agent_task.py --revision "
            f"{arguments.revision} per brief), then mint."
        )
    briefs = sorted(converging_runs)

    for brief_name in briefs:
        iteration = converging_runs[brief_name]
        brief = get_brief(brief_name)
        record = load_record(Path(arguments.log), iteration)
        # The record is the registry of which text ran; the manifest is
        # written from the revision registry so a mismatch between the
        # two is loud instead of silently pinned.
        recorded_identity = record["prompt_identity"]
        print(
            f"[golden] {brief_name} iteration {iteration} recorded {recorded_identity}",
            flush=True,
        )
        if recorded_identity != revision.identity:
            raise SystemExit(
                f"iteration {iteration} ran {recorded_identity!r}, not "
                f"{revision.identity!r} — refusing to pin the wrong text"
            )

        bpy.ops.wm.read_factory_settings(use_empty=True)
        built = replay_record(record, brief.part_names)
        bpy.context.view_layer.update()

        directory = GOLDEN_ROOT / f"{brief_name}_v{revision.revision}"
        directory.mkdir(parents=True, exist_ok=True)
        captured = capture_views(
            built[0],
            directory,
            settings=CaptureSettings(),
            extra_objects=tuple(built[1:]),
        )
        view_hashes = {
            view_name: hashlib.sha256(path.read_bytes()).hexdigest()
            for view_name, path in sorted(captured.items())
        }
        manifest = {
            "brief": brief_name,
            "iteration": iteration,
            "revision": revision.revision,
            "prompt_identity": revision.identity,
            "blender_series": "5.2",
            "captured_at": _datetime.datetime.now(_datetime.UTC).isoformat(),
            "view_sha256": view_hashes,
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"[golden] wrote {len(view_hashes)} views + manifest to {directory}",
            flush=True,
        )
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from blended.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
