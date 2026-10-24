"""glTF export with round-trip verification.

The export call's return value proves nothing about the file on disk.
So export_glb measures the artifact: it re-imports the .glb it just
wrote and runs the analyzer on what actually came back.

Measured lesson (see drift catalog): glTF stores per-vertex normals, so
the exporter SPLITS vertices along flat-shading seams — a watertight
mesh ships as topologically disconnected shards (the pallet: 1 solid
out, 46 components / 376 boundary edges back). Engines render this
fine; naive re-analysis panics. So the shipped file is judged on its
POSITION-WELDED topology (the same convention TRELLIS metadata uses),
while the raw re-import report is kept for information. Invariants:
welded re-import passes the budget, triangle count survives unchanged,
and dimensions match within tolerance (catching axis/unit mistakes).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from golem_blender.analyze.mesh_checks import MeshBudget, MeshReport, analyze_object
from golem_blender.export.blend import (
    BlendSaveReport,
    save_blend,
    validate_blend_request,
)
from golem_blender.export.glb_report import GlbAssetReport, asset_report

EXPORT_DIMENSION_TOLERANCE_M = 1.0e-4
REIMPORT_OBJECT_SUFFIX = "_reimport_check"


@dataclass(frozen=True)
class ExportReport:
    export_path: Path
    file_size_bytes: int
    pre_export: MeshReport
    reimported_raw: MeshReport
    reimported_welded: MeshReport
    pre_export_dimensions_m: tuple[float, float, float]
    reimported_dimensions_m: tuple[float, float, float]
    # The artifact itself, parsed from its own bytes (stdlib only —
    # see glb_report.py). None only in synthetic pure-tier reports;
    # export_glb always populates it.
    file_report: GlbAssetReport | None = None
    # The node name engines walk by. The exporter's default root naming
    # is asserted against this, not assumed.
    exported_object_name: str = ""
    # The editable source saved beside the .glb (OT-50). None only in
    # synthetic pure-tier reports; export_glb always populates it.
    blend: BlendSaveReport | None = None
    # --- assembly export (issue #26) -----------------------------------
    # An assembly is not one mesh, so its gate is the per-PIECE one and its
    # verdict lives here rather than in a `MeshReport`. Empty for a
    # single-object `export_glb`, which is gated by `pre_export` instead.
    assembly_name: str = ""
    # How many objects shipped (the parts, or 1 for a welded mesh) and how
    # many parts the assembly had.
    keep_parts: int = 0
    part_count: int = 0
    # Every part that failed its own piece gate, as (name, failures).
    part_failures: tuple[tuple[str, str], ...] = ()
    # What a real re-import of the written file delivered: the object count,
    # and the material names read from the file's own glTF JSON.
    reimported_object_count: int = 0
    material_names: tuple[str, ...] = ()
    expected_material_names: tuple[str, ...] = ()
    # The root node names the file should carry, one per shipped object.
    expected_root_node_names: tuple[str, ...] = ()

    def assembly_failures(self, budget: MeshBudget = MeshBudget()) -> list[str]:
        """Every way a shipped ASSEMBLY fails its own gate (empty = pass).

        Not `MeshBudget` on one mesh: the assembly's parts were each judged by
        `MeshBudget` already (their failures arrive here as
        `part_failures`), and this checks what an ASSEMBLY additionally
        promises — that every part shipped, that the parts are intact pieces,
        and that the file this call wrote really holds them.
        """
        found_failures: list[str] = []
        for part_name, part_failure in self.part_failures:
            found_failures.append(
                f"part {part_name!r} fails the piece gate: {part_failure}"
            )
        if self.reimported_object_count != self.keep_parts:
            found_failures.append(
                f"the file re-imported {self.reimported_object_count} objects, "
                f"{self.keep_parts} were shipped"
            )
        if self.material_names != tuple(sorted(self.expected_material_names)):
            found_failures.append(
                f"the file's materials are {list(self.material_names)}, the "
                f"assembly's are {sorted(self.expected_material_names)}"
            )
        if self.file_report is not None:
            if tuple(sorted(self.file_report.root_node_names)) != tuple(
                sorted(self.expected_root_node_names)
            ):
                found_failures.append(
                    f"file root nodes are {self.file_report.root_node_names}, "
                    f"expected {list(self.expected_root_node_names)}"
                )
            if self.file_report.triangle_count != self.pre_export.triangle_count:
                found_failures.append(
                    f"file ships {self.file_report.triangle_count} triangles, the "
                    f"assembly measured {self.pre_export.triangle_count} "
                    f"(modifier or exporter drift)"
                )
            if self.file_report.inverted_facet_count > 0:
                found_failures.append(
                    f"{self.file_report.inverted_facet_count} inverted facets in "
                    f"the shipped file"
                )
        else:
            found_failures.append("no file report: the artifact was not read back")
        if self.blend is None:
            found_failures.append("no .blend source: an asset without it is not done")
        for axis_index, axis_name in enumerate(("x", "y", "z")):
            drift_m = abs(
                self.reimported_dimensions_m[axis_index]
                - self.pre_export_dimensions_m[axis_index]
            )
            if drift_m > EXPORT_DIMENSION_TOLERANCE_M:
                found_failures.append(
                    f"dimension {axis_name} drifted {drift_m:.6f} m through export "
                    f"(axis-convention or unit error)"
                )
        return found_failures

    def passes_assembly(self, budget: MeshBudget = MeshBudget()) -> bool:
        """`passes` for an assembly: the per-piece gate plus the set's promises."""
        return not self.assembly_failures(budget)

    def round_trip_failures(self, budget: MeshBudget = MeshBudget()) -> list[str]:
        """Why this export is not shippable (empty = pass).

        A shipped ASSEMBLY is judged by `assembly_failures`, not here: this
        body asks `MeshBudget` about ONE merged mesh, which is the right
        question for a prop and the wrong one for 49 closed solids sharing
        faces — it would fail every building on "disconnected components"
        while the parts are each exactly what the piece gate demands. So one
        entry point answers for both lanes instead of callers having to know
        which gate applies to what they were handed.
        """
        if self.assembly_name:
            return self.assembly_failures(budget)
        found_failures: list[str] = []
        pre_export_gate_failures = self.pre_export.failures(budget)
        if pre_export_gate_failures:
            found_failures.append(
                f"mesh failed the gate BEFORE export: "
                f"{'; '.join(pre_export_gate_failures)}"
            )
        welded_gate_failures = self.reimported_welded.failures(budget)
        if welded_gate_failures:
            found_failures.append(
                f"re-imported file fails the gate even after welding: "
                f"{'; '.join(welded_gate_failures)}"
            )
        if self.reimported_welded.triangle_count != self.pre_export.triangle_count:
            found_failures.append(
                f"triangle count drifted through export: "
                f"{self.pre_export.triangle_count} -> "
                f"{self.reimported_welded.triangle_count}"
            )
        for axis_index, axis_name in enumerate(("x", "y", "z")):
            dimension_drift_m = abs(
                self.reimported_dimensions_m[axis_index]
                - self.pre_export_dimensions_m[axis_index]
            )
            if dimension_drift_m > EXPORT_DIMENSION_TOLERANCE_M:
                found_failures.append(
                    f"dimension {axis_name} drifted {dimension_drift_m:.6f} m "
                    f"through export (axis-convention or unit error)"
                )
        if self.file_report is not None:
            file_report = self.file_report
            if file_report.triangle_count != self.pre_export.triangle_count:
                found_failures.append(
                    f"file ships {file_report.triangle_count} triangles, the "
                    f"scene measured {self.pre_export.triangle_count} "
                    f"(modifier or exporter drift)"
                )
            if (
                file_report.welded_boundary_edge_count
                != self.reimported_welded.boundary_edge_count
            ):
                found_failures.append(
                    f"file and welded re-import disagree on boundary edges: "
                    f"{file_report.welded_boundary_edge_count} vs "
                    f"{self.reimported_welded.boundary_edge_count}"
                )
            if (
                not budget.allow_inverted_facets
                and file_report.inverted_facet_count > 0
            ):
                found_failures.append(
                    f"{file_report.inverted_facet_count} inverted facets in "
                    f"the shipped file"
                )
            if file_report.root_node_names != [self.exported_object_name]:
                found_failures.append(
                    f"file root nodes are {file_report.root_node_names}, "
                    f"expected the exported object's own name "
                    f"{self.exported_object_name!r}"
                )
            # Blender (x, y, z) ships as glTF (x, z, -y), so the file's
            # extents are compared against the scene's with that axis
            # permutation applied.
            file_dimensions_m = (
                file_report.dimensions_m[0],
                file_report.dimensions_m[2],
                file_report.dimensions_m[1],
            )
            for axis_index, axis_name in enumerate(("x", "y", "z")):
                file_drift_m = abs(
                    file_dimensions_m[axis_index]
                    - self.pre_export_dimensions_m[axis_index]
                )
                if file_drift_m > EXPORT_DIMENSION_TOLERANCE_M:
                    found_failures.append(
                        f"file dimension {axis_name} drifted "
                        f"{file_drift_m:.6f} m through export "
                        f"(axis-convention or unit error)"
                    )
        return found_failures

    def passes(self, budget: MeshBudget = MeshBudget()) -> bool:
        return not self.round_trip_failures(budget)


