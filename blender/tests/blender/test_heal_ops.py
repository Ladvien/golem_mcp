"""Healing must survive the meshes it exists to clean.

Iteration 5 died on `boolean_union` raising ReferenceError from inside
its own healing step, which consumed the addend and left the agent
unable to name what had happened to its scene. The op that cleans up
solver debris cannot itself fall over on solver debris.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


# Zero-area QUADS, which is the shape that reaches the collapse branch
# at all: `dissolve_degenerate` handles triangles and short edges, so a
# collinear tri never survives it, but a bow-tie quad has full-length
# edges and folds back on itself to enclose no area. Measured: two of
# these survive both earlier heal steps with area exactly 0.0.
BOWTIE_PAIR_VERTICES = [
    (0.0, 0.0, 0.0),
    (1.0, 1.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (2.0, 1.0, 0.0),
    (2.0, 0.0, 0.0),
]
# Two bow-ties sharing vertices 1 and 2, so collapsing an edge on behalf
# of the first can free the second while it is still in the list.
BOWTIE_PAIR_FACES = [(0, 1, 2, 3), (2, 4, 1, 5)]


def _mesh_of_adjacent_slivers(name="Slivers"):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(BOWTIE_PAIR_VERTICES, [], BOWTIE_PAIR_FACES)
    mesh.update()
    blender_object = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(blender_object)
    return blender_object


def test_adjacent_slivers_do_not_kill_the_healer(empty_scene):
    """The measured iteration-5 failure.

    `bmesh.ops.collapse` was called once per sliver face while iterating
    a list of faces collected beforehand. The first collapse freed the
    second face, and reading `.edges` off it raised
    'ReferenceError: BMesh data of type BMFace has been removed'.
    """
    from blended.ops.heal import weld_and_dissolve

    slivers = _mesh_of_adjacent_slivers()
    report = weld_and_dissolve(slivers.name)

    assert report["removed_zero_area_faces"] >= len(BOWTIE_PAIR_FACES)


def test_healing_actually_removes_the_zero_area_faces(empty_scene):
    """Surviving is not enough — the slivers have to be gone, or the
    analyzer will report them and the agent will chase them."""
    from blended.analyze.mesh_checks import ZERO_AREA_EPSILON_M2
    from blended.ops.heal import weld_and_dissolve

    slivers = _mesh_of_adjacent_slivers()
    weld_and_dissolve(slivers.name)

    bpy.context.view_layer.update()
    areas = [polygon.area for polygon in slivers.data.polygons]
    assert all(area >= ZERO_AREA_EPSILON_M2 for area in areas), areas


def test_a_clean_mesh_is_left_alone(empty_scene):
    """Healing is not allowed to invent work on a mesh with no debris."""
    from blended.ops.heal import weld_and_dissolve
    from blended.ops.primitives import add_box, link_into_scene

    box = add_box("CleanBox", 1.0, 1.0, 1.0)
    link_into_scene(box)
    polygon_count_before = len(bpy.data.objects[box].data.polygons)

    report = weld_and_dissolve(box)

    assert report == {"welded_vertices": 0, "removed_zero_area_faces": 0}
    assert len(bpy.data.objects[box].data.polygons) == polygon_count_before


def test_boolean_on_unlinked_objects_refuses_instead_of_lying(empty_scene):
    """The measured iteration-8 collapse.

    `boolean_union` on two unlinked boxes returned normally, left the
    target at 8 vertices — no union had happened — and consumed the
    addend regardless. The agent concluded the op was broken, wiped the
    scene to A/B-test it, and destroyed its finished stool.
    """
    from blended.ops.booleans import UnlinkedOperand, boolean_union
    from blended.ops.primitives import add_box, link_into_scene

    target = add_box("A", 0.2, 0.2, 0.2)
    addend = add_box("B", 0.2, 0.2, 0.2, location_m=(0.1, 0.0, 0.0))

    with pytest.raises(UnlinkedOperand, match="link_into_scene"):
        boolean_union(target, addend)

    # Nothing was consumed: the refusal happens before any mutation, so
    # the agent's scene is exactly as it left it.
    assert "B" in bpy.data.objects
    assert len(bpy.data.objects[target].data.vertices) == 8

    # And the same call works once the objects are where they belong.
    link_into_scene(target)
    link_into_scene(addend)
    boolean_union(target, addend)
    assert len(bpy.data.objects[target].data.vertices) > 8
    assert "B" not in bpy.data.objects
