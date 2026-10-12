"""Provider matrix smoke: one text chat and one image-in call per lane.

Exit 0 only when every lane answers. Runs on plain Python (no bpy): the
image is a synthetic red disc written as a PNG by hand, so the check is
"does the reply name the colour", which every vision model here can do
and which cannot be faked by a text-only reply.

Lanes (the served ids are what each server's /v1/models lists):
  * openrouter — deepseek/deepseek-v4.1-flash, tools + images at $0.15/M
    tokens; both calls together cost well under a cent. The balance is
    a small prepaid one, so the completion cap is tiny.
  * bmb — text on qwen3.8-27b (a thinking build: the cap must leave
    room for reasoning or content comes back empty), image on glm-ocr,
    the only model bmb serves with a projector (gemma-4 there 500s with
    "image input is not supported", measured 2026-09-04).
  * big — qwen3-vl for both. big is STRICT SWAP: when another model is
    resident (home-still's olmocr during an ingest) the first call
    waits for the swap, so this lane keeps the 900 s llama-swap ceiling.
  * claude-code — the headless Claude Code CLI on this machine, one
    model for both calls. No key and no endpoint: the binary owns its
    sign-in, and the cost is subscription rate-limit budget, not
    dollars. Haiku at low effort keeps a one-word answer cheap.

Usage:
  .venv/bin/python scripts/provider_smoke.py \
      [--only openrouter,bmb,big,claude-code]
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import tempfile
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from blended.agent.loop import ModelConfig, OllamaClient

# The harness's metered writer and its own eye (OT-28): tools,
# structured outputs, text AND image input, a 1,048,576 context read
# from OpenRouter's catalogue, $0.15/M prompt and $0.60/M completion.
# It replaced qwen3-vl-8b-instruct here so the smoke exercises the lane
# the harness actually runs on. gemma-3-4b-it was cheaper but 429s
# upstream (measured 2026-09-04).
OPENROUTER_SMOKE_MODEL = "deepseek/deepseek-v4.1-flash"
BMB_TEXT_MODEL = "qwen3.8-27b"
BMB_IMAGE_MODEL = "glm-ocr"
BIG_MODEL = "qwen3-vl"
# The cheapest model on the CLI lane, and the lowest effort setting:
# both calls want one word, and the subscription windows are the
# budget. Vision comes free with it — the same transport carries the
# image as a native image block.
CLAUDE_CODE_SMOKE_MODEL = "claude-code:haiku"
CLAUDE_CODE_SMOKE_EFFORT = "low"

TEXT_QUESTION = "Reply with the single word: pong"
TEXT_EXPECTED_WORD = "pong"
IMAGE_QUESTION = "What colour is the shape in this image? Answer with one word."
IMAGE_EXPECTED_WORD = "red"

DISC_IMAGE_SIZE_PX = 128
DISC_RADIUS_FRACTION = 0.35
DISC_RGB = (220, 30, 30)
BACKGROUND_RGB = (255, 255, 255)

# Completion caps per lane: metered lane small; the thinking writer needs
# room to reason before it emits content (measured: 4096 starved it).
# 32 was enough for qwen3-vl-8b-instruct but starved
# deepseek-v4.1-flash, which spends reasoning tokens before its first
# content token and answered "pong" in 18 (measured 2026-09-10). 256
# leaves room for the reasoning and still costs $0.00015 a check.
OPENROUTER_MAX_COMPLETION_TOKENS = 256
THINKING_MAX_COMPLETION_TOKENS = 4096
PLAIN_MAX_COMPLETION_TOKENS = 64


def write_red_disc_png(path: Path) -> Path:
    """A PNG with a red disc on white, written without any image library."""
    size = DISC_IMAGE_SIZE_PX
    centre = size / 2
    radius_squared = (size * DISC_RADIUS_FRACTION) ** 2
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter byte: none
        for x in range(size):
            inside = (x - centre) ** 2 + (y - centre) ** 2 <= radius_squared
            rows += bytes(DISC_RGB if inside else BACKGROUND_RGB)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


@dataclass(frozen=True)
class LaneCheck:
    lane: str
    model: str
    kind: str  # "text" | "image"
    ok: bool
    seconds: float
    detail: str


def _ask(config: ModelConfig, question: str, image_base64: str | None) -> str:
    message = {"role": "user", "content": question}
    if image_base64 is not None:
        message["images"] = [image_base64]
    reply = OllamaClient(config).chat([message])
    return (reply.get("content") or "").strip()


def _run_check(
    lane: str, model: str, kind: str, config: ModelConfig, image_base64: str | None
) -> LaneCheck:
    question = TEXT_QUESTION if kind == "text" else IMAGE_QUESTION
    expected = TEXT_EXPECTED_WORD if kind == "text" else IMAGE_EXPECTED_WORD
    started = time.monotonic()
    try:
        content = _ask(config, question, image_base64)
    except Exception as error:  # noqa: BLE001 — a failed lane is the finding
        return LaneCheck(
            lane, model, kind, False, time.monotonic() - started, str(error)[:300]
        )
    ok = expected in content.lower()
    return LaneCheck(lane, model, kind, ok, time.monotonic() - started, content[:120])


def _config(model: str, max_completion_tokens: int) -> ModelConfig:
    return ModelConfig.from_environment(
        model=model, vision_model="", max_completion_tokens=max_completion_tokens
    )


def run_lanes(lanes: list[str], image_base64: str) -> list[LaneCheck]:
    checks: list[LaneCheck] = []
    if "openrouter" in lanes:
        config = _config(OPENROUTER_SMOKE_MODEL, OPENROUTER_MAX_COMPLETION_TOKENS)
        checks.append(
            _run_check("openrouter", OPENROUTER_SMOKE_MODEL, "text", config, None)
        )
        checks.append(
            _run_check(
                "openrouter", OPENROUTER_SMOKE_MODEL, "image", config, image_base64
            )
        )
    if "bmb" in lanes:
        checks.append(
            _run_check(
                "bmb",
                BMB_TEXT_MODEL,
                "text",
                _config(BMB_TEXT_MODEL, THINKING_MAX_COMPLETION_TOKENS),
                None,
            )
        )
        checks.append(
            _run_check(
                "bmb",
                BMB_IMAGE_MODEL,
                "image",
                _config(BMB_IMAGE_MODEL, PLAIN_MAX_COMPLETION_TOKENS),
                image_base64,
            )
        )
    if "big" in lanes:
        config = _config(BIG_MODEL, PLAIN_MAX_COMPLETION_TOKENS)
        checks.append(_run_check("big", BIG_MODEL, "text", config, None))
        checks.append(_run_check("big", BIG_MODEL, "image", config, image_base64))
    if "claude-code" in lanes:
        # The CLI lane has no `max_tokens` knob (the binary owns
        # generation), so the completion cap is irrelevant here; the
        # low-effort setting is what keeps a one-word answer cheap.
        config = ModelConfig.from_environment(
            model=CLAUDE_CODE_SMOKE_MODEL,
            vision_model="",
            claude_code_effort=CLAUDE_CODE_SMOKE_EFFORT,
        )
        checks.append(
            _run_check("claude-code", CLAUDE_CODE_SMOKE_MODEL, "text", config, None)
        )
        checks.append(
            _run_check(
                "claude-code", CLAUDE_CODE_SMOKE_MODEL, "image", config, image_base64
            )
        )
    return checks


KNOWN_LANES = ("openrouter", "bmb", "big", "claude-code")


def parse_lanes(text: str) -> list[str]:
    """The lanes named by `--only`. An unknown name is a typo, and a typo
    that silently ran nothing would make "every lane answers" true of
    zero lanes."""
    lanes = [lane.strip() for lane in text.split(",") if lane.strip()]
    unknown = [lane for lane in lanes if lane not in KNOWN_LANES]
    if unknown or not lanes:
        raise SystemExit(
            f"--only names {unknown or 'no lane'}; known lanes: {', '.join(KNOWN_LANES)}"
        )
    return lanes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--only", default=",".join(KNOWN_LANES))
    arguments = parser.parse_args(argv)
    lanes = parse_lanes(arguments.only)

    with tempfile.TemporaryDirectory() as directory:
        disc = write_red_disc_png(Path(directory) / "red_disc.png")
        image_base64 = base64.b64encode(disc.read_bytes()).decode("ascii")
        checks = run_lanes(lanes, image_base64)

    width = max(len(check.model) for check in checks)
    for check in checks:
        status = "OK  " if check.ok else "FAIL"
        print(
            f"{status} {check.lane:<10} {check.model:<{width}} {check.kind:<5} "
            f"{check.seconds:7.1f}s  {check.detail!r}"
        )
    failed = [check for check in checks if not check.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
