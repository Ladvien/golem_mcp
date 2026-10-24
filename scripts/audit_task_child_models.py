#!/usr/bin/env python3
"""Audit which provider and model a task child's WORK turns actually ran on.

Why this exists: the build-loop fan-out's whole output is a set of reports the
children write about their own work, and a child that ran on the wrong model
would still write a confident report. The pin is enforced by a test
(`tests/test_loop_worker_model_pin.py`); this script is how you CHECK what
already ran, after the fact, from the session transcripts.

Which field to read — this is the trap the script exists to close:

- ``type: message`` with ``message.role == "assistant"`` is ONE REAL WORK TURN.
  It carries its own ``provider``, ``model``, ``api``, ``usage`` and
  ``credentialId``. This is the record that answers "what did this agent
  actually run on", and it is the record to count.
- ``type: model_usage`` is a BILLED CALL TOO, but it appears only a handful of
  times per session (``purpose: task-completion-probe`` in the measured runs) —
  counting these instead of the work turns badly under-samples the session and
  looks like a complete audit when it is 3 records out of 142.
- ``type: model_change`` is the session's RESOLUTION: it names the model chosen
  for the session and carries ``resolvedModelIsFallback``, the only field that
  reveals a retry that silently switched models.
- a ``purpose: auto-thinking`` usage record is the HARNESS'S OWN classifier (e.g.
  ``typesafe/jev-1.14``); it is not an agent work model and must not be counted
  as one.

Usage, from the repository root::

    python3 scripts/audit_task_child_models.py            # EVERY child in the newest session dir
    python3 scripts/audit_task_child_models.py --allow-off-pin probe-model
    python3 scripts/audit_task_child_models.py --dir <session dir> --agent loop-a1...
    python3 scripts/audit_task_child_models.py --json

The default sweep covers EVERY child transcript in the session directory, not a
name pattern. Measured 2026-10-26: an earlier default that matched only
``loop-a*.jsonl`` reported PASS having read 6 of the directory's 17 children, so
the concurrency and probe children were outside the audit while it printed PASS.

Exit status is 0 only when every agent's every work turn matches the required
provider and model, and no session resolved or fell back to another one.
Anything else is exit 1, so this can gate a release. ``--allow-off-pin AGENT``
exists for exactly one situation: a child spawned ON PURPOSE on another model to
prove which layer routes. It prints a NOTE naming what it excused, so an excused
child is never silently green.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

REQUIRED_PROVIDER = "ollama-cloud"
REQUIRED_MODEL = "deepseek-v4.1-flash:1017"

DEFAULT_SESSIONS_ROOT = pathlib.Path.home() / ".omp" / "agent" / "sessions"


def _child_transcripts(session_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    """Every child transcript in ONE session directory.

    A child is a `.jsonl` that is not the session's own dated parent file. Both
    a flat layout (`<session>/loop-a1.jsonl`) and a nested one
    (`<session>/<Date>_<id>/Child.jsonl`, used by other working directories) are
    accepted, because a child's `cwd` follows its worktree.
    """
    found: dict[str, pathlib.Path] = {}
    for path in sorted(session_dir.rglob("*.jsonl")):
        if path.stem.startswith("2026-"):
            continue
        found[path.stem] = path
    return found


def newest_session_dir(root: pathlib.Path) -> pathlib.Path:
    """The most recent session directory that ACTUALLY HOLDS CHILD TRANSCRIPTS.

    Not simply the newest session: measured 2026-10-26, the newest session under
    `~/.omp/agent/sessions` belonged to an unrelated working directory and had no
    children at all, so "newest" would report "nothing audited" for a run that
    spawned sixteen. The default therefore ranks sessions by the newest mtime
    among those WITH children, searching every working-directory folder:
    `-golem_mcp`, and also `--private-tmp--` and others, since a child running in
    a worktree can write to its own folder. Measured: 2718 child transcripts
    live outside the single `-golem_mcp` session this audit first read.
    """
    candidates = [
        session
        for folder in root.iterdir()
        if folder.is_dir()
        for session in folder.iterdir()
        if session.is_dir() and _child_transcripts(session)
    ]
    if not candidates:
        raise SystemExit(
            f"no session under {root} holds any child transcript, so nothing "
            f"could be audited. Pass --dir explicitly."
        )
    return max(candidates, key=lambda session: session.stat().st_mtime)


def audit_one(transcript: pathlib.Path) -> dict:
    """Every work turn, resolution and non-work call in one transcript."""
    work_turns = collections.Counter()
    resolutions = []
    session_resolutions = []
    non_work_calls = collections.Counter()
    for line in transcript.open(encoding="utf-8", errors="ignore"):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = record.get("type")
        if kind == "message":
            message = record.get("message") or {}
            if message.get("role") != "assistant":
                continue
            work_turns[(message.get("provider"), message.get("model"))] += 1
        elif kind == "model_change":
            resolutions.append(
                (record.get("model"), record.get("resolvedModelIsFallback"))
            )
        elif kind == "session_init":
            session_resolutions.append(record.get("resolvedModel"))
        elif kind == "model_usage":
            purpose = record.get("purpose") or "model"
            if purpose != "task-completion-probe":
                non_work_calls[(purpose, record.get("provider"), record.get("model"))] += 1
    return {
        "work_turns": work_turns,
        "resolutions": resolutions,
        "session_resolutions": session_resolutions,
        "non_work_calls": non_work_calls,
    }


def report(
    transcripts: dict[str, pathlib.Path],
    as_json: bool,
    allowed_off_pin: tuple[str, ...] = (),
) -> int:
    """Print the audit and return the process exit status."""
    required = (REQUIRED_PROVIDER, REQUIRED_MODEL)
    total_turns = 0
    total_off_pin = 0
    failures: list[str] = []
    payload: dict[str, dict] = {}

    for name, path in transcripts.items():
        result = audit_one(path)
        work_turns = result["work_turns"]
        turns = sum(work_turns.values())
        off_pin = sum(count for combo, count in work_turns.items() if combo != required)
        total_turns += turns
        total_off_pin += off_pin

        fallbacks = [
            model for model, is_fallback in result["resolutions"] if is_fallback
        ]
        unresolved = [model for model, _ in result["resolutions"] if model is None]
        session_wrong = [
            model
            for model in result["session_resolutions"]
            if model != f"{REQUIRED_PROVIDER}/{REQUIRED_MODEL}"
        ]
        excused = name in allowed_off_pin
        if off_pin and not excused:
            failures.append(f"{name}: {off_pin} work turn(s) off the required pin")
        if (session_wrong or not result["session_resolutions"]) and not excused:
            failures.append(
                f"{name}: session_init resolvedModel is {session_wrong or 'absent'}"
            )
        if fallbacks:
            failures.append(f"{name}: resolved through a fallback ({fallbacks})")
        if unresolved:
            failures.append(f"{name}: a model_change named no model")

        payload[name] = {
            "work_turns": turns,
            "off_pin": off_pin,
            "combinations": {f"{p} / {m}": c for (p, m), c in work_turns.items()},
            "resolutions": result["resolutions"],
            "session_resolutions": result["session_resolutions"],
            "off_pin_allowed": excused,
            "non_work_calls": {
                f"{purpose} / {p} / {m}": c
                for (purpose, p, m), c in result["non_work_calls"].items()
            },
        }

        if not as_json:
            print(f"--- {name}")
            print(f"    work turns: {turns}  off-pin: {off_pin}")
            for (provider, model), count in sorted(work_turns.items(), key=lambda x: -x[1]):
                marker = "OK " if (provider, model) == required else "!! "
                print(f"      {marker}{count:>4}x {provider} / {model}")
            for model, is_fallback in result["resolutions"]:
                print(f"    resolved: {model}  fallback={is_fallback}")
            for model in result["session_resolutions"]:
                print(f"    session_init: {model}")
            for (purpose, provider, model), count in result["non_work_calls"].items():
                print(f"    non-work ({purpose}): {count}x {provider} / {model}")

    if as_json:
        print(
            json.dumps(
                {
                    "required": f"{REQUIRED_PROVIDER}/{REQUIRED_MODEL}",
                    "agents": payload,
                    "total_work_turns": total_turns,
                    "total_off_pin": total_off_pin,
                    "failures": failures,
                },
                indent=2,
            )
        )
    else:
        print()
        print(f"required: {REQUIRED_PROVIDER}/{REQUIRED_MODEL}")
        print(f"TOTAL work turns: {total_turns} | off-pin: {total_off_pin}")
        if failures:
            for failure in failures:
                print(f"FAIL {failure}")
        else:
            print("PASS every work turn ran on the required provider and model")
        if allowed_off_pin:
            print(
                f"NOTE excused as a deliberate discriminator: "
                f"{', '.join(sorted(allowed_off_pin))}"
            )

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dir",
        type=pathlib.Path,
        default=None,
        help="the session directory holding the child transcripts (default: the newest session across EVERY working directory under ~/.omp/agent/sessions)",
    )
    parser.add_argument(
        "--agent",
        action="append",
        default=None,
        dest="agents",
        help="a child transcript name, without .jsonl; repeatable (default: EVERY child transcript in the session dir)",
    )
    parser.add_argument(
        "--allow-off-pin",
        action="append",
        default=[],
        dest="allowed_off_pin",
        metavar="AGENT",
        help=(
            "an agent whose off-pin turns are EXPECTED and must not fail the run; "
            "repeatable. Use it for a deliberate discriminator probe (e.g. one "
            "spawned on a retired model to prove which layer routes), never to "
            "excuse a worker that drifted"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)

    session_dir = arguments.dir or newest_session_dir(DEFAULT_SESSIONS_ROOT)
    if not session_dir.is_dir():
        raise SystemExit(
            f"no such session directory: {session_dir}. An audit that reads "
            f"nothing must not print PASS: point --dir at the directory holding "
            f"the child transcripts."
        )
    if arguments.agents:
        transcripts = {
            name: session_dir / f"{name}.jsonl" for name in arguments.agents
        }
    else:
        # EVERY child transcript, not a name pattern: a default sweep that
        # matched only `loop-a*` silently skipped the concurrency and probe
        # children (measured: 6 of 17 children covered), which is exactly the
        # blind spot an audit must not have.
        transcripts = _child_transcripts(session_dir)

    missing = [name for name, path in transcripts.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"no transcript for {missing} under {session_dir}")
    if not transcripts:
        raise SystemExit(
            f"no child transcripts under {session_dir}: nothing was audited, so "
            f"there is nothing to pass. Check the path, or pass --agent NAME."
        )

    return report(transcripts, arguments.as_json, tuple(arguments.allowed_off_pin))


if __name__ == "__main__":
    sys.exit(main())
