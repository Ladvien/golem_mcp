"""The mesh analyzer: the hard acceptance gate.

The agentic-3D literature is unanimous that once a script executes, the
remaining failures are structural (disconnected components, bad
geometry) and are NOT fixed by more agent autonomy (3DCodeBench) and
NOT reliably caught by VLM screenshot critique (TikZ study: verifiers
are biased toward accepting). So the gate is this analyzer, and the
render critique is advisory.

Check list follows the Attene/Campen/Kobbelt repair taxonomy for
*designed* meshes: non-manifoldness, gaps (boundary edges),
degeneracies, disconnected components (Polygon Mesh Repairing,
DOI 10.1145/2431211.2431214). Validity checks are kept apart from
quality judgements per Fukaya et al.'s metric framework
(DOI 10.1109/TPAMI.2024.3398998).
"""

from __future__ import annotations

from dataclasses import dataclass

# A face smaller than this is degenerate: it breaks normal, circumcenter
# and barycentric computation downstream (Attene et al. 2013).
ZERO_AREA_EPSILON_M2 = 1.0e-9

# Vertices closer than this are treated as accidental doubles.
DUPLICATE_VERTEX_DISTANCE_M = 1.0e-5

# Vaughan, "Digital Modeling" p.340: 1,500-2,000 polys for a real-time
# weapon prop. Default budget for simple props sits at the top of that.
DEFAULT_PROP_TRIANGLE_BUDGET = 2_000


@dataclass(frozen=True)
class MeshBudget:
    """What a mesh must satisfy to pass the gate."""

    maximum_triangle_count: int = DEFAULT_PROP_TRIANGLE_BUDGET
    require_manifold: bool = True
    allow_boundary_edges: bool = False
    maximum_component_count: int = 1
    allow_self_intersections: bool = False
    allow_flipped_normals: bool = False
    allow_inverted_facets: bool = False
    # UV requirements. Off by default so pure-geometry stages (blockout,
    # CSG intermediates) are not forced to carry a UV layout; turn on
    # for anything headed to texturing or export.
    require_uv_layer: bool = False
    allow_uv_overlaps: bool = True
    allow_uv_out_of_bounds: bool = True
    maximum_uv_island_count: int | None = None


