# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The user's OPEN Blender, or a pause.

Every tool that needs Blender looks for the open, running one first
(``require_live_blender``). When none answers, the result starts with
``PAUSE_PREFIX`` and tells the agent to stop and tell the user; no tool starts
a headless Blender of its own, so a missing Blender is never worked around.
"""

__all__ = (
    "PAUSE_INSTRUCTIONS",
    "PAUSE_PREFIX",
    "TOOLS_WITHOUT_BLENDER",
    "LiveBlenderUnavailable",
    "pause_text",
    "require_live_blender",
    "run_in_open_blender_for_file",
)

import os
import socket

from blmcp.tools_helpers.connection import get_connection_params, send_code

# What the instructions head tells the agent to look for.
PAUSE_PREFIX = "PAUSED:"
PAUSE_INSTRUCTIONS = (
    "Stop and tell the user. These tools work only in the user's open Blender "
    "with the MCP add-on server running. Do not start your own Blender (no "
    "`blender --background`, no bpy module), do not retry in a loop and do not "
    "work around it with other tools. Continue when the user says Blender is ready."
)

# Tools that read only the bundled docs: they never touch Blender, so a missing
# Blender is no reason to pause them. A tool left off this list pauses, which is
# the safe direction for a tool added later.
TOOLS_WITHOUT_BLENDER = frozenset(
    {
        "get_python_api_docs",
        "search_api_docs",
        "search_manual_docs",
    }
)

# A listening Blender accepts at once; this only bounds a black-holed address.
_PROBE_TIMEOUT_S = 2.0


class LiveBlenderUnavailable(ConnectionError):
    """No open Blender can serve this call; the message says why."""


def pause_text(reason: str) -> str:
    """The text of a paused result: what was looked at, then what to do."""
    return "{:s} {:s}\n{:s}".format(PAUSE_PREFIX, reason, PAUSE_INSTRUCTIONS)


def require_live_blender() -> None:
    """
    Look for the open Blender: something must accept a connection at the
    configured host and port. Raises ``LiveBlenderUnavailable`` otherwise.
    """
    host, port = get_connection_params()
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_S):
            return
    except OSError as ex:
        raise LiveBlenderUnavailable(
            "No open Blender answers at {:s}:{:d} ({:s}). Open Blender and start the "
            "MCP add-on server (Preferences > Add-ons > MCP), or tell me where it is "
            "listening.".format(host, port, ex.strerror or type(ex).__name__)
        ) from ex


def run_in_open_blender_for_file(blend_file: str, code: str) -> dict[str, object]:
    """
    Run *code* in the open Blender, which must have *blend_file* open.

    The running Blender is the truth for that file: unsaved edits count, and
    nothing is copied or spawned. A Blender with another file open, or none
    open, pauses the call instead: answering from a different file would be
    wrong, and opening one headless is not this tool's call to make.
    """
    require_live_blender()
    probe = send_code(
        "import bpy\nresult = {'filepath': bpy.data.filepath}\n", strict_json=True
    )
    if probe.get("status") != "ok":
        raise RuntimeError(str(probe.get("message", "Unknown error")))
    probe_result = probe["result"]
    assert isinstance(probe_result, dict)
    open_path = str(probe_result.get("filepath", ""))
    if not open_path or os.path.realpath(open_path) != os.path.realpath(blend_file):
        raise LiveBlenderUnavailable(
            "The open Blender has {:s} open, not {:s}. Open that file in Blender "
            "and ask again.".format(open_path or "an unsaved file", blend_file)
        )
    return send_code(code, strict_json=True)
