"""Generating and exporting a PBR texture set: the parts that need no Blender.

The base colour is an AI image (FLUX on the golem server); the ORM and
the normal map are baked from the mesh (see ``ops/pbr_bake.py``). This
module covers the AI half and the export, because both are file work:
they happen in the MCP server's process, not inside Blender.

The path translation is the whole point of this module's existence.
codex_fs is one network filesystem seen under two names: the Mac mounts
it at ``~/mnt/codex_fs`` and big sees it at ``/mnt/codex_fs``. The
generation call goes to big, so the init image must be handed over as
the path BIG sees, and the result comes back as a path the Mac reads.
``kitbash.paths.big_path`` does the swap and refuses a path outside the
codex root, because big cannot open one.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from golem_blender.pbr import paths as pbr_paths

# The metadata file written beside an exported set.
METADATA_FILE_NAME = "metadata.json"


@dataclass(frozen=True)
class GeneratedTexture:
    """One generated base-colour map, where it landed and how it was made."""

    mac_path: str
    big_path: str
    model: str
    seed: int
    steps: int
    width_px: int
    height_px: int
    prompt: str
    image_strength: float
    init_image_path: str = ""
    extra: dict = field(default_factory=dict)


def write_generated_texture(
    *,
    source_png: Path,
    texture_name: str,
    texture_directory: Path,
    model: str,
    seed: int,
    steps: int,
    width_px: int,
    height_px: int,
    prompt: str,
    image_strength: float,
    init_image_path: str = "",
) -> GeneratedTexture:
    """Copy a generated PNG into the texture directory under the set's file name.

    The base colour of a set is ``T_<Name>_BaseColor.png``, the name the
    existing texture sets on codex_fs already use.
    """
    texture_directory = Path(texture_directory)
    texture_directory.mkdir(parents=True, exist_ok=True)
    destination = texture_directory / pbr_paths.base_color_file_name(texture_name)
    shutil.copy2(Path(source_png), destination)

    return GeneratedTexture(
        mac_path=str(destination),
        big_path=_big_path_or_empty(destination),
        model=model,
        seed=seed,
        steps=steps,
        width_px=width_px,
        height_px=height_px,
        prompt=prompt,
        image_strength=image_strength,
        init_image_path=init_image_path,
    )


def _big_path_or_empty(path: Path) -> str:
    """The path big sees, or an empty string when the file is not on codex_fs.

    A texture directory outside the codex root is legal — a test writes
    to a temporary directory, and a caller may keep a set beside the
    project — but big cannot open it, so the map's big path is empty
    rather than a wrong one.
    """
    try:
        return pbr_paths.big_path(Path(path))
    except ValueError:
        return ""


def export_texture_set(
    texture_name: str,
    texture_directory: Path,
    destination: Path,
    metadata: dict | None = None,
) -> dict:
    """Copy a texture set's maps to `destination` and write a metadata.json beside them.

    The three maps are the ones the set is made of — the base colour, the
    ORM and the normal map. A map that does not exist is reported in the
    result rather than silently skipped, so a half-exported set is
    visible.
    """
    texture_directory = Path(texture_directory)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)

    wanted = {
        "base_color": pbr_paths.base_color_file_name(texture_name),
        "orm": pbr_paths.orm_file_name(texture_name),
        "normal": pbr_paths.normal_file_name(texture_name),
    }
    copied: dict[str, str] = {}
    missing: list[str] = []
    for key, file_name in wanted.items():
        source = texture_directory / file_name
        if not source.is_file():
            missing.append(file_name)
            continue
        target = destination / file_name
        shutil.copy2(source, target)
        copied[key] = str(target)

    metadata_path = destination / METADATA_FILE_NAME
    metadata_path.write_text(
        json.dumps(
            {
                "texture_name": texture_name,
                "channel_packing": pbr_paths.ORM_CHANNEL_PACKING,
                "files": copied,
                "missing": missing,
                **(metadata or {}),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "texture_name": texture_name,
        "destination": str(destination),
        "files": copied,
        "missing": missing,
        "metadata_path": str(metadata_path),
        "channel_packing": pbr_paths.ORM_CHANNEL_PACKING,
    }
