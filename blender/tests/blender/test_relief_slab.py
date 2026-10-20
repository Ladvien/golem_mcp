"""The relief slab: the mesh a PBR set is baked from.

Its job is to make the baked maps line up with the texture, so the
tests are about ALIGNMENT and about the solid being sound — the
solidify route produced an inside-out shell, and an open or inverted
mesh bakes nothing useful.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

# A cobblestone-like albedo: pale stones with a mid-grey mortar.
#
# The mortar is MID grey, not near-black, because the test measures
# how much the occlusion DARKENS the joints, and a joint that is
# already black has no room to be darkened. A real cobblestone's
# mortar is pale sand, and the stones are the pale part.
STONE_RGB = 0.72
JOINT_RGB = 0.45


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _write_cobble_albedo(path, cell_count=8):
    """Write a PNG whose dark lines are the joints of a grid of stones."""
    size = cell_count * 16
    image = bpy.data.images.new(path.stem, size, size, alpha=False)
    pixels = []
    for row in range(size):
        for column in range(size):
            on_joint = row % 16 < 3 or column % 16 < 3
            value = JOINT_RGB if on_joint else STONE_RGB
            pixels.extend((value, value, value, 1.0))
    image.pixels = pixels
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)
    return path


def test_the_slab_is_a_sound_solid(empty_scene, tmp_path):
    """No flipped normals, no self-intersections, no open edges."""
    from golem_blender.analyze.mesh_checks import MeshBudget, analyze_object
    from golem_blender.ops.relief import add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png")
    name = add_relief_slab(
        "Street", albedo_path, size_m=2.0, thickness_m=0.06, cell_count=32
    )

    report = analyze_object(
        bpy.data.objects[name], MeshBudget(maximum_triangle_count=100_000)
    )

    assert report.flipped_normal_triangle_count == 0
    assert report.self_intersecting_face_pair_count == 0
    assert report.boundary_edge_count == 0
    assert report.non_manifold_edge_count == 0
    assert report.connected_component_count == 1
    assert report.failures(MeshBudget(maximum_triangle_count=100_000)) == []


def test_the_slab_joins_the_view_layer(empty_scene, tmp_path):
    """An object outside the view layer is invisible to a render."""
    from golem_blender.ops.relief import add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png")
    name = add_relief_slab("Street", albedo_path, cell_count=16)

    assert name in bpy.context.view_layer.objects


def test_the_slab_carries_uvs_over_the_whole_atlas(empty_scene, tmp_path):
    """The UVs have to span 0..1, or the texture is squeezed into a sliver."""
    from golem_blender.ops.relief import add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png")
    name = add_relief_slab("Street", albedo_path, cell_count=16)

    uv_layer = bpy.data.objects[name].data.uv_layers.active
    uvs = [uv_layer.data[index].uv for index in range(len(uv_layer.data))]
    assert min(uv[0] for uv in uvs) == 0.0
    assert max(uv[0] for uv in uvs) == pytest.approx(1.0, abs=1e-5)
    assert min(uv[1] for uv in uvs) == 0.0
    assert max(uv[1] for uv in uvs) == pytest.approx(1.0, abs=1e-5)


def test_the_relief_is_derived_from_the_albedo(empty_scene, tmp_path):
    """The joints of the relief are the joints of the texture.

    That is the whole point: the baked maps' joints have to land on
    the texture's mortar lines, and that only happens if the height
    field comes from the same image.
    """
    from golem_blender.ops.relief import add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png", cell_count=8)
    name = add_relief_slab("Street", albedo_path, cell_count=32)

    slab = bpy.data.objects[name]
    # The top faces sit at two heights: the stone tops and the joints.
    top_z = {
        slab.data.vertices[index].co.z
        for polygon in slab.data.polygons
        if polygon.normal.z > 0.5
        for index in polygon.vertices
    }
    assert len({round(z, 4) for z in top_z}) > 1, "the slab has no relief"


def test_the_orm_is_what_makes_the_relief_read(empty_scene, tmp_path):
    """The ORM's AO channel must DARKEN THE JOINTS.

    This is the acceptance bar for the whole lane: a texture set that
    looks like a painted floor is not usable on a street, however good
    the albedo is.

    The measure is the JOINT DARKNESS, not the global spread. The AO
    multiplies the base colour, so it darkens the joints — and it
    compresses the overall range a little, so a global standard
    deviation can fall even while the joints get darker. Measured on a
    cobblestone slab, the render's darkest decile got DARKER with the
    ORM while its overall spread stayed within a few percent.
    """
    import numpy

    from golem_blender.ops.pbr_bake import bake_orm_map
    from golem_blender.ops.relief import add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png", cell_count=16)
    # A joint 100 mm deep on a 2 m slab at 64 cells. The occlusion needs
    # a CREVICE and a crevice is a physical size: measured, a joint
    # 20 mm deep left 0.00% of the surface dark, 50 mm left 0.12% and
    # 100 mm left 5.66%. The slab is 200 mm thick so the joint is a
    # groove in it rather than a hole through it.
    name = add_relief_slab(
        "Street",
        albedo_path,
        size_m=2.0,
        thickness_m=0.2,
        cell_count=64,
        depth_m=0.1,
    )
    slab = bpy.data.objects[name]

    bpy.ops.object.select_all(action="DESELECT")
    slab.select_set(True)
    bpy.context.view_layer.objects.active = slab
    bpy.ops.object.shade_smooth()
    bpy.context.view_layer.update()

    orm_path = bake_orm_map(
        name,
        tmp_path / "orm.png",
        resolution_px=256,
        ao_distance_m=0.06,
        roughness=0.85,
    )

    def darkest_decile():
        """The darkest tenth of the SLAB's own baked occlusion.

        Measured on the ORM rather than on a render: the render's
        framing changes with the slab's size, so a crop of it is
        measuring the camera as much as the asset. The ORM is the
        thing the relief is supposed to reach, and it is the same
        number the shader multiplies the base colour by.
        """
        image = bpy.data.images.load(str(orm_path))
        pixels = numpy.empty(len(image.pixels), dtype=numpy.float32)
        image.pixels.foreach_get(pixels)
        occlusion = pixels.reshape((-1, 4))[:, 0]
        ordered = numpy.sort(occlusion)
        return float(ordered[: len(ordered) // 10].mean())

    # The occlusion must actually DARKEN: a crevice the occlusion
    # cannot see is a crevice the shader will not draw.
    with_orm = darkest_decile()

    assert with_orm < 0.5, (
        f"the occlusion's darkest tenth is {with_orm:.4f}: the joint is not "
        f"a crevice the occlusion can find, so the relief does not read"
    )


def test_a_missing_albedo_is_refused(empty_scene, tmp_path):
    from golem_blender.ops.relief import add_relief_slab

    with pytest.raises(FileNotFoundError):
        add_relief_slab("Street", tmp_path / "absent.png")


def test_a_cell_count_over_the_cap_is_refused(empty_scene, tmp_path):
    """The cap is the gate's cost, measured: a 256-cell slab made a
    scene-changing call take 41.8 s and wedged the live Blender."""
    from golem_blender.ops.relief import MAXIMUM_CELL_COUNT, add_relief_slab

    albedo_path = _write_cobble_albedo(tmp_path / "cobble.png")
    with pytest.raises(ValueError, match="cells"):
        add_relief_slab("Street", albedo_path, cell_count=MAXIMUM_CELL_COUNT + 1)


def test_a_procedural_source_builds_a_slab_with_no_image_to_read(empty_scene, tmp_path):
    """The relief can be COMPUTED, not photographed.

    This is the module's theme taken all the way: the height field
    comes from Blender's own nodes, so the surface needs no texture
    to derive its joints from.
    """
    from golem_blender.ops.relief import add_relief_slab

    albedo = tmp_path / "albedo.png"
    _write_cobble_albedo(albedo)

    name = add_relief_slab(
        "Procedural",
        albedo,
        size_m=2.0,
        thickness_m=0.09,
        cell_count=64,
        depth_m=0.06,
        source="voronoi",
    )
    slab = bpy.data.objects[name]

    assert len(slab.data.vertices) > 0
    assert slab.data.uv_layers, "the slab has no UV layer to bake against"
    # The relief is not flat: a slab with no joints would bake nothing.
    heights = {round(vertex.co.z, 6) for vertex in slab.data.vertices}
    assert len(heights) > 1, "the procedural slab is flat"


def test_a_procedural_height_field_is_periodic(empty_scene, tmp_path):
    """The procedural field's edge meets its own edge exactly.

    An image-sourced field cannot do this: it is sampled from a
    texture without wrapping, so its last row is the texture's last
    row and its first is the texture's first. A procedural field is
    read on a WRAPPED domain, so it repeats exactly - which is what
    makes the maps baked from it tile.

    The threshold is the measurement's: the Voronoi field's seam is
    0.0083x the interior's largest steps and an albedo-derived
    field's is 0.1604x, so anything under 0.05x is a field that
    repeats rather than one that nearly repeats.

    The albedo-derived field is the CONTROL, and it is in this test
    on purpose: it is the field the lane used before, sampled from a
    texture without wrapping, and it does NOT repeat. Without it
    beside, a threshold of "under 0.5x" would have passed a field
    that is three times worse than the one it replaced.
    """
    import numpy

    from golem_blender.ops.relief import _joint_response, _procedural_height_field

    def seam_ratio(field):
        seam = float(numpy.abs(field[-1] - field[0]).mean())
        inner = numpy.abs(field[:-1] - field[1:])
        baseline = float(numpy.percentile(inner, 95))
        return seam / baseline if baseline else float("inf")

    field, _peak = _procedural_height_field("voronoi", 128, 0.0)
    procedural_ratio = seam_ratio(field)
    assert procedural_ratio < 0.05, (
        f"the procedural field's seam is {procedural_ratio:.3f}x the interior's "
        f"largest steps, so it is not periodic"
    )

    # The control: the field the lane used before, which is sampled
    # from a texture without wrapping and does not repeat.
    albedo = tmp_path / "albedo.png"
    _write_cobble_albedo(albedo)
    image_field, _peak = _joint_response(albedo, 128)
    assert seam_ratio(image_field) > procedural_ratio * 4, (
        "the albedo-derived field is not measurably worse than the "
        "procedural one, so the comparison says nothing"
    )
    # A regression: if the procedural field stops repeating, this
    # catches it, because the two would converge.
    assert procedural_ratio < seam_ratio(image_field) / 4


def test_an_unknown_procedural_source_is_refused(empty_scene, tmp_path):
    """A misspelled source names itself rather than building nothing."""
    from golem_blender.ops.relief import add_relief_slab

    albedo = tmp_path / "albedo.png"
    _write_cobble_albedo(albedo)

    with pytest.raises(ValueError, match="Unknown relief source"):
        add_relief_slab("Bad", albedo, size_m=2.0, cell_count=64, source="voronoii")


def test_the_slab_records_where_its_relief_came_from(empty_scene, tmp_path):
    """The slab says which source it used.

    A procedural height field is PERIODIC and an albedo-derived one
    is not, so the maps baked from them tile differently - and the
    slab's GEOMETRY cannot say which it is, because the two are the
    same shape of thing. So the slab records it, and the report reads
    it back.
    """
    from golem_blender.ops.relief import add_relief_slab, relief_slab_report

    albedo = tmp_path / "albedo.png"
    _write_cobble_albedo(albedo)

    add_relief_slab("FromAlbedo", albedo, size_m=2.0, cell_count=64)
    report = relief_slab_report("FromAlbedo")
    assert report.height_source == "albedo"

    add_relief_slab("Procedural", albedo, size_m=2.0, cell_count=64, source="voronoi")
    report = relief_slab_report("Procedural")
    assert report.height_source == "voronoi", (
        f"the report says the height field came from {report.height_source!r}, "
        f"not from the procedural pattern"
    )
    assert report.source_scale_cells > 0.0
