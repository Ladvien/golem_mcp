"""Issue #17: several objects are one named piece, measured as one asset.

Sanctuary's convention — and golem's own output encourages it — is one
object per material named `<Piece>__<Material>`, so an asset is a SET and
every number the deliverable is judged on (triangles, extents, the lowest
point) belonged to no op. During the 22-piece run the triangle count the
asset was judged on had to be recomputed outside golem by a script that
opened the written `.glb` files.

The acceptance conditions below are the issue's own, each measured rather
than asserted from the implementation: the standalone triangle count each
total is compared against is the analyzer's own reading of the same object.
"""

import dataclasses

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

# A snap that lands the lowest point within a micrometre of zero.
LOWEST_POINT_TOLERANCE_M = 1.0e-6
PIECE_LIFTED_M = 0.5


@pytest.fixture()
def empty_scene():
    """A clean scene AND a clean piece registry: the registry is session
    state, so a name left over from another test would answer for it."""
    from golem_blender.ops import pieces

    bpy.ops.wm.read_factory_settings(use_empty=True)
    pieces._PIECES.clear()
    yield
    pieces._PIECES.clear()


def _piece_box(name, material_name, location_m=(0.0, 0.0, 0.0)):
    from golem_blender.ops import add_box, assign_material, link_into_scene

    box_name = add_box(name, 1.0, 1.0, 1.0, location_m)
    link_into_scene(box_name)
    assign_material(box_name, material_name, (0.6, 0.4, 0.2))
    return box_name


def _standalone_triangles(object_name) -> int:
    """The analyzer's own count for one object, which is what the piece's
    total must agree with — not a number this test computed itself."""
    from golem_blender.analyze import analyze_object

    return analyze_object(bpy.data.objects[object_name]).triangle_count


def _lowest_world_z(object_name) -> float:
    """The object's lowest point in WORLD space.

    The box constructor puts its geometry at `location_m[2]` and leaves the
    object's own `.location` at zero, so an assertion on `.location.z`
    measures the wrong thing — the first version of these tests did exactly
    that and read -0.5 for a box that had been grounded correctly.
    """
    from golem_blender.ops.transforms import _world_bounds_m

    return _world_bounds_m([bpy.data.objects[object_name]])[0][2]


def _what_the_file_holds(blend_path):
    """Open the written .blend as a linked library and report its contents."""
    from pathlib import Path

    with bpy.data.libraries.load(str(blend_path), link=True) as (data_from, data_to):
        held = {
            "objects": sorted(data_from.objects),
            "materials": sorted(data_from.materials),
        }
        data_to.objects = list(data_from.objects)
    library = next(
        candidate
        for candidate in bpy.data.libraries
        if Path(bpy.path.abspath(candidate.filepath)).resolve()
        == Path(blend_path).resolve()
    )
    held["material_slots"] = {
        linked.name: [
            slot.material.name if slot.material else None
            for slot in linked.material_slots
        ]
        for linked in bpy.data.objects
        if linked.library == library
    }
    bpy.data.libraries.remove(library)
    return held


# --- 1. the total is the parts' own counts ---------------------------------


def test_a_piece_total_is_the_sum_of_its_parts_standalone_counts(empty_scene):
    """Condition 1."""
    from golem_blender.ops import define_piece

    first = _piece_box("A__mat1", "PieceWood")
    second = _piece_box("A__mat2", "PieceClay")

    report = define_piece("X", [first, second])

    parts_total = _standalone_triangles(first) + _standalone_triangles(second)
    assert report.triangles_total == parts_total
    assert report.object_name == "X"
    assert report.objects == (first, second)
    assert {part.name: part.triangles for part in report.parts} == {
        first: _standalone_triangles(first),
        second: _standalone_triangles(second),
    }
    # The same number the analyzer gives, read through the tool surface too.
    assert report.triangles_total == sum(
        _standalone_triangles(name) for name in (first, second)
    )


def test_the_piece_report_measures_the_whole_set_not_one_part(empty_scene):
    """A second part placed 3 m away moves the piece's extents, so the
    report's dimensions are the JOINT box and not the first object's."""
    from golem_blender.ops import define_piece

    first = _piece_box("Span__mat1", "PieceWood")
    second = _piece_box("Span__mat2", "PieceClay", (3.0, 0.0, 0.0))

    report = define_piece("Span", [first, second])

    assert report.dimensions_m[0] == pytest.approx(4.0)
    assert report.dimensions_m[2] == pytest.approx(1.0)
    assert report.lowest_point_m == pytest.approx(0.0)


