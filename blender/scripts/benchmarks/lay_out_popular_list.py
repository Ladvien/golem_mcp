"""Lay the popular list's maps out the way the benchmark reads them.

ambientcg's zips carry every file with the asset's id in its name -
`Metal027_1K-JPG_Color.jpg` - and the benchmark's scripts read
`albedo.png`, `roughness.png` and so on. So the files are renamed
and the JPEGs are converted, the same conversion the other sets
went through.

A JPEG is lossy, so the ground truth is measured from the PNG the
JPEG becomes and not from the JPEG itself - the same rule the other
sets follow, so the numbers are comparable.
"""

import os
import pathlib
import shutil
import sys

sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")

import bpy

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg_top",
    )
)

# The map a file is, by the word in its name.
MAP_WORDS = {
    "color": "albedo",
    "roughness": "roughness",
    "displacement": "displacement",
    "normaldx": "normal_dx",
    "normalgl": "normal_gl",
    "metalness": "metalness",
    "ao": "ao",
}


def the_map_of(name: str) -> str | None:
    """The map a file is, or None when it is not a map."""
    lowered = name.lower()
    if not lowered.endswith((".jpg", ".jpeg")):
        return None
    stem = lowered.rsplit("/", 1)[-1]
    for word, map_name in MAP_WORDS.items():
        if word in stem:
            return map_name
    return None


def main():
    renamed = 0
    converted = 0
    for directory in sorted(ROOT.iterdir()):
        if not directory.is_dir():
            continue
        for source in sorted(directory.glob("*.jpg")) + sorted(
            directory.glob("*.jpeg")
        ):
            map_name = the_map_of(source.name)
            if map_name is None:
                continue
            target = directory / f"{map_name}.jpg"
            if target.exists() or target.with_suffix(".png").exists():
                continue
            # And the PNG the earlier run made, and it has to go
            # first: a PNG beside the JPEG is the JPEG's own
            # conversion and not the map.
            source.with_suffix(".png").unlink(missing_ok=True)
            source.rename(target)
            renamed += 1
        # And the stray PNG the zip carries - the preview - and the
        # model files, which the benchmark does not read.
        for source in sorted(directory.glob("*.png")):
            # The stray PNG the zip carries is the preview, and the
            # map's own PNG is the conversion - and only the renamed
            # map's PNG is kept.
            if source.stem == directory.name or the_map_of(source.stem + ".jpg"):
                source.unlink()
        # And the files the zip carried under the asset's own name,
        # once they have been renamed: the renamed map is the truth
        # and the prefixed one is a copy of it.
        for source in sorted(directory.glob("*_1K-JPG_*")):
            source.unlink()
        for source in sorted(directory.glob("*.blend")) + sorted(
            directory.glob("*.usdc")
        ) + sorted(directory.glob("*.mtlx")) + sorted(directory.glob("*.tres")):
            source.unlink()
    print(f"RENAMED {renamed} maps")
    for directory in sorted(ROOT.iterdir()):
        if not directory.is_dir():
            continue
        for source in sorted(directory.glob("*.jpg")):
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
    print(f"CONVERTED {converted} files")
    shutil.rmtree(ROOT / "source.zip", ignore_errors=True)
    print("DONE")


main()
