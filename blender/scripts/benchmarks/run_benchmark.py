"""Run the benchmark over a truth set and score it, in one process.

The scoring is a SECOND process and not a second phase of the same
one, and the reason is the same as the recreation's: measuring
inside the writing process reads the recreation into Blender, and
the next write's EXR read inherits that datablock - so every file
after the first came out as the first one's pattern.

And the two truth sets are run in turn and each with its OWN root,
because the root is an environment variable and a chain of two
commands with one export in front of them runs the second one
against the wrong set.

    blender --background --factory-startup --python run_benchmark.py -- [--root PATH]... [--label NAME]
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import time

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
HERE = pathlib.Path(__file__).resolve().parent

# The truth sets the benchmark runs over, and the label each is
# reported under.
SETS = (
    ("ambientcg", "the twenty hand-picked sets"),
    ("ambientcg_wide", "the eighty-seven wide sets"),
)


def run(root: pathlib.Path, script: str) -> None:
    """One Blender run, with the root in its environment."""
    environment = dict(os.environ)
    environment["GOLEM_BENCH_ROOT"] = str(root)
    result = subprocess.run(
        [
            BLENDER,
            "--background",
            "--factory-startup",
            "--python",
            str(HERE / script),
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        raise SystemExit(f"{script} failed against {root}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=pathlib.Path,
        default=pathlib.Path.home() / "mnt/codex_fs/game_assets/benchmarks",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="a set's name, to run only that one",
    )
    arguments = parser.parse_args()

    for name, label in SETS:
        if arguments.only and name not in arguments.only:
            continue
        root = arguments.base / name
        if not (root / "manifest.json").is_file():
            print(f"BENCH {name} has no truth set at {root}")
            continue
        print(f"BENCH {name} - {label}")
        started = time.time()
        run(root, "recreate_from_descriptions.py")
        run(root, "score_recreations.py")
        scores = json.loads((root / "recreation_scores.json").read_text())
        for key in ("brightness_ratio", "contrast_ratio", "scale_ratio"):
            mean = sum(row[key] for row in scores) / len(scores)
            print(f"BENCH {name} the mean {key} is {mean:.3f}")
        seam = sum(row["recreated_seam_ratio"] for row in scores) / len(scores)
        truth_seam = sum(row["truth_seam_ratio"] for row in scores) / len(scores)
        print(
            f"BENCH {name} the mean seam is {seam:.2f}x against the truth's {truth_seam:.2f}x"
        )
        print(f"BENCH {name} took {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
