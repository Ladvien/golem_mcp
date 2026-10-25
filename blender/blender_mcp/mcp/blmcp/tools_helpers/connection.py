# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Socket client for communicating with the Blender add-on.

Used by MCP "tools" that send-code to the Blender add-on.
"""

__all__ = (
    "BlenderCallTimedOut",
    "get_connection_params",
    "send_code",
)

import json
import os
import socket

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9876
_TIMEOUT = 300.0
# Connecting is a different question from waiting for an answer: the add-on
# accepts within milliseconds, so a slow connect means no Blender is listening,
# and it must be reported as unavailable rather than as a call that ran.
_CONNECT_TIMEOUT_S = 5.0
_RECV_BUFFER_SIZE = 65536


class BlenderCallTimedOut(TimeoutError):
    """Blender accepted the request and did not answer within the timeout.

    NOT a ``ConnectionError``, and deliberately so: the distinction is what the
    bridge uses to decide between "stop, Blender is closed" (a pause) and "the
    call is still running, do not re-issue it". A timed-out call on a live
    Blender is the second kind — measured 2026-10-24, when a 77-part
    ``export_assembly`` outlived the 300 s socket timeout and the agent was told
    the session was ``PAUSED`` while Blender was still measuring.
    """


def get_connection_params() -> tuple[str, int]:
    host = os.environ.get("BLENDER_MCP_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("BLENDER_MCP_PORT", str(_DEFAULT_PORT)))
    return host, port


def send_code(
    code: str, strict_json: bool, timeout_s: float = _TIMEOUT
) -> dict[str, object]:
    """
    Send Python code to the Blender add-on socket server for execution.

    Returns the full response dict from the add-on containing
    ``status`` (``"ok"`` or ``"error"``), ``result`` (on success),
    ``message`` (on error), and optionally ``stdout``/``stderr``
    captured during execution.

    Raises ``ConnectionError`` when Blender is unreachable or
    returns an invalid response.
    """
    host, port = get_connection_params()
    request = (
        json.dumps(
            {
                "type": "execute",
                "code": code,
                "strict_json": strict_json,
            }
        )
        + "\0"
    )

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as ex:
        raise ConnectionError(
            "Socket error communicating with Blender at {:s}:{:d}: {:s}".format(
                host, port, str(ex)
            )
        ) from ex

    with sock:
        # Connect with its own short timeout: a TimeoutError BEFORE the request
        # is sent means nobody is listening, which is a pause, not a call that
        # ran. Everything after the request goes out is a call Blender accepted.
        try:
            sock.settimeout(_CONNECT_TIMEOUT_S)
            sock.connect((host, port))
        except ConnectionRefusedError as ex:
            raise ConnectionError(
                "Cannot connect to Blender at {:s}:{:d}. "
                "Ensure Blender is running with the MCP addon enabled and "
                "the server started.".format(host, port)
            ) from ex
        except TimeoutError as ex:
            raise ConnectionError(
                "Blender connection timed out at {:s}:{:d}".format(host, port)
            ) from ex
        except OSError as ex:
            # NOTE: intentionally not catching `Exception` here.
            # Callers use `ConnectionError` to trigger a fallback path;
            # a broader catch would mask real bugs as connection failures.
            raise ConnectionError(
                "Socket error communicating with Blender at {:s}:{:d}: {:s}".format(
                    host, port, str(ex)
                )
            ) from ex

        try:
            sock.settimeout(timeout_s)
            sock.sendall(request.encode("utf-8"))

            # Read response until the null byte delimiter.
            buf = bytearray()
            while True:
                chunk = sock.recv(_RECV_BUFFER_SIZE)
                if not chunk:
                    break
                buf.extend(chunk)
                if b"\0" in buf:
                    break
        except TimeoutError as ex:
            raise BlenderCallTimedOut(
                "Blender did not answer within {:.0f} s at {:s}:{:d}; it may "
                "still be running the call".format(timeout_s, host, port)
            ) from ex
        except OSError as ex:
            raise ConnectionError(
                "Socket error communicating with Blender at {:s}:{:d}: {:s}".format(
                    host, port, str(ex)
                )
            ) from ex

    if not buf:
        raise ConnectionError("Empty response from Blender")

    # Parse only up to the first null byte delimiter.
    line, _sep, _rest = buf.partition(b"\0")
    try:
        response: dict[str, object] = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        raise ConnectionError(
            "Invalid response from Blender at {:s}:{:d}: {:s}".format(
                host, port, str(ex)
            )
        ) from ex
    return response
