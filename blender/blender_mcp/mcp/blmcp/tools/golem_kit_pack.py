# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
Register a folder of .glb pieces as a golem kit.

Reads files and writes kit.yaml; it needs no Blender, so it takes no declared
plan. The scan runs in a worker thread: a pack of hundreds of pieces is
hundreds of file parses.
"""

__all__ = ("register",)

import dataclasses
import json
from pathlib import Path

import anyio
from golem_blender.kitbash import packs
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Register Kit Pack",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    async def register_kit_pack(
        pack_dir: str,
        kit_dir: str,
        kit_name: str,
        license: str,  # pylint: disable=redefined-builtin
    ) -> str:
        """Register a folder of .glb pieces (e.g. a Kenney pack) as a golem kit (kit.yaml) with measured sizes, for kitbashing new assets."""
        report = await anyio.to_thread.run_sync(
            lambda: packs.register_pack(Path(pack_dir), Path(kit_dir), kit_name, license)
        )
        return json.dumps(dataclasses.asdict(report), indent=2)