@dataclass(frozen=True)
class MeshReport:
    """Measured facts about one mesh object. Numbers, not opinions."""

    object_name: str
    triangle_count: int
    # Edges shared by more than two faces plus wire edges (shared by none).
    non_manifold_edge_count: int
    boundary_edge_count: int
    zero_area_face_count: int
    non_finite_coordinate_count: int
    connected_component_count: int
    duplicate_vertex_pair_count: int
    self_intersecting_face_pair_count: int
    flipped_normal_triangle_count: int
    uv_layer_count: int = 0
    uv_island_count: int = 0
    uv_overlapping_face_pair_count: int = 0
    uv_out_of_bounds_face_count: int = 0
    # SUM of UV triangle areas over the unit square. This DOUBLE-COUNTS
    # overlapped area by design, so a value near or above 1.0 alongside a
    # nonzero overlap count means stacking, not efficient packing
    # (measured: a barrel atlas reporting 94.1% here was 69.9% by
    # rasterization, with 38% of covered pixels multiply-covered).
    uv_coverage_fraction: float = 0.0
    inverted_facet_count: int = 0
    # THE SOLID, as distinct from the mesh that represents it. Signed
    # volume is only meaningful on closed manifold geometry (an open mesh
    # reports whatever its face normals imply), which is why nothing
    # gates on it — the same caveat flipped_normal_triangle_count
    # carries. It exists because "same solid, different triangulation"
    # is otherwise inexpressible: reversing a builder's boolean union
    # order leaves the volume bit-identical on the barrel while moving
    # the pallet's triangle count from 334 to 336.
    volume_m3: float = 0.0
    surface_area_m2: float = 0.0

    def failures(self, budget: MeshBudget) -> list[str]:
        """Return human-readable failures against a budget (empty = pass)."""
        found_failures: list[str] = []
        # An object with no faces measures clean on every other check
        # (0 boundary, 0 non-manifold, 0 components) — measured: an empty
        # mesh returned no failures — so "nothing was built" would pass.
        if self.triangle_count == 0:
            found_failures.append("no faces (empty mesh: nothing was built)")
        if self.triangle_count > budget.maximum_triangle_count:
            found_failures.append(
                f"triangle count {self.triangle_count} exceeds budget "
                f"{budget.maximum_triangle_count}"
            )
        if budget.require_manifold and self.non_manifold_edge_count > 0:
            found_failures.append(f"{self.non_manifold_edge_count} non-manifold edges")
        if not budget.allow_boundary_edges and self.boundary_edge_count > 0:
            found_failures.append(
                f"{self.boundary_edge_count} boundary edges (open mesh)"
            )
        if self.zero_area_face_count > 0:
            found_failures.append(f"{self.zero_area_face_count} zero-area faces")
        if self.non_finite_coordinate_count > 0:
            found_failures.append(
                f"{self.non_finite_coordinate_count} non-finite coordinates"
            )
        if self.connected_component_count > budget.maximum_component_count:
            found_failures.append(
                f"{self.connected_component_count} disconnected components "
                f"(budget {budget.maximum_component_count})"
            )
        if self.duplicate_vertex_pair_count > 0:
            found_failures.append(
                f"{self.duplicate_vertex_pair_count} duplicate vertex pairs "
                f"within {DUPLICATE_VERTEX_DISTANCE_M} m"
            )
        if (
            not budget.allow_self_intersections
            and self.self_intersecting_face_pair_count > 0
        ):
            found_failures.append(
                f"{self.self_intersecting_face_pair_count} self-intersecting "
                f"face pairs (join-without-union is the usual cause)"
            )
        if not budget.allow_flipped_normals and self.flipped_normal_triangle_count > 0:
            found_failures.append(
                f"{self.flipped_normal_triangle_count} triangles face inward "
                f"(flipped normals)"
            )
        if not budget.allow_inverted_facets and self.inverted_facet_count > 0:
            found_failures.append(
                f"{self.inverted_facet_count} triangles disagree with their own "
                f"vertex normals (inverted facets)"
            )
        if budget.require_uv_layer and self.uv_layer_count == 0:
            found_failures.append("no UV layer (cannot be textured)")
        if (
            budget.require_uv_layer
            and not budget.allow_uv_overlaps
            and self.uv_overlapping_face_pair_count > 0
        ):
            found_failures.append(
                f"{self.uv_overlapping_face_pair_count} overlapping UV face "
                f"pairs (texels shared between surfaces)"
            )
        if (
            budget.require_uv_layer
            and not budget.allow_uv_out_of_bounds
            and self.uv_out_of_bounds_face_count > 0
        ):
            found_failures.append(
                f"{self.uv_out_of_bounds_face_count} faces outside the 0-1 UV square"
            )
        if (
            budget.maximum_uv_island_count is not None
            and self.uv_island_count > budget.maximum_uv_island_count
        ):
            found_failures.append(
                f"{self.uv_island_count} UV islands exceeds budget "
                f"{budget.maximum_uv_island_count} (seam-heavy layout)"
            )
        return found_failures

    def passes(self, budget: MeshBudget) -> bool:
        return not self.failures(budget)


def _count_connected_components(working_mesh) -> int:
    """Count edge-connected vertex components with an iterative flood fill."""
    unvisited_vertices = set(working_mesh.verts)
    component_count = 0
    while unvisited_vertices:
        component_count += 1
        frontier = [unvisited_vertices.pop()]
        while frontier:
            current_vertex = frontier.pop()
            for connected_edge in current_vertex.link_edges:
                neighbor_vertex = connected_edge.other_vert(current_vertex)
                if neighbor_vertex in unvisited_vertices:
                    unvisited_vertices.remove(neighbor_vertex)
                    frontier.append(neighbor_vertex)
    return component_count


