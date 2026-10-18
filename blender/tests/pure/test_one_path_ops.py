"""One execution path per operation, enforced rather than remembered.

`uv.smart_unwrap` sat in the vocabulary as a "backwards-compatible
shim" over `unwrap_uvs` — a second path to the same result, found by
reading the generated manifest rather than by any test failing. It was
deleted on 2026-08-22. This is what would have caught it.

The check is deliberately crude: it reads the docstrings the manifest
publishes to the agent and fails on the words a compatibility branch
announces itself with. A shim that hides its nature well enough to pass
this is a different problem; one that says "shim" in the sentence the
agent is shown is exactly this one.
"""

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import pytest

import golem_blender.ops as ops_facade
from golem_blender.manifest import OP_MODULE_NAMES, _public_functions

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "golem_blender"
BUILDERS_ROOT = SOURCE_ROOT / "builders"
# A builder reaching past the facade: `from golem_blender.ops.<module> import`.
_SUBMODULE_IMPORT_PATTERN = re.compile(
    r"^\s*from golem_blender\.ops\.\w+ import", re.MULTILINE
)

# The vocabulary an agent is handed. Every entry must be the only way
# to do what it does — see CLAUDE.md, one path per feature.
FORBIDDEN_DOCSTRING_MARKERS = (
    "shim",
    "backwards-compatible",
    "backward-compatible",
    "deprecated",
    "legacy",
    "for compatibility",
    "fallback",
)


def _all_operations():
    for module_name in OP_MODULE_NAMES:
        module = importlib.import_module(f"golem_blender.ops.{module_name}")
        for signature, summary in _public_functions(module):
            yield module_name, signature, summary


def test_the_op_vocabulary_is_not_empty():
    """Guards the guard: an import slip would pass everything below."""
    assert len(list(_all_operations())) > 10


@pytest.mark.parametrize("marker", FORBIDDEN_DOCSTRING_MARKERS)
def test_no_operation_advertises_a_second_path(marker):
    offenders = [
        f"golem_blender.ops.{module_name}.{signature.split('(')[0]}: {summary}"
        for module_name, signature, summary in _all_operations()
        if marker in summary.lower()
    ]
    assert not offenders, (
        f"operation docstrings mention {marker!r}, which is how a "
        f"compatibility branch announces itself: {offenders}. One path "
        f"per feature — delete the shim and make the primary right."
    )


def _op_module_names_on_disk():
    """Public ops submodules. Underscore modules (`_objects`) are shared
    plumbing: not facade, not manifest, not tool."""
    return {
        m.name
        for m in pkgutil.iter_modules(ops_facade.__path__)
        if not m.name.startswith("_")
    }


def _public_symbols_defined_in_ops():
    """Every public function or class whose home is an ops submodule."""
    for module_name in sorted(_op_module_names_on_disk()):
        module = importlib.import_module(f"golem_blender.ops.{module_name}")
        for symbol_name, symbol in vars(module).items():
            if symbol_name.startswith("_"):
                continue
            if not (inspect.isfunction(symbol) or inspect.isclass(symbol)):
                continue
            if symbol.__module__ != module.__name__:
                continue
            yield module_name, symbol_name


def test_every_ops_submodule_is_in_the_manifest():
    on_disk = _op_module_names_on_disk()
    assert on_disk == set(OP_MODULE_NAMES), (
        "OP_MODULE_NAMES and src/golem_blender/ops/*.py disagree: a module the "
        "manifest never introspects is a vocabulary the agent never sees."
    )


def test_every_public_op_is_reachable_from_the_facade():
    """OT-1: the whitelist is the facade, so the facade must be whole."""
    missing = sorted(
        f"golem_blender.ops.{module_name}.{symbol_name}"
        for module_name, symbol_name in _public_symbols_defined_in_ops()
        if symbol_name not in ops_facade.__all__
        or getattr(ops_facade, symbol_name, None) is None
    )
    assert not missing, (
        f"public ops not re-exported by golem_blender.ops: {missing}. "
        f"Anything off the facade is invisible to the agent and to the "
        f"schema generator."
    )


# Config objects an op takes that live in a dependency, re-exported on the
# facade so the manifest and the schema generator name the REAL class (a
# copy would be a second definition that can drift). name -> home module.
# Each must be importable without numpy: the facade imports with none.
RE_EXPORTED_FROM_DEPENDENCIES = {"RingSkirtSpec": "skinclip.spec"}


def test_facade_exports_nothing_it_does_not_define():
    """The reverse direction: `__all__` names must resolve to ops code."""
    defined = {symbol for _, symbol in _public_symbols_defined_in_ops()}
    stray = sorted(
        set(ops_facade.__all__) - defined - set(RE_EXPORTED_FROM_DEPENDENCIES)
    )
    assert not stray, f"__all__ names with no ops definition: {stray}"


@pytest.mark.parametrize("name", sorted(RE_EXPORTED_FROM_DEPENDENCIES))
def test_a_re_exported_dependency_class_is_the_dependencys_own(name):
    exported = getattr(ops_facade, name)
    assert name in ops_facade.__all__
    assert exported.__module__ == RE_EXPORTED_FROM_DEPENDENCIES[name], (
        f"{name} on the facade is {exported.__module__}.{name}, not the "
        f"{RE_EXPORTED_FROM_DEPENDENCIES[name]} class: a copy can drift"
    )


@pytest.mark.parametrize(
    "builder_path", sorted(BUILDERS_ROOT.glob("*.py")), ids=lambda p: p.name
)
def test_builders_import_only_the_facade(builder_path):
    offending = _SUBMODULE_IMPORT_PATTERN.findall(builder_path.read_text())
    assert not offending, (
        f"{builder_path.name} imports an ops submodule directly: "
        f"{offending}. Builders use `from golem_blender.ops import ...` only."
    )
