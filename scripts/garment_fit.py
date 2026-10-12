#!/usr/bin/env python
"""Place a generated garment onto a target body, push it out of the body, and skin it there.

Run by the SegviGen venv (python 3.11) - it has both trimesh and bpy, and neither
stage needs the GPU. Normally a subprocess of the MCP server's `generate_garment`.

PLACEMENT (numpy, deterministic)
--------------------------------
A garment from `trellis2_garment.py` arrives normalized to roughly a 1 m cube,
because that is what TRELLIS does to everything. Three transforms put it on a body:

  1. Yaw so the garment's shoulder axis matches the body's.
  2. Scale by matching FRONT-BACK DEPTH inside the anchor band. Depth is the one
     horizontal axis an arm pose cannot distort - a T-pose body's width across the
     shoulders includes both arms, so matching width would shrink every garment by
     the arm span. Measured on female_base_v5: depth 0.34 m, "width" 1.70 m.
  3. Translate the garment's vertical centre onto the band's centre.

One rule for every garment, no correspondence search and no ICP.

DRAPING (bpy)
-------------
Shrinkwrap to evict penetrating vertices, headless in bpy 4.5.9. There is no cloth
pass: there was one, and it never reached the output. The export evaluated the
unsimulated mesh (the shipped garment matched shrinkwrap alone to 0.15 mm on
female_base_v5, 2026-10-12); the simulation itself diverged there (vertices 5 m out
by frame 6); and on a dressed 1 m villager it ran 35-90 s a frame, so the fit outlived
generate_garment's timeout and the tool failed with no fit report.

The mode matters more than anything else here. `wrap_mode='OUTSIDE'` moves a vertex
ONLY if it is inside the target, so it pushes the intersecting parts out and leaves
the rest of the garment's shape untouched. Measured on corset -> female_base_v5,
that took vertices-inside-the-body from 32.4% after placement to **0.0%**.

`TARGET_PROJECT` was tried first and is wrong for this: it projects every vertex
onto the surface, which collapses a corset flat against the skin, and because it
pulls a nearly-coincident surface in both directions it still left 30.9% inside.

SKINNING (bpy)
--------------
The fitted garment then takes the body's skin weights, interpolated over the nearest
body face, and is bound to the body's armature, so `<name>_skinned.glb` follows any
clip that drives the body. Nothing else in golem skins a mesh that is not a character.

AXES
----
glTF is Y-up and both assets are glTF, so Y is height. Asserted rather than
assumed silently, because getting it wrong yaws the garment onto its side and the
result still looks superficially plausible.
"""

import argparse
import json
import sys
from pathlib import Path

# Vertical bands as fractions of body height measured from the feet. A corset
# spans chest to waist; the rest exist so the same tool can place other pieces.
ANCHORS = {
    "torso": (0.55, 0.82),
    "chest": (0.62, 0.82),
    "waist": (0.50, 0.66),
    "hips": (0.42, 0.58),
    "legs": (0.05, 0.50),
    "full": (0.00, 1.00),
}
UP = 1   # glTF Y-up


ARM_SLICE_REJECT = 2.0   # a slice wider than this * the median is limbs, not torso


def horizontal_extents(points, lo, hi, slices: int = 24):
    """Robust (depth, width) of the points in a vertical band, ignoring limbs.

    A whole-band bounding box is useless on a T-pose body: measured on
    female_base_v5, torso slices are 0.27-0.35 m across, but the two slices at
    shoulder height are 1.70 and 0.97 - the arm span. Slicing and dropping the
    anomalously wide slices recovers the torso without hard-coding where arms are.
    """
    import numpy as np

    band = points[(points[:, UP] >= lo) & (points[:, UP] <= hi)]
    if len(band) == 0:
        raise SystemExit(f"no geometry between {lo:.3f} and {hi:.3f} on the up axis")
    horiz = [a for a in (0, 1, 2) if a != UP]

    edges = np.linspace(lo, hi, slices + 1)
    per_slice = []
    for i in range(slices):
        s = band[(band[:, UP] >= edges[i]) & (band[:, UP] < edges[i + 1])]
        if len(s) < 3:
            continue
        per_slice.append([float(s[:, a].max() - s[:, a].min()) for a in horiz])
    if not per_slice:
        per_slice = [[float(band[:, a].max() - band[:, a].min()) for a in horiz]]
    per_slice = np.array(per_slice)

    widest = per_slice.max(axis=1)
    keep = per_slice[widest <= ARM_SLICE_REJECT * np.median(widest)]
    if len(keep) == 0:
        keep = per_slice
    spans = {a: float(keep[:, j].max()) for j, a in enumerate(horiz)}

    wide = max(spans, key=spans.get)
    narrow = min(spans, key=spans.get)
    return spans[narrow], spans[wide], wide, narrow, band


