"""CURVATURE and SCRATCHES: the two primitives the lane had none of.

Both are ported from Material Maker (MIT, Rodolphe Suescun), and
both are in the report at `_evaluate/material_maker_report.md`:

  - `smooth_curvature2` is a discrete second difference - a
    Laplacian over a cone of offsets - and it is the CAVITY map.
    A concave crease is a cavity, a convex edge is a wear edge, and
    one map gives both. It is the map that makes a hand-painted
    edge treatment work and the map that gives a wound its depth.

  - `scratches2` is an abrasion: a set of layers of wavy lines, each
    layer with its own angle and its own per-cell randomness. The
    lane had no abrasion primitive at all, and a worn metal sheet and
    a worn stone both need one.

Both are TILEABLE. The curvature samples periodically, and the
scratch's cells wrap.
"""

from __future__ import annotations

import numpy as np

__all__ = (
    "curvature",
    "scratches",
)

# How far the curvature's own spread reaches from the middle.
#
# The map is centred on 0.5 and its spread is normalised, so the
# number is how many of the field's own standard deviations a crest
# is away from the middle. It is 0.5 so a crest is one standard
# deviation out and the map uses its whole range.
CURVATURE_SCALE = 0.5


def _sample_wrapped(field: np.ndarray, offset_x: np.ndarray, offset_y: np.ndarray):
    """Sample `field` at a fractional offset, wrapping at the edges.

    The offset is in PIXELS, and the sample is bilinear. The wrap is
    the field's own period, so a curvature map of a tileable field is
    itself tileable.
    """
    height, width = field.shape
    rows, columns = np.meshgrid(
        np.arange(height, dtype=np.float64),
        np.arange(width, dtype=np.float64),
        indexing="ij",
    )
    source_y = rows + offset_y
    source_x = columns + offset_x
    base_y = np.floor(source_y)
    base_x = np.floor(source_x)
    fraction_y = source_y - base_y
    fraction_x = source_x - base_x
    base_y = base_y.astype(np.int64) % height
    base_x = base_x.astype(np.int64) % width
    next_y = (base_y + 1) % height
    next_x = (base_x + 1) % width

    top = (
        field[base_y, base_x] * (1.0 - fraction_x) + field[base_y, next_x] * fraction_x
    )
    bottom = (
        field[next_y, base_x] * (1.0 - fraction_x) + field[next_y, next_x] * fraction_x
    )
    return top + (bottom - top) * fraction_y


def curvature(
    field: np.ndarray,
    radius: float = 1.0,
    quality: int = 4,
    strength: float = 1.0,
) -> np.ndarray:
    """The field's CURVATURE: a Laplacian over a cone of offsets.

    Material Maker's `smooth_curvature2`, ported.

    For each offset in a `quality` by `quality` cone, the Laplacian
    at that offset is `4 * field(p) - (field(p+o) + field(p-o) +
    field(p+o*(1,-1)) + field(p-o*(1,-1)))`, and the cone weights it
    down with the offset's distance from the centre.

    The result is centred on 0.5: above 0.5 is a CONVEX edge and
    below it is a CONCAVE crease. That is the map that gives a
    hand-painted edge treatment its light rim and a cavity mask its
    darkness.

    The radius is in PIXELS and the offsets step by `radius /
    quality`, so the map measures the curvature at that scale and not
    at a scale of its own.
    """
    field = np.asarray(field, dtype=np.float64)
    if field.ndim != 2:
        raise ValueError(
            f"a curvature needs a two-dimensional field, got {field.ndim} dimensions"
        )
    if quality < 1:
        raise ValueError(f"the curvature's quality must be at least 1, got {quality}")
    reach = max(1e-6, 0.05 * float(radius))
    step = reach / quality
    centre = field * 4.0
    total = np.zeros_like(field)
    for offset_y in range(quality):
        for offset_x in range(quality):
            distance = np.hypot(offset_x, offset_y) * step
            weight = (reach - distance) / reach
            if weight <= 0.0:
                continue
            shift_x = np.full(field.shape, offset_x * step, dtype=np.float64)
            shift_y = np.full(field.shape, offset_y * step, dtype=np.float64)
            diagonal_x = np.full(field.shape, offset_x * step, dtype=np.float64)
            diagonal_y = np.full(field.shape, -offset_y * step, dtype=np.float64)
            laplacian = (
                centre
                - _sample_wrapped(field, shift_x, shift_y)
                - _sample_wrapped(field, -shift_x, -shift_y)
                - _sample_wrapped(field, diagonal_x, diagonal_y)
                - _sample_wrapped(field, -diagonal_x, -diagonal_y)
            )
            total += laplacian * weight
    total /= float(quality * quality)
    # The map is NORMALISED, and it has to be: a Laplacian's size
    # grows with the field's own amplitude and shrinks with the
    # radius squared, so a raw Laplacian of a gentle field is
    # invisible and the same field at a small radius is enormous.
    #
    # The strength is measured against the map's own spread, so the
    # curvature is a MAP and not a number: a crest is above 0.5 and a
    # crease is below it, whatever the field it was taken from.
    spread = float(total.std())
    if spread <= 1e-12:
        return np.full_like(total, 0.5)
    return 0.5 + (total / spread) * float(strength) * CURVATURE_SCALE


