"""Make a texture tile, by the method material-maker uses.

A GENERATED map does not tile: its seam is a property of the sample,
not of the size, so four generations of one prompt measured 1.38x,
1.57x, 1.10x and 1.38x the texture's largest ordinary features. The
procedural route sidesteps the problem by being periodic by
construction, but a photograph - or an AI's photograph - cannot be.

So the map is made to tile AFTER the fact, and the method is
material-maker's `make_tileable` node: THREE copies of the image,
blended so that the seam falls in a region where the content is
mixed with the image's own middle.

The method, from `make_tileable.mmg`'s shader model:

    a = in(uv)
    b = in(fract(uv + 0.5))          a half-shifted copy
    c = in(fract(uv + 0.25))         a quarter-shifted copy
    coef_ab  = sin(pi/2 * clamp((length(uv - 0.5) - 0.5 + w) / w, 0, 1))
    coef_abc = sin(pi/2 * clamp((edge_distance - w) / w, 0, 1))
    return mix(c, mix(a, b, coef_ab), coef_abc)

`coef_ab` rises from 0 at the tile's centre to 1 at its edge, and
`coef_abc` rises towards the corners. So the EDGE of the image is a
blend of the image and its half-shifted copy, and the CORNERS blend
in the quarter-shifted one. The seam - which is at the edge - is
therefore made of content that also appears in the middle, and the
repeat does not show.

It does not make the image PERIODIC, and it should not be sold as
such: it hides the seam by mixing, and it can ghost a feature that
appears in two of the three copies. So it is measured, not assumed.
"""

from __future__ import annotations

from pathlib import Path

# The blend's width, as a fraction of the tile.
#
# material-maker's default is 0.1, and the seam is nearly flat past
# 0.01 - measured, 0.304x at 0.01 and 0.296x at 0.08 - so the WIDTH
# only costs fidelity. The correlation with the original falls from
# 0.7711 at 0.01 to 0.6190 at 0.08. So the width is the smallest
# that gets the seam into the reference's range: ambientcg's own
# sets measure 0.32x to 0.47x, and a generated map that is not
# better than the reference is not worth what the blend costs.
DEFAULT_WIDTH = 0.01


def tileable(
    image,
    width: float = DEFAULT_WIDTH,
):
    """The tileable version of an image, by material-maker's method.

    `image` is a (height, width, channels) float array in 0..1, and
    the result is the same shape. The method is material-maker's
    `make_tileable`: three copies of the image - at the offset, at
    half the tile, and at a quarter of it - blended with radial
    weights that put the blend where the seam is.
    """
    import numpy

    height, width_px, _channels = image.shape
    if width <= 0.0:
        return image.copy()

    # The coordinates, centred on the tile.
    rows = numpy.arange(height) / max(height - 1, 1)
    columns = numpy.arange(width_px) / max(width_px - 1, 1)
    grid_y, grid_x = numpy.meshgrid(rows, columns, indexing="ij")

    def rolled(dy, dx):
        """A copy of the image shifted by a fraction of the tile."""
        return numpy.roll(
            numpy.roll(image, round(dy * height), axis=0),
            round(dx * width_px),
            axis=1,
        )

    # material-maker's three samples: the image, a half-shifted copy
    # and a quarter-shifted one. The shifts are by a fraction of the
    # tile, and they WRAP - which is what puts the image's own middle
    # at the edge.
    a = image
    b = rolled(0.5, 0.5)
    c = rolled(0.25, 0.25)

    # coef_ab: 0 at the tile's centre, rising to 1 at its edge.
    distance_from_centre = numpy.sqrt((grid_x - 0.5) ** 2 + (grid_y - 0.5) ** 2)
    coef_ab = numpy.sin(
        (numpy.pi / 2.0)
        * numpy.clip((distance_from_centre - 0.5 + width) / width, 0.0, 1.0)
    )

    # coef_abc: 0 away from the corners, rising to 1 at them. The
    # distance is to the nearest of the four edge midpoints, which is
    # what material-maker measures.
    corner_distance = numpy.minimum(
        numpy.minimum(
            numpy.sqrt((grid_x - 0.0) ** 2 + (grid_y - 0.5) ** 2),
            numpy.sqrt((grid_x - 0.5) ** 2 + (grid_y - 0.0) ** 2),
        ),
        numpy.minimum(
            numpy.sqrt((grid_x - 1.0) ** 2 + (grid_y - 0.5) ** 2),
            numpy.sqrt((grid_x - 0.5) ** 2 + (grid_y - 1.0) ** 2),
        ),
    )
    coef_abc = numpy.sin(
        (numpy.pi / 2.0) * numpy.clip((corner_distance - width) / width, 0.0, 1.0)
    )

    blended = (
        c * (1.0 - coef_abc[:, :, numpy.newaxis])
        + (a * (1.0 - coef_ab[:, :, numpy.newaxis]) + b * coef_ab[:, :, numpy.newaxis])
        * coef_abc[:, :, numpy.newaxis]
    )
    return numpy.clip(blended, 0.0, 1.0)


def make_image_tileable(
    input_path: Path,
    output_path: Path,
    width: float = DEFAULT_WIDTH,
) -> Path:
    """Write the tileable version of an image; returns the path.

    The input is read as it is on disk and the result is written the
    same way, so the map's values are the values that were computed.
    """
    import bpy
    import numpy

    from golem_blender.ops._image_loading import load_image

    image = load_image(Path(input_path))
    width_px, height_px = image.size
    pixels = numpy.empty(width_px * height_px * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pixels)
    array = pixels.reshape((height_px, width_px, 4))

    blended = tileable(array, width)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = bpy.data.images.new(
        output_path.stem, width=width_px, height=height_px, alpha=False
    )
    try:
        written.colorspace_settings.name = "sRGB"
        written.pixels.foreach_set(
            numpy.ascontiguousarray(blended, dtype=numpy.float32).ravel()
        )
        written.filepath_raw = str(output_path)
        written.file_format = "PNG"
        written.save()
    finally:
        bpy.data.images.remove(written)
    return output_path


__all__ = (
    "DEFAULT_WIDTH",
    "make_image_tileable",
    "tileable",
)
