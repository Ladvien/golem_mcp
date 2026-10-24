"""A dead module in the PBR lane is invisible: nothing imports it, so
nothing fails, and it is found only by a grep.

``pbr/splatter.py`` was a Material Maker ``splatter`` port from an
earlier round. The lane stopped using it when a loose ground's stones
moved to a periodic jittered-grid layer (``pattern.scattered_field``
read through the 3x3 neighbour cells), and the field producer the
graph calls is ``nodegraph.splatter_field``. So the module was a
SECOND definition of the same name, kept alive by nothing.

These tests are the grep, made permanent: the module is gone, no
source names it, and the field producer the graph uses is defined in
exactly one place.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PBR_ROOT = _REPOSITORY_ROOT / "src" / "golem_blender" / "pbr"

# The dead module, spelled in two parts so this file does not itself
# contain the dotted path the search below looks for.
_DEAD_MODULE = "golem_blender.pbr." + "splat" + "ter"
_DEAD_FILE = "splat" + "ter.py"

# Where a golem_blender import can legally live. ``blender_mcp/mcp/blmcp``
# is included because the MCP bridge imports ``golem_blender`` deferred,
# inside Blender's process.
_SCAN_DIRS = ("src/golem_blender", "tests", "scripts", "blender_mcp/mcp/blmcp")


def _python_files() -> list[Path]:
    """Every ``.py`` file under the scanned directories, minus macOS artefacts."""
    found: list[Path] = []
    for relative in _SCAN_DIRS:
        root = _REPOSITORY_ROOT / relative
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if not path.name.startswith("._"):
                found.append(path)
    return found


def _dotted_imports(tree: ast.AST) -> set[str]:
    """Every module path and member path the tree imports, absolute only.

    ``from golem_blender.pbr import splatter`` yields both
    ``golem_blender.pbr`` and ``golem_blender.pbr.splatter``, so the
    ``from package import module`` form is caught as well as the
    ``import a.b.c`` one.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
    return names


def test_the_dead_splatter_module_is_gone():
    """The lane's dead ``splatter.py`` is deleted, not left unused."""
    assert not (_PBR_ROOT / _DEAD_FILE).exists(), (
        "pbr/splatter.py is back: nothing imports it, so nothing would fail; "
        "the field producer the graph calls is nodegraph.splatter_field"
    )


def test_no_source_imports_the_dead_splatter_module():
    """No file in the tree imports the deleted module, in either form."""
    importers = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # not our problem here; import integrity checks it
            continue
        if _DEAD_MODULE in _dotted_imports(tree):
            importers.append(str(path.relative_to(_REPOSITORY_ROOT)))
    assert importers == [], (
        "these files import the deleted module: " + ", ".join(importers)
    )


def test_splatter_field_is_defined_in_exactly_one_module():
    """The graph's splatter field has ONE definition, in ``nodegraph``.

    A second module-level ``def splatter_field`` in the package is a
    dead copy of the live one - which is what ``splatter.py`` was - and
    it is what this test exists to stop coming back.
    """
    definers = sorted(
        path.name
        for path in _PBR_ROOT.glob("*.py")
        if any(
            isinstance(node, ast.FunctionDef) and node.name == "splatter_field"
            for node in ast.parse(path.read_text(encoding="utf-8")).body
        )
    )
    assert definers == ["nodegraph.py"], (
        "splatter_field is defined by: " + (", ".join(definers) or "nobody")
    )
