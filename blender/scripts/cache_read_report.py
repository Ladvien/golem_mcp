"""Cache-read fraction per run, and a paired before/after comparison (OT-26).

.venv/bin/python scripts/cache_read_report.py --before 78-86 --after 87-91
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.evaluate.cache_report import (
    cache_rows,
    paired_by_brief,
    render_pairs,
    render_rows,
)
from blended.evaluate.iteration_log import IterationLog


def _span(text: str) -> tuple[int, int]:
    first, last = text.split("-", 1)
    return int(first), int(last)


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--log", default=str(REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl")
    )
    parser.add_argument(
        "--before", type=_span, help="inclusive iteration span, e.g. 78-86"
    )
    parser.add_argument(
        "--after", type=_span, help="inclusive iteration span, e.g. 87-91"
    )
    arguments = parser.parse_args(argv)
    rows = cache_rows(IterationLog(Path(arguments.log)).records())
    selected = (
        [
            r
            for r in rows
            if (
                arguments.before
                and arguments.before[0] <= r.iteration <= arguments.before[1]
            )
            or (
                arguments.after
                and arguments.after[0] <= r.iteration <= arguments.after[1]
            )
        ]
        if (arguments.before or arguments.after)
        else rows
    )
    print(render_rows(selected))
    if arguments.before and arguments.after:
        before = [
            r for r in rows if arguments.before[0] <= r.iteration <= arguments.before[1]
        ]
        after = [
            r for r in rows if arguments.after[0] <= r.iteration <= arguments.after[1]
        ]
        print()
        print(render_pairs(paired_by_brief(before, after)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
