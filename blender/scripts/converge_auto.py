"""The unattended convergence loop: RUN -> EXAMINE -> CLASSIFY -> ADJUST.

    .venv/bin/python scripts/converge_auto.py --revision 10
    .venv/bin/python scripts/converge_auto.py --propose-only --from-iteration 31

Host Python, not Blender: it spawns one `blender --background` per run,
because a fresh process per run is already the driver's isolation
contract.

The session ends in exactly one of two states:

* a PIN PROPOSAL (`_evaluate/pin_proposal.json`), exit 0 — a full suite
  cycle ran clean at one prompt identity, machine-examined, and the
  human's remaining act is `make pin REVISION=N`; or
* a HALT REPORT (`_evaluate/halt_report.md`), non-zero exit — naming the
  class of failure and the evidence.

WHY A PROMPT EDIT IS RARE. The classifier is deterministic and its
order is the discipline this harness was built on: a tool that raised is
`harness_code`, an examiner that saw something the gates did not is
`harness_critique` (the missing check must become a numeric probe, not a
reworded prompt), an oscillating failure signature is `bad_brief`, and
only a gate failure with every tool call executing cleanly is `prompt`.
Tool feedback outranks model feedback (10.48550/arXiv.2409.02977).

Exit codes: 0 pin proposal, 2 preflight refusal, 3 caps exceeded,
4 halt (a classified failure, or a run that wrote no record).
"""

import argparse
import datetime as _datetime
import json
import os
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)

BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
PIN_PROPOSAL_PATH = Path("_evaluate/pin_proposal.json")
HALT_REPORT_PATH = Path("_evaluate/halt_report.md")
GOLDEN_ROOT = Path("_evaluate/golden")
# An oscillation watchdog: the same failure signature this many times,
# across at least two prompt identities, means the SPEC is the problem,
# not the text. (The sealed-drain and rocking-stool entries in the
# mistake memory are both this shape.)
OSCILLATION_REPEAT_LIMIT = 3
OSCILLATION_IDENTITY_LIMIT = 2
DEFAULT_MAXIMUM_RUNS = 30


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--max-rounds", type=int, default=None)
    parser.add_argument("--max-runs", type=int, default=DEFAULT_MAXIMUM_RUNS)
    parser.add_argument("--model", default="")
    parser.add_argument("--vision-model", default="")
    parser.add_argument("--log", default="_evaluate/iterations.jsonl")
    parser.add_argument("--verdicts", default="_evaluate/verdicts.jsonl")
    parser.add_argument("--renders", default="_evaluate/renders")
    # The driver's own default, restated here so the pin proposal can
    # record the budget the runs actually had.
    parser.add_argument("--max-tool-calls", type=int, default=24)
    parser.add_argument(
        "--propose-only",
        action="store_true",
        help="run ONLY the ADJUST machinery against a recorded iteration: "
        "gate evidence, gradient, candidates, admissibility verdicts. "
        "No Blender is spawned and nothing is written.",
    )
    parser.add_argument("--from-iteration", type=int, default=0)
    return parser.parse_args(argv)


def _now() -> str:
    return _datetime.datetime.now(_datetime.UTC).isoformat()


def _client(model: str, vision_model: str):
    from blended.agent.loop import ModelConfig, OllamaClient

    overrides = {}
    if model:
        overrides["model"] = model
    if vision_model:
        overrides["vision_model"] = vision_model
    return OllamaClient(ModelConfig.from_environment(**overrides))


