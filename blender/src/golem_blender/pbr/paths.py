"""Where PBR texture sets live, and how big sees the same files.

codex_fs is one network filesystem: ~/mnt/codex_fs on the Mac is
/mnt/codex_fs on big. A texture written here is therefore a texture
big's tools (generate_image) can open, once the prefix is swapped by
``kitbash.paths.big_path``.

Every root is read at call time from ``kitbash.paths`` (not copied at
import), so a test that patches the codex root there is seen here too —
the same convention ``kitbash/paths.py`` already uses.
"""

from __future__ import annotations

import os
from pathlib import Path

from golem_blender.kitbash import paths as kitbash_paths

# The texture lane's root: <codex root>/game_assets/textures, overridable
# so a machine (or a test) can point the lane somewhere else without
# touching the codex mount itself.
TEXTURE_ROOT_ENV = "GOLEM_TEXTURE_ROOT"
DEFAULT_TEXTURE_SUBDIRECTORY = ("game_assets", "textures")

# The channel packing, as ONE string the report, the exporter and the
# procedure all read. Measured on the existing sets: R = ambient
# occlusion, G = roughness, B = metallic.
ORM_CHANNEL_PACKING = "R=ao,G=roughness,B=metallic"

# A SET'S RESOLUTION, as one number, because a set is three maps that
# have to agree.
#
# The lane was producing a 1024 base colour with 2048 bakes, because
# the generation tool and the bake ops each had their own default and
# nobody made them agree. Every other set on codex_fs has all three of
# its maps the same size.
#
# 2048 is the number every other set uses, and it is what the relief
# wants: the height field is sampled FROM the base colour, so the base
# colour's pixels decide where the baked joints land, and at 1024 the
# 512-cell grid gets 2 albedo pixels per cell against 4 at 2048. The
# occlusion's dark fraction rises from 10.29% to 12.13% with the finer
# sampling, and the normal map's signal with it.
#
# 2048 is right for the base colour as well, and it took a measurement
# to be sure. The seam of a GENERATED map is a property of the SAMPLE,
# not of the size: the same prompt and seed at 1024 and at 2048 gave
# seams of 2.13x and 4.44x their own feature step, which looked like
# a difference in kind. It is not. Magnified to 3x at the tile
# boundary, BOTH sets' stones run across the boundary continuously,
# and the 2048 set's seam measures 1.38x the texture's largest
# ordinary features - under the limit, and invisible. The first
# impression that the 2048 set "showed its tile boundaries" was a
# misreading of a whole frame: the lines were the stones' own edges.
#
# So the set's size is ONE number, the bakes use it, and the base
# colour is generated at it too. And the lane CHECKS, because a
# generated map's seam is a property of the sample and only a
# measurement can tell: ``tile_seam_ratio`` below is what it reports,
# so a caller can take another sample if one does not tile.
SET_RESOLUTION_PX = 2048

# The file names the existing sets already use (T_Brick_BaseColor.png
# beside T_Brick_Normal.png on codex_fs). The ORM set is the one this
# lane adds.
BASE_COLOR_SUFFIX = "BaseColor"
ORM_SUFFIX = "ORM"
NORMAL_SUFFIX = "Normal"
FILE_PREFIX = "T_"


def texture_root() -> Path:
    """The directory texture sets are written to and read from."""
    override = os.environ.get(TEXTURE_ROOT_ENV)
    if override:
        return Path(override)
    return kitbash_paths.CODEX_ROOT_MAC.joinpath(*DEFAULT_TEXTURE_SUBDIRECTORY)


def big_path(mac_path: Path) -> str:
    """The path big sees for a file under the codex root; ValueError for any other path."""
    return kitbash_paths.big_path(Path(mac_path))


def base_color_file_name(texture_name: str) -> str:
    """The base-colour file name for a texture set: ``T_<Name>_BaseColor.png``."""
    return f"{FILE_PREFIX}{texture_name}_{BASE_COLOR_SUFFIX}.png"


def orm_file_name(texture_name: str) -> str:
    """The ORM file name for a texture set: ``T_<Name>_ORM.png``."""
    return f"{FILE_PREFIX}{texture_name}_{ORM_SUFFIX}.png"


def normal_file_name(texture_name: str) -> str:
    """The normal-map file name for a texture set: ``T_<Name>_Normal.png``."""
    return f"{FILE_PREFIX}{texture_name}_{NORMAL_SUFFIX}.png"


# How large a seam may be, relative to the texture's own features,
# before it is worth telling the caller about.
#
# It is the REFERENCE's range: ambientcg's own sets, which are made
# to tile, measure 0.32x to 0.47x. A map at 1.377x - a generated
# map, before the tileable blend - is in that range's neighbourhood
# and does NOT tile, and one at 3.0x is plainly out of it. So the
# limit is 0.60x: a map inside it is as good as the reference, and
# one outside it is worth the caller's attention.
TILE_SEAM_LIMIT = 0.60


