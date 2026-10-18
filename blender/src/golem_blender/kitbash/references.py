"""Reference images from the internet: search four sources, show a numbered sheet, save the picks.

The flow the kitbash procedure drives:

    search_references  -> thumbnails + results.json under SEARCH_CACHE_ROOT
    contact_sheet      -> one numbered JPEG the user looks at
    save_references    -> the picked originals as PNGs under the kit's
                          reference folder on codex_fs, with provenance

Each source has a pure normalizer (payload dict -> list[ReferenceItem]) so the
shapes are testable from recorded JSON; the network sits behind an injected
`fetch(url, headers) -> bytes`.

Licenses are normalized to one vocabulary. NC and ND are not reusable here:
turning a picture into a mesh is a derivative work.

Pillow is imported where it is used, so the normalizers work without it.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import functools
import hashlib
import io
import itertools
import json
import math
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from golem_blender.kitbash import paths

# What a source's request can raise: the network, a body that is not JSON, or a
# payload whose shape no longer matches its normalizer. Each skips that source.
SOURCE_FAILURES = (OSError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError)

ALL_SOURCES = ("openverse", "wikimedia", "brave", "pexels")
# Round-robin order when results are merged.
MERGE_ORDER = ("openverse", "wikimedia", "pexels", "brave")
LICENSES = (
    "cc0",
    "pdm",
    "by",
    "by-sa",
    "by-nc",
    "by-nd",
    "by-nc-sa",
    "by-nc-nd",
    "pexels",
    "unknown",
)
REUSABLE_LICENSES = frozenset({"cc0", "pdm", "by", "by-sa", "pexels"})
LICENSE_FILTERS = ("any", "reuse")

MINIMUM_COUNT = 1
MAXIMUM_COUNT = 36
OVER_FETCH_FACTOR = 2
# The most each API returns per request.
MAXIMUM_PER_SOURCE = {"openverse": 20, "wikimedia": 50, "pexels": 80, "brave": 100}
REQUEST_TIMEOUT_S = 15.0
# Openverse answers an image search 11-15 s after the request (measured
# 2026-10-18, page sizes 5-20, with and without filter_dead).
SEARCH_TIMEOUT_S = 45.0
USER_AGENT = "golem/0.1 (https://github.com/Ladvien/golem_mcp)"
PEXELS_LICENSE_URL = "https://www.pexels.com/license/"

TILE_PX = 256
SHEET_COLUMNS = 6
LABEL_BOX_PX = (40, 24)
LABEL_FONT_PX = 18
TILE_BACKGROUND_RGB = (128, 128, 128)
SHEET_JPEG_QUALITY = 85
THUMBNAIL_WORKERS = 8
# Below this long edge a picture is too small to give a mesh its shape.
MINIMUM_SHAPE_LONG_EDGE_PX = 512

KIT_SLUG_PATTERN = re.compile(r"[a-z0-9_]+")
SEARCH_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
MAXIMUM_SOURCE_ID_CHARACTERS = 40


@dataclass(frozen=True)
class ReferenceItem:
    source: str
    source_id: str
    title: str
    creator: str
    license: str  # one of LICENSES
    license_url: str
    attribution: str
    landing_url: str
    image_url: str  # full size
    thumbnail_url: str
    width_px: int  # 0 when the source does not say
    height_px: int


@dataclass(frozen=True)
class SearchResult:
    search_id: str
    query: str
    license_filter: str
    items: tuple[ReferenceItem, ...]  # item i is number i + 1
    thumbnail_paths: tuple[Path, ...]
    skipped_sources: dict[str, str]


@dataclass(frozen=True)
class SavedReference:
    id: str  # the file stem
    query: str
    search_id: str
    number: int
    sha256: str
    mac_path: str
    big_path: str
    width_px: int  # of the saved file
    height_px: int
    too_small_for_shape: bool
    saved: str  # ISO date
    source: str
    source_id: str
    title: str
    creator: str
    license: str
    license_url: str
    attribution: str
    landing_url: str
    image_url: str
    thumbnail_url: str


def slugify(text: str, limit: int = 50) -> str:
    """The naming used across models/ and game_assets/generated/ (golem_mcp.server._slugify)."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:limit].rstrip("_") or "asset"


# --- license ------------------------------------------------------------


