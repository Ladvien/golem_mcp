#!/usr/bin/env python
"""Retarget an animation clip onto a canonically-rigged character.

    retarget_animation.py --character rigged.glb --clip walk.fbx --out walking.glb
    retarget_animation.py --character rigged.glb --clip walk.bvh --out walking.glb   # Kimodo (SOMA)

WHY A RETARGET AND NOT A DIRECT APPLICATION
-------------------------------------------
Matching bone names is necessary but not sufficient, and this was measured rather
than assumed. Applying `mutant walking.fbx` straight onto `forge_mixamo.glb`
matched all 23 of our bones to the clip's channels - and produced a character
collapsed on its side. A clip keys LOCAL rotations relative to ITS OWN rest pose
and bone rolls; our bones take their orientation from TokenRig joint positions.

So each bone is driven by the source's rest-relative DELTA rather than its raw
local rotation:

    delta        = src_posed_world_rot * src_rest_world_rot^-1
    target_world = delta * rest_correction * tgt_rest_world_rot

The delta alone is only right when the two rest poses agree. A clip is authored on
a T-pose and a generated character rests in an A-pose (arms ~29 degrees below
horizontal), so the clip's "arm down by the side" carried the A-pose arm 29 degrees
past vertical and across the body: the hands swapped sides. `rest_correction` turns
each target limb onto the clip's rest direction first (see rest_corrections), which
is what makes one clip library drive characters this pipeline generated.

WHY A NAME MAP
--------------
A retarget is required regardless, and once rest poses are being reconciled a
name map costs almost nothing more. That turns the canonical skeleton choice from
load-bearing into a table entry, and it unlocks every library on disk rather than
the one that happens to share our naming:

    game_assets/animation/  Quaternius UAL v1+v2, 86 clips, UE5 Mannequin names,
                            CC0 public domain, shipped with and without root motion
    game_assets/SCP-610/    20 Mixamo clips, mixamorig: names

TWO TRAPS, BOTH MEASURED
------------------------
  * Blender 4.4+ slotted actions: assigning `animation_data.action` evaluates
    NOTHING unless `action_slot` is bound as well. Every bone sits at its rest
    quaternion, which looks exactly like a broken rig.
  * Mixamo FBX keys location in CENTIMETRES. On a 1 m character that is a 100x
    root translation - measured mean vertex motion of 105 units, character gone
    from the scene. Root motion is therefore scaled by the hips-height ratio (the target's rest hips height above its
    toes over the source's, in each rig's own units), and off by default.
  * Root motion is turned by the YAW part of the body-frame alignment only. The alignment between the clip's body frame
    and ours also holds a pitch and roll (the SOMA skeleton's rest leans about 9 degrees about X from the mannequin's);
    turning hip translation by all of it leaked forward travel into height, so a walker sank 1 m in 8 s. Rotations keep
    the full alignment: it conjugates them correctly.
"""

import argparse
import json
import math
import sys
from pathlib import Path

