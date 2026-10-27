# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The golem server on ``big``, served through this MCP server.

golem (image -> 3D -> rigged character, Kimodo motion) runs on Linux with the
GPU and speaks streamable HTTP; this server runs on the Mac beside the user's
open Blender. A client registers this one server as ``golem`` and sees both
halves' tools: ``GolemBlenderFastMCP`` lists the remote tools after its own and
forwards their calls here, unchanged.

golem is stateless (one HTTP request answers one call), so every call opens a
fresh session. Only the tool list and the instructions are cached, and only
after a successful fetch: an unreachable big is retried on the next listing
and never turns into an empty cache.
"""

__all__ = (
    "CALL_TIMEOUT_S",
    "DEFAULT_GOLEM_REMOTE_URL",
    "GOLEM_REMOTE_URL_ENV",
    "LIST_TIMEOUT_S",
    "GolemRemote",
)

import os
import sys
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession, types  # pylint: disable=import-error,no-name-in-module
from mcp.shared.session import (  # pylint: disable=import-error,no-name-in-module
    ProgressFnT,
)
from mcp.client.streamable_http import (  # pylint: disable=import-error,no-name-in-module
    streamable_http_client,
)

GOLEM_REMOTE_URL_ENV = "GOLEM_REMOTE_URL"
DEFAULT_GOLEM_REMOTE_URL = "http://192.168.1.110:9786/mcp"

# Listing and the handshake answer at once or big is down. A call is another
# matter: golem tools wait up to 20 minutes for the GPU and run up to 7200 s.
LIST_TIMEOUT_S = 10.0
CALL_TIMEOUT_S = 10800.0


def _leaf_error(error: BaseException) -> BaseException:
    """
    The first real failure inside *error*: the SDK's task groups wrap what
    went wrong in an ``ExceptionGroup`` whose own message says nothing.
    """
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    return error


def _describe(error: BaseException) -> str:
    leaf = _leaf_error(error)
    text = str(leaf)
    return (
        "{:s}: {:s}".format(type(leaf).__name__, text) if text else type(leaf).__name__
    )


class GolemRemote:
    """Client of the golem server on big: its tools, instructions and calls."""

    def __init__(self, url: str | None = None) -> None:
        self.url = (
            url or os.environ.get(GOLEM_REMOTE_URL_ENV) or DEFAULT_GOLEM_REMOTE_URL
        )
        self._tools: list[types.Tool] | None = None
        self._instructions: str | None = None

    async def list_tools(self) -> list[types.Tool]:
        """
        The remote tools, from the cache once fetched. An unreachable big
        gives ``[]``, is not cached and is reported once on stderr.
        """
        if self._tools is not None:
            return self._tools
        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(LIST_TIMEOUT_S)) as client,
                streamable_http_client(self.url, http_client=client) as (
                    read,
                    write,
                    _session_id,
                ),
                ClientSession(read, write) as session,
            ):
                initialized = await session.initialize()
                listing = await session.list_tools()
        except Exception as error:  # pylint: disable=broad-exception-caught
            print(
                "golem remote unreachable at {:s}: {:s}".format(
                    self.url, _describe(error)
                ),
                file=sys.stderr,
            )
            return []
        self._tools = list(listing.tools)
        self._instructions = initialized.instructions
        return self._tools

    async def instructions(self) -> str | None:
        """The remote server's instructions, or ``None`` while big is unreachable."""
        if self._tools is None:
            await self.list_tools()
        return self._instructions

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        report_progress: ProgressFnT | None = None,
    ) -> types.CallToolResult:
        """
        Run *name* on big and return its result unchanged. A failure to reach
        big is an error result the agent can read, not an exception.

        *report_progress* receives big's own progress notifications as they
        arrive, so a job queued behind another GPU tenant says so to the
        client instead of going quiet for twenty minutes.
        """
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(CALL_TIMEOUT_S, connect=LIST_TIMEOUT_S)
                ) as client,
                streamable_http_client(self.url, http_client=client) as (
                    read,
                    write,
                    _session_id,
                ),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                return await session.call_tool(
                    name,
                    arguments,
                    read_timeout_seconds=timedelta(seconds=CALL_TIMEOUT_S),
                    progress_callback=report_progress,
                )
        except Exception as error:  # pylint: disable=broad-exception-caught
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text="golem on big is unreachable at {:s}: {:s}".format(
                            self.url, _describe(error)
                        ),
                    )
                ],
                isError=True,
            )
