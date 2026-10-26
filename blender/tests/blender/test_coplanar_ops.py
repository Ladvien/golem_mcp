"""Coplanar detection and the fix, measured on boxes whose faces are exact.

The layout is chosen so every other face of the small box is INSIDE the big
one: the ONLY coplanar contact is the two -Y faces. Anything the detector
reports beyond that pair is a false positive, and the count makes it visible.

The fix's target is stated as numbers, not as "it worked": the small box's -Y
face must end up exactly 2 x tolerance behind where it was and the big box's
vertices must not have moved at all — the whole point of moving the SMALLER
side is that most of the asset is untouched.

The measured demand is the shipped crate (52 flush pairs, all visible); that
reproduction lives in the end-to-end script, not here, because it needs a file
outside the repo.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TOLERANCE_M = 1.0e-6
PLANK_SIZE_M = (1.0, 0.1, 1.0)  # y in [-0.05, 0.05], z in [0, 1]
BAND_SIZE_M = (0.2, 0.05, 0.5)  # y in [-0.05, 0.0], z in [0.25, 0.75]
BAND_LOCATION_M = (0.0, -0.025, 0.25)
# The band's -Y face and the plank's -Y face are both at y = -0.05: flush.
FLUSH_Y_M = -0.05


@pytest.fixture()
def empty_scene():
    """A clean scene AND clean registries: declarations are session state."""
    from golem_blender.ops import assembly, coplanar

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()
    coplanar._DECLARED_FLUSH.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()
    coplanar._DECLARED_FLUSH.clear()


def _box(name, size_m, location_m=(0.0, 0.0, 0.0), material=None):
    from golem_blender.ops import add_box, assign_material, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    if material is not None:
        assign_material(box_name, material)
    return box_name


def _plank_and_band(band_location_m=BAND_LOCATION_M):
    """The measured fixture: only the two -Y faces are coplanar."""
    _box("Plank", PLANK_SIZE_M, material="Wood")
    _box("Band", BAND_SIZE_M, band_location_m, material="Iron")


def _world_y_of_face(object_name, normal_y=-1.0):
    """The world y of the object's face whose world normal points along `normal_y`."""
    import bpy as _bpy

    blender_object = _bpy.data.objects[object_name]
    world_normal_matrix = blender_object.matrix_world.to_3x3()
    heights = []
    for polygon in blender_object.data.polygons:
        world_normal = (world_normal_matrix @ polygon.normal).normalized()
        if world_normal.y * normal_y > 0.999:
            heights.append((blender_object.matrix_world @ polygon.center).y)
    assert heights, f"{object_name} has no face facing {normal_y} on y"
    return min(heights)


def _all_vertex_coordinates(object_name):
    import bpy as _bpy

    blender_object = _bpy.data.objects[object_name]
    return sorted(
        tuple(round(value, 9) for value in (blender_object.matrix_world @ vertex.co))
        for vertex in blender_object.data.vertices
    )


def test_the_flush_faces_are_reported_with_the_fix_on_the_smaller_side(empty_scene):
    from golem_blender.ops import coplanar_report

    _plank_and_band()
    report = coplanar_report(["Plank", "Band"])

    assert report.flicker_count > 0
    assert report.control_flush_seen and report.control_gap_silent
    flicker = [
        pair
        for pair in report.pairs
        if pair.kind == "flicker" and not pair.declared_reason
    ]
    assert flicker
    for pair in flicker:
        assert pair.plane_gap_m == pytest.approx(0.0, abs=TOLERANCE_M)
        assert "yaw_0" in pair.visible_from, (
            "a -Y face at the front of the scene must be seen by the yaw_0 view"
        )
    assert len(report.fixes) == 1
    fix = report.fixes[0]
    assert fix.object_name == "Band", "the smaller plate moves, not the plank"
    assert fix.normal[1] == pytest.approx(-1.0, abs=1.0e-6)
    assert fix.move_m == pytest.approx(2.0 * report.tolerance_m)
    assert fix.face_indices


def test_a_band_five_millimetres_proud_is_not_a_coplanar_pair(empty_scene):
    from golem_blender.ops import coplanar_report

    # Front face at y = -0.055: 5 mm proud of the plank's -0.05.
    _plank_and_band((0.0, -0.03, 0.25))
    report = coplanar_report(["Plank", "Band"])
    assert report.pair_count == 0
    assert report.fixes == ()


