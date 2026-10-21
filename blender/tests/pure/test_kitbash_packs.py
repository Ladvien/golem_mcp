"""register_pack on a synthetic pack: sizes in Blender's frame, skips, names, grid candidates.

The GLBs are boxes assembled by hand in the glTF frame (y up); Blender's frame
is z up with (x, y, z) = (gx, -gz, gy).
"""

import dataclasses
import json

import pytest
import yaml
from _glb_fixture import _build_glb, _write_glb

from golem_blender.kitbash import packs

# The 12 triangles of a box over the 8 corners in _box_glb's order.
_BOX_TRIANGLES = (
    0, 2, 1, 0, 3, 2,  # bottom (min y)
    4, 5, 6, 4, 6, 7,  # top (max y)
    0, 1, 5, 0, 5, 4,
    1, 2, 6, 1, 6, 5,
    2, 3, 7, 2, 7, 6,
    3, 0, 4, 3, 4, 7,
)  # fmt: skip


def _box_glb(minimum, maximum, materials=()):
    (x0, y0, z0), (x1, y1, z1) = minimum, maximum
    positions = (
        (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1),
        (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1),
    )  # fmt: skip
    return _build_glb(positions, _BOX_TRIANGLES, materials=materials)


@pytest.fixture()
def pack(tmp_path):
    """A slab 2 x 2 x 0.2 m and a wall 2 x 0.3 x 3 m (Blender frame), a cube 2 m in a
    subfolder, and an .fbx placeholder. The slab is offset so the frame mapping shows."""
    directory = tmp_path / "pack"
    (directory / "sub").mkdir(parents=True)
    # glTF (1..3, 0..0.2, -4..-2) is Blender (1..3, 2..4, 0..0.2).
    _write_glb(
        directory, _box_glb((1, 0, -4), (3, 0.2, -2), materials=("Stone",)), "slab.glb"
    )
    _write_glb(directory, _box_glb((0, 0, 0), (2, 3, 0.3)), "wall.glb")
    _write_glb(directory / "sub", _box_glb((0, 0, 0), (2, 2, 2)), "cube.glb")
    (directory / "model.fbx").write_bytes(b"Kaydara FBX Binary")
    (directory / "readme.txt").write_text("not a model")
    return directory


def _kit(kit_dir):
    return yaml.safe_load((kit_dir / "kit.yaml").read_text())


def test_registering_a_pack_writes_a_kit_of_measured_approved_pieces(pack, tmp_path):
    kit_dir = tmp_path / "kit"

    report = packs.register_pack(pack, kit_dir, "Dungeon Bits", "CC0")

    kit = _kit(kit_dir)
    assert kit["schema"] == "blended-kitbash/kit@1"
    assert (kit["name"], kit["slug"]) == ("Dungeon Bits", "dungeon_bits")
    assert kit["units"] is None and kit["style"] is None
    assert kit["pack"]["license"] == "CC0"
    assert kit["pack"]["source_dir"] == str(pack.resolve())
    assert [piece["name"] for piece in kit["catalog"]] == ["slab", "cube", "wall"]
    assert {piece["source"] for piece in kit["catalog"]} == {"pack"}
    assert {piece["status"] for piece in kit["catalog"]} == {"approved"}
    assert report.piece_count == 3
    assert report.kit_yaml == str(kit_dir / "kit.yaml")

    by_name = {piece["name"]: piece for piece in kit["catalog"]}
    # glTF y up becomes Blender z up: the wall is 3 m tall, 0.3 m deep.
    assert by_name["wall"]["size_m"] == pytest.approx([2, 0.3, 3])
    slab = by_name["slab"]
    assert slab["size_m"] == pytest.approx([2, 2, 0.2])
    assert slab["bounds_min_m"] == pytest.approx([1, 2, 0])
    assert slab["bounds_max_m"] == pytest.approx([3, 4, 0.2])
    assert slab["triangles"] == 12
    assert slab["materials"] == ["Stone"]
    assert by_name["wall"]["materials"] == []
    assert slab["glb"] == str((pack / "slab.glb").resolve())
    assert by_name["cube"]["glb"] == str((pack / "sub" / "cube.glb").resolve())


def test_formats_other_than_glb_are_skipped_with_the_reason(pack, tmp_path):
    report = packs.register_pack(pack, tmp_path / "kit", "Dungeon Bits", "CC0")

    assert report.skipped == ({"file": "model.fbx", "reason": "only .glb is read"},)
    assert _kit(tmp_path / "kit")["pack"]["skipped"] == [
        {"file": "model.fbx", "reason": "only .glb is read"}
    ]


def test_the_report_names_the_grid_the_pieces_snap_to(pack, tmp_path):
    report = packs.register_pack(pack, tmp_path / "kit", "Dungeon Bits", "CC0")

    # X and Y extents: 2, 2, 2, 0.3, 2, 2. The slab and the cube sit on a 2 m grid;
    # the wall's 0.3 m depth fits no multiple of 2.
    assert report.footprint_histogram == ((2.0, 5), (0.3, 1))
    assert report.height_histogram == ((0.2, 1), (2.0, 1), (3.0, 1))
    assert report.grid_candidates == (2.0, 0.3)
    assert json.loads(json.dumps(dataclasses.asdict(report)))["grid_candidates"] == [
        2.0,
        0.3,
    ]


def test_a_second_registration_is_refused_and_changes_nothing(pack, tmp_path):
    kit_dir = tmp_path / "kit"
    packs.register_pack(pack, kit_dir, "Dungeon Bits", "CC0")
    before = (kit_dir / "kit.yaml").read_text()

    with pytest.raises(FileExistsError):
        packs.register_pack(pack, kit_dir, "Other Name", "MIT")

    assert (kit_dir / "kit.yaml").read_text() == before


def test_a_folder_without_a_glb_is_refused_and_writes_no_kit(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "only.fbx").write_bytes(b"x")

    with pytest.raises(ValueError, match="no readable .glb"):
        packs.register_pack(empty, tmp_path / "kit", "Empty", "CC0")
    with pytest.raises(NotADirectoryError):
        packs.register_pack(tmp_path / "absent", tmp_path / "kit", "Absent", "CC0")

    assert not (tmp_path / "kit" / "kit.yaml").exists()


def test_a_glb_the_parser_rejects_is_skipped_with_its_error_and_the_rest_register(
    pack, tmp_path
):
    _write_glb(pack, b"this is not a glb file at all", "broken.glb")

    report = packs.register_pack(pack, tmp_path / "kit", "Dungeon Bits", "CC0")

    assert report.piece_count == 3
    broken = next(entry for entry in report.skipped if entry["file"] == "broken.glb")
    assert broken["reason"].startswith("ValueError")
    assert "not a .glb" in broken["reason"]


def test_piece_names_are_identifiers_and_collisions_get_a_number(tmp_path):
    directory = tmp_path / "pack"
    (directory / "b").mkdir(parents=True)
    box = _box_glb((0, 0, 0), (1, 1, 1))
    _write_glb(directory, box, "Wall A.glb")
    _write_glb(directory, box, "Wall-A.glb")
    _write_glb(directory / "b", box, "Wall A.glb")

    packs.register_pack(directory, tmp_path / "kit", "Names", "CC0")

    assert sorted(piece["name"] for piece in _kit(tmp_path / "kit")["catalog"]) == [
        "Wall_A",
        "Wall_A_2",
        "Wall_A_3",
    ]