def preflight(arguments, brief_names) -> list[str]:
    """Everything that must be true before a single token is spent.

    Returns the problems; empty means the loop may run. There is
    deliberately no blind mode: a run nobody examined is not a pass, so
    an unlicensed examiner stops the session here rather than producing
    unattributable verdicts.
    """
    from blended.agent.prompt_versions import latest_revision, validate_revisions
    from blended.evaluate.examiner import (
        EXAMINED_VIEW_NAMES,
        ExaminerError,
        examiner_identity,
        load_calibration,
        verify_golden_manifest,
    )

    problems: list[str] = []

    registry_problems = validate_revisions()
    if registry_problems:
        problems.extend(f"registry: {problem}" for problem in registry_problems)

    latest = latest_revision().revision
    if arguments.revision != latest:
        problems.append(
            f"revision under test is v{arguments.revision} but the latest "
            f"registered revision is v{latest}: the search proposes from the "
            f"latest revision, so a candidate against an older one would "
            f"differ from its registry predecessor by many hunks"
        )

    client = _client(arguments.model, arguments.vision_model)
    writer_status = client.check_connection()
    if not writer_status.ok:
        problems.append(f"writer model unreachable: {writer_status.detail}")
    # ONE routing rule: the eye's server follows its own model id.
    eye_client = _client(arguments.model, arguments.vision_model)
    eye_client.config = eye_client.config.eye_config()
    eye_status = eye_client.check_connection()
    if not eye_status.ok:
        problems.append(f"vision model unreachable: {eye_status.detail}")

    # The golden reference is verified by the EXAMINER's own function,
    # not by a second copy of the hashing here: two checks that could
    # disagree is exactly the shape of bug this harness refuses.
    for brief_name in brief_names:
        directory = GOLDEN_ROOT / f"{brief_name}_v{arguments.revision}"
        missing_views = [
            directory / f"{view_name}.png"
            for view_name in EXAMINED_VIEW_NAMES
            if not (directory / f"{view_name}.png").exists()
        ]
        if missing_views:
            problems.append(
                f"golden reference incomplete for {brief_name}: missing "
                f"{[str(path) for path in missing_views]} (run "
                f"`make pin-golden-views REVISION={arguments.revision}`)"
            )
            continue
        try:
            verify_golden_manifest(directory, brief_name)
        except ExaminerError as error:
            problems.append(f"golden reference for {brief_name}: {error}")

    vision_model = _client(arguments.model, arguments.vision_model).config.vision_model
    identity = examiner_identity(vision_model)
    calibration_problems = load_calibration().problems(identity)
    problems.extend(f"examiner: {problem}" for problem in calibration_problems)
    return problems


def run_one_brief(arguments, brief_name: str, iteration: int) -> int:
    """Spawn the driver for one brief. Returns its exit code."""
    command = [
        BLENDER,
        "--background",
        "--factory-startup",
        "--python",
        "scripts/run_agent_task.py",
        "--",
        "--brief",
        brief_name,
        "--revision",
        str(arguments.revision),
        "--iteration",
        str(iteration),
        "--examiner",
        "auto",
        "--log",
        arguments.log,
        "--verdicts",
        arguments.verdicts,
        "--renders",
        arguments.renders,
        "--max-tool-calls",
        str(arguments.max_tool_calls),
    ]
    if arguments.model:
        command += ["--model", arguments.model]
    if arguments.vision_model:
        command += ["--vision-model", arguments.vision_model]
    print(f"\n[run] iteration {iteration} {brief_name}", flush=True)
    completed = subprocess.run(command, check=False)
    print(
        f"[run] iteration {iteration} {brief_name} exit {completed.returncode}",
        flush=True,
    )
    return completed.returncode


def _transcript_text(record) -> str:
    render_path = record.render_path
    if not render_path:
        return ""
    transcript = Path(render_path).parent / "transcript.txt"
    if not transcript.exists():
        return ""
    return transcript.read_text(encoding="utf-8", errors="replace")


