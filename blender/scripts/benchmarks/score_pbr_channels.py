"""Score the WHOLE PBR set the lane makes from a description against the truth's own maps.

The albedo benchmark (score_recreations.py) reads only the colour map. A
PBR set is more than its colour: the truths ship a roughness, a normal, a
displacement, often an ambient occlusion and, for the metals, a metalness.
This builds each material's set the way the agent's layered-set tool does -
the description chooses the pattern, the palette, the roughness and the
metal - and compares each channel with the truth's:

- roughness: its mean and its spread;
- metallic: its mean;
- ambient occlusion: its mean and its spread, where the truth ships one;
- height: how it follows the albedo (the correlation of the height with
  the luma - a brick's joint is dark AND low) and its SKEW (a wall's flat
  faces cut by narrow joints skew low; pebbles on a flat skew high), where
  the truth ships a displacement. Two layouts again, so the shape of the
  height and not its pixels;
- normal: its STRENGTH, the mean angle of the normals from flat in
  degrees (the two surfaces are different layouts, so a per-pixel angle
  between them says nothing; how much relief each carries does).

Run it in Blender, with GOLEM_BENCH_ROOT set to one truth set:

    GOLEM_BENCH_ROOT=~/mnt/codex_fs/game_assets/benchmarks/ambientcg_top \\
        blender --background --factory-startup --python score_pbr_channels.py

It writes recreated_set/<asset>/ and pbr_channel_scores.json under the root.
"""

from __future__ import annotations

import glob
import json
import math
import os
import pathlib
import sys

for _p in glob.glob("/Users/ladvien/golem_mcp/blender/.venv/lib/python*/site-packages"):
    sys.path.append(_p)
sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")

import numpy

from golem_blender.ops._image_loading import load_image
from golem_blender.pbr.layered_set import write_layered_texture_set
from golem_blender.pbr.patterns import pattern_for_description

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        str(pathlib.Path.home() / "mnt/codex_fs/game_assets/benchmarks/ambientcg"),
    )
).expanduser()
OUT = ROOT / "recreated_set"
RESOLUTION = int(os.environ.get("GOLEM_BENCH_SET_RESOLUTION", "1024"))
# A spread below this is a flat map, and its ratio is read against it.
SPREAD_FLOOR = 0.005


def _channels(path: pathlib.Path):
    """The map's RGB as floats in 0..1, read as data, not colour."""
    image = load_image(path, non_color=True)
    try:
        width, height = image.size
        pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
    finally:
        import bpy

        bpy.data.images.remove(image)
    return pixels.reshape((height, width, 4))[:, :, :3].astype(numpy.float64)


def _truth_map(asset_dir: pathlib.Path, stem: str):
    for suffix in (".png", ".jpg"):
        path = asset_dir / f"{stem}{suffix}"
        if path.is_file():
            return path
    return None


def _normal_strength(rgb) -> float:
    """The mean angle of a tangent-space normal map's normals from flat, in degrees."""
    normal = rgb * 2.0 - 1.0
    length = numpy.maximum(numpy.linalg.norm(normal, axis=2), 1e-6)
    z = numpy.clip(normal[:, :, 2] / length, -1.0, 1.0)
    return float(numpy.degrees(numpy.arccos(z)).mean())


def _luma(rgb):
    return rgb[:, :, 0] * 0.2126 + rgb[:, :, 1] * 0.7152 + rgb[:, :, 2] * 0.0722


def _correlation(a, b) -> float:
    a = a - a.mean()
    b = b - b.mean()
    scale = float(numpy.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / scale) if scale > 1e-12 else 0.0


def _skew(field) -> float:
    deviation = float(field.std())
    if deviation < 1e-9:
        return 0.0
    return float((((field - field.mean()) / deviation) ** 3).mean())


def _log_ratio(ours: float, truth: float, floor: float) -> float:
    return abs(math.log(max(ours, floor) / max(truth, floor)))


