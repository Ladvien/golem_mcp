"""
Regression tests for defects found reviewing ``blender_mcp/mcp/blmcp/tools_helpers``
and ``blender_mcp/_misc`` (slice ``mcp_helpers``, 2026-10-07).

Each test drives the fixed path with data that fails on the old code:

* ``search`` folded overlapping matches into one hit but left the hit's
  ``text`` at the seed's window, so a folded match was scored yet never shown.
* ``BlendedSession.resume`` read the handoff as UTF-8 outside its ``try``, so a
  corrupt handoff crashed server start-up and was never consumed.
* ``blended_bridge`` left three public module constants out of ``__all__``,
  failing ``blender_mcp/_misc/check_namespace.py`` (``make check_namespace``).
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import types
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_DIRECTORY = REPOSITORY_ROOT / "blender_mcp" / "mcp"
if str(MCP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(MCP_DIRECTORY))

pytest.importorskip("docutils")
pytest.importorskip("mcp")

from blmcp.tools_helpers import (
    blended_bridge,
    rst_doc_search,
    rst_parse_docs,
)

# Three matches, each two paragraphs apart, all in one section-less file.
FOLD_BODY = (
    "needle_zz first.\n\n"
    "Filler a.\n\n"
    "needle_zz second.\n\n"
    "Filler b.\n\n"
    "Filler c.\n\n"
    "needle_zz third.\n"
)
FOLD_CONTEXT = 2


@contextlib.contextmanager
def synthetic_manual(files: dict[str, str]) -> Iterator[str]:
    with tempfile.TemporaryDirectory() as tmp:
        for rel, content in files.items():
            full = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(content)
        rst_parse_docs._PARAGRAPH_CACHE.clear()
        rst_parse_docs._PARAGRAPH_SECTION_CACHE.clear()
        with (
            mock.patch.object(rst_doc_search, "data_dir", return_value=tmp),
            mock.patch.object(rst_parse_docs, "data_dir", return_value=tmp),
        ):
            yield tmp
        rst_parse_docs._PARAGRAPH_CACHE.clear()
        rst_parse_docs._PARAGRAPH_SECTION_CACHE.clear()


def test_folded_matches_are_all_in_the_hit_text() -> None:
    with synthetic_manual({"manual/a.rst": FOLD_BODY}):
        result = rst_doc_search.search(
            query="needle_zz",
            scope="manual",
            max_results=10,
            context=FOLD_CONTEXT,
        )
    (hit,) = result["hits"]
    # The score counts three matches; the text must show all three.
    assert hit["score"] == 3
    for ordinal in ("first", "second", "third"):
        assert f"needle_zz {ordinal}." in hit["text"], hit["text"]


def test_hit_text_does_not_run_past_the_last_paragraph() -> None:
    with synthetic_manual({"manual/a.rst": FOLD_BODY}):
        result = rst_doc_search.search(
            query="needle_zz",
            scope="manual",
            max_results=10,
            context=FOLD_CONTEXT * 10,
        )
    (hit,) = result["hits"]
    assert hit["text"] == "\n\n".join(FOLD_BODY.strip().split("\n\n"))


def test_handoff_that_is_not_utf8_is_refused_loudly_and_consumed() -> None:
    parent_pid = 4242
    with tempfile.TemporaryDirectory() as tmp:
        log_directory = Path(tmp) / "logs"
        log_directory.mkdir()
        path = blended_bridge.handoff_path(log_directory, parent_pid)
        path.write_bytes(b"\xff\xfe not json")
        stderr = io.StringIO()
        with mock.patch.object(
            blended_bridge, "sys", types.SimpleNamespace(stderr=stderr)
        ):
            session = blended_bridge.BlendedSession.resume(
                log_directory,
                Path(tmp) / "outputs",
                parent_pid,
                now_s=time.time(),
            )
        assert not session.plan_declared
        assert session.session_name is None
        assert "refused a malformed handoff" in stderr.getvalue()
        assert not path.exists()


def test_missing_handoff_starts_a_new_session() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = blended_bridge.BlendedSession.resume(
            Path(tmp) / "logs", Path(tmp) / "outputs", 1
        )
    assert not session.plan_declared
    assert session.session_name is None


def test_bridge_module_passes_check_namespace() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "blender_mcp" / "_misc" / "check_namespace.py"),
            str(Path(blended_bridge.__file__)),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
