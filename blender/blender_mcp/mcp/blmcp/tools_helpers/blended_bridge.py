# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
blended's tool surface served through this MCP server.

Every tool in ``blended.agent.tools.TOOL_SCHEMAS`` (service tools and
facade ops) is listed beside the upstream tools and dispatched inside
Blender through ``dispatch_tool``, the one door the in-process agent
loop also uses (see ``blended_bridge_toolcode.py``). The server side
keeps what the loop keeps: the plan gate (a scene-changing tool is
refused until ``declare_plan`` succeeded) and one schema-2 ToolEvent per
call in ``logs/mcp-*.jsonl``, the record ``scripts/mine_candidate_ops.py``
mines. Renders come back as MCP image content.

The add-on execs whatever reaches its localhost socket: the exec-over-
localhost threat model of MCP is discussed in DOI 10.48550/arXiv.2503.23278.
Agentic Blender code generation: LL3M, DOI 10.48550/arXiv.2508.08228.

Freshness: every call carries ``source_fingerprint()`` so Blender purges
and re-imports ``blended`` after a source edit, and
``BlendedFastMCP.exit_on_source_change`` ends an idle server whose own
code went stale; the MCP client restarts it and re-lists the tools.
"""

__all__ = (
    "BLENDED_TOOLS",
    "BLENDED_TOOL_NAMES",
    "BLMCP_ROOT",
    "CLAUDE_CODE_INSTRUCTIONS_LIMIT_CHARACTERS",
    "HANDOFF_MAX_AGE_S",
    "MCP_INSTRUCTIONS_HEAD",
    "MCP_INSTRUCTIONS_HEAD_CONDENSES_REVISION",
    "PLUGIN_PACKAGES",
    "PLUGIN_SOURCE_ROOTS",
    "REPOSITORY_ROOT",
    "REPOSITORY_SRC",
    "SOURCE_CHANGED_EXIT_CODE",
    "SOURCE_POLL_INTERVAL_S",
    "SOURCE_RESPONSE_DRAIN_S",
    "SOURCE_ROOTS",
    "SOURCE_SETTLE_S",
    "SOURCE_SKIPPED_DIRECTORY_NAMES",
    "SOURCE_SKIPPED_PATHS",
    "SOURCE_SUFFIXES",
    "VENV_SITE_PACKAGES",
    "VIEWPORT_FOLLOW_TOOL_NAME",
    "BlendedFastMCP",
    "BlendedSession",
    "blended_instructions",
    "handoff_path",
    "source_fingerprint",
)

import base64
import hashlib
import json
import math
import os
import sys
import sysconfig
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import anyio
import blended
from blended.agent.outcome import ToolOutcome, outcome_from_json
from blended.agent.plan import MISSING_PLAN_REFUSAL, PLAN_TOOL_NAME, plan_required_for
from blended.agent.system_prompt import build_system_prompt
from blended.agent.tool_event import (
    TOOL_EVENT_KIND,
    dispatched_tool_event,
    encode_tool_event,
    refused_tool_event,
)
from blended.agent.tools import (
    MAXIMUM_TRACEBACK_CHARACTERS,
    TOOL_SCHEMAS,
    TOOL_SCHEMAS_FINGERPRINT,
)
from blended.agent.transcript import ChatTranscript, default_log_directory
from blended.plugins import plugin_package_names, plugin_source_roots
from mcp import types  # pylint: disable=import-error,no-name-in-module
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module

from blmcp.tools_helpers import (
    toolcode_format_call,
    toolcode_load_from_filepath,
    toolcode_wrap_with_calling_convention,
)
from blmcp.tools_helpers.blended_bridge_toolcode import Params
from blmcp.tools_helpers.connection import send_code
from blmcp.tools_helpers.live_blender import (
    PAUSE_PREFIX,
    TOOLS_WITHOUT_BLENDER,
    pause_text,
    require_live_blender,
)

REPOSITORY_SRC = Path(blended.__file__).resolve().parent.parent
REPOSITORY_ROOT = REPOSITORY_SRC.parent
VENV_SITE_PACKAGES = sysconfig.get_paths()["purelib"]
BLMCP_ROOT = Path(__file__).resolve().parent.parent

# What a "source change" is: files the server or Blender reads as code or
# data. The bundled API/manual docs are 27 MB of static reference, skipped
# so a fingerprint stays cheap enough to compute on every call.
SOURCE_SUFFIXES = frozenset({".py", ".j2", ".yml", ".yaml", ".toml", ".json"})
SOURCE_SKIPPED_DIRECTORY_NAMES = frozenset({"__pycache__"})
SOURCE_SKIPPED_PATHS = (BLMCP_ROOT / "data" / "api", BLMCP_ROOT / "data" / "manual")
# Op plugins (`blended.plugins`): their packages sit outside `src/blended`, so
# the fingerprint watches them too, and the toolcode puts their roots on
# Blender's `sys.path` (an editable install's `.pth` is not processed there).
PLUGIN_SOURCE_ROOTS = plugin_source_roots()
PLUGIN_PACKAGES = plugin_package_names()
SOURCE_ROOTS = (
    REPOSITORY_SRC / "blended",
    BLMCP_ROOT,
    *(
        Path(root) / package
        for root, package in zip(PLUGIN_SOURCE_ROOTS, PLUGIN_PACKAGES)
    ),
)
_FINGERPRINT_HEX_CHARACTERS = 16

# The source watcher: poll period, how long a change must hold still before
# the server exits (a git checkout rewrites many files), how long after the
# last tool call returned, and the exit code. call_tool returns before the
# SDK serializes and writes the response: decrement-to-flush measured 0.6 ms
# at 256 KB and 19-21 ms at 4 MB over the SDK's stdio transport to a fast
# reader (2026-10-02), and an exit inside that gap dropped the result of a
# call that had already run (5 of 5 at a 1 ms lead). The drain wait is two
# orders of magnitude above the slowest measured write.
SOURCE_POLL_INTERVAL_S = 1.0
SOURCE_SETTLE_S = 2.0
SOURCE_RESPONSE_DRAIN_S = 2.0
SOURCE_CHANGED_EXIT_CODE = 0
_WATCHER_FAILED_EXIT_CODE = 1
_WATCHER_THREAD_NAME = "blended-source-watcher"

# A watcher exit hands the declared plan and the session log to the server
# the client starts next, through a file keyed by the client's pid (the
# parent of both servers). omp restarted the server within 10 s (README,
# measured 2026-09-27). A handoff older than HANDOFF_MAX_AGE_S belongs to no
# restart and is discarded, loudly, so a later client that reuses the pid
# cannot inherit a plan it never declared.
HANDOFF_MAX_AGE_S = 60.0
_HANDOFF_NAME_FORMAT = "mcp-handoff-{:d}.json"
_HANDOFF_PLAN_KEY = "plan_declared"
_HANDOFF_SESSION_KEY = "session_name"
_HANDOFF_WRITTEN_AT_KEY = "written_at_s"
_RESUMED_EVENT_FORMAT = "resumed after a source-change restart; plan declared: {}"

_TOOL_CALL = toolcode_wrap_with_calling_convention(
    toolcode_load_from_filepath(__file__)
)

BLENDED_TOOLS: list[types.Tool] = [
    types.Tool(
        name=schema["function"]["name"],
        description=schema["function"]["description"],
        inputSchema=schema["function"]["parameters"],
    )
    for schema in TOOL_SCHEMAS
]
BLENDED_TOOL_NAMES = frozenset(tool.name for tool in BLENDED_TOOLS)

# blended captures renders as PNG only; any other suffix is a bug.
_IMAGE_SUFFIX = ".png"
_IMAGE_MIME_TYPE = "image/png"
_SESSION_NAME_FORMAT = "mcp-%Y-%m-%d-%H%M%S"
_ROUTING = "mcp"
_RAISED_IN_BLENDER_PREFIX = "Tool raised in Blender:\n"

# Claude Code shows an MCP client only the first 2,048 characters of a
# server's instructions (measured 2026-10-02: the text it delivered ended
# at index 2048 of 22,896). A rule every MCP agent must follow has to sit
# inside that head.
CLAUDE_CODE_INSTRUCTIONS_LIMIT_CHARACTERS = 2048

# MCP only: the user watches a live viewport here, unlike the headless
# bench, so this head leads the MCP instructions and stays out of the
# scored working agreement that build_system_prompt() renders. It condenses
# that agreement for clients that deliver only the head; the full text
# follows it. Models also use the start of a long context best (Lost in
# the Middle, DOI 10.48550/arXiv.2307.03172).
VIEWPORT_FOLLOW_TOOL_NAME = "jump_to_view3d_object_by_name"
# The working-agreement revision MCP_INSTRUCTIONS_HEAD condenses. A test
# fails when the active revision moves, so the head is reviewed with it.
MCP_INSTRUCTIONS_HEAD_CONDENSES_REVISION = 10
MCP_INSTRUCTIONS_HEAD = f"""\
# Must-read: the rules every blended session follows

