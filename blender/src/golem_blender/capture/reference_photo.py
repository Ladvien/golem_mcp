"""Normalize a user's photograph into something the wire can carry.

The harness's own renders are already PNGs of a known size, so nothing
here existed before: `compose.py` loads only images this package wrote.
A phone photo is different — multi-megapixel, usually JPEG, sometimes
HEIC — and both model transports hardcode PNG: `claude_code._image_block`
stamps `media_type: "image/png"` and the OpenAI lane emits a
`data:image/png;base64,...` URL. So a reference photo is re-encoded to
PNG and capped on its long edge before it ever reaches a model.

Blender bundles no EXIF reader and neither does the dev venv, so the
orientation tag is ignored: a sideways phone photo stays sideways and
the model will read a sideways object. There is no rotation handling.
"""

from __future__ import annotations

from pathlib import Path

# What Blender's image loader can decode without a plugin. HEIC — the
# macOS camera default — is not on the list, and refusing it by name is
# the whole of its handling: Blender returns a 0x0 datablock for it,
# which is indistinguishable from a corrupt PNG.
SUPPORTED_PHOTO_SUFFIXES = (".png", ".jpg", ".jpeg")
# Long-edge cap. A 12 MP phone photo is ~4000 px wide and costs an order
# of magnitude more image tokens than the detail adds: the eye is asked
# for silhouette, parts and proportions, all of which survive 1024 px.
MAXIMUM_PHOTO_EDGE_PX = 1024
UNDECODABLE_IMAGE_SIZE = (0, 0)
MINIMUM_EDGE_PX = 1
NORMALIZED_PHOTO_PREFIX = "reference_"
NORMALIZED_PHOTO_FORMAT = "PNG"
NORMALIZED_PHOTO_SUFFIX = ".png"


def normalize_reference_photo(source_path: Path, output_directory: Path) -> Path:
    """Re-encode a reference photo as a size-capped PNG. Blender only.

    Returns the written path. Raises `ValueError` for a suffix Blender
    cannot read or an image it cannot decode, and `FileNotFoundError`
    when the file is absent. The loaded datablock is always removed, so
    the user's scene never accumulates their photographs.
    """
    import bpy

    source_path = Path(source_path)
    if source_path.suffix.lower() not in SUPPORTED_PHOTO_SUFFIXES:
        raise ValueError(
            f"{source_path.name}: reference photos must be .png, .jpg or "
            f".jpeg (HEIC is not readable by Blender) — convert it first."
        )
    if not source_path.is_file():
        raise FileNotFoundError(str(source_path))

    image = bpy.data.images.load(str(source_path))
    try:
        if tuple(image.size) == UNDECODABLE_IMAGE_SIZE:
            raise ValueError(
                f"{source_path.name}: Blender could not decode this image."
            )
        width_px, height_px = image.size
        longest_edge_px = max(width_px, height_px)
        if longest_edge_px > MAXIMUM_PHOTO_EDGE_PX:
            scale_factor = MAXIMUM_PHOTO_EDGE_PX / longest_edge_px
            image.scale(
                max(MINIMUM_EDGE_PX, round(width_px * scale_factor)),
                max(MINIMUM_EDGE_PX, round(height_px * scale_factor)),
            )
        output_directory = Path(output_directory)
        output_directory.mkdir(parents=True, exist_ok=True)
        destination = output_directory / (
            f"{NORMALIZED_PHOTO_PREFIX}{source_path.stem}{NORMALIZED_PHOTO_SUFFIX}"
        )
        image.file_format = NORMALIZED_PHOTO_FORMAT
        image.filepath_raw = str(destination)
        image.save()
    finally:
        bpy.data.images.remove(image)
    return destination
