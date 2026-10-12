"""Modifier operations, applied through the data API (no bpy.ops)."""

from __future__ import annotations

from blended.ops._objects import ObjectName

BEVEL_MODIFIER_NAME = "Bevel"


def add_bevel(
    object_name: str,
    width_m: float,
    segment_count: int,
) -> ObjectName:
    """Add a bevel modifier to every edge of the named object."""
    from blended.ops._objects import object_by_name

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

    from blended.ops._objects import object_by_name

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
