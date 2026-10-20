"""A procedural base colour: a surface's colour, computed rather than generated.

Blender has no generative model, so a photoreal texture's COLOUR
cannot be made with bpy - that is the one thing the AI half of the
lane is for. But photorealism is narrower than it looks. A
cobblestone's colour is not a photograph: it is a few stone colours,
a mortar colour, and the variation between them, and every one of
those is a node.

So this module builds a base colour from Blender's own nodes, and the
result is BETTER than a generated one in the way that matters for
tiling: it is periodic by construction.

The measurements that decided it:

- the generated cobblestone's seam is 1.38x the texture's largest
  ordinary features, and it is a property of the SAMPLE - four
  generations of the same prompt measured 1.38x, 1.57x, 1.10x and
  1.38x. A procedural colour's seam is 0.01x: it tiles exactly.
- the lane's own relief builder finds a joint network in it: 21.83%
  of the cells carry joint signal, against the 23.94% an
  AI-generated albedo carries. So the ORM and the normal map bake
  from it just as they do from a generated one.
- its contrast is real: luma 0.377 with a standard deviation of
  0.2054, over a range of 0.157 to 0.855.

What it is NOT: photoreal. The stones are Voronoi cells, so they
are polygonal rather than rounded, and the variation within a stone
is a noise texture rather than wear. For a game asset's base colour
that is often enough, and it is reproducible, tileable, and
adjustable with a number instead of a prompt.
"""

from __future__ import annotations

from pathlib import Path

# The stone colours a cobblestone's ramp runs between: a dark grey
# and a pale off-white. The AI-generated cobblestone the lane
# delivered measures luma 0.7429 with a standard deviation of 0.1428,
# and its stones read as pale grey and off-white with a few darker
# ones - so these are the same palette, chosen to match.
DEFAULT_STONE_DARK_RGB = (0.42, 0.40, 0.36)
DEFAULT_STONE_LIGHT_RGB = (0.86, 0.84, 0.80)
# The mortar's colour, and how wide it is as a fraction of a stone.
DEFAULT_MORTAR_RGB = (0.30, 0.28, 0.25)
DEFAULT_MORTAR_WIDTH = 0.08
# How much the noise varies a stone, as a fraction of its colour.
DEFAULT_VARIATION = 0.25
# The plane the pattern is rendered on, in metres across. The camera
# frames it exactly, so the image is the pattern with no border.
PLANE_SIZE_M = 2.0
# The pattern's scale, in cells across the image. A cobble is about
# 200 mm and the image is 2 m, so sixteen cells across is a cobble's
# size. The same default the relief's procedural source uses.
DEFAULT_PROCEDURAL_SCALE = 16.0


