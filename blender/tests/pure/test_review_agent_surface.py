"""Regression tests for the agent-surface review (claude_code, tools).

Each test fails on the pre-fix code:

* a child that floods stderr deadlocked the transport until the watchdog;
* a malformed stdout frame left the CLI running, un-waited;
* streamed thinking deltas were re-appended by the complete assistant
  frame, doubling the thinking text;
* a call the op binder rejected was recorded with `{}` arguments.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from blended.agent.claude_code import ClaudeCodeTransport
from blended.agent.tools import dispatch_tool

WRITER_MODEL = "claude-code:sonnet"
# Larger than any OS pipe buffer (64 KiB on Linux, 16-64 KiB on macOS).
STDERR_FLOOD_BYTES = 512 * 1024
FLOOD_TIMEOUT_SECONDS = 10
SLEEP_FOREVER_SECONDS = 120
REAP_WAIT_SECONDS = 5.0
POLL_SECONDS = 0.05

FAKE_SOURCE = '''#!/usr/bin/env python3
"""A stand-in for `claude` whose behaviour a test picks by env var."""
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
sys.stdin.read()
mode = os.environ["FAKE_CLAUDE_MODE"]
if mode == "stderr_flood":
    sys.stderr.write("e" * int(os.environ["FAKE_CLAUDE_STDERR_BYTES"]))
    sys.stderr.flush()
if mode == "malformed_frame":
    open(os.path.join(here, "pid.txt"), "w").write(str(os.getpid()))
    sys.stdout.write("{this is not json\\n")
    sys.stdout.flush()
    time.sleep(int(os.environ["FAKE_CLAUDE_SLEEP_SECONDS"]))
for line in open(os.path.join(here, "frames.jsonl")):
    sys.stdout.write(line)
    sys.stdout.flush()
'''


def _result_frame(text: str = "a red cube") -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "structured_output": None,
    }


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_text(FAKE_SOURCE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "frames")
    monkeypatch.setenv("FAKE_CLAUDE_STDERR_BYTES", str(STDERR_FLOOD_BYTES))
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP_SECONDS", str(SLEEP_FOREVER_SECONDS))
    write_frames(binary, [_result_frame()])
    return binary


def write_frames(binary: Path, frames: list[dict]) -> None:
    (binary.parent / "frames.jsonl").write_text(
        "".join(json.dumps(frame) + "\n" for frame in frames)
    )


def _process_is_gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_a_stderr_flood_does_not_stall_the_turn(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "stderr_flood")
    transport = ClaudeCodeTransport(
        WRITER_MODEL,
        binary_path=str(fake_claude),
        timeout_seconds=FLOOD_TIMEOUT_SECONDS,
    )
    started = time.monotonic()
    message = transport.chat([{"role": "user", "content": "go"}])
    assert message["content"] == "a red cube"
    # A deadlock would have run to the watchdog and raised instead.
    assert time.monotonic() - started < FLOOD_TIMEOUT_SECONDS


def test_a_malformed_frame_does_not_leave_the_cli_running(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "malformed_frame")
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_claude))
    with pytest.raises(json.JSONDecodeError):
        transport.chat([{"role": "user", "content": "go"}])
    pid = int((fake_claude.parent / "pid.txt").read_text())
    deadline = time.monotonic() + REAP_WAIT_SECONDS
    while not _process_is_gone(pid) and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    assert _process_is_gone(pid), (
        "the CLI outlived the failed turn (killed and reaped expected)"
    )


def test_streamed_thinking_is_not_repeated_by_the_complete_frame(fake_claude):
    write_frames(
        fake_claude,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "weigh"},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "ing it"},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "thinking", "thinking": "weighing it"}]
                },
            },
            _result_frame(),
        ],
    )
    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(fake_claude))
    message = transport.chat([{"role": "user", "content": "go"}])
    assert message["thinking"] == "weighing it"


def test_a_rejected_op_call_is_recorded_with_what_the_model_sent():
    outcome = dispatch_tool("add_box", {"name": "A", "bogus": 1, "plan_step": 1})
    assert not outcome.ok
    assert outcome.validated_arguments == {"name": "A", "bogus": 1}
