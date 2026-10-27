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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class OrthoCamera:
    """An orthographic camera looking at a target, and the frame it sees.

    The game's own camera is orthographic (`iso_camera.rs`), so a probe built on
    this matches what a player sees. `forward` is the direction the rays travel
    (-`view_direction`); `right` and `up` complete a right-handed frame, and the
    frame's height follows its width from the pixel aspect, so a square pixel
    covers the same distance in both axes.
    """

    target_m: tuple[float, float, float]
    yaw_deg: float
    pitch_deg: float
    frame_width_m: float
    width_px: int
    height_px: int

    @property
    def forward(self) -> tuple[float, float, float]:
        return _scaled(view_direction(self.yaw_deg, self.pitch_deg), -1.0)

    @property
    def right(self) -> tuple[float, float, float]:
        # forward x Z: the camera's own right, independent of its roll. Straight
        # down (or straight up) makes that cross product degenerate, so the
        # convention is +X there — the only choice that keeps a top view's
        # image axes meaning world X and world Y.
        forward = self.forward
        if abs(forward[2]) > NEAR_VERTICAL_FORWARD:
            return (1.0, 0.0, 0.0)
        return _normalised(_cross(forward, (0.0, 0.0, 1.0)))

    @property
    def up(self) -> tuple[float, float, float]:
        return _cross(self.right, self.forward)

    @property
    def frame_height_m(self) -> float:
        return self.frame_width_m * self.height_px / self.width_px


def fit_ortho_camera_to_height(
    corners_m,
    yaw_deg: float,
    pitch_deg: float,
    subject_height_px: int,
    margin_px: int,
) -> OrthoCamera:
    """The camera that draws a point cloud `subject_height_px` tall on screen.

    This is the whole answer to "does the change read at N pixels": the frame
    is built so the SUBJECT spans exactly `subject_height_px`, and every other
    pixel is then a real fraction of the subject. A game character is 55 px
    tall on screen at the report's own scale, so a fold 1 px deep there is a
    fold nobody can see.

    The frame is fitted on the subject's UP axis only; its width follows the
    pixel aspect, and the caller pads both sides with `margin_px` so a subject
    that pokes past its own height still lands inside the frame.

    `corners_m` is any iterable of (x, y, z) world metres — a bounding box's
    eight corners, or a mesh's vertices. Pure arithmetic: no bpy, no numpy.
    """
    if subject_height_px <= 0:
        raise ValueError(f"subject_height_px must be positive, got {subject_height_px}")
    if margin_px < 0:
        raise ValueError(f"margin_px must be 0 or more, got {margin_px}")
    points = [tuple(float(coordinate) for coordinate in point) for point in corners_m]
    if not points:
        raise ValueError("corners_m is empty: nothing to frame")

    # Only the camera's AXES matter for the fit, so its frame is provisional.
    axes = OrthoCamera((0.0, 0.0, 0.0), yaw_deg, pitch_deg, 1.0, 1, 1)
    projected_right = [_dot(point, axes.right) for point in points]
    projected_up = [_dot(point, axes.up) for point in points]
    up_span_m = max(projected_up) - min(projected_up)
    right_span_m = max(projected_right) - min(projected_right)
    if up_span_m <= 0.0:
        raise ValueError(
            "the subject has no extent along the camera's up axis; it is flat "
            "in this view, so there is no height to fit"
        )

    metres_per_px = up_span_m / subject_height_px
    width_px = math.ceil(right_span_m / metres_per_px) + 2 * margin_px
    height_px = subject_height_px + 2 * margin_px
    centre = tuple(
        (
            min(coordinate[index] for coordinate in points)
            + max(coordinate[index] for coordinate in points)
        )
        / 2.0
        for index in range(3)
    )
    return OrthoCamera(
        target_m=centre,
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        frame_width_m=width_px * metres_per_px,
        width_px=width_px,
        height_px=height_px,
    )


def ortho_pixel_ray(
    camera: OrthoCamera, px: float, py: float, back_off_m: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """(origin, direction) of the ray through one pixel's CENTRE.

    Pixel (0, 0) is the top-left of the image, as every image format and every
    screen coordinate system means it: u runs left to right and v downward, so
    the frame's up axis is negated for v. The origin sits `back_off_m` behind
    the target plane along -forward, which is what puts the whole target in
    front of the eye.
    """
    u = (px + PIXEL_CENTRE_OFFSET) / camera.width_px - 0.5
    v = 0.5 - (py + PIXEL_CENTRE_OFFSET) / camera.height_px
    origin = _add(
        _add(
            camera.target_m,
            _add(
                _scaled(camera.right, u * camera.frame_width_m),
                _scaled(camera.up, v * camera.frame_height_m),
            ),
        ),
        _scaled(camera.forward, -back_off_m),
    )
    return origin, camera.forward


def ortho_project(camera: OrthoCamera, point) -> tuple[float, float]:
    """The fractional (px, py) of `point`, the exact inverse of `ortho_pixel_ray`.

    The centre of pixel (px, py) projects back to (px + 0.5, py + 0.5), so
    projecting a ray's own origin returns its own pixel centre — which is the
    round trip a probe's geometry is checked by.
    """
    offset = _subtract(point, camera.target_m)
    u = _dot(offset, camera.right) / camera.frame_width_m
    v = _dot(offset, camera.up) / camera.frame_height_m
    # Pixel EDGE coordinates, the convention `ortho_pixel_ray` reads: pixel px
    # spans [px, px + 1] and its centre is px + 0.5, so a point at a pixel's
    # centre projects to that fraction and never to the index.
    return ((u + 0.5) * camera.width_px, (0.5 - v) * camera.height_px)
