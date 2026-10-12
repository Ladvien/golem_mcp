"""Procedural and image-texture material ops through the data API.

Extends the flat-colour op (``materials.assign_material``) with shader
nodes: noise/checker/brick/wave textures for procedural materials and
image-file textures for painted assets. Every op reuses a material
datablock by name (idempotent by name, same convention as
``materials.assign_material``) and reuses the blended-prefixed texture
node by name so a re-run updates rather than duplicates.

Why diffuse_color is set alongside the node graph: Workbench — the
engine every inspection render uses — does not read the shader graph at
all. It reads ``material.diffuse_color``. A procedural checker with two
bright colours and a grey ``diffuse_color`` renders grey. Set both,
always (measured in ``materials.py`` iteration 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from blended.ops._contract import op

PRINCIPLED_NODE_NAME = "Principled BSDF"
BASE_COLOR_INPUT_NAME = "Base Color"

# Texture-node bl_idtype per procedural kind. Each maps to the
# corresponding ShaderNodeTex* node; kept as a tuple+dict so the kind
# list is the single source of truth and the report can iterate it.
PROCEDURAL_KINDS = ("noise", "checker", "brick", "wave")
NODE_TYPE_BY_KIND = {
    "noise": "ShaderNodeTexNoise",
    "checker": "ShaderNodeTexChecker",
    "brick": "ShaderNodeTexBrick",
    "wave": "ShaderNodeTexWave",
}

# Reused node names — idempotent by name within the material's node tree.
TEXTURE_NODE_NAME = "blended_texture"
TEX_COORD_NODE_NAME = "blended_tex_coord"
MAPPING_NODE_NAME = "blended_mapping"
IMAGE_NODE_NAME = "blended_image"

DEFAULT_TEXTURE_SCALE = 5.0
DEFAULT_COLOR_A_RGB = (0.8, 0.8, 0.8)
DEFAULT_COLOR_B_RGB = (0.2, 0.2, 0.2)


@dataclass(frozen=True)
class MaterialReport:
    """Snapshot of the first material slot's shader graph."""

    material_names: tuple[str, ...]
    node_type_counts: dict[str, int]
    base_color_linked: bool
    texture_kinds: tuple[str, ...]
    image_paths: tuple[str, ...]


def _ensure_principled(material):
    """Return the Principled BSDF node, raising if it is absent.

    A fresh 5.2 material always has one named ``Principled BSDF``; if it
    is missing the default tree changed and this op must be fixed, not
    worked around.
    """
    principled = material.node_tree.nodes.get(PRINCIPLED_NODE_NAME)
    if principled is None:
        raise RuntimeError(
            f"Material {material.name!r} has no {PRINCIPLED_NODE_NAME!r} "
            f"node. The default node tree changed; fix this op."
        )
    return principled


def _get_or_create_node(material, node_name, bl_idtype):
    """Reuse a node by name or create a new one of the given type."""

    node = material.node_tree.nodes.get(node_name)
    if node is None:
        node = material.node_tree.nodes.new(bl_idtype)
        node.name = node_name
    return node


def _ensure_tex_coord_and_mapping(material, scale):
    """Create/reuse TexCoord + Mapping nodes; set Mapping scale to ``scale``.

    The scale is applied on the Mapping node (not the texture node's own
    Scale input) so a single uniform control point covers all four
    procedural kinds — some have a Scale input, others do not.
    """
    tex_coord = _get_or_create_node(material, TEX_COORD_NODE_NAME, "ShaderNodeTexCoord")
    mapping = _get_or_create_node(material, MAPPING_NODE_NAME, "ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)

    links = material.node_tree.links
    # Re-link: unlink any stale TexCoord -> Mapping link first, then
    # re-add so a re-run does not stack duplicate links.
    for link in list(links):
        if link.from_node == tex_coord and link.to_node == mapping:
            links.remove(link)
    links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])
    return tex_coord, mapping


def assign_procedural_material(
    object_name: str,
    name: str,
    kind: str,
    scale: float = DEFAULT_TEXTURE_SCALE,
    color_a_rgb: tuple[float, float, float] = DEFAULT_COLOR_A_RGB,
    color_b_rgb: tuple[float, float, float] = DEFAULT_COLOR_B_RGB,
) -> str:
    """Create/reuse a procedural-texture material and assign it as the named mesh's only slot.

    `kind` is one of PROCEDURAL_KINDS. Idempotent by material name and by
    node name: re-running the same call updates the existing
    texture/mapping nodes instead of stacking duplicates. Returns the
    material's name.
    """
    import bpy

    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")

    if kind not in NODE_TYPE_BY_KIND:
        raise ValueError(
            f"Unknown procedural kind {kind!r}. Expected one of {PROCEDURAL_KINDS}."
        )

    node_bl_type = NODE_TYPE_BY_KIND[kind]

    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    principled = _ensure_principled(material)
    tree = material.node_tree
    links = tree.links

    # --- texture coordinate + mapping feeding the texture node ---
    _tex_coord, mapping = _ensure_tex_coord_and_mapping(material, scale)

    # --- texture node ---
    texture_node = _get_or_create_node(material, TEXTURE_NODE_NAME, node_bl_type)
    # If the node already exists but is the wrong type (kind changed),
    # remove it and create the correct one.
    if texture_node.bl_idname != node_bl_type:
        tree.nodes.remove(texture_node)
        texture_node = tree.nodes.new(node_bl_type)
        texture_node.name = TEXTURE_NODE_NAME

    # Position nodes left-to-right for readability.
    principled.location = (300.0, 300.0)
    texture_node.location = (0.0, 300.0)
    mapping.location = (-400.0, 300.0)

    # Link Mapping -> texture Vector
    for link in list(links):
        if link.from_node == mapping and link.to_node == texture_node:
            links.remove(link)
    links.new(mapping.outputs["Vector"], texture_node.inputs["Vector"])

    # Link texture Color -> Principled Base Color (remove stale links first)
    base_color_input = principled.inputs[BASE_COLOR_INPUT_NAME]
    for link in list(base_color_input.links):
        links.remove(link)
    links.new(texture_node.outputs["Color"], base_color_input)

    # --- colour inputs per kind ---
    # Checker and Brick have Color1/Color2; Noise/Wave have no colour
    # inputs (they output a scalar factor) — their colour comes from
    # the Principled BSDF default, which we set to color_a for Workbench.
    _set_texture_colors(texture_node, kind, color_a_rgb, color_b_rgb)

    # Workbench reads diffuse_color, not the shader graph (see module
    # docstring and materials.py). Use color_a as the representative
    # viewport colour.
    r_a, g_a, b_a = color_a_rgb
    material.diffuse_color = (r_a, g_a, b_a, 1.0)

    # Assign as the object's only slot.
    mesh_object.data.materials.clear()
    mesh_object.data.materials.append(material)
    return material.name


