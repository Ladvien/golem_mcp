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
| `generate_views` | A consistent front/back/left/right set from one prompt, for multi-view conditioning |
| `generate_3d` | Single image → textured `.glb` + Gaussian `.ply` via TRELLIS |
| `generate_3d_multi_image` | Multi-view conditioning (2–6 images of one object) |
| `generate_orbit_views` | 6 geometrically consistent orbit views from one reference image, via MV-Adapter |
| `rig_model` | Mesh → rigged `.glb` with skeleton + skin weights via TokenRig |
| `segment_mesh` | Mesh → per-face part labels via SegviGen, leaving the mesh untouched |
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

## Where output goes

Local `$TRELLIS_OUTPUT_DIR` is the working area. The durable location is the
`codex_fs` library (NFS export from `three`, autofs-mounted), written on every run:

| What | Where |
|---|---|
| Reference images | `game_assets/generated/<prompt_slug>_<YYYYMMDD_HHMMSS>/reference.png` |
| Generated assets | `game_assets/models/gen_ai/<asset_type>/<output_name>/` |

An asset directory holds `asset.glb`, `asset.ply`, `reference.png`, and
`metadata.json`. `rig_model` adds `asset_rigged.glb` to the same directory and
flips `rigged` to true in the metadata, so a rigged asset stays one bundle.

`asset_type` selects the `gen_ai` subfolder — `characters`, `props` or
`environments`. Publishing **refuses to overwrite** an existing directory: these
are library assets, and silently clobbering one would destroy its provenance.
Pick a different `output_name` or remove the directory deliberately.

> **Note on the raw/curated split.** `/mnt/codex_fs/models/` is the documented
> target for raw pipeline output, with `gen_ai/` reserved for hand-promoted
> assets. This server writes generated assets straight into `gen_ai/` by explicit
> choice, so that tree now contains everything generated, not a curated subset.

**Record provenance at generation time.** Pass `source_prompt` and
`source_image_model` to `generate_3d`; they are the only record of how an asset
was made and cannot be reconstructed afterwards. Omitting `source_prompt` writes a
`_provenance_warning` into the metadata rather than leaving the gap silent.
`generate_image` returns the prompt-derived `reference_dir` to carry forward.

---

## Getting the best mesh and texture

### Scale: every asset comes out ~1 m tall

TRELLIS normalizes into a unit cube, so a generated human, a teacup and a
cathedral all export about 1 metre. Anything reading a measurement in metres —
garment conforming, physics, engine import — is silently wrong until it is scaled.

`generate_3d` always reports `geometry.dimensions_m`, and `target_height_m` scales
at export:

```
generate_3d(image="ref.png", target_height_m=1.75)   # adult human
```

The `.ply` Gaussian splat is always exported at normalized scale; only the `.glb`
is scaled. `rig_model` reports `dimensions_m` too, since `use_transfer` inherits
whatever scale the source mesh had.

### Texture: `render_resolution` is the real ceiling

The texture is baked from renders of the Gaussian splat. Upstream `to_glb`
hardcodes those renders at 1024px, which means a `texture_size` above 1024 only
upsamples — four times the file size, no additional detail. This server calls the
bake internals directly so the source resolution is a parameter, and **rejects**
`texture_size > render_resolution` rather than letting you pay for empty pixels.

| Parameter | Default | Effect |
|---|---|---|
| `render_resolution` | 1024 | Detail ceiling. 2048 needs `evict_trellis_for_bake=true` |
| `nviews` | 100 | Coverage of hidden areas (armpits, crotch, under chin); fewer seams |
| `lambda_tv` | 0.01 | Texture smoothing. Lower is sharper |

**Bake VRAM is the binding constraint.** `bake_texture` in `opt` mode holds every
view's observation, mask, UV and UV-derivative buffer on the GPU simultaneously for
all 2500 optimizer steps, so cost is `nviews x resolution^2 x 37 bytes`:

| | 100 views | 150 | 200 |
|---|---|---|---|
| **1024** | 3.9 GB | 5.8 GB | 7.8 GB |
| **2048** | 15.5 GB | 23.3 GB | 31.0 GB |

On a 24 GB card, `2048 x 100` fits only with TRELLIS evicted
(`evict_trellis_for_bake=true`, costing a ~30s reload next generation).
`2048 x 150` does not fit at all. Both are checked up front — a request that
cannot work fails in seconds with the numbers, rather than OOMing after minutes
of decimation and UV unwrap.

