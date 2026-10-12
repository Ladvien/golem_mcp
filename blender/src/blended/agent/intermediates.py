"""The per-turn ledger of unlinked intermediates (OT-5).

An ungated constructor returns an object nothing has linked. The gate
never sees it, so the loop keeps the account: every `ToolOutcome`
credits the intermediates it created and debits the ones it resolved
(linked, consumed by a boolean, removed). A turn may not end with an
answer while the ledger is non-empty — the model is told what is
pending and what resolves it, and the refusal counts against the
tool-call budget so a model that never resolves still terminates.

Pure: no Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from blended.agent.outcome import ToolOutcome

UNRESOLVED_INTERMEDIATES_REFUSAL = (
    "Cannot end the turn: {pending} — created by an UNGATED op and never "
    "linked, consumed or removed. For each one: link_into_scene it if it "
    "is part of the asset, consume it in a boolean, or "
    "remove_object_and_mesh it. Then answer."
)


@dataclass
class IntermediateLedger:
    # object name -> the tool that created it, in creation order
    pending: dict[str, str] = field(default_factory=dict)

    def record(self, tool_name: str, outcome: ToolOutcome) -> None:
        """Debit what the call resolved, then credit what it created."""
        for object_name in outcome.intermediates_resolved:
            self.pending.pop(object_name, None)
        for object_name in outcome.intermediates_created:
            self.pending[object_name] = tool_name

    def refusal(self) -> str:
        """The message that blocks an answer, or "" when nothing is pending."""
        if not self.pending:
            return ""
        listed = ", ".join(
            f"{name!r} (from {tool_name})" for name, tool_name in self.pending.items()
        )
        return UNRESOLVED_INTERMEDIATES_REFUSAL.format(pending=listed)
