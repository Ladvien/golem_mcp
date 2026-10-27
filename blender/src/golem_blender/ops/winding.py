"""Which way each face of a mesh points, measured against the solid it bounds.

The gap this closes: the analyzer's `flipped_normal_triangle_count` compares
a face's normal with its own vertex normals, so it finds a surface that a
decimate or a boolean folded — and never a whole shell that was built inside
out, because every normal there agrees with every other. A garment imported
from a generator is exactly that failure: it renders, it exports, and in the
engine its back faces are culled and the character wearing it is missing a
skirt.

`analyze/winding.py` does the arithmetic (generalized winding number,
Jacobson, Kavan and Sorkine-Hornung 2013, DOI 10.1145/2461912.2461916). This
module is the reading an agent asks for.
"""

from __future__ import annotations

from dataclasses import dataclass

from golem_blender.ops._contract import op

# Faces measured by a full audit. Every face of a garment or a prop is far
# under this; a 50 000-triangle mesh is measured on an even stride sample
# instead, which is what the gate does with 256. Measured cost on a 4096-face
# audit of a 2048-triangle mesh: 0.09 s in Blender's Python.
WINDING_AUDIT_QUERY_LIMIT = 4096

# Face indices listed for the caller to select and fix. A report that lists
# all 600 inward faces of an inverted shell is a report nobody reads; the
# count is in `inward_area_fraction`, and 32 is enough to see the pattern.
MAXIMUM_LISTED_FACES = 32


@dataclass(frozen=True)
class ComponentWinding:
    """One connected piece of a mesh, measured on its own."""

    component_index: int
    triangle_count: int
    area_m2: float
    # Every undirected edge used exactly twice. Only a closed component has
    # a signed volume; an open one reports None rather than a number its
    # missing caps would make meaningless.
    closed: bool
    signed_volume_m3: float | None
    outward_area_fraction: float
    inward_area_fraction: float
    undecided_area_fraction: float


@dataclass(frozen=True)
class WindingReport:
    """How the named mesh's faces point, per face set and per connected component."""

    subject_object_name: str
    triangle_count: int
    measured_face_count: int
    outward_area_fraction: float
    inward_area_fraction: float
    undecided_area_fraction: float
    components: tuple[ComponentWinding, ...]
    # Polygon indices (`loop_triangle.polygon_index`), the form
    # `select_faces` and a bmesh edit take — at most MAXIMUM_LISTED_FACES.
    inward_face_indices: tuple[int, ...]


@op(reads_only=True)
def audit_winding(object_name: str) -> WindingReport:
    """Measure which way the named mesh's faces point: +1 outward, −1 inward, per component.

    Uses the generalized winding number over the WORLD-space triangles of
    the evaluated mesh (Jacobson, Kavan and Sorkine-Hornung 2013,
    DOI 10.1145/2461912.2461916), so a negative object scale reads
    inverted, as the engine draws it. An open shell is measured too: its
    faces are decided by the solid they bound, and its component reports no
    signed volume rather than a meaningless one.

    An open component always has some undecided area — its rim faces have
    half a neighbourhood — so a correct open garment reads mostly outward
    with the rest undecided, never mostly inward.
    """
    from golem_blender.analyze import winding
    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name, "MESH")
    corners, triangles = _world_triangles(blender_object)
    triangle_count = len(corners)
    if triangle_count == 0:
        raise ValueError(f"{object_name!r} has no faces (empty mesh)")

    sampled = winding.query_face_sample(triangle_count, WINDING_AUDIT_QUERY_LIMIT)
    scores = winding.face_orientation_scores(corners, sampled)
    classified = winding.classify_faces(scores)
    fractions = winding.area_weighted_fractions(corners[sampled], classified)

    component_of_triangle = winding.triangle_components(triangles)
    component_of_sample = component_of_triangle[sampled]
    components: list[ComponentWinding] = []
    for component_index in sorted(set(component_of_triangle.tolist())):
        in_component = component_of_triangle == component_index
        in_sample = component_of_sample == component_index
        component_corners = corners[in_component]
        component_is_closed = winding.component_is_closed(triangles, in_component)
        components.append(
            ComponentWinding(
                component_index=component_index,
                triangle_count=int(in_component.sum()),
                area_m2=float(winding.triangle_areas(component_corners).sum()),
                closed=component_is_closed,
                signed_volume_m3=(
                    winding.signed_volume_m3(component_corners)
                    if component_is_closed
                    else None
                ),
                **winding.area_weighted_fractions(
                    corners[sampled][in_sample], classified[in_sample]
                ),
            )
        )

    inward_polygons: list[int] = []
    if len(sampled) == triangle_count:
        inward_mask = classified == winding.INWARD
        triangle_polygons = _polygon_index_per_triangle(blender_object)
        for sampled_index in sampled[inward_mask][:MAXIMUM_LISTED_FACES]:
            inward_polygons.append(triangle_polygons[sampled_index].item())

    return WindingReport(
        subject_object_name=blender_object.name,
        triangle_count=triangle_count,
        measured_face_count=len(sampled),
        outward_area_fraction=fractions["outward_area_fraction"],
        inward_area_fraction=fractions["inward_area_fraction"],
        undecided_area_fraction=fractions["undecided_area_fraction"],
        components=tuple(components),
        inward_face_indices=tuple(sorted(inward_polygons)),
    )


def _world_triangles(blender_object) -> tuple:
    """The evaluated mesh's triangles as (corners (T,3,3) metres, indices (T,3)).

    WORLD space, from `matrix_world @ vertex`: `FromObject` and a local-space
    read both measure the wrong frame, and a mirrored object's winding is
    only inverted in world space (measured: a cube scaled -1 on X reads
    inward here and outward in local space).
    """
    import bpy
    import numpy as np

    from golem_blender.ops.transforms import _refresh_dependency_graph

    _refresh_dependency_graph()
    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        evaluated_mesh.calc_loop_triangles()
        vertices = np.empty(len(evaluated_mesh.vertices) * 3, dtype=float)
        evaluated_mesh.vertices.foreach_get("co", vertices)
        vertices = vertices.reshape(-1, 3)
        matrix = np.array(blender_object.matrix_world, dtype=float)
        world_vertices = vertices @ matrix[:3, :3].T + matrix[:3, 3]
        flat_indices = np.empty(len(evaluated_mesh.loop_triangles) * 3, dtype=np.int64)
        evaluated_mesh.loop_triangles.foreach_get("vertices", flat_indices)
        indices = flat_indices.reshape(-1, 3)
    finally:
        evaluated_object.to_mesh_clear()
    return world_vertices[indices], indices


def _polygon_index_per_triangle(blender_object):
    """`polygon_index` per loop triangle of the evaluated mesh, in triangle order."""
    import bpy
    import numpy as np

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated_object.to_mesh()
    try:
        evaluated_mesh.calc_loop_triangles()
        polygon_indices = np.empty(len(evaluated_mesh.loop_triangles), dtype=np.int64)
        evaluated_mesh.loop_triangles.foreach_get("polygon_index", polygon_indices)
    finally:
        evaluated_object.to_mesh_clear()
    return polygon_indices
