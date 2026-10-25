"""CSG operations via the boolean modifier, applied through the depsgraph.

The EXACT solver is the reliability default; it is slower than FAST but
does not leave the near-coplanar garbage FAST does. Every operation
consumes its operand (the cutter/addend is removed afterward) so scenes
never accumulate hidden helper objects — an invisible leftover cutter is
exactly the kind of state that made retries lie (see drift catalog).

Every CSG result must go back through the analyzer: booleans are the
single most common way a designed mesh silently goes non-manifold.
"""

from __future__ import annotations

from golem_blender.ops._objects import ObjectName

BOOLEAN_SOLVER_DEFAULT = "EXACT"


class UnlinkedOperand(RuntimeError):
    """A boolean operand is not in the scene, so the modifier cannot see it."""


class BooleanNoOp(RuntimeError):
    """A boolean completed without changing the target's mesh.

    The EXACT solver's worst case is exactly-coplanar faces: a cutter
    whose face lies in the target's face plane can be ignored entirely,
    and the modifier applies as a no-op. Measured 2026-08-22
    (iteration 33): a planter cavity whose top sat exactly coplanar
    with the box top left the target at 16 verts / 12 polys before AND
    after boolean_difference, which returned normally — and the agent
    spent 21 tool calls debugging an op that was never wrong. A
    boolean that changes nothing is a silent wrong answer, so it
    raises here, naming the counts, instead of returning.
    """


class BooleanOperandSelfIntersecting(RuntimeError):
    """A boolean operand's own mesh crosses itself, so the solver may drop the operation.

    Measured 2026-10-25 (a parapet with eight quatrefoil holes): the cutter was
    built from eight overlapping cylinders, so it intersected itself. The EXACT
    solver returned the target WITHOUT the holes — and the result still differed
    from the input, so `BooleanNoOp` stayed quiet and the gate passed a parapet
    with no holes in it. Nothing about a self-intersecting operand is worth
    handing to a solver whose behaviour on it is undefined, so it is refused
    before anything changes.
    """


class BooleanCutIncomplete(RuntimeError):
    """The difference returned a mesh that still fills the cutter's own volume.

    Measured 2026-10-25 (the same parapet): the solver reported success, the
    mesh differed from the input, and the holes were not there. The no-op check
    can only see "the target changed"; this one asks the question that matters —
    is the region the cutter and the target shared now EMPTY — and measures it
    on the evaluated result before anything is applied, so a refusal leaves both
    objects exactly as they were.
    """


def _require_linked(blender_object, role: str) -> None:
    """Refuse to start a boolean on an object the depsgraph cannot see.

    Construction and linking are separate steps in this vocabulary, so
    `add_box` hands back an object that is not in the scene yet. Measured
    2026-08-22 (iteration 8): boolean_union on two unlinked boxes
    RETURNED NORMALLY, left the target at 8 vertices — no union
    happened — and consumed the addend anyway. The agent read that as a
    broken op, wiped the scene to A/B-test it, destroyed the finished
    stool along with everything else, and ended the run with no object
    at all. A silent wrong answer cost fifteen tool calls; this raise
    costs one.
    """
    import bpy

    if blender_object.name not in bpy.context.scene.objects:
        raise UnlinkedOperand(
            f"boolean {role} {blender_object.name!r} is not linked into the "
            f"scene, so the modifier cannot evaluate it and the result "
            f"would silently be the unchanged target. Call "
            f"link_into_scene({blender_object.name!r}) after creating it, "
            f"before any boolean."
        )


def _require_clean_operand(operand_object, operation: str) -> None:
    """Refuse an operand whose own mesh intersects itself.

    Only the OPERAND is inspected: it is the piece the caller built for this one
    purpose, and a target with its own history is not this op's business. The
    count is `analyze.mesh_checks._count_self_intersecting_pairs`, which skips
    triangle pairs sharing a vertex — mesh adjacency is not a defect.
    """
    import bpy

    from golem_blender.analyze.mesh_checks import _count_self_intersecting_pairs

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = operand_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        intersecting_pair_count = _count_self_intersecting_pairs(evaluated_mesh)
    finally:
        evaluated.to_mesh_clear()
    if intersecting_pair_count > 0:
        raise BooleanOperandSelfIntersecting(
            f"boolean {operation} operand {operand_object.name!r} intersects "
            f"itself: {intersecting_pair_count} triangle pairs of it cross "
            f"each other. The EXACT solver can silently ignore a "
            f"self-intersecting operand and return the target with the cut "
            f"missing. Union its overlapping parts into one clean solid first "
            f"(boolean_union them one at a time), then retry. Nothing was "
            f"changed."
        )


