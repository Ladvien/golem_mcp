"""Give an unweighted mesh the weights of the body it covers.

Why this op exists, and why it is not "copy from the nearest vertex": the
nearest-vertex copy is the method every commercial tool starts from, and it
is the one with published counter-evidence on loose clothing — a sleeve
vertex copies the torso's weights, a flared trouser leg copies the other
leg's, and the garment tears when the character moves (Abdrashitov,
Raichstat, Monsen and Hill 2023, "Robust Skin Weights Transfer via Weight
Inpainting", SIGGRAPH Asia 2023 Technical Communications,
DOI 10.1145/3610543.3626180, §1 and §4).

This is that paper's two-stage method. Stage one copies weights only where
the match is CONFIDENT: within a distance threshold and without the normals
deviating past an angle threshold (§3.1). Stage two computes every other
vertex by minimising a combination of the Dirichlet and Laplacian energies
subject to the copied values (§3.2), which is a harmonic relaxation. The
paper solves it with a cotangent Laplacian and a sparse Cholesky solve; this
port uses the uniform Laplacian and Jacobi sweeps, because a sparse solve
needs scipy and `scripts/run_tests_in_blender.py` blocks scipy from
Blender's Python (it has no C extension for 3.13). The uniform Laplacian is
the same energy under a different stiffness matrix, so a vertex with no
confident neighbour inherits from its neighbours' neighbours exactly as the
paper's inpainting does, and the report says which iteration count it took.

Thresholds are the paper's: D = 0.05 x the bounding-box diagonal, Theta = 35
degrees (§3.1, "The default values for D and Theta are chosen as D = 0.05 *
d_box and Theta = 35"). The paper measures d_box on the TARGET mesh; here it
is the SOURCE's, which is the mesh a match is distance-checked against, and
the report states the metres so a caller can see the number it used.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender.ops._contract import op
from golem_blender.ops._influences import MAXIMUM_INFLUENCES_PER_VERTEX

# The paper's match thresholds (§3.1). Distance is a FRACTION of the source
# mesh's world bounding-box diagonal, so the op scales with the character
# rather than with the unit it is modelled in.
RSWT_MATCH_DISTANCE_FRACTION = 0.05
RSWT_MATCH_ANGLE_DEG = 35.0

# The relaxation stops when no vertex moves more than this between sweeps.
# A weight is unitless, so this is a weight per sweep: 1e-5 on a 4-bone
# vertex is a 0.004% change, far below the 8-bit precision a skin weight
# reaches an engine at.
INPAINT_CONVERGENCE_TOLERANCE = 1.0e-5

# A ceiling, not a target: the measured fixture converges in under 200
# sweeps (a 48-around, 17-row ring). 5000 leaves room for a garment with a
# genuinely long unweighted section (a floor-length skirt whose 4 m of hem
# has no confident vertex) while still terminating on one that can never
# converge.
INPAINT_MAXIMUM_ITERATIONS = 5000

# A weight this small is noise from the relaxation, and writing it creates a
# vertex group that drives nothing.
MINIMUM_WRITTEN_WEIGHT = 1.0e-4


@dataclass(frozen=True)
class WeightTransferReport:
    """What a weight transfer left on the target, and how much of it was measured or inferred."""

    object_name: str
    source_object_name: str
    groups_written: int
    vertices_weighted: int
    # Copied from a confident match (stage one) against computed by the
    # relaxation (stage two). A garment that is mostly INFERRED is a garment
    # whose weights are a guess about geometry nobody matched.
    confident_vertex_count: int
    inpainted_vertex_count: int
    inpaint_iterations: int
    inpaint_converged: bool
    match_distance_m: float
    match_angle_deg: float
    # The largest nearest-surface distance over the vertices that DID match.
    # A number at the threshold means the match radius, not the seams.
    maximum_match_distance_m: float
    # Where that vertex is, in world metres: the place an artist looks at
    # when a garment deforms wrongly.
    farthest_vertex_point_m: tuple[float, float, float]
    # Vertices whose dominant group changed, against what they carried
    # before. -1 when the target had no vertex groups at all, so "changed"
    # has no meaning.
    changed_dominant_group_vertex_count: int
    # Groups not named after a bone of the armature the source is bound to:
    # real weights that drive nothing (the same trap `weight_report` reports).
    groups_without_bones: tuple[str, ...]


@op(gated=True)
def transfer_weights(
    source_object_name: str,
    target_object_name: str,
    maximum_influence_count: int = MAXIMUM_INFLUENCES_PER_VERTEX,
    match_distance_m: float | None = None,
    match_angle_deg: float = RSWT_MATCH_ANGLE_DEG,
) -> WeightTransferReport:
    """Copy the source mesh's skin weights onto the target, then inpaint the rest.

    The two stages of Robust Skin Weights Transfer (Abdrashitov et al. 2023,
    DOI 10.1145/3610543.3626180): a vertex whose nearest point on the source
    is within `match_distance_m` and whose normal agrees within
    `match_angle_deg` gets the source's weights INTERPOLATED over that
    triangle; every other vertex is relaxed into agreement with those, which
    is what stops a loose hem from inheriting the nearest leg.

    `match_distance_m` defaults to 5% of the source's world bounding-box
    diagonal, the paper's own threshold. The target is NOT bound: weights
    written on a mesh with no Armature modifier move nothing, so the next
    call is `bind_mesh_to_armature(target, armature, automatic_weights=False)`.

    An inside-out target matches nothing — the normal check is not flipped
    for it, because a garment's outside and its inside would then be the
    same surface to this op (audit_winding says which it is).
    """
    import numpy as np

    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.rigging import ARMATURE_MODIFIER_TYPE
    from golem_blender.ops.transforms import _world_bounds_m

    source = object_by_name(source_object_name, "MESH")
    target = object_by_name(target_object_name, "MESH")
    if not 1 <= maximum_influence_count <= MAXIMUM_INFLUENCES_PER_VERTEX:
        raise ValueError(
            f"maximum_influence_count must be in 1.."
            f"{MAXIMUM_INFLUENCES_PER_VERTEX}, got {maximum_influence_count}"
        )
    if not 0.0 < match_angle_deg <= 90.0:
        raise ValueError(f"match_angle_deg must be in (0, 90], got {match_angle_deg}")

    # The weights are written on the BASE mesh, so a target whose shape comes
    # from modifiers would be weighted at the vertices it no longer has.
    blocking = [
        modifier.type
        for modifier in target.modifiers
        if modifier.type != ARMATURE_MODIFIER_TYPE
    ]
    if blocking:
        raise ValueError(
            f"{target.name!r} carries {sorted(set(blocking))} modifiers; "
            "apply the target's modifiers first (apply_all_modifiers) — "
            "weights are written on its base mesh"
        )

    minimum, maximum = _world_bounds_m([source])
    diagonal_m = float(np.linalg.norm(np.subtract(maximum, minimum)))
    if match_distance_m is None:
        match_distance_m = RSWT_MATCH_DISTANCE_FRACTION * diagonal_m
    if match_distance_m <= 0.0:
        raise ValueError(
            f"match_distance_m must be positive, got {match_distance_m}: a "
            f"source with no extent ({diagonal_m:.3f} m diagonal) cannot be matched"
        )

    armature_object = _bound_armature(source)
    restore_pose = _rest_pose(armature_object)
    try:
        source_vertices, source_triangles = _world_mesh(source)
        weights, group_names = _source_weights(source)
        target_points, target_normals = _target_points_and_normals(target)
        if len(source_triangles) == 0:
            raise ValueError(f"{source.name!r} has no faces to match against")
        if len(target_points) == 0:
            raise ValueError(f"{target.name!r} has no vertices to weight")

        from mathutils.bvhtree import BVHTree

        tree = BVHTree.FromPolygons(
            [tuple(point) for point in source_vertices],
            [tuple(triangle) for triangle in source_triangles],
        )
        nearest = [
            tree.find_nearest(tuple(point), match_distance_m) for point in target_points
        ]
        confident = np.zeros(len(target_points), dtype=bool)
        matched_weights = np.zeros((len(target_points), weights.shape[1]), dtype=float)
        match_distances = np.full(len(target_points), np.inf)
        for index, hit in enumerate(nearest):
            if hit is None or hit[0] is None:
                continue
            location, face_normal, face_index, distance = hit[0], hit[1], hit[2], hit[3]
            match_distances[index] = distance
            if distance > match_distance_m:
                continue
            if _angle_deg(target_normals[index], face_normal) > match_angle_deg:
                continue
            barycentric = _barycentric(
                location, source_vertices, source_triangles[face_index]
            )
            matched_weights[index] = barycentric @ weights[source_triangles[face_index]]
            confident[index] = True

        if not confident.any():
            raise ValueError(
                f"no target vertex matched the source within {match_distance_m:.4f} m "
                f"and {match_angle_deg:g}°: the target may be inside out "
                f"(audit_winding)"
            )

        # Stage two: harmonic relaxation over the target's own edges, the
        # confident vertices held fixed.
        adjacency = _vertex_adjacency(target, len(target_points))
        relaxed, iterations, converged = _relax(matched_weights, confident, adjacency)
        relaxed = _truncate_and_normalise(relaxed, maximum_influence_count)

        previous_dominant = _dominant_groups(target)
        _write_weights(target, relaxed, group_names)
        bone_names = (
            {bone.name for bone in armature_object.data.bones}
            if armature_object is not None
            else set()
        )
        groups_without_bones = (
            tuple(name for name in group_names if name not in bone_names)
            if bone_names
            else ()
        )
        farthest = int(np.argmax(np.where(confident, match_distances, -np.inf)))
        return WeightTransferReport(
            object_name=target.name,
            source_object_name=source.name,
            groups_written=int(
                sum(
                    1 for column in relaxed.T if (column > MINIMUM_WRITTEN_WEIGHT).any()
                )
            ),
            vertices_weighted=int((relaxed > MINIMUM_WRITTEN_WEIGHT).any(axis=1).sum()),
            confident_vertex_count=int(confident.sum()),
            inpainted_vertex_count=int((~confident).sum()),
            inpaint_iterations=iterations,
            inpaint_converged=converged,
            match_distance_m=float(match_distance_m),
            match_angle_deg=float(match_angle_deg),
            maximum_match_distance_m=float(match_distances[farthest]),
            farthest_vertex_point_m=tuple(float(x) for x in target_points[farthest]),
            changed_dominant_group_vertex_count=previous_dominant.changed(
                relaxed, group_names
            ),
            groups_without_bones=groups_without_bones,
        )
    finally:
        restore_pose()


# -- internals -----------------------------------------------------------


class _PreviousDominant:
    """What each vertex's heaviest group was before the transfer."""

    def __init__(self, names_by_vertex: list[str]):
        self._names_by_vertex = names_by_vertex

    def changed(self, weights, group_names) -> int:
        """How many vertices now have a different dominant group. -1 when there were none."""
        if not self._names_by_vertex:
            return -1
        changed = 0
        for index in range(len(weights)):
            if weights[index].max(initial=0.0) <= MINIMUM_WRITTEN_WEIGHT:
                continue
            before = self._names_by_vertex[index]
            after = group_names[int(weights[index].argmax())]
            if before and before != after:
                changed += 1
        return changed


