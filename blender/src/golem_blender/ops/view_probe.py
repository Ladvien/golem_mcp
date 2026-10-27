"""What a camera pixel hits, and what lies behind it — the question a render answers slowly.

The measured need, from an abbey user: "I render it, look at it, and still cannot
say WHICH object that pixel is." A render is a picture; a probe is the answer.
So this op casts the same rays a camera with the same frustum would cast, and
reports for each one the object, material, face, world normal, distance and
whether it was hit from behind — then the surfaces behind it, front to back.
That "what lies behind" half is what makes a SLOT legible: a pixel through a
2 cm gap reports the wall behind the gap, not the wall it missed.

Two camera sources, one geometry:

- a YAW/PITCH ORTHOGRAPHIC camera (`analyze/view_geometry.OrthoCamera`), whose
  angles are the game's own and whose pixel-to-ray mapping has an exact inverse;
- a real CAMERA object in the scene, read through `view_frame` so its lens,
  sensor shift, resolution percentage and ORTHO/PERSP mode are whatever the user
  set rather than a guess.

The op creates NOTHING: no camera, no light, no object. So there is nothing to
restore and no flag to forget — a probe can never move the user's viewport,
which is why there is no `restore_view`.

MAIN THREAD ONLY: everything below touches bpy.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from golem_blender.analyze.occluders import OccluderIndex, RayHit
from golem_blender.analyze.view_geometry import (
    ISO_PITCH_DEG,
    OrthoCamera,
    ortho_pixel_ray,
    ortho_project,
)
from golem_blender.ops._contract import op
from golem_blender.ops._objects import UnknownObject
from golem_blender.ops._targets import resolve_mesh_targets

# A probe is a QUESTION about named pixels, not a picture: more than this many
# is a loop that should have asked for a region or an id map.
MAXIMUM_LISTED_RAYS = 64
# A point counts as visible when the first hit lands within this of it. Two
# millimetres is finer than any modelling tolerance in this repo and far coarser
# than float error, so a point exactly on a surface reads visible and a point
# behind a wall does not.
POINT_VISIBLE_TOLERANCE_M = 0.002
# The default frame is the joint bounds' diagonal times this, so a probe of an
# unknown target still shows the whole of it with room around it.
FRAME_MARGIN_FACTOR = 1.2
# Backing the eye off by twice the diagonal plus a metre guarantees the near
# side of the target is in front of the eye whatever the target's shape.
BACK_OFF_DIAGONAL_FACTOR = 2.0
BACK_OFF_EXTRA_M = 1.0
# A hash of (object|material) is the id colour. Three bytes give 16.7M ids and
# no palette to maintain; pure black is kept for "nothing hit", so a pure-black
# hash is nudged to 0x010101 — invisible to the eye, unmissable to a reader.
ID_COLOUR_BYTES = 3
ID_COLOUR_RESERVED = b"\x00\x00\x00"
ID_COLOUR_FLOOR = b"\x01\x01\x01"
ID_PNG_DIRECTORY = "probe_view"
DEFAULT_YAW_DEG = 45.0


@dataclass(frozen=True)
class ProbeRay:
    """One cast ray: which pixel or point it was aimed at, and what it met."""

    pixel: tuple[int, int]
    point_m: tuple[float, float, float] | None  # set for a points_m ray
    visible: bool | None  # points_m only: the first hit is the point itself
    hits: tuple[RayHit, ...]


@dataclass(frozen=True)
class ViewShare:
    """How much of the probed set is that object's face."""

    object_name: str
    pixel_share: float


@dataclass(frozen=True)
class ViewProbe:
    """What the view sees: per-ray hits, the shares, and an optional id image."""

    camera: str
    width_px: int
    height_px: int
    frame_width_m: float
    rays: tuple[ProbeRay, ...]
    visible: tuple[
        ViewShare, ...
    ]  # share of the probed set whose first hit is that object
    probed_pixel_count: int
    id_png: str  # "" unless write_id_png
    legend: tuple[tuple[str, str, str], ...]  # (object, material, "#rrggbb")


