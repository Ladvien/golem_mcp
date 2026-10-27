"""The generalized winding number and the `audit_winding` op, on geometry whose answer is known by construction.

Why this module is in the Blender tier and not `tests/pure`: the arithmetic
in `analyze/winding.py` needs numpy, and this repo's dev venv deliberately
has none (measured: `import numpy` fails in `blender/.venv`); numpy is
imported inside the functions exactly as `analyze/enclosure.py` does, and
only Blender's Python can exercise it.

Every case here has a right answer that does not come from this module: a
cube's faces are outward because they were written outward, a reversed
cube's are inward because the same list was reversed, a lone quad has no
inside at all. And the open tube is the case the report that started this
needed — a garment has no closed volume to sign, so signed volume cannot
answer for it.

The margin test measures the LOWEST |score| of a face that is correct by
construction. That number is what `WINDING_DECISION_MARGIN` must sit under,
and it is recorded in the constant's own comment.
"""

import numpy as np
import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

from golem_blender.analyze.winding import (
    INWARD,
    OUTWARD,
    UNDECIDED,
    WINDING_DECISION_MARGIN,
    area_weighted_fractions,
    classify_faces,
    component_is_closed,
    face_orientation_scores,
    query_face_sample,
    signed_volume_m3,
    triangle_components,
    triangle_solid_angles,
)

CUBE_CORNER = 0.5
# Measured scores on a cube are 1.0 to within float64 summation error; this
# is far tighter than the 0.1 decision margin, so a scoring BUG (an own-face
# contribution left in, a sign flipped) cannot hide under it.
CUBE_SCORE_TOLERANCE = 1e-6
TUBE_RADIUS_M = 0.1
TUBE_LENGTH_M = 0.4
TUBE_AROUND = 32
TUBE_RINGS = 8
# The lowest score of a face that is correct by construction, measured
# 2026-10-27 on the 32-sided, 8-ring open tube below (Blender 5.2.0 LTS):
# the TOP and BOTTOM rim rings, at 0.5714. The middle ring, farthest from
# every rim, reads 0.7961. See WINDING_DECISION_MARGIN's comment.
MEASURED_LOWEST_RIM_SCORE = 0.5714
MEASURED_LOWEST_MIDDLE_RING_SCORE = 0.7961


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _cube_triangles(corner: float = CUBE_CORNER) -> np.ndarray:
    """A cube as 12 outward-wound triangles (counter-clockwise seen from outside), (12, 3, 3)."""
    vertices = np.array(
        [
            [-corner, -corner, -corner],
            [corner, -corner, -corner],
            [corner, corner, -corner],
            [-corner, corner, -corner],
            [-corner, -corner, corner],
            [corner, -corner, corner],
            [corner, corner, corner],
            [-corner, corner, corner],
        ]
    )
    faces = np.array(
        [
            [0, 2, 1],
            [0, 3, 2],  # bottom, normal -Z
            [4, 5, 6],
            [4, 6, 7],  # top, +Z
            [0, 1, 5],
            [0, 5, 4],  # front, -Y
            [3, 7, 6],
            [3, 6, 2],  # back, +Y
            [0, 4, 7],
            [0, 7, 3],  # left, -X
            [1, 2, 6],
            [1, 6, 5],  # right, +X
        ]
    )
    return vertices[faces]


def _reversed(corners: np.ndarray) -> np.ndarray:
    return corners[:, ::-1, :]


def _tube_triangles(around: int = TUBE_AROUND, rings: int = TUBE_RINGS) -> np.ndarray:
    """Vertex indices (T, 3) of an open tube (no caps) of quads split into triangles."""
    triangles = []
    for ring in range(rings):
        for k in range(around):
            n = (k + 1) % around
            a = ring * around + k
            b = ring * around + n
            c = (ring + 1) * around + n
            d = (ring + 1) * around + k
            triangles.append([a, b, c])
            triangles.append([a, c, d])
    return np.array(triangles)


