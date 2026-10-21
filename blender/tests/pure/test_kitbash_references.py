"""Reference-image search, the contact sheet and saving picks, with the network replaced.

The Openverse and Wikimedia fixtures are trimmed live responses (recorded
2026-10-18 for the query "wooden barrel"); Pexels and Brave need API keys this
repo does not hold, so theirs follow the providers' documented response shapes.
"""

import hashlib
import io
import json
from pathlib import Path

import httpx
import pytest
import yaml
from PIL import Image

from golem_blender.kitbash import paths, references

FIXTURES = Path(__file__).parent / "fixtures" / "kitbash"
IMAGE_SIZE_PX = (300, 200)
PEXELS_KEY = "pexels-secret"
BRAVE_KEY = "brave-secret"


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def _png(size=IMAGE_SIZE_PX, color=(200, 50, 50), mode="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, "PNG")
    return buffer.getvalue()


class FakeNetwork:
    """Answers each provider's API with its fixture and every other URL with an image."""

    def __init__(self, image=None, failing=(), bad_thumbnails=()):
        self.image = image if image is not None else _png()
        self.failing = failing
        self.bad_thumbnails = bad_thumbnails
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict) -> bytes:
        self.requests.append((url, headers))
        for source, prefix in (
            ("openverse", "https://api.openverse.org/v1/images/?"),
            ("wikimedia", "https://commons.wikimedia.org/w/api.php?"),
            ("pexels", "https://api.pexels.com/v1/search?"),
            ("brave", "https://api.search.brave.com/res/v1/images/search?"),
        ):
            if url.startswith(prefix):
                if source in self.failing:
                    raise httpx.ReadTimeout("slow")
                return _fixture(source)
        if url in self.bad_thumbnails:
            return b"this is not an image"
        return self.image


@pytest.fixture()
def keyed(tmp_path, monkeypatch):
    """Key files for both keyed sources and a search cache under tmp_path."""
    key_files = {"brave": tmp_path / "brave_key", "pexels": tmp_path / "pexels_key"}
    key_files["brave"].write_text(BRAVE_KEY + "\n")
    key_files["pexels"].write_text(PEXELS_KEY)
    monkeypatch.setattr(paths, "KEY_FILES", key_files)
    monkeypatch.setattr(paths, "SEARCH_CACHE_ROOT", tmp_path / "searches")
    return key_files


# --- normalizers ---------------------------------------------------------------


def test_openverse_fixture_maps_to_items():
    items = references.normalize_openverse(json.loads(_fixture("openverse")))

    assert [item.license for item in items] == ["by", "by-nc-nd", "by-sa"]
    first = items[0]
    assert first.source == "openverse"
    assert first.title == "One Old Wooden Barrel"
    assert first.creator == "dejankrsmanovic"
    assert (
        first.landing_url == "https://www.flickr.com/photos/155403590@N07/43182338615"
    )
    assert (
        first.image_url
        == "https://live.staticflickr.com/1793/43182338615_1e1ea779a9_b.jpg"
    )
    assert first.thumbnail_url.startswith("https://api.openverse.org/v1/images/")
    assert (first.width_px, first.height_px) == (1024, 683)
    assert first.attribution.startswith('"One Old Wooden Barrel" by dejankrsmanovic')


def test_wikimedia_fixture_maps_to_items_in_search_rank_with_markup_stripped():
    items = references.normalize_wikimedia(json.loads(_fixture("wikimedia")))

    assert [item.title for item in items] == [
        "Rutherford Hill Wine Cave-1369",
        "Four wet wooden barrels",
        "Castello d Volognano - Antichi attrezzi e botti per cantina 1",
    ]
    assert [item.license for item in items] == ["by-sa", "cc0", "by"]
    assert items[0].creator == "Frank Schulenburg"
    assert items[0].license_url == "https://creativecommons.org/licenses/by-sa/4.0"
    assert (
        items[0].attribution
        == "Rutherford Hill Wine Cave-1369 by Frank Schulenburg, CC BY-SA 4.0"
    )
    assert items[0].landing_url.startswith("https://commons.wikimedia.org/wiki/File:")
    assert items[0].image_url.startswith("https://upload.wikimedia.org/")
    assert items[0].thumbnail_url.startswith("https://thumb.wikimedia.org/")
    assert (items[0].width_px, items[0].height_px) == (3948, 3948)


def test_pexels_fixture_maps_to_items_under_the_pexels_license():
    items = references.normalize_pexels(json.loads(_fixture("pexels")))

    assert {item.license for item in items} == {"pexels"}
    assert items[0].license_url == "https://www.pexels.com/license/"
    assert items[0].attribution == "Photo by Ada Example on Pexels"
    assert (
        items[0].image_url
        == "https://images.pexels.com/photos/4443214/pexels-photo-4443214.jpeg"
    )
    assert "tinysrgb" in items[0].thumbnail_url
    assert items[1].title == ""
    assert (items[1].width_px, items[1].height_px) == (1800, 2700)


