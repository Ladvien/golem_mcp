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

# The material a mesh with NO slot gets while its back faces are being
# culled, and the grey it carries: Workbench draws an unmaterialed mesh in
# this exact grey, so a culled frame looks like the same mesh, not like a
# white placeholder.
CAPTURE_CULL_MATERIAL_NAME = "golem_capture_cull"
CAPTURE_CULL_MATERIAL_GREY = (0.8, 0.8, 0.8, 1.0)


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
    # How much empty frame the orthographic views leave around the
    # bounding SPHERE. FRAME_MARGIN_FACTOR is right for an inspection
    # sheet; a close-up of one junction wants the pair to dominate its
    # frame, so `render_assembly` asks for less air.
    frame_margin_factor: float = FRAME_MARGIN_FACTOR
    # Fit each view's FRAME to the geometry instead of the bounding
    # sphere, and match the image aspect to the geometry's own: a sheet
    # framed by a sphere leaves a tall thin junction as a sliver in a
    # square frame. The default (False) keeps every existing sheet as it
    # was, framed by the sphere.
    fit_projection: bool = False
    # Hide back faces, as the engine the asset ships to does: glTF's
    # `doubleSided: false` makes bevy_gltf render with `cull_mode: Back`, so a
    # sheet that draws both sides shows surfaces the game never draws.
    #
    # The default stays False because every pinned golden `view_sha256` was
    # captured with both sides drawn, and culling would move all of them.
    #
    # WHICH flag does it depends on the engine, measured 2026-10-27 in Blender
    # 5.2 on a 1 m plane whose normal faces away from the camera (4096
    # subject pixels at 64x64, of which the plane fills 1024):
    #
    #   Workbench: shading.show_backface_culling True -> 0 px;
    #              material.use_backface_culling True -> 1024 px (ignored)
    #   EEVEE:     shading.show_backface_culling True -> 1024 px (ignored);
    #              material.use_backface_culling True -> 0 px
    #   Cycles:    neither flag culls (1024 px either way)
    #
    # So a culled capture sets BOTH and raises if it lands on Cycles. A CLOSED
    # mesh is byte-identical either way (measured: a cube's render arrays
    # compare equal), which is where the drift entry's old "0 changed pixels"
    # came from — the probe that produced was closed.
    cull_backfaces: bool = False


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


def _projected_extents(blender_objects, view_direction, center):
    """Each corner in the CAMERA's own frame: (right, up, toward-camera).

    The bounding SPHERE is rotation-invariant, which is what a sheet wants and
    what a close-up cannot use: a tall thin junction framed by its sphere is a
    sliver in a square image. So the corners are expressed on the camera's own
    three axes — the axes the FRAME is measured on.
    """
    from mathutils import Vector

    camera_rotation = view_direction.to_track_quat("Z", "Y")
    right_axis = camera_rotation @ Vector((1.0, 0.0, 0.0))
    up_axis = camera_rotation @ Vector((0.0, 1.0, 0.0))
    corners = []
    for blender_object in blender_objects:
        for corner in blender_object.bound_box:
            offset = (blender_object.matrix_world @ Vector(corner)) - center
            corners.append(
                (
                    offset.dot(right_axis),
                    offset.dot(up_axis),
                    offset.dot(view_direction),
                )
            )
    return corners


def _half_extents(corners) -> tuple[float, float]:
    """(half width, half height) of the projected corners, on the frame's axes."""
    if not corners:
        return 0.0, 0.0
    return (
        max(abs(right) for right, _up, _toward in corners),
        max(abs(up) for _right, up, _toward in corners),
    )