def _tube_vertices(around: int = TUBE_AROUND, rings: int = TUBE_RINGS) -> np.ndarray:
    """The tube's ring vertices, (ring * around + k, 3)."""
    angles = 2.0 * np.pi * np.arange(around) / around
    heights = np.linspace(0.0, TUBE_LENGTH_M, rings + 1)
    ring_points = np.stack(
        [
            TUBE_RADIUS_M * np.cos(angles),
            TUBE_RADIUS_M * np.sin(angles),
            np.zeros(around),
        ],
        axis=1,
    )
    return np.array([ring_points + [0.0, 0.0, height] for height in heights]).reshape(
        -1, 3
    )


def _tube(
    around: int = TUBE_AROUND, rings: int = TUBE_RINGS, outward: bool = True
) -> np.ndarray:
    """An open tube's triangle corners, (T, 3, 3)."""
    corners = _tube_vertices(around, rings)[_tube_triangles(around, rings)]
    return corners if outward else _reversed(corners)


# --- the arithmetic -------------------------------------------------------


def test_every_face_of_a_cube_scores_outward():
    corners = _cube_triangles()
    scores = face_orientation_scores(corners, np.arange(len(corners)))
    assert np.allclose(scores, 1.0, atol=CUBE_SCORE_TOLERANCE), scores


def test_the_same_cube_reversed_scores_inward():
    corners = _reversed(_cube_triangles())
    scores = face_orientation_scores(corners, np.arange(len(corners)))
    assert np.allclose(scores, -1.0, atol=CUBE_SCORE_TOLERANCE), scores


def test_a_lone_quad_is_undecided():
    corners = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]]])
    scores = face_orientation_scores(corners, np.array([0]))
    assert abs(float(scores[0])) < WINDING_DECISION_MARGIN, scores
    assert classify_faces(scores)[0] == UNDECIDED


def test_an_open_tube_is_outward_and_reversed_is_inward():
    outward = _tube()
    scores = face_orientation_scores(outward, np.arange(len(outward)))
    assert np.all(scores > WINDING_DECISION_MARGIN), scores.min()

    inverted = _tube(outward=False)
    inverted_scores = face_orientation_scores(inverted, np.arange(len(inverted)))
    assert np.all(inverted_scores < -WINDING_DECISION_MARGIN), inverted_scores.max()


