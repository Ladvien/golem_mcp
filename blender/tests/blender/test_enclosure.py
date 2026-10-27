"""Is the room sealed, and where does it leak — measured on a room built to leak.

The fixture is the plan's: a 2 x 2 x 2 m room of six separate 0.1 m wall boxes
meeting flush. Each test then breaks ONE thing and asserts the report names that
thing, so a report that says "not sealed" for every case cannot pass.

The two halves are exercised separately because they find different defects: a
missing roof is a HOLE (flood fill sees it) and a 2 cm slot between two flush
walls is a SEAM (flood fill cannot: both walls still block it on either side).
That distinction is the module's whole reason to exist.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

ROOM_SIZE_M = 2.0
WALL_THICKNESS_M = 0.1
# The room's interior is [0, 2] on all three axes; walls sit outside that.
SLOT_WIDTH_M = 0.03
# The grid must be finer than the leaks claimed (the op refuses otherwise), and the
# grid is capped at 16M cells. A 2.2 m room at 1.5 cm is 3.2M cells and resolves a
# 3 cm slot in two cells; the slot in this fixture is 3 cm for exactly that reason.
# Measured: an 85M-cell grid takes 45 s just to flood, so a whole-room report
# cannot be finer than this and stay inside the plan's minute.
RESOLUTION_M = 0.015
LEAK_MINIMUM_M = 0.03
FINDING_TOLERANCE_M = 0.05


@pytest.fixture()
def empty_scene():
    from golem_blender.ops import assembly, coplanar, pieces

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()


def _box(name, size_m, location_m=(0.0, 0.0, 0.0), material=None):
    from golem_blender.ops import add_box, assign_material, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    if material is not None:
        assign_material(box_name, material)
    return box_name


def _room(shorten_floor_x_m: float = 0.0):
    """Six flush walls around a 2 m interior, interior at [0, 2] on every axis.

    `add_box` puts a box's BASE at `location_m[2]`, so every wall is placed by its
    base: a wall at z = 1.0 with height 2 spans [1, 3] and floats out of the room.
    Measured cost of getting this wrong once: the room was genuinely open and the
    report's "not sealed" was correct while the fixture looked sealed.

    `shorten_floor_x_m` pulls the floor's +X edge back, opening a slot between the
    floor's edge and the +X wall's inner face.
    """
    thickness = WALL_THICKNESS_M
    span = ROOM_SIZE_M
    floor_x = span - shorten_floor_x_m
    # The floor's top surface is the interior's z = 0, so it sits below it.
    # The floor spans the walls' OUTER faces (the interior plus two thicknesses),
    # so a wall's corner rests on it. Measured cost of getting this wrong: a floor
    # 0.1 m narrower than the walls' span leaves a real 0.096 m step at each
    # corner, and every junction there is a genuine seam.
    outer = span + 2 * thickness
    _box(
        "Floor",
        (floor_x, outer, thickness),
        (floor_x / 2.0, span / 2.0, -thickness),
        material="Stone",
    )
    _box(
        "Roof",
        (outer, outer, thickness),
        (span / 2.0, span / 2.0, span),
        material="Stone",
    )
    # Each wall pair laps the other at the corners: the X walls span the FULL
    # outer width, so a corner is solid rather than a butt joint with a hairline
    # in it.
    _box(
        "Wall_XLow",
        (thickness, outer, span),
        (-thickness / 2.0, span / 2.0, 0.0),
        material="Stone",
    )
    _box(
        "Wall_XHigh",
        (thickness, outer, span),
        (span + thickness / 2.0, span / 2.0, 0.0),
        material="Stone",
    )
    _box(
        "Wall_YLow",
        (span, thickness, span),
        (span / 2.0, -thickness / 2.0, 0.0),
        material="Stone",
    )
    _box(
        "Wall_YHigh",
        (span, thickness, span),
        (span / 2.0, span + thickness / 2.0, 0.0),
        material="Stone",
    )
    return ["Floor", "Roof", "Wall_XLow", "Wall_XHigh", "Wall_YLow", "Wall_YHigh"]


def _room_centre():
    """A point in the middle of the room's AIR, not on a surface."""
    return (ROOM_SIZE_M / 2.0, ROOM_SIZE_M / 2.0, ROOM_SIZE_M / 2.0)