The user watches this Blender's 3D viewport while you work.

1. Call `declare_plan` before any tool that changes the scene.
2. Build with blended's op tools. `run_python` is the last resort, and its
   `reason` must name what the ops lack.
3. Work in the SMALLEST step that makes progress. Read the gate report after
   every call and fix the specific measured failure.
4. Done is three things, in order: it executed, it passed the gate, and it
   looks right in `render_views` from several angles. Executing is not
   passing; passing is not looking right.
5. The gate measures structure, not intent. After the LAST operation, measure
   every number the user gave (sizes, thicknesses, positions, counts) on the
   finished object and print what you measured.
6. Every feature the brief names (ribs, a drainage hole, three legs) is real
   geometry, verified by measuring it.
7. A part resting on a surface meets it with a flat face: measure the
   contact, not the lowest point.
8. Changing a passed asset: touch only what they named; everything else must
   measure the SAME afterwards. Re-gate and re-render after every edit.
9. Every exported asset ships with its .blend: `export_asset` needs
   `blend_path`; anything exported another way calls `save_blend`. An asset
   without its .blend is not done.
10. When all of it holds, stop and report what you built, its measurements and
    the gate verdict. If an operation fails twice the same way, stop and say
    what you are stuck on. Art direction is the user's: ask, show renders.

