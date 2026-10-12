"""Claude Code in headless mode, as a harness transport.

A third transport shape beside the two HTTP protocols in `loop.py`: this
lane's "server" is a local subprocess that owns its own authentication
and its own rate limits. `claude auth status` on this machine reports
`authMethod: claude.ai`, `apiProvider: firstParty` — this module execs
the binary Anthropic ships and never reads, stores or forwards a token,
which is what separates it from the third-party subscription-OAuth
pattern Anthropic prohibited for other harnesses.

Everything below rests on flags and frame shapes measured against the
live CLI (2.1.260) on 2026-09-05; `docs/2026-09-05-claude-code-lane-plan.md`
records the probes. The three that shape the design:

* `--input-format stream-json` requires `--output-format stream-json`,
  which requires `--verbose`. All three or none — and stream-json input
  is the only way to hand the model an image.
* EACH `{"type":"user"}` frame is one billed turn: two user frames in one
  invocation produced two `system init` frames and two `result` frames.
  So a stateless `chat(messages)` call folds the whole conversation into
  exactly ONE trailing user frame. `{"type":"assistant"}` frames are
  accepted as history, but they cannot help here: every interior
  user/tool block would still need a user frame of its own, and moving
  them all after the assistant turns would put tool results before the
  calls that produced them.
* `--json-schema` validates structured output, `oneOf` included, and
  hands back the parsed object as `structured_output`. Tool calls are
  therefore CONSTRAINED, not parsed out of prose — grammar-constrained
  decoding guarantees the output conforms to the schema instead of
  hoping a model formats correctly (Geng et al., Grammar-Constrained
  Decoding for Structured NLP Tasks without Finetuning, DOI
  10.18653/v1/2023.emnlp-main.674). A chat-only turn still answers
  through the schema, with `tool_calls: []`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# Model ids on this lane are `claude-code:<alias>`: the prefix picks the
# transport, the suffix goes to `--model` verbatim. The CLI takes either
# an alias ("opus", "sonnet", "haiku") or a full name
# ("claude-sonnet-5"), so `claude-code:claude-sonnet-5` works too.
CLAUDE_CODE_MODEL_PREFIX = "claude-code:"
CLAUDE_CODE_MODEL_IDS = (
    "claude-code:opus",
    "claude-code:sonnet",
    "claude-code:haiku",
)
# Not a URL. This lane has no server, but every diagnostic in the
# harness is keyed by endpoint, so the transport names itself here.
CLAUDE_CODE_ENDPOINT = "claude-code://cli"
CLAUDE_CODE_BINARY_NAME = "claude"
# Blender launched from Finder inherits no shell PATH — the same trap
# that makes OLLAMA_API_KEY invisible to a GUI Blender. `which` alone
# would leave the lane dead in exactly the environment the addon runs
# in, so the known install directories are searched too.
CLAUDE_CODE_INSTALL_DIRECTORIES = (
    Path.home() / ".local" / "bin",
    Path.home() / ".claude" / "local",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)
CLAUDE_CODE_INSTALL_HINT = (
    "Install it with `curl -fsSL https://claude.ai/install.sh | bash` and "
    "sign in with `claude auth login`, or set the binary path in the addon "
    "preferences."
)
# A ceiling, not a wait. Same reasoning as the llama-swap lanes: a
# high-effort turn over a long transcript takes minutes, and the cloud
# lanes' 300 s killed a healthy local generation mid-flight.
CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS = 900
# `claude auth status` is a local read: no request, no tokens spent, so
# the preflight can check the account before it checks the model.
AUTH_STATUS_TIMEOUT_SECONDS = 30
# How long chat() waits on its stdin-writer and stderr-drain threads once
# the child has exited; they end at the pipe's EOF, so this is a ceiling.
PIPE_THREAD_JOIN_SECONDS = 1
# `--effort` is passed explicitly rather than inherited from the user's
# settings.json, so a harness run does not change behaviour when the
# user changes their editor preference. medium: the writer reasons about
# geometry, but xhigh spends thinking tokens the analyzer gate already
# earns back.
CLAUDE_CODE_DEFAULT_EFFORT = "medium"
CLAUDE_CODE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# cwd is irrelevant to behaviour under `--safe-mode` and
# `--no-session-persistence` (no CLAUDE.md discovery, no settings, no
# session files), and Blender's cwd is arbitrary — so pin it somewhere
# that exists from any launch context and holds nothing of ours.
CLAUDE_CODE_WORKING_DIRECTORY = Path(tempfile.gettempdir())

# The transcript labels. The folded conversation has to stay legible to
# the model, so roles are marked, not merged.
USER_LABEL = "[user]"
ASSISTANT_LABEL = "[assistant]"
TOOL_CALL_LABEL_FORMAT = "[assistant tool call: {name}]"
TOOL_RESULT_LABEL_FORMAT = "[tool result: {name}]"
# A folded transcript often ends in a tool result, mid tool loop, with
# no trailing user message at all (`AgentSession.send` calls back into
# `chat` right after appending results). Without a cue the model has no
# marker for where its own turn starts.
CONTINUATION_CUE = (
    "[your turn]\n"
    "Continue as the assistant: either request more tool calls or give "
    "your final answer to the user."
)
# Appended to the system prompt whenever tools are in play. NOT prompt
# engineering: it is the transport telling the model how tool calls
# travel on THIS wire, the same job `_to_openai_tools` does by putting
# them in the request. The harness's own system prompt describes the
# tools as directly callable, because every other lane hands them
# to the model natively — and Claude Code is itself an agent harness,
# so a model reading that prompt reaches for a native tool call.
# Measured 2026-09-05 without this note: claude-code:sonnet answered
# "Every tool call I make (run_python, list_scene, search_ops) is being
# rejected with 'No such tool available'" and made ZERO calls, failing
# the `object` E2E scenario outright.
TOOL_PROTOCOL_NOTE = (
    "TOOL PROTOCOL ON THIS CONNECTION\n"
    "You have no tools of your own here. A direct tool call is rejected "
    'with "No such tool available" — the tools described above are run '
    "by the harness, not by you.\n"
    "To use one, answer with the structured object you were given a "
    "schema for: put anything you want to say to the user in `message`, "
    "and the calls you want executed in `tool_calls`, each one "
    '`{"name": <tool>, "arguments": {...}}`. The harness runs them '
    "and hands you the results in the next turn's transcript.\n"
    "Leave `tool_calls` empty only when you are finished and answering."
)
# What `loop._image_placeholders` writes into message text for the
# Ollama lanes. Claude delivers multiple images unfused and in order
# (measured: 1315 prompt tokens with no image, 1685 with one, 2068 with
# two), so no placeholder workaround is needed here — but the token is
# already in the text, and substituting the real image at its position
# is what keeps "Image 1" pointing at image 1.
IMAGE_PLACEHOLDER_TOKEN = "[img]"
IMAGE_MEDIA_TYPE = "image/png"

ENVELOPE_MESSAGE_KEY = "message"
ENVELOPE_TOOL_CALLS_KEY = "tool_calls"
TOOL_CALL_ID_PREFIX = "claude_code_"

# Frame and event names on the wire.
_FRAME_ASSISTANT = "assistant"
_FRAME_RESULT = "result"
_FRAME_RATE_LIMIT = "rate_limit_event"
_FRAME_STREAM_EVENT = "stream_event"
_EVENT_CONTENT_BLOCK_DELTA = "content_block_delta"
# Opens every Anthropic call, so counting these counts the calls one
# harness turn really makes.
_EVENT_MESSAGE_START = "message_start"
_DELTA_THINKING = "thinking_delta"
_BLOCK_TEXT = "text"
_BLOCK_THINKING = "thinking"
_RESULT_SUCCESS = "success"
_RATE_LIMIT_ALLOWED = "allowed"
_FIVE_HOUR_WINDOW = "five_hour"
_SEVEN_DAY_WINDOW = "seven_day"


def resolve_binary(configured_path: str = "") -> Path:
    """The `claude` executable, or a loud failure naming the fix."""
    if configured_path:
        candidate = Path(configured_path).expanduser()
        if candidate.is_file():
            return candidate
        raise RuntimeError(
            f"No Claude Code binary at the configured path {candidate}. "
            f"{CLAUDE_CODE_INSTALL_HINT}"
        )
    found = shutil.which(CLAUDE_CODE_BINARY_NAME)
    if found:
        return Path(found)
    for directory in CLAUDE_CODE_INSTALL_DIRECTORIES:
        candidate = directory / CLAUDE_CODE_BINARY_NAME
        if candidate.is_file():
            return candidate
    searched = ", ".join(
        str(directory) for directory in CLAUDE_CODE_INSTALL_DIRECTORIES
    )
    raise RuntimeError(
        f"Claude Code CLI ({CLAUDE_CODE_BINARY_NAME}) is not on PATH and not "
        f"in {searched}. {CLAUDE_CODE_INSTALL_HINT}"
    )


def model_alias(model: str) -> str:
    """`claude-code:sonnet` -> `sonnet`; a bare alias passes through."""
    if model.startswith(CLAUDE_CODE_MODEL_PREFIX):
        return model[len(CLAUDE_CODE_MODEL_PREFIX) :]
    return model


def is_claude_code_model(model: str) -> bool:
    return model.startswith(CLAUDE_CODE_MODEL_PREFIX)


def _image_block(image_base64: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": IMAGE_MEDIA_TYPE,
            "data": image_base64,
        },
    }


def render_call(messages: list[dict]) -> tuple[str, dict]:
    """Harness messages -> (system prompt text, ONE user frame).

    System messages become `--system-prompt`. Everything else folds, in
    order, into a single labelled transcript whose images sit at their
    own positions as native image blocks. One frame is one billed turn
    (measured); the labels and the trailing cue are what keep the fold
    readable as a conversation rather than a wall of text.
    """
    system_parts: list[str] = []
    text_parts: list[str] = []
    blocks: list[dict] = []

    def flush_text() -> None:
        joined = "\n".join(text_parts).strip()
        text_parts.clear()
        if joined:
            blocks.append({"type": _BLOCK_TEXT, "text": joined})

    def open_message(label: str) -> None:
        if text_parts or blocks:
            text_parts.append("")
        text_parts.append(label)

    def add_content(content: str, images: list[str]) -> None:
        """Text, with images spliced in at their placeholder positions."""
        if not images:
            text_parts.append(content)
            return
        pending = list(images)
        segments = content.split(IMAGE_PLACEHOLDER_TOKEN)
        for index, segment in enumerate(segments):
            text_parts.append(segment)
            if index < len(segments) - 1 and pending:
                flush_text()
                blocks.append(_image_block(pending.pop(0)))
        for leftover in pending:
            flush_text()
            blocks.append(_image_block(leftover))

    for message in messages:
        role = message.get("role", "user")
        content = message.get("content") or ""
        images = list(message.get("images") or [])
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role == "assistant":
            open_message(ASSISTANT_LABEL)
            if content:
                text_parts.append(content)
            for tool_call in message.get("tool_calls") or []:
                function_block = tool_call.get("function") or {}
                arguments = function_block.get("arguments", {})
                text_parts.append(
                    TOOL_CALL_LABEL_FORMAT.format(name=function_block.get("name", ""))
                )
                text_parts.append(
                    arguments if isinstance(arguments, str) else json.dumps(arguments)
                )
            continue
        if role == "tool":
            open_message(
                TOOL_RESULT_LABEL_FORMAT.format(name=message.get("tool_name", ""))
            )
            add_content(content, images)
            continue
        open_message(USER_LABEL)
        add_content(content, images)

    open_message(CONTINUATION_CUE)
    flush_text()
    return (
        "\n\n".join(system_parts),
        {"type": "user", "message": {"role": "user", "content": blocks}},
    )


def envelope_schema(tools: list[dict]) -> dict:
    """The structured-output contract, built FROM the harness's tools.

    One `oneOf` variant per tool, each pinning `name` with `const` and
    reusing that tool's own `parameters` schema for `arguments` — so a
    new harness tool needs no change in this lane, and a call that names
    a tool cannot carry another tool's arguments.

    The variant carries the tool's DESCRIPTION too. That is not
    decoration: the other lanes hand descriptions to the model through
    the API's own `tools` field, and this lane has no such field, so
    dropping them leaves the model naming tools it knows nothing about.
    Measured 2026-09-05 — with names and argument schemas only, the
    writer answered "I'm unable to create the Crate cube right now" and
    called nothing; with descriptions in the schema it called
    `run_python` on the first turn.
    """
    variants = []
    for tool in tools:
        function_block = tool["function"]
        variants.append(
            {
                "type": "object",
                "description": function_block.get("description", ""),
                "additionalProperties": False,
                "properties": {
                    "name": {"const": function_block["name"]},
                    "arguments": function_block.get("parameters", {}),
                },
                "required": ["name", "arguments"],
            }
        )
    # OT-25: the disclosed set is a subset of the facade. An op the model
    # found through search_ops is called by name; its arguments are
    # validated at the door and the binder, not here.
    from blended.agent.tools import OP_FUNCTIONS

    offered_names = {tool["function"]["name"] for tool in tools}
    undisclosed = sorted(name for name in OP_FUNCTIONS if name not in offered_names)
    if undisclosed:
        variants.append(
            {
                "type": "object",
                "description": (
                    "An op found through search_ops: name it and pass the "
                    "arguments its schema showed. Bound and gated like any op."
                ),
                "additionalProperties": False,
                "properties": {
                    "name": {"enum": undisclosed},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            }
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            ENVELOPE_MESSAGE_KEY: {
                "type": "string",
                "description": (
                    "What you say to the user this turn. Empty string when "
                    "you are only calling tools."
                ),
            },
            ENVELOPE_TOOL_CALLS_KEY: {
                "type": "array",
                "description": (
                    "The tools to run now, in order. Empty array when you "
                    "are answering instead of acting."
                ),
                "items": {"oneOf": variants},
            },
        },
        "required": [ENVELOPE_MESSAGE_KEY, ENVELOPE_TOOL_CALLS_KEY],
    }


def assistant_message_from_envelope(envelope: dict, thinking: str = "") -> dict:
    """Structured output -> the assistant dict the agent loop consumes.

    Ids are minted here because this lane has no server-side call ids,
    and the loop matches results to calls by id — a per-turn counter
    would collide across turns and silently drop a tool's result.
    """
    tool_calls = []
    for call in envelope.get(ENVELOPE_TOOL_CALLS_KEY) or []:
        tool_calls.append(
            {
                "id": f"{TOOL_CALL_ID_PREFIX}{uuid.uuid4().hex[:12]}",
                "function": {
                    "name": call.get("name", ""),
                    "arguments": call.get("arguments") or {},
                },
            }
        )
    message = {
        "role": "assistant",
        "content": envelope.get(ENVELOPE_MESSAGE_KEY) or "",
        "tool_calls": tool_calls,
    }
    if thinking:
        message["thinking"] = thinking
    return message


@dataclass(frozen=True)
class RateLimitSnapshot:
    """The `rate_limit_event` frame that precedes every turn.

    Surfacing it is guideline G11, make clear why the system did what it
    did (Amershi et al., DOI 10.1145/3290605.3300233): on this account
    overage is `rejected` (`out_of_credits`), so a window hit is a hard
    stop and the user needs the number BEFORE the lane goes quiet.
    """

    status: str
    five_hour_utilization: float
    seven_day_utilization: float
    resets_at_epoch_seconds: int

    @property
    def allowed(self) -> bool:
        return self.status == _RATE_LIMIT_ALLOWED

    def summary(self) -> str:
        return (
            f"limits {self.five_hour_utilization * 100:.0f}% of the 5h window, "
            f"{self.seven_day_utilization * 100:.0f}% of the 7d window"
            f"{'' if self.allowed else f' (status {self.status})'}"
        )


def parse_rate_limit(frame: dict) -> RateLimitSnapshot:
    info = frame.get("rate_limit_info") or {}
    windows = info.get("unifiedWindows") or {}
    return RateLimitSnapshot(
        status=info.get("status", ""),
        five_hour_utilization=float(
            (windows.get(_FIVE_HOUR_WINDOW) or {}).get("utilization", 0.0)
        ),
        seven_day_utilization=float(
            (windows.get(_SEVEN_DAY_WINDOW) or {}).get("utilization", 0.0)
        ),
        resets_at_epoch_seconds=int(info.get("resetsAt", 0) or 0),
    )


class NoBilledInput(ValueError):
    """No prompt-side tokens at all: nothing to take a fraction of."""


def cache_read_fraction(
    input_tokens: int, cache_read_tokens: int, cache_write_tokens: int
) -> float:
    """cache reads over everything billed on the prompt side (OT-26)."""
    billed = input_tokens + cache_read_tokens + cache_write_tokens
    if billed <= 0:
        raise NoBilledInput(
            "no prompt-side tokens were billed; the fraction is undefined"
        )
    return cache_read_tokens / billed


@dataclass(frozen=True)
class TurnCost:
    """What one invocation actually spent.

    Measured 2026-09-06, and the reason this type exists: the harness
    had no token accounting at all, so nobody could see that ONE
    harness turn bills two to three API calls. A turn assembling 12.5k
    of prompt billed 25,851 input tokens — the CLI runs the model once
    for the turn and again to conform the answer to `--json-schema`.
    Recording it makes that visible, and makes a cache regression
    visible too: byte-identical prefixes read at 0.1x while a broken
    prefix re-writes at 1.25x, an 11.8x swing measured on this lane.

    `api_calls` is counted from `message_start` stream events, one per
    Anthropic call. The token fields come from the result frame's
    `usage`, which sums every call in the invocation.
    """

    api_calls: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    # Of `output_tokens`, the share the model spent thinking before its
    # first content token. A reasoning model can spend a whole
    # completion ceiling here and return nothing — which is how the
    # local arm died (two bench instances, zero turns, cut at 16,384) and
    # how the provider smoke starved at 32. Recorded so the next such
    # failure is read off a number instead of inferred from a corpse.
    reasoning_tokens: int = 0
    # Calls the transport had to send again because the gateway said
    # "not now" (429/5xx). A lane that needs many is unhealthy, and the
    # record should show that rather than only a longer wall clock.
    retried_calls: int = 0
    cost_usd: float = 0.0

    @property
    def billed_input_tokens(self) -> int:
        """Everything the prompt side cost, cached or not."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def cache_read_fraction(self) -> float:
        """The share of the prompt side served from cache (OT-26). A ratio:
        it FALLS when the static prefix shrinks (OT-25 took it from 0.829
        to 0.791 on the planter with fewer tokens per call), so a change
        of order is judged by `cache_write_tokens` per call, not by this.
        Undefined before anything was billed."""
        return cache_read_fraction(
            self.input_tokens, self.cache_read_tokens, self.cache_write_tokens
        )

    def plus(self, other: TurnCost) -> TurnCost:
        """Accumulate across the turns of one run."""
        return TurnCost(
            api_calls=self.api_calls + other.api_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            retried_calls=self.retried_calls + other.retried_calls,
            cost_usd=self.cost_usd + other.cost_usd,
        )

    def summary(self) -> str:
        return (
            f"{self.api_calls} api call(s), "
            f"{self.billed_input_tokens:,} input tok "
            f"({self.cache_read_tokens:,} cached"
            + (f", {self.cache_read_fraction:.0%}" if self.billed_input_tokens else "")
            + "), "
            f"{self.output_tokens:,} out"
            + (
                f" ({self.reasoning_tokens:,} reasoning)"
                if self.reasoning_tokens
                else ""
            )
            + (f", {self.retried_calls} retried" if self.retried_calls else "")
            + f", ${self.cost_usd:.4f}"
        )