def _count_self_intersecting_pairs(evaluated_mesh) -> int:
    """Count non-adjacent triangle pairs whose bounding volumes overlap
    and whose triangles actually intersect (BVH self-overlap).

    Pairs sharing any vertex are skipped: mesh adjacency always
    "overlaps" and is not a defect. What remains is real geometry
    passing through other geometry — the signature of a join that
    should have been a boolean union, or of a bad boolean.
    """
    from mathutils.bvhtree import BVHTree

    evaluated_mesh.calc_loop_triangles()
    vertex_coordinates = [vertex.co[:] for vertex in evaluated_mesh.vertices]
    triangles = [
        tuple(loop_triangle.vertices) for loop_triangle in evaluated_mesh.loop_triangles
    ]
    if not triangles:
        return 0
    bvh_tree = BVHTree.FromPolygons(vertex_coordinates, triangles)
    intersecting_pair_count = 0
    for first_index, second_index in bvh_tree.overlap(bvh_tree):
        if first_index >= second_index:
            continue  # symmetric duplicate or self-pair
        if set(triangles[first_index]) & set(triangles[second_index]):
            continue  # adjacency, not a defect
        intersecting_pair_count += 1
    return intersecting_pair_count


# Ray-parity constants for flipped-normal detection.
PARITY_RAY_OFFSET_M = 1.0e-5
PARITY_MAXIMUM_CASTS = 64


def _count_flipped_normal_triangles(evaluated_mesh) -> int:
    """Count triangles whose normal points into the solid (ray parity).

    For each triangle, step epsilon along its normal and count surface
    crossings out to infinity: an even count means the step landed
    outside (normal is outward-correct), an odd count means it landed
    inside (the triangle is flipped). Simplified single-ray variant of
    Takayama et al.'s visibility voting; only meaningful for closed
    manifold meshes, so the caller gates on that.
    """
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree

    evaluated_mesh.calc_loop_triangles()
    vertex_coordinates = [vertex.co[:] for vertex in evaluated_mesh.vertices]
    triangles = [
        tuple(loop_triangle.vertices) for loop_triangle in evaluated_mesh.loop_triangles
    ]
    if not triangles:
        return 0
    bvh_tree = BVHTree.FromPolygons(vertex_coordinates, triangles)

    flipped_count = 0
    for loop_triangle in evaluated_mesh.loop_triangles:
        triangle_normal = Vector(loop_triangle.normal)
        centroid = Vector((0.0, 0.0, 0.0))
        for vertex_index in loop_triangle.vertices:
            centroid += Vector(vertex_coordinates[vertex_index])
        centroid /= 3.0

        ray_origin = centroid + triangle_normal * PARITY_RAY_OFFSET_M
        crossing_count = 0
        for _ in range(PARITY_MAXIMUM_CASTS):
            hit_location = bvh_tree.ray_cast(ray_origin, triangle_normal)[0]
            if hit_location is None:
                break
            crossing_count += 1
            ray_origin = hit_location + triangle_normal * PARITY_RAY_OFFSET_M
        if crossing_count % 2 == 1:
            flipped_count += 1
    return flipped_count


def facet_disagrees_with_its_normals(
    corner_positions: tuple[tuple[float, float, float], ...],
    corner_normals: tuple[tuple[float, float, float], ...],
) -> bool:
    """True when a triangle's winding disagrees with its own corner
    normals: dot(winding_normal, mean(corner_normals)) < 0.0.

    This is the "inverted facet" test — a face that disagrees with
    ITSELF — and it is deliberately NOT edge contiguity. Contiguity
    asks whether two adjacent faces agree, so an island wound
    inside-out passes it, and so does an inverted facet whose
    neighbours were inverted with it. Decimation and boolean work
    create these (scp measured backpack 0 -> 15/164 facets, body
    0 -> 5/749); recalculating normals does not fix them, because
    the geometry has folded.

    Pure arithmetic (no bpy): the same test runs in the file-level
    report, which reads the normals out of the shipped .glb.

    No epsilon, matching scp. A zero-area facet yields a zero cross
    product, dot 0.0, and is therefore NOT counted; the existing
    ZERO_AREA_EPSILON_M2 degenerate-face count reports those.
    """
    first, second, third = corner_positions
    edge_1 = (
        second[0] - first[0],
        second[1] - first[1],
        second[2] - first[2],
    )
    edge_2 = (
        third[0] - first[0],
        third[1] - first[1],
        third[2] - first[2],
    )
    winding_normal = (
        edge_1[1] * edge_2[2] - edge_1[2] * edge_2[1],
        edge_1[2] * edge_2[0] - edge_1[0] * edge_2[2],
        edge_1[0] * edge_2[1] - edge_1[1] * edge_2[0],
    )
    stored_normal = (
        sum(corner[0] for corner in corner_normals) / 3.0,
        sum(corner[1] for corner in corner_normals) / 3.0,
        sum(corner[2] for corner in corner_normals) / 3.0,
    )
    return (
        winding_normal[0] * stored_normal[0]
        + winding_normal[1] * stored_normal[1]
        + winding_normal[2] * stored_normal[2]
    ) < 0.0