def test_a_cover_in_front_buries_the_pair(empty_scene):
    from golem_blender.ops import coplanar_report

    _plank_and_band()
    # y in [-0.6, -0.1]: entirely in front of the flush faces at -0.05.
    _box("Cover", (3.0, 0.5, 3.0), (0.0, -0.35, 0.0), material="Stone")
    report = coplanar_report(["Plank", "Band", "Cover"])
    yaw_0 = [pair for pair in report.pairs if pair.kind == "flicker"]
    assert report.pair_count > 0
    assert report.flicker_count == 0
    assert not yaw_0, "a covered pair cannot be a flicker"
    assert {pair.kind for pair in report.pairs} == {"buried"}
    assert report.fixes == ()


def test_one_material_cannot_flicker_in_colour_until_asked(empty_scene):
    from golem_blender.ops import CoplanarSettings, coplanar_report

    _box("Plank", PLANK_SIZE_M, material="Wood")
    _box("Band", BAND_SIZE_M, BAND_LOCATION_M, material="Wood")
    ignored = coplanar_report(["Plank", "Band"])
    assert {pair.kind for pair in ignored.pairs} == {"same_material"}
    assert ignored.fixes == ()

    reported = coplanar_report(
        ["Plank", "Band"], CoplanarSettings(same_material="report")
    )
    assert reported.flicker_count > 0
    assert len(reported.fixes) == 1


def test_a_declared_flush_leaves_the_flicker_count_and_keeps_its_kind(empty_scene):
    from golem_blender.ops import coplanar_report, declare_flush

    _plank_and_band()
    before = coplanar_report(["Plank", "Band"])
    assert before.flicker_count > 0

    declare_flush("Plank", "Band", "trim laid on")
    after = coplanar_report(["Plank", "Band"])
    assert after.flicker_count == 0
    assert after.fixes == ()
    declared = [pair for pair in after.pairs if pair.declared_reason]
    assert declared
    assert {pair.declared_reason for pair in declared} == {"trim laid on"}
    # The GEOMETRY is unchanged, so the kind still says what the faces do.
    assert {pair.kind for pair in declared} == {"flicker"}


def test_the_fix_moves_the_band_and_leaves_the_plank_untouched(empty_scene):
    from golem_blender.ops import separate_coplanar_faces

    _plank_and_band()
    plank_before = _all_vertex_coordinates("Plank")
    band_face_before = _world_y_of_face("Band")

    fix_report = separate_coplanar_faces(["Plank", "Band"])

    assert fix_report.flicker_before > 0
    assert fix_report.flicker_after == 0
    assert fix_report.moved_vertex_count > 0
    expected_y = band_face_before - 2.0 * fix_report.report_after.tolerance_m
    assert _world_y_of_face("Band") == pytest.approx(expected_y, abs=TOLERANCE_M)
    assert _all_vertex_coordinates("Plank") == plank_before


def test_the_selection_is_exactly_the_paired_faces(empty_scene):
    from golem_blender.ops import coplanar_report, select_coplanar_faces

    _plank_and_band()
    report = coplanar_report(["Plank", "Band"])
    expected: dict[str, set[int]] = {}
    for pair in report.pairs:
        if pair.kind != "flicker" or pair.declared_reason:
            continue
        expected.setdefault(pair.first_object_name, set()).add(pair.first_face_index)
        expected.setdefault(pair.second_object_name, set()).add(pair.second_face_index)

    selection = select_coplanar_faces(["Plank", "Band"])
    assert selection.flicker_count == report.flicker_count
    assert dict(selection.selected) == {
        name: tuple(sorted(indices)) for name, indices in expected.items()
    }
    for object_name in ("Plank", "Band"):
        mesh = bpy.data.objects[object_name].data
        selected = {polygon.index for polygon in mesh.polygons if polygon.select}
        assert selected == expected.get(object_name, set())


def test_a_target_with_modifiers_is_refused(empty_scene):
    from golem_blender.ops import add_bevel, separate_coplanar_faces

    _plank_and_band()
    add_bevel("Band", 0.002, 2)
    with pytest.raises(ValueError, match="has modifiers"):
        separate_coplanar_faces(["Plank", "Band"])


def test_a_detector_that_fails_its_controls_reports_nothing(empty_scene, monkeypatch):
    from golem_blender.ops import coplanar

    _plank_and_band()
    monkeypatch.setattr(coplanar, "coplanar_triangle_pairs", lambda *a, **k: [])
    with pytest.raises(coplanar.CoplanarSelfTestFailed, match="self-test failed"):
        coplanar.coplanar_report(["Plank", "Band"])
