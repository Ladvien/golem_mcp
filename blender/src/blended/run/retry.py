"""The retry loop: execution feedback with drift fixes attached.

3DCodeBench's central result: a stateless retry loop that feeds the
previous script and its traceback back to the generator, capped at TWO
retries, lifted executability 0.702 -> 0.974 (+27.2 pp). Most fixes are
localized API corrections that are "well within model competence once
the traceback is visible." This module is that loop.

The harness does not call a model. The `fix_source` callback is the
seam: in production it is the agent rewriting the source given
`build_retry_prompt(...)`; in tests it is a deterministic function.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from blended.run.executor import RunResult

# 3DCodeBench's measured sweet spot. More retries buys executability
# slowly and geometry not at all; escalate to a human instead.
MAXIMUM_RETRIES_DEFAULT = 2

FixSourceCallback = Callable[[str, RunResult], str]


@dataclass(frozen=True)
class Attempt:
    """One execution attempt: exactly what ran, and what happened."""

    attempt_index: int
    source_code: str
    result: RunResult


@dataclass(frozen=True)
class RetryOutcome:
    ok: bool
    attempts: tuple[Attempt, ...]

    @property
    def final_result(self) -> RunResult:
        return self.attempts[-1].result

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def build_retry_prompt(source_code: str, result: RunResult) -> str:
    """Format a failed attempt for whoever writes the next one.

    Contains the three things the evidence says matter: the exact source
    that ran, the full traceback, and any known-drift fixes so an API
    move is corrected on the first retry instead of rediscovered.
    """
    drift_section = ""
    if result.matched_drift:
        drift_lines = "\n".join(
            f"* {entry.symbol} (changed in {entry.changed_in}): {entry.fix}"
            for entry in result.matched_drift
        )
        drift_section = (
            f"\n--- known API drift matched in this traceback ---\n{drift_lines}\n"
        )
    return (
        "The previous attempt failed. Correct the source and return the "
        "complete corrected script.\n"
        "\n--- source that ran ---\n"
        f"{source_code}\n"
        "\n--- traceback ---\n"
        f"{result.traceback_text}"
        f"{drift_section}"
    )


def run_with_retries(
    initial_source: str,
    fix_source: FixSourceCallback,
    maximum_retries: int = MAXIMUM_RETRIES_DEFAULT,
    script_name: str = "<agent>",
    session_log=None,
) -> RetryOutcome:
    """Run source in-process; on failure, ask `fix_source` and retry.

    Stateless per attempt (no accumulated conversation) — the cheap
    variant that captured most of the measured win.
    """
    from blended.run.executor import run_source_in_process

    if maximum_retries < 0:
        raise ValueError(
            f"maximum_retries must be >= 0, got {maximum_retries}: with no "
            f"attempt there is no result to return"
        )
    attempts: list[Attempt] = []
    current_source = initial_source
    for attempt_index in range(maximum_retries + 1):
        result = run_source_in_process(current_source, script_name=script_name)
        attempts.append(
            Attempt(
                attempt_index=attempt_index,
                source_code=current_source,
                result=result,
            )
        )
        if session_log is not None:
            session_log.record_attempt(
                chunk_label=script_name,
                source_code=current_source,
                result=result,
                attempt_index=attempt_index,
            )
        if result.ok:
            return RetryOutcome(ok=True, attempts=tuple(attempts))
        if attempt_index < maximum_retries:
            current_source = fix_source(current_source, result)
    return RetryOutcome(ok=False, attempts=tuple(attempts))
