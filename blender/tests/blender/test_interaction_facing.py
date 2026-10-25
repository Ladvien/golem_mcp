"""An asset a character cannot USE is not done — measured, not remembered.

The defect this file exists for, found by the user LOOKING at a live
session (2026-10-24): a bakery assembled from kit pieces had its two ovens
facing each other, 0.10 m apart, and its spout sunk into a wall. Every
gate passed — `MeshBudget` measures one mesh, the assembly gate measures
parts, laps and support. None of them knows which side of the asset a
character stands on.

Each test below is a SHAPE of that defect, and the assertion is on the
measured number, not on the message:

- the ovens: two parts whose declared fronts face one another;
- the spout: one part whose declared front is inside another part;
- the clear case: the same geometry, one part rotated 180 degrees, which
  is exactly the repair the user asked for. It must PASS, or the check is
  a tax on every correct asset.

The side is DECLARED (`units.yaml`'s `front: "-Y"`, or
`declare_interaction_side`) because four geometric probes proved it
cannot be inferred from triangles: see `analyze/interaction.py`.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

TOLERANCE_M = 1.0e-3


@pytest.fixture()
def empty_scene():
    """A clean scene AND clean registries: assemblies and sides are session state."""
    from golem_blender.ops import assembly

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._INTERACTION_SIDES.clear()


def _box(name, size_m=(1.0, 1.0, 1.0), location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops import add_box, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    return box_name


def _side_for(report, object_name):
    matches = [
        side for side in report.interaction_sides if side.object_name == object_name
    ]
    assert len(matches) == 1, f"{object_name} has {len(matches)} measured sides"
    return matches[0]


# --- 1. the defect: a front facing another part ----------------------------


def test_a_front_facing_another_part_is_blocked_and_named(empty_scene):
    """The ovens: `front` is local -Y, and B sits 0.1 m in front of A."""
    from golem_blender.ops import define_assembly

    _box("Oven_A", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Oven_B", (1.0, 1.0, 1.0), (0.0, -1.1, 0.0))

    report = define_assembly("Ovens", ["Oven_A", "Oven_B"], interaction_side="front")

    assert report.blocked_sides, "two fronts 0.1 m apart must be reported blocked"
    blocked_names = {side.object_name for side in report.blocked_sides}
    assert "Oven_A" in blocked_names
    # The measured clearance is the real gap, not a constant.
    side = _side_for(report, "Oven_A")
    assert side.side == "front"
    # The gap is 0.1 m; the ray starts RAY_OFFSET_M (2 mm) off the face, so
    # the measured clearance is 0.098 m. Asserting the real number keeps this
    # from quietly becoming a test of a constant.
    assert side.clearance_m == pytest.approx(0.098, abs=TOLERANCE_M)
    assert [name for name, _distance in side.blocked_by] == ["Oven_B"]


def test_the_declared_front_faces_minus_y_by_default(empty_scene):
    """`units.yaml` says `front: "-Y"`, and this is the measurement that agrees."""
    from golem_blender.ops import define_assembly

    _box("Alone", (1.0, 1.0, 1.0))

    report = define_assembly("Alone", ["Alone"], interaction_side="front")

    side = _side_for(report, "Alone")
    assert side.side == "front"
    assert side.bearing_deg == pytest.approx(0.0)
    assert side.normal == pytest.approx((0.0, -1.0, 0.0))


def test_a_part_sunk_into_another_is_blocked_at_its_clearance(empty_scene):
    """The spout: a 0.3 m stub sunk through a 0.4 m wall leaves 0.2 m of the
    wall's thickness outside the stub's own front — 0.05 m of clear space,
    which is real, measured, and far too little to stand in. The assertion is
    on that number, so a future change to the geometry cannot quietly turn
    this test into a tautology."""
    from golem_blender.ops import define_assembly

    _box("Wall", (4.0, 0.4, 3.0), (0.0, 0.0, 0.0))
    _box("Spout", (0.3, 0.2, 0.3), (0.0, 0.0, 1.5))

    report = define_assembly("Mill", ["Wall", "Spout"], interaction_side="front")

    side = _side_for(report, "Spout")
    # The stub spans y -0.1..0.1 and the wall y -0.2..0.2, so the stub's front
    # face sits 0.1 m inside the wall's skin: the ray meets the wall 0.098 m
    # out (0.002 m is the ray's own offset), over the whole face.
    assert side.clearance_m == pytest.approx(0.1, abs=0.01)
    assert side.blocked_fraction == pytest.approx(1.0)
    assert side.blocked_by and side.blocked_by[0][0] == "Wall"
    assert "Spout" in {blocked.object_name for blocked in report.blocked_sides}


# --- 2. the repair the user asked for must PASS ---------------------------


def test_the_same_geometry_with_one_part_turned_round_is_clear(empty_scene):
    """Rotating the offending part 180 degrees is the repair. If this failed,
    the check would punish every correct asset."""
    from golem_blender.ops import define_assembly, rotate_object_euler

    _box("Oven_A", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Oven_B", (1.0, 1.0, 1.0), (0.0, -2.0, 0.0))
    rotate_object_euler("Oven_B", z_rad=3.141592653589793)

    report = define_assembly("Ovens", ["Oven_A", "Oven_B"], interaction_side="front")

    assert report.blocked_sides == ()
    assert _side_for(report, "Oven_A").clearance_m > 0.9
    # ... and the turned part now faces the other way.
    assert _side_for(report, "Oven_B").bearing_deg == pytest.approx(180.0, abs=1.0)


def test_an_open_field_is_clear(empty_scene):
    from golem_blender.ops import define_assembly

    _box("Lone", (1.0, 1.0, 1.0))

    report = define_assembly("Lone", ["Lone"], interaction_side="front")

    assert report.blocked_sides == ()
    assert _side_for(report, "Lone").blocked_by == ()


def test_a_part_behind_the_asset_does_not_block_the_front_it_uses(empty_scene):
    """A hutch behind a desk stands in front of the HUTCH's own front — that is
    the hutch facing the desk's back, which is where a hutch belongs, and the
    report says so per part rather than as one verdict on the whole asset. The
    desk's own front, the side a character uses to sit down, is clear."""
    from golem_blender.ops import define_assembly

    _box("Desk", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Hutch", (1.0, 1.0, 1.0), (0.0, 1.05, 0.0))

    report = define_assembly("Desk", ["Desk", "Hutch"], interaction_side="front")

    assert _side_for(report, "Desk").clearance_m > 0.9
    assert "Desk" not in {blocked.object_name for blocked in report.blocked_sides}
    # The hutch's own declared front points at the desk; declaring `back`
    # instead is the one call that says the hutch faces the room.
    assert "Hutch" in {blocked.object_name for blocked in report.blocked_sides}

    # Declaring the side the hutch really faces makes both parts usable.
    from golem_blender.ops import declare_interaction_side

    declare_interaction_side("Hutch", "back")
    repaired = define_assembly("Desk", ["Desk", "Hutch"], interaction_side="front")

    assert repaired.blocked_sides == ()
    assert _side_for(repaired, "Hutch").side == "back"


# --- 2b. an assembly that claims nothing is measured for nothing ----------


def test_an_assembly_that_claims_no_side_measures_none(empty_scene):
    """A crate beside a wall is not a defect, and a kit of parts is not an
    asset anyone walks up to. This is the case that broke the first design,
    which checked every part's `front` unconditionally: the 49-part building
    fixture failed on `WallWest0` because its own crates sit 0.2 m from it."""
    from golem_blender.ops import define_assembly

    _box("Wall", (4.0, 0.4, 3.0), (0.0, 0.0, 0.0))
    _box("Crate", (0.5, 0.5, 0.5), (0.0, -0.45, 0.0))

    report = define_assembly("Store", ["Wall", "Crate"])

    assert report.interaction_sides == ()
    assert report.blocked_sides == ()
    assert report.interaction_side_by_part == ()


def test_an_unknown_claimed_side_is_refused(empty_scene):
    from golem_blender.ops import define_assembly

    _box("Thing")

    with pytest.raises(ValueError, match="interaction_side must be one of"):
        define_assembly("Thing", ["Thing"], interaction_side="upwards")


# --- 3. the declaration, and what it can say ------------------------------


def test_a_declared_side_replaces_the_default(empty_scene):
    """A shelf's opening faces where the caller says, not where `front` is."""
    from golem_blender.ops import declare_interaction_side, define_assembly

    _box("Shelf", (1.0, 0.4, 1.0), (0.0, 0.0, 0.0))
    # Sits 0.05 m above the shelf's top: the shelf's opening cannot be used.
    _box("Blocked", (1.0, 1.0, 1.0), (0.0, 0.0, 1.05))

    declare_interaction_side("Shelf", "top")
    report = define_assembly("ShelfA", ["Shelf", "Blocked"], interaction_side="front")

    assert _side_for(report, "Shelf").side == "top"
    assert "Shelf" in {blocked.object_name for blocked in report.blocked_sides}


def test_an_unknown_side_is_refused(empty_scene):
    from golem_blender.ops import declare_interaction_side

    _box("Thing")

    with pytest.raises(ValueError, match="side must be one of"):
        declare_interaction_side("Thing", "sideways")


def test_declaring_a_side_for_no_mesh_is_refused(empty_scene):
    from golem_blender.ops import declare_interaction_side
    from golem_blender.ops._objects import UnknownObject

    with pytest.raises(UnknownObject, match="Ghost"):
        declare_interaction_side("Ghost", "front")


# --- 4. the verdict reaches the export ------------------------------------


def test_the_export_refuses_a_blocked_side_and_names_the_fix(empty_scene, tmp_path):
    """The whole point: the defect cannot ship. The sentence names the part,
    the side, the clearance and what is standing there."""
    from golem_blender.ops import define_assembly, export_assembly

    _box("Oven_A", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Oven_B", (1.0, 1.0, 1.0), (0.0, -1.1, 0.0))
    define_assembly("Ovens", ["Oven_A", "Oven_B"], interaction_side="front")

    report = export_assembly(
        "Ovens",
        str(tmp_path / "Ovens.glb"),
        str(tmp_path / "Ovens.blend"),
    )

    assert not report.passes_assembly()
    failures = "\n".join(report.assembly_failures())
    assert "cannot be USED" in failures
    assert "Oven_A" in failures
    assert "blocked by Oven_B" in failures
    assert "declare_interaction_side" in failures


def test_the_export_passes_once_the_part_is_turned_round(empty_scene, tmp_path):
    """The repair makes the export ship — the check has a way to succeed."""
    from golem_blender.ops import define_assembly, export_assembly, rotate_object_euler

    _box("Oven_A", (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    _box("Oven_B", (1.0, 1.0, 1.0), (0.0, -2.0, 0.0))
    rotate_object_euler("Oven_B", z_rad=3.141592653589793)
    define_assembly("Ovens", ["Oven_A", "Oven_B"], interaction_side="front")

    report = export_assembly(
        "Ovens",
        str(tmp_path / "Ovens.glb"),
        str(tmp_path / "Ovens.blend"),
    )

    assert report.passes_assembly(), report.assembly_failures()
    assert report.blocked_sides == ()