def main() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    truth_statistics = {
        entry["asset_id"]: entry
        for entry in json.loads((ROOT / "truth_statistics.json").read_text())
    }
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in manifest:
        asset_id = entry["asset_id"]
        asset_dir = ROOT / asset_id
        roughness_path = _truth_map(asset_dir, "roughness")
        normal_path = _truth_map(asset_dir, "normal_gl")
        if roughness_path is None or normal_path is None:
            continue
        description = ", ".join(entry["tags"])
        kind = pattern_for_description(description)
        scale = max(2.0, round(truth_statistics[asset_id]["albedo"]["features_across"]))
        written = write_layered_texture_set(
            OUT / asset_id,
            asset_id,
            {"description": description, "kind": kind},
            [],
            scale_cells=scale,
            resolution=RESOLUTION,
        )
        orm = _channels(pathlib.Path(written["paths"]["orm"]))
        ours_normal = _channels(pathlib.Path(written["paths"]["normal"]))

        truth_rough = _channels(roughness_path)[:, :, 0]
        metal_path = _truth_map(asset_dir, "metalness")
        # A set without a metalness map has not said whether it is metal,
        # and reading it as zero scored every metal of those sets wrong.
        truth_metal = (
            float(_channels(metal_path)[:, :, 0].mean()) if metal_path else None
        )
        ao_path = _truth_map(asset_dir, "ambient_occlusion")
        truth_ao_map = _channels(ao_path)[:, :, 0] if ao_path else None
        truth_ao = float(truth_ao_map.mean()) if ao_path else None
        height_path = _truth_map(asset_dir, "displacement")
        ours_height = _channels(pathlib.Path(written["paths"]["height"]))[:, :, 0]
        ours_luma = _luma(_channels(pathlib.Path(written["paths"]["base_color"])))
        if height_path is not None:
            truth_height = _channels(height_path)[:, :, 0]
            truth_luma = _luma(_channels(_truth_map(asset_dir, "albedo")))
            if truth_luma.shape != truth_height.shape:
                # Both are square powers of two; take every n-th pixel of
                # the larger so the correlation pairs the same places.
                step = truth_luma.shape[0] // truth_height.shape[0]
                if step >= 1:
                    truth_luma = truth_luma[::step, ::step]
                else:
                    step = truth_height.shape[0] // truth_luma.shape[0]
                    truth_height = truth_height[::step, ::step]
            truth_height_luma = _correlation(truth_height, truth_luma)
            truth_height_skew = _skew(truth_height)
        else:
            truth_height_luma = truth_height_skew = None

        row = {
            "asset_id": asset_id,
            "kind": kind,
            "roughness_mean": [float(orm[:, :, 1].mean()), float(truth_rough.mean())],
            "roughness_spread": [float(orm[:, :, 1].std()), float(truth_rough.std())],
            "metallic_mean": [float(orm[:, :, 2].mean()), truth_metal],
            "ao_mean": [float(orm[:, :, 0].mean()), truth_ao],
            "ao_spread": [
                float(orm[:, :, 0].std()),
                None if truth_ao_map is None else float(truth_ao_map.std()),
            ],
            "height_luma_correlation": [
                _correlation(ours_height, ours_luma),
                truth_height_luma,
            ],
            "height_skew": [_skew(ours_height), truth_height_skew],
            "normal_strength_deg": [
                _normal_strength(ours_normal),
                _normal_strength(_channels(normal_path)),
            ],
        }
        results.append(row)
        print(
            f"SCORE {asset_id:16s} roughness {row['roughness_mean'][0]:.2f}/"
            f"{row['roughness_mean'][1]:.2f}  spread {row['roughness_spread'][0]:.3f}/"
            f"{row['roughness_spread'][1]:.3f}  metal {row['metallic_mean'][0]:.2f}/"
            f"{'-' if truth_metal is None else format(truth_metal, '.2f')}  normal {row['normal_strength_deg'][0]:5.1f}/"
            f"{row['normal_strength_deg'][1]:5.1f} deg",
            flush=True,
        )
    (ROOT / "pbr_channel_scores.json").write_text(json.dumps(results, indent=2))
    if not results:
        print("SCORE no material had a roughness and a normal map")
        return
    count = len(results)
    rough_mean = sum(
        abs(r["roughness_mean"][0] - r["roughness_mean"][1]) for r in results
    )
    rough_spread = sum(
        _log_ratio(r["roughness_spread"][0], r["roughness_spread"][1], SPREAD_FLOOR)
        for r in results
    )
    metals = [r for r in results if r["metallic_mean"][1] is not None]
    metal = sum(abs(r["metallic_mean"][0] - r["metallic_mean"][1]) for r in metals)
    normal = sum(
        _log_ratio(r["normal_strength_deg"][0], r["normal_strength_deg"][1], 0.5)
        for r in results
    )
    aos = [r for r in results if r["ao_mean"][1] is not None]
    ao_mean = sum(abs(r["ao_mean"][0] - r["ao_mean"][1]) for r in aos)
    ao_spread = sum(
        _log_ratio(r["ao_spread"][0], r["ao_spread"][1], SPREAD_FLOOR) for r in aos
    )
    heights = [r for r in results if r["height_skew"][1] is not None]
    height_luma = sum(
        abs(r["height_luma_correlation"][0] - r["height_luma_correlation"][1])
        for r in heights
    )
    height_skew = sum(abs(r["height_skew"][0] - r["height_skew"][1]) for r in heights)
    print(
        f"SCORE over {len(aos)} with an AO: ao mean |error| {ao_mean / max(1, len(aos)):.3f}  "
        f"ao spread mean |log| {ao_spread / max(1, len(aos)):.3f}; over {len(heights)} with a "
        f"height: height-luma correlation |error| {height_luma / max(1, len(heights)):.3f}  "
        f"height skew |error| {height_skew / max(1, len(heights)):.3f}"
    )
    print(
        f"SCORE over {count}: roughness mean |error| {rough_mean / count:.3f}  "
        f"roughness spread mean |log| {rough_spread / count:.3f}  "
        f"metallic mean |error| {metal / max(1, len(metals)):.3f} (over {len(metals)})  "
        f"normal strength mean |log| {normal / count:.3f}"
    )


main()
