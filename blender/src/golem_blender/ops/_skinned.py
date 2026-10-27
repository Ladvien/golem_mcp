"""An armature and its bound meshes as skinclip objects, and keys written back.

Why this adapter exists: skinclip (numpy only) checks and repairs skinned
motion from glTF-shaped data (a node skeleton, a skinned figure, clips of
local translation/rotation/scale). Blender holds the same rig as bones
with a rest matrix and pose-bone channels that are RELATIVE to that rest.
This module is the one place the two are converted, and it only reads the
scene, apart from the three writers at the end (`write_rotation_keys`,
`ensure_chain_bones`, `weight_garment`).

The conversion, per bone (Blender evaluates
``parent_pose @ (parent.matrix_local^-1 @ bone.matrix_local) @ basis``):

  rest_local  = parent.matrix_local^-1 @ bone.matrix_local   (roots: armature.matrix_world @ matrix_local)
  local_t     = rest_t + rotate(rest_r, basis_t)
  local_r     = rest_r (x) basis_r
  local_s     = basis_s            (rest scale is 1)
  basis_r     = conjugate(rest_r) (x) local_r                (the write-back)

Not evaluated, so refused loudly rather than measured wrongly: bone
constraints, drivers, NLA strips, shape keys, modifiers other than the
Armature one, bones that do not inherit rotation or scale, and a keyed
bone whose rotation mode is not QUATERNION (`ArmatureRotationModeError`).
Pose bones the action does not key are at their rest pose.

Private (underscore module): shared plumbing, not an op. It imports numpy
and skinclip at module level, so only op BODIES may import it (the
facade, the MCP server and the pure tests import `golem_blender.ops` with no
numpy).

References: the metamorphic contour check is ContourCraft, SIGGRAPH 2024,
DOI 10.1145/3641519.3657408; the chain simulation is position-based
dynamics, Abu Rumman and Fratarcangeli, Computer Graphics Forum 2015, DOI
10.1111/cgf.12533 (both through skinclip).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from skinclip import cloth, linalg, pose, quat
from skinclip.capsules import Capsule, positions
from skinclip.intersect import CheckSettings, segment_distance
from skinclip.model import Clip, Figure, Skeleton, crease_zones, welded_corners
from skinclip.spec import RingSkirtSpec

from golem_blender.ops._influences import MAXIMUM_INFLUENCES_PER_VERTEX
from golem_blender.ops._pose_paths import (
    LOCATION_CHANNEL,
    ROTATION_QUATERNION_CHANNEL,
    SCALE_CHANNEL,
    parse_pose_bone_path,
    pose_bone_path,
)
from golem_blender.ops.animation import _action_channelbag, _action_fcurves
from golem_blender.ops.motion import ArmatureRotationModeError
from golem_blender.ops.rigging import (
    ARMATURE_MODIFIER_TYPE,
    BoneSpec,
    _create_edit_bones,
)

QUATERNION_ROTATION_MODE = "QUATERNION"
FULL_INHERIT_SCALE = "FULL"
KEY_INTERPOLATION = "LINEAR"

# An armature object scaled away from 1 would put every rest matrix in a
# scaled frame that glTF-shaped nodes (translation, rotation, scale of 1)
# cannot hold; unit scale is checked to this much.
UNIT_SCALE_TOLERANCE = 1e-4

# skinclip's own default for a mesh without a material in the slot.
NO_MATERIAL_LABEL = "mesh"

LABEL_CHUNK_TRIANGLES = 20000

# A channel that moves less than this from the rest value does not count
# as motion (a bone keyed at its rest pose).
MOTION_TOLERANCE = 1e-6

# bone-name groups are weights; any smaller weight is not an influence
MINIMUM_INFLUENCE_WEIGHT = 0.0

# Blender channel -> (skinclip path, components, default basis value).
_CHANNELS = {
    LOCATION_CHANNEL: ("translation", 3, (0.0, 0.0, 0.0)),
    ROTATION_QUATERNION_CHANNEL: ("rotation", 4, (1.0, 0.0, 0.0, 0.0)),  # w, x, y, z
    SCALE_CHANNEL: ("scale", 3, (1.0, 1.0, 1.0)),
}
_WXYZ_TO_XYZW = [1, 2, 3, 0]
_XYZW_TO_WXYZ = [3, 0, 1, 2]


@dataclass(frozen=True)
class ActionClip:
    """The integer frames of an armature's active action as a skinclip clip."""

    action_name: str
    frame_start: int
    frame_end: int
    fps: float
    times_s: np.ndarray  # (F,) seconds from the first frame
    clip: Clip
    keyed_bones: tuple[str, ...]

    @property
    def frame_count(self) -> int:
        return self.frame_end - self.frame_start + 1

    @property
    def frame_numbers(self) -> list[int]:
        return list(range(self.frame_start, self.frame_end + 1))