def _cut_region_before(target_object, operand_object):
    """The volume a DIFFERENCE must empty, captured before the modifier exists.

    Returns `(target_tree, cutter_tree, region_minimum, region_maximum)`, or
    None when the two boxes do not overlap on every axis — no shared volume
    means no region to measure, and the no-op check already covers a cutter that
    misses entirely.
    """
    from golem_blender.analyze.interaction import _world_bvhs
    from golem_blender.ops.transforms import _world_bounds_m

    target_minimum, target_maximum = _world_bounds_m([target_object])
    cutter_minimum, cutter_maximum = _world_bounds_m([operand_object])
    region_minimum = [
        max(target_minimum[axis], cutter_minimum[axis]) for axis in range(3)
    ]
    region_maximum = [
        min(target_maximum[axis], cutter_maximum[axis]) for axis in range(3)
    ]
    if any(region_maximum[axis] <= region_minimum[axis] for axis in range(3)):
        return None
    trees = _world_bvhs([target_object, operand_object])
    target_tree = trees[target_object.name]
    cutter_tree = trees[operand_object.name]
    if target_tree is None or cutter_tree is None:
        return None
    return (
        target_tree,
        cutter_tree,
        region_minimum,
        region_maximum,
        target_minimum,
        target_maximum,
    )


def _evaluated_target_unchanged(
    target_object,
    vertex_count_before: int,
    polygon_count_before: int,
    positions_before,
) -> bool:
    """Whether the target's EVALUATED mesh still equals the mesh it had before.

    Evaluated, not applied: the modifier is still on the object, so a refusal
    that removes it restores the target exactly.
    """
    import bpy

    dependency_graph = bpy.context.evaluated_depsgraph_get()
    evaluated = target_object.evaluated_get(dependency_graph)
    evaluated_mesh = evaluated.to_mesh()
    try:
        return (
            len(evaluated_mesh.vertices) == vertex_count_before
            and len(evaluated_mesh.polygons) == polygon_count_before
            and tuple(
                tuple(round(coordinate, 6) for coordinate in vertex.co)
                for vertex in evaluated_mesh.vertices
            )
            == positions_before
        )
    finally:
        evaluated.to_mesh_clear()


def _target_survived(
    target_object,
    target_before_tree,
    cutter_tree,
    result_tree,
    target_minimum,
    target_maximum,
) -> bool:
    """False only when the result lost ALL of the material the cutter did not cover.

    A cutter that consumes the whole target is legitimate — every point of the
    target is inside it, so nothing had to survive — and then this answers True.
    A result with no geometry at all, where material SHOULD have survived, is a
    solver destroying the target, which is worse than the dropped cut this check
    was written for (measured 2026-10-25: zero polygons).
    """
    from golem_blender.analyze import csg_checks

    if result_tree is not None:
        return True
    return (
        csg_checks.measure_surviving_region(
            target_before_tree, cutter_tree, target_minimum, target_maximum
        )
        == 0
    )


def _require_the_cut_landed(
    target_object, operand_object, boolean_modifier, cut_region
) -> None:
    """Refuse a DIFFERENCE whose result still fills the cutter's own volume.

    `csg_checks.measure_cut_region` is called through the MODULE so a test can
    substitute its own measurement; the threshold and the message live here.
    """
    from golem_blender.analyze import csg_checks
    from golem_blender.analyze.interaction import _world_bvhs

    (
        target_tree_before,
        cutter_tree,
        region_minimum,
        region_maximum,
        target_minimum,
        target_maximum,
    ) = cut_region
    result_tree = _world_bvhs([target_object])[target_object.name]
    report = csg_checks.measure_cut_region(
        target_tree_before,
        cutter_tree,
        result_tree,
        region_minimum,
        region_maximum,
    )
    if not _target_survived(
        target_object,
        target_tree_before,
        cutter_tree,
        result_tree,
        target_minimum,
        target_maximum,
    ):
        target_object.modifiers.remove(boolean_modifier)
        raise BooleanCutIncomplete(
            f"boolean DIFFERENCE destroyed {target_object.name!r}: the result "
            f"has no geometry left, and material outside cutter "
            f"{operand_object.name!r} was expected to survive. An empty mesh is "
            f"not a cut, and it is not a no-op either — it differs from the "
            f"input, so nothing else here would have caught it. Nothing was "
            f"changed: make the cutter a closed solid that overlaps the target "
            f"without swallowing it, then retry."
        )
    if report.probed_point_count == 0:
        return
    if report.remaining_fraction <= csg_checks.CUT_REMAINING_FRACTION_LIMIT:
        return
    target_object.modifiers.remove(boolean_modifier)
    raise BooleanCutIncomplete(
        f"boolean DIFFERENCE left material inside cutter "
        f"{operand_object.name!r}: {report.remaining_point_count} of "
        f"{report.probed_point_count} probe points inside both the cutter and "
        f"{target_object.name!r} are still solid after the cut "
        f"({report.remaining_fraction:.0%}). The solver returned a result "
        f"without the cut. Nothing was changed: make the cutter one closed "
        f"solid that overlaps the target, then retry."
    )


