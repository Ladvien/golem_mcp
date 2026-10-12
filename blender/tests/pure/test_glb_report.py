"""Pure layer: the stdlib .glb parser, exercised on synthetic bytes.

No committed fixture: _evaluate/golden/*.glb are deliberately
untracked, so the test assembles its own JSON chunk + BIN chunk.

The chunk layout mirrors Blender's exporter (io_scene_gltf2
export.py): the JSON chunk's length field carries the PADDED length
(length_gltf += spaces_gltf), not the raw JSON byte count.
"""

import json
import struct

import pytest

from blended.export.glb_report import (
    GLB_CHUNK_HEADER_SIZE_BYTES,
    GLB_HEADER_SIZE_BYTES,
    GLB_MAGIC,
    asset_report,
    format_glb_report,
    parse_glb,
    read_accessor,
)

# float32 encoding of (0,0,0), (1,0,0), (0,1,0) — two triangles sharing
# the edge (1,0,0)-(0,1,0).
SHARED_EDGE_POSITIONS = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (1.0, 1.0, 0.0),
)
UP_NORMALS = (
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
)
# glTF requires the NORMAL accessor to cover every POSITION; the
# 5-vertex fixtures need 5 normals.
UP_NORMALS_5 = UP_NORMALS + ((0.0, 0.0, 1.0),)


def _pack_components(values):
    return b"".join(struct.pack("<fff", *value) for value in values)


def _json_chunk(payload: bytes) -> bytes:
    """Blender-style JSON chunk: length field is the PADDED length."""
    padding = (4 - (len(payload) & 3)) & 3
    return (
        struct.pack("<I", len(payload) + padding) + b"JSON" + payload + b" " * padding
    )


def _bin_chunk(payload: bytes) -> bytes:
    padding = (4 - (len(payload) & 3)) & 3
    return (
        struct.pack("<I", len(payload) + padding)
        + b"BIN\x00"
        + payload
        + b"\x00" * padding
    )


def _build_glb(positions, indices, normals=None):
    """Assemble a minimal .glb: one mesh, one triangle primitive."""
    binary = bytearray()
    binary.extend(_pack_components(positions))
    if normals is not None:
        binary.extend(_pack_components(normals))
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    while len(binary) % 4:
        binary.append(0)

    buffer_views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}]
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [
                min(p[0] for p in positions),
                min(p[1] for p in positions),
                min(p[2] for p in positions),
            ],
            "max": [
                max(p[0] for p in positions),
                max(p[1] for p in positions),
                max(p[2] for p in positions),
            ],
        }
    ]
    attributes = {"POSITION": 0}

    offset = len(_pack_components(positions))
    if normals is not None:
        buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(_pack_components(normals)),
            }
        )
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            }
        )
        attributes["NORMAL"] = len(accessors) - 1
        offset += len(_pack_components(normals))
    buffer_views.append(
        {
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(indices) * 4,
        }
    )
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "Tri",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"name": "TriNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def _write_glb(tmp_path, data, name="test.glb"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_two_triangles_sharing_an_edge(tmp_path):
    """Two triangles on one shared edge: 2 tris, 4 welded boundary
    edges, 0 non-manifold, 0 inverted."""
    indices = (0, 1, 2, 1, 3, 2)
    path = _write_glb(tmp_path, _build_glb(SHARED_EDGE_POSITIONS, indices, UP_NORMALS))
    report = asset_report(path)
    mesh = report.meshes["Tri"]
    assert report.triangle_count == 2
    assert mesh.triangle_count == 2
    assert mesh.welded_boundary_edge_count == 4
    assert mesh.non_manifold_edge_count == 0
    assert mesh.inverted_facet_count == 0
    assert mesh.has_normals is True
    assert mesh.uv_set_count == 0


