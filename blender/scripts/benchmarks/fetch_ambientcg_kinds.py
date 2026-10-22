"""Fetch the WIDE set's missing KINDS from ambientcg.

The wide sample's fetcher walks the popular list and takes the first
eight of each kind, and the popular list is all bricks and tiles: so
in sixteen kinds it found eleven of them, and the missing five -
leather, roof, wallpaper, sand and one more - are the ones the lane
had no pattern for.

That is the wrong order. The kinds the lane has NO PATTERN FOR are
exactly the ones that need measuring, and they are the ones the
popular list never reaches.

So this fetches them DIRECTLY: it asks the API for each kind's own
word, takes the first few of each, and writes them into the same
root with the same maps.

Run it with the system python - it needs only json and zipfile.

    python scripts/benchmarks/fetch_ambientcg_kinds.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import zipfile

DEFAULT_ROOT = pathlib.Path(
    "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg_wide"
)

# The KINDS the lane has no pattern for, and the word that names each
# in ambientcg's own tags.
#
# The wide sample's fetcher walks the POPULAR list, and the popular
# list is all bricks - so the kinds the lane needs measured are the
# ones the popular list never reaches.
KINDS = (
    ("leather", 6),
    ("roof", 6),
    ("wallpaper", 4),
    ("carpet", 4),
    ("shingle", 4),
    ("parquet", 4),
    ("planks", 4),
)

# How many to ask the API for.
LIMIT = 400


def fetch_json(url: str):
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "120", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"the fetch of {url} failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


def zip_url(asset: dict) -> str | None:
    """The 1K archive's URL, and the maps the benchmark needs."""
    for folder in (asset.get("downloadFolders") or {}).values():
        for category in (folder.get("downloadFiletypeCategories") or {}).values():
            for download in category.get("downloads") or []:
                path = download.get("fullDownloadPath", "")
                if path.endswith("_1K-JPG.zip"):
                    return path
    return None


def download(url: str, target: pathlib.Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "600", "-o", str(target), url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"the download of {url} failed: {result.stderr[:200]}")


def extract(directory: pathlib.Path, archive: pathlib.Path) -> list[str]:
    """The maps out of the archive, and their names."""
    picked: dict[str, str] = {}
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            if "_1K-JPG" not in name:
                continue
            if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            lowered = name.lower()
            for key, marker in (
                ("albedo", "_color"),
                ("normal_gl", "_normalgl"),
                ("normal_dx", "_normaldx"),
                ("roughness", "_roughness"),
                ("displacement", "_displacement"),
                ("ambient_occlusion", "_ambientocclusion"),
            ):
                if marker in lowered and key not in picked:
                    picked[key] = name
    for key, name in picked.items():
        with zipfile.ZipFile(archive) as zipped, zipped.open(name) as source:
            (directory / f"{key}{pathlib.Path(name).suffix}").write_bytes(source.read())
    return sorted(picked)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=pathlib.Path, default=DEFAULT_ROOT)
    arguments = parser.parse_args()
    root = arguments.root
    root.mkdir(parents=True, exist_ok=True)

    data = fetch_json(
        "https://ambientcg.com/api/v2/full_json?type=Material"
        f"&sort=popular&limit={LIMIT}&include=downloadData"
    )
    assets = data["foundAssets"]
    print(f"KINDS the API offers {data['numberOfResults']} materials")

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    known = {entry["asset_id"] for entry in manifest}

    for kind, wanted in KINDS:
        taken = 0
        for asset in assets:
            if taken >= wanted:
                break
            url = zip_url(asset)
            if url is None:
                continue
            tags = [tag.lower() for tag in (asset.get("tags") or [])]
            if not any(kind in tag for tag in tags):
                continue
            asset_id = asset["assetId"]
            if asset_id in known:
                taken += 1
                continue
            directory = root / asset_id
            directory.mkdir(parents=True, exist_ok=True)
            archive = directory / "source.zip"
            if not archive.exists():
                download(url, archive)
            maps = extract(directory, archive)
            manifest.append(
                {
                    "asset_id": asset_id,
                    "display_name": asset.get("displayName", asset_id),
                    "tags": asset.get("tags") or [],
                    "maps": maps,
                    "directory": str(directory),
                }
            )
            known.add(asset_id)
            taken += 1
            print(f"KINDS {asset_id:24s} the kind is {kind}  the maps are {maps}")

    manifest_path.write_text(json.dumps(manifest, indent=1))
    print(f"KINDS the manifest now holds {len(manifest)} materials")


if __name__ == "__main__":
    main()
