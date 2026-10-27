"""Kimodo text-to-motion tools: text prompts -> motion, retargeted onto a canonically rigged GLB.

This process imports no torch/kimodo. Generation runs in a per-job worker subprocess under a gpu-tenant lease
(golem_mcp.gpu); retargeting runs in the bpy venv (CPU) via `scripts/retarget_animation.py`.
"""

import base64
import contextlib
import functools
import hashlib
import importlib.util
import json
import multiprocessing
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
import anyio.to_thread
from fastmcp import Context
from pydantic import BaseModel, Field

from golem_mcp.app import mcp
from golem_mcp.gpu import GPU_TENANT, GpuJobError, run_gpu_job, tenant_status
from golem_mcp.job_retry import RetryPolicy, run_with_retries
from golem_mcp.paths import RETARGET_DRIVER, SEGVIGEN_PYTHON

KIMODO_OUTPUT_DIR = Path(os.environ.get("KIMODO_OUTPUT_DIR", "/home/ladvien/kimodo/output"))
KIMODO_CACHE_DIR = Path(os.environ.get("KIMODO_CACHE_DIR", "/home/ladvien/kimodo/cache"))
# LLM2Vec encoder checkpoints (McGill-NLP adapters + the ungated NousResearch Llama-3 mirror), laid out as
# <dir>/<hf repo id>/; kimodo's llm2vec wrapper reads this env var in the worker.
TEXT_ENCODERS_DIR = Path(os.environ.get("TEXT_ENCODERS_DIR", "/home/ladvien/kimodo/text_encoders"))
# Raw generative output is published only under /mnt/codex_fs/models/ (host convention).
KIMODO_RAW_PUBLISH_DIR = Path(os.environ.get("KIMODO_RAW_PUBLISH_DIR", "/mnt/codex_fs/models/kimodo"))
EMBEDDING_CACHE_DIR = KIMODO_CACHE_DIR / "embeddings"

MOTION_VRAM_REQUIRED = 2e9  # peak 1.33 GiB over 210 jobs, 2026-10-12 (the 8B text encoder runs on the CPU)
KIMODO_MODEL_KEY = "kimodo-soma-rp-v1.1"
KIMODO_COMMIT = "58e781898b3d7e328a676a75d3e338c45dce3ad9"
MIN_SEGMENT_DURATION_S = 1.0
MAX_SEGMENT_DURATION_S = 10.0  # the model is trained on <=10 s sequences
MAX_SEGMENTS = 6
MAX_NUM_SAMPLES = 4
MIN_DIFFUSION_STEPS = 50
MAX_DIFFUSION_STEPS = 200
DEFAULT_DIFFUSION_STEPS = 100
MOTION_FPS = 30  # the worker refuses any other model fps via model.fps
MIN_CFG_WEIGHT = 0.0
MAX_CFG_WEIGHT = 10.0
DEFAULT_CFG_WEIGHT = 2.0  # upstream default
MIN_TRANSITION_FRAMES = 1
MAX_TRANSITION_FRAMES = int(MIN_SEGMENT_DURATION_S * MOTION_FPS / 2)  # sliced off the previous segment's end
DEFAULT_TRANSITION_FRAMES = 5  # upstream default
MAX_ROOT_WAYPOINTS = 32
MIN_HEADING_DEG = -180.0
MAX_HEADING_DEG = 180.0
MAX_CHARACTER_BYTES = 64 * 1024 * 1024
GLB_MAGIC = b"glTF"
SLUG_MAX_CHARS = 48
RETARGET_TIMEOUT_S = 900
LOG_TAIL_LINES = 40
WORKER_MARKER = "KIMODO_OK"
RETARGET_MARKER = "RETARGET_OK"
RETARGET_SOURCE_MAP = "soma"
WORKER_ENV = {
    "TEXT_ENCODER_DEVICE": "cpu",
    "TEXT_ENCODERS_DIR": str(TEXT_ENCODERS_DIR),
    "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
}

