"""The four reference views are one definition, in render order, and a
missing one is an error rather than a silent fall-back to text."""

from __future__ import annotations

import pytest

from blended.evaluate.bench_reference_views import (
    REFERENCE_VIEW_FILENAMES,
    reference_view_paths,
)


def test_the_views_are_the_benchs_four_turntable_frames_in_order():
    assert REFERENCE_VIEW_FILENAMES == (
        "Image_005.png",
        "Image_015.png",
        "Image_025.png",
        "Image_035.png",
    )


def test_all_four_views_are_returned_in_render_order(tmp_path):
    directory = tmp_path / "Jar_seed0" / "images"
    directory.mkdir(parents=True)
    for name in REFERENCE_VIEW_FILENAMES:
        (directory / name).write_bytes(b"png")
    paths = reference_view_paths(tmp_path, "Jar_seed0")
    assert tuple(path.name for path in paths) == REFERENCE_VIEW_FILENAMES


def test_a_missing_view_is_named_and_refused(tmp_path):
    directory = tmp_path / "Jar_seed0" / "images"
    directory.mkdir(parents=True)
    for name in REFERENCE_VIEW_FILENAMES[:3]:
        (directory / name).write_bytes(b"png")
    with pytest.raises(FileNotFoundError) as raised:
        reference_view_paths(tmp_path, "Jar_seed0")
    assert "Image_035.png" in str(raised.value)
    assert "bench_render_references" in str(raised.value)