def _apply_boolean(
    target_name: str,
    operand_name: str,
    operation: str,
    solver: str = BOOLEAN_SOLVER_DEFAULT,
) -> None:
    import bpy

    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.modifiers import apply_all_modifiers
    from golem_blender.ops.primitives import remove_object_and_mesh

    target_object = object_by_name(target_name, "MESH")
    operand_object = object_by_name(operand_name, "MESH")

    # Checked BEFORE anything mutates: a boolean that fails halfway has
    # already eaten its operand.
    _require_linked(target_object, "target")
    _require_linked(operand_object, "operand")
    vertex_count_before = len(target_object.data.vertices)
    polygon_count_before = len(target_object.data.polygons)
    # Counts are not enough: the EXACT solver can cut a tilted cap flat
    # while preserving the vertex and polygon counts exactly (measured
    # 2026-08-22, trim_soles_flat on a splayed leg: 136 verts / 76 polys
    # before and after, with the z range changing -0.0269 -> 0.0000).
    # So the no-op check compares POSITIONS too: a boolean that changed
    # nothing leaves every vertex where it was.
    positions_before = tuple(
        tuple(round(coordinate, 6) for coordinate in vertex.co)
        for vertex in target_object.data.vertices
    )

    # The OPERAND's own shape, before it reaches a solver whose behaviour on a
    # self-intersecting input is undefined. Nothing has been mutated yet, so a
    # refusal here costs one tool call instead of a silently uncut asset.
    _require_clean_operand(operand_object, operation)

    # A DIFFERENCE is also measured for WHETHER IT CUT. Both trees are taken
    # now, before the modifier exists: the target's is the volume the cutter is
    # meant to empty, and the cutter's is the volume it is meant to pass through.
    cut_region = None
    if operation == "DIFFERENCE":
        cut_region = _cut_region_before(target_object, operand_object)

    boolean_modifier = target_object.modifiers.new(
        name=f"Boolean_{operation}", type="BOOLEAN"
    )
    boolean_modifier.operation = operation
    boolean_modifier.object = operand_object
    boolean_modifier.solver = solver
    bpy.context.view_layer.update()

    # Both remaining checks read the EVALUATED result, so a refusal removes the
    # modifier and leaves the target's mesh and the operand untouched.
    if _evaluated_target_unchanged(
        target_object, vertex_count_before, polygon_count_before, positions_before
    ):
        target_object.modifiers.remove(boolean_modifier)
        raise BooleanNoOp(
            f"boolean {operation} left {target_object.name} unchanged "
            f"({vertex_count_before} verts / {polygon_count_before} polys "
            f"before and after). The EXACT solver ignores exactly-coplanar "
            f"faces — make the cutter overlap the target instead of "
            f"sharing a face plane, then retry."
        )
    if cut_region is not None:
        _require_the_cut_landed(
            target_object, operand_object, boolean_modifier, cut_region
        )
    apply_all_modifiers(target_name)
    remove_object_and_mesh(operand_name)

    from golem_blender.ops.heal import weld_and_dissolve

    weld_and_dissolve(target_name)


def boolean_difference(
    target_name: str, cutter_name: str, solver: str = BOOLEAN_SOLVER_DEFAULT
) -> ObjectName:
    """Subtract the named cutter from the named target; the cutter is consumed."""
    _apply_boolean(target_name, cutter_name, "DIFFERENCE", solver)
    return ObjectName(target_name)


def boolean_union(
    target_name: str, addend_name: str, solver: str = BOOLEAN_SOLVER_DEFAULT
) -> ObjectName:
    """Merge the named addend into the named target as one solid; the addend is consumed."""
    _apply_boolean(target_name, addend_name, "UNION", solver)
    return ObjectName(target_name)


def boolean_intersect(
    target_name: str, operand_name: str, solver: str = BOOLEAN_SOLVER_DEFAULT
) -> ObjectName:
    """Keep only the overlap of the two named solids; the operand is consumed."""
    _apply_boolean(target_name, operand_name, "INTERSECT", solver)
    return ObjectName(target_name)
