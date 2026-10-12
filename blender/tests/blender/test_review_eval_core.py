"""Regression test for the eval_core review: the clear-axis sweep is WORLD metres.

`_find_axis_blockage` used a fixed LOCAL ray distance, so an object
scaled below 0.5 stopped the sweep short of itself and a solid axis
read as clear (measured: a 2 m cube scaled 0.1 returned None).
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

CUBE_EDGE_M = 2.0
BLOCKAGE_TOLERANCE_M = 1.0e-4


@pytest.mark.parametrize("scale", [1.0, 0.1, 0.01, 10.0])
def test_a_scaled_solid_blocks_the_axis_through_its_centre(scale):
    from blended.evaluate.acceptance import _find_axis_blockage
    from blended.evaluate.briefs import ClearAxisProbe

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=CUBE_EDGE_M, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object
    cube.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    evaluated = cube.evaluated_get(bpy.context.evaluated_depsgraph_get())
    probe = ClearAxisProbe(
        name="through_the_middle", point_m=(0.0, 0.0, 0.0), axis="z", why="solid"
    )

    blocked_at_m = _find_axis_blockage(evaluated, probe)

    assert blocked_at_m is not None
    # The sweep runs along +z from far below, so the first surface hit
    # is the cube's bottom face.
    assert blocked_at_m == pytest.approx(
        -scale * CUBE_EDGE_M / 2.0, abs=BLOCKAGE_TOLERANCE_M
    )


def test_an_axis_that_misses_the_solid_is_clear():
    from blended.evaluate.acceptance import _find_axis_blockage
    from blended.evaluate.briefs import ClearAxisProbe

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=CUBE_EDGE_M, location=(0.0, 0.0, 0.0))
    cube = bpy.context.object
    cube.scale = (0.1, 0.1, 0.1)
    bpy.context.view_layer.update()
    evaluated = cube.evaluated_get(bpy.context.evaluated_depsgraph_get())
    probe = ClearAxisProbe(
        name="beside_the_cube", point_m=(0.5, 0.0, 0.0), axis="z", why="empty"
    )

    assert _find_axis_blockage(evaluated, probe) is None
