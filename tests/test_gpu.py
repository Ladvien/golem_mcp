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
    ("stdout", "stderr", "code", "message", "kind"),
    [
        (
            "TIMEOUT after 20m; held by sanctuary-icons@big\n", "", 2, "Probe: GPU queue timed out",
            gpu.JOB_ERROR_QUEUE_TIMEOUT,
        ),
        (
            "REFUSED: held by sanctuary-icons@big (3d) until 12:00\n", "", 1, "gpu-tenant refused: REFUSED: held by",
            gpu.JOB_ERROR_REFUSED,
        ),
        (
            "", "VRAM_REFUSED need_gb=16.0 free_gb=3.2\n", 75, "needs ~16 GB VRAM but 3.2 GB is free",
            gpu.JOB_ERROR_VRAM_REFUSED,
        ),
        ("", "", 137, "OOM-killed at MemoryMax=22G", gpu.JOB_ERROR_OOM_KILLED),
    ],
)
def test_a_failure_gpu_tenant_explains_raises_its_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: str, stderr: str, code: int, message: str, kind: str
) -> None:
    fake_gpu_tenant(
        tmp_path, monkeypatch, f"printf %s {shlex.quote(stdout)}\nprintf %s {shlex.quote(stderr)} >&2\nexit {code}"
    )
    with pytest.raises(gpu.GpuJobError, match=message) as raised:
        run_probe()
    assert raised.value.kind == kind
    # What the process printed survives on the error, so a caller keeps the log of a job that never finished.
    assert (raised.value.stdout, raised.value.stderr) == (stdout, stderr)


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


# `gpu-tenant status` as big printed it on 2026-10-27, mid-job.
SAMPLE_STATUS = (
    "tenant=3d\n"
    "vram=21558/24576 MiB  mem_available=1.7 GiB\n"
    "who=golem-mcp@big since=13:49 expires=13:55 (4m left) paused=- "
    "note=animate_mesh sanctuary_dead_death_g_s5600_20261027_134955\n"
    "queue=0\n"
)


def test_tenant_status_is_parsed_from_the_real_output() -> None:
    status = gpu.parse_tenant_status(SAMPLE_STATUS)
    assert status.holder_who == "golem-mcp@big"
    assert status.holder_note == "animate_mesh sanctuary_dead_death_g_s5600_20261027_134955"
    assert status.queue_length == 0
    assert status.mem_available_gib == pytest.approx(1.7)
    assert (status.vram_used_mib, status.vram_total_mib) == (21558, 24576)


def test_nobody_holding_the_card_reads_as_an_empty_holder() -> None:
    idle = gpu.parse_tenant_status("tenant=3d\nvram=900/24576 MiB  mem_available=40.2 GiB\nwho=-\nqueue=2\n")
    assert (idle.holder_who, idle.holder_note, idle.queue_length) == ("", "", 2)
    assert gpu.parse_tenant_status("tenant=3d\nqueue=0\n").holder_who == ""


def test_a_running_job_reports_that_it_is_on_the_gpu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The watcher reads `gpu-tenant status` while the job runs and says the job holds the card."""
    note = "probe-running"
    status = SAMPLE_STATUS.replace(
        "note=animate_mesh sanctuary_dead_death_g_s5600_20261027_134955", f"note={note}"
    )
    fake_gpu_tenant(
        tmp_path,
        monkeypatch,
        f'if [ "$1" = status ]; then printf %s {shlex.quote(status)}; exit 0; fi\nsleep 1\nexit 0',
    )
    monkeypatch.setattr(gpu, "GPU_STATUS_POLL_S", 0.1)
    messages: list[str] = []

    gpu.run_gpu_job(["true"], label="Probe", note=note, need_bytes=1e9, timeout_s=30, on_status=messages.append)

    assert any(message.startswith("running on the GPU") for message in messages), messages
    assert any("1.7 GiB RAM available" in message for message in messages), messages


def test_a_job_queued_behind_another_tenant_says_whom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_gpu_tenant(
        tmp_path,
        monkeypatch,
        'if [ "$1" = status ]; then printf "who=voice-serve@big since=1 note=diarize call\\nqueue=1\\n'
        'vram=1/2 MiB  mem_available=3.0 GiB\\n"; exit 0; fi\nsleep 1\nexit 0',
    )
    monkeypatch.setattr(gpu, "GPU_STATUS_POLL_S", 0.1)
    messages: list[str] = []

    gpu.run_gpu_job(["true"], label="Probe", note="mine", need_bytes=1e9, timeout_s=30, on_status=messages.append)

    assert any(
        message == "queued behind voice-serve@big (diarize call); 1 waiting; big has 3.0 GiB RAM available"
        for message in messages
    ), messages
