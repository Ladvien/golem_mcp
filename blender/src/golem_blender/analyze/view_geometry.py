"""View directions and orthographic pixel rays, as arithmetic (no bpy, no numpy).

Two of the ops measure what a VIEW can see, so what a view IS has to be one
definition both of them read.

The angle convention is the isometric one the game itself renders with: the
camera orbits at a yaw and a pitch, and the direction reported is the unit
vector FROM the target TOWARD the camera, in Blender's world frame (Z up). It
is the game's own `camera_directions` — pitch 35.264 degrees, eight compass
yaws — mapped from glTF (Y up, -Z forward) into Blender's (Z up, +Y forward) by
`(x, y, z) -> (x, -z, y)`, which is the same mapping the exporter's `export_yup`
inverts. That mapping is pinned by a test against the game's own list, because
a sign slip here reports a face visible from the side it faces away from.

`yaw_deg` 0 looks at the -Y side (Blender's front), 90 the +X side (right);
`pitch_deg` 90 is straight down from above. Pure: importable without Blender.
"""

from __future__ import annotations

import math

# True isometric: asin(1/sqrt(3)) in degrees. The game's own iso camera uses
# it so every axis of a cube foreshortens equally.
ISO_PITCH_DEG = 35.264
# The eight compass yaws. Measured need: a face is "seen" from whichever of
# these escapes, so a face only facing north-west must still be probed.
ISO_YAWS_DEG = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
TOP_VIEW_LABEL = "top"

# Above this the forward vector is (nearly) parallel to Z, so the usual
# up = (0, 0, 1) reference is degenerate and the camera's right axis is fixed.
NEAR_VERTICAL_FORWARD = 0.999
# A pixel centre sits half a pixel in from the pixel's corner.
PIXEL_CENTRE_OFFSET = 0.5


def view_direction(yaw_deg: float, pitch_deg: float) -> tuple[float, float, float]:
    """Unit vector from the target TOWARD the camera, Blender world (Z up).

    yaw 0 is the front (-Y side) view and yaw 90 the right (+X) view; pitch 90
    is straight down from above. The game's own orbit, mapped to Blender.
    """
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    horizontal = math.cos(pitch)
    return (
        math.sin(yaw) * horizontal,
        -math.cos(yaw) * horizontal,
        math.sin(pitch),
    )


def view_label(yaw_deg: float) -> str:
    """The name a report gives a yaw view, e.g. "yaw_45"."""
    return f"yaw_{yaw_deg:g}"


def _normalised(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length == 0.0:
        raise ValueError("cannot normalise a zero vector")
    return tuple(component / length for component in vector)


def _cross(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _subtract(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _add(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (first[0] + second[0], first[1] + second[1], first[2] + second[2])


def _scaled(
    vector: tuple[float, float, float], factor: float
) -> tuple[float, float, float]:
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _dot(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]
