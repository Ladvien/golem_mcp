"""Pure layer: no bpy anywhere in these imports."""

from blended.drift.catalog import DRIFT_ENTRIES, match_traceback, validate_catalog


def test_catalog_is_schema_valid():
    assert validate_catalog() == []


def test_catalog_is_not_empty():
    assert len(DRIFT_ENTRIES) >= 4


def test_match_traceback_finds_known_signature():
    fake_traceback = (
        "Traceback (most recent call last):\n"
        '  File "<agent>", line 3, in <module>\n'
        "AttributeError: 'Mesh' object has no attribute 'use_auto_smooth'\n"
    )
    matched = match_traceback(fake_traceback)
    assert any("use_auto_smooth" in entry.symbol for entry in matched)


def test_match_traceback_empty_on_clean_text():
    assert match_traceback("everything is fine") == []
