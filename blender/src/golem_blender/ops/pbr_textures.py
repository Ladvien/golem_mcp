"""PBR texture sets on a mesh: base colour, ORM, normal map, one material.

Three maps, one graph, one op. The set is applied to a material by
NAME, so re-running with a new map updates the graph in place instead
of stacking a second image node — the same idempotency rule the rest of
the facade follows.

THE AO CHANNEL IS MULTIPLIED INTO THE BASE COLOUR, NOT ROUTED THROUGH
AN AO NODE. This was measured, not assumed. With a pure-red base-colour
texture and an ORM of R=1.0 / G=0.5 / B=0.0, the Mix-MULTIPLY wiring
rendered ``red 0.697, green 0.110, blue 0.023`` (the red shows), while
routing R through a ``ShaderNodeAmbientOcclusion`` node rendered a
neutral ``red 0.673, green 0.673, blue 0.673`` — the AO node discards
the texture's colour and replaces the base colour with its own
occlusion output. The Mix-MULTIPLY route is the glTF-standard one and
it is the one here.

The Mix node's colour sockets are addressed BY INDEX (``inputs[6]`` is
A, ``inputs[7]`` is B, ``outputs[2]`` is the result) because the socket
NAMES change with ``data_type``; the names are read once here and the
indices are what the code uses.

Why diffuse_color is set too: Workbench — the engine every inspection
render uses — reads only ``material.diffuse_color``, never the shader
graph (measured: a solid-red image texture with a green diffuse_color
rendered bright green in Workbench and bright red in EEVEE). Setting
both keeps a Workbench render meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from golem_blender.ops._contract import op
from golem_blender.ops.material_nodes import (
    BASE_COLOR_INPUT_NAME,
    IMAGE_NODE_NAME,
    PRINCIPLED_NODE_NAME,
    _ensure_principled,
    _get_or_create_node,
    _sync_diffuse_from_image,
)

# Node names, reused across runs so a re-run updates rather than stacks.
ORM_IMAGE_NODE_NAME = "blended_pbr_orm"
NORMAL_IMAGE_NODE_NAME = "blended_pbr_normal"
SEPARATE_NODE_NAME = "blended_pbr_separate"
AO_MIX_NODE_NAME = "blended_pbr_ao_mix"
NORMAL_MAP_NODE_NAME = "blended_pbr_normal_map"

# The Mix node's colour sockets, by index (their names change with
# data_type, so the indices are the stable handle).
MIX_FACTOR_INDEX = 0
MIX_A_COLOR_INDEX = 6
MIX_B_COLOR_INDEX = 7
MIX_RESULT_COLOR_INDEX = 2

# The Separate Color node's outputs, by index.
SEPARATE_RED_INDEX = 0
SEPARATE_GREEN_INDEX = 1
SEPARATE_BLUE_INDEX = 2

# The Normal Map node's sockets, by index.
NORMAL_MAP_STRENGTH_INDEX = 0
NORMAL_MAP_COLOR_INDEX = 1

# The ORM channel packing this op assumes, as the report states it.
ORM_CHANNEL_PACKING = "R=ao,G=roughness,B=metallic"


@dataclass(frozen=True)
class PbrTextureReport:
    """What the material's graph actually has wired, read back from it."""

    material_name: str
    base_color_path: str
    orm_path: str
    normal_path: str
    orm_channels: str
    uv_layer: str
    base_color_linked: bool
    normal_linked: bool
    metallic_linked: bool
    roughness_linked: bool
    ao_multiplied: bool


def assign_pbr_texture_set(
    object_name: str,
    name: str,
    base_color_path: Path,
    orm_path: Path | None = None,
    normal_path: Path | None = None,
) -> str:
    """Apply a PBR texture set to the named mesh as one material; returns the material name.

    `base_color_path` is required; `orm_path` and `normal_path` are
    optional. The material is reused by name and the graph is updated in
    place, so calling this again with a revised map changes the material
    instead of adding a second one. Raises FileNotFoundError naming the
    first image path that does not exist.
    """
    import bpy

    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")

    base_color_path = Path(base_color_path)
    for image_path in (base_color_path, orm_path, normal_path):
        if image_path is not None and not Path(image_path).is_file():
            raise FileNotFoundError(f"Image not found: {image_path}")

    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    principled = _ensure_principled(material)
    tree = material.node_tree
    links = tree.links

    # --- base colour -----------------------------------------------------
    base_color_image = bpy.data.images.load(str(base_color_path), check_existing=True)
    base_color_node = _get_or_create_node(
        material, IMAGE_NODE_NAME, "ShaderNodeTexImage"
    )
    base_color_node.image = base_color_image
    _sync_diffuse_from_image(material, base_color_image)

    # The ORM's AO multiplies the base colour, so the base colour reaches
    # the Principled through the Mix node when an ORM is present, and
    # directly when it is not.
    if orm_path is None:
        _link_direct(
            links,
            base_color_node.outputs["Color"],
            principled.inputs[BASE_COLOR_INPUT_NAME],
        )
    else:
        _wire_orm(material, links, principled, base_color_node, orm_path)

    # --- normal map -------------------------------------------------------
    if normal_path is None:
        _clear_normal_map(material, links, principled)
    else:
        _wire_normal_map(material, links, principled, mesh_object, normal_path)

    _position_nodes(material)

    mesh_object.data.materials.clear()
    mesh_object.data.materials.append(material)
    return material.name


