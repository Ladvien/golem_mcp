"""Skinned-motion ops: does a clip pass its character through itself, and the repairs.

Why these ops exist: a retargeted or generated clip crosses its own body
(a hand through the thigh, a knee through a skirt) and nothing in the
structural gate sees it, because the mesh is sound at rest. The relation
checked is metamorphic: a surface free of intersections at rest must stay
free of them in every pose, measured as the length of the intersection
contour of the posed, skinned triangles (ContourCraft, SIGGRAPH 2024,
DOI 10.1145/3641519.3657408). Two readers (`clip_self_intersection_report`,
`body_capsules_report`) measure; two writers repair what they find.

`repair_limb_penetration` turns the arms and legs off the trunk and off
each other by the smallest rotation that separates their capsules: a
capsule is the cheapest stand-in for a limb that still has a signed depth
with a gradient, from the segment-segment distance of Ericson, Real-Time
Collision Detection, 2005, 5.1.9. `bake_cloth_chains` gives a skirt a ring
of bone chains and bakes their motion by position-based dynamics against
those capsules: Jakobsen, Advanced Character Physics, GDC 2001; for skinned
characters Abu Rumman and Fratarcangeli, Position-Based Skinning for Soft
Articulated Characters, Computer Graphics Forum 2015, DOI
10.1111/cgf.12533.

The numerics live in the `skinclip` package (numpy only; Blender's bundled
numpy serves it). This module imports it INSIDE the op bodies, as it does
bpy, so the facade, the MCP server and the pure test layer import it with
no numpy; `golem_blender.ops._skinned` is the adapter that reads an armature and
its bound meshes into skinclip's objects and writes keys back.

Literature search, 2026-10-12 (`timeout 25 hs distill search`, three
topics). "skinned character self-intersection detection linear blend
skinning" returned, among other papers, Moutafidou et al., Deep fusible
skinning of animation sequences, DOI 10.1007/s00371-023-03130-3 (limb
self-collisions handled as a post-process over a geometric skinning).
"capsule collision proxy character limb penetration" returned nothing
citable beyond what skinclip's docstrings already cite (Ericson, above).
"position based dynamics cloth skirt bone chains" returned Abu Rumman and
Fratarcangeli first. ContourCraft and Jakobsen are cited from skinclip's
docstrings, not from these searches. skinclip says of its repair solver
and its chain layout that no per-frame limb solver and no skirt-bone paper
exist to cite, so both are skinclip's own.
"""

from __future__ import annotations

from dataclasses import dataclass

# skinclip.spec imports nothing (no numpy), so the facade, the manifest and the
# schema generator can name the real class; skinclip.cloth re-exports it.
from skinclip.spec import RingSkirtSpec

from golem_blender.ops._contract import op

# skinclip's `CheckSettings.contour_limit_m`: a frame fails when its
# intersection contour is longer than this. Duplicated here because the
# default must be readable without importing numpy;
# `tests/blender/test_motion_ops.py` asserts the two agree.
DEFAULT_CONTOUR_LIMIT_M = 0.04

# Keep a chain's knee and hem this far off the ground plane (z = 0): the
# cloth has thickness. skinclip's own cloth test uses the same 2 cm.
CLOTH_GROUND_CLEARANCE_M = 0.02

CHAIN_SUFFIX_UPPER = "a"
CHAIN_SUFFIX_LOWER = "b"


class ArmatureRotationModeError(ValueError):
    """A keyed pose bone is not in QUATERNION rotation mode.

    Blender evaluates only the channel of the bone's rotation mode, and
    the clip is read, and the repair written, as quaternion keys: a bone
    keyed through Euler channels would be read as unrotated.
    """


@dataclass(frozen=True)
class PairContour:
    """Two surface parts that cross, and the length of their shared contour."""

    label_a: str
    label_b: str
    contour_m: float


@dataclass(frozen=True)
class ClipIntersectionReport:
    """Where a clip's skinned surface passes through itself, in Blender frame numbers."""

    action_name: str
    frames: int
    failing_frame_count: int
    worst_frame: int
    worst_contour_m: float
    worst_pairs: tuple[PairContour, ...]
    passed: bool


@dataclass(frozen=True)
class CapsuleReading:
    """One body capsule: a bone segment with a radius, at the rest pose, in world metres."""

    name: str
    start_bone: str
    # "" for the centroid rule: the far end mirrors the start through the
    # centroid of the vertices the bone owns (the head, the hand).
    end_bone: str
    radius_m: float
    start_m: tuple[float, float, float]
    end_m: tuple[float, float, float]


@dataclass(frozen=True)
class BodyCapsulesReport:
    """The capsules measured from the mesh that wraps a humanoid rig."""

    rig_convention: str
    capsules: tuple[CapsuleReading, ...]