# Retrying a generation that failed for a reason time can fix (golem_mcp.job_retry): an OOM kill while another
# tenant held big's RAM, a VRAM refusal, a queue timeout. Four attempts with a 60 s, 120 s, 240 s backoff spans the
# few minutes another tenant's job takes to finish, which is what every OOM in the 2026-10-27 report waited behind.
MOTION_MAXIMUM_ATTEMPTS = 4
MOTION_FIRST_BACKOFF_S = 60.0
MOTION_BACKOFF_FACTOR = 2.0
# After an OOM kill, the retry waits for this much free RAM, polling every MOTION_MEMORY_POLL_S for at most
# MOTION_MEMORY_WAIT_LIMIT_S. Half an hour is longer than any one GPU job on big runs.
MOTION_MEMORY_WAIT_LIMIT_S = 1800.0
MOTION_MEMORY_POLL_S = 30.0
# PROPOSED (unmeasured): the RAM a generation needs free on big before a retry is worth starting. 16 GiB is the
# 8B text encoder's own size (the comment at _run_worker), loaded on the CPU on a cache miss. Replace with the
# measured cache-miss peak_rss_gib x 1.25 from worker_report.json.
MOTION_RAM_REQUIRED_GIB = 16.0
# How often the MCP client hears that a long generation is still alive, and where it stands.
MOTION_PROGRESS_HEARTBEAT_S = 10.0

KIMODO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
KIMODO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class MotionSegment(BaseModel):
    text: Annotated[str, Field(min_length=1, description="One behaviour, e.g. 'A person walks forward.'")]
    duration_s: Annotated[float, Field(ge=MIN_SEGMENT_DURATION_S, le=MAX_SEGMENT_DURATION_S)]


class RootWaypoint(BaseModel):
    time_s: Annotated[float, Field(
        ge=0.0, allow_inf_nan=False,
        description="Seconds from the start of the whole motion (all segments concatenated)",
    )]
    x_m: Annotated[float, Field(
        allow_inf_nan=False, description="Kimodo world X in metres; the motion starts at the origin",
    )]
    z_m: Annotated[float, Field(
        allow_inf_nan=False,
        description="Kimodo world Z in metres; +Z is the character's forward direction at start_heading_deg=0",
    )]
    heading_deg: Annotated[float | None, Field(
        ge=MIN_HEADING_DEG, le=MAX_HEADING_DEG, allow_inf_nan=False,
        description="Body heading at this waypoint (0 = facing +Z; positive angles turn the character toward "
                    "+X, its left at heading 0). Give it on every waypoint or on none",
    )] = None


def _root_path_job(root_path: list[RootWaypoint] | None, segments: list[MotionSegment]) -> list[dict[str, Any]]:
    """Validate waypoints against the motion length and convert to the worker's job-JSON form."""
    if not root_path:
        return []
    total_frames = sum(int(s.duration_s * MOTION_FPS) for s in segments)  # same truncation as the worker
    frames = [round(w.time_s * MOTION_FPS) for w in root_path]
    if any(b <= a for a, b in zip(frames, frames[1:])):
        raise ValueError("root_path times must be strictly increasing, at least 1/30 s apart")
    for i, (w, f) in enumerate(zip(root_path, frames)):
        if f >= total_frames:
            raise ValueError(
                f"root_path waypoint {i} at {w.time_s}s is frame {f}, but the motion has only "
                f"{total_frames} frames ({total_frames / MOTION_FPS:.2f}s)"
            )
    if len({w.heading_deg is None for w in root_path}) > 1:
        raise ValueError("root_path heading_deg must be given on every waypoint or on none")
    return [
        {"frame": f, "x_m": w.x_m, "z_m": w.z_m, "heading_deg": w.heading_deg}
        for w, f in zip(root_path, frames)
    ]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:SLUG_MAX_CHARS].strip("_")
    if not slug:
        raise ValueError("output_name / first segment text yields an empty file name")
    return slug


