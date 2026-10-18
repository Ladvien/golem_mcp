"""A Blender-hosted script's exit code (OT-32).

Blender runs `--python script.py` inside its own interpreter and does
NOT propagate an uncaught Python exception to its process exit code:

    blender --background --python-expr "raise RuntimeError('boom')" ; echo $?
    0
    blender --background --python-expr "raise SystemExit(3)"        ; echo $?
    3

So a converge run that dies mid-way — the model call 400s, the visual
gate raises, a driver hits a KeyError — reports SUCCESS to every caller
that gates on the exit status. Measured 2026-09-10: iteration 109's
visual gate raised `EmptyFrame` after the build and export, and
`make converge` returned 0; three metered-lane briefs died on HTTP 429
and returned 0 as well, so the chain that ran them recorded four
"successes" it never had. The repo's own closing rule — gate a commit on
`make test-pure` and `make test-blender-app` exit codes, never on a grep
of their output — rests on exit codes meaning what they say.

`SystemExit` IS honoured, so the fix is to catch everything else and
raise one.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable

# What a script exits with when it died of an uncaught exception, as
# opposed to returning a failing status of its own.
UNCAUGHT_EXCEPTION_EXIT_CODE = 70  # EX_SOFTWARE, sysexits.h


def run_script_main(main: Callable[..., int], *arguments) -> int:
    """Call `main(*arguments)` and turn any exception into a real exit code.

    Returns the status to hand to `SystemExit`. A `SystemExit` raised by
    `main` itself passes through with its own code — a script that means
    to exit 2 still exits 2 — and a `KeyboardInterrupt` keeps the
    conventional 130 so an interrupted run is not read as a crash.
    """
    try:
        return int(main(*arguments) or 0)
    except SystemExit as deliberate:
        code = deliberate.code
        if code is None:
            return 0
        return code if isinstance(code, int) else 1
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr, flush=True)
        return 130
    except BaseException:  # noqa: BLE001 — the whole point is to catch it
        traceback.print_exc()
        print(
            f"[exit] uncaught exception -> exit {UNCAUGHT_EXCEPTION_EXIT_CODE}; "
            f"Blender would otherwise have exited 0 and this run would read "
            f"as a success.",
            file=sys.stderr,
            flush=True,
        )
        return UNCAUGHT_EXCEPTION_EXIT_CODE
