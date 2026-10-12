"""Executes a brief's acceptance spec against the live scene.

This is the deterministic gate for FORM, sitting beside the analyzer's
deterministic gate for STRUCTURE. Both run before any render is looked
at, because a visual critique of a scene that already failed a
measurement is wasted tokens and an invitation to argue with a number.

Everything here answers with a measurement and a delta, never a bare
boolean — "feedback as deltas" (project rule). A failure report that
says `width_x 0.284 m, expected 0.300 +/- 0.020, delta -0.016` tells the
agent what to change; `width_x: FAIL` does not.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

from blended.evaluate.briefs import (
    AssetBrief,
    ClearAxisProbe,
    DimensionSpec,
    DistinctMaterialSpec,
    GroundContactProbe,
    NoInterpenetrationSpec,
    RefinementStep,
    SharedCentreSpec,
    SolidityProbe,
    StackedOnSpec,
)

# Parity ray casting. The ray starts at the probe point and marches +Z,
# counting surface crossings; an odd count means the point started
# inside solid material. Each restart is nudged past the hit it just
# found, or the same face is hit forever.
PARITY_RAY_DIRECTION = (0.0, 0.0, 1.0)
PARITY_RESTART_OFFSET_M = 1.0e-6
PARITY_MAXIMUM_CROSSINGS = 128
# How far a probe ray may travel before we call it "out of the object".
# Generous relative to prop scale; a prop that needs more than this is
# not a prop.
PARITY_RAY_LENGTH_M = 100.0

# Bearings are modulo one full turn; the shortest signed turn is at most half.
FULL_TURN_DEG = 360.0
HALF_TURN_DEG = 180.0


@dataclass(frozen=True)
class DimensionMeasurement:
    spec: DimensionSpec
    measured_m: float

    @property
    def delta_m(self) -> float:
        return self.measured_m - self.spec.expected_m

    @property
    def ok(self) -> bool:
        return abs(self.delta_m) <= self.spec.tolerance_m

    def describe(self) -> str:
        return (
            f"{self.spec.name}: {self.measured_m:.4f} m, expected "
            f"{self.spec.expected_m:.4f} +/- {self.spec.tolerance_m:.4f}, "
            f"delta {self.delta_m:+.4f} m"
        )


@dataclass(frozen=True)
class ProbeMeasurement:
    probe: SolidityProbe
    crossing_count: int

    @property
    def measured_inside(self) -> bool:
        return self.crossing_count % 2 == 1

    @property
    def ok(self) -> bool:
        return self.measured_inside == self.probe.expect_inside

    def describe(self) -> str:
        expected = "solid" if self.probe.expect_inside else "empty"
        measured = "solid" if self.measured_inside else "empty"
        point = ", ".join(f"{value:.3f}" for value in self.probe.point_m)
        line = (
            f"{self.probe.name}: at ({point}) expected {expected}, "
            f"measured {measured} ({self.crossing_count} surface crossings)"
        )
        return line if self.ok else f"{line} -> {self.probe.why}"


@dataclass(frozen=True)
class ClearAxisMeasurement:
    probe: ClearAxisProbe
    blocked_at_m: float | None  # None = clear line of sight

    @property
    def ok(self) -> bool:
        return self.blocked_at_m is None

    def describe(self) -> str:
        point = ", ".join(f"{value:.3f}" for value in self.probe.point_m)
        if self.ok:
            return (
                f"{self.probe.name}: {self.probe.axis}-axis through "
                f"({point}) is clear end to end"
            )
        return (
            f"{self.probe.name}: {self.probe.axis}-axis through ({point}) is "
            f"BLOCKED at {self.probe.axis}={self.blocked_at_m:.4f} m "
            f"-> {self.probe.why}"
        )


def signed_angle_difference_deg(from_deg: float, to_deg: float) -> float:
    """Smallest signed turn from `from_deg` to `to_deg`, in (-180, 180].

    Bearings are modulo 360, so a foot that moves from 0.2 to 359.9 has
    turned -0.3 degrees, not -359.7.
    """
    raw_deg = (to_deg - from_deg) % FULL_TURN_DEG
    return raw_deg - FULL_TURN_DEG if raw_deg > HALF_TURN_DEG else raw_deg


@dataclass(frozen=True)
class GroundContactMeasurement:
    """How much flat sole this foot actually puts on the floor."""

    probe: GroundContactProbe
    contact_area_m2: float
    # Faces near the foot that were rejected for NOT lying in the plane,
    # and the worst z-span among them. Zero area with rejected faces
    # means "the leg is there but its sole is angled"; zero area with
    # none means "there is no leg here at all". Different repairs.
    rejected_face_count: int
    worst_rejected_span_m: float
    # Area-weighted centroid of the flat sole: where the foot ACTUALLY
    # landed, as opposed to where the probe went looking for it.
    centroid_xy_m: tuple[float, float] = (0.0, 0.0)

    @property
    def measured_radius_m(self) -> float:
        return math.hypot(*self.centroid_xy_m)

    @property
    def measured_angle_deg(self) -> float:
        y, x = self.centroid_xy_m[1], self.centroid_xy_m[0]
        return math.degrees(math.atan2(y, x)) % FULL_TURN_DEG

    @property
    def angle_error_deg(self) -> float:
        """Smallest signed turn from the expected bearing to the measured."""
        return signed_angle_difference_deg(
            self.probe.expected_angle_deg, self.measured_angle_deg
        )

    @property
    def has_contact(self) -> bool:
        return self.contact_area_m2 >= self.probe.minimum_area_m2

    @property
    def radius_ok(self) -> bool:
        return (
            abs(self.measured_radius_m - self.probe.expected_radius_m)
            <= self.probe.radius_tolerance_m
        )

    @property
    def angle_ok(self) -> bool:
        return abs(self.angle_error_deg) <= self.probe.angle_tolerance_deg

    @property
    def ok(self) -> bool:
        # Placement is only meaningful once there is a sole to locate.
        return self.has_contact and self.radius_ok and self.angle_ok

    def describe(self) -> str:
        centre = ", ".join(f"{value:.3f}" for value in self.probe.centre_xy_m)
        line = (
            f"{self.probe.name}: at ({centre}) flat sole area "
            f"{self.contact_area_m2:.6f} m2, required "
            f"{self.probe.minimum_area_m2:.6f} m2"
        )
        if self.has_contact:
            line += (
                f"; sole centre r={self.measured_radius_m:.4f} m (expected "
                f"{self.probe.expected_radius_m:.4f} +/- "
                f"{self.probe.radius_tolerance_m:.4f}), bearing "
                f"{self.measured_angle_deg:.1f} deg (expected "
                f"{self.probe.expected_angle_deg:.1f} +/- "
                f"{self.probe.angle_tolerance_deg:.1f}, off by "
                f"{self.angle_error_deg:+.1f})"
            )
        if self.ok:
            return line
        if self.has_contact and not self.radius_ok:
            line += " — this foot is off the specified circle"
        if self.has_contact and not self.angle_ok:
            line += " — the legs are not evenly spaced"
        if self.rejected_face_count:
            line += (
                f" — {self.rejected_face_count} face(s) near this foot are "
                f"NOT level: worst spans {self.worst_rejected_span_m:.4f} m "
                f"in z against a {self.probe.planarity_tolerance_m:.4f} m "
                f"tolerance"
            )
        else:
            line += " — no face at all lies on z=0 near this foot"
        return f"{line} -> {self.probe.why}"


@dataclass(frozen=True)
class PartReport:
    """Measured facts about ONE part of a brief's build.

    Mirrors what AcceptanceReport used to hold per object; an
    AcceptanceReport is a tuple of these plus the relations verdict.
    """

    name: str
    object_found: bool
    # An object can exist in bpy.data and still have no depsgraph
    # instance, because construction and linking are separate steps in
    # the ops vocabulary. Unlinked, it has no evaluated mesh: probing it
    # raises instead of measuring. That is a real, common build failure
    # (the user sees an empty viewport), so it is reported as one.
    linked_into_scene: bool = False
    dimensions: tuple[DimensionMeasurement, ...] = field(default_factory=tuple)
    probes: tuple[ProbeMeasurement, ...] = field(default_factory=tuple)
    clear_axes: tuple[ClearAxisMeasurement, ...] = field(default_factory=tuple)
    ground_contacts: tuple[GroundContactMeasurement, ...] = field(default_factory=tuple)
    base_z_m: float = 0.0
    transform_is_finite: bool = True
    # Two numbers, not one. A boolean modifier leaves an EMPTY slot
    # behind (measured: len(mesh.materials) == 1, contents [None]), so a
    # slot count answers "did a modifier run", not "is this textured".
    material_slot_count: int = 0
    assigned_material_count: int = 0


@dataclass(frozen=True)
class AcceptanceReport:
    """Measured facts about whether the built scene matches the brief.

    One `PartReport` per brief part, plus any relation failures. The
    per-object measurements (`dimensions`, `probes`, `clear_axes`,
    `ground_contacts`, `base_z_m`, `material_*`) read as PROPERTIES
    concatenating across the parts, so every existing caller keeps
    working against a brief that names one part.
    """

    brief_name: str
    part_reports: tuple[PartReport, ...]
    relation_failures: tuple[str, ...] = field(default_factory=tuple)
    stray_object_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def object_name(self) -> str:
        """The part names joined; single-part briefs read as before."""
        return ", ".join(part.name for part in self.part_reports)

    @property
    def object_found(self) -> bool:
        return all(part.object_found for part in self.part_reports)

    @property
    def linked_into_scene(self) -> bool:
        return all(part.linked_into_scene for part in self.part_reports)

    @property
    def dimensions(self) -> tuple[DimensionMeasurement, ...]:
        return tuple(
            measurement for part in self.part_reports for measurement in part.dimensions
        )

    @property
    def probes(self) -> tuple[ProbeMeasurement, ...]:
        return tuple(
            measurement for part in self.part_reports for measurement in part.probes
        )

    @property
    def clear_axes(self) -> tuple[ClearAxisMeasurement, ...]:
        return tuple(
            measurement for part in self.part_reports for measurement in part.clear_axes
        )

    @property
    def ground_contacts(self) -> tuple[GroundContactMeasurement, ...]:
        return tuple(
            measurement
            for part in self.part_reports
            for measurement in part.ground_contacts
        )

    @property
    def base_z_m(self) -> float:
        return min(part.base_z_m for part in self.part_reports)

    @property
    def transform_is_finite(self) -> bool:
        return all(part.transform_is_finite for part in self.part_reports)

    @property
    def material_slot_count(self) -> int:
        return sum(part.material_slot_count for part in self.part_reports)

    @property
    def assigned_material_count(self) -> int:
        return sum(part.assigned_material_count for part in self.part_reports)

    def failures(self, brief: AssetBrief) -> list[str]:
        """Human-readable failures (empty list = the form gate passed).

        Per-part failures are prefixed with the part name ONLY when the
        brief names more than one part, so single-part messages stay
        byte-identical to what they were before parts existed. Relation
        failures follow the parts.
        """
        prefix = lambda part: f"{part.name}: " if len(self.part_reports) > 1 else ""
        found: list[str] = []
        for part in self.part_reports:
            if not part.object_found:
                found.append(
                    f"{prefix(part)}no object named {part.name!r} in the "
                    f"scene (the brief names it explicitly)"
                )
                continue
            if not part.linked_into_scene:
                found.append(
                    f"{prefix(part)}object {part.name!r} exists but is not "
                    f"linked into the scene collection, so it has no "
                    f"evaluated mesh and does not appear in the viewport "
                    f"(call link_into_scene({part.name!r}) after "
                    f"constructing it)"
                )
                continue
            if not part.transform_is_finite:
                found.append(
                    f"{prefix(part)}object transform contains non-finite values"
                )
            found.extend(
                prefix(part) + measurement.describe()
                for measurement in part.dimensions
                if not measurement.ok
            )
            spec = _part_spec(brief, part.name)
            if spec.require_base_at_ground and abs(part.base_z_m) > (
                brief.grounding_tolerance_m
            ):
                found.append(
                    f"{prefix(part)}base sits at z={part.base_z_m:+.4f} m, "
                    f"expected 0 +/- {brief.grounding_tolerance_m:.4f} "
                    f"(not on the ground)"
                )
            found.extend(
                prefix(part) + measurement.describe()
                for measurement in part.probes
                if not measurement.ok
            )
            found.extend(
                prefix(part) + measurement.describe()
                for measurement in part.clear_axes
                if not measurement.ok
            )
            found.extend(
                prefix(part) + measurement.describe()
                for measurement in part.ground_contacts
                if not measurement.ok
            )
            if brief.require_material and part.assigned_material_count == 0:
                found.append(
                    f"{prefix(part)}no material assigned: "
                    f"{part.material_slot_count} slot(s), "
                    f"{part.assigned_material_count} filled (an empty slot "
                    f"left by a boolean modifier is not a material)"
                )
        found.extend(self.relation_failures)
        if self.stray_object_names:
            found.append(
                f"{len(self.stray_object_names)} stray mesh object(s) left in "
                f"the scene: {', '.join(self.stray_object_names)} "
                f"(cutters and offcuts must be removed)"
            )
        return found

    def passes(self, brief: AssetBrief) -> bool:
        return not self.failures(brief)

    def summary(self, brief: AssetBrief) -> str:
        failures = self.failures(brief)
        head = f"FORM {'PASS' if not failures else 'FAIL'}: {self.brief_name}"
        if not self.object_found or not self.linked_into_scene:
            return head + "".join(f"\n  - {failure}" for failure in failures)
        lines = [head]
        for part in self.part_reports:
            lines.append(f"  [{part.name}]")
            lines.extend(
                f"    {measurement.describe()}" for measurement in part.dimensions
            )
            lines.append(f"    base_z: {part.base_z_m:+.4f} m")
            lines.extend(f"    {measurement.describe()}" for measurement in part.probes)
            lines.extend(
                f"    {measurement.describe()}" for measurement in part.clear_axes
            )
            lines.extend(
                f"    {measurement.describe()}" for measurement in part.ground_contacts
            )
            lines.append(
                f"    materials: {part.assigned_material_count} assigned "
                f"in {part.material_slot_count} slot(s)"
            )
        if brief.relations:
            lines.append("  [relations]")
            if self.relation_failures:
                lines.extend(f"    {failure}" for failure in self.relation_failures)
            else:
                for relation in brief.relations:
                    lines.append(f"    {relation.name}: OK")
        if self.stray_object_names:
            lines.append(f"  stray objects: {', '.join(self.stray_object_names)}")
        return "\n".join(lines)


def _count_surface_crossings(evaluated_object, world_point) -> int:
    """Count +Z surface crossings above a world point. Odd = inside."""
    from mathutils import Vector

    to_local = evaluated_object.matrix_world.inverted()
    local_origin = to_local @ Vector(world_point)
    local_direction = (to_local.to_3x3() @ Vector(PARITY_RAY_DIRECTION)).normalized()

    cursor = local_origin.copy()
    for crossing_count in range(PARITY_MAXIMUM_CROSSINGS):
        hit, location, _normal, _index = evaluated_object.ray_cast(
            cursor, local_direction, distance=PARITY_RAY_LENGTH_M
        )
        if not hit:
            return crossing_count
        cursor = location + local_direction * PARITY_RESTART_OFFSET_M
    raise RuntimeError(
        f"Parity ray from {tuple(world_point)} crossed "
        f"{PARITY_MAXIMUM_CROSSINGS} surfaces without leaving the mesh. "
        f"That is a degenerate or self-overlapping surface, not a probe "
        f"failure — fix the geometry before trusting any probe."
    )


def _find_axis_blockage(evaluated_object, probe: ClearAxisProbe) -> float | None:
    """First surface hit along the whole axis, or None if it is clear."""
    from mathutils import Vector

    axis_index = {"x": 0, "y": 1, "z": 2}[probe.axis]
    direction_world = Vector(
        tuple(1.0 if index == axis_index else 0.0 for index in range(3))
    )
    # Start beyond the far side of the object and sweep the full length,
    # so the answer covers BOTH half-spaces around the point.
    start_world = Vector(probe.point_m) - direction_world * (PARITY_RAY_LENGTH_M / 2.0)

    # The sweep is defined in WORLD metres, so both ends are mapped into
    # local space and the ray distance is the local length between them.
    # A fixed local distance covers PARITY_RAY_LENGTH_M * scale metres,
    # which for an object scaled below 0.5 stops short of the object and
    # reports a solid axis as clear (measured: unit cube at scale 0.1).
    end_world = start_world + direction_world * PARITY_RAY_LENGTH_M
    to_local = evaluated_object.matrix_world.inverted()
    local_origin = to_local @ start_world
    local_sweep = (to_local @ end_world) - local_origin
    local_direction = local_sweep.normalized()

    hit, location, _normal, _index = evaluated_object.ray_cast(
        local_origin, local_direction, distance=local_sweep.length
    )
    if not hit:
        return None
    world_hit = evaluated_object.matrix_world @ location
    return world_hit[axis_index]


def _doubled_area_vector(world_vertices):
    """Twice the area vector of a planar polygon: |v| = 2 * area, and it
    points along the outward normal.

    One computation answers both questions the sole probe asks — how big
    is this face, and which way does it face. Fan triangulation would
    overestimate a concave boolean offcut; the cross-product sum is
    exact for any simple planar polygon.
    """
    from mathutils import Vector

    total = Vector((0.0, 0.0, 0.0))
    count = len(world_vertices)
    for index in range(count):
        total = total + world_vertices[index].cross(world_vertices[(index + 1) % count])
    return total


def _measure_sole_contact(
    evaluated_object, probe: GroundContactProbe
) -> GroundContactMeasurement:
    """Total flat-on-z=0 face area near one foot.

    Rays cannot answer this. A downward ray from above hits the seat,
    an upward ray from below hits any single point of an angled sole
    and reports z=0 just as a flat one would. Contact is an area, so
    the faces are measured directly.
    """
    mesh = evaluated_object.to_mesh()
    try:
        to_world = evaluated_object.matrix_world
        centre_x, centre_y = probe.centre_xy_m
        contact_area_m2 = 0.0
        rejected_face_count = 0
        worst_rejected_span_m = 0.0
        weighted_x = 0.0
        weighted_y = 0.0
        for polygon in mesh.polygons:
            world_vertices = [
                to_world @ mesh.vertices[index].co for index in polygon.vertices
            ]
            centroid_x = sum(vertex.x for vertex in world_vertices) / len(
                world_vertices
            )
            centroid_y = sum(vertex.y for vertex in world_vertices) / len(
                world_vertices
            )
            if (
                math.hypot(centroid_x - centre_x, centroid_y - centre_y)
                > probe.search_radius_m
            ):
                continue
            heights = [vertex.z for vertex in world_vertices]
            area_vector = _doubled_area_vector(world_vertices)
            # A candidate sole reaches the floor and faces down. The
            # leg's shaft reaches the floor too, but its normal is
            # horizontal, so it is not a near-miss sole — reporting it
            # as one would put the leg's whole LENGTH in the tilt
            # report instead of the cap's tilt.
            reaches_the_floor = min(heights) <= probe.planarity_tolerance_m
            faces_down = area_vector.z < 0.0
            if not (reaches_the_floor and faces_down):
                continue
            # One condition covers both remaining questions: every vertex
            # within tolerance of z=0 means the face is level AND lying
            # on the floor rather than tilted up off it.
            if max(abs(height) for height in heights) <= probe.planarity_tolerance_m:
                face_area_m2 = area_vector.length / 2.0
                contact_area_m2 += face_area_m2
                weighted_x += centroid_x * face_area_m2
                weighted_y += centroid_y * face_area_m2
                continue
            rejected_face_count += 1
            worst_rejected_span_m = max(
                worst_rejected_span_m, max(heights) - min(heights)
            )
        centroid_xy_m = (
            (weighted_x / contact_area_m2, weighted_y / contact_area_m2)
            if contact_area_m2 > 0.0
            else (0.0, 0.0)
        )
        return GroundContactMeasurement(
            probe=probe,
            contact_area_m2=contact_area_m2,
            rejected_face_count=rejected_face_count,
            worst_rejected_span_m=worst_rejected_span_m,
            centroid_xy_m=centroid_xy_m,
        )
    finally:
        evaluated_object.to_mesh_clear()


def evaluate_brief(brief: AssetBrief) -> AcceptanceReport:
    """Measure the live scene against one brief's acceptance spec.

    One PartReport per part, then the relations verdict, then the
    stray-object check against the brief's part names.
    """
    import bpy
    from mathutils import Vector

    bpy.context.view_layer.update()
    part_reports = tuple(
        _measure_part(brief, part, bpy, Vector) for part in brief.parts
    )
    relation_failures = _measure_relations(brief, bpy, Vector)
    stray_object_names = tuple(
        scene_object.name
        for scene_object in bpy.context.scene.objects
        if scene_object.type == "MESH" and scene_object.name not in brief.part_names
    )
    return AcceptanceReport(
        brief_name=brief.name,
        part_reports=part_reports,
        relation_failures=relation_failures,
        stray_object_names=stray_object_names,
    )


def _part_spec(brief: AssetBrief, part_name: str):
    """The PartSpec for one named part. There is no nearest match."""
    for part in brief.parts:
        if part.name == part_name:
            return part
    raise KeyError(f"no part named {part_name!r} in brief {brief.name!r}")


def _measure_part(brief: AssetBrief, part, bpy, Vector) -> PartReport:
    """Measure one part's object against its own acceptance spec."""
    blender_object = bpy.data.objects.get(part.name)
    if blender_object is None or blender_object.type != "MESH":
        return PartReport(name=part.name, object_found=False)

    linked_into_scene = blender_object.name in bpy.context.scene.objects
    if not linked_into_scene:
        return PartReport(name=part.name, object_found=True, linked_into_scene=False)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated_object = blender_object.evaluated_get(depsgraph)

    matrix_values = [value for row in blender_object.matrix_world for value in row]
    transform_is_finite = all(math.isfinite(value) for value in matrix_values)

    corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    extents = {
        axis: (
            max(corner[index] for corner in corners)
            - min(corner[index] for corner in corners)
        )
        for index, axis in enumerate(("x", "y", "z"))
    }
    base_z_m = min(corner.z for corner in corners)

    return PartReport(
        name=part.name,
        object_found=True,
        linked_into_scene=True,
        dimensions=tuple(
            DimensionMeasurement(spec=spec, measured_m=extents[spec.axis])
            for spec in part.dimensions
        ),
        probes=tuple(
            ProbeMeasurement(
                probe=probe,
                crossing_count=_count_surface_crossings(
                    evaluated_object, probe.point_m
                ),
            )
            for probe in part.probes
        ),
        clear_axes=tuple(
            ClearAxisMeasurement(
                probe=probe,
                blocked_at_m=_find_axis_blockage(evaluated_object, probe),
            )
            for probe in part.clear_axes
        ),
        ground_contacts=tuple(
            _measure_sole_contact(evaluated_object, probe)
            for probe in part.ground_contacts
        ),
        base_z_m=base_z_m,
        transform_is_finite=transform_is_finite,
        material_slot_count=len(blender_object.data.materials),
        assigned_material_count=sum(
            1 for material in blender_object.data.materials if material is not None
        ),
    )


