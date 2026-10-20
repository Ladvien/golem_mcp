# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
Tool-code for rendering a shader-accurate preview of a textured object.

Runs in Blender's Python via the add-on's main-thread exec. The
render engine is EEVEE, NOT Workbench: Workbench reads only
``material.diffuse_color`` and never the shader graph, so a texture
reviewed through a Workbench render is reviewed blind (measured with a
solid-red texture against a green diffuse_color: Workbench rendered
green, EEVEE rendered red).

The stale-module purge is the same one the golem_blender bridge does:
golem_blender is imported from the repository's ``src`` directory, and
every module of the package is dropped and re-imported when the source
fingerprint changed, so a ``src/golem_blender`` edit takes effect
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
    object_name: str
    resolution_px: int
    contact_sheet: bool
    repository_src: str
    venv_site_packages: str
    source_fingerprint: str


class Result(NamedTuple):
    status: str
    paths: tuple[str, ...] = ()
    engine: str = ""
    resolution_px: int = 0
    object_name: str = ""
    message: str = ""


def _purge_if_stale(repository_src: str, source_fingerprint: str) -> None:
    """Drop golem_blender's modules when the source changed since the last import."""
    imported = sys.modules.get(_PACKAGE)
    if imported is None:
        return
    if getattr(imported, "_mcp_source_fingerprint", None) == source_fingerprint:
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
    import bpy  # pylint: disable=import-error,no-name-in-module

    for path in (params.venv_site_packages, params.repository_src):
        if path and path not in sys.path:
            sys.path.insert(0, path)

    _purge_if_stale(params.repository_src, params.source_fingerprint)

    import golem_blender  # pylint: disable=import-outside-toplevel

    setattr(golem_blender, _FINGERPRINT_ATTRIBUTE, params.source_fingerprint)

    from golem_blender.capture.texture_preview import (  # pylint: disable=import-outside-toplevel
        render_texture_contact_sheet,
        render_texture_preview,
    )

    blender_object = bpy.data.objects.get(params.object_name)
    if blender_object is None:
        return Result(
            status="error",
            message="No object named {!r} in the scene.".format(params.object_name),
        )

    output_directory = pathlib.Path(bpy.app.tempdir) / "golem_texture_preview"
    output_directory.mkdir(parents=True, exist_ok=True)

    if params.contact_sheet:
        sheet_path = render_texture_contact_sheet(
            blender_object,
            output_directory,
            resolution_px=params.resolution_px,
        )
        paths = (str(sheet_path),)
    else:
        single_path = render_texture_preview(
            blender_object,
            output_directory / "preview.png",
            resolution_px=params.resolution_px,
        )
        paths = (str(single_path),)

    return Result(
        status="ok",
        paths=paths,
        engine="BLENDER_EEVEE",
        resolution_px=params.resolution_px,
        object_name=blender_object.name,
    )
