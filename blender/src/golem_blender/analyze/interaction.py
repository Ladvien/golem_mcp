"""Can a character REACH the side of this asset it is meant to use?

Measured need, 2026-10-24, in a live session: a bakery assembled from
kit pieces had its ovens facing each other and its spout buried in the
wall. Every gate passed. `MeshBudget` measures one mesh; the assembly
gate measures parts, laps and support; the visual gate measures pixels
against a reference. NONE of them knows which side of the asset a
character stands on, so an asset can be structurally perfect and face
the wall. The user found it by looking, twice.

WHY THIS IS A DECLARATION, NOT AN INFERENCE. Four geometric probes were
built against that same bakery's own pieces (oven, wall with a door,
spout, hopper, shelf, barrel, table) before this module was written, and
every one of them failed to tell the two apart:

1. rays inward from each of the six AABB faces — the faces are in the
   OBJECT frame while the pieces are rotated, so the probe read the
   world, not the piece;
2. the same in world space — an absolute "set back" threshold called an
   open table front and a hollow barrel openings, and a door's thin rim
   a solid face;
3. the same in the piece's LOCAL frame (the frame kit.yaml writes
   `front: "-Y"` in) — a table, a barrel, a hopper and a shelf's open
   front all scored as enclosed openings, while a wall's own door read
   ZERO because its rim is only 0.27 solid;
4. a rim-solid + set-back discriminator — 0.00 for every real opening
   and 0.66 for a shelf's back.

An opening is not recoverable from triangles: the difference between a
door and a hole in a box is which face a character is meant to approach,
and that is intent. `units.yaml` already carries it as `front: "-Y"`, and
the kitbash procedure already says "if the piece's front is not facing
-Y" — prose nothing measured. So the side is DECLARED (the piece's local
-Y, or a named side per part), and what this module measures is the
thing that can be measured: how much clear space that side actually has.

WHAT IS MEASURED. For a declared interaction side, a grid of rays is
cast OUTWARD from the side's face plane, against every OTHER part of the
assembly. Each ray returns the distance to the first thing it meets, so
the result is a profile of the clear approach, not one number that hides
a single buried pipe. Two failure shapes come out of it:

- BLOCKED: part of the interaction face has less than
  `MINIMUM_APPROACH_M` of clear space. A character cannot stand there,
  and a drawer, door or oven mouth cannot open.
- BURIED: the whole face has no clear space at all — the part is inside
  or against another part, which is what a spout sunk into a wall is.

Both thresholds are deliberately generous (a 1.8 m character needs
0.6 m to stand, and the bakery's real defects measured 0.10 m), so this
reports what a player would call "facing the wall", not a tolerance
quibble. `clearance_m` is reported alongside so a caller can judge a
tighter case itself rather than trusting the verdict alone.

WHY IT IS OPT-IN, AND WHY THE ASSEMBLY SAYS SO. The first version checked
every part's `front` by default and failed a WALL for having a crate 0.2 m
from it — measurably, on the 49-part building fixture (`WallWest0`, 75% of
the side inside 0.6 m). A crate beside a wall is not a defect, and a set of
parts is not automatically an asset a character walks up to. So an assembly
CLAIMS its interaction side (`define_assembly(interaction_side=...)`) and
only then is every part measured; with no claim, nothing is measured and
nothing is reported. A part may override the side it personally presents
(`declare_interaction_side`), which is also the one call that repairs a
false positive: a hutch whose own front points at the desk it stands on
declares `back` and reads clear.

MAIN THREAD ONLY: every call below touches bpy/mathutils.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# The sides of an asset, named the way `units.yaml` and `capture.views`
# name them. `front` is the documented interaction side (units.yaml
# `front: "-Y"`); the other five exist so a part can declare a different
# one (a shelf's opening faces +Z, a chimney's flue faces +Z).
INTERACTION_SIDES = ("front", "back", "left", "right", "top", "bottom")

# The axis direction each side faces, in the object's LOCAL frame. These
# are the same directions `capture.views.VIEW_DIRECTIONS` looks FROM, so a
# `front` render and a `front` interaction side are the same side of the
# asset: one place decides it.
SIDE_LOCAL_NORMAL = {
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0),
    "bottom": (0.0, 0.0, -1.0),
}

# How many rays across each side. 12 x 12 = 144 resolves a door-width
# hole (0.6 m across a 2 m wall is ~4 cells) without turning a cheap
# measurement into a per-triangle sweep.
CLEARANCE_GRID = 12
# The clear space a 1.8 m character needs to approach and use a side.
MINIMUM_APPROACH_M = 0.6
# Rays start this far off the face so a ray never hits its own part's
# plane, and a face is never reported as blocking itself.
RAY_OFFSET_M = 0.002
# Two faces closer than this are the same plane: a part resting against
# another is not "buried", it is touching, and touching is legal.
TOUCHING_TOLERANCE_M = 1.0e-3
# A face is BURIED when this little of it has any clear space at all.
BURIED_CLEAR_FRACTION = 0.02


@dataclass(frozen=True)
class SideAccess:
    """How much clear space one declared interaction side of one part has."""

    object_name: str
    side: str
    # The side's outward direction in WORLD space, and its bearing on the
    # XY plane in degrees (0 = -Y, the documented front, turning towards
    # +X). Reported so a caller can see which way the asset ended up.
    normal: tuple[float, float, float]
    bearing_deg: float
    # The clear distance per ray: the median and the worst, in metres.
    # `clearance_m` is the MEDIAN because a single decorative bracket in
    # front of a barn door must not read as the whole side being blocked.
    clearance_m: float
    minimum_clearance_m: float
    # How much of the side has less than MINIMUM_APPROACH_M of space.
    blocked_fraction: float
    # The parts standing in the way, nearest first, with their distance.
    blocked_by: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class InteractionReport:
    """Every declared interaction side of every part, and which ones a character cannot reach."""

    assembly_name: str
    sides: tuple[SideAccess, ...]
    # The sides that fail: the whole face buried, or a large part of it
    # inside MINIMUM_APPROACH_M. Empty means every declared side is usable.
    blocked: tuple[SideAccess, ...]


def _side_normal_world(blender_object, side: str) -> tuple[float, float, float]:
    """The side's outward direction in world space, from the object's own rotation."""
    local = SIDE_LOCAL_NORMAL[side]
    rotation = blender_object.matrix_world.to_3x3()
    world = rotation @ _vector(local)
    length = math.sqrt(sum(component * component for component in world))
    if length <= 0.0:
        raise ValueError(
            f"{blender_object.name!r} has a degenerate rotation, so side "
            f"{side!r} has no direction"
        )
    return tuple(component / length for component in world)


def _vector(values):
    """A mathutils Vector, imported here so this module imports without bpy."""
    from mathutils import Vector

    return Vector(values)


def _world_faces(blender_object):
    """(the eight world corners, their minimum and maximum) of an evaluated object's box."""
    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([blender_object])
    corners = [
        _vector(
            (
                minimum[0] if low_x else maximum[0],
                minimum[1] if low_y else maximum[1],
                minimum[2] if low_z else maximum[2],
            )
        )
        for low_x in (True, False)
        for low_y in (True, False)
        for low_z in (True, False)
    ]
    return corners, minimum, maximum


