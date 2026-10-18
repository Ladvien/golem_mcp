"""Did a follow-up EDIT the asset that existed, or replace it?

Locality is a property of the EDIT, not of the asset, and no measurement
of the finished mesh can recover it. A rebuild that re-runs the same
construction from the same constants lands on the same numbers, so
`RefinementOutcome.preservation_failures` — which compares what was
measured before against what is measured after — has nothing to report.
Iteration 14 is the proof: the taller_stool follow-up re-ran
add_cylinder / boolean_union / ground-cut at 0.55 m instead of editing
the stool in front of it, and the refinement gate said "0 disturbed",
correctly, because nothing was.

So identity is STAMPED rather than inferred. The primitives are
idempotent by name (`add_cylinder` calls `remove_object_and_mesh(name)`
first), which means rebuilding under the same name destroys the
datablock and takes any custom property with it. An in-place edit — a
transform, a boolean against the existing object, a bevel — carries the
stamp through untouched. That asymmetry is the whole measurement.

EVIDENCE, NOT A GATE. Ruled 2026-08-22: a rebuild that preserves every
measurement the user did not name is an acceptable way to satisfy a
follow-up, so nothing here fails a run and `IterationRecord.passed`
never consults it. What it buys is a history that can answer "did the
agent edit or rebuild" long after the render is forgotten — the
question LL3M cares about, since a rebuild costs minutes where an edit
costs seconds, and the log is the only place that cost is visible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# A custom property, so it rides on the object rather than in a side
# table that could disagree with the scene. Namespaced because Blender
# custom properties share one flat dictionary with anything else that
# writes to the object.
IDENTITY_PROPERTY_NAME = "blended_object_identity"


class ObjectHasNoIdentity(KeyError):
    """Raised when a stamp was expected and the object carries none.

    There is no default. An empty string returned in place of a missing
    stamp would read as "rebuilt" whether the object was rebuilt or the
    stamping step was never reached, and those are different facts.
    """


def new_identity() -> str:
    """A fresh identity. Unique per build, never derived from the mesh."""
    return uuid.uuid4().hex


def stamp_identity(blender_object, identity: str) -> str:
    """Write `identity` onto the object. Returns what was written."""
    if not identity:
        raise ValueError("refusing to stamp an empty identity")
    blender_object[IDENTITY_PROPERTY_NAME] = identity
    return identity


def has_identity(blender_object) -> bool:
    # `.keys()`, not `in blender_object`: the test double implements only
    # the keys()/[] surface of a bpy ID-property owner.
    return IDENTITY_PROPERTY_NAME in blender_object.keys()  # noqa: SIM118


def read_identity(blender_object) -> str:
    """The stamp on the object. Raises if there is none."""
    if not has_identity(blender_object):
        raise ObjectHasNoIdentity(
            f"{blender_object.name} carries no "
            f"{IDENTITY_PROPERTY_NAME}: it was never stamped, or it was "
            f"rebuilt and the stamp went with the old datablock"
        )
    return str(blender_object[IDENTITY_PROPERTY_NAME])


@dataclass(frozen=True)
class RefinementLocality:
    """How one follow-up step reached its result.

    `object_present` and `measured_identity` are recorded separately so
    a vanished object is never reported as a rebuild — "the follow-up
    replaced the stool" and "there is no stool" are different failures,
    and only the second one the other gates already catch.
    """

    step_name: str
    stamped_identity: str
    object_present: bool
    measured_identity: str  # "" when absent; see `object_present`

    @property
    def edited_in_place(self) -> bool:
        return (
            self.object_present
            and bool(self.stamped_identity)
            and self.measured_identity == self.stamped_identity
        )

    def summary(self) -> str:
        if not self.object_present:
            return f"LOCALITY {self.step_name}: object absent after the edit"
        if self.edited_in_place:
            return (
                f"LOCALITY {self.step_name}: edited in place "
                f"(identity {self.stamped_identity[:12]} survived)"
            )
        return (
            f"LOCALITY {self.step_name}: rebuilt "
            f"(stamped {self.stamped_identity[:12]}, found "
            f"{self.measured_identity[:12] or 'no stamp'}) — recorded, "
            f"not gated"
        )


def measure_locality(
    blender_object, step_name: str, stamped_identity: str
) -> RefinementLocality:
    """Read the stamp back after a follow-up step.

    `blender_object` is None when the object no longer exists under its
    name — which the caller learns from the scene, not from here.
    """
    if blender_object is None:
        return RefinementLocality(
            step_name=step_name,
            stamped_identity=stamped_identity,
            object_present=False,
            measured_identity="",
        )
    measured = read_identity(blender_object) if has_identity(blender_object) else ""
    return RefinementLocality(
        step_name=step_name,
        stamped_identity=stamped_identity,
        object_present=True,
        measured_identity=measured,
    )