# Source convention -> our canonical core. Values are our Mixamo names; keys are
# what the clip calls them. Only the core is mapped: extra chains (wings, tail,
# horns) are deliberately left undriven so a standard clip cannot flail them.
UE5_TO_CANON = {
    "pelvis": "mixamorig:Hips",
    "spine_01": "mixamorig:Spine", "spine_02": "mixamorig:Spine1",
    "spine_03": "mixamorig:Spine2", "neck_01": "mixamorig:Neck", "Head": "mixamorig:Head",
    "clavicle_l": "mixamorig:LeftShoulder", "upperarm_l": "mixamorig:LeftArm",
    "lowerarm_l": "mixamorig:LeftForeArm", "hand_l": "mixamorig:LeftHand",
    "clavicle_r": "mixamorig:RightShoulder", "upperarm_r": "mixamorig:RightArm",
    "lowerarm_r": "mixamorig:RightForeArm", "hand_r": "mixamorig:RightHand",
    "thigh_l": "mixamorig:LeftUpLeg", "calf_l": "mixamorig:LeftLeg",
    "foot_l": "mixamorig:LeftFoot", "ball_l": "mixamorig:LeftToeBase",
    "thigh_r": "mixamorig:RightUpLeg", "calf_r": "mixamorig:RightLeg",
    "foot_r": "mixamorig:RightFoot", "ball_r": "mixamorig:RightToeBase",
}
MIXAMO_TO_CANON = {n: n for n in set(UE5_TO_CANON.values())}
# Kimodo's SOMA skeleton (somaskel77). Trap: SOMA `LeftLeg` is the THIGH and
# `LeftShin` the shin, so a prefix-only map would bend the knee from the hip.
# Neck2 and the fingers have no canonical counterpart and stay unmapped; world-space
# deltas fold Neck2's rotation into Head, so nothing is lost.
SOMA_TO_CANON = {
    "Hips": "mixamorig:Hips",
    "Spine1": "mixamorig:Spine", "Spine2": "mixamorig:Spine1", "Chest": "mixamorig:Spine2",
    "Neck1": "mixamorig:Neck", "Head": "mixamorig:Head",
    "LeftShoulder": "mixamorig:LeftShoulder", "LeftArm": "mixamorig:LeftArm",
    "LeftForeArm": "mixamorig:LeftForeArm", "LeftHand": "mixamorig:LeftHand",
    "RightShoulder": "mixamorig:RightShoulder", "RightArm": "mixamorig:RightArm",
    "RightForeArm": "mixamorig:RightForeArm", "RightHand": "mixamorig:RightHand",
    "LeftLeg": "mixamorig:LeftUpLeg", "LeftShin": "mixamorig:LeftLeg",
    "LeftFoot": "mixamorig:LeftFoot", "LeftToeBase": "mixamorig:LeftToeBase",
    "RightLeg": "mixamorig:RightUpLeg", "RightShin": "mixamorig:RightLeg",
    "RightFoot": "mixamorig:RightFoot", "RightToeBase": "mixamorig:RightToeBase",
}
BVH_CENTIMETRES_TO_METRES = 0.01   # Kimodo writes BVH in centimetres
MAPS = {"ue5": UE5_TO_CANON, "mixamo": MIXAMO_TO_CANON, "soma": SOMA_TO_CANON}


def pick_map(source_bones, requested="auto"):
    """Choose the name map with the most hits against the clip's own bones."""
    if requested != "auto":
        return requested, MAPS[requested]
    scored = [(sum(1 for k in m if k in source_bones), name) for name, m in MAPS.items()]
    hits, name = max(scored)
    if hits < 6:
        raise SystemExit(
            f"no source convention matches this clip (best {hits} bones). "
            f"Its bones look like: {sorted(source_bones)[:8]}. Add a map to MAPS."
        )
    return name, MAPS[name]