Blender: these tools drive the user's OPEN Blender. If one answers
`{PAUSE_PREFIX}`, stop and tell the user. Never start your own Blender or
bpy, and do not retry or work around it.

Viewport: every scene-changing blended call (`run_python` too) re-centres the
user's 3D viewport on what it created or changed and ends with a `viewport:`
line. An object is framed once it is linked into the scene. To show something
else, call `{VIEWPORT_FOLLOW_TOOL_NAME}`."""


_MAXIMUM_CAUSE_DEPTH = 8


def _connection_error_in(error: BaseException) -> ConnectionError | None:
    """
    The ``ConnectionError`` behind *error*, if there is one: FastMCP wraps what
    an upstream tool raised in a ``ToolError`` whose ``__cause__`` is the
    original, so the exception itself is not enough.
    """
    current: BaseException | None = error
    for _ in range(_MAXIMUM_CAUSE_DEPTH):
        if current is None:
            return None
        if isinstance(current, ConnectionError):
            return current
        current = current.__cause__ or current.__context__
    return None


def blended_instructions(upstream_instructions: str) -> str:
    """The must-read head, blended's working agreement, then upstream's instructions."""
    return (
        f"{MCP_INSTRUCTIONS_HEAD}\n\n{build_system_prompt()}\n\n{upstream_instructions}"
    )


def source_fingerprint(
    roots: tuple[Path, ...] = SOURCE_ROOTS,
    skipped_paths: tuple[Path, ...] = SOURCE_SKIPPED_PATHS,
) -> str:
    """
    A short hash of every source file's path, mtime and size under ``roots``.

    Equal fingerprints mean no watched file was added, removed or rewritten.
    A missing root raises ``FileNotFoundError``: a fingerprint of nothing
    would never change and would silently stop the freshness guarantee. A
    listed name with nothing to stat is not a source file at that instant
    and is left out: one removed between the listing and the stat (a git
    checkout, the ``.!PID!name.py`` temp file of macOS ``sed -i``), or a
    dangling symlink such as Emacs's ``.#name.py`` lock. The change it is
    part of still shows, and the watcher's settle absorbs the churn.
    """
    skipped = frozenset(path.resolve() for path in skipped_paths)
    entries: list[tuple[str, int, int]] = []
    for root in roots:
        if not root.is_dir():
            raise FileNotFoundError(
                "Source root is not a directory: {:s}".format(str(root))
            )
        for directory, directory_names, file_names in os.walk(root):
            directory_path = Path(directory)
            directory_names[:] = [
                name
                for name in directory_names
                if name not in SOURCE_SKIPPED_DIRECTORY_NAMES
                and (directory_path / name).resolve() not in skipped
            ]
            for name in file_names:
                file_path = directory_path / name
                if file_path.suffix not in SOURCE_SUFFIXES:
                    continue
                try:
                    stat = file_path.stat()
                except FileNotFoundError:
                    continue
                relative = (Path(root.name) / file_path.relative_to(root)).as_posix()
                entries.append((relative, stat.st_mtime_ns, stat.st_size))
    entries.sort()
    return hashlib.sha256(repr(entries).encode("utf-8")).hexdigest()[
        :_FINGERPRINT_HEX_CHARACTERS
    ]


def _docstring_as_python_313(docstring: str) -> str:
    """
    The docstring as Python 3.13+ compiles it: common indentation of the
    lines after the first removed, whitespace-only lines emptied. On 3.11
    the raw ``__doc__`` keeps the indentation; upstream's tool listing is
    pinned to the 3.13 form.
    """
    lines = docstring.expandtabs().split("\n")
    margin = min(
        (len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()),
        default=0,
    )
    return "\n".join(
        [
            lines[0].lstrip(),
            *(line[margin:] if line.strip() else "" for line in lines[1:]),
        ]
    )


def _image_content(path: Path) -> types.ImageContent:
    if path.suffix != _IMAGE_SUFFIX:
        raise RuntimeError("blended returned a non-PNG image: {:s}".format(str(path)))
    return types.ImageContent(
        type="image",
        data=base64.b64encode(path.read_bytes()).decode("ascii"),
        mimeType=_IMAGE_MIME_TYPE,
    )


def handoff_path(log_directory: Path, parent_pid: int) -> Path:
    """Where a watcher exit leaves its session for the client's next server."""
    return log_directory / _HANDOFF_NAME_FORMAT.format(parent_pid)