@dataclass(frozen=True)
class LimbRepairReport:
    """What `repair_limb_penetration` changed: depths are capsule overlaps in metres."""

    frames_repaired: int
    bones_changed: tuple[str, ...]
    worst_depth_m_before: float
    worst_depth_m_after: float


@dataclass(frozen=True)
class ClothBakeReport:
    """What `bake_cloth_chains` built and baked."""

    bones_created: int
    vertices_weighted: int
    frames_baked: int
    # The smallest distance, over every frame, from a chain bone's segment
    # to a body capsule's axis, less the capsule radius, read from the
    # POSED pose bones in Blender (not from the simulation's own arrays).
    worst_clearance_m: float


@op(reads_only=True)
def clip_self_intersection_report(
    armature_name: str,
    action_name: str,
    cloth_material: str = "",
    contour_limit_m: float = DEFAULT_CONTOUR_LIMIT_M,
) -> ClipIntersectionReport:
    """Measure where an armature's action passes its skinned meshes through themselves.

    Poses every bound mesh through every integer frame of the action and
    measures the contour where triangles cross, leaving out pairs that
    touched at rest or fold together at one joint. A frame fails when its
    contour is longer than `contour_limit_m`. `cloth_material` names loose
    cloth whose contact with itself is not counted. Frames are Blender
    frame numbers. Changes nothing.
    """
    from skinclip.intersect import CheckSettings, check_clip

    from golem_blender.ops import _skinned
    from golem_blender.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    settings = CheckSettings(
        contour_limit_m=contour_limit_m,
        cloth_materials=(cloth_material,) if cloth_material else (),
        fps=_skinned.scene_fps(),
    )
    figure = _skinned.read_figure(armature_object, settings)
    action = _skinned.read_action_clip(
        armature_object, action_name, figure.skeleton, settings.fps
    )
    check = check_clip(figure, action_name, [action.clip], settings)
    if len(check.contour_by_frame) != action.frame_count:
        raise RuntimeError(
            f"skinclip checked {len(check.contour_by_frame)} frames of "
            f"{action_name!r}; the action has {action.frame_count}"
        )
    return ClipIntersectionReport(
        action_name=action_name,
        frames=check.frames,
        failing_frame_count=check.failing,
        worst_frame=action.frame_start + check.worst_frame,
        worst_contour_m=check.worst_contour_m,
        worst_pairs=tuple(
            PairContour(label_a, label_b, contour_m)
            for label_a, label_b, contour_m in check.worst_parts
        ),
        passed=check.passed,
    )


@op(reads_only=True)
def body_capsules_report(armature_name: str) -> BodyCapsulesReport:
    """Measure the body capsules of a humanoid armature from the meshes bound to it.

    A capsule runs from a bone's joint to its child along the bone, with
    the radius of the 90th percentile of the vertices that bone owns; the
    head and hands have no child and mirror their start through the
    centroid of their vertices. The armature must be a UE5-mannequin or
    Mixamo humanoid (22 joints); anything else raises. Positions are the
    rest pose in world metres. Changes nothing.
    """
    from skinclip import capsules, humanoid
    from skinclip.intersect import CheckSettings

    from golem_blender.ops import _skinned
    from golem_blender.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    figure = _skinned.read_figure(armature_object, CheckSettings())
    roles = humanoid.detect(figure.skeleton.names)
    measured = capsules.measure(figure, roles)
    rest = _skinned.rest_worlds(figure.skeleton)
    placed = capsules.positions(figure, rest[None], measured)
    return BodyCapsulesReport(
        rig_convention=humanoid.convention(roles),
        capsules=tuple(
            CapsuleReading(
                name=name,
                start_bone=capsule.start,
                end_bone=capsule.end or "",
                radius_m=float(capsule.radius_m),
                start_m=_point(placed[name][0][0]),
                end_m=_point(placed[name][1][0]),
            )
            for name, capsule in measured.items()
        ),
    )


