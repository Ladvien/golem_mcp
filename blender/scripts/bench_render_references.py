"""Render 3DCodeBench's reference views for a list of instances.

The eval set ships code and two prompts per category and NO images; the
image-to-3D track needs the four turntable views at azimuths 45/135/225/
315 degrees under `benchmark/categories/<inst>/images/Image_0{05,15,25,35}.png`
(bench README, "Reference images for image-to-3D"). This renders them
from each instance's ground-truth factory `data/<inst>/<inst>.py` with
the bench's OWN `core/render.py` in Blender — the same camera, lights,
resolution and samples the scorers' renders use — so a reference view
and a candidate view at the same frame are comparable pixel for pixel
(the RESP pairing, DOI 10.48550/arXiv.2604.11082, needs that).

One Blender process per instance; an instance with all four PNGs and an
OK log is skipped unless `--overwrite`. Exit 1 if any instance is left
without its four views, listing them — never a partial success.

    python3 scripts/bench_render_references.py \
      --bench-root /Users/ladvien/3dcodebench \
      --instances-file bench_sets/instances_holdout.txt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from blended.evaluate.bench_reference_views import (  # ONE definition of the views
    REFERENCE_IMAGES_SUBDIR,
    REFERENCE_VIEW_FILENAMES,
)

DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
# The bench's own orchestrator (core/render.py --timeout) allows one instance
# this long; the same bound here keeps a hung Blender from stalling the sweep.
DEFAULT_TIMEOUT_SECONDS = 240


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--bench-root", required=True)
    parser.add_argument("--instances-file", required=True)
    parser.add_argument("--blender", default=DEFAULT_BLENDER)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="per-instance seconds (default %(default)s, core/render.py's own)",
    )
    return parser.parse_args(argv)


def images_directory(bench_root: Path, instance: str) -> Path:
    return bench_root / REFERENCE_IMAGES_SUBDIR / instance / "images"


def is_rendered(directory: Path) -> bool:
    log_path = directory / "render_log.json"
    if not log_path.exists():
        return False
    if json.loads(log_path.read_text()).get("status") != "OK":
        return False
    return all((directory / name).exists() for name in REFERENCE_VIEW_FILENAMES)


def render_instance(
    bench_root: Path, blender: str, instance: str, timeout_seconds: int
) -> bool:
    factory = bench_root / "data" / instance / f"{instance}.py"
    if not factory.exists():
        print(f"[reference] {instance}: no factory at {factory}", flush=True)
        return False
    output = images_directory(bench_root, instance)
    output.mkdir(parents=True, exist_ok=True)
    # render.py writes the log in a `finally`, so a normal failure overwrites
    # it; a hard crash or a kill does not, and would otherwise pass on the
    # previous run's OK log under --overwrite.
    (output / "render_log.json").unlink(missing_ok=True)
    command = [
        blender,
        "-b",
        "--python",
        str(bench_root / "core" / "render.py"),
        "--",
        "--blender-render",
        "--script",
        str(factory),
        "--output-dir",
        str(output),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=bench_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[reference] {instance}: FAILED (no result in {timeout_seconds}s)",
            flush=True,
        )
        return False
    if not is_rendered(output):
        tail = (completed.stdout + completed.stderr)[-600:]
        print(
            f"[reference] {instance}: FAILED (exit {completed.returncode})\n{tail}",
            flush=True,
        )
        return False
    print(f"[reference] {instance}: four views under {output}", flush=True)
    return True


def main(argv) -> int:
    arguments = parse_arguments(argv)
    bench_root = Path(arguments.bench_root).resolve()
    instances = Path(arguments.instances_file).read_text().split()
    failed: list[str] = []
    for instance in instances:
        if not arguments.overwrite and is_rendered(
            images_directory(bench_root, instance)
        ):
            print(f"[reference] {instance}: already rendered", flush=True)
            continue
        if not render_instance(
            bench_root, arguments.blender, instance, arguments.timeout
        ):
            failed.append(instance)
    if failed:
        print(
            f"[reference] {len(failed)} of {len(instances)} not rendered: {', '.join(failed)}",
            flush=True,
        )
        return 1
    print(
        f"[reference] all {len(instances)} instances have their four views", flush=True
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
