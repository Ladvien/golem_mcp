"""The PBR texture lane's pure layer: paths, conventions, portability.

Pure: no Blender, no network. What it proves is the part that is
cheap to get wrong and expensive to discover late — the file names, the
channel packing, the Mac<->big path swap, and the promise that nothing
in the new code names a machine.
"""

from __future__ import annotations

import json
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
