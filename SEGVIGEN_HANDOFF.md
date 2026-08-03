# SegviGen — handoff

**Status: environment ~95% built, blocked on one thing. Not yet wired into the MCP.**

Goal: add 3D part segmentation (`segment_mesh`) for garment/body separation,
prop stripping, and per-part rigging. SegviGen is MIT, SIGGRAPH 2026, and claims
+40% IoU@1 over P3-SAM. Background and the rejected alternatives (CubePart,
PartField, SAMPart3D) are in
`/mnt/codex_fs/game_assets/PART_SEGMENTATION_EVALUATION.md`.

---

## What is already proven on our assets

Do not re-test these; they cost hours.

- **The 512³ voxelizer accepts our meshes.** Generated assets are 269 disconnected
  non-watertight shells, which was the single biggest risk of disqualifying this
  whole approach. It worked.
- **bpy renders the conditioning image** in ~2 s (bpy 4.5.9; 5.x removed
  `cycles.filter_type` and breaks `bpy_render.py`).
- **The 4B model loads and runs 131 s** before reaching attention.
- **~16.6 GB VRAM** — the "24 GB minimum" in the README is boilerplate inherited
  from TRELLIS.2. It fits the 3090 comfortably.
- All weights downloaded: TRELLIS.2-4B, three SegviGen heads, RMBG-2.0, DINOv3.
  Your HF token already clears DINOv3's manual gate.

## The one blocker

`ATTN_BACKEND` must be `flash_attn` or `xformers`; there is no SDPA option in
`trellis2/modules/sparse/config.py`. Neither is obtainable prebuilt:

| torch | CUDA extensions build? | flash-attn cu13 wheel? |
|---|---|---|
| 2.9 | ❌ nvcc 13.3 rejects its headers | ✅ cp312 |
| 2.10 | ❌ same | ✅ cp312 / cp313 |
| 2.13 | ✅ | ❌ none exists |

`xformers` has **no cu13 build at any version** — the PyPI wheel installs but
reports "xFormers wasn't build with CUDA support".

Important detail: the torch-header failure is **nvcc-specific**. That same header
compiles cleanly under plain g++ on GCC 13 *and* 16; it only breaks through nvcc's
host pass. So no host-compiler choice fixes it — `CUDAHOSTCXX`, `-ccbin`, PATH
ordering and an nvcc shim were all tried and all fail. Do not repeat that.

### What is running right now

Building flash-attn **from source** in the py3.11 env (`.venv-prep`, torch 2.13,
which already has everything else). If it finishes, this collapses to a **single
environment** and the py3.12 idea is dead — delete `scripts/install_segvigen_infer.sh`.

```
supervisor: /tmp/.../scratchpad/fa_build_guarded.sh
logs:       /tmp/.../scratchpad/fa_supervisor.log , fa_guarded.log
```

It runs `MAX_JOBS=1`, `TORCH_CUDA_ARCH_LIST=8.6`, with a watchdog that kills the
build if available RAM drops under 5 GB. **This matters**: a previous attempt at
`MAX_JOBS=2` spawned three `cicc` processes at ~3.7 GB each and exhausted all
31 GB, triggering OOM kills. Never build flash-attn here unguarded.

Check it with:

```bash
tail -3 /tmp/.../scratchpad/fa_supervisor.log
/home/ladvien/segvigen/.venv-prep/bin/python -c "import flash_attn_2_cuda; print('OK')"
```

## If the build succeeds

1. Rename `.venv-prep` → `.venv`, fold the flash-attn build step into
   `scripts/install_segvigen.sh` (with the `MAX_JOBS=1` + watchdog rationale),
   delete `install_segvigen_infer.sh`, and update `SETUP.md` to four environments.
2. Run the smoke test — it does voxelize → render → inference end to end:
   ```bash
   /home/ladvien/segvigen/.venv/bin/python /tmp/.../scratchpad/segvigen_smoke.py
   ```
   Set `ATTN_BACKEND=flash_attn`. Free the GPU first via the MCP `free_gpu` tool.
