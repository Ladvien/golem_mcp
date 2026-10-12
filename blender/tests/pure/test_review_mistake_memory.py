"""The Experience Library's contract, checked against the repository.

`validate_memory()` only asks that a guard string be non-empty, so a record
whose guard was deleted with the code it guarded kept passing: the
in-Blender chat client's removal (184095f) left 23 records pointing at test
files, modules and a GUI harness that no longer exist. These tests resolve
every reference a guard makes against the tree as it is now.
"""

from __future__ import annotations

import datetime
import functools
import re
from pathlib import Path

import pytest

from blended.evaluate.mistake_memory import MISTAKES, validate_memory

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
# Where a guard may define its tests and helpers.
DEFINITION_ROOTS = ("tests", "scripts", "blender_mcp/tests")
# Repository-relative file references; `jsonl` before `json` so the longer
# suffix wins.
PATH_PATTERN = re.compile(
    r"\b((?:src|tests|scripts|docs|_evaluate|blender_mcp)/[\w./-]*?\.(?:py|md|jsonl|json|sh|toml))\b"
)
PATH_AND_NAME_PATTERN = re.compile(
    r"\b((?:src|tests|scripts|blender_mcp)/[\w./-]*?\.py)::(\w+)"
)
# A bare name is a test, a test class or a guard helper; a stem followed by
# `.py` is a file and is resolved as a path instead.
NAME_PATTERN = re.compile(r"\b((?:test_|_assert_|Test[A-Z])\w*)\b(?!\.py)")
# Hyphenated only: "make sure" is prose, "make test-repro" is a target.
MAKE_PATTERN = re.compile(r"\bmake ([a-z]+(?:-[a-z]+)+)\b")
# Executable means a file that runs or a make target that runs it.
EXECUTABLE_ROOTS = ("tests/", "scripts/", "blender_mcp/tests/")


@functools.cache
def _definitions() -> frozenset[str]:
    names: set[str] = set()
    for root in DEFINITION_ROOTS:
        for source in (REPOSITORY_ROOT / root).rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            names.update(
                re.findall(
                    r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", text, re.MULTILINE
                )
            )
    return frozenset(names)


@functools.cache
def _make_targets() -> frozenset[str]:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    return frozenset(re.findall(r"^([a-z][a-z-]*):", makefile, re.MULTILINE))


def test_the_library_validates_clean():
    assert validate_memory() == []


def test_an_identifier_names_one_record():
    identifiers = [record.identifier for record in MISTAKES]
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize("record", MISTAKES, ids=lambda record: record.identifier)
def test_a_record_is_dated_in_the_past(record):
    recorded_on = datetime.date.fromisoformat(record.recorded_on)
    today_utc = datetime.datetime.now(datetime.UTC).date()
    assert recorded_on <= today_utc, f"{record.identifier} is dated in the future"


@pytest.mark.parametrize("record", MISTAKES, ids=lambda record: record.identifier)
def test_a_guard_names_only_things_that_exist(record):
    guard = record.guarded_by
    assert not guard.lstrip().startswith("RETIRED"), (
        f"{record.identifier}: a record whose guard was deleted is deleted or "
        f"re-guarded, not marked retired — it would stay guarded by nothing"
    )
    missing_paths = [
        path
        for path in PATH_PATTERN.findall(guard)
        if not (REPOSITORY_ROOT / path).exists()
    ]
    assert not missing_paths, (
        f"{record.identifier}: guard cites files that do not exist: {missing_paths}"
    )

    definitions = _definitions()
    for path, name in PATH_AND_NAME_PATTERN.findall(guard):
        text = (REPOSITORY_ROOT / path).read_text(encoding="utf-8")
        assert re.search(
            rf"^\s*(?:async\s+)?(?:def|class)\s+{name}\b", text, re.MULTILINE
        ), f"{record.identifier}: {path} does not define {name}"
    missing_names = [
        name for name in NAME_PATTERN.findall(guard) if name not in definitions
    ]
    assert not missing_names, (
        f"{record.identifier}: guard names tests that are not defined: {missing_names}"
    )

    missing_targets = [
        target
        for target in MAKE_PATTERN.findall(guard)
        if target not in _make_targets()
    ]
    assert not missing_targets, (
        f"{record.identifier}: guard runs make targets that do not exist: {missing_targets}"
    )


@pytest.mark.parametrize("record", MISTAKES, ids=lambda record: record.identifier)
def test_a_guard_names_something_executable(record):
    guard = record.guarded_by
    runs_a_file = any(
        path.startswith(EXECUTABLE_ROOTS) for path in PATH_PATTERN.findall(guard)
    )
    runs_a_test = any(name in _definitions() for name in NAME_PATTERN.findall(guard))
    runs_a_target = bool(MAKE_PATTERN.findall(guard))
    assert runs_a_file or runs_a_test or runs_a_target, (
        f"{record.identifier}: the guard names no test, script or make target — "
        f"'be careful about X' is not a guard"
    )
