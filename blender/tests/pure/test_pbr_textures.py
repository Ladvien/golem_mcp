"""The PBR texture lane's pure layer: paths, conventions, portability.

Pure: no Blender, no network. What it proves is the part that is
cheap to get wrong and expensive to discover late — the file names, the
channel packing, the Mac<->big path swap, and the promise that nothing
in the new code names a machine.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from golem_blender.kitbash import paths as kitbash_paths
from golem_blender.pbr import generate as pbr_generate
from golem_blender.pbr import paths as pbr_paths

# The files the new lane must not contain. "/mnt/codex_fs" is the BIG
# prefix, which must come from GOLEM_CODEX_ROOT_ON_BIG and never be
# written out; "bmb" is the machine that runs mflux; the rest name a
# person, a private address or a home directory.
FORBIDDEN_HOST_STRINGS = (
    "192.168.",
    "ladvien",
    "/Users/",
    "bmb",
    "/home/",
    "/mnt/codex_fs",
)

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "golem_blender"
BLMCP_TOOLS_ROOT = (
    Path(__file__).resolve().parents[2] / "blender_mcp" / "mcp" / "blmcp" / "tools"
)

# The new files the portability check reads.
NEW_SOURCE_FILES = (
    SOURCE_ROOT / "ops" / "pbr_textures.py",
    SOURCE_ROOT / "ops" / "pbr_bake.py",
    SOURCE_ROOT / "pbr" / "paths.py",
    SOURCE_ROOT / "pbr" / "generate.py",
    SOURCE_ROOT / "capture" / "texture_preview.py",
)
NEW_TOOL_FILES = (
    BLMCP_TOOLS_ROOT / "golem_pbr_textures.py",
    BLMCP_TOOLS_ROOT / "golem_pbr_textures_toolcode.py",
    BLMCP_TOOLS_ROOT / "golem_pbr_texture_prompt.py",
)


@pytest.fixture()
def codex(tmp_path, monkeypatch):
    """A codex_fs mounted at tmp_path/codex, which big sees as /mnt/fake_codex."""
    root = tmp_path / "codex"
    (root / "game_assets").mkdir(parents=True)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_MAC", root)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_ON_BIG", "/mnt/fake_codex")
    return root


# --- paths ------------------------------------------------------------------


def test_the_texture_root_is_the_codex_textures_directory(codex, monkeypatch):
    monkeypatch.delenv(pbr_paths.TEXTURE_ROOT_ENV, raising=False)
    assert pbr_paths.texture_root() == codex / "game_assets" / "textures"


def test_the_texture_root_can_be_pointed_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setenv(pbr_paths.TEXTURE_ROOT_ENV, str(tmp_path / "elsewhere"))
    assert pbr_paths.texture_root() == tmp_path / "elsewhere"


def test_a_mac_path_under_the_codex_root_converts_to_the_big_path(codex):
    mac_path = (
        codex
        / "game_assets"
        / "textures"
        / "medieval_village"
        / "T_Brick_BaseColor.png"
    )
    assert (
        pbr_paths.big_path(mac_path)
        == "/mnt/fake_codex/game_assets/textures/medieval_village/T_Brick_BaseColor.png"
    )


def test_a_path_outside_the_codex_root_is_refused(codex, tmp_path):
    with pytest.raises(ValueError):
        pbr_paths.big_path(tmp_path / "elsewhere" / "b.png")


# --- conventions ------------------------------------------------------------


def test_the_set_file_names_are_the_ones_the_existing_sets_use():
    assert pbr_paths.base_color_file_name("Brick") == "T_Brick_BaseColor.png"
    assert pbr_paths.orm_file_name("Brick") == "T_Brick_ORM.png"
    assert pbr_paths.normal_file_name("Brick") == "T_Brick_Normal.png"


def test_the_orm_channel_packing_is_the_one_the_report_states():
    assert pbr_paths.ORM_CHANNEL_PACKING == "R=ao,G=roughness,B=metallic"


# --- export -----------------------------------------------------------------


def test_exporting_a_set_copies_the_maps_and_writes_the_metadata(tmp_path):
    texture_directory = tmp_path / "textures"
    texture_directory.mkdir()
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        (texture_directory / file_name).write_bytes(b"png-bytes")

    destination = tmp_path / "export"
    report = pbr_generate.export_texture_set(
        "Brick", texture_directory, destination, metadata={"model": "flux2-klein-4b"}
    )

    assert set(report["files"]) == {"base_color", "orm", "normal"}
    assert report["missing"] == []
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        assert (destination / file_name).read_bytes() == b"png-bytes"

    metadata = json.loads((destination / "metadata.json").read_text())
    assert metadata["texture_name"] == "Brick"
    assert metadata["channel_packing"] == "R=ao,G=roughness,B=metallic"
    assert metadata["model"] == "flux2-klein-4b"


def test_exporting_copies_the_extras_so_the_set_is_self_contained(tmp_path):
    """The environment map and the references travel with the set.

    A set exported without them says how it was MADE but not how to
    light it or where the pattern came from, so it is not reusable on
    its own.
    """
    texture_directory = tmp_path / "textures"
    texture_directory.mkdir()
    (texture_directory / "T_Brick_BaseColor.png").write_bytes(b"base")
    (texture_directory / "T_Brick_ORM.png").write_bytes(b"orm")
    (texture_directory / "T_Brick_Normal.png").write_bytes(b"normal")

    environment = tmp_path / "T_TownEnv_BaseColor.png"
    environment.write_bytes(b"environment")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")

    destination = tmp_path / "export"
    report = pbr_generate.export_texture_set(
        "Brick",
        texture_directory,
        destination,
        extras=[environment, reference],
    )

    assert set(report["extras"]) == {
        "T_TownEnv_BaseColor.png",
        "reference.png",
    }
    assert (destination / "T_TownEnv_BaseColor.png").read_bytes() == b"environment"
    assert (destination / "reference.png").read_bytes() == b"reference"

    metadata = json.loads((destination / "metadata.json").read_text())
    assert "T_TownEnv_BaseColor.png" in metadata["extras"]


def test_exporting_reports_a_map_that_is_missing_instead_of_hiding_it(tmp_path):
    texture_directory = tmp_path / "textures"
    texture_directory.mkdir()
    (texture_directory / "T_Brick_BaseColor.png").write_bytes(b"png-bytes")

    report = pbr_generate.export_texture_set(
        "Brick", texture_directory, tmp_path / "export"
    )

    assert report["missing"] == ["T_Brick_ORM.png", "T_Brick_Normal.png"]
    assert set(report["files"]) == {"base_color"}


def test_exporting_a_layered_set_carries_its_height_map(tmp_path):
    """A layered set writes a height beside its three maps; an export
    that left it behind would ship a set with no displacement."""
    texture_directory = tmp_path / "textures"
    texture_directory.mkdir()
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
        "T_Brick_Height.png",
    ):
        (texture_directory / file_name).write_bytes(b"png-bytes")

    report = pbr_generate.export_texture_set(
        "Brick", texture_directory, tmp_path / "export"
    )

    assert (tmp_path / "export" / "T_Brick_Height.png").is_file()
    assert report["missing"] == []


def test_the_generated_png_is_found_through_the_mac_mount(tmp_path, monkeypatch):
    """A path big reports must be TRANSLATED before it can be opened.

    The bug this pins: the golem server's `reference_dir` is
    `/mnt/codex_fs/...` — the path BIG sees. Read as a Mac path it does
    not exist, the lookup failed, and the copy silently took the
    PREVIOUS map while the tool reported success.
    """
    from blmcp.tools import golem_pbr_textures

    root = tmp_path / "codex"
    (root / "game_assets" / "generated").mkdir(parents=True)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_MAC", root)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_ON_BIG", "/mnt/fake_codex")
    monkeypatch.setattr(pbr_paths, "big_path", kitbash_paths.big_path)

    published = root / "game_assets" / "generated" / "a_prompt_20260101_000000"
    published.mkdir(parents=True)
    image = published / "reference.png"
    image.write_bytes(b"generated-bytes")

    resolved = golem_pbr_textures._resolve_generated_png(
        {
            "reference_dir": "/mnt/fake_codex/game_assets/generated/a_prompt_20260101_000000",
            "local_path": "/home/someone/else/output.png",
        }
    )

    assert resolved == image
    assert resolved.read_bytes() == b"generated-bytes"


def test_a_path_big_reports_that_is_not_on_codex_is_refused(tmp_path, monkeypatch):
    """A path on big's own filesystem cannot be opened here, and says so."""
    from blmcp.tools import golem_pbr_textures

    root = tmp_path / "codex"
    root.mkdir(parents=True)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_MAC", root)
    monkeypatch.setattr(kitbash_paths, "CODEX_ROOT_ON_BIG", "/mnt/fake_codex")

    assert golem_pbr_textures._mac_path_of("/home/someone/else/output.png") is None
    assert (
        golem_pbr_textures._resolve_generated_png(
            {"local_path": "/home/someone/else/output.png"}
        )
        is None
    )


