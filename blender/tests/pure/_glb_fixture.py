"""Synthetic .glb bytes for the pure layer, shared by the GLB report and pack tests.

No committed fixture: _evaluate/golden/*.glb are deliberately untracked, so
tests assemble their own JSON chunk + BIN chunk.

The chunk layout mirrors Blender's exporter (io_scene_gltf2 export.py): the
JSON chunk's length field carries the PADDED length (length_gltf +=
spaces_gltf), not the raw JSON byte count.
"""

import json
import struct

from golem_blender.export.glb_report import GLB_HEADER_SIZE_BYTES, GLB_MAGIC


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


def _build_glb(positions, indices, normals=None, materials=()):
    """Assemble a minimal .glb: one mesh, one triangle primitive.

    `materials` names the glTF materials; the primitive uses the first.
    """
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

    primitive = {"attributes": attributes, "indices": indices_accessor, "mode": 4}
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
        "meshes": [{"name": "Tri", "primitives": [primitive]}],
        "nodes": [{"name": "TriNode", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if materials:
        primitive["material"] = 0
        gltf["materials"] = [{"name": name} for name in materials]
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    bin_chunk = _bin_chunk(bytes(binary))
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + bin_chunk


def _with_node(data, translation=None, rotation=None, scale=None, matrix=None):
    """The same .glb with node 0's transform rewritten.

    A `matrix` wins over TRS, exactly as glTF 2.0 requires. The JSON chunk's
    length field is regenerated because the padded length depends on the
    payload, and a hand-patched length is how a fixture stops parsing.
    """
    json_length = struct.unpack_from("<I", data, GLB_HEADER_SIZE_BYTES)[0]
    json_start = GLB_HEADER_SIZE_BYTES + 8
    gltf = json.loads(data[json_start : json_start + json_length])
    node = gltf["nodes"][0]
    for key in ("matrix", "translation", "rotation", "scale"):
        node.pop(key, None)
    if matrix is not None:
        node["matrix"] = list(matrix)
    else:
        if translation is not None:
            node["translation"] = list(translation)
        if rotation is not None:
            node["rotation"] = list(rotation)
        if scale is not None:
            node["scale"] = list(scale)
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    tail = data[json_start + json_length :]
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(tail)
    header = struct.pack("<III", GLB_MAGIC, 2, declared)
    return header + json_chunk + tail


def _write_glb(tmp_path, data, name="test.glb"):
    path = tmp_path / name
    path.write_bytes(data)
    return path
