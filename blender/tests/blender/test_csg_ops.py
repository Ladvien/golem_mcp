"""CSG ops: every boolean result must survive the analyzer gate."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

BOX_SIZE_M = 1.0
HOLE_RADIUS_M = 0.2
# Cutter must overshoot both faces or the difference leaves coplanar caps.
CUTTER_OVERSHOOT_FACTOR = 1.5


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _bored_box():
    from blended.ops import add_box, add_cylinder, boolean_difference, link_into_scene

    box_object = add_box("BoredBox", BOX_SIZE_M, BOX_SIZE_M, BOX_SIZE_M)
    link_into_scene(box_object)
    cutter_height_m = BOX_SIZE_M * CUTTER_OVERSHOOT_FACTOR
    cutter_object = add_cylinder(
        "HoleCutter",
        radius_m=HOLE_RADIUS_M,
        height_m=cutter_height_m,
        location_m=(0.0, 0.0, -(cutter_height_m - BOX_SIZE_M) / 2.0),
    )
    link_into_scene(cutter_object)
    return boolean_difference(box_object, cutter_object)


def test_difference_bores_a_clean_hole(empty_scene):
    from blended.analyze import MeshBudget, analyze_object

    bored_box = _bored_box()
    report = analyze_object(bpy.data.objects[bored_box])
    failures = report.failures(MeshBudget())
    assert failures == [], f"analyzer failures: {failures}; report={report}"
    # The hole is real geometry: more triangles than the plain box.
    assert report.triangle_count > 12


def test_difference_consumes_the_cutter(empty_scene):
    _bored_box()
    assert "HoleCutter" not in bpy.data.objects


def test_non_intersecting_cutter_raises_instead_of_silently_no_oping(empty_scene):
    """A cutter that does not touch the target applies as a silent
    no-op: the modifier evaluates, nothing intersects, and the mesh
    comes back unchanged. Measured 2026-08-22 (iteration 33): the
    agent's planter cavity sat 0.01 m short of the box top, the boolean
    returned normally, and the agent spent 21 tool calls debugging an
    op that was never wrong — the gate had already caught the real
    defect (2 disconnected components). A boolean that changes nothing
    must raise, naming the counts, and must leave the target intact —
    the operand is only consumed on a real result."""
    from blended.ops import add_box, boolean_difference, link_into_scene
    from blended.ops.booleans import BooleanNoOp

    box_object = add_box("NoOpBox", 1.0, 1.0, 1.0)
    link_into_scene(box_object)
    # Entirely outside the target: no intersection, no change.
    outside_cutter = add_box("OutsideCutter", 0.5, 0.5, 0.5, location_m=(5.0, 0.0, 0.0))
    link_into_scene(outside_cutter)

    with pytest.raises(BooleanNoOp):
        boolean_difference(box_object, outside_cutter)

    # The refusal must not have eaten the operand or damaged the target.
    assert "OutsideCutter" in bpy.data.objects
    assert len(bpy.data.objects[box_object].data.vertices) == 8


def test_snap_base_to_ground(empty_scene):
    from blended.ops import add_box, link_into_scene, snap_base_to_ground

    GROUND_TOLERANCE_M = 1.0e-6
    floating_box = add_box("Floater", 1.0, 1.0, 1.0, location_m=(0.0, 0.0, 3.0))
    link_into_scene(floating_box)
    snap_base_to_ground(floating_box)
    bpy.context.view_layer.update()
    from mathutils import Vector

    floating_obj = bpy.data.objects[floating_box]
    lowest_z_m = min(
        (floating_obj.matrix_world @ Vector(corner)).z
        for corner in floating_obj.bound_box
    )
    assert abs(lowest_z_m) < GROUND_TOLERANCE_M


def test_transform_ops_see_pending_location_and_rotation(empty_scene):
    """matrix_world is lazily evaluated: transform ops must refresh the
    depsgraph or they silently bake nothing."""
    from blended.ops import add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform

    leg = add_cylinder("PendingLeg", radius_m=0.02, height_m=0.4)
    link_into_scene(leg)
    leg_obj = bpy.data.objects[leg]
    leg_obj.rotation_euler = (0.0, -0.3, 1.0)
    leg_obj.location = (0.2, 0.1, 0.0)

    vertex_before = tuple(leg_obj.data.vertices[0].co)
    apply_object_transform(leg)
    vertex_after = tuple(leg_obj.data.vertices[0].co)
    assert vertex_before != vertex_after, (
        "apply_object_transform baked nothing — matrix_world was stale"
    )