def normalize_license(text: str | None) -> str:
    """A source's license wording as one of LICENSES; anything unrecognized is "unknown".

    Reads both Openverse slugs ("by-nc-sa") and Commons short names
    ("CC BY-SA 4.0", "CC0", "Public domain").
    """
    lowered = (text or "").strip().lower()
    if lowered.startswith("public domain") or lowered in ("pdm", "publicdomain"):
        return "pdm"
    tokens = re.findall(r"[a-z0-9]+", lowered)
    if tokens and tokens[0] == "cc":
        tokens = tokens[1:]
    if not tokens:
        return "unknown"
    if tokens[0] == "cc0":
        return "cc0"
    if tokens[0] != "by":
        return "unknown"
    restrictions = set(tokens[1:]) & {"nc", "nd", "sa"}
    canonical = "by" + "".join(
        f"-{restriction}" for restriction in ("nc", "nd", "sa") if restriction in restrictions
    )
    return canonical if canonical in LICENSES else "unknown"


# --- normalizers: payload -> items -----------------------------------------


def _text(value) -> str:
    return "" if value is None else str(value)


def _pixels(value) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _strip_html(markup) -> str:
    import html

    return html.unescape(re.sub("<[^>]+>", "", _text(markup))).strip()


def normalize_openverse(payload: dict) -> list[ReferenceItem]:
    items = []
    for result in payload["results"]:
        if not result.get("url"):
            continue
        items.append(
            ReferenceItem(
                source="openverse",
                source_id=_text(result["id"]),
                title=_text(result.get("title")),
                creator=_text(result.get("creator")),
                license=normalize_license(result.get("license")),
                license_url=_text(result.get("license_url")),
                attribution=_text(result.get("attribution")),
                landing_url=_text(result.get("foreign_landing_url")),
                image_url=result["url"],
                thumbnail_url=_text(result.get("thumbnail")) or result["url"],
                width_px=_pixels(result.get("width")),
                height_px=_pixels(result.get("height")),
            )
        )
    return items


def _metadata_text(metadata: dict, name: str) -> str:
    """A Commons extmetadata value with its markup stripped."""
    return _strip_html(metadata.get(name, {}).get("value"))


def normalize_wikimedia(payload: dict) -> list[ReferenceItem]:
    pages = payload.get("query", {}).get("pages", [])
    if isinstance(pages, dict):  # formatversion 1 keys pages by page id
        pages = list(pages.values())
    items = []
    for page in sorted(pages, key=lambda candidate: candidate.get("index", 0)):
        image_info = (page.get("imageinfo") or [None])[0]
        if not image_info or not image_info.get("url"):
            continue
        metadata = image_info.get("extmetadata", {})
        short_name = _metadata_text(metadata, "LicenseShortName")
        title = _metadata_text(metadata, "ObjectName") or re.sub(
            r"^File:", "", _text(page.get("title"))
        )
        creator = _metadata_text(metadata, "Artist")
        attribution = ", ".join(part for part in (f"{title} by {creator}" if creator else title, short_name) if part)
        items.append(
            ReferenceItem(
                source="wikimedia",
                source_id=_text(page.get("pageid")),
                title=title,
                creator=creator,
                license=normalize_license(short_name),
                license_url=_metadata_text(metadata, "LicenseUrl"),
                attribution=attribution,
                landing_url=_text(image_info.get("descriptionurl")),
                image_url=image_info["url"],
                thumbnail_url=_text(image_info.get("thumburl")) or image_info["url"],
                width_px=_pixels(image_info.get("width")),
                height_px=_pixels(image_info.get("height")),
            )
        )
    return items


def normalize_pexels(payload: dict) -> list[ReferenceItem]:
    items = []
    for photo in payload["photos"]:
        source_urls = photo.get("src", {})
        if not source_urls.get("original"):
            continue
        photographer = _text(photo.get("photographer"))
        items.append(
            ReferenceItem(
                source="pexels",
                source_id=_text(photo["id"]),
                title=_text(photo.get("alt")),
                creator=photographer,
                license="pexels",
                license_url=PEXELS_LICENSE_URL,
                attribution=f"Photo by {photographer} on Pexels",
                landing_url=_text(photo.get("url")),
                image_url=source_urls["original"],
                thumbnail_url=_text(source_urls.get("medium")) or source_urls["original"],
                width_px=_pixels(photo.get("width")),
                height_px=_pixels(photo.get("height")),
            )
        )
    return items


