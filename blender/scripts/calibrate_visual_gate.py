"""Measure the visual gate's thresholds against the pinned goldens.

    make calibrate-visual-gate REVISION=10

Runs under `blender --background --factory-startup`. For every brief
with a pinned golden directory at that revision:

1. CONTROL run — each pinned golden view against ITSELF. Must read
   silhouette_iou == 1.0 and shading_rmse == 0.0 exactly; abort
   non-zero otherwise (scp saw three harness configurations silently
   produce IoU 0.9981 / 0.9891 / 0.117 on unchanged geometry).
2. CLEAN run — replay the iteration the manifest names (the same path
   pin_golden_views.py uses, because ingest.import_glb recentres and
   would move the placement the golden pins), re-capture with default
   CaptureSettings, compare per view, and record every number.
3. MUTATION run — Decimate at MUTATION_DECIMATE_RATIO on the replayed
   object, re-capture, re-compare. At least one view per brief must
   land outside the thresholds derived in step 4; abort non-zero if the
   mutation passes, because a gate that cannot fail reads as evidence.
4. Derive thresholds just OUTSIDE the accepted assets' worst measured
   reading and write _evaluate/visual_gate_calibration.json. Measured,
   never guessed: scp's pre-calibration guesses (0.98 / 0.030) failed
   all twelve views of a good asset.
"""

import argparse
import datetime as _datetime
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
CALIBRATION_PATH = REPOSITORY_ROOT / "_evaluate" / "visual_gate_calibration.json"

# A Decimate COLLAPSE at this ratio must push the mutation run outside
# the derived thresholds on at least one view per brief.
MUTATION_DECIMATE_RATIO = 0.25
# Thresholds sit just outside the accepted assets' worst reading.
IOU_MARGIN = 0.002
RMSE_MARGIN = 0.010

CAPTURE_VIEWS = ("front", "right", "top", "bottom", "three_quarter")


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    return parser.parse_args(argv)


def _golden_comparison(golden_directory, captured, view_name):
    """Compare one captured view against the pinned golden PNG."""
    from blended.evaluate.visual_diff import compare_view_files

    return compare_view_files(
        view_name,
        golden_directory / f"{view_name}.png",
        captured[view_name],
    )


def _capture_for(brief, built, directory):
    from blended.capture import CaptureSettings, capture_views

    directory.mkdir(parents=True, exist_ok=True)
    return capture_views(
        built[0],
        directory,
        settings=CaptureSettings(),
        extra_objects=tuple(built[1:]),
    )


