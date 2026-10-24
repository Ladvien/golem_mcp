"""Issue #18: a lathe can open an end, or revolve a wall instead of a solid.

`add_lathe` always capped both ends, so a cauldron, a basin or a stone ring
came out lidded — a reviewer read `Prop_WashCopper`'s first build as "a
washer rather than a ball", and `Prop_WashTub`/`Prop_SpringBasin` had to be
built as hand-written ring loops in `run_python` (Sanctuary, 2026-10-24).
The two options the issue proposes are here: `cap_start`/`cap_end` open an
end, and `add_shell_lathe` revolves a wall `wall_m` thick.

Every acceptance condition below is MEASURED off the built mesh — a ray
cast through the wall, boundary loops counted from the mesh's own edges —
rather than read back from the profile the op was handed.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

SEGMENT_COUNT = 24
BOWL_WALL_M = 0.03
BOWL_TOP_Z_M = 0.18
# 5% of the wall, the issue's own tolerance on the measured thickness.
WALL_TOLERANCE_M = 0.05 * BOWL_WALL_M
POSITION_TOLERANCE_M = 1.0e-6
# A cast starting exactly on a surface hits that surface again.
RAY_OFFSET_M = 1.0e-6
# How far outside the outer surface a wall probe starts.
RAY_START_M = 0.05


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


# A basin 0.4 m across and hollow: a flat floor out to r=0.15, a 45-degree
# rise out to r=0.2, and a vertical wall up to z=0.18 — so the profile
# exercises all three segment directions a shell has to offset.
BOWL_PROFILE_M = [
    (0.0, 0.0),
    (0.15, 0.0),
    (0.2, 0.05),
    (0.2, BOWL_TOP_Z_M),
]
BOWL_OUTER_TOP_RADIUS_M = 0.2
BOWL_INNER_TOP_RADIUS_M = BOWL_OUTER_TOP_RADIUS_M - BOWL_WALL_M
BOWL_SMALLEST_RADIUS_M = 0.15
# The inner corner where the 45-degree rise meets the vertical wall is
# mitred, so it sits HIGHER than the outer corner at z=0.05: one mitre
# (wall / cos 22.5 degrees) along the rise's inward normal. Measured
# 0.062424. Above that height the vertical wall is a straight stretch, and
# that is where a horizontal probe measures the wall along its normal.
BOWL_VERTICAL_WALL_START_Z_M = 0.062424

# A ring of SEGMENT_COUNT segments has a polygon's area, not a circle's:
# n/2 * sin(2*pi/n) / pi of it. Every volume asserted below carries this,
# because the mesh is what is measured, not the profile it came from.
POLYGON_AREA_FACTOR = (
    SEGMENT_COUNT / 2.0 * math.sin(math.tau / SEGMENT_COUNT) / math.pi
)

# A barrel: a straight taper, so a horizontal cast is normal to the surface
# and its length IS the wall.
BARREL_PROFILE_M = [(0.16, 0.0), (0.2, 0.1), (0.2, 0.3)]


def _linked(object_name):
    """Link the constructor's output and hand the name back.

    A constructor returns an UNLINKED object, and an object outside the
    view layer is invisible to the depsgraph — `analyze_object` would then
    measure whatever the object stored, not what exists.
    """
    from golem_blender.ops.primitives import link_into_scene

    link_into_scene(object_name)
    return object_name


def _vertices(object_name):
    return [vertex.co.copy() for vertex in bpy.data.objects[object_name].data.vertices]


def _boundary_loops(object_name):
    """Every connected group of boundary edges, as a list of edge counts.

    Counted from the mesh's own edges, not from what the op reported: one
    open end is one loop, and an accidental hole elsewhere is a second.
    """
    import bmesh

    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(bpy.data.objects[object_name].data)
        unvisited = {edge for edge in working_mesh.edges if len(edge.link_faces) == 1}
        loops = []
        while unvisited:
            seed = unvisited.pop()
            group = [seed]
            frontier = [seed]
            while frontier:
                current = frontier.pop()
                for vertex in current.verts:
                    for neighbour in vertex.link_edges:
                        if neighbour in unvisited:
                            unvisited.remove(neighbour)
                            group.append(neighbour)
                            frontier.append(neighbour)
            loops.append(len(group))
        return sorted(loops)
    finally:
        working_mesh.free()


def _min_z(object_name):
    return min(vertex.z for vertex in _vertices(object_name))


def _crossings(object_name, origin, direction):
    """Distances along a ray at which it crosses a surface, nearest first."""
    from mathutils import Vector

    direction_vector = Vector(direction).normalized()
    travelled_m = 0.0
    crossings_m = []
    while travelled_m < 2.0:
        stepped_origin = Vector(origin) + direction_vector * travelled_m
        hit, location, _normal, _face = bpy.data.objects[object_name].ray_cast(
            stepped_origin, direction_vector, distance=2.0
        )
        if not hit:
            break
        travelled_m += (Vector(location) - stepped_origin).length
        crossings_m.append(travelled_m)
        travelled_m += RAY_OFFSET_M
    return crossings_m


def _wall_along_normal(object_name, surface_point_m, inward_normal, outside=True):
    """The wall thickness measured PERPENDICULAR to the surface.

    Starts `RAY_START_M` off the outer surface along the normal and casts
    inward, so the gap between the first two crossings is the distance
    between the outer surface and the inner one along that normal — which
    is the only reading of `wall_m` a shell can be held to.
    """
    sign = -1.0 if outside else 1.0
    origin = tuple(
        coordinate + sign * RAY_START_M * normal
        for coordinate, normal in zip(surface_point_m, inward_normal, strict=True)
    )
    crossings_m = _crossings(object_name, origin, inward_normal)
    assert len(crossings_m) >= 2, (
        f"a probe at {surface_point_m} crossed the wall {len(crossings_m)} time(s), "
        f"so there is not a wall there"
    )
    return crossings_m[1] - crossings_m[0]


# The 45-degree rise, as (radius, z) at each end, for the diagonal probes.
RISE_START_M = (0.15, 0.0)
RISE_END_M = (0.2, 0.05)


def _rise_points(count=3):
    """Points on the outer 45-degree rise, short of both its ends.

    In the +X half-plane, because that is the plane the rise's own normal
    lies in: a point anywhere else has its inward normal pointing partly
    round the piece, and a cast along the XZ normal there would cross the
    surface at an angle and read a wall longer than the wall.
    """
    start_radius_m, start_z_m = RISE_START_M
    end_radius_m, end_z_m = RISE_END_M
    return [
        (
            start_radius_m + (end_radius_m - start_radius_m) * (index + 1) / (count + 1),
            0.0,
            start_z_m + (end_z_m - start_z_m) * (index + 1) / (count + 1),
        )
        for index in range(count)
    ]


# Inward normal of the 45-degree rise, in the XZ half-plane: up and toward
# the axis.
RISE_INWARD_NORMAL = (-1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0))


# --- condition 1: the measured wall is wall_m ------------------------------


def test_the_shelled_bowl_vertical_wall_measures_what_was_asked(empty_scene):
    """Condition 1: 12 rays normal to the vertical wall each cross BOWL_WALL_M."""
    from golem_blender.ops.lathe import add_shell_lathe

    bowl = _linked(
        add_shell_lathe("ShellBowl", BOWL_PROFILE_M, BOWL_WALL_M, SEGMENT_COUNT)
    )

    lowest_probe_z_m = BOWL_VERTICAL_WALL_START_Z_M + 0.005
    heights = [
        lowest_probe_z_m
        + index * (BOWL_TOP_Z_M - 0.005 - lowest_probe_z_m) / 11
        for index in range(12)
    ]
    measured_m = [
        _wall_along_normal(bowl, (0.2, 0.0, height_z_m), (-1.0, 0.0, 0.0))
        for height_z_m in heights
    ]

    worst_error_m = max(abs(thickness_m - BOWL_WALL_M) for thickness_m in measured_m)
    assert worst_error_m <= WALL_TOLERANCE_M, (
        f"measured walls {[round(value, 5) for value in measured_m]}"
    )


def test_the_shelled_bowl_floor_and_rise_measure_the_wall_too(empty_scene):
    """The offset is perpendicular to EVERY segment: floor and rise both wall_m."""
    from golem_blender.ops.lathe import add_shell_lathe

    bowl = _linked(
        add_shell_lathe("ShellBowl", BOWL_PROFILE_M, BOWL_WALL_M, SEGMENT_COUNT)
    )

    floor_m = _wall_along_normal(bowl, (0.08, 0.0, 0.0), (0.0, 0.0, -1.0))
    assert floor_m == pytest.approx(BOWL_WALL_M, abs=WALL_TOLERANCE_M), floor_m

    for surface_point_m in _rise_points():
        rise_m = _wall_along_normal(bowl, surface_point_m, RISE_INWARD_NORMAL)
        assert rise_m == pytest.approx(BOWL_WALL_M, abs=WALL_TOLERANCE_M), (
            f"the 45-degree rise measures {rise_m:.5f} at {surface_point_m}"
        )


# --- condition 2: open_top leaves the mouth open and the mesh manifold -----


def test_an_open_top_has_no_face_across_the_mouth_and_stays_manifold(empty_scene):
    """Condition 2: a ray down the axis reaches the cavity floor, not a lid."""
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.lathe import add_shell_lathe

    bowl = _linked(
        add_shell_lathe("ShellBowl", BOWL_PROFILE_M, BOWL_WALL_M, SEGMENT_COUNT)
    )

    # Nothing spans the mouth: a ray straight down the axis passes the rim
    # height (BOWL_TOP_Z_M) and stops on the cavity's floor at z = wall.
    axis_crossings_m = _crossings(bowl, (0.0, 0.0, 1.0), (0.0, 0.0, -1.0))
    assert len(axis_crossings_m) == 2, (
        f"a ray down the axis crossed {len(axis_crossings_m)} faces"
    )
    cavity_floor_z_m = 1.0 - axis_crossings_m[0]
    assert cavity_floor_z_m == pytest.approx(BOWL_WALL_M, abs=WALL_TOLERANCE_M), (
        f"the first surface under the mouth is at z={cavity_floor_z_m:.4f}: "
        f"something spans the opening at z={BOWL_TOP_Z_M}"
    )

    # Every face at the rim height is the rim ANNULUS: no vertex of one
    # reaches inside the mouth's own radius.
    vertices = _vertices(bowl)
    rim_faces = [
        polygon
        for polygon in bpy.data.objects[bowl].data.polygons
        if min(vertices[index].z for index in polygon.vertices)
        > BOWL_TOP_Z_M - POSITION_TOLERANCE_M
    ]
    assert rim_faces, "no geometry at the rim height at all"
    for polygon in rim_faces:
        for index in polygon.vertices:
            radius_m = math.hypot(vertices[index].x, vertices[index].y)
            assert radius_m >= BOWL_INNER_TOP_RADIUS_M - WALL_TOLERANCE_M, (
                f"a rim face reaches r={radius_m:.4f}, inside the mouth's "
                f"r={BOWL_INNER_TOP_RADIUS_M:.4f}"
            )

    report = analyze_object(bpy.data.objects[bowl])
    assert report.non_manifold_edge_count == 0
    assert report.boundary_edge_count == 0
    assert report.connected_component_count == 1
    assert report.self_intersecting_face_pair_count == 0
    assert report.zero_area_face_count == 0


def test_the_mouth_is_one_wall_wide_and_the_wall_thins_only_at_the_axis(empty_scene):
    """The rim is an annulus exactly `wall_m` wide — the mouth does not
    shrink to a point and the rim does not overhang the outer surface."""
    from golem_blender.ops.lathe import add_shell_lathe

    bowl = _linked(
        add_shell_lathe("ShellBowl", BOWL_PROFILE_M, BOWL_WALL_M, SEGMENT_COUNT)
    )
    top_radii_m = sorted(
        {
            round(math.hypot(vertex.x, vertex.y), 5)
            for vertex in _vertices(bowl)
            if abs(vertex.z - BOWL_TOP_Z_M) < POSITION_TOLERANCE_M
        }
    )
    assert len(top_radii_m) == 2, f"rim radii {top_radii_m}"
    assert top_radii_m[0] == pytest.approx(BOWL_INNER_TOP_RADIUS_M, abs=1.0e-6)
    assert top_radii_m[1] == pytest.approx(BOWL_OUTER_TOP_RADIUS_M, abs=1.0e-6)


# --- condition 3: cap_end=False is no cap and exactly one hole -------------


def test_an_open_end_leaves_no_cap_and_exactly_one_hole(empty_scene):
    """Condition 3: 0 cap triangles, and the hole count is exactly 1."""
    from golem_blender.ops.lathe import add_lathe

    open_barrel = _linked(
        add_lathe("OpenBarrel", BARREL_PROFILE_M, SEGMENT_COUNT, cap_end=False)
    )

    # The wall is quads. The BOTTOM still carries its fan (cap_start is
    # untouched); the top carries none, so the whole deficit is cap_end's.
    capped = _linked(add_lathe("CappedBarrel", BARREL_PROFILE_M, SEGMENT_COUNT))
    open_polygons = bpy.data.objects[open_barrel].data.polygons
    assert len([polygon for polygon in open_polygons if len(polygon.vertices) == 4]) == (
        SEGMENT_COUNT * (len(BARREL_PROFILE_M) - 1)
    )

    # Cap triangles AT THE TOP end: counted by the faces that reach the
    # axis at the top's own height, which only a fan does.
    top_z_m = max(vertex.z for vertex in _vertices(open_barrel))
    axis_pole_count = len(
        [
            vertex
            for vertex in _vertices(open_barrel)
            if abs(vertex.z - top_z_m) < POSITION_TOLERANCE_M
            and math.hypot(vertex.x, vertex.y) < POSITION_TOLERANCE_M
        ]
    )
    assert axis_pole_count == 0, "an open end still carries a pole vertex"

    # The capped version differs by exactly one fan: segment_count triangles.
    assert len(open_polygons) + SEGMENT_COUNT == len(
        bpy.data.objects[capped].data.polygons
    )

    loops = _boundary_loops(open_barrel)
    assert len(loops) == 1, f"boundary loops {loops}, expected exactly 1"
    assert loops[0] == SEGMENT_COUNT


def test_capping_both_ends_is_the_default(empty_scene):
    """The capped default did not move: no flags measures identical to both True."""
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.lathe import add_lathe

    default = _linked(add_lathe("DefaultBarrel", BARREL_PROFILE_M, SEGMENT_COUNT))
    explicit = _linked(
        add_lathe(
            "ExplicitBarrel",
            BARREL_PROFILE_M,
            SEGMENT_COUNT,
            cap_start=True,
            cap_end=True,
        )
    )

    default_report = analyze_object(bpy.data.objects[default])
    explicit_report = analyze_object(bpy.data.objects[explicit])
    assert default_report.triangle_count == explicit_report.triangle_count
    assert default_report.volume_m3 == pytest.approx(explicit_report.volume_m3)
    assert default_report.boundary_edge_count == 0
    assert default_report.non_manifold_edge_count == 0
    # The pre-change shape: the wall quads, plus one fan per capped end.
    quads = SEGMENT_COUNT * (len(BARREL_PROFILE_M) - 1)
    assert default_report.triangle_count == 2 * quads + 2 * SEGMENT_COUNT

    # An existing caller's profile already starts at z=0, and the base
    # shift must leave it exactly where it was: the ring heights are the
    # profile's own, so no golden build moves.
    ring_heights_m = sorted({round(vertex.z, 6) for vertex in _vertices(default)})
    assert ring_heights_m == sorted(
        {round(height_z_m, 6) for _, height_z_m in BARREL_PROFILE_M}
    )


def test_a_closed_profile_is_not_punched_by_an_open_flag(empty_scene):
    """A ring's own section already closes the surface, so cap_end=False is
    a no-op there rather than a hole."""
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.lathe import add_lathe

    # A stone ring: outside up, across the top, inside down, across the base.
    ring_profile_m = [(0.3, 0.0), (0.3, 0.12), (0.22, 0.12), (0.22, 0.0), (0.3, 0.0)]

    capped = _linked(add_lathe("Ring", ring_profile_m, SEGMENT_COUNT))
    open_flag = _linked(
        add_lathe("RingOpenFlag", ring_profile_m, SEGMENT_COUNT, cap_end=False)
    )

    capped_report = analyze_object(bpy.data.objects[capped])
    open_report = analyze_object(bpy.data.objects[open_flag])
    assert capped_report.boundary_edge_count == 0
    assert open_report.boundary_edge_count == 0, "cap_end=False punched the ring"
    assert open_report.non_manifold_edge_count == 0
    assert open_report.connected_component_count == 1
    assert open_report.triangle_count == capped_report.triangle_count
    # A ring is a through-hole: its volume is the annulus, not a disc.
    annular_volume_m3 = math.pi * (0.3**2 - 0.22**2) * 0.12 * POLYGON_AREA_FACTOR
    assert open_report.volume_m3 == pytest.approx(annular_volume_m3, rel=0.01)


def test_a_solid_capped_lathe_still_measures_its_own_solid(empty_scene):
    """The capped default is still the SOLID: its volume is the revolve of
    the profile's area, so the caps are really there."""
    from golem_blender.analyze.mesh_checks import analyze_object
    from golem_blender.ops.lathe import add_lathe

    barrel = _linked(add_lathe("SolidBarrel", BARREL_PROFILE_M, SEGMENT_COUNT))
    # Frustum plus cylinder: the profile's own area revolved about Z.
    frustum_volume_m3 = (
        math.pi * 0.1 / 3.0 * (0.16**2 + 0.16 * 0.2 + 0.2**2)
    ) * POLYGON_AREA_FACTOR
    cylinder_volume_m3 = math.pi * 0.2**2 * 0.2 * POLYGON_AREA_FACTOR
    report = analyze_object(bpy.data.objects[barrel])
    assert report.volume_m3 == pytest.approx(
        frustum_volume_m3 + cylinder_volume_m3, rel=0.01
    )


