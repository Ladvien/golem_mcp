"""OT-51: skinned-motion ops, measured on skinclip's tube humanoid imported into Blender.

`skinclip.testing.tube_humanoid` writes a 22-joint UE5-named tube humanoid
with one animation; Blender imports it through its own glTF importer, so
the bones carry Blender's rest orientation and the action Blender's
slotted-action layout: the conversions in `golem_blender.ops._skinned` are
exercised on a real import, not on a hand-built rig.

What each test defends:
  - the report FAILS on `hand_through_torso` and names the arm against the torso;
  - the capsule report holds the 18 capsules of a humanoid, 6 central and 6 a side;
  - the repair clears the clip (re-measured by the report, which re-reads the
    written fcurves) and leaves every curve it did not change untouched;
  - the cloth bake creates 24 bones once, weights the garment, and the baked
    chains keep clear of the legs as the POSED BONES show, with a control that
    shows the same probe failing on chains that were never baked.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")
mathutils = pytest.importorskip("mathutils", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAMES_PER_SECOND = 30
HAND_THROUGH_TORSO_FRAMES = 61  # 2 s keyed at 30 fps, both ends included
THIGH_SWING_FRAMES = 31  # a 1 s loop
EXPECTED_CAPSULE_COUNT = 18
EXPECTED_CENTRAL_CAPSULE_COUNT = 6
EXPECTED_SIDED_CAPSULE_COUNT = 6
REPAIRED_DEPTH_LIMIT_M = 0.002
# a quaternion component, unitless; far below anything a viewer could see
REPAIRED_KEY_DRIFT_LIMIT = 1e-3
ARM_BONES = {"upperarm_l", "lowerarm_l", "hand_l"}
TORSO_BONES = {"pelvis", "spine_01", "spine_02", "spine_03", "thigh_l", "thigh_r"}
CLEARANCE_LIMIT_M = -0.005
# Measured 2026-10-12 on skinclip v0.1.2: the same 24 bones with their keys
# removed AND their pose reset to rest (chains hanging at their rest pose
# against the swinging thighs) read -0.0700 m, against +0.0170 m for the baked
# chains. (With the keys removed but the pose NOT reset the property keeps its
# last evaluated value, so the chains hang frozen in the baked frame-30 pose
# and read -0.0690 m: that is not a control for "never baked".) A probe that
# could not read below this ceiling could not tell a bake from none.
UNBAKED_CHAIN_CLEARANCE_CEILING_M = -0.02
REST_QUATERNION_WXYZ = (1.0, 0.0, 0.0, 0.0)

MOVE_M = (3.0, -2.0, 0.5)
TURN_RAD = 0.5

GARMENT_MATERIAL = "M_Skirt"
GARMENT_RADIUS_M = 0.18
GARMENT_BOTTOM_M = 0.15
GARMENT_TOP_M = 0.95
GARMENT_RING_STEP_M = 0.05
GARMENT_AROUND_COUNT = 48
GARMENT_NAME = "SkirtGarment"
ANCHOR_BONE = "pelvis"
CHAIN_BONE_COUNT = 24


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FRAMES_PER_SECOND
    bpy.context.scene.render.fps_base = 1.0
    yield


def _import_tube(tmp_path, clip: str) -> tuple[str, str]:
    """Import the tube humanoid with `clip`; return (armature name, action name)."""
    from skinclip.testing import tube_humanoid

    path = tmp_path / f"{clip}.glb"
    tube_humanoid(path, "ue5", clip)
    bpy.ops.import_scene.gltf(filepath=str(path))
    armature = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    return armature.name, armature.animation_data.action.name


def _channel_snapshot(armature_name: str) -> dict:
    """Every fcurve of the active action as (data_path, index) -> list of (frame, value)."""
    from golem_blender.ops.animation import _action_fcurves

    armature = bpy.data.objects[armature_name]
    return {
        (fc.data_path, fc.array_index): [(k.co[0], k.co[1]) for k in fc.keyframe_points]
        for fc in _action_fcurves(armature)
    }


def _add_garment(armature_name: str) -> str:
    """An open ring of quads 0.18 m round the body, 0.15-0.95 m high, on material M_Skirt, bound unweighted."""
    from golem_blender.ops.rigging import bind_mesh_to_armature

    heights = [
        round(GARMENT_BOTTOM_M + i * GARMENT_RING_STEP_M, 4)
        for i in range(
            int((GARMENT_TOP_M - GARMENT_BOTTOM_M) / GARMENT_RING_STEP_M) + 1
        )
    ]
    vertices = [
        (
            GARMENT_RADIUS_M * math.sin(2 * math.pi * k / GARMENT_AROUND_COUNT),
            -GARMENT_RADIUS_M * math.cos(2 * math.pi * k / GARMENT_AROUND_COUNT),
            height,
        )
        for height in heights
        for k in range(GARMENT_AROUND_COUNT)
    ]
    faces = [
        (
            row * GARMENT_AROUND_COUNT + k,
            row * GARMENT_AROUND_COUNT + (k + 1) % GARMENT_AROUND_COUNT,
            (row + 1) * GARMENT_AROUND_COUNT + (k + 1) % GARMENT_AROUND_COUNT,
            (row + 1) * GARMENT_AROUND_COUNT + k,
        )
        for row in range(len(heights) - 1)
        for k in range(GARMENT_AROUND_COUNT)
    ]
    mesh = bpy.data.meshes.new(GARMENT_NAME)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    mesh.materials.append(bpy.data.materials.new(GARMENT_MATERIAL))
    garment = bpy.data.objects.new(GARMENT_NAME, mesh)
    bpy.context.scene.collection.objects.link(garment)
    bind_mesh_to_armature(GARMENT_NAME, armature_name, automatic_weights=False)
    return GARMENT_NAME


def _skirt_spec():
    from golem_blender.ops.motion import RingSkirtSpec

    return RingSkirtSpec(
        count=12,
        top_height_m=0.90,
        knee_height_m=0.55,
        hem_height_m=0.20,
        blend_height_m=1.0,
        inset_m=0.0,
    )


def _group_weights(mesh_name: str) -> dict:
    mesh = bpy.data.objects[mesh_name]
    names = {g.index: g.name for g in mesh.vertex_groups}
    return {
        v.index: {names[e.group]: round(e.weight, 9) for e in v.groups}
        for v in mesh.data.vertices
    }


# ---------------------------------------------------------------------------
# clip_self_intersection_report
# ---------------------------------------------------------------------------


def test_the_hand_through_the_torso_fails_and_names_the_arm_against_the_trunk(
    empty_scene, tmp_path
):
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    report = clip_self_intersection_report(armature, action)

    assert report.action_name == action
    assert report.frames == HAND_THROUGH_TORSO_FRAMES
    assert not report.passed
    assert report.failing_frame_count > 0
    assert report.worst_contour_m > 0.04, "the contour is metres long, not borderline"
    # The arm reaches the hip from about frame 25: Blender frame numbers, not indices
    # (the action starts at frame 0 here, so index == frame; the next test moves it).
    assert 25 <= report.worst_frame <= 60
    assert report.worst_pairs, "a failing report must say which parts cross"
    named = [
        (set(pair.label_a.split(":")[1:]), set(pair.label_b.split(":")[1:]))
        for pair in report.worst_pairs
    ]
    assert any(
        (a & ARM_BONES and b & TORSO_BONES) or (b & ARM_BONES and a & TORSO_BONES)
        for a, b in named
    ), f"no pair names an arm bone against the trunk: {report.worst_pairs}"
    assert all(pair.contour_m > 0 for pair in report.worst_pairs)


def test_frames_are_blender_frame_numbers_when_the_action_starts_late(
    empty_scene, tmp_path
):
    """Shifting every key by 100 frames moves worst_frame by 100; an index would not."""
    from golem_blender.ops.animation import _action_fcurves
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    before = clip_self_intersection_report(armature, action)
    shift = 100
    for fcurve in _action_fcurves(bpy.data.objects[armature]):
        for keyframe in fcurve.keyframe_points:
            keyframe.co[0] += shift
            keyframe.handle_left[0] += shift
            keyframe.handle_right[0] += shift
        fcurve.update()
    after = clip_self_intersection_report(armature, action)

    assert after.worst_frame == before.worst_frame + shift
    assert after.frames == before.frames
    assert after.worst_contour_m == pytest.approx(before.worst_contour_m, abs=1e-6)


def test_a_clean_clip_passes(empty_scene, tmp_path):
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "rest")
    report = clip_self_intersection_report(armature, action)

    assert report.passed
    assert report.failing_frame_count == 0
    assert report.worst_pairs == ()


def test_a_looser_limit_passes_what_the_default_fails(empty_scene, tmp_path):
    """contour_limit_m reaches the check: a limit above the worst contour passes the same clip."""
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    strict = clip_self_intersection_report(armature, action)
    loose = clip_self_intersection_report(
        armature, action, contour_limit_m=strict.worst_contour_m + 1.0
    )

    assert not strict.passed and loose.passed
    assert loose.worst_contour_m == pytest.approx(strict.worst_contour_m, abs=1e-6)


def test_a_rotation_mode_other_than_quaternion_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.motion import (
        ArmatureRotationModeError,
        clip_self_intersection_report,
    )

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    bpy.data.objects[armature].pose.bones["upperarm_l"].rotation_mode = "XYZ"

    with pytest.raises(ArmatureRotationModeError, match="upperarm_l"):
        clip_self_intersection_report(armature, action)
    assert issubclass(ArmatureRotationModeError, ValueError)


def test_a_constrained_bone_is_refused_by_name(empty_scene, tmp_path):
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    bpy.data.objects[armature].pose.bones["hand_r"].constraints.new("COPY_ROTATION")

    with pytest.raises(ValueError, match="hand_r"):
        clip_self_intersection_report(armature, action)


def test_an_action_that_is_not_active_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, _ = _import_tube(tmp_path, "hand_through_torso")

    with pytest.raises(ValueError, match="not the active action"):
        clip_self_intersection_report(armature, "no_such_action")


def test_an_unweighted_vertex_is_refused_not_sent_to_the_origin(empty_scene, tmp_path):
    from golem_blender.ops.motion import clip_self_intersection_report

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    garment = _add_garment(armature)  # bound, no vertex groups at all

    with pytest.raises(
        ValueError,
        match=rf"carry no bone weight.*{garment}|{garment}.*carry no bone weight",
    ):
        clip_self_intersection_report(armature, action)


# ---------------------------------------------------------------------------
# body_capsules_report
# ---------------------------------------------------------------------------


def test_the_capsule_report_holds_the_eighteen_capsules_of_a_ue5_humanoid(
    empty_scene, tmp_path
):
    from golem_blender.ops.motion import body_capsules_report

    armature, _ = _import_tube(tmp_path, "rest")
    report = body_capsules_report(armature)

    assert report.rig_convention == "ue5"
    assert len(report.capsules) == EXPECTED_CAPSULE_COUNT
    names = [capsule.name for capsule in report.capsules]
    assert len(set(names)) == EXPECTED_CAPSULE_COUNT
    sided = {n for n in names if n.endswith(("_l", "_r"))}
    assert len(names) - len(sided) == EXPECTED_CENTRAL_CAPSULE_COUNT
    for side in ("_l", "_r"):
        assert (
            len([n for n in sided if n.endswith(side)]) == EXPECTED_SIDED_CAPSULE_COUNT
        )

    by_name = {capsule.name: capsule for capsule in report.capsules}
    # The centroid rule has no end bone: the head and both hands.
    assert {n for n, c in by_name.items() if c.end_bone == ""} == {
        "head",
        "hand_l",
        "hand_r",
    }
    assert by_name["upperarm_l"].start_bone == "upperarm_l"
    assert by_name["upperarm_l"].end_bone == "lowerarm_l"
    for capsule in report.capsules:
        assert 0.0 < capsule.radius_m <= 0.20
        assert all(math.isfinite(x) for x in (*capsule.start_m, *capsule.end_m))


def test_capsule_positions_are_world_metres_at_rest(empty_scene, tmp_path):
    """The tube's left upper arm runs from x=0.22 to x=0.52 at height 1.42 m, radius 0.05 m."""
    from golem_blender.ops.motion import body_capsules_report

    armature, _ = _import_tube(tmp_path, "rest")
    by_name = {c.name: c for c in body_capsules_report(armature).capsules}
    arm = by_name["upperarm_l"]

    assert arm.start_m == pytest.approx((0.22, 0.0, 1.42), abs=1e-4)
    assert arm.end_m == pytest.approx((0.52, 0.0, 1.42), abs=1e-4)
    assert arm.radius_m == pytest.approx(0.05, abs=0.01)
    # Different capsules sit in different places: a probe that read one value everywhere is broken.
    assert len({c.start_m for c in by_name.values()}) > 10


