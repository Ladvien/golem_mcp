"""Post-CSG healing: weld and de-degenerate a mesh in place.

The EXACT boolean solver is reliable about topology but litters the
seam with exact-duplicate vertices and occasional zero-area slivers
(measured on the pallet: 7 duplicate pairs + 1 zero-area face from
three embed-seam unions). Every boolean op heals its own output so
builders never ship solver debris — and the analyzer stays a defect
detector instead of a solver-debris counter.
"""

from __future__ import annotations

from blended.analyze.mesh_checks import (
    DUPLICATE_VERTEX_DISTANCE_M,
    ZERO_AREA_EPSILON_M2,
)

DEGENERATE_EDGE_DISTANCE_M = 1.0e-6
MAXIMUM_HEAL_PASSES = 3


def weld_and_dissolve(object_name: str) -> dict[str, int]:
    """Weld coincident vertices and collapse zero-area faces of the named mesh in place.

    Returns {"welded_vertices": n, "removed_zero_area_faces": n} for
    logging. Iterates up to MAXIMUM_HEAL_PASSES because collapsing a
    sliver can create a new coincident pair and vice versa.
    """
    import bmesh

    from blended.ops._objects import object_by_name

    blender_object = object_by_name(object_name, "MESH")
    welded_vertex_total = 0
    removed_face_total = 0
    for _ in range(MAXIMUM_HEAL_PASSES):
        working_mesh = bmesh.new()
        working_mesh.from_mesh(blender_object.data)
        try:
            vertex_count_before = len(working_mesh.verts)
            bmesh.ops.remove_doubles(
                working_mesh,
                verts=list(working_mesh.verts),
                dist=DUPLICATE_VERTEX_DISTANCE_M,
            )
            bmesh.ops.dissolve_degenerate(
                working_mesh,
                dist=DEGENERATE_EDGE_DISTANCE_M,
                edges=list(working_mesh.edges),
            )
            # bmesh does not promise valid element indices after a topology
            # op, and the sliver edges below are keyed by index.
            working_mesh.edges.index_update()
            # Collinear zero-area faces have no short edge for
            # dissolve_degenerate; collapse their shortest edge instead.
            zero_area_faces = [
                face
                for face in working_mesh.faces
                if face.calc_area() < ZERO_AREA_EPSILON_M2
            ]
            # Every edge is chosen BEFORE anything is collapsed, and they
            # are collapsed in one call. Collapsing per face while
            # holding a list of faces frees the neighbours still in that
            # list: measured 2026-08-22 (iteration 5), two slivers
            # sharing an edge raised 'ReferenceError: BMesh data of type
            # BMFace has been removed' from inside boolean_union.
            # Adjacent slivers can also nominate the SAME edge, so the
            # set is deduplicated by index rather than passed twice.
            sliver_edges_by_index = {}
            for sliver_face in zero_area_faces:
                shortest_edge = min(
                    sliver_face.edges, key=lambda edge: edge.calc_length()
                )
                sliver_edges_by_index[shortest_edge.index] = shortest_edge
            if sliver_edges_by_index:
                bmesh.ops.collapse(
                    working_mesh, edges=list(sliver_edges_by_index.values())
                )
            welded_this_pass = vertex_count_before - len(working_mesh.verts)
            welded_vertex_total += max(welded_this_pass, 0)
            removed_face_total += len(zero_area_faces)
            working_mesh.to_mesh(blender_object.data)
        finally:
            working_mesh.free()
        if welded_this_pass == 0 and not zero_area_faces:
            break
    return {
        "welded_vertices": welded_vertex_total,
        "removed_zero_area_faces": removed_face_total,
    }
