"""Issue #26: an ASSEMBLY is a first-class thing — defined, measured, rendered
and shipped as ONE asset.

Measured need (`Landmark_BlacksmithShop`, Sanctuary, 2026-10-24): a 49-part
building of 19,967 triangles could not be exported at all, because
`export_asset` gates one object as one closed manifold under 2000 triangles —
a description of a prop, not of a building assembled from kit pieces. And
twelve of that session's defects (a bracket 111.9 cm off its wall, a tool board
hung flat, a tuyere pipe through a bellows, two walls 11.10 cm apart) were found
only by looking at a close-up, never by a measurement.

Every acceptance condition below is the issue's own, asserted from measured
numbers — never from the implementation's own claims.
"""

import re
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

# Two parts built identically measure the same count, so the sum is a real
# measurement rather than a literal that the geometry can drift away from.
HUNDRED_TRIANGLES = 100
BOX_TRIANGLES = 12
# A 49-part building of 432-triangle parts is 21,168 triangles — the size the
# issue names ("a 20 000-triangle total") and strictly harder than 20,000.
BUILDING_PART_TRIANGLES = 432
BUILDING_PART_COUNT = 49
POSITION_TOLERANCE_M = 1.0e-4
# Blender stores mesh coordinates as float32, so a 0.1 m overlap reads
# 0.10000002384185791: the tolerance is float32 noise, not sloppiness.
VOLUME_TOLERANCE_M3 = 1.0e-6
# Two walls lapping one wall thickness at a corner: correct joinery.
WALL_LENGTH_M = 4.0
WALL_THICKNESS_M = 0.406
WALL_HEIGHT_M = 2.5
# Two unit boxes overlapping by this much is a 0.1 m3 shared volume.
OVERLAP_M = 0.1
# The frame the focus close-up must be dominated by: more than half of it.
FRAME_DOMINANCE = 0.5
MINIMUM_FOCUS_ANGLES = 3


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


# --- fixture builders (no external asset anywhere) --------------------------


def _link(mesh_data, name, matrix=None):
    box_object = bpy.data.objects.new(name, mesh_data)
    bpy.context.scene.collection.objects.link(box_object)
    if matrix is not None:
        box_object.matrix_world = matrix
    bpy.context.view_layer.update()
    return box_object


def _box(name, minimum_corner_m, maximum_corner_m, subdivisions=0):
    """A closed box between two world corners, each face a `subdivisions` grid."""
    import bmesh
    from mathutils import Vector

    x_minimum, y_minimum, z_minimum = minimum_corner_m
    x_maximum, y_maximum, z_maximum = maximum_corner_m
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        if subdivisions:
            bmesh.ops.subdivide_edges(
                working_mesh,
                edges=list(working_mesh.edges),
                cuts=subdivisions,
                use_grid_fill=True,
            )
        for vertex in working_mesh.verts:
            vertex.co = Vector(
                (
                    (vertex.co.x + 0.5) * (x_maximum - x_minimum) + x_minimum,
                    (vertex.co.y + 0.5) * (y_maximum - y_minimum) + y_minimum,
                    (vertex.co.z + 0.5) * (z_maximum - z_minimum) + z_minimum,
                )
            )
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    return _link(mesh_data, name)


def _box_of_100_triangles(name, minimum_corner_m, maximum_corner_m):
    """A closed box of EXACTLY 100 triangles, so the total can be asserted literally.

    A cube is 12 triangles and a 2x2-per-face grid is 48; poking a quad turns it
    into four triangles (+2), so 24 pokes reach 96 and two more pokes reach 100.
    Poking only adds a centre vertex per face, so the solid stays closed and
    manifold.
    """
    import bmesh
    from mathutils import Vector

    x_minimum, y_minimum, z_minimum = minimum_corner_m
    x_maximum, y_maximum, z_maximum = maximum_corner_m
    mesh_data = bpy.data.meshes.new(name)
    working_mesh = bmesh.new()
    try:
        bmesh.ops.create_cube(working_mesh, size=1.0)
        bmesh.ops.subdivide_edges(
            working_mesh, edges=list(working_mesh.edges), cuts=1, use_grid_fill=True
        )
        for vertex in working_mesh.verts:
            vertex.co = Vector(
                (
                    (vertex.co.x + 0.5) * (x_maximum - x_minimum) + x_minimum,
                    (vertex.co.y + 0.5) * (y_maximum - y_minimum) + y_minimum,
                    (vertex.co.z + 0.5) * (z_maximum - z_minimum) + z_minimum,
                )
            )
        bmesh.ops.poke(working_mesh, faces=list(working_mesh.faces))
        bmesh.ops.poke(working_mesh, faces=list(working_mesh.faces)[:2])
        working_mesh.to_mesh(mesh_data)
    finally:
        working_mesh.free()
    return _link(mesh_data, name)