# -- reading -----------------------------------------------------------------


def scene_fps() -> float:
    """Frames per second of the active scene (``fps / fps_base``)."""
    import bpy

    render = bpy.context.scene.render
    return float(render.fps) / float(render.fps_base)


def bound_meshes(armature_object) -> list:
    """The mesh objects an enabled Armature modifier points at this armature, as `rig_report` finds them."""
    import bpy

    meshes = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        for modifier in obj.modifiers:
            if (
                modifier.type == ARMATURE_MODIFIER_TYPE
                and modifier.object is armature_object
            ):
                if modifier.show_viewport and modifier.show_render:
                    meshes.append(obj)
                break
    if not meshes:
        raise ValueError(
            f"no mesh is bound to armature {armature_object.name!r} by an "
            "enabled Armature modifier"
        )
    return meshes


def _require_evaluable_rig(armature_object) -> None:
    """Refuse a rig this adapter would measure wrongly: constraints, or bones that do not inherit plainly."""
    constrained = [
        pose_bone.name
        for pose_bone in armature_object.pose.bones
        if len(pose_bone.constraints)
    ]
    if constrained:
        raise ValueError(
            f"pose bones {constrained} of {armature_object.name!r} carry "
            "constraints, which are not evaluated; apply or remove them first"
        )
    odd = [
        bone.name
        for bone in armature_object.data.bones
        if not bone.use_inherit_rotation
        or bone.inherit_scale != FULL_INHERIT_SCALE
        or not bone.use_local_location
    ]
    if odd:
        raise ValueError(
            f"bones {odd} of {armature_object.name!r} do not inherit rotation, "
            "scale or local location plainly; the clip would be read wrongly"
        )


def read_skeleton(armature_object) -> Skeleton:
    """Every bone with its rest transform relative to its parent (roots: in world space)."""
    _require_evaluable_rig(armature_object)
    bones = list(armature_object.data.bones)
    index = {bone.name: i for i, bone in enumerate(bones)}
    world = np.array(armature_object.matrix_world, dtype=float)
    scale = np.linalg.norm(world[:3, :3], axis=0)
    if not np.allclose(scale, 1.0, atol=UNIT_SCALE_TOLERANCE):
        raise ValueError(
            f"armature {armature_object.name!r} has world scale {scale.tolist()}; "
            "apply its scale before measuring motion"
        )
    parent = np.full(len(bones), -1)
    rest_t = np.zeros((len(bones), 3))
    rest_r = np.zeros((len(bones), 4))
    for i, bone in enumerate(bones):
        local = np.array(bone.matrix_local, dtype=float)
        if bone.parent is None:
            relative = world @ local
        else:
            parent[i] = index[bone.parent.name]
            relative = (
                linalg.inverse_affine(np.array(bone.parent.matrix_local, dtype=float))
                @ local
            )
        rest_t[i] = relative[:3, 3]
        rest_r[i] = quat.from_matrix(relative[:3, :3])
    return Skeleton(
        tuple(index),
        parent,
        rest_t,
        rest_r,
        np.ones((len(bones), 3)),
    )


def rest_worlds(skeleton: Skeleton) -> np.ndarray:
    """(N, 4, 4) world matrix of every node at the rest pose."""
    return pose.node_worlds(skeleton, [(Clip("rest", 0.0, {}), np.zeros(1))])[0]


