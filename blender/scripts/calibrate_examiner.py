"""Calibrate the examiner: measure its defect detection on a fixture zoo.

    make calibrate-eye            (full zoo: 4 defects + 5 controls)
    make calibrate-eye ARGS="--only missing_leg"   (one fixture, live check)

Each fixture is built by REPLAYING the converged run for its brief (the
same replay the golden tests use) and damaging it through the existing
ops. Each fixture is then examined EXACTLY the way the loop examines a
run: `examine_asset` against the brief's golden per-view directory —
two eye calls per view (reference-first and test-first, MT-bench
position-bias mitigation) — and the verdict comes from the closed tag
vocabulary, not from substring scoring. The old scorer (measure_eye)
counted a denial as a sighting; this calibration's scoring is exact tag
comparison, so negation is not a scoring surface (see mistake memory
"the-eye-scorer-counted-a-denial-as-a-sighting").

Output `_evaluate/eye_calibration.json` licenses machine verdicts:
`Calibration.problems()` must be empty before the loop runs with
`--examiner auto`. The license is identity-bound: a prompt or model
change invalidates the recorded numbers by construction.

Thresholds live in `examiner.py`; their justification: RESP measures
oracle-reference recall 0.76 / auto-reference recall 0.69 for the small
open model against 0.28 for no reference (10.48550/arXiv.2604.11082),
and one false alarm on a clean control ends refinement early (TikZ
10.48550/arXiv.2606.15693), so control specificity must be exactly 1.0.

Runs under `blender --background --factory-startup`.
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


def _fixtures() -> dict:
    """Fixture name -> (brief name, expected tags, damage callable).

    Damage callables receive the replayed objects and mutate the scene.
    Detection = non-empty intersection of reported deviations with the
    expected tags; a control is clean only when deviations is empty AND
    the examiner did not abstain.
    """
    return {
        "missing_leg": (
            "three_leg_stool",
            ("missing_part", "wrong_count"),
            lambda objects: _delete_stool_leg_at_positive_x(objects[0]),
        ),
        "floating_seat": (
            "three_leg_stool",
            ("floating_part", "offset_part"),
            lambda objects: _translate_seat(objects[0], 0.05),
        ),
        # fat_seat (seat scaled 1.5x -> wrong_proportion) is NOT here.
        # `wrong_proportion` is owned by the form gate, which measures
        # every named dimension against a tolerance: the damaged seat
        # fails at seat_diameter_x 0.6000 against 0.4000 +/- 0.0200
        # (measured 2026-09-06, outputs/gate_covers_fixture.py). A
        # fixture whose defect a measurement catches exactly is not the
        # eye's job, so it moved to
        # tests/blender/test_acceptance_gate.py — see
        # MEASURED_DEVIATION_TAGS in evaluate/examiner.py.
        "sealed_drain": (
            "planter_box",
            ("missing_feature",),
            lambda objects: _seal_drain_hole(objects[0]),
        ),
        "lid_offset": (
            "crate_with_lid",
            ("offset_part",),
            lambda objects: _offset_lid(objects[1], 0.08),
        ),
        # Controls: free (replay, no damage) — a known-clean asset must
        # draw no deviations and no abstention.
        "clean_stool": ("three_leg_stool", (), None),
        "clean_planter": ("planter_box", (), None),
        "clean_crate": ("uv_crate", (), None),
        "clean_column": ("ribbed_column", (), None),
        "clean_crate_with_lid": ("crate_with_lid", (), None),
    }


def _cross_run_controls() -> dict:
    """Control name -> (brief, candidate iteration, reference revision).

    A CROSS-RUN control is two INDEPENDENT gate-clean runs of the same
    brief, on the same lane, at the same prompt identity: the candidate
    is replayed from one run, the reference is the exemplar minted from
    the other. Any deviation is a false alarm by construction, and this
    is the ONLY regime the convergence loop actually uses — the
    same-run controls in `_fixtures` compare a run against a reference
    minted from itself, which is pixel-identical input.

    Pairs measured from `_evaluate/iterations.jsonl` on 2026-09-06:
    the v11 exemplars were minted from iterations 56-60 and the
    following cycle produced independent gate-clean runs 62-65 on the
    same claude-code lane. `crate_with_lid` is absent on purpose — its
    only second v11 run (iteration 61) failed the structural gate, and
    a damaged candidate is not a control. Recording the gap beats
    inventing a pair.
    """
    return {
        "cross_run_planter": ("planter_box", 62, 11),
        "cross_run_column": ("ribbed_column", 63, 11),
        "cross_run_stool": ("three_leg_stool", 64, 11),
        "cross_run_crate": ("uv_crate", 65, 11),
    }


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    parser.add_argument("--renders", default="_evaluate/eye_calibration")
    parser.add_argument("--output", default="_evaluate/eye_calibration.json")
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument(
        "--only",
        default="",
        help="run one fixture and print its verdict without rewriting "
        "the calibration file (the cheap live check)",
    )
    parser.add_argument(
        "--cross-run-only",
        action="store_true",
        help="measure ONLY the cross-run controls and print the "
        "false-alarm table without rewriting the calibration file; the "
        "regime the loop actually uses (see the audit doc)",
    )
    return parser.parse_args(argv)


def _delete_stool_leg_at_positive_x(blender_object) -> None:
    """Delete the +X leg's faces (the bearing-0 leg on the foot circle).

    The terminal stool (iterations 47/42/34) has legs at foot-circle
    radius 0.14 with bearings 0/120/240 and a seat whose bottom sits at
    z=0.51. Faces below z=0.50 near +X with |y| < 0.05 belong to the
    +X leg only; the 120 and 240 degree legs sit at x=-0.07.
    """
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        leg_faces = [
            face
            for face in working_mesh.faces
            if (centre := face.calc_center_median()).z < 0.50
            and 0.05 < centre.x < 0.20
            and abs(centre.y) < 0.05
        ]
        bmesh.ops.delete(working_mesh, geom=leg_faces, context="FACES")
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _translate_seat(blender_object, offset_z_m: float) -> None:
    """Move the seat (everything above the leg tops) up by `offset_z_m`."""
    import bmesh

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        for vertex in working_mesh.verts:
            if vertex.co.z > 0.505:
                vertex.co.z += offset_z_m
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()


def _seal_drain_hole(blender_object) -> None:
    """Union a plug into the drain hole so it reads as sealed."""
    from blended.ops import add_cylinder, boolean_union, link_into_scene

    plug_name = add_cylinder(
        "DrainPlug",
        radius_m=0.014,
        height_m=0.025,
        location_m=(0.0, 0.0, 0.01),
    )
    link_into_scene(plug_name)
    boolean_union(blender_object.name, plug_name)


def _offset_lid(lid_object, offset_x_m: float) -> None:
    """Slide the lid sideways off the crate body."""
    lid_object.location.x += offset_x_m


def main(argv) -> int:
    import bpy

    from blended.agent.loop import ModelConfig, OllamaClient, VisionDescriber
    from blended.capture import CaptureSettings, capture_views
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.examiner import (
        CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY,
        DEVIATION_TAGS,
        EXAMINED_VIEW_NAMES,
        examine_asset,
        examiner_identity,
    )
    from blended.evaluate.replay import load_record, replay_record

    arguments = parse_arguments(argv)

    # A typo'd fixture name is free to catch, so catch it before paying
    # for a connection probe.
    fixtures = _fixtures()
    only = arguments.only
    if only:
        if only not in fixtures:
            raise SystemExit(
                f"unknown fixture {only!r}. Known: {', '.join(sorted(fixtures))}"
            )
        fixtures = {only: fixtures[only]}

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))
    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(f"Model unreachable: {status.detail}")

    vision_model = client.config.vision_model
    eye = VisionDescriber(client, vision_model)
    render_root = Path(arguments.renders)
    render_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(arguments.output)

    def _examine_replay(
        label: str,
        brief_name: str,
        candidate_iteration: int,
        reference_revision: int,
        damage=None,
    ):
        """Replay one recorded run, render it, examine it. Returns the
        verdict and the identity of the reference it was judged against.
        """
        bpy.ops.wm.read_factory_settings(use_empty=True)
        brief = get_brief(brief_name)
        record = load_record(Path(arguments.log), candidate_iteration)
        built = replay_record(record, brief.part_names)
        if damage is not None:
            damage(built)
        bpy.context.view_layer.update()

        render_directory = render_root / label
        render_directory.mkdir(parents=True, exist_ok=True)
        captured = capture_views(
            built[0],
            render_directory,
            settings=CaptureSettings(),
            extra_objects=tuple(built[1:]),
        )
        missing_views = set(EXAMINED_VIEW_NAMES) - set(captured)
        if missing_views:
            raise SystemExit(
                f"{label}: capture_views did not produce {sorted(missing_views)}"
            )
        golden_directory = GOLDEN_ROOT / f"{brief_name}_v{reference_revision}"
        return examine_asset(
            eye, golden_directory, render_directory, brief, vision_model
        )

    def _measure_cross_run_controls() -> list[dict]:
        """The false-alarm rate in the regime the loop uses."""
        records: list[dict] = []
        for name, (brief_name, candidate, revision) in sorted(
            _cross_run_controls().items()
        ):
            print(
                f"\n=== cross-run control {name} "
                f"(brief {brief_name}, candidate iteration {candidate} "
                f"vs exemplar v{revision}) ===",
                flush=True,
            )
            verdict = _examine_replay(name, brief_name, candidate, revision)
            clean = verdict.deviations == () and not verdict.abstained
            records.append(
                {
                    "name": name,
                    "brief": brief_name,
                    "candidate_iteration": candidate,
                    "reference_revision": revision,
                    "deviations": list(verdict.deviations),
                    "abstained": verdict.abstained,
                    "clean": clean,
                    "view_tags": [
                        [view.view_name, list(view.order_consistent_tags)]
                        for view in verdict.views
                    ],
                }
            )
            print(verdict.summary(), flush=True)
            print(
                f"[cross-run] {name}: clean={clean} "
                f"deviations={list(verdict.deviations)} "
                f"abstained={verdict.abstained}",
                flush=True,
            )
        return records

    if arguments.cross_run_only:
        cross_run_records = _measure_cross_run_controls()
        specificity = sum(r["clean"] for r in cross_run_records) / len(
            cross_run_records
        )
        print("\n=========== CROSS-RUN CONTROL SPECIFICITY ===========", flush=True)
        for row in cross_run_records:
            print(
                f"  {row['brief']:<16} candidate {row['candidate_iteration']:<4} "
                f"{'CLEAN' if row['clean'] else 'FALSE ALARM ' + str(row['deviations'])}",
                flush=True,
            )
        print(
            f"cross-run specificity: {specificity:.2f} "
            f"({sum(r['clean'] for r in cross_run_records)}/"
            f"{len(cross_run_records)}), threshold "
            f"{CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY}",
            flush=True,
        )
        print("--- per view, across all controls ---", flush=True)
        for view_name in EXAMINED_VIEW_NAMES:
            # DEVIATION tags only: every clean control also carries a
            # consistent `no_deviation`, so counting any tag would say
            # every view earns its two calls, which is the question.
            tagged = sum(
                1
                for row in cross_run_records
                for name, tags in row["view_tags"]
                if name == view_name and set(tags) & set(DEVIATION_TAGS)
            )
            print(
                f"  {view_name:<14} raised a deviation in "
                f"{tagged}/{len(cross_run_records)} clean controls",
                flush=True,
            )
        print(f"spent: {client.spent.summary()}", flush=True)
        print(f"[cross-run] {output_path} was NOT rewritten", flush=True)
        return 0

    fixture_records: list[dict] = []
    for fixture_name, (brief_name, expected_tags, damage) in sorted(fixtures.items()):
        print(f"\n=== fixture {fixture_name} (brief {brief_name}) ===", flush=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        brief = get_brief(brief_name)
        record = load_record(Path(arguments.log), _converging_iteration(brief_name))
        built = replay_record(record, brief.part_names)
        if damage is not None:
            damage(built)
        bpy.context.view_layer.update()

        render_directory = render_root / fixture_name
        render_directory.mkdir(parents=True, exist_ok=True)
        captured = capture_views(
            built[0],
            render_directory,
            settings=CaptureSettings(),
            extra_objects=tuple(built[1:]),
        )
        missing_views = set(EXAMINED_VIEW_NAMES) - set(captured)
        if missing_views:
            raise SystemExit(
                f"fixture {fixture_name}: capture_views did not produce "
                f"{sorted(missing_views)}"
            )

        golden_directory = GOLDEN_ROOT / f"{brief_name}_v{record['prompt_revision']}"
        verdict = examine_asset(
            eye, golden_directory, render_directory, brief, vision_model
        )
        if expected_tags:
            detected = bool(set(verdict.deviations) & set(expected_tags))
        else:
            detected = verdict.deviations == () and not verdict.abstained
        fixture_records.append(
            {
                "name": fixture_name,
                "brief": brief_name,
                "expected_tags": list(expected_tags),
                "deviations": list(verdict.deviations),
                "detected": detected,
                "abstained": verdict.abstained,
                # Advisory tags a gate owns; recorded so a re-licence
                # shows whether restricting the vocabulary worked.
                "measured_property_reports": list(verdict.measured_property_reports),
            }
        )
        print(verdict.summary(), flush=True)
        print(
            f"[fixture] {fixture_name}: expected {list(expected_tags)} "
            f"reported {list(verdict.deviations)} detected={detected} "
            f"abstained={verdict.abstained}",
            flush=True,
        )

    if only:
        print(
            f"[only] {only}: detected={fixture_records[0]['detected']} "
            f"deviations={fixture_records[0]['deviations']} "
            f"abstained={fixture_records[0]['abstained']}",
            flush=True,
        )
        print(
            f"[only] calibration file {output_path} was NOT rewritten",
            flush=True,
        )
        return 0

    defective = [f for f in fixture_records if f["expected_tags"]]
    controls = [f for f in fixture_records if not f["expected_tags"]]
    sensitivity = sum(f["detected"] for f in defective) / len(defective)
    control_specificity = sum(f["detected"] for f in controls) / len(controls)

    # The regime the loop actually uses is measured in the SAME run, so
    # a licence can never again be issued on same-run controls alone.
    cross_run_records = _measure_cross_run_controls()
    cross_run_specificity = sum(r["clean"] for r in cross_run_records) / len(
        cross_run_records
    )

    calibration = {
        "examiner_identity": examiner_identity(vision_model),
        "vision_model": vision_model,
        "recorded_at": _datetime.datetime.now(_datetime.UTC).isoformat(),
        "view_names": list(EXAMINED_VIEW_NAMES),
        "fixtures": fixture_records,
        "sensitivity": sensitivity,
        "control_specificity": control_specificity,
        "cross_run_control_specificity": cross_run_specificity,
        "cross_run_controls": cross_run_records,
    }
    output_path.write_text(
        json.dumps(calibration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("\n================ EXAMINER CALIBRATION ================", flush=True)
    print(
        f"sensitivity              : {sensitivity:.2f} "
        f"({sum(f['detected'] for f in defective)}/{len(defective)})",
        flush=True,
    )
    print(
        f"control specificity      : {control_specificity:.2f} "
        f"({sum(f['detected'] for f in controls)}/{len(controls)})",
        flush=True,
    )
    print(
        f"CROSS-RUN specificity    : {cross_run_specificity:.2f} "
        f"({sum(r['clean'] for r in cross_run_records)}/"
        f"{len(cross_run_records)}) "
        f"[threshold {CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY}]",
        flush=True,
    )
    print(f"examiner identity        : {calibration['examiner_identity']}", flush=True)
    print(f"spent                    : {client.spent.summary()}", flush=True)
    print(f"calibration written      : {output_path}", flush=True)
    return 0


def _converging_iteration(brief_name: str) -> int:
    """The converging run for this brief (kept beside the golden tests)."""
    return {
        "three_leg_stool": 47,
        "planter_box": 48,
        "uv_crate": 49,
        "ribbed_column": 50,
        "crate_with_lid": 51,
    }[brief_name]


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from blended.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