# --- condition 4: a wall thicker than the piece is refused by name ---------


def test_a_wall_thicker_than_the_piece_names_both_values(empty_scene):
    """Condition 4: wall_m larger than the smallest radius raises, naming both."""
    from golem_blender.ops.lathe import add_shell_lathe

    with pytest.raises(ValueError) as raised:
        add_shell_lathe(
            "TooThick", BOWL_PROFILE_M, BOWL_SMALLEST_RADIUS_M + 0.05, SEGMENT_COUNT
        )

    message = str(raised.value)
    assert "0.2" in message, message
    assert f"{BOWL_SMALLEST_RADIUS_M:g}" in message, message


def test_a_shell_profile_may_start_on_the_axis_but_a_lathe_may_not(empty_scene):
    """The basin's floor begins at radius 0; a plain lathe still refuses it.

    `add_lathe`'s positive-radius rule is unchanged (a cap supplies the
    pole), and `add_shell_lathe` accepts 0 because that IS a bowl's floor.
    """
    from golem_blender.ops.lathe import add_lathe, add_shell_lathe

    with pytest.raises(ValueError) as raised:
        add_lathe("OnAxis", [(0.0, 0.0), (0.2, 0.1)], SEGMENT_COUNT)
    assert "must be positive" in str(raised.value)

    bowl = _linked(
        add_shell_lathe("OnAxisShell", BOWL_PROFILE_M, BOWL_WALL_M, SEGMENT_COUNT)
    )
    assert _min_z(bowl) == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)


