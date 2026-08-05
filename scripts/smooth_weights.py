#!/usr/bin/env python
"""Diffuse skin weights across the surface to soften hard bone boundaries.

    smooth_weights.py --rigged in.glb --out out.glb [--iterations 8] [--rate 0.5]

WHY
---
TokenRig's weights go near-binary across a handful of edges, and the mesh splits
along that line when the limb moves. Measured on emberwake_tpose, weight jump
across an edge (L1, 0 = identical, 2 = disjoint):

    median 0.1008   p90 0.4194   p99 0.8709   max 1.5738
    931 edges (6.34%) jump more than 0.5
    worst boundaries: RightUpLeg-Hips, Hips-LeftUpLeg, RightLeg-RightUpLeg

That is the hip/thigh junction, which is exactly where the skirt tears.

`rig_model(use_postprocess=True)` is NOT the fix and was measured: it sharpens
weights toward binary, taking edges over 0.5 from 6.34% to 12.09% and edges over
1.0 from 0.52% to 3.07%.

WELDING IS REQUIRED FIRST, AND IS NOT OPTIONAL
----------------------------------------------
A TRELLIS GLB carries ~37% duplicate vertices at UV-atlas seams - 7,730 vertices
collapse to 4,889 on position. Split that way the mesh looks like 316 disconnected
components with 29% of its edges on a boundary, and no diffusion can cross them.
Welded on position it is a single closed manifold with ZERO boundary edges, so the
graph the Laplacian needs does exist; it is just not the one the file hands you.

(This cost a wrong diagnosis once. A vertex-distance weld sweep will not reveal it,
because `trimesh.merge_vertices` preserves UV and normal splits at every tolerance.)

Weights are solved per welded vertex and written back to every duplicate, so
coincident vertices keep identical weights - which they already did, and which is
why there were never any seam cracks to fix.

CONSTRAINTS HELD
----------------
  * partition of unity - rows renormalised after every iteration and at the end
  * at most 4 influences per vertex, because glTF JOINTS_0/WEIGHTS_0 are VEC4.
    Truncation happens ONCE, at the end, so intermediate diffusion is not
    repeatedly clipped
  * no vertex may end with zero total weight; that would drop it out of the skin
"""

import argparse
import json
import struct
import sys

import numpy as np

GLTF_JSON_CHUNK = 0x4E4F534A
GLTF_MAGIC = 0x46546C67
_COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


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
        payload = bytes(payload)
        pad = (4 - len(payload) % 4) % 4
        payload += (b" " if ctype == GLTF_JSON_CHUNK else b"\x00") * pad
        out += struct.pack("<II", len(payload), ctype) + payload
    open(path, "wb").write(struct.pack("<III", GLTF_MAGIC, 2, 12 + len(out)) + out)


def accessor_layout(gltf, index):
    acc = gltf["accessors"][index]
    view = gltf["bufferViews"][acc["bufferView"]]
    fmt = _COMPONENT[acc["componentType"]]
    ncomp = _COUNT[acc["type"]]
    item = struct.calcsize(fmt) * ncomp
    stride = view.get("byteStride") or item
    base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    return fmt, ncomp, stride, base, acc["count"]


def read_accessor(gltf, binary, index):
    fmt, ncomp, stride, base, count = accessor_layout(gltf, index)
    return np.array([
        struct.unpack_from("<" + fmt * ncomp, binary, base + i * stride)
        for i in range(count)
    ])