def classify(record, verdict, history) -> tuple[str, str]:
    """(classification, why) for one failing run. Deterministic, ordered.

    First match wins, and the order is the discipline: only the class
    where a MEASUREMENT (not a model) says the agent got it wrong may
    edit the prompt.
    """
    from blended.evaluate.iteration_log import (
        CLASSIFICATION_BAD_BRIEF,
        CLASSIFICATION_HARNESS_CODE,
        CLASSIFICATION_HARNESS_CRITIQUE,
        CLASSIFICATION_PROMPT,
    )

    if "Tool raised" in _transcript_text(record):
        return (
            CLASSIFICATION_HARNESS_CODE,
            "a tool raised during the run: fix the op, not the prompt",
        )

    gates_passed = record.structural_gate_passed and record.form_gate_passed
    if verdict is not None and gates_passed and verdict.visual_deviations:
        return (
            CLASSIFICATION_HARNESS_CRITIQUE,
            (
                f"both gates passed and the examiner reported "
                f"{list(verdict.visual_deviations)}: the missing check must "
                f"become a numeric probe in briefs.py/acceptance.py — the "
                f"loop is not allowed to invent acceptance specs"
            ),
        )
    if verdict is not None and verdict.abstained:
        return (
            CLASSIFICATION_HARNESS_CRITIQUE,
            (
                "the examiner abstained: the instrument could not answer, so "
                "the artifact to fix is the examination, not the prompt"
            ),
        )

    signature = _signature(record)
    repeats = [other for other in history if _signature(other) == signature]
    identities = {other.prompt_identity for other in repeats}
    if (
        len(repeats) >= OSCILLATION_REPEAT_LIMIT
        and len(identities) >= OSCILLATION_IDENTITY_LIMIT
    ):
        return (
            CLASSIFICATION_BAD_BRIEF,
            (
                f"the same failure signature has now appeared in "
                f"{len(repeats)} iterations across {len(identities)} prompt "
                f"identities ({sorted(identities)}): the brief or its spec "
                f"is what is under-determined"
            ),
        )

    if not gates_passed:
        return (
            CLASSIFICATION_PROMPT,
            (
                "a deterministic gate failed and every tool call executed "
                "without raising: the measurement says the agent got it wrong"
            ),
        )
    return (
        "",
        (
            "the run failed but matched no class: refusing to guess. "
            f"structural={record.structural_gate_passed} "
            f"form={record.form_gate_passed} "
            f"refinement={record.refinement_gate_passed} "
            f"inspected={record.visual_inspected}"
        ),
    )


def _signature(record) -> tuple:
    return (
        record.brief_name,
        tuple(sorted(tuple(record.structural_failures) + tuple(record.form_failures))),
    )


def write_halt_report(
    classification: str,
    why: str,
    record,
    verdict,
    gradient: str,
    extra: str = "",
) -> None:
    lines = [
        "# Halt report",
        "",
        f"- written: {_now()}",
        f"- class: **{classification or '(unclassified)'}**",
        f"- why: {why}",
    ]
    if record is not None:
        lines += [
            f"- brief: `{record.brief_name}` (iteration {record.iteration})",
            f"- prompt identity: `{record.prompt_identity}`",
            f"- render directory: `{Path(record.render_path).parent if record.render_path else '(none)'}`",
            "",
            "## Measured failures",
            "",
        ]
        for failure in record.structural_failures:
            lines.append(f"- STRUCTURAL: {failure}")
        for failure in record.form_failures:
            lines.append(f"- FORM: {failure}")
        for failure in record.refinement_failures:
            lines.append(f"- REFINEMENT: {failure}")
    if verdict is not None:
        lines += [
            "",
            "## Examiner verdict",
            "",
            f"- examiner: `{verdict.examiner}`",
            f"- calibration: `{verdict.calibration_identity}`",
            f"- abstained: {verdict.abstained}",
            f"- deviations: {list(verdict.visual_deviations)}",
        ]
    if gradient:
        lines += ["", "## Last gradient", "", "```", gradient, "```"]
    if extra:
        lines += ["", "## Notes", "", extra]
    lines += [
        "",
        "## The one concrete next action",
        "",
        _next_action(classification),
        "",
    ]
    HALT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HALT_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[halt] wrote {HALT_REPORT_PATH}", flush=True)


