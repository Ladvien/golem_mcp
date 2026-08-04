#!/usr/bin/env python
"""Point every bone at its child, preserving the bind pose exactly.

    orient_bones.py --rigged in.glb --out out.glb

THIS DOES NOT FIX RETARGETING - MEASURED
----------------------------------------
It was built expecting to. It does not, and the negative result is worth more than
the script: retargeting `emberwake_herald` before and after orienting produced
BYTE-IDENTICAL output - gait +0.874, arm abduction 55-86 deg, hand swing 77%.

The reason is that the rest-relative delta is invariant to bone-axis convention.
`src_posed * src_rest^-1 * tgt_rest` cancels whatever frame each bone happens to
use, and recomputing inverseBindMatrices cancels it again in the skinning. So the
148.7 degree rest mismatch between our LeftArm and Mixamo's is NOT a convention
artifact - it is the genuine difference between an asset whose arms hang at 45
degrees and a clip authored against a T-pose. That is geometry, not bookkeeping,
and no amount of reorienting bones touches it.

WHAT IT IS ACTUALLY FOR
-----------------------
Hand-animation. SkinTokens' writer does not orient joints along their limbs -
measured on emberwake_herald, the angle between a bone's axis and the direction to
its child:

    Hips 0.0   Spine 3.6   LeftForeArm 3.0   LeftLeg 4.4
    LeftArm 35.3           LeftUpLeg 58.7          -> 8 of 18 bones over 20 deg

An animator rotating such a bone in Blender gets a limb bending about an axis that
has nothing to do with it. After this runs, every bone points at its child (max
angle 121.1 -> 0.0 deg), which is what makes a rig workable by hand. Automated
retargeting neither needs nor notices it.

WHAT THIS DOES
--------------
glTF has no notion of a bone tail; a bone's orientation IS its node's rotation,
and Blender reads it as such. So for each joint:

    new world rotation = the rotation whose Y axis points at the child joint,
                         with roll carried over from the old rotation so no
                         gratuitous twist is introduced

Translations are untouched, so every joint stays exactly where it was. Local
transforms are then recomputed from the new world matrices, and the skin's
inverseBindMatrices are recomputed as the inverse of the new world matrices.

That last step is what makes this safe. Skinning evaluates

    sum_j  w_j * (jointWorld_j * inverseBind_j) * vertex

and at the bind pose jointWorld_j * inverseBind_j is the identity by definition.
Recomputing inverseBind_j = inverse(jointWorld_j) restores that identity exactly,
so the rest mesh is bit-for-bit unchanged while the axes it rotates about are
fixed. Skipping it would smear the mesh the moment the rig loaded.

Leaf joints have nothing to point at and inherit their parent's new rotation,
which keeps hands and toes from twisting relative to the limb they cap.
"""

import argparse
import json
import struct
import sys

import numpy as np

GLTF_JSON_CHUNK = 0x4E4F534A
GLTF_MAGIC = 0x46546C67


def read_glb(path):
    data = open(path, "rb").read()
    magic, _ver, total = struct.unpack("<III", data[:12])
    if magic != GLTF_MAGIC:
        raise SystemExit(f"{path} is not a GLB")
    chunks, off = [], 12
    while off < total:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        chunks.append([ctype, bytearray(data[off + 8:off + 8 + clen])])
        off += 8 + clen
    return chunks


def write_glb(path, chunks):
    out = b""
    for ctype, payload in chunks:
        pad = (4 - len(payload) % 4) % 4
        payload = bytes(payload) + (b" " if ctype == GLTF_JSON_CHUNK else b"\x00") * pad
        out += struct.pack("<II", len(payload), ctype) + payload
    open(path, "wb").write(struct.pack("<III", GLTF_MAGIC, 2, 12 + len(out)) + out)


def local_matrix(node):
    """A node's local 4x4. glTF stores `matrix` column-major."""
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        m[:3, :3] = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    if "scale" in node:
        m[:3, :3] = m[:3, :3] @ np.diag(node["scale"])
    if "translation" in node:
        m[:3, 3] = node["translation"]
    return m


