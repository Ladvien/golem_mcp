"""Pairwise checks between two parts of an assembly: interpenetration
and surface separation.

The assembly briefs relate parts by position (StackedOnSpec,
SharedCentreSpec); nothing measures whether one part intersects
another. scp built the equivalent check against mesh VERTICES first and
it lied: palm-to-weapon distance read 60 mm against vertices and 6.5 mm
against the mesh SURFACE, because on box geometry the nearest vertex is
a far corner. So separation is measured on the surface, never on
vertices.

Interpenetration is a DEPTH, not a face count. Two parts that rest on
each other (a lid on its crate's rim) legitimately share coplanar
faces and even interpenetrate by the resting tolerance (the golden
crate's lid sits ~1 mm into the rim and was human-signed-off). The
face-pair crossing tests fail to distinguish: on axis-aligned boxes
every penetrating face pair touches the other solid along a
zero-depth line. So the measurement is the object-level penetration —
the minimum translation depth between the two evaluated meshes' world
AABBs — and a pair count is reported only when that depth exceeds the
contact tolerance. The count itself is the
`BVHTree.overlap` pair list, the same query `_count_self_intersecting_pairs`
uses; it reports triangle pairs that actually intersect (measured in
Blender 5.2: disjoint triangles whose bounding boxes overlap are NOT
reported, and exactly-coplanar triangles are never reported).

MAIN THREAD ONLY: everything below touches bpy/mathutils.
"""

from __future__ import annotations

from dataclasses import dataclass

# Separation samples are capped so a dense mesh does not make the
# measurement O(vertices) against the other object's BVH.
PAIR_SEPARATION_SAMPLE_LIMIT = 512

# How deep a penetration must be to count as interpenetration rather
# than resting contact. Matches the crate-with-lid stack tolerance
# (GROUNDING_TOLERANCE_M): a lidar sunk up to 2 mm into the rim reads
# as "resting on", anything deeper reads as "sunk into".
CONTACT_DEPTH_TOLERANCE_M = 0.002


@dataclass(frozen=True)
class PairReport:
    first_object_name: str
    second_object_name: str
    intersecting_face_pair_count: int
    minimum_separation_m: float
    aabb_penetration_depth_m: float


def _world_bounds(first_mesh, first_to_world, second_mesh, second_to_world):
    """Per-axis world-space min/max for both evaluated meshes."""
    first_minima = [float("inf")] * 3
    first_maxima = [-float("inf")] * 3
    for vertex in first_mesh.vertices:
        world = first_to_world @ vertex.co
        for axis in range(3):
            first_minima[axis] = min(first_minima[axis], world[axis])
            first_maxima[axis] = max(first_maxima[axis], world[axis])
    second_minima = [float("inf")] * 3
    second_maxima = [-float("inf")] * 3
    for vertex in second_mesh.vertices:
        world = second_to_world @ vertex.co
        for axis in range(3):
            second_minima[axis] = min(second_minima[axis], world[axis])
            second_maxima[axis] = max(second_maxima[axis], world[axis])
    return (
        (first_minima, first_maxima),
        (second_minima, second_maxima),
    )


def _penetration_depth_m(first_bounds, second_bounds) -> float:
    """The minimum translation depth of the two AABB solids, or 0.0
    when they do not overlap. For the crate: the lidar's bottom enters
    the body's rim by the vertical sink (0.001 m in the golden, 0.03 m
    when sunk); for two overlapping boxes: the shared x extent.
    """
    (first_minima, first_maxima), (second_minima, second_maxima) = (
        first_bounds,
        second_bounds,
    )
    overlaps = []
    for axis in range(3):
        overlap = min(first_maxima[axis], second_maxima[axis]) - max(
            first_minima[axis], second_minima[axis]
        )
        if overlap <= 0.0:
            return 0.0  # separated on this axis: no interpenetration
        overlaps.append(overlap)
    return min(overlaps)


