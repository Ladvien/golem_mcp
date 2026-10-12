"""The sample gate on skinclip's tube humanoid: a hand through the torso is scored, repaired, and the original kept."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from skinclip import gltf
from skinclip.intersect import CheckSettings
from skinclip.testing import tube_humanoid

from golem_mcp.motion_gate import assess_sample


@pytest.mark.parametrize("names", ["ue5", "mixamo"])
def test_a_hand_through_the_torso_is_scored_then_repaired(tmp_path: Path, names: str) -> None:
    glb = tmp_path / "walk.glb"
    tube_humanoid(glb, names, "hand_through_torso")  # type: ignore[arg-type]
    before = glb.read_bytes()

    scored = assess_sample(glb, CheckSettings(), "score")
    assert scored["passed"] is False and scored["repaired"] is False and scored["contour_cm"] > 40.0
    assert glb.read_bytes() == before and not (tmp_path / "walk_unrepaired.glb").exists()

    repaired = assess_sample(glb, CheckSettings(), "repair")
    assert repaired["passed"] is True and repaired["repaired"] is True
    assert repaired["contour_cm_before"] == scored["contour_cm"] and repaired["contour_cm"] == 0.0
    assert (tmp_path / "walk_unrepaired.glb").read_bytes() == before  # the original is kept as it was
    assert glb.read_bytes() != before


def test_a_clean_sample_is_left_alone(tmp_path: Path) -> None:
    glb = tmp_path / "rest.glb"
    tube_humanoid(glb, "ue5", "rest")
    before = glb.read_bytes()
    verdict = assess_sample(glb, CheckSettings(), "repair")
    assert verdict["passed"] is True and verdict["repaired"] is False
    assert glb.read_bytes() == before and not (tmp_path / "rest_unrepaired.glb").exists()


def test_a_joint_the_exporter_keyed_with_two_keys_does_not_stop_the_gate(tmp_path: Path) -> None:
    """Blender's glTF export gives a joint that never moves (the retargeted `root`) two keys, not one per frame."""
    plain = tmp_path / "plain.glb"
    tube_humanoid(plain, "ue5", "hand_through_torso")
    document, blob = gltf.read_glb(plain)
    binary = bytearray(blob)

    def add(array: np.ndarray, kind: str) -> int:
        binary.extend(b"\0" * (-len(binary) % 4))
        document["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": array.nbytes})
        binary.extend(array.tobytes())
        document["accessors"].append(
            {"bufferView": len(document["bufferViews"]) - 1, "componentType": 5126, "count": len(array), "type": kind}
        )
        return len(document["accessors"]) - 1

    animation = document["animations"][0]
    times = add(np.array([0.0, 2.0], "<f4"), "SCALAR")
    still = add(np.tile(np.array([0.0, 0.0, 0.0, 1.0], "<f4"), (2, 1)), "VEC4")
    animation["samplers"].append({"input": times, "output": still, "interpolation": "LINEAR"})
    animation["channels"].append({"sampler": len(animation["samplers"]) - 1, "target": {"node": 0, "path": "rotation"}})
    document["buffers"][0]["byteLength"] = len(binary)
    keyed = tmp_path / "keyed.glb"
    gltf.write_glb(document, bytes(binary), keyed)

    repaired = assess_sample(keyed, CheckSettings(), "repair")
    assert repaired["passed"] is True and repaired["repaired"] is True
