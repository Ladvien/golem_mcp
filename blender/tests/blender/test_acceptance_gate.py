"""The acceptance gate must be able to FAIL.

Project rule 9: every validator ships with a seeded-defect test that
trips it. The acceptance gate is what decides whether a convergence
iteration passed, so a check here that cannot fail would silently
certify every prompt revision as converged.

Each test builds the defect deliberately, then asserts that exactly the
intended check trips — not merely that something failed.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


# Where the blind recess bottoms out, as a fraction of floor thickness.
# It must sit BELOW the parity probe point (floor thickness / 2) or the
# fixture stops reproducing the iteration-1 failure: the probe would land
# in solid material and the old spec would catch the defect by accident.
BLIND_RECESS_FLOOR_FRACTION = 0.25


def _assign_material(object_name, material_name="TestMaterial"):
    material = bpy.data.materials.new(material_name)
    bpy.data.objects[object_name].data.materials.append(material)


def _build_planter(
    *,
    hollow: bool = True,
    drain_hole: bool = True,
    with_material: bool = True,
    width_scale: float = 1.0,
    leave_stray_cutter: bool = False,
    drain_is_blind_recess: bool = False,
):
    """Build the planter the brief describes, with optional seeded defects."""
    from blended.evaluate import briefs
    from blended.ops.booleans import boolean_difference
    from blended.ops.primitives import add_box, add_cylinder, link_into_scene
    from blended.ops.transforms import snap_base_to_ground

    wall = briefs.PLANTER_WALL_THICKNESS_M
    body = add_box(
        "PlanterBox",
        width_m=briefs.PLANTER_WIDTH_X_M * width_scale,
        depth_m=briefs.PLANTER_DEPTH_Y_M,
        height_m=briefs.PLANTER_HEIGHT_Z_M,
    )
    link_into_scene(body)
    snap_base_to_ground(body)

    if hollow:
        # Cavity: open at the top, so it rises above the rim.
        cavity_height = briefs.PLANTER_HEIGHT_Z_M
        cavity = add_box(
            "Cavity",
            width_m=briefs.PLANTER_WIDTH_X_M * width_scale - 2 * wall,
            depth_m=briefs.PLANTER_DEPTH_Y_M - 2 * wall,
            height_m=cavity_height,
            location_m=(0.0, 0.0, wall + cavity_height / 2.0),
        )
        link_into_scene(cavity)
        boolean_difference(body, cavity)

    if drain_hole:
        # A cutter spanning well past both faces of the floor: a real
        # through-hole. `drain_is_blind_recess` instead stops the cutter
        # inside the floor, leaving the bottom sealed.
        cutter_base_z_m = (
            wall * BLIND_RECESS_FLOOR_FRACTION
            if drain_is_blind_recess
            else -briefs.PLANTER_HEIGHT_Z_M
        )
        cutter_height_m = (
            briefs.PLANTER_HEIGHT_Z_M
            if drain_is_blind_recess
            else briefs.PLANTER_HEIGHT_Z_M * 2.0
        )
        drain = add_cylinder(
            "Drain",
            radius_m=briefs.PLANTER_DRAIN_HOLE_RADIUS_M,
            height_m=cutter_height_m,
            location_m=(0.0, 0.0, cutter_base_z_m),
        )
        link_into_scene(drain)
        boolean_difference(body, drain)

    if leave_stray_cutter:
        link_into_scene(add_cylinder("LeftoverCutter", radius_m=0.01, height_m=0.01))

    if with_material:
        _assign_material(body)
    bpy.context.view_layer.update()
    return body


def _failure_names(report, brief):
    """The set of spec names that tripped, for exact-cause assertions."""
    tripped = set()
    for measurement in report.dimensions:
        if not measurement.ok:
            tripped.add(measurement.spec.name)
    for measurement in report.probes:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    for measurement in report.clear_axes:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    for measurement in report.ground_contacts:
        if not measurement.ok:
            tripped.add(measurement.probe.name)
    return tripped


def test_correct_planter_passes_every_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter()
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)


def test_sealed_drain_hole_trips_the_drain_checks_and_nothing_else(empty_scene):
    """The canonical wrong-object failure: hollow, but no drainage.

    A hole that was never cut fails BOTH drain checks — there is no
    material missing at the probe point and no line of sight through
    the floor. Nothing else may trip: the box is otherwise correct.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(drain_hole=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert _failure_names(report, brief) == {
        "drain_hole_is_open",
        "drain_hole_goes_all_the_way_through",
    }


def test_solid_block_trips_the_hollow_probe(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(hollow=False, drain_hole=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert "interior_is_hollow" in _failure_names(report, brief)
    assert "drain_hole_is_open" in _failure_names(report, brief)


def test_wrong_width_trips_the_dimension_spec(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(width_scale=1.5)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert "width_x" in _failure_names(report, brief)
    width = next(m for m in report.dimensions if m.spec.name == "width_x")
    assert width.delta_m > 0, width.describe()


def test_missing_material_trips_the_material_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(with_material=False)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert any("no material" in failure for failure in report.failures(brief))


def test_stray_cutter_trips_the_stray_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(leave_stray_cutter=True)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert report.stray_object_names == ("LeftoverCutter",)


def test_missing_object_reports_not_found(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    report = evaluate_brief(brief)

    assert not report.object_found
    assert not report.passes(brief)
    assert "PlanterBox" in report.failures(brief)[0]


def test_ungrounded_object_trips_the_grounding_check(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    body = _build_planter()
    bpy.data.objects[body].location.z += 0.5
    bpy.context.view_layer.update()
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    assert any("not on the ground" in failure for failure in report.failures(brief))


def test_unlinked_object_reports_a_measurement_not_a_crash(empty_scene):
    """Construction and linking are separate ops; forgetting the second
    one leaves an object that exists, has no evaluated mesh, and shows
    nothing in the viewport. Probing it used to raise."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.ops.primitives import add_box

    brief = get_brief("planter_box")
    add_box("PlanterBox", width_m=0.3, depth_m=0.2, height_m=0.25)
    report = evaluate_brief(brief)

    assert report.object_found
    assert not report.linked_into_scene
    assert not report.passes(brief)
    assert "not linked into the scene" in report.failures(brief)[0]


# --- The stool brief must be SATISFIABLE ------------------------------
# A convergence loop against an impossible acceptance spec burns its
# whole iteration budget and blames the prompt. So the spec is proven
# reachable by a reference build before any agent is asked to hit it.
# This build is also the assembly-level regression fixture.


# The sole-clearance margin and cutter depth now live with the
# arithmetic they belong to, in blended.ops.legs. They are not
# redeclared here: two copies is how the fixture and the agent came to
# disagree in the first place.


def _build_reference_stool(*, angled_feet: bool = False, leg_angles_deg=None):
    """A stool that satisfies THREE_LEG_STOOL_BRIEF, built from the
    whitelisted ops only.

    The correct path is `blended.ops.legs`, which owns the placement
    arithmetic. This fixture deliberately does NOT recompute it: the
    sole-inboard trap was measured twice (this fixture, then the agent
    at iteration 17), and a second copy of the numbers is how a fix
    lands in one of them and not the other.

    `angled_feet=True` seeds the iteration-4 defect and therefore does
    not use the op: the legs are naive tilted cylinders whose end caps
    are tilted too, and the stool is dropped onto z=0 by its lowest
    POINT. Grounding passes; the stool rocks on three edges. It is a
    test input, not a second way to build a stool.
    """

    from blended.evaluate import briefs
    from blended.ops.booleans import boolean_union
    from blended.ops.legs import SplayedLegSpec, add_splayed_leg, trim_soles_flat
    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform, snap_base_to_ground

    seat_radius_m = briefs.STOOL_SEAT_DIAMETER_M / 2.0
    leg_radius_m = 0.022
    leg_top_radius_m = seat_radius_m * 0.45
    rise_m = briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M

    seat = add_cylinder(
        "Stool",
        radius_m=seat_radius_m,
        height_m=briefs.STOOL_SEAT_THICKNESS_M,
        segment_count=24,
        location_m=(0.0, 0.0, rise_m),
    )
    link_into_scene(seat)

    placements_deg = leg_angles_deg or [
        360.0 / briefs.STOOL_LEG_COUNT * index
        for index in range(briefs.STOOL_LEG_COUNT)
    ]
    for leg_index, placement_deg in enumerate(placements_deg):
        if angled_feet:
            leg = _add_naive_tilted_leg(
                f"Leg{leg_index}",
                placement_deg=placement_deg,
                foot_radius_m=briefs.STOOL_FOOT_CIRCLE_RADIUS_M,
                top_radius_m=leg_top_radius_m,
                rise_m=rise_m,
                leg_radius_m=leg_radius_m,
            )
        else:
            leg = add_splayed_leg(
                f"Leg{leg_index}",
                SplayedLegSpec(
                    foot_radius_m=briefs.STOOL_FOOT_CIRCLE_RADIUS_M,
                    foot_bearing_deg=placement_deg,
                    top_radius_m=leg_top_radius_m,
                    top_z_m=rise_m,
                    leg_radius_m=leg_radius_m,
                ),
            )
        boolean_union(seat, leg)

    if not angled_feet:
        # Turns each tilted cap into a face to stand on. BEFORE
        # snapping, not after — snapping leaves nothing below z=0.
        trim_soles_flat(seat, span_m=briefs.STOOL_SEAT_DIAMETER_M)
    snap_base_to_ground(seat)
    apply_object_transform(seat)
    _assign_material(seat, "Wood")
    bpy.context.view_layer.update()
    return seat


def _add_naive_tilted_leg(
    name: str,
    *,
    placement_deg: float,
    foot_radius_m: float,
    top_radius_m: float,
    rise_m: float,
    leg_radius_m: float,
):
    """The WRONG construction, kept as a test input.

    Stands the leg's base centre on the foot circle with no drop, so
    the tilted end cap straddles z=0. Nothing here may be reused: this
    is the shape the gate has to keep rejecting.
    """
    import math

    from mathutils import Euler

    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform

    angle_rad = math.radians(placement_deg)
    run_m = foot_radius_m - top_radius_m
    splay_rad = math.atan2(run_m, rise_m)
    leg = add_cylinder(
        name,
        radius_m=leg_radius_m,
        height_m=math.hypot(rise_m, run_m),
        segment_count=12,
    )
    link_into_scene(leg)
    leg_obj = bpy.data.objects[leg]
    leg_obj.rotation_euler = Euler(
        (splay_rad * math.sin(angle_rad), -splay_rad * math.cos(angle_rad), 0.0),
        "XYZ",
    )
    leg_obj.location = (
        foot_radius_m * math.cos(angle_rad),
        foot_radius_m * math.sin(angle_rad),
        0.0,
    )
    apply_object_transform(leg)
    return leg


def test_stool_brief_is_satisfiable(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)
    assert report.passes(brief), report.summary(brief)


def test_stool_reference_passes_the_structural_gate(empty_scene):
    from blended.analyze import analyze_object
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    stool = _build_reference_stool()
    report = analyze_object(bpy.data.objects[stool])
    assert report.passes(brief.budget), report.failures(brief.budget)


def test_legs_collapsed_to_the_axis_trips_no_central_post(empty_scene):
    """The measured historical failure (stale matrix_world): every leg
    ends up at the origin as one central post."""
    from blended.evaluate import briefs
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.ops.booleans import boolean_union
    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import snap_base_to_ground

    brief = get_brief("three_leg_stool")
    rise_m = briefs.STOOL_TOTAL_HEIGHT_Z_M - briefs.STOOL_SEAT_THICKNESS_M
    seat = add_cylinder(
        "Stool",
        radius_m=briefs.STOOL_SEAT_DIAMETER_M / 2.0,
        height_m=briefs.STOOL_SEAT_THICKNESS_M,
        segment_count=24,
        location_m=(0.0, 0.0, rise_m),
    )
    link_into_scene(seat)
    post = add_cylinder("Post", radius_m=0.022, height_m=rise_m)
    link_into_scene(post)
    boolean_union(seat, post)
    snap_base_to_ground(seat)
    _assign_material(seat, "Wood")
    bpy.context.view_layer.update()

    report = evaluate_brief(brief)
    tripped = _failure_names(report, brief)
    assert "no_central_post" in tripped
    assert {
        f"leg_{index}_foot_is_solid" for index in range(briefs.STOOL_LEG_COUNT)
    } <= tripped


def test_blind_recess_trips_the_clear_axis_probe(empty_scene):
    """The failure that slipped through iteration 1.

    A drain cut from the cavity DOWN into the floor but not out the
    bottom is sealed, yet every parity probe reads exactly as it does on
    a correct planter: the point inside the recess still has open air
    above it all the way out of the open top. Only a full-axis line of
    sight distinguishes the two.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter(drain_is_blind_recess=True)
    report = evaluate_brief(brief)

    # The old spec is fooled — this is the point of the test.
    assert all(measurement.ok for measurement in report.probes), (
        "parity probes should NOT be able to see this defect; if they can, "
        "the fixture no longer reproduces the iteration-1 failure"
    )
    # The new spec is not.
    assert not report.passes(brief)
    blocked = [m for m in report.clear_axes if not m.ok]
    assert [m.probe.name for m in blocked] == ["drain_hole_goes_all_the_way_through"]
    assert blocked[0].blocked_at_m is not None


def test_correct_planter_has_a_clear_drain_axis(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("planter_box")
    _build_planter()
    report = evaluate_brief(brief)
    assert all(measurement.ok for measurement in report.clear_axes), report.summary(
        brief
    )


def test_angled_sole_trips_the_ground_contact_probe(empty_scene):
    """The failure that slipped through iteration 4.

    Legs splayed 11.3 deg from vertical end in tilted caps. Dropped onto
    the floor by their lowest point, `base_z` reads exactly 0.0000 and
    every parity probe reads exactly as it does on a flat-footed stool —
    the stool touches along three edges and rocks. Contact is an area,
    and only measuring it as one tells the two apart.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(angled_feet=True)
    report = evaluate_brief(brief)

    # Everything the gate measured BEFORE this probe existed is fooled —
    # if any of it trips, the fixture has stopped reproducing iteration 4.
    assert abs(report.base_z_m) <= brief.grounding_tolerance_m, (
        f"base_z {report.base_z_m:+.4f} should still pass grounding; the "
        f"fixture no longer reproduces the iteration-4 failure"
    )
    assert all(measurement.ok for measurement in report.probes), (
        "parity probes should NOT be able to see an angled sole"
    )
    assert all(measurement.ok for measurement in report.dimensions), (
        "dimensions should NOT be able to see an angled sole"
    )

    # The new probe is not fooled, and it names every foot.
    assert not report.passes(brief)
    tripped = _failure_names(report, brief)
    assert tripped == {
        f"leg_{index}_sole_is_flat_on_the_ground" for index in range(3)
    }, tripped


def test_angled_sole_is_reported_as_a_tilt_not_a_missing_leg(empty_scene):
    """Zero contact area has two causes and they need different repairs.

    An angled sole must say so — naming the faces it rejected and how
    far out of plane they were — rather than reading as "no leg here".
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(angled_feet=True)
    report = evaluate_brief(brief)

    failed = [m for m in report.ground_contacts if not m.ok]
    assert len(failed) == 3
    for measurement in failed:
        assert measurement.rejected_face_count > 0, measurement.describe()
        assert (
            measurement.worst_rejected_span_m > measurement.probe.planarity_tolerance_m
        ), measurement.describe()
        assert "NOT level" in measurement.describe()


def test_flat_soles_measure_real_contact_area(empty_scene):
    """The correct build does not merely pass — it puts a measurable
    face on the floor at each foot."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)

    assert len(report.ground_contacts) == 3
    for measurement in report.ground_contacts:
        assert measurement.ok, measurement.describe()
        assert measurement.contact_area_m2 >= measurement.probe.minimum_area_m2


# Gaps of 105, 120 and 135 degrees instead of three of 120: plainly
# uneven, while every foot stays inside the probe's search radius. A leg
# more than about 29 degrees off is simply not found there, and the
# CONTACT check reports that — a different failure. This fixture targets
# the placement check specifically, so both misplaced legs must still be
# located.
UNEVENLY_SPACED_LEG_ANGLES_DEG = (0.0, 105.0, 225.0)


def test_uneven_leg_spacing_trips_the_placement_check(empty_scene):
    """The question the render cannot answer.

    Measured 2026-08-22 (iteration 10): the contact sheet's front
    orthographic view projects the 120 and 240 degree legs to the SAME
    world x, so they overlap into what reads as one leg. The human
    answered "Unclear" to whether the legs were evenly spaced and was
    right to — the view does not contain the information. It is a
    measurement, so it is measured.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool(leg_angles_deg=UNEVENLY_SPACED_LEG_ANGLES_DEG)
    report = evaluate_brief(brief)

    assert not report.passes(brief)
    off = [m for m in report.ground_contacts if not m.angle_ok]
    assert off, [m.describe() for m in report.ground_contacts]
    for measurement in off:
        # Real contact, in the wrong place — not a missing foot.
        assert measurement.has_contact, measurement.describe()
        assert abs(measurement.angle_error_deg) > (
            measurement.probe.angle_tolerance_deg
        )
        assert "not evenly spaced" in measurement.describe()


def test_correct_spacing_measures_the_specified_bearings(empty_scene):
    """The correct build reports the brief's own angles back."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    report = evaluate_brief(brief)

    bearings = sorted(round(m.measured_angle_deg) for m in report.ground_contacts)
    assert bearings == [0, 120, 240], [m.describe() for m in report.ground_contacts]
    for measurement in report.ground_contacts:
        assert measurement.radius_ok, measurement.describe()
        assert measurement.angle_ok, measurement.describe()


# What a rebuild-instead-of-edit looks like in measurements: the stool
# comes back at the requested height and satisfies the brief in every
# way, but its legs landed somewhere else. 24 degrees is a rebuild that
# simply started its leg loop at a different offset.
REBUILT_LEG_ANGLES_DEG = (24.0, 144.0, 264.0)


def _refined_outcome(before_report, brief, *, rebuild: bool):
    """Apply the refinement either as an edit or as a full rebuild."""
    from blended.evaluate import briefs as brief_module
    from blended.evaluate.acceptance import (
        RefinementOutcome,
        evaluate_brief,
        refine_brief,
    )
    from blended.ops.primitives import remove_object_and_mesh
    from blended.ops.transforms import apply_object_transform

    step = brief.refinements[0]
    target_height_m = step.changed[0].expected_m

    if rebuild:
        # Throw it away and build again — at the right height, but from
        # scratch, so nothing the user already approved is preserved.
        remove_object_and_mesh(brief.part_names[0])
        original = brief_module.STOOL_TOTAL_HEIGHT_Z_M
        brief_module.STOOL_TOTAL_HEIGHT_Z_M = target_height_m
        try:
            _build_reference_stool(leg_angles_deg=REBUILT_LEG_ANGLES_DEG)
        finally:
            brief_module.STOOL_TOTAL_HEIGHT_Z_M = original
    else:
        # A localized edit: stretch what is there along Z only.
        stool = bpy.data.objects[brief.part_names[0]]
        bpy.context.view_layer.update()
        current_height_m = max(
            (stool.matrix_world @ v.co).z for v in stool.data.vertices
        )
        stool.scale = (1.0, 1.0, target_height_m / current_height_m)
        apply_object_transform(stool.name)
    bpy.context.view_layer.update()
    return RefinementOutcome(
        step=step,
        before=before_report,
        after=evaluate_brief(refine_brief(brief, step)),
    )


def test_a_localized_edit_passes_the_refinement_gate(empty_scene):
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    before = evaluate_brief(brief)
    assert before.passes(brief), before.summary(brief)

    outcome = _refined_outcome(before, brief, rebuild=False)
    assert outcome.passes(brief), outcome.summary(brief)
    assert outcome.preservation_failures(brief) == []


def test_a_rebuild_trips_the_preservation_check(empty_scene):
    """The failure the standard exists to prevent.

    A rebuild satisfies the ORIGINAL spec and the new height. Only
    comparing against what the asset measured BEFORE the instruction
    catches that the user's approved work was discarded.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    _build_reference_stool()
    before = evaluate_brief(brief)

    outcome = _refined_outcome(before, brief, rebuild=True)

    # It hit the height it was asked for — a spec check alone is fooled.
    refined = outcome.refined_brief(brief)
    assert all(m.ok for m in outcome.after.dimensions), outcome.after.summary(refined)

    # Preservation is not fooled: the feet are somewhere else.
    disturbed = outcome.preservation_failures(brief)
    assert disturbed, outcome.summary(brief)
    assert any("swung" in failure for failure in disturbed), disturbed
    assert not outcome.passes(brief)


def test_the_refinement_step_is_reachable_from_the_brief(empty_scene):
    """A phase the briefs cannot exercise is a phase nobody tests."""
    from blended.evaluate.briefs import get_brief

    brief = get_brief("three_leg_stool")
    assert brief.refinements, "the stool brief must carry a follow-up step"
    step = brief.refinements[0]
    assert step.instruction_text.strip()
    assert step.changed, "a refinement that changes nothing measures nothing"


def _build_crate(lid_colour_rgb):
    """A geometrically PERFECT crate: only the lid's colour varies."""
    from blended.evaluate import briefs
    from blended.ops.booleans import boolean_difference
    from blended.ops.materials import assign_material
    from blended.ops.primitives import add_box, link_into_scene

    wall = briefs.CRATE_WALL_THICKNESS_M
    body = add_box(
        "CrateBody",
        width_m=briefs.CRATE_BODY_SIZE_M,
        depth_m=briefs.CRATE_BODY_SIZE_M,
        height_m=briefs.CRATE_BODY_HEIGHT_Z_M,
        location_m=(0.0, 0.0, 0.0),
    )
    link_into_scene(body)
    cavity_height = briefs.CRATE_BODY_HEIGHT_Z_M
    cavity = add_box(
        "Cavity",
        width_m=briefs.CRATE_BODY_SIZE_M - 2 * wall,
        depth_m=briefs.CRATE_BODY_SIZE_M - 2 * wall,
        height_m=cavity_height,
        location_m=(0.0, 0.0, wall),
    )
    link_into_scene(cavity)
    boolean_difference(body, cavity)

    lid = add_box(
        "CrateLid",
        width_m=briefs.CRATE_LID_SIZE_M,
        depth_m=briefs.CRATE_LID_SIZE_M,
        height_m=briefs.CRATE_LID_THICKNESS_M,
        location_m=(0.0, 0.0, briefs.CRATE_BODY_HEIGHT_Z_M),
    )
    link_into_scene(lid)
    assign_material(body, "CrateBodyPaint", base_color_rgb=(0.6, 0.4, 0.2))
    assign_material(lid, "CrateLidPaint", base_color_rgb=lid_colour_rgb)
    return body, lid


def test_a_lid_the_same_colour_as_the_body_fails_even_though_it_measures_right(
    empty_scene,
):
    """The gap that halted the v11 convergence attempt.

    Every number is correct — footprint, thickness, resting on the rim,
    centred, not sunk — and the render still shows one continuous box,
    because the lid has the body's exact footprint and its exact
    colour. The examiner saw it (`missing_feature`) when no
    measurement could.
    """
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("crate_with_lid")
    _build_crate(lid_colour_rgb=(0.6, 0.4, 0.2))
    report = evaluate_brief(brief)

    # The geometry is beyond reproach: the ONLY complaint is visibility.
    assert report.relation_failures != (), "an invisible lid passed the gate"
    assert any(
        "lid_is_distinguishable_from_the_body" in failure
        for failure in report.relation_failures
    ), report.relation_failures
    assert not any(
        name in failure
        for failure in report.relation_failures
        for name in ("lid_sits_on_the_body", "lid_is_centred", "does_not_sink")
    ), report.relation_failures


def test_a_contrasting_lid_passes(empty_scene):
    """The signed-off reference's own contrast (0.15) must be accepted,
    or the probe would condemn the artifact that earned the pin."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief

    brief = get_brief("crate_with_lid")
    _build_crate(lid_colour_rgb=(0.5, 0.3, 0.15))
    report = evaluate_brief(brief)

    assert report.relation_failures == (), report.relation_failures


# --- defects the EYE used to judge, now owned by a measurement --------
#
# The calibration zoo's `fat_seat` fixture (three_leg_stool with the
# seat scaled 1.5x) expected the examiner tag `wrong_proportion`. That
# tag moved to MEASURED_DEVIATION_TAGS on 2026-09-06 — the form gate
# measures every named dimension against a tolerance, so asking a
# 0.66-alignment judge about it manufactured false alarms (cross-run
# control specificity 0.50, both false alarms being TRUE observations
# of variation the brief leaves free). A fixture whose defect a
# measurement catches exactly stops being the eye's job and becomes
# this test instead.

SEAT_OVERSIZE_FACTOR = 1.5


def test_an_oversized_seat_fails_the_form_gate_without_the_eye(empty_scene):
    """The measurement that licensed dropping `wrong_proportion`.

    Measured 2026-09-06: the damaged seat fails at seat_diameter_x
    0.6000 m against 0.4000 +/- 0.0200. If this test ever passes
    silently, the form gate has stopped covering the defect the eye is
    no longer asked about, and the tag must go back into
    HALTING_DEVIATION_TAGS.
    """
    from blended.evaluate.acceptance import evaluate_brief, refine_brief
    from blended.evaluate.briefs import get_brief
    from blended.ops.primitives import add_cylinder, link_into_scene

    brief = get_brief("three_leg_stool")
    refined = brief
    for step in brief.refinements:
        refined = refine_brief(refined, step)
    seat_diameter = next(
        dimension.expected_m
        for part in refined.parts
        for dimension in part.dimensions
        if dimension.name == "seat_diameter_x"
    )

    # One cylinder standing in for the seat, at the oversized diameter:
    # the gate reads dimensions, so the defect is the diameter itself.
    seat = add_cylinder(
        "Stool",
        radius_m=(seat_diameter * SEAT_OVERSIZE_FACTOR) / 2.0,
        height_m=0.04,
        location_m=(0.0, 0.0, 0.0),
    )
    link_into_scene(seat)
    bpy.context.view_layer.update()

    failures = evaluate_brief(refined).failures(refined)
    oversize = [f for f in failures if f.startswith("seat_diameter_x")]
    assert oversize, failures
    assert f"{seat_diameter * SEAT_OVERSIZE_FACTOR:.4f}" in oversize[0], oversize


# Two plates, each thinner than pair_checks.CONTACT_DEPTH_TOLERANCE_M,
# crossing at the origin. They genuinely share volume, and both other
# interpenetration numbers call them clean: the face-pair count is
# suppressed below the contact tolerance, and every vertex is a whole
# span from the other plate's surface because the closest approach is
# edge-to-edge.
PLATE_HALF_SPAN_M = 1.0
PLATE_THICKNESS_M = 0.001
# The bound the brief sets. Under the plates' 1 mm depth, so the gate
# has something to fail on; a bound above it would make this test pass
# while measuring nothing.
DEPTH_BOUND_M = 0.0005


def _crossing_plate_brief():
    """A two-part brief whose only relation is the depth bound."""
    from blended.evaluate.briefs import (
        AssetBrief,
        NoInterpenetrationSpec,
        PartSpec,
    )

    return AssetBrief(
        name="crossing_plates",
        prompt_text="Two plates that must not pass through each other.",
        parts=(PartSpec(name="PlateA"), PartSpec(name="PlateB")),
        relations=(
            NoInterpenetrationSpec(
                name="plates_do_not_cross",
                first_part="PlateA",
                second_part="PlateB",
                maximum_intersecting_face_pairs=0,
                maximum_aabb_penetration_depth_m=DEPTH_BOUND_M,
                why="two plates passing through each other are one solid",
            ),
        ),
        require_material=False,
    )


def _plate(name, minimum_corner_m, maximum_corner_m):
    from blended.ops.primitives import link_into_scene

    x_min, y_min, z_min = minimum_corner_m
    x_max, y_max, z_max = maximum_corner_m
    mesh_data = bpy.data.meshes.new(name)
    mesh_data.from_pydata(
        [
            (x_min, y_min, z_min),
            (x_max, y_min, z_min),
            (x_max, y_max, z_min),
            (x_min, y_max, z_min),
            (x_min, y_min, z_max),
            (x_max, y_min, z_max),
            (x_max, y_max, z_max),
            (x_min, y_max, z_max),
        ],
        [],
        [
            (0, 1, 2, 3),
            (7, 6, 5, 4),
            (0, 4, 5, 1),
            (1, 5, 6, 2),
            (2, 6, 7, 3),
            (3, 7, 4, 0),
        ],
    )
    mesh_data.update()
    plate = bpy.data.objects.new(name, mesh_data)
    link_into_scene(plate.name)
    return plate


def test_a_shallow_crossing_fails_only_on_the_penetration_depth(empty_scene):
    """The gate that reads `aabb_penetration_depth_m`.

    Two 1 mm plates passing through each other are reported clean by
    the face-pair count AND by the separation, so this relation is the
    only thing between a fused pair of parts and a passing build.
    Deleting the depth comparison in `_measure_relations` leaves the
    failure list empty and reddens this test.
    """
    from blended.analyze.pair_checks import CONTACT_DEPTH_TOLERANCE_M, analyze_pair
    from blended.evaluate.acceptance import evaluate_brief

    assert PLATE_THICKNESS_M < CONTACT_DEPTH_TOLERANCE_M, (
        "fixture no longer exercises the blind spot: the plates are "
        "thicker than the tolerance that suppresses the pair count"
    )

    first = _plate(
        "PlateA",
        (-PLATE_HALF_SPAN_M, -PLATE_HALF_SPAN_M, 0.0),
        (PLATE_HALF_SPAN_M, PLATE_HALF_SPAN_M, PLATE_THICKNESS_M),
    )
    second = _plate(
        "PlateB",
        (-PLATE_HALF_SPAN_M, 0.0, -PLATE_HALF_SPAN_M),
        (PLATE_HALF_SPAN_M, PLATE_THICKNESS_M, PLATE_HALF_SPAN_M),
    )
    bpy.context.view_layer.update()

    # The other two numbers see nothing: that is why the depth exists.
    pair_report = analyze_pair(first, second)
    assert pair_report.intersecting_face_pair_count == 0
    assert pair_report.minimum_separation_m > PLATE_HALF_SPAN_M / 2.0

    failures = evaluate_brief(_crossing_plate_brief()).relation_failures
    depth_failures = [f for f in failures if "AABB penetration depth" in f]
    assert depth_failures, failures
    assert f"{PLATE_THICKNESS_M:.6f}" in depth_failures[0], depth_failures
