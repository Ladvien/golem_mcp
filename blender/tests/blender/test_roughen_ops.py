"""Issue #20: a seeded roughen, so a stone is not a smooth primitive.

`roughen_object` exists because every prop that must read as HAND-MADE —
Prop_SpringBasin, Prop_AnimalPen, Prop_Effigy, Prop_CaveDrape in the
Sanctuary run of 2026-10-24 — was a hand-written vertex loop in
`run_python` with a local `random.Random(71)`: not reproducible, not
reviewable, and not answerable by a parameter. The acceptance conditions
below are the issue's own, each MEASURED rather than asserted from the
implementation.

The last test is the one the issue spells out and the unit tests cannot
reach: two FRESH Blender launches, under different `PYTHONHASHSEED`, must
produce byte-identical coordinates — the same comparison
`scripts/rebuild_twice.py` makes for the builders, and for the same
reason (a per-process hash seed, a seeded RNG surviving an import, or a
set iterated into geometry all pass a same-process rerun).
"""

import json
import math
import os
import subprocess
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
# The child needs the venv's `skinclip`, which the facade's motion module
# imports; numpy stays Blender's own (see CHILD_SCRIPT).
VENV_SITE_PACKAGES_GLOB = (
    REPOSITORY_ROOT / ".venv" / "lib" / "python3.*" / "site-packages"
)

AMPLITUDE_M = 0.02
# A 20% band around `amplitude_m`, which is the issue's own tolerance for
# the RMS radial error.
RMS_RELATIVE_TOLERANCE = 0.20
# The floor's tolerance: a clamped vertex is placed at exactly z=0 in world
# space and the arithmetic leaves microns. Anything past this is a miss.
FLOOR_TOLERANCE_M = 1.0e-3
DIGEST_MARKER = "ROUGHEN_DIGEST "
CHILD_TIMEOUT_S = 300


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _linked_cylinder(name="Stone", radius_m=0.5, height_m=1.0, segment_count=12):
    from golem_blender.ops.primitives import add_cylinder, link_into_scene

    cylinder_name = add_cylinder(name, radius_m, height_m, segment_count)
    link_into_scene(cylinder_name)
    return cylinder_name


def _coordinates(object_name):
    """Every vertex's local coordinates, exactly as stored (float32)."""
    mesh = bpy.data.objects[object_name].data
    return [tuple(vertex.co) for vertex in mesh.vertices]


def _local_to_world(object_name, coordinates):
    import numpy

    bpy.context.view_layer.update()
    matrix = numpy.array(
        bpy.data.objects[object_name].matrix_world, dtype=numpy.float64
    )
    local = numpy.asarray(coordinates, dtype=numpy.float64)
    return local @ matrix[:3, :3].T + matrix[:3, 3]


def _radial_errors(coordinates):
    """Each vertex's distance from the object's own Z axis, after the move."""
    return [math.hypot(x, y) for x, y, _ in coordinates]


