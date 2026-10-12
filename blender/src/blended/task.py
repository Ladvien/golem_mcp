"""The task entry point: intent in, verified asset out.

This is the layer that was missing while `blended` was only a
well-instrumented modeling library. It closes the loop the research
describes: a task specification goes in, an agent writes code, the code
executes, the GATE judges it, and any failure is fed back to the agent
in a form written FOR the agent rather than for a human reading chat.

The `write_code` callback is the model boundary. The harness never
imports an LLM client; whoever calls this supplies one. That keeps the
gates testable with deterministic stand-ins and keeps model choice out
of the harness.

Iteration is capped at 3 rounds (measured: quality converges or
degrades past ~3 — Planner-Actor-Critic 2026), after which the task
escalates to a human with the contact sheet attached.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from blended.analyze.mesh_checks import MeshBudget
from blended.harness import HarnessResult, HarnessSettings, run_chunk
from blended.stages import STAGE_EXECUTE, STAGE_EXPORT, STAGE_GATE, STAGE_LOCATE

MAXIMUM_TASK_ROUNDS = 3


@dataclass(frozen=True)
class AgentTask:
    """What the agent is being asked to build."""

    object_name: str
    description: str
    budget: MeshBudget = MeshBudget()
    requirements: tuple[str, ...] = ()

    def brief(self, include_manifest: bool = True) -> str:
        """The full prompt an agent receives for round one."""
        from blended.manifest import build_manifest

        sections = []
        if include_manifest:
            sections.append(build_manifest())
        sections.append("\n# Your task\n")
        sections.append(self.description)
        sections.append(
            f"\nThe finished object must be named exactly `{self.object_name}`."
        )
        if self.requirements:
            sections.append("\nRequirements:")
            sections.extend(f"- {requirement}" for requirement in self.requirements)
        sections.append(
            f"\nBudget: at most {self.budget.maximum_triangle_count} triangles, "
            f"at most {self.budget.maximum_component_count} connected "
            f"component(s)."
        )
        return "\n".join(sections)


def build_gate_feedback(
    result: HarnessResult,
    task: AgentTask,
    include_manifest: bool = False,
) -> str:
    """Turn a harness failure into instructions an AGENT can act on.

    Deliberately not human prose. It states which stage failed, the
    measured numbers, and — where the failure has a known structural
    cause — the specific fix, because the measured lesson from
    3DCodeBench is that agents fix localized problems well once the
    problem is actually visible to them.

    `include_manifest` re-attaches the capability manifest. Measured
    reason it exists: feedback that says "use boolean_union" is useless
    to an agent that was never told `blended.ops` exists — it will keep
    reaching for raw bpy and keep failing the same way. When the failure
    is structural (components, self-intersections), the agent needs the
    capability list, not just the diagnosis.
    """
    lines = [
        f"Your previous attempt FAILED at the `{result.stage_reached}` stage.",
    ]
    if result.stage_reached == STAGE_EXECUTE:
        lines.append(
            f"The code did not run. Full execution detail:\n{result.execution_summary}"
        )
    elif result.stage_reached == STAGE_LOCATE:
        # `locate` is also where the scene-state gate stops an object that
        # EXISTS but is hidden, unlinked or has a broken transform; the
        # execution summary carries which one.
        lines.append(
            f"The code ran without error but `{task.object_name}` was not "
            f"usable afterwards. Build the object under exactly that name, "
            f"linked into the scene and visible. Detail:\n"
            f"{result.execution_summary}"
        )
    elif result.stage_reached == STAGE_GATE:
        lines.append("The code ran, but the mesh failed the analyzer gate:")
        lines.extend(f"  - {failure}" for failure in result.gate_failures)
        if result.report is not None:
            lines.append(
                f"\nMeasured: {result.report.triangle_count} triangles, "
                f"{result.report.connected_component_count} components, "
                f"{result.report.self_intersecting_face_pair_count} "
                f"self-intersecting pairs, "
                f"{result.report.boundary_edge_count} boundary edges, "
                f"{result.report.flipped_normal_triangle_count} inward-facing "
                f"triangles."
            )
        lines.append("\n" + _structural_hints(result))
    elif result.stage_reached == STAGE_EXPORT:
        lines.append("The mesh passed the gate but failed export verification:")
        lines.extend(f"  - {failure}" for failure in result.export_failures)

    if include_manifest:
        from blended.manifest import build_manifest

        lines.append(
            "\nUse these operations rather than raw bpy — they are "
            "context-free, drift-resistant, and maintain the invariants the "
            "gate checks:\n"
        )
        lines.append(build_manifest())
    lines.append(
        "\nReturn the COMPLETE corrected Python source. No markdown fences, no prose."
    )
    return "\n".join(lines)


def _structural_hints(result: HarnessResult) -> str:
    """Map measured failures to their known structural causes."""
    if result.report is None:
        return ""
    hints: list[str] = []
    if result.report.connected_component_count > 1:
        hints.append(
            f"{result.report.connected_component_count} components means your "
            f"parts are not touching. Parts must OVERLAP in 3D before "
            f"boolean_union, and every part must be unioned into the single "
            f"target object."
        )
    if result.report.self_intersecting_face_pair_count > 0:
        hints.append(
            "Self-intersections mean geometry passes through other geometry "
            "without being merged. Use boolean_union rather than leaving "
            "parts overlapping, and union every part into one object."
        )
    if result.report.boundary_edge_count > 0:
        hints.append(
            "Boundary edges mean the mesh is open (not watertight). Every "
            "part must be a closed solid, and unions must actually merge."
        )
    if result.report.flipped_normal_triangle_count > 0:
        hints.append(
            "Inward-facing triangles: do not flip normals manually; build "
            "with the ops and let boolean/heal maintain orientation."
        )
    if not hints:
        return "Address the measured failures above."
    return "Likely causes:\n" + "\n".join(f"  - {hint}" for hint in hints)


@dataclass(frozen=True)
class TaskResult:
    ok: bool
    rounds_used: int
    final: HarnessResult
    sources: tuple[str, ...] = field(default_factory=tuple)
    feedback_given: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> str:
        verdict = "SUCCEEDED" if self.ok else "ESCALATE TO HUMAN"
        return f"{verdict} after {self.rounds_used} round(s)\n{self.final.summary()}"


def run_agent_task(
    task: AgentTask,
    write_code: Callable[[str], str],
    settings: HarnessSettings | None = None,
    maximum_rounds: int = MAXIMUM_TASK_ROUNDS,
) -> TaskResult:
    """Run a task to completion or escalation.

    `write_code(prompt) -> python_source` is the model boundary: called
    once with the full brief, then once per round with gate feedback.
    """
    if maximum_rounds < 1:
        raise ValueError(
            f"maximum_rounds must be at least 1, got {maximum_rounds}: "
            f"a task that never runs has no result to return"
        )
    settings = settings or HarnessSettings(budget=task.budget)
    if settings.budget != task.budget:
        settings = replace(settings, budget=task.budget)

    sources: list[str] = []
    feedback_given: list[str] = []
    prompt = task.brief()

    for round_index in range(1, maximum_rounds + 1):
        source_code = write_code(prompt)
        sources.append(source_code)
        result = run_chunk(
            source_code,
            object_name=task.object_name,
            settings=settings,
            chunk_label=f"{task.object_name}_round{round_index}",
        )
        if result.ok:
            return TaskResult(
                ok=True,
                rounds_used=round_index,
                final=result,
                sources=tuple(sources),
                feedback_given=tuple(feedback_given),
            )
        if round_index < maximum_rounds:
            # Structural failures mean the agent needs the capability
            # list, not just the diagnosis.
            structural = (
                result.stage_reached == STAGE_GATE
                and result.report is not None
                and (
                    result.report.connected_component_count > 1
                    or result.report.self_intersecting_face_pair_count > 0
                )
            )
            prompt = build_gate_feedback(result, task, include_manifest=structural)
            feedback_given.append(prompt)

    return TaskResult(
        ok=False,
        rounds_used=maximum_rounds,
        final=result,
        sources=tuple(sources),
        feedback_given=tuple(feedback_given),
    )
