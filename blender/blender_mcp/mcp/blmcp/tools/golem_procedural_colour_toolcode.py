# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
Tool-code for writing a PROCEDURAL base colour.

Runs in Blender's Python via the add-on's main-thread exec. The
pattern is built from Blender's own nodes and rendered to a PNG, so
this needs the open Blender - unlike the AI half of the lane, which
runs on the golem server and needs no Blender at all.

The stale-module purge is the same one the preview tool-code does:
golem_blender is imported from the repository's ``src`` directory, and
every module of the package is dropped and re-imported when the
source fingerprint changed, so a ``src/golem_blender`` edit takes
effect without restarting Blender.
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
    output_path: str
    kind: str
    scale_cells: float
    width_px: int
    height_px: int
    repository_src: str
    venv_site_packages: str
    source_fingerprint: str


class Result(NamedTuple):
    status: str
    output_path: str = ""
    message: str = ""


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
    import bpy  # pylint: disable=import-error,no-name-outside-toplevel

    for path in (params.venv_site_packages, params.repository_src):
        if path and path not in sys.path:
            sys.path.insert(0, path)

    _purge_if_stale(params.repository_src, params.source_fingerprint)

    import golem_blender  # pylint: disable=import-outside-toplevel

    setattr(golem_blender, _FINGERPRINT_ATTRIBUTE, params.source_fingerprint)

    from golem_blender.pbr.procedural import (  # pylint: disable=import-outside-toplevel
        write_procedural_base_color,
    )

    try:
        written = write_procedural_base_color(
            pathlib.Path(params.output_path),
            kind=params.kind,
            scale_cells=params.scale_cells,
            width_px=params.width_px,
            height_px=params.height_px,
        )
    except (OSError, ValueError) as error:
        return Result(status="error", message=str(error))

    return Result(status="ok", output_path=str(written))
