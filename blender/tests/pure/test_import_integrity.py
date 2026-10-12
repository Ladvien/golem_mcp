"""A stale import inside a bpy-only module is invisible to ``make
test-pure`` and only detonates minutes into the app tier — the exact
class that hid 37 failures and 36 errors behind a deferred suite in the
old repo's reorg.  This test parses every ``.py`` under ``src/blended``,
``tests``, ``scripts``, and ``blender_mcp/mcp/blmcp`` with ``ast`` (no execution,
so no bpy needed) and asserts that every import rooted at ``blended``
resolves to a module or package that exists on disk, and that every
``from <blended package> import <name>`` names a submodule or a name
bound in the package's ``__init__.py``.

Parsed, not imported: the whole point is that a broken import must
reddens the pure tier without launching Blender.

The precision-over-recall design — regex extraction of code-element
references from source, matched against the on-disk module tree, erring
on the side of not flagging links we are not confident about — follows
Tan, Wagner & Treude, "Detecting outdated code element references in
software repository documentation", EMSE 2023,
DOI 10.1007/s10664-023-10397-6, §8.3: "we rely on an improved version
of the regular expressions used for code element detection … and then
use a very strict filter (exact match) … we err on the side of caution
to not establish traceability links that we are not confident about."
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

# The probe must have found work to do. Measured 2026-09-06: 708
# blended-rooted imports across 190 Python files; measured 2026-09-26
# after the chat-client deletion (blender_addon/ out, the MCP bridge in):
# 1002. 200 is the floor, so a tree prune that erases them turns this
# gate red instead of green.
MINIMUM_IMPORTS_CHECKED = 200

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPOSITORY_ROOT / "src"

# Directories to walk for Python sources. ``blender_mcp/mcp/blmcp/`` is
# included because the MCP bridge tool-code imports ``blended`` deferred,
# inside ``main()``, in Blender's process: a stale import there surfaces
# only as a traceback string returned over the socket at call time.
_SCAN_DIRS = ("src/blended", "tests", "scripts", "blender_mcp/mcp/blmcp")

# Files whose names start with these prefixes are skipped (macOS
# resource-fork artefacts, etc.).
_SKIP_PREFIXES = ("._",)


def _python_files() -> list[Path]:
    """Yield every non-skip ``.py`` file under the scan directories."""
    found: list[Path] = []
    for rel in _SCAN_DIRS:
        root = _REPOSITORY_ROOT / rel
        if not root.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".py"):
                    continue
                if any(name.startswith(prefix) for prefix in _SKIP_PREFIXES):
                    continue
                found.append(Path(dirpath) / name)
    return found


def _resolve_relative_import(
    level: int, module: str | None, file_path: Path
) -> str | None:
    """Resolve a relative import (``level > 0``) to an absolute dotted path.

    ``level`` is the number of leading dots: 1 = current package, 2 =
    parent, etc.  For files under ``src/blended`` the directory parts are
    mapped from ``src/blended/...`` to ``blended...`` so the result is
    rooted at ``blended`` and the caller's ``root == 'blended'`` check
    fires.  Without that mapping the resolver returns a ``src``-rooted
    path, the caller's ``root == 'blended'`` check is skipped, and
    ``_module_exists_on_disk`` short-circuits via its ``parts[0] !=
    'blended'`` early return — so the relative-import branch is entirely
    dead even though the docstring advertises the coverage.
    """
    try:
        rel = file_path.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        return None
    parts = list(rel.parts)
    # The file's directory is the package.
    dir_parts = parts[:-1]
    # Map src/blended -> blended so relative imports resolve to
    # ``blended.*`` rather than ``src.blended.*``.
    if len(dir_parts) >= 2 and dir_parts[0] == "src" and dir_parts[1] == "blended":
        dir_parts = ["blended"] + list(dir_parts[2:])
    # level=1 means current package (dir_parts), level=2 means parent, etc.
    if level > len(dir_parts):
        return None
    base_parts = dir_parts[: len(dir_parts) - (level - 1)]
    if module:
        full_parts = base_parts + module.split(".")
    else:
        full_parts = base_parts
    return ".".join(full_parts)


def _module_exists_on_disk(dotted: str) -> bool:
    """Check whether a dotted module path exists under ``src/`` as a file or package."""
    if not dotted:
        return False
    parts = dotted.split(".")
    if parts[0] != "blended":
        # We only assert blended-rooted imports; other roots (bpy, numpy,
        # stdlib) are not on disk under src/.
        return True
    # blended.foo.bar -> src/blended/foo/bar.py or src/blended/foo/bar/__init__.py
    rel_parts = ["src"] + parts
    base = _REPOSITORY_ROOT.joinpath(*rel_parts)
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _module_level_names(dotted: str) -> set[str]:
    """Names bound at module level in the module or package named by ``dotted``.

    If ``dotted`` is a package (has ``__init__.py``), parse that file.
    If ``dotted`` is a plain module (``foo.py``), parse the module file
    itself — the names a ``from foo.bar import Baz`` must be in
    ``foo/bar.py``, not in ``foo/__init__.py``.
    """
    parts = dotted.split(".")
    if parts[0] != "blended":
        return set()
    base = _REPOSITORY_ROOT.joinpath("src", *parts)
    if base.is_dir() and (base / "__init__.py").is_file():
        return _names_from_file(base / "__init__.py")
    module_file = base.with_suffix(".py")
    if module_file.is_file():
        return _names_from_file(module_file)
    return set()


def _names_from_file(path: Path) -> set[str]:
    """Parse a Python file and return every name bound at module level.

    Covers ``__all__`` entries, imported names, defs, classes, and
    assignments — parsed, never imported.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name.split(".")[0]
                names.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                names.add(name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    # Also harvest __all__ if it's a list/tuple of string literals.
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
    return names


def _package_submodules(package_dotted: str) -> set[str]:
    """Return the set of submodule names visible on disk for a package."""
    parts = package_dotted.split(".")
    if parts[0] != "blended":
        return set()
    pkg_dir = _REPOSITORY_ROOT.joinpath("src", *parts)
    if not pkg_dir.is_dir():
        return set()
    submodules: set[str] = set()
    for entry in pkg_dir.iterdir():
        if entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
            submodules.add(entry.stem)
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            submodules.add(entry.name)
    return submodules


def test_all_blended_imports_resolve():
    """Every import rooted at ``blended`` must point to a module on disk.

    Coverage gaps, named honestly: (1) ``from blended.x import *`` star
    imports are skipped — the names they pull in are unknowable without
    executing the module, which this test never does.  (2) The
    relative-import branch (``level > 0``) is exercised only if the tree
    contains relative imports; as of 2026-09-06 the tree has zero, so the
    branch is latent coverage advertised by the docstring but not yet
    proven by live data.  The resolver maps ``src/blended`` to
    ``blended`` so the branch will fire when relative imports appear.
    """
    problems: list[str] = []
    checked = 0
    for py_file in _python_files():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError as error:
            problems.append(
                f"{py_file.relative_to(_REPOSITORY_ROOT)}: unparseable, its imports were not checked — {error}"
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root == "blended":
                        checked += 1
                        if not _module_exists_on_disk(alias.name):
                            problems.append(
                                f"{py_file.relative_to(_REPOSITORY_ROOT)}:{node.lineno}: "
                                f"import {alias.name} — module not found on disk"
                            )
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    resolved = _resolve_relative_import(
                        node.level, node.module, py_file
                    )
                    if resolved is None:
                        continue
                    root = resolved.split(".")[0]
                    if root == "blended":
                        # For relative imports, check the module itself.
                        checked += 1
                        if not _module_exists_on_disk(resolved):
                            problems.append(
                                f"{py_file.relative_to(_REPOSITORY_ROOT)}:{node.lineno}: "
                                f"from {'.' * node.level}{node.module or ''} "
                                f"(resolves to {resolved}) — module not found on disk"
                            )
                        # For ``from .pkg import name``, also check name.
                        for alias in node.names:
                            if alias.name == "*":
                                continue
                            if not _imported_name_exists(resolved, alias.name):
                                problems.append(
                                    f"{py_file.relative_to(_REPOSITORY_ROOT)}:{node.lineno}: "
                                    f"from {'.' * node.level}{node.module or ''} import "
                                    f"{alias.name} — not a submodule or bound name in "
                                    f"{resolved}"
                                )
                elif node.module and node.module.split(".")[0] == "blended":
                    checked += 1
                    if not _module_exists_on_disk(node.module):
                        problems.append(
                            f"{py_file.relative_to(_REPOSITORY_ROOT)}:{node.lineno}: "
                            f"from {node.module} import ... — module not found on disk"
                        )
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        if not _imported_name_exists(node.module, alias.name):
                            problems.append(
                                f"{py_file.relative_to(_REPOSITORY_ROOT)}:{node.lineno}: "
                                f"from {node.module} import {alias.name} — "
                                f"not a submodule or bound name in {node.module}"
                            )

    assert checked >= MINIMUM_IMPORTS_CHECKED, (
        f"only {checked} blended-rooted imports checked; the floor is "
        f"{MINIMUM_IMPORTS_CHECKED} so a tree prune that erases them "
        f"turns this gate red instead of green"
    )
    assert not problems, (
        f"{len(problems)} unresolvable blended imports:\n  "
        + "\n  ".join(problems[:30])
        + (f"\n  … and {len(problems) - 30} more" if len(problems) > 30 else "")
    )


def _imported_name_exists(module_dotted: str, name: str) -> bool:
    """Check that ``name`` is a submodule of ``module_dotted`` or bound at its module level.

    ``module_dotted`` may be a package (directory with ``__init__.py``)
    or a plain module (``foo.py``).  In both cases the names a
    ``from module_dotted import name`` must resolve to are either a
    submodule on disk or a name bound at module level in the file.
    """
    if name in _package_submodules(module_dotted):
        return True
    return name in _module_level_names(module_dotted)


def test_the_harness_imports_first_in_a_fresh_interpreter():
    """`blended.harness` must be importable BEFORE anything under
    `blended.run`, in a process that has imported nothing else.

    Measured 2026-09-10 (OT-4): a stage-vocabulary module placed under
    `blended.run` made `harness -> run.stages -> run/__init__ -> run.batch
    -> harness` a cycle. The pure suite never saw it because an earlier
    test had already imported `blended.run.executor`; the agent-loop
    tests inside Blender, which import the harness first, did. A fresh
    interpreter is the only honest probe of import order.
    """
    import subprocess
    import sys

    # A fresh interpreter has none of conftest's sys.path edits: name the
    # src tree explicitly so the probe does not depend on an editable install.
    environment = {**os.environ, "PYTHONPATH": str(_SRC_ROOT)}
    completed = subprocess.run(
        [sys.executable, "-c", "import blended.harness; import blended.agent.tools"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr[-1500:]
