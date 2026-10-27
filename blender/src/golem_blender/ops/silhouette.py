"""Does a change read at the size the game draws it?

Why this op exists: a dressing agent reported it could not answer "does this
crease read on screen". Every measurement the repo had was at full resolution,
and the answer depends on the size. Measured 2026-10-27 on a 1.8 m solid with a
2.7 mm crease, over the game's eight iso directions: the crease moves ONE pixel
at the 55 px a character occupies in the game (the one pixel centre its edge
crosses), one at 110 px, 220 at 220 px and 6000 at 2000 px.

So this op renders NOTHING. It fits an orthographic camera that draws the pair
at exactly `height_px` tall (see `fit_ortho_camera_to_height`) and casts one
ray per pixel centre at both objects. A pixel belongs to an object when a ray
meets a surface there — and, with `cull_backfaces`, when it meets a surface
whose own winding faces the eye, which is what a GPU culls by, not a normal's
agreement with a neighbour.

The comparison is the XOR of the two coverage masks: the pixels where putting
the change on the model actually changes what a player sees. An intersection
over union of 1.0 means the change is invisible at this size even though the
geometry differs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from golem_blender.ops._contract import op

# The height a character occupies in the game's own frame: a 1.8 m character
# against the game's orthographic camera fills 55 px of a 1080-tall view (the
# user's own report, 2026-10-27). A silhouette test is a question about THIS
# number, so it is the default rather than a constant the caller has to know.
DEFAULT_SUBJECT_HEIGHT_PX = 55

# Frame padding around the subject, in pixels. Two is enough that a silhouette
# touching its own bounding box is not clipped by the frame's edge.
SILHOUETTE_MARGIN_PX = 2

# Surfaces one ray reports, front to back. Two objects plus a back face of
# each is four; 16 leaves room for a folded garment without paying for a walk
# to the far side of the scene.
SILHOUETTE_MAXIMUM_HITS = 16

# How far behind the subject the ray origins sit: a multiple of the pair's
# world bounding-box diagonal, so a tall pair does not put the eye inside it.
SILHOUETTE_BACK_OFF_FACTOR = 2.0


@dataclass(frozen=True)
class SilhouetteView:
    """One camera direction's coverage of both objects, in pixels."""

    yaw_deg: float
    pitch_deg: float
    width_px: int
    height_px: int
    metres_per_px: float
    object_pixel_count: int
    against_pixel_count: int
    # XOR: pixels one object covers and the other does not.
    changed_pixel_count: int
    # |AND| / |OR|, or 1.0 when both masks are empty (two objects that both
    # cover nothing are the same, invisible picture).
    iou: float
    # (left, top, right, bottom) of the changed pixels, or None when nothing
    # changed. The window a viewer's eye would have to be on.
    changed_box_px: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class SilhouetteReport:
    """Whether one object reads differently from another at the game's own pixel height."""

    subject_object_name: str
    against_object_name: str
    height_px: int
    cull_backfaces: bool
    views: tuple[SilhouetteView, ...]
    changes_silhouette: bool
    maximum_changed_pixel_count: int
    minimum_iou: float