def test_a_rig_that_is_not_a_humanoid_is_refused(empty_scene):
    from golem_blender.ops.motion import body_capsules_report
    from golem_blender.ops.primitives import add_box, link_into_scene
    from golem_blender.ops.rigging import BoneSpec, add_armature, bind_mesh_to_armature

    link_into_scene(add_box("Subject", 0.3, 0.3, 1.0))
    add_armature(
        "TwoBones",
        (
            BoneSpec("Root", (0, 0, 0), (0, 0, 0.5)),
            BoneSpec("Tip", (0, 0, 0.5), (0, 0, 1.0), parent_name="Root"),
        ),
    )
    bind_mesh_to_armature("Subject", "TwoBones", automatic_weights=True)

    with pytest.raises(ValueError, match="not a humanoid rig"):
        body_capsules_report("TwoBones")


def test_a_moved_and_turned_armature_measures_the_same(empty_scene, tmp_path):
    """A rigid move of the armature (and its child mesh) changes where things are, not what crosses.

    The adapter composes `armature.matrix_world` into the roots' rest matrix, the
    inverse bind and the mesh's vertices; leaving any one out reads a sheared figure.
    """
    from golem_blender.ops.motion import (
        body_capsules_report,
        clip_self_intersection_report,
    )

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    still = clip_self_intersection_report(armature, action)
    still_arm = {c.name: c for c in body_capsules_report(armature).capsules}[
        "upperarm_l"
    ]

    moved = bpy.data.objects[armature]
    moved.location = MOVE_M
    moved.rotation_euler = (0.0, 0.0, TURN_RAD)
    bpy.context.view_layer.update()
    after = clip_self_intersection_report(armature, action)
    moved_arm = {c.name: c for c in body_capsules_report(armature).capsules}[
        "upperarm_l"
    ]

    assert after.worst_contour_m == pytest.approx(still.worst_contour_m, abs=1e-3)
    assert after.worst_frame == still.worst_frame
    assert after.failing_frame_count == still.failing_frame_count
    expected = moved.matrix_world @ mathutils.Vector(still_arm.start_m)
    assert moved_arm.start_m == pytest.approx(tuple(expected), abs=1e-4)
    assert moved_arm.start_m != pytest.approx(still_arm.start_m, abs=0.1)
    assert moved_arm.radius_m == pytest.approx(still_arm.radius_m, abs=1e-6)


