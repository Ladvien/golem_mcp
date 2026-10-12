"""A wipe that is not asserted is a wipe that left something behind.

The postcondition is the point of the module: `reset_scene` wipes and
`assert_clean_scene` proves it, so a rebuild can never measure residue
from the build before it.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

NON_CANONICAL_FPS = 30


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _populate_scene():
    """One object, its mesh, a material and an action: the four kinds of
    datablock a build leaves behind."""
    mesh_data = bpy.data.meshes.new("ResidueMesh")
    mesh_data.from_pydata(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], [], [(0, 1, 2)]
    )
    mesh_data.update()
    residue_object = bpy.data.objects.new("ResidueObject", mesh_data)
    bpy.context.scene.collection.objects.link(residue_object)
    residue_object.data.materials.append(bpy.data.materials.new("ResidueMaterial"))
    bpy.data.actions.new("ResidueAction")
    return residue_object


def test_reset_scene_empties_the_scene_and_pins_the_fps(empty_scene):
    from blended.reset import CANONICAL_FPS, reset_scene

    _populate_scene()
    bpy.context.scene.render.fps = NON_CANONICAL_FPS
    assert len(bpy.data.objects) == 1  # the fixture must be present to be wiped

    reset_scene()

    assert len(bpy.data.objects) == 0
    assert len(bpy.data.meshes) == 0
    assert len(bpy.data.actions) == 0
    assert bpy.context.scene.render.fps == CANONICAL_FPS


def test_a_leftover_object_is_not_a_clean_scene(empty_scene):
    """The assertion, not the wipe, is what a rebuild trusts."""
    from blended.reset import SceneNotClean, assert_clean_scene, reset_scene

    reset_scene()
    assert_clean_scene()  # the wipe's own postcondition, run twice on purpose

    residue_object = _populate_scene()
    with pytest.raises(SceneNotClean) as raised:
        assert_clean_scene()
    assert residue_object.name in str(raised.value)


def test_a_rewritten_fps_is_not_a_clean_scene(empty_scene):
    """An FBX import rewrites scene.render.fps and resamples every clip,
    so fps is part of "clean" rather than a rendering preference."""
    from blended.reset import SceneNotClean, assert_clean_scene, reset_scene

    reset_scene()
    bpy.context.scene.render.fps = NON_CANONICAL_FPS

    with pytest.raises(SceneNotClean) as raised:
        assert_clean_scene()
    assert "fps" in str(raised.value)


def test_every_problem_is_reported_in_one_raise(empty_scene):
    """One problem per raise costs a Blender launch per problem."""
    from blended.reset import SceneNotClean, assert_clean_scene, reset_scene

    reset_scene()
    _populate_scene()
    bpy.context.scene.render.fps = NON_CANONICAL_FPS

    with pytest.raises(SceneNotClean) as raised:
        assert_clean_scene()
    message = str(raised.value)
    assert "objects remain" in message
    assert "meshes remain" in message
    assert "fps" in message


def test_every_wipe_collection_name_resolves_on_bpy_data(empty_scene):
    """Every name in WIPE_COLLECTIONS and MUST_BE_EMPTY must be a real
    bpy.data attribute. This is the test that would have caught
    ``grease_pencils_v3`` — which was never a bpy.data collection in
    Blender 5.2 and made the row dead.

    One-line edit that reddens it: change ``"grease_pencils"`` back to
    ``"grease_pencils_v3"`` in WIPE_COLLECTIONS — the assert below
    fails with AttributeError because getattr returns None.
    """
    from blended.reset import MUST_BE_EMPTY, WIPE_COLLECTIONS

    for name in WIPE_COLLECTIONS:
        assert getattr(bpy.data, name, None) is not None, (
            f"bpy.data has no {name!r} collection — WIPE_COLLECTIONS has a dead name"
        )
    for name in MUST_BE_EMPTY:
        assert getattr(bpy.data, name, None) is not None, (
            f"bpy.data has no {name!r} collection — MUST_BE_EMPTY has a dead name"
        )


def test_a_grease_pencil_datablock_is_wiped_by_reset_scene(empty_scene):
    """A grease-pencil datablock must survive until reset_scene wipes it.
    Measured in Blender 5.2: the RNA name is ``grease_pencils`` (type
    BlendDataGreasePencilsV3), not ``grease_pencils_v3``.
    """
    from blended.reset import reset_scene

    bpy.data.grease_pencils.new("ResidueGreasePencil")
    assert len(bpy.data.grease_pencils) == 1

    reset_scene()

    assert len(bpy.data.grease_pencils) == 0
