"""How images reach the eye: one placeholder per image, never adjacent.

Ollama's renderer prepends `[img-0][img-1]...` back to back when a
message carries images and no explicit placeholders, and llama.cpp's
mtmd tokenizer merges *consecutive* same-size bitmaps into video frames
for the qwen-vl family (ollama/ollama#17321, ggml-org/llama.cpp#24303,
both open). Every render this harness makes comes out of the same
`CaptureSettings`, so every pair is the same size — the exact case that
merges.

Measured 2026-08-22 against `qwen3-vl:8b` on ollama 0.32.14: two 512x512
renders in one message cost 1055 prompt tokens (one image's worth), the
model answered "1" to "how many images did you receive?", and the
examiner returned `cannot_tell` because it had never been shown the
render under review. With the placeholders below: 2089 tokens, both
objects named, and the naming follows the order when the pair is
swapped.

That is a silent instrument failure — a calibrated examiner that cannot
see the candidate scores every defect as unseen — so the wire shape is
pinned here rather than left to a comment. Interception is at
`_request`, the HTTP boundary, because `describe` builds its own client
to swap in the eye's model: the payload on the wire is the only honest
place to assert what the model will be shown.
"""

from pathlib import Path

import pytest

from blended.agent.loop import (
    VISION_DESCRIBE_PROMPT,
    ModelConfig,
    OllamaClient,
    VisionDescriber,
)

EXAMINER_CONTRACT = 'Return exactly this JSON: {"tags": ["no_deviation"]}'


@pytest.fixture
def sent_messages(monkeypatch):
    """Every message this test's calls would have put on the wire."""
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append(payload)
        return {"message": {"role": "assistant", "content": "seen"}}

    monkeypatch.setattr(OllamaClient, "_request", capture)
    return payloads


def _describe(tmp_path: Path, image_count: int, **keywords) -> None:
    paths = []
    for index in range(image_count):
        path = tmp_path / f"view_{index}.png"
        path.write_bytes(f"png-{index}".encode())
        paths.append(path)
    client = OllamaClient(
        ModelConfig.from_environment(
            context_length=32_768, eye_context_length=32_768, model="writer"
        )
    )
    VisionDescriber(client, "eye").describe(paths, **keywords)


@pytest.mark.parametrize("image_count", [1, 2, 5])
def test_every_image_gets_its_own_placeholder(tmp_path, sent_messages, image_count):
    _describe(tmp_path, image_count, prompt=EXAMINER_CONTRACT)

    message = sent_messages[0]["messages"][0]
    assert message["content"].count("[img]") == image_count
    assert len(message["images"]) == image_count


@pytest.mark.parametrize("image_count", [2, 5])
def test_no_two_placeholders_are_adjacent(tmp_path, sent_messages, image_count):
    """Adjacency is the merge trigger; text between them is the fix."""
    _describe(tmp_path, image_count, prompt=EXAMINER_CONTRACT)

    content = sent_messages[0]["messages"][0]["content"]
    assert "[img][img]" not in content
    between = content.split("[img]")[1:-1]
    assert all(gap.strip() for gap in between), (
        f"placeholders separated by whitespace only: {between!r}"
    )


def test_the_placeholders_are_numbered_in_call_order(tmp_path, sent_messages):
    """`examiner.md.j2` says "the FIRST image" — that must be image 1."""
    _describe(tmp_path, 2, prompt=EXAMINER_CONTRACT)

    content = sent_messages[0]["messages"][0]["content"]
    assert content.index("Image 1:") < content.index("Image 2:")


def test_the_callers_prompt_survives_verbatim_after_the_placeholders(
    tmp_path, sent_messages
):
    """The examiner's contract is hashed into its identity; do not edit it."""
    _describe(tmp_path, 2, prompt=EXAMINER_CONTRACT)

    content = sent_messages[0]["messages"][0]["content"]
    assert content.endswith(EXAMINER_CONTRACT)
    assert content.index("[img]") < content.index(EXAMINER_CONTRACT)


def test_the_writer_path_gets_the_same_treatment(tmp_path, sent_messages):
    """Placeholders are unconditional, not an examiner-only special case.

    `render_views` hands this path ONE contact sheet today, so it was
    never bitten — but the seam is shared, and a branch that only
    protects the examiner is a second path waiting to rot.
    """
    _describe(tmp_path, 3, question="is the seat level?")

    content = sent_messages[0]["messages"][0]["content"]
    assert content.count("[img]") == 3
    assert VISION_DESCRIBE_PROMPT in content
    assert "is the seat level?" in content