def _measured_triangles(object_name):
    from golem_blender.analyze.mesh_checks import analyze_object

    return analyze_object(bpy.data.objects[object_name]).triangle_count


def _material(object_name, material_name):
    from golem_blender.ops.materials import assign_material

    return assign_material(object_name, material_name)


def _building_parts_49():
    """A 49-part building: a floor, four walls of three panels, a roof of twelve
    planks and twenty-four crates. Every part is a closed box of
    BUILDING_PART_TRIANGLES; every part stands on the base or on a supported part,
    and no two parts share volume, so the per-part gate and the assembly gate
    both apply without a clash to explain away.
    """
    names = [_box("Floor", (0.0, 0.0, 0.0), (4.0, 4.0, 0.2), subdivisions=5).name]
    for index in range(3):
        names.append(
            _box(
                f"WallNorth{index}",
                (0.05 + index * 1.3, 0.0, 0.2),
                (1.35 + index * 1.3, 0.2, 2.6),
                subdivisions=5,
            ).name
        )
        names.append(
            _box(
                f"WallSouth{index}",
                (0.05 + index * 1.3, 3.8, 0.2),
                (1.35 + index * 1.3, 4.0, 2.6),
                subdivisions=5,
            ).name
        )
        names.append(
            _box(
                f"WallWest{index}",
                (0.0, 0.2 + index * 1.2, 0.2),
                (0.2, 1.4 + index * 1.2, 2.6),
                subdivisions=5,
            ).name
        )
        names.append(
            _box(
                f"WallEast{index}",
                (3.8, 0.2 + index * 1.2, 0.2),
                (4.0, 1.4 + index * 1.2, 2.6),
                subdivisions=5,
            ).name
        )
    # Twelve planks spanning the building's full depth, each resting on the
    # north and south walls' tops at z 2.6: a plank that rests on nothing is
    # `unsupported`, and this fixture must be a building that is not.
    plank_width_m = 4.0 / 12
    for index in range(12):
        x_minimum = index * plank_width_m
        names.append(
            _box(
                f"RoofPlank{index}",
                (x_minimum, 0.0, 2.6),
                (x_minimum + plank_width_m, 4.0, 2.8),
                subdivisions=5,
            ).name
        )
    for column in range(6):
        for row in range(4):
            x_minimum = 0.4 + column * 0.55
            y_minimum = 0.6 + row * 0.7
            names.append(
                _box(
                    f"Crate{column}_{row}",
                    (x_minimum, y_minimum, 0.2),
                    (x_minimum + 0.5, y_minimum + 0.5, 0.7),
                    subdivisions=5,
                ).name
            )
    assert len(names) == BUILDING_PART_COUNT, len(names)
    for name in ("Floor", "WallNorth0", "Crate0_0"):
        _material(name, "KitTimber")
    for name in ("RoofPlank0", "WallWest0"):
        _material(name, "KitShingle")
    return names


