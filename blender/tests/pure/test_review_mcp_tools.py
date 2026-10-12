"""
Regression tests for defects found reviewing ``blender_mcp/mcp/blmcp/tools``
(slice ``mcp_tools``, 2026-10-07).

* ``get_python_api_docs`` compared ``os.path.realpath`` results against an
  un-resolved API root, so a root reached through a symlink (macOS ``/tmp`` is
  ``/private/tmp``) rejected every lookup and answered ``suggestions`` for a
  name that exists.
* ``tools/`` compared ``scene.render.engine`` against engine ids Blender 5.x
  no longer has (``BLENDER_EEVEE_NEXT``); the Blender-side twin of that check
  is ``tests/blender/test_review_mcp_tools.py``.
"""

import sys
from pathlib import Path

import pytest

MCP_DIRECTORY = Path(__file__).resolve().parents[2] / "blender_mcp" / "mcp"
if str(MCP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(MCP_DIRECTORY))

from blmcp.tools import get_python_api_docs


class _CapturingMcp:
    """Stands in for FastMCP: keeps the function ``@mcp.tool(...)`` decorates."""

    def __init__(self) -> None:
        self.functions: dict[str, object] = {}

    def tool(self, **_kwargs: object):
        def decorate(function):
            self.functions[function.__name__] = function
            return function

        return decorate


@pytest.fixture()
def api_docs_through_symlink(tmp_path, monkeypatch):
    """``get_python_api_docs`` over a data root that is reached via a symlink."""
    real_root = tmp_path / "real"
    (real_root / "api").mkdir(parents=True)
    (real_root / "api" / "foo.rst").write_text(
        "Title\n=====\n\nbody\n", encoding="utf-8"
    )
    (real_root / "secret.rst").write_text(
        "outside the api directory\n", encoding="utf-8"
    )
    link_root = tmp_path / "link"
    link_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.setattr(get_python_api_docs, "data_dir", lambda: str(link_root))
    mcp = _CapturingMcp()
    get_python_api_docs.register(mcp)
    return mcp.functions["get_python_api_docs"]


def test_api_docs_exact_match_through_symlinked_data_root(api_docs_through_symlink):
    response = api_docs_through_symlink("foo")
    assert response["kind"] == "exact"
    assert response["found"] is True
    assert "body" in response["content"]


def test_api_docs_traversal_still_rejected_through_symlinked_data_root(
    api_docs_through_symlink,
):
    response = api_docs_through_symlink("../secret")
    assert response["kind"] != "exact"
    assert "outside the api directory" not in str(response)