def _bound_armature(source):
    """The armature the source's enabled Armature modifier points at, or None."""
    from golem_blender.ops.rigging import ARMATURE_MODIFIER_TYPE

    for modifier in source.modifiers:
        if (
            modifier.type == ARMATURE_MODIFIER_TYPE
            and modifier.object is not None
            and modifier.show_viewport
        ):
            return modifier.object
    return None


def _rest_pose(armature_object):
    """Set the armature to REST pose and return the call that undoes it.

    Weights are read at the bind pose: a mesh evaluated in the clip's pose
    has moved away from the shape the weights belong to, so every match
    distance would be measured against the wrong geometry.
    """
    if armature_object is None:
        return lambda: None
    previous = armature_object.data.pose_position
    armature_object.data.pose_position = "REST"

    def restore() -> None:
        armature_object.data.pose_position = previous

    return restore


def _world_mesh(blender_object):
    """(vertices (V,3) world metres, triangles (T,3) indices) of the evaluated mesh.

    World space, so the BVH built from these answers a world-space query;
    `BVHTree.FromObject` builds in the object's own space and would measure
    the wrong frame.
    """
    import bpy
    import numpy as np

    bpy.context.view_layer.update()
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = blender_object.evaluated_get(dependency_graph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = np.empty(len(mesh.vertices) * 3, dtype=float)
        mesh.vertices.foreach_get("co", vertices)
        matrix = np.array(blender_object.matrix_world, dtype=float)
        world = vertices.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
        flat = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
        mesh.loop_triangles.foreach_get("vertices", flat)
        triangles = flat.reshape(-1, 3)
    finally:
        evaluated.to_mesh_clear()
    return world, triangles


def _source_weights(source):
    """(weights (V, G) rows summing to 1, group names in index order) of the source's base mesh."""
    import numpy as np

    group_names = [group.name for group in source.vertex_groups]
    weights = np.zeros((len(source.data.vertices), len(group_names)), dtype=float)
    for vertex in source.data.vertices:
        for element in vertex.groups:
            weights[vertex.index, element.group] = element.weight
    return weights, group_names


def _target_points_and_normals(target):
    """(points (V,3) world metres, normals (V,3) world) of the target's BASE mesh.

    The base mesh, not the evaluated one: weights are written on base
    vertices, so they must be matched at the positions those vertices hold.
    Normals go through the inverse transpose, or a non-uniformly scaled
    object's normals point somewhere the surface does not.
    """
    import numpy as np

    mesh = target.data
    points = np.array([tuple(vertex.co) for vertex in mesh.vertices], dtype=float)
    normals = np.array([tuple(vertex.normal) for vertex in mesh.vertices], dtype=float)
    matrix = np.array(target.matrix_world, dtype=float)
    linear = matrix[:3, :3]
    world_points = points @ linear.T + matrix[:3, 3]
    normal_matrix = np.linalg.inv(linear).T
    world_normals = normals @ normal_matrix.T
    lengths = np.linalg.norm(world_normals, axis=1, keepdims=True)
    lengths[lengths == 0.0] = 1.0
    return world_points, world_normals / lengths


def _angle_deg(a, b) -> float:
    """The angle between two vectors, in degrees; 0 when either is degenerate."""
    import math

    import numpy as np

    length = float(np.linalg.norm(a) * np.linalg.norm(b))
    if length == 0.0:
        return 0.0
    cosine = float(np.dot(a, b)) / length
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _barycentric(point, vertices, triangle):
    """Barycentric coordinates of `point` within one triangle, clamped to it."""
    import numpy as np

    point = np.asarray(tuple(point), dtype=float)
    a, b, c = (np.asarray(corner, dtype=float) for corner in vertices[triangle])
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = float(np.dot(v0, v0))
    d01 = float(np.dot(v0, v1))
    d11 = float(np.dot(v1, v1))
    d20 = float(np.dot(v2, v0))
    d21 = float(np.dot(v2, v1))
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1e-20:
        return np.array([1.0, 0.0, 0.0])
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    u = 1.0 - v - w
    barycentric = np.clip(np.array([u, v, w]), 0.0, 1.0)
    total = barycentric.sum()
    return barycentric / total if total > 0.0 else np.array([1.0, 0.0, 0.0])


def _vertex_adjacency(target, vertex_count: int):
    """Neighbour indices per vertex, from the target's edges."""
    adjacency: list[list[int]] = [[] for _ in range(vertex_count)]
    for edge in target.data.edges:
        left, right = edge.vertices
        adjacency[left].append(right)
        adjacency[right].append(left)
    return adjacency


def _relax(matched_weights, confident, adjacency):
    """Uniform-weight harmonic relaxation of the unmatched rows, held rows fixed.

    RSWT's stage two with a uniform Laplacian (see the module docstring for
    why this port cannot use the cotangent one). Jacobi sweeps: every free
    row becomes the mean of its neighbours, repeated until no row moves more
    than INPAINT_CONVERGENCE_TOLERANCE or INPAINT_MAXIMUM_ITERATIONS is
    spent.

    A connected component with NO confident vertex has no boundary condition
    at all — its rows would average to all-zero and the vertices would be
    left weightless while the report claimed they were weighted. That is
    refused by name.
    """
    import numpy as np

    weights = matched_weights.copy()
    free = np.flatnonzero(~confident)
    if len(free) == 0:
        return weights, 0, True

    component_of = _component_labels(adjacency, len(confident))
    for component in np.unique(component_of[free]):
        in_component = component_of == component
        if not confident[in_component].any():
            raise ValueError(
                f"{int(in_component.sum())} vertices form a component with no "
                f"confident match, so there is nothing to interpolate from; "
                f"that piece is not covered by the source mesh"
            )

    iterations = 0
    for iterations in range(1, INPAINT_MAXIMUM_ITERATIONS + 1):
        updated = weights.copy()
        largest_change = 0.0
        for index in free:
            neighbours = adjacency[index]
            if not neighbours:
                continue
            mean = weights[neighbours].mean(axis=0)
            largest_change = max(
                largest_change, float(np.abs(mean - weights[index]).max())
            )
            updated[index] = mean
        weights = updated
        if largest_change < INPAINT_CONVERGENCE_TOLERANCE:
            return weights, iterations, True
    return weights, iterations, False


def _component_labels(adjacency, vertex_count: int):
    """Connected-component label per vertex, over the adjacency lists."""
    import numpy as np

    labels = np.full(vertex_count, -1, dtype=np.int64)
    next_label = 0
    for start in range(vertex_count):
        if labels[start] != -1:
            continue
        labels[start] = next_label
        frontier = [start]
        while frontier:
            current = frontier.pop()
            for neighbour in adjacency[current]:
                if labels[neighbour] == -1:
                    labels[neighbour] = next_label
                    frontier.append(neighbour)
        next_label += 1
    return labels


def _truncate_and_normalise(weights, maximum_influence_count: int):
    """Keep each row's heaviest weights, drop the noise, renormalise what is left to 1.

    The sub-threshold drop happens BEFORE the normalisation, and it has to:
    `_write_weights` does not write a weight under MINIMUM_WRITTEN_WEIGHT, so
    normalising while such a weight is still in the row leaves the WRITTEN
    weights summing to slightly under 1 and the vertex scaled toward the
    origin by exactly that much (measured: rows summing to 0.99991).
    """
    import numpy as np

    truncated = np.zeros_like(weights)
    for index in range(len(weights)):
        row = weights[index]
        if len(row) > maximum_influence_count:
            keep = np.argpartition(row, -maximum_influence_count)[
                -maximum_influence_count:
            ]
        else:
            keep = np.arange(len(row))
        kept = np.clip(row[keep], 0.0, None)
        kept[kept <= MINIMUM_WRITTEN_WEIGHT] = 0.0
        total = kept.sum()
        if total <= 0.0:
            continue
        truncated[index, keep] = kept / total
    return truncated


def _dominant_groups(target) -> _PreviousDominant:
    """Each vertex's heaviest group before the transfer, by ITS OWN group names; [] when it had none."""
    if not target.vertex_groups:
        return _PreviousDominant([])
    own_names = [group.name for group in target.vertex_groups]
    names: list[str] = []
    for vertex in target.data.vertices:
        heaviest = ""
        heaviest_weight = 0.0
        for element in vertex.groups:
            if element.weight > heaviest_weight:
                heaviest_weight = element.weight
                heaviest = own_names[element.group]
        names.append(heaviest)
    return _PreviousDominant(names)


def _write_weights(target, weights, group_names) -> None:
    """Replace the target's vertex groups with one per source group and write the rows."""
    import numpy as np

    for group in list(target.vertex_groups):
        target.vertex_groups.remove(group)
    for index, name in enumerate(group_names):
        column = weights[:, index]
        if not (column > MINIMUM_WRITTEN_WEIGHT).any():
            continue
        group = target.vertex_groups.new(name=name)
        for vertex_index in np.flatnonzero(column > MINIMUM_WRITTEN_WEIGHT):
            group.add([int(vertex_index)], float(column[vertex_index]), "REPLACE")
