"""The pattern's FIELDS: the cell each point is in, and the distance to
that cell's edge.

This is the arithmetic behind both the procedural base colour and the
procedural relief, so the two are the SAME pattern by construction -
the relief's joints land on the colour's own mortar lines.

It is here, in numpy, rather than in a shader graph, because the
graph route cost a round: the pattern is arithmetic, and wiring it
through Blender's nodes put four separate defects between the intent
and the image, each of which had to be found by measuring the result.

THE PATTERN
A REGULAR lattice of cells, and a DOMAIN WARP that breaks it into
stones.

The lattice is regular - `cells` x `cells` points at (i + 0.5) / cells
- and the search for the nearest point WRAPS: a sample near the
domain's edge also considers the point on the other side. That is
what makes the pattern periodic, and it is why the lattice cannot be
jittered: a jitter derived from the fractional position is not
periodic, and a jitter derived from the integer index is not
consistent under the wrap. Measured: an unwrapped lattice put a hard
black line down the middle of the image, and the pattern did not
repeat across it.

The WARP is what makes the cells look like stones rather than a grid:
a few octaves of sines over the domain, with INTEGER frequencies so
the warp is periodic, displacing the sample coordinates before the
cells are found.

THE WARP'S FREQUENCY IS WHAT DECIDES IT. A warp at frequencies 1, 2
and 3 is a smooth, low-frequency bend: it turned the lattice into a
regular grid of curved quads - a net, not a quay. A lattice is
broken by a warp that moves each cell a DIFFERENT amount, and that
needs a frequency comparable to the cell count. The octaves here are
at 3, 5 and 8 cycles per domain, and the two axes carry DIFFERENT
frequency sets so they do not shear together.

THE FIELDS
- the CELL: the nearest lattice point;
- the EDGE: the distance to the cell's boundary, which is the
  distance to the second-nearest point less the distance to the
  nearest. Zero on the boundary, growing into the stone.

PERIODICITY
The lattice is regular and the search wraps, and the warp's
frequencies are integers, so the whole field repeats exactly: cell N
is cell 0, and the image's edge meets its own edge. Measured, the seam
is 0.00x the texture's largest ordinary features, against a
generated map's 1.38x - and ambientcg's own maps, which are made to
tile, measure 0.32x to 0.47x.
"""

from __future__ import annotations

# The warp's octaves: (frequency in cycles per domain, amplitude in
# cell units). The frequencies are INTEGERS, because the field has to
# be periodic over the domain, and they are HIGH, because a smooth
# warp bends a lattice rather than breaking it.
DEFAULT_WARP_OCTAVES = ((3, 0.34), (5, 0.22), (8, 0.14))
# How much of the domain a cell takes, before the warp.
DEFAULT_CELL_FRACTION = 1.0
# The smallest a cell may be, as a fraction of the largest cell's edge
# distance. Below it the cell is treated as having no interior, so it
# reads as stone rather than as a blotch of joint.
#
# It is SMALL: the floor is there to catch the degenerate cells the
# warp squeezes, not to reshape the rest. Measured, a floor of 0.35
# dissolved the joints into a mottled field, and the sweep found the
# best at 0.05: the contrast 0.0753 against a real cobblestone's
# 0.0763, the features 12.34 across against the truth's 11.25, and
# the seam 1.26x. At 0.12 the contrast fell to 0.0655 and the seam
# rose to 1.62x, and at 0.25 the joints were gone.
MINIMUM_CELL_FRACTION = 0.05