def test_duplicated_shared_vertices_do_not_weld(tmp_path):
    """The same two triangles with their shared vertices duplicated
    1 mm apart: the weld is load-bearing — 6 boundary edges, not 4."""
    positions = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (1.001, 0.0, 0.0),
        (0.001, 1.0, 0.0),
    )
    indices = (0, 1, 2, 1, 3, 4)
    path = _write_glb(tmp_path, _build_glb(positions, indices, UP_NORMALS_5))
    report = asset_report(path)
    assert report.meshes["Tri"].welded_boundary_edge_count == 6


def test_three_triangles_on_one_shared_edge(tmp_path):
    """Three triangles on one edge: that edge is used 3 times ->
    non-manifold."""
    positions = (
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (1.0, -1.0, 0.0),
    )
    indices = (0, 1, 2, 0, 1, 3, 0, 1, 4)
    path = _write_glb(tmp_path, _build_glb(positions, indices, UP_NORMALS_5))
    report = asset_report(path)
    assert report.meshes["Tri"].non_manifold_edge_count == 1


def test_reversed_winding_is_an_inverted_facet(tmp_path):
    """One triangle with reversed winding against unchanged normals."""
    indices = (0, 2, 1)
    path = _write_glb(
        tmp_path, _build_glb(SHARED_EDGE_POSITIONS[:3], indices, UP_NORMALS[:3])
    )
    report = asset_report(path)
    assert report.meshes["Tri"].inverted_facet_count == 1


def test_bad_magic_raises(tmp_path):
    path = tmp_path / "bad.glb"
    path.write_bytes(b"not a glb at all")
    with pytest.raises(ValueError, match="bad magic"):
        parse_glb(path)


def test_declared_length_disagrees_raises(tmp_path):
    data = _build_glb(SHARED_EDGE_POSITIONS[:3], (0, 1, 2))
    bad = bytearray(data)
    bad[8:12] = struct.pack("<I", len(data) + 100)
    path = tmp_path / "lying.glb"
    path.write_bytes(bad)
    with pytest.raises(ValueError, match="declares"):
        parse_glb(path)


def test_sparse_accessor_raises_not_implemented(tmp_path):
    data = _build_glb(SHARED_EDGE_POSITIONS[:3], (0, 1, 2))
    json_length = struct.unpack("<I", data[12:16])[0]
    json_start = GLB_HEADER_SIZE_BYTES + 8
    gltf = json.loads(data[json_start : json_start + json_length])
    gltf["accessors"][0]["sparse"] = {
        "count": 1,
        "indices": {"bufferView": 1, "byteOffset": 0, "componentType": 5123},
        "values": {"bufferView": 2},
    }
    gltf_bytes = json.dumps(gltf).encode("utf-8")
    binary = b"\x00" * 24
    json_chunk = _json_chunk(gltf_bytes)
    bin_chunk = _bin_chunk(binary)
    header = struct.pack(
        "<III", GLB_MAGIC, 2, GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    )
    path = tmp_path / "sparse.glb"
    path.write_bytes(header + json_chunk + bin_chunk)
    gltf_parsed, _ = parse_glb(path)
    with pytest.raises(NotImplementedError, match="sparse"):
        read_accessor(gltf_parsed, b"", 0)


def test_read_accessor_without_buffer_view_raises():
    gltf = {"accessors": [{"componentType": 5126, "count": 3, "type": "VEC3"}]}
    with pytest.raises(ValueError, match="no bufferView"):
        read_accessor(gltf, b"", 0)


def test_format_glb_report_baseline_hides_unchanged_meshes(tmp_path):
    indices = (0, 1, 2, 1, 3, 2)
    path = _write_glb(tmp_path, _build_glb(SHARED_EDGE_POSITIONS, indices))
    report = asset_report(path)
    baseline = asset_report(path)
    text = format_glb_report(report, baseline)
    assert "meshes removed: none" in text
    assert "meshes added:   none" in text
    # No per-mesh row when nothing changed: nothing after the
    # "per mesh" header names the mesh.
    assert "Tri" not in text.split("per mesh")[1]


