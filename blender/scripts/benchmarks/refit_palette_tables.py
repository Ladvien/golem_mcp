"""Rewrite the palette's fitted tables from the truth sets.

The palette's tables - a word's value, its spread, its hue and how
many materials name it - are FITS, and a fit is only as good as the
materials it was made on. There are now four truth sets (the twenty
hand-picked, the eighty-seven wide, the forty-seven from
ambientcg's popular list, and the site's own sixty most-downloaded) and the popular list has kinds the first
two never reach.

So this rewrites the four tables in `src/golem_blender/pbr/palette.py`
from all the materials of all the sets. It is a codemod, not a
library: it edits the source in place, and the values it writes are
printed so the change is visible in the diff.

Run it with the dev venv's python - it needs no numpy and no bpy.

    cd blender && .venv/bin/python scripts/benchmarks/refit_palette_tables.py
"""

import json
import os
import pathlib
import re
from collections import defaultdict

BENCH = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks",
    )
)
SET_NAMES = ("ambientcg", "ambientcg_wide", "ambientcg_popular", "ambientcg_top")
SOURCE = (
    pathlib.Path(__file__).resolve().parents[2] / "src/golem_blender/pbr/palette.py"
)


def load():
    """Every material of every truth set, with its measures."""
    materials = []
    for name in SET_NAMES:
        root = BENCH / name
        if not (root / "manifest.json").is_file():
            continue
        manifest = json.loads((root / "manifest.json").read_text())
        truth = {
            entry["asset_id"]: entry
            for entry in json.loads((root / "truth_statistics.json").read_text())
        }
        for entry in manifest:
            measures = truth.get(entry["asset_id"], {}).get("albedo")
            if not measures:
                continue
            total = (
                measures["red_mean"] + measures["green_mean"] + measures["blue_mean"]
            )
            materials.append(
                {
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
                        measures["red_mean"] / total,
                        measures["green_mean"] / total,
                        measures["blue_mean"] / total,
                    ),
                }
            )
    return materials


def group(materials, key):
    grouped = defaultdict(list)
    for material in materials:
        for word in set(material["tags"]):
            grouped[word].append(material[key])
    return grouped


def replace_table(source, name, body):
    """Replace a table's body, keeping the header and the closing brace."""
    # The annotation may itself contain brackets - HUES is
    # "dict[str, tuple[float, float, float]]" - so the header is
    # matched up to the "= {" and not by a bracket count.
    pattern = re.compile(
        rf"({re.escape(name)}: dict\[.*?\] = \{{)(.*?)(\n\}})", re.DOTALL
    )
    match = pattern.search(source)
    if match is None:
        raise SystemExit(f"the table {name} was not found in the source")
    return source[: match.start(2)] + body + source[match.end(2) :]


def main():
    materials = load()
    if not materials:
        raise SystemExit("no truth set was found")
    print(f"FIT the materials {len(materials)}")

    grouped_luma = group(materials, "luma")
    grouped_spread = group(materials, "spread")
    grouped_hue = group(materials, "hue")

    source = SOURCE.read_text()

    counts = "\n".join(
        f'    "{word}": {len(values)},'
        for word, values in sorted(
            grouped_luma.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    source = replace_table(source, "SPREAD_SPREAD_WORD_COUNTS", "\n" + counts)

    values = "\n".join(
        f'    "{word}": {round(sum(items) / len(items), 4)},'
        for word, items in sorted(
            grouped_luma.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    source = replace_table(source, "MATERIAL_VALUES", "\n" + values)

    spreads = "\n".join(
        f'    "{word}": {round(sum(items) / len(items), 4)},'
        for word, items in sorted(
            grouped_spread.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    source = replace_table(source, "SPREADS", "\n" + spreads)

    hues = "\n".join(
        f'    "{word}": ({round(sum(item[0] for item in items) / len(items), 4)}, '
        f"{round(sum(item[1] for item in items) / len(items), 4)}, "
        f"{round(sum(item[2] for item in items) / len(items), 4)}),"
        for word, items in sorted(
            grouped_hue.items(), key=lambda item: (-len(item[1]), item[0])
        )
    )
    source = replace_table(source, "HUES", "\n" + hues)

    # The MATERIAL words' hues, refitted for the words the table already
    # names: the table was fitted on the wide set alone, where the only
    # grassy material is an olive mossy ground, and every grass and
    # moss on the popular list came out khaki.
    material_words = re.findall(
        r'^    "([a-z]+)": \(',
        re.search(r"MATERIAL_HUES: dict\[.*?\] = \{(.*?)\n\}", source, re.DOTALL).group(1),
        re.MULTILINE,
    )
    material_hues = "\n".join(
        f'    "{word}": ({round(sum(item[0] for item in grouped_hue[word]) / len(grouped_hue[word]), 3)}, '
        f"{round(sum(item[1] for item in grouped_hue[word]) / len(grouped_hue[word]), 3)}, "
        f"{round(sum(item[2] for item in grouped_hue[word]) / len(grouped_hue[word]), 3)}),"
        for word in material_words
        if grouped_hue.get(word)
    )
    source = replace_table(source, "MATERIAL_HUES", "\n" + material_hues)

    SOURCE.write_text(source)
    print(f"FIT the tables in {SOURCE} are rewritten")


if __name__ == "__main__":
    main()
