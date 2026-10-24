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

    python3 scripts/audit_task_child_models.py            # newest golem_mcp session dir
    python3 scripts/audit_task_child_models.py --dir <session dir> --agent loop-a1...
    python3 scripts/audit_task_child_models.py --json

Exit status is 0 only when every agent's every work turn matches the required
provider and model, and no session recorded a fallback resolution. Anything else
is exit 1, so this can gate a release.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

REQUIRED_PROVIDER = "ollama-cloud"
REQUIRED_MODEL = "deepseek-v4.1-flash:1017"

DEFAULT_SESSION_ROOT = pathlib.Path.home() / ".omp" / "agent" / "sessions" / "-golem_mcp"


def newest_session_dir(root: pathlib.Path) -> pathlib.Path:
    """The most recently touched session directory under `root`."""
    candidates = [path for path in root.iterdir() if path.is_dir()]
    if not candidates:
        raise SystemExit(f"no session directories under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


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


def report(transcripts: dict[str, pathlib.Path], as_json: bool) -> int:
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
        if off_pin:
            failures.append(f"{name}: {off_pin} work turn(s) off the required pin")
        if session_wrong or not result["session_resolutions"]:
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

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dir",
        type=pathlib.Path,
        default=None,
        help="the session directory holding the child transcripts (default: newest under ~/.omp/agent/sessions/-golem_mcp)",
    )
    parser.add_argument(
        "--agent",
        action="append",
        default=None,
        dest="agents",
        help="a child transcript name, without .jsonl; repeatable (default: every loop-aN.jsonl found)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    arguments = parser.parse_args(argv)

    session_dir = arguments.dir or newest_session_dir(DEFAULT_SESSION_ROOT)
    if arguments.agents:
        transcripts = {
            name: session_dir / f"{name}.jsonl" for name in arguments.agents
        }
    else:
        transcripts = {
            path.stem: path for path in sorted(session_dir.glob("loop-a*.jsonl"))
        }

    missing = [name for name, path in transcripts.items() if not path.is_file()]
    if missing:
        raise SystemExit(f"no transcript for {missing} under {session_dir}")
    if not transcripts:
        raise SystemExit(f"no loop-aN.jsonl transcripts under {session_dir}")

    return report(transcripts, arguments.as_json)


if __name__ == "__main__":
    sys.exit(main())
