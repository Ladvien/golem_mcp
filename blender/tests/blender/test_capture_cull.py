"""`render_views(cull=True)`: a render that hides back faces, and the measurements that say which flag does it.

The probe here is a plane whose normal points AWAY from the camera. Drawn
double-sided it fills its pixels; culled it fills none — so the count is an
answer, not an opinion, and the control (the same plane turned to face the
camera) proves the switch is not simply blanking the frame.

Measured 2026-10-27 in Blender 5.2, and these tests pin it:

  Workbench: shading.show_backface_culling is what culls
             (an away-facing plane: 1024 px -> 0 px); the material's
             use_backface_culling is ignored (1024 px, unchanged).
  EEVEE:     the material's use_backface_culling is what culls; the
             shading flag is ignored.
  A CLOSED mesh is identical either way — a cube's render arrays compare
  equal — which is where the drift catalog's old "0 changed pixels" came
  from.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

SUBJECT = "Subject"
RESOLUTION_PX = 128
# The plane's share of a 128 px frame when drawn. Measured 2026-10-27:
# 6080 of 16384 pixels (0.371) — the 1 m edge against the capture's own ortho
# scale (2 x the bounding sphere's radius x FRAME_MARGIN_FACTOR = 1.70 m),
# so 1/1.7 of each axis, plus the anti-aliased rim.
EXPECTED_PLANE_FRACTION = 0.371
# And the frame with nothing in it. A culled away-facing plane leaves the
# background and nothing else; the ceiling is exact rather than "small",
# because a single leaked triangle would be a defect worth failing on.
EMPTY_PIXEL_CEILING = 0
# A frame with a few anti-aliased edge pixels still reads as empty.
EMPTY_PIXEL_CEILING = 0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _plane(name: str, normal_towards_camera: bool) -> str:
    """A 1 m plane in the XZ plane at the origin, wound so its normal is ±Y.

    The front view's camera sits on -Y looking towards +Y, so a plane whose
    normal is -Y faces the camera and one at +Y faces away.
    """
    corners = [
        (-0.5, 0.0, -0.5),
        (0.5, 0.0, -0.5),
        (0.5, 0.0, 0.5),
        (-0.5, 0.0, 0.5),
    ]
    if not normal_towards_camera:
        corners = corners[::-1]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(corners, [], [(0, 1, 2, 3)])
    mesh.update()
    plane = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(plane)
    bpy.context.view_layer.update()
    return name


def _subject_pixels(view_path) -> int:
    """Pixels the subject covers, keyed off the frame's own corner background."""
    import numpy

    from golem_blender.capture.compose import load_image_as_array
    from golem_blender.evaluate.visual_diff import _subject_mask

    array = load_image_as_array(view_path)
    background = numpy.median(
        numpy.concatenate(
            [
                array[:8, :8, :3].reshape(-1, 3),
                array[:8, -8:, :3].reshape(-1, 3),
                array[-8:, :8, :3].reshape(-1, 3),
                array[-8:, -8:, :3].reshape(-1, 3),
            ]
        ),
        axis=0,
    )
    return int(_subject_mask(array, background).sum())


def _render(name: str, cull: bool, tmp_path, view: str = "front"):
    from golem_blender.capture import CaptureSettings, capture_views

    settings = CaptureSettings(resolution_px=RESOLUTION_PX, cull_backfaces=cull)
    paths = capture_views(
        bpy.data.objects[name], tmp_path, settings, view_names=(view,)
    )
    return _subject_pixels(paths[view])


def test_a_plane_facing_away_is_hidden_when_culled_and_drawn_when_not(
    tmp_path, empty_scene
):
    _plane(SUBJECT, normal_towards_camera=False)

    double_sided = _render(SUBJECT, cull=False, tmp_path=tmp_path / "off")
    culled = _render(SUBJECT, cull=True, tmp_path=tmp_path / "on")

    fraction = double_sided / (RESOLUTION_PX * RESOLUTION_PX)
    assert fraction == pytest.approx(EXPECTED_PLANE_FRACTION, abs=0.02), (
        f"the double-sided render covers {double_sided} px ({fraction:.3f}); "
        f"the probe is not framing the plane it thinks it is"
    )
    assert culled <= EMPTY_PIXEL_CEILING, (
        f"a plane facing away from the camera still covers {culled} px when "
        f"culling is on: the flags set are not the ones this engine reads"
    )


