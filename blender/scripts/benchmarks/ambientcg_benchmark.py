"""The benchmark: recreate real ambientcg PBR sets from a DESCRIPTION.

The lane had only ever been measured against a texture it made
itself. This measures it against REAL sets - ambientcg's, which are
CC0, photoreal, and carry the three maps the lane produces.

The ground truth is fetched by `fetch_ground_truth.py`. The
RECREATION gets only the material's own words - "bricks",
"weathered", "red", "wool" - and never the ground truth's pixels.
The pattern and its scale are chosen from the description, and the
scale comes from the truth's measured feature size, because a
description cannot say how big the stones are.

The WRITING and the MEASURING are separate processes, and that
matters: measuring inside the writing process reads the recreation
into Blender, and the next write's EXR read inherits that
datablock - so every file after the first came out as the first
one's pattern. Measured: ten files, all 467876 bytes, all the same
hash, the same seam for every one. The lane was never broken; the
measurement was.

Run it:
    blender --background --factory-startup --python scripts/benchmarks/ambientcg_benchmark.py
"""

from __future__ import annotations

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
from golem_blender.pbr.procedural import (  # pylint: disable=import-outside-toplevel
    write_procedural_base_color,
)

ROOT = pathlib.Path("/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg")
OUT = ROOT / "recreated"


def pattern_for(tags, features_across):
    """The pattern and its scale, from the description and the size.

    The size comes from the ground truth's measured feature scale,
    because a description cannot say how big the stones are - and
    the lane has to be told, or derive it. The scale is the cell
    count across the tile, so it IS the number of features across.
    """
    words = " ".join(tags).lower()
    scale = max(2.0, round(features_across))
    if "wood" in words or "plank" in words:
        kind = "wave"
    elif "tile" in words:
        kind = "brick"
    else:
        kind = "voronoi"
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
