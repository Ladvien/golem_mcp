"""The harness entry point: the whole loop in one call.

    execute (retry <= 2, logged) -> analyzer gate -> contact sheet
        -> (optional) verified glTF export

Two front doors, one spine:

* run_chunk(source, ...)  — the AGENT path: source code in, structured
  result out. The fix_source callback is where the agent rewrites code
  from the drift-annotated retry prompt.
* run_builder(builder, ...) — the LIBRARY path: a Parameters+Builder
  object in, same gates, same result.

Design commitments enforced here rather than re-argued per call site:
the analyzer is the hard gate; the contact sheet is produced on FAIL
as well as PASS (a failure you cannot review is a failure you will
repeat); export only runs on gate-passing meshes and is itself
verified by welded round trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from golem_blender.analyze.mesh_checks import MeshBudget, MeshReport
from golem_blender.stages import (
    STAGE_DONE,
    STAGE_EXECUTE,
    STAGE_EXPORT,
    STAGE_GATE,
    STAGE_LOCATE,
)

DEFAULT_OUTPUT_DIRECTORY = Path("_renders/harness")


@dataclass(frozen=True)
class HarnessSettings:
    budget: MeshBudget = MeshBudget()
    output_directory: Path = DEFAULT_OUTPUT_DIRECTORY
    maximum_retries: int = 2
    export_glb_path: Path | None = None  # set to also export + round-trip
    # Where the exported asset's editable .blend goes (OT-50). REQUIRED
    # whenever export_glb_path is set: require_export_blend_path refuses
    # the run before anything is built, and there is no default beside the
    # .glb, so the caller chooses where the source lives.
    export_blend_path: Path | None = None
    session_log_path: Path | None = None


def require_export_blend_path(settings: HarnessSettings) -> None:
    """Refuse a run that would export a .glb with nowhere to save its .blend."""
    if settings.export_glb_path is not None and settings.export_blend_path is None:
        raise ValueError(
            f"HarnessSettings.export_glb_path is set ({settings.export_glb_path}) "
            f"but export_blend_path is not: every exported asset ships with "
            f"its .blend source, so the caller must choose where it goes."
        )


@dataclass(frozen=True)
class GateVerdict:
    """What the gate measured about ONE named object.

    Shared by `run_chunk` (the object a chunk was asked to gate) and by
    an op-tool call (the object the op returned, OT-5), so the two paths
    cannot disagree about what "gated" means. `stage_reached` is
    `locate` when the object is missing or unusable, `gate` when the
    analyzer failed it, `done` when it passed.
    """

    object_name: str
    stage_reached: str  # locate | gate | done
    object_type: str = "MESH"
    scene_state: str = ""  # why the object is unusable; "" when usable
    report: MeshReport | None = None
    gate_failures: tuple[str, ...] = field(default_factory=tuple)
    world_extents_m: tuple[float, float, float] | None = None

    @property
    def ok(self) -> bool:
        return self.stage_reached == STAGE_DONE


def gate_verdict_json(verdict: GateVerdict) -> dict:
    """The verdict as the transcript records it (OT-8): every field, the
    analyzer report expanded, tuples as lists."""
    from dataclasses import asdict

    return {
        "object_name": verdict.object_name,
        "stage_reached": verdict.stage_reached,
        "object_type": verdict.object_type,
        "scene_state": verdict.scene_state,
        "gate_failures": list(verdict.gate_failures),
        "world_extents_m": (
            list(verdict.world_extents_m)
            if verdict.world_extents_m is not None
            else None
        ),
        "report": asdict(verdict.report) if verdict.report is not None else None,
    }


def harness_result_gate_json(result: HarnessResult) -> dict:
    """`run_chunk`'s gate, in the same form as an op call's."""
    return gate_verdict_json(
        GateVerdict(
            object_name=result.object_name,
            stage_reached=result.stage_reached,
            object_type=result.object_type,
            report=result.report,
            gate_failures=result.gate_failures,
            world_extents_m=result.world_extents_m,
        )
    )


def gate_summary_lines(
    object_type: str,
    report: MeshReport | None,
    gate_failures: tuple[str, ...],
    world_extents_m: tuple[float, float, float] | None,
) -> list[str]:
    """The gate's lines of a result summary, one text for both paths."""
    lines: list[str] = []
    if report is not None:
        lines.append(
            f"  gate: {'PASS' if not gate_failures else 'FAIL'} "
            f"({report.triangle_count} tris, "
            f"{report.connected_component_count} components)"
        )
        lines.extend(facing_summary_lines(report))
    elif object_type != "MESH":
        lines.append(f"  gate: scene state only ({object_type} has no mesh to analyze)")
    if world_extents_m is not None:
        # Computed by the pure text function from the stored tuple, so
        # summaries stay free of bpy and the tool the writer checks its
        # own work with cannot disagree with the gate.
        from golem_blender.ops.canonical_orientation import orientation_reading

        lines.append(f"  orient: {orientation_reading(world_extents_m)}")
    lines.extend(f"    - {failure}" for failure in gate_failures)
    return lines