def _count_inverted_facets(evaluated_mesh) -> int:
    """Count triangles whose winding disagrees with their own corner
    normals (inverted facets).

    Per-corner normals, not per-vertex: per-corner is what glTF ships
    (the NORMAL accessor), and the file-level report reads the same
    numbers back out of the .glb. Unconditional — open meshes get
    their normals checked too, which is the entire point: the parity
    test needs a closed manifold, folded geometry does not.
    """
    evaluated_mesh.calc_loop_triangles()
    corner_normals = evaluated_mesh.corner_normals
    inverted_count = 0
    for loop_triangle in evaluated_mesh.loop_triangles:
        corner_positions = tuple(
            tuple(evaluated_mesh.vertices[vertex_index].co)
            for vertex_index in loop_triangle.vertices
        )
        normals = tuple(
            tuple(corner_normals[loop_index].vector)
            for loop_index in loop_triangle.loops
        )
        if facet_disagrees_with_its_normals(corner_positions, normals):
            inverted_count += 1
    return inverted_count


# UV analysis constants.
UV_COINCIDENT_EPSILON = 1.0e-6
UV_BOUNDS_EPSILON = 1.0e-6
# Total area of the 0-1 UV square.
UV_SQUARE_AREA = 1.0


def _uv_signed_area(first_uv, second_uv, third_uv) -> float:
    """Twice the signed area — the standard 2D orientation predicate."""
    return (second_uv[0] - first_uv[0]) * (third_uv[1] - first_uv[1]) - (
        third_uv[0] - first_uv[0]
    ) * (second_uv[1] - first_uv[1])


def _uv_triangle_area(first_uv, second_uv, third_uv) -> float:
    """Absolute area of a triangle in UV space."""
    return abs(_uv_signed_area(first_uv, second_uv, third_uv)) / 2.0


def _point_strictly_inside_triangle(point_uv, triangle_uvs) -> bool:
    """True when the point is strictly inside (not on) the triangle."""
    first_uv, second_uv, third_uv = triangle_uvs
    orientations = (
        _uv_signed_area(first_uv, second_uv, point_uv),
        _uv_signed_area(second_uv, third_uv, point_uv),
        _uv_signed_area(third_uv, first_uv, point_uv),
    )
    if any(abs(value) <= UV_COINCIDENT_EPSILON for value in orientations):
        return False
    return all(value > 0 for value in orientations) or all(
        value < 0 for value in orientations
    )


def _segments_properly_cross(first_start, first_end, second_start, second_end) -> bool:
    """True when two segments cross at an interior point of both.

    Shared endpoints (mesh adjacency in UV space) are not a crossing.
    """
    for endpoint in (first_start, first_end):
        for other_endpoint in (second_start, second_end):
            if (
                abs(endpoint[0] - other_endpoint[0]) <= UV_COINCIDENT_EPSILON
                and abs(endpoint[1] - other_endpoint[1]) <= UV_COINCIDENT_EPSILON
            ):
                return False
    first_side = _uv_signed_area(first_start, first_end, second_start)
    second_side = _uv_signed_area(first_start, first_end, second_end)
    third_side = _uv_signed_area(second_start, second_end, first_start)
    fourth_side = _uv_signed_area(second_start, second_end, first_end)
    return (first_side * second_side < 0.0) and (third_side * fourth_side < 0.0)


