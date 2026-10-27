"""Does the garment stay clear of the body it is worn on, in every frame of every clip?

Why this op exists: the seven gaps a dressing agent reported each cost it a
round trip, and this was the first. `clip_self_intersection_report` answers
"does the BODY pass through itself"; nothing answered "does the garment pass
through the body", which is the defect a viewer sees — a knee through a
skirt, a hand through a tunic — and which is invisible to every mesh-level
check, because both meshes are flawless on their own.

The measurement is a signed clearance in metres, both directions:

  * `garment_inside_body`: a garment vertex to the nearest point on the body,
    signed by the body face's normal. Negative means it is through.
  * `body_through_garment`: a BODY vertex that the garment covers at rest, to
    the nearest point on the garment, signed the other way round, so negative
    there also means the body has come through.

The second kind is why coverage is decided AT REST: a tunic's arm is outside
the sleeve at rest and inside it when the arm swings, and counting that as
penetration would fail every garment with sleeves.

The garment's own facing is checked too, and it is the one place a garment
FAILS on winding (`audit_winding` reports facing for everything, but a room's
walls legitimately face inward). A garment inside out is not drawn in the
engine at all — back-face culling deletes it — so a clearance pass on it
would certify a garment nobody can see.

The clearances are measured against the armature's own evaluated deformation,
so "the knee came through the skirt" is a fact about the frame and the
weights, not about the shape the garment was modelled in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from golem_blender.ops._contract import op
from golem_blender.ops.rigging import ARMATURE_MODIFIER_TYPE
from golem_blender.ops.weight_transfer import WeightTransferReport

# No penetration in either direction. A clearance of exactly 0.0 is touching,
# which is what a garment does along its hem; requiring a positive standoff
# would fail every correctly-fitted garment.
DEFAULT_MINIMUM_CLEARANCE_M = 0.0

# How far from the garment a body vertex may be at rest and still count as
# UNDER it. Measured 2026-10-27 on the tube humanoid with a 1.05-1.30 m chest
# ring of radius 0.18 m: the covered body vertices sit 0.04-0.09 m from the
# ring's surface, and the arm bones' tube centres are 0.20-0.30 m from it.
# 0.15 m sits between the two, so a tunic's arm is never counted as covered.
COVERAGE_REACH_M = 0.15

# A nearest point within this barycentric distance of a garment's boundary
# edge is ON that edge, not on its face: the clearance there is measured to a
# rim and says nothing about whether the body is under it.
BOUNDARY_BARYCENTRIC_EPSILON = 1.0e-3

# A garment this much inside out is not wearable. Measured 2026-10-27: a
# correctly wound chest ring reads 0.000 inward (measured by
# `away_from_body`, an open ring) and the same ring with its faces reversed
# reads 1.000, so nothing lands near this threshold by rounding.
MAXIMUM_GARMENT_INWARD_AREA_FRACTION = 0.02

MAXIMUM_LISTED_FAILURES = 16

# The two clearance kinds, named once so the report and its failure text
# cannot disagree about which is which.
KIND_GARMENT_INSIDE_BODY = "garment_inside_body"
KIND_BODY_THROUGH_GARMENT = "body_through_garment"

# The facing readings, named likewise.
METHOD_WINDING_NUMBER = "winding_number"
METHOD_AWAY_FROM_BODY = "away_from_body"


@dataclass(frozen=True)
class ClipClearance:
    """One clip's worst moment: how far the garment and the body came apart, and where."""

    action_name: str  # "" for the rest pose
    frames_measured: int
    failing_frame_count: int
    worst_frame: int
    worst_clearance_m: float
    # Where that happened, in world metres — the place an artist looks.
    worst_point_m: tuple[float, float, float]
    worst_kind: str
    # The group that moves the offending vertex: the garment's for a garment
    # vertex inside the body, the body's for a body vertex through the
    # garment. The name a weights or a pose fix starts from.
    worst_group_name: str
    penetrating_vertex_count: int
    passed: bool


@dataclass(frozen=True)
class ClearanceReport:
    """Whether a garment stays clear of its body at rest and across every named clip."""

    body_object_name: str
    garment_object_name: str
    armature_name: str
    minimum_clearance_m: float
    # Body vertices the garment covers AT REST. 0 means the garment covers
    # nothing — a belt beside the body rather than on it — and the second
    # clearance kind then measures nothing at all.
    covered_body_vertex_count: int
    # Which measurement decided most of the number below: `"winding_number"`
    # (the garment's own winding, which decides open tubes as well as closed
    # shells) or `"away_from_body"` (a flat panel the winding cannot decide,
    # judged by whether it faces the nearest body surface).
    garment_winding_method: str
    garment_inward_area_fraction: float
    # The rest row first, then one row per named clip, in the order given.
    clips: tuple[ClipClearance, ...]
    passed: bool
    failures: tuple[str, ...]