@dataclass
class BlendedSession:
    """
    The plan gate and the transcript for one MCP client session over stdio.
    A declared plan holds until the next ``declare_plan``, across a watcher
    restart too (``write_handoff``, ``resume``).
    """

    log_directory: Path
    output_root: Path
    plan_declared: bool = False
    # A resumed session's log and output directory; None until the first call
    # of a new session names them.
    session_name: str | None = None
    _transcript: ChatTranscript | None = field(default=None, init=False, repr=False)
    _output_directory: Path | None = field(default=None, init=False, repr=False)

    @classmethod
    def resume(
        cls,
        log_directory: Path,
        output_root: Path,
        parent_pid: int,
        now_s: float | None = None,
    ) -> "BlendedSession":
        """
        The session a watcher exit handed to this client's next server, or a
        new one. The handoff is consumed either way; a malformed or expired
        one is refused on stderr.
        """
        path = handoff_path(log_directory, parent_pid)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return cls(log_directory, output_root)
        # Consumed before it is parsed, so a handoff that cannot be read is
        # refused once, not on every start.
        path.unlink(missing_ok=True)
        try:
            handoff = json.loads(raw.decode("utf-8"))
            plan_declared = handoff[_HANDOFF_PLAN_KEY]
            session_name = handoff[_HANDOFF_SESSION_KEY]
            written_at_s = handoff[_HANDOFF_WRITTEN_AT_KEY]
            if not (
                isinstance(plan_declared, bool)
                and (session_name is None or isinstance(session_name, str))
                and isinstance(written_at_s, (int, float))
            ):
                raise ValueError("unexpected field types: {!r}".format(handoff))
        except (ValueError, KeyError, TypeError) as error:
            print(
                "blender-mcp: refused a malformed handoff {:s} ({:s}); starting a new session".format(
                    str(path), str(error)
                ),
                file=sys.stderr,
                flush=True,
            )
            return cls(log_directory, output_root)
        age_s = (time.time() if now_s is None else now_s) - written_at_s
        if not 0.0 <= age_s <= HANDOFF_MAX_AGE_S:
            print(
                "blender-mcp: discarded a handoff {:.0f} s old (limit {:.0f} s); starting a new session".format(
                    age_s, HANDOFF_MAX_AGE_S
                ),
                file=sys.stderr,
                flush=True,
            )
            return cls(log_directory, output_root)
        return cls(
            log_directory,
            output_root,
            plan_declared=plan_declared,
            session_name=session_name,
        )

    def write_handoff(self, parent_pid: int) -> Path:
        """Leave the plan and the session log to this client's next server."""
        self.log_directory.mkdir(parents=True, exist_ok=True)
        path = handoff_path(self.log_directory, parent_pid)
        path.write_text(
            json.dumps(
                {
                    _HANDOFF_PLAN_KEY: self.plan_declared,
                    _HANDOFF_SESSION_KEY: self.session_name,
                    _HANDOFF_WRITTEN_AT_KEY: time.time(),
                }
            ),
            encoding="utf-8",
        )
        return path

    def _open(self) -> tuple[ChatTranscript, Path]:
        # Created on the first call, so a server that serves no blended
        # call leaves no empty log.
        if self._transcript is None or self._output_directory is None:
            resumed = self.session_name is not None
            if self.session_name is None:
                self.session_name = (
                    datetime.now().astimezone().strftime(_SESSION_NAME_FORMAT)
                )
            self._transcript = ChatTranscript(
                self.log_directory, session_name=self.session_name, routing=_ROUTING
            )
            self._output_directory = (self.output_root / self.session_name).resolve()
            self._output_directory.mkdir(parents=True, exist_ok=True)
            if resumed:
                self._transcript.record(
                    "session", _RESUMED_EVENT_FORMAT.format(self.plan_declared)
                )
        return self._transcript, self._output_directory

    async def call(
        self, tool_name: str, arguments: dict[str, Any] | None
    ) -> types.CallToolResult:
        arguments = arguments or {}
        transcript, output_directory = self._open()
        transcript.record("tool", "{:s}({:s})".format(tool_name, json.dumps(arguments)))

        # Look for the open Blender before anything else: a plan, or the
        # refusal to act without one, means nothing when no Blender is there.
        try:
            await anyio.to_thread.run_sync(require_live_blender)
        except ConnectionError as error:
            transcript.record("error", str(error))
            raise

        if plan_required_for(tool_name) and not self.plan_declared:
            transcript.record("result", MISSING_PLAN_REFUSAL)
            transcript.record(
                TOOL_EVENT_KIND,
                encode_tool_event(
                    refused_tool_event(
                        tool_name,
                        arguments,
                        MISSING_PLAN_REFUSAL,
                        TOOL_SCHEMAS_FINGERPRINT,
                    )
                ),
            )
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=MISSING_PLAN_REFUSAL)],
                isError=True,
            )

        code = toolcode_format_call(
            _TOOL_CALL,
            Params(
                tool_name,
                json.dumps(arguments),
                str(output_directory),
                str(REPOSITORY_SRC),
                VENV_SITE_PACKAGES,
                source_fingerprint(),
                PLUGIN_SOURCE_ROOTS,
                PLUGIN_PACKAGES,
            ),
        )
        started = time.perf_counter()
        try:
            response = await anyio.to_thread.run_sync(send_code, code, True)
        except ConnectionError as error:
            transcript.record("error", str(error))
            raise

        if response["status"] != "ok":
            outcome = ToolOutcome(
                _RAISED_IN_BLENDER_PREFIX
                + str(response.get("message", ""))[:MAXIMUM_TRACEBACK_CHARACTERS],
                ok=False,
            )
        else:
            result = response["result"]
            assert isinstance(result, dict)
            outcome = outcome_from_json(result["outcome"])
        wall_time_s = time.perf_counter() - started

        if tool_name == PLAN_TOOL_NAME and outcome.ok:
            self.plan_declared = True

        transcript.record("result", outcome.text)
        for image_path in outcome.images:
            transcript.record("render", str(image_path), image_paths=(str(image_path),))
        transcript.record(
            TOOL_EVENT_KIND,
            encode_tool_event(
                dispatched_tool_event(
                    tool_name, arguments, outcome, wall_time_s, TOOL_SCHEMAS_FINGERPRINT
                )
            ),
        )
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text=outcome.text),
                *(_image_content(image_path) for image_path in outcome.images),
            ],
            isError=not outcome.ok,
        )


