"""What a tool call hands back to the loop (OT-5).

The model reads `text` and looks at `images`; the loop also needs
STRUCTURE the model never sees: which unlinked intermediates this call
created and which it resolved, so a turn cannot end with an operand
nobody linked, consumed or removed. Parsing that out of `text` would be
a second encoding of the harness's own output, so it travels beside it.
The structured transcript (OT-8) grows from here.

Pure: no Blender.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    images: tuple[Path, ...] = ()
    ok: bool = True
    # One of blended.stages.STAGES for run_python and op tools; "" for a
    # tool that executes nothing in the scene.
    stage_reached: str = ""
    # The arguments as VALIDATED: bound to the op signature (JSON form,
    # plan_step stripped) for an op tool; as sent, plan_step stripped,
    # when the binder rejected the call; as given for a service tool.
    validated_arguments: dict | None = None
    # One JSON gate verdict per gated object (harness.gate_verdict_json).
    gates: tuple[dict, ...] = ()
    # Object names an UNGATED op created this call (unlinked intermediates).
    intermediates_created: tuple[str, ...] = ()
    # Object names a successful op call linked, consumed or removed —
    # every object-name parameter of the call. Applied BEFORE `created`.
    intermediates_resolved: tuple[str, ...] = ()
    # run_python only (OT-7): the reason the vocabulary did not suffice,
    # and a content hash of the source — the candidate_op record's
    # inputs (OT-8, OT-12). Every hatch call is a vote for a new op.
    hatch_reason: str = ""
    source_sha256: str = ""


def outcome_to_json(outcome: ToolOutcome) -> dict:
    """The JSON wire form of an outcome: exactly the dataclass fields,
    paths and tuples as lists. The MCP bridge carries an outcome from
    Blender's process to the server's with it."""
    return {
        "text": outcome.text,
        "images": [str(path) for path in outcome.images],
        "ok": outcome.ok,
        "stage_reached": outcome.stage_reached,
        "validated_arguments": outcome.validated_arguments,
        "gates": list(outcome.gates),
        "intermediates_created": list(outcome.intermediates_created),
        "intermediates_resolved": list(outcome.intermediates_resolved),
        "hatch_reason": outcome.hatch_reason,
        "source_sha256": outcome.source_sha256,
    }


def outcome_from_json(payload: dict) -> ToolOutcome:
    """Inverse of `outcome_to_json`; a missing key raises KeyError."""
    return ToolOutcome(
        text=payload["text"],
        images=tuple(Path(path) for path in payload["images"]),
        ok=payload["ok"],
        stage_reached=payload["stage_reached"],
        validated_arguments=payload["validated_arguments"],
        gates=tuple(payload["gates"]),
        intermediates_created=tuple(payload["intermediates_created"]),
        intermediates_resolved=tuple(payload["intermediates_resolved"]),
        hatch_reason=payload["hatch_reason"],
        source_sha256=payload["source_sha256"],
    )
