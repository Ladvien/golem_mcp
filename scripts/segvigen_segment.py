#!/usr/bin/env python
"""Label the faces of a mesh with SegviGen part ids, leaving the mesh untouched.

Run by the SegviGen venv (python 3.11), normally as a subprocess of the MCP
server's `segment_mesh` tool.

WHY THIS EXISTS INSTEAD OF inference_full.py --export_glb
--------------------------------------------------------
SegviGen's own export is a remeshed reconstruction: slat_to_glb calls
o_voxel.postprocess.to_glb(..., remesh=True, decimation_target=100000), which
throws away our geometry, UVs and texture. Measured on succubus_1011.glb, an
11,200-vertex / 15,692-face asset comes back as 71,053 / 97,052 - a different
mesh wearing a baked copy of the part colours. A rigged, textured asset cannot
survive that.

The part signal is recoverable without it, because the voxels are a direct
discretization of OUR mesh:

  * tex_voxels = tex_decoder(output_tex_slat, guide_subs=subs) carries part
    identity as base_color (channels 0:3 of feats, already scaled to 0..1);
  * its coords index a fixed 512^3 grid with origin [-0.5]*3 and voxel size
    1/512 - about 2 mm on a 1 m asset;
  * process_glb_to_vxz put our mesh in that grid with a normalization we can
    reproduce exactly: translate by -center, then scale by 0.99999/max_extent.

So this script stops before slat_to_glb, maps each original face centroid into
the grid, reads the part colour, and clusters colours into part ids. Geometry,
UVs and texture are never rewritten - the output is a sidecar.

VERIFIED PROPERTIES OF THE SIGNAL (succubus_1011.glb)
-----------------------------------------------------
Part colours are flat: per-cluster standard deviation is 1-3 out of 255, and 5
parts (body, two wings, tail, horns) covered 98% of sampled texels with ~1%
boundary texels between them. That is why plain leader clustering on RGB is
enough and no learned post-process is needed.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo"))

# The grid inference_full.py voxelizes into. Not configurable: these are baked
# into the checkpoint's training distribution and into slat_to_glb's aabb.
GRID_SIZE = 512
GRID_ORIGIN = -0.5

# Two part colours are separated by ~50-80 in RGB distance; texels that sit on a
# boundary between parts land in between. 30 splits real parts without shattering
# them, and every face is assigned to its nearest seed regardless, so a boundary
# colour joins whichever part it is closest to rather than becoming its own.
CLUSTER_MIN_SEPARATION = 30.0
# A cluster holding fewer faces than this is a boundary artefact, not a part.
MIN_PART_FACE_SHARE = 0.001


def _digest(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def render_conditioning_image(glb: str, transforms: str, out: str) -> None:
    """Render the conditioning view in a fresh process.

    bpy is not merely heavy to import - it initializes its own GPU state, and
    inference holds ~16 GB of CUDA allocations. Keeping them in separate
    processes is why this is a subprocess call and not an import.
    """
    child = subprocess.run(
        [sys.executable, __file__, "--render-only",
         "--mesh", glb, "--transforms", transforms, "--conditioning-image", out],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    if not Path(out).is_file():
        tail = "\n".join((child.stdout + child.stderr).splitlines()[-15:])
        raise RuntimeError(f"conditioning render produced no image at {out}\n{tail}")


def do_render(glb: str, transforms: str, out: str) -> None:
    sys.path.insert(0, str(REPO / "data_toolkit"))
    from bpy_render import render_from_transforms

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    render_from_transforms(glb, transforms, out)


def normalization(scene):
    """The exact translate-then-scale process_glb_to_vxz applies (its lines 155-158).

    Reproduced rather than imported because it is applied there to a trimesh
    Scene in place; we need the numbers to map our own face centroids.
    """
    aabb = scene.bounding_box.bounds
    center = (aabb[0] + aabb[1]) / 2
    scale = 0.99999 / (aabb[1] - aabb[0]).max()
    return center, scale


def sample_part_colours(mesh, voxel_coords, voxel_colours, center, scale):
    """Part colour per face, by nearest occupied voxel to the face centroid.

    Nearest-voxel for every face, not exact-hit-with-a-fallback: generated assets
    are non-watertight shells, so some centroids land in empty cells no matter
    what, and a single rule keeps the result explainable.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    centroids = mesh.vertices[mesh.faces].mean(axis=1)
    centroids = (centroids - center) * scale

    # Voxel index -> centre of that voxel in the same normalized space.
    voxel_centres = (voxel_coords.astype(np.float64) + 0.5) / GRID_SIZE + GRID_ORIGIN
    tree = cKDTree(voxel_centres)
    dist, idx = tree.query(centroids, k=1, workers=-1)
    return voxel_colours[idx], dist