def _camera_objects():
    """Every MESH object in the scene that is actually visible."""
    import bpy

    return [
        blender_object
        for blender_object in bpy.context.scene.objects
        if blender_object.type == "MESH" and blender_object.visible_get()
    ]


def _ortho_camera(arguments) -> OrthoCamera:
    """The analytic camera for a yaw/pitch probe, framed on the target's bounds."""
    from golem_blender.ops.transforms import _world_bounds_m

    _label, objects = resolve_mesh_targets(arguments["target"])
    minimum, maximum = _world_bounds_m(objects)
    centre = tuple((minimum[axis] + maximum[axis]) / 2.0 for axis in range(3))
    diagonal = sum((maximum[axis] - minimum[axis]) ** 2 for axis in range(3)) ** 0.5
    target_point = (
        arguments["target_point_m"]
        if arguments["target_point_m"] is not None
        else centre
    )
    frame_width = (
        arguments["frame_width_m"]
        if arguments["frame_width_m"] is not None
        else max(diagonal * FRAME_MARGIN_FACTOR, 1.0e-3)
    )
    if frame_width <= 0.0:
        raise ValueError(f"frame_width_m must be positive, got {frame_width!r}")
    back_off = BACK_OFF_DIAGONAL_FACTOR * diagonal + BACK_OFF_EXTRA_M
    camera = OrthoCamera(
        target_m=tuple(target_point),
        yaw_deg=arguments["yaw_deg"],
        pitch_deg=arguments["pitch_deg"],
        frame_width_m=frame_width,
        width_px=arguments["width_px"],
        height_px=arguments["height_px"],
    )
    label = (
        f"ortho yaw {arguments['yaw_deg']:g} pitch {arguments['pitch_deg']:g} "
        f"width {frame_width:.3f} m"
    )
    return camera, label, back_off


def _scene_camera(camera_object_name):
    """The named CAMERA object and its own view frame, in LOCAL space.

    `view_frame` is Blender's own frustum: it honours the lens, the sensor fit,
    the shift and ORTHO vs PERSP, so a probe through a camera the user placed
    agrees with the render that camera would make. Building the frustum by hand
    from lens and sensor constants is how a probe drifts from its render.

    The four corners come back in camera-local coordinates; their ORDER is not
    part of the documented contract, so the ray below takes their min/max rather
    than indexing them. Assuming an order is how a probe reads the frame
    transposed and misses the object it was aimed at.
    """
    import bpy

    blender_object = bpy.data.objects.get(camera_object_name)
    if blender_object is None:
        raise UnknownObject(
            f"no object named {camera_object_name!r} in bpy.data.objects "
            f"(present: {sorted(o.name for o in bpy.data.objects)})"
        )
    if blender_object.type != "CAMERA":
        raise UnknownObject(
            f"{camera_object_name!r} is a {blender_object.type}, not a CAMERA; "
            f"pass the name of a camera object or leave camera_object_name empty"
        )
    scene = bpy.context.scene
    percentage = scene.render.resolution_percentage / 100.0
    width_px = max(1, round(scene.render.resolution_x * percentage))
    height_px = max(1, round(scene.render.resolution_y * percentage))
    corners = list(blender_object.data.view_frame(scene=scene))
    frame = {
        "min_x": min(corner[0] for corner in corners),
        "max_x": max(corner[0] for corner in corners),
        "min_y": min(corner[1] for corner in corners),
        "max_y": max(corner[1] for corner in corners),
        "z": corners[0][2],
        "is_orthographic": blender_object.data.type == "ORTHO",
    }
    return blender_object, frame, width_px, height_px


def _scene_camera_ray(blender_object, frame, width_px, height_px, px, py):
    """(origin, direction) through a scene camera's pixel, in the camera's own space."""
    from mathutils import Vector

    # u runs left to right and v runs top to bottom, both at the pixel CENTRE.
    u = (px + 0.5) / width_px
    v = (py + 0.5) / height_px
    local_point = Vector(
        (
            frame["min_x"] + (frame["max_x"] - frame["min_x"]) * u,
            frame["max_y"] - (frame["max_y"] - frame["min_y"]) * v,
            frame["z"],
        )
    )
    world_point = blender_object.matrix_world @ local_point
    if frame["is_orthographic"]:
        # An ORTHO camera's rays are parallel: they start on the camera's own
        # plane (local z = 0), offset to this pixel, and travel along its -Z.
        origin = blender_object.matrix_world @ Vector(
            (local_point.x, local_point.y, 0.0)
        )
        direction = blender_object.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    else:
        origin = blender_object.matrix_world.translation.copy()
        direction = world_point - origin
    if direction.length == 0.0:
        raise ValueError(
            f"the camera {blender_object.name!r} has a degenerate frame: the ray "
            f"through pixel ({px}, {py}) has no direction"
        )
    direction.normalize()
    return tuple(origin), tuple(direction)


