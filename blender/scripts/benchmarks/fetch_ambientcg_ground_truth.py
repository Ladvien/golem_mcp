"""Fetch real PBR sets from ambientcg as GROUND TRUTH for the benchmark.

ambientcg is CC0, and its API gives a ZIP per material with the
maps the lane produces: the albedo, the normal map, and the ORM
(the roughness is often called "Displacement" or is packed as an
ORM, and the roughness is usually "Roughness" or in the ORM).

The benchmark needs, for each material:
  - the three maps, as the ground truth;
  - a TEXT DESCRIPTION of the surface, and ONLY that. The
    description must not leak the ground truth - the point is to
    recreate the material from words.

The description comes from the asset's own TAGS and its display
name, which is what a person would write. The tags are things like
"bricks", "stone", "wood", "tiles" - a surface's MATERIAL, not its
photograph.

The download is a ZIP with every resolution of every map, so this
picks the 1K set - the same size the lane works at.
"""

import json
import os
import pathlib
import subprocess
import zipfile

ROOT = pathlib.Path(
    os.environ.get(
        "GOLEM_BENCH_ROOT",
        "/Users/ladvien/mnt/codex_fs/game_assets/benchmarks/ambientcg",
    )
)
# The KINDS the benchmark fetches and how many of each, and the total.
#
# They are read from the environment so ONE script fetches every
# truth set: the sets differ in the kinds they cover, and a second
# script would be a second copy of the same download logic.
#
# The default is the first set's - the twenty hand-picked materials'
# kinds - and the popular set overrides it with the kinds the
# popular list has and the first two sets do not.
KINDS_OVERRIDE = os.environ.get("GOLEM_BENCH_KINDS", "")
PER_KIND_OVERRIDE = os.environ.get("GOLEM_BENCH_PER_KIND", "")
WANTED_OVERRIDE = os.environ.get("GOLEM_BENCH_WANTED", "")
ROOT.mkdir(parents=True, exist_ok=True)

API = "https://ambientcg.com/api/v2/full_json?type=Material&sort=popular&limit={limit}&include=downloadData"


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


# How many materials of each KIND the benchmark fetches, and how many
# in all.
#
# Three of each and twenty in all was a sample, and a fit against
# twenty materials is a fit against twenty materials - the palette's
# tables and the pattern's scales are all fitted to the truths they
# are measured against, and a small sample overfits.
#
# So the sample is wider: eight of each kind and seventy in all, over
# fifteen kinds.
PER_KIND = int(PER_KIND_OVERRIDE) if PER_KIND_OVERRIDE else 8
WANTED = int(WANTED_OVERRIDE) if WANTED_OVERRIDE else 70
# The KINDS the benchmark fetches, and the words that name each.
#
# The popular list is all bricks, so the kinds are chosen to cover
# the surfaces the lane claims to make - and the more kinds there are,
# the less any one of them can be fitted to.
KINDS = (
    tuple(
        kind.strip()
        for kind in KINDS_OVERRIDE.split(",")
        if kind.strip()
    )
    if KINDS_OVERRIDE
    else (
        "brick",
        "wood",
        "tiles",
        "metal",
        "ground",
        "rock",
        "fabric",
        "concrete",
        "plaster",
        "gravel",
        "sand",
        "asphalt",
        "leather",
        "carpet",
        "roof",
        "wallpaper",
    )
)


def main():
    wanted = WANTED
    data = fetch_json(API.format(limit=400))
    assets = data["foundAssets"]
    print(f"BENCH the API offers {data['numberOfResults']} materials")

    # A DIVERSE set: the popular list is all bricks, and a benchmark
    # of one material measures one material. So the materials are
    # chosen to cover the kinds of surface the lane claims to make -
    # stone, wood, tiles, metal, ground, fabric - and the popularity
    # order breaks the ties inside each kind.
    chosen = []
    seen_kinds = {}
    for asset in assets:
        url = zip_url(asset)
        if url is None:
            continue
        tags = [tag.lower() for tag in (asset.get("tags") or [])]
        kind = next(
            (candidate for candidate in KINDS if any(candidate in tag for tag in tags)),
            "",
        )
        if not kind:
            continue
        count = seen_kinds.get(kind, 0)
        if count >= PER_KIND:
            continue
        seen_kinds[kind] = count + 1
        chosen.append((asset, url))
        if len(chosen) >= wanted:
            break
    print(f"BENCH the kinds are {sorted(seen_kinds)}")

    manifest = []
    for asset, url in chosen:
        asset_id = asset["assetId"]
        directory = ROOT / asset_id
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / "source.zip"
        if not archive.exists():
            print(f"BENCH fetching {asset_id}")
            download(url, archive)
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            picked = {}
            for name in names:
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
                with zipped.open(name) as source:
                    (directory / f"{key}{pathlib.Path(name).suffix}").write_bytes(
                        source.read()
                    )
        print(
            f"BENCH {asset_id:24s} the maps are {sorted(picked)}  "
            f"the tags are {asset.get('tags')}"
        )
        manifest.append(
            {
                "asset_id": asset_id,
                "display_name": asset.get("displayName", asset_id),
                "tags": asset.get("tags", []),
                "maps": sorted(picked),
                "directory": str(directory),
            }
        )

    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"BENCH the manifest holds {len(manifest)} materials")
    print(f"BENCH the manifest holds {len(manifest)} materials")


main()
print("DONE")
