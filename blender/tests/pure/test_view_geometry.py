"""The view angle convention, pinned against the game's own camera list.

The one thing this module can get wrong silently is a sign: a direction
reported in the wrong frame says a face is visible from the side it actually
faces away from, and no other test in the suite would notice. So the
authority is not restated here — it is the game's own `camera_directions`,
imported from the Sanctuary checkout and mapped glTF -> Blender, exactly as
the module's docstring claims. If that file is not on this machine the
comparison is skipped loudly rather than quietly weakened; the rest of the
file still guards the convention on its own (yaw 0 is the -Y side, yaw 90 the
+X side, pitch 90 straight down).
"""

import math
import sys
from pathlib import Path

import pytest

from golem_blender.analyze.view_geometry import (
    ISO_PITCH_DEG,
    ISO_YAWS_DEG,
    TOP_VIEW_LABEL,
    view_direction,
    view_label,
)

SANCTUARY_TOOLS = Path.home() / "sanctuary" / "tools" / "blended"
ANGLES_TOLERANCE = 1e-9


def _sanctuary_directions():
    """The game's own camera directions, or a skip."""
    if not (SANCTUARY_TOOLS / "assemblies.py").is_file():
        pytest.skip(f"{SANCTUARY_TOOLS / 'assemblies.py'} is not on this machine")
    sys.path.insert(0, str(SANCTUARY_TOOLS))
    try:
        import assemblies
    finally:
        sys.path.pop(0)
    return assemblies.camera_directions()


def _gltf_to_blender(vector):
    """glTF (Y up, -Z forward) -> Blender (Z up, +Y forward)."""
    x, y, z = vector
    return (x, -z, y)


def test_the_eight_yaws_are_the_games_own_camera_directions():
    directions = _sanctuary_directions()
    assert len(directions) == len(ISO_YAWS_DEG) + 1
    for index, yaw_deg in enumerate(ISO_YAWS_DEG):
        expected = _gltf_to_blender(directions[index + 1])
        actual = view_direction(yaw_deg, ISO_PITCH_DEG)
        for axis in range(3):
            assert actual[axis] == pytest.approx(
                expected[axis], abs=ANGLES_TOLERANCE
            ), f"yaw {yaw_deg} axis {axis}: {actual} vs the game's {expected}"


def test_the_top_view_is_straight_up():
    assert TOP_VIEW_LABEL == "top"
    assert view_direction(0.0, 90.0) == pytest.approx((0.0, 0.0, 1.0))


def test_yaw_zero_faces_the_front_and_ninety_the_right():
    front = view_direction(0.0, 0.0)
    right = view_direction(90.0, 0.0)
    assert front == pytest.approx((0.0, -1.0, 0.0))
    assert right == pytest.approx((1.0, 0.0, 0.0))


@pytest.mark.parametrize("yaw_deg", ISO_YAWS_DEG)
@pytest.mark.parametrize("pitch_deg", (0.0, ISO_PITCH_DEG, 60.0, 90.0))
def test_every_direction_is_a_unit_vector(yaw_deg, pitch_deg):
    x, y, z = view_direction(yaw_deg, pitch_deg)
    assert math.sqrt(x * x + y * y + z * z) == pytest.approx(1.0)


def test_the_label_says_the_yaw():
    assert view_label(45.0) == "yaw_45"
    assert view_label(0.0) == "yaw_0"


# --- the orthographic camera (phase 3) ---------------------------------------


def _camera(yaw_deg, pitch_deg, width_px=512, height_px=512, frame_width_m=2.0):
    from golem_blender.analyze.view_geometry import OrthoCamera

    return OrthoCamera(
        target_m=(0.0, 0.0, 0.0),
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        frame_width_m=frame_width_m,
        width_px=width_px,
        height_px=height_px,
    )


@pytest.mark.parametrize(
    ("yaw_deg", "pitch_deg"), [(0.0, 0.0), (45.0, ISO_PITCH_DEG), (300.0, 80.0)]
)
@pytest.mark.parametrize(("px", "py"), [(0, 0), (256, 256), (511, 511), (100, 300)])
def test_a_pixels_ray_projects_back_to_that_pixel(yaw_deg, pitch_deg, px, py):
    """The exact inverse: a ray's origin projects to its own pixel's centre."""
    from golem_blender.analyze.view_geometry import ortho_pixel_ray, ortho_project

    camera = _camera(yaw_deg, pitch_deg)
    origin, _direction = ortho_pixel_ray(camera, px, py, 2.0)
    projected = ortho_project(camera, origin)
    assert projected[0] == pytest.approx(px + 0.5, abs=1e-9)
    assert projected[1] == pytest.approx(py + 0.5, abs=1e-9)


def test_yaw_zero_pitch_zero_looks_along_plus_y():
    """The camera stands on the -Y side, so its rays travel towards +Y."""
    from golem_blender.analyze.view_geometry import ortho_pixel_ray

    camera = _camera(0.0, 0.0)
    origin, direction = ortho_pixel_ray(camera, 256, 256, 2.0)
    assert direction == pytest.approx((0.0, 1.0, 0.0))
    # Behind the target by back_off_m, so the target plane is 2 m in front.
    assert origin[1] == pytest.approx(-2.0)


def test_the_frame_height_follows_the_pixel_aspect():
    camera = _camera(0.0, 0.0, width_px=512, height_px=256, frame_width_m=4.0)
    assert camera.frame_height_m == pytest.approx(2.0)


def test_a_top_view_keeps_world_x_to_the_right():
    from golem_blender.analyze.view_geometry import ortho_pixel_ray

    camera = _camera(0.0, 90.0)
    assert camera.right == pytest.approx((1.0, 0.0, 0.0))
    _origin, direction = ortho_pixel_ray(camera, 256, 256, 1.0)
    assert direction == pytest.approx((0.0, 0.0, -1.0))


def test_the_frame_is_right_handed_and_orthogonal():
    camera = _camera(37.0, 20.0)
    forward, right, up = camera.forward, camera.right, camera.up

    def dot(first, second):
        return sum(first[axis] * second[axis] for axis in range(3))

    assert dot(forward, right) == pytest.approx(0.0)
    assert dot(forward, up) == pytest.approx(0.0)
    assert dot(right, up) == pytest.approx(0.0)
    for vector in (forward, right, up):
        assert dot(vector, vector) == pytest.approx(1.0)
