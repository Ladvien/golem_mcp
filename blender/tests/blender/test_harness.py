"""The one-call loop, both front doors."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_run_builder_full_loop_with_export(empty_scene, tmp_path):
    from blended.builders import PalletBuilder, PalletParameters
    from blended.harness import HarnessSettings, run_builder

    result = run_builder(
        PalletBuilder(PalletParameters()),
        HarnessSettings(
            output_directory=tmp_path,
            export_glb_path=tmp_path / "pallet.glb",
            export_blend_path=tmp_path / "pallet.blend",
        ),
    )
    assert result.ok, result.summary()
    assert result.stage_reached == "done"
    assert result.contact_sheet_path.exists()
    assert (tmp_path / "pallet.glb").exists()
    assert (tmp_path / "pallet.blend").exists()
    assert result.export_blend_path == tmp_path / "pallet.blend"
    assert result.export_failures == ()


def test_a_glb_export_without_a_blend_path_is_refused_before_building(
    empty_scene, tmp_path
):
    """OT-50: every exported asset ships with its .blend. The harness has
    no default beside the .glb, so the run fails loudly before the builder
    runs and nothing is written."""
    from blended.harness import HarnessSettings, run_builder

    class ExplodingBuilder:
        def build(self):
            raise AssertionError("the builder ran; the refusal came too late")

    with pytest.raises(ValueError, match="export_blend_path"):
        run_builder(
            ExplodingBuilder(),
            HarnessSettings(
                output_directory=tmp_path, export_glb_path=tmp_path / "pallet.glb"
            ),
        )
    assert list(tmp_path.iterdir()) == []


def test_run_chunk_retries_and_logs(empty_scene, tmp_path):
    import json

    from blended.harness import HarnessSettings, run_chunk
    from tests.blender.test_retry import (
        BROKEN_SMOOTH_CRATE_SOURCE,
        FIXED_SMOOTH_CRATE_SOURCE,
    )

    log_path = tmp_path / "session.jsonl"
    result = run_chunk(
        BROKEN_SMOOTH_CRATE_SOURCE,
        object_name="RetryCrate",
        fix_source=lambda source, run_result: FIXED_SMOOTH_CRATE_SOURCE,
        settings=HarnessSettings(output_directory=tmp_path, session_log_path=log_path),
        chunk_label="retry_crate",
    )
    assert result.ok, result.summary()
    assert "2 attempt(s)" in result.execution_summary
    log_records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(log_records) == 2
    assert log_records[0]["ok"] is False and log_records[1]["ok"] is True


def test_gate_failure_still_produces_review_sheet(empty_scene, tmp_path):
    from blended.harness import HarnessSettings, run_chunk

    OPEN_BOX_SOURCE = """
import sys
sys.path.insert(0, "src")
import bmesh
import bpy
from blended.ops import add_box, link_into_scene

