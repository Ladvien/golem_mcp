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
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from golem_blender.pbr import paths as pbr_paths

# The metadata file written beside an exported set.
METADATA_FILE_NAME = "metadata.json"


def _remove_stale_set_files(
    destination: Path,
    current_files: set[str],
    current_extras: set[str],
    set_file_names: set[str],
    texture_name: str,
) -> list[str]:
    """Remove the files THIS SET put here and this one does not.

    Two rules, because a set's files and its extras are identified in
    two different ways:

    - the MAPS are named for the set, so a stale one is found by its
      name: `T_<Name>_BaseColor.png` and its siblings. Another set's
      maps have other names and are left alone.
    - the EXTRAS have no such name - they are the environment map and
      the reference photos - so the only record of whose they are is
      the previous export's own `metadata.json`. It is consulted only
      when it is about THIS set, so a set's export never removes
      another set's extras.

    A destination can hold more than one set: the lane has a
    generated one and a procedural one, and they are the same kind of
    deliverable.

    Returns the names removed.
    """
    keep = {Path(path).name for path in current_files | current_extras}
    keep.add(METADATA_FILE_NAME)
    removed: list[str] = []

    # The set's own stale maps, found by name.
    for file_name in set_file_names:
        if file_name in keep or file_name.startswith("._"):
            continue
        target = destination / file_name
        if target.is_file():
            target.unlink()
            removed.append(file_name)

    # The set's own stale extras, found in its own previous export.
    metadata_path = destination / METADATA_FILE_NAME
    if not metadata_path.is_file():
        return removed
    try:
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return removed
    if previous.get("texture_name") != texture_name:
        return removed
    for path in (previous.get("extras") or {}).values():
        name = Path(path).name
        if name in keep or name.startswith("._"):
            continue
        target = destination / name
        if target.is_file():
            target.unlink()
            removed.append(name)
    return removed


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
    # How large the written map's seam is, against its own largest
    # ordinary features. A generated map measures 1.377x before the
    # tileable blend and 0.304x after it.
    tile_seam_ratio: float = 0.0
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
    make_tileable: bool = True,
) -> GeneratedTexture:
    """Copy a generated PNG into the texture directory under the set's file name.

    The base colour of a set is ``T_<Name>_BaseColor.png``, the name the
    existing texture sets on codex_fs already use.

    `make_tileable` hides the map's seam by the method material-maker
    uses. It is on by default, because a generated map does not tile
    otherwise - its seam is a property of the sample - and the blend
    is cheap at the width it uses.
    """
    texture_directory = Path(texture_directory)
    texture_directory.mkdir(parents=True, exist_ok=True)
    destination = texture_directory / pbr_paths.base_color_file_name(texture_name)
    shutil.copy2(Path(source_png), destination)

    if make_tileable:
        # A GENERATED map does not tile - its seam is a property of
        # the sample - so the seam is hidden by the method
        # material-maker uses: three copies of the map, blended so
        # that the edge carries the image's own middle. Measured, the
        # seam goes from 1.377x to 0.304x, which is BETTER than the
        # reference sets ambientcg makes to tile (0.32x to 0.47x),
        # and the correlation with the original is 0.7711.
        #
        # It is not free: the blend moves the image. So the seam is
        # measured afterwards and reported, so a caller can see what
        # it cost.
        from golem_blender.pbr.tileable import make_image_tileable

        make_image_tileable(destination, destination)
    seam_ratio = pbr_paths.tile_seam_ratio(destination)

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
        tile_seam_ratio=round(seam_ratio, 3),
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
    extras: Sequence[Path] = (),
) -> dict:
    """Copy a texture set's maps to `destination` and write a metadata.json beside them.

    The three maps are the ones the set is made of — the base colour, the
    ORM and the normal map. A map that does not exist is reported in the
    result rather than silently skipped, so a half-exported set is
    visible.

    `extras` are files copied alongside the maps: the environment map the
    set was lit with, the reference photos it was authored from. A set
    exported without them says how it was MADE but not how to LIGHT it
    or where the pattern came from, so the export is not reusable on
    its own.

    The destination is written as a CLEAN SET: a file the previous
    export put there and this one does not is removed. Copying over the
    top would leave a stale reference photo beside the new maps, and
    the metadata — which lists the extras — would not mention it, so it
    would look like part of the deliverable and be nothing of the
    sort. Only files this module's own export writes are removed: the
    three maps, the extras it copied, and the metadata. Anything else
    in the directory is left alone.
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

    # The extras, under their own names so the export says what each
    # one is. A macOS sidecar file ("._name.png") is skipped: it is
    # filesystem metadata, not part of the set, and a set exported with
    # them carries noise.
    extras_copied: dict[str, str] = {}
    for extra in extras:
        extra_path = Path(extra)
        if not extra_path.is_file():
            continue
        if extra_path.name.startswith("._"):
            continue
        target = destination / extra_path.name
        shutil.copy2(extra_path, target)
        extras_copied[extra_path.name] = str(target)

    # The set is written whole, so what a PREVIOUS export put here and
    # this one does not is removed. The previous export's own
    # metadata.json says what it copied - that is the record of what
    # belongs to the set - so the files to remove are read from it
    # rather than guessed. A file nobody's export claims is left
    # alone: the destination may hold other work.
    removed = _remove_stale_set_files(
        destination,
        set(copied.values()),
        set(extras_copied.values()),
        set(wanted.values()),
        texture_name,
    )

    metadata_path = destination / METADATA_FILE_NAME
    metadata_path.write_text(
        json.dumps(
            {
                "texture_name": texture_name,
                "channel_packing": pbr_paths.ORM_CHANNEL_PACKING,
                "files": copied,
                "missing": missing,
                "extras": extras_copied,
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
        "extras": extras_copied,
        "removed": removed,
        "metadata_path": str(metadata_path),
        "channel_packing": pbr_paths.ORM_CHANNEL_PACKING,
    }