def _build_glb_with_weights(positions, indices, weights, normals=None):
    """Assemble a .glb with a WEIGHTS_0 + JOINTS_0 skinned primitive.

    ``weights`` is a sequence of 4-tuples (one per vertex).  Joints are
    all-zero (joint identity does not affect the three skin metrics).
    """
    binary = bytearray()
    binary.extend(_pack_components(positions))
    pos_len = len(_pack_components(positions))
    if normals is not None:
        binary.extend(_pack_components(normals))
    normals_len = len(_pack_components(normals)) if normals else 0
    # WEIGHTS_0: float32 VEC4, one per vertex.
    weights_bytes = b"".join(struct.pack("<ffff", *w) for w in weights)
    binary.extend(weights_bytes)
    weights_len = len(weights_bytes)
    # JOINTS_0: unsigned-byte VEC4, one per vertex.
    joints_bytes = b"".join(struct.pack("<BBBB", 0, 0, 0, 0) for _ in weights)
    binary.extend(joints_bytes)
    joints_len = len(joints_bytes)
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    indices_len = len(indices) * 4
    while len(binary) % 4:
        binary.append(0)

    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": pos_len},
    ]
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [
                min(p[0] for p in positions),
                min(p[1] for p in positions),
                min(p[2] for p in positions),
            ],
            "max": [
                max(p[0] for p in positions),
                max(p[1] for p in positions),
                max(p[2] for p in positions),
            ],
        }
    ]
    attributes = {"POSITION": 0}
    offset = pos_len
    if normals is not None:
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": normals_len}
        )
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            }
        )
        attributes["NORMAL"] = len(accessors) - 1
        offset += normals_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": weights_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(weights),
            "type": "VEC4",
        }
    )
    attributes["WEIGHTS_0"] = len(accessors) - 1
    offset += weights_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": joints_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5121,
            "count": len(weights),
            "type": "VEC4",
        }
    )
    attributes["JOINTS_0"] = len(accessors) - 1
    offset += joints_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": indices_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "Skinned",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"name": "SkinnedNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def _build_glb_with_animations(positions, indices, animation_names, normals=None):
    """Assemble a .glb with top-level ``animations`` entries (name-only;
    no channels — the report reads names, not sampler data)."""
    glb = _build_glb(positions, indices, normals)
    json_length = struct.unpack("<I", glb[12:16])[0]
    json_start = GLB_HEADER_SIZE_BYTES + GLB_CHUNK_HEADER_SIZE_BYTES
    gltf = json.loads(glb[json_start : json_start + json_length])
    gltf["animations"] = [{"name": name} for name in animation_names]
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    # BIN chunk is unchanged after the JSON chunk.
    bin_chunk = glb[json_start + json_length :]
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def test_animation_names_read_in_document_order(tmp_path):
    """Two clips: animation_names preserves the file's document order."""
    indices = (0, 1, 2, 1, 3, 2)
    path = _write_glb(
        tmp_path,
        _build_glb_with_animations(
            SHARED_EDGE_POSITIONS, indices, ["idle", "walk"], UP_NORMALS
        ),
    )
    report = asset_report(path)
    assert report.animation_names == ["idle", "walk"]


def test_weight_sum_violation_and_multi_influence_fraction(tmp_path):
    """Three skinned vertices, all riding two bones (so
    single_influence_vertex_fraction is 0.0); exactly one has weights
    summing to 0.9, outside the spec-derived per-vertex bound
    (2e-7 * 2 influences = 4e-7)."""
    positions = SHARED_EDGE_POSITIONS[:3]
    indices = (0, 1, 2)
    weights = (
        (0.5, 0.5, 0.0, 0.0),  # sum 1.0 — clean
        (0.45, 0.45, 0.0, 0.0),  # sum 0.9 — violation
        (0.3, 0.7, 0.0, 0.0),  # sum 1.0 — clean
    )
    path = _write_glb(
        tmp_path,
        _build_glb_with_weights(positions, indices, weights, UP_NORMALS[:3]),
    )
    mesh = asset_report(path).meshes["Skinned"]
    assert mesh.weight_sum_violation_count == 1
    assert mesh.single_influence_vertex_fraction == 0.0
    assert mesh.negative_weight_vertex_count == 0