def _measure_relations(brief: AssetBrief, bpy, Vector) -> tuple[str, ...]:
    """Score every relation between parts. Failures name the relation.

    StackedOn: the upper part's bbox minimum z must sit within
    tolerance of the lower part's bbox maximum z — resting ON the rim,
    not floating and not sunk into it. SharedCentre: the two parts'
    bbox centres must agree on each named axis within tolerance, so a
    lid cannot hang off one side of the crate it sits on.
    NoInterpenetration: measured on the MESH SURFACE, not bboxes and
    not nearest vertices (see pair_checks.py for the measured
    nearest-vertex lie). DistinctMaterial: the two parts' base colours
    must differ, because a lid flush on the rim with the body's exact
    footprint is invisible otherwise.
    """

    def _base_colour(part_name: str, bpy):
        """The part's first material's Principled base colour, or None.

        None means "nothing to compare" — no object, no material slot,
        no Principled node — and the material gate is what reports
        that. Reading `diffuse_color` as a fallback is deliberately NOT
        done: it is the viewport display colour, which the renderer
        ignores, so a fallback would pass a part the render shows grey.
        """
        blender_object = bpy.data.objects.get(part_name)
        if blender_object is None or not blender_object.material_slots:
            return None
        material = blender_object.material_slots[0].material
        if material is None or material.node_tree is None:
            return None
        from blended.ops.materials import PRINCIPLED_NODE_NAME

        principled = material.node_tree.nodes.get(PRINCIPLED_NODE_NAME)
        if principled is None:
            return None
        return tuple(principled.inputs["Base Color"].default_value[:3])

    def _bbox(part_name: str):
        blender_object = bpy.data.objects.get(part_name)
        if blender_object is None or blender_object.type != "MESH":
            return None
        corners = [
            blender_object.matrix_world @ Vector(corner)
            for corner in blender_object.bound_box
        ]
        minima = tuple(min(corner[i] for corner in corners) for i in range(3))
        maxima = tuple(max(corner[i] for corner in corners) for i in range(3))
        return minima, maxima

    found: list[str] = []
    for relation in brief.relations:
        if isinstance(relation, NoInterpenetrationSpec):
            first_object = bpy.data.objects.get(relation.first_part)
            second_object = bpy.data.objects.get(relation.second_part)
            if (
                first_object is None
                or second_object is None
                or first_object.type != "MESH"
                or second_object.type != "MESH"
            ):
                continue  # a missing part is the part report's failure
            from blended.analyze.pair_checks import analyze_pair

            pair_report = analyze_pair(first_object, second_object)
            failures: list[str] = []
            if (
                pair_report.intersecting_face_pair_count
                > relation.maximum_intersecting_face_pairs
            ):
                failures.append(
                    f"{pair_report.intersecting_face_pair_count} intersecting "
                    f"face pairs"
                )
            if (
                relation.minimum_separation_m is not None
                and pair_report.minimum_separation_m < relation.minimum_separation_m
            ):
                failures.append(
                    f"minimum separation "
                    f"{pair_report.minimum_separation_m:.6f} m, expected at "
                    f"least {relation.minimum_separation_m:.6f} m"
                )
            if (
                relation.maximum_aabb_penetration_depth_m is not None
                and pair_report.aabb_penetration_depth_m
                > relation.maximum_aabb_penetration_depth_m
            ):
                failures.append(
                    f"AABB penetration depth "
                    f"{pair_report.aabb_penetration_depth_m:.6f} m, allowed "
                    f"at most "
                    f"{relation.maximum_aabb_penetration_depth_m:.6f} m"
                )
            if failures:
                found.append(
                    f"{relation.name}: {relation.first_part} against "
                    f"{relation.second_part}: {'; '.join(failures)} "
                    f"-> {relation.why}"
                )
            continue
        if isinstance(relation, StackedOnSpec):
            lower = _bbox(relation.lower_part)
            upper = _bbox(relation.upper_part)
            if lower is None or upper is None:
                continue  # a missing part is the part report's failure
            gap_m = upper[0][2] - lower[1][2]
            if abs(gap_m) > relation.tolerance_m:
                found.append(
                    f"{relation.name}: {relation.upper_part} bottom sits "
                    f"{gap_m:+.4f} m from {relation.lower_part} top, expected "
                    f"0 +/- {relation.tolerance_m:.4f} -> {relation.why}"
                )
            continue
        if isinstance(relation, SharedCentreSpec):
            first = _bbox(relation.part_a)
            second = _bbox(relation.part_b)
            if first is None or second is None:
                continue
            axis_index = {"x": 0, "y": 1, "z": 2}
            for axis in relation.axes:
                index = axis_index[axis]
                first_centre = (first[0][index] + first[1][index]) / 2.0
                second_centre = (second[0][index] + second[1][index]) / 2.0
                offset_m = first_centre - second_centre
                if abs(offset_m) > relation.tolerance_m:
                    found.append(
                        f"{relation.name}: {relation.part_a} centre is "
                        f"{offset_m:+.4f} m off {relation.part_b} on {axis}, "
                        f"expected within {relation.tolerance_m:.4f} "
                        f"-> {relation.why}"
                    )
            continue
        if isinstance(relation, DistinctMaterialSpec):
            first_colour = _base_colour(relation.part_a, bpy)
            second_colour = _base_colour(relation.part_b, bpy)
            if first_colour is None or second_colour is None:
                # No material is the material gate's failure to report,
                # not this relation's — it would say the same thing
                # twice and disagree about which part is at fault.
                continue
            distance = math.sqrt(
                sum(
                    (first - second) ** 2
                    for first, second in zip(first_colour, second_colour)
                )
            )
            if distance < relation.minimum_colour_distance_rgb:
                found.append(
                    f"{relation.name}: {relation.part_a} base colour "
                    f"{tuple(round(value, 3) for value in first_colour)} is "
                    f"{distance:.4f} from {relation.part_b}'s "
                    f"{tuple(round(value, 3) for value in second_colour)}, "
                    f"expected at least "
                    f"{relation.minimum_colour_distance_rgb:.4f} "
                    f"-> {relation.why}"
                )
            continue
        raise TypeError(
            f"unknown relation type {type(relation).__name__} on brief {brief.name!r}"
        )
    return tuple(found)


