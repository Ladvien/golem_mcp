"""Contact sheets: the four inspection views plus the gate verdict,
composed into one reviewable image.

This is the iteration artifact: one call, one image, geometry AND
verdict together. The verdict line comes from the analyzer (the hard
gate), never from how the render looks — the sheet exists so a human
can double-check the gate, not replace it.

Requires Pillow (`pip install pillow`); the import stays inside the
function so the rest of the capture layer works without it.
"""

from __future__ import annotations

from pathlib import Path

SHEET_MARGIN_PX = 8
SHEET_HEADER_HEIGHT_PX = 40
LABEL_HEIGHT_PX = 18
PASS_COLOR = (0, 122, 0)
FAIL_COLOR = (186, 0, 0)
TEXT_COLOR = (20, 20, 20)
SHEET_BACKGROUND_COLOR = (255, 255, 255)


def compose_contact_sheet(
    view_paths: dict[str, Path],
    output_path: Path,
    title: str = "",
    verdict_lines: tuple[str, ...] = (),
    verdict_passed: bool | None = None,
) -> Path:
    """Tile the captured views into a labeled 2x2 sheet."""
    from blended.capture.compose import compose_grid_numpy, pillow_available

    # Blender bundles numpy, not Pillow. Without Pillow we still produce
    # the sheet — just without burnt-in labels. The agent gets the
    # verdict as tool text either way; labels are for humans.
    if not pillow_available():
        return compose_grid_numpy(view_paths, output_path)

    from PIL import Image, ImageDraw

    view_names = list(view_paths)
    view_images = [
        Image.open(view_paths[view_name]).convert("RGB") for view_name in view_names
    ]
    cell_width_px, cell_height_px = view_images[0].size
    column_count = 2
    row_count = (len(view_images) + column_count - 1) // column_count

    sheet = Image.new(
        "RGB",
        (
            column_count * cell_width_px + (column_count + 1) * SHEET_MARGIN_PX,
            SHEET_HEADER_HEIGHT_PX
            + row_count * (cell_height_px + LABEL_HEIGHT_PX + SHEET_MARGIN_PX),
        ),
        SHEET_BACKGROUND_COLOR,
    )
    drawing = ImageDraw.Draw(sheet)
    if title:
        drawing.text((SHEET_MARGIN_PX, 4), title, fill=TEXT_COLOR)
    if verdict_lines:
        verdict_color = (
            TEXT_COLOR
            if verdict_passed is None
            else (PASS_COLOR if verdict_passed else FAIL_COLOR)
        )
        drawing.text(
            (SHEET_MARGIN_PX, 20), " | ".join(verdict_lines), fill=verdict_color
        )

    for view_index, (view_name, view_image) in enumerate(zip(view_names, view_images)):
        column_index = view_index % column_count
        row_index = view_index // column_count
        cell_x_px = SHEET_MARGIN_PX + column_index * (cell_width_px + SHEET_MARGIN_PX)
        cell_y_px = SHEET_HEADER_HEIGHT_PX + row_index * (
            cell_height_px + LABEL_HEIGHT_PX + SHEET_MARGIN_PX
        )
        drawing.text((cell_x_px, cell_y_px), view_name, fill=TEXT_COLOR)
        sheet.paste(view_image, (cell_x_px, cell_y_px + LABEL_HEIGHT_PX))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return output_path


def capture_contact_sheet(
    blender_object,
    output_directory: Path,
    settings=None,
    report=None,
    budget=None,
    extra_objects: tuple = (),
) -> Path:
    """Capture the standard views and compose them with the gate verdict.

    Pass the object's MeshReport (and optionally a MeshBudget) to stamp
    the verdict on the sheet; without a report the sheet is views-only.
    `extra_objects` widens the framing bounds only — an assembly must
    not be cropped to its first part. The default empty tuple leaves
    the framing unchanged.
    """
    from blended.capture.views import CaptureSettings, capture_views

    settings = settings or CaptureSettings()
    output_directory = Path(output_directory)
    view_paths = capture_views(
        blender_object, output_directory, settings, extra_objects=extra_objects
    )

    verdict_lines: tuple[str, ...] = ()
    verdict_passed: bool | None = None
    if report is not None:
        from blended.analyze import MeshBudget

        active_budget = budget or MeshBudget()
        failures = report.failures(active_budget)
        verdict_passed = not failures
        summary = (
            f"tris {report.triangle_count} | components "
            f"{report.connected_component_count} | self-int "
            f"{report.self_intersecting_face_pair_count} | flipped "
            f"{report.flipped_normal_triangle_count}"
        )
        verdict_lines = (
            ("GATE: PASS  " + summary,)
            if verdict_passed
            else ("GATE: FAIL  " + summary + "  " + "; ".join(failures),)
        )

    sheet_name = f"{blender_object.name}_sheet.png"
    return compose_contact_sheet(
        view_paths,
        output_directory / sheet_name,
        title=blender_object.name,
        verdict_lines=verdict_lines,
        verdict_passed=verdict_passed,
    )