def facing_summary_lines(report: MeshReport) -> list[str]:
    """The gate's facing line: inward area, or why nobody measured it.

    Two different "nothing to report" cases, and the text keeps them apart:
    a shell that IS inward-facing says so with a number, and a mesh too big
    to measure says so with its size. Silence about a measurement that
    failed would read exactly like a pass.
    """
    from golem_blender.analyze.mesh_checks import WINDING_GATE_TRIANGLE_LIMIT

    if report.inward_area_fraction < 0.0:
        return [
            (
                f"  facing: not measured ({report.triangle_count} triangles > "
                f"{WINDING_GATE_TRIANGLE_LIMIT})"
            )
        ]
    if report.inward_area_fraction > 0.0:
        return [
            (
                f"  facing: inward {report.inward_area_fraction:.0%} of area, "
                f"undecided {report.undecided_area_fraction:.0%}"
            )
        ]
    return []


def gate_object(blender_object, budget: MeshBudget) -> GateVerdict:
    """Scene state first, then the analyzer — for a MESH. Anything else
    (an armature) is judged on scene state alone: the analyzer measures
    meshes, and `to_mesh()` on an armature is None."""
    unusable = scene_state_failure(blender_object)
    if unusable:
        return GateVerdict(
            object_name=blender_object.name,
            stage_reached=STAGE_LOCATE,
            object_type=blender_object.type,
            scene_state=unusable,
        )
    # The WORLD box — `matrix_world @ bound_box`, the one measurement
    # `apply_canonical_depth_axis` will act on (OT-34). Not
    # `object.dimensions`: that is the local box scaled and ignores
    # rotation, so a writer who turned its object was told one axis
    # assignment and had another applied. Carried on every verdict from
    # here on, including the gate-FAIL one — a writer whose gate just
    # failed is exactly who needs to know which axis holds which extent.
    from golem_blender.ops.transforms import _world_extents_m

    extent_x_m, extent_y_m, extent_z_m = _world_extents_m([blender_object])
    world_extents_m = (float(extent_x_m), float(extent_y_m), float(extent_z_m))
    if blender_object.type != "MESH":
        return GateVerdict(
            object_name=blender_object.name,
            stage_reached=STAGE_DONE,
            object_type=blender_object.type,
            world_extents_m=world_extents_m,
        )
    from golem_blender.analyze import analyze_object

    report = analyze_object(blender_object, budget)
    gate_failures = tuple(report.failures(budget))
    return GateVerdict(
        object_name=blender_object.name,
        stage_reached=STAGE_GATE if gate_failures else STAGE_DONE,
        object_type=blender_object.type,
        report=report,
        gate_failures=gate_failures,
        world_extents_m=world_extents_m,
    )


def gate_named_object(object_name: str, budget: MeshBudget) -> GateVerdict:
    """`gate_object` by name; a missing object fails at `locate`."""
    import bpy

    blender_object = bpy.data.objects.get(object_name)
    if blender_object is None:
        return GateVerdict(
            object_name=object_name,
            stage_reached=STAGE_LOCATE,
            object_type="",
            scene_state=f"no object named {object_name!r} in bpy.data.objects",
        )
    return gate_object(blender_object, budget)


