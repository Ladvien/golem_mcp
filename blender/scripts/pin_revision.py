"""Apply a pin proposal: the one human act the loop leaves behind.

    make pin REVISION=11

Reads `_evaluate/pin_proposal.json` (written by `converge_auto.py` when
a full suite cycle ran clean at one prompt identity) and applies it:

* `PINNED_PROMPT_REVISION`, `CONVERGED_ON`, `CONVERGENCE_RUNS`,
  `CONVERGENCE_WRITER_MODEL`, `CONVERGENCE_VISION_MODEL` and
  `CONVERGENCE_TOOL_CALL_BUDGET` in `prompt_versions.py`
  (`ACTIVE_PROMPT_REVISION` follows the pin by construction);
* `_evaluate/golden/pinned_identity.txt`, which the tests read instead
  of a hardcoded hash, so a pin no longer requires hand-editing tests;
* the per-view golden references for the newly pinned revision, by
  running `pin_golden_views.py` inside Blender.

WHY THIS IS NOT AUTOMATIC. Pinning mints the golden renders that every
later examination is compared against, and RESP measured that a wrong
reference is worse than no reference at all (−0.23 F1,
10.48550/arXiv.2604.11082) — while the examiner's own ceiling is recall
around 0.76 with a perfect reference and verifier-human alignment 0.66
against 0.79 inter-human (BlenderGym, 10.48550/arXiv.2504.01786). A
machine verdict may RUN the loop; it may not mint the reference the loop
is measured against.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
os.chdir(REPOSITORY_ROOT)

BLENDER = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
PIN_PROPOSAL_PATH = Path("_evaluate/pin_proposal.json")
PINNED_IDENTITY_PATH = Path("_evaluate/golden/pinned_identity.txt")
REGISTRY_PATH = REPOSITORY_ROOT / "src" / "blended" / "agent" / "prompt_versions.py"


class PinRefused(SystemExit):
    """The proposal and the repository disagree. Nothing was changed."""


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--proposal", default=str(PIN_PROPOSAL_PATH))
    parser.add_argument(
        "--skip-golden-views",
        action="store_true",
        help="apply the registry edits only (the golden views must then be "
        "pinned separately, or the examiner has no reference)",
    )
    return parser.parse_args(argv)


def _replace_assignment(text: str, name: str, value: str) -> str:
    pattern = re.compile(rf"^{name} = .*$", re.MULTILINE)
    if not pattern.search(text):
        raise PinRefused(f"{REGISTRY_PATH} has no `{name} = ...` to rewrite")
    # A function, not a template: `value` is data, and re.sub would read
    # a backslash in it as an escape.
    return pattern.sub(lambda _match: f"{name} = {value}", text, count=1)


def _runs_source(runs) -> str:
    lines = ["("]
    for iteration, brief_name in runs:
        lines.append(f'    ({iteration}, "{brief_name}"),')
    lines.append(")")
    return "\n".join(lines)


def _replace_runs(text: str, runs) -> str:
    rewritten, replaced = re.subn(
        r"^CONVERGENCE_RUNS = \(\n(?:.*\n)*?\)$",
        lambda _match: f"CONVERGENCE_RUNS = {_runs_source(runs)}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if not replaced:
        raise PinRefused(
            f"{REGISTRY_PATH} has no `CONVERGENCE_RUNS = (...)` to rewrite"
        )
    return rewritten


def main(argv=None) -> int:
    arguments = parse_arguments(argv)
    proposal_path = Path(arguments.proposal)
    if not proposal_path.exists():
        raise PinRefused(
            f"no pin proposal at {proposal_path}: a pin is applied FROM a "
            f"converged run, never composed by hand"
        )
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

    if proposal["revision"] != arguments.revision:
        raise PinRefused(
            f"the proposal is for v{proposal['revision']}, you asked to pin "
            f"v{arguments.revision}"
        )

    from blended.agent.prompt_versions import get_revision, validate_revisions

    registry_problems = validate_revisions()
    if registry_problems:
        raise PinRefused(f"registry is not healthy: {registry_problems}")

    revision = get_revision(arguments.revision)
    if revision.identity != proposal["prompt_identity"]:
        raise PinRefused(
            f"v{arguments.revision} now hashes {revision.identity}, but the "
            f"proposal was earned by {proposal['prompt_identity']} — the text "
            f"changed after it converged"
        )
    if not revision.outcome.strip():
        raise PinRefused(
            f"v{arguments.revision} records no outcome: a pinned revision "
            f"must carry what it measured"
        )

    # converge_auto records "" when the runs used more than one model, and
    # an empty name would pin "the runs happened nowhere".
    for model_field in ("writer_model", "vision_model"):
        if not str(proposal[model_field]).strip():
            raise PinRefused(
                f"the proposal names no {model_field}: the runs recorded "
                f"more than one, so there is no single model to pin"
            )
    runs = [(int(iteration), str(brief)) for iteration, brief in proposal["runs"]]
    text = REGISTRY_PATH.read_text(encoding="utf-8")
    text = _replace_assignment(text, "PINNED_PROMPT_REVISION", str(arguments.revision))
    text = _replace_assignment(
        text, "CONVERGED_ON", f'"{proposal["proposed_at"][:10]}"'
    )
    text = _replace_runs(text, runs)
    text = _replace_assignment(
        text, "CONVERGENCE_WRITER_MODEL", f'"{proposal["writer_model"]}"'
    )
    text = _replace_assignment(
        text, "CONVERGENCE_VISION_MODEL", f'"{proposal["vision_model"]}"'
    )
    text = _replace_assignment(
        text, "CONVERGENCE_TOOL_CALL_BUDGET", str(proposal["tool_call_budget"])
    )
    REGISTRY_PATH.write_text(text, encoding="utf-8")
    print(f"[pin] rewrote {REGISTRY_PATH}", flush=True)

    PINNED_IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PINNED_IDENTITY_PATH.write_text(
        proposal["prompt_identity"] + "\n", encoding="utf-8"
    )
    print(
        f"[pin] wrote {PINNED_IDENTITY_PATH}: {proposal['prompt_identity']}",
        flush=True,
    )

    if not arguments.skip_golden_views:
        completed = subprocess.run(
            [
                BLENDER,
                "--background",
                "--factory-startup",
                "--python",
                "scripts/pin_golden_views.py",
                "--",
                "--revision",
                str(arguments.revision),
            ],
            check=False,
        )
        if completed.returncode != 0:
            raise PinRefused(
                f"pin_golden_views failed (exit {completed.returncode}): the "
                f"registry is pinned but the examiner has no reference for "
                f"v{arguments.revision}. Fix and re-run "
                f"`make pin-golden-views REVISION={arguments.revision}`."
            )

    print(
        f"\n[pin] v{arguments.revision} ({proposal['prompt_identity']}) is "
        f"pinned. Examiner: {proposal['examiner_identity']}; calibration "
        f"{proposal['calibration_identity']}.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