def test_rigid_binding_single_influence(tmp_path):
    """Correctly bound rigid gear: every vertex rides exactly one bone
    with weight 1.0 — single_influence_vertex_fraction 1.0, zero
    violations.  Proves the violation counter distinguishes, not just
    fires."""
    positions = SHARED_EDGE_POSITIONS[:3]
    indices = (0, 1, 2)
    weights = ((1.0, 0.0, 0.0, 0.0),) * 3
    path = _write_glb(
        tmp_path,
        _build_glb_with_weights(positions, indices, weights, UP_NORMALS[:3]),
    )
    mesh = asset_report(path).meshes["Skinned"]
    assert mesh.single_influence_vertex_fraction == 1.0
    assert mesh.weight_sum_violation_count == 0
    assert mesh.negative_weight_vertex_count == 0


def test_format_glb_report_names_animation_count_change(tmp_path):
    """Candidate has 2 animations, baseline has 3: the rendered text
    must name the count change — the zip() blindness this step fixes."""
    indices = (0, 1, 2, 1, 3, 2)
    candidate = _write_glb(
        tmp_path,
        _build_glb_with_animations(
            SHARED_EDGE_POSITIONS, indices, ["idle", "walk"], UP_NORMALS
        ),
        name="candidate.glb",
    )
    baseline = _write_glb(
        tmp_path,
        _build_glb_with_animations(
            SHARED_EDGE_POSITIONS,
            indices,
            ["idle", "walk", "run"],
            UP_NORMALS,
        ),
        name="baseline.glb",
    )
    text = format_glb_report(asset_report(candidate), asset_report(baseline))
    assert "animation count changed: 3 -> 2" in text