@dataclass(frozen=True)
class HarnessResult:
    ok: bool
    stage_reached: str  # one of golem_blender.stages.STAGES (EXE-6)
    object_name: str = ""
    report: MeshReport | None = None
    gate_failures: tuple[str, ...] = field(default_factory=tuple)
    object_type: str = "MESH"
    contact_sheet_path: Path | None = None
    export_failures: tuple[str, ...] = field(default_factory=tuple)
    export_path: Path | None = None
    export_file_size_bytes: int = 0
    export_blend_path: Path | None = None
    execution_summary: str = ""
    # WHERE THE EXTENTS LANDED, so the writer can see it during the turn.
    # The harness rotates the finished object by exactly this reading
    # (`ops.canonical_orientation.apply_canonical_depth_axis`), and the
    # bench prompt carries a placement clause — both AFTER or BESIDE the
    # writer's own decision. Nothing here gates; it is a fact arriving
    # early enough to act on.
    world_extents_m: tuple[float, float, float] | None = None

    def summary(self) -> str:
        verdict = "OK" if self.ok else f"FAILED at {self.stage_reached}"
        lines = [f"{verdict}: {self.object_name or '<no object>'}"]
        if self.execution_summary:
            lines.append(f"  execute: {self.execution_summary}")
        lines.extend(
            gate_summary_lines(
                self.object_type, self.report, self.gate_failures, self.world_extents_m
            )
        )
        lines.extend(f"  export: {failure}" for failure in self.export_failures)
        if self.export_path is not None and not self.export_failures:
            lines.append(
                f"  export: verified round-trip "
                f"({self.export_path}, {self.export_file_size_bytes} bytes)"
            )
        if self.export_blend_path is not None:
            lines.append(f"  export: .blend source saved ({self.export_blend_path})")
        if self.contact_sheet_path is not None:
            lines.append(f"  sheet: {self.contact_sheet_path}")
        return "\n".join(lines)


# An object can hold flawless geometry and still be invisible, and every
# mesh check would still pass: the analyzer reads the mesh datablock, and
# the capture path links a copy into a temporary scene of its own, so it
# renders a contact sheet for an asset nobody can see.
#
# Measured 2026-09-05, one live GUI turn plus a probe of every cause:
#
#   cause                          scene  view_layer  visible_get  gate
#   never linked                   False  False       False        PASS
#   collection excluded            True   False       False        PASS
#   hide_viewport = True           True   True        False        PASS
#   hide_set(True) (eye icon)      True   True        False        PASS
#   control                        True   True        True         PASS
#
# `Object.visible_get()` is False for all four, so ONE call is the whole
# rule — but the model has to know WHICH cause to fix, so the causes are
# distinguished for the message and nothing else.
#
# `hide_render` is the fifth cause and the sneakiest: `visible_get()`
# stays True, the user does see the object, and the gate passes — while
# the render it is judged by silently loses it. Measured on the harness's
# own contact sheet: 634280 bytes with the object, 318310 without.
VISIBILITY_FAILURES = {
    "unlinked": (
        "{name!r} exists as a datablock but is NOT linked into the scene, "
        "so nothing the user can see has changed and it would be missing "
        "from any export. Link it at the end of the chunk with "
        "`golem_blender.ops.link_into_scene({name!r})`."
    ),
    "excluded": (
        "{name!r} is linked into the scene but sits in a collection that "
        "is EXCLUDED from the view layer, so the user's viewport never "
        "shows it. Link it into the scene collection instead of an "
        "excluded one."
    ),
    "hidden": (
        "{name!r} is in the view layer but HIDDEN "
        "(`hide_viewport = True` or `hide_set(True)`), so the user sees "
        "nothing. Clear the flag on the object you just built."
    ),
    "unrenderable": (
        "{name!r} is visible in the viewport but has "
        "`hide_render = True`, so it is absent from every render — "
        "including the contact sheet this gate would have shown you. "
        "Clear it."
    ),
}


def invisibility_failure(blender_object) -> str:
    """Why this object cannot be seen, or "" when it can.

    One ordered walk from the coarsest cause to the finest, so the
    message names the thing to fix rather than the symptom.

    The view layer is synced first, and that is load-bearing: an object
    linked by the chunk that just ran is in `scene.objects` immediately
    but does NOT appear in `view_layer.objects` until the depsgraph
    catches up, so without this the gate accused every freshly built
    object of sitting in an excluded collection (caught by
    tests/blender/test_harness.py and test_task_loop.py).
    """
    import bpy

    _synchronise_view_layer()
    name = blender_object.name
    if name not in bpy.context.scene.objects:
        return VISIBILITY_FAILURES["unlinked"].format(name=name)
    if name not in bpy.context.view_layer.objects:
        return VISIBILITY_FAILURES["excluded"].format(name=name)
    if not blender_object.visible_get():
        return VISIBILITY_FAILURES["hidden"].format(name=name)
    if blender_object.hide_render:
        return VISIBILITY_FAILURES["unrenderable"].format(name=name)
    return ""