def read_figure(armature_object, settings: CheckSettings) -> Figure:
    """Every mesh bound to the armature as one skinned `Figure` at its rest pose, in world space."""
    skeleton = read_skeleton(armature_object)
    meshes = bound_meshes(armature_object)
    bone_names = set(skeleton.names)
    weighted = {
        group.name
        for mesh_object in meshes
        for group in mesh_object.vertex_groups
        if group.name in bone_names
    }
    if not weighted:
        raise ValueError(
            f"no mesh bound to {armature_object.name!r} has a vertex group named for a bone"
        )
    joint_names = [name for name in skeleton.names if name in weighted]
    slot = {name: i for i, name in enumerate(joint_names)}
    armature_world = np.array(armature_object.matrix_world, dtype=float)
    inverse_bind = np.stack(
        [
            linalg.inverse_affine(
                armature_world
                @ np.array(armature_object.data.bones[name].matrix_local, dtype=float)
            )
            for name in joint_names
        ]
    )
    positions, vertex_joints, vertex_weights, triangles, labels = [], [], [], [], []
    offset = 0
    for mesh_object in meshes:
        data = mesh_object.data
        points, joints, weights = _read_vertices(mesh_object, slot)
        tri, tri_labels = _read_triangles(mesh_object, joints, weights, joint_names)
        positions.append(points)
        vertex_joints.append(joints)
        vertex_weights.append(weights)
        triangles.append(tri + offset)
        labels.extend(tri_labels)
        offset += len(data.vertices)
    stacked = np.concatenate(positions)
    all_triangles = np.concatenate(triangles)
    return Figure(
        armature_object.name,
        Path(armature_object.name),
        skeleton,
        np.array([skeleton.index(name) for name in joint_names]),
        inverse_bind,
        stacked,
        np.concatenate(vertex_joints),
        np.concatenate(vertex_weights),
        all_triangles,
        labels,
        welded_corners(stacked, all_triangles),
        crease_zones(
            stacked,
            all_triangles,
            inverse_bind,
            joint_names,
            settings.crease_radius_m,
            settings.non_crease_prefixes,
        ),
    )


def _read_vertices(mesh_object, slot: dict[str, int]):
    """World positions (V, 3), top-4 joint slots (V, 4) and normalised weights (V, 4) of a mesh."""
    data = mesh_object.data
    count = len(data.vertices)
    flat = np.empty(count * 3)
    data.vertices.foreach_get("co", flat)
    world = np.array(mesh_object.matrix_world, dtype=float)
    points = flat.reshape(-1, 3) @ world[:3, :3].T + world[:3, 3]
    group_slot = {
        group.index: slot.get(group.name, -1) for group in mesh_object.vertex_groups
    }
    joints = np.zeros((count, MAXIMUM_INFLUENCES_PER_VERTEX), dtype=int)
    weights = np.zeros((count, MAXIMUM_INFLUENCES_PER_VERTEX))
    unweighted = []
    for vertex in data.vertices:
        entries = sorted(
            (
                (element.weight, group_slot[element.group])
                for element in vertex.groups
                if group_slot[element.group] >= 0
                and element.weight > MINIMUM_INFLUENCE_WEIGHT
            ),
            reverse=True,
        )[:MAXIMUM_INFLUENCES_PER_VERTEX]
        total = sum(weight for weight, _ in entries)
        if total <= MINIMUM_INFLUENCE_WEIGHT:
            unweighted.append(vertex.index)
            continue
        for k, (weight, joint) in enumerate(entries):
            joints[vertex.index, k] = joint
            weights[vertex.index, k] = weight / total
    if unweighted:
        raise ValueError(
            f"{len(unweighted)} vertices of {mesh_object.name!r} carry no bone "
            f"weight (first: {unweighted[:5]}); skinning would send them to "
            "the origin, so weight them before measuring motion"
        )
    return points, joints, weights


def _read_triangles(mesh_object, joints, weights, joint_names):
    """Triangle corner indices (T, 3) and `material:dominant joint` labels of a mesh."""
    data = mesh_object.data
    data.calc_loop_triangles()
    count = len(data.loop_triangles)
    corners = np.empty(count * 3, dtype=np.int32)
    data.loop_triangles.foreach_get("vertices", corners)
    corners = corners.reshape(-1, 3).astype(int)
    material = np.empty(count, dtype=np.int32)
    data.loop_triangles.foreach_get("material_index", material)
    names = []
    for slot_index in range(len(mesh_object.material_slots)):
        linked = mesh_object.material_slots[slot_index].material
        names.append(linked.name if linked is not None else NO_MATERIAL_LABEL)
    labels = []
    for start in range(0, count, LABEL_CHUNK_TRIANGLES):
        block = corners[start : start + LABEL_CHUNK_TRIANGLES]
        totals = np.zeros((len(block), len(joint_names)))
        rows = np.arange(len(block))
        for corner in range(3):
            for influence in range(MAXIMUM_INFLUENCES_PER_VERTEX):
                np.add.at(
                    totals,
                    (rows, joints[block[:, corner], influence]),
                    weights[block[:, corner], influence],
                )
        dominant = np.argmax(totals, axis=1)
        for k, joint in enumerate(dominant):
            slot_index = int(material[start + k])
            label = names[slot_index] if slot_index < len(names) else NO_MATERIAL_LABEL
            labels.append(f"{label}:{joint_names[int(joint)]}")
    return corners, labels


