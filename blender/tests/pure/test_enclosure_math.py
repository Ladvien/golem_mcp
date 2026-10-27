"""The two pure decisions an enclosure report makes, and the cap arithmetic.

`dominant_yaw_deg` and `cluster_cells` are the parts of `analyze/enclosure.py`
that can be wrong without bpy noticing: a mis-weighted histogram aligns the grid
to nothing, and a 6-connected cluster splits one crack into a row of leaks. Both
are pure, so both are pinned here.

`resolution_that_fits` is the arithmetic behind the cell cap, and it has to count
the PADDING: a resolution computed from the unpadded box still allocates past the
cap once the grid is built.
"""

import math

import pytest

from golem_blender.analyze.enclosure import (
    GRID_PADDING_CELLS,
    MAXIMUM_ENCLOSURE_CELLS,
    aligned_point,
    cluster_cells,
    dominant_yaw_deg,
    flood_neighbours,
    resolution_that_fits,
    world_point,
    YAW_BIN_DEG,
)


def _wall_normal(angle_deg):
    radians = math.radians(angle_deg)
    return (math.cos(radians), math.sin(radians), 0.0)


def test_a_wall_at_thirty_seven_degrees_reads_thirty_seven():
    faces = [(_wall_normal(37.0), 2.0), (_wall_normal(127.0), 2.0)]
    assert dominant_yaw_deg(faces) == pytest.approx(37.0, abs=YAW_BIN_DEG)


def test_the_perpendicular_wall_votes_for_the_same_rotation():
    """Mod 90: a room's walls are perpendicular in pairs and agree."""
    one_way = dominant_yaw_deg([(_wall_normal(37.0), 2.0)])
    both = dominant_yaw_deg([(_wall_normal(37.0), 2.0), (_wall_normal(127.0), 2.0)])
    assert one_way == pytest.approx(both, abs=YAW_BIN_DEG)


def test_a_floor_does_not_vote_itself_back_to_world_axes():
    """A big floor's normal is +Z, whose azimuth is 0 by accident."""
    faces = [((0.0, 0.0, 1.0), 100.0), (_wall_normal(37.0), 2.0)]
    assert dominant_yaw_deg(faces) == pytest.approx(37.0, abs=YAW_BIN_DEG)


def test_area_decides_between_two_disagreeing_walls():
    faces = [(_wall_normal(10.0), 100.0), (_wall_normal(50.0), 1.0)]
    assert dominant_yaw_deg(faces) == pytest.approx(10.0, abs=YAW_BIN_DEG)


def test_no_usable_face_is_zero_not_an_error():
    assert dominant_yaw_deg([]) == 0.0
    assert dominant_yaw_deg([((0.0, 0.0, 1.0), 5.0)]) == 0.0
    assert dominant_yaw_deg([((0.0, 0.0, 0.0), 5.0)]) == 0.0


def test_two_separated_blobs_are_two_clusters():
    cells = {(0, 0, 0), (1, 0, 0), (5, 5, 5), (5, 5, 6)}
    components = cluster_cells(cells)
    assert len(components) == 2
    assert components[0] == [(0, 0, 0), (1, 0, 0)]
    assert components[1] == [(5, 5, 5), (5, 5, 6)]


def test_cells_touching_only_at_an_edge_are_one_cluster():
    """26-connectivity: a leak is a surface defect and an edge is still a join."""
    components = cluster_cells({(0, 0, 0), (1, 1, 0)})
    assert len(components) == 1


def test_the_components_come_back_deterministically():
    cells = {(3, 0, 0), (0, 0, 0), (9, 9, 9)}
    first = cluster_cells(cells)
    second = cluster_cells(set(cells))
    assert first == second
    assert [component[0] for component in first] == sorted(
        component[0] for component in first
    )


def test_an_empty_cell_set_has_no_components():
    assert cluster_cells(set()) == []


@pytest.mark.parametrize("yaw_deg", (0.0, 37.0, -120.0, 359.0))
def test_the_aligned_frame_round_trips(yaw_deg):
    origin = (1.5, -2.0, 0.25)
    point = (3.25, 4.5, 1.75)
    aligned = aligned_point(point, yaw_deg, origin)
    back = world_point(aligned, yaw_deg, origin)
    for axis in range(3):
        assert back[axis] == pytest.approx(point[axis], abs=1e-12)


def test_aligning_by_a_yaw_puts_that_yaw_s_wall_on_an_axis():
    """The point of the frame: a 37-degree wall's normal becomes +X."""
    yaw_deg = 37.0
    origin = (0.0, 0.0, 0.0)
    normal = _wall_normal(yaw_deg)
    aligned = aligned_point(normal, yaw_deg, origin)
    assert aligned[0] == pytest.approx(1.0, abs=1e-12)
    assert aligned[1] == pytest.approx(0.0, abs=1e-12)


def test_a_small_target_fits_at_a_fine_resolution():
    resolution = resolution_that_fits((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    assert resolution <= 0.005, "a 1 m target is 8M cells at 5 mm, well under the cap"


def test_the_padding_is_counted_in_the_cap():
    """A resolution computed from the UNPADDED box still allocates past the cap."""
    extent = 20.0
    resolution = resolution_that_fits((-extent, -extent, -extent), (extent,) * 3)
    shape = [
        math.ceil((2 * extent + 2.0 * GRID_PADDING_CELLS * resolution) / resolution)
        for _ in range(3)
    ]
    assert shape[0] * shape[1] * shape[2] <= MAXIMUM_ENCLOSURE_CELLS


def test_a_huge_target_is_refused_with_a_number():
    with pytest.raises(ValueError, match="no resolution"):
        resolution_that_fits((-1.0e6,) * 3, (1.0e6,) * 3)


def test_a_cell_has_six_neighbours_and_none_is_itself():
    neighbours = flood_neighbours((4, 5, 6))
    assert len(neighbours) == 6
    assert (4, 5, 6) not in neighbours
    for offset_axis in range(3):
        for sign in (1, -1):
            expected = [4, 5, 6]
            expected[offset_axis] += sign
            assert tuple(expected) in neighbours
