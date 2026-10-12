"""The bounded cleanup pass for generated geometry.

Order matters and every action is logged with its numbers. Two rules
from the mesh-repair literature (Attene et al.) are load-bearing:

* Hole filling is THRESHOLD-BOUNDED and reported. Blind-filling large
  holes produces "arbitrarily implausible" geometry — a hole bigger
  than the threshold is left open and reported as a remaining failure,
  never papered over.
* Cleanup is measured by the analyzer before and after. The
  CleanupReport carries both MeshReports; the claim "cleanup worked" is
  the analyzer's to make, not this module's.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from blended.analyze.mesh_checks import (
    DUPLICATE_VERTEX_DISTANCE_M,
    MeshBudget,
    MeshReport,
    analyze_object,
)

DEGENERATE_DISSOLVE_DISTANCE_M = 1.0e-6
MAXIMUM_DECIMATE_PASSES = 3
DECIMATE_UNDERSHOOT_FACTOR = 0.98


@dataclass(frozen=True)
class CleanupSettings:
    weld_distance_m: float = DUPLICATE_VERTEX_DISTANCE_M
    maximum_hole_perimeter_m: float = 0.15
    triangle_budget: int = MeshBudget().maximum_triangle_count
    decimate_to_budget: bool = True


@dataclass(frozen=True)
class CleanupReport:
    before: MeshReport
    after: MeshReport
    actions: tuple[str, ...] = field(default_factory=tuple)
    # Hole fills that were reverted because they cost more than they
    # bought (non-manifold edges or inverted facets appeared). The holes
    # stay open and report as remaining failures — the module's existing
    # contract for a hole it refuses to fill.
    reverted_hole_fills: int = 0

    def summary(self) -> str:
        return (
            f"tris {self.before.triangle_count} -> {self.after.triangle_count}"
            f" | boundary {self.before.boundary_edge_count} -> "
            f"{self.after.boundary_edge_count}"
            f" | doubles {self.before.duplicate_vertex_pair_count} -> "
            f"{self.after.duplicate_vertex_pair_count}"
            f" | reverted hole fills {self.reverted_hole_fills}"
        )


def _boundary_hole_groups(working_mesh):
    """Group boundary edges into connected components ('holes'), each
    with its total perimeter in meters."""
    boundary_edges = [edge for edge in working_mesh.edges if len(edge.link_faces) == 1]
    unvisited_edges = set(boundary_edges)
    hole_groups = []
    while unvisited_edges:
        seed_edge = unvisited_edges.pop()
        group_edges = [seed_edge]
        frontier = [seed_edge]
        while frontier:
            current_edge = frontier.pop()
            for edge_vertex in current_edge.verts:
                for neighbor_edge in edge_vertex.link_edges:
                    if neighbor_edge in unvisited_edges:
                        unvisited_edges.remove(neighbor_edge)
                        group_edges.append(neighbor_edge)
                        frontier.append(neighbor_edge)
        perimeter_m = sum(edge.calc_length() for edge in group_edges)
        hole_groups.append((group_edges, perimeter_m))
    return hole_groups


def cleanup_mesh(
    blender_object, settings: CleanupSettings = CleanupSettings()
) -> CleanupReport:
    """Run the bounded cleanup pass; return before/after reports."""
    import bmesh
    import bpy

    before_report = analyze_object(blender_object)
    actions: list[str] = []
    reverted_hole_fills = 0

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        vertex_count_before_weld = len(working_mesh.verts)
        bmesh.ops.remove_doubles(
            working_mesh,
            verts=list(working_mesh.verts),
            dist=settings.weld_distance_m,
        )
        welded_vertex_count = vertex_count_before_weld - len(working_mesh.verts)
        if welded_vertex_count:
            actions.append(
                f"welded {welded_vertex_count} vertices within "
                f"{settings.weld_distance_m} m"
            )

        face_count_before_dissolve = len(working_mesh.faces)
        bmesh.ops.dissolve_degenerate(
            working_mesh,
            dist=DEGENERATE_DISSOLVE_DISTANCE_M,
            edges=list(working_mesh.edges),
        )
        dissolved_face_count = face_count_before_dissolve - len(working_mesh.faces)
        if dissolved_face_count:
            actions.append(f"dissolved {dissolved_face_count} degenerate faces")

        loose_vertices = [
            vertex for vertex in working_mesh.verts if not vertex.link_faces
        ]
        if loose_vertices:
            bmesh.ops.delete(working_mesh, geom=loose_vertices, context="VERTS")
            actions.append(f"deleted {len(loose_vertices)} loose vertices")

        # Snapshot the mesh as it stands AFTER weld/dissolve/loose-vertex
        # deletion and BEFORE the fill pass, so a fill that costs more
        # than it buys can be undone to exactly this state. (Copying
        # blender_object.data here would snapshot the untouched
        # original — the bmesh edits above are not written back yet —
        # and a revert would silently undo the weld and loose-vertex
        # deletion the actions log claims.)
        pre_fill_mesh = blender_object.data.copy()
        working_mesh.to_mesh(pre_fill_mesh)

        for hole_edges, perimeter_m in _boundary_hole_groups(working_mesh):
            if perimeter_m <= settings.maximum_hole_perimeter_m:
                bmesh.ops.holes_fill(working_mesh, edges=hole_edges, sides=0)
                actions.append(
                    f"filled hole of perimeter {perimeter_m:.4f} m "
                    f"({len(hole_edges)} edges)"
                )
            else:
                actions.append(
                    f"LEFT OPEN: hole of perimeter {perimeter_m:.4f} m exceeds "
                    f"threshold {settings.maximum_hole_perimeter_m} m"
                )

        bmesh.ops.recalc_face_normals(working_mesh, faces=list(working_mesh.faces))
        actions.append("recalculated face normals outward")
        working_mesh.to_mesh(blender_object.data)
    finally:
        working_mesh.free()

    # The fill is a trade, not a win (measured on scp's valkyrie_body:
    # every fill ordering traded open edges for non-manifold edges and
    # inverted facets — 241 boundary / 0 non-manifold / 5 inverted
    # became 36 / 18 / 21). An inverted facet is a wrongly-lit patch
    # visible in normal gameplay; an open boundary costs only gib caps.
    # A small fill on a closed prop is usually right, so the fill stays
    # — but a fill that makes the mesh WORSE is reverted, holes open.
    filled_report = analyze_object(blender_object)
    if (
        filled_report.non_manifold_edge_count > before_report.non_manifold_edge_count
        or filled_report.inverted_facet_count > before_report.inverted_facet_count
    ):
        edited_mesh = blender_object.data
        blender_object.data = pre_fill_mesh
        bpy.data.meshes.remove(edited_mesh)
        # The reverted mesh is the pre-fill state; the normals pass the
        # actions log reports still has to hold for it.
        reverted_mesh = bmesh.new()
        try:
            reverted_mesh.from_mesh(pre_fill_mesh)
            bmesh.ops.recalc_face_normals(
                reverted_mesh, faces=list(reverted_mesh.faces)
            )
            reverted_mesh.to_mesh(pre_fill_mesh)
        finally:
            reverted_mesh.free()
        reverted_hole_fills = 1
        actions.append(
            "REVERTED hole fill(s): filling created non-manifold edges or "
            "inverted facets, so the holes stay open"
        )
    else:
        bpy.data.meshes.remove(pre_fill_mesh)

    if settings.decimate_to_budget:
        for _ in range(MAXIMUM_DECIMATE_PASSES):
            interim_report = analyze_object(blender_object)
            if interim_report.triangle_count <= settings.triangle_budget:
                break
            decimate_ratio = (
                settings.triangle_budget
                / interim_report.triangle_count
                * DECIMATE_UNDERSHOOT_FACTOR
            )
            decimate_modifier = blender_object.modifiers.new(
                name="DecimateToBudget", type="DECIMATE"
            )
            decimate_modifier.decimate_type = "COLLAPSE"
            decimate_modifier.ratio = decimate_ratio
            from blended.ops import apply_all_modifiers

            apply_all_modifiers(blender_object.name)
            actions.append(
                f"decimated {interim_report.triangle_count} -> target "
                f"{settings.triangle_budget} (ratio {decimate_ratio:.4f})"
            )

    after_report = analyze_object(blender_object)
    return CleanupReport(
        before=before_report,
        after=after_report,
        actions=tuple(actions),
        reverted_hole_fills=reverted_hole_fills,
    )
