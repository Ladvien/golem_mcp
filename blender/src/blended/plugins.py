"""Third-party op plugins: ops that live outside this repository.

An installed distribution adds ops to the facade by declaring an entry
point in the ``blended.ops`` group whose value names a module::

    [project.entry-points."blended.ops"]
    my_ops = "my_package.ops"

That module lists its public functions in ``__all__``. Each one is a
facade op and must satisfy the same contract as a core op
(``blended.ops._contract``): annotated parameters, unit suffixes, a
one-line docstring, no bpy type in a signature. They are appended to the
core ops in entry-point-name order, so every consumer of
``facade_ops()`` (tool schemas, the plan gate, tool disclosure,
``search_ops``) sees them without a second registration path. A plugin op
whose name collides with a core op, or with another plugin's, is refused
at import: a silent shadow would change what an existing tool does.

Tool code runs inside Blender with only the ``.venv`` site-packages and
``src`` on ``sys.path``; the ``.pth`` file of an editable install is never
processed there. The MCP server therefore resolves each plugin's source
directory on its own side (``plugin_source_roots``) and passes it to the
tool code, which puts it on ``sys.path`` and purges the plugin packages on
a source change, the same way it purges ``blended``.

Setting ``BLENDED_DISABLE_PLUGINS=1`` makes the facade core-only. The
pinned tool-schema fingerprint and the ungated-op allowlist are
properties of the core set, so the test suite sets it.

References: MCP, the protocol these tools are exposed through (DOI
10.48550/arXiv.2503.23278).

Pure: introspection only, no Blender.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import inspect
import os
from dataclasses import dataclass
from pathlib import Path

ENTRY_POINT_GROUP = "blended.ops"
DISABLE_ENVIRONMENT_VARIABLE = "BLENDED_DISABLE_PLUGINS"
_DISABLED_VALUE = "1"


class PluginError(ImportError):
    """A plugin could not contribute its ops: no ``__all__``, a collision,
    or a module that does not resolve to a source directory."""


@dataclass(frozen=True)
class OpPlugin:
    """One ``blended.ops`` entry point: its name and the module it names."""

    entry_point_name: str
    module_name: str


def op_plugins() -> tuple[OpPlugin, ...]:
    """The installed op plugins, by entry-point name; empty when disabled."""
    if os.environ.get(DISABLE_ENVIRONMENT_VARIABLE) == _DISABLED_VALUE:
        return ()
    entry_points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    return tuple(
        OpPlugin(entry_point.name, entry_point.value)
        for entry_point in sorted(
            entry_points, key=lambda entry_point: entry_point.name
        )
    )


def plugin_ops() -> list[tuple[str, object]]:
    """Every op the plugins export, as (name, function), in plugin order."""
    ops: list[tuple[str, object]] = []
    for plugin in op_plugins():
        module = importlib.import_module(plugin.module_name)
        exported = getattr(module, "__all__", None)
        if exported is None:
            raise PluginError(
                f"plugin {plugin.entry_point_name!r}: module {plugin.module_name!r} "
                f"defines no __all__; list the functions it exports as ops"
            )
        for name in exported:
            function = getattr(module, name)
            if inspect.isfunction(function):
                ops.append((name, function))
    return ops


def plugin_package_names() -> tuple[str, ...]:
    """The top-level package of each plugin module, without duplicates."""
    return tuple(
        dict.fromkeys(plugin.module_name.partition(".")[0] for plugin in op_plugins())
    )


def plugin_source_roots() -> tuple[str, ...]:
    """For each plugin package, the directory that holds it.

    Server-side only. ``find_spec`` locates an editable install's real
    source directory, which Blender's ``sys.path`` cannot. Same order as
    ``plugin_package_names``.
    """
    roots: list[str] = []
    for package in plugin_package_names():
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            raise PluginError(
                f"plugin package {package!r} resolves to no source directory; "
                f"a plugin must be a package, not a single-file module"
            )
        roots.append(str(Path(spec.submodule_search_locations[0]).resolve().parent))
    return tuple(roots)
