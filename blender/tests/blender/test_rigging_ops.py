"""Rigging ops must produce a usable armature with bound weights.

These tests defend the contract that an in-Blender chat agent can rig,
bind, and weight-paint through blended.ops without touching bpy.ops
directly: add_armature builds N bones with parenting and is idempotent
by name; bind_mesh_to_armature with automatic weights leaves every
vertex weighted; weight_report on an unbound mesh reports emptiness;
assign_weights_by_height counts only vertices in the z-range.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _tall_box():
    """A 0.3 x 0.3 x 1.0 m box, base at z=0, linked into the scene."""
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("RigSubject", 0.3, 0.3, 1.0)
    link_into_scene(box)
    return box


def _three_bone_chain():
    """A vertical 3-bone armature inside the tall box (0 -> 0.5 -> 1.0 m)."""
    from blended.ops.rigging import BoneSpec, add_armature

    bones = (
        BoneSpec("Root", (0, 0, 0.0), (0, 0, 0.5)),
        BoneSpec("Mid", (0, 0, 0.5), (0, 0, 0.75), parent_name="Root", connected=True),
        BoneSpec("Tip", (0, 0, 0.75), (0, 0, 1.0), parent_name="Mid", connected=True),
    )
    return add_armature("Rig", bones)


# ---------------------------------------------------------------------------
# add_armature
# ---------------------------------------------------------------------------


def test_add_armature_creates_n_bones_with_parenting(empty_scene):
    from blended.ops.rigging import BoneSpec, add_armature

    bones = (
        BoneSpec("Root", (0, 0, 0.0), (0, 0, 0.5)),
        BoneSpec("Child", (0, 0, 0.5), (0, 0, 1.0), parent_name="Root", connected=True),
    )
    armature = add_armature("Arm", bones)

    armature_obj = bpy.data.objects[armature]
    assert armature_obj.type == "ARMATURE"
    bone_map = {b.name: b for b in armature_obj.data.bones}
    assert set(bone_map) == {"Root", "Child"}
    child = bone_map["Child"]
    assert child.parent is not None
    assert child.parent.name == "Root"
    assert child.use_connect is True


def test_add_armature_is_idempotent_by_name(empty_scene):
    from blended.ops.rigging import BoneSpec, add_armature

    bones = (BoneSpec("Only", (0, 0, 0), (0, 0, 0.5)),)
    add_armature("Twin", bones)
    add_armature("Twin", bones)

    armature_objs = [o for o in bpy.data.objects if o.name == "Twin"]
    assert len(armature_objs) == 1, "rerun must not leave a .001 sibling"
    assert len(armature_objs[0].data.bones) == 1


def test_add_armature_rejects_empty_bones(empty_scene):
    from blended.ops.rigging import add_armature

    with pytest.raises(ValueError, match="at least one bone"):
        add_armature("Empty", ())


def test_add_armature_rejects_zero_length_bone(empty_scene):
    from blended.ops.rigging import BoneSpec, add_armature

    with pytest.raises(ValueError, match="zero length"):
        add_armature("Stub", (BoneSpec("Stub", (0, 0, 0), (0, 0, 0)),))


def test_add_armature_rejects_unknown_parent(empty_scene):
    from blended.ops.rigging import BoneSpec, add_armature

    with pytest.raises(ValueError, match="unknown parent"):
        add_armature(
            "Bad",
            (BoneSpec("A", (0, 0, 0), (0, 0, 0.5), parent_name="Ghost"),),
        )


# ---------------------------------------------------------------------------
# bind_mesh_to_armature + weight_report
# ---------------------------------------------------------------------------


def test_bind_with_automatic_weights_weights_all_vertices(empty_scene):
    from blended.ops.rigging import bind_mesh_to_armature
    from blended.ops.weights import weight_report

    box = _tall_box()
    armature = _three_bone_chain()

    bind_mesh_to_armature(box, armature, automatic_weights=True)

    report = weight_report(box)
    nonzero_groups = [g for g, c in report.nonzero_weight_counts.items() if c > 0]
    assert len(nonzero_groups) >= 1, "automatic weights must produce at least one group"
    assert report.unweighted_vertex_count == 0, (
        f"every vertex must be weighted, got {report.unweighted_vertex_count} unweighted"
    )


def test_rig_report_lists_bound_meshes(empty_scene):
    from blended.ops.rigging import bind_mesh_to_armature, rig_report

    box = _tall_box()
    armature = _three_bone_chain()
    bind_mesh_to_armature(box, armature, automatic_weights=True)

    report = rig_report(armature)
    assert report.armature_name == "Rig"
    assert report.bone_count == 3
    assert report.bone_names == ("Root", "Mid", "Tip")
    assert "RigSubject" in report.bound_mesh_names


def test_weight_report_on_unbound_mesh_has_no_groups(empty_scene):
    from blended.ops.weights import weight_report

    box = _tall_box()
    report = weight_report(box)
    assert report.group_names == ()
    assert report.nonzero_weight_counts == {}
    assert report.unweighted_vertex_count == len(bpy.data.objects[box].data.vertices)


# ---------------------------------------------------------------------------
# assign_weights_by_height
# ---------------------------------------------------------------------------


def test_assign_weights_by_height_counts_only_in_range(empty_scene):
    from blended.ops.weights import assign_weights_by_height, weight_report

    box = _tall_box()
    # The box spans z=0 to z=1.  Weight only the top quarter [0.75, 1.0].
    count = assign_weights_by_height(box, "Top", 0.75, 1.0, 1.0)

    # A cube has 8 vertices; the top face has 4 at z=1.0.
    assert count == 4, f"expected 4 top-face vertices in range, got {count}"

    report = weight_report(box)
    assert "Top" in report.group_names
    assert report.nonzero_weight_counts["Top"] == 4


def test_assign_weights_by_height_excludes_out_of_range(empty_scene):
    from blended.ops.weights import assign_weights_by_height

    box = _tall_box()
    # Range above the box — should weight zero vertices.
    count = assign_weights_by_height(box, "Above", 2.0, 3.0, 1.0)
    assert count == 0
