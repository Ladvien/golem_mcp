#!/usr/bin/env python
"""Rig a decimated proxy, wear the weights on the full-resolution mesh.

    rig_proxy.py decimate --mesh full.glb --out proxy.glb --target-vertices 18000
    rig_proxy.py transfer --proxy rigged_proxy.glb --mesh full.glb --out rigged.glb

WHY
---
TRELLIS.2 ships ~88,700 vertices. TokenRig's training mixture is 1k-20k and it is
not a soft limit: a 34,670-vertex asset was killed by the OOM killer at 7.2 GB RSS.
So the mesh that gets rigged and the mesh that gets shipped cannot be the same one,
and `simplify=0.95` - which existed solely to force them to be - can go.

WHY NOT NEAREST-VERTEX TRANSFER
-------------------------------
Copying each target vertex's weights from its single nearest proxy vertex is the
obvious approach and it is the one with published counter-evidence. SkinCells
(CGF 2026) shows transferred weights producing spurious stretches in cloth, and
compares against RSWT (Abdrashitov et al. 2023 - the actual state of the art for
this operation) failing on loose garments with stretching and interpenetration.
Their failure figures are skirts. This character has a skirt.

So weights here are a smooth spatial FIELD, not a copy:

  1. inverse-distance blend over the k nearest proxy vertices, so a target vertex
     between two differently-weighted proxy vertices lands between them rather than
     snapping to whichever is marginally closer
  2. Laplacian diffusion across the TARGET's own surface afterwards, which is what
     removes the seams a per-vertex lookup leaves behind
  3. truncate to four influences last, once, because glTF's JOINTS_0/WEIGHTS_0 are
     VEC4 and clipping before diffusing would re-introduce what diffusing removed

That is not SkinCells - it does not optimise a field, it samples and then smooths
one - but it is materially better than the copy the literature warns about, and it
reuses machinery that already exists here.

WHY BLENDER RATHER THAN GLTF SURGERY
------------------------------------
Attaching a skin to a mesh that has none means new nodes, a skins array, an
inverseBindMatrices accessor and two vertex attributes, all consistent. Blender
already does that correctly on export, and its `vertex_group_smooth` and
`vertex_group_limit_total` operators are the diffusion and truncation steps. The
weld-and-hand-roll approach is reserved for edits that must NOT disturb the skin -
see orient_bones.py and smooth_weights.py.
"""

import argparse
import sys


