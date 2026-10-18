# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
The golem kitbash procedure, served as the MCP prompt ``kitbash``.

The master copy is ``golem_blender/kitbash/procedure.md`` in this repository;
the omp skill ``golem-kitbash`` points at that file, so there is one text and
no second copy to drift.
"""

__all__ = ("register",)

import importlib.resources

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.prompt(
        name="kitbash",
        description=(
            "golem kitbash procedure: style document, modular kit design and build, "
            "pack assembly, internet references to meshes."
        ),
    )
    def kitbash(kit_dir: str = "") -> str:
        text = (
            importlib.resources.files("golem_blender.kitbash")
            .joinpath("procedure.md")
            .read_text(encoding="utf-8")
        )
        return text if not kit_dir else f"Kit directory: {kit_dir}\n\n{text}"
