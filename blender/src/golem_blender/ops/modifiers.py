"""Modifier operations, applied through the data API (no bpy.ops)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName

BEVEL_MODIFIER_NAME = "Bevel"
DECIMATE_MODIFIER_NAME = "Decimate"
# A COLLAPSE pass removes faces in proportion to its `ratio` and lands within
# a face or two of the count it was asked for, so one pass usually reaches the
# budget; the ceiling is the same 3 `ingest.cleanup` uses (ING-2), and a pass
# that cannot lower the count any further ends the loop instead of spending
# the rest of it.
MAXIMUM_DECIMATE_PASSES = 3
# How far off the requested count a result may land and still count as having
# reached it. Issue #16's acceptance condition 1: within 2% of the target.
DECIMATE_TARGET_TOLERANCE = 0.02
# The DECIMATE modifier reads its vertex group by NAME off the object, so
# pinning an open edge means writing one. Reserved by this module: a leftover
# group of this name would silently pin vertices it did not choose.
BOUNDARY_PIN_GROUP_NAME = "__golem_decimate_boundary"


@dataclass(frozen=True)
class DecimateReport:
    """What one decimation left in the scene. Numbers, not opinions.

    `reached_target` is the honest bit for a caller building an LOD: it says
    the requested budget was met, not that a modifier ran. `parts_present`
    and `boundary_edge_count` are there because the issue's fourth edge case
    is a caller deciding to DROP a part rather than ship one collapsed past
    recognition, and neither number is visible from the triangle count.
    """

    object_name: str
    triangles_before: int
    triangles_after: int
    target_triangles: int  # the budget actually applied, resolved from either argument
    reached_target: bool
    decimate_passes: int  # 0 when the mesh was already at or under the target
    material_slots: int  # unchanged by collapse; reported so it cannot drift silently
    uv_layer_count: int  # the layer survives; its islands do not (see the op)
    parts_present: int  # edge-connected components, counted the analyzer's way
    boundary_edge_count: int


def add_bevel(
    object_name: str,
    width_m: float,
    segment_count: int,
) -> ObjectName:
    """Add a bevel modifier to every edge of the named object."""
    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name, "MESH")
    bevel_modifier = blender_object.modifiers.new(
        name=BEVEL_MODIFIER_NAME, type="BEVEL"
    )
    bevel_modifier.width = width_m
    bevel_modifier.segments = segment_count
    bevel_modifier.limit_method = "NONE"
    return ObjectName(object_name)


def apply_all_modifiers(object_name: str) -> ObjectName:
    """Bake the named object's evaluated (post-modifier) mesh back into it.

    Uses the depsgraph rather than bpy.ops.object.modifier_apply, so it
    needs no context override and works identically headless and live.
    The object must already be linked into the scene, or the evaluated
    copy will silently equal the stored mesh (see drift catalog).
    """
    import bpy

    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    baked_mesh = bpy.data.meshes.new_from_object(
        evaluated_object, depsgraph=dependency_graph
    )
    previous_mesh = blender_object.data
    blender_object.data = baked_mesh
    blender_object.modifiers.clear()
    if previous_mesh.users == 0:
        bpy.data.meshes.remove(previous_mesh)
    return ObjectName(object_name)


@op(gated=True)
def decimate_object(
    object_name: str,
    target_triangles: int | None = None,
    ratio: float | None = None,
    preserve_boundary: bool = True,
) -> DecimateReport:
    """Reduce the named mesh to target_triangles, or to ratio of its own count.

    One LOD level of a piece golem built: Sanctuary's decision 0294 wants
    every kit piece at 60% and 30% of LOD0's triangles, and where the caller
    knows the budget `target_triangles` is the honest argument — a ratio
    makes the author compute it. A mesh already at or under the target is
    left untouched, byte for byte, and reports `reached_target` true. A
    target the topology cannot reach reports `reached_target` false with the
    count actually achieved, so the caller can drop a part instead of
    shipping a distorted one.

    `preserve_boundary` pins every vertex on an open edge and keeps quads
    (the modifier's `use_collapse_triangulate` off): a kit piece's parts are
    separate solids in one mesh, and an unpinned rim collapses away — measured
    on a 40x40 grid at ratio 0.3, 160 boundary edge-keys before and after with
    the pin, 79 without it. Material slots are kept. The UV LAYER survives and
    the layout survives better than expected (a smart-projected sphere at 3000
    of 10200 triangles keeps its 6 islands and stretches by ~3%), but collapse
    does re-triangulate, so `unwrap_uvs` any level whose texture must line up
    exactly with LOD0's.
    """
    import bpy

    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.assets import _triangle_count
    from golem_blender.ops.transforms import _refresh_dependency_graph

    if target_triangles is None and ratio is None:
        raise ValueError(
            "decimate_object needs one of target_triangles or ratio; without "
            "one there is nothing to aim at"
        )
    if target_triangles is not None and ratio is not None:
        raise ValueError(
            "give target_triangles OR ratio, not both: a target is the honest "
            "argument, and two budgets cannot both be met"
        )

    blender_object = object_by_name(object_name, "MESH")
    _refresh_dependency_graph()
    if blender_object.name not in bpy.context.scene.objects:
        raise ValueError(
            f"{object_name!r} is not linked into the scene, so its modifier "
            f"would evaluate to nothing (link_into_scene it first)"
        )
    if blender_object.modifiers:
        # `apply_all_modifiers` bakes the WHOLE stack, so decimating a mesh that
        # still carries a pending bevel would apply that bevel too — a change
        # nobody asked for, measured after the fact.
        raise ValueError(
            f"{object_name!r} still has {len(blender_object.modifiers)} unapplied "
            f"modifier(s) ({[modifier.name for modifier in blender_object.modifiers]}); "
            f"apply_all_modifiers it first, so this op acts on the mesh you can "
            f"count rather than baking what you left pending"
        )
    # The reserved group is checked BEFORE the first pass, not inside it: a
    # call that cannot pin has to refuse while the mesh is still untouched.
    if preserve_boundary and BOUNDARY_PIN_GROUP_NAME in blender_object.vertex_groups:
        raise ValueError(
            f"{blender_object.name!r} already has a vertex group named "
            f"{BOUNDARY_PIN_GROUP_NAME!r}, which this op reserves for the "
            f"boundary pin; rename it before decimating with preserve_boundary"
        )

    triangles_before = _triangle_count(blender_object.data)
    if triangles_before == 0:
        raise ValueError(
            f"{object_name!r} has no faces, so there is nothing to decimate"
        )

    if target_triangles is None:
        if not math.isfinite(ratio) or not 0.0 < ratio <= 1.0:
            raise ValueError(
                f"ratio must be in (0, 1], got {ratio}: a ratio above 1 asks a "
                f"collapse to add geometry, which it cannot"
            )
        requested_triangles = max(1, round(triangles_before * ratio))
    else:
        if target_triangles < 1:
            raise ValueError(
                f"target_triangles must be at least 1, got {target_triangles}"
            )
        requested_triangles = target_triangles

    decimate_passes = 0
    previous_triangles = triangles_before
    while (
        requested_triangles < previous_triangles
        and decimate_passes < MAXIMUM_DECIMATE_PASSES
    ):
        pin_group = _pin_open_edges(blender_object) if preserve_boundary else None
        try:
            decimate_modifier = blender_object.modifiers.new(
                name=DECIMATE_MODIFIER_NAME, type="DECIMATE"
            )
            decimate_modifier.decimate_type = "COLLAPSE"
            # Aimed exactly at the budget: a pass that falls short of the
            # reduction is measured and aimed again from the count it left,
            # so an undershoot costs a pass, never the result.
            decimate_modifier.ratio = requested_triangles / previous_triangles
            decimate_modifier.use_collapse_triangulate = not preserve_boundary
            if pin_group is not None:
                decimate_modifier.vertex_group = pin_group.name
                decimate_modifier.vertex_group_factor = 1.0
                decimate_modifier.invert_vertex_group = True
            apply_all_modifiers(object_name)
        finally:
            if pin_group is not None:
                _remove_pin_group(blender_object)
        decimate_passes += 1
        current_triangles = _triangle_count(blender_object.data)
        if current_triangles >= previous_triangles:
            # The collapse refused to remove anything more: the topology is
            # at its floor, and another pass would only spend time arriving
            # at the same count.
            break
        previous_triangles = current_triangles

    triangles_after = _triangle_count(blender_object.data)
    parts_present, boundary_edge_count = _part_and_boundary_counts(blender_object.data)
    if requested_triangles >= triangles_before:
        # Nothing was asked for: the mesh already fits, and "at or under the
        # target" is the issue's own definition of reaching it.
        reached_target = True
    else:
        reached_target = (
            abs(triangles_after - requested_triangles)
            <= DECIMATE_TARGET_TOLERANCE * requested_triangles
        )
    return DecimateReport(
        object_name=blender_object.name,
        triangles_before=triangles_before,
        triangles_after=triangles_after,
        target_triangles=requested_triangles,
        reached_target=reached_target,
        decimate_passes=decimate_passes,
        material_slots=len(blender_object.data.materials),
        uv_layer_count=len(blender_object.data.uv_layers),
        parts_present=parts_present,
        boundary_edge_count=boundary_edge_count,
    )


def _pin_open_edges(blender_object):
    """Weight every vertex on an open edge at 1.0, for the modifier to invert.

    A COLLAPSE modifier has no boundary flag (the modifier's own
    `use_dissolve_boundaries` belongs to DISSOLVE, not COLLAPSE), so an open
    edge is kept the only way Blender offers: a vertex group, inverted, so
    that a weight of 1 becomes an effective weight of 0 and a zero-weight
    vertex is not collapsed. Measured on a 40x40 grid at ratio 0.3: 160
    boundary vertices before, 160 after with the pin and 79 without it.

    Returns None for a closed mesh, which has no open edge to pin — and
    writes no group it would then have to remove.
    """
    if BOUNDARY_PIN_GROUP_NAME in blender_object.vertex_groups:
        raise ValueError(
            f"{blender_object.name!r} already has a vertex group named "
            f"{BOUNDARY_PIN_GROUP_NAME!r}, which this op reserves for the "
            f"boundary pin; rename it before decimating with preserve_boundary"
        )
    mesh = blender_object.data
    faces_per_edge: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            faces_per_edge[edge_key] = faces_per_edge.get(edge_key, 0) + 1
    boundary_vertices = sorted(
        {
            vertex_index
            for edge_key, face_count in faces_per_edge.items()
            if face_count == 1
            for vertex_index in edge_key
        }
    )
    if not boundary_vertices:
        return None
    group = blender_object.vertex_groups.new(name=BOUNDARY_PIN_GROUP_NAME)
    group.add(boundary_vertices, 1.0, "REPLACE")
    return group


def _remove_pin_group(blender_object) -> None:
    """Remove the reserved pin group by NAME.

    `apply_all_modifiers` REPLACES the object's mesh, so the group it
    returns is a different datablock from the one added: removing the
    remembered group raises `DeformGroup '' not in object` (measured). The
    name is the only handle that survives the bake.
    """
    group = blender_object.vertex_groups.get(BOUNDARY_PIN_GROUP_NAME)
    if group is not None:
        blender_object.vertex_groups.remove(group)


def _part_and_boundary_counts(mesh) -> tuple[int, int]:
    """(edge-connected parts, edges used by exactly one face).

    The parts are counted by the analyzer's own flood fill, so a report
    saying "every part is still here" cannot disagree with the gate that
    measures the same object.
    """
    import bmesh

    from golem_blender.analyze.mesh_checks import _count_connected_components

    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(mesh)
        boundary_edge_count = sum(
            1 for edge in working_mesh.edges if len(edge.link_faces) == 1
        )
        return _count_connected_components(working_mesh), boundary_edge_count
    finally:
        working_mesh.free()
