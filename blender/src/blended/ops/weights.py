"""Vertex-group weight assignment operations.

Why this op exists: weight-painting through `bpy.ops` requires a
viewport and paint-mode context, which a headless chat agent does not
have.  These ops assign weights through the data API
(``vertex_group.add``) so the agent can rig a character procedurally
without ever entering Weight Paint mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from blended.ops._contract import op
from blended.ops.selectors import VertexSelector

# The default selection: every vertex. A frozen instance is safe to share.
ALL_VERTICES = VertexSelector(kind="all")

MINIMUM_WEIGHT = 0.0
MAXIMUM_WEIGHT = 1.0


@dataclass(frozen=True)
class WeightReport:
    """Frozen snapshot of a mesh's vertex-group weight state."""

    group_names: tuple[str, ...]
    nonzero_weight_counts: dict[str, int]
    unweighted_vertex_count: int
    # Weight painting's own silent failure: a vertex group whose name
    # matches NO bone of the armature that deforms this mesh drives
    # nothing at all. The weights are real, the count is non-zero, and
    # the mesh does not move — so a report of "8 vertices weighted" is
    # a lie by omission. One typo in a group name produces it.
    groups_without_bones: tuple[str, ...] = ()
    # The mirror image: bones that no group names, i.e. parts of the rig
    # that can never deform anything. Diagnostic, not necessarily wrong
    # (a root or control bone is legitimately unweighted).
    bones_without_groups: tuple[str, ...] = ()


def assign_vertex_group_weights(
    object_name: str,
    group_name: str,
    weight: float,
    vertices: VertexSelector = ALL_VERTICES,
) -> str:
    """Create or reuse a vertex group on the named mesh and assign ``weight`` to the selected vertices.

    ``vertices`` is a VertexSelector (OT-14): by vertex-group name
    pattern, by height range, or all.  Weight must be in [0, 1].  Uses
    ``group.add(indices, weight, 'REPLACE')`` — the data API equivalent
    of painting, no mode switch required.  Returns the vertex group's
    name.
    """
    from blended.ops._objects import object_by_name
    from blended.ops.selectors import select_vertices

    mesh_object = object_by_name(object_name, "MESH")
    if weight < MINIMUM_WEIGHT or weight > MAXIMUM_WEIGHT:
        raise ValueError(
            f"weight {weight} out of range [{MINIMUM_WEIGHT}, {MAXIMUM_WEIGHT}]"
        )

    group = mesh_object.vertex_groups.get(group_name)
    if group is None:
        group = mesh_object.vertex_groups.new(name=group_name)

    indices = list(select_vertices(object_name, vertices))

    if indices:
        group.add(indices, weight, "REPLACE")

    return group.name


def assign_weights_by_height(
    object_name: str,
    group_name: str,
    z_min_m: float,
    z_max_m: float,
    weight: float,
) -> int:
    """Assign ``weight`` to the named mesh's vertices whose world-space z is in [z_min_m, z_max_m].

    World-space z is computed via ``matrix_world`` so the op works on
    translated meshes, not just ones sitting at the origin.
    Returns the number of vertices that received the weight.
    """
    import bpy

    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    if weight < MINIMUM_WEIGHT or weight > MAXIMUM_WEIGHT:
        raise ValueError(
            f"weight {weight} out of range [{MINIMUM_WEIGHT}, {MAXIMUM_WEIGHT}]"
        )

    # matrix_world is lazy (see blended.ops.transforms): a location set a
    # moment ago is invisible to it until the view layer updates.
    bpy.context.view_layer.update()
    matrix_world = mesh_object.matrix_world
    mesh = mesh_object.data

    in_range_indices: list[int] = []
    for i, vertex in enumerate(mesh.vertices):
        world_co = matrix_world @ vertex.co
        if z_min_m <= world_co.z <= z_max_m:
            in_range_indices.append(i)

    if in_range_indices:
        group = mesh_object.vertex_groups.get(group_name)
        if group is None:
            group = mesh_object.vertex_groups.new(name=group_name)
        group.add(in_range_indices, weight, "REPLACE")

    return len(in_range_indices)


@op(reads_only=True)
def deforming_bone_names(object_name: str) -> tuple[str, ...]:
    """Bones of the armature that actually deforms the named mesh.

    Empty when no ENABLED Armature modifier points anywhere: with no
    armature there is nothing to compare group names against, and
    guessing would invent failures on an unrigged mesh.
    """
    from blended.ops._objects import object_by_name
    from blended.ops.rigging import ARMATURE_MODIFIER_TYPE

    mesh_object = object_by_name(object_name, "MESH")
    for modifier in mesh_object.modifiers:
        if (
            modifier.type == ARMATURE_MODIFIER_TYPE
            and modifier.object is not None
            and modifier.show_viewport
            and modifier.show_render
        ):
            return tuple(bone.name for bone in modifier.object.data.bones)
    return ()


@op(reads_only=True)
def weight_report(object_name: str) -> WeightReport:
    """Return a frozen snapshot of the named mesh's vertex-group weights.

    ``nonzero_weight_counts`` maps each group name to the number of
    vertices that have a non-zero weight in that group.
    ``unweighted_vertex_count`` is the number of vertices that belong to
    no group with a non-zero weight. ``groups_without_bones`` and
    ``bones_without_groups`` cross-check the names against the armature
    that deforms the mesh — weights that name no bone move nothing, and
    counting them as work done is how a typo passes for a rig.
    """
    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    mesh = mesh_object.data
    group_names = tuple(group.name for group in mesh_object.vertex_groups)

    nonzero_counts: dict[str, int] = {}
    weighted_vertex_indices: set[int] = set()

    for group in mesh_object.vertex_groups:
        count = 0
        for vertex in mesh.vertices:
            for group_element in vertex.groups:
                if group_element.group == group.index and group_element.weight > 0.0:
                    count += 1
                    weighted_vertex_indices.add(vertex.index)
                    break
        nonzero_counts[group.name] = count

    unweighted = len(mesh.vertices) - len(weighted_vertex_indices)
    bone_names = deforming_bone_names(object_name)
    dead_groups = (
        tuple(name for name in group_names if name not in bone_names)
        if bone_names
        else ()
    )
    unused_bones = tuple(name for name in bone_names if name not in group_names)

    return WeightReport(
        group_names=group_names,
        nonzero_weight_counts=nonzero_counts,
        unweighted_vertex_count=unweighted,
        groups_without_bones=dead_groups,
        bones_without_groups=unused_bones,
    )