def aim(old_rot, direction):
    """Rotation whose Y axis is `direction`, keeping as much of old_rot's roll as possible."""
    y = direction / np.linalg.norm(direction)
    x = old_rot[:, 0] - y * float(old_rot[:, 0] @ y)
    if np.linalg.norm(x) < 1e-6:                 # old X was parallel to the new Y
        x = old_rot[:, 2] - y * float(old_rot[:, 2] @ y)
    if np.linalg.norm(x) < 1e-6:                 # degenerate both ways; any perpendicular
        x = np.cross(y, [1.0, 0.0, 0.0])
        if np.linalg.norm(x) < 1e-6:
            x = np.cross(y, [0.0, 0.0, 1.0])
    x /= np.linalg.norm(x)
    return np.stack([x, y, np.cross(x, y)], axis=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rigged", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    chunks = read_glb(args.rigged)
    ji = next(i for i, (t, _) in enumerate(chunks) if t == GLTF_JSON_CHUNK)
    gltf = json.loads(bytes(chunks[ji][1]).decode("utf-8"))
    binary = next(p for t, p in chunks if t != GLTF_JSON_CHUNK)

    if not gltf.get("skins"):
        raise SystemExit(f"{args.rigged} has no skin; there is nothing to orient")
    skin = gltf["skins"][0]
    joints = skin["joints"]
    nodes = gltf["nodes"]

    parent_of = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}

    def world(i, cache={}):
        if i in cache:
            return cache[i]
        m = local_matrix(nodes[i])
        p = parent_of.get(i)
        out = m if p is None else world(p) @ m
        cache[i] = out
        return out

    joint_set = set(joints)
    old_world = {i: world(i) for i in joints}
    # Non-joint ancestors keep their transforms, so a joint's parent world matrix
    # is whatever it already was unless that parent is itself a joint.
    new_world = {}

    # Parents before children: a child's new local transform is expressed in its
    # parent's NEW frame.
    def depth(i):
        d, k = 0, i
        while parent_of.get(k) is not None:
            d, k = d + 1, parent_of[k]
        return d

    for i in sorted(joints, key=depth):
        kids = [c for c in nodes[i].get("children", []) if c in joint_set]
        old = old_world[i]
        pos = old[:3, 3]
        if kids:
            direction = old_world[kids[0]][:3, 3] - pos
            rot = aim(old[:3, :3], direction) if np.linalg.norm(direction) > 1e-9 else old[:3, :3]
        else:
            p = parent_of.get(i)
            rot = new_world[p][:3, :3] if p in new_world else old[:3, :3]
        m = np.eye(4)
        m[:3, :3] = rot
        m[:3, 3] = pos
        new_world[i] = m

    # Rewrite each joint's LOCAL transform against its parent's new world matrix.
    for i in joints:
        p = parent_of.get(i)
        parent_world = new_world[p] if p in new_world else (world(p) if p is not None else np.eye(4))
        local = np.linalg.inv(parent_world) @ new_world[i]
        node = nodes[i]
        for key in ("rotation", "translation", "scale", "matrix"):
            node.pop(key, None)
        node["matrix"] = [float(v) for v in local.T.reshape(-1)]   # column-major

    # Recompute inverseBindMatrices, or the mesh smears on load.
    acc = gltf["accessors"][skin["inverseBindMatrices"]]
    if acc["componentType"] != 5126 or acc["type"] != "MAT4":
        raise SystemExit("inverseBindMatrices is not float MAT4; refusing to guess its layout")
    if acc["count"] != len(joints):
        raise SystemExit(f"inverseBindMatrices count {acc['count']} != {len(joints)} joints")
    bv = gltf["bufferViews"][acc["bufferView"]]
    base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    for slot, i in enumerate(joints):
        ibm = np.linalg.inv(new_world[i])
        struct.pack_into("<16f", binary, base + slot * 64, *ibm.T.reshape(-1))

    chunks[ji][1] = bytearray(json.dumps(gltf, separators=(",", ":")).encode("utf-8"))
    write_glb(args.out, chunks)

    # Report the thing this exists to fix.
    def angle_to_child(i, table):
        kids = [c for c in nodes[i].get("children", []) if c in joint_set]
        if not kids:
            return None
        d = table[kids[0]][:3, 3] - table[i][:3, 3]
        if np.linalg.norm(d) < 1e-9:
            return None
        d = d / np.linalg.norm(d)
        return float(np.degrees(np.arccos(np.clip(table[i][:3, 1] @ d, -1, 1))))

    before = [a for a in (angle_to_child(i, old_world) for i in joints) if a is not None]
    after = [a for a in (angle_to_child(i, new_world) for i in joints) if a is not None]
    print(json.dumps({
        "rigged": args.rigged, "out": args.out, "joints": len(joints),
        "bones_with_a_child": len(before),
        "axis_off_child_deg": {
            "before": {"max": round(max(before), 1), "mean": round(sum(before) / len(before), 1),
                       "over_20deg": sum(1 for a in before if a > 20)},
            "after": {"max": round(max(after), 1), "mean": round(sum(after) / len(after), 1),
                      "over_20deg": sum(1 for a in after if a > 20)},
        },
    }, indent=2))
    print(f"ORIENT_OK {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