def _load_character(character_path: str, character_base64: str) -> tuple[bytes, str]:
    if bool(character_path) == bool(character_base64):
        raise ValueError("pass exactly one of character_path or character_base64")
    if character_path:
        p = Path(character_path)
        if not p.is_absolute():
            raise ValueError(f"character_path must be absolute: {character_path!r}")
        if not p.is_file():
            raise ValueError(f"character_path does not exist or is not a file: {character_path}")
        if p.suffix.lower() != ".glb":
            raise ValueError(f"character_path must be a .glb, got {p.suffix!r}")
        size = p.stat().st_size
        if size > MAX_CHARACTER_BYTES:
            raise ValueError(f"character is {size} bytes; limit is {MAX_CHARACTER_BYTES}")
        data, source = p.read_bytes(), str(p)
    else:
        b64 = re.sub(r"^data:[^,]*;base64,", "", character_base64.strip())
        # 4 base64 chars carry 3 bytes; reject before decoding.
        if len(b64) * 3 // 4 > MAX_CHARACTER_BYTES:
            raise ValueError(f"character_base64 decodes to more than {MAX_CHARACTER_BYTES} bytes")
        try:
            data = base64.b64decode(b64, validate=True)
        except ValueError as e:
            raise ValueError(f"character_base64 is not valid base64: {e}") from e
        source = "base64"
    if len(data) > MAX_CHARACTER_BYTES:
        raise ValueError(f"character is {len(data)} bytes; limit is {MAX_CHARACTER_BYTES}")
    if data[:4] != GLB_MAGIC:
        raise ValueError("character is not a binary glTF (.glb): missing 'glTF' magic bytes")
    return data, source


def _preflight() -> None:
    missing = [
        f"{name}={path}"
        for name, path in (
            ("SEGVIGEN_PYTHON", SEGVIGEN_PYTHON), ("RETARGET_DRIVER", RETARGET_DRIVER), ("GPU_TENANT", GPU_TENANT),
        )
        if not path.exists()
    ]
    if not KIMODO_RAW_PUBLISH_DIR.parent.is_dir():
        missing.append(f"KIMODO_RAW_PUBLISH_DIR parent {KIMODO_RAW_PUBLISH_DIR.parent} (NFS not mounted?)")
    if missing:
        raise RuntimeError("missing prerequisites: " + "; ".join(missing))
    KIMODO_RAW_PUBLISH_DIR.mkdir(exist_ok=True)


def _tail(text: str) -> str:
    return "\n".join(text.splitlines()[-LOG_TAIL_LINES:])


def _run_worker(
    job_json: Path, report: Path, job_dir: Path, stem: str, timeout: int,
    on_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    # One job at a time on the card (two would each load a 16 GB encoder and could OOM the host): run_gpu_job serialises.
    try:
        proc = run_gpu_job(
            [sys.executable, "-m", "golem_mcp.motion_worker", "--job", str(job_json), "--report", str(report)],
            label="Kimodo generation", note=f"animate_mesh {stem}", need_bytes=MOTION_VRAM_REQUIRED,
            timeout_s=timeout, env={**os.environ, **WORKER_ENV}, on_status=on_status,
        )
    except GpuJobError as error:
        # An OOM-killed job's directory keeps the log of what it printed before it died: without it the retry
        # report says "OOM-killed" and nobody can see how far the job got.
        (job_dir / "worker.log").write_text(f"{error.stdout}\n--- stderr ---\n{error.stderr}")
        raise
    log = f"{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    (job_dir / "worker.log").write_text(log)
    if WORKER_MARKER in proc.stdout and report.exists():
        result: dict[str, Any] = json.loads(report.read_text())
        return result
    raise RuntimeError(f"worker failed (exit {proc.returncode})\n{_tail(log)}".rstrip())


def _retarget(
    job_dir: Path, slug: str, index: int, bvh: str, root_motion: bool, hip_bob: bool,
) -> tuple[Path, dict[str, Any]]:
    out = job_dir / f"{slug}_{index:02d}.glb"
    report = job_dir / f"{slug}_{index:02d}_retarget.json"
    cmd = [
        str(SEGVIGEN_PYTHON), str(RETARGET_DRIVER),
        "--character", str(job_dir / "character.glb"), "--clip", bvh, "--out", str(out),
        "--source-map", RETARGET_SOURCE_MAP, "--report", str(report),
    ]
    if root_motion:
        cmd.append("--root-motion")
    elif hip_bob:
        cmd.append("--hip-bob")
    try:
        proc = subprocess.run(cmd, cwd=job_dir, capture_output=True, text=True, timeout=RETARGET_TIMEOUT_S)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"retarget of sample {index} exceeded {RETARGET_TIMEOUT_S}s") from e
    log = f"$ {' '.join(cmd)}\n{proc.stdout}\n--- stderr ---\n{proc.stderr}\n"
    with (job_dir / "retarget.log").open("a") as f:
        f.write(log)
    if RETARGET_MARKER not in proc.stdout or not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(
            f"retarget of sample {index} failed (exit {proc.returncode}); the character must be a "
            f"canonical mixamorig:* rig\n{_tail(log)}"
        )
    return out, json.loads(report.read_text())


