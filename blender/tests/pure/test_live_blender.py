"""The MCP server drives the user's OPEN Blender, or it pauses and says so.

Rule 2 of the 2026-10-07 live-Blender change: every tool looks for the open
running Blender first; when none can serve the call the result starts with
`PAUSED:`, tells the agent to stop and tell the user, and no headless Blender
is ever started. Before the change, an upstream tool surfaced a raw
`ToolError`, a scene-changing blended tool answered 'No plan declared' before
it noticed there was no Blender, and the five `*_for_cli` tools spawned
`blender --background` on the file instead.
"""

import asyncio
import importlib
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_DIRECTORY = REPOSITORY_ROOT / "blender_mcp" / "mcp"
if str(MCP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(MCP_DIRECTORY))

pytest.importorskip("mcp")
pytest.importorskip("docutils")

LOOPBACK_HOST = "127.0.0.1"
CLI_TOOL_NAME = "get_blendfile_summary_path_info_for_cli"
OPEN_FILE_NAME = "open_in_blender.blend"
OTHER_FILE_NAME = "somewhere_else.blend"


def _closed_loopback_port() -> int:
    """A port nothing listens on: bound, read, closed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK_HOST, 0))
        return probe.getsockname()[1]


@pytest.fixture
def no_blender(monkeypatch):
    """The MCP connection params point at a closed port, so no Blender answers
    (never the user's real one on 9876), and spawning any process fails the test."""
    port = _closed_loopback_port()
    monkeypatch.setenv("BLENDER_MCP_HOST", LOOPBACK_HOST)
    monkeypatch.setenv("BLENDER_MCP_PORT", str(port))

    def refuse_to_spawn(*args, **kwargs):
        raise AssertionError(
            f"a process was started with no Blender answering: {args!r}"
        )

    monkeypatch.setattr(subprocess, "run", refuse_to_spawn)
    monkeypatch.setattr(subprocess, "Popen", refuse_to_spawn)
    return port


@pytest.fixture
def server(tmp_path):
    """A BlendedFastMCP with the upstream tools the test calls, logging under tmp."""
    from blmcp.tools_helpers import blended_bridge

    instance = blended_bridge.BlendedFastMCP("live-blender-test", instructions="x")
    instance._blended = blended_bridge.BlendedSession(
        log_directory=tmp_path / "logs", output_root=tmp_path / "outputs"
    )
    for module_name in ("get_objects_summary", "get_blendfile_summary_path_info"):
        importlib.import_module(f"blmcp.tools.{module_name}").register(instance)
    return instance


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("list_scene", {}),
        ("add_box", {"name": "Box", "width_m": 1.0, "depth_m": 1.0, "height_m": 1.0}),
        ("get_objects_summary", {}),
        (CLI_TOOL_NAME, {"blend_file": "/tmp/never_opened.blend"}),
    ],
)
def test_every_tool_pauses_when_no_blender_answers(
    server, no_blender, tool_name, arguments
):
    """The scene-changing `add_box` has no plan declared: the pause must come
    first, because no plan can be acted on without a Blender."""
    from blmcp.tools_helpers.live_blender import PAUSE_PREFIX

    result = asyncio.run(server.call_tool(tool_name, arguments))

    assert result.isError, tool_name
    text = result.content[0].text
    assert text.startswith(PAUSE_PREFIX), text
    assert str(no_blender) in text, "the pause names the port that was looked at"
    assert "Stop" in text and "tell the user" in text


def test_a_for_cli_tool_pauses_when_the_open_blender_has_another_file(
    monkeypatch, tmp_path
):
    """Blender answers, but it has a different file open: the tool does not
    run its code, and does not spawn a headless Blender for the file."""
    from blmcp.tools_helpers import live_blender

    sent = []

    def fake_send_code(code, strict_json):
        sent.append(code)
        return {"status": "ok", "result": {"filepath": str(tmp_path / OTHER_FILE_NAME)}}

    monkeypatch.setattr(live_blender, "require_live_blender", lambda: None)
    monkeypatch.setattr(live_blender, "send_code", fake_send_code)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("spawned a Blender")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("spawned a Blender")
    )
    wanted = tmp_path / OPEN_FILE_NAME

    with pytest.raises(live_blender.LiveBlenderUnavailable) as raised:
        live_blender.run_in_open_blender_for_file(str(wanted), "result = {}")

    assert len(sent) == 1, "only the which-file probe was sent, not the tool's code"
    assert str(wanted) in str(raised.value) and OTHER_FILE_NAME in str(raised.value)


def test_a_for_cli_tool_answers_from_the_open_blender_that_has_the_file(
    monkeypatch, tmp_path
):
    """The running Blender has the file open (reached through a symlink): it
    answers, so unsaved edits count and nothing is copied or spawned."""
    from blmcp.tools_helpers import live_blender

    real = tmp_path / OPEN_FILE_NAME
    real.write_bytes(b"")
    link = tmp_path / "link.blend"
    os.symlink(real, link)
    sent = []

    def fake_send_code(code, strict_json):
        sent.append(code)
        if len(sent) == 1:
            return {"status": "ok", "result": {"filepath": str(real)}}
        return {"status": "ok", "result": {"answered": True}}

    monkeypatch.setattr(live_blender, "require_live_blender", lambda: None)
    monkeypatch.setattr(live_blender, "send_code", fake_send_code)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("spawned a Blender")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("spawned a Blender")
    )

    response = live_blender.run_in_open_blender_for_file(str(link), "result = {'x': 1}")

    assert response == {"status": "ok", "result": {"answered": True}}
    assert sent[1] == "result = {'x': 1}"


def test_the_instructions_head_names_the_pause_the_server_sends():
    """The head tells the agent what to do on `PAUSED:`; the server sends that
    exact prefix. One constant, so the rule and the message cannot drift apart."""
    from blmcp.tools_helpers.blended_bridge import MCP_INSTRUCTIONS_HEAD
    from blmcp.tools_helpers.live_blender import PAUSE_PREFIX

    assert PAUSE_PREFIX in MCP_INSTRUCTIONS_HEAD
