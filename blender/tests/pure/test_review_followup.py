"""Regression tests for the 2026-10-07 review follow-up (ISSUES.md S1-S3, P*, D*).

Every test here failed on the code it guards before the fix, with the failure
recorded in the matching MistakeRecord (``blended.evaluate.mistake_memory``).
"""

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MCP_DIRECTORY = REPOSITORY_ROOT / "blender_mcp" / "mcp"
if str(MCP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(MCP_DIRECTORY))

pytest.importorskip("mcp")

import blmcp
from mcp.server.transport_security import TransportSecurityMiddleware

HTTP_PORT = 8000
EVIL_HOST_HEADER = f"evil.example:{HTTP_PORT}"
EVIL_ORIGIN = "http://evil.example"
LOOPBACK_HOST_HEADER = f"127.0.0.1:{HTTP_PORT}"
LOOPBACK_IPV6_HOST_HEADER = f"[::1]:{HTTP_PORT}"
LOCALHOST_ORIGIN = "http://localhost:8080"


# --- 1.3: the HTTP transport is loopback-only, with DNS-rebinding protection ---


def test_the_http_transport_refuses_a_non_loopback_host():
    """`--host 0.0.0.0` served the tools (which run Python in Blender) to the LAN."""
    with pytest.raises(ValueError, match="not loopback"):
        blmcp._require_loopback_host("0.0.0.0", HTTP_PORT)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_the_http_transport_accepts_loopback_hosts(host):
    blmcp._require_loopback_host(host, HTTP_PORT)


def test_the_transport_security_settings_reject_a_rebound_host_and_origin():
    """A DNS-rebinding page reaches 127.0.0.1 with `Host: evil.example` and an
    `Origin` of the attacker's page; protection was switched off, so both passed."""
    middleware = TransportSecurityMiddleware(blmcp.loopback_transport_security())
    assert middleware.settings.enable_dns_rebinding_protection
    assert not middleware._validate_host(EVIL_HOST_HEADER)
    assert middleware._validate_host(LOOPBACK_HOST_HEADER)
    assert middleware._validate_host(LOOPBACK_IPV6_HOST_HEADER)
    assert not middleware._validate_origin(EVIL_ORIGIN)
    assert middleware._validate_origin(LOCALHOST_ORIGIN)


# --- 4.2: a raised chunk is reproduced byte for byte ---


def test_a_raised_chunk_keeps_its_multiline_string_literals():
    """`indent()` put four spaces into the continuation lines of a triple-quoted
    string, so the replay built a different value than the run did (`NOTE` was
    'a\\n    b' instead of 'a\\nb')."""
    from blended.evaluate.bench_bridge import RecordedCall, standalone_script

    call = RecordedCall(
        "run_python",
        {"source": "NOTE = '''a\nb'''\nraise RuntimeError('x')"},
        "execute",
        changed_scene=True,
    )

    script = standalone_script([call], "", "")
    namespace: dict = {}
    exec(script.text, namespace)  # noqa: S102 - replaying the generated bake script

    assert namespace["NOTE"] == "a\nb"


# --- 4.5: the Claude Code lane's watchdog and `auth status` edge cases ---

WRITER_MODEL = "claude-code:sonnet"
WATCHDOG_TIMEOUT_SECONDS = 1
STUB_SLEEP_SECONDS = 30

STUB_CLAUDE_SOURCE = '''#!/usr/bin/env python3
"""A stand-in for `claude`: `auth status` prints a chosen payload; a turn
writes a frame that never ends in a newline, then sleeps."""
import os, sys, time

if sys.argv[1:3] == ["auth", "status"]:
    sys.stdout.write(os.environ["STUB_AUTH_STATUS_OUTPUT"])
    sys.exit(0)
sys.stdin.read()
sys.stdout.write('{"type":')
sys.stdout.flush()
time.sleep(int(os.environ["STUB_SLEEP_SECONDS"]))
'''


@pytest.fixture
def stub_claude(tmp_path, monkeypatch):
    import stat

    binary = tmp_path / "claude"
    binary.write_text(STUB_CLAUDE_SOURCE)
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("STUB_SLEEP_SECONDS", str(STUB_SLEEP_SECONDS))
    monkeypatch.setenv("STUB_AUTH_STATUS_OUTPUT", "[]")
    return binary


def test_a_watchdog_kill_mid_frame_reports_the_timeout_not_a_json_error(stub_claude):
    """The watchdog kills the CLI mid-line; stdout then ends on `{"type":`, and
    `json.loads` of that fragment surfaced as JSONDecodeError instead of the
    'did not answer within' the caller handles."""
    from blended.agent.claude_code import ClaudeCodeTransport

    transport = ClaudeCodeTransport(
        WRITER_MODEL,
        binary_path=str(stub_claude),
        timeout_seconds=WATCHDOG_TIMEOUT_SECONDS,
    )

    with pytest.raises(RuntimeError, match="did not answer within"):
        transport.chat([{"role": "user", "content": "go"}])


def test_an_auth_status_that_is_not_a_json_object_is_a_failed_check(stub_claude):
    """`auth status` printing `[]` made `status.get` raise AttributeError, and
    only the json.loads line sat inside the try."""
    from blended.agent.claude_code import ClaudeCodeTransport

    transport = ClaudeCodeTransport(WRITER_MODEL, binary_path=str(stub_claude))

    ok, detail = transport.check_connection()

    assert ok is False
    assert "not a JSON object" in detail


# --- 4.6: a duplicated skill-module name is reported ---


def test_a_duplicate_skill_module_name_is_a_registry_problem(monkeypatch):
    """`registered` was a set, so a name listed twice collapsed to one and
    `validate_modules()` returned [] while `get_module` silently served the first."""
    from blended.agent import skill_modules

    first = skill_modules.SKILL_MODULES[0]
    monkeypatch.setattr(
        skill_modules, "SKILL_MODULES", skill_modules.SKILL_MODULES + (first,)
    )

    problems = skill_modules.validate_modules()

    assert any(
        first.name in problem and "2 times" in problem for problem in problems
    ), problems


# --- 8.4: a formatter must not emit syntax the project's Pythons cannot parse ---

SOURCE_ROOTS = ("src", "tests", "scripts", "blender_mcp", "examples")


def test_every_python_file_parses_under_the_minimum_python():
    """`ruff format` with the add-on's `target-version = "py314"` rewrote
    `except (A, B):` as `except A, B:` (PEP 758), which Blender 5.2.0's Python
    3.13.13 rejects: `make test-blender-app` died at import while `ruff check`,
    mypy and `make test-pure` stayed green. The dev venv's Python is the
    project's minimum (3.11), so parsing every file with it rejects anything newer."""
    import ast

    failures = []
    for root in SOURCE_ROOTS:
        for path in sorted((REPOSITORY_ROOT / root).rglob("*.py")):
            if ".venv" in path.parts:
                continue
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as error:
                failures.append(
                    f"{path.relative_to(REPOSITORY_ROOT)}:{error.lineno}: {error.msg}"
                )

    assert not failures, failures
