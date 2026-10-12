#!/usr/bin/env python
"""Generate an open-surface garment mesh from a standalone garment image.

Run by the SegviGen venv (python 3.11), normally as a subprocess of the MCP
server's `generate_garment` tool.

WHY THIS IS SEPARATE FROM generate_3d
-------------------------------------
Both now run TRELLIS.2, but this driver exports for a GARMENT: `remesh=False` to
keep open boundaries, and a hard check that the result is not a sealed lump.
`generate_3d` targets a rig-compatible vertex budget instead. O-Voxel's Flexible
Dual Grid is what makes open surfaces possible at all - its README lists "Open
Surfaces (e.g. clothing)" as a headline capability, and iso-surface methods like
TRELLIS 1 cannot represent one.

WHY A STANDALONE GARMENT IMAGE, NOT ONE MASKED OFF A DRESSED CHARACTER
----------------------------------------------------------------------
Measured, same model and same export settings:

  corset masked out of the worn character -> featureless blob, vol/hull 1.02
  corset generated as a product shot      -> clean garment,    vol/hull 0.52

Both are topologically open, so watertightness alone does not tell them apart. A
garment worn on a body has its interior occluded and its silhouette broken by
skin and limbs; inverting that gives a stuffed torso. A product shot is
in-distribution and reconstructs cleanly. So the caller's job is to produce a
picture of the garment ALONE, and this script's job is to turn it into a mesh.

TWO SETTINGS THAT ARE NOT OPTIONAL
----------------------------------
  * `remesh=False` in to_glb. It is the default; SegviGen's inference_full.py
    explicitly overrides it to True, and that closes open boundaries.
  * `mesh.simplify()` BEFORE to_glb. Raw extraction measured 3.27M faces, and
    handing that to the exporter got the process killed by the kernel OOM killer.
    The binding constraint is 32 GB of system RAM as much as VRAM: a 2026-10-12 run
    reported a 14.47 GB torch peak on the GPU. Both upstream entrypoints call simplify
    (TRELLIS.2/example.py:26, SegviGen/inference_full.py:285).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo"))

# A garment you cannot put a body into is not a garment. Voxelize, flood-fill the
# air from outside, and measure what fraction of the air is sealed in. Measured:
#
#   corset from a product shot   0.0007   (twice, across separate runs)
#   blob from a masked character 0.3652
#
# Two orders of magnitude apart and reproducible, so 0.05 is a safe line. This
# replaced volume/convex-hull, which returned 0.52 and 0.0007 for the SAME mesh on
# two runs - trimesh computes volume by the divergence theorem, which is undefined
# without a closed surface.
MAX_ENCLOSED_AIR_FRACTION = 0.05
VOXEL_GRID_DIVISIONS = 64


def enclosed_air_fraction(mesh, divisions: int = VOXEL_GRID_DIVISIONS) -> float:
    """Fraction of the air around/inside the mesh that is sealed off from outside.

    Near zero for a real garment - a corset is a tube, so air (and a body) passes
    straight through. Large for a stuffed lump. Well defined for open meshes,
    unlike any volume-based measure.
    """
    import numpy as np
    from scipy import ndimage

    extents = mesh.bounds[1] - mesh.bounds[0]
    occupied = np.asarray(mesh.voxelized(pitch=extents.max() / divisions).matrix, dtype=bool)
    occupied = np.pad(occupied, 2, constant_values=False)   # guarantee an air margin
    air = ~occupied
    labels, _ = ndimage.label(air)
    outside = labels == labels[0, 0, 0]
    return float((air & ~outside).sum() / max(air.sum(), 1))


def do_render(glb: str, out: str) -> None:
    """Render a preview in a fresh process - bpy must not share one with torch's
    CUDA context."""
    sys.path.insert(0, str(REPO / "data_toolkit"))
    from bpy_render import render_from_transforms

    render_from_transforms(glb, str(REPO / "data_toolkit/transforms.json"), out, resolution=640)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, help="picture of the garment ALONE, on a plain background")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", help="output stem (default: the image's stem)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pipeline-type", default="512", choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--simplify-target", type=int, default=300000,
                    help="face cap applied BEFORE export; see the OOM note in the module docstring")
    ap.add_argument("--decimation-target", type=int, default=100000)
    ap.add_argument("--texture-size", type=int, default=2048)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--render-only", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.render_only:
        do_render(args.image, args.out_dir)
        return 0

    image_path = Path(args.image).resolve()
    if not image_path.is_file():
        raise SystemExit(f"no such image: {image_path}")
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or image_path.stem
    out_glb = out_dir / f"{name}.glb"

    # Set before trellis2 is imported: sparse/config.py reads it at import time.
    os.environ.setdefault("ATTN_BACKEND", "sdpa")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.chdir(REPO)   # pipeline.json is opened at a relative path

    import numpy as np
    import o_voxel
    import torch
    import trellis2_common as t2
    import trimesh
    from PIL import Image

    started = time.time()
    print(f"[1/3] loading TRELLIS.2-4B ({args.pipeline_type})", flush=True)
    # Trimmed load: pipeline.json lists eight models (14.82 GB) and low_vram=True
    # pins them all in host RAM, but a '512' run never touches the two 1024 flow
    # models. See scripts/trellis2_common.py - this was the difference between
    # running and being OOM-killed on this box.
    pipeline, dropped_models = t2.load_pipeline(args.pipeline_type)

    print(f"[2/3] generating from {image_path.name} (seed {args.seed})", flush=True)
    mesh = pipeline.run(Image.open(image_path), seed=args.seed, pipeline_type=args.pipeline_type)[0]
    peak_gb = torch.cuda.max_memory_allocated() / 1e9

    raw_faces = int(len(mesh.faces))
    mesh.simplify(args.simplify_target)
    print(f"[3/3] exporting ({raw_faces} -> {len(mesh.faces)} faces, remesh=False)", flush=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size, aabb=[[-0.5] * 3, [0.5] * 3],
        decimation_target=args.decimation_target, texture_size=args.texture_size,
        remesh=False,
        verbose=False,
    )
    glb.export(str(out_glb))

    m = trimesh.load(str(out_glb), force="mesh", process=False)
    _, counts = np.unique(m.edges_sorted, axis=0, return_counts=True)
    boundary_edges = int((counts == 1).sum())
    sealed = enclosed_air_fraction(m)

    # Fail on either way of not being a garment. Watertight means the open surface
    # was lost; sealed air means it is a lump you could never put a body into.
    # Both are unusable, and both are silent failures if only the render is checked.
    if m.is_watertight or boundary_edges == 0:
        raise SystemExit(
            f"FATAL: {out_glb} came back watertight ({boundary_edges} boundary edges). "
            "The open surface was lost - check that to_glb was not passed remesh=True."
        )
    if sealed > MAX_ENCLOSED_AIR_FRACTION:
        raise SystemExit(
            f"FATAL: {sealed:.3f} of the air is sealed inside {out_glb} (limit "
            f"{MAX_ENCLOSED_AIR_FRACTION}). It is open but stuffed - a body cannot go in it. "
            "The usual cause is a source image that still contains a body: generate the "
            "garment ALONE rather than masking it off a dressed character."
        )

    warnings: list[str] = []

    extents = (m.bounds[1] - m.bounds[0]).tolist()
    report = {
        "source_image": str(image_path),
        "garment_glb": str(out_glb),
        "seed": args.seed,
        "pipeline_type": args.pipeline_type,
        "vertices": int(len(m.vertices)),
        "faces": int(len(m.faces)),
        "faces_before_simplify": raw_faces,
        "is_watertight": bool(m.is_watertight),
        "boundary_edges": boundary_edges,
        "enclosed_air_fraction": round(sealed, 4),
        "extents": [round(v, 4) for v in extents],
        "peak_vram_gb": round(peak_gb, 2),
        "dropped_models": dropped_models,
        "elapsed_seconds": round(time.time() - started, 1),
        "warnings": warnings,
    }
    if args.preview:
        preview = out_dir / f"{name}_preview.png"
        subprocess.run(
            [sys.executable, __file__, "--render-only", "--image", str(out_glb), "--out-dir", str(preview)],
            cwd=str(REPO), capture_output=True, text=True, timeout=900,
        )
        if preview.is_file():
            report["preview"] = str(preview)

    report_path = out_dir / f"{name}_garment.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"TRELLIS2_GARMENT_OK {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