def capture_views(
    blender_object,
    output_directory: Path,
    settings: CaptureSettings = CaptureSettings(),
    extra_objects: tuple = (),
    view_names: tuple[str, ...] | None = None,
) -> dict[str, Path]:
    """Render every named view to PNG; return {view_name: path}.

    `view_names` renders only those views, in this module's own order, and
    names an unknown one loudly: a caller that asked for a view which does not
    exist would otherwise get a sheet that silently lacks it. `None` renders
    the whole set, the default every existing caller wants.
    """
    import bpy
    from mathutils import Vector

    unknown_view_names = [
        name for name in (view_names or ()) if name not in VIEW_DIRECTIONS
    ]
    if unknown_view_names:
        raise ValueError(
            f"unknown view(s) {unknown_view_names}; the known views are "
            f"{list(VIEW_DIRECTIONS)}"
        )

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

    previous_resolution = (scene.render.resolution_x, scene.render.resolution_y)
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
    previous_backface_culling = shading.show_backface_culling
    culling_state = None
    if settings.cull_backfaces:
        culling_state = _apply_backface_culling(blender_object, extra_objects, shading)

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
        light_object.rotation_euler = (
            (-light_offset).to_track_quat("-Z", "Y").to_euler()
        )
    try:
        for view_name, direction_tuple in VIEW_DIRECTIONS.items():
            if view_names is not None and view_name not in view_names:
                continue
            view_direction = Vector(direction_tuple).normalized()
            frame_objects = (blender_object, *extra_objects)
            if settings.fit_projection:
                # A FITTED frame is orthographic on purpose. The frame's extent
                # is then exactly the geometry's own projected extent, so the
                # subject fills both axes and nothing near the camera can
                # project outside a frame fitted to the centre plane — a
                # perspective fit clips the nearest corner on a deep solid,
                # which on a junction close-up hides the very edge under review.
                corners = _projected_extents(frame_objects, view_direction, center)
                half_width_m, half_height_m = _half_extents(corners)
                camera_data.type = "ORTHO"
                if half_width_m <= 0.0 or half_height_m <= 0.0:
                    camera_data.ortho_scale = 2.0 * radius_m
                    scene.render.resolution_x = settings.resolution_px
                    scene.render.resolution_y = settings.resolution_px
                else:
                    # `ortho_scale` spans the LARGER image side, so it is twice
                    # the larger half extent and the resolution follows the
                    # geometry's own aspect: the subject fills the frame in BOTH
                    # axes rather than one.
                    camera_data.ortho_scale = (
                        2.0
                        * max(half_width_m, half_height_m)
                        * settings.frame_margin_factor
                    )
                    aspect = max(half_width_m, half_height_m) / min(
                        half_width_m, half_height_m
                    )
                    if half_width_m >= half_height_m:
                        scene.render.resolution_x = round(
                            settings.resolution_px * aspect
                        )
                        scene.render.resolution_y = settings.resolution_px
                    else:
                        scene.render.resolution_x = settings.resolution_px
                        scene.render.resolution_y = round(
                            settings.resolution_px * aspect
                        )
                camera_distance_m = radius_m * PERSPECTIVE_DISTANCE_FACTOR
            elif view_name in ORTHOGRAPHIC_VIEWS:
                camera_data.type = "ORTHO"
                camera_data.ortho_scale = 2.0 * radius_m * settings.frame_margin_factor
                scene.render.resolution_x = settings.resolution_px
                scene.render.resolution_y = settings.resolution_px
                camera_distance_m = radius_m * PERSPECTIVE_DISTANCE_FACTOR
            else:
                camera_data.type = "PERSP"
                scene.render.resolution_x = settings.resolution_px
                scene.render.resolution_y = settings.resolution_px
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
                if settings.cull_backfaces:
                    raise RuntimeError(
                        "backface culling needs Workbench or EEVEE; this render "
                        "dropped to Cycles, which culls on neither flag "
                        "(measured: a plane facing away from the camera still "
                        "fills 1024 of 1024 pixels)"
                    ) from None
                scene.render.engine = settings.fallback_engine
                scene.cycles.samples = settings.fallback_cycles_samples
                bpy.ops.render.render(write_still=True)
            captured_paths[view_name] = output_path
    finally:
        shading.show_xray, shading.xray_alpha = previous_xray_state
        shading.show_backface_culling = previous_backface_culling
        if culling_state is not None:
            culling_state.restore()
        scene.camera = previous_camera
        scene.render.engine = previous_engine
        scene.render.resolution_x, scene.render.resolution_y = previous_resolution
        if light_object is not None:
            bpy.data.objects.remove(light_object)
        if light_data is not None:
            bpy.data.lights.remove(light_data)
        bpy.data.objects.remove(camera_object)
        bpy.data.cameras.remove(camera_data)

    return captured_paths


