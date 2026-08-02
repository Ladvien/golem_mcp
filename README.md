# trellis2-mcp

An MCP server for the **image → 3D → rigged character** pipeline.

Generate a reference image with FLUX, turn it into a textured mesh with TRELLIS,
then generate a skeleton and skin weights with SkinTokens/TokenRig — all as MCP
tools, driven from a single conversation.

```
  generate_image          generate_3d              rig_model
  FLUX.2 / mflux    →     TRELLIS           →      SkinTokens / TokenRig
  (bmb, Apple MLX)        (big, RTX 3090)          (big, RTX 3090)
       .png                 .glb + .ply              rigged .glb
```

The two GPU stages **hot-swap on one RTX 3090** — see [GPU hot-swapping](#gpu-hot-swapping).

---

## Tools

| Tool | What it does |
|---|---|
| `generate_image` | FLUX.2 text-to-image (or img2img) via mflux on `bmb`, copied back to `big` |
| `generate_3d` | Single image → textured `.glb` + Gaussian `.ply` via TRELLIS |
| `generate_3d_multi_image` | Multi-view conditioning (2–6 images of one object) |
| `rig_model` | Mesh → rigged `.glb` with skeleton + skin weights via TokenRig |
| `free_gpu` | Evict TRELLIS from VRAM and report free memory |
| `health_check` | Readiness, GPU state, and whether the rigger is installed |
| `list_outputs` | Recent outputs across 3D, rigged, and image dirs |

`generate_3d` returns an `output_name`; pass it straight to `rig_model`:

```
generate_3d(image="ref.png", output_name="gargoyle")
rig_model(mesh="gargoyle.glb", num_beams=10)
```

Relative names in `rig_model` resolve against the TRELLIS output dir, so no path
plumbing is needed between the two stages.

---

## Installation

Three independent installs. The MCP server itself runs inside the **TRELLIS**
venv; the rigger runs as a subprocess in its own.

> **The two GPU environments cannot be merged.** TRELLIS needs Python 3.10 with
> torch 2.6.0+cu124; SkinTokens needs Python 3.11 with torch 2.7.0+cu128
> (`open3d` ships no cp313 wheel, and `bpy >= 5.1` is cp313-only). This is why
> `rig_model` shells out instead of importing.

### Prerequisites

- NVIDIA GPU, ≥ 14 GB VRAM for rigging (a 24 GB 3090 has comfortable headroom)
- NVIDIA driver ≥ 525, CUDA toolkit ≥ 12.1
- [`uv`](https://docs.astral.sh/uv/)
- An SSH alias to a Mac running mflux, if you want `generate_image`

### 1. TRELLIS (Python 3.10) — hosts the MCP server

```bash
git clone https://github.com/microsoft/TRELLIS.git /home/ladvien/trellis/repo
cd /home/ladvien/trellis/repo

uv venv --python 3.10 /home/ladvien/trellis/.venv
source /home/ladvien/trellis/.venv/bin/activate

# TRELLIS's own installer pulls the heavy CUDA extensions
# (spconv, xformers, flash-attn, nvdiffrast, diffoctreerast, ...).
. ./setup.sh --basic --xformers --flash-attn --diffoctreerast --spconv --mipgaussian --nvdiffrast
```

This deployment runs torch 2.6.0+cu124 and xformers 0.0.29.post3.

**Download the TRELLIS model:**

```bash
uv pip install huggingface_hub
hf download JeffreyXiang/TRELLIS-image-large \
    --local-dir /home/ladvien/trellis/models/TRELLIS-image-large
```

You should end up with `pipeline.json` and a `ckpts/` directory holding the
sparse-structure and SLAT encoder/decoder/flow safetensors.

**Install this server into that venv:**

```bash
cd /home/ladvien/trellis2_mcp
uv pip install --python /home/ladvien/trellis/.venv/bin/python -e .
```

### 2. SkinTokens / TokenRig (Python 3.11) — the rigger

One script does the whole thing:

```bash
./scripts/install_skintokens.sh
```

It is idempotent — re-running will not re-download torch. It performs:

1. Clone `VAST-AI-Research/SkinTokens` to `/home/ladvien/skintokens/repo`
2. Create a **Python 3.11** venv at `/home/ladvien/skintokens/.venv`
3. Install torch 2.7.0 / torchvision 0.22.0 / torchaudio 2.7.0 (cu128)
4. Install `requirements.txt` (the `bpy` wheel alone is several hundred MB)
5. Install a **prebuilt** flash-attn 2.8.3 wheel, auto-selecting the C++ ABI
   variant matching your torch build
6. **Patch `bpy_server` to bind loopback only** (see [Security](#security))
7. Download checkpoints via `download.py --model`
8. Verify imports and checkpoint sizes, failing loudly on any gap

**Rigging model checkpoints** (~1.6 GB, fetched by step 7 into
`/home/ladvien/skintokens/repo/experiments/`):

| Checkpoint | Size | Role |
|---|---|---|
| `skin_vae_2_10_32768/last.ckpt` | 465 MB | FSQ-CVAE skin-weight tokenizer |
| `articulation_xl_quantization_256_token_4/grpo_1400.ckpt` | 1.1 GB | GRPO-refined TokenRig model |

It also pulls the **Qwen3-0.6B config only** into `models/Qwen3-0.6B/`
(`ignore_patterns=["*.bin", "*.safetensors"]`). The transformer weights live
inside the TokenRig checkpoint, so that download being tiny is correct.

Do **not** build flash-attn from source (`--no-build-isolation`) — it takes 1–3
hours and can OOM system RAM. Do not try flash-attn 4 either; Qwen3, the TokenRig
backbone, does not support it.

Verify:

```bash
cd /home/ladvien/skintokens/repo
/home/ladvien/skintokens/.venv/bin/python demo.py \
    --input examples/giraffe.glb --output /tmp/giraffe.glb \
    --use_transfer --num_beams 3
```

A quadruped is the right first test — it is exactly what template-based riggers
cannot do. A correct install yields a sane spine, four leg chains, and a neck.

### 3. mflux on the Mac (optional, for `generate_image`)

On `bmb`, install [mflux](https://github.com/filipstrand/mflux) into
`~/mflux-venv` and make sure `~/mflux-output` exists. The server reaches it over
SSH and copies results back with `scp`, so key-based SSH must work non-interactively.

---

## Configuration

All paths are environment variables with the defaults below.

| Variable | Default |
|---|---|
| `TRELLIS_REPO` | `/home/ladvien/trellis/repo` |
| `TRELLIS_MODEL` | `/home/ladvien/trellis/models/TRELLIS-image-large` |
| `TRELLIS_OUTPUT_DIR` | `/home/ladvien/trellis/output` |
| `SKINTOKENS_REPO` | `/home/ladvien/skintokens/repo` |
| `SKINTOKENS_PYTHON` | `/home/ladvien/skintokens/.venv/bin/python` |
| `BMB_HOST` | `bmb` |
| `BMB_MFLUX_PYTHON` | `~/mflux-venv/bin/python3` |
| `BMB_MFLUX_OUTPUT` | `~/mflux-output` |
| `SPCONV_ALGO` | `native` |
| `ATTN_BACKEND` | `xformers` |

Outputs land in `$TRELLIS_OUTPUT_DIR`, with `images/` and `rigged/` beneath it.

## Running

```bash
sudo cp trellis2-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trellis2-mcp
```

Serves SSE on `0.0.0.0:9786`. After changing server code, restart the unit —
a running instance keeps serving the old code.

---

## GPU hot-swapping

TRELLIS and TokenRig each want most of a 24 GB card, so exactly one holds the GPU
at a time. Every GPU tool serializes on a single lock:

- **TRELLIS stays resident** between generations — a reload costs ~30 s, so
  repeated `generate_3d` calls are fast.
- **`rig_model` evicts TRELLIS first**, then runs the rigger as a subprocess.
  That process's VRAM is reclaimed by the OS when it exits, so there is nothing
  to unload on the way back.
- The next `generate_3d` reloads TRELLIS automatically. `trellis_evicted` in the
  `rig_model` response tells you whether a swap actually happened.
- `free_gpu` hands the card back manually.

Measured on a 3090 with a desktop session running: 18.0 GB free → 12.2 GB with
TRELLIS resident → back to 18.0 GB after eviction.

Because the lock lives in the server process, **run one GPU tool at a time**;
a second process bypasses it entirely.

---

## Security

Upstream SkinTokens issue #7: `src/server/bpy_server.py` binds `0.0.0.0:59876`
and deserializes untrusted request bodies with `torch.load(weights_only=False)`
— i.e. pickle, which executes arbitrary code during unpickling, before any
validation. That is unauthenticated RCE reachable from the LAN whenever a rig job
is running.

Its only client is `demo.py` on loopback, so `install_skintokens.sh` rebinds it to
`127.0.0.1` and aborts the install if the patch does not apply. If you install
SkinTokens by hand, do this yourself.

---

## Known issues and gotchas

**Rigging hangs forever at the progress bar.** Upstream issue #3: `http_proxy` /
`https_proxy` intercept the loopback call from the dataloader to `bpy_server`.
`rig_model` strips all proxy variables from the subprocess environment and sets
`NO_PROXY=localhost,127.0.0.1`, so this should not bite here — but it will if you
run `demo.py` by hand.

**`demo.py` exits 0 even when export fails.** It prints `[Error] ...` and returns
normally, so the exit code is not a success signal. `rig_model` verifies the
output file exists and is non-empty instead.

**Blender import errors on a rigged GLB.** Delete the `glTF_not_exported` node
after importing. No deeper fix upstream.

**Bone names are generic.** TokenRig emits `bone_0 … bone_N`, not Mixamo or UE5
conventions, and output is always GLB. If you need FBX or UE5 Mannequin naming,
the third-party `Rizzlord/ComfyUI-SkinToken` wrapper adds both.

**`flash_attn` undefined symbol on import.** Wrong C++ ABI wheel — install the
other variant. The install script picks this automatically.

**Distilled klein models reject guidance.** `flux2-klein-4b` / `-9b` / `-9b-kv`
accept only `guidance=1.0`; use a `flux2-klein-base-*` model to vary it.
`generate_image` validates this and tells you rather than failing deep in mflux.

**`num_beams` is the rigging speed/VRAM lever.** Default 10 for quality; drop to
1–3 for fast iteration.

**Skin weights need review.** Shoulders and hips are where auto-generated weights
fail. Pose to extremes before trusting them — true of any auto-rigger.