def test_a_non_mesh_member_contributes_no_geometry_or_triangles(empty_scene):
    """A rigged piece holds its armature beside its meshes. The armature has
    no mesh, so its box is not the asset's shape: a report that included it
    would drag a floating piece's lowest point to wherever the armature sits
    (at the origin, for an unplaced one) and read a grounded asset as
    floating-or-not at random."""
    from golem_blender.ops import BoneSpec, add_armature, define_piece, piece_report

    body = _piece_box("Rigged__mat1", "PieceWood", (0.0, 0.0, 2.0))
    armature_name = add_armature(
        "Rigged__rig",
        (BoneSpec("root", (0.0, 0.0, 0.0), (0.0, 0.0, 0.5)),),
    )
    define_piece("Rigged", [body, armature_name])

    report = piece_report("Rigged")

    assert report.lowest_point_m == pytest.approx(2.0)
    assert report.triangles_total == _standalone_triangles(body)
    part_by_name = {part.name: part for part in report.parts}
    assert part_by_name[armature_name].triangles == 0
    assert part_by_name[armature_name].material_names == ()


def test_snapping_a_piece_with_no_mesh_is_refused(empty_scene):
    from golem_blender.ops import (
        BoneSpec,
        add_armature,
        define_piece,
        snap_base_to_ground,
    )

    armature_name = add_armature(
        "Bare__rig",
        (BoneSpec("root", (0.0, 0.0, 1.0), (0.0, 0.0, 1.5)),),
    )
    define_piece("Bare", [armature_name])

    with pytest.raises(ValueError, match="no mesh members"):
        snap_base_to_ground(piece="Bare")


# --- 2. a removed member is loud, never a smaller total --------------------


def test_a_removed_member_makes_every_read_loud_and_is_repairable(empty_scene):
    """Condition 2: the error names the piece AND the object, and the piece is
    repairable — `define_piece` is the only way to say the set changed, so
    refusing it would leave a broken piece unfixable for the rest of the
    session."""
    from pathlib import Path

    from golem_blender.export import BlendSaveError, save_blend
    from golem_blender.ops import (
        define_piece,
        piece_report,
        remove_object_and_mesh,
        snap_base_to_ground,
    )
    from golem_blender.ops.pieces import PieceChangedError

    first = _piece_box("A__mat1", "PieceWood")
    second = _piece_box("A__mat2", "PieceClay")
    define_piece("X", [first, second])

    remove_object_and_mesh(second)

    # Every reader is loud, and the same named error comes out of each.
    with pytest.raises(PieceChangedError, match="A__mat2"):
        piece_report("X")
    with pytest.raises(PieceChangedError, match="A__mat2"):
        snap_base_to_ground(piece="X")
    with pytest.raises(BlendSaveError, match="A__mat2"):
        save_blend(piece="X", blend_path=Path("/tmp") / "never_written.blend")

    # And the stated repair works: re-defining without the removed part.
    repaired = define_piece("X", [first])
    assert repaired.objects == (first,)
    assert piece_report("X") == repaired


def test_a_piece_name_that_was_never_defined_is_a_named_error(empty_scene):
    from golem_blender.ops import piece_report
    from golem_blender.ops.pieces import UnknownPiece

    _piece_box("Orphan__mat1", "PieceWood")

    with pytest.raises(UnknownPiece, match="Ghost"):
        piece_report("Ghost")


# --- 3. save_blend takes a piece -------------------------------------------


def test_save_blend_writes_a_piece_that_re_reads_with_its_objects_and_materials(
    empty_scene, tmp_path
):
    """Condition 3."""
    from golem_blender.export import save_blend
    from golem_blender.ops import define_piece

    first = _piece_box("X__mat1", "PieceWood")
    second = _piece_box("X__mat2", "PieceClay", (1.5, 0.0, 0.0))
    report = define_piece("X", [first, second])

    blend_path = tmp_path / "X.blend"
    saved = save_blend(piece="X", blend_path=blend_path)

    assert blend_path.exists()
    assert saved.object_names == report.objects
    assert saved.triangle_counts == {part.name: part.triangles for part in report.parts}

    held = _what_the_file_holds(blend_path)
    assert held["objects"] == [first, second]
    assert held["materials"] == ["PieceClay", "PieceWood"]
    assert held["material_slots"][first] == ["PieceWood"]
    assert held["material_slots"][second] == ["PieceClay"]


