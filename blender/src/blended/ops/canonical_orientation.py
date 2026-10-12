"""Put the middle extent on the depth axis, deterministically.

3DCodeBench scores a generated mesh against a reference with chamfer
distance, minimised over 4 rotations of the GENERATED cloud about the GLB
file's Z axis (`metrics/shape_chamfer.py:126 chamfer_with_yaw`). The bench
exports with `export_yup=True` (`core/export_glb.py:102`), so

    glTF X = Blender X      glTF Y = Blender Z (up)      glTF Z = -Blender Y

The scorer's yaw group therefore quotients out rotations that mix width
with height, and penalises IN FULL exactly one degree of freedom: which
Blender axis ends up on the depth axis (Blender +/-Y). Nothing the writer
can do about up-vs-across matters to the score; the depth assignment is
the whole orientation artifact (iter2: 0.048 of a 0.0714 mean).

There is no reference convention to copy — over the 145 dev references the
depth-axis extent rank is near-uniform (44 largest / 59 middle / 42
smallest), and the briefs carry no world-axis vocabulary. So the rule is
chosen to minimise EXPECTED penalty, measured by
`scripts/orientation_policy_sim.py` over those 145 references, each used
as its own shape-perfect generation:

    largest extent on depth   mean cd_yawmin 0.0701
    MIDDLE  extent on depth   mean cd_yawmin 0.0311   <- this module
    smallest extent on depth  mean cd_yawmin 0.0883
    unconstrained (today)     mean cd_yawmin 0.0632

Middle wins in every anisotropy band, for two independent reasons: it is
the mode of the reference distribution, and its two possible mistakes are
middle<->largest and middle<->smallest, so it never pays the expensive
largest<->smallest swap.

Why this is harness code and not a prompt sentence: BlenderGym measures a
consistent win from raising the verification ratio of a code-editing loop
(DOI 10.48550/arXiv.2504.01786), and the local visual verifier is
measured at 0.20-0.40 sensitivity, in line with the false-negative rates
reported for imperfect visual verifiers (DOI 10.48550/arXiv.2606.15693).
A deterministic geometric step is the only one of the two that cannot
miss. The rule is derived on a dev split and confirmed once on the frozen
holdout because selecting on the reported set inflates the reported
number by 9-13% (DOI 10.48550/arXiv.2507.02554).

Nothing here reads `object.dimensions`: that is the LOCAL bounding box
scaled, so it ignores the object's rotation, and the whole question here
is a world-axis one. World extents come from `matrix_world @ bound_box`,
after a depsgraph refresh (see `blended.ops.transforms`).
"""

from __future__ import annotations

import math

from blended.ops._contract import op

DEPTH_AXIS_EXTENT_RANK = 1  # middle extent goes on the depth axis
DEPTH_AXIS_INDEX = 1  # Blender Y; glTF Z after export_yup
DEGENERATE_EXTENT_M = 1e-9  # below this the object has no geometry
POST_CONDITION_TOLERANCE_RATIO = 1e-6  # float slack after a 90-deg turn
QUARTER_TURN_RAD = math.pi / 2.0
AXIS_COUNT = 3

# One 90-degree turn per source axis, chosen so the named axis lands on
# Blender Y. Rz(+90) maps X -> Y; Rx(+90) maps Z -> -Y (extent unchanged).
_ROTATION_ONTO_DEPTH_AXIS_RAD = {
    0: (0.0, 0.0, QUARTER_TURN_RAD),
    1: (0.0, 0.0, 0.0),
    2: (QUARTER_TURN_RAD, 0.0, 0.0),
}