def test_brave_fixture_maps_to_items_with_unknown_license_and_skips_results_without_an_image():
    items = references.normalize_brave(json.loads(_fixture("brave")))

    assert [item.title for item in items] == [
        "Old wooden barrel for sale",
        "Whisky cask diagram",
    ]
    assert {item.license for item in items} == {"unknown"}
    assert items[0].image_url == "https://shop.example.com/img/old-oak.jpg"
    assert items[0].landing_url == "https://shop.example.com/barrels/old-oak"
    assert (items[0].width_px, items[0].height_px) == (1200, 900)
    assert (items[1].width_px, items[1].height_px) == (0, 0)
    assert items[0].source_id != items[1].source_id


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        ("by", "by"),
        ("CC BY 4.0", "by"),
        ("CC BY-SA 3.0", "by-sa"),
        ("by-nc", "by-nc"),
        ("CC BY-ND 2.0", "by-nd"),
        ("by-nc-sa", "by-nc-sa"),
        ("CC BY-NC-ND 2.0", "by-nc-nd"),
        ("CC0", "cc0"),
        ("cc0", "cc0"),
        ("CC0 1.0 Universal", "cc0"),
        ("Public domain", "pdm"),
        ("pdm", "pdm"),
        ("publicdomain", "pdm"),
        ("PD-old-70", "unknown"),
        ("GFDL", "unknown"),
        ("sampling+", "unknown"),
        ("by-nd-sa", "unknown"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_license_wording_normalizes_to_one_vocabulary(wording, expected):
    assert references.normalize_license(wording) == expected


# --- search -----------------------------------------------------------------------


def test_search_interleaves_the_sources_and_numbers_from_one(keyed):
    network = FakeNetwork()

    result = references.search_references("wooden barrel", count=12, fetch=network)

    assert [item.source for item in result.items] == (
        ["openverse", "wikimedia", "pexels", "brave"] * 2
        + ["openverse", "wikimedia", "pexels"]
    )
    assert result.skipped_sources == {}
    assert [path.name for path in result.thumbnail_paths] == [
        f"{n}.jpg" for n in range(1, 12)
    ]
    cached = json.loads(
        (paths.SEARCH_CACHE_ROOT / result.search_id / "results.json").read_text()
    )
    assert [entry["n"] for entry in cached["items"]] == list(range(1, 12))
    assert cached["items"][3]["source"] == "brave"
    assert cached["query"] == "wooden barrel"
    assert result.search_id.startswith("wooden_barrel-")


def test_search_asks_each_source_for_its_share_and_sends_the_keys(keyed):
    network = FakeNetwork()

    references.search_references("wooden barrel", count=12, fetch=network)

    api_calls = {
        url.split("/")[2]: (url, headers)
        for url, headers in network.requests
        if "/v1/images/?" in url
        or "w/api.php" in url
        or "v1/search" in url
        or "images/search" in url
    }
    # 12 wanted, doubled, split four ways.
    assert "page_size=6" in api_calls["api.openverse.org"][0]
    assert "gsrlimit=6" in api_calls["commons.wikimedia.org"][0]
    assert "filetype%3Abitmap" in api_calls["commons.wikimedia.org"][0]
    assert api_calls["api.pexels.com"][1] == {"Authorization": PEXELS_KEY}
    assert api_calls["api.search.brave.com"][1] == {"X-Subscription-Token": BRAVE_KEY}


def test_reuse_filter_drops_what_cannot_become_a_mesh(keyed):
    result = references.search_references(
        "wooden barrel", count=12, license_filter="reuse", fetch=FakeNetwork()
    )

    licenses = {item.license for item in result.items}
    assert licenses <= references.REUSABLE_LICENSES
    assert "brave" not in {
        item.source for item in result.items
    }  # its licenses are unknown
    openverse = [item.license for item in result.items if item.source == "openverse"]
    assert openverse == ["by", "by-sa"]  # by-nc-nd is gone


def test_a_missing_key_skips_that_source_with_its_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        paths,
        "KEY_FILES",
        {"brave": tmp_path / "no_brave", "pexels": tmp_path / "empty_pexels"},
    )
    (tmp_path / "empty_pexels").write_text("  \n")
    monkeypatch.setattr(paths, "SEARCH_CACHE_ROOT", tmp_path / "searches")

    result = references.search_references("wooden barrel", count=6, fetch=FakeNetwork())

    assert result.skipped_sources == {
        "brave": f"no key at {tmp_path / 'no_brave'}",
        "pexels": f"no key at {tmp_path / 'empty_pexels'}",
    }
    assert {item.source for item in result.items} == {"openverse", "wikimedia"}


