"""Chat transcripts on disk: one JSONL and one Markdown per session.

Why both. JSONL is the full-fidelity record — every event, untruncated,
machine-readable — which is what you mine later for recurring failure
fingerprints that deserve a drift-catalog entry. Markdown is what you
actually read when you want to know why a session went sideways, so it
truncates noisy tool dumps and formats for eyes.

Both are written APPEND-AS-YOU-GO rather than at session end: the most
interesting sessions are the ones that crash, and a transcript that
only lands on clean exit would lose exactly those.

Logs are development artifacts, not deliverables — the repo gitignores
them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from blended.agent.tool_event import TOOL_EVENT_KIND

# 2 (OT-8): a `tool_event` row carries its structured payload under
# `data` (see agent/tool_event.py); every other row has `data: null`.
TRANSCRIPT_SCHEMA_VERSION = 2
# Tool results can be thousands of characters of JSON. Full text lives
# in the JSONL; the Markdown keeps it readable.
MARKDOWN_TRUNCATE_CHARACTERS = 1200

EVENT_HEADINGS = {
    "user": "🧑 You",
    "answer": "🤖 Agent",
    "thinking": "…thinking",
    "tool": "→ tool call",
    "result": "← tool result",
    "vision": "👁 what the render shows",
    "plan": "📋 plan",
    "step": "▶ step",
    "render": "🖼 render",
    "reference": "📷 reference photo",
    "error": "⚠️ error",
}


def default_log_directory(repository_root: str | Path | None) -> Path:
    """Where transcripts go: <repo>/logs when we know the repo, else a
    stable per-user location that always exists."""
    if repository_root:
        return Path(repository_root).expanduser() / "logs"
    return Path.home() / ".blended" / "logs"


@dataclass
class ChatTranscript:
    """Append-only session log in two formats."""

    log_directory: Path
    session_name: str = ""
    routing: str = ""

    def __post_init__(self) -> None:
        self.log_directory = Path(self.log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        if not self.session_name:
            stamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M%S")
            self.session_name = f"chat-{stamp}"
        self._event_index = self._last_recorded_index()
        self._write_markdown_header()
        self.record("session", f"started; routing: {self.routing or 'unknown'}")

    def _last_recorded_index(self) -> int:
        """Where a reopened session's numbering left off (0 for a new one):
        an index repeated after a reopen would make two events one key."""
        if not self.jsonl_path.exists():
            return 0
        last_index = 0
        with self.jsonl_path.open(encoding="utf-8") as jsonl_file:
            for line in jsonl_file:
                if line.strip():
                    last_index = json.loads(line)["index"]
        return last_index

    @property
    def jsonl_path(self) -> Path:
        return self.log_directory / f"{self.session_name}.jsonl"

    @property
    def markdown_path(self) -> Path:
        return self.log_directory / f"{self.session_name}.md"

    def _write_markdown_header(self) -> None:
        if self.markdown_path.exists():
            return
        local_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self.markdown_path.write_text(
            f"# blended session — {self.session_name}\n\n"
            f"- Started: {local_time}\n"
            f"- Routing: {self.routing or 'unknown'}\n\n---\n\n",
            encoding="utf-8",
        )

    def record(self, kind: str, text: str, image_paths: tuple[str, ...] = ()) -> None:
        """Append one event to both files."""
        self._event_index += 1
        record = {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "index": self._event_index,
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "text": text,
            "images": list(image_paths),
            # The structured tool record (OT-8). Decoded here so a
            # reader never has to parse JSON out of a text field.
            "data": json.loads(text) if kind == TOOL_EVENT_KIND else None,
        }
        with self.jsonl_path.open("a", encoding="utf-8") as jsonl_file:
            jsonl_file.write(json.dumps(record) + "\n")

        if kind in ("session", TOOL_EVENT_KIND):
            # The tool event is the machine's copy of the tool/result
            # pair already in the Markdown; printing it twice is noise.
            return
        heading = EVENT_HEADINGS.get(kind, kind)
        body = (
            text
            if len(text) <= MARKDOWN_TRUNCATE_CHARACTERS
            else (
                text[:MARKDOWN_TRUNCATE_CHARACTERS]
                + f"\n… [{len(text) - MARKDOWN_TRUNCATE_CHARACTERS} more characters "
                f"in {self.jsonl_path.name}]"
            )
        )
        block = f"### {heading}\n\n"
        if kind in ("tool", "result", "error"):
            block += f"```\n{body}\n```\n\n"
        else:
            block += f"{body}\n\n"
        for image_path in image_paths:
            block += f"![{Path(image_path).name}]({image_path})\n\n"
        with self.markdown_path.open("a", encoding="utf-8") as markdown_file:
            markdown_file.write(block)

    def record_turn_separator(self) -> None:
        with self.markdown_path.open("a", encoding="utf-8") as markdown_file:
            markdown_file.write("---\n\n")

    def read_events(self) -> list[dict]:
        if not self.jsonl_path.exists():
            return []
        with self.jsonl_path.open("r", encoding="utf-8") as jsonl_file:
            return [json.loads(line) for line in jsonl_file if line.strip()]
