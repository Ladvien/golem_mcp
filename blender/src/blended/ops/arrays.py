"""Array operations via the ARRAY modifier, applied through the depsgraph.

Note the honest intermediate state: an applied array is N disconnected
copies in ONE mesh — deliberately multi-component. It only becomes a
gate-passing solid once something (usually a boolean_union with a
connecting part) bridges the copies. Builders own that step; the gate
verifies it happened.
"""

from __future__ import annotations

from blended.ops._objects import ObjectName

MINIMUM_ARRAY_COUNT = 2
ARRAY_MODIFIER_NAME = "LinearArray"


def linear_array(
    object_name: str,
    count: int,
    offset_m: tuple[float, float, float],
) -> ObjectName:
    """Repeat the named object `count` times at a constant metric offset, baked into its mesh."""
    from blended.ops._objects import object_by_name
    from blended.ops.modifiers import apply_all_modifiers

    if count < MINIMUM_ARRAY_COUNT:
        raise ValueError(f"Array count must be >= {MINIMUM_ARRAY_COUNT}.")

    blender_object = object_by_name(object_name, "MESH")
    array_modifier = blender_object.modifiers.new(
        name=ARRAY_MODIFIER_NAME, type="ARRAY"
    )
    array_modifier.count = count
    array_modifier.use_relative_offset = False
    array_modifier.use_constant_offset = True
    array_modifier.constant_offset_displace = offset_m
    apply_all_modifiers(object_name)
    return ObjectName(object_name)