def _build_glb_with_normalized_weights(
    positions, indices, raw_weight_bytes, joints=None, normals=None
):
    """Assemble a .glb with WEIGHTS_0 as componentType 5121 (UNSIGNED_BYTE)
    normalized=true VEC4, plus JOINTS_0 as UNSIGNED_BYTE VEC4.

    ``raw_weight_bytes`` is a sequence of 4-tuples of raw byte values
    (0-255); the accessor carries ``"normalized": true`` so read_accessor
    divides by 255.0.  This pins the de-normalization branch that no
    float32 weight fixture exercises.
    """
    binary = bytearray()
    binary.extend(_pack_components(positions))
    pos_len = len(_pack_components(positions))
    if normals is not None:
        binary.extend(_pack_components(normals))
    normals_len = len(_pack_components(normals)) if normals else 0
    weights_bytes = b"".join(struct.pack("<BBBB", *w) for w in raw_weight_bytes)
    binary.extend(weights_bytes)
    weights_len = len(weights_bytes)
    if joints is None:
        joints = [(0, 0, 0, 0)] * len(raw_weight_bytes)
    joints_bytes = b"".join(struct.pack("<BBBB", *j) for j in joints)
    binary.extend(joints_bytes)
    joints_len = len(joints_bytes)
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    indices_len = len(indices) * 4
    while len(binary) % 4:
        binary.append(0)

    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": pos_len},
    ]
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [
                min(p[0] for p in positions),
                min(p[1] for p in positions),
                min(p[2] for p in positions),
            ],
            "max": [
                max(p[0] for p in positions),
                max(p[1] for p in positions),
                max(p[2] for p in positions),
            ],
        }
    ]
    attributes = {"POSITION": 0}
    offset = pos_len
    if normals is not None:
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": normals_len}
        )
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            }
        )
        attributes["NORMAL"] = len(accessors) - 1
        offset += normals_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": weights_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5121,
            "normalized": True,
            "count": len(raw_weight_bytes),
            "type": "VEC4",
        }
    )
    attributes["WEIGHTS_0"] = len(accessors) - 1
    offset += weights_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": joints_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5121,
            "count": len(raw_weight_bytes),
            "type": "VEC4",
        }
    )
    attributes["JOINTS_0"] = len(accessors) - 1
    offset += joints_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": indices_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "Skinned",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"name": "SkinnedNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def _build_glb_with_two_weight_sets(
    positions, indices, weights_0, weights_1, normals=None
):
    """Assemble a .glb with WEIGHTS_0 + WEIGHTS_1 + JOINTS_0 + JOINTS_1,
    all float32 VEC4, to pin the multi-set weight_set_count path."""
    binary = bytearray()
    binary.extend(_pack_components(positions))
    pos_len = len(_pack_components(positions))
    if normals is not None:
        binary.extend(_pack_components(normals))
    normals_len = len(_pack_components(normals)) if normals else 0
    w0_bytes = b"".join(struct.pack("<ffff", *w) for w in weights_0)
    w1_bytes = b"".join(struct.pack("<ffff", *w) for w in weights_1)
    binary.extend(w0_bytes)
    w0_len = len(w0_bytes)
    binary.extend(w1_bytes)
    w1_len = len(w1_bytes)
    j0_bytes = b"".join(struct.pack("<BBBB", 0, 0, 0, 0) for _ in weights_0)
    j1_bytes = b"".join(struct.pack("<BBBB", 0, 0, 0, 0) for _ in weights_0)
    binary.extend(j0_bytes)
    j0_len = len(j0_bytes)
    binary.extend(j1_bytes)
    j1_len = len(j1_bytes)
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    indices_len = len(indices) * 4
    while len(binary) % 4:
        binary.append(0)

    buffer_views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": pos_len},
    ]
    accessors = [
        {
            "bufferView": 0,
            "byteOffset": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [
                min(p[0] for p in positions),
                min(p[1] for p in positions),
                min(p[2] for p in positions),
            ],
            "max": [
                max(p[0] for p in positions),
                max(p[1] for p in positions),
                max(p[2] for p in positions),
            ],
        }
    ]
    attributes = {"POSITION": 0}
    offset = pos_len
    if normals is not None:
        buffer_views.append(
            {"buffer": 0, "byteOffset": offset, "byteLength": normals_len}
        )
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normals),
                "type": "VEC3",
            }
        )
        attributes["NORMAL"] = len(accessors) - 1
        offset += normals_len
    for _w_bytes, _w_len, _label in (
        (w0_bytes, w0_len, "WEIGHTS_0"),
        (w1_bytes, w1_len, "WEIGHTS_1"),
    ):
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": _w_len})
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(weights_0),
                "type": "VEC4",
            }
        )
        attributes[_label] = len(accessors) - 1
        offset += _w_len
    for _j_bytes, _j_len, _label in (
        (j0_bytes, j0_len, "JOINTS_0"),
        (j1_bytes, j1_len, "JOINTS_1"),
    ):
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": _j_len})
        accessors.append(
            {
                "bufferView": len(buffer_views) - 1,
                "byteOffset": 0,
                "componentType": 5121,
                "count": len(weights_0),
                "type": "VEC4",
            }
        )
        attributes[_label] = len(accessors) - 1
        offset += _j_len
    buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": indices_len})
    accessors.append(
        {
            "bufferView": len(buffer_views) - 1,
            "byteOffset": 0,
            "componentType": 5125,
            "count": len(indices),
            "type": "SCALAR",
        }
    )
    indices_accessor = len(accessors) - 1

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [
            {
                "name": "Skinned",
                "primitives": [
                    {
                        "attributes": attributes,
                        "indices": indices_accessor,
                        "mode": 4,
                    }
                ],
            }
        ],
        "nodes": [{"name": "SkinnedNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def test_normalized_unorm8_weights_sum_255_zero_violations(tmp_path):
    """WEIGHTS_0 as componentType 5121 normalized=true with raw bytes
    (128, 127, 0, 0) — sum 255, the exact unorm8 requirement.  After
    de-normalization (128/255 + 127/255 = 1.0) the per-vertex bound is
    2e-7 * 2 = 4e-7, and 1.0 is well within it.  Pins the
    de-normalization branch of read_accessor: dropping or doubling the
    divisor, or applying it to the wrong componentType, reddens this
    test because the sum would no longer be 1.0."""
    positions = SHARED_EDGE_POSITIONS[:3]
    indices = (0, 1, 2)
    raw_weights = (
        (128, 127, 0, 0),
        (128, 127, 0, 0),
        (128, 127, 0, 0),
    )
    path = _write_glb(
        tmp_path,
        _build_glb_with_normalized_weights(
            positions, indices, raw_weights, normals=UP_NORMALS[:3]
        ),
    )
    mesh = asset_report(path).meshes["Skinned"]
    assert mesh.weight_sum_violation_count == 0
    assert mesh.negative_weight_vertex_count == 0
    # 128/255 ≈ 0.502, 127/255 ≈ 0.498 — two influences per vertex.
    assert mesh.single_influence_vertex_fraction == 0.0


def test_negative_weight_vertex_count(tmp_path):
    """One vertex has weights (1.5, -0.5, 0.0, 0.0): sum 1.0 so the
    weight-sum check passes, but the vertex carries a negative
    component.  glTF 2.0 §5.31 (Specification.adoc line 1890) says
    weights MUST NOT be negative.  Reddens if negative_weight_vertex_count
    is not populated (change the ``if any(w < 0.0 ...)`` guard to ``if
    False``)."""
    positions = SHARED_EDGE_POSITIONS[:3]
    indices = (0, 1, 2)
    weights = (
        (1.0, 0.0, 0.0, 0.0),
        (1.5, -0.5, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0),
    )
    path = _write_glb(
        tmp_path,
        _build_glb_with_weights(positions, indices, weights, UP_NORMALS[:3]),
    )
    mesh = asset_report(path).meshes["Skinned"]
    assert mesh.negative_weight_vertex_count == 1
    # The weight-sum check is blind to this: 1.5 + (-0.5) = 1.0.
    assert mesh.weight_sum_violation_count == 0
    # And single-influence is blind: only 1.5 is above the floor.
    assert mesh.single_influence_vertex_fraction == 1.0


def test_two_weight_sets_counted(tmp_path):
    """A primitive with WEIGHTS_0 + WEIGHTS_1 reports
    weight_set_count == 2.  Reddens if the count logic only checks
    WEIGHTS_0 (change ``startswith("WEIGHTS_")`` to
    ``startswith("WEIGHTS_0")``)."""
    positions = SHARED_EDGE_POSITIONS[:3]
    indices = (0, 1, 2)
    w0 = ((0.5, 0.5, 0.0, 0.0),) * 3
    w1 = ((0.0, 0.0, 0.0, 0.0),) * 3
    path = _write_glb(
        tmp_path,
        _build_glb_with_two_weight_sets(
            positions, indices, w0, w1, normals=UP_NORMALS[:3]
        ),
    )
    mesh = asset_report(path).meshes["Skinned"]
    assert mesh.weight_set_count == 2
    assert mesh.weight_sum_violation_count == 0


def test_format_glb_report_animation_reorder_mismatch(tmp_path):
    """Same-length animation lists in different order: the count check
    prints nothing, but the per-index mismatch line must name the swap.
    Reddens if the per-index loop is removed (delete the ``for i in
    range(min(...))`` block)."""
    indices = (0, 1, 2, 1, 3, 2)
    candidate = _write_glb(
        tmp_path,
        _build_glb_with_animations(
            SHARED_EDGE_POSITIONS, indices, ["walk", "idle"], UP_NORMALS
        ),
        name="candidate.glb",
    )
    baseline = _write_glb(
        tmp_path,
        _build_glb_with_animations(
            SHARED_EDGE_POSITIONS, indices, ["idle", "walk"], UP_NORMALS
        ),
        name="baseline.glb",
    )
    text = format_glb_report(asset_report(candidate), asset_report(baseline))
    assert "animation[0]" in text
    assert "'idle' -> 'walk'" in text
