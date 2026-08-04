#!/usr/bin/env python
"""Lay several GLBs out side by side in one .blend, for viewing.

    assemble_blend.py --out scene.blend --item "Base=asset.glb" --item "Rigged=rig.glb"

Each item goes in its own collection, sits on the ground plane, and gets a 3D text
label underneath, so a pipeline's stages can be compared in one viewport instead of
opening five files.

It opens in Solid shading with Colour set to Texture, so a textured asset looks
textured on open rather than like grey clay - Blender's default Solid/Material
colour ignores the base colour map. Material Preview is still one keystroke away
(Z) if you want full shading. This only applies when you OPEN the file; appending
it into an existing session uses that session's shading instead.

The scene's frame range is taken from the longest action found, and every armature
with an action gets its action slot bound - Blender 4.4+ evaluates NOTHING from
`animation_data.action` alone, which looks exactly like a rig that failed to
import. Hit space in the viewport and the animated item plays.

Run with any bpy-carrying interpreter, e.g. SegviGen's.
"""

import argparse
import math
import sys

SPACING = 0.35   # gap between items, as a fraction of the widest item


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--item", action="append", default=[], metavar="LABEL=PATH")
    ap.add_argument("--label-size", type=float, default=0.0,
                    help="absolute label height; 0 scales it to each item's width")
    args = ap.parse_args()

    import bpy
    from mathutils import Vector

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    placed, frame_end = [], 1
    for spec in args.item:
        if "=" not in spec:
            raise SystemExit(f"--item needs LABEL=PATH, got {spec!r}")
        label, path = spec.split("=", 1)

        before = set(bpy.context.scene.objects)
        before_actions = set(bpy.data.actions)
        if path.lower().endswith(".glb") or path.lower().endswith(".gltf"):
            bpy.ops.import_scene.gltf(filepath=path)
        else:
            bpy.ops.import_scene.fbx(filepath=path)
        added = [o for o in bpy.context.scene.objects if o not in before]
        if not added:
            raise SystemExit(f"{path} imported nothing")

        # SkinTokens' rigged GLBs carry a placeholder the README tells you to delete
        # on import. Matching the NAME does not find it: the object is called
        # "Icosphere" and it is `glTF_not_exported` that names the COLLECTION the
        # importer files it under. Membership is the actual marker.
        #
        # It matters beyond clutter - a 42-vertex icosphere 2.0 m across drives the
        # bounding box of a ~1 m character, so it silently sets the row spacing,
        # the label scale and the camera distance for every item.
        junk = [o for o in added
                if any(c.name.startswith("glTF_not_exported") for c in o.users_collection)]
        for obj in junk:
            bpy.data.objects.remove(obj, do_unlink=True)
        added = [o for o in added if o not in junk]
        if not added:
            raise SystemExit(f"{path} contained nothing but glTF_not_exported")

        coll = bpy.data.collections.new(label)
        scene.collection.children.link(coll)
        for obj in added:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            coll.objects.link(obj)

        # Bind the action slot, or the item stands at rest however many keys it has.
        for obj in added:
            ad = obj.animation_data
            if ad and ad.action:
                if hasattr(ad, "action_slot") and getattr(ad.action, "slots", None):
                    ad.action_slot = ad.action.slots[0]
                frame_end = max(frame_end, int(round(ad.action.frame_range[1])))
        for act in set(bpy.data.actions) - before_actions:
            frame_end = max(frame_end, int(round(act.frame_range[1])))

        placed.append({"label": label, "objects": added,
                       "roots": [o for o in added if o.parent is None]})

    # Measure only after everything is imported, so one pass sizes the whole row.
    bpy.context.view_layer.update()

    def bounds(objs):
        pts = [o.matrix_world @ Vector(c) for o in objs
               if o.type == "MESH" for c in o.bound_box]
        if not pts:
            return Vector((0, 0, 0)), Vector((0, 0, 0))
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        return lo, hi

    widths = []
    for item in placed:
        lo, hi = bounds(item["objects"])
        item["lo"], item["hi"] = lo, hi
        widths.append(hi.x - lo.x)
    gap = max(widths, default=1.0) * SPACING
    cursor = 0.0
    tallest = 0.0

    for item in placed:
        lo, hi = item["lo"], item["hi"]
        width = hi.x - lo.x
        # Shift so the item starts at the cursor and its feet sit on z=0.
        offset = Vector((cursor - lo.x, -(lo.y + hi.y) / 2, -lo.z))
        for root in item["roots"]:
            root.location = root.location + offset
        tallest = max(tallest, hi.z - lo.z)

        # Size labels against the row, not an absolute, so they neither vanish on a
        # 2 m character nor overrun a 0.5 m one.
        size = args.label_size if args.label_size > 0 else max(width * 0.11, 0.02)
        # In FRONT of the row, not at y=0, or the label is swallowed by the body it
        # belongs to. Placed against the POST-shift position: the offset above
        # re-centres each item on y=0, so using the measured lo.y here put three of
        # four labels behind the camera.
        depth = hi.y - lo.y
        bpy.ops.object.text_add(
            location=(cursor + width / 2, -depth / 2 - size * 1.2, -size * 1.8))
        text = bpy.context.object
        text.data.body = item["label"]
        text.data.size = size
        text.data.align_x = "CENTER"
        text.rotation_euler = (1.5708, 0, 0)   # stand it up to face the front view
        for c in list(text.users_collection):
            c.objects.unlink(text)
        bpy.data.collections[item["label"]].objects.link(text)

        item["center_x"] = cursor + width / 2
        cursor += width + gap

    total = max(cursor - gap, 1.0)

    light_data = bpy.data.lights.new("Key", type="SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new("Key", light_data)
    light.rotation_euler = (0.9, 0.1, 0.8)
    scene.collection.objects.link(light)

    # Fix the output aspect first - the framing below is computed against it, and
    # rendering a scene at a different aspect than it was framed for is what
    # cropped the heads off the first version of this.
    scene.render.resolution_x, scene.render.resolution_y = 1920, 960

    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    # Fit BOTH axes: solve the distance each one needs and take the larger. Backing
    # off by a flat multiple of the row width ignores height entirely, which is
    # fine for a wide row and wrong for a tall one.
    fov_x = cam_data.angle
    fov_y = 2 * math.atan(math.tan(fov_x / 2) * scene.render.resolution_y
                          / scene.render.resolution_x)
    margin = 1.15
    dist = max((total / 2) / math.tan(fov_x / 2),
               (tallest / 2) / math.tan(fov_y / 2)) * margin
    cam.location = (total / 2, -dist, tallest / 2)
    cam.rotation_euler = (math.pi / 2, 0, 0)   # level, looking down +Y
    scene.collection.objects.link(cam)
    scene.camera = cam

    scene.frame_start = 1
    scene.frame_end = max(frame_end, 1)

    # Save the VIEWPORT shading too, not just the scene. Blender's default is Solid
    # with Material colour, which draws a textured character as grey clay - the
    # asset looks unfinished when it is not. Solid + Texture shows the base colour
    # map at Solid's speed, without waiting for Material Preview to compile
    # shaders. Written across every screen because the file may open in any
    # workspace, and read back after saving because a silently-empty
    # bpy.data.screens would leave this doing nothing.
    views = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "SOLID"
                    space.shading.color_type = "TEXTURE"
                    views += 1
    if not views:
        raise SystemExit(
            "no VIEW_3D space to configure - bpy.data.screens is empty, so the saved "
            "file would open with default shading and the textures would not show"
        )

    frame_end = scene.frame_end          # read before the file is reopened below:
    bpy.ops.wm.save_as_mainfile(filepath=args.out)
    # Confirm it survived the write; "Load UI" restores this on open. Reopening
    # invalidates every Python handle into the old file, so anything still needed
    # is captured above.
    bpy.ops.wm.open_mainfile(filepath=args.out)
    modes = {
        (sp.shading.type, sp.shading.color_type)
        for sc in bpy.data.screens for ar in sc.areas if ar.type == "VIEW_3D"
        for sp in ar.spaces if sp.type == "VIEW_3D"
    }
    print(f"items: {[i['label'] for i in placed]}")
    print(f"viewport shading saved as: {sorted(modes)} across {views} 3D views")
    print(f"frames: 1-{frame_end}   row width: {total:.2f}   tallest: {tallest:.2f}")
    print(f"ASSEMBLE_OK {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
