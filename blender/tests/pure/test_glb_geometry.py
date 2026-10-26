"""A shipped .glb measured in the frame the ENGINE loads it in.

The point of the module under test is that it applies NODE TRANSFORMS, so every
test here either moves a node or checks a number a node transform would change.
A reader that ignored transforms would pass a "bounds" test on a mesh modelled
at the origin and fail the first part whose node carries a translation — which
is every part of every kit.

The frame is checked on both sides: the engine frame leaves glTF's +Y up
alone, and the Blender frame maps (x, y, z) -> (x, -z, y). A sign slip there
reports a part's width as its height.
"""

import math

import pytest

from golem_blender.export.glb_geometry import (
    FEET_PER_METRE,
    convex_hull_2d,
    measure_file,
    node_triangles,
    node_world_matrices,
    to_frame,
)
from tests.pure._glb_fixture import _build_glb, _with_node, _write_glb

# A right triangle in the XZ plane (y = 0): 1 m along X, 1 m along Z. Its
# winding gives +Y as the normal, so it is an UP-facing surface in glTF.
FLAT_TRIANGLE_POSITIONS = [
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0),
]
FLAT_TRIANGLE_INDICES = [0, 1, 2]
# A second, LOWER triangle so base_height is not the same as the top's height.
DROP_M = -0.15


def _down_facing_triangle(drop=None):
    """A triangle at `drop` used only to set the model's base."""
    height = DROP_M if drop is None else drop
    return [(0.0, height, 0.0), (1.0, height, 0.0), (0.0, height, 1.0)]


def _two_triangle_glb(up_translation=None):
    """An up-facing triangle at y = 0.1 and a down-facing one at y = -0.15."""
    positions = [
        (0.0, 0.1, 0.0),
        (1.0, 0.1, 0.0),
        (0.0, 0.1, -1.0),
        *_down_facing_triangle(),
    ]
    # The second triangle is wound the other way, so its normal points DOWN and
    # it is not a top; it exists to give the model a base below the up face.
    data = _build_glb(positions, [0, 1, 2, 3, 5, 4])
    if up_translation is not None:
        data = _with_node(data, translation=up_translation)
    return data


def test_a_translated_node_moves_its_triangles(tmp_path):
    """The whole point: a mesh modelled at the origin measured where its NODE puts it."""
    data = _build_glb(FLAT_TRIANGLE_POSITIONS, FLAT_TRIANGLE_INDICES)
    moved = _with_node(data, translation=(0.0, 2.0, 0.0))
    path = _write_glb(tmp_path, moved)
    measurement = measure_file(path)
    assert measurement["bounds_min"][1] == pytest.approx(2.0)
    assert measurement["bounds_max"][1] == pytest.approx(2.0)


def test_a_quarter_turn_about_y_sends_plus_x_to_minus_z(tmp_path):
    half = math.sqrt(0.5)
    data = _build_glb(FLAT_TRIANGLE_POSITIONS, FLAT_TRIANGLE_INDICES)
    # 90 degrees about +Y: quaternion (x, y, z, w) = (0, sin45, 0, cos45).
    turned = _with_node(data, rotation=(0.0, half, 0.0, half))
    path = _write_glb(tmp_path, turned)
    measurement = measure_file(path)
    # The corner at (1, 0, 0) lands at (0, 0, -1); the model is unchanged in Y.
    assert measurement["bounds_max"][0] == pytest.approx(0.0, abs=1.0e-6)
    assert measurement["bounds_min"][2] == pytest.approx(-1.0, abs=1.0e-6)


def test_a_parent_and_child_compose(tmp_path):
    """A child's own translation is measured in its parent's frame."""
    data = _build_glb(FLAT_TRIANGLE_POSITIONS, FLAT_TRIANGLE_INDICES)
    # Import the fixture's JSON, give node 0 a child, and translate both.
    import json
    import struct

    from golem_blender.export.glb_report import GLB_HEADER_SIZE_BYTES
    from tests.pure._glb_fixture import _json_chunk

    length = struct.unpack_from("<I", data, GLB_HEADER_SIZE_BYTES)[0]
    start = GLB_HEADER_SIZE_BYTES + 8
    gltf = json.loads(data[start : start + length])
    gltf["nodes"].append({"name": "Child", "mesh": 0, "translation": [0.0, 1.0, 0.0]})
    gltf["nodes"][0] = {
        "name": "Parent",
        "children": [1],
        "translation": [0.0, 2.0, 0.0],
    }
    json_chunk = _json_chunk(json.dumps(gltf).encode("utf-8"))
    tail = data[start + length :]
    declared = GLB_HEADER_SIZE_BYTES + len(json_chunk) + len(tail)
    from golem_blender.export.glb_report import GLB_MAGIC

    rebuilt = struct.pack("<III", GLB_MAGIC, 2, declared) + json_chunk + tail

    path = _write_glb(tmp_path, rebuilt)
    measurement = measure_file(path)
    # Parent 2 m + child 1 m = 3 m; the parent has no mesh of its own, so the
    # one measured node carries the SUM.
    assert measurement["bounds_min"][1] == pytest.approx(3.0)
    assert len(measurement["nodes"]) == 1


