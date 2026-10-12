"""Regression tests for the agent_prompts review slice.

Each test asserts measured behaviour of a path that was wrong before.
"""

import ast
import shutil
from pathlib import Path

import pytest

from blended.agent import prompt_search, prompt_versions
from blended.agent.context_budget import write_spec_row

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKAGE = REPOSITORY_ROOT / "src" / "blended"

# Text the old writer corrupted: a double quote ends the literal, a
# backslash-n becomes a real newline, a hyphen break or an overlong word
# gained a spurious space when the chunks were joined.
HOSTILE_TEXT = (
    'The agent said "stop" early and printed C:\\new\\table; '
    "a state-of-the-art-and-then-some-hyphenated-compound-word-longer-than-sixty-"
    "characters-in-one-token follows; DOI 10.48550/arXiv.2310.01798 ends it."
)


def _evaluate_literal(source: str) -> str:
    # The writer emits a parenthesised run of adjacent string literals;
    # literal_eval folds them exactly as the interpreter does, with no exec.
    return ast.literal_eval(source.strip())


def _package_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "src" / "blended"
    shutil.copytree(
        SOURCE_PACKAGE, destination, ignore=shutil.ignore_patterns("__pycache__")
    )
    return destination / "agent"


def test_string_block_round_trips_quotes_backslashes_and_hyphens():
    source = prompt_search._python_string_block(HOSTILE_TEXT, " " * 4)

    assert _evaluate_literal(source) == " ".join(HOSTILE_TEXT.split())


def test_record_outcome_with_a_quote_and_backslash_keeps_the_registry_healthy(tmp_path):
    package = _package_copy(tmp_path)
    body = prompt_versions.latest_revision().body
    lines = body.splitlines(keepends=True)
    candidate = "".join(lines[:5]) + "One inserted sentence.\n" + "".join(lines[5:])
    revision = prompt_search.write_revision(
        candidate, "one sentence", "expect Z", package
    )

    prompt_search.record_outcome(revision, HOSTILE_TEXT, package)

    probe = prompt_search._probe_registry(package)
    assert probe["problems"] == []
    registry = (package / "prompt_versions.py").read_text(encoding="utf-8")
    assert registry.count("C:\\\\new\\\\table") == 1


def test_record_outcome_restores_the_registry_when_it_no_longer_imports(
    tmp_path, monkeypatch
):
    package = _package_copy(tmp_path)
    body = prompt_versions.latest_revision().body
    lines = body.splitlines(keepends=True)
    candidate = "".join(lines[:5]) + "One inserted sentence.\n" + "".join(lines[5:])
    revision = prompt_search.write_revision(
        candidate, "one sentence", "expect Z", package
    )
    registry_path = package / "prompt_versions.py"
    before = registry_path.read_text(encoding="utf-8")

    def registry_does_not_import(package_directory):
        raise prompt_search.RevisionRejected("the registry did not import: simulated")

    monkeypatch.setattr(prompt_search, "_probe_registry", registry_does_not_import)
    with pytest.raises(prompt_search.RevisionRejected):
        prompt_search.record_outcome(revision, "CONFIRMED", package)

    assert registry_path.read_text(encoding="utf-8") == before


def test_write_spec_row_names_the_missing_anchor(tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("| Something else | x |\n", encoding="utf-8")

    with pytest.raises(ValueError, match="The agent's tool surface"):
        write_spec_row(spec, "| Context per call | 1 |")


def test_a_missing_bmb_key_file_is_a_tokenizer_failure_not_a_file_error(tmp_path):
    from blended.agent.context_budget import TokenizerUnreachable, bmb_tokenizer

    with pytest.raises(TokenizerUnreachable, match="bmb api key"):
        bmb_tokenizer("http://127.0.0.1:1", tmp_path / "no_such_key_file")
