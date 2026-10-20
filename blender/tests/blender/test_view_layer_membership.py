"""The view layer: an object the scene holds but the layer does not.

A newly linked object does not appear in
``bpy.context.view_layer.objects`` until the depsgraph has been
refreshed. Measured in Blender 5.2: ``link_into_scene`` put the object
in ``scene.collection.objects`` and the object was NOT in the view
layer's object list. An object outside the view layer is invisible to
a RENDER — the asset looked like a flat empty field while the scene
held it — and the analyzer measures the stored mesh rather than the
evaluated one.

This is the regression test for that.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_a_linked_object_joins_the_view_layer(empty_scene):
    """The op that links an object must also refresh the view layer."""
    from golem_blender.ops.primitives import add_box, link_into_scene

    name = add_box("Subject", 0.4, 0.4, 0.4)
    link_into_scene(name)

    assert name in bpy.context.scene.collection.objects
    assert name in bpy.context.view_layer.objects, (
        "the object is in the scene collection but not in the view layer, "
        "so a render cannot see it"
    )


def test_a_linked_object_is_evaluated_by_the_depsgraph(empty_scene):
    """The evaluated copy must exist, or the analyzer measures stored values."""
    from golem_blender.ops.primitives import add_box, link_into_scene

    name = add_box("Subject", 0.4, 0.4, 0.4)
    link_into_scene(name)
    bpy.context.view_layer.update()

    blender_object = bpy.data.objects[name]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = blender_object.evaluated_get(depsgraph)

    assert evaluated is not None
    assert evaluated.matrix_world is not None


def test_linking_twice_is_still_one_object(empty_scene):
    """The op is idempotent by name, and the view layer still has one copy."""
    from golem_blender.ops.primitives import add_box, link_into_scene

    name = add_box("Subject", 0.4, 0.4, 0.4)
    link_into_scene(name)
    link_into_scene(name)

    matching = [
        scene_object
        for scene_object in bpy.context.view_layer.objects
        if scene_object.name == name
    ]
    assert len(matching) == 1
