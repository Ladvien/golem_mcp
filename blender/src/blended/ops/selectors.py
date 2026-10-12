"""Typed selections of geometry (OT-14).

An op that acts on a SUBSET of a mesh takes a selector, never indices:
a model can reason about "the edges whose faces meet at 90 degrees",
"the top face", "the vertices in the group named top_*"; it cannot
reason about vertex 37. Each selector is a frozen dataclass whose
`kind` is a closed enum, so it round-trips through the schema
generator as an object with an enum and binds back from JSON.

The interpretation of each kind, stated once:

- EdgeSelector `dihedral_angle`: edges whose two faces meet at or above
  `minimum_dihedral_angle_deg` (a boundary edge has no angle: excluded).
- EdgeSelector / FaceSelector `material_slot`: edges (faces) of faces
  whose material slot index is `material_slot_index`.
- Any selector `vertex_group`: elements whose EVERY vertex belongs to a
  vertex group whose name matches `vertex_group_pattern` (a regex,
  full-match). "By name pattern" in the backlog means this.
- FaceSelector `axis_normal`: faces whose normal is within
  `normal_tolerance_deg` of the named world axis.
- VertexSelector `height_range`: vertices with z in [z_min_m, z_max_m]
  (object-local).
- `all`: every element.

Resolution (`select_*`) reads the mesh through bmesh and returns
sorted indices; bpy only inside those functions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from blended.ops._contract import op

EDGE_SELECTOR_KINDS = ("dihedral_angle", "material_slot", "vertex_group", "all")
FACE_SELECTOR_KINDS = ("axis_normal", "material_slot", "vertex_group", "all")
VERTEX_SELECTOR_KINDS = ("vertex_group", "height_range", "all")
AXES = ("+x", "-x", "+y", "-y", "+z", "-z")
AXIS_VECTORS = {
    "+x": (1.0, 0.0, 0.0),
    "-x": (-1.0, 0.0, 0.0),
    "+y": (0.0, 1.0, 0.0),
    "-y": (0.0, -1.0, 0.0),
    "+z": (0.0, 0.0, 1.0),
    "-z": (0.0, 0.0, -1.0),
}
DEFAULT_MINIMUM_DIHEDRAL_ANGLE_DEG = 30.0
DEFAULT_NORMAL_TOLERANCE_DEG = 5.0
MAXIMUM_DIHEDRAL_ANGLE_DEG = 180.0


class InvalidSelector(ValueError):
    """A selector whose fields do not make sense for its kind."""


def _require_pattern(kind: str, pattern: str) -> None:
    if kind == "vertex_group":
        if not pattern:
            raise InvalidSelector(
                "kind 'vertex_group' needs a non-empty vertex_group_pattern"
            )
        try:
            re.compile(pattern)
        except re.error as error:
            raise InvalidSelector(
                f"vertex_group_pattern {pattern!r} is not a regex: {error}"
            ) from error


@dataclass(frozen=True)
class EdgeSelector:
    """Which edges of a mesh an op acts on."""

    kind: Literal["dihedral_angle", "material_slot", "vertex_group", "all"]
    minimum_dihedral_angle_deg: float = DEFAULT_MINIMUM_DIHEDRAL_ANGLE_DEG
    material_slot_index: int = 0
    vertex_group_pattern: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EDGE_SELECTOR_KINDS:
            raise InvalidSelector(
                f"edge selector kind {self.kind!r} not in {EDGE_SELECTOR_KINDS}"
            )
        if not 0.0 < self.minimum_dihedral_angle_deg <= MAXIMUM_DIHEDRAL_ANGLE_DEG:
            raise InvalidSelector(
                f"minimum_dihedral_angle_deg must be in (0, {MAXIMUM_DIHEDRAL_ANGLE_DEG}], "
                f"got {self.minimum_dihedral_angle_deg}"
            )
        if self.material_slot_index < 0:
            raise InvalidSelector(
                f"material_slot_index must be >= 0, got {self.material_slot_index}"
            )
        _require_pattern(self.kind, self.vertex_group_pattern)


@dataclass(frozen=True)
class FaceSelector:
    """Which faces of a mesh an op acts on."""

    kind: Literal["axis_normal", "material_slot", "vertex_group", "all"]
    axis: Literal["+x", "-x", "+y", "-y", "+z", "-z"] = "+z"
    normal_tolerance_deg: float = DEFAULT_NORMAL_TOLERANCE_DEG
    material_slot_index: int = 0
    vertex_group_pattern: str = ""

    def __post_init__(self) -> None:
        if self.kind not in FACE_SELECTOR_KINDS:
            raise InvalidSelector(
                f"face selector kind {self.kind!r} not in {FACE_SELECTOR_KINDS}"
            )
        if self.axis not in AXES:
            raise InvalidSelector(f"axis {self.axis!r} not in {AXES}")
        if not 0.0 < self.normal_tolerance_deg < 90.0:
            raise InvalidSelector(
                f"normal_tolerance_deg must be in (0, 90), got {self.normal_tolerance_deg}"
            )
        if self.material_slot_index < 0:
            raise InvalidSelector(
                f"material_slot_index must be >= 0, got {self.material_slot_index}"
            )
        _require_pattern(self.kind, self.vertex_group_pattern)


@dataclass(frozen=True)
class VertexSelector:
    """Which vertices of a mesh an op acts on."""

    kind: Literal["vertex_group", "height_range", "all"]
    vertex_group_pattern: str = ""
    z_min_m: float = 0.0
    z_max_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in VERTEX_SELECTOR_KINDS:
            raise InvalidSelector(
                f"vertex selector kind {self.kind!r} not in {VERTEX_SELECTOR_KINDS}"
            )
        if self.kind == "height_range" and self.z_max_m < self.z_min_m:
            raise InvalidSelector(
                f"height_range needs z_min_m <= z_max_m, got {self.z_min_m} > {self.z_max_m}"
            )
        _require_pattern(self.kind, self.vertex_group_pattern)


# --- resolution ----------------------------------------------------------------


def _group_vertex_indices(mesh_object, pattern: str) -> set[int]:
    """Indices of vertices in any vertex group whose name full-matches `pattern`."""
    matcher = re.compile(pattern)
    group_indices = {
        group.index
        for group in mesh_object.vertex_groups
        if matcher.fullmatch(group.name)
    }
    return {
        vertex.index
        for vertex in mesh_object.data.vertices
        if any(element.group in group_indices for element in vertex.groups)
    }


@op(reads_only=True)
def select_vertices(object_name: str, selector: VertexSelector) -> tuple[int, ...]:
    """Resolve a VertexSelector on the named mesh to sorted vertex indices."""
    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    vertices = mesh_object.data.vertices
    if selector.kind == "all":
        return tuple(range(len(vertices)))
    if selector.kind == "vertex_group":
        return tuple(
            sorted(_group_vertex_indices(mesh_object, selector.vertex_group_pattern))
        )
    return tuple(
        vertex.index
        for vertex in vertices
        if selector.z_min_m <= vertex.co.z <= selector.z_max_m
    )


@op(reads_only=True)
def select_faces(object_name: str, selector: FaceSelector) -> tuple[int, ...]:
    """Resolve a FaceSelector on the named mesh to sorted face indices."""
    import bpy

    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    polygons = mesh_object.data.polygons
    if selector.kind == "all":
        return tuple(range(len(polygons)))
    if selector.kind == "material_slot":
        return tuple(
            p.index
            for p in polygons
            if p.material_index == selector.material_slot_index
        )
    if selector.kind == "vertex_group":
        members = _group_vertex_indices(mesh_object, selector.vertex_group_pattern)
        return tuple(p.index for p in polygons if all(v in members for v in p.vertices))
    axis = AXIS_VECTORS[selector.axis]
    threshold = math.cos(math.radians(selector.normal_tolerance_deg))
    # matrix_world is lazy (see blended.ops.transforms); read it fresh.
    bpy.context.view_layer.update()
    # Normals transform by the inverse-transpose: with a non-uniform scale
    # the plain 3x3 skews them (measured: a 45-degree face under z-scale 10
    # read as a +z face). Equal to the rotation for rigid transforms.
    normal_matrix = mesh_object.matrix_world.to_3x3().inverted_safe().transposed()
    selected = []
    for polygon in polygons:
        world_normal = (normal_matrix @ polygon.normal).normalized()
        if world_normal.dot(axis) >= threshold:
            selected.append(polygon.index)
    return tuple(selected)


@op(reads_only=True)
def select_edges(object_name: str, selector: EdgeSelector) -> tuple[int, ...]:
    """Resolve an EdgeSelector on the named mesh to sorted edge indices."""
    import bmesh

    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    mesh = mesh_object.data
    if selector.kind == "all":
        return tuple(range(len(mesh.edges)))
    if selector.kind == "vertex_group":
        members = _group_vertex_indices(mesh_object, selector.vertex_group_pattern)
        return tuple(
            e.index for e in mesh.edges if all(v in members for v in e.vertices)
        )
    if selector.kind == "material_slot":
        edge_keys = {
            key
            for polygon in mesh.polygons
            if polygon.material_index == selector.material_slot_index
            for key in polygon.edge_keys
        }
        return tuple(
            e.index for e in mesh.edges if tuple(sorted(e.vertices)) in edge_keys
        )
    working = bmesh.new()
    try:
        working.from_mesh(mesh)
        working.edges.ensure_lookup_table()
        working.normal_update()
        minimum = math.radians(selector.minimum_dihedral_angle_deg)
        selected = [
            edge.index
            for edge in working.edges
            if len(edge.link_faces) == 2
            and edge.calc_face_angle(None) is not None
            and edge.calc_face_angle(None) >= minimum
        ]
    finally:
        working.free()
    return tuple(selected)
