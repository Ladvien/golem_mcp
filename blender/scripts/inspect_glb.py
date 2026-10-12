"""Inspect a shipped ``.glb`` without Blender.

    python3 scripts/inspect_glb.py <path> [--baseline <path>]

Pure Python — reads the file's own bytes via
``blended.export.glb_report``, so it runs anywhere the pure tier runs.
"""

import argparse
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("glb", type=Path, help="the .glb file to report on")
    parser.add_argument("--baseline", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv) -> int:
    from blended.export.glb_report import asset_report, format_glb_report

    arguments = parse_arguments(argv)
    report = asset_report(arguments.glb)
    baseline = asset_report(arguments.baseline) if arguments.baseline else None
    print(format_glb_report(report, baseline))
    return 0


if "--" in sys.argv:
    extra_arguments = sys.argv[sys.argv.index("--") + 1 :]
else:
    extra_arguments = sys.argv[1:]
raise SystemExit(main(extra_arguments))
