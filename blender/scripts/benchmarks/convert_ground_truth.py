"""Convert the ground truth's JPGs to PNGs.

Blender's image loader needs `skinclip` for a JPEG, and this
Blender build does not have it, so the benchmark's ground truth is
read as PNG. The conversion is done with Blender itself, so the
pixels are the ones Blender would read - the conversion does not
change the values.

A JPEG is a lossy format, so this is also worth stating: the
ground truth is measured from the PNG the JPEG becomes, not from
the JPEG.
"""

import pathlib
import sys

sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")

import bpy

ROOT = pathlib.Path("/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg")

converted = 0
for directory in sorted(ROOT.iterdir()):
    if not directory.is_dir():
        continue
    for source in sorted(directory.glob("*.jpg")) + sorted(directory.glob("*.jpeg")):
        target = source.with_suffix(".png")
        if target.exists():
            continue
        try:
            image = bpy.data.images.load(str(source))
        except Exception as error:  # noqa: BLE001
            print(f"CONVERT {source.name}: {error}")
            continue
        if image.size[0] == 0:
            print(f"CONVERT {source.name}: the file did not load")
            bpy.data.images.remove(image)
            continue
        image.filepath_raw = str(target)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
        converted += 1
        print(f"CONVERT {source.name} -> {target.name}")

print(f"CONVERT {converted} files were converted")
print("DONE")
