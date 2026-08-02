from __future__ import annotations

import base64
import gc
import io
import json
import os
import re
import shlex
import shutil
import signal
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

# Shared asset library on codex_fs (NFS export from 'three', autofs-mounted).
# Local OUTPUT_DIR stays the working area; these are the durable locations.
CODEX_GEN_AI_DIR = Path(os.environ.get("CODEX_GEN_AI_DIR", "/mnt/codex_fs/game_assets/models/gen_ai"))
CODEX_GENERATED_DIR = Path(os.environ.get("CODEX_GENERATED_DIR", "/mnt/codex_fs/game_assets/generated"))
ASSET_TYPES = ("characters", "props", "environments")

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
    seed: Annotated[int, Field(description="Random seed for reproducibility", ge=0)] = 42,
    output_name: Annotated[str, Field(description="Base name for output files (without extension)")] = "",
    ss_steps: Annotated[
        int, Field(description="Sparse structure sampler steps (fewer=faster, more=better detail)", ge=1, le=100)
    ] = 12,
    ss_cfg_strength: Annotated[
        float, Field(description="Sparse structure CFG strength (higher=more prompt adherence)", ge=1.0, le=20.0)
    ] = 7.5,
    slat_steps: Annotated[
        int, Field(description="SLAT sampler steps (fewer=faster, more=better texture)", ge=1, le=100)
    ] = 12,
    slat_cfg_strength: Annotated[
        float, Field(description="SLAT CFG strength (higher=more prompt adherence)", ge=1.0, le=20.0)
    ] = 3.0,
    simplify: Annotated[
        float, Field(description="Mesh simplification ratio (0=none, 0.95=aggressive)", ge=0.0, le=1.0)
    ] = 0.95,
    fill_holes: Annotated[bool, Field(description="Fill holes in the generated mesh")] = True,
    fill_holes_max_size: Annotated[
        float, Field(description="Maximum hole area to fill (relative to bounding box)", ge=0.0, le=1.0)
    ] = 0.04,
    texture_size: Annotated[int, Field(description="Output texture resolution in pixels", ge=256, le=4096)] = 1024,
    render_resolution: Annotated[
        int,
        Field(
            description=(
                "Resolution of the renders the texture is baked FROM. This is the real detail ceiling - "
                "texture_size above this only upsamples. Raising to 2048 needs evict_trellis_for_bake=true."
            ),
            ge=256,
            le=2048,
        ),
    ] = 1024,
    nviews: Annotated[
        int,
        Field(
            description=(
                "Number of views baked from. More views means better coverage of hidden areas "
                "(armpits, crotch, under chin) and fewer seams. VRAM scales linearly with this."
            ),
            ge=8,
            le=300,
        ),
    ] = 100,
    lambda_tv: Annotated[
        float,
        Field(
            description="Total-variation smoothing on the baked texture. Lower keeps it sharper, higher blurs.",
            ge=0.0,
            le=0.1,
        ),
    ] = 0.01,
    target_height_m: Annotated[
        float,
        Field(
            description=(
                "Scale the exported mesh to this height in metres (e.g. 1.75 for an adult human). "
                "0 leaves TRELLIS's normalized unit-cube scale, which is ~1 m regardless of subject."
            ),
            ge=0.0,
            le=1000.0,
        ),
    ] = 0.0,
    evict_trellis_for_bake: Annotated[
        bool,
        Field(
            description=(
                "Release TRELLIS from VRAM before baking, freeing ~6 GB. Required for render_resolution=2048 "
                "on a 24 GB card. Costs a ~30s reload on the next generation."
            ),
        ),
    ] = False,
    asset_type: Annotated[
        str,
        Field(description="Which gen_ai folder to publish into: characters, props, or environments"),
    ] = "characters",
    source_prompt: Annotated[
        str,
        Field(
            description=(
                "The prompt the reference image was generated from. Recorded in metadata.json - "
                "without it the asset's provenance is unrecoverable later."
            )
        ),
    ] = "",
    source_image_model: Annotated[
        str, Field(description="Image model that produced the reference (e.g. flux2-klein-9b)")
    ] = "",
    preprocess_image: Annotated[bool, Field(description="Auto-remove background and crop to subject")] = True,
    formats: Annotated[
        str,
        Field(description="Output formats, comma-separated: mesh,gaussian,radiance_field"),
    ] = "mesh,gaussian",
) -> dict[str, Any]:
    """Generate a 3D asset from a single image using TRELLIS.

    Returns paths to generated .glb (textured mesh) and .ply (Gaussian splat) files.
    Generation takes 30-60 seconds on an RTX 3090.

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

        img = _decode_image(image)

        if not output_name:
            output_name = f"trellis_{int(time.time())}"

        started = time.time()

        format_list = [f.strip() for f in formats.split(",") if f.strip()]

        with _gpu_lock:
            pipeline = _get_pipeline()
            outputs = pipeline.run(
                img,
                seed=seed,
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
            "source_image": image if os.path.isfile(image) else None,
            "elapsed_seconds": round(time.time() - started, 1),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if not source_prompt:
            metadata["_provenance_warning"] = (
                "No source_prompt was supplied, so how this asset was made cannot be reconstructed. "
                "Pass source_prompt and source_image_model to generate_3d."
            )

        published = _publish_asset(
            saved["files"], output_name, asset_type, metadata,
            image if os.path.isfile(image) else "",
        )

        return {
            "success": True,
            "output_name": output_name,
            "files": saved["files"],
            "published_to": published,
            "geometry": saved["geometry"],
            "next_step": f"rig_model(mesh='{output_name}.glb') to add a skeleton and skin weights",
            "parameters": {
                "seed": seed,
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
        }

    except Exception as e:
        # Evict rather than leave a half-run pipeline (or an OOM'd allocator)
        # holding the card.
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


def _publish_rig(
    source: Path,
    rigged: Path,
    elapsed: float,
    num_beams: int,
    use_transfer: bool,
    use_postprocess: bool,
    use_skeleton: bool,
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
            "num_beams": num_beams,
            "use_transfer": use_transfer,
            "use_postprocess": use_postprocess,
            "use_skeleton": use_skeleton,
            "elapsed_seconds": elapsed,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "bone_naming": "generic (bone_0..bone_N) - not Mixamo or UE5 conventions",
        }
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
        return str(asset_dir)
    return None


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
    use_skeleton: Annotated[
        bool, Field(description="Input already has a skeleton: predict skin weights only, skip skeleton generation")
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
    timeout: Annotated[int, Field(description="Hard limit in seconds for the rig run", ge=60, le=7200)] = 1800,
) -> dict[str, Any]:
    """Generate a skeleton and skin weights for a 3D mesh using SkinTokens/TokenRig.

    Hot-swaps the GPU: TRELLIS is evicted from VRAM first, then the rigger runs
    in its own Python 3.11 environment and releases the card when it exits.
    The next generate_3d call reloads TRELLIS automatically.

    Output is always .glb. After importing to Blender, delete the
    `glTF_not_exported` node.
    """
    try:
        _rig_preflight()

        # Relative names resolve against the TRELLIS output dir so a generate_3d
        # result can be passed straight through.
        source = Path(mesh)
        if not source.is_absolute():
            source = OUTPUT_DIR / source
        if not source.is_file():
            raise FileNotFoundError(f"Input mesh not found: {source}")
        if source.suffix.lower() not in RIG_INPUT_SUFFIXES:
            raise ValueError(f"Unsupported input format '{source.suffix}'. Supported: {', '.join(RIG_INPUT_SUFFIXES)}")

        if not output_name:
            output_name = f"{source.stem}_rigged"
        target = RIG_OUTPUT_DIR / f"{output_name}.glb"

        cmd = [
            str(SKINTOKENS_PYTHON),
            "demo.py",
            "--input", str(source),
            "--output", str(target),
            "--num_beams", str(num_beams),
            "--top_k", str(top_k),
            "--top_p", str(top_p),
            "--temperature", str(temperature),
            "--repetition_penalty", str(repetition_penalty),
        ]
        if use_transfer:
            cmd.append("--use_transfer")
        if use_postprocess:
            cmd.append("--use_postprocess")
        if use_skeleton:
            cmd.append("--use_skeleton")

        started = time.time()

        with _gpu_lock:
            evicted = _evict_trellis()

            # demo.py resolves bpy_server.py, checkpoints and configs relative to
            # the repo root, so it must run with cwd there.
            proc = subprocess.Popen(
                cmd,
                cwd=str(SKINTOKENS_REPO),
                env=_rig_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            try:
                log, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                _kill_orphan_bpy_server()
                raise TimeoutError(
                    f"Rigging exceeded {timeout}s and was killed. "
                    f"Lower num_beams (currently {num_beams}) or raise timeout."
                ) from None

        elapsed = round(time.time() - started, 1)
        tail = "\n".join(log.strip().splitlines()[-40:]) if log else ""

        # demo.py prints "[Error] ..." on an export failure but still exits 0, so
        # the exit code alone does not mean the rig succeeded. The written file is
        # the only trustworthy signal.
        if not target.is_file() or target.stat().st_size == 0:
            return {
                "success": False,
                "error": f"Rigging produced no output at {target} (exit code {proc.returncode}, {elapsed}s)",
                "log": tail,
            }

        published = _publish_rig(source, target, elapsed, num_beams, use_transfer, use_postprocess, use_skeleton)

        return {
            "success": True,
            "output_name": output_name,
            "input": str(source),
            "rigged_glb": str(target),
            "published_to": published,
            "size_bytes": target.stat().st_size,
            "elapsed_seconds": elapsed,
            "trellis_evicted": evicted,
            "geometry": _glb_dimensions(target),
            "parameters": {
                "num_beams": num_beams,
                "use_transfer": use_transfer,
                "use_postprocess": use_postprocess,
                "use_skeleton": use_skeleton,
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

        if negative_prompt:
            cmd_parts.append(f"--negative-prompt {shlex.quote(negative_prompt)}")
        if image_path:
            cmd_parts.append(f"--image-path {shlex.quote(_bmb_path(image_path))}")
            cmd_parts.append(f"--image-strength {image_strength}")

        full_cmd = " ".join(cmd_parts)

        result = _ssh_bmb(full_cmd, timeout=600)

        if result.returncode != 0:
            return {
                "success": False,
                "error": f"mflux failed (exit {result.returncode})",
                "stderr": result.stderr[-2000:] if result.stderr else "",
                "stdout": result.stdout[-2000:] if result.stdout else "",
            }

        # A local file is the whole point: generate_3d consumes this path. Reporting
        # success with an unreachable path just moves the failure downstream, where
        # it surfaces as an unreadable-image error with no hint of the real cause.
        if not _scp_from_bmb(remote_output, str(local_output)):
            return {
                "success": False,
                "error": (
                    f"Image generated on {BMB_HOST} at {remote_output}, but copying it back failed. "
                    f"Check SSH/scp access to {BMB_HOST}."
                ),
                "remote_path": remote_output,
            }

        if not local_output.is_file() or local_output.stat().st_size == 0:
            return {
                "success": False,
                "error": f"Copy from {BMB_HOST} produced no usable file at {local_output}",
                "remote_path": remote_output,
            }

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