def tile_seam_ratio(image_path: Path) -> float:
    """How large a texture's seam is, against the features it crosses.

    A texture set is something you repeat across a floor, so its own
    edges have to meet. The measure that says whether they do is the
    seam's step against the texture's OWN feature step - the
    difference a stone's edge makes - because a seam that is small
    compared with the features around it is invisible, and a seam that
    is large compared with them is a line.

    The raw ratio is not enough on its own: a high-contrast texture
    has a large step everywhere, so its seam is large too. Comparing
    the seam with the SAME texture's interior steps cancels that out.

    Returns the ratio: the seam's mean absolute step from the last
    column to the first, over the 95th percentile of the steps between
    adjacent columns - the size of the texture's largest ordinary
    features. A ratio at or below 1.0 means the seam is no bigger than
    the biggest stone edge, which is invisible. This reads a PNG
    without numpy, so it runs in the MCP server's process as well as
    inside Blender.
    """
    import struct
    import zlib

    data = Path(image_path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{image_path} is not a PNG file.")

    position = 8
    compressed = b""
    width = height = colour = 0
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        if kind == b"IHDR":
            width, height, _depth, colour = struct.unpack(
                ">IIBB", data[position + 8 : position + 18]
            )
        elif kind == b"IDAT":
            compressed += data[position + 8 : position + 8 + length]
        position += 12 + length

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    stride = width * channels
    raw = zlib.decompress(compressed)

    # The PNG's per-row filters have to be undone. Only the filter
    # types that matter for a photographic image are needed, and they
    # are all here.
    rows = bytearray()
    previous = bytearray(stride)
    index = 0
    for _ in range(height):
        filter_type = raw[index]
        index += 1
        line = bytearray(raw[index : index + stride])
        index += stride
        if filter_type:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = previous[x]
                c = previous[x - channels] if x >= channels else 0
                if filter_type == 1:
                    line[x] = (line[x] + a) & 255
                elif filter_type == 2:
                    line[x] = (line[x] + b) & 255
                elif filter_type == 3:
                    line[x] = (line[x] + (a + b) // 2) & 255
                elif filter_type == 4:
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    line[x] = (line[x] + pred) & 255
        rows += line
        previous = line

    def luma(row, column):
        base = row * stride + column * channels
        return 0.2126 * rows[base] + 0.7152 * rows[base + 1] + 0.0722 * rows[base + 2]

    # The seam, and the interior steps, over a sample of the rows.
    sample = range(0, height, max(height // 256, 1))
    seam_total = 0.0
    interior: list[float] = []
    for row in sample:
        seam_total += abs(luma(row, width - 1) - luma(row, 0))
        for column in range(0, width - 1, max(width // 256, 1)):
            interior.append(abs(luma(row, column) - luma(row, column + 1)))
    seam = seam_total / len(sample)
    interior.sort()
    # The baseline is the interior's 95th percentile, not its median.
    # The median is the typical step between two columns, which in a
    # LOW-CONTRAST texture is tiny - so a seam of any size would look
    # enormous against it, and the measure flagged every quiet texture
    # on codex_fs as seaming (the brick measured 80x its own median
    # and tiles invisibly). The 95th percentile is the size of the
    # texture's LARGEST ordinary features, which is the scale a seam
    # has to be read against: a seam no bigger than the biggest stone
    # edge is not a line.
    baseline = interior[min(int(len(interior) * 0.95), len(interior) - 1)]
    if baseline <= 0.0:
        # A map with NO interior variation has nothing to compare the
        # seam against. It is UNIFORM, and a uniform map tiles
        # trivially - so the seam is 0.0 whatever the absolute step
        # is.
        #
        # It used to return infinity when the seam was not flat, on
        # the reasoning that a step against nothing is the worst
        # case. But a uniform map IS a uniform map: the narrow
        # palette the descriptions call for made several of the
        # benchmark's maps uniform, and infinity said they were the
        # worst rather than the best.
        return 0.0
    return seam / baseline


__all__ = (
    "BASE_COLOR_SUFFIX",
    "FILE_PREFIX",
    "NORMAL_SUFFIX",
    "ORM_CHANNEL_PACKING",
    "ORM_SUFFIX",
    "SET_RESOLUTION_PX",
    "TEXTURE_ROOT_ENV",
    "TILE_SEAM_LIMIT",
    "base_color_file_name",
    "big_path",
    "normal_file_name",
    "orm_file_name",
    "texture_root",
    "tile_seam_ratio",
)