@op(reads_only=True)
def clearance_report(
    body_object_name: str,
    garment_object_name: str,
    action_names: tuple[str, ...] = (),
    minimum_clearance_m: float = DEFAULT_MINIMUM_CLEARANCE_M,
    frame_step: int = 1,
) -> ClearanceReport:
    """Measure garment-to-body clearance over the rest pose and every named clip.

    Both objects must be bound to the SAME armature by an enabled Armature
    modifier: an unbound garment does not follow the body at all, and its
    clearance in a posed frame would measure a garment standing still while
    the body walked out of it.

    Signed metres in both directions, reported per clip with the worst frame,
    point and vertex-group name, so a failure names the bone to fix. The
    garment's facing is measured too, and a garment more than
    MAXIMUM_GARMENT_INWARD_AREA_FRACTION inside out fails even when every
    clearance is positive: in the engine it is not drawn.

    Every piece of scene state this touches — the frame, the armature's pose
    position, the action and its slot, every NLA track's mute — is restored
    before it returns.
    """
    from golem_blender.ops._objects import object_by_name

    return _measure_clearance(
        object_by_name(body_object_name, "MESH"),
        object_by_name(garment_object_name, "MESH"),
        action_names=action_names,
        minimum_clearance_m=minimum_clearance_m,
        frame_step=frame_step,
    )


def _measure_clearance(
    body_object,
    garment_object,
    *,
    action_names: tuple[str, ...] = (),
    minimum_clearance_m: float = DEFAULT_MINIMUM_CLEARANCE_M,
    frame_step: int = 1,
    report_progress=None,
) -> ClearanceReport:
    """The clearance measurement itself, on Blender objects — `fit_garment` reuses it.

    Kept apart from the op so the same measurement runs on a garment that has
    just been fitted and on one that was loaded from a file: one path, one
    verdict.
    """
    import bpy

    from golem_blender.analyze import winding

    if frame_step < 1:
        raise ValueError(f"frame_step must be at least 1, got {frame_step}")
    armature_object = _shared_armature(body_object, garment_object)
    scene = bpy.context.scene
    for action_name in action_names:
        if bpy.data.actions.get(action_name) is None:
            raise ValueError(
                f"no action named {action_name!r} in bpy.data.actions "
                f"(present: {sorted(a.name for a in bpy.data.actions)})"
            )

    state = _SceneState(scene, armature_object)
    try:
        state.capture()
        armature_object.data.pose_position = "REST"
        _refresh()

        rest_body = _WorldMesh(body_object)
        rest_garment = _WorldMesh(garment_object)
        covered = _covered_body_vertices(rest_body, rest_garment)
        method, inward_area_fraction = _garment_facing(rest_garment, rest_body, winding)

        clips: list[ClipClearance] = []
        clips.append(
            _measure_clip(
                rest_body,
                rest_garment,
                covered,
                frame=scene.frame_current,
                action_name="",
                minimum_clearance_m=minimum_clearance_m,
                body_object=body_object,
                garment_object=garment_object,
            )
        )

        for action_name in action_names:
            action = bpy.data.actions[action_name]
            from golem_blender.ops.animation import _bind_action

            _bind_action(armature_object, action)
            for track in armature_object.animation_data.nla_tracks:
                track.mute = True
            armature_object.data.pose_position = "POSE"
            frame_start = math.floor(action.frame_range[0])
            frame_end = math.ceil(action.frame_range[1])
            frames = list(range(frame_start, frame_end + 1, frame_step))
            if frames[-1] != frame_end:
                frames.append(frame_end)

            worst: ClipClearance | None = None
            failing_frames = 0
            for done, frame in enumerate(frames, start=1):
                scene.frame_set(frame)
                _refresh()
                row = _measure_clip(
                    _WorldMesh(body_object),
                    _WorldMesh(garment_object),
                    covered,
                    frame=frame,
                    action_name=action_name,
                    minimum_clearance_m=minimum_clearance_m,
                    body_object=body_object,
                    garment_object=garment_object,
                )
                if not row.passed:
                    failing_frames += 1
                if worst is None or row.worst_clearance_m < worst.worst_clearance_m:
                    worst = row
                if report_progress is not None:
                    report_progress(f"clearance {action_name}", done, len(frames))
            if worst is not None:
                clips.append(
                    ClipClearance(
                        action_name=worst.action_name,
                        frames_measured=len(frames),
                        failing_frame_count=failing_frames,
                        worst_frame=worst.worst_frame,
                        worst_clearance_m=worst.worst_clearance_m,
                        worst_point_m=worst.worst_point_m,
                        worst_kind=worst.worst_kind,
                        worst_group_name=worst.worst_group_name,
                        penetrating_vertex_count=worst.penetrating_vertex_count,
                        passed=failing_frames == 0,
                    )
                )
    finally:
        state.restore()

    failures = _failure_lines(clips, method, inward_area_fraction, garment_object.name)
    return ClearanceReport(
        body_object_name=body_object.name,
        garment_object_name=garment_object.name,
        armature_name=armature_object.name,
        minimum_clearance_m=float(minimum_clearance_m),
        covered_body_vertex_count=len(covered),
        garment_winding_method=method,
        garment_inward_area_fraction=inward_area_fraction,
        clips=tuple(clips),
        passed=not failures,
        failures=failures,
    )


# -- scene state ----------------------------------------------------------


