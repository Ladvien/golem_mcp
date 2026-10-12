# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=C0114  # See tool doc-string.

__all__ = ("register",)

from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module
from mcp.types import ToolAnnotations  # pylint: disable=import-error,no-name-in-module

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.connection import send_code
from blmcp.tools_helpers.live_blender import run_in_open_blender_for_file

_TOOL_CALL = toolcode_wrap_with_calling_convention(
    toolcode_load_from_filepath(__file__)
)


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Blend-File Linked Library Summary",
            readOnlyHint=True,
        )
    )
    def get_blendfile_summary_of_linked_libraries() -> dict[str, object]:
        """
        Return a tree of directly and indirectly linked library files.
        """
        return send_code(toolcode_format_call(_TOOL_CALL, None), strict_json=True)

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Get Blend-File Linked Library Summary for an Open File",
            readOnlyHint=True,
        )
    )
    def get_blendfile_summary_of_linked_libraries_for_cli(
        blend_file: str,
    ) -> dict[str, object]:
        """
        Return linked-library info, answered by the open Blender, which must have *blend_file* open or the call pauses.
        """
        return run_in_open_blender_for_file(
            blend_file, toolcode_format_call(_TOOL_CALL, None)
        )
