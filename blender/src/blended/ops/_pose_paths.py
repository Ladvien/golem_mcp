"""Pose-bone fcurve data paths, read and written one way.

Blender names the channel of a pose bone by a data path such as
``pose.bones["upperarm_l"].rotation_quaternion``. The bone name sits in
a quoted string inside that path, so a name with a quote or a backslash
in it is escaped (``bpy.utils.escape_identifier``: ``\\"`` and ``\\\\``).
Reading a path with a pattern that stops at the first quote hands the op
a truncated bone name, and then "no such bone" or, worse, the wrong bone.

Pure (no bpy, no numpy): `tests/pure/test_pose_paths.py` runs it in the
dev venv. Private (underscore module): shared plumbing, not an op.
"""

from __future__ import annotations

import re
from typing import NamedTuple

POSE_BONE_PREFIX = "pose.bones["
ROTATION_QUATERNION_CHANNEL = "rotation_quaternion"
LOCATION_CHANNEL = "location"
SCALE_CHANNEL = "scale"

_POSE_BONE_PATH = re.compile(
    r'^pose\.bones\["(?P<bone>(?:[^"\\]|\\.)*)"\]\.(?P<channel>[A-Za-z_][A-Za-z0-9_]*)$'
)
_ESCAPED_CHARACTER = re.compile(r"\\(.)")


class PoseBoneChannel(NamedTuple):
    """The bone and the property a pose-bone data path names."""

    bone_name: str
    channel: str


def escape_identifier(name: str) -> str:
    """Escape a bone name the way Blender writes it inside a data path."""
    return name.replace("\\", "\\\\").replace('"', '\\"')


def pose_bone_path(bone_name: str, channel: str) -> str:
    """The data path of ``channel`` on the pose bone ``bone_name``."""
    return f'{POSE_BONE_PREFIX}"{escape_identifier(bone_name)}"].{channel}'


def parse_pose_bone_path(data_path: str) -> PoseBoneChannel | None:
    """The bone and channel a data path names, or None when it is not a plain pose-bone property.

    ``pose.bones["a"].rotation_quaternion`` parses; an array element
    (``pose.bones["a"]["prop"]``), an object-level path (``location``) and
    a nested path do not.
    """
    match = _POSE_BONE_PATH.match(data_path)
    if match is None:
        return None
    return PoseBoneChannel(
        _ESCAPED_CHARACTER.sub(r"\1", match["bone"]), match["channel"]
    )
