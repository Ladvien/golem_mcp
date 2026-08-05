from __future__ import annotations

import base64
import gc
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Annotated, Any

import torch
from fastmcp import FastMCP
from PIL import Image
from pydantic import Field

TRELLIS_REPO = os.environ.get("TRELLIS_REPO", "/home/ladvien/trellis/repo")
TRELLIS_MODEL = os.environ.get("TRELLIS_MODEL", "/home/ladvien/trellis/models/TRELLIS-image-large")
OUTPUT_DIR = Path(os.environ.get("TRELLIS_OUTPUT_DIR", "/home/ladvien/trellis/output"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_OUTPUT_DIR = OUTPUT_DIR / "images"
IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RIG_OUTPUT_DIR = OUTPUT_DIR / "rigged"
RIG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# SkinTokens/TokenRig cannot share this interpreter: it needs Python 3.11 +
# torch 2.7.0+cu128 against TRELLIS's 3.10 + torch 2.6.0+cu124. It runs as a
# subprocess in its own venv; see scripts/install_skintokens.sh.
SKINTOKENS_REPO = Path(os.environ.get("SKINTOKENS_REPO", "/home/ladvien/skintokens/repo"))
SKINTOKENS_PYTHON = Path(os.environ.get("SKINTOKENS_PYTHON", "/home/ladvien/skintokens/.venv/bin/python"))
SKINTOKENS_CKPTS = (
    "experiments/skin_vae_2_10_32768/last.ckpt",
    "experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
)
RIG_INPUT_SUFFIXES = (".glb", ".obj", ".fbx")

# MV-Adapter generates 6 geometrically consistent views from one reference image,
# including true 90/270 degree profiles. Its own Python 3.11 venv, same reason as
# SkinTokens; see scripts/install_mvadapter.sh.
MVADAPTER_REPO = Path(os.environ.get("MVADAPTER_REPO", "/home/ladvien/mvadapter/repo"))
MVADAPTER_PYTHON = Path(os.environ.get("MVADAPTER_PYTHON", "/home/ladvien/mvadapter/.venv/bin/python"))
# Matches the inference script's default azimuths, in the order it emits them.
MVADAPTER_AZIMUTHS = (0, 45, 90, 180, 270, 315)
# Image-to-multiview peaks around 14 GB on the SDXL backbone at 768x768, but was
# measured at 18.1 GB on a 768x1024 reference. 15 GB let a run start with 19.6 GB
# free and then die with CUDA OOM inside the multi-view attention block, which is
# the worst outcome: a minute of GPU time spent to reach a failure the preflight
# exists to catch. Sized to the observed peak plus headroom.
MVADAPTER_VRAM_REQUIRED = 19e9

# SegviGen predicts 3D part segmentation on top of TRELLIS.2. Its own Python 3.11
# venv - see scripts/install_segvigen.sh, and SETUP.md for why the attention
# backend is SDPA. The driver script is ours, not upstream's: SegviGen's own
# export remeshes the asset away, so scripts/segvigen_segment.py stops before that
# and writes face labels instead.
SEGVIGEN_REPO = Path(os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo"))
SEGVIGEN_PYTHON = Path(os.environ.get("SEGVIGEN_PYTHON", "/home/ladvien/segvigen/.venv/bin/python"))
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
SEGVIGEN_DRIVER = _SCRIPTS / "segvigen_segment.py"
# Garment generation shares the SegviGen environment because that is where
# TRELLIS.2 lives - it was installed as SegviGen's backbone and became runnable
# once the SDPA attention backend landed. generate_3d still runs TRELLIS 1, which
# cannot represent an open surface and would seal a garment shut.
GARMENT_DRIVER = _SCRIPTS / "trellis2_garment.py"
CHARACTER_DRIVER = _SCRIPTS / "trellis2_character.py"
# Measured 14.47 GB peak for a pipeline_type=512 character on a 3090, against the
# 3.4 GB a garment costs - a character is remeshed and textured at 2048.
CHARACTER_VRAM_REQUIRED = 16e9
GARMENT_FIT_DRIVER = _SCRIPTS / "garment_fit.py"
# Measured 3.4 GB peak for TRELLIS.2 image-to-3D at pipeline_type=512, against the
# 24 GB its README asks for. Sized to the measurement with headroom.
GARMENT_VRAM_REQUIRED = 6e9
SEGVIGEN_OUTPUT_DIR = Path(os.environ.get("SEGVIGEN_OUTPUT_DIR", str(OUTPUT_DIR / "segmentation")))
# Measured at ~16.6 GB on a dressed character; the README's "24 GB" is boilerplate
# inherited from TRELLIS.2.
SEGVIGEN_VRAM_REQUIRED = 18e9

# Canonical rigging and animation. canonical_skeleton.py needs SkinTokens' Asset
# and BpyParser (it imports them from the repo root, hence the cwd) but runs on
# SegviGen's bpy 4.5.9; retarget_animation.py is pure bpy.
CANONICAL_DRIVER = _SCRIPTS / "canonical_skeleton.py"
ORIENT_DRIVER = _SCRIPTS / "orient_bones.py"
SMOOTH_DRIVER = _SCRIPTS / "smooth_weights.py"
RIG_PROXY_DRIVER = _SCRIPTS / "rig_proxy.py"
# TokenRig's training mixture is 1k-20k vertices and TRELLIS.2 ships ~90k, so the
# mesh that gets rigged and the mesh that gets shipped are no longer the same one.
# 8k rather than the 20k ceiling because memory does not scale with the mesh: the
# model load alone is a fixed ~9.5 GB, and the proxy only supplies landmarks and a
# weight field that gets resampled onto the full mesh anyway.
PROXY_VERTEX_TARGET = 8_000
RETARGET_DRIVER = _SCRIPTS / "retarget_animation.py"
ANIMATION_LIBRARY_DRIVER = _SCRIPTS / "animation_library.py"
ANIMATION_ROOTS = tuple(
    Path(p) for p in os.environ.get(
        "ANIMATION_ROOTS",
        "/mnt/codex_fs/game_assets/animation:/mnt/codex_fs/game_assets/SCP-610",
    ).split(":")
)
ANIMATION_CACHE = OUTPUT_DIR / "animation_cache.json"
ANIM_OUTPUT_DIR = OUTPUT_DIR / "animated"
ANIM_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Shared asset library on codex_fs (NFS export from 'three', autofs-mounted).
# Local OUTPUT_DIR stays the working area; these are the durable locations.
CODEX_GEN_AI_DIR = Path(os.environ.get("CODEX_GEN_AI_DIR", "/mnt/codex_fs/game_assets/models/gen_ai"))
CODEX_GENERATED_DIR = Path(os.environ.get("CODEX_GENERATED_DIR", "/mnt/codex_fs/game_assets/generated"))
ASSET_TYPES = ("characters", "props", "environments", "garments")

BMB_HOST = os.environ.get("BMB_HOST", "bmb")
BMB_MFLUX_PYTHON = os.environ.get("BMB_MFLUX_PYTHON", "~/mflux-venv/bin/python3")
BMB_MFLUX_OUTPUT = os.environ.get("BMB_MFLUX_OUTPUT", "~/mflux-output")

os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("ATTN_BACKEND", "xformers")

if TRELLIS_REPO not in sys.path:
    sys.path.insert(0, TRELLIS_REPO)

MFLUX_MODELS = [
    "flux2-klein-4b",
    "flux2-klein-9b",
    "flux2-klein-9b-kv",
    "flux2-klein-base-4b",
    "flux2-klein-base-9b",
    "dev",
    "schnell",
    "krea-dev",
    "dev-krea",
    "qwen",
    "fibo",
    "fibo-lite",
    "fibo-edit",
    "fibo-edit-rmbg",
    "z-image",
    "z-image-turbo",
    "ernie-image-turbo",
    "ernie-image",
    "ideogram4",
]

MFLUX_QUANTIZE_OPTIONS = [3, 4, 5, 6, 8]

# The distilled FLUX.2 klein models reject any --guidance other than 1.0
# ("--guidance is only supported for FLUX.2 base models"). Only the *-base-*
# variants take a real guidance scale.
FLUX2_DISTILLED_MODELS = frozenset(
    {
        "flux2-klein-4b",
        "flux2-klein-9b",
        "flux2-klein-9b-kv",
    }
)

mcp = FastMCP(
    "trellis2",
    instructions=(
        "Image -> 3D -> rigged-character pipeline. "
        "generate_image (FLUX via mflux on bmb) produces a reference image; "
        "generate_3d / generate_3d_multi_image turn images into a textured .glb via TRELLIS; "
        "rig_model adds a skeleton and skin weights via SkinTokens/TokenRig. "
        "TRELLIS and the rigger share one RTX 3090 and hot-swap automatically - "
        "calls serialize on the GPU, so run them one at a time. "
        "IMPORTANT: TRELLIS normalizes every asset into a unit cube, so output is ~1 m tall "
        "regardless of subject. Pass target_height_m, or scale downstream, before using any "
        "measurement in metres. Check geometry.dimensions_m in the response."
    ),
    version="0.4.0",
)

# --- GPU arbiter -----------------------------------------------------------
#
# One RTX 3090, two models that each want most of it. Exactly one holds the GPU
# at a time and every GPU tool serializes on _gpu_lock.
#
# TRELLIS is an in-process pipeline, so it stays resident between generations
# (a reload costs ~30s) and is evicted only when the rigger needs the card.
# TokenRig runs as a subprocess, so its VRAM is reclaimed when that process
# exits - nothing to evict on the way back.
_gpu_lock = threading.RLock()
_pipeline: Any = None


def _get_pipeline():
    """Load TRELLIS onto the GPU, or return the already-resident pipeline.

    Caller must hold _gpu_lock.
    """
    global _pipeline
    if _pipeline is None:
        from trellis.pipelines import TrellisImageTo3DPipeline

        _pipeline = TrellisImageTo3DPipeline.from_pretrained(TRELLIS_MODEL)
        _pipeline.cuda()
    return _pipeline


def _evict_trellis() -> bool:
    """Drop TRELLIS from VRAM. Returns True if it was resident.

    Caller must hold _gpu_lock.
    """
    global _pipeline
    if _pipeline is None:
        return False
    _pipeline.cpu()
    _pipeline = None
    gc.collect()
    torch.cuda.empty_cache()
    return True


def _vram() -> dict[str, float]:
    if not torch.cuda.is_available():
        return {}
    free, total = torch.cuda.mem_get_info(0)
    return {
        "vram_total_gb": round(total / 1e9, 1),
        "vram_free_gb": round(free / 1e9, 1),
        "vram_allocated_gb": round(torch.cuda.memory_allocated(0) / 1e9, 2),
        "vram_reserved_gb": round(torch.cuda.memory_reserved(0) / 1e9, 2),
    }


# --- codex_fs publishing ----------------------------------------------------


def _slugify(text: str, limit: int = 50) -> str:
    """Match the naming already used across models/ and game_assets/generated/."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:limit].rstrip("_") or "asset"


def _codex_available() -> None:
    """codex_fs is autofs-mounted; a stalled mount must fail loudly, not silently skip."""
    if not CODEX_GEN_AI_DIR.parent.parent.exists():
        raise RuntimeError(
            f"codex_fs is not mounted - {CODEX_GEN_AI_DIR} is unreachable. "
            "Check the NFS export from 'three' (192.168.1.103)."
        )


def _publish_reference_image(local_png: Path, prompt: str) -> str:
    """File a generated reference image under game_assets/generated/<slug>_<ts>/."""
    _codex_available()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = CODEX_GENERATED_DIR / f"{_slugify(prompt)}_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_png, dest / "reference.png")
    return str(dest)


def _publish_asset(
    files: dict[str, str],
    output_name: str,
    asset_type: str,
    metadata: dict[str, Any],
    reference_image: str,
) -> str:
    """Publish a generated asset bundle into the curated gen_ai tree.

    Refuses to overwrite: these directories are the curated library, and silently
    clobbering one would destroy a promoted asset and its provenance.
    """
    _codex_available()
    dest = CODEX_GEN_AI_DIR / asset_type / output_name
    if dest.exists():
        raise FileExistsError(
            f"{dest} already exists. Pick a different output_name, or remove that directory "
            "if you intend to replace the asset."
        )
    dest.mkdir(parents=True)

    if "glb" in files:
        shutil.copy2(files["glb"], dest / "asset.glb")
    if "ply" in files:
        shutil.copy2(files["ply"], dest / "asset.ply")
    if reference_image and os.path.isfile(reference_image):
        shutil.copy2(reference_image, dest / "reference.png")

    (dest / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return str(dest)


def _decode_image(source: str) -> Image.Image:
    if source.startswith("data:"):
        _header, b64 = source.split(",", 1)
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")
    if os.path.isfile(source):
        return Image.open(source).convert("RGBA")
    # Anything path-shaped that does not exist is a missing file, not base64.
    # Falling through would fail deep inside PIL with an unreadable message.
    if "/" in source or len(source) < 256:
        raise FileNotFoundError(f"Image file not found: {source}")
    return Image.open(io.BytesIO(base64.b64decode(source))).convert("RGBA")


# --- mesh + texture bake ----------------------------------------------------
#
# This inlines trellis.utils.postprocessing_utils.to_glb. Upstream hardcodes the
# two values that actually cap texture quality:
#
#     observations, ... = render_multiview(app_rep, resolution=1024, nviews=100)
#     texture = bake_texture(..., lambda_tv=0.01)
#
# so asking to_glb for a 2048 texture bakes it from 1024px observations - four
# times the file size carrying no additional real detail. Calling the same
# internals directly turns those into parameters.
#
# bake_texture's 'opt' mode moves EVERY view's observation, mask, uv and
# uv-derivative buffer onto the GPU at once and holds them for all 2500
# optimizer steps, so VRAM scales as nviews * resolution^2:
#     observation f32 3ch (12) + mask bool (1) + uv f32 2ch (8) + uv_dr f32 4ch (16)
_BAKE_BYTES_PER_PIXEL_PER_VIEW = 37
# Rasterization context, the texture itself, Adam state, and fragmentation.
_BAKE_VRAM_MARGIN = 1.5e9


def _bake_vram_estimate(render_resolution: int, nviews: int) -> float:
    return nviews * render_resolution * render_resolution * _BAKE_BYTES_PER_PIXEL_PER_VIEW


def _dims(extents) -> dict[str, float]:
    """Bounding-box extents as metres. Y is up (the mesh is rotated z-up -> y-up)."""
    return {
        "width": round(float(extents[0]), 4),
        "height": round(float(extents[1]), 4),
        "depth": round(float(extents[2]), 4),
    }


def _check_bake_params(texture_size: int, render_resolution: int, nviews: int) -> str | None:
    """Reject impossible bake settings up front. Returns an error message, or None."""
    if texture_size > render_resolution:
        return (
            f"texture_size={texture_size} exceeds render_resolution={render_resolution}. The texture is "
            f"baked from renders at render_resolution, so a larger texture only upsamples - bigger file, "
            f"no extra detail. Either lower texture_size to {render_resolution}, or raise render_resolution."
        )

    needed = _bake_vram_estimate(render_resolution, nviews) + _BAKE_VRAM_MARGIN
    _free, total = torch.cuda.mem_get_info(0)
    if needed > total * 0.85:
        max_views = int((total * 0.85 - _BAKE_VRAM_MARGIN) // (render_resolution**2 * _BAKE_BYTES_PER_PIXEL_PER_VIEW))
        return (
            f"Baking at {render_resolution}px x {nviews} views needs ~{needed / 1e9:.1f} GB VRAM, which "
            f"exceeds this GPU's {total / 1e9:.1f} GB under any conditions. At {render_resolution}px the "
            f"ceiling is about {max_views} views."
        )
    return None


def _preflight_bake_vram(render_resolution: int, nviews: int) -> None:
    """Refuse a bake that will not fit, before minutes of decimation and UV unwrap."""
    needed = _bake_vram_estimate(render_resolution, nviews) + _BAKE_VRAM_MARGIN
    free, _total = torch.cuda.mem_get_info(0)
    if needed <= free:
        return

    max_views = int((free - _BAKE_VRAM_MARGIN) // (render_resolution**2 * _BAKE_BYTES_PER_PIXEL_PER_VIEW))
    remedy = f"drop nviews to {max_views}" if max_views >= 1 else f"lower render_resolution below {render_resolution}"
    resident = (
        " TRELLIS is still resident; pass evict_trellis_for_bake=true to release it for the bake."
        if _pipeline is not None
        else ""
    )
    raise RuntimeError(
        f"Texture bake at {render_resolution}px x {nviews} views needs ~{needed / 1e9:.1f} GB VRAM but only "
        f"{free / 1e9:.1f} GB is free. Either {remedy}.{resident}"
    )


def _save_outputs(
    outputs: dict,
    stem: str,
    simplify: float,
    fill_holes: bool,
    fill_holes_max_size: float,
    texture_size: int,
    render_resolution: int,
    nviews: int,
    lambda_tv: float,
    target_height_m: float,
    evict_trellis_for_bake: bool,
) -> dict[str, Any]:
    import numpy as np
    import trimesh
    from trellis.utils.postprocessing_utils import bake_texture, parametrize_mesh, postprocess_mesh
    from trellis.utils.render_utils import render_multiview

    files: dict[str, str] = {}
    geometry: dict[str, Any] = {}

    if "gaussian" in outputs and "mesh" in outputs:
        app_rep = outputs["gaussian"][0]
        mesh = outputs["mesh"][0]

        # The pipeline weights play no part in baking - the gaussian and mesh are
        # standalone GPU tensors. Releasing TRELLIS here is what makes 2048px
        # baking reachable at all on a 24 GB card.
        if evict_trellis_for_bake:
            _evict_trellis()

        _preflight_bake_vram(render_resolution, nviews)

        vertices = mesh.vertices.cpu().numpy()
        faces = mesh.faces.cpu().numpy()

        vertices, faces = postprocess_mesh(
            vertices,
            faces,
            simplify=simplify > 0,
            simplify_ratio=simplify,
            fill_holes=fill_holes,
            fill_holes_max_hole_size=fill_holes_max_size,
            fill_holes_max_hole_nbe=int(250 * np.sqrt(1 - simplify)),
            fill_holes_resolution=1024,
            fill_holes_num_views=1000,
            debug=False,
            verbose=False,
        )
        vertices, faces, uvs = parametrize_mesh(vertices, faces)

        observations, extrinsics, intrinsics = render_multiview(
            app_rep, resolution=render_resolution, nviews=nviews
        )
        masks = [np.any(observation > 0, axis=-1) for observation in observations]
        extrinsics = [extrinsics[i].cpu().numpy() for i in range(len(extrinsics))]
        intrinsics = [intrinsics[i].cpu().numpy() for i in range(len(intrinsics))]

        texture = bake_texture(
            vertices,
            faces,
            uvs,
            observations,
            masks,
            extrinsics,
            intrinsics,
            texture_size=texture_size,
            mode="opt",
            lambda_tv=lambda_tv,
            verbose=False,
        )

        # Baking allocates enormous transient buffers (15.5 GB at 2048x100). Once
        # bake_texture returns they are free but still held by torch's caching
        # allocator, so the process keeps squatting on them between calls and
        # starves every other process on the GPU. Hand them back to the driver.
        gc.collect()
        torch.cuda.empty_cache()

        # z-up -> y-up, so height is the Y extent from here on.
        vertices = vertices @ np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])
        material = trimesh.visual.material.PBRMaterial(
            roughnessFactor=1.0,
            baseColorTexture=Image.fromarray(texture),
            baseColorFactor=np.array([255, 255, 255, 255], dtype=np.uint8),
        )
        glb = trimesh.Trimesh(vertices, faces, visual=trimesh.visual.TextureVisuals(uv=uvs, material=material))

        extents = glb.bounds[1] - glb.bounds[0]
        geometry["normalized_dimensions_m"] = _dims(extents)

        if target_height_m > 0:
            factor = target_height_m / float(extents[1])
            glb.apply_scale(factor)
            extents = glb.bounds[1] - glb.bounds[0]
            geometry["scale_factor_applied"] = round(factor, 4)

        geometry["dimensions_m"] = _dims(extents)
        geometry["triangles"] = int(len(glb.faces))
        geometry["scale_note"] = (
            "TRELLIS normalizes every asset into a unit cube, so height is ~1 m regardless of subject. "
            "Pass target_height_m to scale at export, or scale downstream before using any metric measurement."
        )

        glb_path = OUTPUT_DIR / f"{stem}.glb"
        glb.export(str(glb_path))
        files["glb"] = str(glb_path)

    if "gaussian" in outputs:
        ply_path = OUTPUT_DIR / f"{stem}.ply"
        outputs["gaussian"][0].save_ply(str(ply_path))
        files["ply"] = str(ply_path)
        if target_height_m > 0:
            geometry["ply_note"] = "The .ply Gaussian splat is exported at TRELLIS's normalized scale, unscaled."

    return {"files": files, "geometry": geometry}


@mcp.tool
def generate_3d(
    image: Annotated[
        str,
        Field(description="Path to input image, base64-encoded data, or data: URL. PNG with transparency recommended."),
    ],
    seed: Annotated[int, Field(description="Random seed for reproducibility", ge=0)] = 0,
    output_name: Annotated[str, Field(description="Base name for output files (without extension)")] = "",
    pipeline_type: Annotated[
        str,
        Field(description="Quality tier. '512' is the measured default; the cascades cost far more VRAM"),
    ] = "512",
    simplify_target: Annotated[
        int,
        Field(description="Face budget before texture baking. The raw mesh is ~870k faces", ge=10_000, le=2_000_000),
    ] = 300_000,
    decimation_target: Annotated[
        int,
        Field(description="Final shipped face budget", ge=2_000, le=1_000_000),
    ] = 100_000,
    texture_size: Annotated[int, Field(description="Texture resolution in pixels", ge=512, le=4096)] = 2048,
    asset_type: Annotated[
        str,
        Field(description="Which gen_ai folder to publish into: characters, props, or environments"),
    ] = "characters",
    source_prompt: Annotated[
        str,
        Field(description="Prompt that produced the reference image, recorded in metadata"),
    ] = "",
    source_image_model: Annotated[
        str, Field(description="Image model that produced the reference (e.g. flux2-klein-9b)")
    ] = "",
    timeout: Annotated[int, Field(description="Hard limit in seconds", ge=60, le=7200)] = 1800,
) -> dict[str, Any]:
    """Generate a textured, PBR 3D asset from a single image using TRELLIS.2.

    Emits base colour AND metallic-roughness as separate 2048px maps, so materials
    respond to lighting: brass reads as metal rather than as painted cloth.

    Measured against the TRELLIS 1 path this replaces, on the same input image:

        shipped triangles        5,716  ->  97,249
        textures              1x 1024   ->  2x 2048
        metallicRoughness         none  ->  present
        base colour spread       51.4x  ->  10.7x, median luminance 34 -> 140

    That last line is the substantive one. TRELLIS 1's base colour was not albedo,
    it was a photograph of a lit object with the shading painted in, so nothing
    downstream could relight it.

    ~75 s and ~15 GB peak VRAM on an RTX 3090. Output is normalised into a unit
    cube (~1 m tall whatever the subject), so scale before relying on any metric
    measurement.
    """
    try:
        if asset_type not in ASSET_TYPES:
            return {
                "success": False,
                "error": f"asset_type must be one of {', '.join(ASSET_TYPES)}, got '{asset_type}'",
            }
        _garment_preflight()   # same TRELLIS.2 install, same checks

        img = _decode_image(image)
        if not output_name:
            output_name = f"trellis_{int(time.time())}"

        source_png = OUTPUT_DIR / "images" / f"{output_name}_source.png"
        source_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(source_png)

        started = time.time()
        with _gpu_lock:
            # TRELLIS 1 may still be resident from generate_3d_multi_image, which
            # has not been migrated: TRELLIS.2's run() takes a single image, though
            # its get_cond() already accepts a list.
            evicted = _evict_trellis()
            gc.collect()
            torch.cuda.empty_cache()
            free, _total = torch.cuda.mem_get_info(0)
            if free < CHARACTER_VRAM_REQUIRED:
                raise RuntimeError(
                    f"TRELLIS.2 needs ~{CHARACTER_VRAM_REQUIRED / 1e9:.0f} GB VRAM but only "
                    f"{free / 1e9:.1f} GB is free, even after evicting TRELLIS. Something else "
                    "is holding the GPU."
                )
            _run_script(
                SEGVIGEN_PYTHON, CHARACTER_DRIVER,
                [
                    "--image", str(source_png),
                    "--out-dir", str(OUTPUT_DIR),
                    "--name", output_name,
                    "--seed", str(seed),
                    "--pipeline-type", pipeline_type,
                    "--simplify-target", str(simplify_target),
                    "--decimation-target", str(decimation_target),
                    "--texture-size", str(texture_size),
                ],
                timeout, "CHARACTER_OK", "TRELLIS.2 character generation",
            )
        elapsed = round(time.time() - started, 1)

        glb = OUTPUT_DIR / f"{output_name}.glb"
        report_path = OUTPUT_DIR / f"{output_name}_character.json"
        if not glb.is_file() or glb.stat().st_size == 0:
            raise RuntimeError(f"TRELLIS.2 reported success but wrote nothing to {glb}")
        report = json.loads(report_path.read_text())

        metadata = {
            "original_prompt": source_prompt or None,
            "tool": "TRELLIS.2",
            "trellis_model": "microsoft/TRELLIS.2-4B",
            "image_model": source_image_model or None,
            "asset_type": asset_type,
            "seed": seed,
            "rigged": False,
            "rig_tool": None,
            "pbr": True,
            "generation": {
                "pipeline_type": pipeline_type,
                "simplify_target": simplify_target,
                "decimation_target": decimation_target,
                "texture_size": texture_size,
                "faces_before_simplify": report["faces_before_simplify"],
                "peak_vram_gb": report["peak_vram_gb"],
                "elapsed_seconds": elapsed,
            },
            "topology": report["topology"],
            "materials": report["materials"],
        }
        published = _publish_asset(
            {"asset.glb": str(glb)}, output_name, asset_type, metadata, str(source_png),
        )

        welded = report["topology"]["position_welded"]
        return {
            "success": True,
            "output_name": output_name,
            "glb": str(glb),
            "published_to": published,
            "reference_image": str(source_png),
            "size_bytes": glb.stat().st_size,
            "elapsed_seconds": elapsed,
            "trellis_evicted": evicted,
            "faces": report["topology"]["as_shipped"]["faces"],
            "materials": report["materials"],
            "topology": report["topology"],
            "topology_note": (
                "Components and boundary edges are reported BOTH as-shipped and "
                "position-welded. The as-shipped numbers describe the UV atlas, not the "
                f"surface: this mesh welds to {welded['components']} closed shells with "
                f"{welded['boundary_edge_pct']}% boundary edges. Judge topology on the "
                "welded figures - a vertex-distance weld cannot see the difference at any "
                "tolerance, which is what wrongly condemned TRELLIS.2 once already."
            ),
            "next_step": f"rig_model(mesh='{output_name}.glb') to add a skeleton and skin weights",
            "parameters": {
                "seed": seed,
                "pipeline_type": pipeline_type,
                "simplify_target": simplify_target,
                "decimation_target": decimation_target,
                "texture_size": texture_size,
            },
        }

    except Exception as e:
        with _gpu_lock:
            _evict_trellis()
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }

@mcp.tool
def generate_3d_multi_image(
    images: Annotated[
        str,
        Field(
            description=(
                "JSON array of image paths or base64 strings, "
                "e.g. '[\"/path/a.png\",\"/path/b.png\"]'. Multi-view images of the same object."
            )
        ),
    ],
    seed: Annotated[int, Field(description="Random seed for reproducibility", ge=0)] = 42,
    output_name: Annotated[str, Field(description="Base name for output files (without extension)")] = "",
    mode: Annotated[
        str,
        Field(
            description=(
                "Multi-image conditioning mode: "
                "'stochastic' (cycles through images) or 'multidiffusion' (averages predictions)"
            )
        ),
    ] = "stochastic",
    ss_steps: Annotated[int, Field(description="Sparse structure sampler steps", ge=1, le=100)] = 12,
    ss_cfg_strength: Annotated[float, Field(description="Sparse structure CFG strength", ge=1.0, le=20.0)] = 7.5,
    slat_steps: Annotated[int, Field(description="SLAT sampler steps", ge=1, le=100)] = 12,
    slat_cfg_strength: Annotated[float, Field(description="SLAT CFG strength", ge=1.0, le=20.0)] = 3.0,
    simplify: Annotated[float, Field(description="Mesh simplification ratio", ge=0.0, le=1.0)] = 0.95,
    fill_holes: Annotated[bool, Field(description="Fill holes in the generated mesh")] = True,
    fill_holes_max_size: Annotated[float, Field(description="Maximum hole area to fill", ge=0.0, le=1.0)] = 0.04,
    texture_size: Annotated[int, Field(description="Output texture resolution in pixels", ge=256, le=4096)] = 1024,
    render_resolution: Annotated[
        int,
        Field(
            description=(
                "Resolution of the renders the texture is baked FROM - the real detail ceiling. "
                "texture_size above this only upsamples. 2048 needs evict_trellis_for_bake=true."
            ),
            ge=256,
            le=2048,
        ),
    ] = 1024,
    nviews: Annotated[
        int,
        Field(description="Number of views baked from. More means better hidden-area coverage.", ge=8, le=300),
    ] = 100,
    lambda_tv: Annotated[
        float,
        Field(description="Total-variation smoothing on the texture. Lower is sharper.", ge=0.0, le=0.1),
    ] = 0.01,
    target_height_m: Annotated[
        float,
        Field(
            description=(
                "Scale the exported mesh to this height in metres. 0 leaves TRELLIS's normalized "
                "unit-cube scale, which is ~1 m regardless of subject."
            ),
            ge=0.0,
            le=1000.0,
        ),
    ] = 0.0,
    evict_trellis_for_bake: Annotated[
        bool,
        Field(description="Release TRELLIS from VRAM before baking. Required for render_resolution=2048."),
    ] = False,
    asset_type: Annotated[
        str,
        Field(description="Which gen_ai folder to publish into: characters, props, or environments"),
    ] = "characters",
    source_prompt: Annotated[
        str,
        Field(description="Prompt the reference images came from. Recorded in metadata.json as provenance."),
    ] = "",
    source_image_model: Annotated[
        str, Field(description="Image model that produced the references (e.g. flux2-klein-9b)")
    ] = "",
    preprocess_image: Annotated[bool, Field(description="Auto-remove background and crop each image")] = True,
    formats: Annotated[
        str,
        Field(description="Output formats: mesh,gaussian,radiance_field"),
    ] = "mesh,gaussian",
) -> dict[str, Any]:
    """Generate a 3D asset from multiple images (multi-view conditioning).

    Provide 2-6 images of the same object from different angles for best results.
    This is the biggest structural quality lever: from a single image the entire
    unseen side is hallucinated.

    Output is normalized into a unit cube (~1 m tall whatever the subject). Use
    target_height_m, or scale downstream, before relying on any metric measurement.
    """
    try:
        invalid = _check_bake_params(texture_size, render_resolution, nviews)
        if invalid:
            return {"success": False, "error": invalid}
        if asset_type not in ASSET_TYPES:
            return {
                "success": False,
                "error": f"asset_type must be one of {', '.join(ASSET_TYPES)}, got '{asset_type}'",
            }

        image_paths: list[str] = json.loads(images)
        pil_images = [_decode_image(p) for p in image_paths]

        if not output_name:
            output_name = f"trellis_multi_{int(time.time())}"

        started = time.time()

        format_list = [f.strip() for f in formats.split(",") if f.strip()]

        with _gpu_lock:
            pipeline = _get_pipeline()
            outputs = pipeline.run_multi_image(
                pil_images,
                seed=seed,
                mode=mode,
                sparse_structure_sampler_params={
                    "steps": ss_steps,
                    "cfg_strength": ss_cfg_strength,
                },
                slat_sampler_params={
                    "steps": slat_steps,
                    "cfg_strength": slat_cfg_strength,
                },
                formats=format_list,
                preprocess_image=preprocess_image,
            )

            saved = _save_outputs(
                outputs,
                output_name,
                simplify=simplify,
                fill_holes=fill_holes,
                fill_holes_max_size=fill_holes_max_size,
                texture_size=texture_size,
                render_resolution=render_resolution,
                nviews=nviews,
                lambda_tv=lambda_tv,
                target_height_m=target_height_m,
                evict_trellis_for_bake=evict_trellis_for_bake,
            )

        metadata = {
            "original_prompt": source_prompt or None,
            "tool": "TRELLIS",
            "trellis_model": os.path.basename(TRELLIS_MODEL),
            "image_model": source_image_model or None,
            "asset_type": asset_type,
            "seed": seed,
            "rigged": False,
            "rig_tool": None,
            "conditioning": {"mode": "multi_image", "num_images": len(pil_images), "blend_mode": mode},
            "source_images": image_paths,
            "generation": {
                "ss_steps": ss_steps,
                "ss_cfg_strength": ss_cfg_strength,
                "slat_steps": slat_steps,
                "slat_cfg_strength": slat_cfg_strength,
                "simplify": simplify,
                "texture_size": texture_size,
                "render_resolution": render_resolution,
                "nviews": nviews,
                "lambda_tv": lambda_tv,
                "target_height_m": target_height_m,
            },
            "geometry": saved["geometry"],
            "elapsed_seconds": round(time.time() - started, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if not source_prompt:
            metadata["_provenance_warning"] = (
                "No source_prompt was supplied, so how this asset was made cannot be reconstructed. "
                "Pass source_prompt and source_image_model to generate_3d_multi_image."
            )

        published = _publish_asset(
            saved["files"], output_name, asset_type, metadata,
            image_paths[0] if image_paths and os.path.isfile(image_paths[0]) else "",
        )

        return {
            "success": True,
            "output_name": output_name,
            "files": saved["files"],
            "published_to": published,
            "geometry": saved["geometry"],
            "num_images": len(pil_images),
            "mode": mode,
            "next_step": f"rig_model(mesh='{output_name}.glb') to add a skeleton and skin weights",
            "parameters": {
                "seed": seed,
                "ss_steps": ss_steps,
                "ss_cfg_strength": ss_cfg_strength,
                "slat_steps": slat_steps,
                "slat_cfg_strength": slat_cfg_strength,
                "simplify": simplify,
                "texture_size": texture_size,
            },
        }

    except Exception as e:
        with _gpu_lock:
            _evict_trellis()
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


# --- rigging (SkinTokens / TokenRig) ---------------------------------------


def _read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    """Return a GLB's JSON chunk and its binary chunk."""
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{path} is not a GLB")
    offset = 12
    gltf: dict[str, Any] | None = None
    binary = b""
    while offset < len(data):
        length, ctype = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif ctype == 0x004E4942:
            binary = chunk
        offset += 8 + length + (-length % 4)
    if gltf is None:
        raise ValueError(f"{path} has no JSON chunk")
    return gltf, binary


_GLTF_COMPONENTS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_GLTF_COMPONENT_SIZES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
_GLTF_TYPE_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _read_accessor(gltf: dict[str, Any], binary: bytes, index: int) -> list[tuple[float, ...]]:
    """Decode a glTF accessor into tuples, honouring normalized integer forms."""
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    ncomp = _GLTF_TYPE_COUNTS[acc["type"]]
    fmt = _GLTF_COMPONENTS[acc["componentType"]]
    size = _GLTF_COMPONENT_SIZES[acc["componentType"]] * ncomp
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride") or size

    scale = 1.0
    if acc.get("normalized"):
        scale = {5121: 255.0, 5123: 65535.0, 5120: 127.0, 5122: 32767.0}.get(acc["componentType"], 1.0)

    out = []
    for i in range(acc["count"]):
        vals = struct.unpack_from("<" + fmt * ncomp, binary, start + i * stride)
        out.append(tuple(v / scale for v in vals) if scale != 1.0 else tuple(float(v) for v in vals))
    return out


def _skeleton_report(path: Path) -> dict[str, Any]:
    """Structure and skin-weight health of a rigged GLB.

    Judge the skeleton before the weights: TokenRig generates the whole skeleton
    first and conditions the skin tokens on it, so a bad skeleton poisons the
    skinning and no amount of postprocessing recovers it.
    """
    gltf, binary = _read_glb(path)
    skins = gltf.get("skins", [])
    if not skins:
        return {"joints": 0, "warnings": ["Output has no skin - rigging produced no skeleton."]}

    nodes = gltf["nodes"]
    joints = skins[0]["joints"]
    jset = set(joints)

    parent = {}
    for i, node in enumerate(nodes):
        for child in node.get("children", []):
            parent[child] = i
    kids = {j: [c for c in nodes[j].get("children", []) if c in jset] for j in joints}
    roots = [j for j in joints if parent.get(j) not in jset]

    def depth(j, d=0):
        return d if not kids[j] else max(depth(c, d + 1) for c in kids[j])

    # Mirror symmetry across X. Asymmetric limbs are the documented signature of
    # repetition_penalty set too high - bone coordinates legitimately repeat
    # between mirrored limbs, and the penalty suppresses exactly that.
    trs = {j: nodes[j].get("translation", [0.0, 0.0, 0.0]) for j in joints}
    spread = max((abs(t[0]) for t in trs.values()), default=0.0)
    tol = max(spread * 0.05, 1e-4)
    matched = 0
    for t in trs.values():
        if abs(t[0]) <= tol:
            matched += 1  # on the midline, self-symmetric
            continue
        if any(
            abs(o[0] + t[0]) <= tol and abs(o[1] - t[1]) <= tol and abs(o[2] - t[2]) <= tol
            for o in trs.values()
        ):
            matched += 1
    symmetry = round(matched / len(joints), 3) if joints else 0.0

    report: dict[str, Any] = {
        "joints": len(joints),
        "roots": len(roots),
        "chain_tips": sum(1 for j in joints if not kids[j]),
        "branch_points": sum(1 for j in joints if len(kids[j]) > 1),
        "max_depth": max((depth(r) for r in roots), default=0),
        "symmetry": symmetry,
    }

    warnings: list[str] = []
    prim = gltf["meshes"][0]["primitives"][0]
    attrs = prim.get("attributes", {})
    if "WEIGHTS_0" in attrs and "JOINTS_0" in attrs:
        weights = _read_accessor(gltf, binary, attrs["WEIGHTS_0"])
        joint_idx = _read_accessor(gltf, binary, attrs["JOINTS_0"])
        dead = sum(1 for w in weights if sum(w) < 1e-6)
        influenced = {int(j) for jl, wl in zip(joint_idx, weights) for j, w in zip(jl, wl) if w > 1e-6}
        unweighted = len(joints) - len(influenced)
        report["zero_weight_vertices"] = dead
        report["unweighted_bones"] = unweighted
        if dead:
            warnings.append(
                f"{dead} vertices have zero total weight and will not deform. use_postprocess "
                "applies geodesic voxel binding as a MULTIPLICATIVE mask, so it can only remove "
                "influence - on thin geometry it can strip a vertex entirely. Compare against a "
                "run without it."
            )
        if unweighted > 0:
            warnings.append(
                f"{unweighted} bones carry no skin weight. TokenRig's sequence is capped at "
                "max_length=2048, roughly 250 bones, and truncation leaves trailing bones "
                "unskinned."
            )
    if symmetry < 0.8:
        warnings.append(
            f"Skeleton symmetry is {symmetry}. If limbs that should mirror do not, "
            "repetition_penalty (default 2.0) may be suppressing the coordinate repeats that "
            "mirrored limbs legitimately share - try 1.1-1.5."
        )

    report["warnings"] = warnings
    return report


def _publish_rig(
    source: Path,
    rigged: Path,
    elapsed: float,
    num_beams: int,
    use_transfer: bool,
    use_postprocess: bool,
    mesh_diagnostics: dict[str, Any],
    skeleton: dict[str, Any],
    fit_report: dict[str, Any],
    canonical: dict[str, Any],
) -> str | None:
    """Add the rigged mesh to its published asset directory and mark it rigged.

    Matched by the source mesh's stem against the gen_ai tree, which is where
    generate_3d publishes. A mesh rigged from somewhere else has no asset
    directory to update, and simply reports None.
    """
    for asset_type in ASSET_TYPES:
        asset_dir = CODEX_GEN_AI_DIR / asset_type / source.stem
        meta_path = asset_dir / "metadata.json"
        if not meta_path.is_file():
            continue

        shutil.copy2(rigged, asset_dir / "asset_rigged.glb")
        metadata = json.loads(meta_path.read_text())
        metadata["rigged"] = True
        metadata["rig_tool"] = "SkinTokens/TokenRig"
        metadata["rig"] = {
            "checkpoint": SKINTOKENS_CKPTS[1],
            "skeleton_convention": "mixamo-canonical",
            "num_beams": num_beams,
            "use_transfer": use_transfer,
            "use_postprocess": use_postprocess,
            "elapsed_seconds": elapsed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "bone_naming": (
                "Mixamo (mixamorig:*) 23-bone core plus four tip bones "
                "(LeftHand_End, RightHand_End, LeftToe_End, RightToe_End), plus named "
                "wing_/tail_/horn_ chains for whatever else the mesh has. Identical "
                "across every character, which is what makes clips shareable."
            ),
            "skeleton_reproducible": True,
            "skinning_reproducible": False,
            "_reproducibility_note": (
                "The skeleton is fitted deterministically and is the same for every asset. "
                "Skin weights still come from TokenRig, which generates with do_sample=True "
                "and exposes no seed, so re-running gives different weights on the same bones."
            ),
            "input_mesh": mesh_diagnostics,
            "skeleton": skeleton,
            "canonical": canonical,
            "canonical_fit": fit_report.get("from_generated", {}),
        }
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
        return str(asset_dir)
    return None


# TokenRig quantizes joint coordinates into this many bins across the mesh's
# largest bounding-box dimension (checkpoint articulation_xl_quantization_256_...,
# and src/data/augment.py defaults discrete=256). Asset.normalize_vertices divides
# by (v_max - v_min).max(), so the scale is uniform: anything that widens the
# bounding box without adding riggable geometry costs precision on ALL THREE axes.
_JOINT_QUANTIZATION_BINS = 256
# The training mixture averages ~1.3k (ModelsResource) to ~17k (VRoid) vertices.
_VERT_RANGE = (1_000, 20_000)


def _mesh_diagnostics(path: Path) -> dict[str, Any]:
    """Inspect a mesh for the conditions that determine rig quality.

    Advisory, never blocking - an off-distribution mesh still rigs usefully. The
    point is that these conditions are otherwise invisible until the rig is bad.
    """
    import numpy as np
    import trimesh

    # process=True welds duplicate vertices. Exported GLBs split vertices at UV and
    # normal seams, so without welding every seam looks like a topological break and
    # connectivity, watertightness and component counts are all meaningless.
    mesh = trimesh.load(str(path), force="mesh", process=True)
    verts_arr = np.asarray(mesh.vertices)
    extents = mesh.bounds[1] - mesh.bounds[0]
    largest = float(extents.max())

    components = mesh.split(only_watertight=False)

    # Measure bbox inflation against the bulk of the geometry rather than the
    # largest connected component: generated meshes routinely come in many pieces,
    # so "biggest component" is not the body. A prop, base or stray fragment is a
    # small number of vertices sitting far out, which is exactly what comparing the
    # full extent to the 1st-99th percentile extent detects.
    core = np.percentile(verts_arr, 99, axis=0) - np.percentile(verts_arr, 1, axis=0)
    core_largest = float(core.max())
    inflation = round(largest / core_largest, 3) if core_largest > 0 else 1.0

    warnings: list[str] = []
    if inflation > 1.25:
        warnings.append(
            f"Bounding box is {inflation}x the extent of the bulk of the geometry, so a prop, base "
            f"or stray fragment is widening it. Joint coordinates are quantized across the LARGEST "
            f"dimension, so this costs precision on all three axes, not just that one. Rig the body "
            f"alone and reattach afterwards."
        )
    verts = int(len(mesh.vertices))
    if verts > _VERT_RANGE[1]:
        warnings.append(
            f"{verts} vertices is above the ~{_VERT_RANGE[1]} top of the training mixture. "
            "Raise simplify on generate_3d, or rig a decimated copy - but note that transferring "
            "to a different vertex count drops off the exact Umeyama alignment onto a PCA "
            "fallback that can come back mirrored or rotated."
        )
    elif verts < _VERT_RANGE[0]:
        warnings.append(f"{verts} vertices is below the ~{_VERT_RANGE[0]} floor of the training mixture.")
    if not bool(mesh.is_watertight):
        warnings.append(
            "Mesh is not watertight. Two of the four GRPO reward functions were computed over a "
            "196^3 voxelization, so open shells and flipped normals push the model off the "
            "distribution it was tuned against."
        )
    # Reported, deliberately NOT warned on. Measured across four real assets: every
    # one is 119-302 shells with the largest holding only 2.7-13.6% of vertices, so
    # a generated body is simply not one connected piece. A warning that fires every
    # single time teaches the reader to ignore the warnings list.
    substantial = sum(1 for c in components if len(c.vertices) >= 0.02 * max(verts, 1))

    return {
        "vertices": verts,
        "triangles": int(len(mesh.faces)),
        "components": int(len(components)),
        "substantial_components": substantial,
        "is_watertight": bool(mesh.is_watertight),
        "bbox_largest_dim_m": round(largest, 4),
        "bbox_inflation": inflation,
        "joint_resolution_mm": round(largest / _JOINT_QUANTIZATION_BINS * 1000, 2),
        "warnings": warnings,
    }


def _glb_dimensions(path: Path) -> dict[str, Any]:
    """Bounding box of an exported GLB, so scale stays visible after rigging.

    use_transfer preserves the source scale, so a rigged asset inherits whatever
    scale generate_3d produced - including TRELLIS's ~1 m unit-cube default.
    """
    import trimesh

    scene = trimesh.load(str(path), force="scene")
    extents = scene.bounds[1] - scene.bounds[0]
    return {"dimensions_m": _dims(extents)}


def _rig_preflight() -> None:
    """Raise with actionable detail if the SkinTokens install is incomplete."""
    missing: list[str] = []
    if not SKINTOKENS_PYTHON.is_file():
        missing.append(f"interpreter {SKINTOKENS_PYTHON}")
    if not (SKINTOKENS_REPO / "demo.py").is_file():
        missing.append(str(SKINTOKENS_REPO / "demo.py"))
    for ckpt in SKINTOKENS_CKPTS:
        path = SKINTOKENS_REPO / ckpt
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(str(path))
    if missing:
        raise RuntimeError(
            "SkinTokens install is incomplete. Missing: "
            + "; ".join(missing)
            + ". Run scripts/install_skintokens.sh to install it."
        )


def _rig_env() -> dict[str, str]:
    """Environment for the rigger subprocess.

    demo.py talks to its bpy_server child over loopback HTTP. A configured
    http_proxy intercepts that request and the run hangs forever at the progress
    bar (upstream issue #3), so the proxy vars are stripped outright.
    """
    env = dict(os.environ)
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        env.pop(var, None)
    env["NO_PROXY"] = "localhost,127.0.0.1"
    return env


def _canonical_preflight() -> None:
    """Raise if the canonical-rigging drivers or their interpreter are missing."""
    missing = [
        str(p) for p in (SEGVIGEN_PYTHON, CANONICAL_DRIVER, RETARGET_DRIVER)
        if not p.is_file()
    ]
    if missing:
        raise RuntimeError(
            "Canonical rigging is unavailable. Missing: " + "; ".join(missing)
            + ". The drivers ship with this repo; the interpreter comes from "
            "scripts/install_segvigen.sh."
        )


def _run_script(
    python: Path, script: Path, argv: list[str], timeout: int, marker: str, label: str,
) -> str:
    """Run a driver script and verify it printed its success marker.

    Exit codes are not trusted here for the same reason they are not trusted for
    demo.py: a driver can fail after writing partial output and still exit 0. The
    marker is printed as the last act of a successful run.
    """
    proc = subprocess.run(
        [str(python), str(script), *argv],
        cwd=str(SKINTOKENS_REPO), env=_rig_env(),
        capture_output=True, text=True, timeout=timeout,
    )
    if marker not in proc.stdout:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-30:])
        raise RuntimeError(f"{label} failed (exit {proc.returncode}). Output:\n{tail}")
    return proc.stdout


def _demo_pass(
    source: Path, target: Path, use_skeleton: bool, label: str, params: dict[str, Any], timeout: int,
) -> float:
    """One TokenRig pass. Returns elapsed seconds; raises with the log tail on failure."""
    cmd = [
        str(SKINTOKENS_PYTHON), "demo.py",
        "--input", str(source), "--output", str(target),
        "--num_beams", str(params["num_beams"]),
        "--top_k", str(params["top_k"]),
        "--top_p", str(params["top_p"]),
        "--temperature", str(params["temperature"]),
        "--repetition_penalty", str(params["repetition_penalty"]),
    ]
    if params["use_transfer"]:
        cmd.append("--use_transfer")
    if params["use_postprocess"]:
        cmd.append("--use_postprocess")
    if use_skeleton:
        cmd.append("--use_skeleton")

    started = time.time()
    # demo.py resolves bpy_server.py, checkpoints and configs relative to the repo
    # root, so it must run with cwd there.
    proc = subprocess.Popen(
        cmd, cwd=str(SKINTOKENS_REPO), env=_rig_env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    try:
        log, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        proc.wait()
        _kill_orphan_bpy_server()
        raise TimeoutError(
            f"{label} exceeded {timeout}s and was killed. Lower num_beams "
            f"(currently {params['num_beams']}) or raise timeout. Note that timeout "
            "is PER PASS and canonical rigging runs two."
        ) from None

    elapsed = round(time.time() - started, 1)
    # demo.py prints "[Error] ..." on an export failure but still exits 0, so the
    # exit code alone does not mean the pass succeeded. The written file does.
    if not target.is_file() or target.stat().st_size == 0:
        tail = "\n".join(log.strip().splitlines()[-40:]) if log else ""
        raise RuntimeError(
            f"{label} produced no output at {target} (exit {proc.returncode}, {elapsed}s)."
            + (f" Log tail:\n{tail}" if tail else "")
        )
    return elapsed


def _joint_hierarchy(path: Path) -> tuple[list[str], list[int]]:
    """(bone names, parent indices) for a rigged GLB's skin, in joint order."""
    gltf, _binary = _read_glb(path)
    nodes = gltf["nodes"]
    joints = gltf["skins"][0]["joints"]
    parent_of = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    slot = {n: k for k, n in enumerate(joints)}
    names = [nodes[i].get("name", "") for i in joints]
    parents = [slot.get(parent_of.get(i), -1) for i in joints]
    return names, parents


def _verify_canonical(final: Path, canonical: Path, fit_report: dict[str, Any]) -> dict[str, Any]:
    """Confirm the shipped rig carries exactly the skeleton that was supplied.

    Every character having an identical bone list is the whole point, so it is
    asserted rather than eyeballed. Two separate invariants:

      * the final rig's names and hierarchy match the CANONICAL GLB's, in order -
        this is what makes restore-names-by-index valid, and it fails if TokenRig
        reordered or altered the supplied skeleton.
      * the name SET matches what the fitter specified. Not the order: the fitter
        specifies joints in hierarchy-construction order while BpyParser writes
        them in its own, and comparing those two orders only ever tests the
        exporter's bookkeeping.
    """
    got, got_parents = _joint_hierarchy(final)
    ref, ref_parents = _joint_hierarchy(canonical)
    if got != ref or got_parents != ref_parents:
        raise RuntimeError(
            f"Rigged output does not match the supplied skeleton: {len(got)} bones vs "
            f"{len(ref)} supplied, hierarchy "
            f"{'differs' if got_parents != ref_parents else 'matches'}. "
            "Renaming by index is only valid when TokenRig honoured the skeleton exactly."
        )
    want = set(fit_report["names"])
    if set(got) != want:
        raise RuntimeError(
            f"Rig carries the wrong skeleton. Missing: {sorted(want - set(got))[:8]}. "
            f"Unexpected: {sorted(set(got) - want)[:8]}."
        )
    core = [n for n in got if n.startswith("mixamorig:")]
    return {
        "canonical": True,
        "bones": len(got),
        "core_bones": len(core),
        "extra_chains": sorted({n.rsplit("_", 1)[0] for n in got if not n.startswith("mixamorig:")}),
    }


def _kill_orphan_bpy_server() -> None:
    """Kill a bpy_server left holding port 59876 after a killed rig run.

    demo.py puts bpy_server in its own session (os.setsid), so killing demo.py's
    process group does not reach it, and its atexit cleanup never runs when we
    SIGKILL on timeout. The match is the exact argv demo.py spawns.
    """
    subprocess.run(["pkill", "-f", f"^{SKINTOKENS_PYTHON} bpy_server.py$"], capture_output=True)


@mcp.tool
def rig_model(
    mesh: Annotated[
        str,
        Field(
            description=(
                "Mesh to rig: .glb, .obj or .fbx. Absolute path, or a bare filename "
                "resolved against the TRELLIS output dir (e.g. 'trellis_1234.glb')."
            )
        ),
    ],
    output_name: Annotated[str, Field(description="Base name for the rigged output (without extension)")] = "",
    num_beams: Annotated[
        int,
        Field(
            description="Beam search width. Main speed/VRAM lever: 1-3 for fast iteration, 10 for final quality",
            ge=1,
            le=20,
        ),
    ] = 10,
    use_transfer: Annotated[
        bool,
        Field(description="Transfer the rig back onto the original high-detail geometry, preserving texture and scale"),
    ] = True,
    use_postprocess: Annotated[
        bool, Field(description="Voxel-based skin cleanup. Enable when weights bleed across disconnected parts")
    ] = False,
    top_k: Annotated[int, Field(description="Sampling top_k", ge=1, le=200)] = 5,
    top_p: Annotated[float, Field(description="Sampling top_p", ge=0.1, le=1.0)] = 0.95,
    temperature: Annotated[float, Field(description="Sampling temperature", ge=0.1, le=2.0)] = 1.0,
    repetition_penalty: Annotated[
        float,
        Field(
            description="Repetition penalty. Default is high because bone sequences repeat structurally",
            ge=0.5,
            le=3.0,
        ),
    ] = 2.0,
    timeout: Annotated[
        int, Field(description="Hard limit in seconds PER TokenRig pass; this tool runs two", ge=60, le=7200)
    ] = 1800,
) -> dict[str, Any]:
    """Rig a mesh with the canonical Mixamo skeleton, so animations are shareable.

    Every character comes out with the SAME bone list - a 23-bone `mixamorig:*`
    core, four tip bones so leaf bones do not overshoot the mesh, and named
    `wing_`/`tail_`/`horn_` chains for whatever else the mesh has.
    That is what lets one clip drive the whole library via apply_animation, and
    what Unreal's IK Retargeter and Unity's Humanoid avatar need. A per-asset
    skeleton named bone_0..bone_N cannot do either.

    Runs TokenRig TWICE, because the skeleton fitter needs landmarks:

      1. a normal rig pass, read only for where its limb chains ended up
      2. fit the Mixamo skeleton onto those landmarks
      3. a second pass with --use_skeleton, which skins to the supplied skeleton
         rather than inventing one
      4. restore the bone names, which TokenRig drops

    So expect roughly twice the runtime of a raw rig. In exchange the skeleton is
    now fixed by construction - the documented 47-vs-44-joint lottery applies only
    to step 1, which is thrown away.

    Hot-swaps the GPU: TRELLIS is evicted from VRAM first and the lock is held
    across both passes. The next generate_3d call reloads TRELLIS automatically.

    Output is always .glb. After importing to Blender, delete the
    `glTF_not_exported` node.
    """
    try:
        _rig_preflight()
        _canonical_preflight()

        # Relative names resolve against the TRELLIS output dir so a generate_3d
        # result can be passed straight through.
        source = Path(mesh)
        if not source.is_absolute():
            source = OUTPUT_DIR / source
        if not source.is_file():
            raise FileNotFoundError(f"Input mesh not found: {source}")
        if source.suffix.lower() not in RIG_INPUT_SUFFIXES:
            raise ValueError(f"Unsupported input format '{source.suffix}'. Supported: {', '.join(RIG_INPUT_SUFFIXES)}")

        # Inspect before taking the GPU: the conditions that decide rig quality are
        # properties of the input, and reporting them after a 50s run helps nobody.
        mesh_diag = _mesh_diagnostics(source)

        if not output_name:
            output_name = f"{source.stem}_rigged"
        target = RIG_OUTPUT_DIR / f"{output_name}.glb"
        landmarks = RIG_OUTPUT_DIR / f"{output_name}_landmarks.glb"
        canonical = RIG_OUTPUT_DIR / f"{output_name}_canonical.glb"
        skinned = RIG_OUTPUT_DIR / f"{output_name}_skinned.glb"
        named = RIG_OUTPUT_DIR / f"{output_name}_named.glb"
        smoothed = RIG_OUTPUT_DIR / f"{output_name}_smoothed.glb"
        oriented = RIG_OUTPUT_DIR / f"{output_name}_oriented.glb"

        # Rig a decimated proxy when the mesh is out of TokenRig's range, and wear
        # the weights on the full-resolution mesh afterwards. simplify=0.95 used to
        # force these to be the same mesh, at the cost of 95% of the geometry.
        rig_input = source
        proxy = None
        if mesh_diag["vertices"] > _VERT_RANGE[1]:
            proxy = RIG_OUTPUT_DIR / f"{output_name}_proxy.glb"
            _run_script(
                SEGVIGEN_PYTHON, RIG_PROXY_DRIVER,
                ["decimate", "--mesh", str(source), "--out", str(proxy),
                 "--target-vertices", str(PROXY_VERTEX_TARGET)],
                600, "DECIMATE_OK", "Proxy decimation",
            )
            rig_input = proxy

        params = {
            "num_beams": num_beams, "use_transfer": use_transfer,
            "use_postprocess": use_postprocess, "top_k": top_k, "top_p": top_p,
            "temperature": temperature, "repetition_penalty": repetition_penalty,
        }
        started = time.time()

        # One lock across the whole chain: pass 2 needs the card again, and letting
        # another tool take it in between would strand a half-finished rig.
        with _gpu_lock:
            evicted = _evict_trellis()
            t_landmarks = _demo_pass(rig_input, landmarks, False, "Landmark rig pass", params, timeout)

            # The fitter reads joint positions from the landmark rig and vertices
            # from the ORIGINAL mesh, so both must be in the same scale - which is
            # why the landmark pass runs with the same use_transfer as the final one.
            _run_script(
                SEGVIGEN_PYTHON, CANONICAL_DRIVER,
                ["fit", "--mesh", str(rig_input), "--from-rig", str(landmarks), "--out", str(canonical)],
                600, "CANONICAL_FIT_OK", "Canonical skeleton fit",
            )
            fit_report = json.loads(Path(str(canonical).rsplit(".", 1)[0] + "_skeleton.json").read_text())

            t_skin = _demo_pass(canonical, skinned, True, "Skinning pass", params, timeout)

        # Name restore is a JSON-chunk patch - no GPU, no bpy, so it runs outside
        # the lock. TokenRig preserves joint ORDER but drops names, which is what
        # makes renaming by index exact.
        _run_script(
            SEGVIGEN_PYTHON, CANONICAL_DRIVER,
            ["restore-names", "--rigged", str(skinned), "--reference", str(canonical), "--out", str(named)],
            300, "CANONICAL_RESTORE_OK", "Bone name restore",
        )

        # Diffuse the weights before anything else touches them. TokenRig's weights
        # go near-binary across a handful of edges and the mesh splits along that
        # line under motion - measured at 931 of 14,679 edges jumping more than 0.5,
        # worst at Hips<->UpLeg, which is where a skirt tears. Smoothing takes that
        # to 0.81% and eliminates jumps over 1.0 entirely, without moving the median.
        # (use_postprocess is NOT this: measured, it doubles the hard boundaries.)
        _run_script(
            SEGVIGEN_PYTHON, SMOOTH_DRIVER,
            ["--rigged", str(named), "--out", str(smoothed)],
            300, "SMOOTH_OK", "Weight smoothing",
        )

        # Point every bone at its child. TokenRig's writer does not, and Blender
        # draws bones head->tail - so a rig whose joint POSITIONS are perfect still
        # renders as spokes jutting out of the character, and is unusable for hand
        # animation because rotating a bone bends its limb about an unrelated axis.
        # Measured on emberwake_herald: 8 of 18 bones over 20 degrees off, worst
        # 116.6. Invisible to every retargeting metric - the rest-relative delta
        # cancels bone-axis convention, so output is byte-identical either way -
        # which is exactly why it survived this long.
        _run_script(
            SEGVIGEN_PYTHON, ORIENT_DRIVER,
            ["--rigged", str(smoothed), "--out", str(oriented)],
            300, "ORIENT_OK", "Bone orientation",
        )

        if proxy is None:
            oriented.replace(target)
        else:
            # Sample the proxy's weights onto the full mesh as a smooth field. NOT a
            # nearest-vertex copy - SkinCells and RSWT both show that failing on
            # loose garments, with skirts as the named failure case.
            _run_script(
                SEGVIGEN_PYTHON, RIG_PROXY_DRIVER,
                ["transfer", "--proxy", str(oriented), "--mesh", str(source),
                 "--out", str(target)],
                900, "TRANSFER_OK", "Weight transfer to full resolution",
            )

        elapsed = round(time.time() - started, 1)
        canonical_check = _verify_canonical(target, canonical, fit_report)
        skeleton = _skeleton_report(target)
        published = _publish_rig(
            source, target, elapsed, num_beams, use_transfer, use_postprocess,
            mesh_diag, skeleton, fit_report, canonical_check,
        )

        return {
            "success": True,
            "output_name": output_name,
            "input": str(source),
            "rigged_glb": str(target),
            "published_to": published,
            "size_bytes": target.stat().st_size,
            "elapsed_seconds": elapsed,
            "passes": {
                "landmark_rig_seconds": t_landmarks,
                "skinning_seconds": t_skin,
                "landmark_glb": str(landmarks),
                "canonical_glb": str(canonical),
                "pre_smoothing_glb": str(named),
                "pre_orientation_glb": str(smoothed),
                "proxy_glb": str(proxy) if proxy else None,
                "rigged_at_proxy_resolution": proxy is not None,
            },
            "trellis_evicted": evicted,
            "geometry": _glb_dimensions(target),
            "mesh_diagnostics": mesh_diag,
            "skeleton": skeleton,
            "canonical": canonical_check,
            "extras_note": (
                "Chains outside the mixamorig: namespace (wings, tails, horns) are "
                "deliberately left undriven by apply_animation, so a standard humanoid "
                "clip cannot flail them. Key them by hand or procedurally."
            ),
            "warnings": mesh_diag.get("warnings", []) + skeleton.get("warnings", []),
            "reroll_note": (
                "The SKELETON is now fixed by construction and identical across characters. "
                "Skin weights still sample, so a bad deformation is worth re-running; a bad "
                "skeleton is no longer a failure mode. Note that _skeleton_report's symmetry "
                "mirrors LOCAL node translations and is not rotation-invariant - judge "
                "deformation by posing, not by that number."
            ),
            "parameters": {
                "num_beams": num_beams,
                "use_transfer": use_transfer,
                "use_postprocess": use_postprocess,
                "top_k": top_k,
                "top_p": top_p,
                "temperature": temperature,
                "repetition_penalty": repetition_penalty,
            },
            "note": "Delete the 'glTF_not_exported' node after importing to Blender.",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


def _publish_segmentation(
    source: Path, report: dict[str, Any], report_path: Path, seed: int, elapsed: float
) -> str | None:
    """Add the part sidecar to its published asset directory.

    Same matching rule as _publish_rig: by the source mesh's stem against the
    gen_ai tree. A mesh segmented from somewhere else has no asset directory to
    update and reports None.

    The sidecar is only meaningful next to the exact mesh it indexes, so it is
    published INTO the asset directory rather than anywhere on its own.
    """
    for asset_type in ASSET_TYPES:
        asset_dir = CODEX_GEN_AI_DIR / asset_type / source.stem
        meta_path = asset_dir / "metadata.json"
        if not meta_path.is_file():
            continue

        shutil.copy2(report["face_labels"], asset_dir / "asset_face_labels.npy")
        shutil.copy2(report_path, asset_dir / "asset_parts.json")
        if report.get("preview"):
            shutil.copy2(report["preview"], asset_dir / "asset_parts_preview.glb")

        metadata = json.loads(meta_path.read_text())
        metadata["segmented"] = True
        metadata["segmentation_tool"] = "SegviGen"
        metadata["segmentation"] = {
            "part_count": len(report["parts"]),
            "parts": report["parts"],
            "seed": seed,
            "elapsed_seconds": elapsed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "faces": report["faces"],
            "vertices": report["vertices"],
            "source_sha256": report["source_sha256"],
            "reproducible": True,
            "_reproducibility_note": (
                "The partition is sampled. This seed reproduces it exactly; a different seed "
                "gives a genuinely different split, and the part colours are arbitrary labels "
                "that change with it."
            ),
            "_labels_note": (
                "asset_face_labels.npy is int32, one entry per face of "
                "trimesh.load(asset.glb, force='mesh', process=False). process=False matters: "
                "welding reorders faces and the labels stop lining up."
            ),
        }
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
        return str(asset_dir)
    return None


def _segment_preflight() -> None:
    """Raise with actionable detail if the SegviGen install is incomplete."""
    missing: list[str] = []
    if not SEGVIGEN_PYTHON.is_file():
        missing.append(f"interpreter {SEGVIGEN_PYTHON}")
    if not (SEGVIGEN_REPO / "inference_full.py").is_file():
        missing.append(str(SEGVIGEN_REPO / "inference_full.py"))
    if not (SEGVIGEN_REPO / "microsoft" / "TRELLIS.2-4B" / "pipeline.json").is_file():
        missing.append(str(SEGVIGEN_REPO / "microsoft/TRELLIS.2-4B/pipeline.json"))
    if not SEGVIGEN_DRIVER.is_file():
        missing.append(str(SEGVIGEN_DRIVER))
    if not list(Path.home().glob(".cache/huggingface/hub/models--fenghora--SegviGen/snapshots/*/full_seg.ckpt")):
        missing.append("fenghora/SegviGen full_seg.ckpt in the HuggingFace cache")
    if missing:
        raise RuntimeError(
            "SegviGen install is incomplete. Missing: "
            + "; ".join(missing)
            + ". Run scripts/install_segvigen.sh to install it."
        )


@mcp.tool
def segment_mesh(
    mesh: Annotated[
        str,
        Field(
            description=(
                "Mesh to segment: .glb. Absolute path, or a bare filename resolved "
                "against the TRELLIS output dir (e.g. 'trellis_1234.glb')."
            )
        ),
    ],
    output_name: Annotated[str, Field(description="Base name for the sidecar (without extension)")] = "",
    seed: Annotated[
        int, Field(description="Sampler seed. Same seed + same mesh = same partition.", ge=0)
    ] = 0,
    preview: Annotated[
        bool, Field(description="Also write a part-coloured preview GLB for eyeballing")
    ] = True,
    timeout: Annotated[int, Field(description="Hard limit in seconds", ge=60, le=7200)] = 3600,
) -> dict[str, Any]:
    """Label every face of a mesh with a part id, without touching the mesh.

    Runs SegviGen (part segmentation on the TRELLIS.2 backbone) and writes a
    sidecar: a face_labels .npy plus a parts .json. Geometry, UVs, texture and any
    rig are left exactly as they were - the source file is hashed before and after
    and the run fails if it changed.

    This deliberately does NOT use SegviGen's own GLB export, which is a remeshed
    reconstruction: an 11,200-vertex asset comes back as 71,053 vertices with a
    baked copy of the part colours and nothing else preserved.

    Parts come back as whole structural pieces - on a winged character, body /
    left wing / right wing / tail. Useful for prop stripping and per-part rigging.

    `color_rgb` in the report is the sampler's arbitrary label colour for a part,
    not a semantic identity: it changes with the seed and means nothing across
    meshes. Only the partition matters.

    Hot-swaps the GPU: TRELLIS is evicted first, then SegviGen runs in its own
    Python 3.11 environment and releases the card when it exits.
    """
    try:
        _segment_preflight()

        # Relative names resolve against the TRELLIS output dir so a generate_3d
        # result can be passed straight through.
        source = Path(mesh)
        if not source.is_absolute():
            source = OUTPUT_DIR / source
        if not source.is_file():
            raise FileNotFoundError(f"Input mesh not found: {source}")
        if source.suffix.lower() != ".glb":
            raise ValueError(f"Unsupported input format '{source.suffix}'. SegviGen reads .glb only.")

        # Inspect before taking the GPU, same reason as rig_model: these are
        # properties of the input and reporting them after a 3-minute run helps
        # nobody. Shell count in particular predicts how clean the partition is.
        mesh_diag = _mesh_diagnostics(source)

        # The whole promise of this tool is that the asset comes back untouched, so
        # the server checks that itself rather than trusting the driver's own assert.
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()

        if not output_name:
            output_name = source.stem
        out_dir = SEGVIGEN_OUTPUT_DIR / output_name
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / f"{source.stem}_parts.json"

        cmd = [
            str(SEGVIGEN_PYTHON), str(SEGVIGEN_DRIVER),
            "--mesh", str(source),
            "--out-dir", str(out_dir),
            "--seed", str(seed),
        ]
        if preview:
            cmd.append("--preview")

        started = time.time()

        with _gpu_lock:
            evicted = _evict_trellis()
            gc.collect()
            torch.cuda.empty_cache()

            free, _total = torch.cuda.mem_get_info(0)
            if free < SEGVIGEN_VRAM_REQUIRED:
                raise RuntimeError(
                    f"SegviGen needs ~{SEGVIGEN_VRAM_REQUIRED / 1e9:.0f} GB VRAM but only "
                    f"{free / 1e9:.1f} GB is free, even after evicting TRELLIS. Something else is "
                    "holding the GPU."
                )

            # The driver chdirs into the repo itself, but inference_full.py opens
            # microsoft/TRELLIS.2-4B/pipeline.json relatively, so cwd must be the
            # repo from the start.
            env = dict(os.environ)
            env["ATTN_BACKEND"] = "sdpa"
            env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
            proc = subprocess.Popen(
                cmd, cwd=str(SEGVIGEN_REPO), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            try:
                log, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                raise TimeoutError(f"Segmentation exceeded {timeout}s and was killed.") from None

        elapsed = round(time.time() - started, 1)
        tail = "\n".join(log.strip().splitlines()[-40:]) if log else ""

        # The written report is the only trustworthy signal, as elsewhere in this
        # server - and it is also the thing the caller actually needs, so a
        # readable, parseable report doubles as the success check.
        if not report_path.is_file():
            return {
                "success": False,
                "error": f"Segmentation produced no report at {report_path} (exit {proc.returncode}, {elapsed}s)",
                "log": tail,
            }
        report = json.loads(report_path.read_text())

        if hashlib.sha256(source.read_bytes()).hexdigest() != source_digest:
            return {
                "success": False,
                "error": f"{source} was modified during segmentation. The sidecar was discarded.",
            }

        # Deliberately NOT seeded with mesh_diag["warnings"]: those are tuned for
        # rig quality (training-mixture vertex ranges, GRPO reward voxelization) and
        # say nothing about segmentation. The diagnostics themselves are still
        # returned, because the counts are worth seeing.
        warnings: list[str] = []
        if not mesh_diag.get("is_watertight", True):
            warnings.append(
                "Mesh is not watertight, so some face centroids fall outside the voxelized "
                "surface and take the colour of the nearest occupied voxel instead. Check the "
                "preview along thin or open shells, where that guess is least reliable."
            )
        published = _publish_segmentation(source, report, report_path, seed, elapsed)

        if len(report["parts"]) < 2:
            warnings.append(
                f"Only {len(report['parts'])} part was found, so the mesh was not actually "
                "divided. Re-run with a different seed - the partition is sampled, and the "
                "same mesh has returned anywhere from 2 to 7 parts across seeds."
            )

        return {
            "success": True,
            "output_name": output_name,
            "input": str(source),
            "face_labels": report["face_labels"],
            "report": str(report_path),
            "published_to": published,
            "preview_glb": report.get("preview"),
            "part_count": len(report["parts"]),
            "parts": report["parts"],
            "vertices": report["vertices"],
            "faces": report["faces"],
            "source_sha256": source_digest,
            "source_unchanged": True,   # verified above by re-hashing, not assumed
            "max_lookup_distance_voxels": round(
                report["lookup"]["max_distance_normalized"] / report["lookup"]["voxel_size_normalized"], 2
            ),
            "elapsed_seconds": elapsed,
            "trellis_evicted": evicted,
            "seed": seed,
            "mesh_diagnostics": mesh_diag,
            "warnings": warnings,
            "reroll_note": (
                "The partition is sampled, not deduced. A fixed seed makes it reproducible, "
                "but a different seed gives a genuinely different split - judge the preview "
                "and re-roll rather than trying to merge parts afterwards."
            ),
            "usage_note": (
                "face_labels is an int32 .npy with one entry per face of "
                "trimesh.load(<input>, force='mesh', process=False). process=False matters: "
                "welding would reorder faces and the labels would no longer line up."
            ),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


def _garment_preflight() -> None:
    """Raise with actionable detail if the garment path is not installed."""
    missing: list[str] = []
    if not SEGVIGEN_PYTHON.is_file():
        missing.append(f"interpreter {SEGVIGEN_PYTHON}")
    if not (SEGVIGEN_REPO / "microsoft" / "TRELLIS.2-4B" / "pipeline.json").is_file():
        missing.append(str(SEGVIGEN_REPO / "microsoft/TRELLIS.2-4B/pipeline.json"))
    for driver in (GARMENT_DRIVER, GARMENT_FIT_DRIVER):
        if not driver.is_file():
            missing.append(str(driver))
    if missing:
        raise RuntimeError(
            "The garment path is not installed. Missing: " + "; ".join(missing)
            + ". Run scripts/install_segvigen.sh - garments share that environment because "
            "TRELLIS.2 lives there."
        )


def _garment_prompt(description: str) -> str:
    """Build the product-shot prompt.

    The wording is the whole reason this works. Measured: a corset masked out of a
    dressed character reconstructs as a featureless blob with 36.5% of its air
    sealed in, while the same garment described as a standalone product shot
    reconstructs cleanly at 0.07%. A garment worn on a body has its interior
    occluded; asking the model to invert that gives a stuffed lump. Every clause
    below pushes towards "this object is alone and you can see inside it".
    """
    return (
        f"Product photograph of a single {description}, standing alone with nothing inside it, "
        "no body, no mannequin, no person. Hollow interior visible through the openings. "
        "Centred on a plain flat white background, even studio lighting, no shadows, "
        "full object in frame, sharp focus, catalogue photo."
    )


def _publish_garment(output_name: str, files: dict[str, Path], metadata: dict[str, Any]) -> str:
    """Publish a garment bundle to the curated tree, refusing to overwrite.

    Keys are the destination filenames, matching _publish_asset's convention
    (asset.glb, reference.png) so a garment directory reads like every other one.
    """
    _codex_available()
    dest = CODEX_GEN_AI_DIR / "garments" / output_name
    if dest.exists():
        raise FileExistsError(
            f"{dest} already exists. Pick a different output_name, or remove that directory "
            "if you intend to replace the garment."
        )
    dest.mkdir(parents=True)
    for filename, src in files.items():
        if src and src.is_file():
            shutil.copy2(src, dest / filename)
    (dest / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return str(dest)


@mcp.tool
def generate_garment(
    garment: Annotated[
        str,
        Field(
            description=(
                "What the garment is, as a noun phrase - e.g. 'black leather armour corset "
                "with brass buckles'. Taken verbatim from the character prompt that produced "
                "the outfit, so the same words that generated it also define it."
            )
        ),
    ],
    body: Annotated[
        str,
        Field(
            description=(
                "Target body .glb to fit onto. Absolute path, or a name resolved against the "
                "curated characters tree (e.g. 'female_base_v5')."
            )
        ),
    ],
    output_name: Annotated[str, Field(description="Base name for the garment asset")] = "",
    anchor: Annotated[
        str,
        Field(description="Where on the body it sits: torso, chest, waist, hips, legs or full"),
    ] = "torso",
    seed: Annotated[int, Field(description="Seed for the garment generation", ge=0)] = 0,
    drape: Annotated[bool, Field(description="Run the cloth pass after placing")] = True,
    publish: Annotated[bool, Field(description="Publish the bundle to codex_fs")] = True,
    timeout: Annotated[int, Field(description="Hard limit per stage, seconds", ge=60, le=7200)] = 3600,
) -> dict[str, Any]:
    """Generate a garment as its own open-surface asset and fit it to a body.

    This exists because segmentation cannot serve it. Splitting a garment off a
    dressed character yields the outer shell only - no interior, no thickness, and
    nothing where cloth meets skin - so it can never be conformed onto a different
    body. Measured separately: SegviGen partitions by structure, not material, and
    never follows a garment edge at all.

    Three stages: a product-shot image of the garment alone, TRELLIS.2 to turn it
    into an open-surface mesh, then placement and a cloth pass onto the target body.
    TRELLIS.2 rather than this server's generate_3d, which runs TRELLIS 1 and
    defaults fill_holes=True - either of which would seal the garment shut.

    Fails loudly rather than returning a bad garment: a mesh that comes back
    watertight, or with more than 5% of its air sealed inside, is rejected. Both
    mean a body could never go in it.
    """
    try:
        _garment_preflight()

        target = Path(body)
        if not target.is_absolute():
            candidate = CODEX_GEN_AI_DIR / "characters" / body / "asset.glb"
            target = candidate if candidate.is_file() else OUTPUT_DIR / body
        if not target.is_file():
            raise FileNotFoundError(f"Target body not found: {target}")

        if not output_name:
            output_name = _slugify(garment)[:48] or f"garment_{int(time.time())}"
        work = SEGVIGEN_OUTPUT_DIR.parent / "garments" / output_name
        work.mkdir(parents=True, exist_ok=True)
        started = time.time()

        # 1. Product shot. @mcp.tool registers the function and returns it
        #    unchanged, so within this module it is directly callable.
        prompt = _garment_prompt(garment)
        image_result = generate_image(
            prompt=prompt, output_name=f"{output_name}_ref", seed=seed,
            steps=6, width=1024, height=1024,
        )
        if not image_result.get("success"):
            return {"success": False, "stage": "generate_image", "error": image_result.get("error")}
        # generate_image returns the file under "local_path". An earlier version read
        # "image_path" with a constructed path as backup, which silently always took
        # the backup and only worked because the two happened to agree.
        reference = image_result["local_path"]

        env = dict(os.environ)
        env["ATTN_BACKEND"] = "sdpa"
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

        # 2. Mesh it. This is the only GPU stage.
        with _gpu_lock:
            evicted = _evict_trellis()
            gc.collect()
            torch.cuda.empty_cache()
            free, _total = torch.cuda.mem_get_info(0)
            if free < GARMENT_VRAM_REQUIRED:
                raise RuntimeError(
                    f"Garment generation needs ~{GARMENT_VRAM_REQUIRED / 1e9:.0f} GB VRAM but only "
                    f"{free / 1e9:.1f} GB is free, even after evicting TRELLIS."
                )
            gen = subprocess.run(
                [str(SEGVIGEN_PYTHON), str(GARMENT_DRIVER),
                 "--image", reference, "--out-dir", str(work), "--name", output_name,
                 "--seed", str(seed), "--preview"],
                cwd=str(SEGVIGEN_REPO), env=env, capture_output=True, text=True, timeout=timeout,
            )
        garment_report_path = work / f"{output_name}_garment.json"
        if not garment_report_path.is_file():
            return {
                "success": False, "stage": "trellis2_garment",
                "error": f"no garment report at {garment_report_path} (exit {gen.returncode})",
                "log": "\n".join((gen.stdout + gen.stderr).strip().splitlines()[-30:]),
            }
        garment_report = json.loads(garment_report_path.read_text())

        # 3. Place, and optionally drape. CPU only - no GPU lock needed.
        fit_cmd = [str(SEGVIGEN_PYTHON), str(GARMENT_FIT_DRIVER),
                   "--garment", garment_report["garment_glb"], "--body", str(target),
                   "--out-dir", str(work), "--name", f"{output_name}_fitted", "--anchor", anchor]
        if not drape:
            fit_cmd.append("--no-drape")
        fit = subprocess.run(fit_cmd, capture_output=True, text=True, timeout=timeout)
        fit_report_path = work / f"{output_name}_fitted_fit.json"
        if not fit_report_path.is_file():
            return {
                "success": False, "stage": "garment_fit",
                "error": f"no fit report at {fit_report_path} (exit {fit.returncode})",
                "log": "\n".join((fit.stdout + fit.stderr).strip().splitlines()[-30:]),
            }
        fit_report = json.loads(fit_report_path.read_text())

        elapsed = round(time.time() - started, 1)
        fitted = fit_report.get("draped_glb") or fit_report["placed_glb"]

        warnings: list[str] = list(garment_report.get("warnings", []))
        penetration = fit_report.get("penetration_after_drape", fit_report["penetration_after_placement"])
        if penetration > 0.01:
            warnings.append(
                f"{penetration:.1%} of garment vertices are still inside the body. Check the "
                "render before using it; raising --ease or the anchor band usually fixes it."
            )

        metadata = {
            "asset_type": "garments", "tool": "TRELLIS.2", "garment": garment,
            "prompt": prompt, "seed": seed, "anchor": anchor, "draped": drape,
            "target_body": str(target), "reference_image": reference,
            "generation": garment_report, "fit": fit_report,
            "elapsed_seconds": elapsed, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        published = None
        if publish:
            published = _publish_garment(
                output_name,
                {
                    "asset.glb": Path(fitted),                              # fitted to the body
                    "asset_unfitted.glb": Path(garment_report["garment_glb"]),  # as generated
                    "reference.png": Path(reference),
                },
                metadata,
            )

        return {
            "success": True,
            "output_name": output_name,
            "garment_glb": garment_report["garment_glb"],
            "fitted_glb": fitted,
            "published_to": published,
            "reference_image": reference,
            "target_body": str(target),
            "is_open_surface": not garment_report["is_watertight"],
            "enclosed_air_fraction": garment_report["enclosed_air_fraction"],
            "penetration": penetration,
            "faces": garment_report["faces"],
            "peak_vram_gb": garment_report["peak_vram_gb"],
            "trellis_evicted": evicted,
            "elapsed_seconds": elapsed,
            "warnings": warnings,
            "fit": fit_report,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# A canonically rigged character has 23 mixamorig: bones. Accepting slightly fewer
# leaves room for a character with no toes, but not for a bone_0..bone_N rig.
_MIXAMO_CORE_MIN = 20


def _rigged_bones(path: Path) -> list[str]:
    """Bone names carried by a rigged GLB's skin, in joint order."""
    gltf, _binary = _read_glb(path)
    if not gltf.get("skins"):
        raise ValueError(f"{path} carries no skin, so it is not a rigged character.")
    return [gltf["nodes"][j].get("name", "") for j in gltf["skins"][0]["joints"]]


def _require_canonical(path: Path) -> list[str]:
    """Reject a character that was not rigged canonically, before spending a retarget."""
    bones = _rigged_bones(path)
    core = [b for b in bones if b.startswith("mixamorig:")]
    if len(core) < _MIXAMO_CORE_MIN:
        raise ValueError(
            f"{path.name} carries {len(core)} mixamorig: bones out of {len(bones)} - it was not "
            "rigged canonically, and a shared clip cannot drive a per-asset skeleton. Re-run "
            "rig_model on the original mesh; fitting the Mixamo skeleton is now its only path."
        )
    return bones


def _library_report(refresh: bool, timeout: int) -> dict[str, Any]:
    """Scan (or reuse the cache for) every clip on disk."""
    report_path = OUTPUT_DIR / "animation_library.json"
    argv = [
        "--roots", *[str(r) for r in ANIMATION_ROOTS],
        "--cache", str(ANIMATION_CACHE),
        "--report", str(report_path),
    ]
    if refresh:
        argv.append("--refresh")
    _run_script(
        SEGVIGEN_PYTHON, ANIMATION_LIBRARY_DRIVER, argv, timeout,
        "LIBRARY_OK", "Animation library scan",
    )
    return json.loads(report_path.read_text())


def _resolve_clip(clip: str, action: str, report: dict[str, Any]) -> tuple[Path, str, str]:
    """Resolve a clip to (file, action, display name).

    Accepts either a path to a clip file or a clip `name` from list_animations.
    The display name is what the output and the metadata entry are named after:
    every Mixamo export calls its action "Armature|mixamo.com|Layer0", which says
    nothing about the clip, so a single-action file is named after the file.
    """
    path = Path(clip)
    if path.is_file():
        return path, action, (action or path.stem)
    matches = [c for c in report["clip_list"] if c["name"] == clip]
    if not matches:
        near = sorted({c["name"] for c in report["clip_list"] if clip.lower() in c["name"].lower()})
        raise FileNotFoundError(
            f"No clip file at '{clip}', and no action by that name in the library. "
            + (f"Close matches: {near[:10]}" if near else "Call list_animations to see what is available.")
        )
    files = sorted({c["file"] for c in matches})
    if len(files) > 1:
        raise ValueError(
            f"'{clip}' appears in {len(files)} different files: {files[:5]}. "
            "Pass the file path as `clip` and the action name as `action` to disambiguate."
        )
    # Name the action only when the file holds a choice. A single-action file has
    # nothing to disambiguate, and not naming it means not depending on a name.
    n_actions = sum(1 for c in report["clip_list"] if c["file"] == files[0])
    return Path(files[0]), (matches[0]["action"] if n_actions > 1 else ""), matches[0]["name"]


def _publish_animation(
    character: Path, animated: Path, report: dict[str, Any], name: str,
) -> str | None:
    """Add the animated GLB to its published asset directory and record the clip.

    rig_model names its output `<asset>_rigged.glb`, so the asset directory is
    looked up by the stem with that suffix removed as well as by the stem itself.
    A character rigged from somewhere else has no directory to update.
    """
    stems = [character.stem, character.stem.removesuffix("_rigged")]
    for asset_type in ASSET_TYPES:
        for stem in stems:
            meta_path = CODEX_GEN_AI_DIR / asset_type / stem / "metadata.json"
            if not meta_path.is_file():
                continue
            asset_dir = meta_path.parent
            slug = _slugify(name, 40)
            shutil.copy2(animated, asset_dir / f"asset_anim_{slug}.glb")
            metadata = json.loads(meta_path.read_text())
            # Keyed by display name so re-applying the same clip replaces its entry
            # rather than accumulating duplicates.
            existing = {a["name"]: a for a in metadata.get("animations", [])}
            existing[name] = {
                "name": name,
                "action": report["action"],
                "file": f"asset_anim_{slug}.glb",
                "clip_source": report["clip"],
                "frames": report["frames"],
                "source_convention": report["source_convention"],
                "bones_driven": report["bones_mapped"],
                "frame_alignment_deg": report["frame_alignment_deg"],
                "root_motion": report["root_motion"],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            metadata["animations"] = sorted(existing.values(), key=lambda a: a["name"])
            meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
            return str(asset_dir)
    return None


@mcp.tool
def list_animations(
    search: Annotated[str, Field(description="Case-insensitive substring filter on the action name")] = "",
    library: Annotated[str, Field(description="Filter to one library, e.g. 'SCP-610' or 'Unreal-Godot'")] = "",
    convention: Annotated[
        str, Field(description="Filter by source naming convention: 'mixamo' or 'ue5'")
    ] = "",
    limit: Annotated[int, Field(description="Maximum clips to return", ge=1, le=1000)] = 80,
    refresh: Annotated[
        bool, Field(description="Rescan every file instead of trusting the size+mtime cache")
    ] = False,
    timeout: Annotated[int, Field(description="Hard limit in seconds for a full rescan", ge=60, le=7200)] = 3600,
) -> dict[str, Any]:
    """List the animation clips on disk that can drive a canonically rigged character.

    A clip is a (file, action) PAIR, not a file: the Quaternius Universal Animation
    Library ships one fbx per target engine carrying every clip as a separate
    action, so counting files undercounts badly.

    `convention` is the name map that matched the clip's own armature. A clip
    reporting null cannot drive our rigs however it is invoked - that is visible
    here rather than after a wasted retarget.

    Reading actions means importing each file in Blender, so results are cached by
    size and mtime. The first call is slow; later ones are near-instant, and a new
    or changed file is picked up automatically.
    """
    try:
        _canonical_preflight()
        report = _library_report(refresh, timeout)

        clips = report["clip_list"]
        if search:
            clips = [c for c in clips if search.lower() in c["name"].lower()]
        if library:
            clips = [c for c in clips if c["library"] == library]
        if convention:
            clips = [c for c in clips if c["convention"] == convention]

        shown = clips[:limit]
        return {
            "success": True,
            "clips": shown,
            "matched": len(clips),
            "truncated": len(clips) - len(shown),
            "total_clips": report["clips"],
            "usable_clips": report["usable"],
            "by_convention": report["by_convention"],
            "libraries": sorted({c["library"] for c in report["clip_list"]}),
            "files_scanned": report["files"],
            "files_rescanned": report["rescanned"],
            "unusable_files": report["unusable_files"],
            "duplicate_names": sorted(
                n for n in {c["name"] for c in report["clip_list"]}
                if len({c["file"] for c in report["clip_list"] if c["name"] == n}) > 1
            )[:20],
            "note": (
                "Pass a clip's `name` to apply_animation as `clip`. Names listed under "
                "duplicate_names appear in more than one file - for those, pass the file "
                "path as `clip` and the action name as `action`."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@mcp.tool
def apply_animation(
    character: Annotated[
        str,
        Field(
            description=(
                "Canonically rigged .glb. Absolute path, or a bare filename resolved "
                "against the rig output dir (e.g. 'succubus_warden_rigged.glb')."
            )
        ),
    ],
    clip: Annotated[
        str,
        Field(
            description=(
                "An action name from list_animations when it is unique, or a path to a "
                ".fbx/.glb clip file. With a bundle file, also pass `action`."
            )
        ),
    ],
    action: Annotated[
        str, Field(description="Which action inside the clip file. Required only for multi-action bundles")
    ] = "",
    output_name: Annotated[str, Field(description="Base name for the animated output (without extension)")] = "",
    root_motion: Annotated[
        bool,
        Field(description="Carry hip translation, scaled by the height ratio. Off gives an in-place cycle"),
    ] = False,
    timeout: Annotated[int, Field(description="Hard limit in seconds", ge=60, le=7200)] = 1800,
) -> dict[str, Any]:
    """Retarget an animation clip onto a canonically rigged character.

    Needs no GPU and no per-character setup: one clip drives every character
    rig_model has produced, verified on a 1.0 m dwarf, a 1.7 m base body and a
    winged succubus from the same walk.

    This is a real retarget, not a name-match. A clip keys LOCAL rotations against
    ITS OWN rest pose and bone rolls, so each bone is driven by the source's
    rest-relative delta instead. That delta is then conjugated into the character's
    own body frame, because characters do not all face the same way in world space
    - measured alignments of 88, 127 and 180 degrees across three of ours, so
    skipping it turns an arm swing into an arm raise.

    Chains outside the `mixamorig:` namespace - wings, tails, horns - are left
    undriven on purpose, so a humanoid clip cannot flail them.
    """
    try:
        _canonical_preflight()

        source = Path(character)
        if not source.is_absolute():
            source = RIG_OUTPUT_DIR / source
        if not source.is_file():
            raise FileNotFoundError(
                f"Rigged character not found: {source}. Bare names resolve against {RIG_OUTPUT_DIR}; "
                "pass an absolute path for anything else."
            )
        bones = _require_canonical(source)

        clip_path, clip_action, clip_name = _resolve_clip(clip, action, _library_report(False, timeout))
        if not clip_path.is_file():
            raise FileNotFoundError(f"Clip file not found: {clip_path}")

        if not output_name:
            output_name = f"{source.stem}_{_slugify(clip_name, 40)}"
        target = ANIM_OUTPUT_DIR / f"{output_name}.glb"
        report_path = ANIM_OUTPUT_DIR / f"{output_name}_retarget.json"

        argv = [
            "--character", str(source),
            "--clip", str(clip_path),
            "--out", str(target),
            "--report", str(report_path),
        ]
        if clip_action:
            argv += ["--action", clip_action]
        if root_motion:
            argv.append("--root-motion")

        started = time.time()
        _run_script(SEGVIGEN_PYTHON, RETARGET_DRIVER, argv, timeout, "RETARGET_OK", "Retarget")
        elapsed = round(time.time() - started, 1)

        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"Retarget reported success but wrote nothing to {target}")

        report = json.loads(report_path.read_text())
        published = _publish_animation(source, target, report, clip_name)

        return {
            "success": True,
            "output_name": output_name,
            "character": str(source),
            "clip": str(clip_path),
            "clip_name": clip_name,
            "action": report["action"],
            "animated_glb": str(target),
            "published_to": published,
            "size_bytes": target.stat().st_size,
            "elapsed_seconds": elapsed,
            "frames": report["frames"],
            "bones_driven": report["bones_mapped"],
            "source_convention": report["source_convention"],
            "frame_alignment_deg": report["frame_alignment_deg"],
            "root_motion": root_motion,
            "undriven_bones": report["unmapped_target_bones"],
            "character_bones": len(bones),
            "note": (
                "Undriven bones are the extra chains and are left at rest by design. "
                "Root motion is off by default, giving an in-place cycle to drive from "
                "a game engine's locomotion."
            ),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@mcp.tool
def free_gpu() -> dict[str, Any]:
    """Evict TRELLIS from VRAM and report free memory.

    TRELLIS stays resident between generations so repeat calls are fast. Use this
    to hand the card back to something else without running a rig job.
    """
    with _gpu_lock:
        evicted = _evict_trellis()
        # Always release cached blocks, not just when TRELLIS was resident. After a
        # large bake the allocator can hold many GB with almost nothing allocated,
        # and returning early would report success while freeing nothing.
        gc.collect()
        torch.cuda.empty_cache()
        return {"success": True, "trellis_evicted": evicted, "gpu": _vram()}


@mcp.tool
def health_check() -> dict[str, Any]:
    """Check server readiness, GPU status, and whether the rigger is installed."""
    try:
        gpu_info = {}
        if torch.cuda.is_available():
            gpu_info = {"device": torch.cuda.get_device_name(0), **_vram()}

        try:
            _rig_preflight()
            rigging = {"installed": True, "repo": str(SKINTOKENS_REPO)}
        except RuntimeError as e:
            rigging = {"installed": False, "reason": str(e)}

        outputs = list(OUTPUT_DIR.glob("*"))
        recent = sorted(outputs, key=os.path.getmtime, reverse=True)[:10]

        return {
            "status": "healthy",
            "trellis_resident": _pipeline is not None,
            "gpu": gpu_info,
            "rigging": rigging,
            "output_dir": str(OUTPUT_DIR),
            "rig_output_dir": str(RIG_OUTPUT_DIR),
            "recent_outputs": [str(p.name) for p in recent],
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


@mcp.tool
def list_outputs(
    limit: Annotated[int, Field(description="Maximum number of outputs to list", ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """List recently generated output files (3D, rigged 3D, and images)."""
    all_outputs = list(OUTPUT_DIR.glob("*")) + list(IMAGE_OUTPUT_DIR.glob("*")) + list(RIG_OUTPUT_DIR.glob("*"))
    outputs = sorted(all_outputs, key=os.path.getmtime, reverse=True)[:limit]
    files = []
    for p in outputs:
        files.append(
            {
                "name": p.name,
                "size_bytes": p.stat().st_size,
                "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
            }
        )
    return {
        "output_dir": str(OUTPUT_DIR),
        "image_output_dir": str(IMAGE_OUTPUT_DIR),
        "rig_output_dir": str(RIG_OUTPUT_DIR),
        "count": len(files),
        "files": files,
    }


_bmb_home: str | None = None


def _bmb_home_dir() -> str:
    """Absolute home directory on the remote Mac, resolved once."""
    global _bmb_home
    if _bmb_home is None:
        result = subprocess.run(
            ["ssh", BMB_HOST, 'printf %s "$HOME"'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"Could not resolve $HOME on {BMB_HOST}: {result.stderr.strip()}")
        _bmb_home = result.stdout.strip()
    return _bmb_home


def _bmb_path(path: str) -> str:
    """Expand a leading ~ against the remote home.

    Remote paths are shlex-quoted before they reach the remote shell, which stops
    it expanding ~ - without this, output lands in a literal directory named '~'.
    """
    if path == "~":
        return _bmb_home_dir()
    if path.startswith("~/"):
        return f"{_bmb_home_dir()}/{path[2:]}"
    return path


def _ssh_bmb(command: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", BMB_HOST, command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _scp_from_bmb(remote_path: str, local_path: str) -> bool:
    result = subprocess.run(
        ["scp", f"{BMB_HOST}:{remote_path}", local_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def _mflux_generate(
    prompt: str,
    model: str,
    output_name: str,
    seed: int,
    steps: int,
    height: int,
    width: int,
    quantize: int,
    guidance: float,
    image_path: str = "",
    image_strength: float = 0.4,
) -> tuple[Path, str]:
    """Run mflux on bmb and copy the result back. Raises on any failure.

    Shared by generate_image and generate_views so there is one code path from
    prompt to local PNG.
    """
    remote_dir = _bmb_path(BMB_MFLUX_OUTPUT)
    remote_output = f"{remote_dir}/{output_name}.png"
    local_output = IMAGE_OUTPUT_DIR / f"{output_name}.png"

    cmd_parts = [
        f"mkdir -p {shlex.quote(remote_dir)} &&",
        f"{shlex.quote(_bmb_path(BMB_MFLUX_PYTHON))} -m mflux.models.flux2.cli.flux2_generate",
        f"--model {shlex.quote(model)}",
        f"--quantize {quantize}",
        f"--steps {steps}",
        f"--height {height}",
        f"--width {width}",
        f"--seed {seed}",
        f"--guidance {guidance}",
        f"--output {shlex.quote(remote_output)}",
        f"--prompt {shlex.quote(prompt)}",
    ]
    if image_path:
        cmd_parts.append(f"--image-path {shlex.quote(_bmb_path(image_path))}")
        cmd_parts.append(f"--image-strength {image_strength}")

    result = _ssh_bmb(" ".join(cmd_parts), timeout=900)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else "no output"
        raise RuntimeError(f"mflux failed (exit {result.returncode}): {detail}")

    # A local file is the whole point: generate_3d consumes this path. Reporting
    # success with an unreachable path just moves the failure downstream, where it
    # surfaces as an unreadable-image error with no hint of the real cause.
    if not _scp_from_bmb(remote_output, str(local_output)):
        raise RuntimeError(
            f"Image generated on {BMB_HOST} at {remote_output}, but copying it back failed. "
            f"Check SSH/scp access to {BMB_HOST}."
        )
    if not local_output.is_file() or local_output.stat().st_size == 0:
        raise RuntimeError(f"Copy from {BMB_HOST} produced no usable file at {local_output}")

    return local_output, remote_output


# Orbit views for multi-view conditioning. A fixed seed plus exactly one changed
# clause keeps the subject consistent across views, which is what makes
# multi-image conditioning work.
#
# front and back are reliable. left and right are NOT: FLUX.2 klein returns a
# front-facing three-quarter regardless of how forcefully the profile is worded
# (tested plain and emphatic, on klein-4b and klein-9b). The two come out nearly
# identical to each other and close to the front view, so they cost ~110s each and
# add almost nothing. Hence the default set is front+back only.
VIEW_CLAUSES = {
    "front": "seen from directly in front, facing the camera",
    "back": (
        "seen from directly behind, the back of the head and body facing the camera, face not visible"
    ),
    "left": (
        "seen from the left side at exactly 90 degrees, a strict flat side profile with the body "
        "turned fully to the left edge of frame, not a three-quarter view"
    ),
    "right": (
        "seen from the right side at exactly 90 degrees, a strict flat side profile with the body "
        "turned fully to the right edge of frame, not a three-quarter view"
    ),
}

# Phrases that would fight the injected view clause and desynchronise the set.
_VIEW_CONFLICTS = (
    "seen from", "viewed from", "from behind", "facing directly", "in profile",
    "front view", "back view", "side view", "rear view", "three-quarter",
)


def _publish_view_set(paths: dict[str, Path], prompt: str) -> str:
    """File a whole orbit set into one game_assets/generated/ directory."""
    _codex_available()
    dest = CODEX_GENERATED_DIR / f"{_slugify(prompt)}_{time.strftime('%Y%m%d_%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    for view, path in paths.items():
        shutil.copy2(path, dest / f"reference_{view}.png")
    return str(dest)


def _mvadapter_preflight() -> None:
    """Fail with actionable detail if the MV-Adapter install is incomplete."""
    missing: list[str] = []
    if not MVADAPTER_PYTHON.is_file():
        missing.append(f"interpreter {MVADAPTER_PYTHON}")
    if not (MVADAPTER_REPO / "scripts" / "inference_i2mv_sdxl.py").is_file():
        missing.append(str(MVADAPTER_REPO / "scripts/inference_i2mv_sdxl.py"))
    if missing:
        raise RuntimeError(
            "MV-Adapter install is incomplete. Missing: "
            + "; ".join(missing)
            + ". Run scripts/install_mvadapter.sh to install it."
        )


@mcp.tool
def generate_orbit_views(
    image: Annotated[str, Field(description="Reference image path. A clean front view works best.")],
    output_name: Annotated[str, Field(description="Base name; views are saved as <name>_az<deg>.png")] = "",
    text: Annotated[
        str, Field(description="Short quality/style hint used alongside the reference image")
    ] = "high quality",
    steps: Annotated[int, Field(description="Inference steps", ge=1, le=100)] = 50,
    guidance_scale: Annotated[float, Field(description="Guidance scale", ge=0.0, le=20.0)] = 3.0,
    seed: Annotated[int, Field(description="Random seed", ge=0)] = 21,
    remove_bg: Annotated[
        bool, Field(description="Segment the subject out of its background before conditioning")
    ] = True,
    timeout: Annotated[int, Field(description="Hard limit in seconds", ge=60, le=3600)] = 1800,
) -> dict[str, Any]:
    """Generate 6 geometrically consistent orbit views from one reference image.

    Uses MV-Adapter, which produces true 90/270 degree profiles - something FLUX.2
    klein will not do at any prompt, and the reason generate_views defaults to
    front+back only. Views come out at azimuths 0, 45, 90, 180, 270, 315.

    Hot-swaps the GPU: TRELLIS is evicted first, then MV-Adapter runs in its own
    Python 3.11 environment and releases the card when it exits.

    Feed the returned images_json straight to generate_3d_multi_image.
    """
    try:
        _mvadapter_preflight()

        source = Path(image)
        if not source.is_absolute():
            source = IMAGE_OUTPUT_DIR / source
        if not source.is_file():
            raise FileNotFoundError(f"Reference image not found: {source}")

        if not output_name:
            output_name = f"orbit_{int(time.time())}"

        grid_path = IMAGE_OUTPUT_DIR / f"{output_name}_grid.png"
        started = time.time()

        cmd = [
            str(MVADAPTER_PYTHON), "-m", "scripts.inference_i2mv_sdxl",
            "--image", str(source),
            "--text", text,
            "--num_inference_steps", str(steps),
            "--guidance_scale", str(guidance_scale),
            "--seed", str(seed),
            "--output", str(grid_path),
        ]
        if remove_bg:
            cmd.append("--remove_bg")

        with _gpu_lock:
            evicted = _evict_trellis()
            gc.collect()
            torch.cuda.empty_cache()

            free, _total = torch.cuda.mem_get_info(0)
            if free < MVADAPTER_VRAM_REQUIRED:
                raise RuntimeError(
                    f"MV-Adapter needs ~{MVADAPTER_VRAM_REQUIRED / 1e9:.0f} GB VRAM but only "
                    f"{free / 1e9:.1f} GB is free, even after evicting TRELLIS. Something else is "
                    "holding the GPU."
                )

            proc = subprocess.Popen(
                cmd, cwd=str(MVADAPTER_REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, start_new_session=True,
            )
            try:
                log, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                raise TimeoutError(f"MV-Adapter exceeded {timeout}s and was killed.") from None

        tail = "\n".join(log.strip().splitlines()[-30:]) if log else ""
        if not grid_path.is_file() or grid_path.stat().st_size == 0:
            return {
                "success": False,
                "error": f"MV-Adapter produced no output at {grid_path} (exit {proc.returncode})",
                "log": tail,
            }

        # The script writes all views as one horizontal strip; TRELLIS wants them
        # as separate images.
        strip = Image.open(grid_path).convert("RGB")
        count = len(MVADAPTER_AZIMUTHS)
        if strip.width % count:
            return {
                "success": False,
                "error": f"Output strip is {strip.width}px wide, not divisible into {count} views.",
            }
        view_w = strip.width // count
        paths: dict[str, str] = {}
        for i, az in enumerate(MVADAPTER_AZIMUTHS):
            crop = strip.crop((i * view_w, 0, (i + 1) * view_w, strip.height))
            out = IMAGE_OUTPUT_DIR / f"{output_name}_az{az:03d}.png"
            crop.save(out)
            paths[f"az{az:03d}"] = str(out)

        reference_dir = _publish_view_set(
            {k: Path(v) for k, v in paths.items()}, f"{output_name} orbit views"
        )

        return {
            "success": True,
            "output_name": output_name,
            "views": paths,
            "images_json": json.dumps(list(paths.values())),
            "grid": str(grid_path),
            "view_size_px": view_w,
            "azimuths_deg": list(MVADAPTER_AZIMUTHS),
            "reference_dir": reference_dir,
            "trellis_evicted": evicted,
            "elapsed_seconds": round(time.time() - started, 1),
            "next_step": (
                "generate_3d_multi_image(images=<images_json>, source_prompt=<the original prompt>, "
                "asset_type='characters')"
            ),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@mcp.tool
def generate_views(
    prompt: Annotated[
        str,
        Field(
            description=(
                "Subject description WITHOUT any view or facing language - the tool supplies that per view. "
                "Describe the subject, clothing, pose, lighting and background only."
            )
        ),
    ],
    views: Annotated[
        str,
        Field(
            description=(
                "Comma-separated subset of: front, back, left, right. Default is front+back - with FLUX.2 klein "
                "the side views come back as front-facing three-quarters that duplicate the front."
            )
        ),
    ] = "front,back",
    model: Annotated[str, Field(description="Image model. flux2-klein-9b for quality, -4b for speed")] = (
        "flux2-klein-9b"
    ),
    output_name: Annotated[str, Field(description="Base name; each view is saved as <name>_<view>.png")] = "",
    seed: Annotated[
        int,
        Field(description="Shared across every view. Holding it fixed is what keeps the subject consistent", ge=0),
    ] = 7,
    steps: Annotated[int, Field(description="Inference steps per view", ge=1, le=50)] = 8,
    height: Annotated[int, Field(description="Image height in pixels", ge=256, le=2048)] = 1024,
    width: Annotated[int, Field(description="Image width in pixels", ge=256, le=2048)] = 1024,
    quantize: Annotated[int, Field(description="Quantization bits", ge=3, le=8)] = 8,
) -> dict[str, Any]:
    """Generate a consistent set of orbit views for multi-view 3D conditioning.

    From a single image TRELLIS invents everything it cannot see, so the back of a
    character is pure hallucination. Conditioning on several views fixes that, and
    this produces the set: one seed, one prompt, one clause changed per view.

    Takes several minutes - each view is a full image generation (~110s on
    flux2-klein-9b). Feed the returned images_json straight to
    generate_3d_multi_image.

    Avoid strongly asymmetric details like a patch on one arm: they tend to mirror
    between front and back, giving TRELLIS contradictory evidence.
    """
    try:
        requested = [v.strip().lower() for v in views.split(",") if v.strip()]
        unknown = [v for v in requested if v not in VIEW_CLAUSES]
        if unknown:
            return {
                "success": False,
                "error": f"Unknown view(s): {', '.join(unknown)}. Valid: {', '.join(VIEW_CLAUSES)}",
            }
        if len(requested) < 2:
            return {
                "success": False,
                "error": "Multi-view conditioning needs at least 2 views; use generate_image for a single view.",
            }

        # View language in the base prompt would fight the injected clause and
        # desynchronise the set, which is the one thing that makes this work.
        lowered = prompt.lower()
        found = [p for p in _VIEW_CONFLICTS if p in lowered]
        if found:
            return {
                "success": False,
                "error": (
                    f"The prompt contains view language ({', '.join(found)}), which would conflict with the "
                    "clause this tool adds per view. Remove it and describe only the subject."
                ),
            }

        if not output_name:
            output_name = f"views_{int(time.time())}"

        started = time.time()
        produced: dict[str, Path] = {}
        for view in requested:
            local, _remote = _mflux_generate(
                prompt=f"{prompt}, {VIEW_CLAUSES[view]}",
                model=model, output_name=f"{output_name}_{view}", seed=seed, steps=steps,
                height=height, width=width, quantize=quantize, guidance=1.0,
            )
            produced[view] = local

        reference_dir = _publish_view_set(produced, prompt)
        ordered = [str(produced[v]) for v in requested]

        return {
            "success": True,
            "output_name": output_name,
            "views": {v: str(p) for v, p in produced.items()},
            "images_json": json.dumps(ordered),
            "reference_dir": reference_dir,
            "elapsed_seconds": round(time.time() - started, 1),
            "next_step": (
                f"generate_3d_multi_image(images=<images_json>, source_prompt=<this prompt>, "
                f"source_image_model='{model}', asset_type='characters')"
            ),
            "parameters": {"seed": seed, "model": model, "steps": steps, "views": requested},
        }

    except Exception as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@mcp.tool
def generate_image(
    prompt: Annotated[str, Field(description="Text description of the image to generate")],
    model: Annotated[
        str,
        Field(description="Model to use. Recommended: flux2-klein-4b (fast, 4B) or flux2-klein-9b (quality, 9B)"),
    ] = "flux2-klein-4b",
    output_name: Annotated[str, Field(description="Base name for output file (without extension)")] = "",
    seed: Annotated[int, Field(description="Random seed for reproducibility", ge=0)] = 42,
    steps: Annotated[int, Field(description="Inference steps (fewer=faster, more=better quality)", ge=1, le=50)] = 4,
    height: Annotated[int, Field(description="Image height in pixels", ge=256, le=2048)] = 1024,
    width: Annotated[int, Field(description="Image width in pixels", ge=256, le=2048)] = 768,
    quantize: Annotated[
        int, Field(description="Quantization bits (3/4/5/6/8, lower=less VRAM, higher=quality)", ge=3, le=8)
    ] = 8,
    guidance: Annotated[
        float,
        Field(
            description=(
                "Guidance scale (higher=more prompt adherence). Distilled klein models accept only 1.0; "
                "use a flux2-klein-base-* model to vary it."
            ),
            ge=0.0,
            le=30.0,
        ),
    ] = 1.0,
    negative_prompt: Annotated[
        str,
        Field(
            description=(
                "NOT SUPPORTED by FLUX.2 - leave empty and describe what you DO want instead. "
                "Passing a value here is rejected with an explanation rather than silently dropped."
            )
        ),
    ] = "",
    image_strength: Annotated[
        float,
        Field(description="Init image influence strength (0=none, 1=full). Only used with image_path.", ge=0.0, le=1.0),
    ] = 0.4,
    image_path: Annotated[str, Field(description="Path to init image for img2img (on bmb filesystem)")] = "",
) -> dict[str, Any]:
    """Generate an image using FLUX.2 via mflux on bmb (MacBook Pro M4).

    Runs on bmb's Apple Silicon GPU via MLX. The generated image is copied back to big.
    Generation takes 10-30 seconds for flux2-klein-4b at 4 steps.
    """
    try:
        # Every model here is driven through the FLUX.2 CLI, which rejects
        # --negative-prompt outright. Silently dropping it would quietly change
        # what the caller asked for.
        if negative_prompt:
            return {
                "success": False,
                "error": (
                    "FLUX.2 does not support negative prompts. Remove negative_prompt and fold the "
                    f"exclusions into the positive prompt instead (e.g. describe the clean background "
                    f"you want rather than excluding '{negative_prompt}')."
                ),
            }

        if model in FLUX2_DISTILLED_MODELS and guidance != 1.0:
            return {
                "success": False,
                "error": (
                    f"Model '{model}' is a distilled FLUX.2 model and only accepts guidance=1.0 "
                    f"(got {guidance}). Either pass guidance=1.0, or switch to a base model "
                    f"such as 'flux2-klein-base-4b' to use a real guidance scale."
                ),
            }

        if not output_name:
            output_name = f"flux_{int(time.time())}"

        local_output, remote_output = _mflux_generate(
            prompt=prompt, model=model, output_name=output_name, seed=seed, steps=steps,
            height=height, width=width, quantize=quantize, guidance=guidance,
            image_path=image_path, image_strength=image_strength,
        )

        reference_dir = _publish_reference_image(local_output, prompt)

        return {
            "success": True,
            "output_name": output_name,
            "local_path": str(local_output),
            "remote_path": remote_output,
            "reference_dir": reference_dir,
            "next_step": (
                f"generate_3d(image='{local_output}', source_prompt=<this prompt>, "
                f"source_image_model='{model}') to turn this into a 3D mesh"
            ),
            "parameters": {
                "model": model,
                "seed": seed,
                "steps": steps,
                "height": height,
                "width": width,
                "quantize": quantize,
                "guidance": guidance,
            },
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Image generation timed out (10 minute limit)",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


@mcp.tool
def list_image_models() -> dict[str, Any]:
    """List available FLUX/mflux image generation models on bmb."""
    return {
        "models": [
            {"id": "flux2-klein-4b", "params": "4B", "vram": "~8GB", "speed": "fast", "recommended": True},
            {"id": "flux2-klein-9b", "params": "9B", "vram": "~16GB", "speed": "medium", "recommended": True},
            {"id": "flux2-klein-9b-kv", "params": "9B", "vram": "~16GB", "speed": "medium", "recommended": False},
            {"id": "flux2-klein-base-4b", "params": "4B", "vram": "~8GB", "speed": "fast", "recommended": False},
            {"id": "flux2-klein-base-9b", "params": "9B", "vram": "~16GB", "speed": "medium", "recommended": False},
            {"id": "dev", "params": "12B", "vram": "~24GB", "speed": "slow", "recommended": False},
            {"id": "schnell", "params": "12B", "vram": "~24GB", "speed": "fast", "recommended": False},
            {"id": "qwen", "params": "varies", "vram": "varies", "speed": "medium", "recommended": False},
            {"id": "z-image", "params": "varies", "vram": "varies", "speed": "medium", "recommended": False},
            {"id": "z-image-turbo", "params": "varies", "vram": "varies", "speed": "fast", "recommended": False},
            {"id": "ernie-image", "params": "varies", "vram": "varies", "speed": "medium", "recommended": False},
            {"id": "ernie-image-turbo", "params": "varies", "vram": "varies", "speed": "fast", "recommended": False},
            {"id": "ideogram4", "params": "varies", "vram": "varies", "speed": "medium", "recommended": False},
        ],
        "host": BMB_HOST,
        "backend": "mflux (MLX on Apple Silicon)",
        "quantize_options": MFLUX_QUANTIZE_OPTIONS,
        "notes": (
            "flux2-klein-4b is the best balance of speed and quality. "
            "Use quantize=8 for best quality, quantize=4 for lower VRAM."
        ),
    }


def main():
    mcp.run(transport="sse", host="0.0.0.0", port=9786)


if __name__ == "__main__":
    main()