def cluster_colours(colours):
    """Leader clustering on RGB: seeds by population, then nearest-seed assignment.

    Deterministic and k-free. k-means would need k chosen up front and would move
    its centroids off the flat part colours toward the boundary texels between
    them.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    # Seed candidates: 8-level-per-channel bins, most populated first.
    binned = (colours // 32).astype(np.int64)
    keys = binned[:, 0] * 64 + binned[:, 1] * 8 + binned[:, 2]
    uniq, counts = np.unique(keys, return_counts=True)
    order = np.argsort(-counts)

    seeds = []
    for key in uniq[order]:
        mean = colours[keys == key].mean(axis=0)
        if all(np.linalg.norm(mean - s) >= CLUSTER_MIN_SEPARATION for s in seeds):
            seeds.append(mean)
    seeds = np.array(seeds)

    # KD-tree, not a broadcast. `colours[:, None, :] - seeds[None, :, :]` builds an
    # N x K x 3 array: fine at TRELLIS 1's 5,716 faces, but TRELLIS.2 ships ~97,000
    # and the same line asked for 117 GB of virtual address space and was OOM-killed
    # at 11.5 GB resident.
    labels = cKDTree(seeds).query(colours, k=1, workers=-1)[1]

    # Drop clusters too small to be parts, reassigning their faces to the nearest
    # surviving seed, then renumber so part ids are contiguous and population-ordered.
    counts = np.bincount(labels, minlength=len(seeds))
    keep = np.where(counts >= max(1, int(MIN_PART_FACE_SHARE * len(colours))))[0]
    keep = keep[np.argsort(-counts[keep])]
    kept_seeds = seeds[keep]
    labels = cKDTree(kept_seeds).query(colours, k=1, workers=-1)[1]
    return labels, kept_seeds


def write_preview(mesh, labels, seeds, path):
    """A throwaway visual check, NOT the asset.

    Carries face colours and no texture, so it is only for looking at.
    """
    import numpy as np
    import trimesh

    preview = trimesh.Trimesh(vertices=mesh.vertices.copy(), faces=mesh.faces.copy(), process=False)
    preview.visual = trimesh.visual.ColorVisuals(
        mesh=preview, face_colors=np.clip(seeds[labels], 0, 255).astype(np.uint8)
    )
    preview.export(str(path))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mesh", required=True, help="source .glb - never modified")
    ap.add_argument("--out-dir", help="where the sidecar is written (default: alongside --mesh)")
    ap.add_argument("--ckpt", help="SegviGen full_seg.ckpt (default: resolved from the HF cache)")
    ap.add_argument("--transforms", default=str(REPO / "data_toolkit/transforms.json"))
    ap.add_argument("--conditioning-image", help="render target (default: <out-dir>/<stem>_cond.png)")
    ap.add_argument("--seed", type=int, default=0,
                    help="RNG seed for the part sampler. Fixed by default so the same mesh "
                         "always yields the same partition; change it to draw a different one.")
    ap.add_argument("--preview", action="store_true", help="also write a part-coloured preview GLB")
    ap.add_argument("--render-only", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.render_only:
        do_render(args.mesh, args.transforms, args.conditioning_image)
        return 0

    src = Path(args.mesh).resolve()
    if not src.is_file():
        raise SystemExit(f"no such mesh: {src}")
    src_digest = _digest(src)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Path(args.conditioning_image) if args.conditioning_image else out_dir / f"{src.stem}_cond.png"
    ckpt = Path(args.ckpt) if args.ckpt else next(
        Path.home().glob(".cache/huggingface/hub/models--fenghora--SegviGen/snapshots/*/full_seg.ckpt")
    )

    # Set before trellis2 is imported: sparse/config.py reads it at import time.
    os.environ.setdefault("ATTN_BACKEND", "sdpa")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    print(f"[1/5] conditioning render -> {img}", flush=True)
    render_conditioning_image(str(src), args.transforms, str(img))

    print("[2/5] loading models", flush=True)
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)   # inference_full opens microsoft/TRELLIS.2-4B/pipeline.json relatively

    from collections import OrderedDict

    import inference_full as seg
    import numpy as np
    import torch
    import trimesh
    from PIL import Image
    from trellis2 import models
    from trellis2.modules.image_feature_extractor import DinoV3FeatureExtractor
    from trellis2.pipelines.rembg import BiRefNet

    with open("microsoft/TRELLIS.2-4B/pipeline.json") as f:
        pipeline_args = json.load(f)["args"]

    gen3dseg = seg.Gen3DSeg(models.from_pretrained(
        "microsoft/TRELLIS.2-4B/ckpts/slat_flow_imgshape2tex_dit_1_3B_512_bf16"))
    state_dict = torch.load(str(ckpt))["state_dict"]
    gen3dseg.load_state_dict(OrderedDict(
        [(k.replace("gen3dseg.", ""), v) for k, v in state_dict.items()]))
    gen3dseg.eval().cuda()

    shape_encoder = models.from_pretrained("microsoft/TRELLIS.2-4B/ckpts/shape_enc_next_dc_f16c32_fp16").cuda().eval()
    tex_encoder = models.from_pretrained("microsoft/TRELLIS.2-4B/ckpts/tex_enc_next_dc_f16c32_fp16").cuda().eval()
    shape_decoder = models.from_pretrained("microsoft/TRELLIS.2-4B/ckpts/shape_dec_next_dc_f16c32_fp16").cuda().eval()
    tex_decoder = models.from_pretrained("microsoft/TRELLIS.2-4B/ckpts/tex_dec_next_dc_f16c32_fp16").cuda().eval()

    print("[3/5] voxelizing and encoding", flush=True)
    vxz = out_dir / f"{src.stem}.vxz"
    seg.process_glb_to_vxz(str(src), str(vxz))
    shape_slat, meshes, subs, tex_slat = seg.vxz_to_latent_slat(
        shape_encoder, shape_decoder, tex_encoder, str(vxz))

    # Not chained: neither wrapper returns self from .cuda(), unlike nn.Module.
    rembg_model = BiRefNet(model_name="briaai/RMBG-2.0")
    rembg_model.cuda()
    image_cond_model = DinoV3FeatureExtractor(model_name="facebook/dinov3-vitl16-pretrain-lvd1689m")
    image_cond_model.cuda()
    cond = seg.get_cond(image_cond_model, [seg.preprocess_image(rembg_model, Image.open(img))])

    print(f"[4/5] sampling part field (seed {args.seed})", flush=True)
    # tex_slat_sample_single draws its noise with torch.randn_like off the global
    # RNG (inference_full.py:258) and upstream never seeds it, so consecutive runs
    # on the SAME mesh return different partitions - measured at 2 parts one run
    # and 7 the next. Seeding here makes the tool reproducible; --seed re-rolls.
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    output_tex_slat = seg.tex_slat_sample_single(
        gen3dseg, seg.Sampler(), pipeline_args, shape_slat, tex_slat, cond)
    with torch.no_grad():
        tex_voxels = tex_decoder(output_tex_slat, guide_subs=subs) * 0.5 + 0.5

    # STOP HERE. slat_to_glb(meshes, tex_voxels) is what would remesh the asset away.
    voxels = tex_voxels[0]
    voxel_coords = voxels.coords[:, 1:].cpu().numpy()
    voxel_colours = (voxels.feats[:, 0:3].float().clamp(0, 1) * 255).cpu().numpy()

    print(f"[5/5] mapping {len(voxel_coords)} voxels onto source faces", flush=True)

    # Same load and normalization the voxelizer saw. preprocess_scene_textures only
    # touches textures, so scene bounds are unaffected by skipping it here.
    scene = trimesh.load(str(src), force="scene")
    center, scale = normalization(scene)

    # process=False: no vertex welding or reordering, so face indices in the sidecar
    # refer to the file's own faces.
    mesh = trimesh.load(str(src), force="mesh", process=False)
    assert np.allclose(mesh.bounds, scene.bounds, atol=1e-6), (
        f"concatenated mesh bounds {mesh.bounds} != scene bounds {scene.bounds}; "
        "the normalization would not match the voxelizer's")

    # Clustered over the voxel field as well as over faces: if the two disagree,
    # the fault is in the face mapping, not the model, and that is otherwise
    # invisible.
    voxel_labels, voxel_seeds = cluster_colours(voxel_colours.astype(np.float64))
    voxel_counts = np.bincount(voxel_labels, minlength=len(voxel_seeds))
    voxel_parts = [
        {"color_rgb": [int(round(c)) for c in voxel_seeds[i]],
         "voxel_share": round(float(voxel_counts[i] / len(voxel_labels)), 4)}
        for i in np.argsort(-voxel_counts)
    ]

    colours, dist = sample_part_colours(mesh, voxel_coords, voxel_colours, center, scale)
    labels, seeds = cluster_colours(colours)

    counts = np.bincount(labels, minlength=len(seeds))
    parts = [
        {"id": int(i), "color_rgb": [int(round(c)) for c in seeds[i]],
         "face_count": int(counts[i]), "face_share": round(float(counts[i] / len(labels)), 4)}
        for i in range(len(seeds))
    ]

    # The acceptance test CubePart failed: the asset must come back untouched.
    # Geometry, UVs and texture all live in the source file, so hashing it end to
    # end is a stricter check than comparing counts - and the counts are checked
    # anyway, because a sidecar indexed off the wrong mesh is silently useless.
    assert len(labels) == len(mesh.faces), (
        f"{len(labels)} labels for {len(mesh.faces)} faces")
    assert src_digest == _digest(src), f"source file was modified: {src}"

    labels_path = out_dir / f"{src.stem}_face_labels.npy"
    np.save(labels_path, labels.astype(np.int32))

    report = {
        "source": str(src),
        "source_bytes": src.stat().st_size,
        "source_sha256": src_digest,
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "face_labels": str(labels_path),
        "parts": parts,
        "voxels": int(len(voxel_coords)),
        "voxel_parts": voxel_parts,
        "grid": {"size": GRID_SIZE, "origin": GRID_ORIGIN,
                 "center": [float(c) for c in center], "scale": float(scale)},
        "lookup": {"rule": "nearest occupied voxel to face centroid",
                   "max_distance_normalized": round(float(dist.max()), 5),
                   "mean_distance_normalized": round(float(dist.mean()), 5),
                   "voxel_size_normalized": round(1 / GRID_SIZE, 6)},
        "seed": args.seed,
        "clustering": {"rule": "leader clustering on RGB, nearest-seed assignment",
                       "min_separation": CLUSTER_MIN_SEPARATION,
                       "min_part_face_share": MIN_PART_FACE_SHARE,
                       "note": "color_rgb is the sampler's arbitrary label colour for a part, "
                               "not a semantic or stable identity. It changes with --seed and "
                               "carries no meaning across meshes; only the partition matters."},
    }
    if args.preview:
        preview_path = out_dir / f"{src.stem}_parts_preview.glb"
        write_preview(mesh, labels, seeds, preview_path)
        report["preview"] = str(preview_path)

    report_path = out_dir / f"{src.stem}_parts.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"SEGVIGEN_SEGMENT_OK {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
