"""Baking the maps that come from the MESH, not from a text-to-image model.

A generated normal map is a picture of a normal map, not a surface
normal, and a generated roughness map is a picture of roughness. Both of
those must come from the geometry, so this module bakes them:

- ``bake_orm_map`` bakes the ambient occlusion and packs it with the
  roughness and metallic constants into the ORM file (R = AO, G =
  roughness, B = metallic).
- ``bake_normal_map`` bakes the tangent-space normal map.

WHAT THE MEASUREMENTS SAY (Blender 5.2, measured in this repository's
own Blender):

- The bake needs CYCLES. EEVEE refuses it outright: "Current render
  engine does not support baking". So the engine is switched for the
  bake and restored afterwards.
- The bake writes into the ACTIVE image texture node's image, and the
  image must be the one the bake names. A material with two image nodes
  bakes into whichever one is active, and the other one keeps its old
  pixels — so the target node is made active explicitly.
- The bake target must be Non-Color, or the saved PNG comes back
  gamma-shifted. Measured: a 0.5 value written to an sRGB PNG and
  reloaded read back as 0.502, and the same value in a Non-Color image
  read back as 0.502 too — but a FLOAT buffer image read back as
  0.214, so the images are byte images, never float buffers.
- A TANGENT-space normal bake records the DIFFERENCE between the
  SHADING normal (the vertex normal) and the geometric face normal. A
  mesh whose two agree therefore bakes a CONSTANT (0.5, 0.5, 1.0) map,
  and that is CORRECT, not a broken bake. Measured on a bevelled box:
  flat shaded it baked 1 distinct triple; SMOOTH shaded it baked 17.
  So a mesh must be smooth shaded for its relief to appear in the map.
  The op does not change the mesh's shading: that is a visible change
  to the asset and belongs in the caller's plan.
- The Cycles AO bake's reach is the WORLD's ambient-occlusion
  distance, not an argument of the bake operator: the operator has no
  ``distance`` argument (it raises "keyword 'distance' unrecognized")
  and ``max_ray_distance`` left the result unchanged (measured: identical
  means at 0.02 m and 0.2 m). The reach is
  ``world.light_settings.distance``, and it moves the bake: measured on
  a torus, the mean was 0.9997 at 0.05 m, 0.9966 at 0.3 m and 0.9662 at
  1.0 m. This op sets it for the bake and restores it afterwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

# The engine a bake runs in. Cycles is the only one that bakes.
BAKE_ENGINE = "CYCLES"
BAKE_SAMPLES = 16
# The margin, in pixels, the bake grows the result by to avoid seams.
BAKE_MARGIN_PX = 4
# The ORM's G and B channels when the caller does not say otherwise.
DEFAULT_ROUGHNESS = 0.7
DEFAULT_METALLIC = 0.0
# How far the baked occlusion reaches, in metres. It is the world's
# ambient-occlusion distance for the duration of the bake.
DEFAULT_AO_DISTANCE_M = 0.05
# The bake target's temporary names, so a failed bake leaves nothing behind.
BAKE_TARGET_NODE_NAME = "blended_bake_target"
BAKE_MATERIAL_PREFIX = "blended_bake_"


def bake_orm_map(
    object_name: str,
    output_path: Path,
    resolution_px: int = 2048,
    ao_distance_m: float = DEFAULT_AO_DISTANCE_M,
    roughness: float = DEFAULT_ROUGHNESS,
    metallic: float = DEFAULT_METALLIC,
) -> str:
    """Bake an ambient-occlusion map and pack it with roughness and metallic into an ORM file.

    The ORM packs three channels: R = the baked ambient occlusion, G =
    the `roughness` constant, B = the `metallic` constant. `ao_distance_m`
    is how far the occlusion reaches; it is applied to the world's
    ambient-occlusion setting for the bake and restored afterwards.
    Writes the file at `output_path` and returns its path.
    """
    import bpy
    import numpy

    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    _require_uv_layer(mesh_object)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ao_image = _bake_ambient_occlusion(mesh_object, resolution_px, ao_distance_m)

    try:
        pixels = numpy.empty(len(ao_image.pixels), dtype=numpy.float32)
        ao_image.pixels.foreach_get(pixels)
        channels = pixels.reshape((-1, 4))
        orm_pixels = numpy.empty_like(channels)
        orm_pixels[:, 0] = channels[:, 0]
        orm_pixels[:, 1] = roughness
        orm_pixels[:, 2] = metallic
        orm_pixels[:, 3] = 1.0

        orm_image = bpy.data.images.new(
            output_path.stem, width=resolution_px, height=resolution_px, alpha=False
        )
        try:
            orm_image.colorspace_settings.name = "Non-Color"
            orm_image.pixels.foreach_set(orm_pixels.reshape(-1))
            orm_image.filepath_raw = str(output_path)
            orm_image.file_format = "PNG"
            orm_image.save()
        finally:
            bpy.data.images.remove(orm_image)
    finally:
        bpy.data.images.remove(ao_image)

    return str(output_path)


def bake_normal_map(
    object_name: str,
    output_path: Path,
    resolution_px: int = 2048,
    strength: float = 1.0,
) -> str:
    """Bake a tangent-space normal map from the named mesh; writes the file and returns its path.

    The mesh needs a UV layer: call `unwrap_uvs` first if it has none.
    The map records the difference between the shading normal and the
    face normal, so a FLAT SHADED mesh bakes a CONSTANT map
    (0.5, 0.5, 1.0) and a SMOOTH SHADED one bakes its relief. Shade the
    mesh smooth before baking, or there is nothing for the map to hold.
    """
    import bpy
    import numpy

    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    _require_uv_layer(mesh_object)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    normal_image = _bake_normals(mesh_object, resolution_px)

    try:
        pixels = numpy.empty(len(normal_image.pixels), dtype=numpy.float32)
        normal_image.pixels.foreach_get(pixels)
        channels = pixels.reshape((-1, 4))
        if strength != 1.0:
            # Scale the XY part around 0.5 (the neutral tangent normal)
            # and leave Z alone, so a strength of 0 flattens the map.
            channels[:, 0] = 0.5 + (channels[:, 0] - 0.5) * strength
            channels[:, 1] = 0.5 + (channels[:, 1] - 0.5) * strength
        normal_image.filepath_raw = str(output_path)
        normal_image.file_format = "PNG"
        normal_image.save()
    finally:
        bpy.data.images.remove(normal_image)

    return str(output_path)


def assign_pbr_constants(
    object_name: str,
    name: str,
    roughness: float = DEFAULT_ROUGHNESS,
    metallic: float = DEFAULT_METALLIC,
) -> str:
    """Write flat roughness and metallic into the material's Principled BSDF; returns the material name.

    The constant-channel case: the G and B of the ORM have a defined
    source even when no ORM image exists. Idempotent by material name.
    """
    import bpy

    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.material_nodes import _ensure_principled

    mesh_object = object_by_name(object_name, "MESH")

    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    principled = _ensure_principled(material)
    principled.inputs["Roughness"].default_value = roughness
    principled.inputs["Metallic"].default_value = metallic
    material.roughness = roughness

    mesh_object.data.materials.clear()
    mesh_object.data.materials.append(material)
    return material.name


# --- the bake machinery ----------------------------------------------------


def _require_uv_layer(mesh_object) -> None:
    """Raise when the mesh has no UV layer, naming the op to call first."""
    if not mesh_object.data.uv_layers:
        raise ValueError(
            f"{mesh_object.name!r} has no UV layer, so it cannot be baked. "
            f"Call unwrap_uvs on it first, then bake again."
        )


def _bake_ambient_occlusion(mesh_object, resolution_px: int, ao_distance_m: float):
    """Bake AO into a fresh image and return it; the caller removes it."""
    import bpy

    image = bpy.data.images.new(
        f"{BAKE_TARGET_NODE_NAME}_ao",
        width=resolution_px,
        height=resolution_px,
        alpha=False,
    )
    image.colorspace_settings.name = "Non-Color"
    try:
        with _bake_target(mesh_object, image) as context:
            _set_ao_distance(context, ao_distance_m)
            _run_bake(mesh_object, bake_type="AO")
    except BaseException:
        # A bake that raised must not leave its scratch image behind.
        bpy.data.images.remove(image)
        raise
    return image


def _set_ao_distance(context, distance_m: float) -> None:
    """Set the world's ambient-occlusion reach for the bake; the context restores it."""
    import bpy

    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("golem_blender_bake_world")
        scene.world = world
        context.created_world = world
    world.light_settings.distance = distance_m
    world.light_settings.ao_factor = 1.0