def _next_action(classification: str) -> str:
    return {
        "harness_code": (
            "Read the transcript's `Tool raised` traceback, fix the op, and "
            "add the test that fails when it recurs. Do NOT touch the prompt."
        ),
        "harness_critique": (
            "Turn the deviation the examiner reported into a NUMERIC probe in "
            "`briefs.py` + `acceptance.py`, then re-run. The loop may not "
            "invent acceptance specs, and tuning the prompt to satisfy an "
            "instrument bakes the instrument's blindness in."
        ),
        "bad_brief": (
            "Pin the under-determined quantity in the brief's acceptance "
            "spec (the failure recurred across prompt identities, so the "
            "text is not what is wrong)."
        ),
        "prompt": (
            "Re-run `converge-auto`; the search exhausted its candidates or "
            "its caps. Inspect the last gradient before widening the search."
        ),
    }.get(
        classification,
        "Read the record above and classify it by hand: the loop refuses to "
        "guess a class it cannot derive from a measurement.",
    )


def write_pin_proposal(
    arguments,
    identity: str,
    cycle_runs,
    calibration_identity: str,
    examiner: str,
    tool_calls,
    records,
) -> None:
    """The machine's half of a pin: everything `make pin` needs.

    The models are the RESOLVED names the runs recorded, never the
    command-line overrides: a prompt is tuned against a model, and a
    pin that named an empty string would claim the runs happened
    nowhere. Applying it stays a human act — pinning mints the golden
    reference every later examination is compared against, and RESP
    measured a wrong reference is worse than none.
    """
    writer_models = {record.writer_model for record in records}
    vision_models = {record.vision_model for record in records}
    payload = {
        "revision": arguments.revision,
        "prompt_identity": identity,
        "runs": [[iteration, brief] for iteration, brief in cycle_runs],
        "examiner_identity": examiner,
        "calibration_identity": calibration_identity,
        "writer_model": min(writer_models) if len(writer_models) == 1 else "",
        "vision_model": min(vision_models) if len(vision_models) == 1 else "",
        "tool_call_budget": arguments.max_tool_calls,
        "tool_calls": tool_calls,
        "proposed_at": _now(),
    }
    PIN_PROPOSAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIN_PROPOSAL_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\n[pin] wrote {PIN_PROPOSAL_PATH}", flush=True)
    print(
        f"[pin] revision {arguments.revision} ({identity}) converged; "
        f"apply with: make pin REVISION={arguments.revision}",
        flush=True,
    )


def propose_only(arguments) -> int:
    """The ADJUST machinery, printed. No Blender, no writes."""
    from blended.agent import prompt_search
    from blended.agent.prompt_versions import latest_revision
    from blended.evaluate.iteration_log import IterationLog

    records = IterationLog(Path(arguments.log)).records()
    selected = [
        record for record in records if record.iteration == arguments.from_iteration
    ]
    if not selected:
        raise SystemExit(f"no iteration {arguments.from_iteration} in {arguments.log}")

    evidence = prompt_search.gate_evidence(selected)
    print("================ GATE EVIDENCE ================", flush=True)
    print(evidence or "(no measured failures in that iteration)", flush=True)
    if not evidence:
        return 0

    body = latest_revision().body
    client = _client(arguments.model, arguments.vision_model)
    # Same refusal the driver makes: an unreachable writer is reported by
    # name, not as a traceback out of urllib.
    status = client.check_connection()
    print(f"[connection] {status.summary()}", flush=True)
    if not status.ok:
        raise SystemExit(
            f"writer model unreachable, refusing to propose an edit: {status.detail}"
        )
    gradient = prompt_search.textual_gradient(client, body, evidence)
    print("\n================ GRADIENT ================", flush=True)
    print(gradient, flush=True)

    rejected = prompt_search.load_rejected_hunks()
    candidates = prompt_search.propose_bodies(
        client, body, gradient, prompt_search.CANDIDATES_PER_ROUND
    )
    print("\n================ CANDIDATES ================", flush=True)
    admissible_count = 0
    for index, candidate in enumerate(candidates, 1):
        reason = prompt_search.admissible(body, candidate, rejected)
        verdict = "ADMISSIBLE" if not reason else f"REFUSED: {reason}"
        admissible_count += 1 if not reason else 0
        print(
            f"\n--- candidate {index} ({len(candidate.splitlines())} lines) {verdict}",
            flush=True,
        )
    print(
        f"\n{admissible_count}/{len(candidates)} candidates admissible. "
        f"Nothing was written.",
        flush=True,
    )
    return 0


