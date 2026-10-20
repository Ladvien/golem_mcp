"""Where PBR texture sets live, and how big sees the same files.

codex_fs is one network filesystem: ~/mnt/codex_fs on the Mac is
/mnt/codex_fs on big. A texture written here is therefore a texture
big's tools (generate_image) can open, once the prefix is swapped by
``kitbash.paths.big_path``.

Every root is read at call time from ``kitbash.paths`` (not copied at
import), so a test that patches the codex root there is seen here too —
the same convention ``kitbash/paths.py`` already uses.
"""

from __future__ import annotations

import os
from pathlib import Path

from golem_blender.kitbash import paths as kitbash_paths

# The texture lane's root: <codex root>/game_assets/textures, overridable
# so a machine (or a test) can point the lane somewhere else without
# touching the codex mount itself.
TEXTURE_ROOT_ENV = "GOLEM_TEXTURE_ROOT"
DEFAULT_TEXTURE_SUBDIRECTORY = ("game_assets", "textures")

# The channel packing, as ONE string the report, the exporter and the
# procedure all read. Measured on the existing sets: R = ambient
# occlusion, G = roughness, B = metallic.
ORM_CHANNEL_PACKING = "R=ao,G=roughness,B=metallic"

# The file names the existing sets already use (T_Brick_BaseColor.png
# beside T_Brick_Normal.png on codex_fs). The ORM set is the one this
# lane adds.
BASE_COLOR_SUFFIX = "BaseColor"
ORM_SUFFIX = "ORM"
NORMAL_SUFFIX = "Normal"
FILE_PREFIX = "T_"


def texture_root() -> Path:
    """The directory texture sets are written to and read from."""
    override = os.environ.get(TEXTURE_ROOT_ENV)
    if override:
        return Path(override)
    return kitbash_paths.CODEX_ROOT_MAC.joinpath(*DEFAULT_TEXTURE_SUBDIRECTORY)


def big_path(mac_path: Path) -> str:
    """The path big sees for a file under the codex root; ValueError for any other path."""
    return kitbash_paths.big_path(Path(mac_path))


def base_color_file_name(texture_name: str) -> str:
    """The base-colour file name for a texture set: ``T_<Name>_BaseColor.png``."""
    return f"{FILE_PREFIX}{texture_name}_{BASE_COLOR_SUFFIX}.png"


def orm_file_name(texture_name: str) -> str:
    """The ORM file name for a texture set: ``T_<Name>_ORM.png``."""
    return f"{FILE_PREFIX}{texture_name}_{ORM_SUFFIX}.png"


def normal_file_name(texture_name: str) -> str:
    """The normal-map file name for a texture set: ``T_<Name>_Normal.png``."""
    return f"{FILE_PREFIX}{texture_name}_{NORMAL_SUFFIX}.png"


__all__ = (
    "BASE_COLOR_SUFFIX",
    "FILE_PREFIX",
    "NORMAL_SUFFIX",
    "ORM_CHANNEL_PACKING",
    "ORM_SUFFIX",
    "TEXTURE_ROOT_ENV",
    "base_color_file_name",
    "big_path",
    "normal_file_name",
    "orm_file_name",
    "texture_root",
)