class _SceneState:
    """The five pieces of scene state a clearance measurement changes, and the way back."""

    def __init__(self, scene, armature_object):
        self._scene = scene
        self._armature = armature_object
        self._frame = 0
        self._pose_position = ""
        self._action = None
        self._action_slot = None
        self._track_mutes: list[bool] = []

    def capture(self) -> None:
        self._frame = self._scene.frame_current
        self._pose_position = self._armature.data.pose_position
        animation_data = self._armature.animation_data
        if animation_data is not None:
            self._action = animation_data.action
            self._action_slot = animation_data.action_slot
            self._track_mutes = [track.mute for track in animation_data.nla_tracks]

    def restore(self) -> None:
        self._armature.data.pose_position = self._pose_position
        animation_data = self._armature.animation_data
        if animation_data is not None:
            animation_data.action = self._action
            animation_data.action_slot = self._action_slot
            for track, mute in zip(
                animation_data.nla_tracks, self._track_mutes, strict=False
            ):
                track.mute = mute
        self._scene.frame_set(self._frame)
        _refresh()


def _refresh() -> None:
    import bpy

    bpy.context.view_layer.update()


# -- geometry -------------------------------------------------------------


class _WorldMesh:
    """One object's evaluated triangles in world space, with a BVH over them, and its facing test inputs."""

    def __init__(self, blender_object):
        import bpy
        import numpy as np
        from mathutils.bvhtree import BVHTree

        self.object_name = blender_object.name
        dependency_graph = bpy.context.evaluated_depsgraph_get()
        evaluated = blender_object.evaluated_get(dependency_graph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            coordinates = np.empty(len(mesh.vertices) * 3, dtype=float)
            mesh.vertices.foreach_get("co", coordinates)
            matrix = np.array(blender_object.matrix_world, dtype=float)
            self.vertices = (
                coordinates.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]
            )
            flat = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
            mesh.loop_triangles.foreach_get("vertices", flat)
            self.triangles = flat.reshape(-1, 3)
            boundary = _boundary_edges(mesh)
        finally:
            evaluated.to_mesh_clear()
        self.polygon_count = len(blender_object.data.polygons)
        self.boundary_vertex_pairs = boundary
        self.tree = (
            BVHTree.FromPolygons(
                [tuple(point) for point in self.vertices],
                [tuple(triangle) for triangle in self.triangles],
            )
            if len(self.triangles)
            else None
        )
        self.corners = (
            self.vertices[self.triangles]
            if len(self.triangles)
            else np.zeros((0, 3, 3), dtype=float)
        )

    def nearest(self, point):
        """(location, normal, triangle index, distance) of the closest triangle, or None."""
        if self.tree is None:
            return None
        return self.tree.find_nearest(tuple(float(x) for x in point))

    def dominant_group_names(self, blender_object):
        """(vertex-group name of each BASE vertex's heaviest group), "" where it has none."""
        own_names = [group.name for group in blender_object.vertex_groups]
        names: list[str] = []
        for vertex in blender_object.data.vertices:
            heaviest = ""
            heaviest_weight = 0.0
            for element in vertex.groups:
                if element.weight > heaviest_weight:
                    heaviest_weight = element.weight
                    heaviest = own_names[element.group]
            names.append(heaviest)
        return names


def _boundary_edges(mesh) -> set[tuple[int, int]]:
    """Undirected edges used by exactly one polygon, as sorted vertex pairs."""
    counts: dict[tuple[int, int], int] = {}
    for polygon in mesh.polygons:
        loop = list(polygon.vertices)
        for index, start in enumerate(loop):
            end = loop[(index + 1) % len(loop)]
            key = (start, end) if start < end else (end, start)
            counts[key] = counts.get(key, 0) + 1
    return {edge for edge, count in counts.items() if count == 1}


def _barycentric(point, a, b, c):
    """Barycentric coordinates of `point` in triangle abc, clamped inside it."""
    import numpy as np

    point = np.asarray(tuple(point), dtype=float)
    a, b, c = (np.asarray(tuple(corner), dtype=float) for corner in (a, b, c))
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = float(v0 @ v0)
    d01 = float(v0 @ v1)
    d11 = float(v1 @ v1)
    d20 = float(v2 @ v0)
    d21 = float(v2 @ v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) < 1e-20:
        return 1.0, 0.0, 0.0
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return 1.0 - v - w, v, w


def _covered_body_vertices(
    rest_body: _WorldMesh, rest_garment: _WorldMesh
) -> list[int]:
    """Body vertices the garment covers at REST: near enough, off a rim, and on its inner side.

    Three tests, all at rest (see the module docstring for why rest):
      1. the nearest garment surface is within COVERAGE_REACH_M;
      2. that nearest point is not on a garment BOUNDARY edge — a hem's rim is
         not a covering surface, and its signed side is an artefact of where
         the rim happens to be;
      3. the body vertex is on the garment's INNER side, so a tunic's arm
         passing outside the sleeve is never counted as covered.
    """
    covered: list[int] = []
    for index, point in enumerate(rest_body.vertices):
        hit = rest_garment.nearest(point)
        if hit is None or hit[0] is None:
            continue
        location, normal, triangle_index, distance = hit[0], hit[1], hit[2], hit[3]
        if distance > COVERAGE_REACH_M:
            continue
        if _nearest_point_is_on_a_rim(location, rest_garment, triangle_index):
            continue
        offset = rest_body.vertices[index] - _as_array(location)
        if float(offset @ _as_array(normal)) >= 0.0:
            continue
        covered.append(index)
    return covered


