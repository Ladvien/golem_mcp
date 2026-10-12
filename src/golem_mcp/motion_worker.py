"""Per-job Kimodo worker: text -> SOMA motion (.npz + .bvh). Runs under `gpu-tenant run`.

    python -m golem_mcp.motion_worker --job job.json --report report.json

Any failure propagates as a non-zero exit with the traceback on stderr.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any

WORKER_MARKER = "KIMODO_OK"


def run(job: dict[str, Any], encoder: Any = None) -> dict[str, Any]:
    # Upstream silently skips foot-contact correction when this C++ module is missing; refuse instead.
    import motion_correction  # noqa: F401
    import torch
    from kimodo import load_model
    from kimodo.constraints import load_constraints_lst
    from kimodo.exports.bvh import save_motion_bvh
    from kimodo.exports.motion_io import save_kimodo_npz
    from kimodo.skeleton import SOMASkeleton30, global_rots_to_local_rots
    from kimodo.tools import seed_everything

    from golem_mcp.text_cache import CachedTextEncoder

    if not torch.cuda.is_available():
        raise SystemExit("CUDA unavailable")
    device = "cuda:0"
    if encoder is None:
        encoder = CachedTextEncoder(Path(job["embedding_cache_dir"]))
    model = load_model(job["model_key"], device=device, text_encoder=encoder)
    if not isinstance(model.skeleton, SOMASkeleton30):
        raise SystemExit(f"expected a SOMA model, got skeleton {type(model.skeleton).__name__}")

    seed_everything(job["seed"])
    segs = job["segments"]
    texts = [s["text"].strip().rstrip(".") + "." for s in segs]
    num_frames = [int(s["duration_s"] * model.fps) for s in segs]  # same truncation as generate.py

    constraint_lst: list[Any] = []
    path = job["root_path"]
    if path:
        entry: dict[str, Any] = {
            "type": "root2d",
            "frame_indices": [w["frame"] for w in path],
            "smooth_root_2d": [[w["x_m"], w["z_m"]] for w in path],
        }
        if path[0]["heading_deg"] is not None:  # server guarantees all-or-none
            entry["global_root_heading"] = [
                [math.cos(math.radians(w["heading_deg"])), math.sin(math.radians(w["heading_deg"]))] for w in path
            ]
        constraint_lst = load_constraints_lst([entry], model.skeleton)

    output = model(
        texts,
        num_frames,
        num_denoising_steps=job["diffusion_steps"],
        num_samples=job["num_samples"],
        multi_prompt=True,
        constraint_lst=constraint_lst,
        cfg_type="separated",
        cfg_weight=[job["text_cfg_weight"], job["constraint_cfg_weight"]],
        first_heading_angle=torch.full((job["num_samples"],), math.radians(job["start_heading_deg"]), device=device),
        num_transition_frames=job["transition_frames"],
        post_processing=True,
        return_numpy=True,
    )

    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    skeleton = model.skeleton.somaskel77.to(device)
    samples = []
    for i in range(job["num_samples"]):
        stem = f"{job['clip_stem']}_{i:02d}"
        npz = out_dir / f"{stem}.npz"
        bvh = out_dir / f"{stem}.bvh"
        save_kimodo_npz(str(npz), {k: v[i] for k, v in output.items()})
        joints_pos = torch.from_numpy(output["posed_joints"][i]).to(device)
        joints_rot = torch.from_numpy(output["global_rot_mats"][i]).to(device)
        local_rot_mats = global_rots_to_local_rots(joints_rot, skeleton)
        root_positions = joints_pos[:, skeleton.root_idx, :]
        # standard T-pose: the TRELLIS canonical rigs are T-pose and the rest-delta retarget needs matching rests.
        save_motion_bvh(str(bvh), local_rot_mats, root_positions, skeleton=skeleton, fps=model.fps,
                        standard_tpose=True)
        samples.append({"index": i, "npz": str(npz), "bvh": str(bvh), "frames": int(joints_pos.shape[0])})

    return {
        "texts": texts,
        "num_frames": num_frames,
        "constraints": len(constraint_lst),
        "start_heading_deg": job["start_heading_deg"],
        "fps": model.fps,
        "seed": job["seed"],
        "model_key": job["model_key"],
        "samples": samples,
        "encoder_loaded": bool(getattr(encoder, "loaded", True)),
        "cache_hits": getattr(encoder, "hits", 0),
        "cache_misses": getattr(encoder, "misses", 0),
        "peak_vram_gib": torch.cuda.max_memory_allocated() / 2**30,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True)
    ap.add_argument("--report", required=True)
    args = ap.parse_args()
    job = json.loads(Path(args.job).read_text())
    report = run(job)
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(WORKER_MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
