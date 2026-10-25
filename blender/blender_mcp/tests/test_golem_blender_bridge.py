# SPDX-FileCopyrightText: 2026 Thomas Brittain
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for the golem_blender bridge's server side: the plan gate, the
wire call, image content, errors raised in Blender, the event log, and
the source fingerprint that keeps the server and Blender fresh.

No Blender: ``send_code`` is replaced with a stub that answers like the
add-on does, and the probe for the open Blender is stubbed to find one. The
live path is ``test_blender_mcp_with_blender.py``; the pause is
``tests/pure/test_live_blender.py``.
"""

__all__ = ()

import asyncio
import base64
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

from blmcp import argument_parser
from blmcp.tools_helpers import (
    golem_blender_bridge,
    golem_blender_bridge_toolcode,
    toolcode_format_call,
)
from blmcp.tools_helpers.golem_remote import GolemRemote
from mcp import types as mcp_types  # pylint: disable=import-error,no-name-in-module
from mcp.server.fastmcp import FastMCP  # pylint: disable=import-error,no-name-in-module

from golem_blender.agent.outcome import ToolOutcome, outcome_to_json
from golem_blender.agent.plan import MISSING_PLAN_REFUSAL
from golem_blender.agent.prompt_versions import get_revision

_BOX_ARGUMENTS = {"name": "Crate", "width_m": 0.5, "depth_m": 0.5, "height_m": 0.5}

# One second: coarser than any filesystem's timestamp granularity, so a
# rewrite moved this much later always reads as a new mtime.
_REWRITE_LATER_BY_NS = 1_000_000_000
# A bare interpreter running a few toolcode calls on fake checkouts.
_TOOLCODE_DRIVER_TIMEOUT_S = 60.0


def _ok_response(outcome: ToolOutcome) -> dict[str, object]:
    return {
        "status": "ok",
        "result": {"status": "ok", "outcome": outcome_to_json(outcome)},
    }


def _stub_live_blender_probe(test_case: unittest.TestCase) -> None:
    """
    Make the probe for the open Blender find one. It is a socket connect, so
    with no Blender listening it would pause every call before the stubbed
    ``send_code`` is reached.
    """
    patcher = mock.patch.object(golem_blender_bridge, "require_live_blender", lambda: None)
    patcher.start()
    test_case.addCleanup(patcher.stop)


class TestGolemBlenderBridge(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        root = Path(self._directory.name)
        self._log_directory = root / "logs"
        self._session = golem_blender_bridge.GolemBlenderSession(
            self._log_directory, root / "outputs"
        )
        self._responses: list[dict[str, object]] = []
        self._sent: list[str] = []
        patcher = mock.patch.object(golem_blender_bridge, "send_code", self._send_code)
        patcher.start()
        self.addCleanup(patcher.stop)
        _stub_live_blender_probe(self)
        self.addCleanup(self._directory.cleanup)

    def _send_code(
        self, code: str, strict_json: bool, _timeout_s: float = 1800.0
    ) -> dict[str, object]:
        self.assertTrue(strict_json)
        self._sent.append(code)
        return self._responses.pop(0)

    def _call(self, tool_name: str, arguments: dict[str, object]) -> object:
        return asyncio.run(self._session.call(tool_name, arguments))

    def _log_rows(self) -> list[dict[str, object]]:
        (jsonl_path,) = self._log_directory.glob("mcp-*.jsonl")
        return [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_scene_changing_tool_before_plan_is_refused_without_blender(self) -> None:
        result = self._call("add_box", _BOX_ARGUMENTS)

        self.assertTrue(result.isError)
        self.assertEqual(result.content[0].text, MISSING_PLAN_REFUSAL)
        self.assertEqual(self._sent, [])
        self.assertEqual(self._log_rows()[-1]["data"]["refusal"], MISSING_PLAN_REFUSAL)

    def test_declared_plan_opens_the_gate(self) -> None:
        self._responses = [
            _ok_response(ToolOutcome("Plan declared:\n  1. x")),
            _ok_response(ToolOutcome("Added Crate")),
        ]

        self.assertFalse(self._call("declare_plan", {"steps": ["x"]}).isError)
        result = self._call("add_box", _BOX_ARGUMENTS)

        self.assertFalse(result.isError)
        self.assertEqual(len(self._sent), 2)
        self.assertIn("'add_box'", self._sent[1])

    def test_failed_outcome_carries_its_render_as_image_content(self) -> None:
        png_path = Path(self._directory.name) / "front.png"
        png_bytes = b"\x89PNG\r\n\x1a\nnot-a-real-image"
        png_path.write_bytes(png_bytes)
        self._responses = [
            _ok_response(ToolOutcome("gate failed", images=(png_path,), ok=False))
        ]

        result = self._call("render_views", {"object_name": "Crate"})

        self.assertTrue(result.isError)
        self.assertEqual(result.content[1].type, "image")
        self.assertEqual(base64.b64decode(result.content[1].data), png_bytes)

    def test_exception_in_blender_is_an_error_result(self) -> None:
        self._responses = [
            {"status": "error", "message": "Traceback (most recent call last):\n  boom"}
        ]

        result = self._call("render_views", {"object_name": "Crate"})

        self.assertTrue(result.isError)
        self.assertTrue(result.content[0].text.startswith("Tool raised in Blender:"))

    def test_a_long_call_forwards_the_progress_file_as_it_is_written(self) -> None:
        """A call that writes progress while it runs must reach the client as progress.

        The op runs inside Blender and this server is a different process, so the
        only thing they share is the call's output directory: the stub writes
        `progress.json` the way an op would, and the heartbeat must read it and
        hand it upstream instead of leaving the client to time out.
        """
        self._responses = [_ok_response(ToolOutcome("Added Crate"))]
        received: list[tuple[float, float | None, str]] = []
        progress_arguments = {"part": 31, "of": 77, "stage": "part gate"}

        def send_code_writing_progress(
            code: str, strict_json: bool, _timeout_s: float = 1800.0
        ) -> dict[str, object]:
            output_directory = next(
                path
                for path in (Path(self._directory.name) / "outputs").rglob("mcp-*")
                if path.is_dir()
            )
            (output_directory / "progress.json").write_text(
                json.dumps(progress_arguments), encoding="utf-8"
            )
            time.sleep(0.3)
            return self._send_code(code, strict_json)

        async def record_progress(
            progress: float, total: float | None, message: str | None
        ) -> None:
            received.append((progress, total, message or ""))

        with (
            mock.patch.object(
                golem_blender_bridge, "send_code", send_code_writing_progress
            ),
            mock.patch.object(golem_blender_bridge, "PROGRESS_HEARTBEAT_S", 0.05),
        ):
            result = asyncio.run(
                self._session.call(
                    "assembly_report",
                    {"name": "Bakery"},
                    report_progress=record_progress,
                )
            )

        self.assertFalse(result.isError)
        self.assertTrue(received, "the heartbeat sent no progress at all")
        self.assertTrue(
            any('"part": 31' in message for _, _, message in received),
            [message for _, _, message in received],
        )

    def test_a_timed_out_call_says_blender_is_still_running_and_not_paused(self) -> None:
        """A timeout is NOT a pause: Blender accepted the call and kept working.

        Measured need, 2026-10-24: a 77-part export outlived the socket timeout,
        the bridge called it PAUSED, and the agent read a live session as dead.
        """
        self._responses = []

        def send_code_that_times_out(
            _code: str, _strict_json: bool, _timeout_s: float = 1800.0
        ) -> dict[str, object]:
            raise golem_blender_bridge.BlenderCallTimedOut(
                "Blender did not answer within 1800 s at localhost:9876"
            )

        with mock.patch.object(
            golem_blender_bridge, "send_code", send_code_that_times_out
        ):
            result = self._call("assembly_report", {"name": "Bakery"})

        self.assertTrue(result.isError)
        text = result.content[0].text
        self.assertTrue(
            text.startswith("Blender is still running assembly_report"), text
        )
        self.assertIn("it was NOT stopped", text)
        self.assertIn("Do not re-issue the call", text)
        self.assertNotIn(golem_blender_bridge.PAUSE_PREFIX, text)
        self.assertNotIn("PAUSED", text)


class TestSourceFingerprint(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        package = Path(self._directory.name) / "root" / "pkg"
        self._source = package / "a.py"
        # A watched suffix, so only the __pycache__ skip keeps it out (the
        # suffix filter alone already drops a .pyc).
        self._cached = package / "__pycache__" / "a.py"
        self._skipped = package / "data" / "api"
        self._skipped_source = self._skipped / "x.py"
        for path in (self._source, self._cached, self._skipped_source):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("value = 1\n", encoding="utf-8")
        self._roots = (package,)

    def _fingerprint(self) -> str:
        return golem_blender_bridge.source_fingerprint(self._roots, (self._skipped,))

    def _rewrite_later(self, path: Path, text: str) -> None:
        modified_ns = path.stat().st_mtime_ns + _REWRITE_LATER_BY_NS
        path.write_text(text, encoding="utf-8")
        os.utime(path, ns=(modified_ns, modified_ns))

    def test_unchanged_tree_keeps_its_fingerprint(self) -> None:
        self.assertEqual(self._fingerprint(), self._fingerprint())

    def test_a_same_size_rewrite_changes_the_fingerprint(self) -> None:
        # Only the mtime differs: the edit a size check alone would miss.
        before = self._fingerprint()
        size_before = self._source.stat().st_size
        self._rewrite_later(self._source, "value = 2\n")
        self.assertEqual(self._source.stat().st_size, size_before)
        self.assertNotEqual(self._fingerprint(), before)

    def test_a_resize_under_the_old_mtime_changes_the_fingerprint(self) -> None:
        # Only the size differs: the edit an mtime check alone would miss.
        before = self._fingerprint()
        modified_ns = self._source.stat().st_mtime_ns
        self._source.write_text("value = 22\n", encoding="utf-8")
        os.utime(self._source, ns=(modified_ns, modified_ns))
        self.assertNotEqual(self._fingerprint(), before)

    def test_pycache_and_skipped_paths_do_not_change_it(self) -> None:
        before = self._fingerprint()
        self._rewrite_later(self._cached, "value = 3  # changed\n")
        self._rewrite_later(self._skipped_source, "value = 3  # changed\n")
        self.assertEqual(self._fingerprint(), before)

    def test_a_dangling_symlink_is_not_a_source_file(self) -> None:
        # Emacs keeps `.#name.py -> user@host.pid:boot` beside a modified
        # buffer: a watched suffix with nothing to stat.
        before = self._fingerprint()
        (self._source.parent / ".#a.py").symlink_to("user@host.12345:1700000000")
        self.assertEqual(self._fingerprint(), before)

    def test_missing_root_fails_loud(self) -> None:
        with self.assertRaises(FileNotFoundError):
            golem_blender_bridge.source_fingerprint(
                (Path(self._directory.name) / "absent",), ()
            )


class TestInstructionsHead(unittest.TestCase):
    """The rules every MCP agent must get sit in the head every client delivers."""

    def test_head_leads_the_instructions_within_claude_codes_limit(self) -> None:
        instructions = golem_blender_bridge.golem_blender_instructions("upstream")
        self.assertTrue(instructions.startswith(golem_blender_bridge.MCP_INSTRUCTIONS_HEAD))
        self.assertLessEqual(
            len(golem_blender_bridge.MCP_INSTRUCTIONS_HEAD),
            golem_blender_bridge.CLAUDE_CODE_INSTRUCTIONS_LIMIT_CHARACTERS,
        )

    def test_head_condenses_the_active_working_agreement(self) -> None:
        # A new active revision fails here until someone re-reads the head.
        self.assertEqual(
            golem_blender_bridge.MCP_INSTRUCTIONS_HEAD_CONDENSES_REVISION,
            get_revision(None).revision,
        )

    def test_head_names_a_tool_the_server_registers(self) -> None:
        # Ground truth is the registry, not the string: a renamed tool
        # would leave the head pointing at nothing.
        name = golem_blender_bridge.VIEWPORT_FOLLOW_TOOL_NAME
        server = FastMCP("viewport-follow-probe")
        importlib.import_module(f"blmcp.tools.{name}").register(server)
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        self.assertIn(name, registered)
        self.assertIn(f"`{name}`", golem_blender_bridge.MCP_INSTRUCTIONS_HEAD)

    def test_head_requires_the_blend_source_and_names_real_tools(self) -> None:
        # OT-50: an export without its .blend is not done. The rule names
        # the argument and the tool, and both must exist in the registry.
        head = golem_blender_bridge.MCP_INSTRUCTIONS_HEAD
        self.assertIn("without its .blend is not done", head)
        for name in ("export_asset", "save_blend"):
            self.assertIn(f"`{name}`", head)
            self.assertIn(name, golem_blender_bridge.GOLEM_BLENDER_TOOL_NAMES)
        exported = next(
            tool for tool in golem_blender_bridge.GOLEM_BLENDER_TOOLS if tool.name == "export_asset"
        )
        self.assertIn("blend_path", exported.inputSchema["required"])
        self.assertIn("`blend_path`", head)

    def test_head_names_the_grid_layout_tool(self) -> None:
        # Several models in one scene are laid side by side, not stacked: the
        # rule names the op, and the op must still be a registered tool — a
        # rename would leave the head pointing at nothing.
        head = golem_blender_bridge.MCP_INSTRUCTIONS_HEAD
        self.assertIn("`lay_out_grid`", head)
        self.assertIn("lay_out_grid", golem_blender_bridge.GOLEM_BLENDER_TOOL_NAMES)

    def test_head_says_an_assembly_must_declare_the_side_it_is_used_from(
        self,
    ) -> None:
        # The defect the user found by looking: a bakery whose ovens faced each
        # other and whose spout was sunk in a wall passed every gate. The head
        # tells every agent to declare the side, and both names must be real
        # tools so the rule cannot point at nothing.
        head = golem_blender_bridge.MCP_INSTRUCTIONS_HEAD
        self.assertIn("`interaction_side`", head)
        for name in ("define_assembly", "lay_out_grid"):
            self.assertIn(f"`{name}`", head)
            self.assertIn(name, golem_blender_bridge.GOLEM_BLENDER_TOOL_NAMES)

    def test_readme_states_the_measured_head_length(self) -> None:
        # The README said 1,823 characters while the head was 1,981.
        readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(
            encoding="utf-8"
        )
        measured = f"{len(golem_blender_bridge.MCP_INSTRUCTIONS_HEAD):,} characters"
        self.assertIn(f"`MCP_INSTRUCTIONS_HEAD`, {measured}", readme)


class TestWatcherIsOptIn(unittest.TestCase):
    """Claude Code and Claude Desktop never restart a server that exits."""

    def test_watcher_is_off_unless_asked_for(self) -> None:
        self.assertFalse(argument_parser().parse_args([]).exit_on_source_change)
        self.assertTrue(
            argument_parser()
            .parse_args(["--exit-on-source-change"])
            .exit_on_source_change
        )

    def test_project_configs_opt_in_only_for_omp(self) -> None:
        # Ground truth is the config each client reads. The project's own
        # .omp/mcp.json registers nothing (the global ~/.omp/agent/mcp.json
        # carries `golem` with the watcher on); Claude Code's .mcp.json
        # registers `golem` without it.
        claude_code = json.loads(
            (golem_blender_bridge.REPOSITORY_ROOT / ".mcp.json").read_text(encoding="utf-8")
        )
        omp = json.loads(
            (golem_blender_bridge.REPOSITORY_ROOT / ".omp" / "mcp.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn(
            "--exit-on-source-change",
            claude_code["mcpServers"]["golem"].get("args", []),
        )
        self.assertNotIn("golem", omp["mcpServers"])
        self.assertTrue(
            claude_code["mcpServers"]["golem"]["command"].endswith("/blender-mcp")
        )


class _Exited(BaseException):
    """What the patched ``os._exit`` raises: the process would end here."""

    def __init__(self, exit_code: int) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class _ClockStopped(BaseException):
    """Ends a watcher run that has not exited by the end of its timeline."""


class _HeldOpen:
    """Suspends the coroutine awaiting it once: a tool call still inside Blender."""

    def __await__(self):  # type: ignore[no-untyped-def]
        yield


class TestSourceWatcher(unittest.TestCase):
    """
    The watcher's exit decision on a fake clock: the fingerprint follows a
    timeline, scheduled tool calls run through the real ``call_tool`` (its
    golem_blender dispatch held open until the call's return time), and
    ``os._exit`` raises. No real sleep and no real exit.
    """

    # pylint: disable=protected-access

    _BASELINE = "baseline"
    _EDITED = "edited"
    _EDITED_AGAIN = "edited-again"
    _END_S = 60.0

    def setUp(self) -> None:
        self._server = golem_blender_bridge.GolemBlenderFastMCP(
            "watcher-probe", instructions="probe"
        )
        self._handoffs: list[int] = []
        self._server._golem_blender = types.SimpleNamespace(
            call=self._golem_blender_call, write_handoff=self._write_handoff
        )
        self._tool_name = min(golem_blender_bridge.GOLEM_BLENDER_TOOL_NAMES)
        self._now_s = 0.0
        self._timeline: list[tuple[float, str]] = []
        self._calls: list[tuple[float, float]] = []
        self._running: dict[int, object] = {}
        self._stderr = io.StringIO()
        for name, replacement in (
            (
                "time",
                types.SimpleNamespace(sleep=self._sleep, monotonic=lambda: self._now_s),
            ),
            ("os", types.SimpleNamespace(_exit=self._exit)),
            ("sys", types.SimpleNamespace(stderr=self._stderr)),
            ("source_fingerprint", self._fingerprint),
        ):
            patcher = mock.patch.object(golem_blender_bridge, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    async def _golem_blender_call(
        _name: str, _arguments: dict[str, object], **_kwargs: object
    ) -> None:
        await _HeldOpen()

    def _fingerprint(self) -> str:
        current = self._BASELINE
        for time_s, value in self._timeline:
            if time_s <= self._now_s:
                current = value
        return current

    def _sleep(self, interval_s: float) -> None:
        # Advance the clock event by event: at a call's start time, step the
        # real call_tool until its dispatch is held open; at its return
        # time, step it to completion, so call_tool's own bookkeeping runs.
        end_s = self._now_s + interval_s
        if end_s > self._END_S:
            raise _ClockStopped()
        events = sorted(
            (event_s, index, is_return)
            for index, (start_s, return_s) in enumerate(self._calls)
            for event_s, is_return in ((start_s, False), (return_s, True))
            if self._now_s < event_s <= end_s
        )
        for event_s, index, is_return in events:
            self._now_s = event_s
            if is_return:
                with self.assertRaises(StopIteration):
                    self._running.pop(index).send(None)  # type: ignore[attr-defined]
            else:
                call = self._server.call_tool(self._tool_name, {})
                call.send(None)
                self._running[index] = call
        self._now_s = end_s

    def _write_handoff(self, parent_pid: int) -> None:
        self._handoffs.append(parent_pid)

    def _exit(self, exit_code: int) -> None:
        # Every exit first leaves the session to the client's next server.
        if self._handoffs != [self._server._parent_pid]:
            raise AssertionError(
                "exit without exactly one handoff: {!r}".format(self._handoffs)
            )
        raise _Exited(exit_code)

    def _watch(self) -> tuple[int, float] | None:
        """(exit code, exit time) once the watcher exits, or None if the clock ran out first."""
        try:
            self._server._watch_sources(self._BASELINE)
        except _Exited as exited:
            return exited.exit_code, self._now_s
        except _ClockStopped:
            return None
        raise AssertionError("_watch_sources returned without exiting")

    def test_a_settled_edit_exits_cleanly_once_idle(self) -> None:
        edit_s = 1.5
        self._timeline = [(edit_s, self._EDITED)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        exit_code, exit_s = exited
        self.assertEqual(exit_code, golem_blender_bridge.SOURCE_CHANGED_EXIT_CODE)
        self.assertGreaterEqual(exit_s - edit_s, golem_blender_bridge.SOURCE_SETTLE_S)
        self.assertIn(self._EDITED, self._stderr.getvalue())

    def test_the_exit_waits_for_the_last_response_to_drain(self) -> None:
        # The edit settles while a call runs. call_tool returns before the
        # SDK writes the response, so idle alone is not enough to exit.
        call_returned_s = 6.5
        self._timeline = [(1.5, self._EDITED)]
        self._calls = [(1.8, call_returned_s)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        exit_code, exit_s = exited
        self.assertEqual(exit_code, golem_blender_bridge.SOURCE_CHANGED_EXIT_CODE)
        self.assertGreaterEqual(
            exit_s - call_returned_s, golem_blender_bridge.SOURCE_RESPONSE_DRAIN_S
        )

    def test_an_edit_while_waiting_restarts_the_settle_clock(self) -> None:
        # The first edit settles during a long call; a second burst lands
        # just before the call returns, so the exit waits for it to settle.
        second_edit_s = 9.8
        self._timeline = [(1.5, self._EDITED), (second_edit_s, self._EDITED_AGAIN)]
        self._calls = [(1.8, 10.0)]
        exited = self._watch()
        self.assertIsNotNone(exited)
        _exit_code, exit_s = exited
        self.assertGreaterEqual(exit_s - second_edit_s, golem_blender_bridge.SOURCE_SETTLE_S)
        self.assertIn(self._EDITED_AGAIN, self._stderr.getvalue())

    def test_an_edit_reverted_to_the_baseline_never_exits(self) -> None:
        self._timeline = [(1.5, self._EDITED), (2.5, self._BASELINE)]
        self.assertIsNone(self._watch())

    def test_a_broken_watcher_exits_with_the_failure_code_once_idle(self) -> None:
        call_returned_s = 4.5
        self._calls = [(0.5, call_returned_s)]
        with (
            mock.patch.object(
                golem_blender_bridge, "source_fingerprint", side_effect=RuntimeError("probe")
            ),
            self.assertRaises(_Exited) as exited,
        ):
            self._server._watch_sources_or_exit(self._BASELINE)
        self.assertEqual(
            exited.exception.exit_code, golem_blender_bridge._WATCHER_FAILED_EXIT_CODE
        )
        self.assertGreaterEqual(
            self._now_s - call_returned_s, golem_blender_bridge.SOURCE_RESPONSE_DRAIN_S
        )
        self.assertIn("RuntimeError: probe", self._stderr.getvalue())


class TestHandoff(unittest.TestCase):
    """
    A watcher restart keeps the declared plan and the session log: the
    exiting server writes a handoff keyed by its client's pid, and the
    client's next server consumes it.
    """

    # pylint: disable=protected-access

    _CLIENT_PID = 4242
    _OTHER_CLIENT_PID = 4343
    _BOX: ClassVar[dict[str, object]] = {
        "name": "Crate",
        "width_m": 0.5,
        "depth_m": 0.5,
        "height_m": 0.5,
    }

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        root = Path(self._directory.name)
        self._log_directory = root / "logs"
        self._output_root = root / "outputs"
        patcher = mock.patch.object(golem_blender_bridge, "send_code", self._send_code)
        patcher.start()
        self.addCleanup(patcher.stop)
        _stub_live_blender_probe(self)

    @staticmethod
    def _send_code(
        _code: str, _strict_json: bool, _timeout_s: float = 1800.0
    ) -> dict[str, object]:
        return _ok_response(ToolOutcome("ok"))

    def _resume(
        self, parent_pid: int, now_s: float | None = None
    ) -> golem_blender_bridge.GolemBlenderSession:
        return golem_blender_bridge.GolemBlenderSession.resume(
            self._log_directory, self._output_root, parent_pid, now_s
        )

    def _declared_session_handed_off(self) -> golem_blender_bridge.GolemBlenderSession:
        session = self._resume(self._CLIENT_PID)
        asyncio.run(session.call("declare_plan", {"steps": ["Add a box"]}))
        session.write_handoff(self._CLIENT_PID)
        return session

    def test_next_server_keeps_the_plan_and_the_log(self) -> None:
        before = self._declared_session_handed_off()
        after = self._resume(self._CLIENT_PID)
        self.assertTrue(after.plan_declared)
        self.assertEqual(after.session_name, before.session_name)
        self.assertFalse(
            golem_blender_bridge.handoff_path(self._log_directory, self._CLIENT_PID).exists()
        )

        result = asyncio.run(after.call("add_box", self._BOX))
        self.assertFalse(result.isError)
        (jsonl_path,) = self._log_directory.glob("mcp-*.jsonl")
        rows = [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        ]
        indices = [row["index"] for row in rows]
        self.assertEqual(indices, list(range(1, len(indices) + 1)))
        self.assertIn(
            "resumed after a source-change restart; plan declared: True",
            [row["text"] for row in rows if row["kind"] == "session"],
        )

    def test_another_clients_server_starts_fresh_and_leaves_the_handoff(self) -> None:
        self._declared_session_handed_off()
        other = self._resume(self._OTHER_CLIENT_PID)
        self.assertFalse(other.plan_declared)
        self.assertIsNone(other.session_name)
        self.assertTrue(
            golem_blender_bridge.handoff_path(self._log_directory, self._CLIENT_PID).exists()
        )

    def test_expired_handoff_is_discarded_loudly(self) -> None:
        self._declared_session_handed_off()
        stderr = io.StringIO()
        with mock.patch.object(
            golem_blender_bridge, "sys", types.SimpleNamespace(stderr=stderr)
        ):
            later_s = time.time() + golem_blender_bridge.HANDOFF_MAX_AGE_S * 2
            after = self._resume(self._CLIENT_PID, now_s=later_s)
        self.assertFalse(after.plan_declared)
        self.assertIn("discarded a handoff", stderr.getvalue())
        self.assertFalse(
            golem_blender_bridge.handoff_path(self._log_directory, self._CLIENT_PID).exists()
        )

    def test_malformed_handoff_is_refused_loudly(self) -> None:
        path = golem_blender_bridge.handoff_path(self._log_directory, self._CLIENT_PID)
        self._log_directory.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "plan_declared": "yes",
                    "session_name": None,
                    "written_at_s": time.time(),
                }
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with mock.patch.object(
            golem_blender_bridge, "sys", types.SimpleNamespace(stderr=stderr)
        ):
            after = self._resume(self._CLIENT_PID)
        self.assertFalse(after.plan_declared)
        self.assertIn("refused a malformed handoff", stderr.getvalue())
        self.assertFalse(path.exists())

    def test_a_failed_handoff_write_still_exits(self) -> None:
        server = golem_blender_bridge.GolemBlenderFastMCP("handoff-probe", instructions="probe")
        server._golem_blender = types.SimpleNamespace(
            write_handoff=mock.Mock(side_effect=OSError("disk full"))
        )
        stderr = io.StringIO()
        exits: list[int] = []
        with (
            mock.patch.object(
                golem_blender_bridge, "sys", types.SimpleNamespace(stderr=stderr)
            ),
            mock.patch.object(
                golem_blender_bridge, "os", types.SimpleNamespace(_exit=exits.append)
            ),
        ):
            server._exit_if_idle(golem_blender_bridge.SOURCE_CHANGED_EXIT_CODE)
        self.assertEqual(exits, [golem_blender_bridge.SOURCE_CHANGED_EXIT_CODE])
        self.assertIn("disk full", stderr.getvalue())


class TestToolcodeReimport(unittest.TestCase):
    """
    The Blender side of freshness, run the way the add-on runs it (a fresh
    exec namespace per call, in an interpreter that writes and reads
    bytecode as Blender's does) against fake ``golem_blender`` checkouts: an
    unchanged fingerprint keeps the imported modules, a changed one
    re-imports them even past a same-size rewrite in the same second, and
    another checkout's copy is refused without being purged.
    """

    # pylint: disable=protected-access

    _DRIVER = textwrap.dedent("""\
        import json
        import os
        import sys

        out = []
        with open(sys.argv[1], encoding="utf-8") as fh:
            steps = json.load(fh)
        for step in steps:
            for path, text in step["write"].items():
                # Keep the old mtime: the worst case, a same-size rewrite
                # in the second the cached bytecode was compiled.
                modified_ns = os.stat(path).st_mtime_ns
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                os.utime(path, ns=(modified_ns, modified_ns))
            namespace = {"result": {}}
            try:
                exec(step["code"], namespace)
                out.append({"outcome": namespace["result"]["outcome"]["text"]})
            except Exception as error:
                out.append({"error": "{:s}: {:s}".format(type(error).__name__, str(error))})
        print(json.dumps(out))
    """)

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self._root = Path(self._directory.name).resolve()
        self._site_packages = self._root / "site-packages"
        self._site_packages.mkdir()

    @staticmethod
    def _tools_text(value: str) -> str:
        return "VALUE = {!r}\n\n\ndef dispatch_tool(name, arguments, output_directory):\n    return VALUE\n".format(
            value
        )

    def _checkout(self, name: str, value: str) -> Path:
        src = self._root / name / "src"
        agent = src / "golem_blender" / "agent"
        agent.mkdir(parents=True)
        (src / "golem_blender" / "__init__.py").write_text("", encoding="utf-8")
        (agent / "__init__.py").write_text("", encoding="utf-8")
        (agent / "outcome.py").write_text(
            "def outcome_to_json(outcome):\n    return {'text': outcome}\n",
            encoding="utf-8",
        )
        (agent / "tools.py").write_text(self._tools_text(value), encoding="utf-8")
        # The probe tool reads only, so the toolcode never frames for it.
        (agent / "plan.py").write_text(
            "def plan_required_for(tool_name):\n    return False\n",
            encoding="utf-8",
        )
        (src / "golem_blender" / "viewport_follow.py").write_text(
            "def snapshot_scene():\n    raise AssertionError('snapshotted for a read-only probe')\n\n\n"
            "def follow_viewport(outcome, *, before=None):\n    raise AssertionError('framed a read-only probe')\n",
            encoding="utf-8",
        )
        # The toolcode wraps every dispatch in the call's context, so the fake
        # checkout carries the same module: a minimal stand-in that does nothing
        # a probe could observe.
        run_package = src / "golem_blender" / "run"
        run_package.mkdir()
        (run_package / "__init__.py").write_text("", encoding="utf-8")
        (run_package / "call_context.py").write_text(
            "from contextlib import contextmanager\n\n\n"
            "@contextmanager\n"
            "def call_context(output_directory, tool_name):\n"
            "    yield None\n",
            encoding="utf-8",
        )
        return src

    def _step(
        self,
        src: Path,
        fingerprint: str,
        write: dict[str, str] | None = None,
        plugin: tuple[Path, str] | None = None,
    ) -> dict[str, object]:
        plugin_root, plugin_package = plugin or (None, None)
        params = golem_blender_bridge_toolcode.Params(
            "probe",
            "{}",
            str(self._root),
            str(src),
            str(self._site_packages),
            fingerprint,
            (str(plugin_root),) if plugin_root else (),
            (plugin_package,) if plugin_package else (),
        )
        return {
            "code": toolcode_format_call(golem_blender_bridge._TOOL_CALL, params),
            "write": write or {},
        }

    def _run(self, steps: list[dict[str, object]]) -> list[dict[str, str]]:
        plan = self._root / "plan.json"
        plan.write_text(json.dumps(steps), encoding="utf-8")
        driver = self._root / "driver.py"
        driver.write_text(self._DRIVER, encoding="utf-8")
        # -I also ignores PYTHONDONTWRITEBYTECODE, so bytecode is written.
        completed = subprocess.run(
            [sys.executable, "-I", "-S", str(driver), str(plan)],
            capture_output=True,
            text=True,
            check=True,
            timeout=_TOOLCODE_DRIVER_TIMEOUT_S,
        )
        results: list[dict[str, str]] = json.loads(completed.stdout)
        return results

    def test_only_a_changed_fingerprint_reimports(self) -> None:
        src = self._checkout("a", "one")
        tools = src / "golem_blender" / "agent" / "tools.py"
        self.assertEqual(len(self._tools_text("one")), len(self._tools_text("two")))
        results = self._run(
            [
                self._step(src, "fingerprint-1"),
                self._step(
                    src, "fingerprint-1", write={str(tools): self._tools_text("two")}
                ),
                self._step(src, "fingerprint-2"),
            ]
        )
        self.assertEqual(
            results, [{"outcome": "one"}, {"outcome": "one"}, {"outcome": "two"}]
        )
        # The probe is live only if the first import cached bytecode.
        self.assertTrue(any((tools.parent / "__pycache__").glob("tools.*.pyc")))

    def test_a_changed_fingerprint_reimports_a_plugin_package_too(self) -> None:
        """A plugin lives outside the checkout: only its root and package name
        reach the toolcode, which must put the root on sys.path and purge it."""
        src = self._checkout("a", "unused")
        tools = src / "golem_blender" / "agent" / "tools.py"
        tools.write_text(
            "import fake_plugin_package\n\n\n"
            "def dispatch_tool(name, arguments, output_directory):\n"
            "    return fake_plugin_package.VALUE\n",
            encoding="utf-8",
        )
        plugin_root = self._root / "plugin"
        module = plugin_root / "fake_plugin_package" / "__init__.py"
        module.parent.mkdir(parents=True)
        module.write_text("VALUE = 'one'\n", encoding="utf-8")
        plugin = (plugin_root, "fake_plugin_package")
        results = self._run(
            [
                self._step(src, "fingerprint-1", plugin=plugin),
                self._step(
                    src,
                    "fingerprint-1",
                    write={str(module): "VALUE = 'two'\n"},
                    plugin=plugin,
                ),
                self._step(src, "fingerprint-2", plugin=plugin),
            ]
        )
        self.assertEqual(
            results, [{"outcome": "one"}, {"outcome": "one"}, {"outcome": "two"}]
        )

    def test_another_checkouts_copy_is_refused_and_left_loaded(self) -> None:
        a_src = self._checkout("a", "from-a")
        b_src = self._checkout("b", "from-b")
        results = self._run(
            [
                self._step(a_src, "fingerprint-a"),
                self._step(b_src, "fingerprint-b"),
                self._step(a_src, "fingerprint-a"),
            ]
        )
        self.assertEqual(results[0], {"outcome": "from-a"})
        self.assertIn("another copy is loaded", results[1]["error"])
        self.assertEqual(results[2], {"outcome": "from-a"})


class _FakeRemote:
    """Stands in for GolemRemote: no network, records what reaches it."""

    def __init__(self, tools: list[mcp_types.Tool]) -> None:
        self._tools = tools
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self) -> list[mcp_types.Tool]:
        return self._tools

    async def instructions(self) -> str | None:
        return "remote instructions"

    async def call_tool(
        self, name: str, arguments: dict[str, object]
    ) -> mcp_types.CallToolResult:
        self.calls.append((name, arguments))
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="from big")]
        )


def _remote_tool(name: str, description: str = "remote") -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name, description=description, inputSchema={"type": "object"}
    )


class TestGolemRemote(unittest.TestCase):
    """
    The golem server on big, served through this one: its tools are listed
    beside the Blender tools and called without the Blender gates.
    """

    # pylint: disable=protected-access

    def _server(self, remote: object) -> golem_blender_bridge.GolemBlenderFastMCP:
        return golem_blender_bridge.GolemBlenderFastMCP("golem", instructions="x", remote=remote)

    def test_the_tool_list_has_the_blender_tools_and_the_remote_ones(self) -> None:
        remote = _FakeRemote([_remote_tool("generate_3d")])

        names = [tool.name for tool in asyncio.run(self._server(remote).list_tools())]

        self.assertIn("add_box", names)
        self.assertIn("declare_plan", names)
        self.assertIn("generate_3d", names)
        self.assertEqual(len(names), len(set(names)))

    def test_a_remote_tool_named_like_a_local_one_is_not_served(self) -> None:
        remote = _FakeRemote(
            [_remote_tool("declare_plan", "the imposter"), _remote_tool("generate_3d")]
        )
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            tools = asyncio.run(self._server(remote).list_tools())

        (plan_tool,) = [tool for tool in tools if tool.name == "declare_plan"]
        self.assertIn(plan_tool, golem_blender_bridge.GOLEM_BLENDER_TOOLS)
        self.assertNotEqual(plan_tool.description, "the imposter")
        self.assertIn(
            "golem remote tool declare_plan shadows a local tool; not served",
            stderr.getvalue(),
        )

    def test_a_remote_call_needs_neither_a_plan_nor_a_live_blender(self) -> None:
        def no_blender() -> None:
            raise ConnectionRefusedError("no Blender is listening")

        patcher = mock.patch.object(golem_blender_bridge, "require_live_blender", no_blender)
        patcher.start()
        self.addCleanup(patcher.stop)
        remote = _FakeRemote([_remote_tool("generate_3d")])
        server = self._server(remote)
        arguments = {"image_path": "/tmp/reference.png", "seed": 7}

        async def run() -> object:
            await server.list_tools()
            return await server.call_tool("generate_3d", arguments)

        result = asyncio.run(run())

        self.assertEqual(remote.calls, [("generate_3d", arguments)])
        self.assertEqual(result.content[0].text, "from big")
        self.assertEqual(server._in_flight, 0)

    def test_the_remote_instructions_follow_the_head(self) -> None:
        text = golem_blender_bridge.golem_blender_instructions("upstream text", "remote text")

        head_end = len(golem_blender_bridge.MCP_INSTRUCTIONS_HEAD)
        self.assertTrue(text.startswith(golem_blender_bridge.MCP_INSTRUCTIONS_HEAD))
        self.assertEqual(
            text[head_end : head_end + len("\n\nremote text")], "\n\nremote text"
        )
        self.assertEqual(
            golem_blender_bridge.golem_blender_instructions("upstream text"),
            golem_blender_bridge.golem_blender_instructions("upstream text", None),
        )

    def test_an_unreachable_big_lists_nothing_and_fails_calls_readably(self) -> None:
        # Port 9 (discard): nothing listens, the connection is refused at once.
        url = "http://127.0.0.1:9/mcp"
        remote = GolemRemote(url)
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            tools = asyncio.run(remote.list_tools())
        result = asyncio.run(remote.call_tool("health_check", {}))

        self.assertEqual(tools, [])
        self.assertIn("golem remote unreachable at " + url, stderr.getvalue())
        self.assertTrue(result.isError)
        self.assertTrue(
            result.content[0].text.startswith("golem on big is unreachable at " + url)
        )


class TestSuitesPresent(unittest.TestCase):
    """A splice to the end of this file once deleted two suites unnoticed."""

    _SUITES = (
        "TestGolemBlenderBridge",
        "TestSourceFingerprint",
        "TestInstructionsHead",
        "TestWatcherIsOptIn",
        "TestSourceWatcher",
        "TestHandoff",
        "TestToolcodeReimport",
        "TestGolemRemote",
        "TestSuitesPresent",
    )

    def test_every_suite_is_still_defined(self) -> None:
        defined = {
            name
            for name, value in globals().items()
            if isinstance(value, type) and issubclass(value, unittest.TestCase)
        }
        self.assertEqual(sorted(set(self._SUITES) - defined), [])


if __name__ == "__main__":
    unittest.main()
