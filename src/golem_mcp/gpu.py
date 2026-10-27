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
from collections.abc import Callable
from dataclasses import dataclass
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
# How often a caller that asked for status hears where its job stands. `gpu-tenant status` is a cheap read (one
# subprocess, ~0.1 s), and a 15 s cadence is under the MCP client's own progress heartbeat while being far too slow to
# load big.
GPU_STATUS_POLL_S = 15.0

# Why a GPU job did not run to completion, as a value a caller can branch on rather than a sentence it must parse.
JOB_ERROR_QUEUE_TIMEOUT = "queue_timeout"
JOB_ERROR_REFUSED = "refused"
JOB_ERROR_VRAM_REFUSED = "vram_refused"
JOB_ERROR_OOM_KILLED = "oom_killed"
JOB_ERROR_WALL_TIMEOUT = "wall_timeout"

# gpu-tenant lets a second `run` from a `who` that already holds the card proceed, and refuses a second waiter from
# the same `who`, so golem serialises its own jobs here.
_gpu_lock = threading.Lock()
# The note of the job holding `_gpu_lock`, so a caller waiting on it can be told what it is waiting behind. Written
# only under the lock; read without it, which is a benign race on a str reference.
_lock_holder_note = ""


class GpuJobError(RuntimeError):
    """A GPU job did not get to run to completion: refused, queued too long, short of VRAM or RAM, or timed out.

    `kind` says which (one of the JOB_ERROR_* constants), and `stdout`/`stderr` carry what the process printed before
    it stopped, so a caller can keep the log of a job that never finished.
    """

    def __init__(self, message: str, *, kind: str, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.stdout = stdout
        self.stderr = stderr


@dataclass(frozen=True)
class TenantStatus:
    """`gpu-tenant status`, parsed: who holds the card, for what, how many wait, and big's free memory."""

    holder_who: str  # "" when nobody holds the card
    holder_note: str
    queue_length: int
    mem_available_gib: float | None
    vram_used_mib: int | None
    vram_total_mib: int | None


def parse_tenant_status(text: str) -> TenantStatus:
    """Read `gpu-tenant status` output into a TenantStatus.

    The format, measured on big 2026-10-27:

        tenant=3d
        vram=21558/24576 MiB  mem_available=1.7 GiB
        who=golem-mcp@big since=13:49 expires=13:55 (4m left) paused=- note=animate_mesh sanctuary_dead_...
        queue=0

    `note` is the REST of the `who=` line after `note=`, because a note carries spaces. A missing `who=` line, or
    `who=-`, means nobody holds the card.
    """
    holder_who = ""
    holder_note = ""
    queue_length = 0
    mem_available_gib: float | None = None
    vram_used_mib: int | None = None
    vram_total_mib: int | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("who="):
            who = line.split(None, 1)[0].removeprefix("who=")
            holder_who = "" if who == "-" else who
            _, separator, note = line.partition(" note=")
            holder_note = note.strip() if separator else ""
        elif line.startswith("queue="):
            with contextlib.suppress(ValueError):
                queue_length = int(line.removeprefix("queue=").split()[0])
        vram = re.search(r"vram=(\d+)/(\d+)\s*MiB", line)
        if vram:
            vram_used_mib, vram_total_mib = int(vram.group(1)), int(vram.group(2))
        memory = re.search(r"mem_available=([0-9.]+)\s*GiB", line)
        if memory:
            mem_available_gib = float(memory.group(1))
    if not holder_who:
        holder_note = ""
    return TenantStatus(holder_who, holder_note, queue_length, mem_available_gib, vram_used_mib, vram_total_mib)


def tenant_status() -> TenantStatus | None:
    """The card's state right now, or None when `gpu-tenant status` cannot be read."""
    text = gpu_status()
    if text.startswith("unavailable"):
        return None
    return parse_tenant_status(text)


def _status_message(note: str, started: threading.Event) -> str:
    """One sentence about where a job stands: behind golem's own job, running, or queued behind someone else."""
    if not started.is_set():
        return f"waiting for golem's own previous GPU job ({_lock_holder_note or 'unnamed'}) to finish"
    status = tenant_status()
    if status is None:
        return "GPU status unavailable"
    memory = f"{status.mem_available_gib:.1f}" if status.mem_available_gib is not None else "?"
    if status.holder_who == GPU_TENANT_WHO and status.holder_note == note:
        return f"running on the GPU; big has {memory} GiB RAM available"
    return (
        f"queued behind {status.holder_who or 'nobody'} ({status.holder_note}); {status.queue_length} waiting; "
        f"big has {memory} GiB RAM available"
    )


def _watch(note: str, started: threading.Event, stop: threading.Event, on_status: Callable[[str], None]) -> None:
    """Report the job's state every GPU_STATUS_POLL_S until told to stop. A failing callback never kills the job."""
    while not stop.is_set():
        with contextlib.suppress(Exception):
            on_status(_status_message(note, started))
        stop.wait(GPU_STATUS_POLL_S)


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
    on_status: Callable[[str], None] | None = None,
) -> "subprocess.CompletedProcess[str]":
    """Run `argv` under a gpu-tenant lease once at least `need_bytes` of VRAM is free.

    `timeout_s` is how long the job may run; waiting for the lease adds up to GPU_QUEUE_TIMEOUT. The returned process
    carries gpu-tenant's own lines in stdout beside the job's, so callers look for their success marker, not for a
    clean stdout. A non-zero exit that gpu-tenant, the VRAM gate or the RAM cap explains raises GpuJobError with its
    `kind`; any other result is returned for the caller to judge.

    `on_status`, when given, hears where the job stands every GPU_STATUS_POLL_S from a daemon thread: waiting behind
    golem's own previous job, queued behind another tenant, or running.
    """
    global _lock_holder_note
    cmd = [
        str(GPU_TENANT), "run", GPU_TENANT_FOCUS,
        "--who", GPU_TENANT_WHO, "--mem", GPU_JOB_MEM_MAX,
        "--wait", "--timeout", GPU_QUEUE_TIMEOUT, "--note", note,
        "--", sys.executable, "-m", "golem_mcp.vram_gate", "--need-bytes", str(int(need_bytes)), "--", *argv,
    ]
    started = threading.Event()
    stop = threading.Event()
    if on_status is not None:
        threading.Thread(target=_watch, args=(note, started, stop, on_status), daemon=True).start()
    try:
        with _gpu_lock:
            _lock_holder_note = note
            try:
                proc = subprocess.Popen(
                    cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    start_new_session=True,
                )
                started.set()
                try:
                    stdout, stderr = proc.communicate(timeout=timeout_s + GPU_QUEUE_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    _stop(proc)
                    raise GpuJobError(
                        f"{label} exceeded {timeout_s}s and was killed", kind=JOB_ERROR_WALL_TIMEOUT
                    ) from None
            finally:
                _lock_holder_note = ""
    finally:
        stop.set()

    if proc.returncode != 0:
        if _line_starting(stdout, "TIMEOUT after"):
            raise GpuJobError(
                f"{label}: GPU queue timed out after {GPU_QUEUE_TIMEOUT} - see `gpu-tenant status`",
                kind=JOB_ERROR_QUEUE_TIMEOUT, stdout=stdout, stderr=stderr,
            )
        refused = _line_starting(stdout, "REFUSED:")
        if refused:
            raise GpuJobError(
                f"{label}: gpu-tenant refused: {refused}", kind=JOB_ERROR_REFUSED, stdout=stdout, stderr=stderr
            )
        if proc.returncode == VRAM_REFUSED_EXIT and "VRAM_REFUSED" in stderr:
            found = re.search(r"free_gb=([0-9.]+)", stderr)
            free_gb = found.group(1) if found else "?"
            raise GpuJobError(
                f"{label} needs ~{need_bytes / 1e9:.0f} GB VRAM but {free_gb} GB is free under the lease; "
                "a resident outside gpu-tenant (voice-serve, ollama, hs-serve-distill, laya-sidecar) holds the card",
                kind=JOB_ERROR_VRAM_REFUSED, stdout=stdout, stderr=stderr,
            )
        if proc.returncode == OOM_KILLED_EXIT:
            raise GpuJobError(
                f"{label} was OOM-killed at MemoryMax={GPU_JOB_MEM_MAX}",
                kind=JOB_ERROR_OOM_KILLED, stdout=stdout, stderr=stderr,
            )
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def gpu_status() -> str:
    """`gpu-tenant status` (who holds the card, the queue, recent events), or why it is unavailable."""
    try:
        return subprocess.run([str(GPU_TENANT), "status"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unavailable: {e}"


def vram_free_bytes() -> float | None:
    """Free VRAM on the card right now, or None when it cannot be read.

    Read in a subprocess because this process must not import torch (nor hold a CUDA context). It is the same
    reading `vram_gate` makes, taken without a lease, so a llama-swap model the lease would unload counts as used.
    """
    code = "import torch; print(torch.cuda.mem_get_info(0)[0] if torch.cuda.is_available() else -1)"
    try:
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        free = float(lines[-1])
    except ValueError:
        return None
    return free if free >= 0 else None