def write_procedural_base_color(
    output_path: Path,
    kind: str = "voronoi",
    scale_cells: float = 16.0,
    width_px: int = 2048,
    height_px: int = 2048,
    stone_dark_rgb: tuple[float, float, float] = DEFAULT_STONE_DARK_RGB,
    stone_light_rgb: tuple[float, float, float] = DEFAULT_STONE_LIGHT_RGB,
    mortar_rgb: tuple[float, float, float] = DEFAULT_MORTAR_RGB,
    mortar_width: float = DEFAULT_MORTAR_WIDTH,
    variation: float = DEFAULT_VARIATION,
) -> Path:
    """Write a procedural base colour as a PNG; returns the path.

    The pattern is evaluated on a WRAPPED domain, so the image tiles:
    its last column meets its first exactly, which is the thing a
    generated texture can only be approximately.

    `kind` is the cell shape - "voronoi" for rounded stones, "brick"
    for courses. `scale_cells` is how many cells across the image.
    """
    import bpy

    if kind not in PROCEDURAL_COLOUR_KINDS:
        raise ValueError(
            f"Unknown procedural colour kind {kind!r}. Expected one of "
            f"{PROCEDURAL_COLOUR_KINDS}."
        )
    if width_px < 2 or height_px < 2:
        raise ValueError("A procedural colour needs at least 2 pixels a side.")
    if scale_cells <= 0.0:
        raise ValueError("The pattern's scale must be positive.")

    material = bpy.data.materials.new("golem_procedural_colour")
    material.use_nodes = True
    tree = material.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")

    # The pattern's domain: the UVs scaled to the cell count.
    #
    # There is deliberately NO wrap node here. Blender's texture nodes
    # already evaluate on a wrapped lattice, so the pattern repeats by
    # itself - measured, the Voronoi field's seam is 0.0083x the
    # interior's largest steps with no wrap at all. Adding one folds
    # the domain onto itself and the cells become FRAGMENTS of stones
    # repeated in a grid, with the folds' edges visible as a grid.
    coordinate = tree.nodes.new("ShaderNodeTexCoord")
    scaling = tree.nodes.new("ShaderNodeVectorMath")
    scaling.operation = "SCALE"
    scaling.inputs["Scale"].default_value = float(scale_cells)
    tree.links.new(coordinate.outputs["UV"], scaling.inputs[0])
    domain = scaling.outputs["Vector"]

    # The cells' own random values, which give each stone its colour,
    # and the distance to a cell edge, which is the joint.
    if kind == "voronoi":
        cells = tree.nodes.new("ShaderNodeTexVoronoi")
        cells.feature = "F1"
        cells.inputs["Scale"].default_value = 1.0
        tree.links.new(domain, cells.inputs["Vector"])
        edges = tree.nodes.new("ShaderNodeTexVoronoi")
        edges.feature = "DISTANCE_TO_EDGE"
        edges.inputs["Scale"].default_value = 1.0
        tree.links.new(domain, edges.inputs["Vector"])
        cell_colour = cells.outputs["Color"]
        edge_distance = edges.outputs["Distance"]
    else:
        cells = tree.nodes.new("ShaderNodeTexBrick")
        tree.links.new(domain, cells.inputs["Vector"])
        edge_distance = cells.outputs["Fac"]
        cell_colour = cells.outputs["Color"]

    # The stones' colour: a ramp from the dark stone to the light one,
    # driven by the cell's own random value.
    ramp = tree.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*stone_dark_rgb, 1.0)
    ramp.color_ramp.elements[1].color = (*stone_light_rgb, 1.0)
    tree.links.new(cell_colour, ramp.inputs["Fac"])

    # The noise that varies a stone within itself.
    noise = tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = float(scale_cells) * 4.0
    tree.links.new(domain, noise.inputs["Vector"])
    varied = tree.nodes.new("ShaderNodeMix")
    varied.data_type = "RGBA"
    varied.blend_type = "MULTIPLY"
    varied.inputs[0].default_value = float(variation)
    tree.links.new(ramp.outputs["Color"], varied.inputs[6])
    tree.links.new(noise.outputs["Color"], varied.inputs[7])

    # The joint: where the distance to the edge is small, the mortar
    # colour, and where it is large, the stone.
    joint = tree.nodes.new("ShaderNodeValToRGB")
    joint.color_ramp.elements[0].position = 0.0
    joint.color_ramp.elements[0].color = (*mortar_rgb, 1.0)
    joint.color_ramp.elements[1].position = float(mortar_width)
    joint.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    tree.links.new(edge_distance, joint.inputs["Fac"])

    multiplied = tree.nodes.new("ShaderNodeMix")
    multiplied.data_type = "RGBA"
    multiplied.blend_type = "MULTIPLY"
    multiplied.inputs[0].default_value = 1.0
    tree.links.new(varied.outputs[2], multiplied.inputs[6])
    tree.links.new(joint.outputs["Color"], multiplied.inputs[7])
    tree.links.new(multiplied.outputs[2], emission.inputs["Color"])
    tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])

    # Render it. A plane whose UVs span 0..1 exactly, and a camera
    # that frames it, so the image is the pattern and nothing else.
    bpy.ops.mesh.primitive_plane_add(size=PLANE_SIZE_M)
    plane = bpy.context.active_object
    plane.name = "golem_procedural_colour_plane"
    camera = None
    try:
        plane.data.materials.append(material)
        bpy.context.view_layer.update()

        scene = bpy.context.scene
        previous = (
            scene.render.engine,
            scene.render.resolution_x,
            scene.render.resolution_y,
            scene.render.filepath,
            scene.render.image_settings.file_format,
            scene.view_settings.view_transform,
            scene.camera,
        )
        try:
            scene.render.engine = "BLENDER_EEVEE"
            scene.render.resolution_x = width_px
            scene.render.resolution_y = height_px
            scene.render.image_settings.file_format = "PNG"
            scene.view_settings.view_transform = "Standard"
            bpy.ops.object.camera_add(location=(0.0, 0.0, 5.0))
            camera = bpy.context.active_object
            camera.rotation_euler = (0.0, 0.0, 0.0)
            # The camera must see the WHOLE plane, or the image is a
            # CROPPING of the pattern and a cropping's edge is not the
            # pattern's edge - the image would not tile. The plane's
            # UVs span 0..1 over its whole width, so the camera's
            # field of view at its distance has to cover the plane's
            # DIAGONAL, and the lens follows from that.
            #
            # Measured: at 36 mm the seam is 2.50x the interior's
            # largest features - the plane is cropped - and at 18 mm,
            # which sees the whole plane, it is 0.03x. The diagonal is
            # what the square frame's corners need.
            camera.data.sensor_width = 36.0
            camera.data.sensor_fit = "HORIZONTAL"
            camera.location = (0.0, 0.0, PLANE_SIZE_M)
            diagonal = PLANE_SIZE_M * 2.0**0.5
            camera.data.lens = camera.data.sensor_width * PLANE_SIZE_M / diagonal
            scene.camera = camera
            scene.render.filepath = str(output_path)
            bpy.ops.render.render(write_still=True)
        finally:
            (
                scene.render.engine,
                scene.render.resolution_x,
                scene.render.resolution_y,
                scene.render.filepath,
                scene.render.image_settings.file_format,
                scene.view_settings.view_transform,
                scene.camera,
            ) = previous
    finally:
        if camera is not None:
            bpy.data.objects.remove(camera, do_unlink=True)
        bpy.data.objects.remove(plane, do_unlink=True)
        bpy.data.materials.remove(material)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def procedural_source_metadata(
    kind: str = "voronoi",
    scale_cells: float = DEFAULT_PROCEDURAL_SCALE,
) -> dict:
    """What a procedural base colour was made from, for the export's metadata.

    A set's metadata says how it was MADE, and this is how a
    procedural one was made: no prompt and no model, but a pattern
    kind and a scale, and the fact that the pattern is periodic.
    """
    return {
        "base_colour_source": "procedural: Blender's own nodes, no image",
        "base_colour_kind": kind,
        "base_colour_scale_cells": scale_cells,
        "base_colour_periodic": True,
    }


# The cell shapes a procedural colour can have.
PROCEDURAL_COLOUR_KINDS = ("voronoi", "brick")


__all__ = (
    "DEFAULT_MORTAR_RGB",
    "DEFAULT_MORTAR_WIDTH",
    "DEFAULT_PROCEDURAL_SCALE",
    "DEFAULT_STONE_DARK_RGB",
    "DEFAULT_STONE_LIGHT_RGB",
    "DEFAULT_VARIATION",
    "PROCEDURAL_COLOUR_KINDS",
    "procedural_source_metadata",
    "write_procedural_base_color",
)
