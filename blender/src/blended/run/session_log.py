"""Append-only JSONL session log.

Every executed chunk — success or failure, every retry attempt — lands
here as one JSON line. This is the raw material the drift catalog grows
from: recurring error fingerprints in the log are candidate catalog
entries, exactly how 3DCodeBench's Experience Library was populated.
Append-only by design: a log that can be rewritten is a log that lies.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from blended.run.executor import RunResult

LOG_SCHEMA_VERSION = 1
SOURCE_HASH_LENGTH = 12


def _source_digest(source_code: str) -> str:
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:SOURCE_HASH_LENGTH]


class SessionLog:
    """One JSONL file per session; records are only ever appended."""

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def record_attempt(
        self,
        chunk_label: str,
        source_code: str,
        result: RunResult,
        attempt_index: int = 0,
    ) -> dict:
        """Append one attempt; return the record that was written."""
        record = {
            "schema_version": LOG_SCHEMA_VERSION,
            "logged_at": datetime.now(UTC).isoformat(),
            "chunk_label": chunk_label,
            "attempt_index": attempt_index,
            "source_sha256": _source_digest(source_code),
            "source_line_count": source_code.count("\n") + 1,
            "ok": result.ok,
            "duration_s": round(result.duration_s, 4),
            "blender_version": result.blender_version,
            "error_type": result.error_type,
            "error_message": result.error_message,
            "matched_drift": [entry.symbol for entry in result.matched_drift],
        }
        with self.log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record) + "\n")
        return record

    def record_outcome(self, chunk_label: str, outcome) -> None:
        """Append every attempt of a RetryOutcome."""
        for attempt in outcome.attempts:
            self.record_attempt(
                chunk_label=chunk_label,
                source_code=attempt.source_code,
                result=attempt.result,
                attempt_index=attempt.attempt_index,
            )

    def read_records(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        with self.log_path.open("r", encoding="utf-8") as log_file:
            return [json.loads(line) for line in log_file if line.strip()]
