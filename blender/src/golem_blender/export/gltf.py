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

from golem_blender.analyze.interaction import MINIMUM_APPROACH_M, SideAccess
from golem_blender.analyze.mesh_checks import MeshBudget, MeshReport, analyze_object
from golem_blender.export.blend import (
    BlendSaveReport,
    save_blend,
    validate_blend_request,
)
from golem_blender.export.glb_report import GlbAssetReport, asset_report

EXPORT_DIMENSION_TOLERANCE_M = 1.0e-4
REIMPORT_OBJECT_SUFFIX = "_reimport_check"
# The name `ops/assembly.py` gives the re-import check, so this module can tell
# "the re-import found nothing wrong" from "the re-import never ran" without
# importing the ops module (which would be a cycle).
REIMPORT_CHECK = "reimport"


@dataclass(frozen=True)
class ExportReport:
    export_path: Path
    file_size_bytes: int
    # None ONLY for an assembly export whose gate skipped the measurement
    # (`gate="structure"`/`"none"`, or a spent `budget_s`). `export_glb` and a
    # full-gated assembly always fill all three, so a caller that reads them
    # without checking is reading a value that exists — see `gate` and
    # `skipped_checks` for the two that can be absent.
    pre_export: MeshReport | None
    reimported_raw: MeshReport | None
    reimported_welded: MeshReport | None
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
    # The declared interaction sides an assembly's parts could not USE: a
    # character cannot reach them. Empty for a single-object export and for
    # an assembly with every side clear.
    blocked_sides: tuple[SideAccess, ...] = ()
    # --- how much was measured, and whether it finished (the 77-part wedge) ---
    # The gate mode this export ran: "none", "structure" or "full".
    gate: str = "full"
    # True only when `budget_s` cut a check THIS gate asked for. A truncated
    # export is a real file with a partial verification, and the report says
    # exactly which parts of the verification are missing.
    truncated: bool = False
    # Every check that did not run, by name, whether because the gate mode does
    # not include it or because the budget ran out. `("part_gate", "clearance",
    # "combined_analysis", "reimport")` is the list for `gate="none"`.
    skipped_checks: tuple[str, ...] = ()
    # How many parts the per-piece gate actually measured (all of them unless
    # the budget cut the loop short).
    gate_checked_parts: int = 0
    # The triangle count the shipped file must carry, measured from the parts
    # themselves. `pre_export.triangle_count` is the same number when the
    # combined mesh was analysed; this one survives a skipped analysis.
    expected_triangle_count: int = 0
    # The session's safety copy, when a full gate on a large assembly took one
    # BEFORE it started measuring: the scene on disk, if the call went wrong.
    scratch_blend_path: str = ""
    scratch_save_error: str = ""

    def assembly_failures(self, budget: MeshBudget = MeshBudget()) -> list[str]:
        """Every way a shipped ASSEMBLY fails its own gate (empty = pass).

        Not `MeshBudget` on one mesh: the assembly's parts were each judged by
        `MeshBudget` already (their failures arrive here as
        `part_failures`), and this checks what an ASSEMBLY additionally
        promises — that every part shipped, that the parts are intact pieces,
        and that the file this call wrote really holds them.

        WHAT WAS NOT MEASURED IS ITSELF A FAILURE. `gate="none"` writes files
        and verifies none of them, so it cannot pass; a `truncated` export can
        pass the checks that ran but says which ones did not, because "nothing
        found" and "nothing looked at" must never read the same.
        """
        found_failures: list[str] = []
        if self.gate == "none":
            found_failures.append(
                "unverified: gate='none' skipped every check; re-export with "
                "gate='structure' or 'full' before shipping"
            )
            if self.blend is None:
                found_failures.append(
                    "no .blend source: an asset without it is not done"
                )
            return found_failures
        for part_name, part_failure in self.part_failures:
            found_failures.append(
                f"part {part_name!r} fails the piece gate: {part_failure}"
            )
        if (
            REIMPORT_CHECK not in self.skipped_checks
            and self.reimported_object_count != self.keep_parts
        ):
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
            # The count the file must carry: the combined mesh's own when it was
            # analysed, otherwise the parts' sum, which is the same number.
            expected_triangle_count = (
                self.pre_export.triangle_count
                if self.pre_export is not None
                else self.expected_triangle_count
            )
            if self.file_report.triangle_count != expected_triangle_count:
                found_failures.append(
                    f"file ships {self.file_report.triangle_count} triangles, the "
                    f"assembly measured {expected_triangle_count} "
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
        # An asset a character cannot use is not done either. A side is
        # BLOCKED when another part of the same assembly stands inside the
        # space a player needs to approach it: the ovens facing each other
        # and the spout sunk in the wall that no structural gate saw. The
        # sentence names the part, the side, the measured clearance and what
        # is standing there, so the fix is a rotation or a move rather than
        # a guess.
        for blocked_side in self.blocked_sides:
            blockers = (
                ", ".join(
                    f"{name} at {distance:.3f} m"
                    for name, distance in blocked_side.blocked_by
                )
                or "no part named (the face is buried)"
            )
            found_failures.append(
                f"part {blocked_side.object_name!r} cannot be USED: its "
                f"{blocked_side.side} side has {blocked_side.clearance_m:.3f} m "
                f"of clear space (median; worst "
                f"{blocked_side.minimum_clearance_m:.3f} m, "
                f"{blocked_side.blocked_fraction:.0%} of the face inside "
                f"{MINIMUM_APPROACH_M} m), blocked by {blockers}. A character "
                f"must be able to reach the side it uses: rotate or move the "
                f"part, or declare a different side with declare_interaction_side"
            )
        if REIMPORT_CHECK not in self.skipped_checks:
            for axis_index, axis_name in enumerate(("x", "y", "z")):
                drift_m = abs(
                    self.reimported_dimensions_m[axis_index]
                    - self.pre_export_dimensions_m[axis_index]
                )
                if drift_m > EXPORT_DIMENSION_TOLERANCE_M:
                    found_failures.append(
                        f"dimension {axis_name} drifted {drift_m:.6f} m through "
                        f"export (axis-convention or unit error)"
                    )
        if self.truncated:
            found_failures.append(
                f"gate truncated at budget_s: checked {self.gate_checked_parts} "
                f"of {self.part_count} parts; skipped {list(self.skipped_checks)}"
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
