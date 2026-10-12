"""The MCP add-on's code runner must survive code that tries to exit the process.

`blender_mcp/addon/.../weak_sandbox.py` blocks `sys.exit`, but `exit()` and
`raise SystemExit` do not go through `sys.exit`. `_execute_code` caught only
`Exception`, so measured in background Blender 5.2: `exit(4)` and
`raise SystemExit(3)` both escaped `_execute_code` (the server process then
ends in `--command blender_mcp` mode, and in the GUI the exception reaches
Blender's timer machinery). Same for a deferred `check_is_finished` that exits.
"""

import json
import socket
import sys
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender")

pytestmark = pytest.mark.blender

ADDON_PARENT_DIRECTORY = Path(__file__).resolve().parents[2] / "blender_mcp" / "addon"
RECV_BUFFER_BYTES = 65536
PEER_TIMEOUT_S = 5.0


@pytest.fixture(scope="module")
def addon_modules():
    sys.path.insert(0, str(ADDON_PARENT_DIRECTORY))
    try:
        from blender_mcp_addon import deferred_tool, mcp_to_blender_server
    finally:
        sys.path.remove(str(ADDON_PARENT_DIRECTORY))
    return mcp_to_blender_server, deferred_tool


@pytest.mark.parametrize("code", ["exit(4)", "raise SystemExit(3)"])
def test_exiting_code_is_an_error_response_not_an_exit(addon_modules, code):
    server, _deferred = addon_modules
    stdout_before, stderr_before = sys.stdout, sys.stderr
    outcome = server._execute_code(code, strict_json=True)
    assert outcome.check_fn is None
    assert outcome.response["status"] == "error"
    assert "SystemExit" in outcome.response["message"]
    assert (sys.stdout, sys.stderr) == (stdout_before, stderr_before)


def test_sys_exit_is_still_blocked_by_the_sandbox(addon_modules):
    server, _deferred = addon_modules
    exit_before = sys.exit
    outcome = server._execute_code("import sys; sys.exit(1)", strict_json=True)
    assert outcome.response["status"] == "error"
    assert "sys.exit() is not allowed" in outcome.response["message"]
    assert sys.exit is exit_before


def test_deferred_checker_that_exits_gets_an_error_response(addon_modules):
    _server, deferred = addon_modules
    server_end, peer_end = socket.socketpair()
    server_end.setblocking(False)
    peer_end.settimeout(PEER_TIMEOUT_S)

    def check_is_finished():
        raise SystemExit(5)

    deferred.add(server_end, check_is_finished, strict_json=True, stdout="", stderr="")
    try:
        assert deferred.poll() is True
        assert not deferred.has_pending()
        received = bytearray()
        while b"\0" not in received:
            chunk = peer_end.recv(RECV_BUFFER_BYTES)
            assert chunk, "connection closed before a response arrived"
            received.extend(chunk)
    finally:
        deferred.close_all()
        peer_end.close()
    response = json.loads(bytes(received).rstrip(b"\0"))
    assert response["status"] == "error"
    assert "SystemExit" in response["message"]


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_server_refuses_a_non_loopback_host(addon_modules):
    """`_execute_code` runs arbitrary Python with no authentication, so
    binding 0.0.0.0 hands that to the whole LAN. Measured before the fix:
    `start("0.0.0.0", port)` bound and listened."""
    server, _deferred = addon_modules
    port = _free_loopback_port()
    try:
        with pytest.raises(ValueError, match="not loopback"):
            server.start("0.0.0.0", port)
        assert not server.is_running()
    finally:
        server.stop()


def test_the_server_still_binds_loopback(addon_modules):
    server, _deferred = addon_modules
    server.start("127.0.0.1", _free_loopback_port())
    try:
        assert server.is_running()
    finally:
        server.stop()
    assert not server.is_running()