def main(argv) -> int:
    import bpy

    from blended.agent.prompt_versions import get_revision
    from blended.capture import CaptureSettings
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import load_record, replay_record
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    revision = get_revision(arguments.revision)
    brief_names = sorted(
        directory.name.removesuffix(f"_v{revision.revision}")
        for directory in GOLDEN_ROOT.iterdir()
        if directory.is_dir()
        and directory.name.endswith(f"_v{revision.revision}")
        and (directory / "manifest.json").exists()
    )
    if not brief_names:
        raise SystemExit(
            f"no pinned golden directories at revision {revision.revision} "
            f"under {GOLDEN_ROOT}"
        )

    control_readings: dict[str, dict[str, dict]] = {}
    clean_readings: dict[str, dict[str, dict]] = {}
    mutation_readings: dict[str, dict[str, dict]] = {}

    for brief_name in brief_names:
        golden_directory = GOLDEN_ROOT / f"{brief_name}_v{revision.revision}"
        manifest = json.loads(
            (golden_directory / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest["prompt_identity"] != revision.identity:
            raise SystemExit(
                f"{brief_name}: golden pins {manifest['prompt_identity']!r}, "
                f"revision {revision.identity!r} — refusing to calibrate "
                f"against a mismatched reference"
            )

        # 1. CONTROL: golden against itself. Three harness configurations
        # have silently produced IoU < 1.0 on unchanged geometry, so the
        # image loading path itself is what this run validates.
        for view_name in CAPTURE_VIEWS:
            comparison = _golden_comparison(
                golden_directory,
                {view_name: golden_directory / f"{view_name}.png"},
                view_name,
            )
            if comparison.silhouette_iou != 1.0 or comparison.shading_rmse != 0.0:
                raise SystemExit(
                    f"{brief_name} {view_name}: golden vs itself read "
                    f"IoU {comparison.silhouette_iou} / RMSE "
                    f"{comparison.shading_rmse} — the image loading path is "
                    f"corrupting pixels"
                )
            control_readings.setdefault(brief_name, {})[view_name] = {
                "silhouette_iou": comparison.silhouette_iou,
                "shading_rmse": comparison.shading_rmse,
            }

        brief = get_brief(brief_name)
        record = load_record(Path(arguments.log), manifest["iteration"])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        built = replay_record(record, brief.part_names)
        bpy.context.view_layer.update()

        # 2. CLEAN run: the replay IS the golden's source geometry, so a
        # clean reading off the same replay is the closest a machine can
        # get to "unchanged".
        clean_directory = (
            REPOSITORY_ROOT / "_evaluate" / "visual_gate_calibration" / brief_name
        )
        captured = _capture_for(brief, built, clean_directory)
        for view_name in CAPTURE_VIEWS:
            comparison = _golden_comparison(golden_directory, captured, view_name)
            clean_readings.setdefault(brief_name, {})[view_name] = {
                "silhouette_iou": comparison.silhouette_iou,
                "shading_rmse": comparison.shading_rmse,
            }

        # 3. MUTATION run: a Decimate at 25% must move the render.
        for built_object in built:
            decimate = built_object.modifiers.new(
                name="CalibrationDecimate", type="DECIMATE"
            )
            decimate.decimate_type = "COLLAPSE"
            decimate.ratio = MUTATION_DECIMATE_RATIO
        bpy.context.view_layer.update()
        mutation_directory = (
            REPOSITORY_ROOT
            / "_evaluate"
            / "visual_gate_calibration"
            / f"{brief_name}_mutated"
        )
        captured = _capture_for(brief, built, mutation_directory)
        for view_name in CAPTURE_VIEWS:
            comparison = _golden_comparison(golden_directory, captured, view_name)
            mutation_readings.setdefault(brief_name, {})[view_name] = {
                "silhouette_iou": comparison.silhouette_iou,
                "shading_rmse": comparison.shading_rmse,
            }
            clean_reading = clean_readings[brief_name][view_name]
            print(
                f"[{brief_name}] {view_name}: clean "
                f"IoU {clean_reading['silhouette_iou']:.4f} "
                f"RMSE {clean_reading['shading_rmse']:.4f} | "
                f"mutated IoU {comparison.silhouette_iou:.4f} "
                f"RMSE {comparison.shading_rmse:.4f}",
                flush=True,
            )

    # Derive thresholds from the CLEAN readings only, then check the
    # mutation against them — the gate must be able to fail.
    all_clean = [
        readings[view_name]
        for brief_readings in clean_readings.values()
        for readings in (brief_readings,)
        for view_name in CAPTURE_VIEWS
    ]
    minimum_silhouette_iou = round(
        min(reading["silhouette_iou"] for reading in all_clean) - IOU_MARGIN, 4
    )
    maximum_shading_rmse = round(
        max(reading["shading_rmse"] for reading in all_clean) + RMSE_MARGIN, 4
    )

    for brief_name, brief_readings in mutation_readings.items():
        outside = [
            view_name
            for view_name in CAPTURE_VIEWS
            if brief_readings[view_name]["silhouette_iou"] < minimum_silhouette_iou
            or brief_readings[view_name]["shading_rmse"] > maximum_shading_rmse
        ]
        if not outside:
            raise SystemExit(
                f"{brief_name}: no mutated view landed outside the derived "
                f"thresholds — a gate that cannot fail reads as evidence. "
                f"Not writing calibration."
            )

    payload = {
        "minimum_silhouette_iou": minimum_silhouette_iou,
        "maximum_shading_rmse": maximum_shading_rmse,
        "recorded_at": _datetime.datetime.now(_datetime.UTC).isoformat(),
        "revision": revision.revision,
        "blender_series": "5.2",
        "capture_resolution_px": CaptureSettings().resolution_px,
        "iou_margin": IOU_MARGIN,
        "rmse_margin": RMSE_MARGIN,
        "control": control_readings,
        "clean": clean_readings,
        "mutation": mutation_readings,
    }
    CALIBRATION_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"[calibrate] wrote {CALIBRATION_PATH}: IoU >= {minimum_silhouette_iou}, "
        f"RMSE <= {maximum_shading_rmse}",
        flush=True,
    )
    return 0


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from blended.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
