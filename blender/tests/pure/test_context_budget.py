"""OT-23: the composition splits the assembled prompt faithfully, counts
with an injected tokenizer, refuses to estimate, and writes one spec row."""

from __future__ import annotations

import pytest

from blended.agent.context_budget import (
    SPEC_ROW_LABEL,
    TokenizerUnreachable,
    bmb_tokenizer,
    composition,
    prompt_parts,
    render_table,
    spec_row,
    write_spec_row,
)
from blended.agent.tools import TOOL_SCHEMAS


def _words(text: str) -> int:
    return len(text.split())


def test_every_part_is_a_verbatim_substring_and_the_remainder_is_small():
    whole, parts = prompt_parts(revision=12)
    assert [p.name for p in parts] == [
        "working agreement v12",
        "conventions",
        "manifest: gate fields + budget",
        "manifest: drift catalog",
    ]
    assert all(p.text in whole for p in parts)
    covered = sum(len(p.text) for p in parts)
    assert 0 < len(whole) - covered < 2000  # the template's own scaffolding


def test_the_composition_sums_and_names_both_lanes():
    rows = composition(_words, TOOL_SCHEMAS, revision=12)
    names = [r.name.strip() for r in rows]
    assert names[0] == "system prompt (assembled)"
    assert (
        "STATIC PER CALL, OpenAI/Ollama lanes" in names
        and "STATIC PER CALL, Claude Code lane" in names
    )
    by = {r.name.strip(): r for r in rows}
    # The five parts plus the scaffolding remainder sum to the whole exactly.
    prompt_rows = rows[1:6]
    assert prompt_rows[-1].name.strip() == "template scaffolding (remainder)"
    assert sum(r.tokens for r in prompt_rows) == by["system prompt (assembled)"].tokens
    assert (
        by["STATIC PER CALL, OpenAI/Ollama lanes"].tokens
        == by["system prompt (assembled)"].tokens
        + by["tools: OpenAI/Ollama `tools` field (offered)"].tokens
    )
    assert (
        by["of which op tools"].tokens + by["of which service tools"].tokens
        <= by["tools: OpenAI/Ollama `tools` field (offered)"].tokens + 2
    )
    table = render_table(rows, "words")
    assert table.startswith("| part | chars | tokens (words) |")
    assert "| STATIC PER CALL, Claude Code lane |  |" in table


def test_an_unreachable_tokenizer_refuses_instead_of_estimating(tmp_path):
    key = tmp_path / "key"
    key.write_text("0" * 64)
    tokenize = bmb_tokenizer("http://127.0.0.1:9", key)
    with pytest.raises(TokenizerUnreachable, match="bmb tokenizer"):
        tokenize("hello")


def test_the_spec_row_is_written_once_and_replaced_in_place(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text(
        "| Fact | Value | Evidence |\n|---|---|---|\n| The agent's tool surface | x | y |\n| Briefs | 5 | z |\n"
    )
    rows = composition(_words, TOOL_SCHEMAS, revision=12)
    row = spec_row(rows, "words", "2026-09-10")
    assert row.startswith(SPEC_ROW_LABEL) and "static per call" in row
    write_spec_row(spec, row)
    write_spec_row(spec, row.replace("2026-09-10", "2026-09-11"))
    text = spec.read_text()
    assert text.count(SPEC_ROW_LABEL) == 1 and "2026-09-11" in text
    assert text.splitlines()[3].startswith(SPEC_ROW_LABEL)
