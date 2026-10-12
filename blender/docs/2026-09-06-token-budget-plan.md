# Token budget — plan (2026-09-06)

Evidence base: `docs/2026-09-06-token-budget-audit.md` (all numbers
measured today). Literature via home-still; every decision below cites
the paper that argues for it, by DOI, so another agent can look it up.

## The reframing that orders this plan

The right objective is NOT tokens per run. It is **cost-of-pass**:
`v(m,p) = C_m(p) / R_m(p)`, cost divided by the probability of a
passing result — `10.48550/arXiv.2504.13359`. A change that saves 30%
of the tokens and halves the pass rate makes things worse.

Applying that metric to today's measurements is uncomfortable:

| | measured 2026-09-06 |
|---|---|
| one brief, examiner off | 26 API calls, 738,839 input tok, $1.4182 |
| examiner, per brief | 10 eye calls, ~83k tok |
| a 5-brief cycle | ~$7 and ~3.7M input tok, examiner on top |
| cycles run today | 3 |
| cycles that converged | **0** |

`R = 0`, so the cost-of-pass of the convergence loop is currently
**infinite**, and no token saving can improve an infinite number. The
binding problem is not the price of a cycle — it is that three cycles
in a row could not converge because the examiner reported deviations
that moved between briefs (`material_missing` on uv_crate, then
ribbed_column, then planter_box), including one flagged against an
exemplar minted from its own lane's clean run.

So the plan fixes the instrument FIRST, and takes the token saving from
the same change. That ordering is not a preference: with `R = 0`, work
on `C` is unmeasurable.

## Decisions (locked before implementation)