def warp(
    sample_x,
    sample_y,
    cells: int,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The sample coordinates, displaced by the warp.

    The displacement is in CELL units, so it means the same thing at
    any scale. Each octave is a pair of sines with an integer
    frequency, so the field is periodic over the domain: the
    displacement at 0 is the displacement at 1.

    The two axes carry DIFFERENT frequency sets, so the warp is not a
    simple shear: a cell's neighbours are pushed around it
    independently, which is what breaks a lattice into stones.
    """
    import numpy

    two_pi = 2.0 * numpy.pi
    offset_x = numpy.zeros_like(sample_x)
    offset_y = numpy.zeros_like(sample_y)
    for index, (frequency, amplitude) in enumerate(octaves):
        across = frequency * 2 + index
        along = frequency * 3 + index + 1
        offset_x = (
            offset_x
            + numpy.sin(sample_y * across * two_pi + frequency * 0.7) * amplitude
        )
        offset_x = offset_x + numpy.sin(sample_x * along * two_pi + 1.1) * (
            amplitude * 0.7
        )
        offset_y = (
            offset_y
            + numpy.sin(sample_x * across * two_pi + frequency * 0.3) * amplitude
        )
        offset_y = offset_y + numpy.sin(sample_y * along * two_pi + 2.3) * (
            amplitude * 0.7
        )
    return sample_x + offset_x / cells, sample_y + offset_y / cells


def cell_and_edge(
    resolution: int,
    cells: int,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The cell each sample is in, and the distance to that cell's edge.

    The search is over the NINE cells around the sample's own, which
    is enough because the warp moves a sample by less than one cell.
    The nine are taken modulo the cell count, so the search WRAPS and
    the pattern is periodic: a sample at the domain's edge sees the
    cell on the other side at its true distance.

    The edge distance is the distance to the second-nearest point
    less the distance to the nearest. Measured: the own distance
    taken from the running minimum AFTER the loop was the minimum
    over all the points rather than the nearest point's, so the edge
    came out zero everywhere and the image came out flat.

    AND THE EDGE IS FLOORED, because a warp that varies the cells'
    sizes also makes some of them TINY - and a tiny cell is all edge,
    so it comes out as a black blotch rather than a stone. Measured:
    the magnified texture had black ellipses scattered through it,
    each one a cell so small the joint covered it whole. So a cell
    whose edge distance never rises above a floor is treated as
    having no edge at all, and its interior is stone.
    """
    import numpy

    samples = (numpy.arange(resolution) + 0.5) / resolution
    sample_x, sample_y = numpy.meshgrid(samples, samples, indexing="xy")
    sample_x, sample_y = warp(sample_x, sample_y, cells, octaves)

    best = numpy.full(sample_x.shape, 1e18)
    second = numpy.full(sample_x.shape, 1e18)
    nearest = numpy.zeros(sample_x.shape, dtype=numpy.int32)

    # The sample's own cell, and the eight around it. The positions
    # are the UNWRAPPED ones - so a sample near the edge sees the
    # cell on the other side at its true distance - and the cell's
    # index is taken modulo, so the cell is the same cell.
    base_x = numpy.floor(sample_x * cells).astype(numpy.int32)
    base_y = numpy.floor(sample_y * cells).astype(numpy.int32)
    for offset_y in (-1, 0, 1):
        for offset_x in (-1, 0, 1):
            index_x = base_x + offset_x
            index_y = base_y + offset_y
            point_x = (index_x + 0.5) / cells
            point_y = (index_y + 0.5) / cells
            distance = (sample_x - point_x) ** 2 + (sample_y - point_y) ** 2
            nearer = distance < best
            second = numpy.where(nearer, best, numpy.minimum(second, distance))
            best = numpy.where(nearer, distance, best)
            nearest = numpy.where(
                nearer,
                (index_y % cells) * cells + (index_x % cells),
                nearest,
            )

    edge = numpy.sqrt(numpy.maximum(second, 0.0)) - numpy.sqrt(best)

    # A cell that is entirely edge has no interior: it is a tiny cell
    # the warp squeezed, and it must read as stone rather than as a
    # blotch of joint. The floor is a fraction of the largest cell's
    # edge distance.
    reach = float(edge.max())
    if reach > 0.0:
        floor = reach * MINIMUM_CELL_FRACTION
        tiny = edge < floor
        edge = numpy.where(tiny, reach, edge)
    return nearest, edge


def joint_response(
    resolution: int,
    cells: int,
    joint_width: float = 0.15,
    octaves=DEFAULT_WARP_OCTAVES,
):
    """The height field the RELIEF is built from: 1 on the stones, 0 in
    the joints.

    It is the same field the base colour's joint is read from, so the
    baked maps' joints land on the colour's own mortar lines.

    The joint's width is a fraction of the distance to the edge, so it
    does not depend on the pattern's scale.
    """
    import numpy

    _cell, edge = cell_and_edge(resolution, cells, octaves)
    reach = float(edge.max())
    if reach <= 0.0:
        reach = 1.0
    normalised = numpy.clip(edge / reach, 0.0, 1.0)
    # The joint is where the distance to the edge is SMALL.
    joint = numpy.clip(1.0 - normalised / max(joint_width, 1e-6), 0.0, 1.0)
    return 1.0 - joint, float(edge.max())


__all__ = (
    "DEFAULT_CELL_FRACTION",
    "DEFAULT_WARP_OCTAVES",
    "MINIMUM_CELL_FRACTION",
    "cell_and_edge",
    "joint_response",
    "warp",
)