def _as_extent_triple_m(
    extents_m: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Coerce to a float 3-tuple; a wrong-length input raises ValueError."""
    extent_x_m, extent_y_m, extent_z_m = extents_m
    return (float(extent_x_m), float(extent_y_m), float(extent_z_m))


@op(reads_only=True)
def middle_extent_m(extents_m: tuple[float, float, float]) -> float:
    """The rank-DEPTH_AXIS_EXTENT_RANK extent VALUE, not its axis.

    The policy is about a value, not a position: with two equal extents
    the "middle" one is ambiguous as an axis but never as a number, and
    that is what keeps the rule idempotent on a cube.
    """
    return sorted(float(extent) for extent in extents_m)[DEPTH_AXIS_EXTENT_RANK]


@op(reads_only=True)
def depth_axis_holds_middle_extent(extents_m: tuple[float, float, float]) -> bool:
    """Does the depth axis already carry a middle-valued extent?"""
    extents_m = _as_extent_triple_m(extents_m)
    largest = max(extents_m)
    if largest <= DEGENERATE_EXTENT_M:
        return False
    difference = abs(extents_m[DEPTH_AXIS_INDEX] - middle_extent_m(extents_m))
    return difference <= POST_CONDITION_TOLERANCE_RATIO * largest


@op(reads_only=True)
def canonical_depth_axis_rotation_euler_rad(
    extent_x_m: float, extent_y_m: float, extent_z_m: float
) -> tuple[float, float, float]:
    """The single 90-degree turn that puts the middle extent on Blender Y.

    Pure: no bpy, no scene. Returns an XYZ Euler in radians, one of three
    values — identity, a quarter turn about Z, or a quarter turn about X.

    Raises ValueError on a degenerate or negative extent triple: an object
    with no measurable size is a real failure and orienting it would be
    meaningless.
    """
    extents_m = (float(extent_x_m), float(extent_y_m), float(extent_z_m))
    if min(extents_m) < 0.0:
        raise ValueError(f"negative extent in {extents_m}")
    if max(extents_m) <= DEGENERATE_EXTENT_M:
        raise ValueError(
            f"degenerate extents {extents_m}: max <= {DEGENERATE_EXTENT_M} m"
        )
    if depth_axis_holds_middle_extent(extents_m):
        return _ROTATION_ONTO_DEPTH_AXIS_RAD[DEPTH_AXIS_INDEX]
    middle_m = middle_extent_m(extents_m)
    source_axis = min(axis for axis in range(AXIS_COUNT) if extents_m[axis] == middle_m)
    return _ROTATION_ONTO_DEPTH_AXIS_RAD[source_axis]


@op(reads_only=True)
def depth_axis_extent_rank(extents_m: tuple[float, float, float]) -> int:
    """How many extents are strictly larger than the depth-axis extent.

    Reported, never asserted on: for a near-isotropic object the position
    is arbitrary while the VALUE invariant still holds.
    """
    extents_m = _as_extent_triple_m(extents_m)
    return sum(1 for extent in extents_m if extent > extents_m[DEPTH_AXIS_INDEX])


AXIS_NAMES = ("x", "y", "z")
ORIENTATION_READING_DECIMALS = 4


@op(reads_only=True)
def orientation_reading(extents_m: tuple[float, float, float]) -> str:
    """One line naming the extents and where the middle one sits.

    The writer cannot see this today and the harness rotates the object
    by it afterwards, so the fact arrives too late to act on. Text, not
    a verdict: nothing here gates.

    The axis is chosen the same way `canonical_depth_axis_rotation_euler_rad`
    chooses its source axis — lowest index among the extents equal to the
    middle VALUE — so the reading can never name an axis the rotation
    would not have used.
    """
    extents_m = _as_extent_triple_m(extents_m)
    figures = " ".join(
        f"{AXIS_NAMES[axis]} {extents_m[axis]:.{ORIENTATION_READING_DECIMALS}f}"
        for axis in range(AXIS_COUNT)
    )
    if depth_axis_holds_middle_extent(extents_m):
        return (
            f"extents {figures} m; middle extent on "
            f"{AXIS_NAMES[DEPTH_AXIS_INDEX]} (canonical)"
        )
    middle_m = middle_extent_m(extents_m)
    middle_axis = min(axis for axis in range(AXIS_COUNT) if extents_m[axis] == middle_m)
    return (
        f"extents {figures} m; middle extent on "
        f"{AXIS_NAMES[middle_axis]}, canonical depth axis is "
        f"{AXIS_NAMES[DEPTH_AXIS_INDEX]}"
    )


def _mesh_objects(object_name: str | None):
    """The mesh objects this rule applies to, or a loud failure."""
    import bpy

    if object_name is not None:
        blender_object = bpy.data.objects.get(object_name)
        if blender_object is None:
            raise RuntimeError(f"no object named {object_name!r}")
        if blender_object.type != "MESH":
            raise RuntimeError(
                f"object {object_name!r} is {blender_object.type}, not MESH"
            )
        return [blender_object]
    meshes = [
        candidate for candidate in bpy.context.scene.objects if candidate.type == "MESH"
    ]
    if not meshes:
        raise RuntimeError("no mesh object in the scene to orient")
    return meshes


def apply_canonical_depth_axis(object_name: str | None = None) -> dict:
    """Rotate the scene's mesh so its middle extent lies on Blender Y.

    Composed ON TOP of whatever transform the writer already set — world
    pre-multiplication of `matrix_world`, so an object the writer had
    already rotated is respected and the whole scene turns rigidly about
    the world origin (the scorer centres the cloud before comparing, so
    the origin choice cannot affect the score).

    Idempotent: a second call re-measures the world extents, finds a
    middle-valued one already on Y, and composes identity.

    Data API only (`matrix_world`) — never `bpy.ops.transform.*`, which
    needs an operator context the emitted standalone script does not
    have, and never `Mesh.transform`, which would double-apply on any
    linked duplicate that shares a mesh datablock. The glTF exporter
    writes node transforms and the scorer loads with
    `trimesh.load(force="mesh")`, which concatenates with transforms
    applied, so a live object transform reaches the score intact.

    Returns the record written into `.agent_meta.json`, and asserts its
    own post-condition by re-measuring: after the turn, the depth axis
    must hold a middle-valued extent.
    """
    import bpy
    from mathutils import Euler

    # The same measurement the gate's `orient:` line and `inspect_object`
    # report (OT-34): a run that leaves more than one mesh has already
    # broken the task's own rule and is recorded by the export log's
    # `n_meshes`; refusing to orient it would only turn a scoring penalty
    # into an executability failure.
    from blended.ops.transforms import _world_extents_m

    blender_objects = _mesh_objects(object_name)
    extents_before_m = _world_extents_m(blender_objects)
    rotation_rad = canonical_depth_axis_rotation_euler_rad(*extents_before_m)
    rotation_matrix = Euler(rotation_rad, "XYZ").to_matrix().to_4x4()
    for blender_object in blender_objects:
        blender_object.matrix_world = rotation_matrix @ blender_object.matrix_world
    bpy.context.view_layer.update()
    extents_after_m = _world_extents_m(blender_objects)
    if not depth_axis_holds_middle_extent(extents_after_m):
        raise RuntimeError(
            f"depth axis does not hold the middle extent after rotating "
            f"{extents_before_m} by {rotation_rad}: extents "
            f"{extents_after_m}"
        )
    return {
        "objects": [blender_object.name for blender_object in blender_objects],
        "extents_before_m": extents_before_m,
        "extents_after_m": extents_after_m,
        "rotation_applied_rad": rotation_rad,
        "depth_axis_extent_rank": depth_axis_extent_rank(extents_after_m),
    }