def place(garment, body, anchor: str, ease: float):
    """Yaw, scale and translate the garment onto the body. Returns the report."""
    import numpy as np

    lo_f, hi_f = ANCHORS[anchor]
    b_min, b_max = body.bounds
    height = float(b_max[UP] - b_min[UP])
    lo, hi = b_min[UP] + lo_f * height, b_min[UP] + hi_f * height

    b_depth, b_width, b_wide, b_narrow, b_band = horizontal_extents(body.vertices, lo, hi)
    g_min, g_max = garment.bounds
    g_depth, g_width, g_wide, g_narrow, _ = horizontal_extents(
        garment.vertices, g_min[UP], g_max[UP])

    # 1. Yaw: align the garment's wide horizontal axis with the body's.
    yawed = False
    if g_wide != b_wide:
        rot = np.eye(4)
        c, s = 0.0, 1.0   # exactly 90 degrees about the up axis
        a0, a1 = [a for a in (0, 1, 2) if a != UP]
        rot[a0, a0], rot[a0, a1] = c, -s
        rot[a1, a0], rot[a1, a1] = s, c
        garment.apply_transform(rot)
        g_depth, g_width = g_width, g_depth
        yawed = True

    # 2. Scale so the garment SPANS THE ANCHOR BAND vertically, and let its own
    #    proportions decide the girth. TRELLIS normalizes by the largest dimension,
    #    so a garment arrives with its true aspect ratio intact - a corset that is
    #    0.71 wide per 1.0 tall really is that shape. Scaling on height therefore
    #    gets the girth right for free.
    #
    #    Scaling to enclose the body horizontally instead does not work: the band's
    #    widest slice includes the deltoids (0.56 m against a 0.31 m chest), and
    #    matching that made a corset 0.94 m tall on a 1.7 m body.
    g_height = float(garment.bounds[1][UP] - garment.bounds[0][UP])
    scale = (hi - lo) / g_height
    garment.apply_scale(scale)
    g_depth, g_width = g_depth * scale, g_width * scale

    # 3. Translate: garment centre onto band centre, horizontally onto the body's.
    g_min, g_max = garment.bounds
    target = np.array([
        (b_band[:, 0].min() + b_band[:, 0].max()) / 2,
        (lo + hi) / 2,
        (b_band[:, 2].min() + b_band[:, 2].max()) / 2,
    ])
    target[UP] = (lo + hi) / 2
    garment.apply_translation(target - (g_min + g_max) / 2)

    return {
        "anchor": anchor, "ease": ease, "yawed_90deg": yawed, "scale": round(float(scale), 4),
        "body_height": round(height, 4),
        "band": [round(float(lo), 4), round(float(hi), 4)],
        "body_depth_in_band": round(float(b_depth), 4),
        "body_width_in_band": round(float(b_width), 4),
        "garment_width_after_scale": round(float(g_width), 4),
        "garment_depth_after_scale": round(float(g_depth), 4),
        # >1 means the garment is roomier than the body there, which is what the
        # cloth pass wants; <1 means it starts interpenetrating and shrinkwrap has
        # to push it out rather than pull it in.
        "clearance_width": round(float(g_width / b_width), 3),
        "clearance_depth": round(float(g_depth / b_depth), 3),
        "placed_extents": [round(float(v), 4) for v in (garment.bounds[1] - garment.bounds[0])],
    }


def penetration(garment, body, samples: int = 200_000):
    """Fraction of garment vertices sitting inside the body surface.

    Nearest surface sample + that face's normal, rather than
    trimesh.proximity.signed_distance (which needs a watertight mesh - these bodies
    are not) or ProximityQuery (which needs rtree, absent from this venv). Sampling
    gives whatever spatial resolution is needed without a C extension: the body's
    own 6.2k vertices are ~2-3 cm apart, far too coarse against a 6 mm standoff.
    """
    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree

    points, face_idx = trimesh.sample.sample_surface(body, samples)
    tree = cKDTree(points)
    _, nearest = tree.query(garment.vertices, k=1, workers=-1)
    normals = body.face_normals[face_idx[nearest]]
    outward = np.einsum("ij,ij->i", garment.vertices - points[nearest], normals)
    return float((outward < 0).mean())


