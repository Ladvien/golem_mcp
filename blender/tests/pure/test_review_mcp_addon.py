"""The vendored test MCP client must see every line the server wrote.

`blender_mcp/tests/mcp_client` waited with `select` on a `BufferedReader`.
`select` only sees the OS pipe: a second JSON line that arrived in the same
read as the first sits in Python's buffer, so `select` reports "not ready" and
the client times out waiting for a response it already holds. Measured with a
child writing two lines in one `write`: after `readline()` returned the first,
`select` on the same pipe reported the second as not ready for a full second.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

CLIENT_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "blender_mcp"
    / "tests"
    / "mcp_client"
    / "__init__.py"
)
REQUEST_TIMEOUT_S = 5
HOLD_PIPE_OPEN_S = 60

# One `write` carrying a notification and then the response to request id 1.
TWO_LINES_IN_ONE_WRITE_CHILD = (
    "import sys, time\n"
    "sys.stdin.readline()\n"
    "sys.stdout.write(\n"
    '    \'{"jsonrpc": "2.0", "method": "notifications/message"}\\n\'\n'
    '    \'{"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "probe_tool"}]}}\\n\'\n'
    ")\n"
    "sys.stdout.flush()\n"
    f"time.sleep({HOLD_PIPE_OPEN_S})\n"
)


@pytest.fixture()
def client_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "review_mcp_client", CLIENT_MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_REQUEST_TIMEOUT", REQUEST_TIMEOUT_S)
    return module


def test_response_in_the_same_chunk_as_a_notification_is_not_missed(client_module):
    client = client_module.MCPClient(
        [sys.executable, "-c", TWO_LINES_IN_ONE_WRITE_CHILD]
    )
    try:
        assert client.list_tools() == ["probe_tool"]
    finally:
        client.close()


def test_a_silent_server_times_out_instead_of_hanging(client_module):
    silent_child = (
        f"import sys, time; sys.stdin.readline(); time.sleep({HOLD_PIPE_OPEN_S})"
    )
    client = client_module.MCPClient([sys.executable, "-c", silent_child])
    try:
        with pytest.raises(RuntimeError, match="Timeout"):
            client.list_tools()
    finally:
        client.close()