def test_a_mixamo_rig_is_read_as_mixamo(empty_scene, tmp_path):
    from skinclip.testing import tube_humanoid

    from golem_blender.ops.motion import body_capsules_report

    path = tmp_path / "mixamo.glb"
    tube_humanoid(path, "mixamo", "rest")
    bpy.ops.import_scene.gltf(filepath=str(path))
    armature = next(o for o in bpy.data.objects if o.type == "ARMATURE")

    report = body_capsules_report(armature.name)

    assert report.rig_convention == "mixamo"
    assert len(report.capsules) == EXPECTED_CAPSULE_COUNT
    assert {c.start_bone for c in report.capsules} >= {
        "mixamorig:LeftArm",
        "mixamorig:Hips",
    }


# ---------------------------------------------------------------------------
# repair_limb_penetration
# ---------------------------------------------------------------------------


def test_the_repair_clears_the_hand_and_touches_only_the_arm(empty_scene, tmp_path):
    from golem_blender.ops.motion import (
        clip_self_intersection_report,
        repair_limb_penetration,
    )

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    before_report = clip_self_intersection_report(armature, action)
    before_curves = _channel_snapshot(armature)

    repair = repair_limb_penetration(armature, action)
    after_report = clip_self_intersection_report(armature, action)

    assert not before_report.passed and before_report.worst_contour_m > 0.04
    assert repair.worst_depth_m_before > 0.03
    assert repair.worst_depth_m_after <= REPAIRED_DEPTH_LIMIT_M
    assert repair.frames_repaired > 0
    assert repair.bones_changed and set(repair.bones_changed) <= {
        "upperarm_l",
        "lowerarm_l",
    }
    assert after_report.passed, f"the repaired clip still crosses: {after_report}"
    assert after_report.worst_contour_m < before_report.worst_contour_m

    after_curves = _channel_snapshot(armature)
    changed_paths = {
        f'pose.bones["{bone}"].rotation_quaternion' for bone in repair.bones_changed
    }
    for key, keys_before in before_curves.items():
        if key[0] in changed_paths:
            continue
        assert after_curves[key] == keys_before, f"{key} changed but was not repaired"
    for path in changed_paths:
        for component in range(4):
            written = after_curves[(path, component)]
            assert [frame for frame, _ in written] == list(
                range(HAND_THROUGH_TORSO_FRAMES)
            ), "one key per frame"
    assert any(
        after_curves[(path, component)] != before_curves[(path, component)]
        for path in changed_paths
        for component in range(4)
    ), "the repair reported a change and wrote the same keys"