def edge_jump(dense, faces):
    """L1 weight difference across every unique edge, for reporting."""
    e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    e = e[e[:, 0] != e[:, 1]]
    return np.abs(dense[e[:, 0]] - dense[e[:, 1]]).sum(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rigged", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--iterations", type=int, default=8)
    ap.add_argument("--rate", type=float, default=0.5,
                    help="diffusion rate per iteration, 0..1")
    args = ap.parse_args()

    chunks = read_glb(args.rigged)
    ji = next(i for i, c in enumerate(chunks) if c[0] == GLTF_JSON_CHUNK)
    bi = next(i for i, c in enumerate(chunks) if c[0] != GLTF_JSON_CHUNK)
    gltf = json.loads(bytes(chunks[ji][1]).decode("utf-8"))
    binary = chunks[bi][1]

    if not gltf.get("skins"):
        raise SystemExit(f"{args.rigged} has no skin; nothing to smooth")
    prim = gltf["meshes"][0]["primitives"][0]
    attrs = prim["attributes"]
    for need in ("POSITION", "JOINTS_0", "WEIGHTS_0"):
        if need not in attrs:
            raise SystemExit(f"{args.rigged} has no {need}; it is not skinned")

    njoints = len(gltf["skins"][0]["joints"])
    pos = read_accessor(gltf, binary, attrs["POSITION"])
    joints = read_accessor(gltf, binary, attrs["JOINTS_0"]).astype(int)
    weights = read_accessor(gltf, binary, attrs["WEIGHTS_0"])
    faces = read_accessor(gltf, binary, prim["indices"]).reshape(-1, 3).astype(int)

    # Weld on POSITION alone. See the module docstring: the file's own topology is
    # split at UV seams and has no connectivity to diffuse along.
    _uniq, inv = np.unique(np.round(pos, 6), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    nweld = inv.max() + 1

    dense = np.zeros((nweld, njoints))
    for i in range(len(pos)):
        for j, w in zip(joints[i], weights[i]):
            dense[inv[i], j] += w
    dense /= np.maximum(dense.sum(1, keepdims=True), 1e-12)

    wfaces = inv[faces]
    before = edge_jump(dense, wfaces)

    # Adjacency as a sparse sum: accumulate each neighbour's weights, count them,
    # divide. Cheaper and clearer than building an explicit Laplacian.
    e = np.vstack([wfaces[:, [0, 1]], wfaces[:, [1, 2]], wfaces[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    e = e[e[:, 0] != e[:, 1]]
    a, b = e[:, 0], e[:, 1]
    degree = np.bincount(a, minlength=nweld) + np.bincount(b, minlength=nweld)
    degree = np.maximum(degree, 1)[:, None]

    for _ in range(args.iterations):
        acc = np.zeros_like(dense)
        np.add.at(acc, a, dense[b])
        np.add.at(acc, b, dense[a])
        dense = (1.0 - args.rate) * dense + args.rate * (acc / degree)
        dense /= np.maximum(dense.sum(1, keepdims=True), 1e-12)

    after_full = edge_jump(dense, wfaces)

    # glTF allows four influences. Truncate once, at the end.
    order = np.argsort(-dense, axis=1)[:, :4]
    top = np.take_along_axis(dense, order, axis=1)
    total = top.sum(1, keepdims=True)
    if (total <= 1e-9).any():
        raise SystemExit("a vertex lost all weight during smoothing; refusing to write")
    top = top / total
    trunc = np.zeros_like(dense)
    np.put_along_axis(trunc, order, top, axis=1)
    after = edge_jump(trunc, wfaces)

    jfmt, _jn, jstride, jbase, _jc = accessor_layout(gltf, attrs["JOINTS_0"])
    wfmt, _wn, wstride, wbase, _wc = accessor_layout(gltf, attrs["WEIGHTS_0"])
    for i in range(len(pos)):
        k = inv[i]
        struct.pack_into("<" + jfmt * 4, binary, jbase + i * jstride, *order[k].tolist())
        struct.pack_into("<" + wfmt * 4, binary, wbase + i * wstride, *top[k].tolist())

    chunks[bi][1] = binary
    write_glb(args.out, chunks)

    def summarise(x):
        return {
            "median": round(float(np.median(x)), 4),
            "p90": round(float(np.percentile(x, 90)), 4),
            "p99": round(float(np.percentile(x, 99)), 4),
            "max": round(float(x.max()), 4),
            "over_0.5_pct": round(float(100 * (x > 0.5).mean()), 2),
            "over_1.0_pct": round(float(100 * (x > 1.0).mean()), 2),
        }

    print(json.dumps({
        "rigged": args.rigged, "out": args.out,
        "vertices": len(pos), "welded": int(nweld), "edges": int(len(e)),
        "iterations": args.iterations, "rate": args.rate,
        "edge_weight_jump": {
            "before": summarise(before),
            "after_smoothing": summarise(after_full),
            "after_truncation_to_4": summarise(after),
        },
        "min_total_weight": round(float(top.sum(1).min()), 6),
    }, indent=2))
    print(f"SMOOTH_OK {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
