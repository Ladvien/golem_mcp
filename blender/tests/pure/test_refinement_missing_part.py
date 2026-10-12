"""A refinement whose after-state lost the part is a reported finding,
never an exception that loses the record (measured 2026-09-10, iteration
82: the driver died in `_measured` after a turn left the stool named Seat)."""

from __future__ import annotations

from blended.evaluate.acceptance import (
    AcceptanceReport,
    DimensionMeasurement,
    PartReport,
    RefinementOutcome,
)
from blended.evaluate.briefs import get_brief


def test_a_missing_dimension_after_the_edit_is_reported_not_raised():
    brief = get_brief("three_leg_stool")
    step = brief.refinements[0]
    part = brief.parts[0].name
    before = AcceptanceReport(
        brief_name=brief.name,
        part_reports=(
            PartReport(
                name=part,
                object_found=True,
                linked_into_scene=True,
                dimensions=tuple(
                    DimensionMeasurement(spec=spec, measured_m=spec.expected_m)
                    for spec in step.changed
                ),
            ),
        ),
    )
    after = AcceptanceReport(
        brief_name=brief.name, part_reports=(PartReport(name=part, object_found=False),)
    )
    outcome = RefinementOutcome(step=step, before=before, after=after)

    summary = outcome.summary(brief)  # must not raise
    assert "missing (part not found)" in summary
    assert not outcome.passes(brief)
    assert any(
        part in failure or "no object" in failure for failure in outcome.failures(brief)
    )
