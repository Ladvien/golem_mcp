"""Regression tests for the analyze_capture review slice (pure, no bpy)."""

import json
import struct

import pytest

from blended.analyze.mesh_checks import MeshBudget, MeshReport
from blended.export.glb_report import (
    GLB_CHUNK_TYPE_BIN,
    GLB_CHUNK_TYPE_JSON,
    GLB_MAGIC,
    parse_glb,
    read_accessor,
)

CHUNK_HEADER_FORMAT = "<II"
GLB_HEADER_FORMAT = "<III"
GLB_SUPPORTED_VERSION = 2
COMPONENT_TYPE_BYTE = 5120
COMPONENT_TYPE_SHORT = 5122
COMPONENT_TYPE_UNSIGNED_SHORT = 5123
NORMALIZED_TOLERANCE = 1.0e-9


def _clean_report(**overrides):
    fields = {
        "object_name": "Thing",
        "triangle_count": 12,
        "non_manifold_edge_count": 0,
        "boundary_edge_count": 0,
        "zero_area_face_count": 0,
        "non_finite_coordinate_count": 0,
        "connected_component_count": 1,
        "duplicate_vertex_pair_count": 0,
        "self_intersecting_face_pair_count": 0,
        "flipped_normal_triangle_count": 0,
    }
    fields.update(overrides)
    return MeshReport(**fields)


def _glb(json_payload: dict | None, chunks: list[tuple[int, bytes]], version=2):
    """Assemble a .glb from a JSON dict and (type, payload) chunks that
    follow it. Payloads must already be 4-byte aligned."""
    encoded = json.dumps(json_payload if json_payload is not None else {}).encode()
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    body = struct.pack(CHUNK_HEADER_FORMAT, len(encoded), GLB_CHUNK_TYPE_JSON) + encoded
    for chunk_type, payload in chunks:
        body += struct.pack(CHUNK_HEADER_FORMAT, len(payload), chunk_type) + payload
    header = struct.pack(GLB_HEADER_FORMAT, GLB_MAGIC, version, 12 + len(body))
    return header + body


def test_empty_mesh_does_not_pass_the_gate():
    """Measured in Blender 5.2: analyze_object on a mesh with no faces
    reported zero of everything and `failures()` returned [] — "nothing
    was built" passed the gate."""
    failures = _clean_report(triangle_count=0, connected_component_count=0).failures(
        MeshBudget()
    )
    assert any("no faces" in failure for failure in failures), failures


def test_a_nonempty_clean_mesh_still_passes():
    assert _clean_report().failures(MeshBudget()) == []


def test_signed_normalized_short_decodes_and_clamps():
    """glTF 2.0 normalized int16: c / 32767, with -32768 clamped to -1.0.
    The old decoder had no divisor for signed types and returned the raw
    integers."""
    raw_values = (32767, -32767, -32768, 0)
    binary = struct.pack("<4h", *raw_values)
    gltf = {
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(binary)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": COMPONENT_TYPE_SHORT,
                "normalized": True,
                "count": 4,
                "type": "SCALAR",
            }
        ],
    }
    decoded = [value[0] for value in read_accessor(gltf, binary, 0)]
    expected = [1.0, -1.0, -1.0, 0.0]
    assert decoded == pytest.approx(expected, abs=NORMALIZED_TOLERANCE)


def test_signed_normalized_byte_decodes():
    binary = struct.pack("<4b", 127, -127, -128, 0)
    gltf = {
        "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": COMPONENT_TYPE_BYTE,
                "normalized": True,
                "count": 4,
                "type": "SCALAR",
            }
        ],
    }
    decoded = [value[0] for value in read_accessor(gltf, binary, 0)]
    assert decoded == pytest.approx([1.0, -1.0, -1.0, 0.0], abs=NORMALIZED_TOLERANCE)


def test_unsigned_normalized_short_still_decodes():
    binary = struct.pack("<2H", 65535, 0)
    gltf = {
        "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": COMPONENT_TYPE_UNSIGNED_SHORT,
                "normalized": True,
                "count": 2,
                "type": "SCALAR",
            }
        ],
    }
    decoded = [value[0] for value in read_accessor(gltf, binary, 0)]
    assert decoded == pytest.approx([1.0, 0.0], abs=NORMALIZED_TOLERANCE)


def test_parse_glb_rejects_unsupported_container_version(tmp_path):
    path = tmp_path / "v1.glb"
    path.write_bytes(_glb({"asset": {"version": "2.0"}}, [], version=1))
    with pytest.raises(ValueError, match="container version 1"):
        parse_glb(path)


def test_parse_glb_rejects_a_first_chunk_that_is_not_json(tmp_path):
    payload = b"\x00\x00\x00\x00"
    body = struct.pack(CHUNK_HEADER_FORMAT, len(payload), GLB_CHUNK_TYPE_BIN) + payload
    header = struct.pack(
        GLB_HEADER_FORMAT, GLB_MAGIC, GLB_SUPPORTED_VERSION, 12 + len(body)
    )
    path = tmp_path / "bin_first.glb"
    path.write_bytes(header + body)
    with pytest.raises(ValueError, match="not JSON"):
        parse_glb(path)


def test_parse_glb_rejects_a_chunk_running_past_the_file(tmp_path):
    good = _glb(
        {"asset": {"version": "2.0"}}, [(GLB_CHUNK_TYPE_BIN, b"\x01\x02\x03\x04")]
    )
    # Inflate the BIN chunk's declared length without growing the file;
    # the container header length still matches, so only the chunk walk
    # can see the lie.
    bin_header_offset = len(good) - 4 - 8
    lying = bytearray(good)
    lying[bin_header_offset : bin_header_offset + 4] = struct.pack("<I", 4096)
    path = tmp_path / "lying_chunk.glb"
    path.write_bytes(bytes(lying))
    with pytest.raises(ValueError, match="runs past"):
        parse_glb(path)


def test_parse_glb_without_a_bin_chunk_returns_empty_binary(tmp_path):
    """A valid container with no BIN chunk used to die with a bare
    struct.error from reading a 4-byte length out of nothing."""
    path = tmp_path / "json_only.glb"
    path.write_bytes(_glb({"asset": {"version": "2.0"}}, []))
    gltf, binary = parse_glb(path)
    assert gltf["asset"]["version"] == "2.0"
    assert binary == b""


def test_parse_glb_skips_unknown_chunks_before_bin(tmp_path):
    unknown_chunk_type = 0x00574F4E
    payload = b"\xaa\xbb\xcc\xdd"
    path = tmp_path / "extra_chunk.glb"
    path.write_bytes(
        _glb(
            {"asset": {"version": "2.0"}},
            [(unknown_chunk_type, b"\x00" * 4), (GLB_CHUNK_TYPE_BIN, payload)],
        )
    )
    _gltf, binary = parse_glb(path)
    assert binary == payload
