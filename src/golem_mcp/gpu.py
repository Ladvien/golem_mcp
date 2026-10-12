"""One GPU path for every golem tool: the job runs under a `gpu-tenant run` lease.

gpu-tenant (on big) unloads the llama-swap models, queues behind other holders, runs the command in a RAM-capped
systemd scope and releases the card when the command exits. Before the job starts, `vram_gate` checks that the card
really has the VRAM the job needs, so a resident outside gpu-tenant fails the call fast instead of OOM-ing minutes in.
This process holds no VRAM: every job is a subprocess (in another venv when it needs bpy, TRELLIS.2 or MV-Adapter).
"""

import contextlib
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

GPU_TENANT = Path(os.environ.get("GPU_TENANT", "/home/ladvien/.local/bin/gpu-tenant"))
GPU_TENANT_WHO = "golem-mcp@big"
GPU_TENANT_FOCUS = "3d"
GPU_JOB_MEM_MAX = "22G"
GPU_QUEUE_TIMEOUT = "20m"
GPU_QUEUE_TIMEOUT_S = 1200
VRAM_REFUSED_EXIT = 75
OOM_KILLED_EXIT = 137  # gpu-tenant reports a job killed by SIGKILL as 128 + 9
TERMINATE_GRACE_S = 60  # gpu-tenant forwards SIGTERM, then kills the job after its own 30 s grace

# gpu-tenant lets a second `run` from a `who` that already holds the card proceed, and refuses a second waiter from
# the same `who`, so golem serialises its own jobs here.
_gpu_lock = threading.Lock()


class GpuJobError(RuntimeError):
    """A GPU job did not get to run to completion: refused, queued too long, short of VRAM or RAM, or timed out."""


def _line_starting(text: str, prefix: str) -> str | None:
    return next((line for line in text.splitlines() if line.startswith(prefix)), None)


def _stop(proc: "subprocess.Popen[str]") -> None:
    """Ask gpu-tenant to stop its job (it forwards SIGTERM and releases the lease), then kill the whole group."""
    proc.terminate()
    try:
        proc.communicate(timeout=TERMINATE_GRACE_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()


def run_gpu_job(
    argv: list[str],
    *,
    label: str,
    note: str,
    need_bytes: float,
    timeout_s: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> "subprocess.CompletedProcess[str]":
    """Run `argv` under a gpu-tenant lease once at least `need_bytes` of VRAM is free.

    `timeout_s` is how long the job may run; waiting for the lease adds up to GPU_QUEUE_TIMEOUT. The returned process
    carries gpu-tenant's own lines in stdout beside the job's, so callers look for their success marker, not for a
    clean stdout. A non-zero exit that gpu-tenant, the VRAM gate or the RAM cap explains raises GpuJobError; any other
    result is returned for the caller to judge.
    """
    cmd = [
        str(GPU_TENANT), "run", GPU_TENANT_FOCUS,
        "--who", GPU_TENANT_WHO, "--mem", GPU_JOB_MEM_MAX,
        "--wait", "--timeout", GPU_QUEUE_TIMEOUT, "--note", note,
        "--", sys.executable, "-m", "golem_mcp.vram_gate", "--need-bytes", str(int(need_bytes)), "--", *argv,
    ]
    with _gpu_lock:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s + GPU_QUEUE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _stop(proc)
            raise GpuJobError(f"{label} exceeded {timeout_s}s and was killed") from None

    if proc.returncode != 0:
        if _line_starting(stdout, "TIMEOUT after"):
            raise GpuJobError(f"{label}: GPU queue timed out after {GPU_QUEUE_TIMEOUT} - see `gpu-tenant status`")
        refused = _line_starting(stdout, "REFUSED:")
        if refused:
            raise GpuJobError(f"{label}: gpu-tenant refused: {refused}")
        if proc.returncode == VRAM_REFUSED_EXIT and "VRAM_REFUSED" in stderr:
            found = re.search(r"free_gb=([0-9.]+)", stderr)
            free_gb = found.group(1) if found else "?"
            raise GpuJobError(
                f"{label} needs ~{need_bytes / 1e9:.0f} GB VRAM but {free_gb} GB is free under the lease; "
                "a resident outside gpu-tenant (voice-serve, ollama, hs-serve-distill, laya-sidecar) holds the card"
            )
        if proc.returncode == OOM_KILLED_EXIT:
            raise GpuJobError(f"{label} was OOM-killed at MemoryMax={GPU_JOB_MEM_MAX}")
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def gpu_status() -> str:
    """`gpu-tenant status` (who holds the card, the queue, recent events), or why it is unavailable."""
    try:
        return subprocess.run([str(GPU_TENANT), "status"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unavailable: {e}"
