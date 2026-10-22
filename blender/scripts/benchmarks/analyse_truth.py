"""What the TRUTH actually is, in numbers a pattern can be built from.

The score says how close a recreation is. It does not say what the
truth's own structure is - how bright its stones are against its
matrix, how much of a brick's own face is flat, how wide its rows
are. A pattern is built from those numbers, so they have to be
measured, not guessed.

So this reads the truth's own map and reports:
  - the luma's percentiles, and the SPREAD between them: a surface's
    contrast is the gap between its darks and its lights, and a
    pattern has to reproduce that gap.
  - the luma's HISTOGRAM's shape, and how much of the surface is at
    each level: a gravel is bimodal (the stones and the matrix) and
    a plaster is unimodal.
  - the DIRECTIONAL structure: how the luma varies along a row
    against down a column, which is what tells a grain from a
    course from a sheet.

Run it with the system python - it needs only Pillow and NumPy.

    python scripts/benchmarks/analyse_truth.py [--root PATH] [NAME ...]
"""

from __future__ import annotations

import argparse
import json
import pathlib

import numpy
from PIL import Image

DEFAULT_ROOT = pathlib.Path(
    "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg"
)


def luma(path: pathlib.Path) -> numpy.ndarray:
    """The map's luma, as the viewer reads it."""
    with Image.open(path) as image:
        array = numpy.asarray(image.convert("RGB"), dtype=numpy.float32) / 255.0
    return 0.2126 * array[:, :, 0] + 0.7152 * array[:, :, 1] + 0.0722 * array[:, :, 2]


def analyse(path: pathlib.Path) -> dict:
    """What the map is, in numbers."""
    values = luma(path)
    height, width = values.shape

    percentiles = {
        f"p{percentile}": float(numpy.percentile(values, percentile))
        for percentile in (1, 5, 25, 50, 75, 95, 99)
    }

    # The HISTOGRAM's shape, and this is what separates a gravel from
    # a plaster. A gravel is two populations - the stones and the
    # matrix - and a plaster is one.
    counts, _edges = numpy.histogram(values, bins=32, range=(0.0, 1.0))
    counts = counts.astype(numpy.float64) / max(1.0, counts.sum())
    # The peak, and the second peak's height: two peaks of similar
    # height is a bimodal surface.
    order = numpy.argsort(counts)[::-1]
    peak = float(counts[order[0]])
    second = float(counts[order[1]]) if len(order) > 1 else 0.0
    # The VALLEY between them: a deep valley is two separate
    # populations and a shallow one is one.
    valley = float(counts[order[:3]].min())

    # The DIRECTIONAL structure: the row-to-row change against the
    # column-to-column change. A grain runs one way and the other
    # way it is smooth.
    row_change = float(numpy.abs(numpy.diff(values, axis=0)).mean())
    column_change = float(numpy.abs(numpy.diff(values, axis=1)).mean())

    # The FLATNESS: how much of the surface is at one level. A brick's
    # face is flat and a gravel's stone is flat, and the measure is
    # the share of pixels within a narrow band of the median.
    median = float(numpy.median(values))
    flat_share = float((numpy.abs(values - median) < 0.03).mean())

    return {
        "mean": float(values.mean()),
        "std": float(values.std()),
        "percentiles": percentiles,
        "histogram_peak": peak,
        "histogram_second": second,
        "histogram_valley": valley,
        "row_change": row_change,
        "column_change": column_change,
        "flat_share": flat_share,
        "width": width,
        "height": height,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=DEFAULT_ROOT)
    parser.add_argument("names", nargs="*")
    arguments = parser.parse_args()

    manifest = json.loads((arguments.root / "manifest.json").read_text())
    wanted = set(arguments.names)
    for entry in manifest:
        asset_id = entry["asset_id"]
        if wanted and asset_id not in wanted:
            continue
        directory = pathlib.Path(entry["directory"])
        path = directory / "albedo.png"
        if not path.is_file():
            path = directory / "albedo.jpg"
        if not path.is_file():
            continue
        report = analyse(path)
        print(
            f"{asset_id:24s}"
            f" mean {report['mean']:.3f}"
            f" std {report['std']:.3f}"
            f" p5 {report['percentiles']['p5']:.3f}"
            f" p95 {report['percentiles']['p95']:.3f}"
            f" peak {report['histogram_peak']:.3f}"
            f" second {report['histogram_second']:.3f}"
            f" valley {report['histogram_valley']:.3f}"
            f" flat {report['flat_share']:.2f}"
            f" row {report['row_change']:.4f}"
            f" col {report['column_change']:.4f}"
        )


if __name__ == "__main__":
    main()
