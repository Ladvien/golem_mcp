"""The benchmark: recreate real ambientcg PBR sets from a DESCRIPTION.

The ground truth is ambientcg's own maps - CC0, photoreal, and the
three the lane produces. The RECREATION gets only the material's own
words - "bricks", "stone", "grain", "wool" - and never the ground
truth's pixels.

The PATTERN comes from the lane's own rule,
`pbr.patterns.pattern_for_description`. The SIZE comes from the
ground truth's measured feature scale, because a description cannot
say how big the stones are - and the lane has to be told, or derive
it. The size is the pattern's OWN unit: a voronoi cell is a stone, so
the cell count is the stone count, but a brick's cell is a COURSE and
a course holds several bricks across.

The WRITING and the MEASURING are separate processes, and that
matters: measuring inside the writing process reads the recreation
into Blender, and the next write's EXR read inherits that datablock -
so every file after the first came out as the first one's pattern.
"""

import glob
import json
import pathlib
import sys
import time

for _p in glob.glob("/Users/ladvien/golem_mcp/blender/.venv/lib/python*/site-packages"):
    sys.path.append(_p)
sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")

import bpy  # pylint: disable=import-error,import-outside-toplevel

from golem_blender.pbr import (
    paths as pbr_paths,  # pylint: disable=import-outside-toplevel
)
from golem_blender.pbr.palette import (  # pylint: disable=import-outside-toplevel
    palette_for_description,
)
from golem_blender.pbr.patterns import (  # pylint: disable=import-outside-toplevel
    pattern_for_description,
)
from golem_blender.pbr.procedural import (  # pylint: disable=import-outside-toplevel
    write_procedural_base_color,
)

ROOT = pathlib.Path("/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg")
OUT = ROOT / "recreated"

# How many bricks a course holds across, and how many features a
# course is tall. The cell count is the feature count over both.
BRICKS_PER_COURSE = 4.0
FEATURES_PER_COURSE = 2.0


def describe(tags):
    """The DESCRIPTION, from the material's own words.

    The catalogue numbers and the slugs are dropped: what is left is
    what a person would write to describe the surface.
    """
    return ", ".join(
        tag
        for tag in tags
        if not tag.isdigit()
        and not any(character.isdigit() for character in tag)
        and len(tag) >= 3
    )


def pattern_for(tags, features_across):
    """The pattern and its scale, from the description and the size."""
    kind = pattern_for_description(describe(tags))
    scale = max(2.0, round(features_across))
    if kind == "brick":
        scale = max(
            2.0,
            round(features_across / (BRICKS_PER_COURSE * FEATURES_PER_COURSE)),
        )
    elif kind == "grain":
        # A grain's cell is a RING, and the pattern's rings are two per
        # cell - the absolute value folds the axis - so a cell carries
        # about three features. Measured: 3.048 features per cell at
        # twenty-four and at forty-eight cells.
        scale = max(2.0, round(features_across / 3.048))
    return kind, scale


def main():
    cube = bpy.data.objects.get("Cube")
    if cube:
        bpy.data.objects.remove(cube, do_unlink=True)

    manifest = json.loads((ROOT / "manifest.json").read_text())
    truth = {
        entry["asset_id"]: entry
        for entry in json.loads((ROOT / "truth_statistics.json").read_text())
    }
    OUT.mkdir(parents=True, exist_ok=True)

    results = []
    for entry in manifest:
        asset_id = entry["asset_id"]
        if asset_id not in truth:
            continue
        kind, scale = pattern_for(
            entry["tags"], truth[asset_id]["albedo"]["features_across"]
        )
        base_path = OUT / f"{asset_id}_BaseColor.png"
        started = time.time()
        write_procedural_base_color(
            base_path,
            kind=kind,
            scale_cells=float(scale),
            width_px=pbr_paths.SET_RESOLUTION_PX,
            height_px=pbr_paths.SET_RESOLUTION_PX,
            **palette_for_description(describe(entry["tags"])),
        )
        elapsed = time.time() - started
        print(
            f"RUN {asset_id:16s} the pattern is {kind:8s} at {scale:6.1f} cells  "
            f"the file is {base_path.stat().st_size:9d} bytes  ({elapsed:.1f}s)"
        )
        results.append(
            {
                "asset_id": asset_id,
                "pattern": kind,
                "scale_cells": scale,
                "path": str(base_path),
            }
        )
    (ROOT / "recreation_paths.json").write_text(json.dumps(results, indent=2))
    print(f"RUN {len(results)} materials were recreated")


main()
print("DONE")