3. **Judge the output before building anything on it.** The export is a *remeshed
   reconstruction*, not our mesh — confirmed in `inference_full.py`
   (`to_glb(vertices=mesh.vertices, …, remesh=True)`). The question is whether the
   part *colours* are good. If segmentation quality is poor on a dressed character,
   stop: nothing downstream is worth building.

## If the build fails

Then SegviGen cannot run on this box with the current upstream code. Options, in
order of sanity:

1. **Add an SDPA backend to trellis2** — implement `sparse_scaled_dot_product_attention`
   over `torch.nn.functional.scaled_dot_product_attention`, handling the varlen /
   `BlockDiagonalMask` case. This is the only path that needs no external kernel.
   Real work and correctness-critical, but bounded.
2. Wait for an `xformers` cu13 build or a flash-attn cu13 wheel matching torch 2.13.
3. Drop SegviGen. **SAMPart3D** (MIT, predicts mesh face labels, but trains an MLP
   per object) is the documented fallback.

Reporting "it does not work here" is a perfectly good outcome. The seed experiment
earlier in this project is the template: four configurations tested, negative
result recorded, feature not shipped.

## Then: Phase 2, the part that makes it useful

SegviGen's export throws our textured, rigged asset away. **Do not ship that.**
The opportunity is that the part signal is recoverable:

- `tex_voxels = tex_decoder(output_tex_slat)` carries part identity as
  `base_color` on voxels
- those voxels come from `mesh_to_flexible_dual_grid(vertices, faces,
  grid_size=512, aabb=[[-0.5]*3,[0.5]*3])` — a direct discretization of **our**
  mesh at ~2 mm on a 1 m asset

So: fork `inference_full.py` to stop **before** `slat_to_glb`, map each original
face centroid into the 512³ grid using their exact `center`/`scale` normalization,
read the voxel colour, and cluster colours into part ids. Emit `face_labels` and
leave geometry, UVs and texture untouched.

**Acceptance test:** output vertex count, face count and texture bytes must be
*identical* to the input. That is exactly what CubePart failed. Prove it.

## Then: Phase 3, the MCP tool

`segment_mesh` in `src/trellis2_mcp/server.py`, following the `rig_model` /
`generate_orbit_views` pattern: subprocess into the segvigen venv, `_evict_trellis()`
under `_gpu_lock`, VRAM preflight, `expandable_segments` in the subprocess env,
verify the output file rather than trusting the exit code, reuse `_mesh_diagnostics`
for the input report.

## Traps already paid for

All recorded in the install scripts' headers. Summary:

- **CUDA ≤ 12.4 is unusable**: glibc 2.43 declares `rsqrtf` in `math.h`, colliding
  with its math headers. Its installer also can't run (`libxml2.so.2`). Use
  `/opt/cuda` 13.3.
- **`bpy` has no cp310 wheel** anywhere, and `download.blender.org/pypi` 403s.
- **`spconv` is not needed** — sparse conv defaults to `CONV='flex_gemm'`.
- **`mathutils` won't install** (no cp311 wheel, source needs CPython 3.13's
  `PyLong_AsInt`). `bpy` bundles it.
- **`o_voxel` requires nvdiffrast** (`postprocess.py:10`), even though the
  segmentation path never rasterizes. This also drags in a non-commercial licence.
- **Pin torch AND torchvision together** or the resolver drags torch past its pin
  and everything dies on `operator torchvision::nms does not exist`.
- **`TRELLIS.2-4B` must be at a relative path** — `inference_full.py` opens
  `microsoft/TRELLIS.2-4B/pipeline.json`. The installer symlinks it.
- **`inference_full.py` is patched** to skip its internal render when `--img`
  already exists and to import bpy lazily. `--img` is the render's *output* path,
  not an input.
- `example_full_seg.py` is **training-data prep**, not an inference example.

## Repo state

`SETUP.md`, `scripts/install_segvigen.sh` and `scripts/install_segvigen_infer.sh`
are committed alongside this file. `SETUP.md` currently describes the two-env
layout; collapse it to one if the flash-attn build lands.
