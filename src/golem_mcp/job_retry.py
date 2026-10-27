"""Retry a GPU job that failed for a reason time can fix, and wait for the RAM it needs.

Why: Kimodo jobs were OOM-killed while another tenant held big's memory, and each one was abandoned — the caller got
one error, the job directory and its log were thrown away, and the agent had no way to tell "this prompt cannot work"
from "the box was busy for a minute". Three of gpu-tenant's failures are of the second kind:

  * `oom_killed`: the job hit the RAM cap. More free RAM, or fewer samples, changes the outcome.
  * `vram_refused`: a resident outside gpu-tenant held the card. It usually lets go.
  * `queue_timeout`: the lease queue was longer than 20 minutes. It drains.

`refused` (gpu-tenant would not queue us at all) and `wall_timeout` (the job ran past its own budget) are NOT
retried: the first needs an operator, and the second would only spend the same budget again.

Pure: imports only `gpu` (for its error type and kinds) and creates nothing on import. The clock, the sleep and the
memory reading are arguments, so a test runs a 30-minute wait in no time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from golem_mcp import gpu

T = TypeVar("T")

RETRYABLE_KINDS = frozenset({gpu.JOB_ERROR_OOM_KILLED, gpu.JOB_ERROR_VRAM_REFUSED, gpu.JOB_ERROR_QUEUE_TIMEOUT})


@dataclass(frozen=True)
class RetryPolicy:
    """How many times, how long between, and how much RAM a retry waits for."""

    maximum_attempts: int
    first_backoff_s: float
    backoff_factor: float
    required_mem_gib: float
    memory_wait_limit_s: float
    poll_s: float


def run_with_retries(
    attempt: Callable[[int, tuple[str, ...]], T],
    policy: RetryPolicy,
    *,
    read_mem_available_gib: Callable[[], float | None],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    on_status: Callable[[str], None],
) -> tuple[T, list[dict]]:
    """Call `attempt(n, previous_kinds)` until it returns, retrying only the failures time can fix.

    `n` counts from 1; `previous_kinds` are the error kinds of the attempts that failed before this one, in order, so
    an attempt can change course after an OOM (fewer samples). Between attempts the backoff is
    `first_backoff_s * backoff_factor ** (n - 1)`; after an `oom_killed`, the wait continues until big has
    `required_mem_gib` free, polling every `poll_s`, and gives up after `memory_wait_limit_s` with the most it ever
    saw. Returns the result and the log of failed attempts; on exhaustion re-raises the last error with that log
    attached as `.retries`.
    """
    if policy.maximum_attempts < 1:
        raise ValueError(f"maximum_attempts must be at least 1, got {policy.maximum_attempts}")
    log: list[dict] = []
    kinds: list[str] = []
    for n in range(1, policy.maximum_attempts + 1):
        try:
            return attempt(n, tuple(kinds)), log
        except gpu.GpuJobError as error:
            if error.kind not in RETRYABLE_KINDS:
                error.retries = log  # type: ignore[attr-defined]
                raise
            kinds.append(error.kind)
            log.append({"attempt": n, "kind": error.kind, "error": str(error)})
            if n == policy.maximum_attempts:
                error.retries = log  # type: ignore[attr-defined]
                raise
            sleep(policy.first_backoff_s * policy.backoff_factor ** (n - 1))
            if error.kind == gpu.JOB_ERROR_OOM_KILLED:
                _wait_for_memory(policy, n, error.kind, read_mem_available_gib, sleep, clock, on_status, log)
    raise AssertionError("unreachable: the last attempt either returns or raises")


def _wait_for_memory(
    policy: RetryPolicy,
    n: int,
    kind: str,
    read_mem_available_gib: Callable[[], float | None],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    on_status: Callable[[str], None],
    log: list[dict],
) -> None:
    """Block until big has `required_mem_gib` free, or raise with the most it ever had."""
    started = clock()
    seen = 0.0
    while True:
        memory = read_mem_available_gib()
        if memory is not None:
            seen = max(seen, memory)
            if memory >= policy.required_mem_gib:
                return
        shown = f"{memory:.1f}" if memory is not None else "?"
        on_status(
            f"attempt {n + 1}/{policy.maximum_attempts} after {kind}: waiting for {policy.required_mem_gib:.0f} GiB "
            f"RAM, big has {shown} GiB"
        )
        if clock() - started >= policy.memory_wait_limit_s:
            error = gpu.GpuJobError(
                f"animate_mesh needs ~{policy.required_mem_gib:.0f} GiB RAM; big had at most {seen:.1f} GiB "
                f"available for {policy.memory_wait_limit_s:.0f} s",
                kind=gpu.JOB_ERROR_OOM_KILLED,
            )
            error.retries = log  # type: ignore[attr-defined]
            raise error
        sleep(policy.poll_s)