class BlendedFastMCP(FastMCP):  # type: ignore[misc]
    """Upstream's FastMCP server with blended's tools served beside its own."""

    def __init__(self, name: str, instructions: str) -> None:
        super().__init__(name, instructions=instructions)
        # The client that spawned this server; it spawns the next one too.
        self._parent_pid = os.getppid()
        self._blended = BlendedSession.resume(
            default_log_directory(REPOSITORY_ROOT),
            REPOSITORY_ROOT / "outputs" / "mcp",
            self._parent_pid,
        )
        # Calls inside call_tool, and when the last one returned (-inf until
        # one has); both read and written under _in_flight_lock.
        self._in_flight = 0
        self._last_call_returned_s = -math.inf
        self._in_flight_lock = threading.Lock()

    def add_tool(
        self, fn: Any, *args: Any, description: str | None = None, **kwargs: Any
    ) -> None:
        if description is None and fn.__doc__:
            description = _docstring_as_python_313(fn.__doc__)
        super().add_tool(fn, *args, description=description, **kwargs)

    async def list_tools(self) -> list[types.Tool]:
        upstream = await super().list_tools()
        overlap = BLENDED_TOOL_NAMES.intersection(tool.name for tool in upstream)
        if overlap:
            raise RuntimeError(
                "Upstream and blended tools share names: {:s}".format(
                    ", ".join(sorted(overlap))
                )
            )
        return [*upstream, *BLENDED_TOOLS]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        with self._in_flight_lock:
            self._in_flight += 1
        try:
            if name in BLENDED_TOOL_NAMES:
                return await self._blended.call(name, arguments)
            if name not in TOOLS_WITHOUT_BLENDER:
                await anyio.to_thread.run_sync(require_live_blender)
            return await super().call_tool(name, arguments)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Whatever raised, a missing Blender is a pause the agent can act
            # on, not a stack trace; anything else is a real failure.
            unavailable = _connection_error_in(error)
            if unavailable is None:
                raise
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=pause_text(str(unavailable)))
                ],
                isError=True,
            )
        finally:
            with self._in_flight_lock:
                self._in_flight -= 1
                self._last_call_returned_s = time.monotonic()

    def exit_on_source_change(self) -> None:
        """
        Exit the process once the watched sources changed and then held
        still for ``SOURCE_SETTLE_S``, so the MCP client restarts a server
        that lists the current tools and instructions. A change that lands
        while the server waits restarts the settle clock, so the exit does
        not land in the middle of a rewrite.

        The exit happens under the in-flight lock, with no tool call in
        flight and the last one returned at least
        ``SOURCE_RESPONSE_DRAIN_S`` ago: ``call_tool`` returns before the
        SDK writes the response, so "nothing in flight" alone could drop the
        result of a call Blender already ran. A request read in the instant
        of the exit, before it reaches ``call_tool``, is lost undispatched:
        Blender never ran it, and the client sees the connection close.
        """
        baseline = source_fingerprint()
        threading.Thread(
            target=self._watch_sources_or_exit,
            args=(baseline,),
            name=_WATCHER_THREAD_NAME,
            daemon=True,
        ).start()

    def _watch_sources_or_exit(self, baseline: str) -> None:
        try:
            self._watch_sources(baseline)
        except BaseException:  # pylint: disable=broad-exception-caught
            # The watcher can no longer see edits, so freshness is off: say
            # why, then end the process once idle, even when stderr is what
            # broke.
            try:
                traceback.print_exc(file=sys.stderr)
                sys.stderr.flush()
            finally:
                self._exit_once_idle(_WATCHER_FAILED_EXIT_CODE)

    def _watch_sources(self, baseline: str) -> None:
        """Poll the fingerprint until a change from ``baseline`` has settled and the server is idle."""
        latest = baseline
        latest_since_s = time.monotonic()
        announced = baseline
        while True:
            time.sleep(SOURCE_POLL_INTERVAL_S)
            current = source_fingerprint()
            if current != latest:
                latest = current
                latest_since_s = time.monotonic()
                continue
            if (
                current == baseline
                or time.monotonic() - latest_since_s < SOURCE_SETTLE_S
            ):
                continue
            if current != announced:
                announced = current
                print(
                    "blender-mcp: sources changed ({:s} -> {:s}); exiting once idle "
                    "so the client restarts a fresh build".format(baseline, current),
                    file=sys.stderr,
                    flush=True,
                )
            self._exit_if_idle(SOURCE_CHANGED_EXIT_CODE)

    def _exit_once_idle(self, exit_code: int) -> NoReturn:
        while True:
            self._exit_if_idle(exit_code)
            time.sleep(SOURCE_POLL_INTERVAL_S)

    def _exit_if_idle(self, exit_code: int) -> None:
        """``os._exit`` under the in-flight lock, so no call starts meanwhile, once idle and drained."""
        with self._in_flight_lock:
            drained_s = time.monotonic() - self._last_call_returned_s
            if self._in_flight == 0 and drained_s >= SOURCE_RESPONSE_DRAIN_S:
                self._hand_off()
                os._exit(exit_code)

    def _hand_off(self) -> None:
        """
        Write the handoff for the client's next server. A failure is printed
        and the exit goes ahead: a server kept alive on stale code is worse
        than one whose successor asks for the plan again.
        """
        try:
            self._blended.write_handoff(self._parent_pid)
        except Exception:  # pylint: disable=broad-exception-caught
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
