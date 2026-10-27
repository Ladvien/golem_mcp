"""`fit_garment`: a TRELLIS-like open garment is turned, scaled, draped, weighted, bound and measured in one call.

The body is skinclip's tube humanoid via `import_rigged_glb`. The garment is a
stand-in for what TRELLIS produces: an open elliptical tube 1 m tall at the
origin, wider one way than the other (sized below so that the height-driven
scale gives a tunic this body can wear), with its wide axis PERPENDICULAR to
the body band's — read off the body in the test with the module's own
`horizontal_extents`, so the quarter turn is exercised whichever way the
humanoid's arms point.

What each test defends:
  - the band is the caller's two heights above the body's lowest point, to
    1e-4 m; the garment is turned; the rest pose clears the body by the
    standoff (less a millimetre); every vertex is weighted;
  - an inside-out garment comes back turned the right way round (one
    component reversed) and passes the facing check;
  - pleats change the silhouette at 200 px against the same fit without;
  - `thickness_m` closes the rim: no boundary edges and no flipped normals;
  - an unrigged body, an inverted band and a fold count with no depth are each
    refused before anything moves.
"""

import math

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

FRAMES_PER_SECOND = 30
BODY = "body"
GARMENT = "Tunic"
PLAIN = "TunicPlain"
GARMENT_HEIGHT_M = 1.0
# The stand-in's elliptical section. TRELLIS keeps a garment's true aspect and
# `place_garment` scales on HEIGHT, so the section must be the garment's own
# girth per metre of its height: a 0.35 m band scales it by 0.35, and the
# result has to clear a pelvis 0.28 m across and two thighs 0.32 m across
# (measured 2026-10-27 on the tube humanoid). The plan's 0.30 x 0.20 m section
# scaled to 0.105 x 0.07 m — a tube a third the body's width — and the drape
# crumpled it (608 of 2496 triangles flipped after a solidify, measured).
# 1.15 x 0.95 m scales to 0.40 x 0.33 m, which is a tunic on this body.
GARMENT_WIDE_M = 1.15
GARMENT_NARROW_M = 0.95
GARMENT_AROUND = 48
GARMENT_RINGS = 12
# The tube humanoid's chest: spine 1.03-1.434 m above its lowest point at
# -0.036 m (measured 2026-10-27). A band of 0.6-0.95 m above the lowest point
# runs from the thighs to the pelvis, where the torso is a single tube and a
# garment's clearance is one number rather than two legs'.
HEM_HEIGHT_M = 0.6
COLLAR_HEIGHT_M = 0.95
STANDOFF_M = 0.006
# A millimetre under the standoff: the drape holds the garment `offset_m` off
# the NEAREST surface point, and a vertex between two body triangles reads a
# fraction of a millimetre less against the other one.
STANDOFF_TOLERANCE_M = 0.001
FOLD_COUNT = 8
FOLD_DEPTH_M = 0.02
THICKNESS_M = 0.01
SILHOUETTE_HEIGHT_PX = 200


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FRAMES_PER_SECOND
    bpy.context.scene.render.fps_base = 1.0
    yield


def _import_body(tmp_path):
    from skinclip.testing import tube_humanoid

    from golem_blender.ops.assets import import_rigged_glb

    path = tmp_path / "body.glb"
    tube_humanoid(path, "ue5", "thigh_swing")
    return import_rigged_glb(str(path), BODY)


def _body_mesh_name() -> str:
    return next(
        scene_object.name
        for scene_object in bpy.data.objects
        if scene_object.type == "MESH" and scene_object.name.startswith(f"{BODY}_")
    )


def _body_wide_axis() -> int:
    """The body band's wide horizontal axis, read off the body with the module's own measure."""
    import numpy as np

    from golem_blender.analyze.garment_placement import horizontal_extents
    from golem_blender.ops.transforms import _world_bounds_m

    body = bpy.data.objects[_body_mesh_name()]
    armature = bpy.data.objects[BODY]
    previous = armature.data.pose_position
    armature.data.pose_position = "REST"
    try:
        bpy.context.view_layer.update()
        minimum, _ = _world_bounds_m([body])
        evaluated = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = evaluated.to_mesh()
        try:
            points = np.array(
                [tuple(body.matrix_world @ vertex.co) for vertex in mesh.vertices]
            )
        finally:
            evaluated.to_mesh_clear()
    finally:
        armature.data.pose_position = previous
    return horizontal_extents(
        points, minimum[2] + HEM_HEIGHT_M, minimum[2] + COLLAR_HEIGHT_M
    ).wide_axis