### Geometry: `simplify` is a *removal* ratio

`simplify` is passed to `pyvista`'s `decimate(target_reduction)`, which removes
that fraction of faces. `simplify=0.95` keeps **5%**; `0.8` keeps 20%; `0`
disables simplification entirely.

(Upstream's `postprocess_mesh` docstring says "ratio of faces to keep" — it is
wrong; `to_glb`'s "ratio of faces to remove" is correct.)

Geometric detail is capped by the mesh decoder's `resolution: 64` lattice, so
below roughly `0.5` you are adding redundant triangles rather than detail.

### The biggest lever is multi-view conditioning

From a single image the entire unseen side of the object is hallucinated — which,
for a character, is exactly the surface garments and armor conform to. No sampler
setting comes close to fixing this; only more conditioning views do.

`generate_views` produces the set, then feed it straight through:

```
views = generate_views(prompt="<subject only, no view language>", seed=7)
generate_3d_multi_image(images=views["images_json"], source_prompt=..., asset_type="characters")
```

What makes it work, confirmed against a single-image control with identical bake
settings:

- **One seed across every view.** This does most of the consistency work.
- **One clause changed, nothing else.** The tool appends the view phrase and
  leaves the rest of the prompt byte-identical, so the subject does not drift.
- **The same image model for all views.**

Give it the subject only — clothing, pose, lighting, background. View language in
your prompt (`seen from`, `facing directly`, `in profile`, …) fights the injected
clause and desynchronises the set, so it is rejected rather than silently blended.

**Avoid strongly asymmetric details.** A patch on one arm tends to mirror between
front and back, handing TRELLIS contradictory evidence about which arm carries it.
It survived that in testing, but the cleaner run omits it.

**The default set is `front,back`, and that is deliberate.** FLUX.2 klein will not
produce a 90° profile no matter how forcefully the prompt demands one — tested
with plain and emphatic phrasing on both `klein-4b` and `klein-9b`. `left` and
`right` come back as front-facing three-quarters, nearly identical to each other
and close to the front view, so they cost ~110s each and add almost nothing. They
remain available if you want to try them on a different subject.

If you need genuine side coverage, that is the point where a purpose-built
multi-view diffuser (Zero123++ / SV3D / MV-Adapter) earns its setup cost.

**Watch for pose drift.** Limb positions can shift between views — arms hanging in
front/back but spread in the sides. That is contradictory *geometry* evidence,
which matters more than texture drift. Pin the pose explicitly in the prompt
("arms held straight out at shoulder height") rather than loosely ("arms away from
the body").

Budget the time: each view is a full generation (~110s on `flux2-klein-9b`), so a
four-view set is 7–8 minutes before TRELLIS even starts.

`ss_steps` / `slat_steps` are past the knee around 24; 12→24 is visible, 24→50
mostly is not. Input image quality matters more: clean cutout, subject filling the
frame, flat even lighting.

---

## Getting the best rig

`rig_model` reports `mesh_diagnostics` before rigging and a `skeleton` report
after, plus a merged `warnings` list. Both are recorded into the published
`metadata.json`. What they mean:

### Tighten the bounding box — the biggest non-obvious lever

`Asset.normalize_vertices()` divides by `(v_max - v_min).max()` — uniformly, by
the **largest** bounding-box dimension — and joint coordinates are then quantized
into **256 bins**. So joint placement resolution is `largest_dimension / 256`, and
anything that widens the box without adding riggable geometry costs precision on
**all three axes**: a held weapon, a pedestal, wide wings, stray fragments.

Measured on a real asset: appending one stray triangle 1.2 m from the body took
`bbox_inflation` from 1.03 to 1.99 and joint resolution from **3.91 mm to
7.56 mm**. Half the precision, from one triangle. Rig the body alone and reattach
props afterwards.

`joint_resolution_mm` and `bbox_inflation` are in every rig response.

### Rigs are not reproducible, and cannot be made so

`demo.py` generates with `do_sample=True` and ships no seed. Adding one was tried
and measured — seeding `torch`/`numpy`/`random` at startup, again per-batch
immediately before generate, then additionally with
`torch.use_deterministic_algorithms(True, warn_only=True)`,
`CUBLAS_WORKSPACE_CONFIG=:4096:8` and cuDNN determinism. The same mesh at the same
seed still produced **47 vs 44 joints**.

Hashing the input batch across two runs gave identical digests, so the data
pipeline *is* deterministic — the divergence is inside the CUDA forward, where
`warn_only` leaves flash-attn's nondeterministic kernels in place (there is no
deterministic flash-attn), and autoregressive beam-sample amplifies float jitter
into a different token, which changes the whole skeleton.

Practical consequence: **rerolling is just re-running.** Generate 3–5 candidates
at `num_beams=3`, compare their `skeleton` reports, then re-run the winner's
settings at `num_beams=10`. You cannot recreate a specific good rig, so keep the
GLB — `metadata.json` marks this with `reproducible: false` rather than implying
its recorded parameters would reproduce the asset.

### Judge the skeleton first

The model generates the entire skeleton, *then* the skin tokens conditioned on it.
A bad skeleton poisons the skinning and no postprocessing recovers it. The
`skeleton` block gives `joints`, `roots`, `chain_tips`, `branch_points`,
`max_depth` and `symmetry` — check those before looking at deformation.

| Signal | Meaning |
|---|---|
| `symmetry` below 0.8 | Limbs that should mirror don't. `repetition_penalty` (2.0) may be suppressing the coordinate repeats mirrored limbs legitimately share — try 1.1–1.5 |
| `zero_weight_vertices` above 0 | Vertices that will never deform. Invisible in rest pose, a frozen spike under animation |
| `unweighted_bones` above 0 | Sequence truncation — `max_length=2048` caps at roughly 250 bones |

A known-good reference: the rigged succubus scores 43 joints, 1 root, 12 tips,
depth 7, symmetry 0.86, zero dead vertices.

### `use_postprocess` can only take away

It applies geodesic voxel binding as a **multiplicative** mask
(`asset.skin *= voxel_skin(...)`), so it can remove influence but never add it.
Use it when weights bleed across gaps — arm driving the ribcage, a cape picking up
leg weights — because weight transfer is Euclidean nearest-neighbour and jumps
across anatomical gaps. But on thin geometry it can strip a vertex entirely, which
is what `zero_weight_vertices` catches. Always compare a run with and without.

### Other levers

- **`temperature`**: lower (0.7–0.8) for conventional bipeds and quadrupeds. **Raise
  it** for novel creatures — the supervised model regresses to average solutions on
  out-of-distribution assets and drops auxiliary limbs, so a wingless dragon wants
  *higher* temperature, not lower.
- **`use_skeleton`** is the highest-quality path: rig once, fix the skeleton by hand
  in Blender, then re-skin against it. Skeleton errors propagate into skinning but
  not the reverse, and skinning is the part the model is genuinely good at.
- **`target_height_m` does not affect rig quality.** SkinTokens renormalizes, so
  scale is irrelevant to it — don't tune it hoping.
- **Vertex count**: the training mixture spans ~1.3k–17k vertices. Note the shape
  encoder samples a fixed number of surface points, so raw count matters less for
  the *skeleton* than for skin decode and transfer. If you decimate to a proxy,
  remember transfer to a *different* vertex count drops off exact Umeyama alignment
  onto a PCA fallback that can come back mirrored or rotated.
- **`group_per_vertex` stays at 4** and is not exposed: it's hardcoded in `demo.py`
  and the GRPO sparsity reward explicitly penalises more than 4 influences above
  0.1, so raising it works against the training objective.
- **Bone names are `bone_0..bone_N`**, not Mixamo or UE5. `demo.py` hardcodes the
  class as `"articulation"`, so the `configs/skeleton/` templates aren't wired into
  this path.

### This feeds back into your image prompt

A-pose with limbs clearly separated from the torso and fingers splayed is required
**by the rigging step**, not just by TRELLIS. Weight transfer is Euclidean
nearest-neighbour, so arms pinned to the ribcage bleed torso weights into the arms
and clenched fists cross-contaminate finger weights.

---

## Part segmentation (`segment_mesh`)

Labels every face of a mesh with a part id and writes a **sidecar**, never a new
mesh:

```
segment_mesh(mesh="succubus_1011.glb", seed=0)
```

You get `<stem>_face_labels.npy` (int32, one entry per face) and
`<stem>_parts.json` next to it, plus a part-coloured preview GLB for eyeballing.
Measured 45–85 s per asset on a 3090.

### It does not use SegviGen's own export, on purpose

SegviGen's `slat_to_glb` calls `o_voxel.postprocess.to_glb(..., remesh=True,
decimation_target=100000)`. That is a remeshed reconstruction, not your asset: an
11,200-vertex / 15,692-face character comes back as **71,053 / 97,052**, wearing
a baked copy of the part colours with the original UVs, texture and rig gone.

`scripts/segvigen_segment.py` stops before that step and reads the part signal
out of the voxel field instead. The voxels are a direct discretization of *your*
mesh on a 512³ grid (~2 mm on a 1 m asset), so each face centroid can be mapped
back into it and assigned the colour of its nearest occupied voxel. Measured
lookup distance is under 1.2 voxels worst-case. The source file is SHA-256'd
before and after and the run fails if it changed.

### Labels index `process=False`

```python
mesh = trimesh.load(src, force="mesh", process=False)   # process=False matters
labels = np.load("succubus_1011_face_labels.npy")       # len(labels) == len(mesh.faces)
```

The default `process=True` welds duplicate vertices and reorders faces, after
which the labels no longer line up.

### The partition is sampled, so re-roll rather than repair

`tex_slat_sample_single` draws its noise from the global RNG and upstream never
seeds it. The tool seeds it (`seed=0` by default) so a given mesh always returns
the same partition — but a *different* seed returns a genuinely different one.
The same character has come back as 2 parts on one seed and 7 on another, and one
test asset came back undivided at seed 0 (the response warns when `part_count < 2`).

Judge the preview and re-roll. Do not try to merge or split parts afterwards.

### Granularity is structural, not semantic

Parts come out as whole structural pieces. On a winged character: body / left
wing / right wing / tail, with the two wings landing at mirrored centroids and
within 3% of each other in face count. On an isolation suit: body versus both
arms. That suits prop stripping and per-part rigging.

**Garment-versus-body separation does not work.** Tested on `succubus_warden`, a
character in a full leather armour set (corset, pauldrons, thigh guards, plated
boots), across seeds 0–3: the splits are always structural — body / legs / wings /
horns / tail — and never follow the armour edge. Seed 0 found 2 parts, seed 1
found 11, seeds 2 and 3 found 4, and in none of them did a part correspond to a
garment. If you need clothing separated from skin, this is the wrong tool.

`color_rgb` in the report is the sampler's arbitrary label colour for a part. It
changes with the seed and means nothing across meshes; only the partition matters.

---

## GPU hot-swapping

TRELLIS and TokenRig each want most of a 24 GB card, so exactly one holds the GPU
at a time. Every GPU tool serializes on a single lock:

- **TRELLIS stays resident** between generations — a reload costs ~30 s, so
  repeated `generate_3d` calls are fast.
- **`rig_model`, `generate_orbit_views` and `segment_mesh` evict TRELLIS first**,
  then run in their own subprocess. That process's VRAM is reclaimed by the OS
  when it exits, so there is nothing to unload on the way back. `segment_mesh`
  peaks around 16.6 GB and refuses to start below 18 GB free.
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

**`generate_orbit_views` with `remove_bg=True` crashes.** BiRefNet comes back in
fp16 — newer `transformers` honours the checkpoint's declared `torch_dtype` — but
`inference_i2mv_sdxl.py:239` does `birefnet.to(device)` with no dtype cast, while
`remove_bg()` at line 76 still feeds it fp32 from `transforms.ToTensor()`. It dies
with `Input type (float) and bias type (c10::Half) should be the same`. Pass
`remove_bg=False` when the reference image already has a clean background; the
real fix is `.to(device, dtype=next(net.parameters()).dtype)` in the MV-Adapter
clone, which is not yet applied because that repo has no patch mechanism.

**`generate_orbit_views` wants more VRAM than its docs suggest.** Measured at
**18.1 GB** on a 768x1024 reference, not the ~14 GB the SDXL backbone uses at
768x768. The preflight was 15 GB, which let a run start with 19.6 GB free and then
die with CUDA OOM inside the multi-view attention block a minute in.
`MVADAPTER_VRAM_REQUIRED` is now 19 GB so it refuses up front instead. If another
service is holding the card (a 4.4 GB embedding server was, here), free it first.

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
