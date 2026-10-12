"""Primitive construction operations.

Convention: build with bmesh / the data API, not bpy.ops primitives.
Operators depend on context (active object, mode, area) and their
keyword arguments drift across versions; bmesh construction is
context-free, deterministic, and headless-safe. This is the base
vocabulary the reusable-component library grows from — executable code
as the action space (CodeAct, DOI 10.48550/arXiv.2402.01030) over a
surface that survives Blender's API drift (BlenderLLM,
DOI 10.48550/arXiv.2412.14203).

Convention: construction is IDEMPOTENT BY NAME. A failed attempt leaves
its partial objects in the scene; re-creating under the same name would
silently become "Name.001" while lookups still find the stale "Name"
(measured in the stage-1 retry test — see drift catalog). So every
constructor first removes any existing object with its target name.
"""

from __future__ import annotations

from blended.ops._contract import op
from blended.ops._objects import ObjectName


@op(gated=False)
def add_box(
    name: str,
    width_m: float,
    depth_m: float,
    height_m: float,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectName:
    """Create a closed box mesh object, centred on X/Y with its BASE at location_m[2], idempotent by name.

    location_m is NOT the centre: the box sits on z = location_m[2],
    which matches the game-asset convention of feet/base at z=0. Said
    in the summary line because that line is all the manifest and the
    tool schema carry — measured 2026-09-10 (iterations 68 and 73): a
    writer given only "of the given outer dimensions" placed the
    planter's centre at the base and failed the floor probe twice.
    """
    import bmesh
    import bpy

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    box_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        half_height_offset_m = height_m / 2.0
        for vertex in working_mesh.verts:
            vertex.co.x = vertex.co.x * width_m + location_m[0]
            vertex.co.y = vertex.co.y * depth_m + location_m[1]
            vertex.co.z = vertex.co.z * height_m + location_m[2] + half_height_offset_m
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return box_object.name


def link_into_scene(object_name: str) -> ObjectName:
    """Link the named object into the active scene collection.

    Never skip this: an unlinked object has no depsgraph instance, so
    evaluated_get() silently returns stored values (see drift catalog).
    """
    import bpy

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    collection = bpy.context.scene.collection
    # Idempotent by name like every constructor: the gate (OT-5) makes
    # linking the first measured step, and a second link must not fail.
    if blender_object.name not in collection.objects:
        collection.objects.link(blender_object)
    return ObjectName(object_name)


class NameTaken(ValueError):
    """The requested name already belongs to another object."""


def rename_object(object_name: str, new_name: str) -> ObjectName:
    """Rename the named object (and its mesh data) to new_name; loud if new_name is taken.

    Measured demand (OT-12, iterations 69): a boolean keeps its TARGET's
    name, so a brief that names the finished asset differently needed
    four escape-hatch calls to rename it. Blender would silently mint
    `new_name.001` on a collision; that is a second object nobody asked
    for, so a taken name raises NameTaken instead.
    """
    import bpy

    from blended.ops._objects import object_by_name

    if not new_name.strip():
        raise ValueError("new_name must be non-empty")
    blender_object = object_by_name(object_name)
    if new_name == blender_object.name:
        return ObjectName(new_name)
    if new_name in bpy.data.objects:
        raise NameTaken(
            f"cannot rename {object_name!r} to {new_name!r}: an object of that "
            f"name already exists (remove_object_and_mesh it first)"
        )
    blender_object.name = new_name
    if blender_object.data is not None:
        blender_object.data.name = new_name
    # Blender truncates names past its length limit; report the name the
    # object actually has, which is the one every later op must look up.
    return ObjectName(blender_object.name)


def remove_object_and_mesh(object_name: str) -> None:
    """Remove an object (and its now-orphaned mesh) by exact name.

    The idempotency primitive: constructors call this first so a rerun
    after a failed attempt replaces the stale object instead of silently
    creating a .001-suffixed sibling on top of it.
    """
    import bpy

    existing_object = bpy.data.objects.get(object_name)
    if existing_object is None:
        return
    existing_data = existing_object.data
    bpy.data.objects.remove(existing_object)
    # The object may be of ANY type (a constructor replaces whatever holds
    # its name: measured, add_box over an armature raised TypeError from
    # `bpy.data.meshes.remove(armature_data)` AFTER the armature was gone),
    # so its orphaned data is removed type-blind.
    if existing_data is not None and existing_data.users == 0:
        bpy.data.batch_remove((existing_data,))


@op(gated=False)
def add_cylinder(
    name: str,
    radius_m: float,
    height_m: float,
    segment_count: int = 24,
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectName:
    """Create a closed cylinder mesh object, base at location_m[2], idempotent by name."""
    import bmesh
    import bpy

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    cylinder_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cone(
            working_mesh,
            cap_ends=True,
            cap_tris=False,
            segments=segment_count,
            radius1=radius_m,
            radius2=radius_m,
            depth=height_m,
        )
        half_height_offset_m = height_m / 2.0
        for vertex in working_mesh.verts:
            vertex.co.x += location_m[0]
            vertex.co.y += location_m[1]
            vertex.co.z += location_m[2] + half_height_offset_m
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return cylinder_object.name