def normalize_brave(payload: dict) -> list[ReferenceItem]:
    items = []
    for result in payload["results"]:
        properties = result.get("properties") or {}
        image_url = properties.get("url")
        if not image_url:
            continue
        items.append(
            ReferenceItem(
                source="brave",
                # Brave gives no id; the image address is the identity.
                source_id=hashlib.sha1(image_url.encode("utf-8")).hexdigest()[:12],
                title=_text(result.get("title")),
                creator=_text(result.get("source")),
                license="unknown",
                license_url="",
                attribution="",
                landing_url=_text(result.get("url")),
                image_url=image_url,
                thumbnail_url=_text((result.get("thumbnail") or {}).get("src")) or image_url,
                width_px=_pixels(properties.get("width")),
                height_px=_pixels(properties.get("height")),
            )
        )
    return items


NORMALIZERS: dict[str, Callable[[dict], list[ReferenceItem]]] = {
    "openverse": normalize_openverse,
    "wikimedia": normalize_wikimedia,
    "pexels": normalize_pexels,
    "brave": normalize_brave,
}


# --- network ------------------------------------------------------------------


def _http_get(url: str, headers: dict, timeout_s: float = REQUEST_TIMEOUT_S) -> bytes:
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, **headers},
        timeout=timeout_s,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def _search_request(source: str, query: str, per_source: int, key: str) -> tuple[str, dict]:
    """The URL and headers of one source's search call."""
    if source == "openverse":
        parameters = {"q": query, "page_size": per_source, "filter_dead": "true"}
        return "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(parameters), {}
    if source == "wikimedia":
        parameters = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrlimit": per_source,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "iiurlwidth": 400,
        }
        return "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(parameters), {}
    if source == "pexels":
        parameters = {"query": query, "per_page": per_source}
        return "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(parameters), {
            "Authorization": key
        }
    if source == "brave":
        parameters = {"q": query, "count": per_source, "safesearch": "strict"}
        return "https://api.search.brave.com/res/v1/images/search?" + urllib.parse.urlencode(
            parameters
        ), {"X-Subscription-Token": key}
    raise ValueError(f"unknown source {source!r}; sources are {ALL_SOURCES}")


def _read_key(source: str) -> str | None:
    """The API key for a source that needs one; None when its file is missing or empty."""
    key_file = paths.KEY_FILES[source]
    if not key_file.is_file():
        return None
    return key_file.read_text(encoding="utf-8").strip() or None


# --- images ---------------------------------------------------------------------


def _flatten_to_rgb(image):
    """RGB from any mode; transparency is composited onto white, not black."""
    from PIL import Image

    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        backdrop = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(backdrop, rgba).convert("RGB")
    return image.convert("RGB")