def _face_centre_and_spans(corners, normal):
    """(the side's face centre, its half-extents along two spans) of a box side.

    The face plane is the four corners furthest along `normal`, and the face
    centre is THEIR centroid. Taking the furthest corner instead — the
    obvious one-liner — centres the ray grid on a corner, so half of it falls
    outside the part and a fully blocked side reads as a quarter blocked.
    """
    projections = [corner.dot(normal) for corner in corners]
    furthest = max(projections)
    face_corners = [
        corner
        for corner, projection in zip(corners, projections)
        if abs(projection - furthest) <= 1.0e-6
    ]
    face_centre = sum(face_corners, _vector((0.0, 0.0, 0.0))) / len(face_corners)
    span_u, span_v = _side_frame(normal)
    half_u = max(abs((corner - face_centre).dot(span_u)) for corner in face_corners)
    half_v = max(abs((corner - face_centre).dot(span_v)) for corner in face_corners)
    return face_centre, half_u, half_v


def _bearing_deg(normal: tuple[float, float, float]) -> float:
    """The side's compass bearing: 0 degrees faces -Y (the documented front)."""
    bearing = math.degrees(math.atan2(normal[0], -normal[1])) % 360.0
    return round(bearing, 1)


def _side_frame(normal):
    """Two unit vectors spanning the plane perpendicular to `normal`."""
    helper = _vector((0.0, 0.0, 1.0))
    if abs(normal.dot(helper)) > 0.9:
        helper = _vector((1.0, 0.0, 0.0))
    span_u = normal.cross(helper).normalized()
    span_v = normal.cross(span_u).normalized()
    return span_u, span_v


def _world_bvhs(blender_objects) -> dict[str, object]:
    """One world-space BVH per object, so a ray and a hit share a frame.

    `BVHTree.FromObject` builds in the OBJECT's local space, so using it
    with a world-space ray origin silently measures something the viewport
    does not show (this was the second of the four failed probes). The
    triangles are transformed here instead, exactly as `analyze.pair_checks`
    does for its own world-space queries.
    """
    import bpy
    from mathutils.bvhtree import BVHTree

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    trees = {}
    for blender_object in blender_objects:
        evaluated = blender_object.evaluated_get(dependency_graph)
        mesh = evaluated.to_mesh()
        try:
            world_matrix = blender_object.matrix_world
            vertices = [world_matrix @ vertex.co for vertex in mesh.vertices]
            mesh.calc_loop_triangles()
            triangles = [
                tuple(loop_triangle.vertices) for loop_triangle in mesh.loop_triangles
            ]
        finally:
            evaluated.to_mesh_clear()
        trees[blender_object.name] = (
            BVHTree.FromPolygons(vertices, triangles) if triangles else None
        )
    return trees