@dataclass(frozen=True)
class _Request:
    """The validated parts of an `animate_mesh` call that every attempt (one seed) shares."""

    segments: list[dict[str, Any]]
    root_path_job: list[dict[str, Any]]
    num_samples: int
    diffusion_steps: int
    text_cfg_weight: float
    constraint_cfg_weight: float
    transition_frames: int
    start_heading_deg: float
    root_motion: bool
    hip_bob: bool
    timeout: int
    self_intersection: Literal["off", "score", "repair"]
    contour_limit_cm: float
    cloth_materials: list[str]


def _assess_all(samples: list[dict[str, Any]], request: _Request) -> None:
    """Adds `self_intersection` to every sample: its glb checked (and, in repair mode, repaired) by
    `motion_gate.assess_sample`, one process per sample (a fresh interpreter each: this server has threads, and forking it is
    not safe). A sample whose assessment raises gets `{"passed": None, "error": ...}` and does not fail the job."""
    if request.self_intersection == "off":
        for s in samples:
            s["self_intersection"] = {"passed": None, "skipped": "self_intersection is off"}
        return
    from skinclip.intersect import CheckSettings

    from golem_mcp.motion_gate import assess_sample

    settings = CheckSettings(
        contour_limit_m=request.contour_limit_cm / 100.0, cloth_materials=tuple(request.cloth_materials)
    )
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=len(samples), mp_context=context) as pool:
        futures = [
            pool.submit(assess_sample, Path(s["animated_glb"]), settings, request.self_intersection) for s in samples
        ]
        for s, future in zip(samples, futures):
            try:
                s["self_intersection"] = future.result()
            except Exception as e:  # noqa: BLE001 - one sample's failure must not lose the others
                s["self_intersection"] = {"passed": None, "error": f"{type(e).__name__}: {e}"}


def _needs_reroll(samples: list[dict[str, Any]], mode: str) -> bool:
    """A re-roll helps when the samples were assessed and every one of them crosses; a sample that could not be assessed
    (`passed` null) says nothing about the seed."""
    if mode == "off":
        return False
    verdicts = [s["self_intersection"]["passed"] for s in samples]
    return not any(v is True for v in verdicts) and any(v is False for v in verdicts)


