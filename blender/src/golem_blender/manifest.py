"""The agent-facing capability manifest.

SWE-agent's measured result: a purpose-built agent-computer interface
beat a bare shell 18.0% vs 11.0% on the same model. This module is that
interface's documentation half — what an agent is told it can do before
it writes a line of bpy.

It is GENERATED FROM THE LIVE CODE (introspecting the real op modules,
the real MeshBudget fields, the real drift catalog) rather than
hand-written prose, so it cannot quietly drift out of sync with the
harness it describes. A stale manifest would be worse than none: it
would teach the agent APIs that no longer exist, which is precisely the
failure mode the drift catalog exists to prevent.
"""

from __future__ import annotations

import dataclasses
import inspect
from dataclasses import fields

OP_MODULE_NAMES = (
    "assembly",
    "primitives",
    "materials",
    "material_nodes",
    "booleans",
    "lathe",
    "arrays",
    "legs",
    "transforms",
    "alignment",
    "assets",
    "measure_set",
    "pieces",
    "modifiers",
    "heal",
    "roughen",
    "uv",
    "pbr_textures",
    "pbr_bake",
    "relief",
    "rigging",
    "weights",
    "animation",
    "canonical_orientation",
    "selectors",
    "motion",
)

# Config dataclasses that an operation takes as an argument. Listed
# because a signature reading `spec: SplayedLegSpec` documents nothing
# on its own — an agent cannot construct a type it has never been
# shown, and would fall back to hand-rolling the geometry the op
# exists to get right.
OP_CONFIG_DATACLASSES = (
    ("golem_blender.ops.legs", "SplayedLegSpec"),
    ("golem_blender.ops.motion", "RingSkirtSpec"),
    ("golem_blender.ops.rigging", "BoneSpec"),
    ("golem_blender.ops.selectors", "EdgeSelector"),
    ("golem_blender.ops.selectors", "FaceSelector"),
    ("golem_blender.ops.selectors", "VertexSelector"),
)

CONVENTIONS = (
    (
        "Build with `golem_blender.ops`, NOT raw bpy. The ops are context-free, "
        "version-drift-resistant, and idempotent by name; raw bpy.ops is "
        "none of those."
    ),
    (
        "Never call bpy.ops primitives (primitive_cube_add etc). Their "
        "keyword arguments drift between versions."
    ),
    (
        "Objects must be linked into the scene (`link_into_scene`) or the "
        "depsgraph has no instance and measurements silently return stored "
        "values instead of evaluated ones."
    ),
    (
        "Dimensions are in METERS and variable names carry the unit suffix "
        "(`width_m`, `height_m`)."
    ),
    (
        "No magic numbers. Every constant is module-level, named, and "
        "carries the reason for its value."
    ),
    (
        "Parts that will be unioned must OVERLAP slightly first; booleans "
        "on exactly-coplanar faces are the EXACT solver's worst case."
    ),
    (
        "An applied array is N disconnected islands until something bridges "
        "them. Union the connector in, or the gate fails on component count."
    ),
    (
        "Build the object with the EXACT name you were asked for. The "
        "harness looks it up by name after your code runs."
    ),
)


def _public_functions(module) -> list[tuple[str, str]]:
    """Return (signature, first docstring line) for a module's API."""
    described: list[tuple[str, str]] = []
    for function_name, function_object in inspect.getmembers(
        module, inspect.isfunction
    ):
        if function_name.startswith("_"):
            continue
        if function_object.__module__ != module.__name__:
            continue  # imported, not defined here
        try:
            signature = str(inspect.signature(function_object))
        except (TypeError, ValueError):  # pragma: no cover
            signature = "(...)"
        docstring = inspect.getdoc(function_object) or ""
        summary = docstring.split("\n", 1)[0] if docstring else ""
        described.append((f"{function_name}{signature}", summary))
    return described


def build_manifest(include_drift_catalog: bool = True) -> str:
    """Render the manifest an agent reads before writing modeling code."""
    import importlib

    from golem_blender.analyze.mesh_checks import MeshBudget
    from golem_blender.version import TARGET_BLENDER_SERIES

    sections: list[str] = []
    sections.append(
        f"# golem_blender — capability manifest\n\n"
        f"You are writing Python that runs inside Blender "
        f"{TARGET_BLENDER_SERIES[0]}.{TARGET_BLENDER_SERIES[1]}. Your code "
        f"is executed, then the resulting mesh is measured by an analyzer "
        f"gate. Executing without an error is NOT success — the gate "
        f"decides."
    )

    sections.append("## Conventions (violating these fails the gate)\n")
    sections.append(
        "\n".join(f"{index}. {rule}" for index, rule in enumerate(CONVENTIONS, 1))
    )

    sections.append("\n## Available operations — `from golem_blender.ops import ...`\n")
    for module_name in OP_MODULE_NAMES:
        module = importlib.import_module(f"golem_blender.ops.{module_name}")
        functions = _public_functions(module)
        if not functions:
            continue
        sections.append(f"### golem_blender.ops.{module_name}")
        for signature, summary in functions:
            sections.append(f"- `{signature}`\n      {summary}")

    if OP_CONFIG_DATACLASSES:
        sections.append("\n### Operation config objects\n")
        for module_path, class_name in OP_CONFIG_DATACLASSES:
            config_class = getattr(importlib.import_module(module_path), class_name)
            sections.append(
                f"- `{class_name}` — "
                f"{(config_class.__doc__ or '').strip().splitlines()[0]}"
            )
            for config_field in fields(config_class):
                default = config_field.default
                shown_default = (
                    "" if default is dataclasses.MISSING else f" = {default}"
                )
                sections.append(
                    f"      `{config_field.name}: {config_field.type}{shown_default}`"
                )

    sections.append("\n## What the gate measures\n")
    sections.append(
        "Your mesh is analyzed and checked against a budget. The report fields are:"
    )
    from golem_blender.analyze.mesh_checks import MeshReport

    for report_field in fields(MeshReport):
        if report_field.name == "object_name":
            continue
        sections.append(f"- `{report_field.name}`")
    sections.append("\nBudget knobs (defaults in parentheses):")
    default_budget = MeshBudget()
    for budget_field in fields(MeshBudget):
        sections.append(
            f"- `{budget_field.name}` ({getattr(default_budget, budget_field.name)})"
        )

    if include_drift_catalog:
        from golem_blender.drift.catalog import DRIFT_ENTRIES

        sections.append("\n## Known API traps (measured — do not rediscover these)\n")
        for entry in DRIFT_ENTRIES:
            sections.append(f"- **{entry.symbol}** — {entry.fix}")

    sections.append(
        "\n## Your output\n\n"
        "Return ONLY executable Python. No markdown fences, no prose, no "
        "explanation. The response is written verbatim to a .py file and "
        "executed. Begin with the imports you need."
    )
    return "\n".join(sections)
