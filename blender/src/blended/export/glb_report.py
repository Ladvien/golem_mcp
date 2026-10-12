"""Read a shipped ``.glb`` and report what is actually in it — without Blender.

Tier 1 (pure). This module imports ``json``, ``math``, ``struct`` and
``dataclasses`` and nothing else. No ``bpy``, no ``numpy``. That is the
point: the exported file is the artifact the game loads, and checking
it should not require launching Blender.

MEASURE THE FILE, NOT THE SCENE
-------------------------------
The exporter runs with ``export_apply=True``, which bakes modifiers, so
scene polygon counts describe geometry that never shipped. scp measured
a "5k" tier that shipped 9,488 triangles, and a scene report and a raw
bmesh disagreed 0 vs 6,196 boundary edges because one welded by
position and one counted UV seams. Every count here is read out of the
file's own bytes.

TWO MEASUREMENT DECISIONS, BOTH PAID FOR
----------------------------------------
1. **Edges are counted after welding vertices by POSITION.** glTF
   splits a vertex wherever its normal or UV differs, so the raw index
   buffer reports seams as holes. Welded answers "does this surface
   have a hole", which is the question `blended`'s drift catalog asks
   ("judge shipped GLBs on POSITION-WELDED topology").
2. **An inverted facet is a face that disagrees with ITSELF** —
   ``dot(face_normal_from_winding, mean(stored_corner_normals)) < 0``.
   Not edge contiguity: contiguity asks whether two adjacent faces
   agree, so an island wound inside-out passes it.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

# glTF 2.0 binary container layout (little-endian, 12-byte header then chunks).
GLB_MAGIC = 0x46546C67  # 'glTF'
GLB_VERSION = 2
GLB_HEADER_SIZE_BYTES = 12
GLB_CHUNK_HEADER_SIZE_BYTES = 8
GLB_CHUNK_TYPE_JSON = 0x4E4F534A  # 'JSON'
GLB_CHUNK_TYPE_BIN = 0x004E4942  # 'BIN\0'

# Round positions to this many decimals before welding. 1e-6 m = 1
# micron: far below any prop feature, far above float32 round-trip
# noise.
POSITION_WELD_DECIMALS = 6
# glTF core primitives are triangles in every file this harness ships.
GLTF_MODE_TRIANGLES = 4
# Per-influence tolerance for the weight-sum check.  glTF 2.0 §5.31
# Skinned Mesh Attributes (Specification.adoc line ~1902, Implementation
# Note): "The threshold in the official validation tool is set to 2e-7
# times the number of non-zero weights per vertex."  For unorm8/unorm16
# the pre-normalization sum MUST be exactly 255 or 65535 (line 1897), so
# the old 1e-3 tolerance was 5000x too loose and hid real violations.
# The per-vertex bound is WEIGHT_SUM_TOLERANCE_PER_INFLUENCE * max(1,
# non_zero_influences).
WEIGHT_SUM_TOLERANCE_PER_INFLUENCE = 2.0e-7
# An influence is a weight strictly above this floor.  Derived from the
# same spec threshold as the weight-sum tolerance (one source of truth):
# 2e-7 is far below the smallest legitimate quantized weight in either
# format — unorm8 step 1/255 ≈ 3.9e-3, unorm16 step 1/65535 ≈ 1.5e-5 —
# and a raw byte of 0 dequantizes to exactly 0.0 (no quantization dust
# exists to suppress).  1e-4, the old value, was ABOVE 1/65535 and so
# discarded real influences.
WEIGHT_INFLUENCE_FLOOR = WEIGHT_SUM_TOLERANCE_PER_INFLUENCE

_COMPONENT_FORMATS = {
    5120: ("b", 1),  # BYTE
    5121: ("B", 1),  # UNSIGNED_BYTE
    5122: ("h", 2),  # SHORT
    5123: ("H", 2),  # UNSIGNED_SHORT
    5125: ("I", 4),  # UNSIGNED_INT
    5126: ("f", 4),  # FLOAT
}
_COMPONENT_MAXIMA = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
_TYPE_COMPONENT_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


@dataclass(frozen=True)
class GlbMeshReport:
    """Per-mesh geometry facts, all read out of the file."""

    name: str
    triangle_count: int
    welded_boundary_edge_count: int
    non_manifold_edge_count: int
    inverted_facet_count: int
    has_normals: bool
    has_tangents: bool
    # Count of TEXCOORD_* attributes. `blended` gates UVs, so the file
    # must report them: an unwrapped scene that ships without its UV
    # layer is exactly the export-time drift this module exists to see.
    uv_set_count: int
    # max number of WEIGHTS_* attribute sets on any primitive. glTF
    # 2.0 §5.31 (Specification.adoc line 1911) makes multiple sets
    # conformant: vertices influenced by more than four joints store the
    # extra data in JOINTS_1/WEIGHTS_1, and the count of JOINTS_n sets
    # MUST equal the count of WEIGHTS_n sets. But §5.31 (line 1913) also
    # says clients MAY support only a single set, so >1 is a
    # runtime-portability risk, not a validity error.
    weight_set_count: int = 0
    # skinned vertices whose weight sum falls outside the spec-derived
    # per-vertex bound: WEIGHT_SUM_TOLERANCE_PER_INFLUENCE * max(1,
    # non_zero_influences).  See the constant for the spec citation.
    weight_sum_violation_count: int = 0
    # vertices with any negative weight component.  glTF 2.0 §5.31
    # (Specification.adoc line 1890): "The joint weights for each vertex
    # MUST NOT be negative."  A negative weight explodes under
    # linear-blend skinning; this count must be zero.
    negative_weight_vertex_count: int = 0
    # fraction of skinned vertices riding exactly one bone. 1.0 on
    # correctly bound rigid gear; less means barycentric weights leaked
    # into something that must move as one piece.  0.0 is ambiguous:
    # it means "nothing is skinned" (every prop this harness ships)
    # AND "worst possible multi-bone skinning".  Only meaningful when
    # weight_set_count is non-zero.
    single_influence_vertex_fraction: float = 0.0


@dataclass(frozen=True)
class GlbAssetReport:
    """Everything a rig-less prop contract asks about a shipped file."""

    path: str
    size_bytes: int
    mesh_names: list
    meshes: dict = field(default_factory=dict)  # name -> GlbMeshReport
    material_count: int = 0
    image_count: int = 0
    root_node_names: list = field(default_factory=list)
    node_names: list = field(default_factory=list)
    # From the POSITION accessors' min/max, which glTF requires.
    minimum_corner_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    maximum_corner_m: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Animation clip names in document order, because a runtime that
    # loads clips by index can have every name match while the indices
    # shuffle.
    animation_names: list = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(m.triangle_count for m in self.meshes.values())

    @property
    def welded_boundary_edge_count(self) -> int:
        return sum(m.welded_boundary_edge_count for m in self.meshes.values())

    @property
    def non_manifold_edge_count(self) -> int:
        return sum(m.non_manifold_edge_count for m in self.meshes.values())

    @property
    def inverted_facet_count(self) -> int:
        return sum(m.inverted_facet_count for m in self.meshes.values())

    @property
    def dimensions_m(self) -> tuple[float, float, float]:
        """glTF-space extents, max - min."""
        return (
            self.maximum_corner_m[0] - self.minimum_corner_m[0],
            self.maximum_corner_m[1] - self.minimum_corner_m[1],
            self.maximum_corner_m[2] - self.minimum_corner_m[2],
        )


def parse_glb(path: Path) -> tuple[dict, bytes]:
    """Split a ``.glb`` into ``(gltf_json_dict, binary_chunk_bytes)``.

    Fails loudly on anything unexpected rather than returning a
    half-parsed file — a silently misread accessor becomes a confident
    wrong number, which is the failure mode this whole module exists to
    stop.
    """
    data = Path(path).read_bytes()
    if len(data) < GLB_HEADER_SIZE_BYTES:
        raise ValueError(f"parse_glb({path!r}): file is too short to be a .glb")
    magic, version, declared_length = struct.unpack(
        "<III", data[:GLB_HEADER_SIZE_BYTES]
    )
    if magic != GLB_MAGIC:
        raise ValueError(f"parse_glb({path!r}): not a .glb — bad magic {magic:#x}")
    if version != GLB_VERSION:
        raise ValueError(
            f"parse_glb({path!r}): container version {version}, "
            f"only {GLB_VERSION} is read here"
        )
    if declared_length != len(data):
        raise ValueError(
            f"parse_glb({path!r}): header declares {declared_length} bytes, "
            f"file is {len(data)}"
        )

    json_start = GLB_HEADER_SIZE_BYTES + GLB_CHUNK_HEADER_SIZE_BYTES
    if len(data) < json_start:
        raise ValueError(f"parse_glb({path!r}): no JSON chunk header")
    json_length, json_chunk_type = struct.unpack_from(
        "<II", data, GLB_HEADER_SIZE_BYTES
    )
    if json_chunk_type != GLB_CHUNK_TYPE_JSON:
        raise ValueError(
            f"parse_glb({path!r}): first chunk type {json_chunk_type:#x} is not JSON"
        )
    json_end = json_start + json_length
    if json_end > len(data):
        raise ValueError(
            f"parse_glb({path!r}): JSON chunk of {json_length} bytes runs past "
            f"the end of the file"
        )
    gltf = json.loads(data[json_start:json_end])

    # glTF 2.0 §4.4.3: later chunks are optional and unknown types must
    # be skipped; the BIN chunk is the one that carries accessor bytes.
    binary = b""
    chunk_cursor = json_end
    while chunk_cursor < len(data):
        if chunk_cursor + GLB_CHUNK_HEADER_SIZE_BYTES > len(data):
            raise ValueError(f"parse_glb({path!r}): truncated chunk header")
        chunk_length, chunk_type = struct.unpack_from("<II", data, chunk_cursor)
        chunk_start = chunk_cursor + GLB_CHUNK_HEADER_SIZE_BYTES
        chunk_end = chunk_start + chunk_length
        if chunk_end > len(data):
            raise ValueError(
                f"parse_glb({path!r}): chunk of {chunk_length} bytes runs past "
                f"the end of the file"
            )
        if chunk_type == GLB_CHUNK_TYPE_BIN:
            binary = data[chunk_start:chunk_end]
            break
        chunk_cursor = chunk_end
    return gltf, binary


def read_accessor(gltf: dict, binary: bytes, index: int) -> list[tuple[float, ...]]:
    """Decode accessor ``index`` into a list of component tuples,
    honouring byteStride and the ``normalized`` flag."""
    accessor = gltf["accessors"][index]
    if "sparse" in accessor:
        raise NotImplementedError(
            f"read_accessor({index}): sparse accessors are not decoded here. "
            f"Blender's exporter does not emit them, so encountering one means "
            f"the file came from elsewhere and every count below would be wrong."
        )
    if "bufferView" not in accessor:
        raise ValueError(
            f"read_accessor({index}): no bufferView (implicit-zero accessor)"
        )

    buffer_view = gltf["bufferViews"][accessor["bufferView"]]
    component_format, component_size = _COMPONENT_FORMATS[accessor["componentType"]]
    component_count = _TYPE_COMPONENT_COUNTS[accessor["type"]]
    start = buffer_view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = buffer_view.get("byteStride") or component_size * component_count
    layout = "<" + component_format * component_count
    divisor = (
        _COMPONENT_MAXIMA.get(accessor["componentType"])
        if accessor.get("normalized")
        else None
    )

    values = []
    for element in range(accessor["count"]):
        raw = struct.unpack_from(layout, binary, start + element * stride)
        # glTF 2.0 §3.11: signed normalized c/MAX clamps at -1.0 (the
        # most negative integer is one step beyond -1.0); unsigned
        # values are never negative so the clamp is inert for them.
        values.append(tuple(max(v / divisor, -1.0) for v in raw) if divisor else raw)
    return values


def _weld(positions: list) -> list:
    """Map each vertex index to a POSITION-welded index. See the module
    docstring — this is what makes a boundary-edge count mean "hole in
    the surface" rather than "UV seam"."""
    welded: dict[tuple[float, ...], int] = {}
    remap: list[int] = []
    for position in positions:
        key = tuple(round(component, POSITION_WELD_DECIMALS) for component in position)
        remap.append(welded.setdefault(key, len(welded)))
    return remap


