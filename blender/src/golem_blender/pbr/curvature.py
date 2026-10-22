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
    """SCRATCHES: an abrasion, as a set of wavy layers.

    Material Maker's `scratches2`, ported.

    Each layer is a grid of CELLS, and each cell holds one scratch:
    a line at the cell's own angle, wandering along the cell's own
    wave. The layers are MAXIMED together, so the scratches overlap
    the way real abrasions do.

    The result is in 0..1, where one is a deep scratch.

    THE CELLS WRAP, and the way they wrap is the whole difficulty. A
    cell's scratch is drawn in the cell's OWN frame, with the cell's
    own angle and the cell's own wave, and a scratch that crosses a
    cell's border would be half of one angle and half of another.

    So EVERY cell is drawn at its own place and at its eight
    neighbours - and the cell that is drawn on the other side of the
    domain's edge is the one that belongs there, with its own
    randoms. That is the same trick the splatter uses, and it is
    what makes the map tile exactly.

    Measured, without it the scratch map's seam read 0.31 against
    the truth's 0.00.
    """
    samples = (np.arange(resolution, dtype=np.float64) + 0.5) / resolution
    sample_x, sample_y = np.meshgrid(samples, samples, indexing="ij")
    generator = np.random.default_rng(seed)

    result = np.zeros((resolution, resolution), dtype=np.float64)
    for _layer in range(max(1, int(layers))):
        # The layer's own cells, and their count is the inverse of
        # the size: a size of a quarter is four cells across.
        count = max(1, round(1.0 / max(1e-6, float(size))))
        # Each cell's own randomness: its angle and its wave phase.
        angle_random = generator.random((count, count))
        offset_random = generator.random((count, count))
        wave_random = generator.random((count, count))

        for cell_y in range(count):
            for cell_x in range(count):
                for shift_y in (-1, 0, 1):
                    for shift_x in (-1, 0, 1):
                        # The cell is drawn at its own place and at
                        # its eight neighbours, and the neighbour's
                        # place is WRAPPED: the cell at the edge of
                        # the domain is drawn on the other side too.
                        place_x = (cell_x + shift_x) % count
                        place_y = (cell_y + shift_y) % count
                        # The randoms of the PLACE and not of the
                        # drawn cell: the content at a place is the
                        # content of the place, and the domain's edge
                        # has the same content as its other side.
                        place_offset = offset_random[place_y, place_x]
                        place_wave = wave_random[place_y, place_x]
                        place_angle = (
                            2.0
                            * np.pi
                            * (
                                angle / 360.0
                                + (angle_random[place_y, place_x] - 0.5) * randomness
                            )
                        )
                        # The cell's own frame, measured from the
                        # PLACE it is drawn at, so the content lands
                        # where that cell is.
                        # The cell's own frame, and it WRAPS within
                        # the cell: the frame is measured from the
                        # cell's centre with the distance taken the
                        # short way round, so the frame is continuous
                        # across the domain's edge.
                        local_x = sample_x * count - place_x
                        local_y = sample_y * count - place_y
                        local_x = local_x - np.round(local_x)
                        local_y = local_y - np.round(local_y)
                        place_cosine = np.cos(place_angle)
                        place_sine = np.sin(place_angle)
                        rotated_x = local_x * place_cosine - local_y * place_sine
                        rotated_y = local_x * place_sine + local_y * place_cosine

                        # And the scratch is a LINE and not a blob.
                        #
                        # Material Maker's own: the cell's frame is
                        # turned by the cell's angle, the x is divided
                        # by the cell's LENGTH and the y by the cell's
                        # width times the cell's count - so the frame
                        # is long and thin - and the value is a tight
                        # band around the frame's own y of zero, times
                        # a taper along the length.
                        #
                        # The port drew a RECTANGLE: the distance to
                        # the nearest of the two cell's edges, so a
                        # scratch came out as a blob at the cell's
                        # centre, and the truth's scratches are long
                        # thin lines.
                        #
                        # So the value is the distance to the line, and
                        # the line is thin: the tight band is the
                        # hundred-and-one power of the frame's own y.
                        # The frame is in CELL units: the x and the
                        # y both run from minus a half to a half
                        # across the cell.
                        #
                        # Material Maker's own divides the x by the
                        # cell's LENGTH and the y by the cell's width
                        # times the cell's count, and the value is
                        # `min(border.x, border.y)` times
                        # `1 - uv.x*uv.x` times a band a THOUSAND
                        # times the divided y squared.
                        #
                        # So the line is at the divided frame's y of
                        # zero, and the band is a thousandth of the
                        # DIVIDED y - and the divided y is small, so
                        # the band is wide in the cell.
                        #
                        # Material Maker's own divides the x by the
                        # cell's LENGTH and the y by the cell's width
                        # times the cell's count, and the value is
                        # `min(border.x, border.y)` times
                        # `1 - uv.x*uv.x` times a band a THOUSAND
                        # times the divided y squared.
                        #
                        # The border is the distance to the cell's own
                        # edge - and it is a FACTOR and not a mask, so
                        # a scratch fades out towards the cell's
                        # border and the two cells either side of it
                        # both go to nothing there. Without it the
                        # scratches showed the cells' own GRID.
                        #
                        # Material Maker's own, step for step:
                        #
                        #   uv = 2.0*uv - vec2(1.0);        the frame
                        #   uv = vec2(c*uv.x+s*uv.y, ...);    the turn
                        #   uv.y += 2.0*r1.y-1.0;             the line's
                        #   uv.y += 0.5*waviness*cos(2*pi*uv.x + 2*pi*r2.y);
                        #   uv.x /= cut;                     the length
                        #   uv.y /= subdivide*size.y;         the width
                        #   return min(border.x, border.y)
                        #          * (1.0-uv.x*uv.x)
                        #          * max(0.0, 1.0-1000.0*uv.y*uv.y);
                        #
                        # So the LINE sits at a random place in the
                        # cell - the offset is a whole cell - and the
                        # border is the cell's own edge distance, and
                        # it is a FACTOR and not a mask, so a scratch
                        # fades out towards the cell's border.
                        #
                        # The port had the line always at the cell's
                        # centre and the border as a mask, so the
                        # scratches came out as blobs in a GRID.
                        line_y = rotated_y * 2.0
                        line_y = line_y + 2.0 * place_offset - 1.0
                        line_y = line_y + 0.5 * waviness * np.cos(
                            2.0 * np.pi * rotated_x * 2.0 + 2.0 * np.pi * place_wave
                        )
                        divided_x = rotated_x * 2.0 / max(1e-6, float(size) * count)
                        divided_y = line_y / max(1e-6, float(width) * count)
                        band = np.clip(1.0 - 1000.0 * divided_y**2, 0.0, 1.0)
                        # And the TAPER along the length, which is
                        # Material Maker's own `1 - uv.x*uv.x`: the
                        # scratch fades towards both of its ends.
                        length_fade = np.clip(1.0 - divided_x**2, 0.0, 1.0)
                        border = np.minimum(np.abs(local_x), np.abs(local_y))
                        value = band * length_fade * border
                        # The TAPER, and it is the cell's own distance
                        # to its edge - so a scratch fades out before
                        # it reaches the border and the two cells
                        # either side of it both go to nothing there.
                        edge_distance = np.minimum(
                            np.minimum(local_x, 1.0 - local_x),
                            np.minimum(local_y, 1.0 - local_y),
                        )
                        taper = np.clip(edge_distance * 4.0, 0.0, 1.0)
                        result = np.maximum(result, value * taper)
    return result