def _image_frame_dominance(image_path):
    """(width fraction, height fraction) of the rendered content's bounding box.

    The background is the most common quantized colour in the frame — a
    Workbench render of an empty region is uniform, and the object is not. The
    measurement is the box the rendered objects OCCUPY, which is what
    "the two named objects occupy more than half the frame" asserts.
    """
    import numpy

    loaded_image = bpy.data.images.load(str(image_path))
    try:
        width_px, height_px = loaded_image.size
        flat_pixels = numpy.array(loaded_image.pixels[:], dtype=numpy.float32)
    finally:
        bpy.data.images.remove(loaded_image)
    pixels = flat_pixels.reshape((height_px, width_px, 4))[:, :, :3]
    quantized = (pixels * 32.0).astype(numpy.int16).reshape(-1, 3)
    unique, counts = numpy.unique(quantized, axis=0, return_counts=True)
    background = unique[counts.argmax()]
    differs = (numpy.abs(quantized - background).max(axis=1) > 0).reshape(
        (height_px, width_px)
    )
    rows = numpy.flatnonzero(differs.any(axis=1))
    columns = numpy.flatnonzero(differs.any(axis=0))
    if not len(rows) or not len(columns):
        return 0.0, 0.0
    return (
        (columns[-1] - columns[0] + 1) / width_px,
        (rows[-1] - rows[0] + 1) / height_px,
    )


# --- criterion 1 -----------------------------------------------------------