def mesh_reports(gltf: dict, binary: bytes) -> dict[str, GlbMeshReport]:
    """``{mesh_name: GlbMeshReport}`` for every mesh in the file."""
    reports: dict[str, GlbMeshReport] = {}
    for mesh in gltf.get("meshes", []):
        triangles = inverted = boundary = nonmanifold = 0
        has_normals = has_tangents = False
        uv_set_count = 0
        weight_set_count = 0
        skinned_vertex_count = 0
        weight_sum_violation_count = 0
        negative_weight_vertex_count = 0
        single_influence_vertex_count = 0
        edge_uses: dict = {}

        for primitive in mesh["primitives"]:
            attributes = primitive["attributes"]
            mode = primitive.get("mode", GLTF_MODE_TRIANGLES)
            if mode != GLTF_MODE_TRIANGLES:
                raise ValueError(
                    f"mesh {mesh.get('name', '<unnamed>')!r}: primitive mode "
                    f"{mode} is not triangles ({GLTF_MODE_TRIANGLES})"
                )
            has_tangents = has_tangents or "TANGENT" in attributes
            positions = read_accessor(gltf, binary, attributes["POSITION"])
            normals = (
                read_accessor(gltf, binary, attributes["NORMAL"])
                if "NORMAL" in attributes
                else None
            )
            has_normals = has_normals or normals is not None
            uv_set_count = max(
                uv_set_count,
                sum(1 for key in attributes if key.startswith("TEXCOORD_")),
            )

            weight_keys = sorted(
                key for key in attributes if key.startswith("WEIGHTS_")
            )
            weight_set_count = max(weight_set_count, len(weight_keys))
            if weight_keys:
                weights_all = [
                    read_accessor(gltf, binary, attributes[key]) for key in weight_keys
                ]
                vertex_count = len(weights_all[0])
                for vertex_index in range(vertex_count):
                    vertex_weights: list[float] = []
                    for weight_set in weights_all:
                        vertex_weights.extend(weight_set[vertex_index])
                    if any(w < 0.0 for w in vertex_weights):
                        negative_weight_vertex_count += 1
                    weight_sum = sum(vertex_weights)
                    non_zero_influences = sum(
                        1 for w in vertex_weights if w > WEIGHT_INFLUENCE_FLOOR
                    )
                    per_vertex_tolerance = WEIGHT_SUM_TOLERANCE_PER_INFLUENCE * max(
                        1, non_zero_influences
                    )
                    if not math.isclose(
                        weight_sum,
                        1.0,
                        rel_tol=0.0,
                        abs_tol=per_vertex_tolerance,
                    ):
                        weight_sum_violation_count += 1
                    if non_zero_influences == 1:
                        single_influence_vertex_count += 1
                    skinned_vertex_count += 1

            indices = [
                int(i[0]) for i in read_accessor(gltf, binary, primitive["indices"])
            ]
            remap = _weld(positions)
            for corner in range(0, len(indices), 3):
                corner_indices = indices[corner : corner + 3]
                triangles += 1
                for first, second in ((0, 1), (1, 2), (2, 0)):
                    edge = tuple(
                        sorted(
                            (
                                remap[corner_indices[first]],
                                remap[corner_indices[second]],
                            )
                        )
                    )
                    edge_uses[edge] = edge_uses.get(edge, 0) + 1
                if normals is not None and _face_disagrees_with_itself(
                    positions, normals, corner_indices
                ):
                    inverted += 1

        boundary = sum(1 for uses in edge_uses.values() if uses == 1)
        nonmanifold = sum(1 for uses in edge_uses.values() if uses > 2)
        single_influence_fraction = (
            single_influence_vertex_count / skinned_vertex_count
            if skinned_vertex_count > 0
            else 0.0
        )
        name = mesh.get("name", "<unnamed>")
        reports[name] = GlbMeshReport(
            name=name,
            triangle_count=triangles,
            welded_boundary_edge_count=boundary,
            non_manifold_edge_count=nonmanifold,
            inverted_facet_count=inverted,
            has_normals=has_normals,
            has_tangents=has_tangents,
            uv_set_count=uv_set_count,
            weight_set_count=weight_set_count,
            weight_sum_violation_count=weight_sum_violation_count,
            negative_weight_vertex_count=negative_weight_vertex_count,
            single_influence_vertex_fraction=single_influence_fraction,
        )
    return reports