def _link_direct(links, from_socket, to_socket) -> None:
    """Link one socket to another, dropping any stale link into the target."""
    for stale_link in list(to_socket.links):
        links.remove(stale_link)
    links.new(from_socket, to_socket)


def _wire_orm(material, links, principled, base_color_node, orm_path: Path) -> None:
    """Wire the ORM: AO multiplied into the base colour, G to roughness, B to metallic."""
    import bpy

    orm_image = bpy.data.images.load(str(orm_path), check_existing=True)
    # The ORM carries VALUES, not colour: R = occlusion, G = roughness,
    # B = metallic. Loaded as sRGB its channels would be gamma-decoded
    # on the way in, so a roughness of 0.7 would reach the shader as
    # 0.7^(1/2.2) = 0.85. Non-Color is the only correct space for it.
    orm_image.colorspace_settings.name = "Non-Color"
    orm_node = _get_or_create_node(material, ORM_IMAGE_NODE_NAME, "ShaderNodeTexImage")
    orm_node.image = orm_image

    separate = _get_or_create_node(
        material, SEPARATE_NODE_NAME, "ShaderNodeSeparateColor"
    )
    mix = _get_or_create_node(material, AO_MIX_NODE_NAME, "ShaderNodeMix")
    # data_type and blend_type BEFORE the sockets are addressed: the
    # socket NAMES change with data_type, so the indices below are only
    # the colour pair once data_type is RGBA.
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs[MIX_FACTOR_INDEX].default_value = 1.0

    _link_direct(links, orm_node.outputs["Color"], separate.inputs["Color"])
    _link_direct(
        links,
        base_color_node.outputs["Color"],
        mix.inputs[MIX_A_COLOR_INDEX],
    )
    _link_direct(
        links,
        separate.outputs[SEPARATE_RED_INDEX],
        mix.inputs[MIX_B_COLOR_INDEX],
    )
    _link_direct(
        links,
        mix.outputs[MIX_RESULT_COLOR_INDEX],
        principled.inputs[BASE_COLOR_INPUT_NAME],
    )
    _link_direct(
        links,
        separate.outputs[SEPARATE_GREEN_INDEX],
        principled.inputs["Roughness"],
    )
    _link_direct(
        links,
        separate.outputs[SEPARATE_BLUE_INDEX],
        principled.inputs["Metallic"],
    )


def _clear_normal_map(material, links, principled) -> None:
    """Remove the normal map's wiring, so a re-run without one is not a second path."""
    normal_map = material.node_tree.nodes.get(NORMAL_MAP_NODE_NAME)
    if normal_map is None:
        return
    for link in list(principled.inputs["Normal"].links):
        links.remove(link)
    material.node_tree.nodes.remove(normal_map)


def _wire_normal_map(
    material, links, principled, mesh_object, normal_path: Path
) -> None:
    """Wire the tangent-space normal map into the Principled's Normal input."""
    import bpy

    normal_image = bpy.data.images.load(str(normal_path), check_existing=True)
    normal_image.colorspace_settings.name = "Non-Color"
    normal_node = _get_or_create_node(
        material, NORMAL_IMAGE_NODE_NAME, "ShaderNodeTexImage"
    )
    normal_node.image = normal_image

    normal_map = _get_or_create_node(
        material, NORMAL_MAP_NODE_NAME, "ShaderNodeNormalMap"
    )
    normal_map.space = "TANGENT"
    uv_layer = _active_uv_layer_name(mesh_object)
    if uv_layer:
        normal_map.uv_map = uv_layer

    _link_direct(
        links, normal_node.outputs["Color"], normal_map.inputs[NORMAL_MAP_COLOR_INDEX]
    )
    _link_direct(links, normal_map.outputs["Normal"], principled.inputs["Normal"])


