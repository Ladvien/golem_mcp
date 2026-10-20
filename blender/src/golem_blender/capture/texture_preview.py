"""Shader-accurate previews: the only way to SEE a texture.

Workbench — the engine every other inspection render uses — reads only
``material.diffuse_color`` and never the shader graph. Measured with a
solid-red image texture against a green ``diffuse_color``: EEVEE
rendered bright red (0.683) and Workbench rendered bright green
(0.621). A texture reviewed through the Workbench contact sheet is
reviewed BLIND, so this module renders in a shader-accurate engine.

The render setup, each part of it measured:

- EEVEE with no light is near-black (mean 0.0003), so a light is
  created when the scene has none.
- The camera must FACE the object's surface. A camera on the -Y axis
  looking at a horizontal plane sees the plane EDGE-ON, and the sampled
  pixels are background, not the surface. The single preview therefore
  looks down the object's WIDEST extent, square on.
- The camera and the light are removed afterwards, and the previous
  engine, camera and resolution are restored, so a preview leaves the
  scene as it found it.
- The contact sheet reuses ``capture/views.py``'s view names, their
  order and its framing maths, so the two sheets read the same way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from golem_blender.capture.views import (
    FRAME_MARGIN_FACTOR,
    ORTHOGRAPHIC_VIEWS,
    PERSPECTIVE_DISTANCE_FACTOR,
    VIEW_DIRECTIONS,
)

# The engine a texture preview renders in. Workbench is refused: it
# shows diffuse_color, not the texture.
PREVIEW_ENGINE = "BLENDER_EEVEE"
# The engines that can show a shader graph.
SHADER_ENGINES = ("BLENDER_EEVEE", "CYCLES")
# The sun's energy. Measured: a sun at 3.0 lights the surface enough to
# judge a texture's colour.
PREVIEW_LIGHT_ENERGY = 3.0
# The names the temporary objects carry, so a failed preview leaves
# nothing behind that looks like part of the asset.
PREVIEW_CAMERA_NAME = "golem_texture_preview_camera"
PREVIEW_LIGHT_NAME = "golem_texture_preview_light"


def render_texture_preview(
    blender_object,
    output_path: Path,
    *,
    resolution_px: int = 512,
    engine: str = PREVIEW_ENGINE,
) -> Path:
    """Render the object in a shader-accurate engine and write a PNG; returns its path.

    `engine` must be a shader-accurate engine; BLENDER_WORKBENCH is
    refused with a ValueError naming the reason, because a Workbench
    preview shows the material's viewport colour and therefore cannot
    show a texture. The camera looks down the object's widest extent,
    so it faces the surface instead of its edge.
    """
    import bpy

    if engine not in SHADER_ENGINES:
        raise ValueError(
            f"engine {engine!r} cannot show a texture: Workbench reads only "
            f"material.diffuse_color, never the shader graph. Use one of "
            f"{SHADER_ENGINES}."
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    center, radius_m = _center_and_radius(blender_object)
    direction = _facing_direction(blender_object)

    with _preview_scene(
        blender_object,
        center,
        radius_m,
        resolution_px=resolution_px,
        engine=engine,
        direction=direction,
    ) as camera_data:
        camera_data.type = "PERSP"
        scene = bpy.context.scene
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)

    return output_path


def render_texture_contact_sheet(
    blender_object,
    output_directory: Path,
    *,
    resolution_px: int = 512,
    engine: str = PREVIEW_ENGINE,
    title: str = "",
) -> Path:
    """Render the standard view set in a shader-accurate engine and compose one sheet.

    The view names and their order are the ones `capture/views.py` uses
    (front, right, top, bottom, three_quarter) and the framing is its
    framing maths, so the two sheets read the same way; the sheet is
    composed by the same compositor, so the layout and the labels are
    the same too.
    """
    import bpy
    from mathutils import Vector

    from golem_blender.capture.contact_sheet import compose_contact_sheet

    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    center, radius_m = _center_and_radius(blender_object)

    view_paths: dict[str, Path] = {}
    for view_name, direction_tuple in VIEW_DIRECTIONS.items():
        view_direction = Vector(direction_tuple).normalized()
        with _preview_scene(
            blender_object,
            center,
            radius_m,
            resolution_px=resolution_px,
            engine=engine,
            direction=view_direction,
        ) as camera_data:
            if view_name in ORTHOGRAPHIC_VIEWS:
                camera_data.type = "ORTHO"
                camera_data.ortho_scale = 2.0 * radius_m * FRAME_MARGIN_FACTOR
            else:
                camera_data.type = "PERSP"
            scene = bpy.context.scene
            view_path = output_directory / f"{view_name}.png"
            scene.render.filepath = str(view_path)
            bpy.ops.render.render(write_still=True)
        view_paths[view_name] = view_path

    return compose_contact_sheet(
        view_paths,
        output_directory / "texture_contact_sheet.png",
        title=title or f"{blender_object.name} (shader-accurate preview)",
    )


class _preview_scene:
    """The scene as a preview needs it: a camera, a light, an engine.

    Everything the preview changes is restored on the way out, including
    when the render raises, so a failed preview leaves the user's scene
    exactly as it found it.
    """

    def __init__(
        self, blender_object, center, radius_m, *, resolution_px, engine, direction
    ):
        self.blender_object = blender_object
        self.center = center
        self.radius_m = radius_m
        self.resolution_px = resolution_px
        self.engine = engine
        self.direction = direction
        self.camera_object = None
        self.camera_data = None
        self.light_object = None
        self.light_data = None
        self.previous: dict = {}

    def __enter__(self):
        import bpy
        from mathutils import Vector

        scene = bpy.context.scene
        self.previous = {
            "engine": scene.render.engine,
            "camera": scene.camera,
            "resolution": (scene.render.resolution_x, scene.render.resolution_y),
            "filepath": scene.render.filepath,
            "file_format": scene.render.image_settings.file_format,
        }

        self.camera_data = bpy.data.cameras.new(PREVIEW_CAMERA_NAME)
        self.camera_object = bpy.data.objects.new(PREVIEW_CAMERA_NAME, self.camera_data)
        scene.collection.objects.link(self.camera_object)
        self.camera_object.location = (
            self.center + self.direction * self.radius_m * PERSPECTIVE_DISTANCE_FACTOR
        )
        self.camera_object.rotation_euler = self.direction.to_track_quat(
            "Z", "Y"
        ).to_euler()
        scene.camera = self.camera_object

        self.light_data = bpy.data.lights.new(PREVIEW_LIGHT_NAME, type="SUN")
        self.light_data.energy = PREVIEW_LIGHT_ENERGY
        self.light_object = bpy.data.objects.new(PREVIEW_LIGHT_NAME, self.light_data)
        scene.collection.objects.link(self.light_object)
        light_direction = Vector((1.0, -1.0, 2.0)).normalized()
        self.light_object.location = self.center + light_direction * self.radius_m * 3.0
        self.light_object.rotation_euler = light_direction.to_track_quat(
            "-Z", "Y"
        ).to_euler()

        scene.render.engine = self.engine
        scene.render.resolution_x = self.resolution_px
        scene.render.resolution_y = self.resolution_px
        scene.render.image_settings.file_format = "PNG"
        return self.camera_data

    def __exit__(self, exception_type, exception, traceback) -> Literal[False]:
        import bpy

        scene = bpy.context.scene
        scene.render.engine = self.previous["engine"]
        scene.camera = self.previous["camera"]
        scene.render.resolution_x, scene.render.resolution_y = self.previous[
            "resolution"
        ]
        scene.render.filepath = self.previous["filepath"]
        scene.render.image_settings.file_format = self.previous["file_format"]
        if self.light_object is not None:
            bpy.data.objects.remove(self.light_object)
        if self.light_data is not None:
            bpy.data.lights.remove(self.light_data)
        if self.camera_object is not None:
            bpy.data.objects.remove(self.camera_object)
        if self.camera_data is not None:
            bpy.data.cameras.remove(self.camera_data)
        return False


def _center_and_radius(blender_object):
    """The object's world-space bounding-sphere centre and radius."""
    from mathutils import Vector

    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    center = sum(world_corners, Vector()) / len(world_corners)
    radius_m = max((corner - center).length for corner in world_corners)
    return center, radius_m


def _facing_direction(blender_object):
    """The direction the camera looks FROM, aimed at the object's widest face.

    A camera on an axis the object presents edge-on samples background
    instead of surface, so the widest extent picks the axis and the
    camera looks straight down it.
    """
    from mathutils import Vector

    corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    minimum = Vector(
        (
            min(corner.x for corner in corners),
            min(corner.y for corner in corners),
            min(corner.z for corner in corners),
        )
    )
    maximum = Vector(
        (
            max(corner.x for corner in corners),
            max(corner.y for corner in corners),
            max(corner.z for corner in corners),
        )
    )
    sizes = maximum - minimum
    axis_index = max(range(3), key=lambda index: sizes[index])
    direction = Vector((0.0, 0.0, 0.0))
    direction[axis_index] = -1.0
    return direction.normalized()
