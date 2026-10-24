"""run_gpu_job turns what gpu-tenant, the VRAM gate and the RAM cap report into one error, against a fake gpu-tenant."""

import os
import shlex
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from golem_mcp import gpu

# How long the fake job would run if nothing stopped it. Its argument carries a
# per-run token (see `_job_token`), so a leftover process from an earlier run of
# this test can never be mistaken for this run's job — measured: a fixed argument
# matched an orphan left by a mutation probe and made a green run red.
JOB_WOULD_HAVE_RUN_S = 41.3
# The ceiling a terminated job must come back under. Anything at or above
# JOB_WOULD_HAVE_RUN_S means the op waited the job out instead of stopping it.
TERMINATED_WITHIN_S = 15


def fake_gpu_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    script = tmp_path / "gpu-tenant"
    script.write_text(f"#!/usr/bin/env bash\n{body}\n")
    script.chmod(0o755)
    monkeypatch.setattr(gpu, "GPU_TENANT", script)


def run_probe() -> subprocess.CompletedProcess[str]:
    return gpu.run_gpu_job(["true"], label="Probe", note="probe", need_bytes=16e9, timeout_s=30)


@pytest.mark.parametrize(
    ("stdout", "stderr", "code", "message"),
    [
        ("TIMEOUT after 20m; held by sanctuary-icons@big\n", "", 2, "Probe: GPU queue timed out"),
        ("REFUSED: held by sanctuary-icons@big (3d) until 12:00\n", "", 1, "gpu-tenant refused: REFUSED: held by"),
        ("", "VRAM_REFUSED need_gb=16.0 free_gb=3.2\n", 75, "needs ~16 GB VRAM but 3.2 GB is free"),
        ("", "", 137, "OOM-killed at MemoryMax=22G"),
    ],
)
def test_a_failure_gpu_tenant_explains_raises_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, code: int, message: str
) -> None:
    fake_gpu_tenant(
        tmp_path, monkeypatch, f"printf %s {shlex.quote(stdout)}\nprintf %s {shlex.quote(stderr)} >&2\nexit {code}"
    )
    with pytest.raises(gpu.GpuJobError, match=message):
        run_probe()


def test_an_unexplained_failure_is_returned_for_the_caller_to_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_gpu_tenant(tmp_path, monkeypatch, "printf x\nexit 3")
    result = run_probe()
    assert (result.returncode, result.stdout) == (3, "x")


def _processes_matching(token: str) -> list[int]:
    """PIDs whose command line carries `token`; empty when the job is gone.

    The token is per run, so an orphan from an earlier run cannot answer for
    this one — a fixed marker did exactly that to a green run (measured).
    """
    listing = subprocess.run(["ps", "-A", "-o", "pid=,args="], capture_output=True, text=True).stdout
    return [int(line.split(None, 1)[0]) for line in listing.splitlines() if token in line]


def test_a_job_over_its_timeout_is_terminated_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A job past its timeout raises, and the job is KILLED rather than left running.

    The fixture is `exec sleep`, not `sleep &` plus a `trap`: a trap only runs
    for a signal that arrives after bash installed it, and this test gives the
    job one second, so a trap-ran marker asked whether bash reached its second
    line in time — a question about the host's exec latency. Measured on this
    Mac, a freshly written script's first exec took up to 7.8s while a warm one
    took 0.01s, so the marker's outcome was a coin flip (issue #24: 5 of 5 runs
    failed on a cold cache, 10 of 10 passed on a warm one).

    `exec` makes the fixture exactly one process from the first instant, so the
    SIGTERM always reaches it. Two things are asserted, because the mutation
    probe proved one is not enough: a branch that raises on timeout but never
    stops the job still returns in ~1s and passed a timing-only check. So the
    job must be ABSENT from the process table, and the call must return far
    sooner than the job would have ended on its own.
    """
    # `exec` replaces bash with the job, so no shell has to reach a trap line and
    # the job is ONE process from the first instant. It is Python, not `sleep`,
    # because the run's token must be a real ARGUMENT: `sleep 41.3 <token>` is
    # rejected ("invalid time interval") and `# <token>` is a shell comment that
    # never reaches argv — measured, and the comment form left the
    # process-table assertion below vacuous (a mutant that reported the timeout
    # and left the job running still passed).
    token = f"golem-gpu-timeout-{uuid.uuid4().hex[:12]}"
    fake_gpu_tenant(
        tmp_path,
        monkeypatch,
        f'exec {shlex.quote(sys.executable)} -c "import time; time.sleep({JOB_WOULD_HAVE_RUN_S})" {token}',
    )
    monkeypatch.setattr(gpu, "GPU_QUEUE_TIMEOUT_S", 0)

    started_at = time.monotonic()
    with pytest.raises(gpu.GpuJobError, match="exceeded 1s and was killed"):
        gpu.run_gpu_job(["true"], label="Probe", note="probe", need_bytes=1e9, timeout_s=1)
    elapsed_s = time.monotonic() - started_at

    survivors = _processes_matching(token)
    for pid in survivors:  # the test's own cleanup: never leave a 41s sleep behind
        os.kill(pid, signal.SIGKILL)
    assert not survivors, (
        f"PIDs {survivors} still running after run_gpu_job raised: the timeout was reported but the job was not stopped"
    )
    assert elapsed_s < TERMINATED_WITHIN_S, f"took {elapsed_s:.1f}s: the job ran to completion instead of being killed"