# --- portability ------------------------------------------------------------


@pytest.mark.parametrize(
    "source_path", NEW_SOURCE_FILES + NEW_TOOL_FILES, ids=lambda path: path.name
)
def test_the_new_files_name_no_machine(source_path):
    """No hard-coded host in the CODE.

    A docstring may name the convention it explains (that is what a
    docstring is for); a string literal or a path in the code may not,
    because the code has to run on any host.
    """
    code_lines = []
    in_docstring = False
    for line in source_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not in_docstring and stripped.startswith(('"""', "'''")):
            in_docstring = not (stripped.endswith(('"""', "'''")) and len(stripped) > 3)
            continue
        if in_docstring:
            if stripped.endswith(('"""', "'''")):
                in_docstring = False
            continue
        code_lines.append(line)

    code = "\n".join(code_lines)
    for forbidden in FORBIDDEN_HOST_STRINGS:
        assert forbidden not in code, (
            f"{source_path.name} contains {forbidden!r} in its code: the lane "
            f"must work on any host, so every root comes from the environment."
        )


# --- the procedure stays true ----------------------------------------------

PROCEDURE_PATH = SOURCE_ROOT / "pbr" / "procedure.md"
# The names the procedure mixes: some are OPS the Blender runs, some
# are TOOLS the MCP server runs. An agent reads the procedure and calls
# names from it, so every one must be callable, and none may be a dead
# end.
PROCEDURE_TOOL_NAMES = (
    "generate_texture_base",
    "preview_texture",
    "export_texture_set",
    "search_reference_images",
    "save_reference_images",
    "generate_procedural_base_color",
    "generate_layered_texture_set",
)
PROCEDURE_OP_NAMES = (
    "add_relief_slab",
    "assign_pbr_texture_set",
    "assign_pbr_constants",
    "bake_orm_map",
    "bake_normal_map",
    "pbr_texture_report",
    "unwrap_uvs",
)


