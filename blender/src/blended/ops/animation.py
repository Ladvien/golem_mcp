"""Keyframing and frame-range operations through the data API.

Why this op exists: the chat agent needs to animate assets (door
swings, lid lifts) but raw ``bpy.ops.anim.keyframe_insert`` depends on
context overrides that drift across Blender versions.  The data API
``obj.keyframe_insert(data_path, frame=)`` is context-free and
headless-safe, so that is the only path exposed.

Blender 5.2 action model (measured 2026-09-04 on Blender 5.2.0 LTS,
hash fbe6228777e7): ``action.fcurves`` **does not exist** — accessing it
raises ``AttributeError``.  Actions are *slotted*: fcurves live on a
``ActionChannelbag`` obtained via ``action.layers[0].strips[0].
channelbag(slot)`` where ``slot = obj.animation_data.action_slot``.
``keyframe_insert`` creates the layer, strip, channelbag, and slot
automatically on first call, so we only need to *read* the fcurves back
through the slotted path.
"""

from __future__ import annotations

from dataclasses import dataclass

from blended.ops._contract import op

# Conversion: Blender stores rotation_euler in radians; the caller
# thinks in degrees.  One named constant, no implicit conversion.
_RAD_PER_DEG = 0.017453292519943295


@dataclass(frozen=True)
class AnimationReport:
    """Snapshot of an object's animation state for E2E assertion."""

    action_name: str
    fcurve_count: int
    keyframe_count: int
    frame_start: int
    frame_end: int
    animated_data_paths: tuple[str, ...]
    # A muted fcurve keeps its keyframes and drives nothing, so
    # `keyframe_count` alone reports a working animation for a channel
    # that is switched off — the animation lane's version of the gate's
    # `hide_render` hole.
    muted_fcurve_count: int = 0
    # Keys outside [frame_start, frame_end] never play. An action keyed
    # at 100-200 under a 1-48 scene range reports "2 keyframes, range
    # set" and shows a motionless object for the whole playback.
    keyframes_outside_frame_range_count: int = 0


def set_frame_range(start_frame: int, end_frame: int) -> tuple[int, int]:
    """Set the active scene's ``frame_start`` and ``frame_end``.

    Validates ``start_frame < end_frame`` — an inverted or degenerate
    range silently breaks every playback and export downstream, so it
    is rejected loudly rather than clamped.
    """
    import bpy

    if start_frame >= end_frame:
        raise ValueError(
            f"start_frame ({start_frame}) must be strictly less than "
            f"end_frame ({end_frame})"
        )
    scene = bpy.context.scene
    scene.frame_start = start_frame
    scene.frame_end = end_frame
    return (start_frame, end_frame)


def keyframe_object_transform(
    object_name: str,
    frame: int,
    location_m: tuple[float, float, float] | None = None,
    rotation_euler_deg: tuple[float, float, float] | None = None,
    scale: tuple[float, float, float] | None = None,
) -> int:
    """Set the named object's transform channels and insert keyframes at ``frame``.

    Only the channels whose argument is non-None are written and
    keyframed — an agent that wants to animate location only does not
    accidentally bake the current rotation/scale.

    Returns the number of fcurves on the object's action after
    insertion (read via the slotted API — see module docstring).
    """
    from blended.ops._objects import object_by_name

    obj = object_by_name(object_name)
    if location_m is not None:
        obj.location = location_m
        obj.keyframe_insert("location", frame=frame)

    if rotation_euler_deg is not None:
        obj.rotation_euler = tuple(d * _RAD_PER_DEG for d in rotation_euler_deg)
        obj.keyframe_insert("rotation_euler", frame=frame)

    if scale is not None:
        obj.scale = scale
        obj.keyframe_insert("scale", frame=frame)

    return _fcurve_count(obj)


def keyframe_pose_bone_rotation(
    armature_name: str,
    bone_name: str,
    frame: int,
    rotation_euler_deg: tuple[float, float, float],
) -> int:
    """Set a pose bone's Euler rotation on the named armature and keyframe it at ``frame``.

    Forces ``rotation_mode='XYZ'`` because a bone defaults to
    ``QUATERNION`` and keyframing ``rotation_euler`` on a quaternion
    bone silently writes to a channel Blender ignores at playback.

    Returns the fcurve count on the armature's action after insertion.
    """
    from blended.ops._objects import object_by_name

    armature_object = object_by_name(armature_name, "ARMATURE")
    pose_bone = armature_object.pose.bones[bone_name]
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = tuple(d * _RAD_PER_DEG for d in rotation_euler_deg)
    pose_bone.keyframe_insert("rotation_euler", frame=frame)

    return _fcurve_count(armature_object)


@op(reads_only=True)
def animation_report(object_name: str) -> AnimationReport:
    """Summarise the named object's animation against the active scene's frame range.

    A never-animated object (no ``animation_data`` or no action)
    reports an empty action name and all-zero counts.
    """
    import bpy

    from blended.ops._objects import object_by_name

    obj = object_by_name(object_name)
    scene = bpy.context.scene
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return AnimationReport(
            action_name="",
            fcurve_count=0,
            keyframe_count=0,
            frame_start=scene.frame_start,
            frame_end=scene.frame_end,
            animated_data_paths=(),
        )

    fcurves = _action_fcurves(obj)
    fcurve_count = len(fcurves)
    keyframe_count = sum(len(fc.keyframe_points) for fc in fcurves)
    muted_fcurve_count = sum(1 for fc in fcurves if fc.mute)
    outside_count = sum(
        1
        for fc in fcurves
        for keyframe in fc.keyframe_points
        if not (scene.frame_start <= keyframe.co.x <= scene.frame_end)
    )
    # Deduplicate while preserving order: one data_path may have 3
    # array-index fcurves (x/y/z) but appears once in the report.
    seen: list[str] = []
    for fc in fcurves:
        if fc.data_path not in seen:
            seen.append(fc.data_path)

    return AnimationReport(
        action_name=ad.action.name,
        fcurve_count=fcurve_count,
        keyframe_count=keyframe_count,
        frame_start=scene.frame_start,
        frame_end=scene.frame_end,
        animated_data_paths=tuple(seen),
        muted_fcurve_count=muted_fcurve_count,
        keyframes_outside_frame_range_count=outside_count,
    )


# -- internals -----------------------------------------------------------


def _action_channelbag(obj):
    """Return the channelbag of ``obj``'s action slot, or None when it has none.

    Measured in Blender 5.2.0 LTS: ``action.fcurves`` raises
    ``AttributeError``.  The working path is
    ``action.layers[0].strips[0].channelbag(slot)`` where
    ``slot`` is ``obj.animation_data.action_slot``.
    """
    ad = obj.animation_data
    if ad is None or ad.action is None:
        return None
    action = ad.action
    slot = ad.action_slot
    # An action assigned without any keyframe (or with no slot bound) has
    # no layer/strip/channelbag: that is no channelbag, not an IndexError.
    # keyframe_insert creates one layer and one strip, so [0] is the
    # whole structure once anything has been keyed.
    if slot is None or not action.layers or not action.layers[0].strips:
        return None
    return action.layers[0].strips[0].channelbag(slot)


def _action_fcurves(obj):
    """Return the fcurves list for ``obj``'s action via the slotted API."""
    channelbag = _action_channelbag(obj)
    if channelbag is None:
        return []
    return list(channelbag.fcurves)


def _fcurve_count(obj) -> int:
    """Count fcurves on ``obj``'s action via the slotted API."""
    return len(_action_fcurves(obj))
