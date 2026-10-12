"""The system prompt as a VERSIONED artifact.

The prompt is the tunable part of this harness, so it is not a string
literal buried in a renderer — it is an addressable revision with an
identity the iteration log can cite and a predecessor it can be rolled
back to.

LL3M's finding is the reason each revision differs from its predecessor
by exactly ONE element: surgical edits to a working prompt outperform
rewrites, and a rewrite destroys the attribution that makes the next
edit informed. So `PROMPT_REVISIONS` reads as a diff history, and every
entry after v1 carries the hypothesis that motivated it and the outcome
that was measured — the record 3DCodeBench's Experience Library keeps,
in the artifact it is about. The Prompt Report's field note that prompts
are sensitive to detail without obvious reason (DOI
10.48550/arXiv.2406.06608) is why a pin needs repeated clean runs, not one.

This module is the REGISTRY, not the text. Each body lives in
`prompts/working_agreement_v{n}.md.j2` so it can be read and reviewed as
prose; what a file cannot carry — why the revision exists and what it
measured — lives here. `validate_revisions()` checks the two agree, and
enforces by measurement the discipline the old chained-`.replace()`
build enforced by construction.

Adding a revision: see `prompts/README.md`. In short — copy the previous
template, change ONE element, state `hypothesis` BEFORE running it, fill
`outcome` from the measurement rather than impression, and move
PINNED_PROMPT_REVISION (ACTIVE_PROMPT_REVISION follows it) only once
the measurement supports it, through `make pin`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class PromptRevision:
    """One revision of the working agreement, with its provenance."""

    revision: int
    changed_element: str  # the ONE thing this revision changed
    hypothesis: str  # stated BEFORE the run: "changed X because Y; expect Z"
    outcome: str  # filled from measurement AFTER the run; "" while pending

    @property
    def body(self) -> str:
        """The prompt text, rendered from `prompts/`.

        Read from disk rather than stored here so the text is a file a
        person or an agent can open, diff and review on its own terms.
        This registry keeps what a file cannot: why the revision exists
        and what it measured.
        """
        from blended.agent.prompt_templates import render_working_agreement

        return render_working_agreement(self.revision)

    @property
    def identity(self) -> str:
        """Content hash: proves which text actually ran."""
        digest = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        return f"v{self.revision}:{digest[:12]}"


PROMPT_REVISIONS: tuple[PromptRevision, ...] = (
    PromptRevision(
        revision=1,
        changed_element="(baseline)",
        hypothesis="(baseline — written from the research brief, never scored)",
        outcome=(
            "Iteration 2: both briefs passed both deterministic gates with "
            "zero visual deviations, but planter_box never terminated — it "
            "met every done-condition, then exported unprompted and "
            "exhausted its 16-call budget, returning 'Stopped after 16 tool "
            "calls in one turn without reaching an answer'. three_leg_stool "
            "terminated cleanly at 12 calls. Classified: prompt failure, no "
            "terminal state defined."
        ),
    ),
    PromptRevision(
        revision=2,
        changed_element=(
            "Added a terminal state to 'What done means': when all three "
            "conditions hold, stop calling tools and report."
        ),
        hypothesis=(
            "Changed the done-definition to name an explicit STOP, because "
            "v1 listed three done-conditions but never said what to do once "
            "they held — so the agent treated 'done' as an internal "
            "checklist and kept working past it. Expect planter_box to end "
            "with a final report in fewer tool calls, and three_leg_stool, "
            "which already terminated, to be unaffected."
        ),
        outcome=(
            "CONFIRMED for planter_box: 17 tool calls -> 3, ending in a "
            "written report instead of 'Stopped after 16 tool calls'. Both "
            "gates passed. NOT sufficient for three_leg_stool: it still "
            "exhausted 16 calls and now FAILED the form gate "
            "(base_z -0.0043 m against a 0.002 m tolerance, total height "
            "0.4543 m). It spent 4 calls discovering there was no rotate "
            "op, and never re-checked grounding after its final union."
        ),
    ),
    PromptRevision(
        revision=3,
        changed_element=(
            "Added, before the terminal state: the gate measures structure "
            "not intent, so verify the user's stated numbers by measuring "
            "the finished object after the last operation."
        ),
        hypothesis=(
            "Changed the done-definition to require measuring the brief's "
            "own numbers, because three_leg_stool passed the structural "
            "gate with its feet 4.3 mm below z=0 and its height 4.3 mm "
            "over — drift introduced by the final boolean union, which "
            "nothing in the loop ever re-checked, and which the analyzer "
            "gate cannot see because it does not know the brief. Expect "
            "base_z and total_height_z inside tolerance, and planter_box "
            "(already passing in 3 calls) to stay passing."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 4: base_z -0.0043 -> "
            "+0.0000 m and total_height_z 0.4543 -> 0.4500 m, both exact, "
            "and the agent printed its own measurements after the final "
            "boolean. NOT sufficient overall — the run still exhausted "
            "its budget (20 calls / 16 turns) without answering, and the "
            "human rejected the feet: one sole was angled, which base_z "
            "cannot see. Both were classified harness-code, not prompt, "
            "so v3 stands unchanged into iteration 5: search_ops now "
            "matches words (3 wasted turns returned), the budget counts "
            "and reports real calls, and GroundContactProbe measures "
            "sole contact as an area."
        ),
    ),
    PromptRevision(
        revision=4,
        changed_element=(
            "Tool discipline: replaced 'call search_ops when you need an "
            "operation you have not used' with a statement that the "
            "listed vocabulary is complete and must not be searched for."
        ),
        hypothesis=(
            "Changed the search instruction because the prompt contains "
            "all 20 operations with their exact signatures and then tells "
            "the agent to go and look operations up. Measured: "
            "three_leg_stool spent 6 of 16 calls on search_ops in "
            "iteration 4 and 5 of 16 in iteration 6, and every single op "
            "it searched for — boolean_union, add_cylinder, "
            "assign_material, boolean_difference, add_box, "
            "rotate_object_euler, move_object_to, add_bevel — was already "
            "printed in its own system prompt. That is 31-37 percent of "
            "the budget spent re-deriving what it was handed, on the one "
            "brief that has now failed to terminate three times running. "
            "Expect three_leg_stool to reach a written answer inside its "
            "budget, and planter_box (which already answers in 3 calls "
            "and searched for nothing) to be unaffected."
        ),
        outcome=(
            "CONFIRMED, iteration 7: 16 tool calls -> 5, and the run "
            "TERMINATED with a written report for the first time in four "
            "attempts on this brief. Zero search_ops calls. Structural "
            "PASS; base_z +0.0000 m and total_height_z 0.4500 m both "
            "exact; material assigned; and the agent correctly explained "
            "the +0.0048 m seat_diameter_x delta as the splayed foot "
            "protruding past the seat rim rather than treating it as a "
            "defect. One failure remains, unrelated to this edit: all "
            "three soles are angled (zero flat contact area)."
        ),
    ),
    PromptRevision(
        revision=5,
        changed_element=(
            "Added to the measure-your-own-numbers paragraph: resting on "
            "a surface is a contact, not a height — a part that stands on "
            "the floor must meet it with a flat face."
        ),
        hypothesis=(
            "Changed it because 'feet on the ground at z=0' is being read "
            "as a height and satisfied by the lowest point. Measured "
            "across iterations 4 and 7: base_z +0.0000 m exactly, every "
            "foot probe solid, and every sole still angled — 7 non-level "
            "faces per foot spanning 0.41-0.43 m in z, zero flat contact "
            "area. The agent verifies the number it was given and the "
            "number is not the requirement. Expect the three "
            "leg_N_sole_is_flat_on_the_ground probes to report contact "
            "area above the minimum, and the 5-call termination from v4 "
            "to survive."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 9: all three soles went "
            "from 0.000000 m2 of flat contact to 0.001459 m2 each — 14.6x "
            "the required minimum — and base_z stayed at +0.0000 m. This "
            "is the defect the human caught by eye at iteration 4 and the "
            "gate could not see; it is now built correctly and measured. "
            "NOT a passing run overall, and the failures are new ones: "
            "the material was never assigned (0 in 1 slot), "
            "seat_diameter_x reached 0.3798 m (+0.0598, outside the "
            "0.0200 tolerance) as the legs splayed past the seat rim, and "
            "the run again used all 16 calls without answering — v4's "
            "5-call termination did NOT survive."
        ),
    ),
    PromptRevision(
        revision=6,
        changed_element=(
            "Added a 'Changing something they already have' section: "
            "follow-up instructions are localized edits that preserve the "
            "rest of the asset, the gate and a render are re-run after "
            "each one, and the turn ends on the user's approval."
        ),
        hypothesis=(
            "Added it because the harness code standards REQUIRE a "
            "user-guided refinement phase and v5 contains none — it says "
            "how to build an asset and stop, and nothing about changing "
            "one that exists, so a follow-up instruction invites a full "
            "rebuild that discards approved work. This is a compliance "
            "gap, not an observed run failure: v5 converged without it "
            "only because no brief exercised a second turn. The briefs "
            "now carry a RefinementStep, so it is measurable. Expect "
            "first-build behaviour unchanged (the section governs only "
            "follow-ups), so runs should stay near 7-10 calls with both "
            "gates clean, AND the taller_stool follow-up to reach 0.55 m "
            "while every other dimension, foot radius and leg bearing "
            "stays where it was."
        ),
        outcome=(
            "Iteration 14, the first run to exercise a RefinementStep: "
            "both deterministic gates PASS and the refinement gate PASS "
            "— total_height_z 0.4500 -> 0.5500 m exact, 2 dimensions "
            "and 3 foot placements preserved with 0 disturbed, soles "
            "0.001522 m2 flat contact each at bearings 0.0/120.0/240.0 "
            "deg, material 1-in-1, 21 tool calls of 24 (16 first build, "
            "5 refinement) ending in a written report. The human "
            "confirmed the render with zero visual deviations. The "
            "section's first-build prediction held. Its CENTRAL "
            "instruction did not: told to change one dimension, the "
            "agent re-ran add_cylinder / boolean_union / ground-cut "
            "from scratch at 0.55 m rather than editing the stool in "
            "front of it. No gate could see it — a rebuild from the "
            "same constants lands on the same numbers, which is exactly "
            "what preservation compares. The human ruled the rebuild "
            "ACCEPTABLE, which makes the examiner's finding a false "
            "positive (mistake memory: "
            "the-critique-called-a-clean-rebuild-a-failure) and makes "
            "v6's 'Do not rebuild it from scratch' a demand nothing "
            "enforces and nobody wants enforced. Superseded by v7."
        ),
    ),
    PromptRevision(
        revision=7,
        changed_element=(
            "Softened the opening of 'Changing something they already "
            "have' from an absolute prohibition on rebuilding to a "
            "preference for editing, with the preservation of settled "
            "detail as the binding requirement instead."
        ),
        hypothesis=(
            "Changed it because iteration 14 rebuilt the stool at "
            "0.55 m, preserved every unnamed measurement exactly, and "
            "the human ruled that acceptable. v6 forbids in words what "
            "the loop permits in measurement: an instruction that can "
            "be violated with no consequence and no signal teaches the "
            "reader which lines are decorative. v7 keeps the reason "
            "(seconds versus minutes) and the requirement that survives "
            "scrutiny (nothing settled may be lost), and drops the ban "
            "that does not. Expect iteration 15 to measure as 14 did — "
            "both gates clean, the refinement preserving every unnamed "
            "number — with the run no longer in conflict with its own "
            "instructions, and `refinement_locality` in the log "
            "recording which way the follow-up went."
        ),
        outcome=(
            "CONFIRMED on its own target across iterations 15-17. "
            "Iteration 15 (three_leg_stool): both gates PASS, "
            "refinement PASS with 0 unnamed measurements disturbed, 18 "
            "tool calls (down from 21 at v6), and LOCALITY recorded "
            "'rebuilt (stamped 9337507e4ccd, found no stamp)' — the "
            "follow-up replaced the datablock, which v7 permits and the "
            "gate correctly did not fail. The instruction and the "
            "measurement agree for the first time. Iteration 16 "
            "(planter_box): both gates PASS at 12 calls, every "
            "dimension exact. Human confirmed both renders, zero "
            "deviations. NOT a converging sequence: iteration 17 "
            "(three_leg_stool) FAILED the form gate at 10 calls — all "
            "three sole centres at r=0.1281 m against 0.1400 +/- "
            "0.0100. Unrelated to this edit: v7 changed only the "
            "follow-up paragraph, and 17 failed on its FIRST build, "
            "before any follow-up ran. Superseded by v8, which "
            "addresses that failure."
        ),
    ),
    PromptRevision(
        revision=8,
        changed_element=(
            "Extended the contact paragraph: a position the user "
            "specified belongs to the contact patch, not to the axis "
            "that produced it."
        ),
        hypothesis=(
            "Changed it because iteration 17 placed all three leg base "
            "centres at r=0.1400, cut them flat at z=0, and the "
            "surviving ellipse's centroid landed at r=0.1281 on every "
            "foot — 11.9 mm inboard, past the 0.0100 tolerance — while "
            "the run's own report claimed 'each foot's axis landing on "
            "radius 0.14'. It measured, and measured the wrong feature: "
            "v5 taught it that resting is a contact rather than a "
            "height, and it now produces a flat sole and then verifies "
            "the axis that made it. The number is not incidental: "
            "0.1281 is exactly what the harness's own reference fixture "
            "produced before it was fixed (mistake memory: "
            "the-reference-stool-put-its-soles-inboard), so this is a "
            "known geometric trap, not run-to-run noise, and the "
            "tolerance was deliberately not loosened when the fixture "
            "hit it. Expect all three sole centres inside 0.1400 +/- "
            "0.0100, with the flatness, spacing, termination and "
            "refinement behaviour of v5-v7 unchanged."
        ),
        outcome=(
            "CONFIRMED on its target, iteration 18: all three sole "
            "centres measured r=0.1400 m exactly (from 0.1281), "
            "bearings 0.0/120.0/240.0 deg, flat contact 0.001228 m2 "
            "each, both gates PASS, refinement PASS with 0 disturbed, "
            "and 7 tool calls — the shortest run the suite has "
            "produced. The sentence worked. SUPERSEDED ANYWAY, by "
            "decision rather than by measurement: the trap was "
            "reclassified harness_code and moved into the builder API "
            "(blended/ops/legs.py), because prose that asks the model "
            "to re-derive trigonometry has to be re-derived on every "
            "run, while an op that cannot be called wrongly does not. "
            "Iteration 18 was not human-verified; no convergence claim "
            "rests on it."
        ),
    ),
    PromptRevision(
        revision=9,
        changed_element=(
            "Reverted v8's contact-position sentence. The text is "
            "byte-identical to v7 again."
        ),
        hypothesis=(
            "Reverted because v8 was an edit made under a "
            "classification that was wrong. Iteration 17 was called a "
            "prompt failure; it is a harness_code failure, and the "
            "loop's own discipline says a harness_code failure is "
            "fixed by coding and permits no prompt edit. The fix now "
            "lives in blended.ops.legs, which owns the placement "
            "arithmetic and is exposed to the agent through the "
            "generated manifest, so the sentence is redundant — and "
            "keeping it would leave the loop unable to tell which of "
            "the two fixed the run. Expect iteration 19 to hold "
            "iteration 18's sole placement (r=0.1400 +/- 0.0100 on all "
            "three feet) with the sentence gone, because the op "
            "supplies it. If placement regresses, the op is present "
            "but unused, and the answer is to make it the obvious call "
            "in the manifest — not to restore the prose."
        ),
        outcome=(
            "CONFIRMED, and CONVERGED. Iteration 19 answered the "
            "question the revert was written to ask: with v8's sentence "
            "gone, the agent reached for add_splayed_leg unprompted (23 "
            "references in its transcript) and sole centres held at "
            "r=0.1400 m exactly on all three feet. The geometry came "
            "from the op, not the prose. Then three consecutive "
            "human-verified clean runs on the settled harness: "
            "iteration 20 planter_box (8 calls), 21 three_leg_stool (9 "
            "calls, refinement 0 disturbed), 22 planter_box (3 calls, "
            "the fewest any run has taken). Iterations 15, 16 and 19 "
            "ran this same TEXT and are NOT counted: 15 and 16 predate "
            "the leg ops, 19 predates the removal of the smart_unwrap "
            "shim, and 'no prompt change between them' has to mean the "
            "bytes the agent actually received."
        ),
    ),
    PromptRevision(
        revision=10,
        changed_element=(
            "Added, to the 'gate measures STRUCTURE, not intent' "
            "paragraph: every feature the brief NAMES must exist as "
            "real geometry, not be approximated or skipped."
        ),
        hypothesis=(
            "Changed it because iteration 31 (ribbed_column) built a "
            "plain 0.20 m cylinder with NO ribs: the brief named a "
            "0.16 m shaft with five ribs reaching 0.20 m, and the "
            "agent read '0.20 m in diameter' as the shaft and skipped "
            "the rib geometry entirely — rib_crest_is_solid at radius "
            "0.09 read empty. The brief was self-consistent; the "
            "working agreement v9 never told the agent that a named "
            "feature is a build requirement, not a suggestion. Expect "
            "ribbed_column to build the five ribs as real material "
            "reaching the named diameter, and the other four briefs "
            "to be unaffected (they already build their named "
            "features)."
        ),
        outcome=(
            "CONFIRMED on its target, and CONVERGED. Iteration 37 "
            "(ribbed_column, first run of v10) built five ribs reaching "
            "the named 0.20 m diameter — the sentence worked; the run "
            "failed only on a probe the brief had not pinned (rib "
            "positions), which was a bad_brief fix, not a prompt one. "
            "Then the five-brief convergence rule was met: iterations "
            "47-51, one clean human-verified run per brief, consecutive, "
            "no prompt change between them — three_leg_stool (23 calls, "
            "three refinement steps, 0 disturbed), planter_box (15), "
            "uv_crate (22, 1 UV island, 0 overlaps), ribbed_column (6), "
            "crate_with_lid (14, both relations OK). The four "
            "pre-existing briefs were unaffected by the sentence, as the "
            "hypothesis predicted; the harness defects the five-brief "
            "suite surfaced (refinement composition, silent boolean "
            "no-op, shared-material destruction) were all classified "
            "harness_code and fixed by coding."
        ),
    ),
    PromptRevision(
        revision=11,
        changed_element=(
            "Added a 'Beyond the mesh: rigs, weights, animation, "
            "materials' section after Tool discipline: each domain names "
            "its ops and the inspect_domain report that verifies it."
        ),
        hypothesis=(
            "Added because the chat now covers rigging, weight painting, "
            "animation and node materials (ops.rigging / weights / "
            "animation / material_nodes, tool inspect_domain), and v10 "
            "only ever speaks of the mesh gate — a writer told 'done "
            "means the gate passed' has no verification step for an "
            "armature or an action and either skips it or raw-bpy's it. "
            "Expect the six chat E2E scenarios (scripts/chat_e2e.py) to "
            "pass their domain assertions, and the five mesh briefs plus "
            "the 3DCodeBench frozen-20 to be unaffected (the mesh text "
            "is byte-identical)."
        ),
        outcome=(
            "CONFIRMED on its target, 2026-09-04: scripts/chat_e2e.py "
            "passed 6/6 on two independent rolls (object/rig/weights/"
            "animation/material/iterative; tool calls 10/11/12/3/5/3 and "
            "17/9/4/6/2/2), zero raw bpy.ops in any transcript, every "
            "domain scenario reached for the named ops and read "
            "inspect_domain back. Still a candidate: the frozen-20 bench "
            "guard and the human pin remain (make pin)."
        ),
    ),
    PromptRevision(
        revision=12,
        changed_element=(
            "Rewrote the 'How you work' opening paragraph: a step is an "
            "op-tool call (bound, run, gated per call), or a Python chunk "
            "only when no op fits; run_python is the escape hatch and must "
            "name in `reason` the operation that was missing."
        ),
        hypothesis=(
            "Changed because OT-3..OT-6 made every facade op a tool (bound "
            "to its signature, gated when it returns an object, plan-"
            "required), and OT-7 makes run_python refuse a blank reason — "
            "but v11 still opens by telling the writer to work in Python "
            "chunks through run_python, so a v11 writer reaches for the "
            "hatch first and is refused. Expect, on the five briefs within "
            "three paired rolls on the convergence writer: escape-hatch "
            "calls per gate-passing brief below 1.0 (measured from the v2 "
            "transcripts' candidate_op records, OT-8/OT-12); executability "
            "and cd_pca on the frozen-20 per the ops-lane pre-registration "
            "(docs/2026-09-06-bench-panel-preregistration.md, OT-9)."
        ),
        outcome=(
            "MEASURED ONCE, 2026-09-10, Claude Code lane; no claim yet. "
            "Chat E2E with run_python WITHHELD (--no-hatch): 6/6 scenarios "
            "(object/rig/weights/animation/material/iterative), tool calls "
            "8/10/9/8/8/12, zero hatch attempts. Five-brief roll (iterations "
            "68-73): stool, uv_crate and column passed both deterministic "
            "gates with 6, 1 and 2 hatch calls — 3.00 per gate-passing "
            "brief against the < 1.0 target; planter FAILED the form gate "
            "twice (location_m read as a centre, base at z 0.125; 0 hatch "
            "calls on the re-run); crate_with_lid died on the lane's "
            "structured-output retry limit before a record was written. "
            "Cost: 58k tokens per call with 50 tools vs 26k with 8. Still "
            "a candidate: the frozen-20 paired rolls (OT-9) and the human "
            "pin remain."
        ),
    ),
    PromptRevision(
        revision=13,
        changed_element=(
            "'How you work' opening: 'and the rest listed below' -> 'and the "
            "rest of your tool list'. The prompt no longer prints the ops "
            "(OT-24); the sentence must not promise a list that is not there."
        ),
        hypothesis=(
            "Wording only. Expect the five briefs to pass with the hatch "
            "withheld exactly as on v12, and per-call tokens unchanged (the "
            "removal itself is v14's hunk)."
        ),
        outcome=(
            "Not run alone: superseded by v14 the same hour, which carries "
            "this hunk. Measured through v14 (below)."
        ),
    ),
    PromptRevision(
        revision=14,
        changed_element=(
            "Tool discipline: the 'listed below ... do not search for it' "
            "bullet becomes 'a tool in your tool list, with its exact schema "
            "... search_ops finds an operation by keyword and returns its "
            "schema — one call, then use it'. Ships with the manifest's "
            "operations section removed from the prompt (OT-24)."
        ),
        hypothesis=(
            "Changed because the ops were described twice per call — 3,074 "
            "tokens of manifest prose beside 7,904 of schemas on bmb's "
            "tokenizer (OT-23) — and v12 told the writer not to use "
            "search_ops. Expect the five briefs to pass with the hatch "
            "withheld with at most one search_ops call each, the system "
            "prompt to drop by ~3,000 tokens, and hatch calls per gate-"
            "passing brief unchanged when the hatch is offered."
        ),
        outcome=(
            "MEASURED ONCE, 2026-09-10, Claude Code lane, hatch withheld: all "
            "five briefs passed both gates (iterations 81 planter 13 calls, "
            "86 stool 56 calls with three refinements, 83 uv_crate 10, 84 "
            "column 8, 85 crate_with_lid 21), zero search_ops calls; chat "
            "E2E 6/6 in 46 tool calls (55 on v12). The system prompt fell "
            "from 7,569 to 4,482 tokens on bmb's tokenizer (-3,087); static "
            "per call 16,814 -> 13,727 on the OpenAI/Ollama lanes. The "
            "hatch-offered reading (hatch calls per gate-passing brief) is "
            "not yet measured on v14. Still a candidate."
        ),
    ),
)

# --- CONVERGED --------------------------------------------------------
# v10 is PINNED, superseding the v9 pin of earlier the same day. The
# rule for THIS attempt (recorded in
# docs/2026-08-22-prompt-convergence-plan.md Phase 3): one clean
# human-verified run per brief, CONSECUTIVE, with no prompt change
# between them — five runs. Met 2026-08-22:
#
#   iteration 47  three_leg_stool    23 calls  both gates PASS  0 deviations
#   iteration 48  planter_box        15 calls  both gates PASS  0 deviations
#   iteration 49  uv_crate           22 calls  both gates PASS  0 deviations
#   iteration 50  ribbed_column       6 calls  both gates PASS  0 deviations
#   iteration 51  crate_with_lid     14 calls  both gates PASS  0 deviations
#
# All five terminated with a written report, all five exported
# round-trip-verified .glb files, and the human confirmed every render.
# The stool run also passed all THREE refinement steps (taller, wider
# seat, thicker legs) with 0 unnamed measurements disturbed — the
# multi-step refinement gate v9 was never asked to run.
#
# WHAT v10 CHANGED. One sentence added to the "gate measures STRUCTURE,
# not intent" paragraph: every feature the brief NAMES must exist as
# real geometry, not be approximated or skipped. Made because
# iteration 31 (ribbed_column) built a plain 0.20 m cylinder with NO
# ribs — the brief named a 0.16 m shaft with five ribs reaching
# 0.20 m, and the agent read the diameter as the shaft and skipped the
# rib geometry entirely. The sentence is the one element between v9
# and v10; the rest of the text is byte-identical.
#
# WHAT THE RUNS COST. The five-brief suite found three harness defects
# and two under-determined briefs before it converged: a refinement
# scorer that graded each step against the ORIGINAL brief instead of
# the accumulated one (iteration 23), a boolean that silently no-opped
# (iteration 33 — now guarded by BooleanNoOp, which compares geometry,
# not counts, because the EXACT solver cuts a tilted cap flat while
# preserving counts), and assign_material destroying a shared material
# datablock (iteration 46 — now reuses the datablock). ribbed_column
# needed its shaft diameter, rib centers, and rib thickness pinned
# (iterations 27/37/41). Each was classified into exactly one bucket
# and fixed in the right artifact; the prompt changed only once.
#
# The v9 pin was earned on its own harness and is not disowned: it is
# in the append-only log, and v9 still carries its outcome above. Its
# three runs (20/21/22) were against the two-brief suite, which is why
# v10 re-ran the sequence on the five-brief suite.
#
# The evidence is MODEL-SPECIFIC and the log records it per run.
# v1-v4 were scored against deepseek-v4-flash, which never converged
# this suite; v9 and v10 were scored against deepseek-v4-pro, which
# holds the pin.
PINNED_PROMPT_REVISION = 10
CONVERGED_ON = "2026-08-22"
CONVERGENCE_RUNS = (
    (47, "three_leg_stool"),
    (48, "planter_box"),
    (49, "uv_crate"),
    (50, "ribbed_column"),
    (51, "crate_with_lid"),
)
# PROVENANCE, NOT THE SHIPPED DEFAULT. This names the writer whose runs
# MINTED the golden references in _evaluate/golden — which is why the
# visual gate reports drift for any other writer by construction, and
# why this constant must not be repointed without re-minting them
# (`make pin-golden-views`, the one act reserved for a human: RESP
# measures a wrong reference as worse than none at all, -0.23 F1,
# 10.48550/arXiv.2604.11082).
#
# The shipped default writer is claude-code:sonnet, which qualified on
# the same five-brief suite at this prompt on 2026-09-05 (iterations
# 52-56: structural, form and refinement gates green on 5/5, first
# attempt). That claim is guarded against the append-only run log by
# tests/pure/test_prompt_templates.py::
# test_the_shipped_configuration_is_the_converged_configuration, which
# is stronger evidence than a constant equal to another constant.
CONVERGENCE_WRITER_MODEL = "deepseek-v4-pro:cloud"
# The v10 runs recorded minimax-m3:cloud as their eye (iterations.jsonl
# 47-51), but that model was measured broken on 2026-08-24: it answers
# in message.thinking and returns empty content, so every examiner call
# fails the JSON contract. kimi-k2.7-code replaced it that day on
# calibration evidence alone (sensitivity 0.80, control specificity
# 1.00) — the eye slot is earned by CALIBRATION, not by re-running the
# convergence suite, because the eye does not write the runs.
#
# claude-code:sonnet takes the slot on 2026-09-05 by the same standard,
# measured on the same fixture zoo: sensitivity 0.80 (4/5), control
# specificity 1.00 (5/5), problems() empty, identity
# claude-code:sonnet+examiner:60a9920cb938. Its miss is COMPLEMENTARY
# to kimi's rather than worse — kimi missed lid_offset and saw
# floating_seat, claude-code missed floating_seat and saw lid_offset.
# Both calibrations are kept: _evaluate/eye_calibration.json is the
# licensed one (identity-bound, so it must match the eye in use) and
# _evaluate/eye_calibration_kimi.json is the superseded record. Why
# this eye is the default: it is the WRITER's own model, so a render
# reaches the writer as a native image block instead of a prose
# summary, and RESP measures the reference-paired path at recall 0.76
# against 0.28 for no reference (10.48550/arXiv.2604.11082).
CONVERGENCE_VISION_MODEL = "claude-code:sonnet"
CONVERGENCE_TOOL_CALL_BUDGET = 24

# Revisions above the pin are CANDIDATES: scripts/chat_e2e.py runs one
# explicitly (build_system_prompt(revision=n)) and records its outcome;
# it becomes the shipped text only through `make pin`, the one human act.
ACTIVE_PROMPT_REVISION = PINNED_PROMPT_REVISION


# LL3M's one-element rule used to be enforced by construction: each body
# was built by `.replace()` on its predecessor and raised if the anchor
# text had moved. Templates are far easier to read and review, and they
# lose that guard — nothing stops a file from being quietly rewritten.
# So the rule is enforced by MEASUREMENT instead, which is stricter: a
# revision must differ from its predecessor by exactly one contiguous
# run of changed lines.
MAXIMUM_CHANGED_HUNKS_PER_REVISION = 1


def changed_hunks(previous_body: str, body: str) -> list[str]:
    """The contiguous runs of changed lines between two revisions."""
    import difflib

    matcher = difflib.SequenceMatcher(
        None, previous_body.splitlines(), body.splitlines(), autojunk=False
    )
    hunks: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        hunks.append(f"{tag} lines {i1}-{i2} -> {j1}-{j2}")
    return hunks


def validate_revisions() -> list[str]:
    """Schema and discipline problems (empty list = a healthy history).

    Checks what a reader would otherwise have to take on trust: the
    revisions are consecutive from 1, each has a template that renders,
    each differs from its predecessor by one hunk and by SOMETHING, and
    every revision before the active one has recorded what it measured.
    """
    problems: list[str] = []
    numbers = [entry.revision for entry in PROMPT_REVISIONS]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"revisions are not consecutive from 1: {numbers}")
    previous: PromptRevision | None = None
    for entry in PROMPT_REVISIONS:
        try:
            body = entry.body
        except Exception as error:  # noqa: BLE001 — reported, not raised
            problems.append(f"v{entry.revision}: template did not render: {error}")
            previous = None
            continue
        if not body.strip():
            problems.append(f"v{entry.revision}: template rendered empty")
        if previous is not None:
            hunks = changed_hunks(previous.body, body)
            if not hunks:
                problems.append(
                    f"v{entry.revision} is identical to v{previous.revision}: "
                    f"a revision that changes nothing cannot be attributed"
                )
            elif len(hunks) > MAXIMUM_CHANGED_HUNKS_PER_REVISION:
                problems.append(
                    f"v{entry.revision} changes {len(hunks)} separate places "
                    f"in v{previous.revision}, not one: {hunks}. Surgical "
                    f"edits beat rewrites (LL3M); split it into revisions."
                )
        if not entry.hypothesis.strip():
            problems.append(f"v{entry.revision}: no hypothesis recorded")
        if entry.revision < ACTIVE_PROMPT_REVISION and not entry.outcome.strip():
            problems.append(
                f"v{entry.revision} was superseded without recording what it "
                f"measured — the next edit would be uninformed"
            )
        previous = entry
    return problems


class UnknownPromptRevision(KeyError):
    """Raised when a revision number has no entry. There is no default."""


def get_revision(revision: int | None = None) -> PromptRevision:
    """Return one revision. `None` means the active one.

    Unknown revisions raise. A convergence loop that silently fell back
    to the active prompt when asked for v3 would attribute v3's score to
    text that never ran.
    """
    wanted = ACTIVE_PROMPT_REVISION if revision is None else revision
    for entry in PROMPT_REVISIONS:
        if entry.revision == wanted:
            return entry
    available = ", ".join(str(entry.revision) for entry in PROMPT_REVISIONS)
    raise UnknownPromptRevision(f"No prompt revision {wanted}. Available: {available}.")


def latest_revision() -> PromptRevision:
    return max(PROMPT_REVISIONS, key=lambda entry: entry.revision)
