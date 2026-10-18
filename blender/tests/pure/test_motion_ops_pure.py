"""OT-51: what the motion ops promise without Blender or numpy.

The numerics sit in skinclip, which imports numpy; golem_blender puts its venv
ahead of Blender's own site-packages, so a numpy wheel in the venv would
shadow Blender's. The facade, the MCP server and this layer therefore
must import the ops with numpy absent: skinclip is imported inside op
bodies only.
"""

import subprocess
import sys

import pytest
from skinclip.spec import RingSkirtSpec

import golem_blender.ops as ops_facade
from golem_blender.agent.op_call import call_op
from golem_blender.manifest import OP_CONFIG_DATACLASSES, OP_MODULE_NAMES
from golem_blender.ops._contract import changes_scene, is_gated, is_reads_only
from golem_blender.ops.motion import ArmatureRotationModeError, bake_cloth_chains

MOTION_READERS = ("body_capsules_report", "clip_self_intersection_report")
MOTION_WRITERS = ("bake_cloth_chains", "repair_limb_penetration")

BLOCKED_IMPORT_PROGRAM = """
import sys
sys.modules["numpy"] = None   # an import of numpy now raises ImportError
import golem_blender.ops, golem_blender.manifest
from golem_blender.manifest import build_manifest
build_manifest()
import golem_blender.ops.motion
import skinclip.spec
assert golem_blender.ops.RingSkirtSpec is skinclip.spec.RingSkirtSpec
print("IMPORTED", len(golem_blender.ops.__all__))
"""


def test_the_ops_import_with_numpy_unavailable():
    result = subprocess.run(
        [sys.executable, "-c", BLOCKED_IMPORT_PROGRAM],
        capture_output=True,
        text=True,
        check=False,
        env={"GOLEM_BLENDER_DISABLE_PLUGINS": "1", "PATH": ""},
    )

    assert result.returncode == 0, result.stderr
    assert "IMPORTED" in result.stdout


def test_the_readers_are_plan_free_and_the_writers_are_not():
    for name in MOTION_READERS:
        assert is_reads_only(getattr(ops_facade, name)), name
    for name in MOTION_WRITERS:
        function = getattr(ops_facade, name)
        assert changes_scene(function), name
        assert not is_gated(function), f"{name} returns a report, not an object name"


def test_the_module_is_in_the_manifest_and_its_config_object_is_documented():
    assert "motion" in OP_MODULE_NAMES
    assert ("golem_blender.ops.motion", "RingSkirtSpec") in OP_CONFIG_DATACLASSES


def test_the_rotation_mode_error_is_a_value_error_on_the_facade():
    assert ops_facade.ArmatureRotationModeError is ArmatureRotationModeError
    assert issubclass(ArmatureRotationModeError, ValueError)


GOOD_SPEC = {
    "top_height_m": 0.9,
    "knee_height_m": 0.55,
    "hem_height_m": 0.2,
    "blend_height_m": 1.0,
    "inset_m": 0.0,
}


def test_the_facade_exports_skinclips_own_ring_skirt_spec():
    """One class: the schema the model reads is built from skinclip's dataclass, not a copy."""
    assert ops_facade.RingSkirtSpec is RingSkirtSpec
    spec = RingSkirtSpec(**GOOD_SPEC)
    assert spec.count == 12
    assert spec.prefix == "skirt_"
    with pytest.raises(TypeError):
        RingSkirtSpec(12, 0.9, 0.55, 0.2, 1.0, 0.0)  # type: ignore[misc]


BAD_SPECS = [
    ({"count": 2}, "at least 3 chains"),
    ({"knee_height_m": 0.95}, "heights must rise"),
    ({"hem_height_m": 0.55}, "heights must rise"),
    ({"blend_height_m": 0.9}, "heights must rise"),
    ({"prefix": ""}, "prefix is empty"),
]

BAKE_ARGUMENTS = {
    "armature_name": "NoSuchArmature",
    "mesh_name": "NoSuchMesh",
    "garment_material": "M_Skirt",
    "anchor_bone_name": "pelvis",
    "action_name": "thigh_swing",
}


@pytest.mark.parametrize(("override", "message"), BAD_SPECS)
def test_skinclips_spec_refuses_a_ring_that_would_divide_by_zero(override, message):
    """skinclip's weights divide by top - knee and blend - top; the dataclass refuses those at construction."""
    with pytest.raises(ValueError, match=message):
        RingSkirtSpec(**{**GOOD_SPEC, **override})


@pytest.mark.parametrize(("override", "message"), BAD_SPECS)
def test_a_bad_spec_fails_before_the_op_body_runs_and_so_before_the_scene_is_touched(
    override, message
):
    """The agent binds the spec while building the call, so the op never starts.

    The armature named here does not exist: had the op body run, the error
    would be `UnknownObject`, and importing bpy would fail in this layer.
    """
    result = call_op(
        "bake_cloth_chains",
        bake_cloth_chains,
        {**BAKE_ARGUMENTS, "spec": {**GOOD_SPEC, **override}},
    )

    assert not result.ok
    assert result.stage_reached == "execute"
    assert result.execution.error_type == "ValueError"
    assert message in result.execution.traceback_text
    assert "UnknownObject" not in result.execution.traceback_text