def _face_disagrees_with_itself(positions, normals, corner_indices) -> bool:
    a, b, c = (positions[i] for i in corner_indices)
    edge_1 = [b[i] - a[i] for i in range(3)]
    edge_2 = [c[i] - a[i] for i in range(3)]
    winding_normal = (
        edge_1[1] * edge_2[2] - edge_1[2] * edge_2[1],
        edge_1[2] * edge_2[0] - edge_1[0] * edge_2[2],
        edge_1[0] * edge_2[1] - edge_1[1] * edge_2[0],
    )
    stored_normal = [
        sum(normals[i][axis] for i in corner_indices) / 3.0 for axis in range(3)
    ]
    return sum(winding_normal[axis] * stored_normal[axis] for axis in range(3)) < 0.0


def asset_report(path: Path) -> GlbAssetReport:
    """Everything the prop pipeline asks about a shipped file, read out
    of ``path``."""
    gltf, binary = parse_glb(path)
    nodes = gltf.get("nodes", [])
    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]

    minimum_corner = (math.inf, math.inf, math.inf)
    maximum_corner = (-math.inf, -math.inf, -math.inf)
    for mesh in gltf.get("meshes", []):
        for primitive in mesh["primitives"]:
            position_accessor = gltf["accessors"][primitive["attributes"]["POSITION"]]
            minimum = position_accessor.get("min")
            maximum = position_accessor.get("max")
            if minimum is None or maximum is None:
                raise ValueError(
                    f"mesh {mesh.get('name', '<unnamed>')!r}: POSITION accessor "
                    f"has no min/max — glTF requires them"
                )
            minimum_corner = tuple(
                min(existing, value) for existing, value in zip(minimum_corner, minimum)
            )
            maximum_corner = tuple(
                max(existing, value) for existing, value in zip(maximum_corner, maximum)
            )

    return GlbAssetReport(
        path=str(path),
        size_bytes=Path(path).stat().st_size,
        mesh_names=[mesh.get("name", "") for mesh in gltf.get("meshes", [])],
        meshes=mesh_reports(gltf, binary),
        material_count=len(gltf.get("materials", [])),
        image_count=len(gltf.get("images", [])),
        root_node_names=[nodes[i].get("name", "") for i in scene.get("nodes", [])],
        node_names=[node.get("name", "") for node in nodes],
        minimum_corner_m=minimum_corner,
        maximum_corner_m=maximum_corner,
        animation_names=[anim.get("name", "") for anim in gltf.get("animations", [])],
    )