def read_action_clip(
    armature_object, action_name: str, skeleton: Skeleton, fps: float
) -> ActionClip:
    """The armature's active action, evaluated at every integer frame of its range, as a skinclip clip."""
    animation_data = armature_object.animation_data
    if (
        animation_data is None
        or animation_data.action is None
        or animation_data.action.name != action_name
    ):
        active = (
            animation_data.action.name
            if animation_data is not None and animation_data.action is not None
            else None
        )
        raise ValueError(
            f"action {action_name!r} is not the active action of "
            f"{armature_object.name!r} (active: {active!r}); assign it first"
        )
    action = animation_data.action
    frame_start = math.floor(action.frame_range[0])
    frame_end = math.ceil(action.frame_range[1])
    frames = np.arange(frame_start, frame_end + 1)
    curves: dict[tuple[str, str], dict[int, Any]] = {}
    keyed: list[str] = []
    for fcurve in _action_fcurves(armature_object):
        parsed = parse_pose_bone_path(fcurve.data_path)
        if parsed is None or fcurve.mute:
            continue
        if parsed.bone_name not in skeleton.names:
            raise ValueError(
                f"fcurve {fcurve.data_path!r} of action {action_name!r} names no "
                f"bone of {armature_object.name!r}"
            )
        if parsed.bone_name not in keyed:
            keyed.append(parsed.bone_name)
        if parsed.channel in _CHANNELS:
            curves.setdefault((parsed.bone_name, parsed.channel), {})[
                fcurve.array_index
            ] = fcurve
    wrong_mode = [
        name
        for name in keyed
        if armature_object.pose.bones[name].rotation_mode != QUATERNION_ROTATION_MODE
    ]
    if wrong_mode:
        raise ArmatureRotationModeError(
            f"keyed pose bones {wrong_mode} of {armature_object.name!r} are not in "
            f"{QUATERNION_ROTATION_MODE} rotation mode; their rotation would be "
            "read as zero"
        )
    times_s = (frames - frame_start) / fps
    channels: dict[str, dict[str, tuple[np.ndarray, np.ndarray, str]]] = {}
    for (bone, channel), by_index in curves.items():
        path, width, default = _CHANNELS[channel]
        basis = np.tile(np.array(default), (len(frames), 1))
        for index, fcurve in by_index.items():
            if index >= width:
                raise ValueError(
                    f"fcurve {fcurve.data_path!r}[{index}] is out of range for {channel}"
                )
            basis[:, index] = [fcurve.evaluate(float(frame)) for frame in frames]
        i = skeleton.index(bone)
        if channel == ROTATION_QUATERNION_CHANNEL:
            basis_r = basis[:, _WXYZ_TO_XYZW]
            basis_r = basis_r / np.linalg.norm(basis_r, axis=1, keepdims=True)
            values = quat.multiply(skeleton.rest_r[i], basis_r)
        elif channel == LOCATION_CHANNEL:
            values = skeleton.rest_t[i] + quat.rotate(skeleton.rest_r[i], basis)
        else:
            values = basis
        channels.setdefault(bone, {})[path] = (times_s, values, "LINEAR")
    seconds = float(times_s[-1])
    return ActionClip(
        action_name,
        int(frame_start),
        int(frame_end),
        fps,
        times_s,
        Clip(action_name, seconds, channels),
        tuple(keyed),
    )


def local_rotations(skeleton: Skeleton, action: ActionClip) -> dict[str, np.ndarray]:
    """(F, 4) local rotation keys of EVERY bone: the action's where keyed, the rest rotation elsewhere."""
    frames = action.frame_count
    out = {}
    for i, name in enumerate(skeleton.names):
        keyed = action.clip.channels.get(name, {}).get("rotation")
        out[name] = (
            keyed[1] if keyed is not None else np.tile(skeleton.rest_r[i], (frames, 1))
        )
    return out