@op(reads_only=True)
def silhouette_test(
    object_name: str,
    against_object_name: str,
    height_px: int = DEFAULT_SUBJECT_HEIGHT_PX,
    yaws_deg: tuple[float, ...] = (),
    pitch_deg: float = -1.0,
    cull_backfaces: bool = True,
) -> SilhouetteReport:
    """Compare two objects' silhouettes at `height_px` tall, and say where they differ.

    `against_object_name` is the object to compare with — normally a copy of
    `object_name` made BEFORE the change, so the report answers "would a player
    see this change at the size the game draws it". Both are framed by one
    shared camera per direction, sized from the pair's joint bounds.

    Coverage is one ray per pixel CENTRE with no anti-aliasing, so a change
    smaller than a pixel counts only where it crosses a pixel centre: the
    changed count is a lower bound on what an anti-aliased frame would show.

    `yaws_deg` empty means the game's own eight compass directions at
    `analyze.view_geometry.ISO_PITCH_DEG`; `pitch_deg` below zero means the
    same. `cull_backfaces` decides coverage the way a GPU does, by each
    triangle's own winding.
    """
    from golem_blender.analyze import occluders, view_geometry
    from golem_blender.ops._objects import object_by_name
    from golem_blender.ops.transforms import _world_bounds_m

    subject = object_by_name(object_name, "MESH")
    against = object_by_name(against_object_name, "MESH")
    if height_px < 1:
        raise ValueError(f"height_px must be at least 1, got {height_px}")
    yaws = tuple(yaws_deg) if yaws_deg else view_geometry.ISO_YAWS_DEG
    pitch = view_geometry.ISO_PITCH_DEG if pitch_deg < 0.0 else pitch_deg

    objects = [subject, against]
    minimum, maximum = _world_bounds_m(objects)
    diagonal_m = math.dist(minimum, maximum)
    if diagonal_m <= 0.0:
        raise ValueError(
            f"{object_name!r} and {against_object_name!r} have no extent "
            f"between them, so there is no silhouette to compare"
        )
    back_off_m = diagonal_m * SILHOUETTE_BACK_OFF_FACTOR
    corner_points = [
        (
            minimum[0] if index & 1 == 0 else maximum[0],
            minimum[1] if index & 2 == 0 else maximum[1],
            minimum[2] if index & 4 == 0 else maximum[2],
        )
        for index in range(8)
    ]
    indices = {
        subject.name: occluders.OccluderIndex([subject]),
        against.name: occluders.OccluderIndex([against]),
    }

    views: list[SilhouetteView] = []
    for yaw in yaws:
        camera = view_geometry.fit_ortho_camera_to_height(
            corner_points,
            yaw_deg=yaw,
            pitch_deg=pitch,
            subject_height_px=height_px,
            margin_px=SILHOUETTE_MARGIN_PX,
        )
        subject_mask = _coverage_mask(
            camera, indices[subject.name], back_off_m, cull_backfaces
        )
        against_mask = _coverage_mask(
            camera, indices[against.name], back_off_m, cull_backfaces
        )
        views.append(
            _view_row(
                camera,
                subject_mask,
                against_mask,
                yaw_deg=yaw,
                pitch_deg=pitch,
                cull_backfaces=cull_backfaces,
            )
        )

    return SilhouetteReport(
        subject_object_name=subject.name,
        against_object_name=against.name,
        height_px=height_px,
        cull_backfaces=cull_backfaces,
        views=tuple(views),
        changes_silhouette=any(view.changed_pixel_count > 0 for view in views),
        maximum_changed_pixel_count=max(view.changed_pixel_count for view in views),
        minimum_iou=min(view.iou for view in views),
    )


def _coverage_mask(
    camera, index, back_off_m: float, cull_backfaces: bool
) -> list[bool]:
    """One ray per pixel centre: does the object cover it, as the GPU draws it?"""
    from golem_blender.analyze import view_geometry

    mask: list[bool] = []
    for row in range(camera.height_px):
        for column in range(camera.width_px):
            origin, direction = view_geometry.ortho_pixel_ray(
                camera, column, row, back_off_m
            )
            hits = index.cast(origin, direction, SILHOUETTE_MAXIMUM_HITS)
            if cull_backfaces:
                mask.append(any(not hit.backface for hit in hits))
            else:
                mask.append(bool(hits))
    return mask


def _view_row(
    camera, subject_mask, against_mask, *, yaw_deg, pitch_deg, cull_backfaces
):
    both = sum(
        1
        for left, right in zip(subject_mask, against_mask, strict=True)
        if left and right
    )
    either = sum(
        1
        for left, right in zip(subject_mask, against_mask, strict=True)
        if left or right
    )
    changed = sum(
        1
        for left, right in zip(subject_mask, against_mask, strict=True)
        if left != right
    )
    return SilhouetteView(
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        width_px=camera.width_px,
        height_px=camera.height_px,
        metres_per_px=camera.frame_width_m / camera.width_px,
        object_pixel_count=sum(subject_mask),
        against_pixel_count=sum(against_mask),
        changed_pixel_count=changed,
        iou=(both / either) if either else 1.0,
        changed_box_px=_changed_box(
            subject_mask, against_mask, camera.width_px, camera.height_px
        )
        if changed
        else None,
    )


def _changed_box(subject_mask, against_mask, width_px: int, height_px: int):
    """(left, top, right, bottom) of the differing pixels, inclusive."""
    left, top, right, bottom = width_px, height_px, -1, -1
    for index, (left_covers, right_covers) in enumerate(
        zip(subject_mask, against_mask, strict=True)
    ):
        if left_covers == right_covers:
            continue
        row, column = divmod(index, width_px)
        left = min(left, column)
        right = max(right, column)
        top = min(top, row)
        bottom = max(bottom, row)
    if right < 0:
        return None
    return (left, top, right, bottom)