def test_the_world_matrix_of_every_node_is_reachable():
    data = _build_glb(FLAT_TRIANGLE_POSITIONS, FLAT_TRIANGLE_INDICES)
    gltf, binary = _parse(data)
    matrices = node_world_matrices(gltf)
    assert set(matrices) == {0}
    triangles = node_triangles(gltf, binary, 0, matrices[0])
    assert len(triangles) == 1


def _parse(data):
    from golem_blender.export.glb_report import parse_glb

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as handle:
        handle.write(data)
        name = handle.name
    try:
        return parse_glb(Path(name))
    finally:
        Path(name).unlink()


def test_the_blender_frame_swaps_y_and_z():
    assert to_frame((1.0, 2.0, 3.0), "blender") == (1.0, -3.0, 2.0)
    assert to_frame((1.0, 2.0, 3.0), "engine") == (1.0, 2.0, 3.0)
    with pytest.raises(ValueError, match="frame must be"):
        to_frame((0.0, 0.0, 0.0), "unity")


def test_a_hulls_interior_points_are_dropped():
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    hull = convex_hull_2d([*square, (0.5, 0.5), (0.5, 0.0)])
    assert sorted(hull) == sorted(square)


def test_the_base_and_the_top_are_measured_where_the_node_puts_them(tmp_path):
    path = _write_glb(tmp_path, _two_triangle_glb())
    measurement = measure_file(path)
    assert measurement["base_height"] == pytest.approx(DROP_M)
    assert measurement["top_height"] == pytest.approx(0.1)
    tops = [top for top in measurement["tops"] if abs(top.height - 0.1) < 0.005]
    assert len(tops) == 1
    assert tops[0].area == pytest.approx(0.5)
    assert tops[0].above_base == pytest.approx(0.1 - DROP_M)


def test_feet_are_the_engines_own_factor(tmp_path):
    path = _write_glb(tmp_path, _two_triangle_glb())
    measurement = measure_file(path, units="ft")
    assert measurement["units"] == "ft"
    assert measurement["top_height"] == pytest.approx(0.1 * FEET_PER_METRE)
    assert measurement["base_height"] == pytest.approx(DROP_M * FEET_PER_METRE)


def test_a_step_threshold_buckets_the_top_by_its_height_above_the_base(tmp_path):
    """The bucket is ABOVE_BASE, not the absolute height: a step is climbed from the floor."""
    path = _write_glb(tmp_path, _two_triangle_glb())
    top_above_base = 0.1 - DROP_M  # 0.25 m
    within = measure_file(path, step_thresholds=(top_above_base + 0.05,))
    beyond = measure_file(path, step_thresholds=(top_above_base - 0.05,))
    top = next(top for top in within["tops"] if abs(top.height - 0.1) < 0.005)
    assert top.above_base == pytest.approx(top_above_base)
    assert top.bucket == f"≤{top_above_base + 0.05:g}"
    assert beyond["tops"][0].bucket == f">{top_above_base - 0.05:g}"


def test_a_profile_across_the_quad_hits_it_and_misses_outside(tmp_path):
    path = _write_glb(tmp_path, _two_triangle_glb())
    # The up triangle spans x in [0, 1], z in [-1, 0], with the hypotenuse from
    # (1, -0) to (0, -1). Walk x from -0.5 to 1.5 at z = -0.2.
    measurement = measure_file(
        path,
        profile_from=(-0.5, -0.2),
        profile_to=(1.5, -0.2),
        profile_step=0.05,
        top_minimum_area_m2=0.0,
    )
    samples = measurement["profile"]
    assert samples, "a section across a face must return samples"
    assert samples[0].distance == pytest.approx(0.0)
    assert samples[-1].distance == pytest.approx(2.0)
    # Outside x in [0, 0.8] (the hypotenuse is at x = 1 + z = 0.8 for z = -0.2)
    # there is nothing, and inside there is the 0.1 m face.
    assert samples[0].hit is False
    assert samples[-1].hit is False
    inside = [sample for sample in samples if sample.hit]
    assert inside
    assert all(sample.height == pytest.approx(0.1) for sample in inside)


def test_one_profile_end_without_the_other_is_refused(tmp_path):
    path = _write_glb(tmp_path, _two_triangle_glb())
    with pytest.raises(ValueError, match="go together"):
        measure_file(path, profile_from=(0.0, 0.0))


def test_a_missing_file_and_a_wrong_suffix_are_named(tmp_path):
    with pytest.raises(FileNotFoundError, match="no .glb file"):
        measure_file(tmp_path / "absent.glb")
    other = tmp_path / "model.obj"
    other.write_text("v 0 0 0\n")
    with pytest.raises(ValueError, match="reads a .glb"):
        measure_file(other)