def local_translation(
    skeleton: Skeleton, action: ActionClip, bone_name: str
) -> np.ndarray:
    """(F, 3) local translation keys of one bone: the action's where keyed, the rest translation elsewhere."""
    keyed = action.clip.channels.get(bone_name, {}).get("translation")
    if keyed is not None:
        return keyed[1]
    return np.tile(skeleton.rest_t[skeleton.index(bone_name)], (action.frame_count, 1))


def require_rotation_and_root_motion_only(
    action: ActionClip, skeleton: Skeleton, root_bone_name: str
) -> None:
    """Refuse an action whose motion the limb repair does not see: other bones' location, or any scale, off rest."""
    moving = []
    for name, paths in action.clip.channels.items():
        i = skeleton.index(name)
        translation = paths.get("translation")
        if (
            translation is not None
            and name != root_bone_name
            and np.abs(translation[1] - skeleton.rest_t[i]).max() > MOTION_TOLERANCE
        ):
            moving.append(f"{name} (location)")
        scale = paths.get("scale")
        if scale is not None and np.abs(scale[1] - 1.0).max() > MOTION_TOLERANCE:
            moving.append(f"{name} (scale)")
    if moving:
        raise ValueError(
            f"action {action.action_name!r} moves {moving}; the limb repair "
            "reads rotations and the pelvis location only, so it would "
            "repair a different motion than the one that plays"
        )


# -- writing -----------------------------------------------------------------


def _continuous(keys: np.ndarray) -> np.ndarray:
    """Quaternion keys (F, 4) with each neighbour in the previous one's hemisphere, so interpolation takes the short way."""
    out = keys.copy()
    for f in range(1, len(out)):
        if float(out[f] @ out[f - 1]) < 0.0:
            out[f] = -out[f]
    return out


def write_rotation_keys(
    armature_object,
    skeleton: Skeleton,
    frame_numbers: list[int],
    local: dict[str, np.ndarray],
) -> None:
    """Replace the `rotation_quaternion` curves of the named bones with one linear key per frame.

    ``local`` holds local rotations (F, 4, xyzw) in glTF terms; the keys
    written are the pose-bone basis ``conjugate(rest_r) (x) local_r``.
    Other curves of the action are untouched.
    """
    wrong_mode = [
        name
        for name in local
        if armature_object.pose.bones[name].rotation_mode != QUATERNION_ROTATION_MODE
    ]
    if wrong_mode:
        raise ArmatureRotationModeError(
            f"pose bones {wrong_mode} of {armature_object.name!r} are not in "
            f"{QUATERNION_ROTATION_MODE} rotation mode; keys written to them would not play"
        )
    channelbag = _action_channelbag(armature_object)
    if channelbag is None:
        raise ValueError(
            f"armature {armature_object.name!r} has no action channelbag to write keys into"
        )
    frames = np.asarray(frame_numbers, dtype=float)
    for bone, rotation in local.items():
        rest = skeleton.rest_r[skeleton.index(bone)]
        basis = _continuous(quat.multiply(quat.conjugate(rest), rotation))
        wxyz = basis[:, _XYZW_TO_WXYZ]
        path = pose_bone_path(bone, ROTATION_QUATERNION_CHANNEL)
        for stale in [fc for fc in channelbag.fcurves if fc.data_path == path]:
            channelbag.fcurves.remove(stale)
        for component in range(wxyz.shape[1]):
            fcurve = channelbag.fcurves.new(path, index=component, group_name=bone)
            fcurve.keyframe_points.add(len(frames))
            coordinates = np.empty(2 * len(frames))
            coordinates[0::2] = frames
            coordinates[1::2] = wxyz[:, component]
            fcurve.keyframe_points.foreach_set("co", coordinates)
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = KEY_INTERPOLATION
            fcurve.update()


# -- cloth chains ------------------------------------------------------------