def _clean_import(path):
    """Import a GLB into an empty scene, dropping SkinTokens' placeholder."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    for obj in list(bpy.context.scene.objects):
        if any(c.name.startswith("glTF_not_exported") for c in obj.users_collection):
            bpy.data.objects.remove(obj, do_unlink=True)
    return bpy.context.scene


def cmd_decimate(args):
    import bpy

    scene = _clean_import(args.mesh)
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit(f"{args.mesh} contains no mesh")
    before = sum(len(o.data.vertices) for o in meshes)
    if before <= args.target_vertices:
        raise SystemExit(
            f"{args.mesh} already has {before} vertices, at or under the {args.target_vertices} "
            "target - decimating would only lose detail for nothing."
        )

    # Weld first. The proxy is thrown away after rigging - it never needs UVs or
    # materials - and a TRELLIS.2 mesh carries ~37% duplicate vertices at UV-atlas
    # seams that collapse decimation cannot merge across. Without this the decimator
    # stalls: it bottomed out at 22,014 vertices after six passes against an 18,000
    # target, because every UV island has its own floor.
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=1e-5)
        bpy.ops.object.mode_set(mode="OBJECT")
    welded = sum(len(o.data.vertices) for o in meshes)

    # DECIMATE's ratio is a FACE ratio, and vertices do not fall proportionally -
    # asking for 0.20 returned 0.42 of the vertices. Iterate onto the vertex target
    # instead of solving for it, since the relationship depends on the topology.
    passes = 0
    current = welded
    while current > args.target_vertices and passes < 6:
        ratio = max(0.05, min(0.95, args.target_vertices / current))
        for obj in meshes:
            bpy.context.view_layer.objects.active = obj
            mod = obj.modifiers.new("proxy", type="DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = ratio
            bpy.ops.object.modifier_apply(modifier=mod.name)
        passes += 1
        current = sum(len(o.data.vertices) for o in meshes)

    after = current
    if after > args.target_vertices:
        raise SystemExit(
            f"decimation stalled at {after} vertices after {passes} passes, target "
            f"{args.target_vertices}. Rigging this would exceed TokenRig's range."
        )
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=args.out, export_format="GLB")
    print(f'{{"mesh": "{args.mesh}", "out": "{args.out}", '
          f'"vertices_before": {before}, "vertices_welded": {welded}, '
          f'"vertices_after": {after}, "passes": {passes}}}')
    print(f"DECIMATE_OK {args.out}")


def cmd_transfer(args):
    import bpy
    from mathutils.kdtree import KDTree

    scene = _clean_import(args.proxy)
    armature = next((o for o in scene.objects if o.type == "ARMATURE"), None)
    if armature is None:
        raise SystemExit(f"{args.proxy} has no armature - it is not a rigged proxy")
    proxy = next((o for o in scene.objects if o.type == "MESH"), None)
    if proxy is None:
        raise SystemExit(f"{args.proxy} has no mesh to read weights from")

    bone_names = [b.name for b in armature.data.bones]
    slot_of = {g.name: g.index for g in proxy.vertex_groups}
    group_name = {v: k for k, v in slot_of.items()}

    # Proxy sample points and their weight vectors, in world space.
    pts, weights = [], []
    for vert in proxy.data.vertices:
        pts.append(proxy.matrix_world @ vert.co)
        w = {}
        for g in vert.groups:
            name = group_name.get(g.group)
            if name and g.weight > 1e-6:
                w[name] = w.get(name, 0.0) + g.weight
        total = sum(w.values())
        weights.append({k: v / total for k, v in w.items()} if total > 1e-9 else {})
    tree = KDTree(len(pts))
    for i, p in enumerate(pts):
        tree.insert(p, i)
    tree.balance()

    # Bring the full-resolution mesh into the same scene.
    before = set(scene.objects)
    bpy.ops.import_scene.gltf(filepath=args.mesh)
    added = [o for o in scene.objects if o not in before]
    for obj in list(added):
        if any(c.name.startswith("glTF_not_exported") for c in obj.users_collection):
            bpy.data.objects.remove(obj, do_unlink=True)
            added.remove(obj)
    targets = [o for o in added if o.type == "MESH"]
    if not targets:
        raise SystemExit(f"{args.mesh} contains no mesh")

    for target in targets:
        for name in bone_names:
            if name not in target.vertex_groups:
                target.vertex_groups.new(name=name)
        for vert in target.data.vertices:
            co = target.matrix_world @ vert.co
            near = tree.find_n(co, args.neighbours)
            # Inverse distance, so a vertex between two differently-weighted proxy
            # points lands between them instead of snapping to the nearer one.
            blended = {}
            total = 0.0
            for _p, idx, dist in near:
                infl = 1.0 / max(dist, 1e-6) ** 2
                total += infl
                for name, w in weights[idx].items():
                    blended[name] = blended.get(name, 0.0) + w * infl
            if total <= 1e-12 or not blended:
                raise SystemExit(
                    f"vertex at {tuple(round(c, 4) for c in co)} found no weighted proxy "
                    "neighbour; the proxy and the mesh are not the same object"
                )
            for name, w in blended.items():
                target.vertex_groups[name].add([vert.index], w / total, "REPLACE")

        # Diffuse across the TARGET's surface, then clip to glTF's four influences.
        bpy.context.view_layer.objects.active = target
        bpy.ops.object.select_all(action="DESELECT")
        target.select_set(True)
        # vertex_group_smooth polls for edit mode with a selection; the limit and
        # normalize operators are object-mode. Getting this wrong fails at poll()
        # with "context is incorrect" rather than doing nothing quietly.
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        for _ in range(args.smooth_iterations):
            bpy.ops.object.vertex_group_smooth(group_select_mode="ALL", factor=0.5)
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)

        target.parent = armature
        mod = target.modifiers.new("Armature", type="ARMATURE")
        mod.object = armature

    # The proxy has done its job; shipping it would put two bodies in the file.
    bpy.data.objects.remove(proxy, do_unlink=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=args.out, export_format="GLB")

    verts = sum(len(o.data.vertices) for o in targets)
    print(f'{{"proxy": "{args.proxy}", "mesh": "{args.mesh}", "out": "{args.out}", '
          f'"proxy_samples": {len(pts)}, "target_vertices": {verts}, '
          f'"bones": {len(bone_names)}, "neighbours": {args.neighbours}, '
          f'"smooth_iterations": {args.smooth_iterations}}}')
    print(f"TRANSFER_OK {args.out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decimate", help="collapse a mesh to a rig-sized proxy")
    d.add_argument("--mesh", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--target-vertices", type=int, default=8_000,
                   help="TokenRig's training mixture is 1k-20k, but memory scales "
                        "steeply: a 16,882-vertex proxy was OOM-killed at 9.5 GB RSS. "
                        "The proxy only supplies landmarks and a weight field that is "
                        "resampled onto the full mesh, so its resolution matters less "
                        "than the shipped mesh's.")
    d.set_defaults(func=cmd_decimate)

    t = sub.add_parser("transfer", help="sample the proxy's weights onto the full mesh")
    t.add_argument("--proxy", required=True, help="the RIGGED proxy")
    t.add_argument("--mesh", required=True, help="the full-resolution mesh")
    t.add_argument("--out", required=True)
    t.add_argument("--neighbours", type=int, default=8)
    t.add_argument("--smooth-iterations", type=int, default=4)
    t.set_defaults(func=cmd_transfer)

    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
