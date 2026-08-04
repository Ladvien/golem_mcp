#!/usr/bin/env python
"""Image -> textured mesh with TRELLIS.2. NOT wired into generate_3d.

STATUS: the migration was attempted and reverted. generate_3d stays on TRELLIS 1.
This driver remains for display-only assets that never get rigged.

TRELLIS.2 makes visibly better-looking characters - defined facial features, scale
texture, rivets and material separation where TRELLIS 1 gives smooth blobs - at
comparable wall time (85s vs 80s at pipeline_type=512), and in a fraction of the
VRAM (TRELLIS 1's 2048px bake wanted 17.0 GB and was refused by its own preflight
until views were cut).

It is still the wrong choice for this pipeline, because its meshes are
topologically FRAGMENTED and that breaks the rigging stage generate_3d exists to
feed:

                       TRELLIS 1     TRELLIS.2
  vertices : faces     0.74          1.57      (a coherent mesh is ~0.5)
  boundary edges       5,816         66,756
  rig_model wall       39 s          >20 min, never observed to finish

More vertices than faces means the surface is in pieces. remesh=True does not fix
it (22,792 boundary edges, still not watertight): the open-surface representation
that makes TRELLIS.2 right for GARMENTS is the same property that makes its
character meshes unriggable. Reviving this needs a mesh repair stage between
generation and rigging, not a different export flag.

Runs as a subprocess, unlike TRELLIS 1 which generate_3d loads in-process - the
reason the server peaked at 19.5 GB RSS and was OOM-killed mid-run.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True, help="output .glb path")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--pipeline-type", default="1024", choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--simplify-to", type=int, default=300000,
                    help="face cap before export; see trellis2_common for why this is mandatory")
    ap.add_argument("--decimate-to", type=int, default=100000, help="faces in the delivered mesh")
    ap.add_argument("--texture-size", type=int, default=2048)
    ap.add_argument("--no-remesh", action="store_true",
                    help="keep O-Voxel's raw open-surface output instead of remeshing")
    args = ap.parse_args()

    os.environ.setdefault("ATTN_BACKEND", "sdpa")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(REPO)   # pipeline.json and its ckpts are relative

    import torch
    import trellis2_common as t2
    from PIL import Image

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        raise SystemExit(f"no such image: {image_path}")
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    print(f"[1/3] loading TRELLIS.2 ({args.pipeline_type})", flush=True)
    pipeline, dropped = t2.load_pipeline(args.pipeline_type)
    load_s = time.time() - started
    print(f"      dropped {dropped}; RSS peak {t2.host_rss_peak_gb():.1f} GB", flush=True)

    print(f"[2/3] generating from {image_path.name} (seed {args.seed})", flush=True)
    t1 = time.time()
    mesh = pipeline.run(Image.open(image_path), seed=args.seed, pipeline_type=args.pipeline_type)[0]
    gen_s = time.time() - t1
    peak_vram = torch.cuda.max_memory_allocated() / 1e9

    # Free the models before the export, which is the host-RAM-hungry half.
    del pipeline
    torch.cuda.empty_cache()

    print("[3/3] exporting", flush=True)
    # remesh=True for characters. O-Voxel's raw output is an OPEN surface: measured
    # 24,853 vertices for 15,822 faces (V:F 1.57, where a coherent mesh is ~0.5) and
    # 66,756 boundary edges against TRELLIS 1's 5,816. That fragmentation is the
    # whole point for a garment, but it wrecks rigging - TokenRig took 39s on a
    # TRELLIS 1 mesh and had not finished after 20 minutes on this one.
    # scripts/trellis2_garment.py keeps remesh=False for the opposite reason.
    raw = t2.export_glb(mesh, str(out), args.simplify_to, args.decimate_to, args.texture_size,
                        remesh=not args.no_remesh)
    if not out.is_file() or out.stat().st_size == 0:
        raise SystemExit(f"FATAL: no mesh written to {out}")

    report = {
        "model": "TRELLIS.2-4B", "pipeline_type": args.pipeline_type,
        "source_image": str(image_path), "glb": str(out), "seed": args.seed,
        "faces_raw": raw, "dropped_models": dropped, "remeshed": not args.no_remesh,
        "peak_vram_gb": round(peak_vram, 2),
        "host_rss_peak_gb": round(t2.host_rss_peak_gb(), 1),
        "load_seconds": round(load_s, 1), "generate_seconds": round(gen_s, 1),
        "total_seconds": round(time.time() - started, 1),
    }
    report.update(t2.mesh_stats(str(out)))
    report_path = out.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"TRELLIS2_GENERATE_OK {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
