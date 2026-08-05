#!/usr/bin/env python
"""Generate a CHARACTER with TRELLIS.2, keeping its PBR channels.

    trellis2_character.py --image hero.png --out-dir output --name emberwake

WHY THIS EXISTS
---------------
`generate_3d` runs TRELLIS 1, which emits one base-colour map and nothing else.
Measured on its output: no metallicRoughness, no normal, no occlusion,
`roughnessFactor: 1.0` - brass is mathematically identical to wool. Worse, that
base colour is not albedo: within a single segmented material region its luminance
p95/p5 runs 24x to 155x, where flat albedo would be 2-3x. It is a photograph of a
lit object, so nothing downstream can relight it.

TRELLIS.2 emits base_color, roughness and metallic as separate channels, and
`o_voxel.postprocess.to_glb` writes them as baseColorTexture +
metallicRoughnessTexture. This is not speculative: `trellis2_garment.py` has been
producing 2048px PBR GLBs through this exact path all along.

DIFFERENCES FROM THE GARMENT DRIVER
-----------------------------------
Same pipeline, opposite geometry contract:

  * `remesh=True`. A garment MUST stay an open surface - its hem and front opening
    are boundaries - so that driver passes remesh=False and fails loudly if the
    result comes back watertight. A character is the other case, and gets the
    opposite check.
  * `texture_size=2048` rather than TRELLIS 1's 1024.

TOPOLOGY IS REPORTED BOTH WAYS, AND THAT IS DELIBERATE
------------------------------------------------------
TRELLIS.2 was tried for characters once before and reverted as producing
"fragmented" meshes - tens of thousands of boundary edges. That measurement welded
by VERTEX DISTANCE, which cannot see the actual structure: these generators emit a
mesh split at UV-atlas seams, where the duplicated vertices are coincident but
carry different UVs, so `trimesh.merge_vertices` will not join them at ANY
tolerance. The same method reported a TRELLIS 1 character as 173 disconnected
components when a position-weld shows 2 components and 0.8% boundary edges.

So this reports components, boundary-edge fraction and Euler characteristic BOTH
as-shipped and position-welded. The welded numbers are the real topology; the
as-shipped ones only describe the atlas.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

REPO = os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, REPO)


def survey(vertices, faces):
    """Components, boundary-edge fraction and Euler characteristic."""
    import numpy as np
    import trimesh

    v = np.asarray(vertices)
    f = np.asarray(faces)
    edges = np.sort(np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    counts = Counter(map(tuple, edges))
    boundary = sum(1 for n in counts.values() if n == 1)
    comps = len(trimesh.Trimesh(vertices=v, faces=f, process=False)
                .split(only_watertight=False))
    return {
        "vertices": int(len(v)),
        "faces": int(len(f)),
        "components": int(comps),
        "boundary_edge_pct": round(100.0 * boundary / max(len(counts), 1), 2),
        "euler": int(len(v) - len(counts) + len(f)),
    }


def topology(path):
    """Survey as-shipped and after welding on POSITION alone. See the docstring."""
    import numpy as np
    import trimesh

    mesh = trimesh.load(path, force="mesh", process=False)
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.faces)
    uniq, inv = np.unique(np.round(v, 6), axis=0, return_inverse=True)
    wf = inv[f]
    wf = wf[(wf[:, 0] != wf[:, 1]) & (wf[:, 1] != wf[:, 2]) & (wf[:, 0] != wf[:, 2])]
    return {"as_shipped": survey(v, f), "position_welded": survey(uniq, wf)}


def materials(path):
    """What the GLB actually carries - the whole point of this driver."""
    import io
    import struct

    from PIL import Image

    data = open(path, "rb").read()
    length = struct.unpack("<I", data[12:16])[0]
    gltf = json.loads(data[20:20 + length].decode("utf-8"))
    binary = data[20 + length + 8:]
    out = {"materials": len(gltf.get("materials", [])), "images": []}
    for image in gltf.get("images", []):
        view = gltf["bufferViews"][image["bufferView"]]
        start = view.get("byteOffset", 0)
        blob = binary[start:start + view["byteLength"]]
        out["images"].append(list(Image.open(io.BytesIO(blob)).size))
    if gltf.get("materials"):
        pbr = gltf["materials"][0].get("pbrMetallicRoughness", {})
        out["baseColorTexture"] = "baseColorTexture" in pbr
        out["metallicRoughnessTexture"] = "metallicRoughnessTexture" in pbr
        out["normalTexture"] = "normalTexture" in gltf["materials"][0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", help="output stem (default: the image's stem)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pipeline-type", default="512",
                    choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--simplify-target", type=int, default=300000)
    ap.add_argument("--decimation-target", type=int, default=100000)
    ap.add_argument("--texture-size", type=int, default=2048)
    args = ap.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or image_path.stem
    out_glb = out_dir / f"{stem}.glb"

    # Set BEFORE trellis2 is imported: sparse/config.py reads these at import time,
    # and the default backend is flash_attn, which is not installed on this box -
    # its build reads FLASH_ATTN_CUDA_ARCHS rather than TORCH_CUDA_ARCH_LIST and
    # compiles for every architecture for hours. SDPA was verified against a
    # block-diagonal reference instead.
    # ASSIGNED, not setdefault. The MCP server sets ATTN_BACKEND=xformers at import
    # for TRELLIS 1, a subprocess inherits it, and setdefault then silently keeps the
    # inherited value - so this driver worked when run by hand and failed through the
    # tool with an empty error. TRELLIS.2 needs sdpa here: flash_attn is not built on
    # this box and xformers does not carry it.
    os.environ["ATTN_BACKEND"] = "sdpa"
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

    os.chdir(REPO)   # pipeline.json is opened at a relative path

    import o_voxel
    import torch
    import trellis2_common as t2
    from PIL import Image

    started = time.time()
    print(f"[1/3] loading TRELLIS.2-4B ({args.pipeline_type})", flush=True)
    pipeline, dropped = t2.load_pipeline(args.pipeline_type)

    print(f"[2/3] generating from {image_path.name} (seed {args.seed})", flush=True)
    mesh = pipeline.run(Image.open(image_path), seed=args.seed,
                        pipeline_type=args.pipeline_type)[0]
    peak_gb = torch.cuda.max_memory_allocated() / 1e9

    raw_faces = int(len(mesh.faces))
    mesh.simplify(args.simplify_target)
    print(f"[3/3] exporting ({raw_faces} -> {len(mesh.faces)} faces, remesh=True)", flush=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size, aabb=[[-0.5] * 3, [0.5] * 3],
        decimation_target=args.decimation_target, texture_size=args.texture_size,
        remesh=True,
        verbose=False,
    )
    glb.export(str(out_glb))

    topo = topology(str(out_glb))
    mats = materials(str(out_glb))

    # A character is the opposite contract to a garment: it must come back CLOSED.
    # Judged on the welded topology, because the as-shipped numbers describe the UV
    # atlas rather than the surface.
    welded = topo["position_welded"]
    if welded["boundary_edge_pct"] > 5.0:
        raise SystemExit(
            f"FATAL: {out_glb} is {welded['boundary_edge_pct']}% boundary edges even "
            f"after welding on position ({welded['components']} components). A character "
            "should come back closed - check that to_glb was passed remesh=True."
        )
    if not mats.get("metallicRoughnessTexture"):
        raise SystemExit(
            f"FATAL: {out_glb} has no metallicRoughnessTexture. Emitting PBR is the "
            "entire reason this driver exists rather than generate_3d's TRELLIS 1 path."
        )

    report = {
        "source_image": str(image_path),
        "character_glb": str(out_glb),
        "seed": args.seed,
        "pipeline_type": args.pipeline_type,
        "faces_before_simplify": raw_faces,
        "topology": topo,
        "materials": mats,
        "peak_vram_gb": round(peak_gb, 2),
        "dropped_models": dropped,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (out_dir / f"{stem}_character.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"CHARACTER_OK {out_glb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