# The analyzer measures the EVALUATED mesh (modifiers included) in the
# object's own LOCAL space, so the object matrix sits outside everything
# it can see. Measured 2026-09-05, every case gate=PASS before this:
#
#   transform            world extent        glTF export
#   scale.x = 0          (0, 1, 1)           writes a degenerate mesh
#   scale.x = 1e-9       (1e-09, 1, 1)       writes a degenerate mesh
#   location.x = NaN     (nan, 1, 1)         writes, silently poisoned
#   scale.x = inf        (3.4e+38, 1, 1)     raises RuntimeError
#   scale.x = 10         (10, 1, 1)          fine — a legitimate stretch
#
# A NaN transform is the worst of them: the mesh measures perfect, the
# gate passes, and every world-space number the model prints back to
# itself is NaN.
TRANSFORM_FAILURES = {
    "non_finite": (
        "{name!r} has a NON-FINITE object transform ({detail}), so every "
        "world-space measurement you print is meaningless and a glTF "
        "export raises. Its mesh is fine — fix the object's location, "
        "rotation or scale."
    ),
    "collapsed": (
        "{name!r} has a COLLAPSED axis in its transform (world scale "
        "{detail}), so it is flattened to nothing in the scene even "
        "though its mesh measures fine. Give it a non-zero scale, or "
        "bake the intended size into the mesh."
    ),
}
# Nothing legitimate scales one axis a MILLION times smaller than
# another: a 1 cm panel cut from a 1 m cube is 1e-2, and a small object
# is scaled uniformly (ratio 1), so this catches only genuine collapse.
# The observed degenerate values are exactly 0 and 1e-9.
COLLAPSED_SCALE_RATIO = 1e-6


def _synchronise_view_layer() -> None:
    """Make the evaluated scene state current before reading it.

    Load-bearing for BOTH scene-state checks, and for the same reason:
    an object linked by the chunk that just ran is absent from
    `view_layer.objects`, and a scale assigned by that chunk is absent
    from `matrix_world`, until the depsgraph catches up. Reading either
    without this measures the previous frame — which first turned nine
    green tests red, then hid a collapsed transform behind a PASS.
    """
    import bpy

    bpy.context.view_layer.update()


def degenerate_transform_failure(blender_object) -> str:
    """Why this object's transform is unusable, or "" when it is fine.

    Tests the SCALE LENGTHS' anisotropy rather than the determinant: a
    legitimately tiny object (a 1 mm cube scaled 0.001 uniformly) has a
    determinant of 1e-9 while being perfectly healthy, so a determinant
    threshold would refuse real work.
    """
    import math

    _synchronise_view_layer()
    matrix = blender_object.matrix_world
    non_finite = [value for row in matrix for value in row if not math.isfinite(value)]
    if non_finite:
        return TRANSFORM_FAILURES["non_finite"].format(
            name=blender_object.name,
            detail=f"{len(non_finite)} non-finite matrix element(s)",
        )
    scale = matrix.to_scale()
    magnitudes = [abs(component) for component in scale]
    if max(magnitudes) == 0.0 or (
        min(magnitudes) / max(magnitudes) < COLLAPSED_SCALE_RATIO
    ):
        return TRANSFORM_FAILURES["collapsed"].format(
            name=blender_object.name,
            detail="(" + ", ".join(f"{value:.3g}" for value in scale) + ")",
        )
    return ""


def scene_state_failure(blender_object) -> str:
    """Everything the mesh analyzer cannot see, in one call.

    The transform first: with a NaN matrix, "can it be seen" is not even
    a meaningful question.
    """
    return degenerate_transform_failure(blender_object) or invisibility_failure(
        blender_object
    )


