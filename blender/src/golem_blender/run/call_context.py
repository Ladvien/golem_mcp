"""The OUTSIDE of one tool call: its progress file, its safety copy, its budget.

Measured need, 2026-10-24, in a live session: `export_assembly` on a 77-part
bakery outlived the client's 300 s socket timeout. The MCP bridge then reported
the call as `PAUSED` — "no Blender" — while Blender was still measuring, so the
agent read a finished session as a dead one, and the 77 parts an hour of work
had built existed only in memory until the session was closed. Three things
were missing, and none of them belongs to the op that needed them:

- PROGRESS. A long op can say where it is, and the bridge can turn that into
  MCP progress notifications, so a client that would otherwise time out keeps
  waiting. The channel is a FILE, not a shared object: the op runs in Blender's
  main thread inside the add-on's exec, the bridge runs in another process, and
  they already share exactly one thing — the call's output directory.
- A SAFETY COPY. The scene can be saved before the expensive part starts, so a
  crash or a wedged socket costs the work done inside the call, not the session.
- A BUDGET. A wall-clock deadline lets a long op return what it measured with
  `truncated: true` instead of running until something else gives up.

WHY THIS MODULE IMPORTS NO bpy AT MODULE LEVEL: the MCP bridge imports
`PROGRESS_FILE_NAME` from here, in a process that has no bpy at all. Everything
that needs Blender imports it inside the function that uses it.

The progress write is ATOMIC (write a temporary file, then `os.replace`), so a
reader never sees half a JSON document — and the reader here is a heartbeat
polling several times a second, which is the one reader guaranteed to catch a
partial write if it were possible.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

__all__ = (
    "PROGRESS_FILE_NAME",
    "PROGRESS_MINIMUM_INTERVAL_S",
    "SCRATCH_DIRECTORY_NAME",
    "SCRATCH_SAVE_MINIMUM_PARTS",
    "CallContext",
    "Deadline",
    "call_context",
    "current_context",
    "report_progress",
    "save_scratch_copy",
)

PROGRESS_FILE_NAME = "progress.json"
SCRATCH_DIRECTORY_NAME = "scratch"
# The throttle, in seconds. A pair loop over 45 candidates must not write 45
# files a second when the reader polls five times a second; the last write of a
# stage is always taken (`done == total`), so "finished 77 of 77" is never
# dropped for arriving too soon after "76 of 77".
PROGRESS_MINIMUM_INTERVAL_S = 0.5
# A full gate on this many parts saves the session first. The number is the
# measured cost of the alternative: the 77-part bakery's whole-assembly gate ran
# for minutes, and every part of it is scene reads that a saved copy gives back.
SCRATCH_SAVE_MINIMUM_PARTS = 20


class CallContext:
    """Where one tool call writes its progress and its safety copy."""

    def __init__(self, output_directory: Path, tool_name: str) -> None:
        self.output_directory = Path(output_directory)
        self.tool_name = tool_name

    @property
    def progress_path(self) -> Path:
        return self.output_directory / PROGRESS_FILE_NAME

    @property
    def scratch_path(self) -> Path:
        return (
            self.output_directory / SCRATCH_DIRECTORY_NAME / f"{self.tool_name}.blend"
        )


# The call in flight, or None outside one. Module-level for the same reason a
# session's assemblies are: there is exactly one Blender main thread, so there is
# exactly one call, and threading it through every op's signature would put a
# plumbing argument on forty tools that do not care.
_CURRENT: CallContext | None = None
# When the last progress write happened, and when the call in flight started,
# both by `time.monotonic`.
_LAST_PROGRESS_S = 0.0
_STARTED_S = 0.0


@contextmanager
def call_context(output_directory: Path, tool_name: str):
    """Make *tool_name*'s progress file and scratch directory current for one call."""
    global _CURRENT, _LAST_PROGRESS_S, _STARTED_S
    previous = _CURRENT
    previous_written_s = _LAST_PROGRESS_S
    _CURRENT = CallContext(output_directory, tool_name)
    # Reset, not inherited: a new call writes its first progress immediately
    # rather than waiting out the previous call's throttle window, and its
    # `elapsed_s` counts from its own start.
    _LAST_PROGRESS_S = 0.0
    _STARTED_S = time.monotonic()
    try:
        yield _CURRENT
    finally:
        _CURRENT = previous
        _LAST_PROGRESS_S = previous_written_s


def current_context() -> CallContext | None:
    """The call in flight, or None. Read by the bridge's scratch-path lookup."""
    return _CURRENT


def report_progress(stage: str, done: int, total: int) -> None:
    """Say where the call in flight has got to; a no-op outside a call.

    Throttled to `PROGRESS_MINIMUM_INTERVAL_S` so a tight loop costs nothing,
    and never throttled when `done == total`: the completion of a stage is the
    one message that must arrive.
    """
    global _LAST_PROGRESS_S
    if _CURRENT is None:
        return
    now_s = time.monotonic()
    finished = total > 0 and done >= total
    if not finished and now_s - _LAST_PROGRESS_S < PROGRESS_MINIMUM_INTERVAL_S:
        return
    _LAST_PROGRESS_S = now_s
    _write_progress(
        _CURRENT.progress_path,
        {
            "tool": _CURRENT.tool_name,
            "stage": stage,
            "part": int(done),
            "of": int(total),
            "elapsed_s": round(max(0.0, now_s - _STARTED_S), 1),
        },
    )


def _write_progress(path: Path, payload: dict) -> None:
    """Write one progress document atomically; a failure here never fails the call."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # A progress file is a courtesy to the bridge, not a measurement: an
        # unwritable output directory must not turn a working op into a failure.
        return


def save_scratch_copy(tool_name: str) -> tuple[str, str]:
    """Save the session as it stands to the call's scratch copy; never raise.

    Returns `(path, error)`: the written path, or `("", the reason)`. A safety
    copy that cannot be written is REPORTED and never fails the op — the op was
    asked for an asset, and a missing backup is not a reason to refuse one.

    `copy=True` saves a copy and leaves the session's own filepath alone, so a
    later `Ctrl-S` still lands where the user expects. One file per tool,
    overwritten each call, so the disk cost stays bounded no matter how many
    long calls a session makes.
    """
    import bpy

    destination = (
        _CURRENT.scratch_path
        if _CURRENT is not None
        else Path(bpy.app.tempdir) / "golem_scratch" / f"{tool_name}.blend"
    )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(
            filepath=str(destination), copy=True, compress=False
        )
    except (RuntimeError, OSError) as error:
        return "", str(error)
    return str(destination), ""


class Deadline:
    """A wall-clock budget for one call: `expired()` once `budget_s` has passed.

    A deadline, not a timeout: nothing is interrupted. Every check asks before
    it starts and stops asking once the answer is yes, so the work already done
    is returned rather than thrown away, and a check already running is allowed
    to finish instead of leaving a half-measured report.
    """

    def __init__(self, budget_s: float) -> None:
        self.budget_s = float(budget_s)
        self._started_s = time.monotonic()

    def elapsed_s(self) -> float:
        return time.monotonic() - self._started_s

    def expired(self) -> bool:
        return self.elapsed_s() >= self.budget_s

    def remaining_s(self) -> float:
        return max(0.0, self.budget_s - self.elapsed_s())
