"""The coplanar detector measured against its own controls and its boundaries.

Every number here is a BOUNDARY, not a plausible case: 0.9 mm and 1.1 mm, 1.9
degrees and 2.1, 0.9 cm^2 and 1.1. A detector that reports "some pairs" tells a
user nothing about whether their asset will shimmer, and a test that asserts
"more than zero" cannot tell a tolerance of 1 mm from one of 1 cm.

The flush/gap pair is the detector's SELF-TEST — the two soups `control_soups`
returns, which every report runs before it measures a scene. They are checked
here as ordinary maths so a change to the detector fails in the smallest place
it can.
"""

import math

import pytest

from golem_blender.analyze.coplanar import (
    DEFAULT_DEPTH_BITS,
    DEFAULT_FAR_M,
    DEFAULT_NEAR_M,
    DEFAULT_NORMAL_TOLERANCE_DEG,
    DEFAULT_TOLERANCE_M,
    KINDS,
    RESOLVED_GAP_QUANTA,
    SoupTriangle,
    classify,
    clip_polygon,
    control_soups,
    coplanar_triangle_pairs,
    depth_quantum_m,
    triangle_area_m2,
    triangle_overlap,
)

QUANTUM_M = depth_quantum_m(DEFAULT_NEAR_M, DEFAULT_FAR_M, DEFAULT_DEPTH_BITS)


def quad(height, owner, material, dx=0.0, dy=0.0, size=1.0, corner=(0.0, 0.0)):
    """One 1 m-facing-+Z quad as two triangles, split along a chosen corner."""
    far_x, far_y = dx + size, dy + size
    corners = [
        (dx, dy, height),
        (far_x, dy, height),
        (far_x, far_y, height),
        (dx, far_y, height),
    ]
    first, second = (0, 1, 2), (0, 2, 3)
    out = []
    for face_index, triangle in enumerate((first, second)):
        picked = tuple(corners[index] for index in triangle)
        out.append(
            SoupTriangle(
                corners=picked,
                normal=(0.0, 0.0, 1.0),
                owner=owner,
                face_index=face_index,
                material=material,
            )
        )
    return out


def square_at(z, half=1.0):
    """A unit square as a 2D ring, for the clip test."""
    return [(-half, -half), (half, -half), (half, half), (-half, half)]


def test_clipping_two_offset_squares_measures_the_overlap():
    subject = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    clip = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
    polygon = clip_polygon(subject, clip)
    area = 0.5 * abs(
        sum(
            polygon[index][0] * polygon[(index + 1) % len(polygon)][1]
            - polygon[(index + 1) % len(polygon)][0] * polygon[index][1]
            for index in range(len(polygon))
        )
    )
    assert area == pytest.approx(1.0)


def test_the_flush_control_reports_a_pair_and_the_gap_control_reports_none():
    flush, gap = control_soups()
    flush_pairs = coplanar_triangle_pairs(flush)
    assert len(flush_pairs) >= 1
    assert {pair.separation_m for pair in flush_pairs} == {0.0}
    assert coplanar_triangle_pairs(gap) == []


def test_a_pair_just_under_the_tolerance_is_reported_and_just_over_is_not():
    first = quad(0.0, owner=0, material="A")
    under = quad(DEFAULT_TOLERANCE_M * 0.9, owner=1, material="B")
    over = quad(DEFAULT_TOLERANCE_M * 1.1, owner=1, material="B")
    assert coplanar_triangle_pairs(first + under)
    assert coplanar_triangle_pairs(first + over) == []


def test_normals_just_inside_the_angle_tolerance_pair_and_just_outside_do_not():
    """Small quads, so the ANGLE is the only thing that can reject the pair.

    A tilted plane diverges: across a 1 m quad a 2 degree tilt is 33 mm, which
    the SEPARATION test rejects long before the angle test sees it. A 2 cm quad
    diverges 0.7 mm at either angle — inside the 1 mm tolerance — so only the
    normal tolerance separates these two cases.
    """
    tilt = math.radians(DEFAULT_NORMAL_TOLERANCE_DEG * 0.95)
    steeper = math.radians(DEFAULT_NORMAL_TOLERANCE_DEG * 1.05)

    def tilted(angle):
        soup = []
        size = 0.02
        for face_index, triangle in enumerate(((0, 1, 2), (0, 2, 3))):
            corners = [
                (0.5, 0.5, 0.0),
                (0.5 + size, 0.5, 0.0),
                (0.5 + size, 0.5 + size, size * math.tan(angle)),
                (0.5, 0.5 + size, 0.0),
            ]
            picked = tuple(corners[index] for index in triangle)
            soup.append(
                SoupTriangle(
                    corners=picked,
                    normal=(0.0, -math.sin(angle), math.cos(angle)),
                    owner=1,
                    face_index=face_index,
                    material="B",
                )
            )
        return soup

    inside = coplanar_triangle_pairs(quad(0.0, owner=0, material="A") + tilted(tilt))
    outside = coplanar_triangle_pairs(
        quad(0.0, owner=0, material="A") + tilted(steeper)
    )
    assert inside, "1.9 degrees inside a 2 degree tolerance must pair"
    assert outside == [], "2.1 degrees outside a 2 degree tolerance must not pair"


