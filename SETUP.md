# Setup

This server orchestrates several models that **cannot share a Python
environment**. Each has its own venv on `big`, and the MCP server shells out to
them. This file explains what each one is, why it is separate, and how to rebuild
it.

Every install script is idempotent — re-running skips what is already present.
None needs root.

## The environments

| Env | Path | Python | torch | Purpose | Installer |
|---|---|---|---|---|---|
| **TRELLIS** | `/home/ladvien/trellis` | 3.10 | 2.6.0+cu124 | image → 3D. **Hosts the MCP server itself** | manual (see below) |
| **SkinTokens** | `/home/ladvien/skintokens` | 3.11 | 2.7.0+cu128 | rigging (`rig_model`) | `scripts/install_skintokens.sh` |
| **MV-Adapter** | `/home/ladvien/mvadapter` | 3.11 | 2.13.0+cu130 | orbit views (`generate_orbit_views`) | `scripts/install_mvadapter.sh` |
| **SegviGen** | `/home/ladvien/segvigen/.venv` | 3.11 | 2.13.0+cu130 | part segmentation (`segment_mesh`) | `scripts/install_segvigen.sh` |

Roughly 42 GB on disk in total. The MCP server runs inside the **TRELLIS** env
(`trellis2-mcp.service`), which is why that one is special — everything else is a
subprocess target.

Only one may hold the GPU at a time; see "GPU hot-swapping" in the README.

## Why they can't be merged

Not stubbornness — each pair genuinely conflicts:

- **TRELLIS vs SkinTokens**: 3.10/torch 2.6.0+cu124 against 3.11/torch 2.7.0+cu128.
  SkinTokens needs 3.11 exactly (`open3d` has no cp313 wheel; `bpy >= 5.1` is
  cp313-only).
- **MV-Adapter**: compiles nvdiffrast, so its torch CUDA major must match the
  system toolkit (13.3) → cu130 → torch 2.13.
- **SegviGen**: same cu130 constraint as MV-Adapter, but pinned to Python 3.11
  because `bpy` has no cp310 wheel at all and `bpy` 5.x (cp313-only) removed
  `cycles.filter_type`, which `data_toolkit/bpy_render.py` sets.

### SegviGen attention: SDPA, not flash-attn or xformers

Neither compiled attention backend is obtainable on this box. `xformers` has no
cu13 build at any version — its PyPI wheel installs but reports "xFormers wasn't
build with CUDA support" — and no flash-attn cu13 wheel exists for torch 2.13 at
any Python version.

Building flash-attn from source is not the answer either. It was measured at
**~7 hours** here: its `setup.py` ignores `TORCH_CUDA_ARCH_LIST` (it reads
`FLASH_ATTN_CUDA_ARCHS`) and emits `sm_80/90/100/120` for all 72 `.cu` files,
three-quarters of it dead weight for a 3090. It also cannot be built unguarded —
at `MAX_JOBS=2` it spawns three `cicc` processes at ~3.7 GB each and exhausts all
31 GB.

Instead, `scripts/segvigen-patches/` adds an **SDPA backend to trellis2's sparse
attention**. Upstream already ships one for its *dense* attention
(`trellis2/modules/attention/full_attn.py`) and simply omitted it from the sparse
module; the models only use `attn_mode='full'`, so `sparse/windowed_attn.py` is
never reached and a single dispatch branch closes the gap. Run everything with
`ATTN_BACKEND=sdpa`.

## Prerequisites

- NVIDIA GPU, 24 GB (RTX 3090 here). Driver 610+.
- **CUDA toolkit at `/opt/cuda`** (13.3 via `pacman -S cuda`). Three of the envs
  compile CUDA extensions against it.
