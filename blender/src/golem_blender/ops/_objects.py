"""Name-to-datablock resolution shared by every op.

OPS-21 (OT-2): an op's signature carries no bpy type. Callers — the agent
through a generated tool schema, a builder, a test — hand over the NAME
of an object, and the op looks it up here. One helper, one error, so a
typo in a name fails the same way from every op instead of surfacing as
whichever AttributeError the first bpy access happens to raise.

Private (underscore module): not part of the facade, not in the
manifest, not a tool. The facade's contract test skips underscore
modules for exactly this reason.
"""

from __future__ import annotations

from typing import NewType

# The return type of an op that CREATES OR MODIFIES an object. `str` at
# runtime; distinct to the contract, the schema generator and the gate:
# an op annotated `-> ObjectName` names a scene object the harness can
# locate and measure, an op annotated `-> str` returns text (a material
# name, a reading). OT-5 gates on this distinction.
ObjectName = NewType("ObjectName", str)


class UnknownObject(LookupError):
    """No datablock of the requested name exists in `bpy.data.objects`."""


class WrongObjectType(TypeError):
    """The named object exists but is not of the type the op requires."""


def object_by_name(object_name: str, expected_type: str | None = None):
    """Return the `bpy.data.objects` entry named `object_name`, loudly.

    `expected_type` is a Blender object type string ("MESH", "ARMATURE");
    when given, a mismatch raises WrongObjectType naming both sides so an
    op that needs a mesh never gets three attribute errors deep into an
    armature before anyone notices.
    """
    import bpy

    if not isinstance(object_name, str):
        raise TypeError(
            f"ops take object NAMES (str), got {type(object_name).__name__}: "
            f"{object_name!r}. Pass the name the constructor returned."
        )
    blender_object = bpy.data.objects.get(object_name)
    if blender_object is None:
        raise UnknownObject(
            f"no object named {object_name!r} in bpy.data.objects "
            f"(present: {sorted(o.name for o in bpy.data.objects)})"
        )
    if expected_type is not None and blender_object.type != expected_type:
        raise WrongObjectType(
            f"{object_name!r} is a {blender_object.type}, not {expected_type}"
        )
    return blender_object
