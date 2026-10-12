"""Split one call's static tokens into its parts, per lane (OT-23).

    .venv/bin/python scripts/context_composition.py            # table on stdout
    .venv/bin/python scripts/context_composition.py --spec     # also rewrite the spec row
    .venv/bin/python scripts/context_composition.py --lane chat --revision 12

Counts with bmb's llama-server tokenizer (the local lane's own). If bmb
is unreachable the script exits 2 rather than estimate.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.agent.context_budget import (
    TokenizerUnreachable,
    bmb_tokenizer,
    composition,
    render_table,
    spec_row,
    write_spec_row,
)
from blended.agent.loop import BMB_API_KEY_FILE, BMB_ENDPOINT
from blended.agent.tool_disclosure import core_ops, offered_tools
from blended.agent.tools import SERVICE_TOOL_NAMES, TOOL_SCHEMAS

SPEC_PATH = REPOSITORY_ROOT / "docs" / "2026-09-10-specification-and-requirements.md"
TOKENIZER_NAME = "bmb qwen3.8-27b tokenizer"


def main(argv) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--revision", type=int, default=None)
    parser.add_argument("--lane", default=None)
    parser.add_argument("--spec", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        # What a call CARRIES (OT-25), not the whole set: the disclosed surface.
        offered = offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
        rows = composition(
            bmb_tokenizer(BMB_ENDPOINT, BMB_API_KEY_FILE),
            offered,
            arguments.revision,
            arguments.lane,
        )
    except TokenizerUnreachable as error:
        print(f"[composition] REFUSED: {error}", file=sys.stderr)
        return 2
    print(render_table(rows, TOKENIZER_NAME))
    if arguments.spec:
        revision_text = (
            f", working agreement v{arguments.revision}" if arguments.revision else ""
        ) + f", {len(offered)} of {len(TOOL_SCHEMAS)} tools offered (OT-25)"
        row = spec_row(
            rows,
            TOKENIZER_NAME,
            _datetime.datetime.now(_datetime.UTC).date().isoformat(),
            revision_text,
        )
        write_spec_row(SPEC_PATH, row)
        print(f"[composition] spec row written to {SPEC_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
