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

CAPTURE_CAMERA_NAME = "_golem_blender_capture_camera"

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

# The capture's own light, used only when the scene has none and the
# capture is rendering shader-accurately. A sun at energy 3.0 lights a
# surface enough to judge it; EEVEE with no light is near-black
# (measured mean 0.0003).
CAPTURE_LIGHT_NAME = "golem_capture_light"
CAPTURE_LIGHT_ENERGY = 3.0


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
    # The engine used when the object carries a TEXTURE. Workbench reads
    # only `material.diffuse_color` and never the shader graph, so a
    # textured asset inspected through it shows no texture at all —
    # measured: a solid-red image texture with a green diffuse_color
    # rendered bright green in Workbench and bright red in EEVEE. So an
    # object with an image texture is rendered shader-accurately, and
    # one without keeps the fast Workbench path. `None` means "choose
    # by what the object carries".
    textured_engine: str | None = "BLENDER_EEVEE"


def _carries_an_image_texture(blender_object) -> bool:
    """Does the object's material graph hold an IMAGE texture?

    A procedural texture (noise, checker) is visible in Workbench only
    through `diffuse_color`, so it does not need the slow engine. An
    IMAGE texture — a painted or baked map — is not visible in
    Workbench at all, and that is the case worth paying for.
    """
    if blender_object.type != "MESH":
        return False
    for material in blender_object.data.materials:
        if material is None or material.node_tree is None:
            continue
        for node in material.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                return True
    return False


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
    # The VIEW LAYER, not just the collection: a newly linked object
    # does not join the layer until the depsgraph is refreshed, and an
    # object outside the layer is invisible to a render.
    bpy.context.view_layer.update()
    previous_camera = scene.camera
    scene.camera = camera_object

    scene.render.resolution_x = settings.resolution_px
    scene.render.resolution_y = settings.resolution_px
    scene.render.image_settings.file_format = "PNG"
    # The engine is restored afterwards: the capture picks one, and the
    # scene must not be left in it.
    previous_engine = scene.render.engine

    shading = scene.display.shading
    previous_xray_state = (shading.show_xray, shading.xray_alpha)
    if settings.xray:
        shading.show_xray = True
        shading.xray_alpha = settings.xray_alpha

    captured_paths: dict[str, Path] = {}
    # A textured object is rendered shader-accurately, so the inspection
    # sheet shows the texture the agent just applied. An object without
    # one keeps the fast Workbench path.
    engine = settings.preferred_engine
    if settings.textured_engine is not None and _carries_an_image_texture(
        blender_object
    ):
        engine = settings.textured_engine
    # EEVEE with no light is near-black (measured mean 0.0003), so the
    # shader-accurate path needs a light. Workbench does not, so the
    # light is only added when the scene has none AND the capture is
    # about to use a light-requiring engine.
    light_object = None
    light_data = None
    if engine != "BLENDER_WORKBENCH" and not _scene_has_a_light():
        light_data = bpy.data.lights.new(CAPTURE_LIGHT_NAME, type="SUN")
        light_data.energy = CAPTURE_LIGHT_ENERGY
        light_object = bpy.data.objects.new(CAPTURE_LIGHT_NAME, light_data)
        scene.collection.objects.link(light_object)
        bpy.context.view_layer.update()
        light_offset = Vector((1.0, -1.0, 2.0)).normalized()
        light_object.location = center + light_offset * radius_m * 3.0
        # A sun's light travels along its local -Z, so the aim is the
        # NEGATED offset: the light has to travel TOWARD the object.
        light_object.rotation_euler = (-light_offset).to_track_quat(
            "-Z", "Y"
        ).to_euler()
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
                scene.render.engine = engine
                bpy.ops.render.render(write_still=True)
            except Exception:  # noqa: BLE001 - bpy.ops raises bare RuntimeError
                scene.render.engine = settings.fallback_engine
                scene.cycles.samples = settings.fallback_cycles_samples
                bpy.ops.render.render(write_still=True)
            captured_paths[view_name] = output_path
    finally:
        shading.show_xray, shading.xray_alpha = previous_xray_state
        scene.camera = previous_camera
        scene.render.engine = previous_engine
        if light_object is not None:
            bpy.data.objects.remove(light_object)
        if light_data is not None:
            bpy.data.lights.remove(light_data)
        bpy.data.objects.remove(camera_object)
        bpy.data.cameras.remove(camera_data)

    return captured_paths


def _scene_has_a_light() -> bool:
    """Is the scene already lit — by a lamp or by a world environment?

    A world with a Background node of non-zero strength lights the
    scene as surely as a lamp does, so it counts.
    """
    import bpy

    for scene_object in bpy.context.scene.objects:
        if scene_object.type == "LIGHT" and not scene_object.hide_render:
            return True

    world = bpy.context.scene.world
    if world is not None and world.use_nodes and world.node_tree is not None:
        for node in world.node_tree.nodes:
            if node.bl_idname != "ShaderNodeBackground":
                continue
            if node.inputs["Strength"].default_value > 0.0:
                return True
    return False
