"""The GROUND TRUTH's statistics - the target the recreation must hit.

Every material is measured the same way, and the measures are the
ones a viewer reads: the brightness, the contrast, the colour
balance, and the FEATURE SCALE - how big the surface's details are,
which is what tells a brick from a plank from a gravel.

The feature scale is the one that matters most for the lane. A
texture set is a thing you repeat across a floor, and the details'
size relative to the tile decides whether the repeat reads. The AI
cobblestone the lane made has about 4.8 stones across its 2 m tile.

This also measures the ground truth's SEAM, so the target's own
tiling quality is known - ambientcg's maps are made to tile, so
their seams should be small, and that is the standard the lane's
procedural path is being measured against.
"""

import glob
import json
import os
import pathlib
import sys

for _p in glob.glob("/Users/ladvien/golem_mcp/blender/.venv/lib/python*/site-packages"):
    sys.path.append(_p)
sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")


from golem_blender.pbr import benchmark
from golem_blender.pbr import paths as pbr_paths

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg",
    )
)
manifest = json.loads((ROOT / "manifest.json").read_text())

results = []
for entry in manifest:
    directory = pathlib.Path(entry["directory"])
    albedo = next(iter(sorted(directory.glob("albedo.png"))), None)
    if albedo is None:
        continue
    statistics = benchmark.albedo_statistics(albedo)
    seam = pbr_paths.tile_seam_ratio(albedo)
    print(
        f"TRUTH {entry['asset_id']:16s} the luma is {statistics['luma_mean']:.3f} "
        f"with a spread of {statistics['luma_std']:.3f}  the features repeat "
        f"every {statistics['feature_period_px']:4d} px "
        f"({statistics['features_across']:5.2f} across)  the seam is {seam:5.2f}x"
    )
    results.append(
        {
            "asset_id": entry["asset_id"],
            "tags": entry["tags"],
            "albedo": statistics,
            "seam_ratio": round(seam, 3),
        }
    )

(ROOT / "truth_statistics.json").write_text(json.dumps(results, indent=2))
print(f"TRUTH the statistics of {len(results)} materials are written")
print("DONE")
