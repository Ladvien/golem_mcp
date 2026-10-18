# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

"""
Reference images for kitbashing: search the web, show a numbered sheet, save the picks.

Runs in this server process and needs no Blender, so it takes no declared plan.
The work (golem_blender.kitbash.references) is blocking network I/O, so it runs
in a worker thread and the server keeps answering meanwhile.
"""

__all__ = ("register",)

import dataclasses
import json

import anyio
from golem_blender.kitbash import references
from mcp.server.fastmcp import (  # pylint: disable=import-error,no-name-in-module
    FastMCP,
    Image,
)
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

_LISTED_ITEM_FIELDS = (
    "source",
    "title",
    "creator",
    "license",
    "landing_url",
    "width_px",
    "height_px",
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Search Reference Images",
            readOnlyHint=False,
            destructiveHint=False,
            openWorldHint=True,
        )
    )
    async def search_reference_images(
        query: str,
        sources: list[str] | None = None,
        count: int = 24,
        license_filter: str = "any",
    ) -> list:
        """Search Openverse, Wikimedia Commons, Pexels and Brave for reference images; returns a numbered contact sheet and the items' sources and licenses."""
        result = await anyio.to_thread.run_sync(
            lambda: references.search_references(
                query=query,
                sources=tuple(sources or ()),
                count=count,
                license_filter=license_filter,
            )
        )
        listing = json.dumps(
            {
                "search_id": result.search_id,
                "items": [
                    {"n": number, **{field: getattr(item, field) for field in _LISTED_ITEM_FIELDS}}
                    for number, item in enumerate(result.items, 1)
                ],
                "skipped_sources": result.skipped_sources,
            },
            indent=2,
        )
        if not result.items:
            return [listing]
        sheet = await anyio.to_thread.run_sync(
            references.contact_sheet, list(result.thumbnail_paths)
        )
        return [Image(data=sheet, format="jpeg"), listing]

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Save Reference Images",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
    )
    async def save_reference_images(
        search_id: str,
        numbers: list[int],
        kit_slug: str,
    ) -> str:
        """Download the numbered images of a search into the kit's codex_fs reference folder with provenance; returns Mac and big paths."""
        saved = await anyio.to_thread.run_sync(
            lambda: references.save_references(search_id, numbers, kit_slug)
        )
        return json.dumps([dataclasses.asdict(entry) for entry in saved], indent=2)
