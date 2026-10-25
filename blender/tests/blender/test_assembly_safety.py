"""A long assembly call must not wedge the session, and must not lose the scene.

Measured need, 2026-10-24: a 77-part bakery's `export_assembly` outlived the
client's 300 s socket timeout. The bridge then reported `PAUSED` (no Blender)
while Blender was still measuring, so the agent read a live session as a dead
one; and the 77 parts existed only in memory. Four properties keep that from
happening again, and each has a test here:

- a GATE MODE, so a caller can say how much measurement it wants, and "none"
  still writes the files;
- a BUDGET, so a long gate returns `truncated: true` with what it measured
  instead of running until something else gives up;
- SAVE-FIRST, so the `.blend` and the session's safety copy exist before the
  gate starts;
- a PROGRESS FILE, so the bridge can tell the client the call is alive.

`declare_join` is here too, because it is what makes `undeclared_clashes`
useful: the report can only separate a junction from a defect if somebody said
which junctions are intended.
"""

import json

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TOLERANCE_M = 1.0e-3
# Small enough that every check the mode asked for is cut by the budget.
SPENT_BUDGET_S = 1.0e-6


@pytest.fixture()
def empty_scene():
    """A clean scene AND clean registries: assemblies, sides and joins are session state."""
    from golem_blender.ops import assembly

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    assembly._DECLARED_JOINS.clear()


