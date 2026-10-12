"""What one call to the model is made of, in tokens (OT-23).

`TurnCost` measures what a call cost in total. This module splits the
static prefix of a call — the assembled system prompt and the tool
schemas as each lane sends them — into the parts a person can act on,
and counts each with the lane's OWN tokenizer where one is reachable
(bmb's llama-server `/tokenize`). Nothing here estimates silently: a
count is either the named tokenizer's or the script refuses.

Measured 2026-09-10 (bmb tokenizer, v12, 56 tools): 7,569 tokens of
system prompt of which the operations section is 3,074, and 7,407 of
tool schemas of which 6,254 are the 48 op tools — 15.0k static tokens
per call, every op described twice.

Pure: strings and a caller-supplied `tokenize` function; the bmb client
is the one network-touching helper and is injected, never implicit.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from blended.agent.system_prompt import (
    GATE_HEADING,
    OUTPUT_CONTRACT_HEADING,
    build_system_prompt,
    manifest_slice,
)

# The drift catalog's heading inside the manifest's gate-and-traps slice.
# Asserted present, never searched for with a silent -1.
DRIFT_HEADING = "## Known API traps"
BMB_TOKENIZE_PATH = "/upstream/qwen3.8-27b/tokenize"
TOKENIZE_TIMEOUT_SECONDS = 120


class TokenizerUnreachable(RuntimeError):
    """The lane's tokenizer did not answer; no estimate stands in for it."""


@dataclass(frozen=True)
class Part:
    name: str
    text: str


def prompt_parts(
    revision: int | None = None, lane: str | None = None
) -> tuple[str, list[Part]]:
    """The assembled system prompt and its parts, each a verbatim substring."""
    from blended.agent.prompt_versions import get_revision
    from blended.manifest import CONVENTIONS, build_manifest

    whole = build_system_prompt(revision=revision, lane=lane)
    agreement = get_revision(revision).body
    conventions = "\n".join(
        f"{index}. {rule}" for index, rule in enumerate(CONVENTIONS, 1)
    )
    manifest = build_manifest()
    parts = [
        Part(f"working agreement v{get_revision(revision).revision}", agreement),
        Part("conventions", conventions),
        # The operations section is measured from the manifest but is no
        # longer in the prompt (OT-24); the schemas carry the ops.
        Part(
            "manifest: gate fields + budget",
            manifest_slice(manifest, GATE_HEADING, DRIFT_HEADING),
        ),
        Part(
            "manifest: drift catalog",
            manifest_slice(manifest, DRIFT_HEADING, OUTPUT_CONTRACT_HEADING),
        ),
    ]
    if lane is not None:
        from blended.agent.skill_modules import render_modules

        parts.append(Part(f"skills ({lane})", render_modules(lane)))
    for part in parts:
        if part.text and part.text not in whole:
            raise ValueError(
                f"part {part.name!r} is not a substring of the assembled prompt"
            )
    return whole, parts


def tool_parts(tools: list[dict]) -> list[Part]:
    """The OFFERED tool set as each lane puts it on the wire (OT-25: the
    service tools, the readers and the core; the rest ride search_ops)."""
    from blended.agent.claude_code import TOOL_PROTOCOL_NOTE, envelope_schema
    from blended.agent.tools import OP_TOOL_SCHEMAS, SERVICE_TOOL_SCHEMAS

    return [
        Part("tools: OpenAI/Ollama `tools` field (offered)", json.dumps(tools)),
        Part(
            "  of which op tools",
            json.dumps([t for t in tools if t in OP_TOOL_SCHEMAS]),
        ),
        Part(
            "  of which service tools",
            json.dumps([t for t in tools if t in SERVICE_TOOL_SCHEMAS]),
        ),
        Part(
            "tools: Claude Code envelope + protocol note",
            json.dumps(envelope_schema(tools)) + "\n\n" + TOOL_PROTOCOL_NOTE,
        ),
    ]


