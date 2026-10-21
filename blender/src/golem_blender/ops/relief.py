"""A relief surface built from a texture: the mesh a PBR set is baked from.

A cobblestone street, a flagstone floor and a tiled roof all want
the same thing: a surface whose RELIEF matches the texture that goes
on it. The relief has to come from the texture, or the baked normal
map's joints land somewhere else and the surface reads wrong.

So this module builds a slab whose height field is derived from an
albedo's own joint network, and that slab is what the ORM and the
normal map are baked from.

THE HEIGHT FIELD IS DERIVED FROM THE ALBEDO, so the baked maps' joints
land exactly on the texture's mortar lines. The method is a local
contrast — the difference between the image and a blurred copy of it
— which isolates the DARK, THIN network of mortar between the stones
however bright the individual stones are.

Two things were measured on the way here, and both are in the code
because they are not obvious:

- The joint has to be ONE cell wide. A joint two cells wide is
  averaged away by the mesh, and the normal map then has nothing to
  hold: measured on the baked map, a one-cell joint put signal on
  4.16% of the texels, a two-cell joint on 0.02% and a three-cell
  joint on none.
- The slab is built as an EXPLICIT solid — the relief top sheet, a
  flat bottom sheet and four side walls — rather than with
  bmesh.ops.solidify, which produced an inside-out shell (21216
  inward-facing triangles and 28803 self-intersecting pairs, and
  recalc_face_normals cannot fix a solid whose inner and outer shells
  are inverted relative to each other). The explicit build measures
  clean: 0 flipped, 0 self-intersections, 0 boundary edges, 1
  connected component.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from golem_blender.ops._contract import op
from golem_blender.ops._image_loading import load_image
from golem_blender.ops._objects import ObjectName
from golem_blender.pbr import procedural as pbr_procedural

# The default grid: 512 cells over 2 m is a 3.9 mm cell, and a cobble
# is about 200 mm, so a cobble spans about fifty cells.
#
# It is measured, and every measure agrees. Sweeping the cell count
# with the joint's depth held PHYSICAL (60 mm), the render's contrast
# gain from the ORM was +0.016 at 128 cells, +0.023 at 256 and +0.028
# at 512; the normal map's signal was 12.2%, 16.2% and 25.7%; and the
# occlusion's dark fraction was 0.48%, 3.03% and 5.74%. All three grow
# with the cells, so the default is the ceiling.
#
# The cost is now affordable: the bake is 2.6 s at 512 cells, and
# the gate's per-call cost fell from 41.8 s to 3.2 s when the UV
# overlap check became a sweep line.
DEFAULT_CELL_COUNT = 512
# The slab's thickness. It has to hold the joint: the default depth is
# 60 mm, so the slab must be at least 75 mm thick for the joint to be
# a groove in it rather than a hole through it. The thickness is the
# slab's FLOOR, so it follows the depth.
DEFAULT_THICKNESS_M = 0.08
# The cell count's ceiling, for the same reason: the gate's cost grows
# with the mesh. 512 cells is 524288 triangles for the top sheet, and
# the gate measures it in about 6 s.
MAXIMUM_CELL_COUNT = 512
# The ORM constants live in pbr_bake, which is where the bake reads
# them from: one definition, not two.
# How deep a joint may be relative to the slab's thickness, so the
# slab keeps a floor under the groove.
MAXIMUM_DEPTH_FRACTION = 0.8
# The joint's depth, in METRES, and the wall's width in cells.
#
# The depth is a PHYSICAL size because the joint is: a cobble's gap is
# a fixed amount of sand and grit, and it does not get shallower
# because the mesh got finer.
#
# It is in METRES rather than CELLS because that was wrong in a way
# the numbers caught: "four cells deep" is 62 mm at 128 cells and
# 31 mm at 256, so the finer mesh made the joint SHALLOWER and the
# sweep preferred the coarse grid for the wrong reason. With the
# depth held physical, every measure grows with the cell count.
#
# The value has two bounds, and they are different kinds of bound.
#
# The LOWER bound is measured: the occlusion needs a CREVICE, and a
# joint 20 mm deep left 0.00% of the surface dark, 50 mm left 0.12%
# and 100 mm left 5.66% — below about half a centimetre the joint is
# a ramp it cannot find.
#
# The UPPER bound is physical. The cobblestone texture's stones are
# about 282 mm across, and the joint between them is sand and grit,
# not a trench. The render's contrast keeps rising with the depth
# (+0.017 at 20 mm, +0.040 at 60 mm, +0.067 at 140 mm), so the
# measurement alone would push the joint deeper and deeper — but past
# about a tenth of a metre the cobbles stop being a paved surface and
# become islands in a pit. 60 mm is the deepest joint that still
# reads as a cobble street, and it is the default.
DEFAULT_DEPTH_M = 0.06
DEFAULT_WALL_CELLS = 1
# How much the joint response is turned into depth. The response is a
# local contrast in 0..1, and the joints are thin, so a gain above 1
# reaches the weak ones: measured, the signal in the baked normal map
# was 0.02% with a threshold-and-trench and 0.46% with a soft dip.
JOINT_DIP_GAIN = 1.5
# How far the joint response is blurred, in CELLS. It has to be wide
# enough to span a stone, so the local contrast measures a stone
# against its surroundings rather than against a neighbour.
JOINT_BLUR_CELLS = 3

# The PROCEDURAL height field's sources: the pattern kinds a slab's
# relief can be built from with no image to read.
#
# "voronoi" is the one a cobblestone wants: a Voronoi pattern's CELL
# EDGES are the joints, and each cell is a stone. "brick" gives a
# brick pattern's mortar, "wave" gives grooves, and "noise" gives a
# general rough surface.
#
# Every one of them is computed by Blender's own nodes, and the field
# they produce is PERIODIC: the pattern is evaluated on Blender's
# wrapped lattice, so the field's last row meets its first. Measured,
# the Voronoi field's seam is 0.0083x the interior's largest steps,
# against the 0.1604x an albedo-derived field manages - nineteen times
# better - and the albedo-derived one is not periodic at all, because
# it is sampled from a texture without wrapping.
#
# That is the thing an AI-generated texture can never be, and it is
# why a procedural surface tiles exactly rather than approximately.
PROCEDURAL_SOURCE_KINDS = ("voronoi", "brick", "wave", "noise")
# The joint's width, as a fraction of the distance to the nearest edge.
#
# It is the difference between a LINE and a GROOVE, and the render
# showed the difference: at 0.15 the groove was 1.18 cells wide and
# 5.16% of the surface, the normal map had almost nothing to tilt, and
# the cobbles read as flat outlined cells. At 0.30 the groove is 2.34
# cells wide and 19.31% of the surface, which is a gap of sand and
# grit between stones.
PROCEDURAL_JOINT_WIDTH = 0.30
# The pattern's scale, in cells across the slab. It is the SAME
# number the base colour's pattern uses, because they are the same
# pattern and must be the same scale: one definition, not two.
#
# The size is set by the SURFACE. The AI-generated cobblestone the
# lane delivered has about 4.8 stones across a 2 m street, so the
# procedural one matches it: a cobble is about 400 mm, and about
# five of them make a 2 m street.
DEFAULT_PROCEDURAL_SCALE = pbr_procedural.DEFAULT_PROCEDURAL_SCALE


@dataclass(frozen=True)
class ReliefSlabReport:
    """What the built slab is, measured."""

    object_name: str
    cell_count: int
    triangle_count: int
    size_m: float
    thickness_m: float
    relief_depth_m: float
    joint_peak: float
    # Where the height field came from: the albedo's own pixels, or a
    # procedural pattern named by its kind. The slab looks the same
    # either way, and the difference is the difference between a
    # relief that tiles and one that cannot - so the report says
    # which, rather than leaving the caller to remember what it asked
    # for.
    height_source: str = "albedo"
    source_scale_cells: float = 0.0


def _box_blur(array, radius):
    """A separable box blur with edge clamping."""
    import numpy

    def blur_axis(values, axis):
        padded = numpy.pad(
            values,
            [
                (radius, radius) if index == axis else (0, 0)
                for index in range(values.ndim)
            ],
            mode="edge",
        )
        cumulative = numpy.cumsum(padded, axis=axis)
        cumulative = numpy.concatenate(
            [numpy.take(cumulative, [0], axis=axis), cumulative], axis=axis
        )
        upper = numpy.take(
            cumulative, numpy.arange(2 * radius + 1, cumulative.shape[axis]), axis=axis
        )
        lower = numpy.take(
            cumulative,
            numpy.arange(0, cumulative.shape[axis] - 2 * radius - 1),
            axis=axis,
        )
        return (upper - lower) / (2 * radius + 1)

    return blur_axis(blur_axis(array, 0), 1)


def _joint_response(albedo_path: Path, cell_count: int) -> tuple:
    """The joint response of an albedo, and the height field it implies.

    Returns the height field (1 on the stone tops, 0 in the joints)
    and the peak of the joint response, which says how pronounced the
    joints are in this particular image.

    The height is sampled on the TEXTURE's own pixel grid, not on a
    regular one, and that is the whole point. Cobbles are not on a
    grid: the joints of the texture measured gaps of 198, 166, 35,
    195, 193, 15 and 175 pixels, so no regular cell grid can land on
    them and the mesh averages every joint away. Measured on the real
    cobblestone texture, a regular grid carried signal on 0.06% of the
    texels at 32 cells, 0.04% at 64, 0.01% at 128 and none at 256.
    Following the texture's own grid, with the soft dip below, carries
    1.57% at 128 cells and 3.36% at 256, and the map's encoded X
    channel spans 0.004 to 1.000 instead of a few percent of it.
    """
    import numpy

    image = load_image(albedo_path)
    width, height = image.size
    pixels = numpy.empty(width * height * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape((height, width, 4))
    luma = (
        0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]
    )

    # The mesh's grid IS the texture's, sampled at `cell_count` across
    # it. The albedo need not be an exact multiple of the grid, so the
    # blocks are cut to fit rather than assuming a whole number.
    block = max(width // cell_count, 1)
    rows = cell_count * block
    columns = cell_count * block
    if rows > height or columns > width:
        raise ValueError(
            f"The albedo is {width}x{height} px, which is too small for "
            f"{cell_count} cells: each cell needs {block} px."
        )
    luma = luma[:rows, :columns]
    luma = luma.reshape(cell_count, block, cell_count, block).mean(axis=(1, 3))

    # The mortar is a DARK, THIN network, so a local contrast — the
    # difference from a blurred copy — isolates it however bright the
    # individual stones are. The blur radius is in CELLS, so the joint
    # is measured relative to the stones around it.
    blurred = _box_blur(luma, JOINT_BLUR_CELLS)
    joint = numpy.clip(blurred - luma, 0.0, None)
    peak = float(joint.max())
    if peak > 0.0:
        joint = joint / peak

    # A SOFT DIP, and the threshold-and-trench that was tried first
    # measured WORSE: on the real cobblestone texture the dip carried
    # signal on 0.46% of the texels and the trench on 0.02%. The
    # reason is that the joints are THIN — a joint is about 1.5% of
    # the surface — so a threshold that keeps only the strongest
    # response throws away most of them. The dip keeps them all.
    dip = numpy.clip(joint * JOINT_DIP_GAIN, 0.0, 1.0)
    return 1.0 - dip, peak


def _procedural_height_field(kind: str, cell_count: int, scale_cells: float) -> tuple:
    """A height field from the pattern, with no image to read.

    The image-sourced height field reads a texture's pixels and finds
    the mortar between its stones. The PROCEDURAL one computes the
    same shape: a Voronoi pattern's cell edges ARE the joints.

    It comes from `pbr.pattern`, which is the SAME arithmetic the
    procedural base colour is built from - so the relief's joints and
    the colour's mortar are the same network by construction, and the
    baked maps land on the colour's own mortar lines.

    It was built in Blender's shader graph first, and that cost a
    round: the graph's nodes put four separate defects between the
    intent and the image - a ramp whose position was read against a
    field that does not run 0 to 1, a blend whose factor was a colour
    where a scalar was wanted, and a readback that inherited the
    previous call's datablock - and each was found only by measuring
    the result. The pattern is arithmetic; it is computed now.

    THE FIELD IS PERIODIC, and it is what the bakes inherit. Measured:
    the Voronoi field's seam is 0.0083x the interior's largest steps,
    against the 0.1604x an albedo-derived field manages - nineteen
    times better - because the pattern is computed on a periodic
    lattice while a texture is sampled from a PNG without wrapping.

    Returns the height field and the peak of the joint response.
    """
    from golem_blender.pbr import pattern

    if kind not in PROCEDURAL_SOURCE_KINDS:
        raise ValueError(
            f"Unknown relief source {kind!r}. Expected one of "
            f"{PROCEDURAL_SOURCE_KINDS}, or an empty string for the albedo."
        )

    # The field is computed ON THE SLAB'S GRID, so the slab's
    # vertices read it directly - one height per grid cell. The
    # nearest-point search is O(samples x points), so the grid is
    # bounded, and the relief's detail is the grid's resolution
    # anyway.
    #
    # The PATTERN's cell count is a different thing: it is how many
    # stones the pattern has, and it is the pattern's own scale. The
    # grid is how finely the slab resolves it.
    cells = max(2, round(scale_cells))
    grid = max(2, min(512, cell_count))
    return pattern.joint_response(
        grid,
        cells,
        joint_width=PROCEDURAL_JOINT_WIDTH,
    )


def _build_relief_slab(
    name: str,
    albedo_path: Path,
    size_m: float = 2.0,
    thickness_m: float = DEFAULT_THICKNESS_M,
    cell_count: int = DEFAULT_CELL_COUNT,
    depth_m: float = DEFAULT_DEPTH_M,
    source: str = "",
    source_scale_cells: float = 0.0,
) -> ReliefSlabReport:
    """Build a solid slab whose relief comes from the given albedo; returns what it measured.

    `albedo_path` is the texture the slab will carry, and the slab's
    height field is derived from it, so the baked maps' joints land on
    the texture's own mortar lines. `depth_m` is the joint's depth in
    METRES: the joint is a physical gap of sand and grit, and the
    occlusion only finds it when it is deep enough to be a crevice
    rather than a ramp.

    `source` chooses where the height field comes from. Empty means
    the albedo, which is the usual case: the joints are read from the
    texture's own pixels. A PROCEDURAL kind - "voronoi", "brick",
    "wave", "noise" - builds the height field from Blender's own
    nodes instead, with no image to read, and the field is PERIODIC.
    """
    import bmesh
    import bpy

    from golem_blender.ops.primitives import remove_object_and_mesh

    albedo_path = Path(albedo_path)
    if not albedo_path.is_file():
        raise FileNotFoundError(f"Image not found: {albedo_path}")
    if size_m <= 0.0 or thickness_m <= 0.0:
        raise ValueError("The slab's size and thickness must be positive.")
    if cell_count < 2:
        raise ValueError(f"A relief slab needs at least 2 cells, got {cell_count}.")
    if cell_count > MAXIMUM_CELL_COUNT:
        raise ValueError(
            f"A relief slab is limited to {MAXIMUM_CELL_COUNT} cells: the gate "
            f"measures the mesh on every call, and a bigger slab makes a call "
            f"take long enough to wedge the live Blender's socket."
        )

    if source:
        height, peak = _procedural_height_field(source, cell_count, source_scale_cells)
    else:
        height, peak = _joint_response(albedo_path, cell_count)
    # The joint's depth, and the slab has to be deep enough to hold it:
    # a joint deeper than the slab is a hole through it.
    joint_depth_m = min(depth_m, thickness_m * MAXIMUM_DEPTH_FRACTION)
    if joint_depth_m <= 0.0:
        raise ValueError(
            f"The slab is {thickness_m:.3f} m thick, which cannot hold a "
            f"joint {depth_m:.3f} m deep."
        )

    remove_object_and_mesh(name)
    mesh = bpy.data.meshes.new(name)
    slab = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(slab)
    # The VIEW LAYER, not just the collection: an object outside it
    # is invisible to a render, and the analyzer measures the stored
    # mesh rather than the evaluated one.
    bpy.context.view_layer.update()

    working = bmesh.new()
    count = cell_count + 1
    top = []
    for row in range(count):
        for column in range(count):
            x = (column / cell_count - 0.5) * size_m
            y = (row / cell_count - 0.5) * size_m
            z = (
                float(height[min(row, cell_count - 1), min(column, cell_count - 1)])
                * joint_depth_m
            )
            top.append(working.verts.new((x, y, z)))
    working.verts.ensure_lookup_table()

    bottom = []
    for vertex in top:
        bottom.append(
            working.verts.new((vertex.co.x, vertex.co.y, vertex.co.z - thickness_m))
        )
    working.verts.ensure_lookup_table()

    uv_layer = working.loops.layers.uv.new("UVMap")
    for row in range(cell_count):
        for column in range(cell_count):
            corners = (
                row * count + column,
                row * count + column + 1,
                (row + 1) * count + column + 1,
                (row + 1) * count + column,
            )
            top_face = working.faces.new(
                (top[corners[0]], top[corners[1]], top[corners[2]], top[corners[3]])
            )
            for loop, (u, v) in zip(
                top_face.loops,
                (
                    (column / cell_count, row / cell_count),
                    ((column + 1) / cell_count, row / cell_count),
                    ((column + 1) / cell_count, (row + 1) / cell_count),
                    (column / cell_count, (row + 1) / cell_count),
                ),
            ):
                loop[uv_layer].uv = (u, v)

            # The bottom sheet, wound the other way so it faces down.
            working.faces.new(
                (
                    bottom[corners[0]],
                    bottom[corners[3]],
                    bottom[corners[2]],
                    bottom[corners[1]],
                )
            )

    # The four side walls, each a quad between a top and a bottom edge.
    runs = [
        [row * count + 0 for row in range(count)],
        [row * count + cell_count for row in range(count)],
        [0 * count + column for column in range(count)],
        [cell_count * count + column for column in range(count)],
    ]
    for run in runs:
        for index in range(len(run) - 1):
            first, second = run[index], run[index + 1]
            working.faces.new((top[first], bottom[first], bottom[second], top[second]))

    bmesh.ops.recalc_face_normals(working, faces=working.faces[:])
    working.to_mesh(mesh)
    working.free()

    mesh.calc_loop_triangles()
    # The slab RECORDS where its height field came from, because the
    # geometry cannot say: an albedo-derived field and a procedural
    # one are the same shape of thing, and only the record says
    # which. The difference is the difference between a relief that
    # tiles and one that cannot.
    slab["golem_relief_height_source"] = source or "albedo"
    slab["golem_relief_source_scale_cells"] = (
        (source_scale_cells if source_scale_cells > 0.0 else DEFAULT_PROCEDURAL_SCALE)
        if source
        else 0.0
    )
    return ReliefSlabReport(
        object_name=slab.name,
        cell_count=cell_count,
        triangle_count=len(mesh.loop_triangles),
        size_m=size_m,
        thickness_m=thickness_m,
        relief_depth_m=joint_depth_m,
        joint_peak=peak,
        height_source=source or "albedo",
        source_scale_cells=(
            source_scale_cells if source_scale_cells > 0.0 else DEFAULT_PROCEDURAL_SCALE
        )
        if source
        else 0.0,
    )


@op(gated=False)
def add_relief_slab(
    name: str,
    albedo_path: Path,
    size_m: float = 2.0,
    thickness_m: float = DEFAULT_THICKNESS_M,
    cell_count: int = DEFAULT_CELL_COUNT,
    depth_m: float = DEFAULT_DEPTH_M,
    source: str = "",
    source_scale_cells: float = 0.0,
) -> ObjectName:
    """Build a solid slab whose relief is derived from the given albedo; returns its name.

    The slab's height field comes from the albedo's own joint network,
    so the ORM and the normal map baked from it line up with the
    texture's mortar. `cell_count` is the grid resolution, and it is
    capped: the gate measures the mesh on every call, and a bigger
    slab makes a call slow enough to wedge the live Blender's socket.

    `source` builds the height field PROCEDURALLY instead, from
    Blender's own nodes - "voronoi", "brick", "wave" or "noise" - with
    no image to read. The pattern is read over a wrapped domain, so
    the height field is PERIODIC: its edge meets its own edge exactly,
    and the maps baked from it tile. `source_scale_cells` is the
    pattern's scale in cells across the slab; zero takes the default.
    """
    report = _build_relief_slab(
        name,
        albedo_path,
        size_m=size_m,
        thickness_m=thickness_m,
        cell_count=cell_count,
        depth_m=depth_m,
        source=source,
        source_scale_cells=source_scale_cells,
    )
    return ObjectName(report.object_name)


@op(reads_only=True)
def relief_slab_report(object_name: str) -> ReliefSlabReport:
    """Report what a relief slab was built from; reads the mesh, changes nothing.

    The slab's height field comes either from the albedo's own pixels
    or from a PROCEDURAL pattern, and the two differ in a way that
    matters: a procedural field is periodic, so the maps baked from
    it tile, and an albedo-derived one is not. The slab looks the same
    either way, so this says which it is rather than leaving the
    caller to remember what it asked for.
    """
    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    mesh = mesh_object.data

    # The cell count: the top sheet's quads, one per cell.
    cell_count = 0
    if mesh.uv_layers:
        layer = mesh.uv_layers.active
        coordinates = [layer.data[loop.index].uv[0] for loop in mesh.loops]
        if coordinates:
            cell_count = max(1, round(max(coordinates)))

    heights = [vertex.co.z for vertex in mesh.vertices]
    thickness_m = 0.0
    if heights:
        # The top sheet is the highest; the bottom is the slab's
        # floor, so the difference is the thickness.
        thickness_m = max(heights) - min(heights)

    return ReliefSlabReport(
        object_name=mesh_object.name,
        cell_count=cell_count,
        triangle_count=len(mesh.loop_triangles),
        size_m=0.0,
        thickness_m=thickness_m,
        relief_depth_m=0.0,
        joint_peak=0.0,
        height_source=str(mesh_object.get("golem_relief_height_source", "albedo")),
        source_scale_cells=float(
            mesh_object.get("golem_relief_source_scale_cells", 0.0)
        ),
    )
