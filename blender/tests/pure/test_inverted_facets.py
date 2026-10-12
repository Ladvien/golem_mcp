"""Pure layer: the inverted-facet arithmetic, tested without bpy."""

from blended.analyze.mesh_checks import facet_disagrees_with_its_normals

# A CCW triangle in the xy plane, viewed from +Z (winding normal +Z),
# with corner normals pointing +Z: agrees with itself.
CCW_CORNER_POSITIONS = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
)
UP_NORMALS = (
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
)


def test_agreeing_facet_reads_false():
    assert not facet_disagrees_with_its_normals(CCW_CORNER_POSITIONS, UP_NORMALS)


def test_reversed_winding_reads_true():
    reversed_positions = (
        CCW_CORNER_POSITIONS[0],
        CCW_CORNER_POSITIONS[2],
        CCW_CORNER_POSITIONS[1],
    )
    assert facet_disagrees_with_its_normals(reversed_positions, UP_NORMALS)


def test_zero_area_facet_reads_false():
    collapsed_positions = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
    )
    assert not facet_disagrees_with_its_normals(collapsed_positions, UP_NORMALS)
