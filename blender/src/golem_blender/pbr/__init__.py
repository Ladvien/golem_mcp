"""Agent-driven PBR texture authoring: paths, conventions, the procedure.

One package for the whole texture lane, so the file names, the channel
packing and the mount translation live in ONE place instead of being
repeated in the op that writes them, the tool that exports them and the
procedure that tells the agent what they are.

Host-agnostic by construction: every root is read from the environment
at call time, and the Mac<->big swap is the one ``kitbash.paths.big_path``
already does. Nothing here names a machine.
"""

from golem_blender.pbr.paths import (
    ORM_CHANNEL_PACKING,
    base_color_file_name,
    big_path,
    height_file_name,
    normal_file_name,
    orm_file_name,
    texture_root,
)

__all__ = (
    "ORM_CHANNEL_PACKING",
    "base_color_file_name",
    "big_path",
    "height_file_name",
    "normal_file_name",
    "orm_file_name",
    "texture_root",
)