def test_every_name_the_procedure_mentions_is_callable():
    """A name in the procedure that is neither an op nor a tool is a dead end.

    The procedure is the only thing an agent READS before it starts.
    A name there that resolves to nothing sends the agent looking for
    something that does not exist.
    """
    import golem_blender.ops as facade

    text = PROCEDURE_PATH.read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z_]+)\(", text))
    named |= set(re.findall(r"^\| `([a-z_]+)`", text, re.MULTILINE))

    for name in sorted(named):
        assert hasattr(facade, name) or name in PROCEDURE_TOOL_NAMES, (
            f"the procedure names {name!r}, which is neither an op on the "
            f"facade nor a tool the server serves"
        )


def test_the_procedure_quotes_the_codes_own_defaults():
    """The procedure's example numbers must be the code's defaults.

    The procedure is a copy of the code's numbers, and copies drift.
    This reads the signature and checks the procedure says the same
    thing, so a default that moves cannot silently leave the
    procedure quoting the old one.
    """
    import inspect

    from golem_blender.ops import pbr_bake, relief

    text = PROCEDURE_PATH.read_text(encoding="utf-8")
    expected = {
        "ao_distance_m": inspect.signature(pbr_bake.bake_orm_map)
        .parameters["ao_distance_m"]
        .default,
        "roughness": inspect.signature(pbr_bake.bake_orm_map)
        .parameters["roughness"]
        .default,
        "depth_m": inspect.signature(relief.add_relief_slab)
        .parameters["depth_m"]
        .default,
        "cell_count": inspect.signature(relief.add_relief_slab)
        .parameters["cell_count"]
        .default,
    }
    for name, value in expected.items():
        assert f"{name}={value}" in text, (
            f"the procedure does not quote {name}={value}, the code's default. "
            f"It must: the procedure is what the agent reads."
        )


def test_the_normal_map_ranges_are_quoted_consistently():
    """One measured set of ranges, quoted the same way everywhere.

    Three different sets of numbers for the same two maps were in the
    code and the procedure at once. The point of this test is not the
    numbers but that there is only ONE place they are written down.
    """
    from golem_blender.ops import pbr_bake

    doc = pbr_bake.bake_normal_map.__doc__ or ""
    # Every NUMBER RANGE in the docstring, whatever words introduce it.
    # Keying on one phrasing ("spans X to Y") lets a third range through
    # under a different wording, which is the defect being guarded.
    quoted = re.findall(r"([\d.]+) to ([\d.]+)", doc)
    assert len(quoted) == 2, (
        f"bake_normal_map's docstring quotes {len(quoted)} ranges; it should "
        f"quote exactly two - the from_height one and the bake one - so the "
        f"two numbers cannot disagree with each other. Found: {quoted}"
    )
    assert len(set(quoted)) == 2, (
        f"bake_normal_map's docstring quotes the same range twice: {quoted}. "
        f"The two maps have different ranges, so two identical ones means "
        f"one of them is wrong."
    )

    text = PROCEDURE_PATH.read_text(encoding="utf-8")
    for low, high in quoted:
        assert f"{low} to {high}" in text, (
            f"the procedure does not quote the range {low} to {high} that "
            f"the code's docstring quotes."
        )


def test_a_re_export_leaves_no_stale_file_in_the_set(tmp_path):
    """The destination is written as a CLEAN SET.

    A previous export put a reference photo there; this one does not
    include it. Copying over the top would leave the old photo beside
    the new maps, and the metadata - which lists the extras - would
    not mention it, so it would look like part of the deliverable and
    be nothing of the sort.
    """
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "out"
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        (source / file_name).write_bytes(b"png")
    reference = source / "reference.png"
    reference.write_bytes(b"reference")

    pbr_generate.export_texture_set("Brick", source, destination, extras=[reference])
    assert (destination / "reference.png").is_file()

    report = pbr_generate.export_texture_set("Brick", source, destination)

    assert not (destination / "reference.png").exists(), (
        "the reference from the previous export survived, so the set "
        "carries a file its own metadata does not list"
    )
    assert report["removed"] == ["reference.png"]
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        assert (destination / file_name).is_file(), (
            f"the re-export removed {file_name}, which is part of the set"
        )


def test_the_export_leaves_a_file_it_does_not_own_alone(tmp_path):
    """Only the export's OWN files are removed.

    The destination may hold other work. The previous export's
    metadata.json is the record of what belongs to the set, so a file
    no export claims is not this export's to delete.
    """
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "out"
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        (source / file_name).write_bytes(b"png")

    pbr_generate.export_texture_set("Brick", source, destination)
    other = destination / "notes.txt"
    other.write_text("someone else's work")

    pbr_generate.export_texture_set("Brick", source, destination)

    assert other.is_file(), "the export deleted a file that was never its own"
    assert other.read_text() == "someone else's work"


def test_a_set_three_maps_are_the_same_size_by_default():
    """The base colour and the bakes must agree on the set's resolution.

    A set is three maps that go on one surface, and every other set on
    codex_fs has all three at 2048. The lane was producing something
    else - a 1024 base colour with 2048 bakes - because the generator
    and the bakes each had their own default and nobody made them
    agree.
    """
    import inspect

    from golem_blender.ops import pbr_bake

    bake_orm = inspect.signature(pbr_bake.bake_orm_map).parameters["resolution_px"]
    bake_normal = inspect.signature(pbr_bake.bake_normal_map).parameters[
        "resolution_px"
    ]
    assert bake_orm.default == pbr_paths.SET_RESOLUTION_PX
    assert bake_normal.default == pbr_paths.SET_RESOLUTION_PX
    assert bake_orm.default == bake_normal.default, (
        "the two bakes disagree on the set's resolution, so a set can come "
        "out with maps of different sizes"
    )


def test_the_generator_writes_the_set_resolution_by_default():
    """The base colour is generated at the set's resolution too.

    The generator runs in the MCP server's process, so its default is
    read from the tool source rather than from a signature.
    """
    tool_source = (BLMCP_TOOLS_ROOT / "golem_pbr_textures.py").read_text(
        encoding="utf-8"
    )
    assert "width: int = pbr_paths.SET_RESOLUTION_PX" in tool_source, (
        "the generator's width is not the set's resolution, so a set's base "
        "colour comes out at a different size from its bakes"
    )
    assert "height: int = pbr_paths.SET_RESOLUTION_PX" in tool_source


# --- does a texture tile? -------------------------------------------------


def _write_png(path, width, height, pixel):
    """A PNG of one flat colour, written with zlib and no filter."""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes(pixel) * width for _ in range(height))

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_a_flat_texture_has_no_seam_at_all(tmp_path):
    """A flat map tiles trivially, and the measure says so."""
    path = tmp_path / "flat.png"
    _write_png(path, 32, 32, (128, 128, 128))
    assert pbr_paths.tile_seam_ratio(path) == 0.0