def _box(name, size_m=(1.0, 1.0, 1.0), location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops import add_box, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    return box_name


def _clashing_pair():
    """Two boxes whose interiors overlap and which share NO bounding plane."""
    _box("Body", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Axle", (0.3, 0.3, 1.6), (0.0, 0.0, 0.2))
    return ["Body", "Axle"]


# --- declare_join ---------------------------------------------------------------


def test_an_intended_clash_leaves_the_undeclared_list_and_keeps_its_reason(
    empty_scene,
):
    from golem_blender.ops import declare_join, define_assembly

    names = _clashing_pair()

    before = define_assembly("Machine", names, gate="structure")
    assert ("Body", "Axle") in before.undeclared_clashes

    declare_join("Body", "Axle", "the axle passes through its hub")
    after = define_assembly("Machine", names, gate="structure")

    assert after.undeclared_clashes == ()
    row = next(
        entry
        for entry in after.part_intersections
        if {entry.first_object_name, entry.second_object_name} == {"Body", "Axle"}
    )
    assert row.declared_reason == "the axle passes through its hub"
    # The clash is still REPORTED: declaring it intended does not hide the contact.
    assert after.part_intersection_count == before.part_intersection_count


def test_declaring_in_either_order_is_one_declaration(empty_scene):
    from golem_blender.ops import declare_join, define_assembly

    names = _clashing_pair()
    declare_join("Axle", "Body", "first reason")
    declare_join("Body", "Axle", "a better reason")

    report = define_assembly("Machine", names, gate="structure")

    assert report.undeclared_clashes == ()
    row = next(
        entry
        for entry in report.part_intersections
        if {entry.first_object_name, entry.second_object_name} == {"Body", "Axle"}
    )
    assert row.declared_reason == "a better reason"


def test_a_declared_join_that_does_not_touch_is_reported(empty_scene):
    """A claim that stopped being true is a part that moved, so it is a defect too."""
    from golem_blender.ops import declare_join, define_assembly

    _box("First", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Second", (1.0, 1.0, 1.0), (4.0, 0.0, 0.0))
    declare_join("First", "Second", "they are bolted together")

    report = define_assembly("Set", ["First", "Second"], gate="structure")

    assert report.declared_without_contact == (("First", "Second"),)
    assert report.undeclared_clashes == ()


def test_a_join_needs_two_live_different_parts_and_a_reason(empty_scene):
    from golem_blender.ops import declare_join
    from golem_blender.ops._objects import UnknownObject

    _box("Only", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Other", (1.0, 1.0, 1.0), (0.0, 0.0, 1.0))

    with pytest.raises(ValueError, match="two different parts"):
        declare_join("Only", "Only", "a part does not join itself")
    with pytest.raises(ValueError, match="needs a reason"):
        declare_join("Only", "Other", "   ")
    # A name with no mesh is refused as the missing geometry it is.
    with pytest.raises(UnknownObject):
        declare_join("Only", "NoSuchPart", "a real reason")


# --- gate modes and the budget --------------------------------------------------


def test_gate_none_measures_no_pair_and_structure_measures_no_triangles(empty_scene):
    from golem_blender.ops import define_assembly

    names = _clashing_pair()

    none_report = define_assembly("Machine", names, gate="none")
    assert none_report.gate == "none"
    assert none_report.part_intersections == ()
    assert none_report.pairs_total == 0
    assert not none_report.truncated
    # The cheap box arithmetic still runs: support and floating are free.
    assert none_report.triangles_total > 0

    structure_report = define_assembly("Machine", names, gate="structure")
    assert structure_report.gate == "structure"
    assert structure_report.pairs_total == 1
    assert structure_report.pairs_checked == 0
    assert not structure_report.truncated
    # A structure-mode row still carries its measured DEPTH; only the triangle
    # sweep is missing, and -1 says so rather than a zero claiming a measurement.
    (row,) = structure_report.part_intersections
    assert row.intersecting_face_pair_count == -1
    assert row.penetration_depth_m > 0.0


def test_a_spent_budget_truncates_the_full_gate_and_keeps_the_rows(empty_scene):
    from golem_blender.ops import define_assembly

    names = _clashing_pair()

    report = define_assembly("Machine", names, gate="full", budget_s=SPENT_BUDGET_S)

    assert report.truncated
    assert report.pairs_checked == 0
    assert report.pairs_total == 1
    # Not one row is lost: a truncated report is a real measurement of less.
    assert report.part_intersection_count == 1
    assert len(report.part_intersections) == 1


def test_a_bad_gate_and_a_non_positive_budget_are_refused(empty_scene):
    from golem_blender.ops import define_assembly

    names = _clashing_pair()

    with pytest.raises(ValueError, match="gate must be one of"):
        define_assembly("Machine", names, gate="everything")
    with pytest.raises(ValueError, match="budget_s must be a positive"):
        define_assembly("Machine", names, budget_s=0.0)


def test_rows_are_paged_while_the_count_and_the_defects_are_not(empty_scene):
    """45 overlapping pairs against a 40-row page: page 2 holds the other five."""
    from golem_blender.ops import assembly_report, define_assembly

    # Nine beams along X and five joists along Y, crossing at one z: every one of
    # the 9 x 5 = 45 crossings shares volume, and no two runs of the same
    # direction touch (0.3 m pitch against 0.3 m thickness). 45 pairs exactly.
    names = []
    for index in range(9):
        names.append(
            _box(f"Beam{index}", (3.0, 0.3, 0.4), (0.0, -1.6 + index * 0.4, 0.0))
        )
    for index in range(5):
        names.append(
            _box(f"Joist{index}", (0.3, 3.0, 0.4), (-0.8 + index * 0.4, 0.0, 0.0))
        )
    define_assembly("Lattice", names, gate="structure")

    first_page = assembly_report("Lattice", gate="structure")
    second_page = assembly_report("Lattice", gate="structure", intersection_offset=40)

    assert first_page.part_intersection_count == 45
    assert len(first_page.part_intersections) == 40
    assert first_page.part_intersection_offset == 0
    assert len(second_page.part_intersections) == 5
    assert second_page.part_intersection_offset == 40
    assert second_page.part_intersection_count == 45
    # The pages do not overlap: together they are the whole list, once each.
    seen = {
        (row.first_object_name, row.second_object_name)
        for row in first_page.part_intersections
    } | {
        (row.first_object_name, row.second_object_name)
        for row in second_page.part_intersections
    }
    assert len(seen) == 45


def test_a_negative_offset_is_refused(empty_scene):
    from golem_blender.ops import assembly_report, define_assembly

    define_assembly("Machine", _clashing_pair(), gate="structure")

    with pytest.raises(ValueError, match="intersection_offset must be 0 or more"):
        assembly_report("Machine", gate="structure", intersection_offset=-1)


# --- export: save first, gate second -------------------------------------------


def test_gate_none_writes_both_files_and_refuses_to_call_them_verified(
    empty_scene, tmp_path
):
    from golem_blender.ops import define_assembly, export_assembly

    define_assembly("Clean", [_box("Part", (1.0, 1.0, 1.0))], gate="none")

    report = export_assembly(
        "Clean",
        str(tmp_path / "clean.glb"),
        str(tmp_path / "clean.blend"),
        gate="none",
    )

    assert (tmp_path / "clean.glb").stat().st_size > 0
    assert (tmp_path / "clean.blend").stat().st_size > 0
    assert report.gate == "none"
    assert report.skipped_checks == (
        "part_gate",
        "clearance",
        "combined_analysis",
        "reimport",
    )
    assert not report.passes_assembly()
    assert report.assembly_failures() == [
        (
            "unverified: gate='none' skipped every check; re-export with "
            "gate='structure' or 'full' before shipping"
        )
    ]


def test_gate_structure_passes_clean_boxes_and_names_the_check_it_skipped(
    empty_scene, tmp_path
):
    from golem_blender.ops import define_assembly, export_assembly

    define_assembly("Clean", [_box("Part", (1.0, 1.0, 1.0))], gate="none")

    report = export_assembly(
        "Clean",
        str(tmp_path / "clean.glb"),
        str(tmp_path / "clean.blend"),
        gate="structure",
    )

    assert report.gate == "structure"
    assert report.reimported_raw is None
    assert report.pre_export is None
    assert report.skipped_checks == ("combined_analysis", "reimport")
    assert report.passes_assembly(), report.assembly_failures()
    assert (tmp_path / "clean.blend").stat().st_size > 0


def test_a_spent_budget_truncates_the_gate_and_still_leaves_the_blend(
    empty_scene, tmp_path
):
    """The ORDER is the point: the .blend is written before any measurement."""
    from golem_blender.ops import define_assembly, export_assembly

    define_assembly("Clean", [_box("Part", (1.0, 1.0, 1.0))], gate="none")

    report = export_assembly(
        "Clean",
        str(tmp_path / "clean.glb"),
        str(tmp_path / "clean.blend"),
        gate="full",
        budget_s=SPENT_BUDGET_S,
    )

    assert report.truncated
    assert (tmp_path / "clean.blend").stat().st_size > 0
    assert (tmp_path / "clean.glb").stat().st_size > 0
    truncated_lines = [
        line
        for line in report.assembly_failures()
        if "gate truncated at budget_s" in line
    ]
    assert len(truncated_lines) == 1, report.assembly_failures()


# --- the scratch copy and the progress file ------------------------------------


def test_a_full_gate_on_a_large_assembly_saves_the_session_first(
    empty_scene, tmp_path, monkeypatch
):
    """The safety copy lands where the progress file's neighbour can be reloaded."""
    from golem_blender.ops import define_assembly, export_assembly
    from golem_blender.run import call_context

    monkeypatch.setattr(call_context, "SCRATCH_SAVE_MINIMUM_PARTS", 1)
    define_assembly("Clean", [_box("Part", (1.0, 1.0, 1.0))], gate="none")

    with call_context.call_context(tmp_path, "export_assembly"):
        report = export_assembly(
            "Clean",
            str(tmp_path / "clean.glb"),
            str(tmp_path / "clean.blend"),
            gate="full",
        )
        progress_path = tmp_path / call_context.PROGRESS_FILE_NAME
        assert progress_path.exists()
        written = json.loads(progress_path.read_text(encoding="utf-8"))
        assert written["stage"]

    expected_scratch = (
        tmp_path / call_context.SCRATCH_DIRECTORY_NAME / ("export_assembly.blend")
    )
    assert report.scratch_blend_path == str(expected_scratch)
    assert report.scratch_save_error == ""
    assert expected_scratch.stat().st_size > 0
    # It is a real .blend: Blender can open it as a library.
    bpy.data.libraries.load(str(expected_scratch))


def test_the_parts_own_triangle_total_is_the_count_the_file_must_carry(
    empty_scene, tmp_path
):
    from golem_blender.ops import define_assembly, export_assembly

    parts = [
        _box("First", (1.0, 1.0, 1.0)),
        _box("Second", (1.0, 1.0, 1.0), (1.0, 0.0, 0.0)),
    ]
    define_assembly("Pair", parts, gate="none")

    report = export_assembly(
        "Pair",
        str(tmp_path / "pair.glb"),
        str(tmp_path / "pair.blend"),
        gate="structure",
    )

    # A cube is 12 triangles and both parts are separate closed boxes.
    assert report.expected_triangle_count == 24
    assert report.gate_checked_parts == 2
    assert report.part_count == 2
    assert report.file_report.triangle_count == 24
    assert report.pre_export is None
    assert report.passes_assembly(), report.assembly_failures()


def test_an_assembly_report_still_refuses_an_unknown_assembly(empty_scene):
    from golem_blender.ops import assembly_report

    with pytest.raises(KeyError):
        assembly_report("NoSuchAssembly", gate="structure")
