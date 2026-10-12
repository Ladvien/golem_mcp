"""The MCP bridge carries a ToolOutcome from Blender's process to the
server's as JSON: it must round-trip exactly (through real JSON text, so
tuples and Paths come back typed) and refuse a truncated payload.
Pure: no Blender."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from blended.agent.outcome import ToolOutcome, outcome_from_json, outcome_to_json
from blended.stages import STAGE_DONE


def test_an_outcome_round_trips_through_json_text():
    outcome = ToolOutcome(
        text="Crate: 0.5 x 0.5 x 0.5 m",
        images=(Path("/tmp/views/front.png"), Path("/tmp/views/top.png")),
        ok=False,
        stage_reached=STAGE_DONE,
        validated_arguments=None,
        gates=({"object_name": "Crate", "gate_failures": ["non_manifold"]},),
        intermediates_created=("Cutter",),
        intermediates_resolved=("Crate", "Lid"),
        hatch_reason="no bevel op",
        source_sha256="ab" * 32,
    )

    assert (
        outcome_from_json(json.loads(json.dumps(outcome_to_json(outcome)))) == outcome
    )


def test_a_payload_missing_ok_raises():
    payload = outcome_to_json(ToolOutcome("x"))
    del payload["ok"]

    with pytest.raises(KeyError):
        outcome_from_json(payload)
