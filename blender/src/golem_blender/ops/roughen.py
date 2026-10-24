"""Rough surfaces: a seeded per-vertex displacement, reproducible by argument.

Everything the constructors build is geometrically exact — `add_box`,
`add_cylinder`, `add_lathe` — and a prop that must read as HAND-MADE (a
rough stone basin, a wattle hurdle, a lumpy straw effigy, a split-log
bench) needs its vertices nudged off the ideal surface. Before this op
that was a hand-written vertex loop in `run_python` with a local
`random.Random(71)`: "rough" was whatever that turn's RNG produced, and
a reviewer's note such as "the basin's rim is too even" could not be
answered by a parameter — it meant rewriting the Python.

Five decisions, each stated so a reviewer can disagree with a specific
one.

**The noise is hashed from the vertex's POSITION, not its index.**
`(seed, quantized position)` is the hash's input, so two vertices in the
same place move by the same vector. That is what keeps a mesh WELDED: a
per-index hash splits every seam the mesh carries (the issue names this
edge case), because the two halves of a coincident pair are different
indices and would be pushed apart. It also survives a topology change:
subdividing the surface later puts the same roughness in the same places.

**The field is smooth, not white.** A per-vertex random is a SPIKE field
— the surface reads as noise, not as a rock. The field here is a
trilinear value noise on a lattice whose cell is `BASE_NOISE_CELL_M *
frequency`, with the QUINTIC fade on each axis (the fade
`pbr/noise.py` uses, and for the same reason: zero first and second
derivatives at the cell's edge, so there is no crease where two cells
meet). The hashed corner values are the same integer-mix shape as
`pbr.noise._hash01`, extended to the third axis, because a sine-based
hash is white noise wearing a smooth interpolation (measured there).

**`amplitude_m` is the RMS deviation, not the peak.** A trilinear
field's amplitude on a given mesh is a SAMPLE statistic — the same field
peaks at a lattice corner and passes through zero between them — so the
field is normalized per call to unit RMS and scaled by `amplitude_m`:
the surface's mean square deviation from where it was is exactly
`amplitude_m` (measured on a 12-segment cylinder in
`tests/blender/test_roughen_ops.py`, within 0.1%). `rms_displacement_m`
and `max_displacement_m` in the report are MEASURED off the finished
vertices, so a caller reads what actually happened rather than the
parameter it asked for. The gain is capped (`MAXIMUM_NOISE_GAIN`) so a
degenerate sample — a handful of coincident vertices where the field
happens to vanish — cannot explode the mesh instead, and the report then
shows the shortfall.

**A vertex is never moved below the floor.** The issue's run hit this
twice (a tent flap 1 cm under the floor, a stone ring 6 mm under), and
the gate's base check fails on it. With `clamp_to_ground` (the default)
a vertex whose WORLD z would go negative is lifted back to exactly z=0,
which needs the object's own transform: the lift is `M3⁻¹·(0,0,−z)` in
local space, so it is a pure world-Z translation whatever the object's
rotation and scale are. The clamp is measured in world space because
z=0 is the SCENE floor, not a local plane.

**A face that inverts is refused, loudly, with the mesh untouched.**
Moving vertices independently folds a face once the displacement is a
useful fraction of the face's own size, and a folded face is a flipped
normal the gate reports as a defect three steps later with no trace of
the cause. So the op measures it directly: every polygon's normal before
and after, and a face counted as inverted when the two disagree
(`dot < 0`). Above `MAXIMUM_INVERTED_FACE_COUNT` (0) the original
coordinates are written back and `FaceInversion` names the count, the
amplitude and the seed, so the caller lowers the amplitude rather than
discovering a flipped normal in the render.

Determinism is by construction: the only randomness is the integer hash
of `(seed, position)`, evaluated in numpy float64, with no `random`, no
clock, and no dict or set iterated into geometry. Two fresh Blender
launches under different `PYTHONHASHSEED` produce identical coordinates
(proven in `tests/blender/test_roughen_ops.py`, the same way
`scripts/rebuild_twice.py` proves it for the builders).

`mode` picks the direction each vertex travels, and the choice matters
to what the piece reads as:

- `"radial"` — away from the object's own Z axis. A pot or a stone ring
  keeps its rim a rim; the rim is just uneven.
- `"normal"` — along the vertex's own normal. A hide, a cloth, a lump of
  clay.
- `"z"` — straight up. A ground slab, a bench seat.

The displacement happens in the object's LOCAL frame (the modes are about
the object's own axes, and the noise is a property of the piece, not of
where it stands); only the floor clamp is measured in world space.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from golem_blender.ops._contract import op

# The noise's base lattice cell, in METRES. `frequency` multiplies it, so
# `frequency=1.0` gives 100 mm lumps and `frequency=4.0` gives 400 mm
# ones — larger is chunkier, which is the direction the issue names (a
# stone wants a 100–400 mm lump; a straw bundle wants 20–50 mm).
#
# It is a PHYSICAL length rather than a fraction of the object because
# the roughness is: a stone's lumps do not get smaller because the basin
# was scaled down.
BASE_NOISE_CELL_M = 0.1

# A vertex this close to the object's local Z axis has no radial
# direction (the vector `(x, y, 0)` is zero there). Measured need: every
# gridded slab and lathe has a ring of vertices exactly on the axis. Such
# a vertex moves along local Z instead, so the axis stays a place on the
# surface rather than a line nothing ever touches.
RADIAL_AXIS_EPSILON_M = 1.0e-9

# A polygon whose normal turns past 90 degrees from where it pointed is
# inverted: the displacement folded the face back on itself. Expressed as
# a cosine so the comparison is one dot product per face.
FACE_INVERSION_COSINE = 0.0
# How many inverted faces a call may leave behind. Zero, because the point
# of measuring them is to stop before the gate finds them three steps
# later with no trace of the cause.
MAXIMUM_INVERTED_FACE_COUNT = 0

# The field's RMS is a SAMPLE statistic, so on a mesh with a few
# coincident vertices it can be nearly zero and the gain to unit RMS
# absurd. Capped so such a mesh is roughened too little (and says so in
# `rms_displacement_m`) instead of being blown apart.
MAXIMUM_NOISE_GAIN = 8.0
# Below this the sample's RMS says nothing about the field; normalizing by
# it would divide by nothing.
MINIMUM_NOISE_RMS = 1.0e-6

# The eight lattice corners, in a FIXED order. A set or a dict here would
# be the one place hash order could reach the geometry.
CORNER_OFFSETS = (
    (0, 0, 0),
    (1, 0, 0),
    (0, 1, 0),
    (1, 1, 0),
    (0, 0, 1),
    (1, 0, 1),
    (0, 1, 1),
    (1, 1, 1),
)

ROUGHEN_MODES = ("radial", "normal", "z")


@dataclasses.dataclass(frozen=True)
class RoughenReport:
    """What a roughen left on the mesh, measured off the finished vertices."""

    object_name: str
    vertices_moved: int
    # The largest distance any vertex travelled, in WORLD metres: an object
    # carrying a scale moves its vertices further in the scene than in its
    # own data, and the scene is what a consumer sees.
    max_displacement_m: float
    # The RMS distance the vertices travelled, in world metres. This is the
    # number `amplitude_m` names, measured rather than assumed.
    rms_displacement_m: float
    seed: int
    amplitude_m: float
    frequency: float
    mode: str
    # How many vertices the floor clamp lifted. Zero means the amplitude was
    # small enough (or `clamp_to_ground` was off) that nothing crossed z=0.
    clamped_vertex_count: int
    # Measured always, and zero on any call that returns: a non-zero count
    # is refused before the coordinates are kept.
    inverted_face_count: int


class FaceInversion(ValueError):
    """The displacement would fold the mesh; the coordinates were restored.

    A refusal rather than a warning because the alternative is a flipped
    normal that reaches the gate with nothing in the log naming its cause.
    """


def _corner_value(ix, iy, iz, seed):
    """Each lattice corner's noise value in [-1, 1), from its index and the seed.

    An INTEGER mix, not a sine: `pbr/noise.py` measured that a sine of a
    linear combination of the coordinates decorrelates neighbours (two
    corners one cell apart differ by 220 radians), so the lattice's
    corners become white noise wearing a smooth interpolation. The mix
    here is that module's `_hash01` shape with a third axis, so the two
    fields have one character between them.
    """
    import numpy

    hashed = (
        (ix * 0x27D4EB2D)
        ^ (iy * 0x165667B1)
        ^ (iz * 0x27D4EB2F)
        ^ (numpy.int64(0x9E3779B1) * numpy.int64(seed))
    ) & 0xFFFFFFFF
    hashed ^= hashed >> 15
    hashed = (hashed * 0x2C1B3C6D) & 0xFFFFFFFF
    hashed ^= hashed >> 13
    return (hashed.astype(numpy.float64) / 0xFFFFFFFF) * 2.0 - 1.0


def _quintic(fraction):
    """The quintic fade, `t^3 (6 t^2 - 15 t + 10)`, as `pbr/noise.py` uses it.

    Its first AND second derivatives are zero at 0 and at 1, so the field
    has no crease where two lattice cells meet — a plain smoothstep
    leaves its second derivative discontinuous and the surface shows the
    lattice's grid as a set of faint ridges.
    """
    return fraction**3 * (6.0 * fraction**2 - 15.0 * fraction + 10.0)


def _noise_at(points, cell_m, seed):
    """Trilinear value noise at `points` (N, 3), one value in [-1, 1) each."""
    import numpy

    scaled = points / cell_m
    base = numpy.floor(scaled)
    fraction = scaled - base
    faded = _quintic(fraction)
    integer_base = base.astype(numpy.int64)

    value = numpy.zeros(points.shape[0], dtype=numpy.float64)
    for offset_x, offset_y, offset_z in CORNER_OFFSETS:
        weight = numpy.ones(points.shape[0], dtype=numpy.float64)
        for axis, offset in enumerate((offset_x, offset_y, offset_z)):
            weight *= faded[:, axis] if offset else 1.0 - faded[:, axis]
        corner = _corner_value(
            integer_base[:, 0] + offset_x,
            integer_base[:, 1] + offset_y,
            integer_base[:, 2] + offset_z,
            seed,
        )
        value += weight * corner
    return value


def _position_pooled_normals(normals, points):
    """Give every set of coincident vertices ONE normal: the mean of theirs.

    The direction has to be a function of the vertex's POSITION as much as
    the noise is, or a seam splits in `"normal"` mode even though its two
    halves move by the same vector. Measured on the duplicated-seam
    fixture (two quads, their shared seam stored twice): the halves'
    vertex normals differ by their own face's tilt, so the pair travelled
    to z=+0.0124 and z=-0.0124 and the surface tore open. The mean of a
    seam's two half-normals is the surface's own normal, so the pair moves
    as one — and the mean of the three face normals at a cube's corner is
    the diagonal, which is the direction a lumpy stone's corner wants.

    A group whose mean vanishes (two exactly opposite normals at the same
    place: a zero-thickness double-sided sheet) keeps the lowest-index
    member's normal, which is deterministic and is all such a surface
    offers.
    """
    import numpy

    _, group_of_vertex = numpy.unique(points, axis=0, return_inverse=True)
    group_of_vertex = group_of_vertex.ravel()
    pooled = numpy.zeros((int(group_of_vertex.max()) + 1, 3), dtype=numpy.float64)
    numpy.add.at(pooled, group_of_vertex, normals)
    lengths = numpy.linalg.norm(pooled, axis=1)
    degenerate = lengths <= RADIAL_AXIS_EPSILON_M
    pooled[~degenerate] /= lengths[~degenerate][:, None]
    if bool(degenerate.any()):
        # The lowest-index member of each group, found with `minimum.at`
        # seeded above every index. Deterministic by index, which is the
        # only order a vertex list has.
        first_of_group = numpy.full(len(pooled), len(points), dtype=numpy.int64)
        numpy.minimum.at(first_of_group, group_of_vertex, numpy.arange(len(points)))
        fallback = normals[first_of_group]
        pooled[degenerate] = fallback[degenerate]
    return pooled[group_of_vertex]


def _displacement_directions(normals, points, mode):
    """One unit direction per vertex, for the three modes.

    Every direction is normalized where it can be, and a vertex with no
    direction at all (the axis for `radial`, a zero normal) travels along
    local Z instead of not moving: a vertex that cannot move where the
    mode says is still part of the surface.

    Each mode is a function of POSITION (or of a position-pooled normal),
    never of the vertex's index — that is what keeps coincident vertices
    together in all three.
    """
    import numpy

    if mode == "z":
        directions = numpy.zeros(points.shape, dtype=numpy.float64)
        directions[:, 2] = 1.0
        return directions

    if mode == "normal":
        directions = _position_pooled_normals(normals, points)
    else:  # "radial"
        directions = numpy.zeros(points.shape, dtype=numpy.float64)
        directions[:, 0] = points[:, 0]
        directions[:, 1] = points[:, 1]

    lengths = numpy.linalg.norm(directions, axis=1)
    usable = lengths > RADIAL_AXIS_EPSILON_M
    directions[usable] /= lengths[usable][:, None]
    directions[~usable] = (0.0, 0.0, 1.0)
    return directions


def _polygon_normals(mesh):
    """Every polygon's normal, as (faces, 3) float64."""
    import numpy

    normals = numpy.empty(len(mesh.polygons) * 3, dtype=numpy.float64)
    mesh.polygons.foreach_get("normal", normals)
    return normals.reshape(len(mesh.polygons), 3)


