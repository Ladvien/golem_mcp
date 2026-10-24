"""Lathe (surface of revolution) built ring-by-ring with bmesh.

The general op behind barrels, bottles, columns, wheels: give it a 2D
profile of (radius_m, z_m) points and it revolves them around Z. Ends
with radius > 0 are capped with triangle fans so the result is closed,
unless the caller opens one of them; a ring's own closed cross-section
is revolved as it stands and needs no cap at all.

`add_shell_lathe` revolves a WALL instead of a surface: give it the
OUTER profile and a thickness, and it builds the inner surface by
offsetting the profile inward. A basin, a wash boiler or a stone ring
comes out hollow that way, where a capped lathe would come out lidded
and read as a ball.

Deterministic, context-free, idempotent by name.
"""

from __future__ import annotations

import itertools
import math

from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName

MINIMUM_PROFILE_POINTS = 2
MINIMUM_SEGMENTS = 3
# Two profile points closer than this, in BOTH radius and height, are the
# same point. A ring's cross-section repeats its first point at the end,
# and revolving that repeat would build a second ring of vertices on top
# of the first: a duplicated seam with zero-area faces down it.
PROFILE_POINT_TOLERANCE_M = 1.0e-6
# A corner sharper than this turns the inward offset into a spike (a miter
# is 1/cos of the half-angle, unbounded at a needle corner), so the miter is
# capped at this many wall thicknesses: a sharp corner thins the wall
# locally instead of throwing the inner surface past the axis.
MAXIMUM_MITER_FACTOR = 3.0


@op(gated=False)
def add_lathe(
    name: str,
    profile_m: list[tuple[float, float]],
    segment_count: int = 24,
    cap_start: bool = True,
    cap_end: bool = True,
) -> ObjectName:
    """Revolve `profile_m` [(radius_m, z_m), ...] around Z into a mesh object, capped by default.

    The profile is shifted so its lowest point sits at z=0, the convention
    every other constructor follows, and the object comes back unlinked
    like `add_box` and `add_cylinder`.

    `cap_start` and `cap_end` say whether the bottom and the top end get a
    triangle fan. `cap_end=False` leaves the mouth open at the profile's
    own top radius, which is what a barrel, a cup or a chimney wants; the
    mesh then has one boundary loop there and is not closed, so it fails a
    gate that demands a watertight solid. Pass both False for an open tube.

    Radii must be positive: a point on the axis is what a cap already
    supplies, so a zero-radius point would only be a pinch. Heights must be
    non-decreasing, because revolving an out-of-order profile folds the
    surface over itself.

    A profile that repeats its first point at the end is a CLOSED
    cross-section — a ring, a torus, a tyre — and is revolved as it
    stands: it is already a closed surface, so neither cap flag applies
    and an open flag cannot punch a hole in it. Its heights necessarily
    come back down, which is why the ordering rule does not apply to it.
    """
    import bmesh
    import bpy

    from golem_blender.ops.primitives import remove_object_and_mesh

    _check_profile_shape(profile_m, segment_count)
    if any(radius_m <= 0.0 for radius_m, _ in profile_m):
        raise ValueError(
            "Profile radii must be positive; poles are added automatically."
        )
    closes_on_itself = _closes_on_itself(profile_m)
    if closes_on_itself:
        if len(profile_m) < 4:
            raise ValueError(
                "A closed profile (one that repeats its first point) needs at "
                "least four points to enclose an area."
            )
        # Drop the repeated point: its ring IS the first ring, and the
        # wrap builds the closing band.
        cross_section_m = list(profile_m[:-1])
    else:
        _check_ordered_by_height(profile_m)
        cross_section_m = list(profile_m)
    cross_section_m = _based_profile(cross_section_m)

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    lathe_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        _revolve(
            working_mesh,
            cross_section_m,
            segment_count,
            closed=closes_on_itself,
            cap_start=cap_start,
            cap_end=cap_end,
        )
        bmesh.ops.recalc_face_normals(working_mesh, faces=working_mesh.faces)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return lathe_object.name