def main(argv=None) -> int:
    arguments = parse_arguments(argv)

    from blended.agent import prompt_search
    from blended.agent.prompt_versions import get_revision
    from blended.evaluate.briefs import BRIEFS
    from blended.evaluate.examiner import calibration_file_identity, examiner_identity
    from blended.evaluate.iteration_log import (
        CLASSIFICATION_PROMPT,
        IterationLog,
        VerdictLog,
        converged_suite_cycles,
        fold_verdict,
    )

    brief_names = tuple(sorted(BRIEFS))

    if arguments.propose_only:
        return propose_only(arguments)

    problems = preflight(arguments, brief_names)
    if problems:
        print("\n================ PREFLIGHT REFUSED ================", flush=True)
        for problem in problems:
            print(f"  - {problem}", flush=True)
        print(
            "\nNothing ran. There is deliberately no blind mode: a run "
            "nobody examined is not a pass.",
            flush=True,
        )
        return 2

    maximum_rounds = (
        arguments.max_rounds
        if arguments.max_rounds is not None
        else prompt_search.MAXIMUM_SEARCH_ROUNDS
    )
    log = IterationLog(Path(arguments.log))
    verdict_log = VerdictLog(Path(arguments.verdicts))
    runs_spent = 0
    gradient = ""

    for round_index in range(1, maximum_rounds + 1):
        print(
            f"\n================ ROUND {round_index}/{maximum_rounds} "
            f"(revision v{arguments.revision}) ================",
            flush=True,
        )
        for brief_name in brief_names:
            if runs_spent >= arguments.max_runs:
                write_halt_report(
                    "",
                    f"run cap reached ({arguments.max_runs} runs)",
                    None,
                    None,
                    gradient,
                )
                return 3
            iteration = log.next_iteration_number()
            exit_code = run_one_brief(arguments, brief_name, iteration)
            if record_for_run(log.records(), iteration, brief_name) is None:
                write_halt_report(
                    "",
                    f"iteration {iteration} {brief_name} wrote no record "
                    f"(driver exit {exit_code}): the run died before it was "
                    f"measured",
                    None,
                    None,
                    gradient,
                    extra=(
                        "Classifying an OLDER record of this brief as this run "
                        "would blame the prompt for a harness or provider "
                        "failure. Read the driver's output above (exit 70 is "
                        "an uncaught exception, 1 with no record is a "
                        "refusal), fix that, and re-run."
                    ),
                )
                return 4
            runs_spent += 1

        records = log.records()
        verdicts = verdict_log.verdicts()
        cycles, identity = converged_suite_cycles(records, brief_names, verdicts)
        under_test = get_revision(arguments.revision).identity
        print(
            f"\n[convergence] trailing clean suite cycles: {cycles} "
            f"({identity or 'no converged cycle'}); "
            f"revision under test is {under_test}",
            flush=True,
        )
        # The converged cycle must be the one that just ran THIS revision.
        # A cycle at some other identity is somebody else's evidence, and
        # a pin is a claim about the text that earned it.
        if cycles >= 1 and identity == under_test:
            newest = _newest_cycle(records, brief_names)
            write_pin_proposal(
                arguments,
                identity,
                [(record.iteration, record.brief_name) for record in newest],
                calibration_file_identity(),
                examiner_identity(
                    _client(arguments.model, arguments.vision_model).config.vision_model
                ),
                {record.brief_name: len(record.tool_calls) for record in newest},
                newest,
            )
            return 0

        # CLASSIFY every failing brief in the newest cycle.
        newest = _newest_cycle(records, brief_names)
        verdict_by_key = {
            (verdict.iteration, verdict.brief_name): verdict for verdict in verdicts
        }
        failing = []
        for record in newest:
            verdict = verdict_by_key.get((record.iteration, record.brief_name))
            folded = fold_verdict(record, verdict)
            if folded.passed:
                continue
            classification, why = classify(record, verdict, records)
            print(
                f"[classify] {record.brief_name} iteration {record.iteration}: "
                f"{classification or '(unclassified)'} — {why}",
                flush=True,
            )
            if classification != CLASSIFICATION_PROMPT:
                write_halt_report(classification, why, record, verdict, gradient)
                return 4
            failing.append((record, verdict, why))

        if not failing:
            write_halt_report(
                "",
                "no brief failed, yet the suite did not converge — the "
                "convergence rule and the per-run verdicts disagree",
                None,
                None,
                gradient,
            )
            return 4

        try:
            gradient, written_revision = adjust(
                arguments, [record for record, _, _ in failing]
            )
        except ScreeningRunWroteNoRecord as error:
            write_halt_report("", str(error), failing[0][0], failing[0][1], "")
            return 4
        if written_revision is None:
            write_halt_report(
                CLASSIFICATION_PROMPT,
                (
                    "every candidate was refused: no admissible one-hunk edit "
                    "survived screening"
                ),
                failing[0][0],
                failing[0][1],
                gradient,
            )
            return 4
        # The CONFIRMATION ROUND runs the whole suite at the revision the
        # search just wrote — screening proved it on one brief only, and a
        # prompt that fixes one brief by breaking another has not
        # converged.
        arguments.revision = written_revision
        print(
            f"\n[adjust] confirmation round will run the full suite at "
            f"v{written_revision}",
            flush=True,
        )

    write_halt_report(
        "",
        f"round cap reached ({maximum_rounds} rounds). ProTeGi measured the "
        f"peak at about 3 steps, so more rounds is not the lever — the "
        f"gradient above is.",
        None,
        None,
        gradient,
    )
    return 3