def test_a_texture_with_a_hard_seam_measures_it(tmp_path):
    """A map whose last column differs from its first is caught.

    The baseline is the 95th percentile of the interior steps, so the
    map needs a realistic interior: a texture with big features and a
    small seam is a good texture, and one with a small feature and a
    big seam is a bad one. So the map here has ordinary variation and
    a last column that is off by much more than that variation.
    """
    import struct
    import zlib

    width, height = 32, 32
    rows = bytearray()
    for row in range(height):
        rows += b"\x00"
        for column in range(width):
            # The interior is mostly flat with a FEW big features, so
            # its median step and its 95th percentile step differ -
            # which is the whole point: the measure is against the
            # largest ordinary features, not the typical one. The last
            # column is far brighter than any of them.
            value = 100
            if column in (7, 8, 23):
                value = 115
            if column == width - 1:
                value = 220
            rows += bytes((value, value, value))

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = tmp_path / "seamed.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )

    ratio = pbr_paths.tile_seam_ratio(path)
    assert ratio > pbr_paths.TILE_SEAM_LIMIT, (
        f"a hard seam measured {ratio}, which is not past the limit, so the "
        f"measure would not warn about a texture that does not tile"
    )


def test_the_seam_measure_refuses_a_file_that_is_not_a_png(tmp_path):
    """Not a PNG is an error, not a silent zero."""
    path = tmp_path / "not.png"
    path.write_bytes(b"this is not a png")
    with pytest.raises(ValueError):
        pbr_paths.tile_seam_ratio(path)