def parse_turn_cost(result_frame: dict, api_calls: int) -> TurnCost:
    """The result frame's `usage`, as a record."""
    usage = result_frame.get("usage") or {}
    return TurnCost(
        api_calls=api_calls,
        input_tokens=int(usage.get("input_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cost_usd=float(result_frame.get("total_cost_usd") or 0.0),
    )


class ClaudeCodeTransport:
    """One headless `claude -p` invocation per chat call.

    Stateless on purpose: no `--session-id`, no `--resume`. Claude
    Code's own session store would be a second source of truth beside
    `AgentSession.messages`, which is the record the gates, the recorder
    and the replayer all read.

    The model gets NO tools of its own (`--tools ""`, `--safe-mode`):
    no Bash, no Read, no CLAUDE.md, no hooks, no MCP. The harness's tools
    are the whole interface, exactly as on every other lane, so a
    turn cannot reach the filesystem behind the builder API.
    """

    def __init__(
        self,
        model: str,
        effort: str = CLAUDE_CODE_DEFAULT_EFFORT,
        binary_path: str = "",
        timeout_seconds: int = CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS,
        working_directory: Path = CLAUDE_CODE_WORKING_DIRECTORY,
    ) -> None:
        self.model = model
        if effort and effort not in CLAUDE_CODE_EFFORT_LEVELS:
            raise ValueError(
                f"effort {effort!r} is not one of "
                f"{', '.join(CLAUDE_CODE_EFFORT_LEVELS)}"
            )
        self.effort = effort
        self.binary_path = binary_path
        self.timeout_seconds = timeout_seconds
        self.working_directory = working_directory
        self.last_rate_limit: RateLimitSnapshot | None = None
        self.last_turn_cost: TurnCost | None = None

    def command(self, system_prompt: str, tools: list[dict] | None) -> list[str]:
        """The argv for one turn. Pure, so a test can read the flags."""
        arguments = [
            str(resolve_binary(self.binary_path)),
            "--print",
            # Images ride in stream-json input, and that format demands
            # the other two flags.
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            # Deltas for the panel; also the only source of thinking
            # text when the model thinks.
            "--include-partial-messages",
            # No built-in tools, no skills, no MCP, no customizations,
            # nothing that can prompt, nothing written to disk.
            "--tools",
            "",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--safe-mode",
            "--no-session-persistence",
            "--permission-prompts",
            "none",
            "--model",
            model_alias(self.model),
        ]
        if tools:
            # The note travels WITH the schema: they describe the same
            # wire contract, so neither may ship without the other.
            system_prompt = "\n\n".join(
                part for part in (system_prompt, TOOL_PROTOCOL_NOTE) if part
            )
            arguments += ["--json-schema", json.dumps(envelope_schema(tools))]
        if system_prompt:
            arguments += ["--system-prompt", system_prompt]
        if self.effort:
            arguments += ["--effort", self.effort]
        return arguments

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One turn. Returns the assistant dict the agent loop consumes."""
        system_prompt, frame = render_call(messages)
        arguments = self.command(system_prompt, tools)
        process = subprocess.Popen(
            arguments,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(self.working_directory),
            env=os.environ.copy(),
        )
        # All three were requested as PIPE above; Popen only leaves one
        # None when it was not.
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        # stdin is written from a thread: a transcript carrying renders
        # is megabytes of base64, and writing it inline would deadlock
        # against a child that is already writing its init frames.
        writer = threading.Thread(
            target=_write_frame, args=(process.stdin, frame), daemon=True
        )
        writer.start()
        # stderr is drained as it arrives: read only after stdout hit EOF,
        # a child that fills the 64 KiB pipe buffer blocks on stderr while
        # this side waits on stdout, and only the watchdog ends it.
        stderr_chunks: list[str] = []
        stderr_reader = threading.Thread(
            target=_drain_stream, args=(process.stderr, stderr_chunks), daemon=True
        )
        stderr_reader.start()
        timed_out = threading.Event()

        def kill_on_deadline() -> None:
            timed_out.set()
            process.kill()

        watchdog = threading.Timer(self.timeout_seconds, kill_on_deadline)
        watchdog.start()
        started = time.monotonic()
        assembled: _Assembled | None = None
        try:
            assembled = self._consume(process.stdout, tools)
        except BaseException:
            # A malformed frame (or an interrupt) must not leave the CLI
            # running for the rest of its 900 s ceiling, un-waited.
            process.kill()
            # The watchdog's kill ends stdout mid-line, and that fragment is
            # what failed to parse: report the timeout, not the symptom.
            if not timed_out.is_set():
                raise
        finally:
            watchdog.cancel()
            writer.join(timeout=PIPE_THREAD_JOIN_SECONDS)
            process.stdout.close()
            return_code = process.wait()
            stderr_reader.join(timeout=PIPE_THREAD_JOIN_SECONDS)
        stderr_text = "".join(stderr_chunks).strip()
        if timed_out.is_set():
            raise RuntimeError(
                f"Claude Code did not answer within {self.timeout_seconds} s "
                f"(model {self.model}). {stderr_text[:300]}"
            )
        # Reaching here, an exception was re-raised above unless the watchdog
        # fired, and that case raised "did not answer within".
        assert assembled is not None
        if assembled.result is None:
            raise RuntimeError(
                f"Claude Code exited {return_code} with no result frame "
                f"(model {self.model}, {time.monotonic() - started:.1f} s). "
                f"{stderr_text[:500] or 'No stderr.'}"
            )
        return self._message_from_result(assembled, tools)

    def _consume(self, stdout, tools) -> _Assembled:
        assembled = _Assembled()
        for raw_line in stdout:
            line = raw_line.strip()
            if not line.startswith("{"):
                continue
            frame = json.loads(line)
            kind = frame.get("type")
            if kind == _FRAME_RATE_LIMIT:
                self.last_rate_limit = parse_rate_limit(frame)
            elif kind == _FRAME_STREAM_EVENT:
                _absorb_stream_event(frame.get("event") or {}, assembled)
            elif kind == _FRAME_ASSISTANT:
                _absorb_assistant(frame.get("message") or {}, assembled)
            elif kind == _FRAME_RESULT:
                assembled.result = frame
                self.last_turn_cost = parse_turn_cost(frame, assembled.api_calls)
        return assembled

    def _message_from_result(self, assembled: _Assembled, tools) -> dict:
        result = assembled.result or {}
        subtype = result.get("subtype", "")
        if result.get("is_error") or subtype != _RESULT_SUCCESS:
            limit_note = (
                f" {self.last_rate_limit.summary()}."
                if self.last_rate_limit is not None
                else ""
            )
            raise RuntimeError(
                f"Claude Code returned {subtype or 'no subtype'} for model "
                f"{self.model}: {str(result.get('result'))[:300]}.{limit_note}"
            )
        thinking = "".join(assembled.thinking).strip()
        if tools:
            envelope = result.get("structured_output")
            if not isinstance(envelope, dict):
                raise RuntimeError(
                    f"Claude Code answered without the structured envelope "
                    f"(model {self.model}). A CLI too old for --json-schema "
                    f"would do this; `claude update` fixes it. Got: "
                    f"{str(result.get('result'))[:200]}"
                )
            return assistant_message_from_envelope(envelope, thinking)
        message = {
            "role": "assistant",
            "content": str(result.get("result") or "").strip(),
            "tool_calls": [],
        }
        if thinking:
            message["thinking"] = thinking
        return message

    def check_connection(self, tools: list[dict] | None = None) -> tuple[bool, str]:
        """(ok, detail): binary, then auth, then one real turn.

        Auth is checked before any token is spent, and the ping carries
        the REAL envelope schema, so a CLI too old for `--json-schema`
        fails here instead of mid-conversation.
        """
        try:
            binary = resolve_binary(self.binary_path)
        except RuntimeError as error:
            return False, str(error)
        try:
            status_output = subprocess.run(
                [str(binary), "auth", "status"],
                capture_output=True,
                text=True,
                check=False,
                timeout=AUTH_STATUS_TIMEOUT_SECONDS,
                cwd=str(self.working_directory),
            ).stdout
            status = json.loads(status_output or "{}")
            if not isinstance(status, dict):
                return False, (
                    f"`{binary} auth status` printed {type(status).__name__}, "
                    f"not a JSON object"
                )
        except Exception as error:  # noqa: BLE001 — diagnostic path
            return False, f"`{binary} auth status` failed: {error}"
        if not status.get("loggedIn"):
            return False, (
                f"Claude Code at {binary} is not signed in. Run "
                f"`claude auth login`, or export ANTHROPIC_API_KEY for the "
                f"metered path."
            )
        try:
            reply = self.chat([{"role": "user", "content": "ping"}], tools)
        except Exception as error:  # noqa: BLE001 — diagnostic path
            return False, f"{binary} answered the preflight with: {error}"
        account = (
            f"{status.get('authMethod', 'unknown auth')}, "
            f"{status.get('subscriptionType', 'no subscription')}"
        )
        limits = (
            f", {self.last_rate_limit.summary()}"
            if self.last_rate_limit is not None
            else ""
        )
        answered = (reply.get("content") or "").strip()[:40]
        return True, (
            f"{self.model} via Claude Code CLI ({account}){limits}"
            f"{f'; said {answered!r}' if answered else ''}"
        )


@dataclass
class _Assembled:
    """What one invocation's frames add up to."""

    thinking: list[str] = field(default_factory=list)
    result: dict | None = None
    # One per Anthropic call. A harness turn is NOT one call: the CLI
    # runs the model again to conform the answer to `--json-schema`,
    # measured at 2-3 calls per turn on 2026-09-06.
    api_calls: int = 0


def _write_frame(stdin, frame: dict) -> None:
    """Send the one user frame, then EOF so the CLI starts the turn."""
    try:
        stdin.write(json.dumps(frame) + "\n")
    except (BrokenPipeError, ValueError):
        # The child died or was killed (watchdog); the reader side
        # reports it.
        pass
    finally:
        # EOF whether or not the write landed: an unclosed pipe is an fd
        # held until garbage collection.
        try:
            stdin.close()
        except (BrokenPipeError, ValueError):
            pass


def _drain_stream(stream, sink: list[str]) -> None:
    """Read a pipe to EOF so the child never blocks on a full buffer."""
    try:
        sink.append(stream.read())
    finally:
        stream.close()


def _absorb_stream_event(event: dict, assembled: _Assembled) -> None:
    if event.get("type") == _EVENT_MESSAGE_START:
        assembled.api_calls += 1
        return
    if event.get("type") != _EVENT_CONTENT_BLOCK_DELTA:
        return
    delta = event.get("delta") or {}
    if delta.get("type") == _DELTA_THINKING:
        assembled.thinking.append(delta.get(_BLOCK_THINKING) or "")
    # Text arrives whole in the result frame; input_json_delta is the
    # structured envelope arriving token by token on a StructuredOutput
    # tool_use block, and the parsed envelope arrives whole in the
    # result frame too.


def _absorb_assistant(message: dict, assembled: _Assembled) -> None:
    """Thinking from the complete assistant frame.

    Taken from the frame rather than only the deltas so a non-streaming
    caller still gets the thinking text in its assistant dict.
    """
    for block in message.get("content") or []:
        if block.get("type") == _BLOCK_THINKING:
            thinking = block.get(_BLOCK_THINKING) or ""
            if thinking and thinking not in "".join(assembled.thinking):
                assembled.thinking.append(thinking)