def repair_limb_penetration(
    armature_name: str,
    action_name: str,
    loop: bool = False,
) -> LimbRepairReport:
    """Turn the arms and legs of an action off the body and each other where their capsules overlap.

    Finds the frames where two limb capsules (or a limb and the trunk)
    are closer than their radii plus skinclip's margin (5 mm at v0.1.1) and rotates the upper
    and lower limb bones by the smallest rotation that clears them,
    smoothed over time; `loop` keeps the last frame equal to the first.
    Replaces the `rotation_quaternion` keys of the bones it changed with
    one key per frame; every other curve is untouched. The armature must
    be a UE5 or Mixamo humanoid whose action is its active action, all
    bones in QUATERNION mode, and only the pelvis may carry location keys.
    """
    from skinclip import capsules, humanoid
    from skinclip.intersect import CheckSettings
    from skinclip.repair import repair

    from golem_blender.ops import _skinned
    from golem_blender.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    settings = CheckSettings(fps=_skinned.scene_fps())
    figure = _skinned.read_figure(armature_object, settings)
    roles = humanoid.detect(figure.skeleton.names)
    action = _skinned.read_action_clip(
        armature_object, action_name, figure.skeleton, settings.fps
    )
    _skinned.require_rotation_and_root_motion_only(
        action, figure.skeleton, roles["pelvis"]
    )
    fixed, report = repair(
        figure,
        roles,
        capsules.measure(figure, roles),
        _skinned.local_rotations(figure.skeleton, action),
        _skinned.local_translation(figure.skeleton, action, roles["pelvis"]),
        loop,
        fps=settings.fps,
    )
    _skinned.write_rotation_keys(
        armature_object,
        figure.skeleton,
        action.frame_numbers,
        {bone: fixed[bone] for bone in report.joints_changed},
    )
    return LimbRepairReport(
        frames_repaired=report.frames_repaired,
        bones_changed=tuple(report.joints_changed),
        worst_depth_m_before=float(report.worst_depth_m_before),
        worst_depth_m_after=float(report.worst_depth_m_after),
    )


def bake_cloth_chains(
    armature_name: str,
    mesh_name: str,
    garment_material: str,
    anchor_bone_name: str,
    action_name: str,
    spec: RingSkirtSpec,
    loop: bool = False,
) -> ClothBakeReport:
    """Hang a ring of bone chains under a bone, weight a garment to them and bake their motion.

    When the bone `{prefix}00_a` is missing, creates 2 * count bones under
    `anchor_bone_name` (top to knee, then knee to hem, on the garment
    surface) and writes vertex groups for the vertices of
    `garment_material` on `mesh_name`; when the bones exist they are
    reused and the weights are left alone. Then always bakes
    `rotation_quaternion` keys for the chain bones over every frame of the
    action, simulating the chains against the body capsules (they keep
    clear of the legs, feet and arms) and reports the clearance measured
    on the posed bones. Every refusal happens before the scene is touched.

    `spec` places the chains: `count` chains round the garment, hung from
    `top_height_m` (the chain top) through `knee_height_m` to
    `hem_height_m`, all world Z in metres; the garment keeps its own
    weights above `blend_height_m` and is mixed with the chains' between
    the top and that height; `inset_m` pulls the chains inside the garment
    surface; bones are named `{prefix}{NN}_a` (top to knee) and
    `{prefix}{NN}_b` (knee to hem). Heights must satisfy hem < knee < top
    < blend. `mesh_name` must be bound to the armature.
    """
    from skinclip import capsules, humanoid
    from skinclip.intersect import CheckSettings

    from golem_blender.ops import _skinned
    from golem_blender.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    mesh_object = object_by_name(mesh_name, "MESH")
    # Everything that can refuse does so before the scene is touched: a bad
    # action name, a rig that is not a humanoid, a keyed bone in Euler mode,
    # a mesh that is not bound or has no such material.
    fps = _skinned.scene_fps()
    rig = _skinned.read_skeleton(armature_object)
    roles = humanoid.detect(rig.names)
    action = _skinned.read_action_clip(armature_object, action_name, rig, fps)
    skirt = _skinned.chain_layout(armature_object, mesh_object, garment_material, spec)
    created = _skinned.ensure_chain_bones(armature_object, anchor_bone_name, skirt)
    weighted = (
        _skinned.weight_garment(armature_object, mesh_object, garment_material, skirt)
        if created
        else 0
    )
    figure = _skinned.read_figure(
        armature_object, CheckSettings(fps=fps, non_crease_prefixes=(spec.prefix,))
    )
    measured = capsules.measure(figure, roles, ignore_prefixes=(spec.prefix,))
    rotations = _skinned.simulate_chains(
        figure, measured, action, skirt, loop, CLOTH_GROUND_CLEARANCE_M
    )
    _skinned.write_rotation_keys(
        armature_object, figure.skeleton, action.frame_numbers, rotations
    )
    return ClothBakeReport(
        bones_created=created,
        vertices_weighted=weighted,
        frames_baked=action.frame_count,
        worst_clearance_m=_skinned.posed_chain_clearance_m(
            armature_object, action.frame_numbers, measured, skirt
        ),
    )


def _point(vector) -> tuple[float, float, float]:
    """A numpy 3-vector as a plain tuple of floats."""
    return (float(vector[0]), float(vector[1]), float(vector[2]))
