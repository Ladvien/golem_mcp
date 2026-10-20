"""Armature rigging operations through the data API.

Why this op exists: a chat agent needs to rig, weight-paint, and animate
through `golem_blender.ops`, but creating bones requires entering EDIT mode on
an armature — an inherently context-dependent operation. This module
wraps that context dance behind a declarative `BoneSpec` list so the
caller never touches `bpy.ops` directly.

Idempotent by name, like the primitive constructors: re-running
`add_armature` under the same name removes the stale object and armature
data before rebuilding, so a failed attempt never poisons a retry with
a `.001`-suffixed sibling.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName

MINIMUM_BONE_LENGTH_M = 1e-6
"""Bones shorter than this are treated as zero-length and rejected.

Blender allows degenerate bones but they break the heat-skin solver and
confuse the weight-paint UI; rejecting them early turns a mysterious
runtime crash into a clear ValueError."""

ARMATURE_MODIFIER_TYPE = "ARMATURE"


@dataclass(frozen=True)
class BoneSpec:
    """Declarative description of one edit bone.

    Coordinates are in **armature-local** metres, matching the
    `location_m` offset applied to the armature object.  `parent_name`
    must reference a bone that appears earlier in the `bones` tuple
    (parents are resolved in order during edit-bone construction).
    """

    name: str
    head_m: tuple[float, float, float]
    tail_m: tuple[float, float, float]
    parent_name: str = ""
    connected: bool = False


@dataclass(frozen=True)
class RigReport:
    """Frozen snapshot of an armature's rig state for chat-E2E asserts."""

    armature_name: str
    bone_count: int
    bone_names: tuple[str, ...]
    # Meshes this armature ACTUALLY deforms: an Armature modifier that
    # points here and is enabled in both viewport and render.
    bound_mesh_names: tuple[str, ...]
    # Meshes wired to this armature by a DISABLED modifier. They carry
    # every sign of a finished rig — parent set, vertex groups weighted,
    # modifier present — and deform nothing, which is the rig-lane
    # version of the gate's `hide_render` hole. Reported separately so
    # `bound_mesh_names` keeps meaning "deforming".
    disabled_modifier_mesh_names: tuple[str, ...] = ()


