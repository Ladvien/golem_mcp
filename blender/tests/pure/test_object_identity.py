"""Edit-versus-rebuild is measured, recorded, and never gated on.

Iteration 14 rebuilt a stool it was asked to make taller, preserved
every unnamed measurement exactly, and the human ruled that acceptable.
Two things have to stay true after that ruling, and they pull in
opposite directions: the difference must be VISIBLE — a rebuild is
minutes where an edit is seconds, and nothing in the finished mesh
records which happened — and it must not FAIL a run. A test is the only
thing that keeps both from drifting, because either one is a one-line
change away from the other.

`FakeBlenderObject` stands in for the real datablock: custom properties
are a plain mapping on the object, which is all `object_identity`
touches. Keeping this in the pure lane means the guard runs on every
`make test-pure`, not only when Blender is around.
"""

import pytest

from blended.evaluate.iteration_log import IterationRecord
from blended.evaluate.object_identity import (
    IDENTITY_PROPERTY_NAME,
    ObjectHasNoIdentity,
    RefinementLocality,
    has_identity,
    measure_locality,
    new_identity,
    read_identity,
    stamp_identity,
)


class FakeBlenderObject:
    """The custom-property surface of a bpy object, and nothing else."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._properties: dict[str, object] = {}

    def __setitem__(self, key: str, value: object) -> None:
        self._properties[key] = value

    def __getitem__(self, key: str) -> object:
        return self._properties[key]

    def keys(self):
        return self._properties.keys()


def _stamped(name: str = "Stool") -> tuple[FakeBlenderObject, str]:
    blender_object = FakeBlenderObject(name)
    identity = stamp_identity(blender_object, new_identity())
    return blender_object, identity


def test_a_stamp_survives_an_in_place_edit():
    """A transform or a boolean leaves custom properties alone."""
    blender_object, identity = _stamped()
    locality = measure_locality(blender_object, "taller_stool", identity)
    assert locality.edited_in_place
    assert "edited in place" in locality.summary()


def test_a_rebuild_loses_the_stamp_and_reads_as_a_rebuild():
    """`add_cylinder` is idempotent by name: the datablock is replaced.

    The replacement is a fresh object carrying no stamp, which is the
    whole reason this measurement works — a rebuild from the same
    constants is otherwise indistinguishable from an edit.
    """
    _, identity = _stamped()
    rebuilt = FakeBlenderObject("Stool")  # what add_cylinder leaves behind
    locality = measure_locality(rebuilt, "taller_stool", identity)
    assert not locality.edited_in_place
    assert "rebuilt" in locality.summary()


def test_a_rebuild_is_recorded_as_evidence_and_never_gated():
    """The ruling of 2026-08-22, pinned.

    A run whose follow-up rebuilt the asset still passes, provided the
    gates pass and a human looked. Wiring `refinement_locality` into
    `IterationRecord.passed` would reverse a human's verdict in an
    append-only log; this test is what breaks first if anyone does.
    """
    _, identity = _stamped()
    locality = measure_locality(FakeBlenderObject("Stool"), "taller_stool", identity)
    assert not locality.edited_in_place, "precondition: this is the rebuild case"

    record = IterationRecord(
        iteration=14,
        brief_name="three_leg_stool",
        prompt_identity="v6:0de49b92aa30",
        prompt_revision=6,
        started_at="2026-08-22T00:00:00",
        structural_gate_passed=True,
        form_gate_passed=True,
        refinement_gate_passed=True,
        refinement_locality=(locality.summary(),),
        visual_inspected=True,
    )
    assert record.passed
    assert record.refinement_locality, "the evidence is kept, not discarded"


def test_a_vanished_object_is_not_reported_as_a_rebuild():
    """Two different failures; only one of them the other gates catch."""
    _, identity = _stamped()
    locality = measure_locality(None, "taller_stool", identity)
    assert not locality.object_present
    assert not locality.edited_in_place
    assert "absent" in locality.summary()
    assert "rebuilt" not in locality.summary()


def test_reading_a_missing_stamp_raises_rather_than_defaulting():
    """ "" would read as "rebuilt" whether it was rebuilt or never stamped."""
    with pytest.raises(ObjectHasNoIdentity):
        read_identity(FakeBlenderObject("Stool"))


def test_an_empty_identity_is_refused_at_the_door():
    with pytest.raises(ValueError):
        stamp_identity(FakeBlenderObject("Stool"), "")


def test_the_stamp_lands_under_a_namespaced_property():
    blender_object, identity = _stamped()
    assert has_identity(blender_object)
    assert blender_object[IDENTITY_PROPERTY_NAME] == identity


def test_two_builds_never_share_an_identity():
    assert new_identity() != new_identity()


def test_an_unstamped_run_is_not_silently_an_edit():
    """A stamped_identity of "" cannot make `edited_in_place` true.

    If the stamping step is ever skipped, the measurement must read as
    "not an in-place edit" rather than matching a missing stamp against
    a missing stamp and calling it preserved.
    """
    locality = RefinementLocality(
        step_name="taller_stool",
        stamped_identity="",
        object_present=True,
        measured_identity="",
    )
    assert not locality.edited_in_place
