"""ProTeGi prompt search: propose ONE validated hunk per round.

The ADJUST half of the convergence loop, as a beam search over prompt
text (10.18653/v1/2023.emnlp-main.494). ProTeGi's shape, kept:

- EXPAND: run the prompt, collect errors, have `LLM∇` describe the
  prompt's flaws (the "gradient"), have `LLM_δ` edit the prompt to fix
  them.
- SELECT: score candidates on a minibatch and keep the best; every
  bandit beat the uniform baseline, and beam beat greedy on all tasks.
- STOP EARLY: "all datasets peaked at around 3 steps", so
  MAXIMUM_SEARCH_ROUNDS is 3, not a number chosen for comfort.

Two deviations from the paper, both measured elsewhere and load-bearing
here:

1. The gradient is computed from DETERMINISTIC GATE OUTPUT ONLY — never
   from the examiner's tags. Intrinsic self-correction degrades without
   an oracle (10.48550/arXiv.2310.01798: GPT-4 GSM8K 95.5 -> 91.5 ->
   89.0), and of Self-Refine's failures 33% mislocalised the error and
   61% proposed an inappropriate fix (10.48550/arXiv.2303.17651 read
   through 10.48550/arXiv.2409.02977). Tool feedback outranks model
   feedback, so only measurements enter the gradient.
2. Every candidate must pass the repo's own discipline before it can
   run: exactly ONE contiguous changed hunk against its predecessor
   (LL3M's surgical-edit rule, enforced by `validate_revisions`), and
   never a hunk that was already rejected — the catastrophic-forgetting
   guard, because a hunk that regressed a brief must not be re-proposed
   in a later session.

No `bpy` here: this module reads text, calls the writer model, and
edits two files on disk.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from blended.agent.prompt_templates import render
from blended.agent.prompt_versions import (
    MAXIMUM_CHANGED_HUNKS_PER_REVISION,
    changed_hunks,
)

# ProTeGi's beam width b=4: measured to beat greedy/flat search on every
# task in the paper (Jailbreak 0.85 vs 0.82/0.80).
CANDIDATES_PER_ROUND = 4
# "the process can begin to overfit on the train data, or get caught in
# a local minima after only a few optimization steps; all datasets
# peaked at around 3 steps."
MAXIMUM_SEARCH_ROUNDS = 3
REJECTED_HUNKS_PATH = Path("_evaluate/rejected_hunks.jsonl")
GRADIENT_TEMPLATE = "gradient"  # prompts/gradient.md.j2
REVISE_TEMPLATE = "revise"  # prompts/revise.md.j2

STRING_BLOCK_WIDTH_CHARACTERS = 60
REGISTRY_FILENAME = "prompt_versions.py"
PROMPTS_DIRECTORY_NAME = "prompts"
REGISTRY_ANCHOR = "PROMPT_REVISIONS: tuple[PromptRevision, ...] = ("
WORKING_AGREEMENT_STEM = "working_agreement_v"


class RevisionRejected(RuntimeError):
    """A candidate revision was refused; both edits were rolled back."""


@dataclass(frozen=True)
class RejectedHunk:
    """A hunk that regressed a brief and may never be re-proposed."""

    hunk: str
    reason: str
    brief_name: str


def gate_evidence(records) -> str:
    """The error set for the gradient: MEASURED failures, verbatim.

    Deliberately excludes the examiner's tags. A prompt edit computed
    from an unverified judgement is the failure mode
    10.48550/arXiv.2310.01798 measured; the gates are the oracle this
    loop has.
    """
    lines: list[str] = []
    for record in records:
        failures = tuple(record.structural_failures) + tuple(record.form_failures)
        if not failures:
            continue
        lines.append(f"BRIEF {record.brief_name} (iteration {record.iteration})")
        lines.append(f"  tool calls: {len(record.tool_calls)}")
        for failure in record.structural_failures:
            lines.append(f"  STRUCTURAL: {failure}")
        for failure in record.form_failures:
            lines.append(f"  FORM: {failure}")
        final_text = (record.agent_final_text or "").strip()
        if final_text:
            lines.append(f"  agent's final report: {final_text}")
    return "\n".join(lines)


def textual_gradient(client, body: str, evidence: str) -> str:
    """What about this TEXT allowed these measured failures (<=5 bullets)."""
    reply = client.chat(
        [
            {
                "role": "user",
                "content": render(GRADIENT_TEMPLATE, body=body, evidence=evidence),
            }
        ]
    )
    return (reply.get("content") or "").strip()


def propose_bodies(client, body: str, gradient: str, count: int) -> list[str]:
    """`count` candidate bodies, each claiming exactly one changed region."""
    prompt = render(REVISE_TEMPLATE, body=body, gradient=gradient)
    candidates: list[str] = []
    for _ in range(count):
        reply = client.chat([{"role": "user", "content": prompt}])
        candidates.append(reply.get("content") or "")
    return candidates


def admissible(previous_body: str, candidate: str, rejected_hunks: set[str]) -> str:
    """Empty string when the candidate may be written; else why it may not."""
    if not candidate.strip():
        return "candidate is empty"
    hunks = changed_hunks(previous_body, candidate)
    if not hunks:
        return "candidate is identical to its predecessor: nothing to attribute"
    if len(hunks) != MAXIMUM_CHANGED_HUNKS_PER_REVISION:
        return (
            f"candidate changes {len(hunks)} separate places, not "
            f"{MAXIMUM_CHANGED_HUNKS_PER_REVISION}: {hunks}"
        )
    if hunks[0] in rejected_hunks:
        return f"hunk {hunks[0]!r} was rejected in an earlier round"
    return ""


def load_rejected_hunks(path: Path = REJECTED_HUNKS_PATH) -> set[str]:
    """Hunk descriptors that regressed a brief, from every earlier session."""
    path = Path(path)
    if not path.exists():
        return set()
    hunks: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            hunks.add(json.loads(line)["hunk"])
    return hunks


def record_rejection(
    hunk: str, reason: str, brief_name: str, path: Path = REJECTED_HUNKS_PATH
) -> None:
    """Remember a hunk that regressed a brief. Append-only, forever."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"hunk": hunk, "reason": reason, "brief_name": brief_name},
                sort_keys=True,
            )
            + "\n"
        )