def drape(garment_path: Path, body_path: Path, out_path: Path, thickness: float):
    """Shrinkwrap the garment out of the body, headless."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(body_path))
    body = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
    body.name = "body"
    before = {o.name for o in bpy.context.scene.objects}
    bpy.ops.import_scene.gltf(filepath=str(garment_path))
    garment = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name not in before][0]
    garment.name = "garment"

    # wrap_mode OUTSIDE moves a vertex ONLY if it is inside the target. That is the
    # whole trick: it evicts the penetrating vertices while leaving the rest of the
    # garment's shape alone. TARGET_PROJECT was tried first and is wrong here - it
    # projects every vertex onto the surface, collapsing a corset flat against the
    # skin, and it left 30.9% of vertices still inside because it pulls a
    # nearly-coincident surface both ways.
    sw = garment.modifiers.new("Shrinkwrap", "SHRINKWRAP")
    sw.target = body
    sw.wrap_method = "NEAREST_SURFACEPOINT"
    sw.wrap_mode = "OUTSIDE"
    sw.offset = thickness            # hold the garment off the skin
    bpy.context.view_layer.objects.active = garment
    bpy.ops.object.modifier_apply(modifier="Shrinkwrap")
    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(out_path), export_format="GLB",
                              use_selection=True, export_apply=True)


def skin_to_body(garment_path: Path, body_path: Path, out_path: Path) -> dict:
    """Weight the fitted garment from the body's own skin and bind it to the body's armature.

    Each garment vertex takes the weights interpolated over the nearest body face, so the cloth follows the bones the
    skin under it follows, and a clip that drives the body drives the garment: the bone names are the body's.
    """
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(body_path))
    scene = bpy.context.scene
    for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
    if arm is None:
        return {"skinned_glb": None, "skin_warning": "body has no armature"}
    body = next((o for o in scene.objects
                 if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)), None)
    if body is None:
        return {"skinned_glb": None, "skin_warning": "body has an armature but no mesh skinned to it"}

    before = set(scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(garment_path))
    garment = next(o for o in scene.objects if o not in before and o.type == "MESH")
    garment.name = "garment"

    bpy.ops.object.select_all(action="DESELECT")
    garment.select_set(True)
    bpy.context.view_layer.objects.active = garment
    dt = garment.modifiers.new("BodyWeights", "DATA_TRANSFER")
    dt.object = body
    dt.use_vert_data = True
    dt.data_types_verts = {"VGROUP_WEIGHTS"}
    dt.vert_mapping = "POLYINTERP_NEAREST"
    dt.layers_vgroup_select_src = "ALL"
    dt.layers_vgroup_select_dst = "NAME"
    bpy.ops.object.datalayout_transfer(modifier=dt.name)
    bpy.ops.object.modifier_apply(modifier=dt.name)
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)

    world = garment.matrix_world.copy()
    garment.parent = arm
    garment.matrix_world = world
    mod = garment.modifiers.new("Armature", "ARMATURE")
    mod.object = arm

    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    garment.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(out_path), export_format="GLB", use_selection=True,
                              export_skins=True, export_animations=False)

    unweighted = sum(1 for v in garment.data.vertices if sum(g.weight for g in v.groups) < 0.01)
    return {"skinned_glb": str(out_path), "unweighted_vertices": unweighted}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--garment", required=True)
    ap.add_argument("--body", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", default="garment_fitted")
    ap.add_argument("--anchor", default="torso", choices=sorted(ANCHORS))
    ap.add_argument("--ease", type=float, default=1.08, help="scale margin so cloth sits off the skin")
    ap.add_argument("--thickness", type=float, default=0.006, help="metres of standoff")
    ap.add_argument("--no-drape", action="store_true", help="place only; skip the shrinkwrap stage")
    args = ap.parse_args()

    import trimesh

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    body = trimesh.load(args.body, force="mesh", process=False)
    garment = trimesh.load(args.garment, force="mesh", process=False)

    b_ext = body.bounds[1] - body.bounds[0]
    if not (b_ext[UP] >= 0.9 * b_ext.max()):
        raise SystemExit(
            f"body extents {b_ext.round(3).tolist()} - axis {UP} is not the tallest, so this is "
            "not the Y-up glTF this tool assumes. Placement would yaw the garment onto its side.")

    report = place(garment, body, args.anchor, args.ease)
    placed = out_dir / f"{args.name}_placed.glb"
    garment.export(str(placed))
    report["placed_glb"] = str(placed)
    report["penetration_after_placement"] = round(penetration(garment, body), 4)

    if not args.no_drape:
        draped = out_dir / f"{args.name}.glb"
        drape(placed, Path(args.body), draped, args.thickness)
        report["draped_glb"] = str(draped)
        d = trimesh.load(str(draped), force="mesh", process=False)
        report["penetration_after_drape"] = round(penetration(d, body), 4)
        report["draped_faces"] = int(len(d.faces))

    fitted = Path(report.get("draped_glb") or placed)
    report.update(skin_to_body(fitted, Path(args.body), out_dir / f"{args.name}_skinned.glb"))

    report_path = out_dir / f"{args.name}_fit.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"GARMENT_FIT_OK {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