def _active_uv_layer_name(mesh_object) -> str:
    """The UV layer the normal map must use: the mesh's active one, else the first."""
    return _mesh_uv_layer_name(mesh_object)


def _position_nodes(material) -> None:
    """Lay the graph out left to right, so a human reading it can follow it."""
    positions = {
        IMAGE_NODE_NAME: (-800.0, 400.0),
        ORM_IMAGE_NODE_NAME: (-800.0, 100.0),
        SEPARATE_NODE_NAME: (-560.0, 100.0),
        AO_MIX_NODE_NAME: (-320.0, 400.0),
        NORMAL_IMAGE_NODE_NAME: (-800.0, -200.0),
        NORMAL_MAP_NODE_NAME: (-320.0, -200.0),
        PRINCIPLED_NODE_NAME: (0.0, 200.0),
    }
    for node_name, location in positions.items():
        node = material.node_tree.nodes.get(node_name)
        if node is not None:
            node.location = location


@op(reads_only=True)
def pbr_texture_report(object_name: str) -> PbrTextureReport:
    """Report what the named mesh's PBR material has wired; reads the graph, changes nothing."""
    from golem_blender.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    material = mesh_object.data.materials[0] if mesh_object.data.materials else None

    if material is None or material.node_tree is None:
        return PbrTextureReport(
            material_name=material.name if material is not None else "",
            base_color_path="",
            orm_path="",
            normal_path="",
            orm_channels=ORM_CHANNEL_PACKING,
            uv_layer=_mesh_uv_layer_name(mesh_object),
            base_color_linked=False,
            normal_linked=False,
            metallic_linked=False,
            roughness_linked=False,
            ao_multiplied=False,
        )

    tree = material.node_tree
    principled = tree.nodes.get(PRINCIPLED_NODE_NAME)
    base_color_linked = False
    normal_linked = False
    metallic_linked = False
    roughness_linked = False
    ao_multiplied = False
    base_color_path = ""
    orm_path = ""
    normal_path = ""

    if principled is not None:
        base_color_input = principled.inputs.get(BASE_COLOR_INPUT_NAME)
        if base_color_input is not None and base_color_input.links:
            base_color_linked = True
            source = base_color_input.links[0].from_node
            if source.bl_idname == "ShaderNodeMix":
                # The ORM's AO multiplies the base colour, so the base
                # colour image sits in the Mix node's A input.
                ao_multiplied = True
                base_color_path = _image_path_of(source.inputs[MIX_A_COLOR_INDEX])
            elif source.bl_idname == "ShaderNodeTexImage":
                base_color_path = _image_path_of(source)

        normal_input = principled.inputs.get("Normal")
        if normal_input is not None and normal_input.links:
            normal_linked = True
            normal_map = normal_input.links[0].from_node
            if normal_map.bl_idname == "ShaderNodeNormalMap":
                colour_input = normal_map.inputs.get("Color")
                if colour_input is not None and colour_input.links:
                    source = colour_input.links[0].from_node
                    if (
                        source.bl_idname == "ShaderNodeTexImage"
                        and source.image is not None
                    ):
                        normal_path = source.image.filepath

        metallic_input = principled.inputs.get("Metallic")
        if metallic_input is not None and metallic_input.links:
            metallic_linked = True
        roughness_input = principled.inputs.get("Roughness")
        if roughness_input is not None and roughness_input.links:
            roughness_linked = True

    orm_node = tree.nodes.get(ORM_IMAGE_NODE_NAME)
    if orm_node is not None and orm_node.image is not None:
        orm_path = orm_node.image.filepath

    return PbrTextureReport(
        material_name=material.name,
        base_color_path=base_color_path,
        orm_path=orm_path,
        normal_path=normal_path,
        orm_channels=ORM_CHANNEL_PACKING,
        uv_layer=_mesh_uv_layer_name(mesh_object),
        base_color_linked=base_color_linked,
        normal_linked=normal_linked,
        metallic_linked=metallic_linked,
        roughness_linked=roughness_linked,
        ao_multiplied=ao_multiplied,
    )


def _image_path_of(socket) -> str:
    """The file path of the image feeding a socket, or an empty string."""
    if not socket.links:
        return ""
    source = socket.links[0].from_node
    if source.bl_idname == "ShaderNodeTexImage" and source.image is not None:
        return source.image.filepath
    return ""


def _mesh_uv_layer_name(mesh_object) -> str:
    """The mesh's active UV layer name, or the first one's, or none."""
    layers = mesh_object.data.uv_layers
    if not layers:
        return ""
    active = layers.active
    return active.name if active is not None else layers[0].name
