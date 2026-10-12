"""Fixture for test_op_plugins: a plugin module with one reader and one
scene-changing op, both satisfying the op contract. Not an op module of
blended; nothing imports it except the test that fakes an entry point."""

from __future__ import annotations

from dataclasses import dataclass

from blended.ops._contract import op

__all__ = ("fake_plugin_edit", "fake_plugin_reading")


@dataclass(frozen=True)
class FakePluginReading:
    """What the fake reader reports."""

    face_count: int


@dataclass(frozen=True)
class FakePluginEdit:
    """What the fake editor reports."""

    moved_by_m: float


@op(reads_only=True)
def fake_plugin_reading(object_name: str) -> FakePluginReading:
    """Read the face count of the named object (fake)."""
    return FakePluginReading(face_count=0)


def fake_plugin_edit(object_name: str, offset_m: float = 0.0) -> FakePluginEdit:
    """Move the named object by an offset (fake)."""
    return FakePluginEdit(moved_by_m=offset_m)
