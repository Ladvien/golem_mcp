#!/usr/bin/env python
"""Zoomed renders of named body regions, for looking at what metrics cannot see.

    inspect_render.py --glb rigged.glb --out-prefix /tmp/look --regions head,hands,hip,feet
    inspect_render.py --glb walk.glb --regions head --frame 12 --views front,side

WHY THIS EXISTS
---------------
Every serious defect in this project was found by looking, and nearly every one
was nearly MISSED because the looking was done at 512 px on a whole character.
At that size a head is about 40 pixels: it reads as a blank mask whether it is
beautifully textured or genuinely broken, and "the face is a blank mask" was
written into a commit here on exactly that non-evidence.

So this frames a REGION and fills the frame with it.

FRAMING, WHICH THE FIRST ATTEMPT GOT WRONG
------------------------------------------
Distance is solved from the sensor, not guessed: for a target of radius r and a
lens of focal length f on a sensor of width w, the distance that fits it is
r * f / (w/2), times a margin. Guessing a multiple of the region size instead,
with an 85 mm telephoto, produced a close-up of a chin when the target was a head.

EXPOSURE
--------
AgX is the default view transform and it does roll off highlights - a claim that
this build only offers 'None' came from probing bl_rna, which returns a
placeholder rather than the real enum. Still, the session default of world 1.6 +
sun 4.0 is several times a sane key light, so this uses 1.0/2.5 and exposes the
knobs. Pale skin against a bright world is the case that clips first.
"""

import argparse
import math
import sys

# Regions are (bone_a, bone_b, radius_scale, default_views). The pair spans the
# region; the radius is a multiple of that span.
#
# The VIEWS are part of the region, and that is not cosmetic. On a T-posed
# character the arm points along the lateral axis, so "front" foreshortens the
# hand into a featureless paddle and "side" stares straight down the arm. Rendered
# that way, a hand with five perfectly good fingers reads as a flat stump - which
# is exactly what happened here, and got written up as a defect before a top-down
# view showed the fingers. A region has to be looked at from somewhere it is not
# edge-on.
REGIONS = {
    "head":   ("mixamorig:Head", "mixamorig:HeadTop_End", 1.6, ("front", "side")),
    "hands":  ("mixamorig:LeftForeArm", "mixamorig:LeftHand", 1.3, ("top", "front")),
    "hip":    ("mixamorig:Hips", "mixamorig:LeftUpLeg", 2.6, ("front", "side")),
    "feet":   ("mixamorig:LeftLeg", "mixamorig:LeftFoot", 1.8, ("front", "side")),
    "torso":  ("mixamorig:Spine", "mixamorig:Neck", 1.5, ("front", "side")),
    "full":   (None, None, 1.0, ("front", "side")),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glb", required=True)
    ap.add_argument("--out-prefix", required=True)
    ap.add_argument("--regions", default="head,hands,hip,feet")
    ap.add_argument("--views", default="", help="override the per-region defaults")
    ap.add_argument("--frame", type=int, default=None, help="animation frame; default is rest")
    ap.add_argument("--resolution", type=int, default=768)
    ap.add_argument("--lens", type=float, default=50.0)
    ap.add_argument("--world", type=float, default=1.0)
    ap.add_argument("--sun", type=float, default=2.5)
    ap.add_argument("--wire", action="store_true", help="overlay wireframe to see topology")
    args = ap.parse_args()

    import bpy
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=args.glb)
    scene = bpy.context.scene
    for o in list(scene.objects):
        if any(c.name.startswith("glTF_not_exported") for c in o.users_collection):
            bpy.data.objects.remove(o, do_unlink=True)

    arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
    meshes = [o for o in scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit(f"{args.glb} contains no mesh")

    if args.frame is not None:
        if arm is None or arm.animation_data is None or arm.animation_data.action is None:
            raise SystemExit("--frame given but the file carries no action")
        scene.frame_set(args.frame)

    def bone_world(name):
        if arm is None or name not in arm.pose.bones:
            return None
        return arm.matrix_world @ arm.pose.bones[name].head

    pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    body_centre, body_r = (lo + hi) / 2, (hi - lo).length / 2

    # A body frame, so "front" means the character's front and not world -Y.
    up = Vector((0, 0, 1))
    fwd = Vector((0, -1, 0))
    if arm is not None:
        h, s2 = bone_world("mixamorig:Hips"), bone_world("mixamorig:Spine2")
        lf, lt = bone_world("mixamorig:LeftFoot"), bone_world("mixamorig:LeftToeBase")
        rf, rt = bone_world("mixamorig:RightFoot"), bone_world("mixamorig:RightToeBase")
        if h and s2 and lf and lt and rf and rt:
            up = (s2 - h).normalized()
            f = (lt - lf) + (rt - rf)
            fwd = (f - f.dot(up) * up).normalized()
    lat = up.cross(fwd).normalized()

    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = scene.render.resolution_y = args.resolution
    scene.view_settings.view_transform = "AgX"
    world = bpy.data.worlds.new("w")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[1].default_value = args.world

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = args.lens
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    sun_data = bpy.data.lights.new("sun", type="SUN")
    sun_data.energy = args.sun
    sun = bpy.data.objects.new("sun", sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))

    if args.wire:
        for m in meshes:
            mod = m.modifiers.new("wire", type="WIREFRAME")
            mod.thickness = 0.0015
            mod.use_replace = False

    sensor = cam_data.sensor_width
    written = []
    for region in [r.strip() for r in args.regions.split(",") if r.strip()]:
        if region not in REGIONS:
            raise SystemExit(f"unknown region {region!r}; have {', '.join(REGIONS)}")
        a, b, scale, default_views = REGIONS[region]
        if a is None:
            centre, radius = body_centre, body_r
        else:
            pa, pb = bone_world(a), bone_world(b)
            if pa is None or pb is None:
                print(f"[skip] {region}: {a} or {b} absent", flush=True)
                continue
            centre = (pa + pb) / 2
            radius = max((pb - pa).length * scale, 1e-3)

        # Solve the distance that actually fits `radius`, rather than guessing a
        # multiple of it - see the docstring.
        dist = radius * args.lens / (sensor / 2.0) * 1.15
        views = [v.strip() for v in args.views.split(",") if v.strip()] or list(default_views)
        for view in views:
            direction = {"front": -fwd, "back": fwd, "side": lat, "side2": -lat,
                         "top": up, "bottom": -up}[view]
            cam.location = centre - direction * dist + up * (radius * 0.05)
            look = (centre - cam.location).normalized()
            # Straight up/down gimbals against a "Y"-up track; use forward there.
            track_up = "Y" if abs(look.dot(up)) < 0.95 else "Z"
            cam.rotation_euler = look.to_track_quat("-Z", track_up).to_euler()
            path = f"{args.out_prefix}_{region}_{view}.png"
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            written.append(path)
            print(f"[ok] {path}", flush=True)

    print(f"INSPECT_OK {len(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