def _nearest_point_is_on_a_rim(
    location, world_mesh: _WorldMesh, triangle_index: int
) -> bool:
    """Is this nearest point within epsilon of a BOUNDARY edge of its triangle?"""
    triangle = world_mesh.triangles[triangle_index]
    a, b, c = (world_mesh.vertices[index] for index in triangle)
    opposite = dict(
        zip(
            sorted(
                (
                    (triangle[1], triangle[2]),
                    (triangle[0], triangle[2]),
                    (triangle[0], triangle[1]),
                )
            ),
            _barycentric(location, a, b, c),
        )
    )
    for edge, coordinate in opposite.items():
        if edge in world_mesh.boundary_vertex_pairs and (
            coordinate < BOUNDARY_BARYCENTRIC_EPSILON
        ):
            return True
    return False


def _as_array(vector):
    import numpy as np

    return np.asarray(tuple(vector), dtype=float)


def _garment_facing(rest_garment: _WorldMesh, rest_body: _WorldMesh, winding):
    """("winding_number" | "away_from_body", inward area fraction) over the garment at rest."""
    if len(rest_garment.corners) == 0:
        raise ValueError("the garment has no faces, so it has no facing to measure")
    return _surface_facing(rest_garment.corners, rest_body.nearest)


def _surface_facing(corners, nearest_on_body) -> tuple[str, float]:
    """Which share of one garment surface faces the body, and which measure decided it.

    The garment's OWN generalized winding number decides first (Jacobson,
    Kavan and Sorkine-Hornung 2013, DOI 10.1145/2461912.2461916): it works on
    an open tube as on a closed shell — an outward-wound open tube's faces
    score 0.57 at the rims and above in the middle (measured, see
    `analyze/winding.py`), an inverted one the negatives.

    `away_from_body` — does the face's normal point away from the nearest
    body surface — decides only the area the winding number leaves
    UNDECIDED, a flat cape or a lone panel with no inside of its own. It is not
    trusted with more, because it misreads limbs: measured 2026-10-27 on a
    Kimodo mannequin, a uniformly outward lathe tube fitted up to the armpits
    read 5% "facing the body" by it alone, every such face one whose nearest
    body surface was an ARM outside the tube.

    The method reported is the one that decided most of the area.
    """
    import numpy as np

    from golem_blender.analyze import winding as winding_module

    sampled = winding_module.query_face_sample(len(corners), _winding_query_limit())
    classified = winding_module.classify_faces(
        winding_module.face_orientation_scores(corners, sampled)
    )
    sampled_corners = corners[sampled]
    areas = winding_module.triangle_areas(sampled_corners)
    total_m2 = float(areas.sum())
    if total_m2 <= 0.0:
        return METHOD_WINDING_NUMBER, 0.0
    inward_m2 = float(areas[classified == winding_module.INWARD].sum())
    undecided = np.flatnonzero(classified == winding_module.UNDECIDED)
    centroids = sampled_corners.mean(axis=1)
    for index in undecided:
        hit = nearest_on_body(centroids[index])
        if hit is None or hit[0] is None:
            continue
        corner_a, corner_b, corner_c = sampled_corners[index]
        normal = np.cross(corner_b - corner_a, corner_c - corner_a)
        if float(normal @ (centroids[index] - _as_array(hit[0]))) < 0.0:
            inward_m2 += float(areas[index])
    undecided_m2 = float(areas[undecided].sum())
    method = (
        METHOD_WINDING_NUMBER
        if undecided_m2 <= total_m2 / 2.0
        else METHOD_AWAY_FROM_BODY
    )
    return method, inward_m2 / total_m2


def _winding_query_limit() -> int:
    from golem_blender.ops.winding import WINDING_AUDIT_QUERY_LIMIT

    return WINDING_AUDIT_QUERY_LIMIT


# -- one frame ------------------------------------------------------------


def _measure_clip(
    body: _WorldMesh,
    garment: _WorldMesh,
    covered: list[int],
    *,
    frame: int,
    action_name: str,
    minimum_clearance_m: float,
    body_object,
    garment_object,
) -> ClipClearance:
    """Both clearance kinds for one frame, and the worst moment's whole story."""
    garment_groups = garment.dominant_group_names(garment_object)
    body_groups = body.dominant_group_names(body_object)

    worst_clearance_m = math.inf
    worst_point = (0.0, 0.0, 0.0)
    worst_kind = KIND_GARMENT_INSIDE_BODY
    worst_group_name = ""
    penetrating = 0

    for index, point in enumerate(garment.vertices):
        hit = body.nearest(point)
        if hit is None or hit[0] is None:
            continue
        location, normal, _face, distance = hit[0], hit[1], hit[2], hit[3]
        signed = (
            distance
            if float((_as_array(point) - _as_array(location)) @ _as_array(normal))
            >= 0.0
            else -distance
        )
        if signed < minimum_clearance_m:
            penetrating += 1
        if signed < worst_clearance_m:
            worst_clearance_m = signed
            worst_point = tuple(float(x) for x in point)
            worst_kind = KIND_GARMENT_INSIDE_BODY
            worst_group_name = (
                garment_groups[index] if index < len(garment_groups) else ""
            )

    for index in covered:
        point = body.vertices[index]
        hit = garment.nearest(point)
        if hit is None or hit[0] is None:
            continue
        location, normal, face, distance = hit[0], hit[1], hit[2], hit[3]
        # A covered vertex whose nearest garment point is on a RIM has left
        # through an opening (a thigh out of a hem, an arm out of a sleeve),
        # not through the cloth — the same rule that keeps a rim out of the
        # coverage at rest. Measured 2026-10-27 on a Kimodo mannequin kneeling
        # in a tunic: without it, every frame of the kneel failed at -0.156 m,
        # a thigh vertex 0.7 m below the hem it had slid out of.
        if _nearest_point_is_on_a_rim(location, garment, face):
            continue
        # The body is INSIDE the garment when it is on the garment's inner
        # side, so the sign is inverted relative to the first kind.
        signed = (
            -distance
            if float((_as_array(point) - _as_array(location)) @ _as_array(normal))
            >= 0.0
            else distance
        )
        if signed < minimum_clearance_m:
            penetrating += 1
        if signed < worst_clearance_m:
            worst_clearance_m = signed
            worst_point = tuple(float(x) for x in point)
            worst_kind = KIND_BODY_THROUGH_GARMENT
            worst_group_name = body_groups[index] if index < len(body_groups) else ""

    passed = penetrating == 0
    return ClipClearance(
        action_name=action_name,
        frames_measured=1,
        failing_frame_count=0 if passed else 1,
        worst_frame=frame,
        worst_clearance_m=float(worst_clearance_m)
        if worst_clearance_m < math.inf
        else 0.0,
        worst_point_m=worst_point,
        worst_kind=worst_kind,
        worst_group_name=worst_group_name,
        penetrating_vertex_count=penetrating,
        passed=passed,
    )