def _unmoved_report(object_name, seed, amplitude_m, frequency, mode):
    """The report for a call that moves nothing: `amplitude_m=0` or no vertices."""
    return RoughenReport(
        object_name=object_name,
        vertices_moved=0,
        max_displacement_m=0.0,
        rms_displacement_m=0.0,
        seed=int(seed),
        amplitude_m=amplitude_m,
        frequency=frequency,
        mode=mode,
        clamped_vertex_count=0,
        inverted_face_count=0,
    )


@op(gated=True)
def roughen_object(
    object_name: str,
    amplitude_m: float,
    frequency: float = 1.0,
    seed: int = 0,
    mode: Literal["radial", "normal", "z"] = "radial",
    clamp_to_ground: bool = True,
) -> RoughenReport:
    """Push vertices off the ideal surface by seeded position-hashed noise; the same seed repeats.

    `amplitude_m` is the RMS distance the surface moves, and `0` is a
    no-op that reports `vertices_moved: 0`. `frequency` multiplies the
    noise's 100 mm base cell, so a larger value gives chunkier lumps.
    `mode` is the direction each vertex travels: away from the object's
    own Z axis (`"radial"`), along its own normal (`"normal"`), or up
    (`"z"`). With `clamp_to_ground` a vertex is never left below the
    scene's floor, and a displacement that would fold a face is refused
    with `FaceInversion`, the mesh left as it was.
    """
    import bpy
    import numpy

    from golem_blender.ops._objects import object_by_name

    if amplitude_m < 0.0:
        raise ValueError(f"amplitude_m must be >= 0, got {amplitude_m}.")
    if frequency <= 0.0:
        raise ValueError(f"frequency must be > 0, got {frequency}.")
    if mode not in ROUGHEN_MODES:
        raise ValueError(f"mode must be one of {ROUGHEN_MODES}, got {mode!r}.")

    blender_object = object_by_name(object_name, "MESH")
    mesh = blender_object.data
    vertex_count = len(mesh.vertices)
    if amplitude_m == 0.0 or vertex_count == 0:
        return _unmoved_report(object_name, seed, amplitude_m, frequency, mode)

    original = numpy.empty(vertex_count * 3, dtype=numpy.float64)
    mesh.vertices.foreach_get("co", original)
    original = original.reshape(vertex_count, 3)
    # Read only where the mode wants it: `"z"` and `"radial"` have their
    # directions already, and a smoothed-normal array on a 500k-vertex
    # surface is not free.
    normals = None
    if mode == "normal":
        normals = numpy.empty(vertex_count * 3, dtype=numpy.float64)
        mesh.vertex_normals.foreach_get("vector", normals)
        normals = normals.reshape(vertex_count, 3)
    faces_before = _polygon_normals(mesh)

    noise = _noise_at(original, BASE_NOISE_CELL_M * frequency, int(seed) & 0xFFFFFFFF)
    sample_rms = float(numpy.sqrt(numpy.mean(noise * noise)))
    gain = min(amplitude_m / max(sample_rms, MINIMUM_NOISE_RMS), MAXIMUM_NOISE_GAIN)

    directions = _displacement_directions(normals, original, mode)
    displaced = original + directions * (noise * gain)[:, None]

    # The transform is read AFTER a view-layer update: measured in Blender
    # 5.2, `matrix_world` on a freshly moved object still reports the old
    # translation, and a clamp computed from it lifts to the wrong floor.
    bpy.context.view_layer.update()
    world = numpy.array(blender_object.matrix_world, dtype=numpy.float64)
    linear = world[:3, :3]
    clamped_vertex_count = 0
    if clamp_to_ground:
        world_z = displaced @ linear[2, :] + world[2, 3]
        below_floor = world_z < 0.0
        clamped_vertex_count = int(numpy.count_nonzero(below_floor))
        if clamped_vertex_count:
            # A pure world-Z lift, mapped into local space: M3⁻¹·(0,0,−z)
            # moves the vertex to exactly z=0 whatever M3's rotation and
            # scale are.
            local_z_axis = numpy.linalg.inv(linear) @ numpy.array([0.0, 0.0, 1.0])
            displaced[below_floor] += (-world_z[below_floor])[:, None] * local_z_axis[
                None, :
            ]

    world_moves = (displaced - original) @ linear.T
    distances = numpy.linalg.norm(world_moves, axis=1)

    mesh.vertices.foreach_set("co", displaced.ravel())
    mesh.update()
    bpy.context.view_layer.update()
    faces_after = _polygon_normals(mesh)
    inverted_face_count = int(
        numpy.count_nonzero(
            (numpy.linalg.norm(faces_before, axis=1) > 0.0)
            & ((faces_before * faces_after).sum(axis=1) < FACE_INVERSION_COSINE)
        )
    )
    if inverted_face_count > MAXIMUM_INVERTED_FACE_COUNT:
        mesh.vertices.foreach_set("co", original.ravel())
        mesh.update()
        bpy.context.view_layer.update()
        raise FaceInversion(
            f"{object_name}: amplitude_m={amplitude_m} at frequency={frequency}, "
            f"seed={seed} would invert {inverted_face_count} face(s) "
            f"(allowance {MAXIMUM_INVERTED_FACE_COUNT}); the mesh is unchanged. "
            f"Lower amplitude_m, raise frequency so the field is smoother across "
            f"a face, or subdivide the surface first."
        )

    return RoughenReport(
        object_name=object_name,
        # A vertex the field happened to leave exactly where it was did not
        # move, and a count that included it would overstate the surface.
        vertices_moved=int(numpy.count_nonzero(distances > 0.0)),
        max_displacement_m=float(distances.max()),
        rms_displacement_m=float(numpy.sqrt(numpy.mean(distances * distances))),
        seed=int(seed),
        amplitude_m=amplitude_m,
        frequency=frequency,
        mode=mode,
        clamped_vertex_count=clamped_vertex_count,
        inverted_face_count=inverted_face_count,
    )
