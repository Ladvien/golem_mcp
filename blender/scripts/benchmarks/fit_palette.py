"""Fit the palette's tables on the truth sets, and print the new ones.

The palette's tables - a word's value, its spread and its hue - are
fits: a word's value is the mean over the materials that name it, and
its count is how many name it. So they are only as good as the
materials they were fitted on.

There are now THREE truth sets: the twenty hand-picked materials, the
eighty-seven wide ones, and the forty-seven from ambientcg's POPULAR
list - and the popular list has kinds the first two never reach
(plastic, marble, cobble, paving, bark, onyx, travertine, mosaic) and
materials that are nearly FLAT, which the first two sets barely have.

So this refits the three tables on all hundred and fifty-four
materials, and prints the new values in the form the source file
wants. It also prints the LEAVE-ONE-OUT error, so a fit that is only
good in-sample is visible as such.

Run it with the dev venv's python - it needs no numpy and no
bpy.

    cd blender && .venv/bin/python scripts/benchmarks/fit_palette.py
"""

import json
import os
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks",
    )
)
SET_NAMES = ("ambientcg", "ambientcg_wide", "ambientcg_popular")


def load():
    """The materials of every truth set: their tags and their measures."""
    materials = []
    for name in SET_NAMES:
        root = ROOT / name
        if not (root / "manifest.json").is_file():
            print(f"FIT the set {name} is not there")
            continue
        manifest = {
            entry["asset_id"]: entry
            for entry in json.loads((root / "manifest.json").read_text())
        }
        truth = {
            entry["asset_id"]: entry
            for entry in json.loads((root / "truth_statistics.json").read_text())
        }
        for asset_id, entry in manifest.items():
            measures = truth.get(asset_id, {}).get("albedo")
            if not measures:
                continue
            materials.append(
                {
                    "asset_id": asset_id,
                    "tags": [
                        tag
                        for tag in entry.get("tags", [])
                        if not tag.isdigit()
                        and not any(character.isdigit() for character in tag)
                        and len(tag) >= 3
                    ],
                    "luma": measures["luma_mean"],
                    "spread": measures["luma_std"],
                    "hue": (
                        measures["red_mean"]
                        / (
                            measures["red_mean"]
                            + measures["green_mean"]
                            + measures["blue_mean"]
                        ),
                        measures["green_mean"]
                        / (
                            measures["red_mean"]
                            + measures["green_mean"]
                            + measures["blue_mean"]
                        ),
                        measures["blue_mean"]
                        / (
                            measures["red_mean"]
                            + measures["green_mean"]
                            + measures["blue_mean"]
                        ),
                    ),
                }
            )
    return materials


def group(materials, key):
    """Each word's own measures: the mean and the count."""
    grouped = defaultdict(list)
    for material in materials:
        for word in set(material["tags"]):
            grouped[word].append(material[key])
    return {
        word: {
            "mean": sum(values) / len(values),
            "count": len(values),
            "values": values,
        }
        for word, values in grouped.items()
    }


def leave_one_out(values):
    """The mean with the value nearest the mean left out."""
    if len(values) < 2:
        return values[0] if values else 0.0
    mean = sum(values) / len(values)
    nearest = min(values, key=lambda value: abs(value - mean))
    rest = [value for value in values if value is not nearest]
    return sum(rest) / len(rest)


def main():
    materials = load()
    print(f"FIT the materials {len(materials)}")
    if not materials:
        raise SystemExit("no truth set was found")

    for key, table_name in (
        ("luma", "MATERIAL_VALUES"),
        ("spread", "SPREADS"),
    ):
        grouped = group(materials, key)
        print(f"\nFIT the {table_name} - the words whose fit moved")
        for word in sorted(grouped, key=lambda word: -grouped[word]["count"]):
            entry = grouped[word]
            print(
                f"    {word:16s} n={entry['count']:3d} the mean {entry['mean']:.4f} "
                f"the leave-one-out {leave_one_out(entry['values']):.4f}"
            )

    grouped = group(materials, "hue")
    print(f"\nFIT the hues")
    for word in sorted(grouped, key=lambda word: -grouped[word]["count"]):
        entry = grouped[word]
        print(
            f"    {word:16s} n={entry['count']:3d} the mean "
            f"({entry['mean'][0]:.4f}, {entry['mean'][1]:.4f}, {entry['mean'][2]:.4f})"
        )


if __name__ == "__main__":
    main()