def test_the_seam_measure_compares_against_the_largest_features(tmp_path):
    """The baseline is the 95th percentile, not the median.

    A texture's interior is mostly flat with a few large features, so
    its median step and its 95th percentile step are different numbers.
    The seam has to be read against the LARGEST ordinary features: a
    seam no bigger than the biggest stone edge is invisible, and a
    median would call a big seam small whenever the texture is quiet.

    This map has a quiet interior (a step of 2) with three loud
    features (a step of 40), and a seam of 20. Against the median the
    seam is ten times over; against the largest features it is half -
    which is the honest answer, because the seam is half the size of
    the features it crosses.
    """
    import struct
    import zlib

    width, height = 32, 32
    rows = bytearray()
    for row in range(height):
        rows += b"\x00"
        for column in range(width):
            value = 100
            if column in (7, 8, 23):
                value = 140
            elif column in (15, 16, width - 1):
                value = 120
            rows += bytes((value, value, value))

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = tmp_path / "features.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )

    ratio = pbr_paths.tile_seam_ratio(path)
    # Against the median (2) the seam would be 10.0; against the
    # largest features (40) it is 0.5.
    assert 0.3 < ratio < 0.8, (
        f"the measure read {ratio}, which is not the ratio against the "
        f"largest features (0.5). It is being compared against the wrong "
        f"baseline."
    )


def test_an_export_does_not_delete_another_sets_files(tmp_path):
    """A destination can hold more than one set.

    The lane has a generated set and a procedural one, and they are
    the same kind of deliverable - so they can be exported side by
    side. The clean-set rule removes what a PREVIOUS export put here
    and this one does not include, and it must not take another set's
    maps with it: the removal is scoped by the set's own file names.
    """
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "out"

    for name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        (source / name).write_bytes(b"png")

    pbr_generate.export_texture_set("Brick", source, destination)
    assert (destination / "T_Brick_BaseColor.png").is_file()

    # A DIFFERENT set, exported into the same directory.
    for name in (
        "T_Cobble_BaseColor.png",
        "T_Cobble_ORM.png",
        "T_Cobble_Normal.png",
    ):
        (source / name).write_bytes(b"png")
    pbr_generate.export_texture_set("Cobble", source, destination)

    assert (destination / "T_Brick_BaseColor.png").is_file(), (
        "the second export deleted the first set's base colour"
    )
    assert (destination / "T_Cobble_BaseColor.png").is_file()


