"""Register a folder of .glb pieces (a Kenney pack, another project's exports) as a golem kit.

The kit.yaml this writes lists every piece with its measured size, so a new
asset can be assembled from the pieces (procedure §6A) without opening each
file. Sizes are read from the files, never from names: the glTF accessor
min/max of each piece, converted from glTF's y-up frame to Blender's z-up
frame.

Only .glb is read. A .gltf, .fbx, .obj or .blend in the folder is listed as
skipped with its reason; the pack's author exports those formats, golem does
not guess at them.
"""

from __future__ import annotations

import collections
import datetime
import math
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import yaml

from golem_blender.export.glb_report import asset_report, parse_glb
from golem_blender.kitbash.references import slugify

KIT_SCHEMA = "blended-kitbash/kit@1"  # persisted name; see procedure §2
PACK_FAMILY = "pack"
PACK_SOURCE = "pack"
PIECE_STATUS = "approved"
GLB_SUFFIX = ".glb"
SKIPPED_SUFFIXES = (".gltf", ".fbx", ".obj", ".blend")
NOT_READ_REASON = "only .glb is read"
SIZE_ROUNDING_DIGITS = 6
HISTOGRAM_STEP_M = 0.05
HISTOGRAM_TOP_COUNT = 5
GRID_CANDIDATE_COUNT = 3
GRID_TOLERANCE_M = 0.02
# What a .glb the report rejects can raise: a bad container, a mesh without
# POSITION min/max, a truncated chunk.
UNREADABLE_GLB = (ValueError, KeyError, IndexError, TypeError, OSError, struct.error)


@dataclass(frozen=True)
class PackReport:
    kit_yaml: str
    piece_count: int
    skipped: tuple[dict, ...]  # {file, reason}
    # (extent_m rounded to 0.05, how many extents), most common five.
    footprint_histogram: tuple[tuple[float, int], ...]  # X and Y extents
    height_histogram: tuple[tuple[float, int], ...]  # Z extents
    # Up to three footprint values g, the one that most pieces fit first: a
    # piece fits g when both its X and Y extents are within 0.02 m of a
    # whole multiple of g.
    grid_candidates: tuple[float, ...]


def _blender_bounds(
    glb_minimum: tuple[float, float, float], glb_maximum: tuple[float, float, float]
) -> tuple[list[float], list[float]]:
    """Corners of a glTF (x, y up, z) box in Blender's frame: (x, y, z) = (gx, -gz, gy)."""
    minimum = [glb_minimum[0], -glb_maximum[2], glb_minimum[1]]
    maximum = [glb_maximum[0], -glb_minimum[2], glb_maximum[1]]
    return minimum, maximum


def _piece_name(stem: str, taken: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", stem)
    name, suffix = base, 1
    while name in taken:
        suffix += 1
        name = f"{base}_{suffix}"
    taken.add(name)
    return name


def _rounded(value: float) -> float:
    return round(value, SIZE_ROUNDING_DIGITS)


def _histogram(extents_m: list[float]) -> tuple[tuple[float, int], ...]:
    """The most common extents rounded to 0.05 m, commonest first, ties smaller first."""
    counts = collections.Counter(
        round(round(extent / HISTOGRAM_STEP_M) * HISTOGRAM_STEP_M, 2) for extent in extents_m
    )
    ranked = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0]))
    return tuple(ranked[:HISTOGRAM_TOP_COUNT])


def _fits_grid(extent_m: float, grid_m: float) -> bool:
    multiple = round(extent_m / grid_m)
    return multiple >= 1 and abs(extent_m - multiple * grid_m) <= GRID_TOLERANCE_M