class _BackfaceCulling:
    """The culling flags a capture set, and the way to put every one of them back."""

    def __init__(self, shading, previous_shading_flag: bool):
        self._shading = shading
        self._previous_shading_flag = previous_shading_flag
        self._material_flags: list[tuple[object, bool]] = []
        self._temporary_slots: list[tuple[object, object]] = []
        self._temporary_material = None

    def remember_material(self, material, previous: bool) -> None:
        self._material_flags.append((material, previous))

    def temporary_material(self):
        """The shared grey material for a slotless mesh, created on first use."""
        if self._temporary_material is None:
            self._temporary_material = _cull_material()
        return self._temporary_material

    def remember_temporary_slot(self, mesh_object, material) -> None:
        self._temporary_slots.append((mesh_object, material))

    def restore(self) -> None:
        for material, previous in self._material_flags:
            material.use_backface_culling = previous
        for mesh_object, material in self._temporary_slots:
            mesh_object.data.materials.pop(
                index=mesh_object.data.materials.find(material.name)
            )
        self._shading.show_backface_culling = self._previous_shading_flag
        if self._temporary_material is not None:
            import bpy

            for mesh_object, _material in self._temporary_slots:
                mesh_object.data.update()
            if self._temporary_material.users == 0:
                bpy.data.materials.remove(self._temporary_material)
            self._temporary_material = None


def _apply_backface_culling(blender_object, extra_objects, shading) -> _BackfaceCulling:
    """Turn on back-face culling for every visible mesh; return the undo record.

    BOTH flags are set, because which one works depends on the engine and the
    capture may land on either (see `CaptureSettings.cull_backfaces` for the
    measurements): Workbench culls on the SHADING flag alone and ignores the
    material's, EEVEE the other way round.

    A mesh with no material slot gets a temporary grey one, because
    `use_backface_culling` is a MATERIAL property and a slotless mesh cannot
    carry it. The temporary slot is removed afterwards.
    """
    import bpy

    culling = _BackfaceCulling(shading, shading.show_backface_culling)
    shading.show_backface_culling = True
    view_layer_objects = bpy.context.view_layer.objects
    for candidate in (blender_object, *extra_objects):
        if candidate.type != "MESH" or not candidate.visible_get():
            continue
        if candidate.name not in view_layer_objects:
            continue
        if not candidate.data.materials:
            temporary = culling.temporary_material()
            candidate.data.materials.append(temporary)
            culling.remember_temporary_slot(candidate, temporary)
        for material in candidate.data.materials:
            if material is None:
                continue
            culling.remember_material(material, material.use_backface_culling)
            material.use_backface_culling = True
    return culling


def _cull_material():
    """The shared grey material a slotless mesh gets while culling; created once per scene."""
    import bpy

    existing = bpy.data.materials.get(CAPTURE_CULL_MATERIAL_NAME)
    if existing is not None:
        existing.diffuse_color = CAPTURE_CULL_MATERIAL_GREY
        existing.use_backface_culling = True
        return existing
    material = bpy.data.materials.new(CAPTURE_CULL_MATERIAL_NAME)
    material.diffuse_color = CAPTURE_CULL_MATERIAL_GREY
    material.use_backface_culling = True
    return material


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
