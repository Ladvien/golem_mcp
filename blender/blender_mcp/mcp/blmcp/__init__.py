# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
MCP server for Blender.

Provides tools for LLM's, connecting to Blender via a bridge-server.
All tools send code to the add-on to run.
"""

__all__ = (
    "LOOPBACK_ALLOWED_HOSTS",
    "LOOPBACK_ALLOWED_ORIGINS",
    "argument_parser",
    "loopback_transport_security",
    "main",
)

import argparse
import importlib
import ipaddress
import os
import pkgutil
import socket

import yaml
from mcp.server.transport_security import TransportSecuritySettings

from blmcp.tools_helpers.blended_bridge import BlendedFastMCP, blended_instructions

# NOTE(@ideasman42): this was written to support LLAMA-C++'s Web UI,
# which is one of the nicer ways to run this locally.
# It is not full HTTP support because there looks to be many options for this protocol.
# This could be disabled if it no longer serves its purpose - as most agents wont use STDIO.
_USE_HTTP_SUPPORT = True

# The HTTP transport serves tools that run arbitrary Python in Blender and has
# no authentication, so it is loopback-only and checks Host/Origin against the
# loopback names (DNS-rebinding protection). A page on another origin reaches
# 127.0.0.1 through the browser; the Origin check is what refuses it.
LOOPBACK_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ALLOWED_ORIGINS = [
    "http://127.0.0.1:*",
    "http://localhost:*",
    "http://[::1]:*",
]

_TRANSPORTS = ("stdio", *(("http",) if _USE_HTTP_SUPPORT else ()))


def loopback_transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection that admits only loopback Host and Origin headers."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=LOOPBACK_ALLOWED_HOSTS,
        allowed_origins=LOOPBACK_ALLOWED_ORIGINS,
    )


def _require_loopback_host(host: str, port: int) -> None:
    """
    Refuse a ``host`` that does not resolve only to loopback addresses.

    Duplicated in the add-on's ``mcp_to_blender_server`` on purpose: the add-on
    runs inside Blender and cannot import ``blmcp``. ``socket.gaierror`` from
    an unresolvable host propagates unchanged.
    """
    infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    addresses = {str(info[4][0]) for info in infos}
    if not all(
        ipaddress.ip_address(address.split("%", 1)[0]).is_loopback
        for address in addresses
    ):
        raise ValueError(
            "refusing to listen on {!r}: it resolves to {}, not loopback; "
            "this server runs arbitrary Python without authentication".format(
                host, ", ".join(sorted(addresses))
            )
        )


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MCP server for Blender.")
    parser.add_argument(
        "--transport",
        "-t",
        choices=_TRANSPORTS,
        default="stdio",
        help="Transport protocol (default: stdio).",
    )
    parser.add_argument(
        "--exit-on-source-change",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Exit when src/blended or blmcp changes while idle, so a stdio client that "
            "reconnects re-lists fresh tools. Off by default: Claude Code and Claude "
            "Desktop do not restart a server that exits. omp opts in (.omp/mcp.json). "
            "Needs --transport stdio."
        ),
    )
    if _USE_HTTP_SUPPORT:
        parser.add_argument(
            "--host",
            default="127.0.0.1",
            help="Loopback host to bind to for HTTP transports (default: 127.0.0.1); any other host is refused.",
        )
        parser.add_argument(
            "--port",
            "-p",
            type=int,
            default=8000,
            help="Port to bind to for HTTP transports (default: 8000).",
        )
    return parser


def main() -> int:
    parser = argument_parser()
    args = parser.parse_args()
    # Only a client-spawned stdio server gets restarted after it exits.
    if args.exit_on_source_change and args.transport != "stdio":
        parser.error(
            "--exit-on-source-change needs --transport stdio: nothing restarts an HTTP server that exits"
        )

    # Load prompts.
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    with open(os.path.join(data_dir, "prompts.yml"), encoding="utf-8") as fh:
        prompts = yaml.safe_load(fh)

    mcp = BlendedFastMCP(
        "blender-mcp",
        instructions=blended_instructions(str(prompts["initial_instructions"])),
    )
    # Exit once src/blended or blmcp changes while idle; a reconnecting client
    # restarts the server, which then lists the current tools and instructions.
    if args.exit_on_source_change:
        mcp.exit_on_source_change()

    # Auto-discover and register all tools (they are never un-registered).
    import blmcp.tools as tools_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(tools_pkg.__path__):
        if modname.endswith("_toolcode") or modname.startswith("_template_"):
            continue
        mod = importlib.import_module("blmcp.tools.{:s}".format(modname))
        if hasattr(mod, "register"):
            mod.register(mcp)

    transport = args.transport
    if _USE_HTTP_SUPPORT and transport == "http":
        from starlette.applications import Starlette
        from starlette.middleware.cors import CORSMiddleware

        try:
            _require_loopback_host(args.host, args.port)
        except (ValueError, OSError) as error:
            parser.error(str(error))

        transport = "streamable-http"

        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.settings.streamable_http_path = "/"
        mcp.settings.stateless_http = True
        mcp.settings.transport_security = loopback_transport_security()

        # Add CORS middleware so browser-based clients
        # (e.g. llama.cpp web UI) can connect without preflight failures.
        _orig = mcp.streamable_http_app

        def _app_with_cors() -> Starlette:
            app = _orig()
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
            return app

        mcp.streamable_http_app = _app_with_cors  # type: ignore[method-assign]

    mcp.run(transport=transport)
    return 0