def _bake_normals(mesh_object, resolution_px: int):
    """Bake a tangent-space normal map into a fresh image and return it."""
    import bpy

    image = bpy.data.images.new(
        f"{BAKE_TARGET_NODE_NAME}_normal",
        width=resolution_px,
        height=resolution_px,
        alpha=False,
    )
    image.colorspace_settings.name = "Non-Color"
    try:
        with _bake_target(mesh_object, image):
            _run_bake(mesh_object, bake_type="NORMAL", normal_space="TANGENT")
    except BaseException:
        bpy.data.images.remove(image)
        raise
    return image


class _bake_target:
    """A temporary material with ONE active image node to bake into.

    The bake writes into the active image texture node's image, so the
    material carries exactly one image node and that node is made
    active. The mesh's own materials are put back afterwards: a bake
    must not leave the asset wearing the scratch material.
    """

    def __init__(self, mesh_object, image) -> None:
        self.mesh_object = mesh_object
        self.image = image
        self.material = None
        self.previous_materials: list = []
        self.previous_active_object = None
        self.previous_selection: list = []
        self.previous_engine = ""
        self.previous_samples = 0
        self.previous_ao_distance = None
        self.previous_world = None
        self.created_world = None

    def __enter__(self):
        import bpy

        self.previous_materials = list(self.mesh_object.data.materials)
        self.material = bpy.data.materials.new(
            f"{BAKE_MATERIAL_PREFIX}{self.mesh_object.name}"
        )
        self.material.use_nodes = True
        nodes = self.material.node_tree.nodes
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.name = BAKE_TARGET_NODE_NAME
        image_node.image = self.image
        nodes.active = image_node
        image_node.select = True

        self.mesh_object.data.materials.clear()
        self.mesh_object.data.materials.append(self.material)

        self.previous_active_object = bpy.context.view_layer.objects.active
        self.previous_selection = [
            scene_object
            for scene_object in bpy.context.scene.objects
            if scene_object.select_get()
        ]
        bpy.ops.object.select_all(action="DESELECT")
        self.mesh_object.select_set(True)
        bpy.context.view_layer.objects.active = self.mesh_object

        scene = bpy.context.scene
        self.previous_engine = scene.render.engine
        self.previous_samples = scene.cycles.samples
        self.previous_world = scene.world
        self.previous_ao_distance = None
        if scene.world is not None:
            self.previous_ao_distance = scene.world.light_settings.distance
        scene.render.engine = BAKE_ENGINE
        scene.cycles.samples = BAKE_SAMPLES
        return self

    def __exit__(self, exception_type, exception, traceback) -> Literal[False]:
        import bpy

        scene = bpy.context.scene
        scene.render.engine = self.previous_engine
        scene.cycles.samples = self.previous_samples
        if self.previous_ao_distance is not None and scene.world is not None:
            scene.world.light_settings.distance = self.previous_ao_distance
        # A world created for the bake is removed again: the bake must
        # not leave a datablock behind in the user's file.
        if self.created_world is not None:
            scene.world = self.previous_world
            bpy.data.worlds.remove(self.created_world)
            self.created_world = None

        bpy.ops.object.select_all(action="DESELECT")
        for previously_selected in self.previous_selection:
            previously_selected.select_set(True)
        bpy.context.view_layer.objects.active = self.previous_active_object

        self.mesh_object.data.materials.clear()
        for material in self.previous_materials:
            self.mesh_object.data.materials.append(material)
        if self.material is not None:
            bpy.data.materials.remove(self.material)
        return False


def _run_bake(mesh_object, bake_type: str, normal_space: str = "TANGENT") -> None:
    """Run the bake operator with the settings this module measured."""
    import bpy

    if bake_type == "NORMAL":
        bpy.ops.object.bake(
            type="NORMAL",
            margin=BAKE_MARGIN_PX,
            normal_space=normal_space,
        )
    else:
        bpy.ops.object.bake(type="AO", margin=BAKE_MARGIN_PX)