def body_frame(arm, canon_to_own):
    """Orthonormal frame built from the rig's own rest pose: lateral, up, forward.

    Characters do not all face the same way in world space. Measured on two of
    ours - female_base_v5 carries its arms along Z (hands at +/-0.734, mesh only
    +/-0.17 wide in X) while forge_warden carries them along X. They are yawed 90
    degrees apart.

    That matters because a clip's delta is a WORLD rotation. Applied raw to a rig
    yawed against the clip's own convention, a Mixamo arm swing arrives as an arm
    raise - which is exactly what female_base_v5 did. Conjugating the delta by the
    rotation between the two body frames puts it back in the right plane.
    """
    from mathutils import Matrix, Vector

    # Keyed by CANONICAL name and resolved through the map, because the clip's rig
    # speaks its own convention - a UE5 Mannequin has pelvis and thigh_l, not
    # mixamorig:Hips and mixamorig:LeftUpLeg.
    need = ("mixamorig:Hips", "mixamorig:Spine2",
            "mixamorig:LeftFoot", "mixamorig:RightFoot",
            "mixamorig:LeftToeBase", "mixamorig:RightToeBase")
    missing = [n for n in need if n not in canon_to_own]
    if missing:
        raise SystemExit(
            f"cannot build a body frame for {arm.name}: no mapping for {missing}. "
            "The spine gives up and the feet give forward; a clip missing either "
            "cannot be aligned."
        )

    def rest(n):
        return arm.pose.bones[canon_to_own[n]].bone.matrix_local.translation
    # Forward comes from the TOES, not from a hip-axis cross product. Measured, the
    # cross-product convention disagrees with anatomy on every standard rig:
    #
    #     Mixamo clip rig        lat x up . toe-fwd = -1.00
    #     UE5 Mannequin rig      lat x up . toe-fwd = -1.00
    #     our fitted rigs        lat x up . toe-fwd = +1.00
    #
    # so the alignment baked in a 180 degree yaw and the character moonwalked -
    # planted foot travelling FORWARD through the stance phase. forge_warden only
    # looked right because its sides were mirrored and the two errors cancelled.
    #
    # Anchoring on the feet makes the frame anatomical on both sides, so no
    # handedness convention has to agree with anything.
    up = (rest("mixamorig:Spine2") - rest("mixamorig:Hips")).normalized()
    fwd = ((rest("mixamorig:LeftToeBase") - rest("mixamorig:LeftFoot"))
           + (rest("mixamorig:RightToeBase") - rest("mixamorig:RightFoot")))
    fwd = (fwd - up * fwd.dot(up)).normalized()
    lat = up.cross(fwd)
    return Matrix((Vector((lat.x, up.x, fwd.x)),
                   Vector((lat.y, up.y, fwd.y)),
                   Vector((lat.z, up.z, fwd.z))))


def hierarchy_order(arm, names):
    """Parents before children - `pose_bone.matrix` assignment is order-sensitive."""
    depth = {}
    for n in names:
        d, b = 0, arm.data.bones[n]
        while b.parent:
            d, b = d + 1, b.parent
        depth[n] = d
    return sorted(names, key=lambda n: depth[n])


# Limb segments whose rest direction is matched between the clip's rig and ours, each as (bone, child bone).
REST_CHAINS = (
    ("mixamorig:LeftArm", "mixamorig:LeftForeArm"), ("mixamorig:LeftForeArm", "mixamorig:LeftHand"),
    ("mixamorig:RightArm", "mixamorig:RightForeArm"), ("mixamorig:RightForeArm", "mixamorig:RightHand"),
    ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg"), ("mixamorig:LeftLeg", "mixamorig:LeftFoot"),
    ("mixamorig:RightUpLeg", "mixamorig:RightLeg"), ("mixamorig:RightLeg", "mixamorig:RightFoot"),
)


