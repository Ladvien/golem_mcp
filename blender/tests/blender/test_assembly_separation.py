"""A gap between two parts must be a NUMBER, not something only a render shows.

Measured need, 2026-10-24: an inner corner stood 0.323 m clear of its wall and
`assembly_report` said nothing, because `part_intersections` holds only pairs
whose boxes OVERLAP. The number a writer needed existed nowhere in the report.
So nearby NON-overlapping pairs are now measured, and a pair further apart than
`gap_tolerance_m` is an OPEN joint named in `open_gaps`.

Reported, never refused — `export_assembly` is unchanged — and `gate="none"`
claims no measurement at all.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

WALL_SIZE_M = (4.0, 0.3, 3.0)
CORNER_SIZE_M = (0.3, 1.0, 3.0)
# The measured gap: the corner's -X face against the wall's +X face.
MEASURED_GAP_M = 0.323
GAP_TOLERANCE_M = 0.002
TOLERANCE_M = 1.0e-3


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


def _wall_and_corner(corner_location_m):
    """The measured layout: a low wall, and an inner corner against one end."""
    _box("Wall_Low", WALL_SIZE_M, (0.0, 0.0, 0.0))
    _box("Corner_Inner", CORNER_SIZE_M, corner_location_m)


# The corner's -X face lands exactly MEASURED_GAP_M past the wall's +X face:
# the wall ends at x = 2.0, and the corner is 0.3 wide, so its centre is
# 2.0 + gap + 0.15.
OPEN_CORNER_X_M = 2.0 + MEASURED_GAP_M + CORNER_SIZE_M[0] / 2.0
# Butted: the same construction with no gap, which is what a joint IS.
BUTTED_CORNER_X_M = 2.0 + CORNER_SIZE_M[0] / 2.0


def test_an_open_joint_is_measured_where_no_intersection_row_existed(empty_scene):
    from golem_blender.ops import assembly_report, define_assembly

    _wall_and_corner((OPEN_CORNER_X_M, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="full")

    # The old report was SILENT here: the boxes share no volume, so the pair was
    # never a candidate. That is the whole point of the test.
    assert report.part_intersections == ()
    assert report.separation_count == 1
    row = report.separations[0]
    assert row.separation_m == pytest.approx(MEASURED_GAP_M, abs=TOLERANCE_M)
    assert row.is_open
    assert report.separations_measured == 1
    assert report.open_gaps == (
        "Wall_Low → Corner_Inner: 0.323 m apart, expected ≤ 0.002 m",
    )


def test_a_butted_joint_is_closed(empty_scene):
    from golem_blender.ops import assembly_report, define_assembly

    _wall_and_corner((BUTTED_CORNER_X_M, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="full")

    assert report.separation_count == 1
    row = report.separations[0]
    assert row.separation_m == pytest.approx(0.0, abs=1.0e-4)
    assert not row.is_open
    assert report.open_gaps == ()


def test_structure_mode_reports_the_box_bound_and_says_so(empty_scene):
    from golem_blender.ops import assembly_report, define_assembly

    _wall_and_corner((OPEN_CORNER_X_M, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="structure")

    row = report.separations[0]
    assert row.separation_m == -1.0
    assert row.box_gap_m == pytest.approx(MEASURED_GAP_M, abs=TOLERANCE_M)
    assert row.is_open
    assert report.separations_measured == 0
    assert report.open_gaps[0].startswith(
        "Wall_Low → Corner_Inner: at least 0.323 m apart (bounding boxes"
    )


def test_a_pair_beyond_the_margin_is_not_measured_until_the_margin_reaches_it(
    empty_scene,
):
    from golem_blender.ops import assembly_report, define_assembly

    # 1.0 m clear: beyond the default 0.5 m margin.
    _wall_and_corner((2.0 + 1.0 + CORNER_SIZE_M[0] / 2.0, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    assert assembly_report("Abbey", gate="full").separation_count == 0

    report = assembly_report("Abbey", gate="full", separation_margin_m=2.0)
    assert report.separation_count == 1
    assert report.separations[0].separation_m == pytest.approx(1.0, abs=TOLERANCE_M)


def test_a_declared_pair_is_measured_at_any_distance(empty_scene):
    from golem_blender.ops import assembly_report, declare_join, define_assembly

    # 3 m apart: far outside the default margin, measured because DECLARED.
    _wall_and_corner((2.0 + 3.0 + CORNER_SIZE_M[0] / 2.0, 0.35, 0.0))
    declare_join("Corner_Inner", "Wall_Low", "they are bolted together")
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="full")

    assert report.separation_count == 1
    row = report.separations[0]
    assert row.declared_reason == "they are bolted together"
    assert row.is_open
    assert report.declared_without_contact == (("Corner_Inner", "Wall_Low"),)


def test_a_declared_pair_that_really_touches_is_not_a_defect(empty_scene):
    """A butted declared joint is what a declaration is FOR, so it cannot be a fault."""
    from golem_blender.ops import assembly_report, declare_join, define_assembly

    _wall_and_corner((BUTTED_CORNER_X_M, 0.35, 0.0))
    declare_join("Wall_Low", "Corner_Inner", "the corner butts into the wall")
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="full")

    assert report.separation_count == 1
    assert report.declared_without_contact == ()


def test_a_spent_budget_leaves_the_row_unmeasured_and_the_report_truncated(
    empty_scene,
):
    from golem_blender.ops import assembly_report, define_assembly

    _wall_and_corner((OPEN_CORNER_X_M, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    report = assembly_report("Abbey", gate="full", budget_s=1.0e-6)

    assert report.truncated
    assert report.separation_count == 1
    assert report.separations[0].separation_m == -1.0
    # The boxes still answer the question, so the defect is not lost with the
    # measurement.
    assert report.separations[0].is_open


def test_a_negative_tolerance_or_offset_is_refused(empty_scene):
    from golem_blender.ops import assembly_report, define_assembly

    _wall_and_corner((OPEN_CORNER_X_M, 0.35, 0.0))
    define_assembly("Abbey", ["Wall_Low", "Corner_Inner"], gate="none")

    with pytest.raises(ValueError, match="gap_tolerance_m must be 0 or more"):
        assembly_report("Abbey", gate="full", gap_tolerance_m=-0.1)
    with pytest.raises(ValueError, match="separation_offset must be 0 or more"):
        assembly_report("Abbey", gate="full", separation_offset=-1)
    with pytest.raises(ValueError, match="separation_margin_m must be 0 or more"):
        assembly_report("Abbey", gate="full", separation_margin_m=-1.0)