def _failure_lines(
    clips, method, inward_area_fraction, garment_name
) -> tuple[str, ...]:
    """The lines a caller reads: the facing first, then each clip's worst moment."""
    lines: list[str] = []
    if inward_area_fraction > MAXIMUM_GARMENT_INWARD_AREA_FRACTION:
        lines.append(
            f"facing: {garment_name} faces the body on "
            f"{inward_area_fraction:.0%} of its area (inside out; measured by "
            f"{method}) — an engine culls it, so it is not drawn at all"
        )
    for clip in clips:
        if clip.passed:
            continue
        lines.append(
            f"{clip.action_name or 'rest'}: frame {clip.worst_frame} "
            f"{clip.worst_kind} {clip.worst_clearance_m:+.3f} m at "
            f"{clip.worst_group_name or '(no group)'} "
            f"({clip.penetrating_vertex_count} vertices)"
        )
    if len(lines) > MAXIMUM_LISTED_FAILURES:
        extra = len(lines) - MAXIMUM_LISTED_FAILURES
        lines = lines[:MAXIMUM_LISTED_FAILURES]
        lines.append(f"... and {extra} more")
    return tuple(lines)


def _shared_armature(body_object, garment_object):
    """The one armature both meshes are bound to, or a refusal naming the missing bind."""
    body_armature = _bound_armature(body_object)
    garment_armature = _bound_armature(garment_object)
    if body_armature is None:
        raise ValueError(
            f"{body_object.name!r} is not bound to an armature: "
            f"bind_mesh_to_armature it with automatic_weights=False"
        )
    if garment_armature is None:
        raise ValueError(
            f"garment is not bound to {body_armature.name}: transfer_weights "
            f"from the body, then bind_mesh_to_armature("
            f"{garment_object.name!r}, {body_armature.name!r}, automatic_weights=False)"
        )
    if garment_armature != body_armature:
        raise ValueError(
            f"{garment_object.name!r} is bound to {garment_armature.name!r} and "
            f"{body_object.name!r} to {body_armature.name!r}; a clearance "
            f"between two rigs is not a garment and a body"
        )
    return body_armature


def _bound_armature(blender_object):
    """The armature the object's enabled Armature modifier points at, or None."""
    for modifier in blender_object.modifiers:
        if (
            modifier.type == ARMATURE_MODIFIER_TYPE
            and modifier.object is not None
            and modifier.show_viewport
        ):
            return modifier.object
    return None


# -- fit_garment ----------------------------------------------------------

# The standoff the original script's `--thickness` default holds the garment
# off the skin, and the depth at which it measured vertices-inside-the-body
# going from 32.4% to 0.0% (scripts/garment_fit.py:217-223, :180-196).
GARMENT_STANDOFF_M = 0.006

# The band fractions the original script's own ANCHORS table uses for a
# torso garment: 0.55 to 0.82 of body height. Cited in `fit_garment`'s
# docstring as guidance; the caller passes metres, because the body's own
# height is a measurement and a fraction of it hides which number was used.
TORSO_ANCHOR_FRACTIONS = (0.55, 0.82)

# A component facing the body on more than this share of its area is turned
# round: more of it is wrong than right, so reversing it is the smaller edit.
MAXIMUM_COMPONENT_INWARD_AREA_FRACTION = 0.5

# A vertex the drape moved further than this counts as moved. A metre
# tolerance: 1e-6 m is a micron, far under any standoff and far over float
# noise from a modifier evaluation.
DRAPE_MOVED_TOLERANCE_M = 1.0e-6


@dataclass(frozen=True)
class FitGarmentReport:
    """What fitting one generated garment onto one body did, and what the clearance says afterwards."""

    object_name: str
    body_object_name: str
    armature_name: str
    # The band the garment was scaled onto, in metres above the body's lowest
    # world z — the caller's own two heights, so the report repeats what was
    # asked for and not an approximation of it.
    band_m: tuple[float, float]
    quarter_turn: bool
    scale: float
    vertices_moved_by_drape: int
    components_reversed: int
    thickness_m: float
    fold_count: int
    weights: WeightTransferReport
    clearance: ClearanceReport
    passed: bool