def _thumbnail_jpeg(data: bytes) -> bytes | None:
    """The bytes as a JPEG no larger than a contact-sheet tile; None when they do not decode."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            flattened = _flatten_to_rgb(image)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None
    flattened.thumbnail((TILE_PX, TILE_PX))
    buffer = io.BytesIO()
    flattened.save(buffer, "JPEG", quality=SHEET_JPEG_QUALITY)
    return buffer.getvalue()


def _fetch_thumbnail(item: ReferenceItem, fetch: Callable[[str, dict], bytes]) -> bytes | None:
    try:
        data = fetch(item.thumbnail_url, {})
    except (OSError, httpx.HTTPError):
        return None
    return _thumbnail_jpeg(data)


def contact_sheet(thumbnail_paths: list[Path]) -> bytes:
    """JPEG bytes of the thumbnails in a numbered grid: 6 columns, tiles of TILE_PX, number at top left."""
    from PIL import Image, ImageDraw, ImageFont

    if not thumbnail_paths:
        raise ValueError("a contact sheet needs at least one thumbnail")
    rows = math.ceil(len(thumbnail_paths) / SHEET_COLUMNS)
    sheet = Image.new("RGB", (SHEET_COLUMNS * TILE_PX, rows * TILE_PX), TILE_BACKGROUND_RGB)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=LABEL_FONT_PX)
    for index, thumbnail_path in enumerate(thumbnail_paths):
        column, row = index % SHEET_COLUMNS, index // SHEET_COLUMNS
        left, top = column * TILE_PX, row * TILE_PX
        with Image.open(thumbnail_path) as thumbnail:
            tile = _flatten_to_rgb(thumbnail)
        tile.thumbnail((TILE_PX, TILE_PX))
        sheet.paste(tile, (left + (TILE_PX - tile.width) // 2, top + (TILE_PX - tile.height) // 2))
        draw.rectangle(
            (left, top, left + LABEL_BOX_PX[0] - 1, top + LABEL_BOX_PX[1] - 1),
            fill=(255, 255, 255),
        )
        draw.text((left + 4, top + 2), str(index + 1), fill=(0, 0, 0), font=font)
    buffer = io.BytesIO()
    sheet.save(buffer, "JPEG", quality=SHEET_JPEG_QUALITY)
    return buffer.getvalue()


# --- search --------------------------------------------------------------------------


def search_references(
    query: str,
    sources: tuple[str, ...] = (),
    count: int = 24,
    license_filter: str = "any",
    fetch: Callable[[str, dict], bytes] | None = None,
) -> SearchResult:
    """Search the sources, merge, keep `count` items that have a thumbnail, and cache them as a numbered search.

    A source without a key, or whose request fails, is reported in
    `skipped_sources` and never raises. `fetch` replaces the network for both
    the search calls and the thumbnails; by default the search calls wait up
    to SEARCH_TIMEOUT_S (Openverse measured 11-15 s to first byte) and the
    thumbnails REQUEST_TIMEOUT_S.
    """
    fetch_page = fetch or functools.partial(_http_get, timeout_s=SEARCH_TIMEOUT_S)
    fetch_image = fetch or _http_get
    if not query.strip():
        raise ValueError("query must not be empty")
    if not MINIMUM_COUNT <= count <= MAXIMUM_COUNT:
        raise ValueError(f"count must be {MINIMUM_COUNT}..{MAXIMUM_COUNT}, got {count}")
    if license_filter not in LICENSE_FILTERS:
        raise ValueError(f"license_filter must be one of {LICENSE_FILTERS}, got {license_filter!r}")
    unknown = [source for source in sources if source not in ALL_SOURCES]
    if unknown:
        raise ValueError(f"unknown sources {unknown}; sources are {ALL_SOURCES}")
    requested = [source for source in MERGE_ORDER if not sources or source in sources]

    skipped_sources: dict[str, str] = {}
    keys: dict[str, str] = {}
    enabled = []
    for source in requested:
        if source in paths.KEY_FILES:
            key = _read_key(source)
            if key is None:
                skipped_sources[source] = f"no key at {paths.KEY_FILES[source]}"
                continue
            keys[source] = key
        enabled.append(source)

    def ask(source: str) -> tuple[list[ReferenceItem] | None, str]:
        per_source = min(
            math.ceil(count * OVER_FETCH_FACTOR / len(enabled)), MAXIMUM_PER_SOURCE[source]
        )
        try:
            url, headers = _search_request(source, query, per_source, keys.get(source, ""))
            return NORMALIZERS[source](json.loads(fetch_page(url, headers))), ""
        except SOURCE_FAILURES as error:
            return None, f"{type(error).__name__}: {error}"

    kept: list[tuple[ReferenceItem, bytes]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=THUMBNAIL_WORKERS) as pool:
        per_source_lists: list[list[ReferenceItem]] = []
        for source, (found, failure) in zip(enabled, pool.map(ask, enabled)):
            if found is None:
                skipped_sources[source] = failure
                continue
            if license_filter == "reuse":
                found = [item for item in found if item.license in REUSABLE_LICENSES]
            per_source_lists.append(found)

        candidates: list[ReferenceItem] = []
        seen_images: set[str] = set()
        for item in itertools.chain.from_iterable(itertools.zip_longest(*per_source_lists)):
            if item is not None and item.image_url not in seen_images:
                seen_images.add(item.image_url)
                candidates.append(item)

        position = 0
        while len(kept) < count and position < len(candidates):
            batch = candidates[position : position + (count - len(kept))]
            position += len(batch)
            thumbnails = pool.map(lambda candidate: _fetch_thumbnail(candidate, fetch_image), batch)
            for item, thumbnail in zip(batch, thumbnails):
                if thumbnail is not None:
                    kept.append((item, thumbnail))

    search_id = f"{slugify(query)}-{time.strftime('%Y%m%d-%H%M%S')}"
    search_directory = paths.SEARCH_CACHE_ROOT / search_id
    (search_directory / "thumbs").mkdir(parents=True, exist_ok=True)
    thumbnail_paths = []
    for number, (_, thumbnail) in enumerate(kept, 1):
        thumbnail_path = search_directory / "thumbs" / f"{number}.jpg"
        thumbnail_path.write_bytes(thumbnail)
        thumbnail_paths.append(thumbnail_path)
    items = tuple(item for item, _ in kept)
    (search_directory / "results.json").write_text(
        json.dumps(
            {
                "query": query,
                "license_filter": license_filter,
                "items": [{**asdict(item), "n": number} for number, item in enumerate(items, 1)],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return SearchResult(
        search_id=search_id,
        query=query,
        license_filter=license_filter,
        items=items,
        thumbnail_paths=tuple(thumbnail_paths),
        skipped_sources=skipped_sources,
    )


# --- save --------------------------------------------------------------------------------


def _png_bytes(data: bytes) -> tuple[bytes, int, int]:
    """The image as PNG (RGBA when it has alpha, else RGB) with its pixel size."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image.load()
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        converted = image.convert("RGBA" if has_alpha else "RGB")
    buffer = io.BytesIO()
    converted.save(buffer, "PNG")
    return buffer.getvalue(), converted.width, converted.height


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_references(
    search_id: str,
    numbers: list[int],
    kit_slug: str,
    fetch: Callable[[str, dict], bytes] = _http_get,
    reference_root: Path | None = None,
) -> list[SavedReference]:
    """Download the numbered items of a search as PNGs into <reference_root>/<kit_slug>/ and log their provenance.

    A file with the same content is reused, so saving a number twice adds no file.
    """
    import yaml

    reference_root = paths.REFERENCE_ROOT if reference_root is None else reference_root
    if not KIT_SLUG_PATTERN.fullmatch(kit_slug):
        raise ValueError(f"kit_slug must match [a-z0-9_]+, got {kit_slug!r}")
    if not SEARCH_ID_PATTERN.fullmatch(search_id):
        raise ValueError(f"search_id must match [A-Za-z0-9_-]+, got {search_id!r}")
    if not reference_root.parent.exists():
        raise FileNotFoundError(f"{reference_root.parent} is missing: codex_fs is not mounted")
    results_path = paths.SEARCH_CACHE_ROOT / search_id / "results.json"
    if not results_path.is_file():
        raise FileNotFoundError(f"no search {search_id!r}: {results_path} does not exist")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    by_number = {entry["n"]: entry for entry in results["items"]}
    unknown = [number for number in numbers if number not in by_number]
    if unknown:
        raise ValueError(
            f"numbers {unknown} are not in search {search_id}; valid numbers are 1..{len(by_number)}"
        )

    kit_directory = reference_root / kit_slug
    kit_directory.mkdir(parents=True, exist_ok=True)
    log_path = kit_directory / "references.yaml"
    log = yaml.safe_load(log_path.read_text(encoding="utf-8")) if log_path.is_file() else None
    log = log or []

    saved: list[SavedReference] = []
    for number in numbers:
        entry = by_number[number]
        item = ReferenceItem(**{name: entry[name] for name in ReferenceItem.__dataclass_fields__})
        png, width_px, height_px = _png_bytes(fetch(item.image_url, {}))
        sha256 = hashlib.sha256(png).hexdigest()
        stem_base = f"{item.source}_{re.sub(r'[^A-Za-z0-9_-]', '_', item.source_id)[:MAXIMUM_SOURCE_ID_CHARACTERS]}"
        stem, suffix = stem_base, 1
        while (kit_directory / f"{stem}.png").exists() and _file_sha256(
            kit_directory / f"{stem}.png"
        ) != sha256:
            suffix += 1
            stem = f"{stem_base}_{suffix}"
        image_path = kit_directory / f"{stem}.png"
        if not image_path.exists():
            image_path.write_bytes(png)

        existing = next((logged for logged in log if logged["id"] == stem), None)
        if existing is not None:
            saved.append(SavedReference(**existing))
            continue
        reference = SavedReference(
            id=stem,
            query=results["query"],
            search_id=search_id,
            number=number,
            sha256=sha256,
            mac_path=str(image_path),
            big_path=paths.big_path(image_path),
            width_px=width_px,
            height_px=height_px,
            too_small_for_shape=max(width_px, height_px) < MINIMUM_SHAPE_LONG_EDGE_PX,
            saved=datetime.datetime.now(datetime.UTC).date().isoformat(),
            **{
                name: getattr(item, name)
                for name in ReferenceItem.__dataclass_fields__
                if name not in ("width_px", "height_px")
            },
        )
        log.append(asdict(reference))
        saved.append(reference)

    log_path.write_text(yaml.safe_dump(log, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return saved