def bmb_tokenizer(endpoint: str, api_key_path: Path) -> Callable[[str], int]:
    """A `tokenize(text) -> int` bound to bmb's llama-server; loud when it is down."""
    try:
        key = api_key_path.read_text().strip()
    except OSError as error:
        raise TokenizerUnreachable(f"bmb api key at {api_key_path}: {error}") from error

    def tokenize(text: str) -> int:
        request = urllib.request.Request(
            endpoint.rstrip("/") + BMB_TOKENIZE_PATH,
            data=json.dumps({"content": text}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=TOKENIZE_TIMEOUT_SECONDS
            ) as reply:
                return len(json.loads(reply.read())["tokens"])
        except (OSError, KeyError, ValueError) as error:
            raise TokenizerUnreachable(
                f"bmb tokenizer at {endpoint}: {error}"
            ) from error

    return tokenize


@dataclass(frozen=True)
class CountedPart:
    name: str
    characters: int
    tokens: int


def count_parts(parts: list[Part], tokenize: Callable[[str], int]) -> list[CountedPart]:
    return [
        CountedPart(part.name, len(part.text), tokenize(part.text) if part.text else 0)
        for part in parts
    ]


def composition(
    tokenize: Callable[[str], int],
    tools: list[dict],
    revision: int | None = None,
    lane: str | None = None,
) -> list[CountedPart]:
    """Every row of the table: prompt parts, the scaffolding remainder, the tools, totals."""
    whole, parts = prompt_parts(revision, lane)
    counted = count_parts(parts, tokenize)
    whole_tokens = tokenize(whole)
    scaffolding_tokens = whole_tokens - sum(row.tokens for row in counted)
    scaffolding_chars = len(whole) - sum(row.characters for row in counted)
    rows = [
        CountedPart("system prompt (assembled)", len(whole), whole_tokens),
        *[CountedPart("  " + row.name, row.characters, row.tokens) for row in counted],
        CountedPart(
            "  template scaffolding (remainder)", scaffolding_chars, scaffolding_tokens
        ),
    ]
    tools_counted = count_parts(tool_parts(tools), tokenize)
    rows.extend(tools_counted)
    static_openai = whole_tokens + tools_counted[0].tokens
    static_cli = whole_tokens + tools_counted[3].tokens
    rows.append(CountedPart("STATIC PER CALL, OpenAI/Ollama lanes", 0, static_openai))
    rows.append(CountedPart("STATIC PER CALL, Claude Code lane", 0, static_cli))
    return rows


def render_table(rows: list[CountedPart], tokenizer_name: str) -> str:
    lines = [f"| part | chars | tokens ({tokenizer_name}) |", "|---|---:|---:|"]
    for row in rows:
        chars = f"{row.characters:,}" if row.characters else ""
        lines.append(f"| {row.name} | {chars} | {row.tokens:,} |")
    return "\n".join(lines)


SPEC_ROW_LABEL = "| Context per call |"


def spec_row(
    rows: list[CountedPart],
    tokenizer_name: str,
    date_text: str,
    revision_text: str = "",
) -> str:
    by_name = {row.name.strip(): row for row in rows}
    whole = by_name["system prompt (assembled)"]
    tools_all = by_name["tools: OpenAI/Ollama `tools` field (offered)"]
    op_tools = by_name["of which op tools"]
    cli = by_name["tools: Claude Code envelope + protocol note"]
    static_openai = by_name["STATIC PER CALL, OpenAI/Ollama lanes"]
    static_cli = by_name["STATIC PER CALL, Claude Code lane"]
    return (
        f"{SPEC_ROW_LABEL} {tokenizer_name}, {date_text}{revision_text}: system prompt {whole.tokens:,} "
        f"(no operations section since OT-24); tools {tools_all.tokens:,} on the OpenAI/Ollama lanes "
        f"(op tools {op_tools.tokens:,}), {cli.tokens:,} as the Claude Code envelope; "
        f"static per call {static_openai.tokens:,} / {static_cli.tokens:,} before scene and history "
        f"| `scripts/context_composition.py` |"
    )


def write_spec_row(
    spec_path: Path, row: str, after_label: str = "| The agent's tool surface |"
) -> None:
    """Insert or replace the context row in the measured-state table, idempotently."""
    lines = spec_path.read_text().splitlines()
    existing = [
        index for index, line in enumerate(lines) if line.startswith(SPEC_ROW_LABEL)
    ]
    if existing:
        lines[existing[0]] = row
    else:
        anchor = next(
            (index for index, line in enumerate(lines) if line.startswith(after_label)),
            None,
        )
        if anchor is None:
            raise ValueError(
                f"{spec_path} has no row starting {after_label!r} to insert the context row after"
            )
        lines.insert(anchor + 1, row)
    spec_path.write_text("\n".join(lines) + "\n")