@op(gated=True)
def fit_garment(
    garment_object_name: str,
    body_object_name: str,
    hem_height_m: float,
    collar_height_m: float,
    offset_m: float = GARMENT_STANDOFF_M,
    thickness_m: float = 0.0,
    fold_count: int = 0,
    fold_depth_m: float = 0.0,
    action_names: tuple[str, ...] = (),
) -> FitGarmentReport:
    """Fit an unbound garment onto a rigged body: turn, scale, pleat, drape out, weight, bind, measure.

    This is `scripts/garment_fit.py` as an op. Heights are metres above the
    body's lowest world z, so the caller states the band it wants rather than
    a fraction of a height it would have to measure first; the script's own
    ANCHORS table is the guidance for what a torso band looks like — 0.55 to
    0.82 of body height.

    `offset_m` is the standoff the drape holds the garment off the skin
    (the script's own default, which took its fixture from 32.4% of vertices
    inside the body to 0.0%). `thickness_m` gives the garment a solid rim with
    Blender's SOLIDIFY modifier, which is what closes an open garment's
    boundary edges — the gate fails those on every open mesh otherwise.
    `fold_count`/`fold_depth_m` add pleats that deepen toward the hem.

    The clearance verdict is REPORTED, not raised: an agent iterates on
    `offset_m` and on the band, and a raise would throw away the numbers that
    say which way to move. A garment component whose winding is mixed is the
    one refusal — reversing it would flip its correct faces too.
    """
    import bpy
    import numpy as np

    from golem_blender.analyze import garment_placement
    from golem_blender.analyze import winding as winding_module
    from golem_blender.ops._objects import object_by_name

    garment = object_by_name(garment_object_name, "MESH")
    body = object_by_name(body_object_name, "MESH")

    if collar_height_m <= hem_height_m:
        raise ValueError(
            f"collar_height_m ({collar_height_m}) must be above hem_height_m "
            f"({hem_height_m})"
        )
    if hem_height_m < 0.0:
        raise ValueError(f"hem_height_m must be 0 or more, got {hem_height_m}")
    if fold_count < 0:
        raise ValueError(f"fold_count must be 0 or more, got {fold_count}")
    if fold_depth_m < 0.0:
        raise ValueError(f"fold_depth_m must be 0 or more, got {fold_depth_m}")
    if (fold_count > 0) != (fold_depth_m > 0.0):
        raise ValueError(
            f"fold_count ({fold_count}) and fold_depth_m ({fold_depth_m}) must "
            f"both be set or both be 0: a fold_count with no depth pleats "
            f"nothing, and a depth with no count pleats nowhere"
        )
    if thickness_m < 0.0:
        raise ValueError(f"thickness_m must be 0 or more, got {thickness_m}")
    armature_object = _bound_armature(body)
    if armature_object is None:
        raise ValueError(
            "body is not rigged: import it with import_rigged_glb (or bind it "
            "with bind_mesh_to_armature), then fit the garment to it"
        )
    if _bound_armature(garment) is not None or garment.vertex_groups:
        raise ValueError(
            f"{garment.name!r} is already bound (it has an Armature modifier or "
            f"vertex groups); fit an unbound garment"
        )

    from golem_blender.ops.transforms import _world_bounds_m

    previous_pose = armature_object.data.pose_position
    armature_object.data.pose_position = "REST"
    # A refused fit leaves the garment exactly as it was handed over: the
    # agent's next move is a retry with another band or offset, and a garment
    # already turned, scaled and draped by the failed call would be fitted
    # twice (measured: a refused fit left the mesh placed and draped).
    snapshot = _GarmentSnapshot(garment)
    try:
        # The band is measured at REST, the pose the garment is fitted in:
        # measured on the tube humanoid, the lowest point at frame 1 of a leg
        # swing is 0.016 m lower than at rest, and a band read from the posed
        # body sits that far off the one the drape and the weights use.
        bpy.context.view_layer.update()
        body_minimum, _body_maximum = _world_bounds_m([body])
        lowest_z_m = body_minimum[2]
        band_bottom_m = lowest_z_m + hem_height_m
        band_top_m = lowest_z_m + collar_height_m

        # Bake the garment's own transform into its mesh FIRST: every point
        # read below must be world, and every point written below is
        # mesh-local, so the two only agree once the matrix is identity.
        garment.data.transform(garment.matrix_world)
        from mathutils import Matrix

        garment.matrix_world = Matrix.Identity(4)
        bpy.context.view_layer.update()

        body_points = _world_points(body)
        garment_points = np.array(
            [tuple(vertex.co) for vertex in garment.data.vertices], dtype=float
        )
        placement = garment_placement.place_garment(
            garment_points, body_points, band_bottom_m, band_top_m
        )
        placed = garment_placement.apply_placement(garment_points, placement)
        girth_note = _girth_note(placed, placement, garment_placement)
        if fold_count > 0:
            axis_xy_m = (
                float(placed[:, 0].mean()),
                float(placed[:, 1].mean()),
            )
            placed = placed + garment_placement.pleat_offsets(
                placed,
                axis_xy_m,
                band_bottom_m,
                band_top_m,
                fold_count,
                fold_depth_m,
            )
        _set_vertices(garment, placed)

        try:
            vertices_moved_by_drape = _drape(garment, body, offset_m)
            components_reversed = _orient_components(garment, body, winding_module)
            if thickness_m > 0.0:
                _solidify(garment, thickness_m)
            weights = _transfer_and_bind(garment, body, armature_object)
        except ValueError as error:
            # A garment too thin for the body is folded by the drape, and the
            # step that notices is whichever comes next — the facing check, or
            # the weight transfer finding no face that agrees with the body
            # (measured: both, on two different garments). The cause is the
            # girth, so the refusal says so whichever step raised.
            if girth_note:
                raise ValueError(f"{error}. Likely cause: {girth_note}") from error
            raise
    except BaseException:
        snapshot.restore()
        raise
    else:
        snapshot.discard()
    finally:
        armature_object.data.pose_position = previous_pose

    clearance = _measure_clearance(
        body,
        garment,
        action_names=action_names,
        minimum_clearance_m=DEFAULT_MINIMUM_CLEARANCE_M,
    )
    return FitGarmentReport(
        object_name=garment.name,
        body_object_name=body.name,
        armature_name=armature_object.name,
        band_m=(band_bottom_m, band_top_m),
        quarter_turn=placement.quarter_turn,
        scale=placement.scale,
        vertices_moved_by_drape=vertices_moved_by_drape,
        components_reversed=components_reversed,
        thickness_m=thickness_m,
        fold_count=fold_count,
        weights=weights,
        clearance=clearance,
        passed=clearance.passed,
    )