# What a measurement may drift by and still count as "untouched" by a
# localized edit. Tight on purpose: this is not a build tolerance, it is
# the claim that the edit did not disturb the value at all, and the
# numbers being compared came out of the same measurement code minutes
# apart. A rebuild lands well outside it.
PRESERVED_DIMENSION_TOLERANCE_M = 0.001
PRESERVED_SOLE_BEARING_TOLERANCE_DEG = 1.0


def refine_brief(brief: AssetBrief, step: RefinementStep) -> AssetBrief:
    """The brief as it stands AFTER the instruction.

    The changed dimensions and their derived probes replace their
    originals inside each PART; everything else — clear axes, ground
    contacts, relations, budget — carries over untouched, because the
    user changed one thing. A refinement names a MEASUREMENT, not a
    part, so the replacement is by spec name across all parts.

    Measure the refined asset against THIS, not against the original.
    A DimensionMeasurement carries the spec it was measured with, so
    judging an old measurement against a new brief silently changes
    nothing: the numbers still answer the question they were asked.
    """
    replacements = {spec.name: spec for spec in step.changed}
    probe_replacements = {probe.name: probe for probe in step.changed_probes}
    return dataclasses.replace(
        brief,
        parts=tuple(
            dataclasses.replace(
                part,
                dimensions=tuple(
                    replacements.get(spec.name, spec) for spec in part.dimensions
                ),
                probes=tuple(
                    probe_replacements.get(probe.name, probe) for probe in part.probes
                ),
            )
            for part in brief.parts
        ),
    )