def test_a_failing_source_is_skipped_not_raised(keyed):
    result = references.search_references(
        "wooden barrel", count=6, fetch=FakeNetwork(failing=("wikimedia",))
    )

    assert result.skipped_sources == {"wikimedia": "ReadTimeout: slow"}
    assert "wikimedia" not in {item.source for item in result.items}
    assert result.items


def test_a_source_that_answers_with_something_else_is_skipped(keyed):
    def fetch(url, headers):
        return (
            b"<html>captcha</html>"
            if "openverse" in url
            else FakeNetwork()(url, headers)
        )

    result = references.search_references("wooden barrel", count=6, fetch=fetch)

    assert result.skipped_sources["openverse"].startswith("JSONDecodeError")


def test_an_item_whose_thumbnail_does_not_decode_is_dropped_and_numbering_stays_contiguous(
    keyed,
):
    openverse = references.normalize_openverse(json.loads(_fixture("openverse")))
    network = FakeNetwork(bad_thumbnails=(openverse[0].thumbnail_url,))

    result = references.search_references(
        "wooden barrel", sources=("openverse",), count=3, fetch=network
    )

    assert [item.title for item in result.items] == [
        openverse[1].title,
        openverse[2].title,
    ]
    assert len(result.items) == 2
    assert [path.name for path in result.thumbnail_paths] == ["1.jpg", "2.jpg"]


def test_search_rejects_arguments_it_cannot_honor(keyed):
    for bad in (
        {"query": " "},
        {"query": "x", "count": 0},
        {"query": "x", "count": 37},
        {"query": "x", "license_filter": "some"},
        {"query": "x", "sources": ("bing",)},
    ):
        with pytest.raises(ValueError):
            references.search_references(fetch=FakeNetwork(), **bad)


# --- contact sheet -------------------------------------------------------------------


def _thumbnail_files(tmp_path, count):
    thumbnails = []
    for index in range(count):
        path = tmp_path / f"{index + 1}.jpg"
        Image.new("RGB", (256, 171), (30 * index, 90, 160)).save(path, "JPEG")
        thumbnails.append(path)
    return thumbnails


def test_seven_thumbnails_make_a_six_column_two_row_sheet(tmp_path):
    sheet = Image.open(
        io.BytesIO(references.contact_sheet(_thumbnail_files(tmp_path, 7)))
    )

    assert sheet.format == "JPEG"
    assert sheet.size == (6 * 256, 2 * 256)


