"""Script execution with structured traceback capture.

The execution-feedback loop is the single biggest measured lever in
agentic 3D modeling (3DCodeBench: visible tracebacks + <=2 retries took
executability 0.702 -> 0.974). This module's job is to make the
environment tell the truth loudly: every run returns a RunResult with
the full traceback, and failed runs are matched against the drift
catalog so known API moves are surfaced with their fix attached.

Execution is in-process, against the current bpy: a bpy wheel, or code
already inside Blender.
"""

from __future__ import annotations

import contextlib
import io
import time
import traceback as traceback_module
from collections.abc import Callable
from dataclasses import dataclass, field

from blended.drift.catalog import DriftEntry, match_traceback

# How much of a chunk's stdout comes back to the agent. Bounded, because
# SWE-agent measured a too-LARGE observation window costing more than a
# too-small one (-5.3pp vs -3.7pp). The tail is kept rather than the
# head: a script that prints in a loop puts its conclusion last.
MAXIMUM_STDOUT_CHARACTERS = 2000


@dataclass(frozen=True)
class RunResult:
    ok: bool
    duration_s: float
    blender_version: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback_text: str = ""
    stdout_text: str = ""
    matched_drift: tuple[DriftEntry, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        printed = f"\n  printed:\n{self.stdout_text}" if self.stdout_text else ""
        if self.ok:
            return (
                f"ok in {self.duration_s:.2f}s "
                f"(Blender {self.blender_version}){printed}"
            )
        drift_notes = "".join(
            f"\n  drift[{entry.symbol}]: {entry.fix}" for entry in self.matched_drift
        )
        return (
            f"FAILED in {self.duration_s:.2f}s: {self.error_type}: "
            f"{self.error_message}{printed}{drift_notes}"
        )


def _bounded_stdout(captured_text: str) -> str:
    """Trim captured stdout to the observation window, keeping the tail."""
    trimmed = captured_text.rstrip()
    if len(trimmed) <= MAXIMUM_STDOUT_CHARACTERS:
        return trimmed
    dropped = len(trimmed) - MAXIMUM_STDOUT_CHARACTERS
    return (
        f"[{dropped} earlier characters dropped]\n"
        + trimmed[-MAXIMUM_STDOUT_CHARACTERS:]
    )


def execute_captured(
    thunk: Callable[[], object], name: str, blender_version: str
) -> tuple[RunResult, object]:
    """Run `thunk` with stdout captured and failure reported, never raised.

    The ONE capture path: a Python chunk (`run_source_in_process`) and a
    facade op called as a tool (`agent.op_call`) both come through here,
    so a traceback is bounded, drift-matched and summarised the same way
    whichever door the model used. Returns the result and what the thunk
    returned (None on failure).
    """
    started_at = time.perf_counter()
    # print() is the agent's only way to ask the scene a question. Without
    # this capture the answer goes to Blender's console, invisible to the
    # model — measured 2026-08-22: an agent with no observation channel
    # started raising RuntimeError to smuggle values back through the
    # traceback, one wasted tool call per value.
    stdout_buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buffer):
            returned = thunk()
    # SystemExit is not an Exception: a chunk that ends with `sys.exit()` or
    # `exit()` would otherwise unwind through the caller and quit the host
    # Blender instead of coming back as a failed result.
    except (Exception, SystemExit) as error:  # noqa: BLE001 - we report, not swallow
        traceback_text = traceback_module.format_exc()
        return (
            RunResult(
                ok=False,
                duration_s=time.perf_counter() - started_at,
                blender_version=blender_version,
                error_type=type(error).__name__,
                error_message=str(error),
                traceback_text=traceback_text,
                stdout_text=_bounded_stdout(stdout_buffer.getvalue()),
                matched_drift=tuple(match_traceback(traceback_text)),
            ),
            None,
        )
    return (
        RunResult(
            ok=True,
            duration_s=time.perf_counter() - started_at,
            blender_version=blender_version,
            stdout_text=_bounded_stdout(stdout_buffer.getvalue()),
        ),
        returned,
    )


def run_source_in_process(source_code: str, script_name: str = "<agent>") -> RunResult:
    """Execute Python source against the current bpy, capturing failure."""
    import bpy

    execution_namespace: dict = {"__name__": "__main__"}

    def execute_source() -> None:
        compiled = compile(source_code, script_name, "exec")
        exec(compiled, execution_namespace)  # noqa: S102 - the harness's job

    result, _ = execute_captured(execute_source, script_name, bpy.app.version_string)
    return result