def _uv_triangles_overlap(first_triangle_uvs, second_triangle_uvs) -> bool:
    """True when two UV triangles share area, not merely an edge.

    Corner-sharing alone is NOT overlap (that is island adjacency) and
    is NOT a licence to skip the pair either: perfectly stacked
    triangles share every corner and overlap completely. So the test is
    geometric: containment either way, or a proper edge crossing.
    """
    first_centroid = (
        sum(uv[0] for uv in first_triangle_uvs) / 3.0,
        sum(uv[1] for uv in first_triangle_uvs) / 3.0,
    )
    if _point_strictly_inside_triangle(first_centroid, second_triangle_uvs):
        return True
    second_centroid = (
        sum(uv[0] for uv in second_triangle_uvs) / 3.0,
        sum(uv[1] for uv in second_triangle_uvs) / 3.0,
    )
    if _point_strictly_inside_triangle(second_centroid, first_triangle_uvs):
        return True
    for first_index in range(3):
        for second_index in range(3):
            if _segments_properly_cross(
                first_triangle_uvs[first_index],
                first_triangle_uvs[(first_index + 1) % 3],
                second_triangle_uvs[second_index],
                second_triangle_uvs[(second_index + 1) % 3],
            ):
                return True
    return False


# Uniform-grid broadphase resolution for UV overlap search. A 2D grid
# replaces BVHTree here deliberately: BVHTree.overlap silently returns
# NOTHING for exactly-coplanar triangles (measured), and every triangle
# in UV space is coplanar by definition. See the drift catalog.
UV_BROADPHASE_GRID_RESOLUTION = 32


def _count_overlapping_uv_triangle_pairs(triangle_uv_corners) -> int:
    """Count genuinely overlapping UV triangle pairs.

    Uniform-grid broadphase (cheap AABB bucketing) then the exact 2D
    predicate on each candidate pair.
    """
    if len(triangle_uv_corners) < 2:
        return 0

    all_u = [uv[0] for corners in triangle_uv_corners for uv in corners]
    all_v = [uv[1] for corners in triangle_uv_corners for uv in corners]
    minimum_u, maximum_u = min(all_u), max(all_u)
    minimum_v, maximum_v = min(all_v), max(all_v)
    span_u = max(maximum_u - minimum_u, UV_COINCIDENT_EPSILON)
    span_v = max(maximum_v - minimum_v, UV_COINCIDENT_EPSILON)

    buckets: dict[tuple[int, int], list[int]] = {}
    triangle_bounds: list[tuple[float, float, float, float]] = []
    for triangle_index, corners in enumerate(triangle_uv_corners):
        low_u = min(uv[0] for uv in corners)
        high_u = max(uv[0] for uv in corners)
        low_v = min(uv[1] for uv in corners)
        high_v = max(uv[1] for uv in corners)
        triangle_bounds.append((low_u, high_u, low_v, high_v))
        first_column = int(
            (low_u - minimum_u) / span_u * (UV_BROADPHASE_GRID_RESOLUTION - 1)
        )
        last_column = int(
            (high_u - minimum_u) / span_u * (UV_BROADPHASE_GRID_RESOLUTION - 1)
        )
        first_row = int(
            (low_v - minimum_v) / span_v * (UV_BROADPHASE_GRID_RESOLUTION - 1)
        )
        last_row = int(
            (high_v - minimum_v) / span_v * (UV_BROADPHASE_GRID_RESOLUTION - 1)
        )
        for column in range(first_column, last_column + 1):
            for row in range(first_row, last_row + 1):
                buckets.setdefault((column, row), []).append(triangle_index)

    checked_pairs: set[tuple[int, int]] = set()
    overlapping_pair_count = 0
    for bucket_triangles in buckets.values():
        for position, first_index in enumerate(bucket_triangles):
            for second_index in bucket_triangles[position + 1 :]:
                pair_key = (
                    (first_index, second_index)
                    if first_index < second_index
                    else (second_index, first_index)
                )
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                first_low_u, first_high_u, first_low_v, first_high_v = triangle_bounds[
                    pair_key[0]
                ]
                second_low_u, second_high_u, second_low_v, second_high_v = (
                    triangle_bounds[pair_key[1]]
                )
                if (
                    first_high_u < second_low_u
                    or second_high_u < first_low_u
                    or first_high_v < second_low_v
                    or second_high_v < first_low_v
                ):
                    continue
                if _uv_triangles_overlap(
                    triangle_uv_corners[pair_key[0]],
                    triangle_uv_corners[pair_key[1]],
                ):
                    overlapping_pair_count += 1
    return overlapping_pair_count