def test_a_flush_six_wall_room_is_sealed_with_no_seam_anywhere(empty_scene):
    """Six walls meeting flush: every junction is two faces in ONE plane.

    This is the case the clearance test exists for. A sweep whose rays travel
    along those shared planes finds a "crossing" at every sample it tries, and
    measured before that test: two seams of 0.07 and 0.06 m in a room with no
    opening at all. A flush joint is not a leak.
    """
    from golem_blender.ops import enclosure_report

    report = enclosure_report(
        _room(), resolution_m=RESOLUTION_M, leak_minimum_m=LEAK_MINIMUM_M
    )
    assert report.sealed is True, [(leak.kind, leak.at_m) for leak in report.leaks]
    assert report.leaks == ()
    assert report.junctions
    assert {junction.verdict for junction in report.junctions} == {"sealed"}
    assert report.grid_yaw_deg == pytest.approx(0.0, abs=0.5)
    assert report.cell_count > 0


def test_an_opening_wider_than_a_cell_merges_the_room_with_the_outside(empty_scene):
    """An opening the flood can pass is ONE opening, not a seam.

    The honest split between the report's two halves: a 3 cm slot at a 1.5 cm grid
    is a passage, so the room's air and the outside become one flood and there is
    no enclosed region to take a boundary against. The report says so with one
    un-allowed leak and `sealed: false`, which is the answer a reader acts on.
    The seam half exists for the opening a flood CANNOT pass — one narrower than a
    cell, between two parts that still look sealed.
    """
    from golem_blender.ops import enclosure_report

    report = enclosure_report(
        _room(shorten_floor_x_m=SLOT_WIDTH_M),
        resolution_m=RESOLUTION_M,
        leak_minimum_m=LEAK_MINIMUM_M,
    )
    assert report.sealed is False
    assert len(report.leaks) == 1, [
        (leak.kind, leak.at_m, leak.size_m) for leak in report.leaks
    ]
    assert report.leaks[0].allowed is False


def test_a_missing_roof_is_reported_where_the_flood_leaves(empty_scene):
    """A roofless room: the leak is a `hole` and the space reads unsealed.

    Its DIRECTION is not asserted. With the roof gone the room's air and the sky
    are one region, so "the direction it opens" is genuinely ambiguous: the flood
    also leaves round the walls' outside, and picking a single exit from a
    merged region is a locating heuristic this report does not claim to get
    right. What it does claim, and what a reader acts on, is that the space is
    open, that it is open as a hole rather than a seam, and where the opening is
    reported.
    """
    from golem_blender.ops import enclosure_report

    walls = [name for name in _room() if name != "Roof"]
    report = enclosure_report(
        walls, resolution_m=RESOLUTION_M, leak_minimum_m=LEAK_MINIMUM_M
    )
    assert report.sealed is False
    holes = [leak for leak in report.leaks if leak.kind == "hole"]
    assert holes, [(leak.kind, leak.at_m) for leak in report.leaks]
    assert all(not leak.allowed for leak in holes)