class _GarmentSnapshot:
    """The garment as it was handed to `fit_garment`, and the way back to it."""

    def __init__(self, garment):
        self._garment = garment
        self._mesh = garment.data.copy()
        self._mesh_name = garment.data.name
        self._matrix = garment.matrix_world.copy()
        self._parent = garment.parent
        self._modifier_names = {modifier.name for modifier in garment.modifiers}

    def restore(self) -> None:
        """Put the original mesh, transform and modifier stack back; drop what the fit added."""
        import bpy

        garment = self._garment
        for modifier in list(garment.modifiers):
            if modifier.name not in self._modifier_names:
                garment.modifiers.remove(modifier)
        for group in list(garment.vertex_groups):
            garment.vertex_groups.remove(group)
        fitted_mesh = garment.data
        garment.data = self._mesh
        bpy.data.meshes.remove(fitted_mesh)
        self._mesh.name = self._mesh_name
        garment.parent = self._parent
        garment.matrix_world = self._matrix
        bpy.context.view_layer.update()

    def discard(self) -> None:
        """The fit succeeded: the copy is not needed."""
        import bpy

        bpy.data.meshes.remove(self._mesh)


def _girth_note(placed, placement, garment_placement) -> str:
    """Why the drape would crumple this garment, when the reason is its girth; "" otherwise.

    `place_garment` scales on HEIGHT and lets the garment's own proportions
    decide its girth, so a garment narrower than the body band it was put on is
    inside the body before the drape — and the drape pushes each vertex out to
    whichever surface is nearest, folding it over itself. Its faces then point
    every which way, and the facing check refuses it. That is a girth problem,
    not a winding one, and the message has to say which.
    """
    bottom_m, top_m = placement.band_m
    extents = garment_placement.horizontal_extents(placed, bottom_m, top_m)
    if (
        extents.width_m >= placement.body_width_m
        and extents.depth_m >= placement.body_depth_m
    ):
        return ""
    return (
        f"before the drape the garment was {extents.width_m:.3f} x "
        f"{extents.depth_m:.3f} m across against a {placement.body_width_m:.3f} x "
        f"{placement.body_depth_m:.3f} m body band, so the drape folded it onto "
        f"the body. The fit scales on height; give the source garment more girth "
        f"per metre of height, or fit it to a taller band"
    )


def _world_points(blender_object):
    """The evaluated mesh's vertices in world metres, as an (N, 3) array."""
    import bpy
    import numpy as np

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = blender_object.evaluated_get(dependency_graph)
    mesh = evaluated.to_mesh()
    try:
        coordinates = np.empty(len(mesh.vertices) * 3, dtype=float)
        mesh.vertices.foreach_get("co", coordinates)
        matrix = np.array(blender_object.matrix_world, dtype=float)
    finally:
        evaluated.to_mesh_clear()
    return coordinates.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3]


def _set_vertices(blender_object, points) -> None:
    """Write world-metre points into a mesh whose matrix is identity."""
    import numpy as np

    blender_object.data.vertices.foreach_set(
        "co", np.asarray(points, dtype=np.float32).reshape(-1)
    )
    blender_object.data.update()


def _drape(garment, body, offset_m: float) -> int:
    """Shrinkwrap the garment out of the body, and count the vertices it moved.

    `wrap_mode="OUTSIDE"` moves a vertex ONLY when it is inside the target,
    which is the whole trick: it evicts the penetrating vertices and leaves
    the rest of the garment's shape alone. `TARGET_PROJECT` was tried first in
    the original script and is wrong here — it projects EVERY vertex onto the
    surface, collapsing a corset flat against the skin, and it left 30.9% of
    vertices still inside.
    """
    import bpy
    import numpy as np

    before = np.array(
        [tuple(vertex.co) for vertex in garment.data.vertices], dtype=float
    )
    modifier = garment.modifiers.new(name="Drape", type="SHRINKWRAP")
    modifier.target = body
    modifier.wrap_method = "NEAREST_SURFACEPOINT"
    modifier.wrap_mode = "OUTSIDE"
    modifier.offset = offset_m
    with bpy.context.temp_override(object=garment, active_object=garment):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.context.view_layer.update()
    after = np.array(
        [tuple(vertex.co) for vertex in garment.data.vertices], dtype=float
    )
    return int((np.linalg.norm(after - before, axis=1) > DRAPE_MOVED_TOLERANCE_M).sum())


