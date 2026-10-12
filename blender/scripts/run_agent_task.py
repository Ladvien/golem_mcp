"""Run ONE brief through the agent, inside a real Blender, and score it.

    make converge BRIEF=planter_box REVISION=1 ITERATION=1

This is the RUN + RENDER + deterministic half of EXAMINE. It does not
judge the render — that is the visual pass, done by a human or a
supervising agent reading the contact sheet this writes. It ends by
appending one IterationRecord with everything measured.

Runs inside `blender --background`, so bpy is on the main thread and
`dispatch_here` is the correct dispatcher. Ordering is not negotiable:
the structural gate and the form gate BOTH run and are BOTH recorded
before anything renders, because a visual critique of a scene that
already failed a measurement is wasted tokens.
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


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--iteration", type=int, required=True)
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    parser.add_argument("--verdicts", default="_evaluate/verdicts.jsonl")
    parser.add_argument("--renders", default="_evaluate/renders")
    # The visual pass. `none` keeps the manual protocol: the driver
    # measures and renders, a human records the verdict afterwards.
    # `auto` hands the verdict to the calibrated examiner, which refuses
    # to run unless its calibration licenses it.
    parser.add_argument("--examiner", choices=("none", "auto"), default="none")
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    # Measured, not guessed. three_leg_stool needs 17 calls to build and
    # verify itself (iteration 10, a run that passed both deterministic
    # gates) and then has nothing left to answer with — three consecutive
    # runs ended in the exhaustion string holding a finished asset. 24
    # leaves room to report and to absorb one failed chunk, while still
    # capping a runaway loop: planter_box answers in 3.
    parser.add_argument("--max-tool-calls", type=int, default=24)
    # OT-13's acceptance: the vocabulary alone has to carry the brief.
    parser.add_argument(
        "--no-hatch", action="store_true", help="withhold run_python entirely"
    )
    return parser.parse_args(argv)


def main(argv) -> int:
    import bpy

    from blended.agent.loop import (
        AgentSession,
        ModelConfig,
        OllamaClient,
        VisionDescriber,
    )
    from blended.agent.prompt_versions import PINNED_PROMPT_REVISION, get_revision
    from blended.agent.system_prompt import (
        assembled_prompt_fingerprint,
        build_system_prompt,
    )
    from blended.agent.tool_event import TOOL_EVENT_KIND
    from blended.agent.tools import TOOL_SCHEMAS_FINGERPRINT
    from blended.analyze import analyze_object
    from blended.capture import CaptureSettings, capture_contact_sheet
    from blended.evaluate.acceptance import (
        RefinementOutcome,
        evaluate_brief,
        refine_brief,
    )
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.examiner import examiner_identity
    from blended.evaluate.iteration_log import IterationLog, IterationRecord
    from blended.evaluate.object_identity import (
        measure_locality,
        new_identity,
        stamp_identity,
    )
    from blended.evaluate.visual_diff import VisualGateNotCalibrated
    from blended.export.gltf import export_glb
    from blended.version import assert_supported_blender

    arguments = parse_arguments(argv)
    assert_supported_blender()

    brief = get_brief(arguments.brief)
    revision = get_revision(arguments.revision)
    # A second record for the same (iteration, brief) would be read as
    # the same run by every consumer keyed on that pair, and its render
    # directory would overwrite the first run's. `make converge` defaults
    # ITERATION to 1, which the pinned log already holds.
    if any(
        existing.iteration == arguments.iteration and existing.brief_name == brief.name
        for existing in IterationLog(Path(arguments.log)).records()
    ):
        raise SystemExit(
            f"iteration {arguments.iteration} {brief.name} is already in "
            f"{arguments.log}: pass an unused --iteration (ITERATION=N)"
        )
    render_directory = Path(arguments.renders) / (
        f"iteration{arguments.iteration:02d}_{brief.name}_v{revision.revision}"
    )
    render_directory.mkdir(parents=True, exist_ok=True)

    # A fresh scene per run. Convergence is about the prompt; leftover
    # geometry from a previous iteration would silently score for it.
    bpy.ops.wm.read_factory_settings(use_empty=True)

    configuration_overrides = {}
    if arguments.model:
        configuration_overrides["model"] = arguments.model
    if arguments.vision_model:
        configuration_overrides["vision_model"] = arguments.vision_model
    client = OllamaClient(ModelConfig.from_environment(**configuration_overrides))

    # If this run is to be examined by machine, establish the licence
    # BEFORE spending anything on it — a local file read, so it costs
    # nothing and comes first. Checking after the run would throw away a
    # measured record because the instrument was not calibrated, and the
    # measurement is the expensive part; it is not the examiner's to
    # discard.
    # TWO references, because two instruments ask different questions.
    #
    # The VISUAL GATE asks "did the render move from the accepted
    # state?", so its reference is the PINNED revision's — that is what
    # "accepted" means.
    #
    # The EXAMINER asks "does this asset deliver the brief?", and it
    # answers by comparison, so its reference must be an exemplar of the
    # configuration under test. Pointing it at the pinned reference
    # instead made it answer a third question nobody asked — "does this
    # look like the artifact another writer built?" — and every
    # incidental choice of that writer came back as a deviation.
    # Measured 2026-09-05 on the Claude Code lane: `material_missing`
    # because its browns are darker than deepseek's (planter
    # 0.35/0.22/0.12 against 0.55/0.35/0.20), `wrong_proportion`
    # because its stool is a different legitimate stool. Worse, the
    # verdicts were not stable — uv_crate came back `material_missing`
    # in one cycle and clean in the next on the same configuration — and
    # the examiner's licensed specificity of 1.00 was measured on
    # controls where candidate and reference come from the SAME run, so
    # it never covered this use at all.
    #
    # converge_auto's own preflight already demands the reference for
    # the revision under test; this is the half that disagreed.
    pinned_golden_directory = (
        Path("_evaluate/golden") / f"{brief.name}_v{PINNED_PROMPT_REVISION}"
    )
    candidate_golden_directory = (
        Path("_evaluate/golden") / f"{brief.name}_v{arguments.revision}"
    )
    golden_directory = pinned_golden_directory
    examiner_golden_directory = (
        candidate_golden_directory
        if (candidate_golden_directory / "manifest.json").exists()
        else pinned_golden_directory
    )
    if arguments.examiner == "auto":
        from blended.evaluate.examiner import load_calibration

        licence_problems = load_calibration().problems(
            examiner_identity(client.config.vision_model)
        )
        if not (examiner_golden_directory / "manifest.json").exists():
            licence_problems.append(
                f"no golden reference at {examiner_golden_directory}: run "
                f"`make pin-golden-views REVISION={arguments.revision}`"
            )
        if licence_problems:
            raise SystemExit(
                "--examiner auto but this examiner may not judge:\n  - "
                + "\n  - ".join(licence_problems)
            )

    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(f"Model unreachable, refusing to score a run: {status.detail}")

    system_prompt = build_system_prompt(revision=revision.revision)
    session = AgentSession(
        client=client,
        output_directory=render_directory / "agent",
        maximum_tool_calls_per_turn=arguments.max_tool_calls,
        messages=[{"role": "system", "content": system_prompt}],
        disabled_tools=frozenset({"run_python"}) if arguments.no_hatch else frozenset(),
    )

    tool_calls: list[str] = []
    tool_events: list[dict] = []
    transcript: list[str] = []

    def on_event(kind: str, text: str) -> None:
        transcript.append(f"--- {kind} ---\n{text}")
        if kind == "tool":
            tool_calls.append(text)
        if kind == TOOL_EVENT_KIND:
            tool_events.append(json.loads(text))
            return  # the machine's copy of the tool/result pair just printed
        preview = text if len(text) <= 400 else text[:400] + " ..."
        print(f"[{kind}] {preview}", flush=True)

    started_at = _datetime.datetime.now(_datetime.UTC).isoformat()
    print(f"[brief] {brief.prompt_text}", flush=True)
    final_text = session.send(brief.prompt_text, on_event=on_event)

    # --- EXAMINE (a): deterministic gates, both, before any render ----
    # The structural gate runs per part: each part's object is analyzed
    # against the brief-level budget, and failures are prefixed with the
    # part name so a multi-part build names the part that failed.
    bpy.context.view_layer.update()
    built_objects: list = []
    structural_failures: list[str] = []
    for part in brief.parts:
        part_object = bpy.data.objects.get(part.name)
        if part_object is None:
            structural_failures.append(
                f"{part.name}: no object named {part.name!r} — nothing to analyze"
            )
            continue
        part_report = analyze_object(part_object)
        structural_failures.extend(
            f"{part.name}: {failure}" for failure in part_report.failures(brief.budget)
        )
        built_objects.append(part_object)
    structural_passed = not structural_failures
    structural_failures = tuple(structural_failures)

    form_report = evaluate_brief(brief)
    form_failures = tuple(form_report.failures(brief))

    # --- RENDER: on failure too. A failure you cannot review is one
    # you will repeat.
    render_path = ""
    glb_path = ""
    built_objects_in_scene = [
        built_object
        for built_object in built_objects
        if built_object.name in bpy.context.scene.objects
    ]
    if built_objects_in_scene:
        sheet = capture_contact_sheet(
            built_objects_in_scene[0],
            render_directory,
            settings=CaptureSettings(),
            extra_objects=tuple(built_objects_in_scene[1:]),
        )
        render_path = str(sheet)
        # AFTER both gates: export_glb re-imports to verify the file, and
        # a temporary re-import in the scene would read as a stray object.
        # One .glb per part, named for the part: the round-trip
        # verification analyzes a single object, and keeping that
        # contract per part preserves it. The first part's path is the
        # record's glb_path, matching the pre-assembly convention.
        exported: list[str] = []
        for built_object in built_objects_in_scene:
            destination = render_directory / f"{built_object.name}.glb"
            export_report = export_glb(
                built_object, destination, blend_path=destination.with_suffix(".blend")
            )
            exported.append(destination.name)
            print(
                f"[export] {destination} ({export_report.file_size_bytes} "
                f"bytes), round trip "
                f"{'OK' if export_report.passes(brief.budget) else 'FAILED'}",
                flush=True,
            )
            for failure in export_report.round_trip_failures(brief.budget):
                print(f"   - {failure}", flush=True)
        glb_path = str(render_directory / exported[0])

    # --- VISUAL GATE: deterministic pixel check against the pinned
    # golden. A different instrument from the examiner: it cannot judge
    # brief-conformance, only whether the render moved. Runs whenever a
    # pinned golden exists at the active revision AND the calibration
    # file exists; absent calibration prints one line and skips, so
    # this port never blocks the pending eye calibration. Failures join
    # the driver's own failure list and exit non-zero. The gate never
    # writes an IterationVerdict; verdict authorship stays with the
    # human or a licensed examiner.
    visual_gate_failures: list[str] = []
    if built_objects_in_scene:
        try:
            from blended.evaluate.visual_diff import (
                CALIBRATION_PATH,
                compare_view_files,
                gate_failures,
                load_thresholds,
            )

            thresholds = load_thresholds(CALIBRATION_PATH)
            comparisons = []
            for view_name in (
                "front",
                "right",
                "top",
                "bottom",
                "three_quarter",
            ):
                golden_view = golden_directory / f"{view_name}.png"
                candidate_view = render_directory / f"{view_name}.png"
                if not golden_view.exists() or not candidate_view.exists():
                    continue
                comparisons.append(
                    compare_view_files(view_name, golden_view, candidate_view)
                )
            if comparisons:
                print(
                    "\n[visual gate] "
                    + "  ".join(
                        f"{comparison.view_name} "
                        f"iou {comparison.silhouette_iou:.4f} "
                        f"rmse {comparison.shading_rmse:.4f}"
                        for comparison in comparisons
                    ),
                    flush=True,
                )
                visual_gate_failures.extend(gate_failures(comparisons, thresholds))
        except VisualGateNotCalibrated:
            print(
                "[visual gate] uncalibrated — "
                "run `make calibrate-visual-gate REVISION=10`; skipping",
                flush=True,
            )

    # --- EXAMINE (b): the VISUAL pass, by a calibrated instrument.
    # Only when both deterministic gates passed: a visual critique of a
    # scene that already failed a measurement is wasted tokens (Voyager's
    # ordering, 10.48550/arXiv.2305.16291), and an unexamined run is not
    # a pass with no deviations — `IterationRecord.passed` already
    # encodes that. The exit code below stays a function of the
    # deterministic gates only; the examiner's output lives in the
    # verdict log, where the convergence rule reads it.
    if (
        arguments.examiner == "auto"
        and structural_passed
        and not form_failures
        and built_objects_in_scene
    ):
        from blended.evaluate.examiner import (
            calibration_file_identity,
            examine_asset,
        )
        from blended.evaluate.iteration_log import IterationVerdict, VerdictLog

        # The licence was established before the run; here the examiner
        # only examines.
        verdict = examine_asset(
            VisionDescriber(client, client.config.vision_model),
            examiner_golden_directory,
            render_directory,
            brief,
            client.config.vision_model,
        )
        print(verdict.summary(), flush=True)
        VerdictLog(Path(arguments.verdicts)).append(
            IterationVerdict(
                iteration=arguments.iteration,
                brief_name=brief.name,
                visual_inspected=True,
                visual_deviations=verdict.deviations,
                examiner=verdict.examiner_identity,
                abstained=verdict.abstained,
                calibration_identity=calibration_file_identity(),
                view_tags=tuple(
                    (view.view_name, tuple(view.order_consistent_tags))
                    for view in verdict.views
                ),
            )
        )

    # --- USER-GUIDED REFINEMENT: a second turn, gated exactly like the
    # first. The standard requires follow-up instructions to be applied
    # as LOCALIZED edits that preserve the rest of the asset, so the
    # measurement is not "does it still satisfy the brief" (a rebuild
    # does too) but "did anything the user did not name move".
    refinement_summaries: list[str] = []
    refinement_failures: list[str] = []
    refinement_locality: list[str] = []
    refinement_passed = True
    if brief.refinements and not form_failures and structural_passed:
        # Stamp AFTER the export, so the shipped .glb never carries it,
        # and BEFORE the first follow-up, so the stamp predates any edit
        # it is meant to survive. The primitives are idempotent by name,
        # so a rebuild under the same name destroys the datablock and
        # takes the stamp with it — which is the whole measurement.
        # One identity for the whole build: parts are rebuilt together
        # or edited together.
        stamped_identity = new_identity()
        for built_object in built_objects_in_scene:
            stamp_identity(built_object, stamped_identity)
        step_brief = brief
        for step in brief.refinements:
            print(f"\n[refine] {step.instruction_text}", flush=True)
            before_report = form_report
            session.send(step.instruction_text, on_event=on_event)
            bpy.context.view_layer.update()
            # Each step is scored against the brief refined by its
            # predecessors — a multi-step sequence is cumulative. Scoring
            # every step against the ORIGINAL brief is how a run that
            # correctly widened the seat then failed for still having a
            # 0.40 m seat (measured at iteration 23).
            step_brief = refine_brief(step_brief, step)
            after_report = evaluate_brief(step_brief)
            outcome = RefinementOutcome(
                step=step, before=before_report, after=after_report
            )
            step_failures = outcome.failures(brief)
            refinement_failures.extend(step_failures)
            refinement_summaries.append(outcome.summary(brief))
            refinement_passed = refinement_passed and not step_failures
            print(outcome.summary(brief), flush=True)
            refined_objects_in_scene = [
                bpy.data.objects[part.name]
                for part in brief.parts
                if part.name in bpy.data.objects
                and part.name in bpy.context.scene.objects
            ]
            for refined_object in refined_objects_in_scene:
                locality = measure_locality(refined_object, step.name, stamped_identity)
                refinement_locality.append(locality.summary())
                print(locality.summary(), flush=True)
            if refined_objects_in_scene:
                capture_contact_sheet(
                    refined_objects_in_scene[0],
                    render_directory / f"refined_{step.name}",
                    settings=CaptureSettings(),
                    extra_objects=tuple(refined_objects_in_scene[1:]),
                )
            form_report = after_report
    elif brief.refinements:
        # Refining an asset that already failed measures nothing.
        refinement_summaries.append(
            "REFINEMENT SKIPPED: the first build did not pass both gates"
        )
        refinement_passed = False

    record = IterationRecord(
        iteration=arguments.iteration,
        brief_name=brief.name,
        prompt_identity=revision.identity,
        prompt_revision=revision.revision,
        assembled_prompt_fingerprint=assembled_prompt_fingerprint(revision.revision),
        tool_schemas_fingerprint=TOOL_SCHEMAS_FINGERPRINT,
        offered_tools_fingerprint=session.offered_tools_fingerprint(),
        started_at=started_at,
        writer_model=client.config.model,
        vision_model=client.config.vision_model,
        agent_turns=len([m for m in session.messages if m.get("role") == "assistant"]),
        tool_calls=tuple(tool_calls),
        tool_events=tuple(tool_events),
        agent_final_text=final_text,
        structural_gate_passed=structural_passed,
        structural_failures=structural_failures,
        form_gate_passed=not form_failures,
        form_failures=form_failures,
        form_summary=form_report.summary(brief),
        render_path=render_path,
        glb_path=glb_path,
        refinement_gate_passed=refinement_passed,
        refinement_failures=tuple(refinement_failures),
        refinement_summary="\n".join(refinement_summaries),
        refinement_locality=tuple(refinement_locality),
        # Writer AND eye: VisionDescriber folds its own client's usage
        # back into this one, so a row covers everything the iteration
        # spent. See docs/2026-09-06-token-budget-audit.md.
        api_calls=client.spent.api_calls,
        input_tokens=client.spent.input_tokens,
        cache_read_tokens=client.spent.cache_read_tokens,
        cache_write_tokens=client.spent.cache_write_tokens,
        output_tokens=client.spent.output_tokens,
        reasoning_tokens=client.spent.reasoning_tokens,
        cost_usd=client.spent.cost_usd,
    )
    IterationLog(Path(arguments.log)).append(record)

    (render_directory / "transcript.txt").write_text(
        "\n\n".join(transcript), encoding="utf-8"
    )
    (render_directory / "system_prompt.txt").write_text(system_prompt, encoding="utf-8")

    print("\n================ ITERATION RESULT ================", flush=True)
    print(f"brief      : {brief.name}", flush=True)
    print(f"prompt     : {revision.identity}", flush=True)
    print(
        f"models     : writer {client.config.model} / eye {client.config.vision_model}",
        flush=True,
    )
    print(f"tool calls : {len(tool_calls)}", flush=True)
    print(f"spent      : {client.spent.summary()}", flush=True)
    print(
        f"STRUCTURAL : {'PASS' if structural_passed else 'FAIL'}",
        flush=True,
    )
    for failure in structural_failures:
        print(f"   - {failure}", flush=True)
    print(form_report.summary(brief), flush=True)
    print(f"render     : {render_path or '(none — nothing to render)'}", flush=True)
    print(f"glb        : {glb_path or '(none)'}", flush=True)
    for summary in refinement_summaries:
        print(summary, flush=True)
    # Evidence, printed beside the gates but never folded into them:
    # the exit code below does not consult it.
    for summary in refinement_locality:
        print(summary, flush=True)
    for failure in visual_gate_failures:
        print(f"VISUAL GATE: {failure}", flush=True)
    print("=================================================", flush=True)
    return (
        0
        if (
            structural_passed
            and not form_failures
            and refinement_passed
            and not visual_gate_failures
        )
        else 1
    )


extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
# Blender exits 0 on an uncaught Python exception, so a run that
# died would read as a success (OT-32).
from blended.run.script_exit import run_script_main

raise SystemExit(run_script_main(main, extra_arguments))
