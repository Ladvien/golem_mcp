"""Issue #17, the parts of a piece that need no Blender.

The registry is a dict of NAMES, and the argument rules are the ones a
caller gets wrong: a bare string instead of a one-element list, a
repeated member, an empty set. None of that needs bpy, so none of it
should need a Blender launch to find out — the measurements themselves
are in `tests/blender/test_pieces.py`.
"""

import pytest

from golem_blender.ops import pieces
from golem_blender.ops._contract import changes_scene, is_gated, is_reads_only


@pytest.fixture(autouse=True)
def empty_registry():
    pieces._PIECES.clear()
    yield
    pieces._PIECES.clear()


def test_a_bare_string_is_refused_by_type_not_measured_as_one_object():
    """A piece is always several names; `"A__mat1"` is a one-member set that
    would silently read as eleven characters without this refusal."""
    with pytest.raises(TypeError, match="list of names"):
        pieces._checked_names("A__mat1")


def test_the_set_is_canonical_so_order_cannot_leak_into_a_total():
    assert pieces._checked_names(["b", "a", "c"]) == ("a", "b", "c")
    assert pieces._checked_names(("c", "a")) == ("a", "c")


def test_an_empty_set_and_a_repeated_member_are_refused():
    with pytest.raises(ValueError, match="empty"):
        pieces._checked_names([])
    with pytest.raises(ValueError, match="repeats"):
        pieces._checked_names(["a", "a"])
    with pytest.raises(ValueError, match="non-empty string"):
        pieces._checked_names(["a", ""])


def test_an_undefined_piece_is_a_named_lookup_error():
    """`UnknownPiece` subclasses LookupError, so a caller catching what
    `object_by_name` raises handles both without knowing which layer
    noticed the missing name."""
    with pytest.raises(pieces.UnknownPiece, match="Ghost"):
        pieces._resolved_names("Ghost")
    assert issubclass(pieces.UnknownPiece, LookupError)
    assert issubclass(pieces.PieceChangedError, LookupError)


def test_the_two_ops_have_the_gating_the_contract_requires():
    """Neither op returns a scene object, so neither is gated: the report's
    `object_name` is the PIECE's name, which no object has, and gating it
    would send the gate looking for an object that does not exist.

    `define_piece` is a plain `@op()` (it writes session state, so it is
    plan-required like any writer) and `piece_report` is `@op(
    reads_only=True)` because it changes nothing.
    """
    assert is_reads_only(pieces.piece_report)
    assert not changes_scene(pieces.piece_report)
    assert not is_gated(pieces.piece_report)
    assert changes_scene(pieces.define_piece)
    assert not is_reads_only(pieces.define_piece)
    assert not is_gated(pieces.define_piece)


def test_the_report_fields_the_issue_asks_for_are_all_present():
    import dataclasses

    assert [field.name for field in dataclasses.fields(pieces.PieceReport)] == [
        "object_name",
        "objects",
        "triangles_total",
        "dimensions_m",
        "lowest_point_m",
        "parts",
    ]
    assert [field.name for field in dataclasses.fields(pieces.PiecePart)] == [
        "name",
        "triangles",
        "material_names",
    ]