def _count_uv_islands(working_mesh, uv_layer) -> int:
    """Count UV islands: faces are in one island when they share an edge
    whose UV coordinates match on BOTH sides. A UV seam is exactly an
    edge where they do not."""
    unvisited_faces = set(working_mesh.faces)
    island_count = 0
    while unvisited_faces:
        island_count += 1
        frontier = [unvisited_faces.pop()]
        while frontier:
            current_face = frontier.pop()
            for current_loop in current_face.loops:
                shared_edge = current_loop.edge
                for neighbor_face in shared_edge.link_faces:
                    if neighbor_face not in unvisited_faces:
                        continue
                    # Compare the edge's UVs as seen from both faces.
                    current_edge_uvs = {
                        tuple(round(component, 6) for component in loop[uv_layer].uv)
                        for loop in current_face.loops
                        if loop.vert in shared_edge.verts
                    }
                    neighbor_edge_uvs = {
                        tuple(round(component, 6) for component in loop[uv_layer].uv)
                        for loop in neighbor_face.loops
                        if loop.vert in shared_edge.verts
                    }
                    if current_edge_uvs == neighbor_edge_uvs:
                        unvisited_faces.remove(neighbor_face)
                        frontier.append(neighbor_face)
    return island_count


def _measure_uvs(working_mesh) -> dict:
    """Measure the active UV layer: islands, overlaps, bounds, coverage."""
    empty_measurements = {
        "uv_island_count": 0,
        "uv_overlapping_face_pair_count": 0,
        "uv_out_of_bounds_face_count": 0,
        "uv_coverage_fraction": 0.0,
    }
    uv_layer = working_mesh.loops.layers.uv.active
    if uv_layer is None or not working_mesh.faces:
        return empty_measurements

    # Flatten UVs into a z=0 mesh so the same BVH overlap machinery that
    # finds 3D self-intersections finds UV overlaps.
    uv_vertex_coordinates: list[tuple[float, float, float]] = []
    uv_triangles: list[tuple[int, int, int]] = []
    out_of_bounds_face_count = 0
    total_uv_area = 0.0
    for face in working_mesh.faces:
        face_uvs = [tuple(loop[uv_layer].uv) for loop in face.loops]
        if any(
            component < -UV_BOUNDS_EPSILON or component > 1.0 + UV_BOUNDS_EPSILON
            for uv in face_uvs
            for component in uv
        ):
            out_of_bounds_face_count += 1
        base_index = len(uv_vertex_coordinates)
        uv_vertex_coordinates.extend((uv[0], uv[1], 0.0) for uv in face_uvs)
        # Fan-triangulate the face in UV space.
        for corner_index in range(1, len(face_uvs) - 1):
            uv_triangles.append(
                (base_index, base_index + corner_index, base_index + corner_index + 1)
            )
            total_uv_area += _uv_triangle_area(
                face_uvs[0], face_uvs[corner_index], face_uvs[corner_index + 1]
            )

    triangle_uv_corners = [
        [uv_vertex_coordinates[vertex_index][:2] for vertex_index in triangle]
        for triangle in uv_triangles
    ]
    overlapping_pair_count = _count_overlapping_uv_triangle_pairs(triangle_uv_corners)

    return {
        "uv_island_count": _count_uv_islands(working_mesh, uv_layer),
        "uv_overlapping_face_pair_count": overlapping_pair_count,
        "uv_out_of_bounds_face_count": out_of_bounds_face_count,
        "uv_coverage_fraction": total_uv_area / UV_SQUARE_AREA,
    }


