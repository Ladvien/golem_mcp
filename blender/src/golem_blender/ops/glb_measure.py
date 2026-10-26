"""A shipped .glb measured read-only, in the frame the engine loads it in.

`export/glb_report.py` answers the file's INTEGRITY (inverted facets, boundary
edges, weight sums) in mesh-local space; that is the right frame for integrity
and the wrong one for placement. The questions this op answers are the ones a
level designer asks about a file already in the game: how tall is it, does it
stand on its base, what is its pivot off by, which faces could a character stand
on, and what does the section across it look like.

`export/glb_geometry.py` does the arithmetic (pure: json, math, struct — it
imports from the pure layer and works in `test-pure`). This module is the op:
it names the file, validates the arguments, and returns the frozen report.

Reads a file and nothing else: it never touches bpy, so it cannot disturb the
scene, the viewport or the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from golem_blender.export.glb_geometry import FRAME_AXIS_MAPPING as _AXIS_MAPPING
from golem_blender.export.glb_geometry import measure_file
from golem_blender.ops._contract import op


@dataclass(frozen=True)
class GlbNodeMeasure:
    """One node's geometry: counts, connectivity, and where it sits."""

    name: str
    mesh_name: str
    material_names: tuple[str, ...]
    triangle_count: int
    component_count: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]


@dataclass(frozen=True)
class GlbTop:
    """A standable top surface: how high, how big, and which way its outline runs."""

    height: float
    area: float
    outline: tuple[tuple[float, float], ...]
    node_names: tuple[str, ...]
    above_base: float
    bucket: str


@dataclass(frozen=True)
class GlbProfileSample:
    """The highest surface above one point of a section, or a miss."""

    distance: float
    height: float
    hit: bool


@dataclass(frozen=True)
class GlbMeasurement:
    """Everything one read of a .glb says about it, in one frame and one unit."""

    path: str
    frame: str
    units: str
    axis_mapping: str
    nodes: tuple[GlbNodeMeasure, ...]
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    pivot_offset: tuple[float, float, float]
    base_height: float
    top_height: float
    tops: tuple[GlbTop, ...]
    profile: tuple[GlbProfileSample, ...]
    step_thresholds: tuple[float, ...]


@op(reads_only=True)
def measure_glb(
    glb_path: str,
    frame: Literal["engine", "blender"] = "engine",
    units: Literal["m", "ft"] = "m",
    top_minimum_area_m2: float = 0.01,
    top_normal_tolerance_deg: float = 5.0,
    profile_from: tuple[float, float] | None = None,
    profile_to: tuple[float, float] | None = None,
    profile_step: float = 0.1,
    step_thresholds: tuple[float, ...] = (),
) -> GlbMeasurement:
    """Measure a .glb file read-only, per node, in the engine or Blender frame: bounds, pivot, standable tops, profile.

    Every number is taken from the file the ENGINE loads, which means the node
    transforms are applied: a mesh modelled at the origin but placed 2 m up
    measures 2 m up here, and its pivot offset is that placement. Reading the
    mesh's own coordinates would answer a question nobody asked.

    `frame` says which way is up: `engine` is glTF/Bevy (+X right, +Y up, -Z
    forward) and `blender` is (+X right, +Z up, +Y forward), the same mapping
    `export_yup` inverts. `units` is `m` or `ft` for every length in the answer,
    with the engine's own feet-per-metre (3.2808), so a height compares against
    the engine rather than against a rounded constant.

    `pivot_offset` is where the file's ORIGIN sits relative to the geometry's
    centre: a part modelled in place reports 0, and a part authored around its
    own corner reports the distance a placement has to subtract. `tops` are the
    standable surfaces — upward faces grouped into one surface when they share a
    welded corner and agree in height, at least `top_minimum_area_m2` in area —
    each with its height, area, a convex outline on the ground axes and a
    `bucket` when `step_thresholds` are given (the step it is on, measured above
    the base). `profile` samples the highest surface above a straight section of
    the ground plane, for the silhouette check a render would otherwise be
    needed for.

    `profile_step`, `profile_from`, `profile_to` and `step_thresholds` are in
    `units`, on the frame's ground axes (engine: x, z; blender: x, y); the
    section needs both ends or neither. Nothing is imported, linked or created:
    this reads a path and returns numbers, so it needs no declared plan.
    """
    values = measure_file(
        glb_path,
        frame=frame,
        units=units,
        top_minimum_area_m2=top_minimum_area_m2,
        top_normal_tolerance_deg=top_normal_tolerance_deg,
        profile_from=profile_from,
        profile_to=profile_to,
        profile_step=profile_step,
        step_thresholds=tuple(step_thresholds),
    )
    return GlbMeasurement(
        path=values["path"],
        frame=values["frame"],
        units=values["units"],
        axis_mapping=values["axis_mapping"],
        nodes=tuple(
            GlbNodeMeasure(
                name=node.name,
                mesh_name=node.mesh_name,
                material_names=node.material_names,
                triangle_count=node.triangle_count,
                component_count=node.component_count,
                bounds_min=node.bounds_min,
                bounds_max=node.bounds_max,
            )
            for node in values["nodes"]
        ),
        bounds_min=values["bounds_min"],
        bounds_max=values["bounds_max"],
        pivot_offset=values["pivot_offset"],
        base_height=values["base_height"],
        top_height=values["top_height"],
        tops=tuple(
            GlbTop(
                height=top.height,
                area=top.area,
                outline=top.outline,
                node_names=top.node_names,
                above_base=top.above_base,
                bucket=top.bucket,
            )
            for top in values["tops"]
        ),
        profile=tuple(
            GlbProfileSample(
                distance=sample.distance, height=sample.height, hit=sample.hit
            )
            for sample in values["profile"]
        ),
        step_thresholds=values["step_thresholds"],
    )


# The mapping this op reports is the geometry module's, so a reader of the tool
# description and a reader of the answer cannot disagree about the frame.
AXIS_MAPPING = _AXIS_MAPPING
