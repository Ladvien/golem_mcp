"""Op plugins (`blended.plugins`): installed distributions extend the facade.

The entry-point lookup is faked, so these run with no plugin installed and
leave the pinned core tool set alone (tests/conftest.py disables real
plugins for the whole suite; each test here re-enables the mechanism).
"""

import importlib.metadata
import sys
import types

import pytest

from blended import plugins
from blended.agent.tool_schemas import build_tool_schemas
from blended.ops._contract import changes_scene, facade_ops

FAKE_MODULE = "_fake_plugin_ops"
READER = "fake_plugin_reading"
EDITOR = "fake_plugin_edit"


def _install_entry_points(monkeypatch, *values: tuple[str, str]) -> None:
    """Make `blended.ops` entry-point discovery return `values` (name, module)."""
    monkeypatch.delenv(plugins.DISABLE_ENVIRONMENT_VARIABLE, raising=False)

    def fake_entry_points(*, group):
        assert group == plugins.ENTRY_POINT_GROUP
        return [
            importlib.metadata.EntryPoint(name=name, value=module, group=group)
            for name, module in values
        ]

    monkeypatch.setattr(plugins.importlib.metadata, "entry_points", fake_entry_points)


def _core_op_names(monkeypatch) -> list[str]:
    monkeypatch.setenv(plugins.DISABLE_ENVIRONMENT_VARIABLE, "1")
    return [name for name, _ in facade_ops()]


def test_plugin_ops_follow_the_core_ops_and_reach_the_tool_schemas(monkeypatch):
    core = _core_op_names(monkeypatch)
    _install_entry_points(monkeypatch, ("fake", FAKE_MODULE))

    names = [name for name, _ in facade_ops()]
    assert names == [*core, EDITOR, READER]
    tool_names = [schema["function"]["name"] for schema in build_tool_schemas()]
    assert tool_names == names


def test_only_the_scene_changing_plugin_op_requires_a_plan(monkeypatch):
    _install_entry_points(monkeypatch, ("fake", FAKE_MODULE))

    plan_required = {name for name, function in facade_ops() if changes_scene(function)}
    assert EDITOR in plan_required
    assert READER not in plan_required


def test_a_plugin_op_named_like_a_core_op_is_refused(monkeypatch):
    colliding = types.ModuleType("_fake_plugin_colliding")

    def add_box(object_name: str) -> str:
        """Shadow the core add_box (fake)."""
        return object_name

    colliding.add_box = add_box
    colliding.__all__ = ["add_box"]
    monkeypatch.setitem(sys.modules, "_fake_plugin_colliding", colliding)
    _install_entry_points(monkeypatch, ("fake", "_fake_plugin_colliding"))

    with pytest.raises(plugins.PluginError, match="add_box.*collides"):
        facade_ops()


def test_the_disable_variable_makes_the_facade_core_only(monkeypatch):
    core = _core_op_names(monkeypatch)
    _install_entry_points(monkeypatch, ("fake", FAKE_MODULE))
    monkeypatch.setenv(plugins.DISABLE_ENVIRONMENT_VARIABLE, "1")

    assert [name for name, _ in facade_ops()] == core
    assert plugins.op_plugins() == ()


def test_a_plugin_module_without_all_is_refused(monkeypatch):
    bare = types.ModuleType("_fake_plugin_bare")
    monkeypatch.setitem(sys.modules, "_fake_plugin_bare", bare)
    _install_entry_points(monkeypatch, ("fake", "_fake_plugin_bare"))

    with pytest.raises(plugins.PluginError, match="__all__"):
        plugins.plugin_ops()


def test_source_roots_name_the_directory_that_holds_each_plugin_package(
    monkeypatch, tmp_path
):
    """What Blender's sys.path needs: an editable install's real location."""
    package = tmp_path / "fake_plugin_package"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "ops.py").write_text("__all__ = ()\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    _install_entry_points(
        monkeypatch,
        ("b_second", "fake_plugin_package.ops"),
        ("a_first", "fake_plugin_package"),
    )

    assert plugins.plugin_package_names() == ("fake_plugin_package",)
    assert plugins.plugin_source_roots() == (str(tmp_path.resolve()),)
    assert [plugin.entry_point_name for plugin in plugins.op_plugins()] == [
        "a_first",
        "b_second",
    ]