def _set_texture_colors(texture_node, kind, color_a_rgb, color_b_rgb):
    """Set the colour inputs that exist on the given texture node type."""
    if kind in ("checker", "brick"):
        color1 = texture_node.inputs.get("Color1")
        color2 = texture_node.inputs.get("Color2")
        if color1 is not None:
            r, g, b = color_a_rgb
            color1.default_value = (r, g, b, 1.0)
        if color2 is not None:
            r, g, b = color_b_rgb
            color2.default_value = (r, g, b, 1.0)
    # noise and wave: no color inputs — colour comes from diffuse_color
    # and the Principled BSDF default for Workbench/Eevee solid shading.


def assign_image_texture_material(object_name: str, name: str, image_path: Path) -> str:
    """Create/reuse an image-texture material and assign it as the named mesh's only slot.

    Raises FileNotFoundError if ``image_path`` does not exist.
    Returns the material's name.
    """
    import bpy

    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")

    image_path = Path(image_path)
    if not image_path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)

    principled = _ensure_principled(material)
    tree = material.node_tree
    links = tree.links

    image = bpy.data.images.load(str(image_path), check_existing=True)

    image_node = _get_or_create_node(material, IMAGE_NODE_NAME, "ShaderNodeTexImage")
    image_node.image = image

    # Position nodes left-to-right.
    principled.location = (300.0, 300.0)
    image_node.location = (0.0, 300.0)

    # Link image Color -> Principled Base Color (remove stale links first)
    base_color_input = principled.inputs[BASE_COLOR_INPUT_NAME]
    for link in list(base_color_input.links):
        links.remove(link)
    links.new(image_node.outputs["Color"], base_color_input)

    # Workbench reads diffuse_color; use the image's average as a
    # representative viewport colour so the render is not grey.
    _sync_diffuse_from_image(material, image)

    mesh_object.data.materials.clear()
    mesh_object.data.materials.append(material)
    return material.name


def _sync_diffuse_from_image(material, image):
    """Set diffuse_color to the average pixel of the image for Workbench."""
    pixels = list(image.pixels)
    if not pixels:
        return
    channels = image.channels
    pixel_count = len(pixels) // channels
    if pixel_count == 0:
        return
    r_total = g_total = b_total = 0.0
    for i in range(pixel_count):
        base = i * channels
        r_total += pixels[base]
        g_total += pixels[base + 1]
        b_total += pixels[base + 2]
    r_avg = r_total / pixel_count
    g_avg = g_total / pixel_count
    b_avg = b_total / pixel_count
    material.diffuse_color = (r_avg, g_avg, b_avg, 1.0)


@op(reads_only=True)
def material_report(object_name: str) -> MaterialReport:
    """Snapshot the named mesh's first material slot shader graph for assertion."""
    from blended.ops._objects import object_by_name

    mesh_object = object_by_name(object_name, "MESH")
    material_names = tuple(
        mat.name for mat in mesh_object.data.materials if mat is not None
    )

    node_type_counts: dict[str, int] = {}
    texture_kinds: list[str] = []
    image_paths: list[str] = []

    first_mat = mesh_object.data.materials[0] if mesh_object.data.materials else None
    base_color_linked = False

    if first_mat is not None and first_mat.node_tree is not None:
        for node in first_mat.node_tree.nodes:
            node_type_counts[node.bl_idname] = (
                node_type_counts.get(node.bl_idname, 0) + 1
            )

        # Detect texture kinds by node type.
        kind_by_type = {v: k for k, v in NODE_TYPE_BY_KIND.items()}
        for node_type, count in node_type_counts.items():
            if node_type in kind_by_type and count > 0:
                texture_kinds.append(kind_by_type[node_type])

        # Collect image paths from ShaderNodeTexImage nodes.
        for node in first_mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                image_paths.append(node.image.filepath)

        # base_color_linked = Principled Base Color input has a link.
        principled = first_mat.node_tree.nodes.get(PRINCIPLED_NODE_NAME)
        if principled is not None:
            base_color_input = principled.inputs.get(BASE_COLOR_INPUT_NAME)
            if base_color_input is not None and base_color_input.links:
                base_color_linked = True

    return MaterialReport(
        material_names=material_names,
        node_type_counts=node_type_counts,
        base_color_linked=base_color_linked,
        texture_kinds=tuple(texture_kinds),
        image_paths=tuple(image_paths),
    )
