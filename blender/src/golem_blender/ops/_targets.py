"""Resolve a target argument to MESH objects: one name may mean three things.

Every measuring op added for view geometry takes `target: str | list[str]`,
and a string has to be allowed to say "this assembly" or "this piece" because
that is what the user built — an assembly is a REGISTRY ENTRY, not a scene
object (see `ops/assembly.define_assembly`), so resolving it through
`bpy.data.objects` would fail on a name the user just created. The precedence
is therefore assembly, then piece, then object, and it is stated once here so
every op agrees; a name that means two things resolves the same way in all of
them.

Private (underscore module): shared plumbing, not an op, not a tool.
"""

from __future__ import annotations

from golem_blender.ops._objects import UnknownObject

EMPTY_TARGET_REFUSAL = "a target must name at least one thing to measure"


def resolve_mesh_targets(target: str | list[str]) -> tuple[str, list]:
    """(label, MESH objects). A list names objects. A string is an assembly,
    else a piece, else one MESH object."""
    import bpy

    from golem_blender.ops._objects import object_by_name

    if isinstance(target, str):
        name = target.strip()
        if not name:
            raise ValueError(EMPTY_TARGET_REFUSAL)
        # Imported inside the function: `assembly` and `pieces` import ops
        # that take targets, so a module-level import would close a cycle.
        from golem_blender.ops import assembly, pieces

        if name in assembly._ASSEMBLIES:
            names, objects = assembly._resolved_parts(name)
            if not objects:
                raise UnknownObject(
                    f"assembly {name!r} has no MESH parts in the scene "
                    f"(its names: {list(names)})"
                )
            return name, objects
        if name in pieces._PIECES:
            objects = pieces._piece_mesh_objects(name)
            if not objects:
                raise UnknownObject(f"piece {name!r} has no MESH members")
            return name, objects
        try:
            return name, [object_by_name(name, expected_type="MESH")]
        except UnknownObject:
            raise UnknownObject(
                f"{name!r} is no assembly, piece or mesh object (assemblies: "
                f"{sorted(assembly._ASSEMBLIES)}, pieces: {sorted(pieces._PIECES)}, "
                f"meshes: {sorted(o.name for o in bpy.data.objects if o.type == 'MESH')})"
            ) from None

    if isinstance(target, (list, tuple)):
        names = list(target)
        if not names:
            raise ValueError(EMPTY_TARGET_REFUSAL)
        objects = []
        missing = []
        for name in names:
            try:
                objects.append(object_by_name(name, expected_type="MESH"))
            except UnknownObject:
                missing.append(name)
        if missing:
            raise UnknownObject(
                f"no MESH object named {missing} (present: "
                f"{sorted(o.name for o in bpy.data.objects if o.type == 'MESH')})"
            )
        return ", ".join(names), objects

    raise TypeError(
        f"a target is a name or a list of names, got {type(target).__name__}"
    )