def _grid_candidates(
    footprints_m: list[tuple[float, float]], histogram: tuple[tuple[float, int], ...]
) -> tuple[float, ...]:
    def pieces_fitting(grid_m: float) -> int:
        return sum(
            1
            for x_m, y_m in footprints_m
            if _fits_grid(x_m, grid_m) and _fits_grid(y_m, grid_m)
        )

    candidates = [value for value, _ in histogram if value > 0]
    ranked = sorted(candidates, key=lambda grid_m: (-pieces_fitting(grid_m), -grid_m))
    return tuple(ranked[:GRID_CANDIDATE_COUNT])


def register_pack(pack_dir: Path, kit_dir: Path, kit_name: str, license: str) -> PackReport:
    """Write kit_dir/kit.yaml listing every .glb under pack_dir as an approved piece with its measured size."""
    pack_dir, kit_dir = Path(pack_dir), Path(kit_dir)
    kit_yaml_path = kit_dir / "kit.yaml"
    if kit_yaml_path.exists():
        raise FileExistsError(f"{kit_yaml_path} already exists; a kit is registered once")
    if not pack_dir.is_dir():
        raise NotADirectoryError(f"{pack_dir} is not a directory")

    skipped: list[dict] = []
    catalog: list[dict] = []
    taken_names: set[str] = set()
    for path in sorted(pack_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = str(path.relative_to(pack_dir))
        suffix = path.suffix.lower()
        if suffix in SKIPPED_SUFFIXES:
            skipped.append({"file": relative, "reason": NOT_READ_REASON})
            continue
        if suffix != GLB_SUFFIX:
            continue
        try:
            report = asset_report(path)
            gltf, _ = parse_glb(path)
        except UNREADABLE_GLB as error:
            skipped.append({"file": relative, "reason": f"{type(error).__name__}: {error}"})
            continue
        if not all(math.isfinite(value) for value in (*report.minimum_corner_m, *report.maximum_corner_m)):
            skipped.append({"file": relative, "reason": "no mesh geometry"})
            continue
        minimum, maximum = _blender_bounds(report.minimum_corner_m, report.maximum_corner_m)
        catalog.append(
            {
                "name": _piece_name(path.stem, taken_names),
                "family": PACK_FAMILY,
                "class": PACK_FAMILY,
                "source": PACK_SOURCE,
                "glb": str(path.resolve()),
                "size_m": [_rounded(high - low) for low, high in zip(minimum, maximum)],
                "bounds_min_m": [_rounded(value) for value in minimum],
                "bounds_max_m": [_rounded(value) for value in maximum],
                "triangles": report.triangle_count,
                "materials": [
                    material["name"] for material in gltf.get("materials", []) if material.get("name")
                ],
                "status": PIECE_STATUS,
            }
        )
    if not catalog:
        raise ValueError(f"no readable .glb under {pack_dir}; skipped: {skipped}")

    kit = {
        "schema": KIT_SCHEMA,
        "name": kit_name,
        "slug": slugify(kit_name),
        "units": None,
        "style": None,
        "pack": {
            "source_dir": str(pack_dir.resolve()),
            "license": license,
            "registered": datetime.datetime.now(datetime.UTC).date().isoformat(),
            "skipped": skipped,
        },
        "catalog": catalog,
    }
    kit_dir.mkdir(parents=True, exist_ok=True)
    kit_yaml_path.write_text(yaml.safe_dump(kit, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if len(yaml.safe_load(kit_yaml_path.read_text(encoding="utf-8"))["catalog"]) != len(catalog):
        raise RuntimeError(f"{kit_yaml_path} does not read back as the {len(catalog)} pieces written")

    footprints_m = [(piece["size_m"][0], piece["size_m"][1]) for piece in catalog]
    footprint_histogram = _histogram([extent for footprint in footprints_m for extent in footprint])
    return PackReport(
        kit_yaml=str(kit_yaml_path),
        piece_count=len(catalog),
        skipped=tuple(skipped),
        footprint_histogram=footprint_histogram,
        height_histogram=_histogram([piece["size_m"][2] for piece in catalog]),
        grid_candidates=_grid_candidates(footprints_m, footprint_histogram),
    )