| # | Decision | Evidence |
|---|---|---|
| D1 | **Cost-of-pass is the reported metric**, not tokens. Every phase reports cost per CLEAN run and per converged cycle. | `10.48550/arXiv.2504.13359` (cost-of-pass = cost / pass rate; capability and cost must not be reported separately) |
| D2 | **Measure the examiner in the regime it is used.** Its licence was earned on controls where candidate and reference come from the SAME run (pixel-identical). The loop compares a FRESH run against an exemplar. Add a cross-run control class and license against that. | `10.48550/arXiv.2606.15693` (one false alarm on a clean control ends refinement early); `10.48550/arXiv.2504.01786` (verifier-human alignment 0.66 vs 0.79 inter-human — the instrument's error rate is first-class) |
| D3 | **Keep both orderings per comparison.** Position bias is real and the order-consistency filter is what keeps false alarms out. Cutting it would buy tokens with reliability. | `10.48550/arXiv.2306.05685` (MT-bench position bias); `10.48550/arXiv.2504.01786` (measured judge position bias on 3D edits) |
| D4 | **Batch the five views into one call per ordering** (10 calls -> 2). Multi-image delivery on this lane is verified unfused and in order; the reference stays paired with the candidate. | `10.48550/arXiv.2604.11082` (RESP: reference pairing 0.28 -> 0.76 recall; a WRONG reference is worse than none, so pairing must survive batching) |
| D5 | **Static work is amortized, never re-derived.** The system prompt stays byte-stable and history append-only, because that is what makes the cache read at 0.1x instead of writing at 1.25x (11.8x measured). | `10.48550/arXiv.2504.13171` (sleep-time compute: precomputing on the static context reaches comparable quality with 5x fewer test-time tokens) |
| D6 | **Deterministic gates keep precedence.** Nothing here lets a cheaper examiner override a measurement. | `10.48550/arXiv.2409.02977` (tool feedback outranks model feedback) |
| D7 | **No change ships without its own measurement.** Each phase names the number that licenses it and the number that rejects it. | repo rule "validation = assertions"; `10.48550/arXiv.2305.11206` (tie-discounted agreement as the way to compare two instruments on shared items) |

Non-goals, explicitly: leaving the CLI for the metered API (Phase E
supplies the number first); the per-message block fold (measured and
rejected — write 1,374/5,369/5,169 merged vs 2,057/3,242/6,102
per-message); pruning transcript history (Phase D only, and only with
the cache trade written down); touching the pinned system prompt text.

## Decisions the user signed, 2026-09-06

| question | answer | consequence |
|---|---|---|
| Phase B branch | **B2'** — restrict the eye to vision-only defects | implemented below |
| Phase C timing | **Sequential** — prove B, then batch | C waits for a clean B re-licence; costs one extra calibration run (~$1) and buys unambiguous attribution |
| Binding currency | **Neither** — $7/cycle and the window are both acceptable | **Phases D and E are DROPPED.** Effort goes to capability. Phase A already fixed the thing that was actually wasting money, and the accounting stays because it is how a regression becomes visible |
| Criterion 4 | **>=3-roll mean +/- SD** | restated in the success criteria; a claimed bench improvement must exceed its own spread |
| Criterion 5 | **Live walkthrough first** | a driven turn with per-step screenshots before sign-off |

## Phase A — measure the instrument where it is used

**Files.** `scripts/calibrate_examiner.py`,
`src/blended/evaluate/examiner.py`,
`src/blended/evaluate/iteration_log.py` (verdict rows),
`tests/pure/test_examiner.py`.

**Change.**
1. New control class `cross_run`: candidate = clean run B, reference =
   exemplar minted from clean run A, same brief / lane / prompt
   identity. Both must have passed every deterministic gate, so any tag
   the examiner emits is a false alarm by construction. Sources exist
   already: `_evaluate/iterations.jsonl` rows 52-65 hold several
   gate-clean claude-lane runs per brief at v11.
2. Named constants, no literals:
   `CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY = 1.0` (the existing
   `REQUIRED_CONTROL_SPECIFICITY`, applied to the new class),
   `CROSS_RUN_CONTROL_PAIRS_PER_BRIEF`.
3. `IterationVerdict` gains `view_tags: tuple[tuple[str, tuple[str, ...]], ...]`
   — per view, the order-consistent tags. Costs nothing and turns
   "which views earn their calls" into evidence instead of opinion.

**Terminal state.** `_evaluate/eye_calibration.json` carries
`cross_run_control_specificity` alongside the same-run number;
`_evaluate/verdicts.jsonl` carries per-view tags for every new row.

**Acceptance.** The calibration record reports both specificities and
`problems()` names any threshold miss. A run of
`make calibrate-eye ARGS="--only cross-run"` prints the per-brief
false-alarm table.

## Phase A — DONE. Terminal state reached.

`cross_run` control class in `scripts/calibrate_examiner.py`
(`--cross-run-only`), `CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY` and
`CROSS_RUN_CONTROL_PAIRS_PER_BRIEF` in `evaluate/examiner.py`,
`Calibration.cross_run_control_specificity` reported by `problems()`
(None means "not measured", never "failed"), and
`IterationVerdict.view_tags` recording per-view order-consistent tags.
Guarded by `test_a_licence_measured_on_identical_images_does_not_cover_a_fresh_run`
and `test_a_verdict_records_which_view_earned_its_tags`.

`crate_with_lid` has no cross-run pair: its only second v11 run
(iteration 61) failed the structural gate, and a damaged candidate is
not a control. Recorded as a gap rather than papered over.

**The measured 0.50 is deliberately NOT written into
`_evaluate/eye_calibration.json` yet.** Writing it makes `problems()`
non-empty, which disqualifies the shipped examiner outright and stops
`converge_auto` from running at all. That is the Phase B decision, and
it is the user's.

### Phase A RESULT, measured 2026-09-06

`make calibrate-eye ARGS="--cross-run-only"`, 40 eye calls, 258,200
input tok, $0.4165:

| brief | candidate | verdict |
|---|---|---|
| ribbed_column | 63 vs v11 exemplar | CLEAN |
| uv_crate | 65 | CLEAN |
| planter_box | 62 | FALSE ALARM `material_missing` |
| three_leg_stool | 64 | FALSE ALARM `wrong_proportion` |

**Cross-run control specificity 0.50** against a threshold of 1.0 —
and the two that fired are exactly the two deviations that halted the
convergence cycles. A cycle needs five clean briefs at once, so at a
per-brief false-alarm rate of 0.5 a clean cycle has probability
~0.5^5 = 3%: about 32 cycles, ~$224, to reach a pin by luck. Three
failed cycles were not bad luck, they were the expected outcome, and
re-rolling was never going to work.

**And the "false alarms" are TRUE observations.** Measured
deterministically from the meshes (`outputs/cross_run_variation.py`):

| pair | dimensions | base colour |
|---|---|---|
| planter_box 57 vs 62 | identical (0.3, 0.2, 0.25) | (0.45, 0.28, 0.15) vs (0.35, 0.22, 0.12) — **distance 0.120** |
| three_leg_stool 59 vs 64 | identical joint bbox (0.4, 0.4, 0.55) | (0.45, 0.29, 0.15) vs (0.45, 0.30, 0.17) |

The examiner is not hallucinating. The candidate planter really is a
different brown, and the stool's internal proportions really do differ
inside the bbox the form gate bounds. **The loop is asking the wrong
question**: "does this match the exemplar?" is not "does this satisfy
the brief?", and everything the brief leaves free differs between runs
by construction.

## Phase B — the branch, now that the number exists

**My drafted B2 is REFUTED by Phase A and is struck.** It required a
deviation to be "reproduced in an independent examination", on the
assumption that false alarms are random. They are not: the planter
really is a different brown, so the tag reproduces every time. A
reproduction rule would have bought nothing and cost double the
examiner calls.

What the evidence supports:

- **B2' — restrict the examiner's question to what only vision can
  adjudicate (RECOMMENDED).** The reference stays paired, because
  pairing is worth +0.32 F1 (`10.48550/arXiv.2604.11082`), but the
  examiner is told which properties the brief leaves free and its tag
  vocabulary drops the ones a deterministic gate already measures.
  `wrong_proportion` and `material_missing` are exactly those two: the
  form gate measures every named dimension against a tolerance and the
  material gate measures assignment and, since 2026-09-06, colour
  contrast between named parts. Delegating a measurable property to a
  0.66-alignment judge is what D6 forbids
  (`10.48550/arXiv.2409.02977`, `10.48550/arXiv.2504.01786`).
  Cost: re-licence on the zoo. Note two zoo fixtures name the dropped
  tags — `fat_seat` (seat scaled 1.5x) and `sealed_drain` — and BOTH
  are catchable deterministically (a 1.5x seat fails the form gate's
  tolerance; the drain hole has a solidity probe), so the coverage
  loss must be measured, not assumed, before the tags go.
- **B3 — drop the exemplar, ask only "does this satisfy the brief".**
  Rejected on measured grounds: no-reference recall is 0.28 against
  0.76 with an oracle reference (`10.48550/arXiv.2604.11082`).
- **B4 — examiner advisory only; the pin rests on deterministic
  gates.** Cheapest and consistent with D6, but it gives up the visual
  net that caught the invisible crate lid — a defect no gate could
  see. Keep as the fallback if B2' fails its re-licence.

**Acceptance for B2'.** Re-measure both specificities: same-run must
stay 1.00, cross-run must reach
`CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY`, and sensitivity must stay
>= `MINIMUM_FIXTURE_SENSITIVITY` counting ONLY defects that no
deterministic gate catches. Any fixture that the gates already catch
moves to a gate test and stops being the eye's job.

### B2' RESULT, measured 2026-09-06 — improved, did NOT pass

Implemented: `MEASURED_DEVIATION_TAGS` (`wrong_proportion`,
`material_missing`) split out of `HALTING_DEVIATION_TAGS`, recorded as
`AssetVerdict.measured_property_reports` (evidence, never a gate); the
examiner prompt now frames the reference as a signed-off EXAMPLE of
the brief rather than how the asset "should look", and states that
colour, finish and any dimension inside tolerance are measured exactly
elsewhere and must not be reported. `fat_seat` left the zoo for
`tests/blender/test_acceptance_gate.py` after the gate coverage was
measured, not assumed.

Re-licence (130 eye calls, 857,480 input tok, $1.3856):

| metric | before | after | threshold |
|---|---|---|---|
| sensitivity | 0.80 (4/5) | 0.75 (3/4) | >= 0.60 PASS |
| same-run specificity | 1.00 | 1.00 (5/5) | 1.00 PASS |
| **cross-run specificity** | **0.50** | **0.75 (3/4)** | 1.00 **FAIL** |

planter_box is now clean — the colour false alarm is gone, so the
diagnosis was right and the fix worked on that class. three_leg_stool
still fires, now as `intersecting_parts, surface_artifact` instead of
`wrong_proportion`.

**And it is right again.** Reading both renders independently: the
exemplar's legs are roughly seat-thickness in diameter with a notch on
the front rim; the clean candidate's are 15-20% of seat diameter,
narrower than the rim, with a visible gap where the rear leg meets the
seat underside. Two gate-clean stools that genuinely differ in leg
thickness and junction quality.

So the residual leak is a CLASS no prompt can close: geometric
variation the brief leaves free. Telling the eye to ignore geometry is
telling it to ignore the only thing it is for — sensitivity already
slipped to 0.75 with `floating_seat` missed.

**State: the examiner is unlicensed for the loop's regime, and the
harness behaves correctly about it.** The measured 0.75 IS written
into `_evaluate/eye_calibration.json`, `problems()` names it, and
`converge_auto` refuses to gate on it. The strict guard test is marked
`xfail(strict=True)` with the number and this document named, so the
state is loud rather than papered over.

**Recommendation — B4', a strict improvement on the pre-approved B4.**
The re-licence shows exactly where the instrument IS reliable:
same-run controls 1.00 and 3/4 seeded defects detected. It is
excellent at "did this asset change from this reference" and unreliable
at "is this different asset defective". The loop uses only the second.
So: machine verdicts become ADVISORY on fresh-vs-exemplar (plain B4,
already signed as the fallback), and the examiner KEEPS gate authority
in the same-run regime it measured 1.00 on — the refinement turn, where
before-and-after are the same asset. That preserves the visual net
that caught the invisible crate lid instead of discarding it.

## Phase C — batch the views: 10 calls -> 2 per brief

**Files.** `src/blended/evaluate/examiner.py`,
`src/blended/agent/prompts/examiner.md.j2`, `tests/pure/test_examiner.py`.

**Change.** `examine_asset` sends all five views in ONE call per
ordering, with the reference paired to each candidate view and the
view named in the text so tags stay attributable. Constant
`EXAMINED_VIEWS_PER_CALL = len(EXAMINED_VIEW_NAMES)`. Both orderings
stay (D3).

**Measured target.** 10 calls -> 2 per brief, ~66k input tok saved per
brief, ~330k per cycle.

**Acceptance, and the number that rejects it.** Re-license on the
fixture zoo AND the Phase A cross-run controls:
sensitivity >= `MINIMUM_EXAMINER_SENSITIVITY` (0.6) and cross-run
specificity no worse than Phase A's baseline. Additionally, agreement
with the per-view instrument on the same artifacts, scored
tie-discounted (`10.48550/arXiv.2305.11206`), must be reported. Any
degradation and the batching is reverted — a cheaper instrument that
sees less is not a saving, it is a higher cost-of-pass (D1).

## Phases D and E — DROPPED 2026-09-06

The user ruled that neither the subscription window nor the dollar
meter binds at these amounts. Both remaining phases were pure `C`
reductions — the image budget (sheet resolution, pruning superseded
renders) and rate-limit visibility with a `cost-report` script — and
cost-of-pass says a `C` reduction is worthless next to an `R` that is
still being repaired (D1). Effort goes to capability instead.

What stays from that work, because it is how a regression becomes
visible rather than an optimisation: the per-turn accounting landed in
commit `14ba140` (`TurnCost`, `OllamaClient.spent`, six cost fields on
`IterationRecord`, the `spent:` line) and the two tests that guard the
11.8x caching property. The measurements that would have opened D and
E are recorded in the audit doc, so reopening them needs no rework:
sheets are 2,191 image tokens against 786 for a 2x2 at 768x768, and
the transport already parses the `rate_limit_event` frame it discards.

## Order, and why

A -> B -> C. A was the only phase that could move `R` off zero, and
C's licence depends on B's re-licensed baseline — which is why the
user chose sequential over combined: a specificity change after two
simultaneous edits cannot be attributed to either.

## Mistake-memory hook

Each phase that rejects its own hypothesis appends a record with the
measured numbers, as the block-layout rejection already did. The
failure mode this plan is most exposed to is tuning an instrument until
it agrees — so every acceptance above names the number that REJECTS the
change, not only the one that licenses it.