def test_an_export_does_not_delete_another_sets_extras(tmp_path):
    """The same, for the extras: the reference photos of one set are
    the reference photos of that set, not of the next."""
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "out"

    for name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
    ):
        (source / name).write_bytes(b"png")
    brick_photo = source / "brick_reference.png"
    brick_photo.write_bytes(b"photo")

    pbr_generate.export_texture_set("Brick", source, destination, extras=[brick_photo])
    assert (destination / "brick_reference.png").is_file()

    for name in (
        "T_Cobble_BaseColor.png",
        "T_Cobble_ORM.png",
        "T_Cobble_Normal.png",
    ):
        (source / name).write_bytes(b"png")
    cobble_photo = source / "cobble_reference.png"
    cobble_photo.write_bytes(b"photo")

    report = pbr_generate.export_texture_set(
        "Cobble", source, destination, extras=[cobble_photo]
    )

    assert (destination / "brick_reference.png").is_file(), (
        "the second export deleted the first set's reference photo"
    )
    assert (destination / "cobble_reference.png").is_file()
    # The cobble set's export removes nothing: the brick's photo is
    # the brick set's, and the cobble's own photo is still wanted.
    assert report["removed"] == []

    # And the BRICK set's export removes the cobble's photo, because
    # that is not the brick set's file either - and the brick's own
    # photo is still wanted, so nothing is removed there either.
    report = pbr_generate.export_texture_set(
        "Brick", source, destination, extras=[brick_photo]
    )
    assert (destination / "cobble_reference.png").is_file(), (
        "the brick set's export deleted the cobble set's reference photo"
    )
    assert report["removed"] == []


def test_the_export_says_which_range_its_height_map_spans(tmp_path):
    """A displacement shader reads the Height map's values as depth, and
    the map's pixels cannot say which range they were written in.

    A layered set writes that beside the map; the export carries it into
    `metadata.json`, so a consumer reads one file and knows its
    displacement scale. A set with a Height but no sidecar (one written
    before the range existed) reports nothing rather than a guess.
    """
    texture_directory = tmp_path / "textures"
    texture_directory.mkdir()
    for file_name in (
        "T_Brick_BaseColor.png",
        "T_Brick_ORM.png",
        "T_Brick_Normal.png",
        "T_Brick_Height.png",
    ):
        (texture_directory / file_name).write_bytes(b"png-bytes")

    destination = tmp_path / "export"
    report = pbr_generate.export_texture_set("Brick", texture_directory, destination)
    metadata = json.loads((destination / "metadata.json").read_text())
    assert "height" not in metadata, (
        "a set with no height sidecar must not report a range it cannot know"
    )

    # Now the set says its range, as a layered set writes it.
    described = {
        "map": "T_Brick_Height.png",
        "range": [0.205, 0.830],
        "kind": "brick",
        "is_measured": True,
        "source": "the median of brick's own truths",
    }
    (texture_directory / "T_Brick_Height.json").write_text(json.dumps(described))

    report = pbr_generate.export_texture_set("Brick", texture_directory, destination)
    assert report["height"] == described
    metadata = json.loads((destination / "metadata.json").read_text())
    assert metadata["height"] == described
    assert metadata["height"]["range"] == [0.205, 0.830]
    assert (destination / "T_Brick_Height.json").is_file()


def test_the_height_sidecar_is_a_layered_sets_own_file(tmp_path):
    """The sidecar is named for the set, so a re-export that stops having
    one removes it - and never touches another set's."""
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "out"
    for name in ("T_Brick_BaseColor.png", "T_Brick_ORM.png", "T_Brick_Normal.png"):
        (source / name).write_bytes(b"png")
    (source / "T_Brick_Height.png").write_bytes(b"png")
    (source / "T_Brick_Height.json").write_text(json.dumps({"range": [0.1, 0.9]}))

    pbr_generate.export_texture_set("Brick", source, destination)
    assert (destination / "T_Brick_Height.json").is_file()

    # The set is regenerated WITHOUT a height: the stale pair goes.
    (source / "T_Brick_Height.png").unlink()
    (source / "T_Brick_Height.json").unlink()
    report = pbr_generate.export_texture_set("Brick", source, destination)
    assert not (destination / "T_Brick_Height.json").exists()
    assert not (destination / "T_Brick_Height.png").exists()
    assert sorted(report["removed"]) == ["T_Brick_Height.json", "T_Brick_Height.png"]
