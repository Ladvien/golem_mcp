"""Transform operations through the data API (no bpy.ops, no context).

Every op here reads `matrix_world`, which Blender evaluates LAZILY:
setting `.location` or `.rotation_euler` does NOT update it until the
dependency graph runs. Reading it before then returns the STALE matrix
(identity on a fresh object) and the transform silently does nothing —
no error, no warning. Measured: an agent set rotation and location,
called apply_object_transform, and its vertices were untouched, so
three splayed stool legs collapsed into a single central post.

So every function here refreshes the depsgraph first. See the drift
catalog.
"""

from __future__ import annotations

import math

from golem_blender.ops._contract import op
from golem_blender.ops._objects import ObjectName


def _refresh_dependency_graph() -> None:
    """Force matrix_world to reflect pending location/rotation changes."""
    import bpy

    bpy.context.view_layer.update()


AXIS_COUNT = 3


def _world_bounds_m(blender_objects) -> tuple[list[float], list[float]]:
    """(minimum, maximum) per world axis of the objects' JOINT bounding box.

    THE one place world extents are measured (OT-34). `object.dimensions`
    is the local bounding box scaled — it ignores rotation, so a
    0.9 x 0.3 x 0.6 m box turned a quarter turn about X still reports
    (0.9, 0.3, 0.6) while occupying (0.9, 0.6, 0.3) of world space. Every
    reader that asks "which world axis holds which extent" — the gate's
    `orient:` line, `inspect_object`, `list_scene`, `world_bounds` and
    `apply_canonical_depth_axis` — reads this, so the reading the writer
    sees and the rotation the op applies come from the same numbers.

    Joint, not per-object, because the exporter writes the whole scene
    into one GLB and the scorer samples that one cloud; a single-object
    caller passes a one-element list. The depsgraph is refreshed first
    (OPS-14) so the box is this frame's, not the previous one's.
    """
    import bpy
    from mathutils import Vector

    bpy.context.view_layer.update()
    minimum = [math.inf] * AXIS_COUNT
    maximum = [-math.inf] * AXIS_COUNT
    for blender_object in blender_objects:
        for corner in blender_object.bound_box:
            world_corner = blender_object.matrix_world @ Vector(corner)
            for axis in range(AXIS_COUNT):
                minimum[axis] = min(minimum[axis], world_corner[axis])
                maximum[axis] = max(maximum[axis], world_corner[axis])
    return minimum, maximum


def _world_extents_m(blender_objects) -> tuple[float, float, float]:
    """Axis-aligned world extents of the objects' joint bounding box."""
    minimum, maximum = _world_bounds_m(blender_objects)
    extent_x_m, extent_y_m, extent_z_m = (
        maximum[axis] - minimum[axis] for axis in range(AXIS_COUNT)
    )
    return (extent_x_m, extent_y_m, extent_z_m)


@op(reads_only=True)
def world_bounds(object_name: str) -> dict[str, list[float]]:
    """Read the named object's world-space bounding box: min_m, max_m, extents_m corners of its evaluated bounds.

    Measured demand (OT-12): five escape-hatch chunks in the v12 runs
    existed only to print world extents of a target and a cutter when a
    boolean reported no overlap. The depsgraph is refreshed first
    (OPS-14) so the box is this frame's, not the previous one's.
    """
    from golem_blender.ops._objects import object_by_name

    minimum, maximum = _world_bounds_m([object_by_name(object_name)])
    return {
        "min_m": minimum,
        "max_m": maximum,
        "extents_m": [maximum[axis] - minimum[axis] for axis in range(AXIS_COUNT)],
    }


def apply_object_transform(object_name: str) -> ObjectName:
    """Bake the named object's matrix into its mesh and reset it to identity.

    Do this before export or measurement whenever the object transform
    is not identity — analyzers and exporters that read mesh-local
    coordinates otherwise measure something the viewport does not show.
    """
    from mathutils import Matrix

    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name, "MESH")
    _refresh_dependency_graph()
    blender_object.data.transform(blender_object.matrix_world)
    blender_object.matrix_world = Matrix.Identity(4)
    return ObjectName(object_name)