@dataclasses.dataclass(frozen=True)
class RefinementOutcome:
    """Did the follow-up edit change what it should and nothing else?"""

    step: RefinementStep
    before: AcceptanceReport
    after: AcceptanceReport

    def refined_brief(self, brief: AssetBrief) -> AssetBrief:
        return refine_brief(brief, self.step)

    def _measured(self, report: AcceptanceReport, name: str) -> float | None:
        """The measured value, or None when the report has no such
        dimension — the part was not found. A missing part is a finding
        the summary must print, never an exception that loses the
        record (measured 2026-09-10, iteration 82: the driver died in
        this lookup after a refinement turn left the stool named Seat)."""
        for measurement in report.dimensions:
            if measurement.spec.name == name:
                return measurement.measured_m
        return None

    def preservation_failures(self, brief: AssetBrief) -> list[str]:
        """Everything the instruction did NOT name must not have moved.

        Compared against what it measured BEFORE, not against the spec.
        A full rebuild can satisfy the spec again while quietly landing
        on different numbers — that is exactly the failure this catches.
        """
        changed_names = {spec.name for spec in self.step.changed}
        found: list[str] = []
        for measurement in self.after.dimensions:
            if measurement.spec.name in changed_names:
                continue
            was = self._measured(self.before, measurement.spec.name)
            if was is None:
                found.append(
                    f"{measurement.spec.name} has no measurement before the "
                    f"instruction, so its preservation cannot be judged"
                )
                continue
            drift_m = measurement.measured_m - was
            if abs(drift_m) > PRESERVED_DIMENSION_TOLERANCE_M:
                found.append(
                    f"{measurement.spec.name} was not part of the "
                    f"instruction but moved {drift_m:+.4f} m "
                    f"({was:.4f} -> {measurement.measured_m:.4f})"
                )
        before_by_name = {m.probe.name: m for m in self.before.ground_contacts}
        for after_contact in self.after.ground_contacts:
            before_contact = before_by_name.get(after_contact.probe.name)
            if before_contact is None:
                continue
            radius_drift_m = (
                after_contact.measured_radius_m - before_contact.measured_radius_m
            )
            if abs(radius_drift_m) > PRESERVED_DIMENSION_TOLERANCE_M:
                found.append(
                    f"{after_contact.probe.name} moved {radius_drift_m:+.4f} m "
                    f"off its circle ({before_contact.measured_radius_m:.4f} -> "
                    f"{after_contact.measured_radius_m:.4f})"
                )
            bearing_drift_deg = signed_angle_difference_deg(
                before_contact.measured_angle_deg, after_contact.measured_angle_deg
            )
            if abs(bearing_drift_deg) > PRESERVED_SOLE_BEARING_TOLERANCE_DEG:
                found.append(
                    f"{after_contact.probe.name} swung "
                    f"{bearing_drift_deg:+.1f} deg "
                    f"({before_contact.measured_angle_deg:.1f} -> "
                    f"{after_contact.measured_angle_deg:.1f})"
                )
        return found

    def failures(self, brief: AssetBrief) -> list[str]:
        """The edit must land AND leave the rest alone."""
        return self.after.failures(self.refined_brief(brief)) + [
            f"{failure} -> {self.step.why}"
            for failure in self.preservation_failures(brief)
        ]

    def passes(self, brief: AssetBrief) -> bool:
        return not self.failures(brief)

    def summary(self, brief: AssetBrief) -> str:
        failures = self.failures(brief)
        head = f"REFINEMENT {'PASS' if not failures else 'FAIL'}: {self.step.name}"
        lines = [head]
        for spec in self.step.changed:
            was = self._measured(self.before, spec.name)
            now = self._measured(self.after, spec.name)
            was_text = f"{was:.4f}" if was is not None else "missing"
            now_text = f"{now:.4f}" if now is not None else "missing (part not found)"
            lines.append(
                f"  {spec.name}: {was_text} -> {now_text} m, asked for "
                f"{spec.expected_m:.4f} +/- {spec.tolerance_m:.4f}"
            )
        preserved = self.preservation_failures(brief)
        lines.append(
            f"  preserved: {len(self.after.dimensions) - len(self.step.changed)} "
            f"dimension(s) + {len(self.after.ground_contacts)} foot "
            f"placement(s), {len(preserved)} disturbed"
        )
        lines.extend(f"  {failure}" for failure in preserved)
        # The refined brief's own failures belong here too. Printing only
        # the preservation half would report REFINEMENT FAIL beside a list
        # of everything that went right.
        lines.extend(
            f"  {failure}" for failure in self.after.failures(self.refined_brief(brief))
        )
        return "\n".join(lines)
