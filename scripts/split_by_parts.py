#!/usr/bin/env python
"""Split a textured mesh into one object per part, keeping UVs and texture.

    split_by_parts.py --mesh asset.glb --labels asset_face_labels.npy --out-dir .

Produces a single GLB containing one named mesh per part. Blender imports it as
N separate objects, each already textured - there is nothing to re-apply.

SPLIT THE ASSET, NOT THE PREVIEW
--------------------------------
`asset_parts_preview.glb` from segment_mesh carries flat face colours and NOTHING
else: it is built with trimesh ColorVisuals, which replaces the TextureVisuals and
so discards the UVs. Splitting the preview therefore gives parts that can never be
textured - the UV coordinates that would map them onto the TRELLIS.2 texture are
already gone. It exists to be looked at, not to be worked on.

`asset_face_labels.npy` indexes the faces of the ORIGINAL asset, so splitting that
carries the texture along automatically. Each part keeps its own slice of the
shared UV layout and references the same image.

WHY process=False
-----------------
The labels index `trimesh.load(mesh, force='mesh', process=False)`. The default
process=True welds duplicate vertices and reorders faces, after which label i no
longer refers to face i and the split silently scrambles.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mesh", required=True, help="the TEXTURED asset .glb, not the parts preview")
    ap.add_argument("--labels", required=True, help="asset_face_labels.npy from segment_mesh")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", default="", help="output stem (default: the mesh's stem)")
    ap.add_argument("--min-face-share", type=float, default=0.0,
                    help="drop parts smaller than this fraction of faces; 0 keeps every part")
    ap.add_argument("--separate-files", action="store_true",
                    help="also write one .glb per part alongside the combined scene")
    args = ap.parse_args()

    import numpy as np
    import trimesh

    mesh_path = Path(args.mesh).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or mesh_path.stem

    mesh = trimesh.load(str(mesh_path), force="mesh", process=False)
    labels = np.load(args.labels)
    if len(labels) != len(mesh.faces):
        raise SystemExit(
            f"{len(labels)} labels for {len(mesh.faces)} faces. The labels index the asset they "
            "were generated from, loaded with process=False - check you are not splitting the "
            "parts preview, which has a different face count."
        )
    if not hasattr(mesh.visual, "uv") or mesh.visual.uv is None:
        raise SystemExit(
            f"{mesh_path} has no UVs. This looks like the parts preview rather than the textured "
            "asset; split asset.glb instead."
        )

    scene = trimesh.Scene()
    report, dropped = [], []
    for part in sorted(np.unique(labels)):
        face_idx = np.where(labels == part)[0]
        share = len(face_idx) / len(labels)
        if share < args.min_face_share:
            dropped.append({"part": int(part), "faces": len(face_idx), "face_share": round(share, 5)})
            continue
        sub = mesh.submesh([face_idx], append=True)
        node = f"part_{int(part):02d}"
        scene.add_geometry(sub, geom_name=node, node_name=node)
        entry = {"part": int(part), "node": node, "faces": int(len(sub.faces)),
                 "vertices": int(len(sub.vertices)), "face_share": round(share, 5)}
        if args.separate_files:
            single = out_dir / f"{stem}_{node}.glb"
            sub.export(str(single))
            entry["glb"] = str(single)
        report.append(entry)

    # Named _split, not _parts: segment_mesh already writes asset_parts.json and
    # asset_parts_preview.glb, and a third "parts" file would be ambiguous.
    combined = out_dir / f"{stem}_split.glb"
    scene.export(str(combined))

    # Never drop geometry silently: if a filter removed parts, say which.
    if dropped:
        print(f"dropped {len(dropped)} part(s) below --min-face-share={args.min_face_share}: "
              + ", ".join(f"part {d['part']} ({d['face_share']:.3%})" for d in dropped), flush=True)

    summary = {
        "source": str(mesh_path), "labels": str(Path(args.labels).resolve()),
        "combined_glb": str(combined), "parts": report, "dropped": dropped,
        "total_faces_in": int(len(mesh.faces)),
        "total_faces_out": int(sum(p["faces"] for p in report)),
    }
    (out_dir / f"{stem}_split.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"SPLIT_OK {combined}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
