"""Image compositing that works inside a real Blender install.

Blender bundles numpy. Blender does NOT bundle Pillow. Since the whole
point of the addon is that it runs without `pip install` inside
Blender, the contact-sheet compositor must not need Pillow.

So numpy is the primary path, using Blender's own image API to load and
save. Pillow is used only when present, purely to add text labels —
nice for humans reading a sheet in a chat log or CI artifact, and
irrelevant to the agent, which receives the verdict as tool TEXT
alongside the image anyway.
"""

from __future__ import annotations

from pathlib import Path

SHEET_MARGIN_PX = 8
SHEET_BACKGROUND_RGBA = (1.0, 1.0, 1.0, 1.0)
CHANNELS_PER_PIXEL = 4


def pillow_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("PIL") is not None


def load_image_as_array(image_path: Path):
    """Load a PNG through Blender's image API into an (h, w, 4) array.

    Blender stores pixels bottom-up; the array is returned in that same
    orientation so tiling math stays in one coordinate system.
    """
    import bpy
    import numpy

    loaded_image = bpy.data.images.load(str(image_path))
    try:
        width_px, height_px = loaded_image.size
        flat_pixels = numpy.empty(
            width_px * height_px * CHANNELS_PER_PIXEL, dtype=numpy.float32
        )
        loaded_image.pixels.foreach_get(flat_pixels)
        return flat_pixels.reshape((height_px, width_px, CHANNELS_PER_PIXEL))
    finally:
        bpy.data.images.remove(loaded_image)


def compose_grid_numpy(
    view_paths: dict[str, Path],
    output_path: Path,
    column_count: int = 2,
) -> Path:
    """Tile views into a grid PNG using only numpy + Blender's image API."""
    import bpy
    import numpy

    view_arrays = [load_image_as_array(path) for path in view_paths.values()]
    cell_height_px, cell_width_px = view_arrays[0].shape[:2]
    row_count = (len(view_arrays) + column_count - 1) // column_count

    sheet_width_px = column_count * cell_width_px + (column_count + 1) * SHEET_MARGIN_PX
    sheet_height_px = row_count * cell_height_px + (row_count + 1) * SHEET_MARGIN_PX
    sheet = numpy.zeros(
        (sheet_height_px, sheet_width_px, CHANNELS_PER_PIXEL), dtype=numpy.float32
    )
    sheet[:, :] = SHEET_BACKGROUND_RGBA

    for view_index, view_array in enumerate(view_arrays):
        column_index = view_index % column_count
        # Rows fill top-down visually; the buffer is bottom-up, so invert.
        row_index = row_count - 1 - (view_index // column_count)
        left_px = SHEET_MARGIN_PX + column_index * (cell_width_px + SHEET_MARGIN_PX)
        bottom_px = SHEET_MARGIN_PX + row_index * (cell_height_px + SHEET_MARGIN_PX)
        sheet[
            bottom_px : bottom_px + cell_height_px,
            left_px : left_px + cell_width_px,
        ] = view_array

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_image = bpy.data.images.new(
        output_path.stem, width=sheet_width_px, height=sheet_height_px, alpha=True
    )
    try:
        sheet_image.pixels.foreach_set(sheet.reshape(-1))
        sheet_image.filepath_raw = str(output_path)
        sheet_image.file_format = "PNG"
        sheet_image.save()
    finally:
        bpy.data.images.remove(sheet_image)
    return output_path
