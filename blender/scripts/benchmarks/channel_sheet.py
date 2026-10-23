"""A sheet of whole PBR sets: the truth's albedo, roughness and normal beside the lane's.

    python channel_sheet.py --root <set> --out sheet.png Asset1 Asset2 ...

Reads the truth's maps from <set>/<asset>/ and the lane's set from
<set>/recreated_set/<asset>/ (written by score_pbr_channels.py). The ORM's
green channel is the roughness.
"""

from __future__ import annotations

import argparse
import pathlib

from PIL import Image, ImageDraw

CELL = 220
GAP = 6
LABEL = 16


def _first(directory: pathlib.Path, *names: str):
    for name in names:
        path = directory / name
        if path.is_file():
            return path
    return None


def _cell(path, channel: int | None = None) -> Image.Image:
    if path is None:
        return Image.new("RGB", (CELL, CELL), (60, 0, 0))
    image = Image.open(path).convert("RGB")
    if channel is not None:
        image = image.getchannel(channel).convert("RGB")
    return image.resize((CELL, CELL), Image.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("assets", nargs="+")
    arguments = parser.parse_args()
    root = arguments.root.expanduser()
    columns = (
        "truth albedo",
        "truth roughness",
        "truth normal",
        "ours albedo",
        "ours roughness",
        "ours normal",
    )
    sheet = Image.new(
        "RGB",
        (
            len(columns) * (CELL + GAP) + GAP,
            len(arguments.assets) * (CELL + LABEL + GAP) + GAP,
        ),
        (24, 24, 24),
    )
    draw = ImageDraw.Draw(sheet)
    for row, asset in enumerate(arguments.assets):
        truth = root / asset
        ours = root / "recreated_set" / asset
        cells = (
            _cell(_first(truth, "albedo.png", "albedo.jpg")),
            _cell(_first(truth, "roughness.png", "roughness.jpg")),
            _cell(_first(truth, "normal_gl.png", "normal_gl.jpg")),
            _cell(_first(ours, f"T_{asset}_BaseColor.png")),
            _cell(_first(ours, f"T_{asset}_ORM.png"), channel=1),
            _cell(_first(ours, f"T_{asset}_Normal.png")),
        )
        top = GAP + row * (CELL + LABEL + GAP)
        draw.text((GAP, top), f"{asset}: " + " | ".join(columns), fill=(230, 230, 230))
        for column, image in enumerate(cells):
            sheet.paste(image, (GAP + column * (CELL + GAP), top + LABEL))
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(arguments.out)
    print(arguments.out)


if __name__ == "__main__":
    main()
