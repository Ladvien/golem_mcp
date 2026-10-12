"""run_gpu_job turns what gpu-tenant, the VRAM gate and the RAM cap report into one error, against a fake gpu-tenant."""

import shlex
import subprocess
from pathlib import Path

import pytest

from golem_mcp import gpu


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


def test_a_job_over_its_timeout_is_terminated_and_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    terminated = tmp_path / "terminated"
    fake_gpu_tenant(
        tmp_path, monkeypatch,
        f"sleep 30 &\ntrap 'kill $!; echo done > {terminated}; exit 143' TERM\nwait",
    )
    monkeypatch.setattr(gpu, "GPU_QUEUE_TIMEOUT_S", 0)
    with pytest.raises(gpu.GpuJobError, match="exceeded 1s and was killed"):
        gpu.run_gpu_job(["true"], label="Probe", note="probe", need_bytes=1e9, timeout_s=1)
    assert terminated.exists()