def test_an_out_of_order_profile_is_refused(empty_scene):
    """Edge case: non-monotonic z is a named error, not folded geometry."""
    from golem_blender.ops.lathe import add_lathe

    with pytest.raises(ValueError) as raised:
        add_lathe("Folded", [(0.2, 0.3), (0.2, 0.1)], SEGMENT_COUNT)

    assert "ordered by height" in str(raised.value)
    assert "0.1" in str(raised.value) and "0.3" in str(raised.value)


# --- condition 5: base at z=0 ----------------------------------------------


def test_both_ops_put_the_lowest_point_at_z_zero(empty_scene):
    """Condition 5: a profile given 3.5 m up still comes back based at 0."""
    from golem_blender.ops.lathe import add_lathe, add_shell_lathe

    raised_solid_m = [
        (radius_m, height_z_m + 3.5) for radius_m, height_z_m in BARREL_PROFILE_M
    ]
    raised_bowl_m = [
        (radius_m, height_z_m + 3.5) for radius_m, height_z_m in BOWL_PROFILE_M
    ]

    # add_lathe keeps its positive-radius rule, so the solid gets the
    # barrel's profile and the shell gets the bowl's (which starts on the
    # axis, as a bowl's floor does).
    solid = _linked(add_lathe("HighSolid", raised_solid_m, SEGMENT_COUNT))
    shell = _linked(
        add_shell_lathe("HighShell", raised_bowl_m, BOWL_WALL_M, SEGMENT_COUNT)
    )

    assert _min_z(solid) == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
    assert _min_z(shell) == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
