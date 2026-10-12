"""Renders the conversational agent's system prompt.

Distinct from `manifest.build_manifest()`, which is a one-shot brief for
"write this script". This is for a modeling PARTNER the user chats with
inside Blender across many turns: it establishes the working
relationship, the tool discipline, and — most importantly — what
counts as done.

The core instruction is the one the whole harness exists to enforce:
running without an error is not success, and a render that looks right
is not success. The analyzer gate decides.

This module is the ASSEMBLER. It gathers what only code can know — the
version pin, the conventions, the live ops manifest and its drift traps
— and hands them to `prompts/system_prompt.md.j2`. The prose lives in
`prompts/`; the tunable working agreement is an addressable revision in
`prompt_versions.py`, so a convergence run can cite exactly which text
it scored and roll back to its predecessor.

The user never writes any of this: non-experts design prompts
opportunistically and the result is brittle (Why Johnny Can't Prompt,
DOI 10.1145/3544548.3581388), so the chat takes plain words and the
harness supplies the agreement.
"""

from __future__ import annotations

import hashlib

SYSTEM_PROMPT_TEMPLATE = "system_prompt"
# The manifest headings the prompt slices between: the gate's fields and
# budget, then the drift catalog, up to the one-shot output contract,
# which tells a script writer to "return only Python" and is wrong in a
# chat where the agent also talks to the user. The operations section
# between the manifest's operations heading and the gate heading is NOT
# rendered (OT-24): the tool schemas carry the ops.
GATE_HEADING = "## What the gate measures"
OUTPUT_CONTRACT_HEADING = "## Your output"


def build_system_prompt(
    revision: int | None = None,
    lane: str | None = None,
) -> str:
    """Render the system prompt for an interactive modeling session.

    `revision` selects the working-agreement revision; `None` uses the
    active one. Unknown revisions raise rather than defaulting — see
    `prompt_versions.get_revision`.

    `lane` selects which capability modules load, and defaults to NONE.
    That default is deliberate: with no lane this renders exactly the
    text the convergence loop scored, so every existing measurement
    keeps meaning what it meant. Skills are opt-in per turn until a run
    has scored them — see `skill_modules`, and the -1.3 pp that
    self-authored skills measured there. Unknown lanes raise.

    The manifest's operations section is NOT rendered (OT-24): the
    generated tool schemas are the one description of each op, and the
    prose copy cost 3,074 tokens per call on bmb's tokenizer for the
    same information. Conventions, the gate's fields and budget, and
    the drift catalog stay.
    """
    from blended.agent.prompt_templates import render
    from blended.agent.prompt_versions import get_revision
    from blended.manifest import CONVENTIONS, build_manifest
    from blended.version import TARGET_BLENDER_SERIES

    skills_text = ""
    if lane is not None:
        from blended.agent.skill_modules import render_modules

        skills_text = render_modules(lane)

    conventions_text = "\n".join(
        f"{index}. {rule}" for index, rule in enumerate(CONVENTIONS, 1)
    )
    manifest_text = build_manifest()
    gate_and_traps_text = manifest_slice(
        manifest_text, GATE_HEADING, OUTPUT_CONTRACT_HEADING
    )

    return render(
        SYSTEM_PROMPT_TEMPLATE,
        blender_series=(f"{TARGET_BLENDER_SERIES[0]}.{TARGET_BLENDER_SERIES[1]}"),
        working_agreement=get_revision(revision).body,
        skills=skills_text,
        conventions=conventions_text,
        gate_and_traps=gate_and_traps_text,
    )


def manifest_slice(manifest_text: str, start_heading: str, end_heading: str) -> str:
    """The manifest between two headings, loudly: a renamed heading is an
    error, not a silent -1 slice."""
    start = manifest_text.find(start_heading)
    end = manifest_text.find(end_heading)
    if start < 0 or end < 0 or end < start:
        raise ValueError(
            f"manifest headings {start_heading!r} .. {end_heading!r} not found in order"
        )
    return manifest_text[start:end]


# The identity in prompt_versions covers the working-agreement body. It
# does NOT cover the conventions, the operations manifest, the drift
# catalog or the skill modules, all of which the model reads on every
# turn: a drift row edited today moved the prompt by 695 characters
# while the pinned identity did not move at all. This is the hash of
# the text that actually ran.
ASSEMBLED_FINGERPRINT_DIGEST_CHARACTERS = 12


def assembled_prompt_fingerprint(
    revision: int | None = None, lane: str | None = None
) -> str:
    """Content hash of the assembled system prompt: `a{revision}:{hex12}`.

    Prefixed `a` so it can never be mistaken in a log for the
    working-agreement identity's `v` prefix.
    """
    from blended.agent.prompt_versions import get_revision

    assembled = build_system_prompt(revision=revision, lane=lane)
    digest = hashlib.sha256(assembled.encode("utf-8")).hexdigest()
    return (
        f"a{get_revision(revision).revision}:"
        f"{digest[:ASSEMBLED_FINGERPRINT_DIGEST_CHARACTERS]}"
    )