class ScreeningRunWroteNoRecord(RuntimeError):
    """A screening run died before it was measured. Distinct from a run
    that failed its gates: only a measured failure may blacklist a hunk."""


def record_for_run(records, iteration: int, brief_name: str):
    """The record the driver appended for exactly this run, or None."""
    return next(
        (
            record
            for record in records
            if record.iteration == iteration and record.brief_name == brief_name
        ),
        None,
    )


def _newest_cycle(records, brief_names):
    """The newest record per brief, newest iteration first."""
    newest: dict[str, object] = {}
    for record in sorted(records, key=lambda item: item.iteration, reverse=True):
        if record.brief_name in brief_names and record.brief_name not in newest:
            newest[record.brief_name] = record
    return [newest[name] for name in brief_names if name in newest]


def adjust(arguments, failing_records) -> tuple[str, int | None]:
    """ProTeGi EXPAND + SELECT.

    Returns (gradient, the revision written) — None when every candidate
    was refused, either by the admissibility filter, by the registry, or
    by the screening run.
    """
    from blended.agent import prompt_search
    from blended.agent.prompt_versions import latest_revision

    package_directory = REPOSITORY_ROOT / "src" / "blended" / "agent"
    body = latest_revision().body
    evidence = prompt_search.gate_evidence(failing_records)
    client = _client(arguments.model, arguments.vision_model)
    gradient = prompt_search.textual_gradient(client, body, evidence)
    print("\n================ GRADIENT ================", flush=True)
    print(gradient, flush=True)

    rejected = prompt_search.load_rejected_hunks()
    candidates = prompt_search.propose_bodies(
        client, body, gradient, prompt_search.CANDIDATES_PER_ROUND
    )
    screened: list[tuple[tuple, str]] = []
    for index, candidate in enumerate(candidates, 1):
        reason = prompt_search.admissible(body, candidate, rejected)
        if reason:
            print(f"[candidate {index}] REFUSED: {reason}", flush=True)
            continue
        screened.append(((index,), candidate))
        print(f"[candidate {index}] admissible", flush=True)

    if not screened:
        return gradient, None

    # ProTeGi's minibatch: screen on the FAILING brief only (cheap arm
    # pulls), ranked lexicographically by
    # (form failures, structural failures, tool calls).
    failing_brief = failing_records[0].brief_name
    from blended.evaluate.iteration_log import IterationLog

    log = IterationLog(Path(arguments.log))
    for (index,), candidate in screened:
        hunk = prompt_search.changed_hunks(body, candidate)[0]
        try:
            revision = prompt_search.write_revision(
                candidate,
                f"ProTeGi candidate {index}: {hunk}",
                f"Changed one region because the measured failures on "
                f"{failing_brief} indicate: {gradient.splitlines()[0] if gradient else 'see gradient'}",
                package_directory,
            )
        except prompt_search.RevisionRejected as error:
            print(f"[candidate {index}] rejected by the registry: {error}", flush=True)
            continue

        print(f"\n[screen] wrote v{revision}; screening on {failing_brief}", flush=True)
        screening_arguments = argparse.Namespace(**vars(arguments))
        screening_arguments.revision = revision
        iteration = log.next_iteration_number()
        run_one_brief(screening_arguments, failing_brief, iteration)
        screened_record = record_for_run(log.records(), iteration, failing_brief)
        if screened_record is None:
            # Not a measured failure: a crash must not blacklist a hunk.
            _roll_back(revision, package_directory)
            raise ScreeningRunWroteNoRecord(
                f"the screening run of v{revision} on {failing_brief} "
                f"(iteration {iteration}) wrote no record; the candidate was "
                f"rolled back and NOT recorded as rejected"
            )
        if not (
            screened_record.structural_gate_passed and screened_record.form_gate_passed
        ):
            failures = tuple(screened_record.form_failures) + tuple(
                screened_record.structural_failures
            )
            prompt_search.record_rejection(
                hunk,
                f"screening on {failing_brief} still failed: {list(failures)}",
                failing_brief,
            )
            _roll_back(revision, package_directory)
            print(
                f"[screen] v{revision} did not fix {failing_brief}; rolled back",
                flush=True,
            )
            continue

        print(f"[screen] v{revision} fixed {failing_brief}", flush=True)
        prompt_search.record_outcome(
            revision,
            f"Screening run on {failing_brief} passed both deterministic "
            f"gates at iteration {iteration}.",
            package_directory,
        )
        return gradient, revision

    return gradient, None


def _roll_back(revision: int, package_directory: Path) -> None:
    """Undo a candidate revision: its template AND its registry entry."""
    template = package_directory / "prompts" / f"working_agreement_v{revision}.md.j2"
    registry_path = package_directory / "prompt_versions.py"
    text = registry_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip() == f"revision={revision},"
        ),
        None,
    )
    if start is not None:
        entry_start = next(
            index
            for index in range(start, -1, -1)
            if lines[index].strip() == "PromptRevision("
        )
        entry_end = next(
            index
            for index in range(start, len(lines))
            if lines[index].rstrip("\n") == "    ),"
        )
        del lines[entry_start : entry_end + 1]
        registry_path.write_text("".join(lines), encoding="utf-8")
    if template.exists():
        template.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
