"""Multi-angle inspection captures.

Headless frontend: renders through a temporary camera (front, right,
top, three-quarter). The live-GUI frontend will implement the same
view set through viewport framing + screenshot with a rotation
assertion; both must keep this module's view names and ordering so
inspection reads identically in either mode.

Never judge work from a single view — front/right/top/three-quarter is
the minimum coverage before a step counts as inspected.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CAPTURE_CAMERA_NAME = "_blended_capture_camera"

# Direction TO the object, per named view. Orthographic for the three
# axis views; perspective for the three-quarter.
VIEW_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "front": (0.0, -1.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0),
    # Looking UP. Measured 2026-08-22 (iterations 10 and 11): for a
    # three-legged stool NO other view can show how the legs are placed.
    # `top` is blind to them — the 0.16 m seat covers feet at 0.14 m —
    # and `front` projects the 120 and 240 degree legs to the SAME world
    # x, so they overlap into what reads as one leg and the sheet looks
    # wrong while the geometry is right. A human reviewer called it out
    # twice. From below there is no occluder and the spacing is direct.
    "bottom": (0.0, 0.0, -1.0),
    "three_quarter": (1.0, -1.0, 0.8),
}
ORTHOGRAPHIC_VIEWS = ("front", "right", "top", "bottom")

# How much breathing room around the object's bounding sphere.
FRAME_MARGIN_FACTOR = 1.2
PERSPECTIVE_DISTANCE_FACTOR = 3.0


XRAY_ALPHA_DEFAULT = 0.4


@dataclass(frozen=True)
class CaptureSettings:
    resolution_px: int = 512
    # Workbench is the fast solid-shading engine; Cycles (CPU) is the
    # fallback where no GPU/GL context exists (e.g. headless containers).
    preferred_engine: str = "BLENDER_WORKBENCH"
    fallback_engine: str = "CYCLES"
    fallback_cycles_samples: int = 8
    # X-ray: semi-transparent Workbench shading, the supported way to see
    # THROUGH geometry when debugging mesh conflicts (interpenetration,
    # hidden components). Measured working in headless Workbench renders;
    # note backface culling is NOT (see drift catalog).
    xray: bool = False
    xray_alpha: float = XRAY_ALPHA_DEFAULT


def _world_bounds_center_and_radius(blender_object):
    from mathutils import Vector

    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    center = sum(world_corners, Vector()) / len(world_corners)
    radius_m = max((corner - center).length for corner in world_corners)
    return center, radius_m


def _assembly_bounds_center_and_radius(blender_object, extra_objects):
    """Frame the object AND the extra objects together.

    An assembly sheet must show every part; framing by the first part
    alone would crop the rest out of view.
    """
    from mathutils import Vector

    all_objects = (blender_object, *extra_objects)
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for blender_object in all_objects
        for corner in blender_object.bound_box
    ]
    center = sum(world_corners, Vector()) / len(world_corners)
    radius_m = max((corner - center).length for corner in world_corners)
    return center, radius_m


def capture_views(
    blender_object,
    output_directory: Path,
    settings: CaptureSettings = CaptureSettings(),
    extra_objects: tuple = (),
) -> dict[str, Path]:
    """Render every named view to PNG; return {view_name: path}."""
    import bpy
    from mathutils import Vector

    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    scene = bpy.context.scene
    if extra_objects:
        center, radius_m = _assembly_bounds_center_and_radius(
            blender_object, extra_objects
        )
    else:
        center, radius_m = _world_bounds_center_and_radius(blender_object)

    camera_data = bpy.data.cameras.new(CAPTURE_CAMERA_NAME)
    camera_object = bpy.data.objects.new(CAPTURE_CAMERA_NAME, camera_data)
    scene.collection.objects.link(camera_object)
    previous_camera = scene.camera
    scene.camera = camera_object

    scene.render.resolution_x = settings.resolution_px
    scene.render.resolution_y = settings.resolution_px
    scene.render.image_settings.file_format = "PNG"

    shading = scene.display.shading
    previous_xray_state = (shading.show_xray, shading.xray_alpha)
    if settings.xray:
        shading.show_xray = True
        shading.xray_alpha = settings.xray_alpha

    captured_paths: dict[str, Path] = {}
    try:
        for view_name, direction_tuple in VIEW_DIRECTIONS.items():
            view_direction = Vector(direction_tuple).normalized()
            if view_name in ORTHOGRAPHIC_VIEWS:
                camera_data.type = "ORTHO"
                camera_data.ortho_scale = 2.0 * radius_m * FRAME_MARGIN_FACTOR
                camera_distance_m = radius_m * PERSPECTIVE_DISTANCE_FACTOR
            else:
                camera_data.type = "PERSP"
                camera_distance_m = radius_m * PERSPECTIVE_DISTANCE_FACTOR
            camera_object.location = center + view_direction * camera_distance_m
            camera_object.rotation_euler = view_direction.to_track_quat(
                "Z", "Y"
            ).to_euler()

            output_path = output_directory / f"{view_name}.png"
            scene.render.filepath = str(output_path)
            try:
                scene.render.engine = settings.preferred_engine
                bpy.ops.render.render(write_still=True)
            except Exception:  # noqa: BLE001 - bpy.ops raises bare RuntimeError
                scene.render.engine = settings.fallback_engine
                scene.cycles.samples = settings.fallback_cycles_samples
                bpy.ops.render.render(write_still=True)
            captured_paths[view_name] = output_path
    finally:
        shading.show_xray, shading.xray_alpha = previous_xray_state
        scene.camera = previous_camera
        bpy.data.objects.remove(camera_object)
        bpy.data.cameras.remove(camera_data)

    return captured_paths
