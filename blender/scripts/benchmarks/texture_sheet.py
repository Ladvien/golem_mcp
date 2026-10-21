"""The TEXTURE SHEET: every recreated map beside the truth it recreates.

The score says how close a recreation is. It does not say whether it
*looks* like the material - and a recreation can be within 5% on
every measure and still be a plate of cracked mud where the truth is
a gravel.

So this builds a sheet: one row per material, the truth's own
albedo on the left and the recreation's on the right, with the
material's name and the numbers between them. It is the one thing
worth looking at, because a wrong structure is obvious in it and
invisible in the score.

Run it with the system python - it needs only Pillow and NumPy,
and not Blender.

    python scripts/benchmarks/texture_sheet.py [--root PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import pathlib

import numpy
from PIL import Image, ImageDraw

# The truth's own ROOT, and the sheet's default.
DEFAULT_ROOT = pathlib.Path(
    "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg"
)

# How big each cell of the sheet is.
CELL_PX = 200
# The gap between the truth's cell and the recreation's.
GAP_PX = 8
# The label's height.
LABEL_PX = 22


def _luma(path: pathlib.Path) -> numpy.ndarray:
    """The map's luma, as the viewer reads it."""
    with Image.open(path) as image:
        array = numpy.asarray(image.convert("RGB"), dtype=numpy.float32) / 255.0
    return 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]


def _crop_to_square(path: pathlib.Path) -> Image.Image:
    """The map's middle square, so a close crop shows the structure."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        return rgb.crop((left, top, left + side, top + side)).resize(
            (CELL_PX, CELL_PX), Image.LANCZOS
        )


def _features(luma: numpy.ndarray) -> float:
    """The feature count, the way `benchmark.albedo_statistics` does it."""
    height, width = luma.shape
    rows = luma - luma.mean(axis=1, keepdims=True)
    correlation = numpy.zeros(width)
    for row in rows[:: max(1, height // 64)]:
        correlation += numpy.correlate(row, row, mode="full")[width - 1 :]
    if correlation[0]:
        correlation = correlation / correlation[0]
    sign = numpy.sign(correlation)
    crossings = numpy.where(numpy.diff(sign) != 0)[0]
    period = int(crossings[0]) if len(crossings) else 0
    return width / period if period else 0.0


def build(root: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """The sheet, written to `out`; the path is returned."""
    manifest = json.loads((root / "manifest.json").read_text())
    truth = {
        entry["asset_id"]: entry
        for entry in json.loads((root / "truth_statistics.json").read_text())
    }
    recreated = root / "recreated"

    rows = []
    for entry in manifest:
        asset_id = entry["asset_id"]
        if asset_id not in truth:
            continue
        ours = recreated / f"{asset_id}_BaseColor.png"
        theirs = next(iter((root / asset_id).glob("albedo.*")), None)
        if not ours.is_file() or theirs is None:
            continue
        rows.append((asset_id, theirs, ours, truth[asset_id]))

    if not rows:
        raise SystemExit(f"no recreations under {recreated}")

    # The sheet is a GRID: a row per material, the truth's own
    # albedo on the left and the recreation's on the right, and the
    # material's name and its numbers between them.
    #
    # It has to be a grid and not a strip: a strip of twenty is one
    # row, and a row of twenty is a stripe - readable at no zoom.
    cell_width = CELL_PX * 2 + GAP_PX
    per_row = 4
    row_count = (len(rows) + per_row - 1) // per_row
    row_height = CELL_PX + LABEL_PX + GAP_PX
    width = per_row * cell_width + GAP_PX
    sheet = Image.new("RGB", (width, row_count * row_height), (18, 18, 20))
    draw = ImageDraw.Draw(sheet)

    for index, (asset_id, theirs, ours, truth_entry) in enumerate(rows):
        column = index % per_row
        row = index // per_row
        left = GAP_PX + column * cell_width
        top = row * row_height
        sheet.paste(_crop_to_square(theirs), (left, top))
        sheet.paste(_crop_to_square(ours), (left + CELL_PX + GAP_PX, top))

        truth_luma = truth_entry["albedo"]["luma_mean"]
        our_luma = float(_luma(ours).mean())
        their_features = truth_entry["albedo"]["features_across"]
        our_features = _features(_luma(ours))
        draw.text(
            (left, top + CELL_PX + 4),
            f"{asset_id}  {our_luma / truth_luma:.2f}x  {our_features / their_features:.2f}x",
            fill=(210, 210, 210),
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    print(f"SHEET {len(rows)} materials at {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=pathlib.Path,
        default=DEFAULT_ROOT,
        help="the benchmark's root directory",
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="where the sheet is written; the root's own by default",
    )
    arguments = parser.parse_args()
    out = arguments.out or (arguments.root / "contact_sheet.png")
    build(arguments.root, out)


if __name__ == "__main__":
    main()
