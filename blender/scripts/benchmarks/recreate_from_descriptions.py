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
import os
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
    line_palette_for_description,
    palette_for_description,
)
from golem_blender.pbr.patterns import (  # pylint: disable=import-outside-toplevel
    is_checkered,
    pattern_for_description,
)
from golem_blender.pbr.procedural import (  # pylint: disable=import-outside-toplevel
    write_procedural_base_color,
)

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg",
    )
)
OUT = ROOT / "recreated"

# How many features a cell carries.
#
# It is ONE, and it was not: a brick's cell was a course of four
# bricks and two features, and a grain's cell was three features, and
# both made the pattern far too coarse.
#
# Measured against the truth's own: the tiles read 0.50x the truth's
# feature scale with the old divisor and 1.05x with one; the third
# tile 0.46x and 0.98x; the fourth 0.48x and 1.02x; the first brick
# 1.19x and 0.90x; and the wood 0.37x and 0.84x.
FEATURES_PER_CELL = 1.0


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


def pattern_for(tags, features_across, features_down=0.0):
    """The pattern and its scale, from the description and the size.

    The count is the truth's own ACROSS count, and it is the count
    the feature measure reads - the measure reads along a row, and
    the truth's own Wood096 measures 5.8 across where its rings
    come every eight rows down.
    """
    kind = pattern_for_description(describe(tags))
    scale = max(2.0, round(features_across / FEATURES_PER_CELL))
    return kind, scale, scale


def courses_for(tags, features_down):
    """The COURSES a surface has, and it is the truth's own DOWN count.

    A parquet is a set of LONG BOARDS: many blocks across and few
    courses down. The truth's own WoodFloor051 measures 7.1 features
    across and ONE down, and the floor's courses came from the
    across count - so it came out as a grid of squares where the
    truth has long boards.
    """
    if features_down <= 0.0:
        return None
    return max(1, round(features_down))


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
        kind, scale, fibre_scale = pattern_for(
            entry["tags"],
            truth[asset_id]["albedo"]["features_across"],
            truth[asset_id]["albedo"].get("features_down", 0.0),
        )
        base_path = OUT / f"{asset_id}_BaseColor.png"
        started = time.time()
        # A GRAIN and a METAL are LINES on a surface, and a line
        # pattern has no cells to vary: the whole image is ONE colour
        # and the lines are the only variation on it. So they take the
        # line palette and not the cell one.
        description = describe(entry["tags"])
        palette = (
            line_palette_for_description(description, path=kind)
            if kind in ("grain", "metal")
            else palette_for_description(description, path=kind)
        )
        write_procedural_base_color(
            base_path,
            kind=kind,
            scale_cells=float(scale),
            fibre_scale=float(fibre_scale),
            width_px=pbr_paths.SET_RESOLUTION_PX,
            height_px=pbr_paths.SET_RESOLUTION_PX,
            checkered=is_checkered(description),
            courses=courses_for(
                entry["tags"], truth[asset_id]["albedo"].get("features_down", 0.0)
            ),
            **palette,
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
