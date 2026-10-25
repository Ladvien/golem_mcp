"""A boolean must not drop its cut, and must not eat its operand finding out.

Measured need, 2026-10-25 (a parapet with eight quatrefoil holes): the cutter was
built from eight overlapping cylinders, so its mesh intersected itself. The EXACT
solver returned the target WITHOUT the holes, and the result still differed from
the input, so `BooleanNoOp` stayed quiet. Two checks close that:

- the OPERAND is inspected for self-intersection before anything changes
  (`BooleanOperandSelfIntersecting`);
- a DIFFERENCE's result is measured for whether the region the cutter and the
  target shared is now EMPTY (`BooleanCutIncomplete`), on the EVALUATED result,
  so a refusal leaves the target's mesh and the operand exactly as they were.

Both refusals are checked for what they leave behind, not only for the message:
a raise that already ate the cutter is the failure this exists to prevent.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TOLERANCE_M = 1.0e-4


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _linked_mesh_object(name, build):
    """One linked mesh object whose geometry `build(bmesh)` creates."""
    import bmesh

    mesh = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        build(working_mesh)
        working_mesh.to_mesh(mesh)
    finally:
        working_mesh.free()
    blender_object = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(blender_object)
    return blender_object


def _lobe(centre_x_m, radius_m=0.15, depth_m=1.0):
    """A cylinder with its axis along Y, so a difference bores through the prism."""

    def build(working_mesh):
        import bmesh
        from mathutils import Matrix, Vector

        bmesh.ops.create_cone(
            working_mesh,
            cap_ends=True,
            segments=16,
            radius1=radius_m,
            radius2=radius_m,
            depth=depth_m,
            matrix=Matrix.Translation(Vector((0.0, 0.0, 0.0)))
            @ Matrix.Rotation(1.5707963267948966, 4, "X"),
        )
        bmesh.ops.translate(
            working_mesh, verts=working_mesh.verts, vec=(centre_x_m, 0.0, 0.5)
        )

    return build


def _prism():
    from golem_blender.ops import add_box, link_into_scene

    prism_name = add_box("Prism", 2.0, 0.4, 1.0)
    link_into_scene(prism_name)
    return prism_name


# --- the operand's own shape ---------------------------------------------------


def test_a_self_intersecting_cutter_is_refused_and_changes_nothing(empty_scene):
    """The measured parapet: two overlapping lobes as ONE mesh."""
    from golem_blender.ops import BooleanOperandSelfIntersecting, boolean_difference

    _prism()

    def build(working_mesh):
        import bmesh
        from mathutils import Matrix, Vector

        for centre_x_m in (-0.08, 0.08):
            bmesh.ops.create_cone(
                working_mesh,
                cap_ends=True,
                segments=16,
                radius1=0.15,
                radius2=0.15,
                depth=1.0,
                matrix=Matrix.Translation(Vector((centre_x_m, 0.0, 0.5)))
                @ Matrix.Rotation(1.5707963267948966, 4, "X"),
            )

    _linked_mesh_object("Lobes", build)

    with pytest.raises(BooleanOperandSelfIntersecting, match="intersects itself"):
        boolean_difference("Prism", "Lobes")

    prism = bpy.data.objects["Prism"]
    assert len(prism.data.vertices) == 8
    assert len(prism.modifiers) == 0
    # The operand is still there: a refusal that consumed it would be the same
    # class of loss the check exists to prevent.
    assert "Lobes" in bpy.data.objects


def test_a_unioned_cutter_cuts_a_hole(empty_scene):
    """Two separate lobes, unioned first, are one clean solid and DO cut."""
    from golem_blender.ops import boolean_difference, boolean_union, measure_feature

    _prism()
    _linked_mesh_object("LobeLeft", _lobe(-0.08))
    _linked_mesh_object("LobeRight", _lobe(0.08))
    boolean_union("LobeLeft", "LobeRight")
    boolean_difference("Prism", "LobeLeft")

    feature_report = measure_feature("Prism", "opening")
    front = next(side for side in feature_report.sides if side.side == "front")
    assert front.through_fraction > 0.0


# --- whether the cut landed ----------------------------------------------------


def _bored_box_trees():
    """A box, the cylinder that bores it, and both results — as world BVHs."""
    from golem_blender.analyze.interaction import _world_bvhs
    from golem_blender.ops import add_box, add_cylinder, link_into_scene
    from golem_blender.ops.transforms import _world_bounds_m

    box_name = add_box("BoredBox", 1.0, 1.0, 1.0)
    link_into_scene(box_name)
    cutter_height_m = 1.0 * 1.5
    cutter_name = add_cylinder(
        "HoleCutter",
        radius_m=0.2,
        height_m=cutter_height_m,
        location_m=(0.0, 0.0, -(cutter_height_m - 1.0) / 2.0),
    )
    link_into_scene(cutter_name)

    box_object = bpy.data.objects[box_name]
    cutter_object = bpy.data.objects[cutter_name]
    trees = _world_bvhs([box_object, cutter_object])
    box_minimum, box_maximum = _world_bounds_m([box_object])
    cutter_minimum, cutter_maximum = _world_bounds_m([cutter_object])
    region_minimum = [max(box_minimum[axis], cutter_minimum[axis]) for axis in range(3)]
    region_maximum = [min(box_maximum[axis], cutter_maximum[axis]) for axis in range(3)]
    return (
        box_name,
        cutter_name,
        trees[box_name],
        trees[cutter_name],
        region_minimum,
        region_maximum,
    )


def test_the_cut_check_reads_a_missing_cut_as_all_remaining(empty_scene):
    from golem_blender.analyze.csg_checks import measure_cut_region

    (
        _box_name,
        _cutter_name,
        box_tree,
        cutter_tree,
        region_minimum,
        region_maximum,
    ) = _bored_box_trees()

    # A solver that returned the target: the result tree IS the before tree.
    report = measure_cut_region(
        box_tree, cutter_tree, box_tree, region_minimum, region_maximum
    )

    assert report.probed_point_count > 0
    assert report.remaining_point_count == report.probed_point_count
    assert report.remaining_fraction == 1.0


def test_the_cut_check_reads_a_real_cut_as_empty(empty_scene):
    from golem_blender.analyze.csg_checks import measure_cut_region
    from golem_blender.analyze.interaction import _world_bvhs
    from golem_blender.ops import boolean_difference

    (
        box_name,
        cutter_name,
        box_tree,
        cutter_tree,
        region_minimum,
        region_maximum,
    ) = _bored_box_trees()
    boolean_difference(box_name, cutter_name)
    result_tree = _world_bvhs([bpy.data.objects[box_name]])[box_name]

    report = measure_cut_region(
        box_tree, cutter_tree, result_tree, region_minimum, region_maximum
    )

    assert report.probed_point_count > 0
    assert report.remaining_point_count == 0


def test_a_cut_that_left_material_is_refused_and_changes_nothing(
    empty_scene, monkeypatch
):
    """The silent-drop path, forced: the measurement says nothing was removed."""
    from golem_blender.analyze import csg_checks
    from golem_blender.ops import (
        BooleanCutIncomplete,
        add_box,
        boolean_difference,
        link_into_scene,
    )

    box_name = add_box("Target", 1.0, 1.0, 1.0)
    link_into_scene(box_name)
    cutter_name = add_box("Cutter", 0.4, 0.4, 0.4, (0.2, 0.2, 0.2))
    link_into_scene(cutter_name)

    monkeypatch.setattr(
        csg_checks,
        "measure_cut_region",
        lambda *arguments: csg_checks.CutRegionReport(
            probed_point_count=100, remaining_point_count=100
        ),
    )

    with pytest.raises(BooleanCutIncomplete, match="100 of 100"):
        boolean_difference("Target", "Cutter")

    target = bpy.data.objects["Target"]
    assert len(target.data.vertices) == 8
    assert len(target.modifiers) == 0
    assert "Cutter" in bpy.data.objects


def test_a_result_with_no_geometry_is_refused_not_accepted(empty_scene):
    """The measured 2026-10-25 case: the solver returned a ZERO-polygon target.

    Found by the throwaway parapet reproduction with the operand guard patched
    out: EXACT annihilated the parapet. An empty mesh is neither a no-op (it did
    change) nor a cut, so only a check that asks "did anything that had to
    survive survive" can catch it — and a cutter that genuinely swallows the
    whole target must still be allowed.
    """
    from golem_blender.analyze import csg_checks
    from golem_blender.ops import (
        BooleanCutIncomplete,
        add_box,
        boolean_difference,
        link_into_scene,
    )

    box_name = add_box("Target", 1.0, 1.0, 1.0)
    link_into_scene(box_name)
    cutter_name = add_box("Cutter", 0.4, 0.4, 0.4, (0.2, 0.2, 0.2))
    link_into_scene(cutter_name)

    # An empty result, with material outside the cutter that should have lived.
    monkeypatch_result = csg_checks.measure_cut_region
    try:
        csg_checks.measure_cut_region = lambda *arguments: csg_checks.CutRegionReport(
            probed_point_count=100, remaining_point_count=100
        )
        from golem_blender.analyze import interaction

        real_world_bvhs = interaction._world_bvhs

        def empty_result_trees(blender_objects):
            trees = real_world_bvhs(blender_objects)
            for blender_object in blender_objects:
                if blender_object.name == "Target" and blender_object.modifiers:
                    trees[blender_object.name] = None
            return trees

        interaction._world_bvhs = empty_result_trees
        with pytest.raises(BooleanCutIncomplete, match="destroyed 'Target'"):
            boolean_difference("Target", "Cutter")
    finally:
        csg_checks.measure_cut_region = monkeypatch_result
        interaction._world_bvhs = real_world_bvhs

    target = bpy.data.objects["Target"]
    assert len(target.data.vertices) == 8
    assert len(target.modifiers) == 0
    assert "Cutter" in bpy.data.objects
