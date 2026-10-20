"""Loading an image from disk, so a REGENERATED file is not read stale.

`bpy.data.images.load(path, check_existing=True)` returns the
datablock Blender already holds for that PATH — with its OLD pixels.
The texture lane regenerates at the same path every iteration, so
that is not an edge case, it is the normal case: measured, a map
written red, then regenerated blue at the same path, was read back
RED by the next load, and the agent saw no change.

So every image load in the texture lane goes through here, which
reloads the pixels from disk.
"""

from __future__ import annotations

from pathlib import Path


def load_image(image_path: Path, *, non_color: bool = False):
    """Load an image, reading the pixels that are on disk NOW.

    `non_color` marks the image as DATA rather than colour: a normal
    map, an ORM, a height field. Loaded as sRGB its values would be
    gamma-decoded on the way in — a roughness of 0.7 would reach the
    shader as 0.7^(1/2.2) = 0.85.
    """
    import bpy

    image = bpy.data.images.load(str(image_path), check_existing=True)
    # The datablock may be one the file already had, holding the
    # pixels as they were before the file was regenerated. Reloading
    # is what makes the load see the current file.
    image.reload()
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return image


def load_image_fresh(image_path: Path, *, non_color: bool = False):
    """Load an image into a NEW datablock, so nothing stale survives.

    The counterpart to `load_image`: it does not share the datablock
    with anything else, so the pixels cannot be another's. The
    caller owns the datablock and must remove it.
    """
    import bpy

    image = bpy.data.images.load(str(image_path), check_existing=False)
    if non_color:
        image.colorspace_settings.name = "Non-Color"
    return image
