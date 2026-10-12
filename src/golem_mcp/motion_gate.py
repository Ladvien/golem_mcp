"""Does a retargeted sample pass its own surface through itself? And if it does, can the limbs be turned off the body?

This module imports numpy and skinclip and never torch, so it runs in the server process or in a small worker process
(`ProcessPoolExecutor`) without loading the 16 GB text encoder. The algorithms are skinclip's
(`github.com/Ladvien/skinclip`): the checker poses the sample's own skinned mesh with its own animation, frame by
frame, and measures the length of the contour where its triangles cross (Grigorev et al., *ContourCraft*, SIGGRAPH
2024, doi:10.1145/3641519.3657408); the repair turns the arms and legs off the trunk and off each other by the smallest
rotation that clears their capsules.
"""

from __future__ import annotations

import os

# One BLAS thread per process, set before numpy loads: the assessments run one process per sample.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

from pathlib import Path  # noqa: E402
from typing import Any, Literal  # noqa: E402

import numpy as np  # noqa: E402
from skinclip import capsules, gltf, humanoid, pose, repair  # noqa: E402
from skinclip.intersect import CheckSettings, ClipCheck, check_clip  # noqa: E402
from skinclip.model import Figure, read_figure  # noqa: E402

FPS = 30.0
Mode = Literal["score", "repair"]


def _verdict(check: ClipCheck) -> dict[str, Any]:
    pair = check.worst_parts[0] if check.worst_parts else None
    return {
        "passed": check.failing == 0,
        "frames": check.frames,
        "failing_frames": check.failing,
        "worst_frame": check.worst_frame,
        "contour_cm": round(check.worst_contour_m * 100.0, 2),
        "worst_pair": f"{pair[0]} x {pair[1]}" if pair else "",
    }


def _only_animation(figure: Figure) -> tuple[str, Any]:
    if len(figure.clips) != 1:
        raise ValueError(f"expected one animation in the glb, found {len(figure.clips)}: {sorted(figure.clips)}")
    name, clip = next(iter(figure.clips.items()))
    return name, clip


def _sampled(figure: Figure, clip: Any, roles: dict[str, str]) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """The rotation keys of every joint that has any and the pelvis's translation keys, a row per frame at 30 fps.
    Kimodo's retarget keys every frame, so the keys are read as they are; a clip keyed at another rate is refused."""
    pelvis = roles["pelvis"]
    times = clip.channels[pelvis]["rotation"][0]
    if len(times) < 2 or not np.allclose(np.diff(times), 1.0 / FPS, atol=1e-3):
        raise ValueError(f"the clip is not keyed at {FPS:.0f} fps on every frame")
    rotations = {}
    for joint, paths in clip.channels.items():
        if "rotation" not in paths:
            continue
        # A joint that does not move is keyed with two keys by the exporter (the retargeted `root` is): sampling at the
        # pelvis's times gives it a row per frame all the same.
        rotations[joint] = pose.sample(paths["rotation"], times, "rotation")
    index = figure.skeleton.index(pelvis)
    if "translation" in clip.channels[pelvis]:
        translation = pose.sample(clip.channels[pelvis]["translation"], times, "translation")
    else:
        translation = np.tile(figure.skeleton.rest_t[index], (len(times), 1))
    return rotations, translation


def assess_sample(glb: Path, settings: CheckSettings, mode: Mode) -> dict[str, Any]:
    """Checks a retargeted sample against itself and, in `repair` mode, repairs it when it crosses.

    A failing sample is repaired once: the original is kept beside it as `<stem>_unrepaired.glb` and the repaired keys
    are written into `<stem>.glb`, which is then checked again. Returns the verdict (`passed`, `frames`,
    `failing_frames`, `worst_frame`, `contour_cm`, `worst_pair`), whether it was `repaired` and, when it was,
    `contour_cm_before`. A sample whose rig is not a humanoid skinclip knows is left alone with `repair_skipped`."""
    figure = read_figure("character", glb, settings)
    name, clip = _only_animation(figure)
    check = check_clip(figure, name, [clip], settings)
    verdict = {**_verdict(check), "repaired": False, "contour_cm_before": None}
    if check.failing == 0 or mode != "repair":
        return verdict
    try:
        roles = humanoid.detect(figure.skeleton.names)
    except ValueError as error:
        return {**verdict, "repair_skipped": str(error)}
    rotations, translation = _sampled(figure, clip, roles)
    fixed, report = repair.repair(figure, roles, capsules.measure(figure, roles), rotations, translation, loop=False)
    if not report.joints_changed:
        return {**verdict, "repair_skipped": "no capsule penetration to turn away"}
    keys = {joint: np.asarray(fixed[joint], "<f4") for joint in report.joints_changed}
    unrepaired = glb.with_name(f"{glb.stem}_unrepaired.glb")
    glb.rename(unrepaired)
    gltf.write_rotations(unrepaired, glb, 0, keys)  # the clip is the glb's only animation (checked above)
    repaired = read_figure("character", glb, settings)
    again = check_clip(repaired, name, [repaired.clips[name]], settings)
    return {**_verdict(again), "repaired": True, "contour_cm_before": verdict["contour_cm"]}
