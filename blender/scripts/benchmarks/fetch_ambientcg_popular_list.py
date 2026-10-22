"""Fetch the POPULAR LIST from ambientcg as GROUND TRUTH.

The other sets pick their materials by KIND - eight of each kind, so
that no kind can be fitted to. That is the right shape for fitting
the palette's tables, and the wrong shape for asking "how good is
this lane on what people actually download".

So this one takes the site's own popular list: the materials with
the most downloads, in the site's own order.

The site's `sort=popular` on the API sorts by RELEASE DATE and not
by downloads, so the list is built here: the API is asked for a wide
page of materials and they are sorted by `downloadCount` themselves.

The download is the 1K-JPG zip, and it is the same one the other
sets use, so the truths are measured the same way.
"""

import json
import os
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        str(pathlib.Path.home() / "mnt/codex_fs/game_assets/benchmarks/ambientcg_top"),
    )
)
# How many of the popular list to fetch.
WANTED = int(os.environ.get("GOLEM_BENCH_WANTED", "60"))
# How many the API is asked for, and it is more than the wanted
# because the list is sorted AFTER the fetch.
PAGE = max(WANTED * 4, 240)

API = (
    "https://ambientcg.com/api/v2/full_json?type=Material&limit={limit}"
    "&include=downloadData,displayData,tagData"
)

ROOT.mkdir(parents=True, exist_ok=True)


def fetch_json(url):
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "120", url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"the fetch of {url} failed: {result.stderr[:200]}")
    return json.loads(result.stdout)


def zip_url(asset):
    """The 1K-JPG zip, and the same one the other sets take."""
    for folder in (asset.get("downloadFolders") or {}).values():
        for category in (folder.get("downloadFiletypeCategories") or {}).values():
            for download in category.get("downloads") or []:
                path = download.get("fullDownloadPath", "")
                if path.endswith("_1K-JPG.zip"):
                    return path
    return None


def download(url, target):
    # curl, not urllib: this machine's Python has no CA bundle, and
    # curl does.
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "600", "-o", str(target), url],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"the download of {url} failed: {result.stderr[:200]}")


def _extract(archive: pathlib.Path, directory: pathlib.Path) -> None:
    """Unpack an archive, and unpack it PROPERLY.

    Python's `extractall` writes the Mac's AppleDouble sidecar
    files beside every member when the filesystem is a network one -
    and the sidecar then SHADOWS the real file, so the map reads as
    an unreadable AppleDouble stub and Blender will not load it.

    So the archive is unpacked with the `unzip` binary and
    COPYFILE_DISABLE set, which is what stops the sidecars.
    """
    environment = dict(os.environ)
    environment["COPYFILE_DISABLE"] = "1"
    result = subprocess.run(
        ["unzip", "-o", "-q", str(archive), "-d", str(directory)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(f"the unpack of {archive} failed: {result.stderr[:200]}")
    for sidecar in directory.rglob("._*"):
        sidecar.unlink(missing_ok=True)


def main():
    print(f"FETCH the popular list of {WANTED} materials")
    payload = fetch_json(API.format(limit=PAGE))
    assets = payload.get("foundAssets") or []
    print(f"FETCH the API answered with {len(assets)} materials")
    # The popular list is the site's own, and the site sorts by
    # DOWNLOADS - the API's own `sort=popular` sorts by release date.
    ranked = sorted(
        assets,
        key=lambda asset: (-int(asset.get("downloadCount") or 0), asset["assetId"]),
    )
    manifest = []
    for asset in ranked:
        if len(manifest) >= WANTED:
            break
        asset_id = asset["assetId"]
        directory = ROOT / asset_id
        if not directory.is_dir():
            url = zip_url(asset)
            if not url:
                print(f"SKIP {asset_id}: no 1K-JPG zip")
                continue
            archive = ROOT / f"{asset_id}.zip"
            try:
                download(url, archive)
                directory.mkdir(parents=True, exist_ok=True)
                _extract(archive, directory)
            except (OSError, RuntimeError, zipfile.BadZipFile) as error:
                print(f"SKIP {asset_id}: {error}")
                continue
            finally:
                archive.unlink(missing_ok=True)
        maps = sorted(
            path.stem
            for path in directory.iterdir()
            if path.suffix.lower() in (".jpg", ".png")
        )
        manifest.append(
            {
                "asset_id": asset_id,
                "display_name": asset.get("displayName") or asset_id,
                "download_count": int(asset.get("downloadCount") or 0),
                "popularity_score": float(asset.get("popularityScore") or 0.0),
                "tags": list(asset.get("tags") or []),
                "maps": maps,
                "directory": str(directory),
            }
        )
        print(f"GOT  {asset_id:28s} {manifest[-1]['download_count']:>9} downloads")
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"BENCH the manifest holds {len(manifest)} materials")


main()
print("DONE")