def format_glb_report(
    report: GlbAssetReport, baseline: GlbAssetReport | None = None
) -> str:
    """Human-readable report; with ``baseline``, only the meshes that
    CHANGED are listed, plus explicit added/removed mesh lines."""
    lines = [
        f"{report.path}",
        f"  bytes ................. {report.size_bytes:,}",
        f"  triangles ............. {report.triangle_count:,}",
        (
            f"  boundary edges ........ {report.welded_boundary_edge_count}  "
            f"(welded by position)"
        ),
        f"  non-manifold edges .... {report.non_manifold_edge_count}",
        f"  inverted facets ....... {report.inverted_facet_count}",
        f"  materials / images .... {report.material_count} / {report.image_count}",
        f"  root node(s) .......... {report.root_node_names}",
        (
            f"  extents (m) ........... "
            f"{', '.join(f'{value:.4f}' for value in report.dimensions_m)}"
        ),
        (
            f"  animations ............ {len(report.animation_names)} "
            f"{report.animation_names}"
        ),
        (
            f"  skin: sets/violations/neg .. "
            f"{max((m.weight_set_count for m in report.meshes.values()), default=0)}/"
            f"{sum(m.weight_sum_violation_count for m in report.meshes.values())}/"
            f"{sum(m.negative_weight_vertex_count for m in report.meshes.values())}"
        ),
    ]
    if baseline is not None:
        removed = sorted(set(baseline.mesh_names) - set(report.mesh_names))
        added = sorted(set(report.mesh_names) - set(baseline.mesh_names))
        lines += [
            "",
            f"  vs baseline {baseline.path}:",
            f"    meshes removed: {removed or 'none'}",
            f"    meshes added:   {added or 'none'}",
        ]
        # Report the count change BEFORE any per-item comparison: a
        # bare zip() over two name lists compares only the shorter one
        # and calls an 8-clip file identical to a 20-clip baseline.
        if len(baseline.animation_names) != len(report.animation_names):
            lines.append(
                f"    animation count changed: "
                f"{len(baseline.animation_names)} -> {len(report.animation_names)}"
            )
        # Per-index mismatch over the overlapping range: same-length
        # reordered clips print nothing from the count check above, but
        # a runtime loading by index sees them in different order.
        for i in range(min(len(baseline.animation_names), len(report.animation_names))):
            if baseline.animation_names[i] != report.animation_names[i]:
                lines.append(
                    f"    animation[{i}]: "
                    f"{baseline.animation_names[i]!r} -> {report.animation_names[i]!r}"
                )

    lines += [
        "",
        (
            "  per mesh (tris / boundary / non-manifold / inverted / UV sets / "
            "weight-sets / sum-viol / neg-wt / 1-infl):"
        ),
    ]
    for name in sorted(report.meshes):
        mesh = report.meshes[name]
        if baseline is not None:
            was = baseline.meshes.get(name)
            if was is not None and (
                was.triangle_count,
                was.welded_boundary_edge_count,
                was.non_manifold_edge_count,
                was.inverted_facet_count,
                was.weight_set_count,
                was.weight_sum_violation_count,
                was.negative_weight_vertex_count,
                was.single_influence_vertex_fraction,
            ) == (
                mesh.triangle_count,
                mesh.welded_boundary_edge_count,
                mesh.non_manifold_edge_count,
                mesh.inverted_facet_count,
                mesh.weight_set_count,
                mesh.weight_sum_violation_count,
                mesh.negative_weight_vertex_count,
                mesh.single_influence_vertex_fraction,
            ):
                continue
        lines.append(
            f"    {name:28s} {mesh.triangle_count:6d} "
            f"{mesh.welded_boundary_edge_count:6d} {mesh.non_manifold_edge_count:5d} "
            f"{mesh.inverted_facet_count:5d}  {mesh.uv_set_count}  "
            f"{mesh.weight_set_count} {mesh.weight_sum_violation_count} "
            f"{mesh.negative_weight_vertex_count} "
            f"{mesh.single_influence_vertex_fraction:.2f}"
        )
    return "\n".join(lines)
