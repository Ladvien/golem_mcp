"""FIT THE PALETTE from the ground truth, and write the tables back.

The palette's tables - the value a colour word carries, the spread a
texture word carries, the hue a material carries - are MEASURED from
the truth sets and not chosen by hand. They were fitted on the
twenty hand-picked ambientcg sets, and a fit against twenty
materials is a fit against twenty materials.

So this fits them on the WIDE sample: seventy real ambientcg sets
over sixteen kinds, and every word's value is the mean over the
materials that name it.

Run it with the system python - it needs only json.

    python scripts/benchmarks/fit_palette.py [--root PATH] [--write]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

DEFAULT_ROOT = pathlib.Path(
    "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg_wide"
)

# The palette's file and the tables in it.
PALETTE = pathlib.Path(
    pathlib.Path(__file__).resolve().parents[2]
    / "src"
    / "golem_blender"
    / "pbr"
    / "palette.py"
)

# The words that name a MATERIAL, and they are read before the
# colour words - a description's word order is alphabetical and says
# nothing.
#
# The list is the palette's own: a word that is in here is a word the
# palette already treats as a material.
MATERIAL_WORDS = (
    "bricks",
    "brick",
    "wood",
    "wooden",
    "metal",
    "steel",
    "iron",
    "concrete",
    "stone",
    "rock",
    "rocky",
    "tiles",
    "tile",
    "fabric",
    "wool",
    "carpet",
    "leather",
    "asphalt",
    "pavement",
    "plaster",
    "stucco",
    "paint",
    "glass",
    "plastic",
    "paper",
    "grass",
    "leaves",
    "moss",
    "mossy",
    "sand",
    "gravel",
    "dirt",
    "earth",
    "mud",
    "soil",
    "ground",
    "clay",
    "terracotta",
    "limestone",
    "sandstone",
    "marble",
    "granite",
    "parquet",
    "plank",
    "planks",
    "carpet",
    "scattered",
    "roof",
    "roofing",
    "shingle",
    "wallpaper",
    "woodchip",
    "herringbone",
    "basketweave",
    "woven",
    "weave",
    "textile",
    "cloth",
)

# The words that name a METAL, and a metal's value is read from the
# NAMED_COLOURS table and not from the colour words' one.
METAL_WORDS = (
    "silver",
    "steel",
    "iron",
    "chrome",
    "aluminium",
    "aluminum",
    "brass",
    "bronze",
    "copper",
    "gold",
    "cobalt",
    "rust",
)

# The words that name a COLOUR.
COLOUR_WORDS = (
    "white",
    "black",
    "grey",
    "gray",
    "red",
    "green",
    "blue",
    "yellow",
    "orange",
    "brown",
    "beige",
    "cream",
    "tan",
    "charcoal",
    "silver",
    "gold",
    "brass",
    "copper",
    "rust",
    "rusty",
    "natural",
    "dark",
    "light",
    "bright",
    "pale",
    "cobalt",
    "espresso",
)


def describe(tags) -> str:
    """The DESCRIPTION, from the material's own words."""
    return ", ".join(
        tag
        for tag in tags
        if not tag.isdigit()
        and not any(character.isdigit() for character in tag)
        and len(tag) >= 3
    )


def _mean(values) -> float:
    return sum(values) / len(values) if values else 0.0