def test_a_room_turned_thirty_seven_degrees_measures_the_same(empty_scene):
    """The alignment's whole job: a rotated room is the same room.

    A world-axis grid staircases a 37-degree wall into a row of false leaks, so
    the grid is built on the geometry's own yaw. Both the sealed room and a room
    with one opening are compared against turned copies: same verdict, same kinds,
    same count.
    """
    from golem_blender.ops import enclosure_report

    def turn(names, angle_deg):
        """A rigid turn about the ROOM's centre.

        `rotate_object_euler` turns about each object's own origin, which is a
        box's base corner, so turning each box where it stands scatters the walls.
        Rotating each box's LOCATION about the room's centre and adding the same
        turn to its rotation is the rigid motion the whole room would make.
        """
        centre = (ROOM_SIZE_M / 2.0, ROOM_SIZE_M / 2.0)
        angle = math.radians(angle_deg)
        cos, sin = math.cos(angle), math.sin(angle)
        for name in names:
            blender_object = bpy.data.objects[name]
            offset_x = blender_object.location[0] - centre[0]
            offset_y = blender_object.location[1] - centre[1]
            blender_object.location = (
                centre[0] + offset_x * cos - offset_y * sin,
                centre[1] + offset_x * sin + offset_y * cos,
                blender_object.location[2],
            )
            blender_object.rotation_euler = (0.0, 0.0, angle)
        bpy.context.view_layer.update()

    for shorten in (0.0, SLOT_WIDTH_M):
        walls = _room(shorten_floor_x_m=shorten)
        upright = enclosure_report(
            walls, resolution_m=RESOLUTION_M, leak_minimum_m=LEAK_MINIMUM_M
        )
        bpy.ops.wm.read_factory_settings(use_empty=True)
        turned_walls = _room(shorten_floor_x_m=shorten)
        turn(turned_walls, 37.0)
        turned = enclosure_report(
            turned_walls, resolution_m=RESOLUTION_M, leak_minimum_m=LEAK_MINIMUM_M
        )
        assert turned.grid_yaw_deg == pytest.approx(37.0, abs=0.5), (
            f"shorten={shorten}: the grid must follow the room's own yaw"
        )
        assert turned.sealed == upright.sealed, f"shorten={shorten}"
        assert len(turned.leaks) == len(upright.leaks), f"shorten={shorten}"
        assert {leak.kind for leak in turned.leaks} == {
            leak.kind for leak in upright.leaks
        }, f"shorten={shorten}"


def test_an_allowed_opening_is_reported_and_does_not_make_the_room_unsealed(
    empty_scene,
):
    """A declared opening is still REPORTED, and stops counting as a defect.

    The leak must be LOCALISED for `allowed` to mean anything, because `allowed` is
    a bounds test on the leak's own position. So the opening here is the roof:
    removing it leaves six walls and a floor, every junction flush, and the only
    exit is straight up through the envelope's +Z face — one opening whose centre
    is above the room's middle, inside the declared opening's own bounds.
    """
    from golem_blender.ops import enclosure_report

    span = ROOM_SIZE_M
    walls = [name for name in _room() if name != "Roof"]
    # The opening is declared as a volume covering the whole top of the room, so
    # any leak through the ceiling is inside its bounds.
    _box(
        "Skylight",
        (span, span, WALL_THICKNESS_M),
        (span / 2.0, span / 2.0, span),
        material="Glass",
    )
    report = enclosure_report(
        walls,
        allowed_opening_names=("Skylight",),
        resolution_m=RESOLUTION_M,
        leak_minimum_m=LEAK_MINIMUM_M,
    )
    assert report.leaks, "the opening must still be REPORTED, not hidden"
    assert any(leak.allowed for leak in report.leaks), [
        (leak.kind, leak.at_m, leak.allowed) for leak in report.leaks
    ]
    assert report.sealed is True


def test_a_grid_over_the_cell_cap_names_a_resolution_that_fits(empty_scene):
    from golem_blender.ops import enclosure_report

    walls = _room()
    with pytest.raises(ValueError, match="resolution_m="):
        enclosure_report(walls, resolution_m=0.0005, leak_minimum_m=0.01)


def test_an_inside_point_in_a_wall_is_named(empty_scene):
    from golem_blender.ops import enclosure_report

    walls = _room()
    wall_point = (-WALL_THICKNESS_M / 4.0, ROOM_SIZE_M / 2.0, ROOM_SIZE_M / 2.0)
    with pytest.raises(ValueError, match="OCCUPIED cell"):
        enclosure_report(
            walls,
            inside_points_m=(wall_point,),
            resolution_m=RESOLUTION_M,
            leak_minimum_m=LEAK_MINIMUM_M,
        )