def _garment(name: str, wide_axis: int, reversed_faces: bool = False) -> str:
    """An open elliptical tube, 1 m tall at the origin, wide along `wide_axis`."""
    import bmesh

    half_x = (GARMENT_WIDE_M if wide_axis == 0 else GARMENT_NARROW_M) / 2.0
    half_y = (GARMENT_NARROW_M if wide_axis == 0 else GARMENT_WIDE_M) / 2.0
    vertices = [
        (
            half_x * math.cos(2 * math.pi * k / GARMENT_AROUND),
            half_y * math.sin(2 * math.pi * k / GARMENT_AROUND),
            GARMENT_HEIGHT_M * ring / GARMENT_RINGS,
        )
        for ring in range(GARMENT_RINGS + 1)
        for k in range(GARMENT_AROUND)
    ]
    faces = [
        (
            ring * GARMENT_AROUND + k,
            ring * GARMENT_AROUND + (k + 1) % GARMENT_AROUND,
            (ring + 1) * GARMENT_AROUND + (k + 1) % GARMENT_AROUND,
            (ring + 1) * GARMENT_AROUND + k,
        )
        for ring in range(GARMENT_RINGS)
        for k in range(GARMENT_AROUND)
    ]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    if reversed_faces:
        working = bmesh.new()
        try:
            working.from_mesh(mesh)
            bmesh.ops.reverse_faces(working, faces=list(working.faces))
            working.to_mesh(mesh)
        finally:
            working.free()
        mesh.update()
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(name, mesh))
    bpy.context.view_layer.update()
    return name


def _perpendicular_garment(name: str, reversed_faces: bool = False) -> str:
    """The stand-in, wide across the body's NARROW axis so the fit must turn it."""
    wide = _body_wide_axis()
    return _garment(name, 1 - wide, reversed_faces=reversed_faces)


def _lowest_z() -> float:
    from golem_blender.ops.transforms import _world_bounds_m

    armature = bpy.data.objects[BODY]
    previous = armature.data.pose_position
    armature.data.pose_position = "REST"
    try:
        bpy.context.view_layer.update()
        minimum, _ = _world_bounds_m([bpy.data.objects[_body_mesh_name()]])
    finally:
        armature.data.pose_position = previous
    return minimum[2]


def test_a_garment_is_turned_banded_draped_weighted_and_clear_at_rest(
    tmp_path, empty_scene
):
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    _perpendicular_garment(GARMENT)
    lowest = _lowest_z()
    report = fit_garment(
        GARMENT,
        _body_mesh_name(),
        hem_height_m=HEM_HEIGHT_M,
        collar_height_m=COLLAR_HEIGHT_M,
        offset_m=STANDOFF_M,
    )

    assert report.band_m[0] == pytest.approx(lowest + HEM_HEIGHT_M, abs=1e-4)
    assert report.band_m[1] == pytest.approx(lowest + COLLAR_HEIGHT_M, abs=1e-4)
    assert report.quarter_turn is True
    rest = report.clearance.clips[0]
    assert rest.action_name == ""
    assert rest.worst_clearance_m >= STANDOFF_M - STANDOFF_TOLERANCE_M, (
        f"the rest pose clears the body by {rest.worst_clearance_m:.4f} m; the "
        f"drape asked for {STANDOFF_M} m"
    )
    garment = bpy.data.objects[GARMENT]
    assert report.weights.vertices_weighted == len(garment.data.vertices)
    assert any(modifier.type == "ARMATURE" for modifier in garment.modifiers)
    assert report.clearance.garment_inward_area_fraction <= 0.02


def test_an_inside_out_garment_is_reversed_and_then_faces_out(tmp_path, empty_scene):
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    _perpendicular_garment(GARMENT, reversed_faces=True)
    report = fit_garment(
        GARMENT,
        _body_mesh_name(),
        hem_height_m=HEM_HEIGHT_M,
        collar_height_m=COLLAR_HEIGHT_M,
    )

    assert report.components_reversed == 1
    assert report.clearance.garment_inward_area_fraction <= 0.02


def test_pleats_change_the_silhouette_at_200_px(tmp_path, empty_scene):
    from golem_blender.ops.garments import fit_garment
    from golem_blender.ops.silhouette import silhouette_test

    _import_body(tmp_path)
    _perpendicular_garment(PLAIN)
    _perpendicular_garment(GARMENT)
    fit_garment(
        PLAIN,
        _body_mesh_name(),
        hem_height_m=HEM_HEIGHT_M,
        collar_height_m=COLLAR_HEIGHT_M,
    )
    pleated = fit_garment(
        GARMENT,
        _body_mesh_name(),
        hem_height_m=HEM_HEIGHT_M,
        collar_height_m=COLLAR_HEIGHT_M,
        fold_count=FOLD_COUNT,
        fold_depth_m=FOLD_DEPTH_M,
    )
    assert pleated.fold_count == FOLD_COUNT

    # Both fitted garments follow the body's rest pose, so compare them there.
    armature = bpy.data.objects[BODY]
    armature.data.pose_position = "REST"
    bpy.context.view_layer.update()
    report = silhouette_test(
        GARMENT,
        PLAIN,
        height_px=SILHOUETTE_HEIGHT_PX,
        yaws_deg=(0.0, 90.0),
        pitch_deg=0.0,
    )
    assert report.changes_silhouette is True