def test_two_100_triangle_boxes_sum_and_an_unlinked_name_is_reported(empty_scene):
    """Criterion 1: 200 triangles report 200; a name never linked is listed and
    excluded from the total."""
    from golem_blender.ops.assembly import define_assembly

    first = _box_of_100_triangles("Left", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    second = _box_of_100_triangles("Right", (1.0, 0.0, 0.0), (2.0, 1.0, 1.0)).name
    assert _measured_triangles(first) == HUNDRED_TRIANGLES
    assert _measured_triangles(second) == HUNDRED_TRIANGLES

    report = define_assembly("TwoBoxes", [first, second, "Ghost"])

    assert report.triangles_total == 2 * HUNDRED_TRIANGLES
    assert report.unlinked == ("Ghost",)
    assert report.objects == (first, second, "Ghost")


# --- criterion 2 -----------------------------------------------------------


def test_a_part_hanging_in_air_is_floating_and_a_part_on_another_is_not(empty_scene):
    """Criterion 2: a part 1 m above the floor floats; a part resting on another
    does not."""
    from golem_blender.ops.assembly import define_assembly

    floor = _box("Floor", (0.0, 0.0, 0.0), (1.0, 1.0, 0.2)).name
    resting = _box("Resting", (0.1, 0.1, 0.2), (0.9, 0.9, 0.7)).name
    hanging = _box("Hanging", (0.1, 0.1, 1.7), (0.9, 0.9, 2.2)).name

    report = define_assembly("Stack", [floor, resting, hanging])

    assert report.floating == ("Hanging",)
    assert "Resting" not in report.floating
    assert "Floor" not in report.floating
    # A part whose support is itself floating is unsupported but not floating:
    # the distinction is what tells a writer which part to move.
    assert "Resting" not in report.unsupported


# --- criterion 3 -----------------------------------------------------------


def test_overlapping_parts_report_a_volume_and_touching_parts_report_nothing(
    empty_scene,
):
    """Criterion 3: two boxes overlapping 10 cm appear WITH a volume; the same two
    moved face-to-face do not appear at all."""
    from golem_blender.ops.assembly import assembly_report, define_assembly

    first = _box("First", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    second = _box(
        "Second", (1.0 - OVERLAP_M, 0.0, 0.0), (2.0 - OVERLAP_M, 1.0, 1.0)
    ).name
    define_assembly("Overlapping", [first, second])

    report = assembly_report("Overlapping")
    assert len(report.part_intersections) == 1
    intersection = report.part_intersections[0]
    assert (intersection.first_object_name, intersection.second_object_name) == (
        first,
        second,
    )
    assert intersection.overlap_volume_m3 == pytest.approx(
        OVERLAP_M * 1.0 * 1.0, abs=VOLUME_TOLERANCE_M3
    )
    assert intersection.penetration_depth_m == pytest.approx(
        OVERLAP_M, abs=VOLUME_TOLERANCE_M3
    )

    # Face to face: zero depth, so the pair is not reported at all.
    bpy.data.objects[second].location.x += OVERLAP_M
    bpy.context.view_layer.update()
    touching = assembly_report("Overlapping")
    assert touching.part_intersections == ()


# --- criterion 4 -----------------------------------------------------------


def test_a_corner_lap_is_a_lap_and_not_a_clash(empty_scene):
    """Criterion 4: two kit walls lapping one wall thickness at a corner are NOT a
    clash, and the report names them as a lap."""
    from golem_blender.ops.assembly import assembly_report, define_assembly

    north = _box(
        "WallNorth", (0.0, 0.0, 0.0), (WALL_LENGTH_M, WALL_THICKNESS_M, WALL_HEIGHT_M)
    ).name
    west = _box(
        "WallWest",
        (WALL_LENGTH_M - WALL_THICKNESS_M, 0.0, 0.0),
        (WALL_LENGTH_M, WALL_LENGTH_M, WALL_HEIGHT_M),
    ).name
    define_assembly("Corner", [north, west])

    report = assembly_report("Corner")

    assert not [entry for entry in report.part_intersections if entry.kind == "clash"]
    assert (north, west) in report.laps
    assert len(report.part_intersections) == 1
    assert report.part_intersections[0].overlap_volume_m3 == pytest.approx(
        WALL_THICKNESS_M * WALL_THICKNESS_M * WALL_HEIGHT_M, rel=1.0e-6
    )


# --- criteria 5, 6 and the per-part gate ------------------------------------


def test_a_49_part_building_exports_and_its_glb_reimports_whole(empty_scene, tmp_path):
    """Criteria 5 and 6: a 49-part ~20 000-triangle building exports, reports
    keep_parts: 49, and the written .glb re-imports with the same object count,
    triangle total and material names — while the per-part gate still applies."""
    from golem_blender.ops.assembly import define_assembly, export_assembly

    parts = _building_parts_49()
    assembly = define_assembly("BlacksmithShop", parts)
    assert len(assembly.objects) == BUILDING_PART_COUNT
    assert assembly.triangles_total == BUILDING_PART_COUNT * BUILDING_PART_TRIANGLES
    assert assembly.triangles_total >= 20_000
    assert assembly.unlinked == () and assembly.floating == ()
    assert assembly.unsupported == ()

    report = export_assembly(
        assembly.object_name,
        str(tmp_path / "building.glb"),
        str(tmp_path / "building.blend"),
    )

    assert report.passes(), report.round_trip_failures()
    assert report.keep_parts == BUILDING_PART_COUNT
    assert report.part_count == BUILDING_PART_COUNT
    # Criterion 6, measured from the file and from a real re-import.
    assert report.reimported_object_count == BUILDING_PART_COUNT
    assert report.material_names == ("KitShingle", "KitTimber")
    assert report.file_report.triangle_count == assembly.triangles_total
    assert (tmp_path / "building.glb").stat().st_size > 0
    assert (tmp_path / "building.blend").stat().st_size > 0


def test_an_open_part_fails_the_assembly_gate_and_names_itself(empty_scene, tmp_path):
    """Criterion 5's second half: the piece gate still applies to each part."""
    import bmesh

    from golem_blender.ops.assembly import define_assembly, export_assembly

    closed = _box("Closed", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    # An open box: one face deleted, so its edges are boundary edges.
    open_box = _box("Open", (1.0, 0.0, 0.0), (2.0, 1.0, 1.0)).name
    working_mesh = bmesh.new()
    try:
        working_mesh.from_mesh(bpy.data.objects[open_box].data)
        bmesh.ops.delete(
            working_mesh, geom=[next(iter(working_mesh.faces))], context="FACES"
        )
        working_mesh.to_mesh(bpy.data.objects[open_box].data)
    finally:
        working_mesh.free()
    define_assembly("Broken", [closed, open_box])

    report = export_assembly(
        "Broken", str(tmp_path / "broken.glb"), str(tmp_path / "broken.blend")
    )

    assert not report.passes()
    joined = "\n".join(report.round_trip_failures())
    assert "Open" in joined and "piece gate" in joined


# --- criterion 7 -----------------------------------------------------------


def test_a_welded_export_reports_its_own_counts_and_still_writes_the_file(
    empty_scene, tmp_path
):
    """Criterion 7: keep_parts=False reports the welded mesh's component and
    boundary counts truthfully and still writes the file."""
    from golem_blender.ops.assembly import (
        assembly_report,
        define_assembly,
        export_assembly,
    )

    # Six separate boxes with air between them: welding them joins nothing, so
    # the honest counts are six components and no boundary edge.
    parts = [
        _box(
            f"Crate{index}", (index * 0.6, 0.0, 0.0), (index * 0.6 + 0.5, 0.5, 0.5)
        ).name
        for index in range(6)
    ]
    define_assembly("SixCrates", parts)
    before = assembly_report("SixCrates")
    assert before.part_intersections == ()

    report = export_assembly(
        "SixCrates",
        str(tmp_path / "welded.glb"),
        str(tmp_path / "welded.blend"),
        keep_parts=False,
    )

    assert report.passes(), report.round_trip_failures()
    assert report.keep_parts == 1
    assert report.part_count == 6
    assert report.reimported_object_count == 1
    # The welded mesh as measured in the session...
    assert report.pre_export.connected_component_count == 6
    assert report.pre_export.boundary_edge_count == 0
    assert report.pre_export.triangle_count == 6 * BOX_TRIANGLES
    # ...and as re-imported from the file it shipped.
    assert report.reimported_welded.triangle_count == 6 * BOX_TRIANGLES
    assert (tmp_path / "welded.glb").stat().st_size > 0
    assert (tmp_path / "welded.blend").stat().st_size > 0


# --- criterion 8 -----------------------------------------------------------


def test_focus_renders_the_named_pair_where_it_dominates_the_frame(
    empty_scene, tmp_path
):
    """Criterion 8: render_assembly(focus=[a, b]) writes images where the two
    named objects fill more than half the frame, from at least three angles, each
    path naming its pair."""
    from golem_blender.ops.assembly import define_assembly, render_assembly

    wall = _box("Wall", (0.0, 0.0, 0.0), (2.0, 0.4, 2.4)).name
    shelf = _box("Shelf", (0.2, 0.4, 1.2), (1.8, 0.7, 1.25)).name
    define_assembly("Workshop", [wall, shelf])

    paths = render_assembly(
        "Workshop", focus=[wall, shelf], output_dir=str(tmp_path / "renders")
    )

    # The whole-assembly sheet comes first, then one directory per PAIR: the
    # path itself says which junction the image is of, so a reader never has to
    # guess which close-up it is looking at.
    focus_paths = [
        path for path in paths if Path(path).parent.name.startswith("focus_")
    ]
    assert len(focus_paths) >= MINIMUM_FOCUS_ANGLES
    for path in focus_paths:
        assert "Wall" in path and "Shelf" in path, path
        assert re.search(r"\.png$", path), path
    dominated = [
        path
        for path in focus_paths
        if min(_image_frame_dominance(path)) > FRAME_DOMINANCE
    ]
    assert len(dominated) >= MINIMUM_FOCUS_ANGLES, [
        (path, _image_frame_dominance(path)) for path in focus_paths
    ]


def test_the_whole_assembly_sheet_frames_every_part(empty_scene, tmp_path):
    """The assembly sheet is what the contact sheet could never be: one frame that
    holds all of it."""
    from golem_blender.ops.assembly import define_assembly, render_assembly

    parts = [
        _box(
            f"Panel{index}", (index * 1.0, 0.0, 0.0), (index * 1.0 + 0.8, 0.3, 1.5)
        ).name
        for index in range(3)
    ]
    define_assembly("Row", parts)

    paths = render_assembly(
        "Row", views=["front", "three_quarter"], output_dir=str(tmp_path)
    )

    assert len(paths) == 2
    for path in paths:
        width_fraction, _height_fraction = _image_frame_dominance(path)
        assert width_fraction > FRAME_DOMINANCE, path
    with pytest.raises(ValueError, match="unknown view"):
        render_assembly("Row", views=["nowhere"], output_dir=str(tmp_path))


# --- criterion 9 and the documented edge cases -----------------------------


def test_assembly_report_changes_nothing(empty_scene):
    """Criterion 9: assembly_report is read-only."""
    from golem_blender.ops.assembly import assembly_report, define_assembly

    parts = [
        _box("Base", (0.0, 0.0, 0.0), (1.0, 1.0, 0.2)).name,
        _box("Lid", (0.1, 0.1, 0.2), (0.9, 0.9, 0.4)).name,
    ]
    _material(parts[0], "ReadOnlyWood")
    define_assembly("Crate", parts)

    def snapshot():
        names = sorted(bpy.data.objects.keys())
        return (
            names,
            {
                name: [
                    round(value, 9)
                    for row in bpy.data.objects[name].matrix_world
                    for value in row
                ]
                for name in names
            },
            {
                name: sorted(
                    material.name
                    for material in bpy.data.objects[name].data.materials
                    if material is not None
                )
                if bpy.data.objects[name].type == "MESH"
                else []
                for name in names
            },
            len(bpy.data.materials),
            {name: len(bpy.data.objects[name].data.polygons) for name in names},
        )

    before = snapshot()
    assembly_report("Crate")
    assert snapshot() == before


def test_a_part_listed_twice_fails_loudly(empty_scene):
    from golem_blender.ops.assembly import define_assembly

    box = _box("Once", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    with pytest.raises(ValueError, match="twice"):
        define_assembly("Doubled", [box, box])


def test_a_part_removed_after_definition_is_reported_not_silently_dropped(
    empty_scene,
):
    from golem_blender.ops.assembly import assembly_report, define_assembly
    from golem_blender.ops.primitives import remove_object_and_mesh

    kept = _box("Kept", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    doomed = _box("Doomed", (1.0, 0.0, 0.0), (2.0, 1.0, 1.0)).name
    first = define_assembly("Vanishing", [kept, doomed])
    assert first.triangles_total == 2 * BOX_TRIANGLES

    remove_object_and_mesh(doomed)
    after = assembly_report("Vanishing")

    assert after.unlinked == ("Doomed",)
    assert after.triangles_total == BOX_TRIANGLES
    assert after.objects == (kept, doomed)


def test_two_assemblies_sharing_pieces_report_their_own_totals(empty_scene):
    from golem_blender.ops.assembly import define_assembly

    shared = _box("Shared", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)).name
    extra_a = _box("ExtraA", (1.0, 0.0, 0.0), (2.0, 1.0, 1.0)).name

    first = define_assembly("First", [shared, extra_a])
    second = define_assembly("Second", [shared])

    assert first.triangles_total == 2 * BOX_TRIANGLES
    assert second.triangles_total == BOX_TRIANGLES


def test_definition_honours_the_pivot(empty_scene):
    """The issue's gate: the pivot is honoured and lowest_point_m is 0."""
    from golem_blender.ops.assembly import define_assembly

    _box("A", (1.0, 2.0, 0.5), (2.0, 3.0, 1.5))
    _box("B", (2.0, 3.0, 0.5), (3.0, 4.0, 1.5))

    report = define_assembly("Pivoted", ["A", "B"])

    assert report.lowest_point_m == pytest.approx(0.0, abs=POSITION_TOLERANCE_M)
    from golem_blender.ops.transforms import _world_bounds_m

    minimum, maximum = _world_bounds_m([bpy.data.objects["A"], bpy.data.objects["B"]])
    assert (minimum[0] + maximum[0]) / 2.0 == pytest.approx(
        0.0, abs=POSITION_TOLERANCE_M
    )
    assert (minimum[1] + maximum[1]) / 2.0 == pytest.approx(
        0.0, abs=POSITION_TOLERANCE_M
    )


def test_an_unknown_assembly_is_refused_by_name(empty_scene):
    from golem_blender.ops.assembly import assembly_report

    with pytest.raises(KeyError, match="no assembly named"):
        assembly_report("Nothing")