def _garment_vertex_indices(mesh_object, material_name: str) -> np.ndarray:
    """Indices of the vertices used by faces whose material slot holds `material_name`."""
    slots = [
        index
        for index, slot in enumerate(mesh_object.material_slots)
        if slot.material is not None and slot.material.name == material_name
    ]
    if not slots:
        raise ValueError(
            f"mesh {mesh_object.name!r} has no material slot holding {material_name!r} "
            f"(slots: {[slot.material.name if slot.material else None for slot in mesh_object.material_slots]})"
        )
    data = mesh_object.data
    count = len(data.polygons)
    material = np.empty(count, dtype=np.int32)
    data.polygons.foreach_get("material_index", material)
    used: set[int] = set()
    for polygon in data.polygons:
        if int(material[polygon.index]) in slots:
            used.update(polygon.vertices)
    if not used:
        raise ValueError(
            f"no face of {mesh_object.name!r} uses material {material_name!r}"
        )
    return np.array(sorted(used))


def _garment_world_points(mesh_object, indices: np.ndarray) -> np.ndarray:
    data = mesh_object.data
    flat = np.empty(len(data.vertices) * 3)
    data.vertices.foreach_get("co", flat)
    world = np.array(mesh_object.matrix_world, dtype=float)
    return flat.reshape(-1, 3)[indices] @ world[:3, :3].T + world[:3, 3]


def _chain_bone_names(spec: RingSkirtSpec) -> list[str]:
    return [
        f"{spec.prefix}{i:02d}_{suffix}"
        for i in range(spec.count)
        for suffix in ("a", "b")
    ]


def chain_layout(
    armature_object, mesh_object, garment_material: str, spec: RingSkirtSpec
) -> cloth.RingSkirt:
    """Where the chains hang: the existing chain bones when the armature has them, else a layout on the garment."""
    if mesh_object not in bound_meshes(armature_object):
        raise ValueError(
            f"mesh {mesh_object.name!r} is not bound to armature {armature_object.name!r}"
        )
    names = _chain_bone_names(spec)
    bones = armature_object.data.bones
    present = [name for name in names if name in bones]
    garment = _garment_world_points(
        mesh_object, _garment_vertex_indices(mesh_object, garment_material)
    )
    layout = cloth.ring_skirt_layout(garment, spec, "z")
    if not present:
        return layout
    if len(present) != len(names):
        raise ValueError(
            f"armature {armature_object.name!r} has {len(present)} of the "
            f"{len(names)} chain bones {names[0]}..{names[-1]}; remove the "
            "strays or add the rest"
        )
    world = np.array(armature_object.matrix_world, dtype=float)

    def at_world(point) -> np.ndarray:
        return world[:3, :3] @ np.array(point, dtype=float) + world[:3, 3]

    chains = tuple(
        cloth.Chain(
            f"{spec.prefix}{i:02d}_a",
            f"{spec.prefix}{i:02d}_b",
            at_world(bones[f"{spec.prefix}{i:02d}_a"].head_local),
            at_world(bones[f"{spec.prefix}{i:02d}_b"].head_local),
            at_world(bones[f"{spec.prefix}{i:02d}_b"].tail_local),
        )
        for i in range(spec.count)
    )
    return cloth.RingSkirt(layout.spec, "z", chains, layout.centres)


def ensure_chain_bones(
    armature_object, anchor_bone_name: str, skirt: cloth.RingSkirt
) -> int:
    """Create the skirt's bones under the anchor when the first is missing; the count created (0 when they exist)."""
    bones = armature_object.data.bones
    if anchor_bone_name not in bones:
        raise ValueError(
            f"armature {armature_object.name!r} has no anchor bone {anchor_bone_name!r}"
        )
    if skirt.chains[0].name_a in bones:
        return 0
    to_local = linalg.inverse_affine(
        np.array(armature_object.matrix_world, dtype=float)
    )

    def local(point) -> tuple[float, float, float]:
        moved = to_local[:3, :3] @ point + to_local[:3, 3]
        return (float(moved[0]), float(moved[1]), float(moved[2]))

    specs = []
    for chain in skirt.chains:
        specs.append(
            BoneSpec(
                chain.name_a,
                local(chain.a),
                local(chain.b),
                parent_name=anchor_bone_name,
            )
        )
        specs.append(
            BoneSpec(
                chain.name_b, local(chain.b), local(chain.hem), parent_name=chain.name_a
            )
        )
    import bpy

    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    was_selected = armature_object.select_get()
    _create_edit_bones(armature_object, tuple(specs))
    armature_object.select_set(was_selected)
    view_layer.objects.active = previous_active
    return len(specs)


