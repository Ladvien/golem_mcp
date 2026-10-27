"""`run_with_retries`: which GPU failures are retried, how long it waits, and what it says when it gives up.

The clock, the sleep and the RAM reading are fakes, so a half-hour memory wait runs in no time and the numbers asserted
are the ones the policy produced, not wall time.
"""

import pytest

from golem_mcp import gpu
from golem_mcp.job_retry import RetryPolicy, run_with_retries

POLICY = RetryPolicy(
    maximum_attempts=4,
    first_backoff_s=60.0,
    backoff_factor=2.0,
    required_mem_gib=16.0,
    memory_wait_limit_s=1800.0,
    poll_s=30.0,
)


class FakeClock:
    """Time that moves only when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def _memory(readings: list[float | None]):
    """A RAM reading that walks through `readings`, then repeats the last."""
    remaining = list(readings)

    def read() -> float | None:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return read


def _run(attempt, readings: list[float | None], clock: FakeClock, statuses: list[str]):
    return run_with_retries(
        attempt,
        POLICY,
        read_mem_available_gib=_memory(readings),
        sleep=clock.sleep,
        clock=clock.clock,
        on_status=statuses.append,
    )


def test_an_oom_then_a_success_waits_for_memory_and_retries_once() -> None:
    clock = FakeClock()
    statuses: list[str] = []
    seen_kinds: list[tuple[str, ...]] = []

    def attempt(n: int, kinds: tuple[str, ...]) -> str:
        seen_kinds.append(kinds)
        if n == 1:
            raise gpu.GpuJobError("OOM", kind=gpu.JOB_ERROR_OOM_KILLED)
        return "generated"

    result, log = _run(attempt, [2.0, 9.0, 17.5], clock, statuses)

    assert result == "generated"
    assert log == [{"attempt": 1, "kind": "oom_killed", "error": "OOM"}]
    # The backoff first, then two polls while big has 2.0 and 9.0 GiB, then 17.5 is enough.
    assert clock.sleeps == [60.0, 30.0, 30.0]
    assert statuses == [
        "attempt 2/4 after oom_killed: waiting for 16 GiB RAM, big has 2.0 GiB",
        "attempt 2/4 after oom_killed: waiting for 16 GiB RAM, big has 9.0 GiB",
    ]
    # The second attempt was told about the first one's OOM, so it can ask for fewer samples.
    assert seen_kinds == [(), ("oom_killed",)]


def test_a_refusal_is_not_retried() -> None:
    clock = FakeClock()
    calls: list[int] = []

    def attempt(n: int, kinds: tuple[str, ...]) -> str:
        calls.append(n)
        raise gpu.GpuJobError("held", kind=gpu.JOB_ERROR_REFUSED)

    with pytest.raises(gpu.GpuJobError, match="held") as raised:
        _run(attempt, [40.0], clock, [])

    assert calls == [1]
    assert clock.sleeps == []
    assert raised.value.retries == []


def test_memory_that_never_comes_back_is_reported_with_the_most_seen() -> None:
    clock = FakeClock()

    def attempt(n: int, kinds: tuple[str, ...]) -> str:
        raise gpu.GpuJobError("OOM", kind=gpu.JOB_ERROR_OOM_KILLED)

    with pytest.raises(gpu.GpuJobError) as raised:
        _run(attempt, [3.0, 7.5, 4.0], clock, [])

    message = str(raised.value)
    assert "needs ~16 GiB RAM" in message
    assert "at most 7.5 GiB" in message
    assert "for 1800 s" in message
    assert raised.value.kind == gpu.JOB_ERROR_OOM_KILLED
    assert raised.value.retries == [{"attempt": 1, "kind": "oom_killed", "error": "OOM"}]


def test_every_attempt_failing_reraises_the_last_with_the_whole_log() -> None:
    clock = FakeClock()

    def attempt(n: int, kinds: tuple[str, ...]) -> str:
        raise gpu.GpuJobError(f"queue {n}", kind=gpu.JOB_ERROR_QUEUE_TIMEOUT)

    with pytest.raises(gpu.GpuJobError, match="queue 4") as raised:
        _run(attempt, [40.0], clock, [])

    assert len(raised.value.retries) == 4
    assert [entry["attempt"] for entry in raised.value.retries] == [1, 2, 3, 4]
    # Exponential backoff between the four attempts, and none after the last.
    assert clock.sleeps == [60.0, 120.0, 240.0]


def test_an_error_that_is_not_a_gpu_failure_passes_straight_through() -> None:
    clock = FakeClock()

    def attempt(n: int, kinds: tuple[str, ...]) -> str:
        raise ValueError("bad prompt")

    with pytest.raises(ValueError, match="bad prompt"):
        _run(attempt, [40.0], clock, [])
    assert clock.sleeps == []
