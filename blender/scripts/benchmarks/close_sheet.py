"""The CLOSE sheet: the truth and the recreation, whole AND cropped at one scale.

The texture sheet shows each map whole at two hundred pixels, and a
whole map at two hundred pixels hides a wood's fibre, a marble's
veins and a metal's scratches - the fine structure is a fifth of a
pixel there.

So each row here has four cells: the truth whole, the recreation
whole, then a quarter of each at the TRUTH's own pixel scale. The
recreation is drawn at 2048 and the truth is 1024, so the recreation
is brought down to the truth's size before it is cropped - a crop of
the same pixels shows the same features at the same size.

Run it with the system python - Pillow and NumPy, no Blender:

    python scripts/benchmarks/close_sheet.py --root PATH --out /tmp/sheet --rows 10
"""

from __future__ import annotations

import argparse
import json
import pathlib

from PIL import Image, ImageDraw

CELL_PX = 230
GAP_PX = 6
LABEL_PX = 20
CROP_FRACTION = 0.25


def _truth_map(directory: pathlib.Path) -> pathlib.Path | None:
    for name in ("albedo.png", "albedo.jpg"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _crop(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = int(width * CROP_FRACTION)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _row(truth: Image.Image, ours: Image.Image) -> list[Image.Image]:
    ours_at_truth = ours.resize(truth.size, Image.LANCZOS)
    cells = [truth, ours, _crop(truth), _crop(ours_at_truth)]
    return [cell.resize((CELL_PX, CELL_PX), Image.LANCZOS) for cell in cells]


def build(root: pathlib.Path, out: pathlib.Path, rows_per_page: int) -> list[pathlib.Path]:
    manifest = json.loads((root / "manifest.json").read_text())
    scores_path = root / "recreation_scores.json"
    scores = (
        {entry["asset_id"]: entry for entry in json.loads(scores_path.read_text())}
        if scores_path.is_file()
        else {}
    )
    entries = []
    for entry in manifest:
        asset_id = entry["asset_id"]
        recreated = root / "recreated" / f"{asset_id}_BaseColor.png"
        truth = _truth_map(root / asset_id)
        if recreated.is_file() and truth is not None:
            entries.append((asset_id, entry, truth, recreated))

    pages = []
    out.mkdir(parents=True, exist_ok=True)
    for page_index in range(0, len(entries), rows_per_page):
        page_entries = entries[page_index : page_index + rows_per_page]
        width = 4 * CELL_PX + 5 * GAP_PX
        height = len(page_entries) * (CELL_PX + LABEL_PX + GAP_PX) + GAP_PX
        sheet = Image.new("RGB", (width, height), (24, 24, 24))
        draw = ImageDraw.Draw(sheet)
        for row_index, (asset_id, entry, truth_path, ours_path) in enumerate(page_entries):
            top = GAP_PX + row_index * (CELL_PX + LABEL_PX + GAP_PX)
            score = scores.get(asset_id, {})
            words = ", ".join(
                tag
                for tag in entry.get("tags", [])
                if not any(character.isdigit() for character in tag)
            )
            label = (
                f"{asset_id}  brt {score.get('brightness_ratio', 0):.2f} "
                f"cnt {score.get('contrast_ratio', 0):.2f} "
                f"scl {score.get('scale_ratio', 0):.2f} "
                f"seam {score.get('recreated_seam_ratio', 0):.2f}  | {words}"
            )[:150]
            draw.text((GAP_PX, top), label, fill=(235, 235, 235))
            with Image.open(truth_path) as truth, Image.open(ours_path) as ours:
                cells = _row(truth.convert("RGB"), ours.convert("RGB"))
            for column, cell in enumerate(cells):
                left = GAP_PX + column * (CELL_PX + GAP_PX)
                sheet.paste(cell, (left, top + LABEL_PX))
        page_path = out / f"close_{page_index // rows_per_page + 1:02d}.png"
        sheet.save(page_path)
        pages.append(page_path)
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--rows", type=int, default=10)
    arguments = parser.parse_args()
    for page in build(arguments.root, arguments.out, arguments.rows):
        print(page)


if __name__ == "__main__":
    main()
