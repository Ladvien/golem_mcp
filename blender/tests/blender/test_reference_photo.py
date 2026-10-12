"""A user's photograph, made carriable: PNG, size-capped, no leftovers.

Both model transports hardcode PNG (`claude_code.IMAGE_MEDIA_TYPE`, the
`data:image/png;base64,` URL on the OpenAI lane), and a phone photo is
neither PNG nor small. The three things a caller depends on are pinned
here: the bytes really are a PNG, the long edge really is capped, and
the user's scene does not keep their photograph as a datablock.

Read through Blender's own image API rather than the module's — a
normalizer measured with its own loader only proves it agrees with
itself.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

from blended.capture.reference_photo import (
    MAXIMUM_PHOTO_EDGE_PX,
    normalize_reference_photo,
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
OVERSIZE_WIDTH_PX = 2000
OVERSIZE_HEIGHT_PX = 1500
UNDERSIZE_WIDTH_PX = 64
UNDERSIZE_HEIGHT_PX = 48


@pytest.fixture()
def oversize_photo(tmp_path):
    """A 2000x1500 PNG on disk, standing in for a phone photo."""
    source = tmp_path / "phone_photo.png"
    image = bpy.data.images.new(
        "phone_photo", width=OVERSIZE_WIDTH_PX, height=OVERSIZE_HEIGHT_PX
    )
    try:
        image.filepath_raw = str(source)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)
    return source


def _image_size_px(image_path):
    loaded = bpy.data.images.load(str(image_path))
    try:
        return tuple(loaded.size)
    finally:
        bpy.data.images.remove(loaded)


def test_the_long_edge_is_capped_and_aspect_is_kept(oversize_photo, tmp_path):
    result = normalize_reference_photo(oversize_photo, tmp_path / "normalized")

    width_px, height_px = _image_size_px(result)
    assert max(width_px, height_px) == MAXIMUM_PHOTO_EDGE_PX
    source_aspect = OVERSIZE_WIDTH_PX / OVERSIZE_HEIGHT_PX
    assert width_px / height_px == pytest.approx(source_aspect, abs=0.01)


def test_the_written_bytes_are_a_png(oversize_photo, tmp_path):
    """The wire says image/png; a re-suffixed JPEG would be a lie."""
    result = normalize_reference_photo(oversize_photo, tmp_path / "normalized")

    assert result.read_bytes()[: len(PNG_MAGIC)] == PNG_MAGIC


def test_the_photograph_does_not_linger_in_the_scene(oversize_photo, tmp_path):
    """It runs in the user's live session; it must leave no datablock."""
    before = len(bpy.data.images)

    normalize_reference_photo(oversize_photo, tmp_path / "normalized")

    assert len(bpy.data.images) == before


def test_an_image_smaller_than_the_cap_is_not_upscaled(tmp_path):
    small_source = tmp_path / "small.png"
    image = bpy.data.images.new(
        "small", width=UNDERSIZE_WIDTH_PX, height=UNDERSIZE_HEIGHT_PX
    )
    try:
        image.filepath_raw = str(small_source)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)

    result = normalize_reference_photo(small_source, tmp_path / "normalized")

    assert _image_size_px(result) == (UNDERSIZE_WIDTH_PX, UNDERSIZE_HEIGHT_PX)


def test_heic_is_refused_by_name(tmp_path):
    """The macOS camera default. Blender decodes it to 0x0, silently."""
    heic = tmp_path / "photo.heic"
    heic.write_bytes(b"not-really-heic")

    with pytest.raises(ValueError, match="convert it first"):
        normalize_reference_photo(heic, tmp_path / "normalized")


def test_a_missing_photo_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        normalize_reference_photo(tmp_path / "absent.png", tmp_path / "normalized")
