"""Render the UV atlas as an inspectable image.

Geometry gets four viewport renders; the UV layout gets this. Islands
are drawn in distinct colors so packing, seams, wasted space, and
overlaps are all readable at a glance — the texture lane's equivalent
of the contact sheet.
"""

from __future__ import annotations

from pathlib import Path

UV_IMAGE_SIZE_PX = 512
UV_BACKGROUND_COLOR = (26, 26, 28)
UV_SQUARE_COLOR = (70, 70, 76)
UV_EDGE_WIDTH_PX = 1
# Distinct hues so adjacent islands never share a color by accident.
ISLAND_PALETTE = (
    (122, 176, 255),
    (255, 176, 122),
    (150, 220, 150),
    (230, 150, 220),
    (240, 220, 130),
    (140, 220, 220),
    (220, 140, 140),
    (180, 180, 240),
)


def render_uv_layout(
    blender_object,
    output_path: Path,
    image_size_px: int = UV_IMAGE_SIZE_PX,
) -> Path:
    """Draw the active UV layer's islands into a PNG; return the path."""
    import bmesh

    from blended.capture.compose import pillow_available

    if not pillow_available():
        raise RuntimeError(
            "render_uv_layout needs Pillow, which Blender does not bundle. "
            "Install it into Blender's Python, or inspect UVs numerically "
            "via the analyzer's uv_* fields instead."
        )
    from PIL import Image, ImageDraw

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (image_size_px, image_size_px), UV_BACKGROUND_COLOR)
    drawing = ImageDraw.Draw(image)
    drawing.rectangle(
        [0, 0, image_size_px - 1, image_size_px - 1], outline=UV_SQUARE_COLOR
    )

    working_mesh = bmesh.new()
    working_mesh.from_mesh(blender_object.data)
    try:
        uv_layer = working_mesh.loops.layers.uv.active
        if uv_layer is None:
            drawing.text((8, 8), "no UV layer", fill=(220, 90, 90))
            image.save(output_path)
            return output_path

        # Group faces into islands so each gets its own color.
        island_index_by_face: dict = {}
        unvisited_faces = set(working_mesh.faces)
        island_index = 0
        while unvisited_faces:
            frontier = [unvisited_faces.pop()]
            island_index_by_face[frontier[0]] = island_index
            while frontier:
                current_face = frontier.pop()
                for current_loop in current_face.loops:
                    shared_edge = current_loop.edge
                    for neighbor_face in shared_edge.link_faces:
                        if neighbor_face not in unvisited_faces:
                            continue
                        current_edge_uvs = {
                            tuple(round(c, 6) for c in loop[uv_layer].uv)
                            for loop in current_face.loops
                            if loop.vert in shared_edge.verts
                        }
                        neighbor_edge_uvs = {
                            tuple(round(c, 6) for c in loop[uv_layer].uv)
                            for loop in neighbor_face.loops
                            if loop.vert in shared_edge.verts
                        }
                        if current_edge_uvs == neighbor_edge_uvs:
                            unvisited_faces.remove(neighbor_face)
                            island_index_by_face[neighbor_face] = island_index
                            frontier.append(neighbor_face)
            island_index += 1

        for face in working_mesh.faces:
            face_color = ISLAND_PALETTE[
                island_index_by_face.get(face, 0) % len(ISLAND_PALETTE)
            ]
            # UV origin is bottom-left; image origin is top-left.
            pixel_points = [
                (
                    loop[uv_layer].uv[0] * (image_size_px - 1),
                    (1.0 - loop[uv_layer].uv[1]) * (image_size_px - 1),
                )
                for loop in face.loops
            ]
            drawing.polygon(pixel_points, outline=face_color, width=UV_EDGE_WIDTH_PX)
    finally:
        working_mesh.free()

    image.save(output_path)
    return output_path