def scratches(
    resolution: int,
    size: float = 0.25,
    width: float = 0.5,
    layers: int = 4,
    waviness: float = 0.5,
    angle: float = 0.0,
    randomness: float = 0.5,
    seed: int = 0,
) -> np.ndarray:
    """SCRATCHES: an abrasion, as layers of long thin lines.

    Material Maker's `scratches2` (MIT), ported step for step. Each
    LAYER shifts the domain by its own random offset, cuts it into
    cells, and draws ONE scratch in each cell, in the cell's own frame:
    turned by the cell's angle, set off by the cell's offset, bent by
    the cell's wave, and fading to nothing at the cell's border - so a
    scratch never shows the cell it was drawn in. The layers are
    MAXIMED together, and their offsets put their cells in different
    places, so no grid shows.

    The result is in 0..1, where one is a deep scratch.

    It TILES: the offset wraps, the cell count is whole, and each cell's
    randoms are its own, so the image's edge meets itself.

    The earlier port wrapped the frame PER CELL, so every cell carried
    every cell's scratch and the map repeated at the cell's period as a
    grid of short dashes; and it drew each cell nine times over the
    whole image, O(cells^2 x resolution^2). This is one pass a layer.
    """
    samples = np.arange(resolution, dtype=np.float64) / resolution
    sample_x, sample_y = np.meshgrid(samples, samples, indexing="ij")
    generator = np.random.default_rng(seed)
    count = max(1, int(np.floor(1.0 / max(1e-6, float(size)))))
    cut = max(1e-6, float(size) * count)
    two_pi = 2.0 * np.pi

    result = np.zeros((resolution, resolution), dtype=np.float64)
    for _layer in range(max(1, int(layers))):
        shift = generator.random(2)
        randoms = generator.random((count, count, 3))
        cells_x = np.mod(sample_x + shift[0], 1.0) * count
        cells_y = np.mod(sample_y + shift[1], 1.0) * count
        cell_x = np.floor(cells_x).astype(np.int64) % count
        cell_y = np.floor(cells_y).astype(np.int64) % count
        local_x = cells_x - np.floor(cells_x)
        local_y = cells_y - np.floor(cells_y)
        border = np.clip(
            10.0
            * np.minimum(
                np.minimum(local_x, 1.0 - local_x), np.minimum(local_y, 1.0 - local_y)
            ),
            0.0,
            1.0,
        )
        turn = two_pi * (
            angle / 360.0 + (randoms[cell_x, cell_y, 0] - 0.5) * randomness
        )
        frame_x = 2.0 * local_x - 1.0
        frame_y = 2.0 * local_y - 1.0
        cosine = np.cos(turn)
        sine = np.sin(turn)
        along = cosine * frame_x + sine * frame_y
        across = sine * frame_x - cosine * frame_y
        across = across + 2.0 * randoms[cell_x, cell_y, 1] - 1.0
        across = across + 0.5 * waviness * np.cos(
            2.0 * along + two_pi * randoms[cell_x, cell_y, 2]
        )
        along = along / cut
        across = across / max(1e-6, count * float(width))
        value = (
            border
            * np.clip(1.0 - along * along, 0.0, 1.0)
            * np.clip(1.0 - 1000.0 * across * across, 0.0, 1.0)
        )
        result = np.maximum(result, value)
    return result