def test_the_minimum_overlap_is_a_boundary():
    """Overlap is measured PER TRIANGLE PAIR, so the square's half is what counts.

    A 14.8 mm square wholly inside one 1 m triangle contributes 1.095 cm^2 on
    its own half-quad, just over the 1 cm^2 floor; 13.8 mm contributes 0.952
    and must be dropped. Both sit at (0.1, 0.05), inside the big quad's first
    triangle and clear of its diagonal, so the OVERLAP is the only variable.
    """
    big = quad(0.0, owner=0, material="A", size=1.0)
    kept = coplanar_triangle_pairs(
        big + quad(0.0, owner=1, material="B", size=0.0148, dx=0.1, dy=0.05)
    )
    dropped = coplanar_triangle_pairs(
        big + quad(0.0, owner=1, material="B", size=0.0138, dx=0.1, dy=0.05)
    )
    assert kept, "an overlap of 1.095 cm^2 must be reported"
    assert dropped == [], "an overlap of 0.952 cm^2 must not be reported"


def test_one_quad_split_into_two_triangles_is_not_its_own_pair():
    assert coplanar_triangle_pairs(quad(0.0, owner=0, material="A")) == []


def test_two_triangles_of_the_same_face_are_never_a_pair():
    """Same object, same face index: the two halves of one polygon."""
    triangles = []
    for triangle in ((0, 1, 2), (0, 2, 3)):
        corners = [
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        ]
        triangles.append(
            SoupTriangle(
                corners=tuple(corners[index] for index in triangle),
                normal=(0.0, 0.0, 1.0),
                owner=0,
                face_index=7,
                material="A",
            )
        )
    assert coplanar_triangle_pairs(triangles) == []


@pytest.mark.parametrize(
    ("same_material_ignored", "facing_any", "visible", "quanta", "expected"),
    [
        (True, True, True, 0.0, "same_material"),
        (False, False, True, 0.0, "back_facing"),
        (False, True, False, 0.0, "buried"),
        (False, True, True, RESOLVED_GAP_QUANTA, "clearance"),
        (False, True, True, RESOLVED_GAP_QUANTA * 0.5, "flicker"),
    ],
)
def test_each_kind_is_reachable_from_its_defining_inputs(
    same_material_ignored, facing_any, visible, quanta, expected
):
    assert (
        classify(
            same_material_ignored=same_material_ignored,
            facing_any=facing_any,
            visible=visible,
            quanta=quanta,
        )
        == expected
    )


def test_every_kind_is_in_the_report_order():
    assert KINDS == ("flicker", "clearance", "buried", "back_facing", "same_material")


def test_the_depth_quantum_is_the_linear_orthographic_step():
    assert QUANTUM_M == pytest.approx(3.576e-4, rel=1e-3)


def test_the_overlap_of_two_flush_quads_is_the_shared_area():
    """Two identical half-quads: each triangle's overlap with its twin is 0.5 m^2."""
    first = quad(0.0, owner=0, material="A", size=1.0)
    second = quad(0.0, owner=1, material="B", size=1.0)
    area, separation, centroid, polygon = triangle_overlap(first[0], second[0])
    assert area == pytest.approx(0.5)
    assert separation == pytest.approx(0.0)
    assert centroid[2] == pytest.approx(0.0)
    assert len(polygon) >= 3


def test_a_triangle_that_misses_another_does_not_overlap():
    first = quad(0.0, owner=0, material="A", size=1.0)
    away = quad(0.0, owner=1, material="B", size=1.0, dx=5.0)
    area, separation, centroid, polygon = triangle_overlap(first[0], away[0])
    assert (area, separation, centroid, polygon) == (0.0, 0.0, (0.0, 0.0, 0.0), ())


def test_a_zero_area_triangle_has_no_normal_and_is_dropped():
    degenerate = SoupTriangle(
        corners=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        normal=(0.0, 0.0, 0.0),
        owner=5,
        face_index=0,
        material="A",
    )
    assert triangle_area_m2(degenerate.corners) == pytest.approx(0.0)
    assert coplanar_triangle_pairs([degenerate, *quad(0.0, 0, "A")]) == []


def test_a_pair_is_symmetric_in_area_but_reports_the_firsts_plane():
    first = quad(0.0, owner=0, material="A")
    second = quad(0.0005, owner=1, material="B")
    forward = coplanar_triangle_pairs(first + second)
    backward = coplanar_triangle_pairs(second + first)
    assert len(forward) == len(backward) == 2, "each half-quad pairs with its twin"
    assert [pair.overlap_m2 for pair in forward] == pytest.approx(
        [pair.overlap_m2 for pair in backward]
    )
    assert sorted({round(pair.centroid[2], 9) for pair in forward}) == [0.0]
    assert sorted({round(pair.centroid[2], 9) for pair in backward}) == [0.0005]
