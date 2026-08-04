#!/usr/bin/env python
"""Enumerate the animation clips on disk and say which can drive our characters.

    animation_library.py --roots /mnt/codex_fs/game_assets/animation ... --cache c.json

A "clip" is a (file, action) pair, not a file. The Quaternius Universal Animation
Library ships ONE fbx per target engine carrying every clip as a separate action,
so listing files alone reports 13 clips where there are dozens.

Reading that requires importing each file in Blender, which is slow enough that
the result is cached by (path, size, mtime). A file whose stamp is unchanged is
never reopened; a changed or new one is rescanned. Deleted files drop out.

The `convention` field is what makes the listing useful: it is the name map that
matched the clip's own armature, so a clip reporting null cannot drive our rigs
no matter how it is invoked, and that is visible before spending a retarget on it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from retarget_animation import MAPS  # noqa: E402

CLIP_SUFFIXES = (".fbx", ".glb")


def stamp(path):
    st = path.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def scan_file(path):
    """(actions, convention, bones) for one clip file, via a fresh Blender scene."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    loader = bpy.ops.import_scene.fbx if path.suffix.lower() == ".fbx" else bpy.ops.import_scene.gltf
    loader(filepath=str(path))
    arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
    bones = {b.name for a in arms for b in a.data.bones}
    scored = [(sum(1 for k in m if k in bones), name) for name, m in MAPS.items()]
    hits, best = max(scored) if scored else (0, None)
    actions = [
        {"action": a.name, "frames": int(round(a.frame_range[1] - a.frame_range[0])) + 1}
        for a in bpy.data.actions
    ]
    return actions, (best if hits >= 6 else None), len(bones)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roots", nargs="+", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--refresh", action="store_true", help="rescan every file, ignoring stamps")
    ap.add_argument("--report", help="write the JSON result here; Blender's own chatter makes "
                                     "stdout unsafe to parse")
    args = ap.parse_args()

    cache_path = Path(args.cache)
    cached = {}
    if cache_path.is_file() and not args.refresh:
        cached = json.loads(cache_path.read_text()).get("files", {})

    found = []
    for root in args.roots:
        r = Path(root)
        if not r.is_dir():
            raise SystemExit(f"animation root does not exist: {r}")
        # `._name.fbx` are macOS AppleDouble resource forks that shipped with these
        # packs. They carry the .fbx suffix but are not FBX, and Blender rejects
        # them with "Invalid header". A real clip that fails to open still raises.
        found += [
            p for p in sorted(r.rglob("*"))
            if p.suffix.lower() in CLIP_SUFFIXES and not p.name.startswith("._")
        ]

    files, rescanned = {}, 0
    for p in found:
        key, st = str(p), stamp(p)
        hit = cached.get(key)
        if hit and hit.get("stamp") == st:
            files[key] = hit
            continue
        actions, convention, bones = scan_file(p)
        files[key] = {"stamp": st, "actions": actions, "convention": convention, "bones": bones}
        rescanned += 1

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"files": files}, indent=2) + "\n")

    # The handle a human would use differs by how the file is packed. Every Mixamo
    # export names its single action "Armature|mixamo.com|Layer0", so all 40 of ours
    # collide on action name and the FILE name is the only thing that identifies
    # them; a UAL bundle is the reverse, one file holding dozens of named actions.
    # One rule covers both: single-action files are named by file, bundles by action.
    clips = [
        {"file": f, "action": a["action"], "frames": a["frames"],
         "name": Path(f).stem if len(v["actions"]) == 1 else a["action"],
         "convention": v["convention"], "library": Path(f).parent.name}
        for f, v in sorted(files.items()) for a in v["actions"]
    ]
    usable = [c for c in clips if c["convention"]]
    result = {
        "files": len(files), "rescanned": rescanned, "from_cache": len(files) - rescanned,
        "clips": len(clips), "usable": len(usable),
        "unusable_files": sorted({c["file"] for c in clips if not c["convention"]}),
        "by_convention": {k: sum(1 for c in usable if c["convention"] == k) for k in MAPS},
        "clip_list": clips,
    }
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("LIBRARY_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
