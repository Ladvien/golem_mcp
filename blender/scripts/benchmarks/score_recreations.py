"""The benchmark's SCORE, measured in a fresh process.

The recreation is written by one process and measured by another,
because measuring inside the writing process turned out to be the
thing that broke it: reading the recreation into Blender puts it in
an image datablock, and the NEXT write's EXR read inherits that
datablock - so every file after the first came out as the first
one's pattern. Measured: ten files, all 467876 bytes, all the same
hash, and the same seam for every one.

The score per material:
  - the ALBEDO as statistics a viewer reads: the brightness ratio,
    the contrast ratio, the feature-scale ratio, and the colour
    balance error.
  - the SEAM: the recreation's against the truth's, because a set
    that does not tile is not usable however good it looks.

The truth's numbers are the target, and the ground truth's own seam
is the standard - ambientcg's maps are made to tile.
"""

import glob
import json
import os
import pathlib
import sys

for _p in glob.glob("/Users/ladvien/golem_mcp/blender/.venv/lib/python*/site-packages"):
    sys.path.append(_p)
sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")

import bpy

from golem_blender.pbr import benchmark
from golem_blender.pbr import paths as pbr_paths

SEAM_SCALED_DIR = pathlib.Path("/tmp/golem-seam-scaled")


def _seam_at_truth_resolution(recreated, truth_map) -> float:
    """The recreated map's seam, measured at the TRUTH's own size.

    The recreated maps are 2048 pixels and the truths are 1024, and
    the seam's step is the step across ONE pixel while the interior's
    step is the step between two - so the interior's step halves with
    the resolution and the seam's does not, and a map at twice the
    resolution reads a worse seam against the same truth for no
    reason at all.

    Measured on the truth's own Metal032: at its own 1024 the seam
    reads 0.98x its interior's biggest step - which is what a tiling
    map is - and at 2048 the same map reads 7.76x.
    """
    from PIL import Image

    with Image.open(truth_map) as handle:
        truth_size = handle.size
    with Image.open(recreated) as handle:
        our_size = handle.size
    if our_size == truth_size:
        return pbr_paths.tile_seam_ratio(recreated)
    SEAM_SCALED_DIR.mkdir(parents=True, exist_ok=True)
    scaled = SEAM_SCALED_DIR / f"{pathlib.Path(recreated).stem}_at_truth.png"
    with Image.open(recreated) as handle:
        handle.convert("RGB").resize(truth_size, Image.LANCZOS).save(scaled)
    try:
        return pbr_paths.tile_seam_ratio(scaled)
    finally:
        scaled.unlink(missing_ok=True)


ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg",
    )
)

cube = bpy.data.objects.get("Cube")
if cube:
    bpy.data.objects.remove(cube, do_unlink=True)

manifest = json.loads((ROOT / "manifest.json").read_text())
truth_statistics = {
    entry["asset_id"]: entry
    for entry in json.loads((ROOT / "truth_statistics.json").read_text())
}

results = []
for entry in manifest:
    asset_id = entry["asset_id"]
    truth = truth_statistics.get(asset_id)
    if truth is None:
        continue
    directory = pathlib.Path(entry["directory"])
    recreated = ROOT / "recreated" / f"{asset_id}_BaseColor.png"
    if not recreated.is_file():
        continue

    truth_map = next(iter(sorted(directory.glob("albedo.png"))), None)
    if truth_map is None:
        truth_map = next(iter(sorted(directory.glob("albedo.jpg"))), None)
    if truth_map is None:
        continue
    albedo = benchmark.compare_albedo(truth_map, recreated)
    seam = _seam_at_truth_resolution(recreated, truth_map)

    print(
        f"SCORE {asset_id:16s} the brightness is {albedo['brightness_ratio']:5.2f}x "
        f"the truth's  the contrast is {albedo['contrast_ratio']:5.2f}x  the scale is "
        f"{albedo['scale_ratio']:5.2f}x  the colour error is "
        f"{albedo['colour_balance_error']:.4f}  |  the seam is {seam:5.2f}x against "
        f"the truth's {truth['seam_ratio']:5.2f}x"
    )
    results.append(
        {
            "asset_id": asset_id,
            "brightness_ratio": round(albedo["brightness_ratio"], 3),
            "contrast_ratio": round(albedo["contrast_ratio"], 3),
            "scale_ratio": round(albedo["scale_ratio"], 3),
            "colour_balance_error": round(albedo["colour_balance_error"], 4),
            "recreated_seam_ratio": round(seam, 3),
            "truth_seam_ratio": truth["seam_ratio"],
        }
    )

if results:
    print()
    print(
        f"SCORE the mean brightness ratio is "
        f"{sum(r['brightness_ratio'] for r in results) / len(results):.2f}x  "
        f"the mean contrast ratio is "
        f"{sum(r['contrast_ratio'] for r in results) / len(results):.2f}x  "
        f"the mean scale ratio is "
        f"{sum(r['scale_ratio'] for r in results) / len(results):.2f}x  "
        f"the mean seam is "
        f"{sum(r['recreated_seam_ratio'] for r in results) / len(results):.2f}x "
        f"against the truth's "
        f"{sum(r['truth_seam_ratio'] for r in results) / len(results):.2f}x"
    )
(ROOT / "recreation_scores.json").write_text(json.dumps(results, indent=2))
print("DONE")