def test_a_second_repair_only_trims_micrometres(empty_scene, tmp_path):
    """The repaired clip is clear to REPAIRED_DEPTH_LIMIT_M, so a second pass has nothing real to move.

    The first pass solves onto the clearance's edge and Blender stores keys as
    float32, so the second can still see a micrometre of overlap on a few
    frames (measured 2026-10-12: 0.9 micrometre on 4 frames); it must stay
    that small and must not move a key by more than a hair.
    """
    from golem_blender.ops.motion import repair_limb_penetration

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    repair_limb_penetration(armature, action)
    curves = _channel_snapshot(armature)

    again = repair_limb_penetration(armature, action)

    assert again.worst_depth_m_before <= REPAIRED_DEPTH_LIMIT_M
    assert again.worst_depth_m_after <= REPAIRED_DEPTH_LIMIT_M
    moved = max(
        abs(value - before)
        for key, keys in _channel_snapshot(armature).items()
        for (_, value), (_, before) in zip(keys, curves[key])
    )
    assert moved < REPAIRED_KEY_DRIFT_LIMIT


def test_the_repair_refuses_an_action_that_moves_a_bone_it_cannot_see(
    empty_scene, tmp_path
):
    """Only rotations and the pelvis location are read; a moving hand location would be repaired blind."""
    from golem_blender.ops.animation import _action_channelbag
    from golem_blender.ops.motion import repair_limb_penetration

    armature, action = _import_tube(tmp_path, "hand_through_torso")
    bag = _action_channelbag(bpy.data.objects[armature])
    fcurve = bag.fcurves.new(
        'pose.bones["hand_l"].location', index=0, group_name="hand_l"
    )
    fcurve.keyframe_points.add(2)
    fcurve.keyframe_points.foreach_set("co", [0.0, 0.0, 60.0, 0.1])
    fcurve.update()

    with pytest.raises(ValueError, match=r"hand_l \(location\)"):
        repair_limb_penetration(armature, action)