def _probe_registry(package_directory: Path) -> dict:
    """Import the registry in a FRESH process and report its state.

    A subprocess because this process already has the module imported:
    an edited file would not be re-read, so the validation would score
    the text that is no longer on disk.
    """
    source_root = Path(package_directory).resolve().parents[1]
    code = (
        "import json\n"
        "from blended.agent.prompt_versions import "
        "PROMPT_REVISIONS, validate_revisions\n"
        "print(json.dumps({\n"
        "    'problems': validate_revisions(),\n"
        "    'latest': max(entry.revision for entry in PROMPT_REVISIONS),\n"
        "}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(source_root),
        env={"PYTHONPATH": str(source_root), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RevisionRejected(
            f"the registry did not import: {completed.stderr.strip()[:2000]}"
        )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _python_string_block(value: str, indent: str) -> str:
    """A wrapped, parenthesised string literal in the registry's style.

    The literal evaluates back to the whitespace-normalised `value`:
    chunks are joined by exactly one space, so wrapping must only break
    where the text already had whitespace (no mid-word or after-hyphen
    breaks, which the join would turn into a spurious space), and each
    chunk is escaped so a quote or backslash cannot end or alter the
    literal.
    """
    wrapped = textwrap.wrap(
        " ".join(value.split()),
        width=STRING_BLOCK_WIDTH_CHARACTERS,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    lines = [f"{indent}("]
    for index, chunk in enumerate(wrapped):
        suffix = "" if index == len(wrapped) - 1 else " "
        escaped = json.dumps(chunk, ensure_ascii=False)[1:-1]
        lines.append(f'{indent}    "{escaped}{suffix}"')
    lines.append(f"{indent})")
    return "\n".join(lines)


def _entry_source(revision: int, changed_element: str, hypothesis: str) -> str:
    return (
        "    PromptRevision(\n"
        f"        revision={revision},\n"
        "        changed_element=\n"
        f"{_python_string_block(changed_element, ' ' * 12)},\n"
        "        hypothesis=\n"
        f"{_python_string_block(hypothesis, ' ' * 12)},\n"
        '        outcome="",\n'
        "    ),\n"
    )


def _tuple_close_index(lines: list[str]) -> int:
    """The line index of the `)` that closes PROMPT_REVISIONS."""
    try:
        anchor = next(
            index for index, line in enumerate(lines) if REGISTRY_ANCHOR in line
        )
    except StopIteration as error:
        raise RevisionRejected(f"registry has no {REGISTRY_ANCHOR!r} anchor") from error
    for index in range(anchor + 1, len(lines)):
        if lines[index].rstrip("\n") == ")":
            return index
    raise RevisionRejected("registry's PROMPT_REVISIONS tuple never closes")


def write_revision(
    candidate_body: str,
    changed_element: str,
    hypothesis: str,
    package_directory: Path,
) -> int:
    """Write the next revision: its template AND its registry entry.

    Rolls both edits back and raises `RevisionRejected` if the resulting
    registry fails `validate_revisions()`. `ACTIVE_PROMPT_REVISION` and
    `PINNED_PROMPT_REVISION` are never touched, so a pending candidate
    does not become the text a user chats with, and the "superseded
    without an outcome" rule stays quiet while it is pending.
    """
    package_directory = Path(package_directory)
    registry_path = package_directory / REGISTRY_FILENAME
    original_registry = registry_path.read_text(encoding="utf-8")

    before = _probe_registry(package_directory)
    if before["problems"]:
        raise RevisionRejected(
            f"registry was already unhealthy before the write: {before['problems']}"
        )
    revision = int(before["latest"]) + 1
    template_path = (
        package_directory
        / PROMPTS_DIRECTORY_NAME
        / f"{WORKING_AGREEMENT_STEM}{revision}.md.j2"
    )
    if template_path.exists():
        raise RevisionRejected(
            f"{template_path} already exists — refusing to overwrite a revision"
        )

    lines = original_registry.splitlines(keepends=True)
    close_index = _tuple_close_index(lines)
    edited = (
        "".join(lines[:close_index])
        + _entry_source(revision, changed_element, hypothesis)
        + "".join(lines[close_index:])
    )

    template_path.write_text(candidate_body, encoding="utf-8")
    registry_path.write_text(edited, encoding="utf-8")
    try:
        problems = _probe_registry(package_directory)["problems"]
    except RevisionRejected:
        template_path.unlink()
        registry_path.write_text(original_registry, encoding="utf-8")
        raise
    if problems:
        template_path.unlink()
        registry_path.write_text(original_registry, encoding="utf-8")
        raise RevisionRejected(
            f"v{revision} was refused by validate_revisions(): {problems}"
        )
    return revision


def record_outcome(revision: int, outcome: str, package_directory: Path) -> None:
    """Fill one pending entry's `outcome` from measurement.

    The next edit is only informed if the last one recorded what it
    measured — 3DCodeBench's Experience Library kept in the artifact it
    is about.
    """
    package_directory = Path(package_directory)
    registry_path = package_directory / REGISTRY_FILENAME
    original = registry_path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    revision_marker = re.compile(rf"^\s*revision={revision},\s*$")
    start = next(
        (index for index, line in enumerate(lines) if revision_marker.match(line)),
        None,
    )
    if start is None:
        raise RevisionRejected(f"no registry entry with revision={revision}")
    # The entry ends at its own closing `    ),`; searching past it would
    # fill a LATER revision's outcome with this revision's measurement.
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].rstrip("\n") == "    ),"
        ),
        None,
    )
    if end is None:
        raise RevisionRejected(f"registry entry v{revision} never closes")
    pending = next(
        (index for index in range(start, end) if lines[index].strip() == 'outcome="",'),
        None,
    )
    if pending is None:
        raise RevisionRejected(f"v{revision} has no pending outcome to fill")
    lines[pending] = f"        outcome=\n{_python_string_block(outcome, ' ' * 12)},\n"

    registry_path.write_text("".join(lines), encoding="utf-8")
    try:
        problems = _probe_registry(package_directory)["problems"]
    except RevisionRejected:
        registry_path.write_text(original, encoding="utf-8")
        raise
    if problems:
        registry_path.write_text(original, encoding="utf-8")
        raise RevisionRejected(
            f"recording v{revision}'s outcome broke the registry: {problems}"
        )
