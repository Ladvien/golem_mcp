"""compose_contact_sheet's Pillow branch, which needs Pillow.

Pillow is neither in `.venv` nor in Blender's Python, so this directory runs
in `make test-bench-scripts`' throwaway env, never in `make test-pure`.
"""

from PIL import Image


def test_contact_sheet_pillow_branch_returns_the_written_sheet(tmp_path):
    """compose_contact_sheet's Pillow branch fell off the end of the
    function (returned None, wrote nothing)."""
    from blended.capture.contact_sheet import compose_contact_sheet

    view_size_px = (64, 48)
    view_paths = {}
    for view_name in ("front", "right", "top", "three_quarter"):
        view_path = tmp_path / f"{view_name}.png"
        Image.new("RGB", view_size_px, (200, 100, 50)).save(view_path)
        view_paths[view_name] = view_path

    sheet_path = compose_contact_sheet(view_paths, tmp_path / "sheet.png", title="t")

    assert sheet_path == tmp_path / "sheet.png"
    assert sheet_path.is_file()
    with Image.open(sheet_path) as sheet:
        assert sheet.size[0] > view_size_px[0] * 2
        assert sheet.size[1] > view_size_px[1] * 2
