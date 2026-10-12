"""Rank the ops the escape hatch is asking for (OT-12).

    .venv/bin/python scripts/mine_candidate_ops.py --from-iteration 68
    .venv/bin/python scripts/mine_candidate_ops.py --from-iteration 68 \
        --transcript logs/chat-2026-09-10-120000.jsonl

Reads iteration records (v2: with `tool_events`) and chat transcripts
(schema 2) and writes a dated Markdown report. A record without
structured tool events predates OT-8 and is REFUSED, not skipped: run
with --from-iteration to select the mineable range.
"""

import argparse
import datetime as _datetime
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.evaluate.candidate_ops import (
    UnminableRecord,
    hatch_events_from_transcript,
    load_records,
    render_report,
)

DEFAULT_REPORT_DIRECTORY = REPOSITORY_ROOT / "docs" / "candidate_ops"


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log", default=str(REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl")
    )
    parser.add_argument("--from-iteration", type=int, default=None)
    parser.add_argument("--transcript", action="append", default=[])
    parser.add_argument("--out", default=None)
    arguments = parser.parse_args(argv)

    today = _datetime.datetime.now(_datetime.UTC).date()
    records = load_records(Path(arguments.log), arguments.from_iteration)
    transcripts = {}
    try:
        for path in arguments.transcript:
            rows = [
                json.loads(line)
                for line in Path(path).read_text().splitlines()
                if line.strip()
            ]
            name = Path(path).name
            if name in transcripts:
                raise SystemExit(
                    f"two --transcript files are named {name!r}: the report keys "
                    f"events by file name, so one would silently replace the other"
                )
            transcripts[name] = hatch_events_from_transcript(name, rows)
        report = render_report(records, transcripts, today)
    except UnminableRecord as error:
        print(f"[mine] REFUSED: {error}", file=sys.stderr)
        print(
            "[mine] pass --from-iteration to select records written after OT-8",
            file=sys.stderr,
        )
        return 2
    out = (
        Path(arguments.out)
        if arguments.out
        else DEFAULT_REPORT_DIRECTORY / f"{today.isoformat()}-candidate-ops.md"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"[mine] wrote {out}")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