def _side_access(
    blender_object,
    side: str,
    others,
    other_trees: dict[str, object],
    *,
    clearance_grid: int,
    minimum_approach_m: float,
) -> SideAccess:
    """Cast the grid of rays outward from one declared side of one part."""
    normal = _vector(_side_normal_world(blender_object, side))
    corners, _minimum, _maximum = _world_faces(blender_object)
    face_centre, half_u, half_v = _face_centre_and_spans(corners, normal)
    span_u, span_v = _side_frame(normal)

    # How far to look: far enough to prove the side is usable, and no
    # further, so an open field does not cost a ray travelling to infinity.
    reach_m = max(minimum_approach_m * 2.5, 1.0)
    clearances: list[float] = []
    blockers: dict[str, float] = {}
    for index_u in range(clearance_grid):
        for index_v in range(clearance_grid):
            offset_u = ((index_u + 0.5) / clearance_grid * 2.0 - 1.0) * half_u
            offset_v = ((index_v + 0.5) / clearance_grid * 2.0 - 1.0) * half_v
            origin = (
                face_centre
                + span_u * offset_u
                + span_v * offset_v
                + normal * RAY_OFFSET_M
            )
            nearest_m = reach_m
            nearest_name = ""
            for other in others:
                tree = other_trees.get(other.name)
                if tree is None:
                    continue
                hit, _hit_normal, _index, distance = tree.ray_cast(origin, normal)
                if hit is not None and distance < nearest_m:
                    nearest_m = float(distance)
                    nearest_name = other.name
            clearances.append(nearest_m)
            if nearest_name and nearest_m < minimum_approach_m:
                blockers[nearest_name] = min(
                    blockers.get(nearest_name, nearest_m), nearest_m
                )

    clearances.sort()
    blocked_count = sum(1 for clearance in clearances if clearance < minimum_approach_m)
    return SideAccess(
        object_name=blender_object.name,
        side=side,
        normal=tuple(round(component, 4) for component in normal),
        bearing_deg=_bearing_deg(tuple(normal)),
        clearance_m=round(clearances[len(clearances) // 2], 4),
        minimum_clearance_m=round(clearances[0], 4),
        blocked_fraction=round(blocked_count / len(clearances), 4),
        blocked_by=tuple(
            (name, round(distance, 4))
            for name, distance in sorted(blockers.items(), key=lambda item: item[1])
        ),
    )


def _is_blocked(access: SideAccess, minimum_approach_m: float) -> bool:
    """Is this side unusable? Buried entirely, or most of it inside the approach distance."""
    buried = (
        access.minimum_clearance_m <= TOUCHING_TOLERANCE_M
        and access.blocked_fraction >= 1.0 - BURIED_CLEAR_FRACTION
    )
    return buried or access.blocked_fraction > 0.5


def measure_interaction_sides(
    assembly_name: str,
    parts,
    declared_sides: dict[str, str],
    *,
    clearance_grid: int = CLEARANCE_GRID,
    minimum_approach_m: float = MINIMUM_APPROACH_M,
) -> InteractionReport:
    """Measure every declared interaction side of `parts` against the others.

    `declared_sides` maps a part name to the side a character uses; a part
    absent from it declares nothing and is not measured. The assembly's
    OWN default is applied by the caller (`define_assembly`), so this
    function measures exactly the sides it is given and never invents one.
    """
    for object_name, side in declared_sides.items():
        if side not in SIDE_LOCAL_NORMAL:
            raise ValueError(
                f"{object_name!r} declares interaction side {side!r}, which is "
                f"not one of {list(INTERACTION_SIDES)}"
            )
    other_trees = _world_bvhs(parts)
    sides: list[SideAccess] = []
    blocked: list[SideAccess] = []
    for blender_object in parts:
        side = declared_sides.get(blender_object.name)
        if side is None:
            continue
        access = _side_access(
            blender_object,
            side,
            [other for other in parts if other.name != blender_object.name],
            other_trees,
            clearance_grid=clearance_grid,
            minimum_approach_m=minimum_approach_m,
        )
        sides.append(access)
        if _is_blocked(access, minimum_approach_m):
            blocked.append(access)
    return InteractionReport(
        assembly_name=assembly_name,
        sides=tuple(sides),
        blocked=tuple(blocked),
    )
