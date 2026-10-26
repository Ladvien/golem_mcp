"""measure_glb: the file's own numbers, and the scene it must not touch.

The measured demand is a shipped kit part whose pivot and standable height were
being read off a render: `Prop_HolySeal.glb`, three nodes, no node transforms,
whose seal disc tops out at 0.10 m and whose model is 0.15 m tall. Those are the
plan's acceptance numbers, and they are checked here against the real file
(skipped, not weakened, when the kit is not on this machine).

The negative half matters as much: this op reads a PATH, so it must leave
objects, meshes and materials exactly as it found them, and the viewport-follow
ledger must report nothing changed. An op that quietly imported the file would
pass the first half and break the second.
"""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

SEAL_GLB = Path.home() / "sanctuary/assets/models/kit/Prop_HolySeal.glb"
ROUND_ROCKS_NODE = "Prop_HolySeal__MI_RoundRocks"
SEAL_DISC_TOP_M = 0.10
SEAL_TOTAL_HEIGHT_M = 0.15
BOUNDS_TOLERANCE_M = 1.0e-4
TOP_HEIGHT_TOLERANCE_M = 0.005


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _require_seal():
    if not SEAL_GLB.is_file():
        pytest.skip(f"{SEAL_GLB} is not on this machine")


def test_the_shipped_seal_measures_what_its_kit_says(empty_scene):
    from golem_blender.ops import measure_glb

    _require_seal()
    measurement = measure_glb(str(SEAL_GLB))
    rocks = next(node for node in measurement.nodes if node.name == ROUND_ROCKS_NODE)
    assert rocks.bounds_max[1] == pytest.approx(SEAL_DISC_TOP_M, abs=BOUNDS_TOLERANCE_M)
    assert rocks.bounds_min[1] == pytest.approx(-SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M)
    assert measurement.base_height == pytest.approx(
        -SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M
    )
    assert measurement.top_height == pytest.approx(
        SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M
    )
    disc_tops = [
        top
        for top in measurement.tops
        if abs(top.height - SEAL_DISC_TOP_M) <= TOP_HEIGHT_TOLERANCE_M
    ]
    assert len(disc_tops) == 1
    assert ROUND_ROCKS_NODE in disc_tops[0].node_names


def test_reading_a_file_creates_nothing_and_changes_no_object(empty_scene):
    from golem_blender import viewport_follow
    from golem_blender.ops import measure_glb

    _require_seal()
    before_counts = (
        len(bpy.data.objects),
        len(bpy.data.meshes),
        len(bpy.data.materials),
    )
    before_snapshot = viewport_follow.snapshot_scene()
    measure_glb(str(SEAL_GLB))
    assert (
        len(bpy.data.objects),
        len(bpy.data.meshes),
        len(bpy.data.materials),
    ) == before_counts
    assert viewport_follow.changed_object_names(before_snapshot) == ()


def test_the_two_frames_report_different_up_axes(empty_scene):
    from golem_blender.ops import measure_glb

    _require_seal()
    engine = measure_glb(str(SEAL_GLB), frame="engine")
    blender = measure_glb(str(SEAL_GLB), frame="blender")
    # Engine: +Y is up. Blender: +Z is up. The SAME model reads 0.15 tall in
    # both, which is what makes the frame a naming choice and not a scaling.
    assert engine.top_height == pytest.approx(SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M)
    assert blender.top_height == pytest.approx(SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M)
    assert engine.bounds_max[1] == pytest.approx(
        SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M
    )
    assert blender.bounds_max[2] == pytest.approx(
        SEAL_TOTAL_HEIGHT_M, abs=BOUNDS_TOLERANCE_M
    )
    assert "glTF" in engine.axis_mapping and "Blender" in blender.axis_mapping


def test_feet_use_the_engines_own_factor(empty_scene):
    from golem_blender.export.glb_geometry import FEET_PER_METRE
    from golem_blender.ops import measure_glb

    _require_seal()
    feet = measure_glb(str(SEAL_GLB), units="ft")
    assert feet.top_height == pytest.approx(SEAL_TOTAL_HEIGHT_M * FEET_PER_METRE)
