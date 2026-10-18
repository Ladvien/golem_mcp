"""Where kitbash reads and writes, on this Mac and as big sees the same files.

codex_fs is one network filesystem: ~/mnt/codex_fs on the Mac is /mnt/codex_fs
on big. A file saved here is therefore a path big's tools (generate_image,
generate_3d) can open, once the prefix is swapped by `big_path`.

Every constant is read at call time by its users, so tests patch this module.
"""

from __future__ import annotations

import os
from pathlib import Path

CODEX_ROOT_MAC = Path(
    os.environ.get("GOLEM_CODEX_ROOT", str(Path.home() / "mnt" / "codex_fs"))
)
CODEX_ROOT_ON_BIG = os.environ.get("GOLEM_CODEX_ROOT_ON_BIG", "/mnt/codex_fs")
REFERENCE_ROOT = CODEX_ROOT_MAC / "game_assets" / "references"
SEARCH_CACHE_ROOT = Path.home() / ".golem" / "reference_searches"
KEY_FILES = {
    "brave": Path.home() / ".golem" / "brave_api_key",
    "pexels": Path.home() / ".golem" / "pexels_api_key",
}


def big_path(mac_path: Path) -> str:
    """The path big sees for a file under CODEX_ROOT_MAC; ValueError for any other path."""
    mac_path = Path(mac_path)
    try:
        relative = mac_path.relative_to(CODEX_ROOT_MAC)
    except ValueError:
        raise ValueError(
            f"{mac_path} is not under {CODEX_ROOT_MAC}, so big cannot see it"
        ) from None
    return f"{CODEX_ROOT_ON_BIG.rstrip('/')}/{relative.as_posix()}"