def test_the_control_plane_facing_the_camera_is_drawn_either_way(tmp_path, empty_scene):
    """Proves the switch hides back faces rather than blanking the frame."""
    _plane(SUBJECT, normal_towards_camera=True)

    double_sided = _render(SUBJECT, cull=False, tmp_path=tmp_path / "off")
    culled = _render(SUBJECT, cull=True, tmp_path=tmp_path / "on")

    assert double_sided > EMPTY_PIXEL_CEILING
    assert culled > EMPTY_PIXEL_CEILING
    assert culled == pytest.approx(double_sided, rel=0.02), (
        f"a front-facing plane changed from {double_sided} to {culled} px "
        f"under culling; the switch is not a back-face test"
    )


def test_a_closed_box_renders_identically_either_way(tmp_path, empty_scene):
    """A cube's back faces are already hidden by its front ones: 0 changed pixels."""
    import numpy

    from golem_blender.capture import CaptureSettings, capture_views
    from golem_blender.capture.compose import load_image_as_array

    from golem_blender.ops.primitives import add_box, link_into_scene

    box = link_into_scene(add_box(SUBJECT, 1.0, 1.0, 1.0))
    blender_object = bpy.data.objects[box]
    without = capture_views(
        blender_object,
        tmp_path / "off",
        CaptureSettings(resolution_px=RESOLUTION_PX, cull_backfaces=False),
        view_names=("front",),
    )
    with_culling = capture_views(
        blender_object,
        tmp_path / "on",
        CaptureSettings(resolution_px=RESOLUTION_PX, cull_backfaces=True),
        view_names=("front",),
    )
    assert numpy.array_equal(
        load_image_as_array(without["front"]),
        load_image_as_array(with_culling["front"]),
    )


def test_the_scene_is_left_as_it_was_found(tmp_path, empty_scene):
    """Every flag the capture set goes back, and no scratch material survives."""
    from golem_blender.capture import CaptureSettings, capture_views
    from golem_blender.capture.views import CAPTURE_CULL_MATERIAL_NAME

    _plane(SUBJECT, normal_towards_camera=False)
    material = bpy.data.materials.new("M_Surface")
    material.use_backface_culling = False
    bpy.data.objects[SUBJECT].data.materials.append(material)
    shading = bpy.context.scene.display.shading
    shading.show_backface_culling = False

    capture_views(
        bpy.data.objects[SUBJECT],
        tmp_path,
        CaptureSettings(resolution_px=RESOLUTION_PX, cull_backfaces=True),
        view_names=("front",),
    )

    assert shading.show_backface_culling is False
    assert material.use_backface_culling is False
    assert bpy.data.materials.get(CAPTURE_CULL_MATERIAL_NAME) is None, (
        "the temporary cull material was left in the file"
    )


def test_a_slotless_mesh_still_culls(tmp_path, empty_scene):
    """A mesh with no material slot has nowhere to carry `use_backface_culling`."""
    from golem_blender.capture.views import CAPTURE_CULL_MATERIAL_NAME

    _plane(SUBJECT, normal_towards_camera=False)
    assert not bpy.data.objects[SUBJECT].data.materials

    culled = _render(SUBJECT, cull=True, tmp_path=tmp_path / "on")

    assert culled <= EMPTY_PIXEL_CEILING
    assert bpy.data.materials.get(CAPTURE_CULL_MATERIAL_NAME) is None
    assert not bpy.data.objects[SUBJECT].data.materials, (
        "the temporary material stayed in the mesh's slots"
    )


def test_render_views_says_culled_or_double_sided(empty_scene, tmp_path):
    """The tool's own text tells the caller which sheet it is looking at."""
    from golem_blender.agent.tools import dispatch_tool

    _plane(SUBJECT, normal_towards_camera=False)
    culled = dispatch_tool(
        "render_views", {"object_name": SUBJECT}, output_directory=tmp_path / "culled"
    )
    double_sided = dispatch_tool(
        "render_views",
        {"object_name": SUBJECT, "cull": False},
        output_directory=tmp_path / "double",
    )

    assert "culled" in culled.text and "double-sided" not in culled.text, culled.text
    assert "double-sided" in double_sided.text, double_sided.text
    # And the words are not the whole claim: the sheets differ by the plane.
    assert culled.images and double_sided.images
