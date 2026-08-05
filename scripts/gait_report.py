"""Measure a retargeted walk, and render frames to actually look at.

    gait_report.py -- animated.glb out_prefix

Frame convention matches retarget_animation.py:body_frame - up from Hips->Spine2,
forward from the TOES (not a hip-axis cross product, which disagrees with anatomy
on every standard rig), lateral = up x forward.

WHY MORE THAN ONE NUMBER
------------------------
Because the correlation alone has already passed a real defect. `norm()`
mean-centres both series before correlating, so a character walking with its hands
parked permanently BEHIND its body still scores -0.96 - which is what happened,
and it took someone looking at a viewport to catch. The mean offset is the term
that sees it.

  lat      rest laterality of the left arm. Mixamo and UE5 clips both sit at +1.00,
           and a mirrored rig is not a rotation, so no retarget can fix it.
  gait     corr(left hand fwd, left foot fwd). NEGATIVE = contralateral = correct.
  offset   mean hand position along forward, % of leg length. Source walk: +19.2.
  swing    peak-to-peak of the same. Source walk: 74.4. Ours runs ~75% of source -
           a known, unexplained damping.

TWO MEASUREMENT BUGS WORTH NOT REPEATING
----------------------------------------
  * Sample the ACTION's frame_range, not the scene's. Blender defaults a scene to
    1-250; a 44-frame clip then contributes 206 frames of held final pose that
    quietly dominate every mean.
  * Angles from acos(dot) are UNSIGNED. A head tilted 15 degrees forward and one
    tilted 15 degrees back read identically - enough to make a correct rig look
    broken, or the reverse.
"""
import sys, json, math
import bpy
from mathutils import Vector

glb, out_prefix = sys.argv[-2], sys.argv[-1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene
for o in list(scene.objects):
    if any(c.name.startswith("glTF_not_exported") for c in o.users_collection):
        bpy.data.objects.remove(o, do_unlink=True)

arm = next(o for o in scene.objects if o.type == "ARMATURE")
meshes = [o for o in scene.objects if o.type == "MESH"]


def rest(n):
    return arm.matrix_world @ arm.pose.bones[n].bone.matrix_local.translation


up = (rest("mixamorig:Spine2") - rest("mixamorig:Hips")).normalized()
fwd = ((rest("mixamorig:LeftToeBase") - rest("mixamorig:LeftFoot"))
       + (rest("mixamorig:RightToeBase") - rest("mixamorig:RightFoot")))
fwd = (fwd - fwd.dot(up) * up).normalized()
lat = up.cross(fwd).normalized()

leg = (rest("mixamorig:LeftUpLeg") - rest("mixamorig:LeftFoot")).length

# Rest laterality of the left arm: does it extend to +lat like every clip's does?
arm_dir = (rest("mixamorig:LeftHand") - rest("mixamorig:LeftShoulder")).normalized()
lat_rest = arm_dir.dot(lat)

hands, feet = [], []
# The ACTION's range, not the scene's. Blender defaults the scene to 1-250; this
# clip is 44 frames, so 206 of them would just hold the final pose and quietly
# dominate every mean.
act = arm.animation_data.action
f0, f1 = (int(round(x)) for x in act.frame_range)
for f in range(f0, f1 + 1):
    scene.frame_set(f)
    hips = arm.matrix_world @ arm.pose.bones["mixamorig:Hips"].head
    h = arm.matrix_world @ arm.pose.bones["mixamorig:LeftHand"].head
    ft = arm.matrix_world @ arm.pose.bones["mixamorig:LeftFoot"].head
    hands.append((h - hips).dot(fwd) / leg * 100.0)
    feet.append((ft - hips).dot(fwd) / leg * 100.0)


def corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da = [x - ma for x in a]; db = [x - mb for x in b]
    na = math.sqrt(sum(x * x for x in da)); nb = math.sqrt(sum(x * x for x in db))
    return sum(x * y for x, y in zip(da, db)) / (na * nb) if na and nb else 0.0


report = {
    "glb": glb, "frames": f1 - f0 + 1,
    "rest_arm_laterality": round(lat_rest, 3),
    "gait_corr_lhand_lfoot": round(corr(hands, feet), 3),
    "hand_mean_offset_pct_leg": round(sum(hands) / len(hands), 1),
    "hand_swing_pct_leg": round(max(hands) - min(hands), 1),
    "foot_swing_pct_leg": round(max(feet) - min(feet), 1),
}
print("GAIT " + json.dumps(report))

# --- render, because every defect this session was found by looking ---
bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
bpy.ops.object.select_all(action="SELECT")
lo = Vector((min(v.x for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box]),
             min(v.y for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box]),
             min(v.z for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box])))
hi = Vector((max(v.x for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box]),
             max(v.y for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box]),
             max(v.z for o in meshes for v in [o.matrix_world @ Vector(c) for c in o.bound_box])))
centre = (lo + hi) / 2
height = (hi - lo).z or 1.0

scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = scene.render.resolution_y = 512
scene.render.film_transparent = False
world = bpy.data.worlds.new("w"); scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[1].default_value = 1.6

cam_data = bpy.data.cameras.new("cam"); cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam); scene.camera = cam
sun_d = bpy.data.lights.new("sun", type="SUN"); sun_d.energy = 4.0
sun = bpy.data.objects.new("sun", sun_d); scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), 0, math.radians(35))

# Front = looking along +forward at the character; side = along +lat.
views = {"front": -fwd, "side": lat}
phases = [f0 + round((f1 - f0) * t) for t in (0.0, 0.25, 0.5, 0.75)]
dist = height * 2.1
for vname, direction in views.items():
    cam.location = centre - direction * dist + up * (height * 0.06)
    look = (centre - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat("-Z", "Y").to_euler()
    for i, f in enumerate(phases):
        scene.frame_set(f)
        scene.render.filepath = f"{out_prefix}_{vname}_{i}.png"
        bpy.ops.render.render(write_still=True)
print("RENDER_OK")