- [`uv`](https://docs.astral.sh/uv/) on `PATH`.
- A HuggingFace token in `~/.cache/huggingface/token` — DINOv3 is manually gated
  and RMBG-2.0 auto-gated. `hf auth login` writes it there, which matters because
  it must be readable by **non-interactive SSH**; `.zshrc` is not.

### Do not use an older CUDA

This box has **glibc 2.43**, and glibc ≥ 2.41 declares `rsqrtf` and friends in
`math.h`, colliding with the math headers of CUDA ≤ 12.4. Every `.cu` fails with
redeclaration errors. This is not a compiler-version problem and
`-allow-unsupported-compiler` does not help. CUDA 12.4's installer also cannot run
here at all (it is linked against `libxml2.so.2`; this distro ships `.so.16`).

Consequence: anything that compiles must use CUDA 13.3 and therefore cu130 torch,
even where upstream documents cu124.

### Cap build parallelism

`ninja` defaults to one job per core (24 here) and each `cudafe++`/`cicc` wants
several GB. Unbounded, the o-voxel build OOM-killed 13 of its own compiler
processes. The scripts set `MAX_JOBS=4`. **flash-attn cannot be built from source
on this box at all** — it spawns past `MAX_JOBS=2` and exhausts 31 GB.

## Rebuilding

```bash
./scripts/install_skintokens.sh        # rigging
./scripts/install_mvadapter.sh         # orbit views
./scripts/install_segvigen.sh          # part segmentation
```

Each script's header records the dead ends found while building it — read those
before "fixing" an apparent oddity.

`install_segvigen.sh` pins both of its clones to exact commits and applies
`scripts/segvigen-patches/*.patch` on top, so an upstream change cannot silently
drift out from under the patch. It fails loudly if a patch no longer applies.

### TRELLIS (hosts the server)

Not scripted here; it predates this repo. To recreate:

```bash
git clone https://github.com/microsoft/TRELLIS.git /home/ladvien/trellis/repo
uv venv --python 3.10 /home/ladvien/trellis/.venv
source /home/ladvien/trellis/.venv/bin/activate
cd /home/ladvien/trellis/repo
. ./setup.sh --basic --xformers --flash-attn --diffoctreerast --spconv --mipgaussian --nvdiffrast
hf download JeffreyXiang/TRELLIS-image-large \
    --local-dir /home/ladvien/trellis/models/TRELLIS-image-large
cd /home/ladvien/trellis2_mcp && uv pip install --python /home/ladvien/trellis/.venv/bin/python -e .
```

The MCP package is installed **editable**, so a `systemctl restart trellis2-mcp`
picks up source changes with no reinstall.

## The service

```bash
sudo cp trellis2-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trellis2-mcp
```

Serves SSE on `0.0.0.0:9786`. **After changing server code you must restart it** —
a running instance keeps serving the old code, and that has caused confusion more
than once.

Clients connect to `http://<big-ip>:9786/sse`. On macOS, Claude Desktop needs
**Local Network** permission (System Settings → Privacy & Security), or its
connection fails with `EHOSTUNREACH` while a shell `curl` from the same machine
succeeds.

## Image generation lives on `bmb`

`generate_image` and `generate_views` SSH to `bmb` and run **mflux** there
(Apple MLX), copying results back. That needs:

- key-based SSH to `bmb` working **non-interactively**
- mflux in `~/mflux-venv` on `bmb`, output dir `~/mflux-output`
- the HF token in `~/.cache/huggingface/token` **on bmb** (FLUX.2-klein-9B is gated)

Remote paths are resolved against the remote `$HOME` before quoting — a literal
`~` inside a quoted argument silently creates a directory named `~`.

## Licensing note

`nvdiffrast` is present in the TRELLIS, MV-Adapter and both SegviGen envs, and
TRELLIS bakes **every texture** with it (`postprocessing_utils.py:5`, `:378`). Its
licence is *Nvidia Source Code License (1-Way Commercial)*: "may be used or
intended for use non-commercially… research or evaluation purposes only." It is
not optional — `o_voxel` cannot even be imported without it.

Everything else in the pipeline is permissive: TRELLIS (MIT), SkinTokens (MIT),
MV-Adapter (Apache 2.0), SDXL base (CreativeML Open RAIL++-M), SegviGen (MIT).

Not legal advice — recorded so the constraint is visible if these assets ever
become commercial. See
`/mnt/codex_fs/game_assets/PART_SEGMENTATION_EVALUATION.md`.