def fit(root: pathlib.Path, extra_roots=()) -> dict:
    """The tables, fitted from the truth set.

    The extra roots are read too: the wide set has four metals and
    the narrow one has four more, and a metal's value fitted on four
    materials is a fit on four materials.
    """
    manifest = {}
    statistics = []
    for one in (root, *extra_roots):
        manifest.update(
            {
                entry["asset_id"]: entry
                for entry in json.loads((one / "manifest.json").read_text())
            }
        )
        statistics.extend(json.loads((one / "truth_statistics.json").read_text()))

    spreads: dict[str, list[float]] = collections.defaultdict(list)
    values: dict[str, list[float]] = collections.defaultdict(list)
    hues: dict[str, list[tuple[float, float, float]]] = collections.defaultdict(list)
    # The COLOUR words' own values, and they are fitted on the
    # materials where the colour is the ONLY word that says the
    # colour.
    #
    # "blue" names three materials in the wide set - a blue microfibre
    # at 0.527, a blue carpet at 0.229 and a blue cloth at 0.243 - and
    # their mean is 0.333, which is no material's colour.
    #
    # A colour word's value is its own when the word is ALONE about
    # the colour: a "blue, fabric, fur, microfiber, soft" is a blue
    # thing and the blue says how light it is.
    #
    # So the colour's value is fitted on the materials whose
    # description names that colour and NO other colour.
    colour_values: dict[str, list[float]] = collections.defaultdict(list)
    colour_hues: dict[str, list[tuple[float, float, float]]] = collections.defaultdict(
        list
    )

    for entry in statistics:
        asset_id = entry["asset_id"]
        if asset_id not in manifest:
            continue
        albedo = entry["albedo"]
        words = set(describe(manifest[asset_id]["tags"]).replace(",", " ").split())
        for word in words:
            spreads[word].append(albedo["luma_std"])
            values[word].append(albedo["luma_mean"])
            total = albedo["red_mean"] + albedo["green_mean"] + albedo["blue_mean"]
            if total > 0:
                hues[word].append(
                    (
                        albedo["red_mean"] / total,
                        albedo["green_mean"] / total,
                        albedo["blue_mean"] / total,
                    )
                )
        named = words & set(COLOUR_WORDS)
        if len(named) == 1:
            word = next(iter(named))
            colour_values[word].append(albedo["luma_mean"])
            total = albedo["red_mean"] + albedo["green_mean"] + albedo["blue_mean"]
            if total > 0:
                colour_hues[word].append(
                    (
                        albedo["red_mean"] / total,
                        albedo["green_mean"] / total,
                        albedo["blue_mean"] / total,
                    )
                )

    def table(source, minimum=2):
        """The words with enough materials behind them.

        A word with ONE material behind it is a single reading and
        not a fit - for the SPREAD, which is noisy, one material is
        not enough.
        """
        return {
            word: source[word]
            for word in sorted(source)
            if len(source[word]) >= minimum
        }

    def measured(source):
        """The words with AT LEAST ONE material behind them.

        A word's VALUE and HUE are a measurement and not a fit: a
        single material's luma is its luma, and the lane's pattern
        choice depends on the word being there at all.

        "carpet" names one material in the wide set and the lane has
        a kind for it, and the kind's colour is that material's.
        """
        return {word: source[word] for word in sorted(source) if source[word]}

    return {
        # The METAL words' values, and they are read from the
        # NAMED_COLOURS table and not from the colour words' one -
        # a metal's colour words name the RUST and the WEATHERING on
        # it, and the sheet's own colour comes first.
        #
        # So the metals are fitted on their own: the truth's own gold
        # measures 0.893 and the table said 0.70, and its iron
        # measures 0.745 where the table said 0.42.
        "named_colours": {
            word: round(_mean(values_list), 4)
            for word, values_list in measured(values).items()
            if word in METAL_WORDS
        },
        "spreads": {
            word: round(_mean(values_list), 4)
            for word, values_list in table(spreads).items()
        },
        # The METAL words' spreads, and they are SPECIFIC: "gold"
        # names one material in the wide set and its spread measures
        # 0.0064, and the finish words - "clean" and "smooth" - name
        # eleven and twenty-two and their means are means of nothing
        # in particular.
        "metal_spreads": {
            word: round(_mean(values_list), 4)
            for word, values_list in measured(spreads).items()
            if word in METAL_WORDS
        },
        # The palette keeps the MATERIAL's value and the COLOUR's
        # value apart, and the reason is the reading order: a
        # material says what the surface is made of and a colour says
        # what it looks like, and a description carries both.
        #
        # "brown, clean, floor, parquet, wood" is a WOOD that is
        # BROWN, and the wood's value is the material's and the
        # brown's is the colour's.
        "material_values": {
            word: round(_mean(values_list), 4)
            for word, values_list in measured(values).items()
            if word in MATERIAL_WORDS
        },
        "colour_values": {
            word: round(_mean(values_list), 4)
            for word, values_list in measured(colour_values).items()
            if word in COLOUR_WORDS
        },
        # And the HUES are split the same way: a MATERIAL's hue is
        # tighter than a colour word's, so the palette keeps them
        # apart and reads the material's first.
        "material_hues": {
            word: tuple(round(part, 3) for part in _mean_hue(hues[word]))
            for word in hues
            if hues[word] and word in MATERIAL_WORDS
        },
        "hues": {
            word: tuple(round(part, 3) for part in _mean_hue(colour_hues[word]))
            for word in colour_hues
            if colour_hues[word] and word in COLOUR_WORDS
        },
    }