# ---------------------------------------------------------------------------
# bake_cloth_chains
# ---------------------------------------------------------------------------


def _bake(tmp_path):
    from golem_blender.ops.motion import bake_cloth_chains

    armature, action = _import_tube(tmp_path, "thigh_swing")
    garment = _add_garment(armature)
    spec = _skirt_spec()
    report = bake_cloth_chains(
        armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, action, spec, loop=True
    )
    return armature, action, garment, spec, report


def test_the_cloth_bake_creates_the_chains_weights_the_garment_and_clears_the_legs(
    empty_scene, tmp_path
):
    armature, _, garment, spec, report = _bake(tmp_path)

    assert report.bones_created == CHAIN_BONE_COUNT
    assert report.frames_baked == THIGH_SWING_FRAMES
    assert report.vertices_weighted > 0
    assert report.worst_clearance_m >= CLEARANCE_LIMIT_M, (
        f"a chain passes {-report.worst_clearance_m * 1000:.1f} mm into a leg"
    )

    bones = bpy.data.objects[armature].data.bones
    for i in range(spec.count):
        upper, lower = bones[f"skirt_{i:02d}_a"], bones[f"skirt_{i:02d}_b"]
        assert upper.parent.name == ANCHOR_BONE
        assert lower.parent.name == upper.name
        # a's tail is b's head: the chain is one continuous run of two bones
        assert tuple(upper.tail_local) == pytest.approx(
            tuple(lower.head_local), abs=1e-5
        )

    groups = {g.name for g in bpy.data.objects[garment].vertex_groups}
    assert groups >= {f"skirt_{i:02d}_{s}" for i in range(spec.count) for s in "ab"}
    weights = _group_weights(garment)
    assert all(
        math.isclose(sum(w.values()), 1.0, abs_tol=1e-4) and len(w) <= 4
        for w in weights.values()
    ), "every garment vertex is normalised over at most four influences"