def export_glb(blender_object, output_path: Path, *, blend_path: Path) -> ExportReport:
    """Export one object to .glb, verify the file by re-importing it, and
    save the object's editable .blend source at `blend_path` (OT-50).

    `blend_path` is required: an asset without its source cannot be
    edited and re-exported, and a silent default beside the .glb would
    hide that choice from the caller. A bad path raises BlendSaveError
    BEFORE anything is written, so no .glb is left without its source.
    """
    import bpy

    from golem_blender.ingest.import_glb import import_glb
    from golem_blender.ops.primitives import remove_object_and_mesh

    _, blend_path = validate_blend_request([blender_object.name], blend_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pre_export_report = analyze_object(blender_object)
    bpy.context.view_layer.update()
    pre_export_dimensions_m = tuple(blender_object.dimensions)

    for scene_object in bpy.context.scene.objects:
        scene_object.select_set(scene_object == blender_object)
    bpy.context.view_layer.objects.active = blender_object
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )
    file_size_bytes = output_path.stat().st_size
    file_report = asset_report(output_path)
    exported_object_name = blender_object.name

    reimport_name = blender_object.name + REIMPORT_OBJECT_SUFFIX
    reimported_object = import_glb(output_path, reimport_name)
    reimported_raw_report = analyze_object(reimported_object)
    from golem_blender.ops import weld_and_dissolve

    weld_and_dissolve(reimport_name)
    reimported_welded_report = analyze_object(reimported_object)
    bpy.context.view_layer.update()
    reimported_dimensions_m = tuple(reimported_object.dimensions)
    remove_object_and_mesh(reimport_name)
    blend_report = save_blend([exported_object_name], blend_path)

    return ExportReport(
        export_path=output_path,
        file_size_bytes=file_size_bytes,
        pre_export=pre_export_report,
        reimported_raw=reimported_raw_report,
        reimported_welded=reimported_welded_report,
        pre_export_dimensions_m=pre_export_dimensions_m,
        reimported_dimensions_m=reimported_dimensions_m,
        file_report=file_report,
        exported_object_name=exported_object_name,
        blend=blend_report,
    )