open_box = add_box("OpenChunk", 1.0, 1.0, 1.0)
link_into_scene(open_box)
working = bmesh.new(); working.from_mesh(bpy.data.objects[open_box].data)
working.faces.ensure_lookup_table(); working.faces.remove(working.faces[0])
working.to_mesh(bpy.data.objects[open_box].data); working.free()
"""
    result = run_chunk(
        OPEN_BOX_SOURCE,
        object_name="OpenChunk",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "gate"
    assert result.gate_failures
    assert result.contact_sheet_path.exists()  # failures are reviewable


def test_missing_object_is_a_distinct_failure(empty_scene, tmp_path):
    from blended.harness import HarnessSettings, run_chunk

    result = run_chunk(
        "x = 1",
        object_name="NeverBuilt",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "locate"
    assert "NeverBuilt" in result.execution_summary


def test_an_unlinked_object_fails_the_gate(empty_scene, tmp_path):
    """Flawless geometry the user cannot see is not a pass.

    Measured 2026-09-05 in a live GUI turn: a writer built a barrel
    with 192 faces and a material but never linked it, and the gate
    said PASS, `inspect_object` said PASS and the contact sheet
    rendered — while the viewport stayed empty and the object would
    have been absent from any export, because `export_glb` writes the
    SCENE.
    """
    from blended.harness import HarnessSettings, run_chunk

    UNLINKED_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box

add_box("Orphan", 1.0, 1.0, 1.0)
"""
    result = run_chunk(
        UNLINKED_SOURCE,
        object_name="Orphan",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "locate"
    assert "NOT linked into the scene" in result.execution_summary
    assert "link_into_scene" in result.execution_summary


def test_a_linked_object_passes_the_same_gate(empty_scene, tmp_path):
    """The control: the only difference is the link call."""
    from blended.harness import HarnessSettings, run_chunk

    LINKED_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene

link_into_scene(add_box("Linked", 1.0, 1.0, 1.0))
"""
    result = run_chunk(
        LINKED_SOURCE,
        object_name="Linked",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert result.ok, result.summary()
    assert result.stage_reached == "done"


def test_the_summary_tells_the_writer_where_the_extents_landed(empty_scene, tmp_path):
    """The orientation fact, in the text the writer reads every turn.

    The harness rotates the finished object by exactly this reading and
    the bench prompt carries a placement clause, but both act AFTER or
    BESIDE the writer's own decision — nothing told it, during a turn,
    which axis currently holds which extent. A 0.9 x 0.3 x 0.6 box has
    its middle extent (0.6) on z while the canonical depth axis is y, so
    the summary must name both.
    """
    from blended.harness import HarnessSettings, run_chunk

    OBLONG_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene

link_into_scene(add_box("Oblong", 0.9, 0.3, 0.6))
"""
    result = run_chunk(
        OBLONG_SOURCE,
        object_name="Oblong",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert result.ok, result.summary()
    assert result.world_extents_m == pytest.approx((0.9, 0.3, 0.6))
    summary = result.summary()
    assert "middle extent on z" in summary, summary
    assert "canonical depth axis is y" in summary, summary
    # And it reads AFTER the gate line, where the writer is already
    # looking when something went wrong.
    assert summary.index("gate:") < summary.index("orient:"), summary


# A quarter turn about X swaps the y and z extents of a box.
QUARTER_TURN_RAD = 3.141592653589793 / 2.0
ROTATED_OBLONG_SOURCE = f"""
import sys
sys.path.insert(0, "src")
from blended.ops import add_box, link_into_scene, rotate_object_euler

link_into_scene(add_box("Oblong", 0.9, 0.3, 0.6))
rotate_object_euler("Oblong", x_rad={QUARTER_TURN_RAD!r})
"""


def test_the_reading_and_the_op_measure_the_same_box(empty_scene, tmp_path):
    """OT-34. A 0.9 x 0.3 x 0.6 box turned a quarter turn about X occupies
    0.9 x 0.6 x 0.3 m of world space, and `apply_canonical_depth_axis`
    measures it that way (`matrix_world @ bound_box`). Measured
    2026-09-11 before the fix: the gate read `object.dimensions` — the
    local box scaled, rotation-blind — and reported (0.9, 0.3, 0.6),
    "middle extent on z", while the op would compose identity because
    the middle extent already sat on y. The harness told the writer one
    axis assignment and applied another.
    """
    from blended.harness import HarnessSettings, run_chunk
    from blended.ops import canonical_depth_axis_rotation_euler_rad

    result = run_chunk(
        ROTATED_OBLONG_SOURCE,
        object_name="Oblong",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert result.ok, result.summary()
    assert result.world_extents_m == pytest.approx((0.9, 0.6, 0.3), abs=1e-5)
    summary = result.summary()
    assert "middle extent on y (canonical)" in summary, summary
    # The rotation the op would apply to the SAME numbers is identity:
    # reading and op agree.
    assert canonical_depth_axis_rotation_euler_rad(*result.world_extents_m) == (
        0.0,
        0.0,
        0.0,
    )


def test_inspect_object_and_list_scene_read_the_world_box(empty_scene, tmp_path):
    """OT-34, the tools the writer checks its own work with."""
    from blended.agent.tools import dispatch_tool
    from blended.harness import HarnessSettings, run_chunk

    result = run_chunk(
        ROTATED_OBLONG_SOURCE,
        object_name="Oblong",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert result.ok, result.summary()

    inspected = dispatch_tool(
        "inspect_object", {"object_name": "Oblong"}, tmp_path
    ).text
    assert "extents x 0.9000 y 0.6000 z 0.3000 m" in inspected, inspected
    assert "middle extent on y (canonical)" in inspected, inspected

    listed = dispatch_tool("list_scene", {}, tmp_path).text
    assert "0.900 x 0.600 x 0.300 m" in listed, listed


def _visible_box(name: str):
    """A gate-clean, linked, visible cube — the control for every case."""
    from blended.ops import add_box, link_into_scene

    built = add_box(name, 1.0, 1.0, 1.0)
    link_into_scene(built)
    return bpy.data.objects[built]


def test_every_invisibility_cause_is_named_not_just_detected(empty_scene):
    """One rule, four causes, four different instructions.

    `Object.visible_get()` is False for all four (measured 2026-09-05:
    unlinked, excluded collection, hide_viewport, hide_set), so one call
    is the whole rule — but a model that is told "invisible" cannot act,
    while "not linked, call link_into_scene" can be fixed in one line.
    """
    import bpy

    from blended.harness import invisibility_failure

    control = _visible_box("Control")
    assert invisibility_failure(control) == ""

    orphan = bpy.data.objects.new("Orphan", control.data)
    assert "NOT linked into the scene" in invisibility_failure(orphan)

    excluded_collection = bpy.data.collections.new("Excluded")
    bpy.context.scene.collection.children.link(excluded_collection)
    banished = _visible_box("Banished")
    for parent in list(banished.users_collection):
        parent.objects.unlink(banished)
    excluded_collection.objects.link(banished)
    bpy.context.view_layer.layer_collection.children["Excluded"].exclude = True
    bpy.context.view_layer.update()
    assert "EXCLUDED from the view layer" in invisibility_failure(banished)

    hidden = _visible_box("Hidden")
    hidden.hide_viewport = True
    bpy.context.view_layer.update()
    assert "HIDDEN" in invisibility_failure(hidden)

    eye_hidden = _visible_box("EyeHidden")
    eye_hidden.hide_set(True)
    assert "HIDDEN" in invisibility_failure(eye_hidden)


def test_an_unrenderable_object_fails_even_though_it_is_visible(empty_scene, tmp_path):
    """The sneakiest cause: the user sees it, the render does not.

    `hide_render` leaves `visible_get()` True, so a visibility-only rule
    would pass it — while the contact sheet the eye judges silently
    loses the object. Measured on the harness's own sheet: 634280 bytes
    with the object, 318310 without.
    """
    from blended.harness import HarnessSettings, run_chunk

    UNRENDERABLE_SOURCE = """
import sys
sys.path.insert(0, "src")
import bpy
from blended.ops import add_box, link_into_scene

built = add_box("Ghost", 1.0, 1.0, 1.0)
link_into_scene(built)
bpy.data.objects[built].hide_render = True
"""
    result = run_chunk(
        UNRENDERABLE_SOURCE,
        object_name="Ghost",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "locate"
    assert "hide_render" in result.execution_summary


def test_inspect_object_agrees_with_the_gate(empty_scene, tmp_path):
    """The writer's own check must not contradict the gate that stopped
    it — one shared rule, one verdict."""
    import bpy

    from blended.agent.tools import dispatch_tool

    hidden = _visible_box("Checked")
    hidden.hide_viewport = True
    bpy.context.view_layer.update()
    _outcome = dispatch_tool("inspect_object", {"object_name": "Checked"}, tmp_path)
    text, _ = _outcome.text, list(_outcome.images)
    assert "GATE FAIL" in text
    assert "HIDDEN" in text

    hidden.hide_viewport = False
    bpy.context.view_layer.update()
    _outcome = dispatch_tool("inspect_object", {"object_name": "Checked"}, tmp_path)
    text, _ = _outcome.text, list(_outcome.images)
    assert "GATE PASS" in text


def test_a_collapsed_or_non_finite_transform_fails_the_gate(empty_scene):
    """The analyzer measures the mesh in LOCAL space, so the object
    matrix is outside everything it can see.

    Measured 2026-09-05, all four gate=PASS before this check: scale 0
    and 1e-9 flatten the object to nothing while its mesh measures
    perfect; a NaN location makes every world-space number the model
    prints NaN; an inf scale makes the glTF export raise RuntimeError.
    """
    import bpy

    from blended.harness import degenerate_transform_failure

    control = _visible_box("Control")
    assert degenerate_transform_failure(control) == ""

    zeroed = _visible_box("Zeroed")
    zeroed.scale = (0.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    assert "COLLAPSED" in degenerate_transform_failure(zeroed)

    nearly = _visible_box("Nearly")
    nearly.scale = (1e-9, 1.0, 1.0)
    bpy.context.view_layer.update()
    assert "COLLAPSED" in degenerate_transform_failure(nearly)

    poisoned = _visible_box("Poisoned")
    poisoned.location = (float("nan"), 0.0, 0.0)
    bpy.context.view_layer.update()
    assert "NON-FINITE" in degenerate_transform_failure(poisoned)

    overflowed = _visible_box("Overflowed")
    overflowed.scale = (float("inf"), 1.0, 1.0)
    bpy.context.view_layer.update()
    assert degenerate_transform_failure(overflowed) != ""


def test_legitimate_scales_are_left_alone(empty_scene):
    """A stretch and a small uniform scale are normal modelling, and a
    determinant threshold would have refused both (a 0.001 uniform
    scale has determinant 1e-9)."""
    import bpy

    from blended.harness import degenerate_transform_failure

    stretched = _visible_box("Stretched")
    stretched.scale = (10.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    assert degenerate_transform_failure(stretched) == ""

    tiny = _visible_box("Tiny")
    tiny.scale = (0.001, 0.001, 0.001)
    bpy.context.view_layer.update()
    assert degenerate_transform_failure(tiny) == ""

    panel = _visible_box("Panel")
    panel.scale = (1.0, 1.0, 0.01)
    bpy.context.view_layer.update()
    assert degenerate_transform_failure(panel) == ""


def test_the_gate_reports_a_broken_transform_through_run_chunk(empty_scene, tmp_path):
    """End to end: the model must read the cause in the tool result."""
    from blended.harness import HarnessSettings, run_chunk

    COLLAPSED_SOURCE = """
import sys
sys.path.insert(0, "src")
import bpy
from blended.ops import add_box, link_into_scene

built = add_box("Flat", 1.0, 1.0, 1.0)
link_into_scene(built)
bpy.data.objects[built].scale = (1.0, 1.0, 0.0)
"""
    result = run_chunk(
        COLLAPSED_SOURCE,
        object_name="Flat",
        settings=HarnessSettings(output_directory=tmp_path),
    )
    assert not result.ok
    assert result.stage_reached == "locate"
    assert "COLLAPSED" in result.execution_summary