def add_armature(
    name: str,
    bones: tuple[BoneSpec, ...],
    location_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> ObjectName:
    """Create an armature object with the given edit bones, linked into the scene.

    Idempotent by name (removes any existing object + armature data of
    that name first).  Bones are created in EDIT mode via
    `temp_override` — the only context-safe way to manipulate
    `armature.edit_bones` in a headless Blender.  Returns the armature
    object's name (in OBJECT mode).

    Raises:
        ValueError: on empty bones, duplicate bone names, unknown parent
            references, a parent listed after its child, or zero-length
            bones (below ``MINIMUM_BONE_LENGTH_M``).
    """
    import bpy

    from golem_blender.ops.primitives import remove_object_and_mesh

    if not bones:
        raise ValueError("add_armature requires at least one bone")

    bone_names = [b.name for b in bones]
    if len(set(bone_names)) != len(bone_names):
        raise ValueError(
            f"Duplicate bone names in add_armature({name!r}): {bone_names}"
        )

    # Parents are resolved in order during edit-bone construction, so a
    # parent must be listed BEFORE its child (BoneSpec contract). Checked
    # here: found mid-build it would be a KeyError inside EDIT mode.
    bones_listed_so_far: set[str] = set()
    for spec in bones:
        if spec.parent_name:
            if spec.parent_name not in bone_names:
                raise ValueError(
                    f"Bone {spec.name!r} references unknown parent {spec.parent_name!r}"
                )
            if spec.parent_name not in bones_listed_so_far:
                raise ValueError(
                    f"Bone {spec.name!r} lists parent {spec.parent_name!r} "
                    f"at or after itself; parents must come first"
                )
        bones_listed_so_far.add(spec.name)

    for spec in bones:
        dx = spec.tail_m[0] - spec.head_m[0]
        dy = spec.tail_m[1] - spec.head_m[1]
        dz = spec.tail_m[2] - spec.head_m[2]
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        if length < MINIMUM_BONE_LENGTH_M:
            raise ValueError(
                f"Bone {spec.name!r} has zero length ({length:.2e} m < "
                f"{MINIMUM_BONE_LENGTH_M:.2e} m)"
            )

    remove_object_and_mesh(name)

    armature_data = bpy.data.armatures.new(name)
    armature_object = bpy.data.objects.new(name, armature_data)
    armature_object.location = location_m
    bpy.context.scene.collection.objects.link(armature_object)
    # The VIEW LAYER, not just the collection: a newly linked object
    # does not join the layer until the depsgraph is refreshed, and the
    # edit bones below need the object to be in it.
    bpy.context.view_layer.update()

    _create_edit_bones(armature_object, bones)
    armature_object.select_set(False)
    return armature_object.name


def bind_mesh_to_armature(
    mesh_name: str,
    armature_name: str,
    automatic_weights: bool = True,
) -> ObjectName:
    """Parent the named mesh to the named armature with an Armature modifier.

    Uses the data API for the parent relationship and modifier
    (``mesh_object.parent``, ``modifier.object``).  When
    ``automatic_weights`` is True, delegates to
    ``bpy.ops.object.parent_set(type='ARMATURE_AUTO')`` under
    ``temp_override`` — bpy.ops is unavoidable here because the
    automatic heat-skin weight generation (`mesh_data.transform`,
    nearest-bone heat diffusion) is implemented entirely inside that
    operator with no data-API equivalent.  The override supplies the
    selection/active context the operator requires.

    Idempotent: removes any pre-existing Armature modifier on the mesh
    before (re-)adding exactly one, so re-binding never stacks modifiers.
    Returns the mesh name.
    """
    import bpy

    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(mesh_name, "MESH")
    armature_object = object_by_name(armature_name, "ARMATURE")

    # Remove stale Armature modifiers so re-binding leaves exactly one.
    for mod in list(mesh_object.modifiers):
        if mod.type == ARMATURE_MODIFIER_TYPE:
            mesh_object.modifiers.remove(mod)

    mesh_object.parent = armature_object
    # Setting `.parent` leaves the parent-inverse as it was (identity on a
    # fresh mesh), so a mesh bound to an armature that is not at the world
    # origin would jump by the armature's transform (measured: armature at
    # z=1, automatic_weights=False, box moved from z 0..1 to z 1..2). The
    # inverse of the armature's world matrix keeps the mesh where it is.
    bpy.context.view_layer.update()
    mesh_object.matrix_parent_inverse = armature_object.matrix_world.inverted()

    if automatic_weights:
        # parent_set with ARMATURE_AUTO generates vertex groups + heat
        # weights AND adds the Armature modifier internally.  We run it
        # first, then normalise the modifier count to exactly one.
        for obj in bpy.context.scene.collection.all_objects:
            obj.select_set(False)
        mesh_object.select_set(True)
        armature_object.select_set(True)
        bpy.context.view_layer.objects.active = armature_object
        with bpy.context.temp_override(
            selected_objects=[mesh_object, armature_object],
            active_object=armature_object,
        ):
            bpy.ops.object.parent_set(type="ARMATURE_AUTO")

        # parent_set may add its own Armature modifier; collapse to one.
        armature_mods = [
            m for m in mesh_object.modifiers if m.type == ARMATURE_MODIFIER_TYPE
        ]
        if armature_mods:
            armature_mods[0].object = armature_object
            for extra in armature_mods[1:]:
                mesh_object.modifiers.remove(extra)
        else:
            mod = mesh_object.modifiers.new(
                name="Armature", type=ARMATURE_MODIFIER_TYPE
            )
            mod.object = armature_object
    else:
        mod = mesh_object.modifiers.new(name="Armature", type=ARMATURE_MODIFIER_TYPE)
        mod.object = armature_object

    return ObjectName(mesh_name)


@op(reads_only=True)
def rig_report(armature_name: str) -> RigReport:
    """Return a frozen snapshot of the named armature and its bound meshes.

    A mesh counts as BOUND only when its Armature modifier points at
    ``armature_object`` AND is enabled in viewport and render. A
    disabled modifier is reported separately rather than counted:
    parenting, vertex groups and a modifier can all be in place while
    the mesh deforms nowhere, and a report that called that "bound"
    would be telling the writer its rig works.
    """
    import bpy

    from golem_blender.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    armature_data = armature_object.data
    bone_names = tuple(bone.name for bone in armature_data.bones)

    bound_mesh_names: list[str] = []
    disabled_mesh_names: list[str] = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for mod in obj.modifiers:
            if mod.type == ARMATURE_MODIFIER_TYPE and mod.object is armature_object:
                if mod.show_viewport and mod.show_render:
                    bound_mesh_names.append(obj.name)
                else:
                    disabled_mesh_names.append(obj.name)
                break

    return RigReport(
        armature_name=armature_object.name,
        bone_count=len(bone_names),
        bone_names=bone_names,
        bound_mesh_names=tuple(bound_mesh_names),
        disabled_modifier_mesh_names=tuple(disabled_mesh_names),
    )


# -- internals -----------------------------------------------------------


def _create_edit_bones(armature_object, bones: tuple[BoneSpec, ...]) -> None:
    """Create ``bones`` on ``armature_object`` in EDIT mode, then return to OBJECT mode.

    The one place bones are made. A parent named by a spec is looked up
    among the bones created earlier in this call, then among the bones
    the armature already has, so the same path adds a first skeleton
    (``add_armature``) and extends an existing one (``bake_cloth_chains``).
    The armature becomes the active, selected object.
    """
    import bpy

    armature_data = armature_object.data
    # edit_bones are only editable in EDIT mode.  In a headless context
    # there is no active area, so we must override the mode context via
    # temp_override rather than relying on the viewport.
    bpy.context.view_layer.objects.active = armature_object
    armature_object.select_set(True)
    with bpy.context.temp_override(
        object=armature_object,
        active_object=armature_object,
        selected_objects=[armature_object],
    ):
        bpy.ops.object.mode_set(mode="EDIT")
        try:
            created: dict[str, object] = {}
            for spec in bones:
                edit_bone = armature_data.edit_bones.new(spec.name)
                edit_bone.head = spec.head_m
                edit_bone.tail = spec.tail_m
                if spec.parent_name:
                    edit_bone.parent = (
                        created[spec.parent_name]
                        if spec.parent_name in created
                        else armature_data.edit_bones[spec.parent_name]
                    )
                    edit_bone.use_connect = spec.connected
                created[spec.name] = edit_bone
        finally:
            # A failure mid-build must not strand the file in EDIT mode.
            bpy.ops.object.mode_set(mode="OBJECT")
