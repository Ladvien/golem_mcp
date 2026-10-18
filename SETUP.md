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
| **golem** | `/home/ladvien/golem_mcp/.venv` | 3.11 | 2.11.0+cu128 | the MCP server itself, and text-to-motion (`animate_mesh`, Kimodo) | `make sync-golem` |
| **SkinTokens** | `/home/ladvien/skintokens` | 3.11 | 2.7.0+cu128 | rigging (`rig_model`) | `scripts/install_skintokens.sh` |
| **MV-Adapter** | `/home/ladvien/mvadapter` | 3.11 | 2.13.0+cu130 | orbit views (`generate_orbit_views`) | `scripts/install_mvadapter.sh` |
| **TRELLIS.2** | `/home/ladvien/segvigen/.venv` | 3.11 | 2.13.0+cu130 | part segmentation (`segment_mesh`) **and** garment generation (`generate_garment`) | `scripts/install_segvigen.sh` |

Roughly 42 GB on disk in total. The MCP server runs in the **golem** env
(`golem-mcp.service`, a user unit), which is why that one is special — everything
else is a subprocess target. `/home/ladvien/trellis` now holds only the output
directory (`TRELLIS_OUTPUT_DIR`); the TRELLIS 1 venv, repo and models were deleted.

Every GPU job runs under a `gpu-tenant` lease; see "GPU leases" in the README.

## Why they can't be merged

Not stubbornness — each pair genuinely conflicts:

- **TRELLIS vs SkinTokens**: 3.10/torch 2.6.0+cu124 against 3.11/torch 2.7.0+cu128.
  SkinTokens needs 3.11 exactly (`open3d` has no cp313 wheel; `bpy >= 5.1` is
  cp313-only).
- **MV-Adapter**: compiles nvdiffrast, so its torch CUDA major must match the
  system toolkit (13.3) → cu130 → torch 2.13.
- **TRELLIS.2**: same cu130 constraint as MV-Adapter, but pinned to Python 3.11
  because `bpy` has no cp310 wheel at all and `bpy` 5.x (cp313-only) removed
  `cycles.filter_type`, which `data_toolkit/bpy_render.py` sets.

### The SegviGen env is really the TRELLIS.2 env

It is named for SegviGen because that is what it was built for, but SegviGen runs
*on* TRELLIS.2 and the install pulls the whole `TRELLIS.2-4B` backbone. So the
directory also provides:

- `Trellis2ImageTo3DPipeline` — image-to-3D that can emit **open surfaces**, which
  `generate_garment` needs and this repo's TRELLIS 1 `generate_3d` cannot do
- `bpy` 4.5.9 — the cloth and shrinkwrap draping in `scripts/garment_fit.py`

None of that needed extra installation; it became reachable once the SDPA
attention backend landed. Two TRELLIS generations therefore coexist on purpose:
TRELLIS 1 for characters (`generate_3d`), TRELLIS.2 for garments and segmentation.

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
./scripts/install_segvigen.sh          # part segmentation + garments (TRELLIS.2)
```

Each script's header records the dead ends found while building it — read those
before "fixing" an apparent oddity.

`install_segvigen.sh` pins both of its clones to exact commits and applies
`scripts/segvigen-patches/*.patch` on top, so an upstream change cannot silently
drift out from under the patch. It fails loudly if a patch no longer applies.

### golem (hosts the server)

```bash
git clone git@github.com:Ladvien/golem_mcp.git /home/ladvien/golem_mcp
cd /home/ladvien/golem_mcp
make sync-golem
```

The package is installed **editable**, so a `systemctl --user restart golem-mcp`
picks up source changes with no reinstall. `motion_correction` (Kimodo's foot-contact
correction) is a compiled module that is not on PyPI or in `uv.lock`: copy its
directory from an existing environment into `.venv/lib/python3.11/site-packages/`.
`health_check` reports `motion_correction_installed`.

## The service

```bash
cp golem-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now golem-mcp
```

A **user** unit, because `gpu-tenant run` uses `systemd-run --user`. Serves streamable
HTTP on `0.0.0.0:9786`. **After changing server code you must restart it**
(`systemctl --user restart golem-mcp`) — a running instance keeps serving the old
code, and that has caused confusion more than once.

Clients connect to `http://<big-ip>:9786/mcp`. On macOS, Claude Desktop needs
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

`nvdiffrast` is present in the TRELLIS, MV-Adapter and TRELLIS.2 envs, and
TRELLIS bakes **every texture** with it (`postprocessing_utils.py:5`, `:378`). Its
licence is *Nvidia Source Code License (1-Way Commercial)*: "may be used or
intended for use non-commercially… research or evaluation purposes only." It is
not optional — `o_voxel` cannot even be imported without it.

Everything else in the pipeline is permissive: TRELLIS (MIT), TRELLIS.2 (MIT),
SkinTokens (MIT), MV-Adapter (Apache 2.0), SDXL base (CreativeML Open RAIL++-M),
SegviGen (MIT).

`generate_garment` inherits the same nvdiffrast constraint, since `o_voxel` is on
its export path too.

Not legal advice — recorded so the constraint is visible if these assets ever
become commercial. See
`/mnt/codex_fs/game_assets/PART_SEGMENTATION_EVALUATION.md`.