def _sampled_minimum_distance_m(
    query_mesh, query_to_world, target_evaluated, target_to_world
) -> float | None:
    """World distance from the query mesh's sampled vertices to the
    target object's SURFACE, or None when the query mesh has no
    vertices or no closest-point query ever lands.

    Samples every ``ceil(count / PAIR_SEPARATION_SAMPLE_LIMIT)``-th
    vertex so a dense mesh does not make the measurement
    O(vertices) against the other object's BVH. The step is re-derived
    from the caller's own mesh, so the limit is PER DIRECTION:
    ``analyze_pair`` calls this twice and samples at most
    ``2 * PAIR_SEPARATION_SAMPLE_LIMIT`` points.
    ``closest_point_on_mesh`` is an OBJECT method and wants the point
    in the target's LOCAL space; the distance is taken back in world
    space so a scaled object cannot flatter itself.
    """
    vertex_count = len(query_mesh.vertices)
    if not vertex_count:
        return None
    target_to_local = target_to_world.inverted()
    sample_step = (
        1
        if vertex_count <= PAIR_SEPARATION_SAMPLE_LIMIT
        else -(-vertex_count // PAIR_SEPARATION_SAMPLE_LIMIT)
    )
    minimum_world_distance = None
    for vertex_index in range(0, vertex_count, sample_step):
        world_point = query_to_world @ query_mesh.vertices[vertex_index].co
        target_local_point = target_to_local @ world_point
        hit, location, _normal, _index = target_evaluated.closest_point_on_mesh(
            target_local_point
        )
        if not hit:
            continue
        world_closest = target_to_world @ location
        distance_m = (world_closest - world_point).length
        if minimum_world_distance is None or distance_m < minimum_world_distance:
            minimum_world_distance = distance_m
    return minimum_world_distance


def analyze_pair(first_object, second_object) -> PairReport:
    """Measure one object against another.

    ``intersecting_face_pair_count``: the `BVHTree.overlap` triangle pairs
    of the two evaluated meshes' world-space triangles (pairs that
    actually intersect, not merely pairs with overlapping bounding boxes),
    but only when the object-level penetration depth exceeds
    ``CONTACT_DEPTH_TOLERANCE_M``. Resting contact (a lidar on its
    crate, sink within 2 mm) reads zero.

    ``minimum_separation_m``: each object's evaluated vertices in world
    space (all of them when under ``PAIR_SEPARATION_SAMPLE_LIMIT``,
    else every ``ceil(count / limit)``-th) measured to the other
    object's closest SURFACE point, minimised over both directions.
    Surface, never nearest-vertex. An UPPER BOUND on the true
    surface-to-surface separation, not the separation itself: the
    closest approach between two coarse solids is edge-to-edge and
    touches no vertex, and above the sample limit most vertices are
    never probed. Measured: two crossing 1 mm plates that share volume
    — true separation 0 — report 0.999 m in both argument orders.
    Direction matters, because `evaluate.acceptance` fails a relation
    on ``minimum_separation_m < required``, so an over-estimate makes
    that gate lenient and never strict.

    Both directions on purpose: sampling one side only made
    ``analyze_pair(a, b)`` and ``analyze_pair(b, a)`` disagree whenever
    the meshes differed in vertex density (measured 0.0224 m one way,
    0.3274 m the other), and a separation measure that depends on
    argument order is not a measure. The MINIMUM of the two one-sided
    readings, not the maximum: each is an over-estimate of the same
    infimum, so the smaller is the better estimate. That is the
    opposite convention to the two-sided Hausdorff distance
    (``max`` of the one-sided distances), which measures shape
    dissimilarity rather than closest approach.

    ``aabb_penetration_depth_m``: the world-AABB minimum translation
    depth, the same number that gates the pair count. It is the
    residual limit made visible — a genuine interpenetration whose
    AABB min-axis overlap stays under ``CONTACT_DEPTH_TOLERANCE_M``
    (parts thinner than 2 mm, or a grazing crossing) is reported by
    neither ``intersecting_face_pair_count`` nor a shrunken
    ``minimum_separation_m``. Gated by
    ``NoInterpenetrationSpec.maximum_aabb_penetration_depth_m``, which
    the crate-with-lid brief sets: opt-in, because AABB depth is
    meaningless for parts that legitimately share a bounding volume.
    An AABB depth is a PROXY for penetration depth; the principled
    measure is a signed distance field, which would also give the sign
    this pair of numbers lacks — `10.1109/tvcg.2006.56` (Jones,
    Bærentzen & Šrámek, 3D distance fields: a survey of techniques and
    applications) surveys the construction if that trade is ever worth
    making.
    """
    import bpy
    from mathutils.bvhtree import BVHTree

    dependency_graph = bpy.context.evaluated_depsgraph_get()

    first_evaluated = first_object.evaluated_get(dependency_graph)
    first_mesh = first_evaluated.to_mesh()
    second_evaluated = second_object.evaluated_get(dependency_graph)
    second_mesh = second_evaluated.to_mesh()
    try:
        first_mesh.calc_loop_triangles()
        second_mesh.calc_loop_triangles()
        first_to_world = first_evaluated.matrix_world
        second_to_world = second_evaluated.matrix_world

        first_bounds, second_bounds = _world_bounds(
            first_mesh, first_to_world, second_mesh, second_to_world
        )
        penetration_m = _penetration_depth_m(first_bounds, second_bounds)

        intersecting_pair_count = 0
        if penetration_m > CONTACT_DEPTH_TOLERANCE_M:
            # The solids really overlap: count the triangle pairs that
            # intersect — the same query the self-intersection checker
            # uses.
            first_vertex_coordinates = [
                tuple(first_to_world @ vertex.co) for vertex in first_mesh.vertices
            ]
            first_triangles = [
                tuple(loop_triangle.vertices)
                for loop_triangle in first_mesh.loop_triangles
            ]
            second_vertex_coordinates = [
                tuple(second_to_world @ vertex.co) for vertex in second_mesh.vertices
            ]
            second_triangles = [
                tuple(loop_triangle.vertices)
                for loop_triangle in second_mesh.loop_triangles
            ]
            if first_triangles and second_triangles:
                first_tree = BVHTree.FromPolygons(
                    first_vertex_coordinates, first_triangles
                )
                second_tree = BVHTree.FromPolygons(
                    second_vertex_coordinates, second_triangles
                )
                intersecting_pair_count = len(first_tree.overlap(second_tree))

        # Both directions, minimised: see the docstring on why one
        # direction is not a measurement.
        sampled_distances = [
            distance_m
            for distance_m in (
                _sampled_minimum_distance_m(
                    first_mesh, first_to_world, second_evaluated, second_to_world
                ),
                _sampled_minimum_distance_m(
                    second_mesh, second_to_world, first_evaluated, first_to_world
                ),
            )
            if distance_m is not None
        ]
        minimum_world_distance = min(sampled_distances) if sampled_distances else None
    finally:
        first_evaluated.to_mesh_clear()
        second_evaluated.to_mesh_clear()

    return PairReport(
        first_object_name=first_object.name,
        second_object_name=second_object.name,
        intersecting_face_pair_count=intersecting_pair_count,
        minimum_separation_m=(
            minimum_world_distance
            if minimum_world_distance is not None
            else float("inf")
        ),
        aabb_penetration_depth_m=penetration_m,
    )
