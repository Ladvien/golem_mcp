"""Ground truth for blended.viewport_follow, in a GUI Blender.

The check is independent of the fit's own arithmetic. Blender's own
projection (`view3d_utils.location_3d_to_region_2d`) must put every
corner of each framed bounding box inside the 3D viewport's region. This
must hold in perspective, in ortho and when starting from camera view,
for a tiny box and a large one placed off centre. The probe has to vary:
the two boxes must end at different view distances. Framing must not
change selection, the active object, the mode or the view rotation.

A background Blender has no window, so this cannot join
`make test-blender-app`. Run it with `make test-viewport-gui`, which
launches a factory-startup GUI Blender with isolated user resources.
The verdict is the exit code.
"""

import os
import sys
import traceback
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(
    0, str(max((REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")))
)
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

from blended.agent.outcome import ToolOutcome
from blended.ops import add_box, link_into_scene
from blended.viewport_follow import follow_viewport, frame_in_viewports, snapshot_scene

# The window has drawn at least once by then, so regions have sizes.
FIRST_CHECK_DELAY_S = 2.0
PASS_EXIT_CODE = 0
FAIL_EXIT_CODE = 1

TINY_BOX_NAME = "viewport_follow_tiny"
TINY_BOX_SIZE_M = 0.05
TINY_BOX_LOCATION_M = (3.0, -2.0, 0.5)
LARGE_BOX_NAME = "viewport_follow_large"
LARGE_BOX_SIZE_M = 8.0
LARGE_BOX_LOCATION_M = (-10.0, 4.0, 0.0)
UNLINKED_BOX_NAME = "viewport_follow_unlinked"
# Factory startup's default cube: selected and active before framing.
BYSTANDER_NAME = "Cube"
STARTING_PERSPECTIVES = ("PERSP", "ORTHO", "CAMERA")
UNNAMED_MOVE_M = 3.0


def _viewport():
    for area in bpy.context.window_manager.windows[0].screen.areas:
        if area.type == "VIEW_3D":
            region = next(region for region in area.regions if region.type == "WINDOW")
            return area, region, area.spaces.active.region_3d
    raise AssertionError("factory startup opened no 3D viewport")


def _corners_outside_region(name, region, region_3d):
    region_3d.update()
    blender_object = bpy.data.objects[name]
    outside = []
    for corner in blender_object.bound_box:
        world = blender_object.matrix_world @ Vector(corner)
        projected = location_3d_to_region_2d(region, region_3d, world)
        if projected is None or not (
            0.0 <= projected.x <= region.width and 0.0 <= projected.y <= region.height
        ):
            outside.append((tuple(round(value, 3) for value in world), projected))
    return outside


def _state():
    return (
        tuple(sorted(o.name for o in bpy.context.view_layer.objects if o.select_get())),
        bpy.context.view_layer.objects.active.name,
        bpy.context.mode,
    )


def run_checks() -> list[str]:
    failures: list[str] = []
    for name, size_m, location_m in (
        (TINY_BOX_NAME, TINY_BOX_SIZE_M, TINY_BOX_LOCATION_M),
        (LARGE_BOX_NAME, LARGE_BOX_SIZE_M, LARGE_BOX_LOCATION_M),
    ):
        add_box(name, size_m, size_m, size_m, location_m)
        link_into_scene(name)
    add_box(UNLINKED_BOX_NAME, TINY_BOX_SIZE_M, TINY_BOX_SIZE_M, TINY_BOX_SIZE_M)

    bystander = bpy.data.objects[BYSTANDER_NAME]
    bystander.select_set(True)
    bpy.context.view_layer.objects.active = bystander
    _area, region, region_3d = _viewport()
    before = _state()

    for starting in STARTING_PERSPECTIVES:
        distances = {}
        for name in (TINY_BOX_NAME, LARGE_BOX_NAME):
            region_3d.view_perspective = starting
            rotation_before = region_3d.view_rotation.copy()
            framing = frame_in_viewports((name,))
            label = f"{starting} {name}"
            print(
                f"viewport_follow_check: {label}: {framing.line}; view_distance {region_3d.view_distance:.4f}"
            )
            if framing.framed_names != (name,) or framing.viewport_count != 1:
                failures.append(
                    f"{label}: framed {framing.framed_names} in {framing.viewport_count}"
                )
            outside = _corners_outside_region(name, region, region_3d)
            if outside:
                failures.append(
                    f"{label}: corners outside the region {region.width}x{region.height}: {outside}"
                )
            if region_3d.view_rotation != rotation_before:
                failures.append(f"{label}: view rotation changed")
            distances[name] = region_3d.view_distance
        if not distances[TINY_BOX_NAME] < distances[LARGE_BOX_NAME]:
            failures.append(f"{starting}: the probe did not vary: {distances}")

    unlinked = frame_in_viewports((UNLINKED_BOX_NAME,))
    if (
        unlinked.framed_names
        or "nothing this call touched is in the scene" not in unlinked.line
    ):
        failures.append(f"unlinked object: {unlinked}")

    # A chunk moves an object without naming it. Without the before-snapshot the
    # call frames nothing (the control: this is what the viewport did before the
    # diff); with it, the moved object is framed and fits the region.
    region_3d.view_perspective = STARTING_PERSPECTIVES[0]
    snapshot = snapshot_scene()
    bpy.data.objects[LARGE_BOX_NAME].location.x += UNNAMED_MOVE_M
    distance_before = region_3d.view_distance
    without_diff = follow_viewport(ToolOutcome("ok")).text
    if "unchanged: nothing this call touched" not in without_diff:
        failures.append(
            f"control: a call naming nothing framed something: {without_diff!r}"
        )
    if region_3d.view_distance != distance_before:
        failures.append("control: the view moved with no names and no snapshot")
    with_diff = follow_viewport(ToolOutcome("ok"), before=snapshot).text
    print(f"viewport_follow_check: unnamed move: {with_diff.splitlines()[-1]}")
    if (
        with_diff.splitlines()[-1]
        != f"viewport: framed {LARGE_BOX_NAME} in 1 3D viewport(s)"
    ):
        failures.append(f"unnamed move: {with_diff!r}")
    outside = _corners_outside_region(LARGE_BOX_NAME, region, region_3d)
    if outside:
        failures.append(f"unnamed move: corners outside the region: {outside}")
    if _state() != before:
        failures.append(f"selection/active/mode changed: {before} -> {_state()}")
    return failures


def check_and_exit():
    try:
        failures = run_checks()
    except Exception:  # noqa: BLE001 - any failure is a failed check; printed, exit code 1
        traceback.print_exc()
        os._exit(FAIL_EXIT_CODE)
    for failure in failures:
        print(f"viewport_follow_check FAILED: {failure}")
    print(f"viewport_follow_check: {len(failures)} failure(s)")
    sys.stdout.flush()
    os._exit(FAIL_EXIT_CODE if failures else PASS_EXIT_CODE)


bpy.app.timers.register(check_and_exit, first_interval=FIRST_CHECK_DELAY_S)