def test_save_blend_refuses_a_named_piece_and_a_missing_one_aloud(
    empty_scene, tmp_path
):
    from golem_blender.export import BlendSaveError, save_blend
    from golem_blender.ops import define_piece, remove_object_and_mesh

    first = _piece_box("Y__mat1", "PieceWood")
    second = _piece_box("Y__mat2", "PieceClay")
    define_piece("Y", [first, second])
    blend_path = tmp_path / "Y.blend"

    with pytest.raises(BlendSaveError, match="Ghost"):
        save_blend(piece="Ghost", blend_path=blend_path)

    # Both spellings at once is a caller mistake: it is neither.
    with pytest.raises(BlendSaveError, match="not both"):
        save_blend([first], blend_path, piece="Y")

    remove_object_and_mesh(second)
    with pytest.raises(BlendSaveError, match="Y__mat2"):
        save_blend(piece="Y", blend_path=blend_path)

    assert list(tmp_path.iterdir()) == []


def test_object_names_still_work_without_a_piece(empty_scene, tmp_path):
    """The old spelling is untouched: a bare list saves exactly those."""
    from golem_blender.export import save_blend

    first = _piece_box("Z__mat1", "PieceWood")
    second = _piece_box("Z__mat2", "PieceClay")
    blend_path = tmp_path / "pair.blend"

    saved = save_blend([first, second], blend_path)

    assert saved.object_names == (first, second)
    assert _what_the_file_holds(blend_path)["objects"] == [first, second]


# --- 4. the piece is what gets snapped to the ground -----------------------


def test_snapping_a_piece_puts_the_whole_sets_lowest_point_at_zero(empty_scene):
    """Condition 4.

    The parts sit at different heights (0.5 m and 0.0 m), so a snap that
    moved only one of them would put the piece's lowest point at 0.5 m.
    """
    from golem_blender.ops import define_piece, piece_report, snap_base_to_ground

    first = _piece_box("Ground__mat1", "PieceWood", (0.0, 0.0, PIECE_LIFTED_M))
    second = _piece_box("Ground__mat2", "PieceClay", (1.5, 0.0, PIECE_LIFTED_M))
    define_piece("Ground", [first, second])

    applied_m = snap_base_to_ground(piece="Ground")

    assert applied_m == pytest.approx(-PIECE_LIFTED_M)
    assert piece_report("Ground").lowest_point_m == pytest.approx(
        0.0, abs=LOWEST_POINT_TOLERANCE_M
    )
    # Every part moved by the same offset, so the piece kept its shape.
    for name in (first, second):
        assert _lowest_world_z(name) == pytest.approx(0.0, abs=LOWEST_POINT_TOLERANCE_M)


def test_a_single_object_still_snaps_by_name(empty_scene):
    """The old spelling is untouched."""
    from golem_blender.ops import snap_base_to_ground

    lifted = _piece_box("Lone", "PieceWood", (0.0, 0.0, PIECE_LIFTED_M))

    assert snap_base_to_ground(lifted) == pytest.approx(-PIECE_LIFTED_M)
    assert _lowest_world_z(lifted) == pytest.approx(0.0, abs=LOWEST_POINT_TOLERANCE_M)

    # Neither or both is refused, loudly.
    with pytest.raises(ValueError, match="one of"):
        snap_base_to_ground()
    with pytest.raises(ValueError, match="not both"):
        snap_base_to_ground(lifted, piece="Ground")


# --- 5. order independence -------------------------------------------------


def test_the_totals_do_not_depend_on_the_order_the_names_were_given(empty_scene):
    """Condition 5."""
    from golem_blender.ops import define_piece, piece_report

    first = _piece_box("Order__mat1", "PieceWood")
    second = _piece_box("Order__mat2", "PieceClay", (2.0, 0.0, 0.0))

    forward = define_piece("Forward", [first, second])
    backward = define_piece("Backward", [second, first])

    assert forward.triangles_total == backward.triangles_total
    assert forward.dimensions_m == backward.dimensions_m
    assert forward.lowest_point_m == backward.lowest_point_m
    assert forward.objects == backward.objects == (first, second)
    assert forward.parts == backward.parts
    # The whole report is order-independent apart from the name it carries.
    assert dataclasses.replace(forward, object_name="") == dataclasses.replace(
        backward, object_name=""
    )
    assert piece_report([first, second]) == piece_report([second, first])


def test_a_bare_list_of_objects_is_measured_without_being_defined(empty_scene):
    """`name_or_objects` accepts the list the issue's signature spells; a
    set that was never named has no name to report."""
    from golem_blender.ops import piece_report

    first = _piece_box("Loose__mat1", "PieceWood")
    second = _piece_box("Loose__mat2", "PieceClay")

    report = piece_report([first, second])

    assert report.object_name == ""
    assert report.triangles_total == _standalone_triangles(
        first
    ) + _standalone_triangles(second)
    with pytest.raises(LookupError, match="Loose__mat9"):
        piece_report([first, "Loose__mat9"])