def _mean_hue(shares) -> tuple[float, float, float]:
    return (
        _mean([share[0] for share in shares]),
        _mean([share[1] for share in shares]),
        _mean([share[2] for share in shares]),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--also",
        type=pathlib.Path,
        action="append",
        default=[],
        help="another truth set to read as well",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the fitted tables into the palette",
    )
    arguments = parser.parse_args()

    tables = fit(arguments.root, arguments.also)
    print(f"fitted on {arguments.root}")
    for name, table in tables.items():
        print(f"  {name}: {len(table)} words")
    if arguments.write:
        print("writing the palette's tables")
        write_tables(tables)
    else:
        for name, table in tables.items():
            print(f"\n{name}:")
            for word, value in table.items():
                print(f"    {word!r}: {value},")


def write_tables(tables: dict) -> None:
    """Write the fitted tables into the palette's source.

    The tables are MERGED and not replaced: a word the truth set does
    not measure - "purple", "pink", "chrome" - keeps the value the
    word's own sense gives it, and only the words the truth set
    carries take the measured one.

    And the TIERS are not touched at all: a tier says which word
    wins when a description names several, and that is a reading
    order and not a measurement.
    """
    source = PALETTE.read_text()
    for name, table in tables.items():
        if name == "metal_spreads":
            continue
        source = _merge_table(source, name, table)
    # The METAL words' spreads go into the SPREADS table too: they
    # are the SPECIFIC words for a metal's variation, and the
    # finish words - "clean" and "smooth" - name eleven and
    # twenty-two materials and their means are means of nothing in
    # particular.
    metal_spreads = tables.get("metal_spreads", {})
    if metal_spreads:
        source = _merge_values(source, "SPREADS", metal_spreads)
    PALETTE.write_text(source)


def _merge_values(source: str, name: str, values: dict) -> str:
    """Merge some values into one table, and leave the rest."""
    marker = f"{name}: dict[str, "
    start = source.find(marker)
    if start < 0:
        raise SystemExit(f"the palette has no table named {name!r}")
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                close = index
                break
    body = source[open_brace + 1 : close]
    existing: dict[str, str] = {}
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split(":", 1)[0].strip().strip("\"'")
        existing[key] = stripped
    lines: list[str] = []
    for word, value in values.items():
        lines.append(f'    "{word}": {value:.4f},')
    for word, line in existing.items():
        if word not in values:
            lines.append(line)
    return (
        source[: open_brace + 1] + "\n" + "\n".join(lines) + "\n}" + source[close + 1 :]
    )


def _merge_table(source: str, name: str, table: dict) -> str:
    """Merge the fitted values into one table, keeping the rest."""
    marker = f"{name.upper()}: dict[str, "
    start = source.find(marker)
    if start < 0:
        raise SystemExit(f"the palette has no table named {name!r}")
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                close = index
                break
    body = source[open_brace + 1 : close]
    # The words the table already carries, and their lines.
    existing: dict[str, str] = {}
    for line in body.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split(":", 1)[0].strip().strip("\"'")
        existing[key] = stripped
    # The fitted words come first, and the rest keep their lines.
    lines: list[str] = []
    for word, value in table.items():
        if isinstance(value, tuple):
            rendered = "(" + ", ".join(f"{part:.3f}" for part in value) + ")"
        else:
            rendered = f"{value:.4f}"
        lines.append(f"    {word!r}: {rendered},")
    for word, line in existing.items():
        if word not in table:
            lines.append(line)
    # The table's own type, and it is not the generic one: the
    # palette's tables are typed so a wrong value is a type error and
    # not a wrong pixel.
    annotation = {
        "SPREADS": "dict[str, float]",
        "NAMED_COLOURS": "dict[str, float]",
        "MATERIAL_VALUES": "dict[str, float]",
        "COLOUR_VALUES": "dict[str, float]",
        "HUES": "dict[str, tuple[float, float, float]]",
        "MATERIAL_HUES": "dict[str, tuple[float, float, float]]",
    }.get(name.upper(), "dict[str, float]")
    return (
        source[:start]
        + f"{name.upper()}: {annotation} = {{"
        + "\n"
        + "\n".join(lines)
        + "\n}"
        + source[close + 1 :]
    )


def _replace_table(source: str, name: str, table: dict) -> str:
    """Replace one table in the palette's source."""
    marker = f"{name.upper()}: dict[str, "
    start = source.find(marker)
    if start < 0:
        raise SystemExit(f"the palette has no table named {name!r}")
    open_brace = source.index("{", start)
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                close = index
                break
    lines = [f"{name.upper()}: dict[str, object] = {{"]
    for word, value in table.items():
        if isinstance(value, tuple):
            rendered = "(" + ", ".join(f"{part:.3f}" for part in value) + ")"
        else:
            rendered = f"{value:.4f}"
        lines.append(f"    {word!r}: {rendered},")
    lines.append("}")
    return source[:start] + "\n".join(lines) + source[close + 1 :]


if __name__ == "__main__":
    main()
