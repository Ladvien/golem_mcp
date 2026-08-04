"""Probe: apply a real Mixamo clip to a canonical rig by name, and render it.

    apply_mixamo_probe.py <character.glb> <clip.fbx> <out.png>

A DIAGNOSTIC, not the shipping path. It answered the question Phase 3 rested on -
whether a Mixamo clip can be applied directly once bone names and hierarchy match.

Result on forge_mixamo.glb + "mutant walking.fbx": all 23 of our bones matched the
clip's channels (only fingers and Toe_End unmatched, which we omit by design), and
the character still came out collapsed on its side. Matching names and hierarchy
is NOT sufficient - a Mixamo clip keys local rotations relative to Mixamo's rest
pose and bone rolls, while ours take their orientation from TokenRig joint
positions. Shipping apply_animation therefore needs a real retarget: conjugate
each local rotation by the rest-orientation delta, or drive our bones from the
source armature with world-space Copy Rotation constraints and bake.

Two traps this probe also surfaced, both worth keeping:

  * Blender 4.4+ slotted actions - assigning animation_data.action evaluates
    NOTHING unless action_slot is bound too. Every bone sits at its rest
    quaternion, which is indistinguishable from a broken rig.
  * Mixamo FBX keys location in CENTIMETRES. On a 1 m character that is a 100x
    root translation (measured: mean vertex motion of 105 units) and the
    character leaves the scene. Rotations are the animation; drop location/scale
    for an in-place clip, or scale root motion by the height ratio.
"""
import sys

sys.path.insert(0, "/home/ladvien/segvigen/repo/data_toolkit")

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from bpy_render import BpyRenderer  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

char, clip, out = sys.argv[1], sys.argv[2], sys.argv[3]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=char)
tgt = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
tgt_bones = {b.name for b in tgt.data.bones}

before = set(bpy.data.actions)
bpy.ops.import_scene.fbx(filepath=clip)
act = [a for a in bpy.data.actions if a not in before]
if not act:
    raise SystemExit("no action imported from clip")
act = act[0]

# Which of the clip's channels land on bones we actually have?
chan = set()
for fc in act.fcurves:
    if 'pose.bones["' in fc.data_path:
        chan.add(fc.data_path.split('"')[1])
hit = chan & tgt_bones
print(f"clip channels: {len(chan)} bones | our skeleton: {len(tgt_bones)} | matched: {len(hit)}")
print(f"unmatched clip bones: {sorted(chan - tgt_bones)[:8]}")

# Mixamo FBX keys location in CENTIMETRES. Applied to a 1 m character that is a
# 100x root translation - measured mean vertex motion of 105 units, i.e. the
# character leaves the scene. Rotations ARE the animation; drop location and scale
# for an in-place clip.
drop = [fc for fc in act.fcurves if fc.data_path.endswith(("location", "scale"))]
for fc in drop:
    act.fcurves.remove(fc)
print(f"dropped {len(drop)} location/scale channels, kept {len(act.fcurves)} rotation channels")

if tgt.animation_data is None:
    tgt.animation_data_create()
tgt.animation_data.action = act
# Blender 4.4+ slotted actions: assigning the action alone evaluates NOTHING.
# The slot must be bound or every bone stays at its rest quaternion, which looks
# exactly like a broken rig.
if hasattr(tgt.animation_data, "action_slot") and getattr(act, "slots", None):
    tgt.animation_data.action_slot = act.slots[0]
rng = act.frame_range
print(f"frame range: {rng[0]:.0f}-{rng[1]:.0f}")

# Measure motion, then render three frames.
r = BpyRenderer(resolution=420, engine="CYCLES")
r.init_render_settings()
r.normalize_scene()
cam = r.init_camera()
r.init_lighting()
cam.data.lens = 16 / np.tan(0.6981317 / 2)
cam.location = (2.1, 0.0, 0.30)   # orbit about Z; TRACK_TO aims it at the origin
bpy.context.scene.cycles.samples = 20

frames, imgs = [int(rng[0]), int((rng[0]+rng[1])/2), int(rng[1])], []
prev = None
for f in frames:
    bpy.context.scene.frame_set(f)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    v = np.array([x.co[:] for x in mesh.evaluated_get(dg).to_mesh().vertices])
    if prev is not None:
        print(f"  frame {f}: mean vertex motion vs prev = {np.linalg.norm(v-prev,axis=1).mean():.4f}")
    prev = v
    p = f"/tmp/_mx_{f}.png"
    bpy.context.scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    imgs.append((f, Image.open(p).convert("RGB")))

w, h = imgs[0][1].size
sheet = Image.new("RGB", (w*len(imgs), h+20), "white")
for i, (f, im) in enumerate(imgs):
    sheet.paste(im, (i*w, 0))
    ImageDraw.Draw(sheet).text((i*w+8, h+5), f"frame {f}", fill="black")
sheet.save(out)
print("MIXAMO_APPLY_OK", out)