def _sheet_with_a_duplicated_seam(name="Seam"):
    """Two quads sharing a seam whose vertices are DUPLICATED, not shared.

    The shape a glTF import and a boolean seam both leave behind: the
    surface looks welded and its two halves are separate vertices at the
    same coordinates. A per-INDEX displacement hash splits it.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    coordinates = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
        # The seam, duplicated: the same two places as vertices 1 and 2.
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (2.0, 0.0, 0.0),
        (2.0, 1.0, 0.0),
    ]
    faces = [(0, 1, 2, 3), (4, 5, 7, 6)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(coordinates, [], faces)
    mesh.update()
    sheet = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(sheet)
    bpy.context.view_layer.update()
    return sheet.name


def _analyzed(object_name):
    from golem_blender.analyze.mesh_checks import analyze_object

    bpy.context.view_layer.update()
    return analyze_object(bpy.data.objects[object_name])


# --- condition 1: same inputs, same coordinates ---------------------------


def test_two_calls_with_the_same_amplitude_frequency_and_seed_agree(empty_scene):
    """Condition 1. Two identical meshes, two calls, one set of coordinates."""
    from golem_blender.ops.roughen import roughen_object

    first = _linked_cylinder("First")
    second = _linked_cylinder("Second")
    first_report = roughen_object(first, AMPLITUDE_M, 2.0, 11, "radial")
    roughen_object(second, AMPLITUDE_M, 2.0, 11, "radial")

    assert _coordinates(first) == _coordinates(second)
    assert first_report.vertices_moved == len(_coordinates(first))
    assert first_report.seed == 11


# --- condition 2: a different seed is a different surface -----------------


def test_a_different_seed_moves_the_vertices_somewhere_else(empty_scene):
    """Condition 2a. Same mesh, same amplitude, seed 3 against seed 4."""
    from golem_blender.ops.roughen import roughen_object

    first = _linked_cylinder("First")
    second = _linked_cylinder("Second")
    roughen_object(first, AMPLITUDE_M, 2.0, 3, "radial")
    roughen_object(second, AMPLITUDE_M, 2.0, 4, "radial")

    assert _coordinates(first) != _coordinates(second)


def test_the_rms_radial_error_is_the_requested_amplitude(empty_scene):
    """Condition 2b. `amplitude_m` is the RMS the surface actually moves.

    Measured on the finished vertices against the ideal surface (a
    cylinder's own radius), not read back from the report.
    """
    from golem_blender.ops.roughen import roughen_object

    ideal_radius_m = 0.5
    cylinder = _linked_cylinder("Stone", radius_m=ideal_radius_m)
    report = roughen_object(cylinder, AMPLITUDE_M, 2.0, 21, "radial")

    radii = _radial_errors(_coordinates(cylinder))
    radial_errors = [abs(radius - ideal_radius_m) for radius in radii]
    rms = math.sqrt(sum(error * error for error in radial_errors) / len(radial_errors))

    assert rms == pytest.approx(AMPLITUDE_M, rel=RMS_RELATIVE_TOLERANCE), (
        f"RMS radial error {rms:.6f} m is not within "
        f"{RMS_RELATIVE_TOLERANCE:.0%} of amplitude_m={AMPLITUDE_M} m"
    )
    assert report.rms_displacement_m == pytest.approx(rms, rel=0.02)


# --- condition 3: nothing goes below the floor ----------------------------


def test_a_radial_roughen_on_a_grounded_piece_keeps_its_base(empty_scene):
    """Condition 3. The issue's own case: cube, base at 0, mode radial."""
    from golem_blender.ops.primitives import add_box, link_into_scene
    from golem_blender.ops.roughen import roughen_object

    box_name = add_box("Basin", 1.0, 1.0, 1.0, (0.0, 0.0, 0.0))
    link_into_scene(box_name)
    report = roughen_object(box_name, AMPLITUDE_M, 2.0, 5, "radial")

    world = _local_to_world(box_name, _coordinates(box_name))
    lowest_z_m = float(min(point[2] for point in world))
    assert abs(lowest_z_m) <= FLOOR_TOLERANCE_M, (
        f"the base moved to z={lowest_z_m:.6f} m, past the "
        f"{FLOOR_TOLERANCE_M} m tolerance"
    )
    assert report.vertices_moved > 0


def test_the_clamp_lifts_a_vertex_the_displacement_pushed_under_the_floor(
    empty_scene,
):
    """Condition 3's real case: a mode whose displacement has a Z component.

    `radial` cannot push a vertex below the floor on an upright piece —
    it only moves it in X/Y — so the clamp has to be proven with `z`,
    where it does happen. The slab's bottom face sits exactly at z=0.
    """
    from golem_blender.ops.primitives import add_box, link_into_scene
    from golem_blender.ops.roughen import roughen_object

    slab_name = add_box("Slab", 1.0, 1.0, 0.2, (0.0, 0.0, 0.0))
    link_into_scene(slab_name)
    unclamped_report = roughen_object(
        slab_name, AMPLITUDE_M, 2.0, 5, "z", clamp_to_ground=False
    )
    assert unclamped_report.clamped_vertex_count == 0
    unclamped_world = _local_to_world(slab_name, _coordinates(slab_name))
    assert min(point[2] for point in unclamped_world) < -FLOOR_TOLERANCE_M, (
        "the measurement cannot fail: without the clamp something has to go "
        "under the floor, or the clamp is not what keeps it up"
    )

    clamped_name = add_box("Clamped", 1.0, 1.0, 0.2, (0.0, 0.0, 0.0))
    link_into_scene(clamped_name)
    clamped_report = roughen_object(clamped_name, AMPLITUDE_M, 2.0, 5, "z")

    clamped_world = _local_to_world(clamped_name, _coordinates(clamped_name))
    assert clamped_report.clamped_vertex_count > 0
    assert min(point[2] for point in clamped_world) >= -FLOOR_TOLERANCE_M


def test_the_clamp_works_in_world_space_on_a_moved_and_rotated_object(empty_scene):
    """The floor is z=0 of the SCENE, so the clamp has to use the transform.

    A pure local-Z clamp would put the vertices on the object's own base
    plane, which is a different place once the object is turned or
    lifted. This piece is turned 90 degrees about X, so its local Y is
    the world Z: a local-Z clamp lands 1 m away from the floor.
    """
    import math

    from golem_blender.ops.primitives import add_box, link_into_scene
    from golem_blender.ops.roughen import roughen_object

    slab_name = add_box("Tilted", 1.0, 0.2, 1.0, (0.0, 0.0, 0.0))
    link_into_scene(slab_name)
    bpy.data.objects[slab_name].rotation_euler = (math.radians(90.0), 0.0, 0.0)
    bpy.context.view_layer.update()

    report = roughen_object(slab_name, AMPLITUDE_M, 2.0, 9, "normal")

    world = _local_to_world(slab_name, _coordinates(slab_name))
    assert report.clamped_vertex_count > 0
    assert min(point[2] for point in world) >= -FLOOR_TOLERANCE_M


# --- condition 4: a welded mesh stays welded ------------------------------


def test_coincident_vertices_move_together_so_a_seam_stays_welded(empty_scene):
    """Condition 4. Two coincident boundary vertices are one place, still."""
    from golem_blender.ops.roughen import roughen_object

    sheet_name = _sheet_with_a_duplicated_seam()
    before = _analyzed(sheet_name)
    assert before.duplicate_vertex_pair_count == 2, (
        "the fixture has to carry the seam it is here to test"
    )
    assert before.boundary_edge_count == 8

    roughen_object(sheet_name, AMPLITUDE_M, 2.0, 6, "normal", clamp_to_ground=False)

    after = _analyzed(sheet_name)
    coordinates = _coordinates(sheet_name)
    assert coordinates[1] == coordinates[4], (
        "the seam's duplicated vertices were pushed apart: the displacement "
        "hash is keyed on the vertex INDEX, not its position"
    )
    assert coordinates[2] == coordinates[5]
    assert after.duplicate_vertex_pair_count == before.duplicate_vertex_pair_count
    assert after.boundary_edge_count == before.boundary_edge_count
    assert after.non_manifold_edge_count == before.non_manifold_edge_count
    assert coordinates[0] != (0.0, 0.0, 0.0), "the mesh has to have moved"


# --- condition 5: amplitude 0 is a no-op ----------------------------------


def test_an_amplitude_of_zero_moves_no_vertex(empty_scene):
    """Condition 5. The op reports zero and the coordinates are untouched."""
    from golem_blender.ops.roughen import roughen_object

    cylinder = _linked_cylinder("Stone")
    before = _coordinates(cylinder)
    report = roughen_object(cylinder, 0.0, 2.0, 17, "radial")

    assert report.vertices_moved == 0
    assert report.max_displacement_m == 0.0
    assert report.rms_displacement_m == 0.0
    assert report.clamped_vertex_count == 0
    assert _coordinates(cylinder) == before


# --- condition 6: a face-inverting amplitude is refused, loudly -----------


def test_an_amplitude_that_folds_a_face_is_refused_with_the_mesh_unchanged(
    empty_scene,
):
    """Condition 6. The inversion is reported, not silently produced.

    A displacement larger than the piece's own radius pushes a vertex
    through the axis and turns the faces beside it inside out, so this is
    an inversion by construction rather than by luck: the rim is 50 mm out
    and the field asks for 200 mm.
    """
    from golem_blender.ops.roughen import FaceInversion, roughen_object

    cylinder = _linked_cylinder("Thin", radius_m=0.05, height_m=1.0, segment_count=12)
    before = _coordinates(cylinder)
    with pytest.raises(FaceInversion) as raised:
        roughen_object(cylinder, 0.2, 1.0, 2, "radial")

    message = str(raised.value)
    assert "would invert" in message and "seed=2" in message
    assert _coordinates(cylinder) == before, "the coordinates were not restored"

    # And the same mesh at an amplitude it can take is not refused, so the
    # refusal is about this geometry and not about the op refusing anything
    # past a fixed size.
    report = roughen_object(cylinder, 0.005, 1.0, 2, "radial")
    assert report.inverted_face_count == 0
    assert report.vertices_moved > 0
    radii = _radial_errors(_coordinates(cylinder))
    assert max(abs(radius - 0.05) for radius in radii) <= 0.005 * 8.0 + 1e-6


# --- the report measures world metres, not local ones ---------------------


def test_the_report_measures_world_displacement_on_a_scaled_object(empty_scene):
    """A 2x-scaled object moves its vertices twice as far in the scene."""
    from golem_blender.ops.roughen import roughen_object

    cylinder = _linked_cylinder("Scaled")
    bpy.data.objects[cylinder].scale = (2.0, 2.0, 2.0)
    bpy.context.view_layer.update()

    report = roughen_object(cylinder, AMPLITUDE_M, 2.0, 13, "radial")

    assert report.max_displacement_m >= report.rms_displacement_m > AMPLITUDE_M
    assert report.rms_displacement_m == pytest.approx(
        2.0 * AMPLITUDE_M, rel=RMS_RELATIVE_TOLERANCE
    )


# --- determinism across two fresh Blender launches ------------------------

# The child builds, roughens, and prints a hash of the stored coordinates.
# `repr` of a Python float round-trips exactly, so the comparison is
# byte-exact rather than a tolerance.
CHILD_SCRIPT = """
import glob
import hashlib
import sys

sys.path.insert(0, {source_root!r})
# The dev venv's site-packages, APPENDED rather than inserted: `skinclip`
# (the facade's motion module imports it) lives only there, and numpy must
# stay BLENDER's own — the venv's numpy is built for another interpreter
# and would shadow the bundled copy at sys.path[0].
sys.path.append(sorted(glob.glob({site_packages_glob!r}))[-1])

from golem_blender.ops.primitives import add_cylinder, link_into_scene
from golem_blender.ops.roughen import roughen_object
from golem_blender.reset import reset_scene

reset_scene()
name = add_cylinder("Stone", 0.5, 1.0, 16)
link_into_scene(name)
report = roughen_object(name, 0.02, 3.0, 29, "radial")

import bpy

mesh = bpy.data.objects[name].data
coordinates = [tuple(round(coordinate, 12) for coordinate in vertex.co) for vertex in mesh.vertices]
print(
    {marker!r}
    + hashlib.sha256(repr(coordinates).encode("utf-8")).hexdigest()
    + " "
    + repr(len(coordinates))
    + " "
    + repr(report.vertices_moved)
)
"""

HASH_SEEDS = ("0", "1")


def _blender_binary():
    """The binary that can be launched again, or None (bpy-as-a-module)."""
    binary = getattr(bpy.app, "binary_path", "") or ""
    return binary if os.path.isfile(binary) else None


def _digest_in_a_fresh_blender(binary, script_path, hash_seed):
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = hash_seed
    # --python-use-system-env is what makes PYTHONHASHSEED reach CPython at
    # all (bpy_interface.cc initialises an isolated config by default and
    # each launch then gets a random seed), so the two launches differ in
    # exactly the variable this test is about.
    completed = subprocess.run(
        [
            binary,
            "--background",
            "--factory-startup",
            "--python-use-system-env",
            "--python",
            str(script_path),
        ],
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_S,
        env=environment,
        cwd=str(REPOSITORY_ROOT),
        check=False,
    )
    marked = [
        line for line in completed.stdout.splitlines() if line.startswith(DIGEST_MARKER)
    ]
    assert completed.returncode == 0 and marked, (
        f"the child Blender (PYTHONHASHSEED={hash_seed}) exited "
        f"{completed.returncode} without a digest.\n"
        f"--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    digest, vertex_count, vertices_moved = marked[-1][len(DIGEST_MARKER) :].split()
    return {
        "digest": digest,
        "vertex_count": int(vertex_count),
        "vertices_moved": int(vertices_moved),
    }


def test_the_same_seed_gives_the_same_coordinates_in_two_fresh_blenders(tmp_path):
    """Two launches, two hash seeds, one set of coordinates.

    The in-session tests above cannot see a per-process hash seed, a module
    cached from an earlier test, or a set iterated into geometry; this can,
    which is why `scripts/rebuild_twice.py` is the pin for the builders and
    this is the pin for the roughen.
    """
    binary = _blender_binary()
    if binary is None:
        pytest.skip("no Blender binary to launch (bpy is installed as a module)")

    script_path = tmp_path / "roughen_digest.py"
    script_path.write_text(
        CHILD_SCRIPT.format(
            source_root=str(SOURCE_ROOT),
            site_packages_glob=str(VENV_SITE_PACKAGES_GLOB),
            marker=DIGEST_MARKER,
        ),
        encoding="utf-8",
    )
    readings = [
        _digest_in_a_fresh_blender(binary, script_path, hash_seed)
        for hash_seed in HASH_SEEDS
    ]

    first, second = readings
    assert first["vertex_count"] == 32, "the child built a 16-segment cylinder"
    assert first["vertices_moved"] == 32
    assert first["digest"] == second["digest"], (
        f"the same (amplitude, frequency, seed) produced different coordinates "
        f"in two fresh Blenders: {json.dumps(readings)}"
    )