def _orient_components(garment, body, winding_module) -> int:
    """Reverse every garment component that faces the body; refuse one whose winding is mixed.

    A generated garment arrives with whichever winding its generator produced,
    and a component facing the body is invisible in the engine — back-face
    culling deletes it. Each component is decided on its own, because a tunic
    and its separate sleeves are separate shells.

    Two passes, the second a MEASUREMENT of the first: a component facing the
    body on more than half its area is reversed, and then every component is
    measured again. One still over MAXIMUM_GARMENT_INWARD_AREA_FRACTION after
    that had faces both ways — reversing it turned its correct half inward —
    and it is refused rather than shipped half-culled.
    """
    import bmesh

    mesh = garment.data
    body_tree = _body_bvh(body)
    fractions, polygons_of_component = _component_inward_fractions(
        mesh, body_tree, winding_module
    )
    to_reverse = sorted(
        polygon
        for component, fraction in fractions.items()
        if fraction > MAXIMUM_COMPONENT_INWARD_AREA_FRACTION
        for polygon in polygons_of_component[component]
    )
    reversed_components = sum(
        1
        for fraction in fractions.values()
        if fraction > MAXIMUM_COMPONENT_INWARD_AREA_FRACTION
    )
    if to_reverse:
        working = bmesh.new()
        try:
            working.from_mesh(mesh)
            working.faces.ensure_lookup_table()
            bmesh.ops.reverse_faces(
                working, faces=[working.faces[index] for index in to_reverse]
            )
            working.to_mesh(mesh)
        finally:
            working.free()
        mesh.update()

    after, _ = _component_inward_fractions(mesh, body_tree, winding_module)
    for component, fraction in after.items():
        if fraction > MAXIMUM_GARMENT_INWARD_AREA_FRACTION:
            raise ValueError(
                f"component {component} faces the body on {fraction:.0%} of its "
                f"area after orientation: its winding is mixed; fix the source "
                f"garment"
            )
    return reversed_components


def _component_inward_fractions(mesh, body_tree, winding_module):
    """({component: area fraction facing the body}, {component: polygon indices}).

    Each component is measured by `_surface_facing` on its OWN triangles, so a
    separate sleeve is not decided by the tunic's winding beside it.
    """
    import numpy as np

    mesh.calc_loop_triangles()
    flat = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int64)
    mesh.loop_triangles.foreach_get("vertices", flat)
    triangles = flat.reshape(-1, 3)
    polygon_of_triangle = np.empty(len(mesh.loop_triangles), dtype=np.int64)
    mesh.loop_triangles.foreach_get("polygon_index", polygon_of_triangle)
    corners = np.array([tuple(vertex.co) for vertex in mesh.vertices], dtype=float)[
        triangles
    ]
    components = winding_module.triangle_components(triangles)

    def nearest_on_body(point):
        return body_tree.find_nearest(tuple(float(x) for x in point))

    fractions: dict[int, float] = {}
    polygons: dict[int, list[int]] = {}
    for component in sorted(set(components.tolist())):
        in_component = np.flatnonzero(components == component)
        _method, fractions[component] = _surface_facing(
            corners[in_component], nearest_on_body
        )
        polygons[component] = sorted(set(polygon_of_triangle[in_component].tolist()))
    return fractions, polygons


def _body_bvh(body):
    """A world-space BVH over the body's evaluated triangles."""
    from mathutils.bvhtree import BVHTree

    points = _world_points(body)
    mesh = body.data
    mesh.calc_loop_triangles()
    triangles = [tuple(loop_triangle.vertices) for loop_triangle in mesh.loop_triangles]
    return BVHTree.FromPolygons(
        [tuple(float(coordinate) for coordinate in point) for point in points],
        triangles,
    )


def _solidify(garment, thickness_m: float) -> None:
    """Give the garment a wall with Blender's SOLIDIFY modifier and bake it in.

    `offset=1.0` grows the wall OUTWARD, so the inner surface stays where the
    drape put it and the standoff survives. Blender's modifier, not
    `bmesh.ops.solidify`: `ops/relief.py` measured that producing inverted
    shells.
    """
    import bpy

    modifier = garment.modifiers.new(name="Thickness", type="SOLIDIFY")
    modifier.thickness = thickness_m
    modifier.offset = 1.0
    modifier.use_rim = True
    modifier.use_even_offset = True
    with bpy.context.temp_override(object=garment, active_object=garment):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.context.view_layer.update()


def _transfer_and_bind(garment, body, armature_object):
    """Weight the garment from the body (RSWT), then bind it with no second weighting."""
    from golem_blender.ops.rigging import bind_mesh_to_armature
    from golem_blender.ops.weight_transfer import transfer_weights

    report = transfer_weights(body.name, garment.name)
    bind_mesh_to_armature(garment.name, armature_object.name, automatic_weights=False)
    return report
