"""Transcript logging: pure, no bpy."""

from blended.agent.transcript import ChatTranscript, default_log_directory


def test_writes_both_formats_with_a_header(tmp_path):
    transcript = ChatTranscript(tmp_path, session_name="s1", routing="w/e")
    assert transcript.jsonl_path.exists()
    assert transcript.markdown_path.exists()
    header = transcript.markdown_path.read_text()
    assert "blended session — s1" in header
    assert "Routing: w/e" in header


def test_events_append_to_both_files(tmp_path):
    transcript = ChatTranscript(tmp_path, session_name="s2")
    transcript.record("user", "make a crate")
    transcript.record("tool", "run_python({...})")
    transcript.record("answer", "Built it.")

    events = transcript.read_events()
    kinds = [event["kind"] for event in events]
    assert kinds == ["session", "user", "tool", "answer"]
    assert [event["index"] for event in events] == [1, 2, 3, 4]

    markdown = transcript.markdown_path.read_text()
    assert "make a crate" in markdown
    assert "Built it." in markdown
    assert "```" in markdown  # tool events are fenced


def test_jsonl_keeps_full_text_while_markdown_truncates(tmp_path):
    transcript = ChatTranscript(tmp_path, session_name="s3")
    long_result = "x" * 5000
    transcript.record("result", long_result)

    stored = transcript.read_events()[-1]["text"]
    assert stored == long_result, "JSONL must keep full fidelity"

    markdown = transcript.markdown_path.read_text()
    assert "more characters in s3.jsonl" in markdown
    assert len(markdown) < len(long_result)


def test_images_are_referenced_not_embedded(tmp_path):
    transcript = ChatTranscript(tmp_path, session_name="s4")
    transcript.record("result", "rendered", ("/tmp/sheet.png",))
    assert "![sheet.png](/tmp/sheet.png)" in transcript.markdown_path.read_text()
    assert transcript.read_events()[-1]["images"] == ["/tmp/sheet.png"]


def test_append_survives_reopening_the_same_session(tmp_path):
    first = ChatTranscript(tmp_path, session_name="s5")
    first.record("user", "one")
    second = ChatTranscript(tmp_path, session_name="s5")
    second.record("user", "two")

    texts = [event["text"] for event in second.read_events()]
    assert "one" in texts and "two" in texts


def test_reopening_continues_the_event_numbering(tmp_path):
    first = ChatTranscript(tmp_path, session_name="s6")
    first.record("user", "one")
    second = ChatTranscript(tmp_path, session_name="s6")
    second.record("user", "two")

    indices = [event["index"] for event in second.read_events()]
    assert indices == list(range(1, len(indices) + 1))


def test_default_log_directory_prefers_the_repository(tmp_path):
    assert default_log_directory(tmp_path) == tmp_path / "logs"
    fallback = default_log_directory(None)
    assert fallback.parts[-2:] == (".blended", "logs")


def test_schema_two_stores_the_tool_event_under_data(tmp_path):
    """OT-8: a tool_event row is decoded into `data`; every other row has
    data null; the Markdown does not repeat the machine copy."""
    import json

    from blended.agent.tool_event import TOOL_EVENT_KIND, ToolEvent, encode_tool_event
    from blended.agent.transcript import TRANSCRIPT_SCHEMA_VERSION

    assert TRANSCRIPT_SCHEMA_VERSION == 2
    transcript = ChatTranscript(tmp_path, session_name="s")
    transcript.record("tool", 'add_box({"name": "Crate"})')
    event = ToolEvent(
        tool_name="add_box",
        arguments={"name": "Crate"},
        ok=True,
        stage_reached="done",
        wall_time_s=0.5,
    )
    transcript.record(TOOL_EVENT_KIND, encode_tool_event(event))

    rows = transcript.read_events()
    assert [row["schema_version"] for row in rows] == [2, 2, 2]
    assert rows[1]["data"] is None
    assert rows[2]["data"] == json.loads(encode_tool_event(event))
    markdown = transcript.markdown_path.read_text()
    assert "tool_event" not in markdown and 'add_box({"name": "Crate"})' in markdown