def test_the_baked_keys_are_one_per_frame_on_the_chain_bones_only(
    empty_scene, tmp_path
):
    armature, _, _, spec, _ = _bake(tmp_path)
    curves = _channel_snapshot(armature)
    chain_paths = {
        f'pose.bones["skirt_{i:02d}_{s}"].rotation_quaternion'
        for i in range(spec.count)
        for s in "ab"
    }

    for path in chain_paths:
        for component in range(4):
            keys = curves[(path, component)]
            assert [frame for frame, _ in keys] == list(range(THIGH_SWING_FRAMES))
    # a loop: the last key equals the first (skinclip closes the seam)
    for path in chain_paths:
        first = [curves[(path, c)][0][1] for c in range(4)]
        last = [curves[(path, c)][-1][1] for c in range(4)]
        assert last == pytest.approx(first, abs=1e-4) or last == pytest.approx(
            [-x for x in first], abs=1e-4
        )


def test_the_chains_move_and_the_new_bones_have_their_own_rest_orientation(
    empty_scene, tmp_path
):
    """Two guards on the proof itself: the posed chains vary, and the rest frame is not the identity.

    A clearance read off bones that never moved, or off bones whose rest frame
    happened to be the world's, would pass for the wrong reason.
    """
    armature_name, _, _, _, _ = _bake(tmp_path)
    armature = bpy.data.objects[armature_name]
    scene = bpy.context.scene

    hems = []
    for frame in (0, THIGH_SWING_FRAMES // 4, THIGH_SWING_FRAMES // 2):
        scene.frame_set(frame)
        posed = armature.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones
        hems.append(tuple(posed["skirt_03_b"].tail))
    assert len(set(hems)) == len(hems), f"the hem of chain 3 never moves: {hems}"
    assert max(math.dist(hems[0], other) for other in hems[1:]) > 0.01, (
        "the hem moves less than a centimetre"
    )

    rotation = armature.data.bones["skirt_00_a"].matrix_local.to_3x3()
    identity_distance = sum(
        abs(rotation[r][c] - (1.0 if r == c else 0.0))
        for r in range(3)
        for c in range(3)
    )
    assert identity_distance > 0.5, "the chain bone's rest frame is the world frame"


def test_the_clearance_probe_fails_on_chains_that_were_never_baked(
    empty_scene, tmp_path
):
    """Control: the same probe on the same bones, keys removed, must read a leg through the skirt."""
    from skinclip import capsules, humanoid
    from skinclip.intersect import CheckSettings

    from golem_blender.ops import _skinned
    from golem_blender.ops.animation import _action_channelbag

    armature_name, _, garment, spec, report = _bake(tmp_path)
    armature = bpy.data.objects[armature_name]
    bag = _action_channelbag(armature)
    for fcurve in [
        fc for fc in bag.fcurves if fc.data_path.startswith('pose.bones["skirt_')
    ]:
        bag.fcurves.remove(fcurve)
    # Removing a curve leaves its property at the last value it evaluated to.
    for pose_bone in armature.pose.bones:
        if pose_bone.name.startswith("skirt_"):
            pose_bone.rotation_quaternion = REST_QUATERNION_WXYZ
    bpy.context.view_layer.update()

    figure = _skinned.read_figure(
        armature, CheckSettings(non_crease_prefixes=("skirt_",))
    )
    measured = capsules.measure(
        figure, humanoid.detect(figure.skeleton.names), ignore_prefixes=("skirt_",)
    )
    skirt = _skinned.chain_layout(
        armature, bpy.data.objects[garment], GARMENT_MATERIAL, spec
    )
    unbaked = _skinned.posed_chain_clearance_m(
        armature, list(range(THIGH_SWING_FRAMES)), measured, skirt
    )

    assert report.worst_clearance_m >= CLEARANCE_LIMIT_M
    assert unbaked < UNBAKED_CHAIN_CLEARANCE_CEILING_M, (
        f"unbaked chains read {unbaked:.4f} m: the probe cannot tell a bake from none"
    )


def test_a_bake_leaves_the_active_object_and_selection_as_it_found_them(
    empty_scene, tmp_path
):
    from golem_blender.ops.motion import bake_cloth_chains

    armature, action = _import_tube(tmp_path, "thigh_swing")
    garment = _add_garment(armature)
    garment_object = bpy.data.objects[garment]
    bpy.context.view_layer.objects.active = garment_object
    for obj in bpy.data.objects:
        obj.select_set(obj is garment_object)

    bake_cloth_chains(
        armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, action, _skirt_spec()
    )

    assert bpy.context.view_layer.objects.active is garment_object
    assert {o.name for o in bpy.data.objects if o.select_get()} == {garment}


def test_a_second_bake_reuses_the_bones_and_leaves_the_weights_alone(
    empty_scene, tmp_path
):
    from golem_blender.ops.motion import bake_cloth_chains

    armature, action, garment, spec, first = _bake(tmp_path)
    weights = _group_weights(garment)
    bone_names = {b.name for b in bpy.data.objects[armature].data.bones}

    second = bake_cloth_chains(
        armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, action, spec, loop=True
    )

    assert first.bones_created == CHAIN_BONE_COUNT
    assert second.bones_created == 0
    assert second.vertices_weighted == 0
    assert _group_weights(garment) == weights
    assert {b.name for b in bpy.data.objects[armature].data.bones} == bone_names
    assert second.frames_baked == first.frames_baked
    assert second.worst_clearance_m == pytest.approx(first.worst_clearance_m, abs=1e-6)


def test_a_partial_set_of_chain_bones_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.animation import _action_channelbag
    from golem_blender.ops.motion import bake_cloth_chains

    armature, action = _import_tube(tmp_path, "thigh_swing")
    garment = _add_garment(armature)
    spec = _skirt_spec()
    bake_cloth_chains(armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, action, spec)
    arm_object = bpy.data.objects[armature]
    bpy.context.view_layer.objects.active = arm_object
    with bpy.context.temp_override(object=arm_object, active_object=arm_object):
        bpy.ops.object.mode_set(mode="EDIT")
        arm_object.data.edit_bones.remove(arm_object.data.edit_bones["skirt_05_b"])
        bpy.ops.object.mode_set(mode="OBJECT")
    bag = _action_channelbag(arm_object)
    for stale in [fc for fc in bag.fcurves if "skirt_05_b" in fc.data_path]:
        bag.fcurves.remove(stale)  # the removed bone's keys would be refused first

    with pytest.raises(ValueError, match="23 of the 24 chain bones"):
        bake_cloth_chains(
            armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, action, spec
        )


def test_a_material_the_mesh_does_not_hold_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.motion import bake_cloth_chains

    armature, action = _import_tube(tmp_path, "thigh_swing")
    garment = _add_garment(armature)

    with pytest.raises(ValueError, match="no material slot holding 'M_Missing'"):
        bake_cloth_chains(
            armature, garment, "M_Missing", ANCHOR_BONE, action, _skirt_spec()
        )


def _bone_names(armature_name: str) -> set[str]:
    return {b.name for b in bpy.data.objects[armature_name].data.bones}


def test_a_refused_bake_leaves_the_scene_as_it_found_it(empty_scene, tmp_path):
    """Each refusal comes before the first bone or weight is written."""
    from golem_blender.ops.motion import bake_cloth_chains
    from golem_blender.ops.primitives import add_box, link_into_scene
    from golem_blender.ops.rigging import BoneSpec, add_armature

    armature, action = _import_tube(tmp_path, "thigh_swing")
    garment = _add_garment(armature)
    spec = _skirt_spec()
    bones_before = _bone_names(armature)
    groups_before = [g.name for g in bpy.data.objects[garment].vertex_groups]

    with pytest.raises(ValueError, match="not the active action"):
        bake_cloth_chains(
            armature, garment, GARMENT_MATERIAL, ANCHOR_BONE, "no_such_action", spec
        )
    with pytest.raises(ValueError, match="no anchor bone 'no_such_bone'"):
        bake_cloth_chains(
            armature, garment, GARMENT_MATERIAL, "no_such_bone", action, spec
        )
    link_into_scene(add_box("Loose", 0.3, 0.3, 0.3))
    with pytest.raises(ValueError, match="is not bound to armature"):
        bake_cloth_chains(
            armature, "Loose", GARMENT_MATERIAL, ANCHOR_BONE, action, spec
        )
    add_armature("Plain", (BoneSpec("Only", (0, 0, 0), (0, 0, 1)),))
    with pytest.raises(ValueError, match="not a humanoid rig"):
        bake_cloth_chains("Plain", garment, GARMENT_MATERIAL, "Only", action, spec)

    assert _bone_names(armature) == bones_before
    assert [g.name for g in bpy.data.objects[garment].vertex_groups] == groups_before


# ---------------------------------------------------------------------------
# the definitions golem_blender shares with skinclip
# ---------------------------------------------------------------------------


def test_the_exported_ring_skirt_spec_is_skinclips_own():
    from skinclip import cloth
    from skinclip.spec import RingSkirtSpec as skinclip_spec

    import golem_blender.ops
    from golem_blender.ops.motion import RingSkirtSpec

    assert RingSkirtSpec is skinclip_spec
    assert golem_blender.ops.RingSkirtSpec is skinclip_spec
    assert cloth.RingSkirtSpec is skinclip_spec


def test_the_default_contour_limit_is_skinclips():
    from skinclip.intersect import CheckSettings

    from golem_blender.ops.motion import DEFAULT_CONTOUR_LIMIT_M

    assert DEFAULT_CONTOUR_LIMIT_M == CheckSettings().contour_limit_m