def rest_corrections(src, tgt, by_target, align_q):
    """Per target bone, the rotation that turns the target's rest limb onto the clip's rest limb.

    A delta is posed*rest^-1 on the clip's rig. Applied to a target whose rest differs (an A-pose character
    against a T-pose clip), every pose lands off by the rest difference: the clip's "arms down" carried a
    29-degree A-pose arm past vertical and across the body. Directions are head -> child head, never bone
    tails, which FBX and BVH imports guess.
    """
    corr = {}
    for t, child in REST_CHAINS:
        if t not in by_target or child not in by_target:
            continue
        tgt_dir = tgt.data.bones[child].head_local - tgt.data.bones[t].head_local
        src_dir = align_q @ (src.data.bones[by_target[child]].head_local - src.data.bones[by_target[t]].head_local)
        if tgt_dir.length < 1e-6 or src_dir.length < 1e-6:
            continue
        corr[t] = tgt_dir.normalized().rotation_difference(src_dir.normalized())
    return corr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--character", required=True, help="canonically rigged .glb")
    ap.add_argument("--clip", required=True, help=".fbx, .glb/.gltf or .bvh carrying the animation")
    ap.add_argument("--out", required=True)
    ap.add_argument("--action", default="",
                    help="which action, when a file bundles several (Quaternius UAL ships one "
                         "fbx per engine holding every clip). See --list-clips.")
    ap.add_argument("--source-map", default="auto", choices=["auto", *MAPS])
    ap.add_argument("--root-motion", action="store_true",
                    help="carry hip translation, scaled by the hips-height ratio and turned by the yaw part of the "
                         "body-frame alignment only (default: in place)")
    ap.add_argument("--hip-bob", action="store_true",
                    help="in place, but keep the pelvis's vertical motion; ignored with --root-motion")
    ap.add_argument("--list-clips", action="store_true", help="print the file's actions and exit")
    ap.add_argument("--report", help="write the JSON result here; Blender's own chatter makes "
                                     "stdout unsafe to parse")
    args = ap.parse_args()

    import bpy
    from mathutils import Matrix, Quaternion, Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.character)
    tgt = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
    if tgt is None:
        raise SystemExit(f"{args.character} has no armature - it is not a rigged character")
    # The FBX importer builds action names as "{armature_name}|{take}". Our
    # characters ship an armature literally called "Armature", so importing a clip
    # afterwards renames ITS armature to "Armature.001" and every action name shifts
    # with it - "Armature|mixamo.com|Layer0" becomes "Armature.001|mixamo.com|Layer0"
    # and no name the caller was given can match. Freeing the name first keeps the
    # clip's own names exactly as animation_library.py catalogued them.
    tgt.name = "TargetRig"
    tgt.data.name = "TargetRigData"
    tgt_bones = {b.name for b in tgt.data.bones}
    mesh = next(o for o in bpy.context.scene.objects if o.type == "MESH")

    before_obj = set(bpy.context.scene.objects)
    before_act = set(bpy.data.actions)
    suffix = Path(args.clip).suffix.lower()
    if suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=args.clip)
    elif suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=args.clip)
    elif suffix == ".bvh":
        bpy.ops.import_anim.bvh(filepath=args.clip, global_scale=BVH_CENTIMETRES_TO_METRES,
                                update_scene_fps=True, update_scene_duration=True)
    else:
        raise SystemExit(f"unsupported clip type {suffix!r}: expected .fbx, .glb, .gltf or .bvh")
    src = next(o for o in bpy.context.scene.objects
               if o.type == "ARMATURE" and o not in before_obj)
    actions = [a for a in bpy.data.actions if a not in before_act]
    if args.list_clips:
        print(json.dumps({"clip": args.clip, "actions": [a.name for a in actions]}, indent=2))
        return 0
    if not actions:
        raise SystemExit(f"{args.clip} contains no animation")
    if args.action:
        act = next((a for a in actions if a.name == args.action), None)
        if act is None:
            raise SystemExit(
                f"{args.clip} has no action named {args.action!r}. It has: "
                + ", ".join(sorted(a.name for a in actions))
            )
    elif len(actions) == 1:
        act = actions[0]
    else:
        raise SystemExit(
            f"{args.clip} bundles {len(actions)} actions - pass --action NAME to choose one: "
            + ", ".join(sorted(a.name for a in actions)[:12])
            + (" ..." if len(actions) > 12 else "")
        )

    if src.animation_data is None:
        src.animation_data_create()
    src.animation_data.action = act
    # Blender 4.4+ slotted actions: without this every bone stays at rest.
    if hasattr(src.animation_data, "action_slot") and getattr(act, "slots", None):
        src.animation_data.action_slot = act.slots[0]

    src_bones = {b.name for b in src.data.bones}
    map_name, name_map = pick_map(src_bones, args.source_map)
    pairs = [(s, t) for s, t in name_map.items() if s in src_bones and t in tgt_bones]
    if len(pairs) < 6:
        raise SystemExit(f"only {len(pairs)} bones map between clip and character; too few to retarget")
    order = hierarchy_order(tgt, [t for _s, t in pairs])
    by_target = {t: s for s, t in pairs}

    # Rest orientations in ARMATURE space, not world. Including matrix_world does
    # not cancel in the delta - it CONJUGATES it:
    #     (M*posed)*(M*rest)^-1 = Q_M * (posed*rest^-1) * Q_M^-1
    # and a Mixamo FBX imports with a -90 deg X rotation on its armature object,
    # which showed up as the retargeted character lying on its side.
    src_rest = {s: src.pose.bones[s].bone.matrix_local.to_quaternion() for s, _t in pairs}
    tgt_rest = {t: tgt.pose.bones[t].bone.matrix_local.to_quaternion() for _s, t in pairs}

    # Rotation taking the clip's body frame onto ours. Identity when the two rigs
    # already face the same way, which is why forge_warden retargeted correctly
    # while female_base_v5 did not.
    tgt_frame = body_frame(tgt, {t: t for _s, t in pairs})
    src_frame = body_frame(src, by_target)
    align = tgt_frame @ src_frame.inverted()
    align_q = align.to_quaternion()
    align_inv = align_q.inverted()

    # Rest-pose difference per limb, so a T-pose clip drives an A-pose character. A bone without its own entry
    # (a hand, a foot) inherits its nearest corrected ancestor's, so it follows its forearm or shin rigidly.
    corr = rest_corrections(src, tgt, by_target, align_q)
    corr_all = {}
    for _s, t in pairs:
        b = tgt.data.bones[t]
        while b is not None and b.name not in corr:
            b = b.parent
        corr_all[t] = corr[b.name] if b is not None else Quaternion((1.0, 0.0, 0.0, 0.0))

    # Root motion is turned by the alignment's YAW (its twist about armature Z) only, and scaled by the ratio of the
    # two rigs' rest hips heights. A hips height is measured above the toes along the rig's own up, never from the
    # armature origin: a generated character is centred on its origin (hips at z -0.06, toes at -0.49), so the
    # origin-based height made the ratio 0.07 instead of 0.48 and shrank its root motion and bob fourteenfold.
    yaw_q = Quaternion((align_q.w, 0.0, 0.0, align_q.z))
    align_yaw = (yaw_q.normalized() if yaw_q.magnitude > 1e-9 else Quaternion((1.0, 0.0, 0.0, 0.0))).to_matrix()

    hips = "mixamorig:Hips"
    root_src = by_target.get(hips)
    src_hips_rest = src.pose.bones[root_src].bone.matrix_local.translation if root_src else None
    # The offset is applied to the REST head, not to the pose's current translation: the pose keeps
    # the previous frame's location, so adding to it accumulated the displacement every frame.
    tgt_hips_rest = tgt.pose.bones[hips].bone.matrix_local.translation.copy() if hips in tgt_bones else None

    def hips_height(arm, canon_to_own, up) -> float:
        def head(n):
            return arm.data.bones[canon_to_own[n]].head_local
        toes = (head("mixamorig:LeftToeBase") + head("mixamorig:RightToeBase")) / 2
        return (head(hips) - toes).dot(up)

    height_ratio = 1.0
    if (args.root_motion or args.hip_bob) and src_hips_rest is not None and tgt_hips_rest is not None:
        src_height = hips_height(src, by_target, src_frame.col[1].normalized())
        tgt_height = hips_height(tgt, {t: t for _s, t in pairs}, tgt_frame.col[1].normalized())
        if src_height > 1e-6 and tgt_height > 1e-6:
            height_ratio = tgt_height / src_height

    for pb in tgt.pose.bones:
        pb.rotation_mode = "QUATERNION"
    if tgt.animation_data is None:
        tgt.animation_data_create()
    new_act = bpy.data.actions.new(name=f"retargeted_{Path(args.clip).stem}")
    tgt.animation_data.action = new_act
    if hasattr(tgt.animation_data, "action_slot") and getattr(new_act, "slots", None):
        tgt.animation_data.action_slot = new_act.slots[0]

    source_action_name = act.name       # captured before the stale actions are freed
    start, end = (int(round(v)) for v in act.frame_range)
    # In place with the bob: only the pelvis's travel along the WORLD vertical survives, read in each rig's own
    # armature space. Neither the body frames nor their alignment may carry it: their up is the spine's, which leans,
    # so a clip that walks forward (Kimodo's BVH keeps its root travel) leaked that travel into height and the walker
    # sank 9 cm in 84 frames through a 2.6-degree alignment.
    bob = args.hip_bob and not args.root_motion and src_hips_rest is not None and tgt_hips_rest is not None
    world_up = Vector((0.0, 0.0, 1.0))
    up_s = src.matrix_world.to_quaternion().inverted() @ world_up
    up_t = tgt.matrix_world.to_quaternion().inverted() @ world_up

    # The floor. A clip's pelvis height is right for the clip's legs, not ours: with the limbs turned onto the clip's
    # rest, a splayed A-stance leg stands straighter and reaches lower, and the walk on a generated villager put its
    # soles 2.9 cm under the floor with the pelvis held at rest and 5.2 cm with the clip's bob. Whenever the pelvis is
    # keyed, it is lifted on any frame where the sole would go below its rest height. The sole is the character's own
    # skin - the lower half of each foot, every vertex carried rigidly by the foot bone that weighs it most - because
    # the toe joints and a heel point under the ankle missed the foot's roll by 2 cm. Lifting only: a jump keeps its
    # air.
    foot_bones = {n for side in ("Left", "Right")
                  for n in (f"mixamorig:{side}Foot", f"mixamorig:{side}ToeBase", f"mixamorig:{side}Toe_End")
                  if n in tgt.data.bones}
    to_arm = tgt.matrix_world.inverted()
    skin = []
    for ob in [o for o in bpy.context.scene.objects if o.type == "MESH" and o.find_armature() is tgt]:
        groups = {g.index: g.name for g in ob.vertex_groups if g.name in foot_bones}
        m = to_arm @ ob.matrix_world
        for v in ob.data.vertices:
            best = max(((g.weight, groups[g.group]) for g in v.groups if g.group in groups), default=None)
            if best is not None and best[0] >= 0.5:
                skin.append((best[1], m @ v.co))
    floor = min((p.dot(up_t) for _b, p in skin), default=None)
    soles = []
    if floor is not None:
        ankle = max((tgt.data.bones[n].head_local.dot(up_t) for n in foot_bones if n.endswith("Foot")), default=floor)
        band = floor + 0.5 * (ankle - floor)
        low = [(b, p) for b, p in skin if p.dot(up_t) <= band]
        stride = max(1, len(low) // 4000)
        soles = [(b, tgt.data.bones[b].matrix_local.inverted() @ p) for b, p in low[::stride]]
    ground = (args.root_motion or bob) and bool(soles) and hips in tgt_bones
    lifts = []

    def lowest_sole() -> float:
        return min((tgt.pose.bones[b].matrix @ p).dot(up_t) for b, p in soles)

    for frame in range(start, end + 1):
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for t in order:
            s = by_target[t]
            spb, tpb = src.pose.bones[s], tgt.pose.bones[t]
            delta = spb.matrix.to_quaternion() @ src_rest[s].inverted()
            delta = align_q @ delta @ align_inv          # into our body frame
            want = delta @ corr_all[t] @ tgt_rest[t]
            cur = tpb.matrix.copy()
            loc = cur.translation.copy()
            if args.root_motion and t == hips and src_hips_rest is not None:
                off = align_yaw @ (spb.matrix.translation - src_hips_rest)
                loc = tgt_hips_rest + off * height_ratio
            elif bob and t == hips:
                rise = (spb.matrix.translation - src_hips_rest).dot(up_s)
                loc = tgt_hips_rest + up_t * (rise * height_ratio)
            tpb.matrix = Matrix.LocRotScale(loc, want, cur.to_scale())
            bpy.context.view_layer.update()
        if ground:
            sink = floor - lowest_sole()
            lifts.append(max(sink, 0.0))
            if sink > 0.0:
                hpb = tgt.pose.bones[hips]
                m = hpb.matrix.copy()
                hpb.matrix = Matrix.LocRotScale(m.translation + up_t * sink, m.to_quaternion(), m.to_scale())
                bpy.context.view_layer.update()
        for t in order:
            tgt.pose.bones[t].keyframe_insert("rotation_quaternion", frame=frame)
        if args.root_motion or bob:
            tgt.pose.bones[hips].keyframe_insert("location", frame=frame)

    # Hands crossing the body's midline: the visible symptom of a rest-pose mismatch. Left bones sit at +lat.
    lat = tgt_frame.col[0]
    crossed_hand_frames, min_hand_sep_pct = None, None
    side_bones = ("mixamorig:LeftHand", "mixamorig:RightHand", "mixamorig:LeftUpLeg", "mixamorig:RightUpLeg")
    if all(n in tgt.pose.bones for n in side_bones):
        hip_w = (tgt.data.bones["mixamorig:LeftUpLeg"].head_local
                 - tgt.data.bones["mixamorig:RightUpLeg"].head_local).dot(lat)
        if abs(hip_w) >= 1e-6:
            seps = []
            for frame in range(start, end + 1):
                bpy.context.scene.frame_set(frame)
                seps.append((tgt.pose.bones["mixamorig:LeftHand"].head
                             - tgt.pose.bones["mixamorig:RightHand"].head).dot(lat))
            crossed_hand_frames = sum(1 for sep in seps if sep <= 0)
            min_hand_sep_pct = round(100 * min(seps) / hip_w, 1)

    # Drop EVERYTHING the clip import brought in, plus its action. Removing only
    # the armature object left the source character's MESH in the scene - the
    # Quaternius packs ship the UE5 Mannequin alongside the animation, so the
    # output GLB contained a full second character standing next to ours. The
    # Mixamo FBXs carry no mesh, which is why this only appeared on the glb
    # libraries. Removing only the object (not the action) ships the raw clip too,
    # where it is picked up ahead of the retargeted one, carrying the source's
    # centimetre root translation.
    for obj in [o for o in bpy.context.scene.objects if o not in before_obj]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for stale in [a for a in bpy.data.actions if a is not new_act]:
        bpy.data.actions.remove(stale)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=args.out, export_format="GLB", export_animations=True)

    report = {
        "character": args.character, "clip": args.clip, "out": args.out,
        "action": source_action_name, "source_convention": map_name,
        "bones_mapped": len(pairs), "frames": end - start + 1,
        "frame_alignment_deg": round(align_q.angle * 57.29578, 1),
        "root_motion": args.root_motion, "hip_bob": bool(bob), "height_ratio": round(height_ratio, 4),
        "root_alignment": "yaw", "height_ratio_basis": "hips_above_toes",
        "unmapped_target_bones": sorted(tgt_bones - {t for _s, t in pairs}),
        "rest_correction_deg": {t: round(math.degrees(q.angle), 1) for t, q in corr.items()},
        "crossed_hand_frames": crossed_hand_frames,
        "min_hand_separation_pct_hip_width": min_hand_sep_pct,
        "grounded": bool(ground),
        "floor_lift_max": round(max(lifts), 4) if lifts else None,
        "floor_lifted_frames": sum(1 for v in lifts if v > 1e-4) if lifts else None,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"RETARGET_OK {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