def _attempt(
    seed: int, request: _Request, slug: str, data: bytes, source: str, job_dirs: list[Path],
    *, on_status: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """One seed: generate, retarget every sample, assess them, write `metadata.json` and publish the job."""
    t0 = time.time()
    stem = f"{slug}_{time.strftime('%Y%m%d_%H%M%S')}"
    job_dir = KIMODO_OUTPUT_DIR / stem
    job_dir.mkdir(exist_ok=False)
    job_dirs.append(job_dir)
    (job_dir / "character.glb").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()

    job_json = job_dir / "job.json"
    job_json.write_text(json.dumps({
        "segments": request.segments, "num_samples": request.num_samples, "seed": seed,
        "diffusion_steps": request.diffusion_steps, "model_key": KIMODO_MODEL_KEY, "clip_stem": slug,
        "out_dir": str(job_dir), "embedding_cache_dir": str(EMBEDDING_CACHE_DIR),
        "text_cfg_weight": request.text_cfg_weight, "constraint_cfg_weight": request.constraint_cfg_weight,
        "transition_frames": request.transition_frames, "start_heading_deg": request.start_heading_deg,
        "root_path": request.root_path_job,
    }, indent=2))
    report = _run_worker(job_json, job_dir / "worker_report.json", job_dir, stem, request.timeout, on_status)

    samples = []
    for s in report["samples"]:
        glb, rt = _retarget(job_dir, slug, s["index"], s["bvh"], request.root_motion, request.hip_bob)
        samples.append({
            "index": s["index"], "animated_glb": str(glb), "bvh": s["bvh"], "npz": s["npz"],
            "frames": s["frames"], "bones_mapped": rt["bones_mapped"],
            "frame_alignment_deg": rt["frame_alignment_deg"],
            "rest_correction_deg": rt["rest_correction_deg"],
            "crossed_hand_frames": rt["crossed_hand_frames"],
            "min_hand_separation_pct_hip_width": rt["min_hand_separation_pct_hip_width"],
        })
    _assess_all(samples, request)

    elapsed = round(time.time() - t0, 1)
    (job_dir / "metadata.json").write_text(json.dumps({
        "tool": "Kimodo",
        "model": "Kimodo-SOMA-RP-v1.1",
        "model_license": "NVIDIA Open Model License",
        "text_encoder": "LLM2Vec-Meta-Llama-3-8B-Instruct (Meta Llama 3 Community License)",
        "kimodo_commit": KIMODO_COMMIT,
        "segments": request.segments, "seed": seed, "diffusion_steps": request.diffusion_steps,
        "num_samples": request.num_samples, "root_motion": request.root_motion, "hip_bob": request.hip_bob,
        "text_cfg_weight": request.text_cfg_weight, "constraint_cfg_weight": request.constraint_cfg_weight,
        "transition_frames": request.transition_frames, "start_heading_deg": request.start_heading_deg,
        "root_path": request.root_path_job,
        "self_intersection_mode": request.self_intersection, "contour_limit_cm": request.contour_limit_cm,
        "cloth_materials": request.cloth_materials,
        "character_source": source, "character_sha256": sha,
        "samples": samples,
        "encoder_loaded": report["encoder_loaded"],
        "elapsed_seconds": elapsed,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }, indent=2))

    published = KIMODO_RAW_PUBLISH_DIR / stem
    shutil.copytree(job_dir, published)
    return {
        "job_dir": str(job_dir), "published_to": str(published), "seed": seed, "samples": samples,
        "encoder_loaded": report["encoder_loaded"],
    }


class _LatestStatus:
    """The most recent status line from the worker thread, read by the progress heartbeat on the event loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text = "starting"

    def set(self, text: str) -> None:
        with self._lock:
            self._text = text

    def get(self) -> str:
        with self._lock:
            return self._text


@mcp.tool
async def animate_mesh(
    segments: Annotated[
        list[MotionSegment],
        Field(min_length=1, max_length=MAX_SEGMENTS, description="Consecutive behaviours; each <=10 s"),
    ],
    character_path: Annotated[str, Field(description="Absolute path on this host to a canonically rigged .glb")] = "",
    character_base64: Annotated[str, Field(description="Base64 of the rigged .glb (alternative to path)")] = "",
    output_name: Annotated[str, Field(description="File-name stem; defaults to the first prompt")] = "",
    num_samples: Annotated[int, Field(ge=1, le=MAX_NUM_SAMPLES, description="Independent variations")] = 1,
    seed: Annotated[int | None, Field(ge=0, le=2**31 - 1, description="Random if omitted")] = None,
    diffusion_steps: Annotated[
        int, Field(ge=MIN_DIFFUSION_STEPS, le=MAX_DIFFUSION_STEPS, description="Denoising steps")
    ] = DEFAULT_DIFFUSION_STEPS,
    text_cfg_weight: Annotated[float, Field(
        ge=MIN_CFG_WEIGHT, le=MAX_CFG_WEIGHT, allow_inf_nan=False,
        description="How strongly the prompt steers the motion. Higher follows the text more literally "
                    "but looks less natural",
    )] = DEFAULT_CFG_WEIGHT,
    constraint_cfg_weight: Annotated[float, Field(
        ge=MIN_CFG_WEIGHT, le=MAX_CFG_WEIGHT, allow_inf_nan=False,
        description="How strongly root_path is enforced; ignored without root_path",
    )] = DEFAULT_CFG_WEIGHT,
    transition_frames: Annotated[int, Field(
        ge=MIN_TRANSITION_FRAMES, le=MAX_TRANSITION_FRAMES,
        description="Frames (30 per second) used to blend consecutive segments; only matters with 2+ segments",
    )] = DEFAULT_TRANSITION_FRAMES,
    start_heading_deg: Annotated[float, Field(
        ge=MIN_HEADING_DEG, le=MAX_HEADING_DEG, allow_inf_nan=False,
        description="Initial body heading in degrees (0 = facing +Z; positive angles turn the character "
                    "toward +X, its left at heading 0)",
    )] = 0.0,
    root_path: Annotated[list[RootWaypoint] | None, Field(
        max_length=MAX_ROOT_WAYPOINTS,
        description="Optional root trajectory the character must pass through (metres, Kimodo world frame, "
                    "motion starts at the origin). Requires root_motion=true. The path is for Kimodo's ~1.7 m "
                    "skeleton; the retargeter scales root motion by the hips-height ratio of the character to "
                    "Kimodo's skeleton, so a 3 m path moves a 1 m character about 1.7 m. The saved BVH/NPZ are "
                    "unscaled",
    )] = None,
    root_motion: Annotated[bool, Field(description="Carry hip translation (default: in place)")] = False,
    hip_bob: Annotated[bool, Field(
        description="In place but keeping the pelvis's vertical bob; ignored when root_motion is set",
    )] = True,
    return_base64: Annotated[bool, Field(description="Also return each animated GLB as base64")] = False,
    self_intersection: Annotated[Literal["off", "score", "repair"], Field(
        description="Check every sample for its surface passing through itself (a hand through the torso, a knee "
                    "through the other leg). score: report only. repair: also turn the arms and legs of a failing "
                    "sample off the body (rotation keys only; the original stays beside it as "
                    "<name>_unrepaired.glb) and check again. off: skip. The humanoid rig must be UE5 or mixamo named",
    )] = "repair",
    max_rerolls: Annotated[int, Field(
        ge=0, le=5,
        description="Extra attempts with seed + 100 * n while no sample is clean (each costs a generation, about "
                    "1-3 min of GPU). 0 (default) generates once",
    )] = 0,
    contour_limit_cm: Annotated[float, Field(
        ge=0.5, le=50, allow_inf_nan=False,
        description="A frame fails when the contour where its triangles cross is longer than this (default 4 cm, "
                    "about a 1.3 cm poke)",
    )] = 4.0,
    cloth_materials: Annotated[list[str], Field(
        description="Names of loose-cloth materials: two triangles of one of them crossing is contact, not a "
                    "limb through the body",
    )] = [],  # noqa: B006 - pydantic copies the default per call
    timeout: Annotated[
        int,
        Field(
            ge=300, le=7200,
            description="Seconds generation may run once the GPU is granted; waiting for the GPU adds up to 20 min",
        ),
    ] = 1800,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Generate motion from text with Kimodo and retarget it onto a rigged GLB character.

    Returns animated GLB paths (plus the raw BVH/NPZ) under a job directory that is also
    published to /mnt/codex_fs/models/kimodo/. Each sample carries a `self_intersection` assessment; `passed` and
    `best_sample` summarise the last attempt (null when self_intersection is off). Out-of-memory kills, VRAM refusals
    and queue timeouts are retried; progress notifications say what the job is queued behind.
    """
    latest = _LatestStatus()
    run = functools.partial(
        _animate,
        segments=segments, character_path=character_path, character_base64=character_base64,
        output_name=output_name, num_samples=num_samples, seed=seed, diffusion_steps=diffusion_steps,
        text_cfg_weight=text_cfg_weight, constraint_cfg_weight=constraint_cfg_weight,
        transition_frames=transition_frames, start_heading_deg=start_heading_deg, root_path=root_path,
        root_motion=root_motion, hip_bob=hip_bob, return_base64=return_base64, self_intersection=self_intersection,
        max_rerolls=max_rerolls, contour_limit_cm=contour_limit_cm, cloth_materials=cloth_materials,
        timeout=timeout, on_status=latest.set,
    )
    result: dict[str, Any] = {}
    async with anyio.create_task_group() as group:
        if ctx is not None:
            group.start_soon(_heartbeat, ctx, latest)
        result = await anyio.to_thread.run_sync(run)
        group.cancel_scope.cancel()
    return result


async def _heartbeat(ctx: Context, latest: _LatestStatus) -> None:
    """Tell the client the job is alive, and where it stands, every MOTION_PROGRESS_HEARTBEAT_S.

    A progress notification the client cannot take (it sent no progress token, or it went away) must never fail the
    generation, so every error from `report_progress` is swallowed, as the Mac bridge does with its own.
    """
    started = time.monotonic()
    while True:
        await anyio.sleep(MOTION_PROGRESS_HEARTBEAT_S)
        with contextlib.suppress(Exception):
            await ctx.report_progress(time.monotonic() - started, None, latest.get())


def _animate(
    *,
    segments: list[MotionSegment],
    character_path: str,
    character_base64: str,
    output_name: str,
    num_samples: int,
    seed: int | None,
    diffusion_steps: int,
    text_cfg_weight: float,
    constraint_cfg_weight: float,
    transition_frames: int,
    start_heading_deg: float,
    root_path: list[RootWaypoint] | None,
    root_motion: bool,
    hip_bob: bool,
    return_base64: bool,
    self_intersection: Literal["off", "score", "repair"],
    max_rerolls: int,
    contour_limit_cm: float,
    cloth_materials: list[str],
    timeout: int,
    on_status: Callable[[str], None],
) -> dict[str, Any]:
    """`animate_mesh`'s body, run on a worker thread so the event loop stays free for the progress heartbeat."""
    job_dirs: list[Path] = []
    try:
        if root_path and not root_motion:
            raise ValueError(
                "root_path needs root_motion=true: the path constrains the generated root trajectory, "
                "and in-place output discards it"
            )
        request = _Request(
            segments=[s.model_dump() for s in segments], root_path_job=_root_path_job(root_path, segments),
            num_samples=num_samples, diffusion_steps=diffusion_steps, text_cfg_weight=text_cfg_weight,
            constraint_cfg_weight=constraint_cfg_weight, transition_frames=transition_frames,
            start_heading_deg=start_heading_deg, root_motion=root_motion, hip_bob=hip_bob, timeout=timeout,
            self_intersection=self_intersection, contour_limit_cm=contour_limit_cm,
            cloth_materials=list(cloth_materials),
        )
        t0 = time.time()
        data, source = _load_character(character_path, character_base64)
        _preflight()
        slug = _slugify(output_name or segments[0].text)
        first_seed = seed if seed is not None else secrets.randbelow(2**31)
        attempts: list[dict[str, Any]] = []
        result: dict[str, Any] = {}
        policy = RetryPolicy(
            maximum_attempts=MOTION_MAXIMUM_ATTEMPTS, first_backoff_s=MOTION_FIRST_BACKOFF_S,
            backoff_factor=MOTION_BACKOFF_FACTOR, required_mem_gib=MOTION_RAM_REQUIRED_GIB,
            memory_wait_limit_s=MOTION_MEMORY_WAIT_LIMIT_S, poll_s=MOTION_MEMORY_POLL_S,
        )
        for n in range(max_rerolls + 1):
            attempt_seed = first_seed if n == 0 else (first_seed + 100 * n) % 2**31

            def one_try(_try: int, kinds: tuple[str, ...], attempt_seed: int = attempt_seed) -> dict[str, Any]:
                # After an OOM kill the next try generates ONE sample: each sample is a full decode, and one is
                # what fits beside another tenant's job.
                this_request = replace(request, num_samples=1) if "oom_killed" in kinds else request
                return _attempt(attempt_seed, this_request, slug, data, source, job_dirs, on_status=on_status)

            result, retries = run_with_retries(
                one_try, policy,
                read_mem_available_gib=_mem_available_gib, sleep=time.sleep, clock=time.monotonic,
                on_status=on_status,
            )
            samples = result["samples"]
            entry: dict[str, Any] = {
                "seed": attempt_seed, "job_dir": result["job_dir"], "published_to": result["published_to"],
                "passed_samples": [s["index"] for s in samples if s["self_intersection"]["passed"] is True],
                "retries": retries,
            }
            if any(r["kind"] == "oom_killed" for r in retries) and request.num_samples != 1:
                entry["reduced_num_samples_from"] = request.num_samples
            attempts.append(entry)
            if not _needs_reroll(samples, self_intersection):
                break

        samples = result["samples"]
        if return_base64:
            for s in samples:
                s["animated_glb_base64"] = base64.b64encode(Path(s["animated_glb"]).read_bytes()).decode()
        checked = self_intersection != "off"
        assessed = [s for s in samples if s["self_intersection"].get("contour_cm") is not None]
        passing = [s for s in assessed if s["self_intersection"]["passed"] is True]
        best = min(passing or assessed, key=lambda s: s["self_intersection"]["contour_cm"], default=None)
        return {
            "success": True, "job_dir": result["job_dir"], "published_to": result["published_to"],
            "seed": result["seed"], "samples": samples, "encoder_loaded": result["encoder_loaded"],
            "elapsed_seconds": round(time.time() - t0, 1),
            "attempts": attempts,
            "passed": bool(passing) if checked else None,
            "best_sample": best["index"] if checked and best is not None else None,
        }
    except Exception as e:
        return {
            "success": False, "error": str(e), "traceback": traceback.format_exc(),
            "job_dir": str(job_dirs[-1]) if job_dirs else None,
            "job_dirs": [str(d) for d in job_dirs],
            "retries": getattr(e, "retries", []),
        }


def _mem_available_gib() -> float | None:
    """big's free RAM right now, from `gpu-tenant status`; None when it cannot be read."""
    status = tenant_status()
    return status.mem_available_gib if status is not None else None


def motion_health() -> dict[str, Any]:
    """Whether the Kimodo pipeline's dependencies are in place: `checks` (name -> value) and `problems` (failed names)."""
    checks: dict[str, Any] = {
        "kimodo_installed": importlib.util.find_spec("kimodo") is not None,
        "motion_correction_installed": importlib.util.find_spec("motion_correction") is not None,
        "skinclip_installed": importlib.util.find_spec("skinclip") is not None,
        "bpy_python": SEGVIGEN_PYTHON.exists(),
        "retarget_script": RETARGET_DRIVER.exists(),
        "gpu_tenant": GPU_TENANT.exists(),
    }
    try:
        proc = subprocess.run([str(SEGVIGEN_PYTHON), str(RETARGET_DRIVER), "--help"],
                              capture_output=True, text=True, timeout=120)
        checks["retarget_supports_soma"] = "soma" in proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        checks["retarget_supports_soma"] = False
    checks["text_encoder_weights"] = all(
        (TEXT_ENCODERS_DIR / rel).is_file()
        for rel in (
            "NousResearch/Meta-Llama-3-8B-Instruct/model.safetensors.index.json",
            "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised/adapter_model.safetensors",
        )
    )
    checks["raw_publish_mounted"] = KIMODO_RAW_PUBLISH_DIR.parent.is_dir()
    checks["embedding_cache_entries"] = (
        len(list(EMBEDDING_CACHE_DIR.glob("*.pt"))) if EMBEDDING_CACHE_DIR.is_dir() else 0
    )
    problems = [k for k, v in checks.items() if isinstance(v, bool) and not v]
    return {"checks": checks, "problems": problems}