@op(gated=False)
def add_shell_lathe(
    name: str,
    profile_m: list[tuple[float, float]],
    wall_m: float,
    segment_count: int = 24,
    open_top: bool = True,
) -> ObjectName:
    """Revolve `profile_m` into a wall `wall_m` thick, base at z=0, mouth open by default.

    `profile_m` is the OUTER profile [(radius_m, z_m), ...], ordered by
    height; radius 0 is a point on the axis, which is how a basin's floor
    starts. The inner surface is that profile offset inward by `wall_m`
    with mitred corners, so the wall measures `wall_m` perpendicular to
    the surface, not merely across a vertical stretch.

    `open_top=True` (the default) leaves the mouth open: the rim is an
    annulus one wall wide, the inside is visible, and the mesh is a single
    closed manifold piece. `open_top=False` fills the mouth instead, so
    the result is the SOLID revolve `add_lathe` gives — a sealed cavity
    would be a second surface, and the gate counts a second surface as a
    second component.

    `wall_m` must be less than the profile's smallest positive radius: a
    thicker wall would invert the inner profile rather than shell it, and
    that is refused by both values instead of shipped as inside-out
    geometry. A radius of 0 stays on the axis, where there is no inward
    direction to offset along, so the cavity's floor centre sits `wall_m`
    ABOVE the base's own centre — a bowl's floor is solid under its
    middle, which is what a floor is.

    The profile is shifted so its lowest point sits at z=0, and the object
    comes back unlinked like every other constructor.
    """
    import bmesh
    import bpy

    from golem_blender.ops.primitives import remove_object_and_mesh

    _check_profile_shape(profile_m, segment_count)
    if any(radius_m < 0.0 for radius_m, _ in profile_m):
        raise ValueError(
            "Shell profile radii cannot be negative; a point on the axis is 0."
        )
    _check_ordered_by_height(profile_m)
    if wall_m <= 0.0:
        raise ValueError(f"wall_m must be positive; got {wall_m:g}.")
    positive_radii_m = [radius_m for radius_m, _ in profile_m if radius_m > 0.0]
    smallest_radius_m = min(positive_radii_m) if positive_radii_m else 0.0
    if wall_m >= smallest_radius_m:
        raise ValueError(
            f"wall_m {wall_m:g} must be less than the profile's smallest radius "
            f"{smallest_radius_m:g}; a thicker wall inverts the inner profile."
        )

    outer_profile_m = _based_profile(list(profile_m))
    inner_profile_m = _inner_profile(outer_profile_m, wall_m)

    if open_top:
        # The generating cross-section of the wall itself: up the outside,
        # across the rim, back down the inside. Closed, so it needs no caps,
        # and the only face at the top is the rim — nothing spans the mouth.
        cross_section_m = outer_profile_m + list(reversed(inner_profile_m))
        closed = True
        cap_start = cap_end = False
    else:
        cross_section_m = outer_profile_m
        closed = False
        cap_start = cap_end = True

    remove_object_and_mesh(name)
    mesh_data = bpy.data.meshes.new(name)
    lathe_object = bpy.data.objects.new(name, mesh_data)

    working_mesh = bmesh.new()
    try:
        _revolve(
            working_mesh,
            cross_section_m,
            segment_count,
            closed=closed,
            cap_start=cap_start,
            cap_end=cap_end,
        )
        bmesh.ops.recalc_face_normals(working_mesh, faces=working_mesh.faces)
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()

    return lathe_object.name


# --- profile rules ---------------------------------------------------------


def _check_profile_shape(
    profile_m: list[tuple[float, float]], segment_count: int
) -> None:
    if len(profile_m) < MINIMUM_PROFILE_POINTS:
        raise ValueError("Lathe profile needs at least two points.")
    if segment_count < MINIMUM_SEGMENTS:
        raise ValueError("Lathe needs at least three segments.")
    for radius_m, height_z_m in profile_m:
        if not (math.isfinite(radius_m) and math.isfinite(height_z_m)):
            raise ValueError(
                f"Lathe profile point ({radius_m!r}, {height_z_m!r}) is not finite."
            )


def _check_ordered_by_height(profile_m: list[tuple[float, float]]) -> None:
    """Revolving an out-of-order profile folds the surface over itself."""
    for index in range(1, len(profile_m)):
        previous_z_m = profile_m[index - 1][1]
        this_z_m = profile_m[index][1]
        if this_z_m < previous_z_m - PROFILE_POINT_TOLERANCE_M:
            raise ValueError(
                f"Lathe profile points must be ordered by height (z "
                f"non-decreasing): point {index} has z={this_z_m:g} after "
                f"z={previous_z_m:g}. Re-order the profile, or make it a "
                f"closed one by repeating its first point at the end."
            )