def _scene_camera_ray_through(blender_object, frame, point):
    """The camera's ray that passes exactly THROUGH `point`.

    A point is a question about that point, so its ray must pass through it. A
    pixel-quantised ray (`_scene_camera_ray`) answers about a neighbouring ray up
    to half a pixel away — measured at 3.6 mm on a 3.7 m orthographic frame,
    which is larger than the 2 mm visibility tolerance, so a point ON a surface
    would read "not visible" because the ray missed it.
    """
    from mathutils import Vector

    target = Vector(point)
    camera_location = blender_object.matrix_world.translation.copy()
    if frame["is_orthographic"]:
        forward = blender_object.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
        forward.normalize()
        origin = target - forward * (
            BACK_OFF_EXTRA_M + (target - camera_location).length
        )
        return tuple(origin), tuple(forward)
    direction = target - camera_location
    if direction.length == 0.0:
        raise ValueError(f"the camera {blender_object.name!r} is AT the probed point")
    direction.normalize()
    return tuple(camera_location), tuple(direction)


def _pixel_of_point(blender_object, width_px, height_px, point):
    """Which pixel a world point projects to, through a scene camera."""
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    coordinates = world_to_camera_view(bpy.context.scene, blender_object, Vector(point))
    return (coordinates.x * width_px, (1.0 - coordinates.y) * height_px)


def _id_colour(object_name: str, material_name: str) -> bytes:
    digest = hashlib.blake2b(
        f"{object_name}|{material_name}".encode(), digest_size=ID_COLOUR_BYTES
    ).digest()
    return ID_COLOUR_FLOOR if digest == ID_COLOUR_RESERVED else digest


def _hex_colour(colour: bytes) -> str:
    return "#{:02x}{:02x}{:02x}".format(*colour)


def _write_id_png(image_name, rows, width_px, height_px, destination: Path) -> str:
    """Write the id image bottom-up (Blender's pixel order) as a PNG."""
    import bpy

    image = bpy.data.images.new(image_name, width_px, height_px, alpha=False)
    try:
        pixels = [0.0] * (width_px * height_px * 4)
        # Blender stores row 0 at the BOTTOM; the rows here are top-down.
        for row_index, row in enumerate(reversed(rows)):
            base = row_index * width_px * 4
            for column, colour in enumerate(row):
                offset = base + column * 4
                pixels[offset] = colour[0] / 255.0
                pixels[offset + 1] = colour[1] / 255.0
                pixels[offset + 2] = colour[2] / 255.0
                pixels[offset + 3] = 1.0
        image.pixels = pixels
        image.filepath_raw = str(destination)
        image.file_format = "PNG"
        image.save()
    finally:
        bpy.data.images.remove(image)
    return str(destination)


def _validate_pixel_bounds(pixel, width_px, height_px, what):
    px, py = pixel
    if not (0 <= px < width_px and 0 <= py < height_px):
        raise ValueError(
            f"{what} ({px}, {py}) is outside the {width_px} x {height_px} frame; "
            f"pixels run 0..{width_px - 1} and 0..{height_px - 1}"
        )