def rotate_object_euler(
    object_name: str,
    x_rad: float = 0.0,
    y_rad: float = 0.0,
    z_rad: float = 0.0,
    order: str = "XYZ",
) -> ObjectName:
    """Set the named object's Euler rotation, in radians, about its own origin.

    Exists because the whitelisted vocabulary had no way to rotate
    anything — measured 2026-08-22: an agent asked for a stool with
    splayed legs spent three search_ops calls and a dir() probe before
    concluding "There's no rotate op", then improvised with raw
    attribute writes. Rotation is not an exotic operation; a facade that
    omits it is not a facade.

    The rotation is SET, not accumulated, so re-running a chunk is
    idempotent. The depsgraph is refreshed afterwards so the very next
    read of matrix_world is truthful — the trap that once collapsed
    three splayed legs into a central post.
    """
    from mathutils import Euler

    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    # The Euler is built FIRST: an `order` it rejects (e.g. "AXIS_ANGLE",
    # a valid rotation_mode but not an Euler order) must raise before the
    # object's rotation_mode has been changed.
    rotation = Euler((x_rad, y_rad, z_rad), order)
    blender_object.rotation_mode = order
    blender_object.rotation_euler = rotation
    _refresh_dependency_graph()
    return ObjectName(object_name)


def move_object_to(
    object_name: str, location_m: tuple[float, float, float]
) -> ObjectName:
    """Set the named object's world location in metres, then refresh.

    Same reason as rotate_object_euler: placement is half of assembly,
    and it shares the stale-matrix_world trap.
    """
    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    if blender_object.parent is None:
        blender_object.location = location_m
    else:
        # `location` is parent-relative; the op promises a WORLD location
        # (measured: a child of an empty at z=5 moved to (0,0,0) stayed
        # at world z=5). Only the translation of the world matrix changes.
        _refresh_dependency_graph()
        world_matrix = blender_object.matrix_world.copy()
        world_matrix.translation = location_m
        blender_object.matrix_world = world_matrix
    _refresh_dependency_graph()
    return ObjectName(object_name)


def snap_base_to_ground(
    object_name: str | None = None, *, piece: str | None = None
) -> float:
    """Move the named object, or a PIECE, so the lowest point sits at z=0; returns the offset in m.

    A piece moves as one: every member takes the SAME z offset, so the
    piece keeps its shape and the set's lowest point lands at 0 (moving
    one part would put the piece's lowest point somewhere else). The
    measurement reads the parts' joint world bounds, so it is the set's
    lowest point that is grounded, not one member's.

    Give `object_name` or `piece`, never both: two targets in one call
    have no single offset to report.
    """
    from mathutils import Vector

    from golem_blender.ops._objects import object_by_name

    if object_name is not None and piece is not None:
        raise ValueError(
            f"give object_name or piece, not both: got object_name="
            f"{object_name!r} and piece={piece!r}"
        )
    if object_name is None and piece is None:
        raise ValueError(
            "give exactly one of object_name or piece; got neither, so there "
            "is nothing to ground"
        )

    if piece is not None:
        from golem_blender.ops.pieces import _piece_all_objects, _piece_mesh_objects

        # The SAME members the report measures (decision 4 of ops.pieces):
        # a non-mesh member has no geometry to ground, so including its box
        # would put the piece's lowest point where the report does not
        # read it.
        mesh_objects = _piece_mesh_objects(piece)
        if not mesh_objects:
            raise ValueError(
                f"piece {piece!r} has no mesh members, so it has no lowest "
                f"point to ground"
            )
        _refresh_dependency_graph()
        lowest_z_m = min(
            (blender_object.matrix_world @ Vector(corner)).z
            for blender_object in mesh_objects
            for corner in blender_object.bound_box
        )
        offset_z_m = -lowest_z_m
        # EVERY member moves, meshes and the armature/empties beside them,
        # by the same offset: grounding half a rigged piece would tear it
        # apart.
        for blender_object in _piece_all_objects(piece):
            blender_object.location.z += offset_z_m
        _refresh_dependency_graph()
        return offset_z_m

    blender_object = object_by_name(object_name)
    _refresh_dependency_graph()
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    lowest_z_m = min(corner.z for corner in world_corners)
    offset_z_m = -lowest_z_m
    blender_object.location.z += offset_z_m
    _refresh_dependency_graph()
    return offset_z_m


def center_on_origin_xy(object_name: str) -> ObjectName:
    """Center the named object's world-space bounds on the X/Y origin."""
    from mathutils import Vector

    from golem_blender.ops._objects import object_by_name

    blender_object = object_by_name(object_name)
    _refresh_dependency_graph()
    world_corners = [
        blender_object.matrix_world @ Vector(corner)
        for corner in blender_object.bound_box
    ]
    bounds_center = sum(world_corners, Vector()) / len(world_corners)
    blender_object.location.x -= bounds_center.x
    blender_object.location.y -= bounds_center.y
    _refresh_dependency_graph()
    return ObjectName(object_name)
