# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
The PBR texture procedure, served as the MCP prompt ``pbr_texture``.

The master copy is ``golem_blender/pbr/procedure.md`` in this repository;
this module only reads it, so there is one text and no second copy to
drift.
"""

__all__ = ("register",)

import importlib.resources

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="pbr_texture",
        description=(
            "golem PBR texture procedure: generate the base colour, preview it "
            "in a shader-accurate engine, revise it, apply it, bake the ORM and "
            "normal maps from the mesh, export the set."
        ),
    )
    def pbr_texture(texture_dir: str = "") -> str:
        text = (
            importlib.resources.files("golem_blender.pbr")
            .joinpath("procedure.md")
            .read_text(encoding="utf-8")
        )
        return (
            text if not texture_dir else f"Texture directory: {texture_dir}\n\n{text}"
        )