@op(reads_only=True)
def probe_view(
    target: str | list[str] | None = None,
    camera_object_name: str | None = None,
    yaw_deg: float = DEFAULT_YAW_DEG,
    pitch_deg: float = ISO_PITCH_DEG,
    frame_width_m: float | None = None,
    target_point_m: tuple[float, float, float] | None = None,
    width_px: int = 512,
    height_px: int = 512,
    pixels: tuple[tuple[int, int], ...] = (),
    points_m: tuple[tuple[float, float, float], ...] = (),
    region_px: tuple[int, int, int, int] | None = None,
    hit_layers: int = 3,
    write_id_png: bool = False,
    output_dir: str | None = None,
) -> ViewProbe:
    """Cast camera rays at pixels or points: each hit's object, material, face, normal, distance and what lies behind.

    `pixels` asks about named pixels and `points_m` about world points; a
    point's ray passes EXACTLY through that point (not through the nearest pixel
    centre, which can be millimetres off), so `visible` says whether the point is
    the FIRST thing the camera meets — which is how a point behind a wall, or a
    point in a 2 cm slot, answers for itself. `hit_layers` is how many surfaces
    one cast reports, front to back, so the surface behind a slot is visible
    rather than reported as a miss. `region_px` (x0, y0, x1, y1) and
    `write_id_png` describe a SET of pixels: `visible` is the share of that set
    each object's face occupies, and the png writes the whole frame with one
    colour per (object, material), so a silhouette question is one call.

    `camera_object_name` probes through a real camera in the scene, read through
    its own `view_frame` — lens, sensor shift, ORTHO vs PERSP, resolution
    percentage and all — so the probe agrees with the render that camera would
    make. Without it the camera is analytic: an orthographic yaw/pitch orbit at
    the game's own angles, framed on the target's bounds (`frame_width_m`
    overrides the framing, `target_point_m` the aim). `target` names what the
    rays may hit: an object, a list, an assembly or a piece; empty means every
    visible MESH object in the scene.

    Nothing is created and no object, camera or light is touched, so the user's
    viewport is never moved and there is no state to restore. An id png is written
    under `output_dir`, or under the temp directory's `probe_view`.
    """
    import bpy

    if len(pixels) > MAXIMUM_LISTED_RAYS:
        raise ValueError(
            f"{len(pixels)} pixels listed; the maximum is {MAXIMUM_LISTED_RAYS}. "
            f"For a whole region use region_px or write_id_png."
        )
    if len(points_m) > MAXIMUM_LISTED_RAYS:
        raise ValueError(
            f"{len(points_m)} points listed; the maximum is {MAXIMUM_LISTED_RAYS}."
        )
    if hit_layers < 1:
        raise ValueError(f"hit_layers must be at least 1, got {hit_layers!r}")
    if width_px < 1 or height_px < 1:
        raise ValueError(
            f"the frame must be at least 1 x 1 px, got {width_px} x {height_px}"
        )
    if bpy.context.mode != "OBJECT":
        raise ValueError(
            f"probe_view needs OBJECT mode, got {bpy.context.mode!r}; leave Edit "
            f"mode first (object.mode_set(mode='OBJECT')) and call again"
        )

    if target is None:
        objects = _camera_objects()
        if not objects:
            raise UnknownObject(
                "the scene has no visible MESH objects to probe; pass target "
                "with an object, list, assembly or piece name"
            )
    else:
        objects = resolve_mesh_targets(target)[1]

    index = OccluderIndex(objects)

    if camera_object_name is None:
        camera, camera_label, back_off_m = _ortho_camera(
            {
                "target": target,
                "yaw_deg": yaw_deg,
                "pitch_deg": pitch_deg,
                "frame_width_m": frame_width_m,
                "target_point_m": target_point_m,
                "width_px": width_px,
                "height_px": height_px,
            }
        )
        width_px, height_px = camera.width_px, camera.height_px
        frame_width_m = camera.frame_width_m

        def ray_of(pixel):
            return ortho_pixel_ray(camera, pixel[0], pixel[1], back_off_m)

        def pixel_of(point):
            return ortho_project(camera, point)

        def ray_through(point):
            origin = tuple(
                point[axis] - camera.forward[axis] * back_off_m for axis in range(3)
            )
            return origin, camera.forward

    else:
        blender_object, frame, width_px, height_px = _scene_camera(camera_object_name)
        camera_label = camera_object_name
        frame_width_m = 0.0

        def ray_of(pixel):
            return _scene_camera_ray(
                blender_object, frame, width_px, height_px, pixel[0], pixel[1]
            )

        def pixel_of(point):
            return _pixel_of_point(blender_object, width_px, height_px, point)

        def ray_through(point):
            return _scene_camera_ray_through(blender_object, frame, point)

    for pixel in pixels:
        _validate_pixel_bounds(pixel, width_px, height_px, "pixel")
    region = region_px
    if region is not None:
        x0, y0, x1, y1 = region
        for corner in ((x0, y0), (x1, y1)):
            _validate_pixel_bounds(corner, width_px, height_px, "region corner")
        if x1 < x0 or y1 < y0:
            raise ValueError(f"region_px must run low corner first, got {region!r}")

    rays = []
    for pixel in pixels:
        origin, direction = ray_of(pixel)
        hits = index.cast(origin, direction, hit_layers)
        rays.append(
            ProbeRay(
                pixel=(pixel[0], pixel[1]),
                point_m=None,
                visible=None,
                hits=tuple(hits),
            )
        )
    for point in points_m:
        projected = pixel_of(tuple(point))
        origin, direction = ray_through(tuple(point))
        hits = index.cast(origin, direction, hit_layers)
        visible = False
        if hits:
            first = hits[0]
            offset = (
                sum((first.point_m[axis] - point[axis]) ** 2 for axis in range(3))
                ** 0.5
            )
            visible = offset <= POINT_VISIBLE_TOLERANCE_M
        rays.append(
            ProbeRay(
                pixel=(round(projected[0]), round(projected[1])),
                point_m=tuple(point),
                visible=visible,
                hits=tuple(hits),
            )
        )

    # Which pixels count toward `visible`'s shares: an explicit region wins,
    # then the whole frame when an id png is asked for, then the listed rays.
    counted_pixels: list[tuple[int, int]] = []
    if region is not None:
        x0, y0, x1, y1 = region
        counted_pixels = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    elif write_id_png:
        counted_pixels = [(x, y) for y in range(height_px) for x in range(width_px)]
    else:
        counted_pixels = [ray.pixel for ray in rays]

    shares: dict[str, int] = {}
    hit_count = 0
    for pixel in counted_pixels:
        origin, direction = ray_of(pixel)
        hits = index.cast(origin, direction, 1)
        if hits:
            shares[hits[0].object_name] = shares.get(hits[0].object_name, 0) + 1
            hit_count += 1
    visible_shares = tuple(
        ViewShare(
            object_name=name,
            pixel_share=(count / len(counted_pixels)) if counted_pixels else 0.0,
        )
        for name, count in sorted(shares.items(), key=lambda item: (-item[1], item[0]))
    )

    id_png = ""
    legend: tuple[tuple[str, str, str], ...] = ()
    if write_id_png:
        rows = []
        legend_entries: dict[tuple[str, str], bytes] = {}
        for y in range(height_px):
            row = []
            for x in range(width_px):
                origin, direction = ray_of((x, y))
                hits = index.cast(origin, direction, 1)
                if not hits:
                    row.append(ID_COLOUR_RESERVED)
                    continue
                key = (hits[0].object_name, hits[0].material_name)
                if key not in legend_entries:
                    legend_entries[key] = _id_colour(*key)
                row.append(legend_entries[key])
            rows.append(row)
        directory = (
            Path(output_dir)
            if output_dir is not None
            else Path(bpy.app.tempdir) / ID_PNG_DIRECTORY
        )
        directory.mkdir(parents=True, exist_ok=True)
        if camera_object_name is None:
            stem = f"probe_{yaw_deg:g}_{pitch_deg:g}"
        else:
            stem = f"probe_{camera_object_name}".replace(" ", "_")
        id_png = _write_id_png(
            "probe_view_id", rows, width_px, height_px, directory / f"{stem}.png"
        )
        legend = tuple(
            (object_name, material_name, _hex_colour(colour))
            for (object_name, material_name), colour in sorted(legend_entries.items())
        )

    return ViewProbe(
        camera=camera_label,
        width_px=width_px,
        height_px=height_px,
        frame_width_m=frame_width_m,
        rays=tuple(rays),
        visible=visible_shares,
        probed_pixel_count=len(counted_pixels),
        id_png=id_png,
        legend=legend,
    )
