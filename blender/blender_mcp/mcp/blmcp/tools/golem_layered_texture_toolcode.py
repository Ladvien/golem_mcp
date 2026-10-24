# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
Tool-code for writing a LAYERED texture set: a base material with others
laid over it under masks, written as BaseColor, ORM and Normal.

Runs in Blender's Python via the add-on's main-thread exec: every
material is written through Blender's image API and read back, the same
path the procedural base colour takes.

The stale-module purge is the same one the procedural colour tool-code
does: golem_blender is imported from the repository's ``src`` directory,
and every module of the package is dropped and re-imported when the
source fingerprint changed, so a ``src/golem_blender`` edit takes effect
without restarting Blender.
"""

__all__ = (
    "Params",
    "Result",
    "main",
)

import importlib
import importlib.util
import pathlib
import sys
from typing import NamedTuple

_PACKAGE = "golem_blender"
# Stamped on the imported package: the source fingerprint it was imported at.
_FINGERPRINT_ATTRIBUTE = "_mcp_source_fingerprint"


class Params(NamedTuple):
    texture_dir: str
    texture_name: str
    base_json: str
    layers_json: str
    scale_cells: float
    resolution_px: int
    repository_src: str
    venv_site_packages: str
    source_fingerprint: str


class Result(NamedTuple):
    status: str
    message: str = ""
    paths_json: str = ""
    kinds: tuple = ()
    height_range_json: str = ""
    height_range_is_measured: bool = False


def _purge_if_stale(repository_src: str, source_fingerprint: str) -> None:
    """Drop golem_blender's modules when the source changed since the last import."""
    imported = sys.modules.get(_PACKAGE)
    if imported is None:
        return
    if getattr(imported, _FINGERPRINT_ATTRIBUTE, None) == source_fingerprint:
        return
    for module_name in [
        name
        for name in list(sys.modules)
        if name == _PACKAGE or name.startswith(_PACKAGE + ".")
    ]:
        del sys.modules[module_name]
    for source in pathlib.Path(repository_src, _PACKAGE).rglob("*.py"):
        pathlib.Path(importlib.util.cache_from_source(str(source))).unlink(
            missing_ok=True
        )
    importlib.invalidate_caches()


def main(params: Params) -> Result:
    import json  # pylint: disable=import-outside-toplevel

    for path in (params.venv_site_packages, params.repository_src):
        if path and path not in sys.path:
            sys.path.insert(0, path)

    _purge_if_stale(params.repository_src, params.source_fingerprint)

    import golem_blender  # pylint: disable=import-outside-toplevel

    setattr(golem_blender, _FINGERPRINT_ATTRIBUTE, params.source_fingerprint)

    from golem_blender.pbr.layered_set import (  # pylint: disable=import-outside-toplevel
        write_layered_texture_set,
    )

    try:
        written = write_layered_texture_set(
            pathlib.Path(params.texture_dir),
            params.texture_name,
            json.loads(params.base_json),
            json.loads(params.layers_json),
            scale_cells=params.scale_cells,
            resolution=params.resolution_px,
        )
    except (OSError, TypeError, ValueError) as error:
        return Result(status="error", message=str(error))

    return Result(
        status="ok",
        paths_json=json.dumps(written["paths"]),
        kinds=tuple(written["kinds"]),
        height_range_json=json.dumps(written["height_range"]),
        height_range_is_measured=bool(written["height_range_is_measured"]),
    )
