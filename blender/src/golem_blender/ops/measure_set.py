"""Measure a SET of objects as one piece: the number the LOD budget is on.

`analyze_object` measures ONE object, and every real asset is several. So
the three questions a piece actually has to answer were unanswerable from
inside golem (issue #23): how many triangles the PIECE is (Sanctuary's LOD
budget is per piece — 2 000 at LOD0, 60% at LOD1, 30% at LOD2), whether its
parts pass through each other, and whether all its parts are actually
linked. During the 22-piece run each was recomputed by a script over the
written `.glb`/`.blend`, a verification path that bypasses the gate.

Three measurements are REUSED, never re-derived, because a second copy of
a number is a second thing that can disagree with the gate:

- the per-object triangle count is `analyze_object`'s, so it is the number
  `inspect_object` prints (criterion 5). It is measured on the EVALUATED
  mesh, so a modifier's triangles are in the piece's budget.
- the joint bounds are `transforms._world_bounds_m`'s, the one place world
  extents are measured (OT-34): the same box the gate's `orient:` line and
  the writer's own `world_bounds` read, so the piece's dimensions cannot
  differ from the parts' reported extents.
- the pairwise check is `analyze.pair_checks.analyze_pair`'s. That module
  already draws the line this issue asks for: the face-pair count is
  reported only when the object-level penetration depth exceeds
  `CONTACT_DEPTH_TOLERANCE_M` (2 mm), so a lid resting on its body — the
  golden crate's lid sits ~1 mm into the rim and was human-signed-off —
  reads zero and is NOT an intersection. Coplanar faces are never reported
  at all (`BVHTree.overlap` returns an empty list for them, measured), the
  same property `ops.booleans.BooleanNoOp` exists to name. Nothing here
  invents a second coplanar test.

`unlinked` is the silent-skip case the issue was filed from: a name that
is not in the scene. That covers BOTH a name nothing was ever created for
AND an object that exists in `bpy.data.objects` but was never linked —
`add_box` returns exactly that until `link_into_scene` runs, and a piece
shipped with one, so the export missed it while every mesh measured clean.
Neither is an error: the name is REPORTED and kept out of every total.
A set where NOTHING resolves is refused, because "0 triangles, 0 parts"
passes any budget and is the same silent wrong answer.

This op is a READER (criterion 6): nothing is created, moved or assigned.
It is deliberately NOT gated — the gate measures one scene object against
a mesh budget, and a set report is not a verdict about an object.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from golem_blender.ops._contract import op

AXIS_COUNT = 3


@dataclass(frozen=True)
class SetReport:
    """A set of objects measured as one piece. Numbers, not opinions."""

    # THE FIRST NAME GIVEN, so the report is unambiguous about which piece it
    # describes and the anchor is the same string on every call. It is NOT
    # the gate's target: this op issues no verdict, so nothing measures it.
    # A caller that named an unlinked part first gets that name here and the
    # same name in `unlinked` — the two fields together say plainly that the
    # anchor is not a measured object.
    object_name: str
    # The measured parts, in the order they were asked for.
    objects: tuple[str, ...]
    triangles_total: int
    # Per measured part, from the same analyzer count `inspect_object`
    # reports. A linked non-mesh (an armature in a piece) counts 0.
    triangles_by_object: dict[str, int]
    # The UNION of the parts' world boxes, never a sum of their extents.
    dimensions_m: tuple[float, float, float]
    # The joint box's lowest point, so a piece's floor contact is measurable.
    lowest_point_m: float
    # Names that resolve to no linked object; excluded from every total.
    unlinked: tuple[str, ...]
    # DISTINCT materials, not slots: one material worn by two parts is 1.
    material_slots: int
    # Pairs that genuinely interpenetrate. Empty means "none" only when
    # `part_intersections_checked` is True.
    part_intersections: tuple[tuple[str, str], ...]
    # Whether the pairwise measurement ran: it is the expensive one, so it
    # is opt-in, and a reader of an empty `part_intersections` has to know
    # which question was actually asked.
    part_intersections_checked: bool = False


def _linked_objects_or_unlinked(names):
    """(measured objects, unlinked names) — loud on a name that is not text."""
    import bpy

    scene_objects = bpy.context.scene.objects
    measured = []
    unlinked: list[str] = []
    for name in names:
        if not isinstance(name, str):
            raise TypeError(
                f"measure_objects takes object NAMES (str), got "
                f"{type(name).__name__}: {name!r}"
            )
        blender_object = bpy.data.objects.get(name)
        # Scene membership, not `bpy.data.objects` membership: an object that
        # exists but was never linked has no depsgraph instance, no export
        # and no place in the piece — the bug this field was filed for.
        if blender_object is None or name not in scene_objects:
            unlinked.append(name)
            continue
        measured.append(blender_object)
    return measured, tuple(unlinked)


def _distinct_material_names(blender_objects) -> set[str]:
    """Every material name assigned by a slot on any of the objects."""
    names: set[str] = set()
    for blender_object in blender_objects:
        for slot in blender_object.material_slots:
            if slot.material is not None:
                names.add(slot.material.name)
    return names


def _intersecting_pairs(blender_objects) -> tuple[tuple[str, str], ...]:
    """The pairs of parts that genuinely interpenetrate, in report order.

    `analyze_pair` does the measurement: its face-pair count is suppressed
    below `CONTACT_DEPTH_TOLERANCE_M` of object-level penetration, which IS
    the touching-versus-clashing line (a part resting on another shares
    faces and sinks up to the resting tolerance by design).
    """
    from golem_blender.analyze.pair_checks import analyze_pair

    mesh_objects = [
        blender_object
        for blender_object in blender_objects
        if blender_object.type == "MESH"
    ]
    clashing: list[tuple[str, str]] = []
    for first_object, second_object in combinations(mesh_objects, 2):
        pair_report = analyze_pair(first_object, second_object)
        if pair_report.intersecting_face_pair_count > 0:
            clashing.append((first_object.name, second_object.name))
    return tuple(clashing)


@op(reads_only=True)
def measure_objects(
    object_names: list[str],
    check_part_intersections: bool = False,
) -> SetReport:
    """Measure a set of objects as one piece: triangles, joint bounds, links, materials, clashes."""

    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.ops.transforms import _world_bounds_m

    if not object_names:
        raise ValueError(
            "measure_objects needs at least one object name: a set of none "
            "measure 0 triangles and would pass any budget"
        )
    if len(set(object_names)) != len(object_names):
        duplicates = sorted(
            {name for name in object_names if object_names.count(name) > 1}
        )
        raise ValueError(
            f"measure_objects got a name more than once {duplicates}: counting "
            f"a part twice would spend the piece's budget on geometry it "
            f"does not have"
        )

    blender_objects, unlinked = _linked_objects_or_unlinked(object_names)
    if not blender_objects:
        raise ValueError(
            f"Nothing to measure: none of {list(object_names)} is a linked "
            f"scene object, so the piece has no parts. Create them, "
            f"link_into_scene them, or check the names (unlinked: {list(unlinked)})."
        )

    # `MeshBudget()` on purpose: it allows UV overlaps, which is what keeps
    # `analyze_object` from taking the 30-second pairwise UV measurement.
    # The triangle count is identical either way.
    mesh_budget = MeshBudget()
    triangles_by_object = {
        blender_object.name: (
            analyze_object(blender_object, mesh_budget).triangle_count
            if blender_object.type == "MESH"
            else 0
        )
        for blender_object in blender_objects
    }

    minimum, maximum = _world_bounds_m(blender_objects)
    dimensions_m = tuple(maximum[axis] - minimum[axis] for axis in range(AXIS_COUNT))

    return SetReport(
        object_name=object_names[0],
        objects=tuple(blender_object.name for blender_object in blender_objects),
        triangles_total=sum(triangles_by_object.values()),
        triangles_by_object=triangles_by_object,
        dimensions_m=dimensions_m,
        lowest_point_m=minimum[2],
        unlinked=unlinked,
        material_slots=len(_distinct_material_names(blender_objects)),
        part_intersections=(
            _intersecting_pairs(blender_objects) if check_part_intersections else ()
        ),
        part_intersections_checked=bool(check_part_intersections),
    )
