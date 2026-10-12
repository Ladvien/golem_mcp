"""Prompts name tool symbols by hand, so a renamed tool mis-instructs the
writer on every turn.  These tests are the assertion that the names a
prompt cites are names the tool registry actually answers to.

The check is deliberately narrow: only single-backtick identifiers that
*look like a tool call* — ``run_python``, ``inspect_domain``, etc. — are
asserted against the registry.  A draft that scanned all prose scored 50
hits and was right about 3 in the old repo, a 94% false-positive rate,
and a gate that cries wolf gets switched off inside a week.  That
sentence is the reason the pattern below matches
``^(run|inspect|render|search|list|export|save|declare)_[a-z_]+$`` and
nothing broader.

The precision-over-recall design — regex extraction of code-element
references from documentation, matched against the registry — follows
Tan, Wagner & Treude, "Detecting outdated code element references in
software repository documentation", EMSE 2023,
DOI 10.1007/s10664-023-10397-6, §8.3: "we rely on an improved version
of the regular expressions used for code element detection … and then
use a very strict filter (exact match) … we err on the side of caution
to not establish traceability links that we are not confident about."
"""

from __future__ import annotations

import re
from pathlib import Path

from blended.agent.tools import SERVICE_TOOL_SCHEMAS, TOOL_SCHEMAS
from blended.ops._contract import facade_ops

# The probe must have found work to do, so reformatting the prompts away
# turns the gate red instead of green. Measured 2026-09-06: 45
# tool-call-shaped citations across the prompt corpus, so a floor of 10
# leaves room for the corpus to shrink without ever passing vacuously.
MINIMUM_TOOL_CITATIONS_CHECKED = 10

# Single-backtick identifier: ``run_python``, ``inspect_domain``, …
_BACKTICK_IDENTIFIER = re.compile(r"`([a-z_][a-z0-9_]*)`")

# A tool-call-shaped identifier — the narrow pattern explained in the
# module docstring.  Anything matching this but NOT in the registry is a
# prompt citing a tool that no longer exists.
_TOOL_CALL_PATTERN = re.compile(
    r"^(run|inspect|render|search|list|export|save|declare)_[a-z_]+$"
)

# Registered tool names, read from the schema the agent dispatches
# against.  TOOL_SCHEMAS entries are ``{"type": "function", "function":
# {"name": …}}``, so the name lives one level inside each entry.
_REGISTERED_TOOL_NAMES: set[str] = {entry["function"]["name"] for entry in TOOL_SCHEMAS}
# The hand-written service tools: the only ones the verb-prefix pattern
# below is about. Op tools are named by the facade (OT-3) and checked
# against it instead.
_SERVICE_TOOL_NAMES: set[str] = {
    entry["function"]["name"] for entry in SERVICE_TOOL_SCHEMAS
}

_PROMPTS_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "blended" / "agent" / "prompts"
)


def _harvest_citations() -> dict[str, set[str]]:
    """Map each prompt file to the set of tool-call-shaped identifiers it cites."""
    citations: dict[str, set[str]] = {}
    for path in sorted(_PROMPTS_DIR.rglob("*.md.j2")):
        text = path.read_text(encoding="utf-8")
        identifiers = {match.group(1) for match in _BACKTICK_IDENTIFIER.finditer(text)}
        tool_call_ids = {
            ident for ident in identifiers if _TOOL_CALL_PATTERN.match(ident)
        }
        if tool_call_ids:
            citations[str(path.relative_to(_PROMPTS_DIR))] = tool_call_ids
    return citations


def test_found_enough_citations_to_be_meaningful():
    """The probe must have found work to do — at least MINIMUM citations."""
    all_citations = _harvest_citations()
    total = sum(len(ids) for ids in all_citations.values())
    assert total >= MINIMUM_TOOL_CITATIONS_CHECKED, (
        f"only {total} tool-call citations found across "
        f"{len(all_citations)} prompt files; the floor is "
        f"{MINIMUM_TOOL_CITATIONS_CHECKED} so a reformat that erases "
        f"the citations turns this gate red instead of green"
    )


def test_every_cited_tool_name_is_registered():
    """Every tool-call-shaped identifier in a prompt must be a registered tool.

    A prompt naming a renamed tool mis-instructs the writer on every
    turn.  The narrow pattern — ``^(run|inspect|render|search|list|
    export|declare)_[a-z_]+$`` — is deliberate: a broader scan of all
    prose scored 50 hits and was right about 3 in the old repo, a 94%
    false-positive rate, and a gate that cries wolf gets switched off
    inside a week.
    """
    citations = _harvest_citations()
    unregistered: list[str] = []
    for file_name, identifiers in citations.items():
        for ident in identifiers:
            if ident not in _REGISTERED_TOOL_NAMES:
                unregistered.append(f"{file_name}: `{ident}`")
    assert not unregistered, (
        "prompts cite tool names that are not registered in "
        f"TOOL_SCHEMAS: {'; '.join(sorted(unregistered))}"
    )


def test_every_registered_tool_matches_the_call_pattern():
    """Every SERVICE tool must match ``_TOOL_CALL_PATTERN``.

    The prefix whitelist ``(run|inspect|render|search|list|export|declare)``
    is what ties prompt citations to the registry.  If a tool is added
    under a verb the whitelist does not cover (``measure_*``,
    ``capture_*``), it would be cited in prompts, never matched by the
    pattern, and therefore never checked — the exact failure this file
    exists to prevent, silently.  This test makes the gap loud: widen
    the prefix list in ``_TOOL_CALL_PATTERN`` to cover the new verb.
    """
    unmatched = [
        name
        for name in sorted(_SERVICE_TOOL_NAMES)
        if not _TOOL_CALL_PATTERN.match(name)
    ]
    assert not unmatched, (
        "SERVICE_TOOL_SCHEMAS contains tool names that do not match the "
        "citation pattern _TOOL_CALL_PATTERN; add the missing verb "
        f"prefix to the pattern: {'; '.join(unmatched)}"
    )


def test_every_other_registered_tool_is_a_facade_op():
    """The registry is exactly service tools + facade ops (OT-3): a name
    that is neither was hand-added somewhere the generator cannot see."""
    op_names = {name for name, _ in facade_ops()}
    assert _REGISTERED_TOOL_NAMES - _SERVICE_TOOL_NAMES == op_names
