"""What a camera pixel actually hits — measured, not looked at.

The measured need: a user renders, looks at the picture, and still cannot say
which object a pixel is, or what a 2 cm slot reveals behind it. Each test here
is one of those questions with an answer that can only be right one way:

- the FIRST hit names the object and material, and its normal points back at
  the camera (a reversed normal would light the face from the wrong side);
- a pixel through a SLOT hits what is behind and reports the point as not
  visible, which is the difference between "the wall is there" and "the gap
  shows the wall behind it";
- `hit_layers` reports the far side of a solid box, marked `backface`;
- two runs write byte-identical id maps (a nondeterministic id is not an id);
- nothing in the scene is created or changed, because the op must never move the
  user's viewport.
"""

import hashlib
from pathlib import Path

from golem_blender.ops.view_probe import FRAME_MARGIN_FACTOR

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

CUBE_MINIMUM_M = -0.5
CUBE_MAXIMUM_M = 0.5
SLOT_WIDTH_M = 0.02

WALL_FRONT_Y_M = -0.05
WALL_BACK_Y_M = 0.05


@pytest.fixture()
def empty_scene():
    from golem_blender.ops import assembly, coplanar, pieces

    bpy.ops.wm.read_factory_settings(use_empty=True)
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()
    yield
    assembly._ASSEMBLIES.clear()
    assembly._DECLARED_JOINS.clear()
    assembly._INTERACTION_SIDES.clear()
    pieces._PIECES.clear()
    coplanar._DECLARED_FLUSH.clear()


def _box(name, size_m, location_m=(0.0, 0.0, 0.0), material=None):
    from golem_blender.ops import add_box, assign_material, link_into_scene

    box_name = add_box(name, size_m[0], size_m[1], size_m[2], location_m)
    link_into_scene(box_name)
    if material is not None:
        assign_material(box_name, material)
    return box_name


def test_the_front_pixel_resolves_to_the_front_face(empty_scene):
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5), material="Stone")
    probe = probe_view(["Front"], yaw_deg=0.0, pitch_deg=0.0, pixels=((256, 256),))
    assert len(probe.rays) == 1
    hits = probe.rays[0].hits
    assert hits, "a ray at the middle of the frame must meet the box"
    assert hits[0].object_name == "Front"
    assert hits[0].material_name == "Stone"
    # Facing the camera, which looks towards +Y: the face's normal is -Y.
    assert hits[0].normal[1] == pytest.approx(-1.0, abs=1.0e-6)
    assert hits[0].backface is False
    assert hits[0].distance_m > 0.0


def test_a_twenty_millimetre_slot_reveals_the_surface_behind_it(empty_scene):
    """The measured question: does the 2 cm gap show the room, or the wall?

    Three points, one ray each, through the SAME slot:
      * the middle of the slot itself — nothing there, so the first hit is 1 m
        away, on the surface behind;
      * a point on that surface, dead centre of the slot — visible, because the
        slot is open all the way through;
      * the same surface 0.5 m to the side, behind a wall — not visible.
    A probe that only answered "which object does this pixel hit" could not tell
    the last two apart; they differ only in whether the point IS the first hit.
    """
    from golem_blender.ops import probe_view

    half_gap = SLOT_WIDTH_M / 2.0
    # Two 2 m panels meeting at x = 0 with SLOT_WIDTH_M between them, base at z=0.
    _box("Wall_Left", (2.0, 0.1, 2.0), (-1.0 - half_gap, 0.0, 0.0), material="Stone")
    _box("Wall_Right", (2.0, 0.1, 2.0), (1.0 + half_gap, 0.0, 0.0), material="Stone")
    _box("Behind", (2.0, 0.1, 2.0), (0.0, 1.0, 0.0), material="Stone")

    # Behind is centred at y = 1.0 and 0.1 m thick, so its FRONT face is at 0.95.
    behind_front_y_m = 0.95
    probe = probe_view(
        ["Wall_Left", "Wall_Right", "Behind"],
        yaw_deg=0.0,
        pitch_deg=0.0,
        width_px=512,
        height_px=512,
        points_m=(
            (0.0, 0.0, 1.0),
            (0.0, behind_front_y_m, 1.0),
            (0.5, behind_front_y_m, 1.0),
        ),
    )
    in_the_slot, through_the_slot, behind_a_wall = probe.rays

    # Nothing in the slot: the ray passes through it and meets the far surface.
    assert in_the_slot.hits, "a ray through the slot must meet something"
    assert in_the_slot.hits[0].object_name == "Behind"
    assert in_the_slot.hits[0].distance_m > 1.0
    assert in_the_slot.visible is False

    # The far surface's own face, centred in the slot: visible.
    assert through_the_slot.hits[0].object_name == "Behind"
    assert through_the_slot.visible is True

    # The same surface behind a wall: the wall is what the camera meets.
    assert behind_a_wall.hits[0].object_name == "Wall_Right"
    assert behind_a_wall.visible is False