def analyze_object(blender_object) -> MeshReport:
    """Measure the object's *evaluated* mesh (modifiers included).

    Measures the mesh itself, never a derivation shared with the builder
    that made it — the analyzer must be able to fail.
    """
    import math

    import bmesh
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        working_mesh = bmesh.new()
        working_mesh.from_mesh(evaluated_mesh)
        try:
            # Computed FIRST, off the mesh exactly as loaded: every later
            # measurement here either mutates or is entitled to, and a
            # volume read after a weld is a volume of something else.
            volume_m3 = working_mesh.calc_volume(signed=True)
            surface_area_m2 = sum(face.calc_area() for face in working_mesh.faces)
            triangle_count = sum(len(face.verts) - 2 for face in working_mesh.faces)
            # Blender's own Select Non-Manifold: an edge shared by more than
            # two faces, or by none (a wire edge).
            non_manifold_edge_count = sum(
                1
                for edge in working_mesh.edges
                if len(edge.link_faces) > 2 or len(edge.link_faces) == 0
            )
            boundary_edge_count = sum(
                1 for edge in working_mesh.edges if len(edge.link_faces) == 1
            )
            zero_area_face_count = sum(
                1
                for face in working_mesh.faces
                if face.calc_area() < ZERO_AREA_EPSILON_M2
            )
            non_finite_coordinate_count = sum(
                1
                for vertex in working_mesh.verts
                for coordinate in vertex.co
                if not math.isfinite(coordinate)
            )
            connected_component_count = _count_connected_components(working_mesh)
            duplicate_search = bmesh.ops.find_doubles(
                working_mesh,
                verts=list(working_mesh.verts),
                dist=DUPLICATE_VERTEX_DISTANCE_M,
            )
            duplicate_vertex_pair_count = len(duplicate_search["targetmap"])
            self_intersecting_face_pair_count = _count_self_intersecting_pairs(
                evaluated_mesh
            )
            # Parity is only meaningful on closed manifold geometry;
            # open/non-manifold meshes already fail their own checks.
            if boundary_edge_count == 0 and non_manifold_edge_count == 0:
                flipped_normal_triangle_count = _count_flipped_normal_triangles(
                    evaluated_mesh
                )
            else:
                flipped_normal_triangle_count = 0
            # Deliberately NOT inside the closed-manifold branch above:
            # parity needs a closed solid, but folded geometry does not
            # respect manifoldness (measured: decimation and boolean
            # work create inverted facets on open meshes too, and the
            # parity branch used to report zero normals checking for
            # every open prop).
            inverted_facet_count = _count_inverted_facets(evaluated_mesh)
            uv_layer_count = len(working_mesh.loops.layers.uv)
            uv_measurements = _measure_uvs(working_mesh)
        finally:
            working_mesh.free()
    finally:
        evaluated_object.to_mesh_clear()

    return MeshReport(
        object_name=blender_object.name,
        triangle_count=triangle_count,
        non_manifold_edge_count=non_manifold_edge_count,
        boundary_edge_count=boundary_edge_count,
        zero_area_face_count=zero_area_face_count,
        non_finite_coordinate_count=non_finite_coordinate_count,
        connected_component_count=connected_component_count,
        duplicate_vertex_pair_count=duplicate_vertex_pair_count,
        self_intersecting_face_pair_count=self_intersecting_face_pair_count,
        flipped_normal_triangle_count=flipped_normal_triangle_count,
        inverted_facet_count=inverted_facet_count,
        uv_layer_count=uv_layer_count,
        uv_island_count=uv_measurements["uv_island_count"],
        uv_overlapping_face_pair_count=uv_measurements[
            "uv_overlapping_face_pair_count"
        ],
        uv_out_of_bounds_face_count=uv_measurements["uv_out_of_bounds_face_count"],
        uv_coverage_fraction=uv_measurements["uv_coverage_fraction"],
        volume_m3=volume_m3,
        surface_area_m2=surface_area_m2,
    )