def _gate_capture_export(
    blender_object, settings: HarnessSettings, execution_summary: str
) -> HarnessResult:
    """The shared back half: gate (scene state + analyzer), sheet, optionally export."""
    from golem_blender.capture import capture_contact_sheet

    verdict = gate_object(blender_object, settings.budget)
    if verdict.stage_reached == STAGE_LOCATE:
        return HarnessResult(
            ok=False,
            stage_reached=STAGE_LOCATE,
            object_name=verdict.object_name,
            object_type=verdict.object_type,
            execution_summary=execution_summary + "; " + verdict.scene_state,
        )
    if verdict.report is None:
        # Not a mesh: scene state was the whole gate, and there is no
        # mesh to sheet or to round-trip.
        return HarnessResult(
            ok=True,
            stage_reached=STAGE_DONE,
            object_name=verdict.object_name,
            object_type=verdict.object_type,
            execution_summary=execution_summary,
            world_extents_m=verdict.world_extents_m,
        )
    contact_sheet_path = capture_contact_sheet(
        blender_object,
        settings.output_directory,
        report=verdict.report,
        budget=settings.budget,
    )
    if verdict.gate_failures:
        return HarnessResult(
            ok=False,
            stage_reached=STAGE_GATE,
            object_name=verdict.object_name,
            object_type=verdict.object_type,
            report=verdict.report,
            gate_failures=verdict.gate_failures,
            contact_sheet_path=contact_sheet_path,
            execution_summary=execution_summary,
            world_extents_m=verdict.world_extents_m,
        )

    export_path: Path | None = None
    export_file_size_bytes = 0
    export_blend_path: Path | None = None
    if settings.export_glb_path is not None:
        from golem_blender.export import export_glb

        export_report = export_glb(
            blender_object,
            settings.export_glb_path,
            blend_path=settings.export_blend_path,
        )
        export_failures = tuple(export_report.round_trip_failures(settings.budget))
        export_path = export_report.export_path
        export_file_size_bytes = export_report.file_size_bytes
        export_blend_path = export_report.blend.blend_path
        if export_failures:
            return HarnessResult(
                ok=False,
                stage_reached=STAGE_EXPORT,
                object_name=verdict.object_name,
                object_type=verdict.object_type,
                report=verdict.report,
                contact_sheet_path=contact_sheet_path,
                export_failures=export_failures,
                execution_summary=execution_summary,
                world_extents_m=verdict.world_extents_m,
            )

    return HarnessResult(
        ok=True,
        stage_reached=STAGE_DONE,
        object_name=verdict.object_name,
        object_type=verdict.object_type,
        report=verdict.report,
        contact_sheet_path=contact_sheet_path,
        export_path=export_path,
        export_file_size_bytes=export_file_size_bytes,
        export_blend_path=export_blend_path,
        execution_summary=execution_summary,
        world_extents_m=verdict.world_extents_m,
    )


def run_chunk(
    source_code: str,
    object_name: str,
    fix_source=None,
    settings: HarnessSettings = HarnessSettings(),
    chunk_label: str = "<agent>",
) -> HarnessResult:
    """The agent path: execute source, then gate the named object."""
    require_export_blend_path(settings)
    import bpy

    from golem_blender.run.retry import run_with_retries
    from golem_blender.run.session_log import SessionLog

    session_log = (
        SessionLog(settings.session_log_path)
        if settings.session_log_path is not None
        else None
    )
    if fix_source is None:
        maximum_retries = 0

        def fix_source(previous_source, result):  # pragma: no cover
            return previous_source
    else:
        maximum_retries = settings.maximum_retries

    outcome = run_with_retries(
        source_code,
        fix_source,
        maximum_retries=maximum_retries,
        script_name=chunk_label,
        session_log=session_log,
    )
    # final_result.summary() already carries the chunk's printed output;
    # that is the agent's only observation channel into the scene.
    execution_summary = (
        f"{outcome.attempt_count} attempt(s), {outcome.final_result.summary()}"
    )
    if not outcome.ok:
        return HarnessResult(
            ok=False, stage_reached=STAGE_EXECUTE, execution_summary=execution_summary
        )

    built_object = bpy.data.objects.get(object_name)
    if built_object is None:
        return HarnessResult(
            ok=False,
            stage_reached=STAGE_LOCATE,
            object_name=object_name,
            execution_summary=execution_summary
            + f"; expected object {object_name!r} does not exist "
            + "(no such datablock in bpy.data.objects)",
        )
    return _gate_capture_export(built_object, settings, execution_summary)


def run_builder(
    builder, settings: HarnessSettings = HarnessSettings()
) -> HarnessResult:
    """The library path: build via a Parameters+Builder object, then gate."""
    require_export_blend_path(settings)
    try:
        built_object = builder.build()
    except Exception as build_error:  # noqa: BLE001 — reported, not swallowed
        import traceback

        return HarnessResult(
            ok=False,
            stage_reached=STAGE_EXECUTE,
            execution_summary=(
                f"builder raised {type(build_error).__name__}: {build_error}\n"
                f"{traceback.format_exc()}"
            ),
        )
    return _gate_capture_export(built_object, settings, execution_summary="builder ok")
