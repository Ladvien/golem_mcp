"""The fixture zoo: each seeded defect trips its own check.

A gate that cannot fail is not a gate. Every analyzer check gets a
fixture that constructs its defect deliberately, plus the shared clean
control (the crate) proving the checks stay quiet on healthy geometry.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _join_into_one_mesh(name, *source_objects):
    """The classic mistake: merge meshes into one datablock, no union."""
    import bmesh

    from blended.ops.primitives import remove_object_and_mesh

    remove_object_and_mesh(name)
    joined_mesh = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        for source_object in source_objects:
            working_mesh.from_mesh(source_object.data)
        working_mesh.to_mesh(joined_mesh)
    finally:
        working_mesh.free()
    joined_object = bpy.data.objects.new(name, joined_mesh)
    bpy.context.scene.collection.objects.link(joined_object)
    for source_object in source_objects:
        remove_object_and_mesh(source_object.name)
    return joined_object


def test_clean_control_trips_nothing(empty_scene):
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import CrateBuilder, CrateParameters

    report = analyze_object(CrateBuilder(CrateParameters()).build())
    assert report.failures(MeshBudget()) == []
    assert report.self_intersecting_face_pair_count == 0


def test_joined_overlap_trips_self_intersection_and_components(empty_scene):
    from blended.analyze import analyze_object
    from blended.ops import add_box, link_into_scene

    first_box = bpy.data.objects[add_box("JoinA", 1.0, 1.0, 1.0)]
    link_into_scene(first_box.name)
    second_box = bpy.data.objects[
        add_box("JoinB", 1.0, 1.0, 1.0, location_m=(0.5, 0.3, 0.2))
    ]
    link_into_scene(second_box.name)
    joined_object = _join_into_one_mesh("JoinedOverlap", first_box, second_box)

    report = analyze_object(joined_object)
    assert report.self_intersecting_face_pair_count > 0
    assert report.connected_component_count == 2


def test_coincident_join_trips_duplicate_vertices(empty_scene):
    from blended.analyze import analyze_object
    from blended.ops import add_box, link_into_scene

    first_box = bpy.data.objects[add_box("CoinA", 1.0, 1.0, 1.0)]
    link_into_scene(first_box.name)
    second_box = bpy.data.objects[add_box("CoinB", 1.0, 1.0, 1.0)]  # identical position
    link_into_scene(second_box.name)
    joined_object = _join_into_one_mesh("CoincidentJoin", first_box, second_box)

    report = analyze_object(joined_object)
    assert report.duplicate_vertex_pair_count > 0


def test_degenerate_face_trips_zero_area(empty_scene):
    import bmesh

    from blended.analyze import analyze_object

    degenerate_mesh = bpy.data.meshes.new("Degenerate")
    working_mesh = bmesh.new()
    try:
        # Three collinear vertices: a face with zero area.
        collinear_vertices = [
            working_mesh.verts.new((0.0, 0.0, 0.0)),
            working_mesh.verts.new((0.5, 0.0, 0.0)),
            working_mesh.verts.new((1.0, 0.0, 0.0)),
        ]
        working_mesh.faces.new(collinear_vertices)
        working_mesh.to_mesh(degenerate_mesh)
    finally:
        working_mesh.free()
    degenerate_object = bpy.data.objects.new("Degenerate", degenerate_mesh)
    bpy.context.scene.collection.objects.link(degenerate_object)

    report = analyze_object(degenerate_object)
    assert report.zero_area_face_count > 0


def test_union_beats_join_on_the_same_barrel(empty_scene):
    """Same silhouette, different verdicts: the gate sees what a render
    cannot. The unioned barrel passes; the naive join fails on both
    self-intersection and component count."""
    from blended.analyze import MeshBudget, analyze_object
    from blended.builders import BarrelBuilder, BarrelParameters
    from blended.builders.barrel import HOOP_POSITION_FRACTIONS
    from blended.ops import add_cylinder, link_into_scene
    from blended.ops.lathe import add_lathe

    parameters = BarrelParameters(name="UnionBarrel")
    unioned_barrel = BarrelBuilder(parameters).build()
    union_report = analyze_object(unioned_barrel)
    assert union_report.failures(MeshBudget()) == []

    profile = [
        (
            parameters.radius_at_height(
                ring_index / parameters.ring_count * parameters.height_m
            ),
            ring_index / parameters.ring_count * parameters.height_m,
        )
        for ring_index in range(parameters.ring_count + 1)
    ]
    naive_body_name = add_lathe("NaiveBody", profile, parameters.segment_count)
    link_into_scene(naive_body_name)
    naive_parts = [bpy.data.objects[naive_body_name]]
    for hoop_index, height_fraction in enumerate(HOOP_POSITION_FRACTIONS):
        hoop_center_z_m = parameters.height_m * height_fraction
        hoop_name = add_cylinder(
            f"NaiveHoop{hoop_index}",
            radius_m=parameters.radius_at_height(hoop_center_z_m)
            + parameters.hoop_protrusion_m,
            height_m=parameters.hoop_height_m,
            segment_count=parameters.segment_count,
            location_m=(
                0.0,
                0.0,
                hoop_center_z_m - parameters.hoop_height_m / 2.0,
            ),
        )
        link_into_scene(hoop_name)
        naive_parts.append(bpy.data.objects[hoop_name])
    naive_barrel = _join_into_one_mesh("NaiveBarrel", *naive_parts)

    naive_report = analyze_object(naive_barrel)
    naive_failures = naive_report.failures(MeshBudget())
    assert naive_report.self_intersecting_face_pair_count > 0
    assert naive_report.connected_component_count == 3
    assert naive_failures != []