def test_each_tile_carries_its_own_number_in_a_white_box(tmp_path):
    sheet = Image.open(
        io.BytesIO(references.contact_sheet(_thumbnail_files(tmp_path, 7)))
    ).convert("RGB")
    box_width, box_height = references.LABEL_BOX_PX

    def label(tile_index):
        left, top = (tile_index % 6) * 256, (tile_index // 6) * 256
        return sheet.crop((left, top, left + box_width, top + box_height))

    # White corner, dark digit strokes, and a different picture for tile 7 than tile 1.
    assert min(label(0).convert("L").tobytes()) < 80
    assert label(0).getpixel((box_width - 2, 1))[0] > 230
    assert label(0).tobytes() != label(6).tobytes()
    # The seventh tile starts the second row.
    assert sheet.getpixel((5, 256 + 5))[0] > 230


def test_a_sheet_of_nothing_is_an_error():
    with pytest.raises(ValueError):
        references.contact_sheet([])


# --- save -----------------------------------------------------------------------------


@pytest.fixture()
def codex(tmp_path, monkeypatch):
    """A codex_fs mounted at tmp_path/codex, which big sees as /mnt/fake_codex."""
    root = tmp_path / "codex"
    (root / "game_assets").mkdir(parents=True)
    monkeypatch.setattr(paths, "CODEX_ROOT_MAC", root)
    monkeypatch.setattr(paths, "CODEX_ROOT_ON_BIG", "/mnt/fake_codex")
    return root / "game_assets" / "references"


def _searched(keyed, network=None):
    return references.search_references(
        "wooden barrel", count=6, fetch=network or FakeNetwork()
    )


def test_saving_writes_the_png_and_a_log_whose_hash_matches_the_file(keyed, codex):
    search = _searched(keyed)

    saved = references.save_references(
        search.search_id,
        [1, 2],
        "barrel_kit",
        fetch=FakeNetwork(),
        reference_root=codex,
    )

    assert len(saved) == 2
    for entry in saved:
        image_path = Path(entry.mac_path)
        assert image_path.parent == codex / "barrel_kit"
        assert image_path.suffix == ".png"
        assert hashlib.sha256(image_path.read_bytes()).hexdigest() == entry.sha256
        assert (
            entry.big_path
            == f"/mnt/fake_codex/game_assets/references/barrel_kit/{image_path.name}"
        )
        assert (entry.width_px, entry.height_px) == IMAGE_SIZE_PX
        assert (
            entry.too_small_for_shape is True
        )  # 300 px is under the 512 px shape threshold
    assert saved[0].id.startswith("openverse_") and saved[1].id.startswith("wikimedia_")
    log = yaml.safe_load((codex / "barrel_kit" / "references.yaml").read_text())
    assert [entry["id"] for entry in log] == [entry.id for entry in saved]
    assert log[0]["query"] == "wooden barrel"
    assert log[0]["search_id"] == search.search_id
    assert (log[0]["number"], log[1]["number"]) == (1, 2)
    assert log[0]["license"] == "by" and log[0]["creator"] == "dejankrsmanovic"
    assert log[0]["landing_url"].startswith("https://www.flickr.com/")


def test_saving_the_same_number_twice_adds_no_file_and_no_log_entry(keyed, codex):
    search = _searched(keyed)
    first = references.save_references(
        search.search_id, [1], "barrel_kit", fetch=FakeNetwork(), reference_root=codex
    )[0]

    again = references.save_references(
        search.search_id, [1], "barrel_kit", fetch=FakeNetwork(), reference_root=codex
    )

    assert len(list((codex / "barrel_kit").glob("*.png"))) == 1
    assert (
        len(yaml.safe_load((codex / "barrel_kit" / "references.yaml").read_text())) == 1
    )
    assert again == [first]


def test_a_picture_that_changed_since_it_was_saved_gets_a_numbered_name(keyed, codex):
    search = _searched(keyed)
    first = references.save_references(
        search.search_id, [1], "barrel_kit", fetch=FakeNetwork(), reference_root=codex
    )[0]

    second = references.save_references(
        search.search_id,
        [1],
        "barrel_kit",
        fetch=FakeNetwork(image=_png(color=(10, 200, 10))),
        reference_root=codex,
    )[0]

    assert second.id == f"{first.id}_2"
    assert second.sha256 != first.sha256
    assert len(list((codex / "barrel_kit").glob("*.png"))) == 2


def test_a_picture_with_transparency_is_saved_with_its_alpha(keyed, codex):
    search = _searched(keyed)
    network = FakeNetwork(image=_png(color=(255, 0, 0, 80), mode="RGBA"))

    saved = references.save_references(
        search.search_id, [1], "barrel_kit", fetch=network, reference_root=codex
    )[0]

    assert Image.open(saved.mac_path).mode == "RGBA"


def test_a_large_picture_is_not_flagged_too_small(keyed, codex):
    search = _searched(keyed)

    saved = references.save_references(
        search.search_id,
        [1],
        "barrel_kit",
        fetch=FakeNetwork(image=_png((1024, 600))),
        reference_root=codex,
    )[0]

    assert saved.too_small_for_shape is False


def test_save_refuses_what_it_cannot_do(keyed, codex, tmp_path):
    search = _searched(keyed)
    network = FakeNetwork()

    with pytest.raises(ValueError, match=r"1\.\.6"):
        references.save_references(
            search.search_id, [7], "barrel_kit", fetch=network, reference_root=codex
        )
    with pytest.raises(ValueError, match="kit_slug"):
        references.save_references(
            search.search_id, [1], "Barrel Kit", fetch=network, reference_root=codex
        )
    with pytest.raises(ValueError, match="search_id"):
        references.save_references(
            "../elsewhere", [1], "barrel_kit", fetch=network, reference_root=codex
        )
    with pytest.raises(FileNotFoundError, match="codex_fs is not mounted"):
        references.save_references(
            search.search_id,
            [1],
            "barrel_kit",
            fetch=network,
            reference_root=tmp_path / "unmounted" / "game_assets" / "references",
        )
    assert not (codex / "barrel_kit").exists()


# --- paths -----------------------------------------------------------------------------


def test_big_path_swaps_the_mount_prefix_and_refuses_files_outside_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(paths, "CODEX_ROOT_MAC", tmp_path / "mnt")
    monkeypatch.setattr(paths, "CODEX_ROOT_ON_BIG", "/mnt/codex_fs/")

    assert paths.big_path(tmp_path / "mnt" / "a" / "b.png") == "/mnt/codex_fs/a/b.png"
    with pytest.raises(ValueError):
        paths.big_path(tmp_path / "elsewhere" / "b.png")
