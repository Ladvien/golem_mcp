"""Append-only record of prompt-convergence iterations.

One JSON object per iteration, never rewritten. The log is the evidence
that a prompt revision earned its promotion: it carries the exact brief,
the prompt identity that ran, what the deterministic gates measured,
where the render landed, the visual deviations, the failure
classification, and the hypothesis behind the next edit.

Append-only matters. A convergence claim is "three consecutive clean
runs", which is a statement about HISTORY — a log that can be edited
after the fact cannot support it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

DEFAULT_LOG_PATH = Path("_evaluate/iterations.jsonl")
DEFAULT_VERDICT_PATH = Path("_evaluate/verdicts.jsonl")

# The four causes an iteration failure can have. Exactly one applies,
# and only the first permits a prompt edit — the discipline that keeps
# the loop from "fixing" a code bug by rewording the prompt until the
# bug is hidden.
#
# HARNESS_CRITIQUE is the fourth because the critique is itself a
# fallible instrument, and its failures look exactly like the other
# three from the outside. LL3M measured a critic VLM that missed
# spatial errors a human caught in 3-4 follow-ups; the TikZ study
# measured visual verification at imperfect precision AND recall. So a
# run can fail two ways that are not about the asset at all: the
# critique answered "Yes" to a question the render answers "No" (a
# missed deviation), or it reported a deviation that is not there (a
# false positive). Either way the artifact to fix is the critique — the
# eye's question set, the render that feeds it, or the gate that should
# have measured the thing instead of asking about it. Tuning the
# working agreement to satisfy a blind critic tunes the wrong artifact
# and bakes the blindness in. This project has already paid for the
# distinction once: see the mistake memory entry
# "the-critique-explained-away-its-own-evidence", where the critique
# held both the evidence and the verdict, answered Yes, and the human
# caught the angled sole by eye at iteration 4.
CLASSIFICATION_PROMPT = "prompt"
CLASSIFICATION_HARNESS_CODE = "harness_code"
CLASSIFICATION_HARNESS_CRITIQUE = "harness_critique"
CLASSIFICATION_BAD_BRIEF = "bad_brief"
CLASSIFICATIONS = (
    CLASSIFICATION_PROMPT,
    CLASSIFICATION_HARNESS_CODE,
    CLASSIFICATION_HARNESS_CRITIQUE,
    CLASSIFICATION_BAD_BRIEF,
)

# The author of a verdict written by a person. Any other value names a
# machine examiner and requires the calibration that licensed it.
HUMAN_EXAMINER = "human"


class InvalidClassification(ValueError):
    """Raised for a classification outside the closed set."""


class InvalidVerdict(ValueError):
    """Raised for a verdict that does not name a legitimate author."""


@dataclass(frozen=True)
class IterationRecord:
    """One RUN -> RENDER -> EXAMINE pass over one brief."""

    iteration: int
    brief_name: str
    prompt_identity: str  # e.g. "v2:9fa1c0d3e771"
    prompt_revision: int
    started_at: str  # ISO 8601, supplied by the caller
    # The PROMPT THE MODEL ACTUALLY READ. `prompt_identity` hashes the
    # working-agreement body only — 6,955 of the 23,580 characters that
    # reach the model — so the conventions, the operations manifest, the
    # drift catalog and the skill modules are all outside it. Editing
    # one drift row moved the assembled prompt by 695 characters while
    # `prompt_identity` did not move at all. Defaulted so every
    # historical record still loads through
    # `IterationRecord(**json.loads(line))`.
    assembled_prompt_fingerprint: str = ""
    # The TOOLS the model could call: service tools plus every generated
    # op tool (OT-3), fingerprinted like the assembled prompt. Defaulted
    # so records from before OT-3 load unchanged.
    tool_schemas_fingerprint: str = ""
    # The subset actually OFFERED per call (OT-25): service tools, readers,
    # the derived core. Empty on records from before OT-25.
    offered_tools_fingerprint: str = ""
    # WHICH MODELS RAN. A prompt is tuned against a model, not in the
    # abstract: v1-v5 were all scored against deepseek-v4-flash, and a
    # log that does not say so would silently compare runs from
    # different baselines and attribute the difference to the prompt.
    writer_model: str = ""
    vision_model: str = ""
    # RUN
    agent_turns: int = 0
    tool_calls: tuple[str, ...] = field(default_factory=tuple)
    # The STRUCTURED record of every tool call (OT-8): one
    # agent.tool_event.ToolEvent as a dict — validated arguments, plan
    # step, stage, gate verdicts, wall time, hatch reason and source
    # hash. `tool_calls` above is the raw call text the replay reads;
    # this is what the miner (OT-12) and the exporter (OT-18) read.
    # Empty on records from before OT-8.
    tool_events: tuple[dict, ...] = field(default_factory=tuple)
    agent_final_text: str = ""
    # EXAMINE (a) — deterministic, in order
    structural_gate_passed: bool = False
    structural_failures: tuple[str, ...] = field(default_factory=tuple)
    form_gate_passed: bool = False
    form_failures: tuple[str, ...] = field(default_factory=tuple)
    form_summary: str = ""
    # RENDER
    render_path: str = ""
    # A contact sheet answers what one viewpoint can answer. Measured
    # 2026-08-22 (iteration 10): the front orthographic view projects a
    # stool's 120 and 240 degree legs to the same world x, so it cannot
    # show spacing at all and the human could only answer "Unclear".
    # The .glb can be turned.
    glb_path: str = ""
    # USER-GUIDED REFINEMENT: the follow-up turn, gated like the
    # first. A localized edit is only localized if what the user did
    # NOT name still measures what it measured before.
    refinement_gate_passed: bool = True
    refinement_failures: tuple[str, ...] = field(default_factory=tuple)
    refinement_summary: str = ""
    # HOW the follow-up reached its result: edited in place, or rebuilt.
    # Evidence, never a gate — see evaluate/object_identity.py. Kept in
    # the record because it is the only place the edit-vs-rebuild cost
    # is visible once the render is forgotten, and no measurement of the
    # finished mesh can recover it after the fact.
    refinement_locality: tuple[str, ...] = field(default_factory=tuple)
    # EXAMINE (b) — visual, only meaningful once (a) passed
    visual_deviations: tuple[str, ...] = field(default_factory=tuple)
    visual_inspected: bool = False
    # EXAMINE (c) + ADJUST
    classification: str = ""
    hypothesis: str = ""
    prompt_change: str = ""
    notes: str = ""
    # WHAT IT SPENT. Added 2026-09-06 after an audit found the harness
    # had no token accounting at all: one measured brief billed 243,137
    # input tokens to convey ~22.5k of assembled prompt, and 14 API
    # calls for 7 harness turns, none of it visible anywhere. Zero on
    # older rows means "not recorded", not "free" — the log is
    # append-only, so history stays as it was written.
    api_calls: int = 0
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    # Of `output_tokens`, what the model spent thinking (OT-28). Zero on
    # a lane that does not report it and on rows written before it did.
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    def __post_init__(self) -> None:
        if self.classification and self.classification not in CLASSIFICATIONS:
            raise InvalidClassification(
                f"classification {self.classification!r} not in {CLASSIFICATIONS}"
            )

    @property
    def passed(self) -> bool:
        """A clean iteration: both deterministic gates, zero deviations.

        Deliberately requires `visual_inspected`. An iteration where
        nobody looked is not a pass with no deviations — it is a pass
        with no evidence.
        """
        return (
            self.structural_gate_passed
            and self.form_gate_passed
            # The refinement turn is a gate, not a bonus: the standards
            # require a user-guided refinement phase, so a run whose
            # follow-up moved something the user did not name has not
            # passed, however clean the first build was.
            #
            # What this gate does NOT decide is whether the follow-up
            # edited the asset or rebuilt it. Ruled 2026-08-22, on
            # iteration 14: a rebuild that lands on every preserved
            # number is an acceptable way to satisfy a follow-up. That
            # is measured and recorded in `refinement_locality`, and
            # deliberately not consulted here.
            and self.refinement_gate_passed
            and self.visual_inspected
            and not self.visual_deviations
        )


@dataclass(frozen=True)
class IterationVerdict:
    """The examiner's judgement of one iteration, written separately.

    Measurements and judgements have different authors and different
    lifetimes: the driver measures, a human (or supervising agent)
    examines the render afterwards. Keeping them in one mutable row
    would mean rewriting a measured record hours after it was taken,
    which is exactly what an append-only log exists to prevent. So the
    verdict is its own append-only file, keyed to (iteration, brief).
    """

    iteration: int
    brief_name: str
    visual_inspected: bool
    visual_deviations: tuple[str, ...] = field(default_factory=tuple)
    classification: str = ""
    hypothesis: str = ""
    prompt_change: str = ""
    notes: str = ""
    # WHO JUDGED. The harness's whole discipline is that measurements
    # and judgements have different authors and lifetimes; a machine
    # judgement that is indistinguishable in the log from a human
    # sign-off destroys that distinction, and the pin rests on it. So a
    # verdict names its author: "human", or `examiner_identity()` for a
    # machine verdict, which additionally must name the calibration
    # that licensed it. The defaults keep every existing log line
    # loadable — `VerdictLog.verdicts()` constructs with `**payload`.
    examiner: str = "human"
    # The examiner could not answer (order-consistent `cannot_tell`).
    # Distinct from "no deviations": an instrument that could not see
    # is not a pass, and the orchestrator halts on it.
    abstained: bool = False
    calibration_identity: str = ""
    # PER VIEW, the order-consistent tags, as (view_name, tags) pairs.
    # Recorded because the aggregate alone cannot answer whether a view
    # earns its cost: each of the five views is examined TWICE (both
    # image orders), so a view that never produces a consistent tag is
    # two API calls per brief for no information — and examination is
    # the loop's largest token consumer, measured 2026-09-06 at 10
    # calls per brief against the writer's 26 for the whole build.
    # Empty on older rows means "not recorded", not "no tags".
    view_tags: tuple[tuple[str, tuple[str, ...]], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.classification and self.classification not in CLASSIFICATIONS:
            raise InvalidClassification(
                f"classification {self.classification!r} not in {CLASSIFICATIONS}"
            )
        if not self.examiner.strip():
            raise InvalidVerdict(
                "a verdict must name its examiner: 'human', or the "
                "examiner identity of the instrument that judged it"
            )
        if self.examiner != HUMAN_EXAMINER and not self.calibration_identity.strip():
            raise InvalidVerdict(
                f"machine verdict by {self.examiner!r} carries no "
                f"calibration_identity — a machine verdict without the "
                f"measurement that licensed it is not a verdict"
            )


def _tuple_field_names(
    record_type: type[IterationRecord | IterationVerdict],
) -> tuple[str, ...]:
    """Names of the dataclass fields declared with `default_factory=tuple`.
    JSON has no tuple, so a line reads back as lists; the loaders restore
    the declared top-level type (values nested inside `tool_events` dicts
    stay as JSON read them).
    """
    return tuple(
        item.name for item in fields(record_type) if item.default_factory is tuple
    )


class VerdictLog:
    """Append-only JSONL of examiner verdicts."""

    def __init__(self, path: Path = DEFAULT_VERDICT_PATH) -> None:
        self.path = Path(path)

    def append(self, verdict: IterationVerdict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(verdict), sort_keys=True) + "\n")

    def verdicts(self) -> list[IterationVerdict]:
        if not self.path.exists():
            return []
        loaded: list[IterationVerdict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                for tuple_field in _tuple_field_names(IterationVerdict):
                    if tuple_field in payload:
                        payload[tuple_field] = tuple(payload[tuple_field])
                if "view_tags" in payload:
                    payload["view_tags"] = tuple(
                        (view_name, tuple(tags))
                        for view_name, tags in payload["view_tags"]
                    )
                loaded.append(IterationVerdict(**payload))
        return loaded

    def latest_for(self, iteration: int, brief_name: str) -> IterationVerdict | None:
        """The most recent verdict for a run. Later lines supersede earlier
        ones, so a correction is an append, never an edit."""
        matching = [
            verdict
            for verdict in self.verdicts()
            if verdict.iteration == iteration and verdict.brief_name == brief_name
        ]
        return matching[-1] if matching else None


class IterationLog:
    """Append-only JSONL log of iterations."""

    def __init__(self, path: Path = DEFAULT_LOG_PATH) -> None:
        self.path = Path(path)

    def append(self, record: IterationRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")

    def records(self) -> list[IterationRecord]:
        if not self.path.exists():
            return []
        loaded: list[IterationRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                for tuple_field in _tuple_field_names(IterationRecord):
                    if tuple_field in payload:
                        payload[tuple_field] = tuple(payload[tuple_field])
                loaded.append(IterationRecord(**payload))
        return loaded

    def next_iteration_number(self) -> int:
        existing = self.records()
        return 1 + max((record.iteration for record in existing), default=0)


def fold_verdict(
    record: IterationRecord, verdict: IterationVerdict | None
) -> IterationRecord:
    """The measured record with the examiner's judgement folded in.

    Measurements and judgements are written separately and read
    together; this is the one place they are combined, so the
    convergence rule and any reporting agree by construction.
    """
    if verdict is None:
        return record
    return replace(
        record,
        visual_inspected=verdict.visual_inspected,
        visual_deviations=verdict.visual_deviations,
        classification=verdict.classification,
        prompt_change=verdict.prompt_change,
        hypothesis=verdict.hypothesis,
    )


def clean_cycle_for_identity(
    records: list[IterationRecord],
    brief_names: tuple[str, ...],
    prompt_identity: str,
) -> dict[str, int]:
    """The newest clean run per brief that RAN this prompt identity.

    Which runs may mint a golden reference for a revision? Only runs
    that executed that revision's text. `CONVERGENCE_RUNS` cannot
    answer it: that tuple names the runs of the CURRENTLY PINNED
    revision, which by definition executed the old text, so sourcing
    from it and then asserting the identity matches can only ever
    succeed for the revision already pinned — which deadlocked the loop
    against advancing to a candidate at all (measured 2026-09-05: every
    door refused, `pin-golden-views REVISION=11` with "iteration 51 ran
    'v10:...', not 'v11:...'").

    Clean means the deterministic gates only — structural, form and
    refinement. The examiner's verdict is deliberately not consulted:
    its judgement is made AGAINST a reference, so requiring it here
    would ask a reference to exist before it is minted.
    """
    newest: dict[str, int] = {}
    for record in records:
        if record.brief_name not in set(brief_names):
            continue
        if record.prompt_identity != prompt_identity:
            continue
        if not (
            record.structural_gate_passed
            and record.form_gate_passed
            and record.refinement_gate_passed
        ):
            continue
        if record.iteration >= newest.get(record.brief_name, -1):
            newest[record.brief_name] = record.iteration
    return newest


def converged_suite_cycles(
    records: list[IterationRecord],
    brief_names: tuple[str, ...],
    verdicts: list[IterationVerdict] | None = None,
) -> tuple[int, str]:
    """Trailing complete suite cycles that are clean, and the prompt
    identity they ran.

    Convergence is a property of the SUITE, not of one brief: a prompt
    that fixes the planter by breaking the stool has not converged. The
    protocol runs ONE brief per iteration, so a cycle is not an
    iteration number — it is the newest record per brief, walking
    iterations downwards until every brief has been seen once. (The
    predecessor of this function grouped by iteration number and
    therefore returned 0 on iterations 47-51, the very cycle that
    earned the v10 pin; see mistake memory
    "the-convergence-rule-was-never-executable".)

    A cycle is converged when, for all its records: the folded verdict
    was inspected, did not abstain and reported no deviations; the
    record passed both deterministic gates and its refinement; no
    verdict carries a prompt change; and every record ran ONE prompt
    identity. Returns (cycle count, identity of the newest converged
    cycle) — ("" when the count is zero).
    """
    verdict_by_key: dict[tuple[int, str], IterationVerdict] = {}
    for verdict in verdicts or []:
        verdict_by_key[(verdict.iteration, verdict.brief_name)] = verdict

    by_iteration: dict[int, list[IterationRecord]] = {}
    for record in records:
        by_iteration.setdefault(record.iteration, []).append(record)

    wanted = set(brief_names)
    if not wanted:
        return 0, ""

    cycles: list[tuple[bool, str]] = []
    current: dict[str, IterationRecord] = {}
    current_verdicts: dict[str, IterationVerdict | None] = {}
    for iteration in sorted(by_iteration, reverse=True):
        for record in by_iteration[iteration]:
            if record.brief_name not in wanted:
                continue
            if record.brief_name in current:
                # Older run of a brief already seen in this cycle: it
                # belongs to the previous cycle, not this one.
                continue
            run_verdict = verdict_by_key.get((record.iteration, record.brief_name))
            current[record.brief_name] = fold_verdict(record, run_verdict)
            current_verdicts[record.brief_name] = run_verdict
        if set(current) == wanted:
            cycles.append(_cycle_verdict(current, current_verdicts))
            current = {}
            current_verdicts = {}

    trailing = 0
    identity = ""
    for converged, cycle_identity in cycles:
        if not converged:
            break
        if trailing == 0:
            identity = cycle_identity
        trailing += 1
    return trailing, identity


def _cycle_verdict(
    folded: dict[str, IterationRecord],
    verdicts: dict[str, IterationVerdict | None],
) -> tuple[bool, str]:
    """(is this cycle converged, the one prompt identity it ran)."""
    identities = {record.prompt_identity for record in folded.values()}
    identity = identities.pop() if len(identities) == 1 else ""
    if not identity:
        # A cycle spanning two prompt identities is not a cycle OF a
        # prompt: the claim "this text converged" would name two texts.
        return False, ""
    for brief_name, record in folded.items():
        verdict = verdicts.get(brief_name)
        if verdict is None or not verdict.visual_inspected:
            return False, identity
        if verdict.abstained or verdict.visual_deviations:
            return False, identity
        if verdict.prompt_change:
            # A run whose verdict also changed the prompt is not a run
            # of the converged prompt: the next cycle is the first that
            # exercises the new text.
            return False, identity
        if not record.passed:
            return False, identity
    return True, identity