def _closes_on_itself(profile_m: list[tuple[float, float]]) -> bool:
    """Does the profile repeat its first point at the end (a ring's section)?"""
    first_radius_m, first_z_m = profile_m[0]
    last_radius_m, last_z_m = profile_m[-1]
    return (
        abs(first_radius_m - last_radius_m) <= PROFILE_POINT_TOLERANCE_M
        and abs(first_z_m - last_z_m) <= PROFILE_POINT_TOLERANCE_M
    )


def _based_profile(
    profile_m: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Shift the profile so its lowest point sits at z=0."""
    base_z_m = min(height_z_m for _, height_z_m in profile_m)
    return [(radius_m, height_z_m - base_z_m) for radius_m, height_z_m in profile_m]


def _segment_normals(
    profile_m: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """The inward normal of each segment, as (radius, z).

    Read bottom-to-top, the LEFT normal of the tangent points at the
    inside of the piece: toward the axis along a vertical wall, and up
    along a horizontal floor.
    """
    normals: list[tuple[float, float]] = []
    for (start_radius_m, start_z_m), (end_radius_m, end_z_m) in itertools.pairwise(
        profile_m
    ):
        delta_radius_m = end_radius_m - start_radius_m
        delta_z_m = end_z_m - start_z_m
        length_m = math.hypot(delta_radius_m, delta_z_m)
        if length_m <= PROFILE_POINT_TOLERANCE_M:
            raise ValueError(
                f"Lathe profile repeats the point ({start_radius_m:g}, "
                f"{start_z_m:g}), so two of its points describe one segment; "
                f"remove one."
            )
        normals.append((-delta_z_m / length_m, delta_radius_m / length_m))
    return normals


def _offset_profile_inward(
    profile_m: list[tuple[float, float]], wall_m: float
) -> list[tuple[float, float]]:
    """The profile moved `wall_m` toward the cavity, mitred corner by corner.

    An inside corner takes both neighbours' normals averaged and scaled by
    1/cos(half-angle), so its distance from BOTH segments is exactly
    `wall_m`; the scale is capped at MAXIMUM_MITER_FACTOR. The two ends
    take their single neighbour's normal, which is what makes a straight
    wall measure `wall_m` right up to the rim.
    """
    segment_normals = _segment_normals(profile_m)
    offset_points: list[tuple[float, float]] = []
    for index, (radius_m, height_z_m) in enumerate(profile_m):
        if index == 0:
            normal_radius, normal_z = segment_normals[0]
            miter_scale = 1.0
        elif index == len(profile_m) - 1:
            normal_radius, normal_z = segment_normals[-1]
            miter_scale = 1.0
        else:
            previous_normal = segment_normals[index - 1]
            following_normal = segment_normals[index]
            sum_radius = previous_normal[0] + following_normal[0]
            sum_z = previous_normal[1] + following_normal[1]
            sum_length = math.hypot(sum_radius, sum_z)
            if sum_length <= PROFILE_POINT_TOLERANCE_M:
                # The profile doubles back: there is no inside corner to
                # mitre, so keep the segment that arrives at the point.
                normal_radius, normal_z = previous_normal
                miter_scale = 1.0
            else:
                normal_radius = sum_radius / sum_length
                normal_z = sum_z / sum_length
                cosine = (
                    normal_radius * previous_normal[0] + normal_z * previous_normal[1]
                )
                miter_scale = min(
                    MAXIMUM_MITER_FACTOR,
                    1.0 / max(cosine, 1.0 / MAXIMUM_MITER_FACTOR),
                )
        offset_points.append(
            (
                radius_m + wall_m * miter_scale * normal_radius,
                height_z_m + wall_m * miter_scale * normal_z,
            )
        )
    return offset_points


def _inner_profile(
    outer_profile_m: list[tuple[float, float]], wall_m: float
) -> list[tuple[float, float]]:
    """The cavity's own profile: the outer one offset inward by `wall_m`."""
    inner_profile_m: list[tuple[float, float]] = []
    for (outer_radius_m, outer_z_m), (inner_radius_m, inner_z_m) in zip(
        outer_profile_m, _offset_profile_inward(outer_profile_m, wall_m), strict=True
    ):
        if outer_radius_m <= PROFILE_POINT_TOLERANCE_M:
            # A point on the axis stays on it, and its height is the
            # offset's own (the base's centre, wall_m up): a radius has no
            # inward direction there. Never below the outer surface either,
            # because the piece's lowest point is the outer profile's.
            inner_profile_m.append((0.0, max(inner_z_m, outer_z_m)))
            continue
        if inner_radius_m < 0.0:
            raise ValueError(
                f"wall_m {wall_m:g} drives the inner radius to {inner_radius_m:g} "
                f"at z {outer_z_m:g}, where the outer radius is "
                f"{outer_radius_m:g}; the wall is thicker than the piece at "
                f"that point."
            )
        inner_profile_m.append((inner_radius_m, inner_z_m))
    return inner_profile_m


# --- the revolve -----------------------------------------------------------


def _revolve(
    working_mesh,
    cross_section_m: list[tuple[float, float]],
    segment_count: int,
    *,
    closed: bool,
    cap_start: bool,
    cap_end: bool,
) -> None:
    """Revolve one generating polyline (or a closed section) around Z."""
    rings = [
        _ring(working_mesh, radius_m, height_z_m, segment_count)
        for radius_m, height_z_m in cross_section_m
    ]
    spans = list(itertools.pairwise(rings))
    if closed:
        spans.append((rings[-1], rings[0]))
    for lower_ring, upper_ring in spans:
        _bridge(working_mesh, lower_ring, upper_ring, segment_count)
    if closed:
        return
    if cap_start:
        _cap(working_mesh, rings[0], segment_count, at_the_bottom=True)
    if cap_end:
        _cap(working_mesh, rings[-1], segment_count, at_the_bottom=False)


def _ring(working_mesh, radius_m: float, height_z_m: float, segment_count: int):
    """One ring of `segment_count` vertices; a point on the axis is ONE pole.

    A ring of coincident vertices at radius 0 would make zero-area faces
    all the way round, which the gate counts as a defect, so radius 0 is a
    single vertex. `add_lathe` refuses radius 0 (a cap supplies the pole),
    but a SHELL profile legitimately starts on the axis at its floor.
    """
    if radius_m <= PROFILE_POINT_TOLERANCE_M:
        return [working_mesh.verts.new((0.0, 0.0, height_z_m))]
    return [
        working_mesh.verts.new(
            (
                radius_m * math.cos((segment_index / segment_count) * math.tau),
                radius_m * math.sin((segment_index / segment_count) * math.tau),
                height_z_m,
            )
        )
        for segment_index in range(segment_count)
    ]


def _bridge(working_mesh, lower_ring, upper_ring, segment_count: int) -> None:
    """Quads between two rings, or a fan where one of them is a pole."""
    lower_is_pole = len(lower_ring) == 1
    upper_is_pole = len(upper_ring) == 1
    if lower_is_pole and upper_is_pole:
        # A segment that runs along the axis has no surface at all.
        return
    for segment_index in range(segment_count):
        next_index = (segment_index + 1) % segment_count
        if lower_is_pole:
            working_mesh.faces.new(
                (lower_ring[0], upper_ring[next_index], upper_ring[segment_index])
            )
        elif upper_is_pole:
            working_mesh.faces.new(
                (upper_ring[0], lower_ring[segment_index], lower_ring[next_index])
            )
        else:
            working_mesh.faces.new(
                (
                    lower_ring[segment_index],
                    lower_ring[next_index],
                    upper_ring[next_index],
                    upper_ring[segment_index],
                )
            )


def _cap(working_mesh, ring, segment_count: int, *, at_the_bottom: bool) -> None:
    """Close one end with a triangle fan to a pole vertex."""
    pole_vertex = working_mesh.verts.new((0.0, 0.0, ring[0].co.z))
    for segment_index in range(segment_count):
        next_index = (segment_index + 1) % segment_count
        if at_the_bottom:
            triangle = (pole_vertex, ring[next_index], ring[segment_index])
        else:
            triangle = (pole_vertex, ring[segment_index], ring[next_index])
        working_mesh.faces.new(triangle)