def test_a_thickness_closes_the_rim(tmp_path, empty_scene):
    from golem_blender.analyze import analyze_object
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    _perpendicular_garment(GARMENT)
    report = fit_garment(
        GARMENT,
        _body_mesh_name(),
        hem_height_m=HEM_HEIGHT_M,
        collar_height_m=COLLAR_HEIGHT_M,
        thickness_m=THICKNESS_M,
    )
    assert report.thickness_m == THICKNESS_M

    armature = bpy.data.objects[BODY]
    armature.data.pose_position = "REST"
    bpy.context.view_layer.update()
    measured = analyze_object(bpy.data.objects[GARMENT])
    assert measured.boundary_edge_count == 0, (
        f"{measured.boundary_edge_count} boundary edges after a "
        f"{THICKNESS_M} m solidify: the rim was not closed"
    )
    assert measured.flipped_normal_triangle_count == 0


def test_an_unrigged_body_is_refused(empty_scene):
    from golem_blender.ops.garments import fit_garment
    from golem_blender.ops.primitives import add_box, link_into_scene

    link_into_scene(add_box("plain_body", 0.4, 0.3, 1.8))
    _garment(GARMENT, 0)
    with pytest.raises(ValueError, match="body is not rigged"):
        fit_garment(GARMENT, "plain_body", hem_height_m=0.6, collar_height_m=0.95)


def test_a_band_upside_down_is_refused(tmp_path, empty_scene):
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    _garment(GARMENT, 0)
    with pytest.raises(ValueError, match="must be above hem_height_m"):
        fit_garment(GARMENT, _body_mesh_name(), hem_height_m=0.95, collar_height_m=0.95)


def test_a_fold_count_with_no_depth_is_refused(tmp_path, empty_scene):
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    _garment(GARMENT, 0)
    with pytest.raises(ValueError, match="both be set or both be 0"):
        fit_garment(
            GARMENT,
            _body_mesh_name(),
            hem_height_m=HEM_HEIGHT_M,
            collar_height_m=COLLAR_HEIGHT_M,
            fold_count=3,
            fold_depth_m=0.0,
        )


def test_a_garment_too_thin_for_the_body_is_refused_by_girth_and_left_untouched(
    tmp_path, empty_scene
):
    """The plan's original 0.30 x 0.20 m stand-in: scaled on height it is a third of the body's width.

    The drape folds it onto the body and the facing check refuses it — and the
    refusal must say WHY (girth, not winding: a lathe-built tube is wound one
    way throughout) and leave the garment as it was handed over, so the
    retry starts from the source and not from a half-fitted copy.
    """
    from golem_blender.ops.garments import fit_garment

    _import_body(tmp_path)
    wide = _body_wide_axis()
    thin = "ThinTunic"
    half_wide, half_narrow = 0.15, 0.10
    vertices = [
        (
            (half_wide if wide == 0 else half_narrow)
            * math.cos(2 * math.pi * k / GARMENT_AROUND),
            (half_narrow if wide == 0 else half_wide)
            * math.sin(2 * math.pi * k / GARMENT_AROUND),
            GARMENT_HEIGHT_M * ring / GARMENT_RINGS,
        )
        for ring in range(GARMENT_RINGS + 1)
        for k in range(GARMENT_AROUND)
    ]
    faces = [
        (
            ring * GARMENT_AROUND + k,
            ring * GARMENT_AROUND + (k + 1) % GARMENT_AROUND,
            (ring + 1) * GARMENT_AROUND + (k + 1) % GARMENT_AROUND,
            (ring + 1) * GARMENT_AROUND + k,
        )
        for ring in range(GARMENT_RINGS)
        for k in range(GARMENT_AROUND)
    ]
    mesh = bpy.data.meshes.new(thin)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    bpy.context.scene.collection.objects.link(bpy.data.objects.new(thin, mesh))
    bpy.context.view_layer.update()
    before = [tuple(vertex.co) for vertex in bpy.data.objects[thin].data.vertices]
    meshes_before = len(bpy.data.meshes)

    with pytest.raises(
        ValueError, match="body band, so the drape folded it onto the body"
    ):
        fit_garment(
            thin,
            _body_mesh_name(),
            hem_height_m=HEM_HEIGHT_M,
            collar_height_m=COLLAR_HEIGHT_M,
        )

    garment = bpy.data.objects[thin]
    after = [tuple(vertex.co) for vertex in garment.data.vertices]
    assert after == before, "the refused fit left the garment moved"
    assert not garment.modifiers
    assert not garment.vertex_groups
    assert garment.parent is None
    assert garment.data.name == thin
    assert len(bpy.data.meshes) == meshes_before, (
        "the refused fit left a mesh copy behind"
    )