def test_hit_layers_report_the_far_side_of_a_solid_as_a_backface(empty_scene):
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5), material="Stone")
    probe = probe_view(
        ["Front"], yaw_deg=0.0, pitch_deg=0.0, pixels=((256, 256),), hit_layers=3
    )
    hits = probe.rays[0].hits
    assert len(hits) >= 2, "a ray through a solid box meets its far side too"
    assert hits[0].backface is False
    assert hits[1].backface is True
    assert hits[1].distance_m > hits[0].distance_m


def test_the_id_map_is_deterministic_and_named_in_the_legend(empty_scene, tmp_path):
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5), material="Stone")
    first = probe_view(
        ["Front"],
        yaw_deg=0.0,
        pitch_deg=0.0,
        width_px=200,
        height_px=200,
        write_id_png=True,
        output_dir=str(tmp_path),
    )
    first_bytes = Path(first.id_png).read_bytes()
    second = probe_view(
        ["Front"],
        yaw_deg=0.0,
        pitch_deg=0.0,
        width_px=200,
        height_px=200,
        write_id_png=True,
        output_dir=str(tmp_path),
    )
    assert second.id_png == first.id_png
    assert Path(second.id_png).read_bytes() == first_bytes
    assert hashlib.sha256(first_bytes).hexdigest()
    assert first.legend
    object_name, material_name, colour = first.legend[0]
    assert (object_name, material_name) == ("Front", "Stone")
    assert colour.startswith("#") and len(colour) == 7
    # The whole frame was probed, so the shares cover the object.
    assert first.probed_pixel_count == 200 * 200
    assert first.visible
    assert first.visible[0].object_name == "Front"
    # The default framing is the bounds' diagonal x 1.2, so a 1 m cube covers
    # (1 / 1.2*sqrt(3))^2 = 1/4.32 = 0.23 of the frame's area. The share is the
    # box's own footprint, not the whole frame.
    expected_share = (
        1.0 / (FRAME_MARGIN_FACTOR * 3**0.5)
    ) ** 2  # a 1 m cube in a diagonal x 1.2 frame
    assert first.visible[0].pixel_share == pytest.approx(expected_share, rel=0.02)


def test_a_perspective_camera_object_probes_through_its_own_frustum(empty_scene):
    from mathutils import Vector

    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5), material="Stone")
    camera_data = bpy.data.cameras.new("ProbeCam")
    camera_data.type = "PERSP"
    camera_data.lens = 50.0
    camera = bpy.data.objects.new("ProbeCam", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = Vector((0.0, -5.0, 0.5))
    # Looking down +Y: a camera's own -Z is its view direction, so a rotation of
    # +90 degrees about X turns -Z into +Y.
    camera.rotation_euler = (1.5707963267948966, 0.0, 0.0)
    bpy.context.view_layer.update()

    bpy.context.scene.render.resolution_x = 64
    bpy.context.scene.render.resolution_y = 64
    bpy.context.scene.render.resolution_percentage = 100

    probe = probe_view(
        ["Front"], camera_object_name="ProbeCam", points_m=((0.0, -0.5, 1.0),)
    )
    assert probe.camera == "ProbeCam"
    assert probe.width_px == 64 and probe.height_px == 64
    hits = probe.rays[0].hits
    assert hits
    assert hits[0].object_name == "Front"
    # The point is ON the front face, so through this camera it IS the surface.
    assert probe.rays[0].visible is True


def test_more_pixels_than_the_cap_are_refused(empty_scene):
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5))
    too_many = tuple((index % 8, index // 8) for index in range(65))
    with pytest.raises(ValueError, match="maximum is 64"):
        probe_view(["Front"], pixels=too_many)


def test_a_pixel_outside_the_frame_is_refused(empty_scene):
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5))
    with pytest.raises(ValueError, match="outside the"):
        probe_view(["Front"], width_px=64, height_px=64, pixels=((64, 10),))


def test_a_probe_creates_and_changes_nothing(empty_scene):
    from golem_blender import viewport_follow
    from golem_blender.ops import probe_view

    _box("Front", (1.0, 1.0, 1.0), (0.0, 0.0, 0.5), material="Stone")
    before = (
        len(bpy.data.objects),
        len(bpy.data.meshes),
        len(bpy.data.materials),
        len(bpy.data.cameras),
        len(bpy.data.lights),
        len(bpy.data.images),
    )
    snapshot = viewport_follow.snapshot_scene()
    probe_view(["Front"], pixels=((256, 256),), hit_layers=2)
    probe_view(["Front"], points_m=((0.0, -0.5, 1.0),))
    assert (
        len(bpy.data.objects),
        len(bpy.data.meshes),
        len(bpy.data.materials),
        len(bpy.data.cameras),
        len(bpy.data.lights),
        len(bpy.data.images),
    ) == before
    assert viewport_follow.changed_object_names(snapshot) == ()