def weight_garment(
    armature_object, mesh_object, garment_material: str, skirt: cloth.RingSkirt
) -> int:
    """Write the chains' weights onto the garment's vertices; the count of vertices that now name a chain bone."""
    bones = {bone.name for bone in armature_object.data.bones}
    indices = _garment_vertex_indices(mesh_object, garment_material)
    points = _garment_world_points(mesh_object, indices)
    group_name = {group.index: group.name for group in mesh_object.vertex_groups}
    data = mesh_object.data
    existing = [
        {
            group_name[element.group]: element.weight
            for element in data.vertices[int(i)].groups
            if group_name[element.group] in bones
        }
        for i in indices
    ]
    updated = cloth.ring_skirt_weights(points, existing, skirt)
    chain_names = {
        name for chain in skirt.chains for name in (chain.name_a, chain.name_b)
    }
    groups = {}
    for name in chain_names:
        groups[name] = mesh_object.vertex_groups.get(
            name
        ) or mesh_object.vertex_groups.new(name=name)
    weighted = 0
    for i, before, after in zip(indices, existing, updated):
        if before == after:
            continue
        for name in before.keys() - after.keys():
            mesh_object.vertex_groups[name].remove([int(i)])
        for name, weight in after.items():
            group = groups.get(name) or mesh_object.vertex_groups[name]
            group.add([int(i)], float(weight), "REPLACE")
        if chain_names & after.keys():
            weighted += 1
    return weighted


# -- simulation and proof ----------------------------------------------------


def simulate_chains(
    figure: Figure,
    capsules_by_role: dict[str, Capsule],
    action: ActionClip,
    skirt: cloth.RingSkirt,
    loop: bool,
    ground_m: float,
) -> dict[str, np.ndarray]:
    """Local rotation keys (F, 4, xyzw) of the chain bones for the action, by bone name: skinclip's simulation over the body's capsule tracks."""
    skeleton = figure.skeleton
    worlds = pose.node_worlds(skeleton, [(action.clip, action.times_s)])
    body = positions(figure, worlds, capsules_by_role)
    tracks = {
        role: (start, end, capsules_by_role[role].radius_m)
        for role, (start, end) in body.items()
    }
    return cloth.bake(
        skeleton, worlds, rest_worlds(skeleton), skirt, tracks, loop, ground_m
    )


def posed_chain_clearance_m(
    armature_object,
    frame_numbers: list[int],
    capsules_by_role: dict[str, Capsule],
    skirt: cloth.RingSkirt,
) -> float:
    """The smallest chain-segment-to-capsule distance, less the radius, over all frames, read from the posed bones.

    Blender itself evaluates the action at each frame (``frame_set``), so
    this measures what the keys written to the action DO to the bones,
    not what the simulation intended: the rest orientation of the new
    bones, the write-back and the interpolation all sit between the two.
    """
    import bpy

    scene = bpy.context.scene
    world = np.array(armature_object.matrix_world, dtype=float)

    def to_world(point) -> np.ndarray:
        return world[:3, :3] @ np.array(point, dtype=float) + world[:3, 3]

    colliders = {
        role: capsule
        for role, capsule in capsules_by_role.items()
        if role.rpartition("_")[0] in cloth.COLLIDERS
    }
    segments = [(chain.name_a, chain.name_b) for chain in skirt.chains]
    original_frame = scene.frame_current
    worst = math.inf
    try:
        for frame in frame_numbers:
            scene.frame_set(frame)
            posed = armature_object.evaluated_get(
                bpy.context.evaluated_depsgraph_get()
            ).pose.bones
            chain_p, chain_q = [], []
            for name_a, name_b in segments:
                chain_p += [to_world(posed[name_a].head), to_world(posed[name_b].head)]
                chain_q += [to_world(posed[name_a].tail), to_world(posed[name_b].tail)]
            for capsule in colliders.values():
                start = to_world(posed[capsule.start].head)
                if capsule.end is not None:
                    end = to_world(posed[capsule.end].head)
                else:
                    rotation = (
                        world[:3, :3]
                        @ np.array(posed[capsule.start].matrix, dtype=float)[:3, :3]
                    )
                    end = rotation @ capsule.centroid_offset + start
                rows = len(chain_p)
                distance = segment_distance(
                    np.array(chain_p),
                    np.array(chain_q),
                    np.broadcast_to(start, (rows, 3)),
                    np.broadcast_to(end, (rows, 3)),
                )
                worst = min(worst, float(distance.min()) - capsule.radius_m)
    finally:
        scene.frame_set(original_frame)
    return worst
