"""What a ray hits, and WHOSE face it hit — one world-space index over many parts.

`analyze/interaction._world_bvhs` builds one BVH per object and answers "is
anything in the way", which is all a clearance probe needs. A view probe needs
more: after a ray stops, which OBJECT stopped it, with which material, on which
face, how far away, and facing which way — and to keep going to the surface
behind. So this builds ONE tree over every part's world triangles and keeps an
owner table beside it, index for index.

Two traps this module exists to avoid, both measured elsewhere in the repo:

- `BVHTree.FromObject` builds in the OBJECT's local space, so a world-space ray
  against it silently measures something the viewport does not show. The
  vertices are transformed by `matrix_world` here and the tree is built with
  `FromPolygons`, exactly as `analyze.pair_checks` and `interaction` do.
- A ray that restarts exactly on the surface it just hit hits that surface
  again. Each restart steps `PARITY_RAY_OFFSET_M` along the ray direction, the
  same offset `mesh_checks` uses for its parity walk.

MAIN THREAD ONLY: everything here touches bpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from golem_blender.analyze.mesh_checks import PARITY_MAXIMUM_CASTS, PARITY_RAY_OFFSET_M

# find_nearest_range starts here and grows by doubling until enough DISTINCT
# objects are found. 5 cm is under a hand's width: closer triangles are almost
# always the surface the caller is standing on, and would name one object.
NEAREST_START_RADIUS_M = 0.05
NEAREST_MAXIMUM_RADIUS_M = 64.0
NEAREST_GROWTH_FACTOR = 2.0


@dataclass(frozen=True)
class RayHit:
    """One surface a ray met: whose it is, where, which way it faces, how far."""

    object_name: str
    material_name: str  # "" when the polygon's slot is empty
    face_index: int  # evaluated-mesh polygon index
    point_m: tuple[float, float, float]
    normal: tuple[float, float, float]  # world, from the triangle
    distance_m: float  # from the ray ORIGIN, cumulative across layers
    backface: bool  # dot(normal, direction) > 0


class OccluderIndex:
    """One world-space BVH over every part, with the owner of each triangle.

    An object with no triangles contributes nothing, and an index built over
    nothing answers every cast with a miss — a caller needs no special case for
    an empty scene.
    """

    def __init__(self, mesh_objects):
        import bpy
        from mathutils.bvhtree import BVHTree

        dependency_graph = bpy.context.evaluated_depsgraph_get()
        vertices: list[tuple[float, float, float]] = []
        triangles: list[tuple[int, int, int]] = []
        self.owner: list[tuple[str, int, str]] = []
        for blender_object in mesh_objects:
            evaluated = blender_object.evaluated_get(dependency_graph)
            mesh = evaluated.to_mesh()
            try:
                world_matrix = blender_object.matrix_world
                base = len(vertices)
                vertices.extend(
                    tuple(world_matrix @ vertex.co) for vertex in mesh.vertices
                )
                mesh.calc_loop_triangles()
                material_of_slot = [
                    slot.material.name if slot.material is not None else ""
                    for slot in blender_object.material_slots
                ]
                polygons = mesh.polygons
                for loop_triangle in mesh.loop_triangles:
                    triangles.append(
                        tuple(base + index for index in loop_triangle.vertices)
                    )
                    polygon_index = loop_triangle.polygon_index
                    slot_index = polygons[polygon_index].material_index
                    material_name = (
                        material_of_slot[slot_index]
                        if 0 <= slot_index < len(material_of_slot)
                        else ""
                    )
                    self.owner.append(
                        (blender_object.name, polygon_index, material_name)
                    )
            finally:
                evaluated.to_mesh_clear()
        self.vertices = vertices
        self.triangles = triangles
        self.tree = BVHTree.FromPolygons(vertices, triangles) if triangles else None

    def __len__(self) -> int:
        return len(self.triangles)

    def cast(
        self,
        origin: tuple[float, float, float],
        direction: tuple[float, float, float],
        maximum_hits: int = 1,
        maximum_distance_m: float = math.inf,
    ) -> list[RayHit]:
        """The first `maximum_hits` surfaces along the ray, front to back.

        Each restart steps `PARITY_RAY_OFFSET_M` along `direction` from the hit
        it just made, so the surface is not met again. Stops early at a miss, at
        `PARITY_MAXIMUM_CASTS`, or once the walk passes `maximum_distance_m`.
        """
        if self.tree is None or maximum_hits <= 0:
            return []
        from mathutils import Vector

        ray_origin = Vector(origin)
        ray_direction = Vector(direction)
        if ray_direction.length == 0.0:
            raise ValueError("a ray needs a non-zero direction")
        ray_direction.normalize()
        hits: list[RayHit] = []
        travelled = 0.0
        for _ in range(PARITY_MAXIMUM_CASTS):
            location, normal, index, distance = self.tree.ray_cast(
                ray_origin, ray_direction
            )
            if location is None:
                break
            travelled += distance
            if travelled > maximum_distance_m:
                break
            object_name, face_index, material_name = self.owner[index]
            normal_tuple = (normal.x, normal.y, normal.z)
            hits.append(
                RayHit(
                    object_name=object_name,
                    material_name=material_name,
                    face_index=face_index,
                    point_m=(location.x, location.y, location.z),
                    normal=normal_tuple,
                    distance_m=travelled,
                    backface=(
                        normal_tuple[0] * ray_direction.x
                        + normal_tuple[1] * ray_direction.y
                        + normal_tuple[2] * ray_direction.z
                    )
                    > 0.0,
                )
            )
            if len(hits) >= maximum_hits:
                break
            ray_origin = location + ray_direction * PARITY_RAY_OFFSET_M
        return hits

    def nearest_distance_m(self, point: tuple[float, float, float]) -> float:
        """How far `point` is from the closest surface, or inf when there is none.

        The clearance test a seam needs: a ray grazing two faces that meet FLUSH
        is at distance ~0 from both, while a real 2 cm gap puts its centre 1 cm
        from each. A crossing with no clearance is a degenerate contact, not a
        passage a character could breathe through.
        """
        if self.tree is None:
            return math.inf
        from mathutils import Vector

        found = self.tree.find_nearest(Vector(point))
        if found is None or found[0] is None:
            return math.inf
        return found[3]

    def nearest_object_names(
        self, point: tuple[float, float, float], count: int = 2
    ) -> tuple[str, ...]:
        """The distinct objects owning the triangles closest to `point`.

        The radius doubles from `NEAREST_START_RADIUS_M` until `count` distinct
        objects are found or `NEAREST_MAXIMUM_RADIUS_M` is reached, so a point
        in open space still answers with the few parts that are near it.
        """
        if self.tree is None or count <= 0:
            return ()
        from mathutils import Vector

        centre = Vector(point)
        radius = NEAREST_START_RADIUS_M
        while True:
            found: list[str] = []
            for _location, _normal, index, _distance in self.tree.find_nearest_range(
                centre, radius
            ):
                object_name = self.owner[index][0]
                if object_name not in found:
                    found.append(object_name)
                    if len(found) >= count:
                        return tuple(found)
            if radius >= NEAREST_MAXIMUM_RADIUS_M:
                return tuple(found)
            radius = min(radius * NEAREST_GROWTH_FACTOR, NEAREST_MAXIMUM_RADIUS_M)