def test_the_margin_clears_the_lowest_score_of_a_face_correct_by_construction():
    """The measurement `WINDING_DECISION_MARGIN` is set from.

    A tube's middle-ring faces are the ones farthest from any rim, so they
    carry the LOWEST |score| of any face that is right by construction —
    every other face of a correct open shell is nearer a closed
    neighbourhood and scores higher. The margin must sit under this, or a
    correct garment would be reported undecided.
    """
    corners = _tube()
    scores = face_orientation_scores(corners, np.arange(len(corners)))
    lowest = float(scores.min())
    assert lowest > WINDING_DECISION_MARGIN, (
        f"the lowest score of a correct open tube is {lowest:.4f}, at or "
        f"under WINDING_DECISION_MARGIN={WINDING_DECISION_MARGIN}: a correct "
        f"garment would read undecided"
    )
    # The measured values, pinned so a change to the arithmetic is visible.
    assert lowest == pytest.approx(MEASURED_LOWEST_RIM_SCORE, abs=5e-4)
    middle_ring = np.isin(np.arange(len(corners)) // (2 * TUBE_AROUND), (2, 3, 4, 5))
    assert float(scores[middle_ring].min()) == pytest.approx(
        MEASURED_LOWEST_MIDDLE_RING_SCORE, abs=5e-4
    )


def test_two_disconnected_tubes_are_measured_apart():
    around, rings = 12, 2
    outward = _tube(around=around, rings=rings, outward=True)
    inverted = _tube(around=around, rings=rings, outward=False) + np.array(
        [1.0, 0.0, 0.0]
    )
    corners = np.concatenate([outward, inverted])
    # The second tube is a separate set of vertices at an offset, so its
    # index block starts after the first tube's.
    first_indices = _tube_triangles(around, rings)
    second_indices = first_indices + len(_tube_vertices(around, rings))
    component = triangle_components(np.concatenate([first_indices, second_indices]))
    scores = face_orientation_scores(corners, np.arange(len(corners)))
    classified = classify_faces(scores)

    first = component == component[0]
    second = component != component[0]
    assert classified[first].tolist() == [OUTWARD] * int(first.sum())
    assert classified[second].tolist() == [INWARD] * int(second.sum())
    assert area_weighted_fractions(corners[first], classified[first])[
        "outward_area_fraction"
    ] == pytest.approx(1.0, abs=1e-9)
    assert area_weighted_fractions(corners[second], classified[second])[
        "inward_area_fraction"
    ] == pytest.approx(1.0, abs=1e-9)


def test_signed_volume_signs_the_solid():
    cube = _cube_triangles()
    assert signed_volume_m3(cube) == pytest.approx((2 * CUBE_CORNER) ** 3, rel=1e-9)
    assert signed_volume_m3(_reversed(cube)) == pytest.approx(
        -((2 * CUBE_CORNER) ** 3), rel=1e-9
    )


def test_two_coplanar_triangles_sharing_an_edge_score_zero():
    """A flat patch with no other geometry has no inside: every face reads 0.

    This is the failure the coplanar guard in `triangle_solid_angles`
    defends: with y = 0 and x < 0 an unguarded atan2 returns exactly π for
    a point on the plane but outside the triangle, which would sum to a
    full 4π and call a flat sheet outward.
    """
    corners = np.array(
        [
            [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
            [[0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        ]
    )
    scores = face_orientation_scores(corners, np.arange(2))
    assert np.allclose(scores, 0.0, atol=1e-9), scores
    assert classify_faces(scores).tolist() == [UNDECIDED, UNDECIDED]


def test_the_solid_angle_of_a_triangle_approaches_half_a_turn_from_the_front():
    """One triangle, a query point a millimetre in front of its centroid.

    A FINITE triangle only subtends a whole half-space as the point reaches
    its face: from 5 m away the same triangle subtends 0.078 sr, not 2π
    (measured). The limit is what the ±2π claim in `face_orientation_scores`
    rests on, so this measures the limit.
    """
    corners = np.array([[[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [0.0, 1.0, 0.0]]])
    just_in_front = triangle_solid_angles(np.array([[0.0, 1.0 / 3.0, 1.0e-3]]), corners)
    just_behind = triangle_solid_angles(np.array([[0.0, 1.0 / 3.0, -1.0e-3]]), corners)
    # Counter-clockwise seen from +Z means the normal is +Z: a point at +Z
    # is IN FRONT of it, and the winding there is negative.
    # 1 mm in front of the centroid of a 2 m triangle: 6.2697 against the
    # 6.2832 limit, a 0.2% shortfall that closes as the point reaches the
    # face. This is the measurement, not a tolerance chosen to fit.
    assert float(just_in_front[0, 0]) == pytest.approx(-6.2697, abs=5e-4)
    assert float(just_behind[0, 0]) == pytest.approx(6.2697, abs=5e-4)
    far_behind = triangle_solid_angles(np.array([[0.0, 1.0 / 3.0, -5.0]]), corners)
    assert 0.0 < float(far_behind[0, 0]) < 0.1, far_behind


def test_a_closed_shell_reads_one_inside_and_zero_outside():
    """The winding number itself, not just the orientation score."""
    cube = _cube_triangles()
    inside = triangle_solid_angles(np.zeros((1, 3)), cube).sum() / (4 * np.pi)
    outside = triangle_solid_angles(np.array([[5.0, 5.0, 5.0]]), cube).sum() / (
        4 * np.pi
    )
    assert float(inside.sum()) == pytest.approx(1.0, abs=1e-9)
    assert abs(float(outside.sum())) < 1e-9


def test_components_and_closedness():
    cube = _cube_triangles()
    vertices = np.unique(cube.reshape(-1, 3), axis=0)
    index_of = {tuple(corner): i for i, corner in enumerate(vertices)}
    closed_triangles = np.array(
        [[index_of[tuple(corner)] for corner in face] for face in cube]
    )
    assert component_is_closed(closed_triangles, np.ones(12, dtype=bool)) is True
    assert component_is_closed(closed_triangles, np.arange(12) < 8) is False, (
        "eight of a cube's twelve triangles leave a hole and are not closed"
    )

    tube_triangles = _tube_triangles(around=8, rings=2)
    assert triangle_components(tube_triangles).tolist() == [0] * len(tube_triangles)
    assert (
        component_is_closed(tube_triangles, np.ones(len(tube_triangles), dtype=bool))
        is False
    ), "an open tube has two rim loops, so it is not closed"


def test_the_sample_is_evenly_spread_and_bounded():
    sample = query_face_sample(1000, 10)
    assert len(sample) == 10
    assert sample[0] == 0 and sample[-1] == 999
    assert len(query_face_sample(5, 10)) == 5
    assert len(query_face_sample(0, 10)) == 0
    with pytest.raises(ValueError, match="limit must be positive"):
        query_face_sample(10, 0)


def test_area_fractions_sum_to_one():
    corners = _tube()
    scores = face_orientation_scores(corners, np.arange(len(corners)))
    fractions = area_weighted_fractions(corners, classify_faces(scores))
    assert sum(fractions.values()) == pytest.approx(1.0, abs=1e-12)
    assert fractions["outward_area_fraction"] == pytest.approx(1.0, abs=1e-9)


# --- the op --------------------------------------------------------------


def _audit(object_name: str):
    from golem_blender.ops.winding import audit_winding

    return audit_winding(object_name)


def _reversed_box(name: str) -> str:
    """A `add_box` cube whose faces are all reversed by bmesh, so it is inside out."""
    import bmesh

    from golem_blender.ops.primitives import add_box, link_into_scene

    box = add_box(name, 1.0, 1.0, 1.0)
    link_into_scene(box)
    mesh = bpy.data.objects[box].data
    working = bmesh.new()
    try:
        working.from_mesh(mesh)
        bmesh.ops.reverse_faces(working, faces=list(working.faces))
        working.to_mesh(mesh)
    finally:
        working.free()
    mesh.update()
    return box


def test_a_box_audits_outward_and_closed(empty_scene):
    from golem_blender.ops.primitives import add_box, link_into_scene

    box = link_into_scene(add_box("crate", 1.0, 1.0, 1.0))
    report = _audit(box)

    assert report.outward_area_fraction == pytest.approx(1.0, abs=1e-9)
    assert report.inward_area_fraction == pytest.approx(0.0, abs=1e-9)
    assert report.inward_face_indices == ()
    assert len(report.components) == 1
    component = report.components[0]
    assert component.closed is True
    assert component.signed_volume_m3 == pytest.approx(1.0, rel=1e-6)
    assert component.inward_area_fraction == pytest.approx(0.0, abs=1e-9)


def test_a_reversed_box_audits_inward_with_negative_volume(empty_scene):
    box = _reversed_box("crate_inside_out")
    report = _audit(box)

    assert report.inward_area_fraction == pytest.approx(1.0, abs=1e-9)
    assert report.outward_area_fraction == pytest.approx(0.0, abs=1e-9)
    assert len(report.inward_face_indices) > 0
    assert report.inward_face_indices[0] < report.triangle_count
    assert report.components[0].signed_volume_m3 == pytest.approx(-1.0, rel=1e-6)


def test_a_negative_scale_reads_inverted_as_the_gpu_draws_it(empty_scene):
    """Mirroring an object turns it inside out on screen; the audit must agree."""
    from golem_blender.ops.primitives import add_box, link_into_scene

    box = link_into_scene(add_box("mirrored", 1.0, 1.0, 1.0))
    bpy.data.objects[box].scale = (-1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    report = _audit(box)
    assert report.inward_area_fraction == pytest.approx(1.0, abs=1e-9)


def test_an_armature_is_refused(empty_scene):
    from golem_blender.ops.rigging import BoneSpec, add_armature

    armature = add_armature(
        "rig", (BoneSpec(name="root", head_m=(0.0, 0.0, 0.0), tail_m=(0.0, 0.0, 1.0)),)
    )
    with pytest.raises(TypeError, match="ARMATURE|MESH"):
        _audit(armature)


def test_an_empty_mesh_is_refused(empty_scene):
    from golem_blender.ops.primitives import link_into_scene

    mesh = bpy.data.meshes.new("nothing")
    nothing = bpy.data.objects.new("nothing", mesh)
    bpy.context.scene.collection.objects.link(nothing)
    link_into_scene("nothing")
    with pytest.raises(ValueError, match="no faces"):
        _audit("nothing")


def test_the_analyzer_reports_the_facing_without_failing_an_open_shell(empty_scene):
    """A reversed open tube: the gate REPORTS the inward area and does not fail on it.

    Rooms and interiors face inward by design, so this reading is
    information, not a verdict — which is why the failure list must be
    unchanged from the correctly-wound tube's. The garment tools are what
    fail on it.
    """
    from golem_blender.analyze import MeshBudget, analyze_object
    from golem_blender.ops.primitives import link_into_scene

    def tube(name: str, reversed_faces: bool):
        import bmesh

        mesh = bpy.data.meshes.new(name)
        around, rings = 24, 6
        angles = [2 * np.pi * k / around for k in range(around)]
        vertices = [
            (TUBE_RADIUS_M * np.cos(angle), TUBE_RADIUS_M * np.sin(angle), z)
            for z in np.linspace(0.0, TUBE_LENGTH_M, rings + 1)
            for angle in angles
        ]
        faces = [
            (
                ring * around + k,
                ring * around + (k + 1) % around,
                (ring + 1) * around + (k + 1) % around,
                (ring + 1) * around + k,
            )
            for ring in range(rings)
            for k in range(around)
        ]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        if reversed_faces:
            working = bmesh.new()
            try:
                working.from_mesh(mesh)
                bmesh.ops.reverse_faces(working, faces=list(working.faces))
                working.to_mesh(mesh)
            finally:
                working.free()
            mesh.update()
        scene_object = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(scene_object)
        link_into_scene(name)
        bpy.context.view_layer.update()
        return scene_object

    correct = analyze_object(tube("tube_correct", False))
    inverted_object = tube("tube_inverted", True)
    inverted = analyze_object(inverted_object)

    assert correct.inward_area_fraction == pytest.approx(0.0, abs=1e-9)
    assert inverted.inward_area_fraction >= 0.9
    budget = MeshBudget(allow_boundary_edges=True, maximum_component_count=1)
    assert inverted.failures(budget) == correct.failures(budget), (
        "the facing reading must not change the gate's verdict: "
        f"{inverted.failures(budget)}"
    )

    from golem_blender.harness import facing_summary_lines

    assert facing_summary_lines(inverted) == [
        (
            f"  facing: inward {inverted.inward_area_fraction:.0%} of area, "
            f"undecided {inverted.undecided_area_fraction:.0%}"
        )
    ]
    assert facing_summary_lines(correct) == []


def test_a_mesh_over_the_facing_limit_says_it_was_not_measured(empty_scene):
    """`-1.0` and `0.0` are different answers, and the gate text keeps them apart."""
    from golem_blender.analyze.mesh_checks import (
        WINDING_GATE_TRIANGLE_LIMIT,
        MeshReport,
    )
    from golem_blender.harness import facing_summary_lines

    unmeasured = MeshReport(
        object_name="big",
        triangle_count=WINDING_GATE_TRIANGLE_LIMIT + 1,
        non_manifold_edge_count=0,
        boundary_edge_count=0,
        zero_area_face_count=0,
        non_finite_coordinate_count=0,
        connected_component_count=1,
        duplicate_vertex_pair_count=0,
        self_intersecting_face_pair_count=0,
        flipped_normal_triangle_count=0,
        inward_area_fraction=-1.0,
        undecided_area_fraction=-1.0,
    )
    assert facing_summary_lines(unmeasured) == [
        (
            f"  facing: not measured ({WINDING_GATE_TRIANGLE_LIMIT + 1} triangles > "
            f"{WINDING_GATE_TRIANGLE_LIMIT})"
        )
    ]
