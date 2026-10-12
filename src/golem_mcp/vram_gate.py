"""Refuse to start a GPU job the card cannot hold: `python -m golem_mcp.vram_gate --need-bytes N -- cmd...`.

Runs inside the gpu-tenant lease, after llama-swap has been unloaded, so what is free now is what the job gets. It
reads VRAM through torch, not NVML, which this host's driver/module mismatch has broken. When there is room it
replaces itself with `cmd` (same process, same RAM-capped scope), so the gate's CUDA context goes with it.
"""

import os
import sys

import torch

VRAM_REFUSED_EXIT = 75  # EX_TEMPFAIL, read by golem_mcp.gpu


def main(argv: list[str]) -> int:
    if "--" not in argv or argv[0] != "--need-bytes" or len(argv) < 4 or argv.index("--") != 2:
        sys.stderr.write("usage: python -m golem_mcp.vram_gate --need-bytes N -- cmd [args...]\n")
        return 64
    try:
        need = float(argv[1])
    except ValueError:
        sys.stderr.write(f"vram_gate: --need-bytes is not a number: {argv[1]!r}\n")
        return 64
    cmd = argv[3:]

    if not torch.cuda.is_available():
        sys.stderr.write(f"VRAM_REFUSED need_gb={need / 1e9:.1f} free_gb=0.0 (cuda unavailable)\n")
        return VRAM_REFUSED_EXIT
    free = torch.cuda.mem_get_info(0)[0]
    if free < need:
        sys.stderr.write(f"VRAM_REFUSED need_gb={need / 1e9:.1f} free_gb={free / 1e9:.1f}\n")
        return VRAM_REFUSED_EXIT

    # libcuda's /dev/nvidia* descriptors survive exec unless closed, and would keep this context's VRAM held.
    os.closerange(3, os.sysconf("SC_OPEN_MAX"))
    os.execvp(cmd[0], cmd)
    return 1  # unreachable: execvp raises OSError when cmd cannot start


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
