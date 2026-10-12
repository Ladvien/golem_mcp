# Fine-tune decision — report

Spec: `docs/research/2026-09-19-finetune-decision-experiment.md`. Pre-registration: `scripts/finetune_decision_thresholds.py`. No training happened; this is a decision plus its evidence.

## 1. Environment and precondition deviations

| item | value |
|---|---|
| repository HEAD | `5098a5db9efc800afbc10ff32ebc018ca59534cf` |
| Blender | `Blender 5.2.0 LTS` |
| target series | [5, 2] |
| assembled prompt fingerprint | `a10:c68237772de1` |
| tool-schema fingerprint | `t:fd10e7f510a8` |
| facade ops / service tools / schemas | 48 / 8 / 56 |
| GPU host (registered, NOT used for the arms — see deviation 1) | `NVIDIA GeForce RTX 3090, 610.57.04, 24576 MiB, 10465 MiB` |
| local serving | `http://127.0.0.1:8091` — Apple M5, version: 0.4.1-dev (build 10964, commit b29c606e2), q8_0, 4 slots x -c 16384 |
| instance set | `bench_sets/instances_holdout.txt` (20 instances, sha256 `ab39317f95e17680`, matches pre-registration: True) |
| archived render logs | 538 |
| schema-2 transcripts | 28 of 97 iteration records; 157 chat transcripts |

### Precondition deviations

1. **Neither vLLM nor the 3090 served the local arms.** vLLM is not installed on that host, and its card stayed committed to a live home-still conversion run for the whole experiment (olmocr vLLM 13.2 GiB + hs-distill-server 3.5 GiB + an Ollama child, ~23 of 24 GiB, with a steady stream of 20-40 s OCR calls). Under llama-swap's strict swap a single request of mine waited 8 minutes while the two workloads evicted each other, so A2/A3/A4 ran instead against a `llama-server` on the workstation (Apple Silicon, Metal) reading the SAME GGUFs — one OpenAI-compatible endpoint for all local arms, which is what §5.2 actually requires. Measured single-stream decode: 11.8-12.8 tok/s, prefill 235 tok/s, prompt prefixes cached across completions.
2. **Precision is q8_0, not F16.** F16 asked CUDA for 13,486.77 MiB and the card refused: 10.0 GiB was held by two orphaned `llama-server` processes (one with four live connections) plus an Ollama child — a foreign workload this run did not preempt. Both checkpoints moved together, so precision is not a confound between A3 and A4.
3. **A2/A3 ride Qwen2.5-Coder-7B-Instruct**, not the non-coder instruct checkpoint the HF card names as BlenderLLM's base. Three measurements say the card is wrong: BlenderLLM's own `config.json` names `Qwen2.5-Coder-7B-Instruct`; its four safetensors shards match the coder repo's byte sizes and share its `model.safetensors.index.json` blob; and its weights sit 1.0-1.1% from the coder base against 99-124% from the non-coder one. The spec's §5.1 text agrees with the checkpoint.
4. **The sandbox is the benchmark's own** `core/render.py` subprocess with its 240 s wall-clock cap — no memory cap and no network isolation. A second sandbox would have broken comparability with the archive, which is the Phase A denominator.
5. **G1 vs G2 is decided by the metric decomposition**, not a VLM (spec §4 proposed a VLM for all of G1-G3). The decomposition is ground truth against the reference mesh and reproducible; no §3 rule reads the interior split of `F_geom`. G3 is still judged.
6. **The op arms' task text carries a single-shot paragraph** the archive's does not. Measured before any arm ran: with the unmodified multi-turn harness prompt, 3 of 4 single-shot replies were a `declare_plan` call and nothing else. Spec §9 says to investigate the prompt rather than burn the roll; the raw arms already carry the equivalent sentence in the benchmark's own prompt. Both op arms get identical text.

### Pipeline parity gate (spec §5.2 / §9)

- **Stage 1, exact**: the same baked artifacts scored through two differently-named model dirs agree on cd_pca, cd_yawmin, delta_orient and fscore_005 to 1e-09 — passed: True over 3 instances. The scorer cannot see which path wrote the script.
- **Stage 2, measured**: the same scripts baked twice reproduce the SOLID (volume within 1e-09 relative — passed: True) but not the tessellation. The pipeline's own noise floor on a re-bake is cd_pca 0.000328, fscore_005 0.034266.
- What this does and does not license: it says a cd_pca VALUE is comparable across arms to ~3e-4, which is 1.3% of the 0.0252 pass bar, so the pass/fail verdict on an individual completion is stable. It says NOTHING about how far an arm's RATE would move on a different set of instances — that is sampling error, it is a much larger number, and it is computed in §4. An earlier draft of this report used this floor as if it were the rate uncertainty.

## 2. Phase A — where the harness actually fails

Attempts counted: **265** (INFRA and UNSCORED excluded and listed in `phaseA/summary.md`). Passes at `cd_pca <= 0.0252`: **154**. Failures: **111**.

| share | value | bar |
|---|---|---|
| `F_syntax` (E1-E5, E7, O1-O2) | 1.8% (2/111) | >= 40.0% for rules 2-3 |
| `F_geom` (G1-G3) | 98.2% (109/111) | >= 60.0% fires rule 1 |
| `E6` (executed, degenerate) | 0.0% | in neither share, by the spec's own definitions |

Codes: `{'PASS': 154, 'G2': 97, 'G1': 12, 'E7': 2, 'INFRA': 7, 'UNSCORED': 13}`

### What `F_syntax` = 1.8% does and does not say

The Phase A denominator is the ARCHIVE, and the archive is multi-turn: every attempt in it ran through `AgentSession` with up to 24 tool calls per turn, a gate report after each one, and the error text fed back to the writer. So 1.8% is the share of failures that are syntactic AFTER the loop has already absorbed the syntactic failures.

The single-shot contrast is in this same report: A5 is the same class of model writing raw bpy with no feedback at all, and it fails to execute 18.8% of the time. The gap between that and 1.8% IS the retry loop.

Rule 1's conclusion is therefore correctly scoped as "where should investment go to raise the pass CEILING" — and the answer is planning, not syntax. It is NOT the stronger claim that the harness has no syntactic failure mode: it has one, and it pays tokens and turns to avoid paying for it in the score. §5's note is worded to that weaker, measured claim.

**G3 judge**: 18 of 40 sampled non-passing executed attempts were judged to violate an explicit constraint (0 unparsed), eye `claude-code:sonnet`.

**Judge error, measured by hand on 20 of those rows** (same rule the judge was given, "cannot tell -> false"): 5 disagreements = **25.0%**. Every disagreement is a judge FALSE POSITIVE: precision on its positives is 37.5% and on its negatives 100.0%, so the G3 count corrects from 18 to about **7** of 40.

Two mechanisms, both identified from the disagreeing rows:

- colour or material constraints judged on geometry the benchmark's own prompt requires to be UNTEXTURED (3 of 5 disagreements)
- near-white, low-contrast turntable renders that are effectively unreadable (2 of 5)

Per-row verdicts, notes and the `agrees` flag are in `phaseA/g3_judgements.jsonl`. G3 re-labels rows already inside `F_geom`, so neither the judge's error nor its correction moves any §3 rule.

## 3. Phase B — the funnel, single-shot

| arm | model | format | completions | schema | script emitted | executed | non-degenerate | cd_pca pass |
|---|---|---|---|---|---|---|---|---|
| a1 | claude-code:sonnet | ops | 80/80 | 97.5% | 87.5% | 80.0% | 80.0% | 42.5% |
| a2 | qwen2.5-coder-7b-instruct | ops | 80/80 | 73.8% | 1.2% | 0.0% | 0.0% | 0.0% |
| a3 | qwen2.5-coder-7b-instruct | raw | 80/80 | 78.8% | 78.8% | 2.5% | 2.5% | 2.5% |
| a4 | blenderllm | raw | 80/80 | 100.0% | 100.0% | 98.8% | 98.8% | 45.0% |
| a5 | claude-code:sonnet | raw | 80/80 | 100.0% | 100.0% | 81.2% | 81.2% | 48.8% |

Per-draw rates, cd_pca distribution and latency are in `phaseB/summary.md`; per-completion rows in `phaseB/scores.csv`.

## 4. The four deltas, with their uncertainty

Every interval below is **instance-clustered**: the four draws of one instance answer the same prompt, so the effective sample is nearer the 20 instances than the 80 completions, and the half-width is `1.96 * sd(per-instance means) / sqrt(20)`. This is NOT the parity gate's ~3e-4 cd_pca noise floor — that is metric precision under a re-bake and says nothing about how far a 20-instance rate would move on another 20 instances. An earlier draft of this report used the noise floor as if it were sampling error; it is corrected here, and the correction changes what can be claimed.

| quantity | value | 95% half-width | bar | verdict |
|---|---|---|---|---|
| Δ_tune (executability A4 − A3) | 96.2 pp | ±5.5 pp | >= 15.0 pp | clears the bar by ~15x its own interval |
| Δ_facade (executability A2 − A3) | -2.5 pp | ±4.9 pp | >= 25.0 pp | void — computed against A2, which passed nothing |
| Δ_size (cd_pca pass A1 − A2, k-mean) | 40.0 pp | ±16.7 pp | <= 10.0 pp | void — computed against A2, which passed nothing |
| Δ_size (greedy draw) | 50.0 pp | — | <= 10.0 pp | void — computed against A2, which passed nothing |

### Δ_facade, Δ_size and the zero-variance artifact are one failure, not three

A2 reached a scorable script on 1.2% of its 80 completions and passed 0 of them. Every quantity whose subtrahend is A2 therefore measures a FLOORED ARM rather than the factor it is named for — the facade for Δ_facade, model size for Δ_size — and the same floor is why A2's between-instance variance is exactly zero. That zero is a real value, not a missing one: it is the `se == 0` case the interval code now handles explicitly, after a falsy check on it silently dropped both half-widths.

Δ_facade carries a second, separate defect on top of the floor: the op arms' task text still mandates that geometry be built inside `run_python` chunks, so A2 exercised bpy-in-an-envelope rather than the 48-op facade. Q2 is therefore UNANSWERED, and Δ_facade should not be read as answering it.

The spec's §9 stop condition caught none of this, because it is written on SCHEMA CONFORMANCE, which A2 passed at 73.8% — above the 20% bar — while the funnel stage the deltas are actually computed from, reaching a scorable script, sat at 1.2%. The roll was spent on a dead arm. Put the stop condition on the stage the delta is computed from, and a future facade arm has to change the TASK TEXT so facade ops are the geometry path, not just the wire format.

### cd_pca pass rates are mutually indistinguishable

| arm | cd_pca pass | 95% interval |
|---|---|---|
| a1 | 42.5% | [25.8, 59.2] |
| a2 | 0.0% | [0.0, 0.0] |
| a3 | 2.5% | [0.0, 7.4] |
| a4 | 45.0% | [25.7, 64.3] |
| a5 | 48.8% | [29.8, 67.7] |

A1, A4 and A5 overlap pairwise. The report therefore claims NEITHER that the frontier model beat BlenderLLM nor that BlenderLLM reached parity with it: on 20 instances neither claim is available.

Δ_size is NOT discounted for width — its interval [23.3, 56.7] excludes zero. It is discounted because its subtrahend is A2.

## 4b. Cost per PASSING asset (spec §5.3 metric 8)

Omitted from the first draft of this report. A rate says nothing about whether a lane is worth calling; the cost per pass is the only number on which a cheap-and-often lane can beat an expensive one.

| arm | lane | passing | tokens per pass | completion tokens per pass | wall per pass |
|---|---|---|---|---|---|
| a1 | Claude Code CLI | 34/80 | 42938 | 42932 | 425s |
| a2 | local llama-server | 0/80 | — | — | — |
| a3 | local llama-server | 2/80 | 36550 | 26052 | 16196s |
| a4 | local llama-server | 36/80 | 1652 | 1078 | 124s |
| a5 | Claude Code CLI | 39/80 | 9488 | 9484 | 90s |

The comparator for “does a local specialist beat calling a frontier model” is **A5**, not A1: the same task, the same raw answer format, no schema overhead on either side. Against A5 the specialist's advantage is 5.7x in tokens per passing asset, and it does not extend to wall clock — A5 is FASTER per passing asset (90 s against 124 s) despite A4's queue contamination, and A5 holds the highest point-estimate pass rate of any arm (48.8% against 45.0%). The case for a local specialist here is real but narrow: it is token-shaped, not a general win.

Dollars are $0 on every arm here — A1/A5 ride a subscription, A2/A3/A4 ride owned hardware — so tokens and wall clock are the cost. Two caveats, both load-bearing: wall clock is contaminated by four-way queueing on a single GPU and is NOT a clean per-completion latency; and A1's token count carries the harness system prompt plus 56 tool schemas on every call, which is the op format's cost, not the model's.

## 4c. A1 against A5 — the facade's cost, with no measured return

Same model (`claude-code:sonnet`), same bench, same single-shot regime, same 20 instances x 4 draws. The only difference is the prompt and the answer format.

| | A1 (ops) | A5 (raw) |
|---|---|---|
| cd_pca pass | 42.5% | 48.8% |
| tokens per passing asset | 42938 | 9488 |
| wall clock per passing asset | 425 s | 90 s |
| system prompt | 190 lines + 56 tool schemas | 38 lines |

A1's cost is NOT explained by the model ignoring the facade, on either instrument. Of the geometry-emitting calls A1 CHOSE, 746 were scene-changing facade ops against 59 `run_python` chunks (92.7%); of what the score then SAW, 550 ops against 54 chunks (91.1%). It used the surface, paid 4.5x the tokens and 4.7x the wall clock of A5, and did not win on the point estimate. The pass-rate intervals overlap, so the DIRECTION is not claimed either — what is claimed is the absence of a measured return for a measured cost. This stands on its own evidence: §4d's archive hatch share is NOT independent corroboration, because part of that share is an instrument reading.

## 4d. The hatch rate — corrected, and its mechanism measured

On archived attempts that PASSED and whose bake could record an op call at all, 90.4% of the geometry-emitting calls were `run_python` chunks rather than scene-changing facade ops (321 chunks against 34 op calls, with 17 of 72 such attempts using any op). On failing attempts it is 70.4%.

Those numbers replace the 95.1%/89.9% an earlier draft published, and the correction is a measurement, not a re-opinion (`phaseA/hatch_mechanism.md`, `scripts/finetune_hatch_mechanism.py`). Three faults in the old instrument: `.agent_meta.json`'s `n_op_calls_included` counts READER ops as geometry-emitting, because `emits_geometry` is "the hatch or ANY facade op"; `n_chunks_included` is the label COUNTER, which advances on op calls too; and 82 of 154 passing attempts come from rolls whose bridge collected `run_python` and nothing else, so their scripts CANNOT hold an op call and their forced 100% was being averaged in. Measured directly on `blended-deepseek-v4-pro-ops-roll1/Tap_seed0`: 13 scene-changing op calls dispatched, every one `ok`, 0 op labels in the baked script.

The harness's stated architecture is a 48-op facade as the tool surface with `run_python` demoted to a reason-gated escape hatch (`docs/harness_design.md` rows 1 and 7). Corrected, the hatch is still the surface in the benchmark configuration. What changed is that the mechanism is no longer open.

**Op-failure feedback is not the mechanism.** The hypothesis — an op call that errors teaches the agent, inside the run, that `run_python` is the reliable path — predicts a higher op failure rate in the multi-turn archive than in single-shot A1, and a first chunk that FOLLOWS the first op failure. Measured on the one instrument both regimes share (a dispatched call that never reached the baked script): the archive drops 7.0% of its scene-op calls against A1's 26.3%, while the chunk drop rates are 8.4% and 8.5% — the op path is MORE reliable in the archive, not less. Ordering finishes it: 93.8% of instrumented attempts made a chunk their FIRST geometry-emitting call, 96 of 144 chunk-using attempts never called a scene-changing op at all, and of the 16 that did see one fail, only 5 failed before the first chunk. The facade is not abandoned after it breaks; it is never entered.

**What does separate the rolls is the offered set.** Every archived roll that offered the disclosed 29-of-56 set (`blended.agent.tool_disclosure.offered_tools`, fingerprint `t:6b6093efb569`) bakes a 14.0%–23.9% op share; rolls predating op collection bake zero, and for rolls with no tool events at all "did not call" cannot be told from "was not recorded". Against that, A1 — single-shot, all 56 schemas offered — baked 91.1% ops. So the live axis is the one this experiment cannot settle from the archive: what the multi-turn loop does to a surface the model demonstrably uses in one shot. Settle it before the candidate-op miner proposes more ops.

## 5. The decision rule that fired

**Rule 1 fires: F_geom = 98.2% >= 60% -> DO NOT FINE-TUNE. The failures are planning failures; invest in decomposition, reference-image grounding and the multi-angle visual inspection loop instead.**

- Rules 4 and 5 are VOID rather than un-fired-on-the-evidence: Δ_facade and Δ_size are both computed against A2, which passed nothing, so each subtraction measures a floored arm instead of the facade or model size. Neither rule's §3 threshold comparison changes; only what the number is allowed to mean does.
- Δ_tune = 96.2 pp clears rule 2's 15.0 pp bar, and rule 2 STILL CANNOT FIRE, because it is conjoined with F_syntax >= 40% and F_syntax measured 1.8%. The careful statement, not the flattering one: domain SFT fixes the class a 7B fails in, and the archive does not fail in that class BECAUSE IT PAYS A RETRY LOOP TO AVOID IT. The Phase A denominator is multi-turn with error feedback; single-shot A5 — frontier model, raw bpy, no feedback — fails to execute 18.8% of the time against the archive's 1.8%. So the harness HAS a syntactic failure mode and spends tokens and turns instead of score on it. What the arm codes do show is the regime SFT buys: 100.0% of the untuned base's (A3) failures are syntactic (E1, E2, E3, E4, E5, E7, O1, O2), against 97.7% of the fine-tune's (A4) that are geometric (G1, G2, G3).

## 6. Secondary agentic-mode measurement

Not run. The primary single-shot regime is the one the spec registers, and mixing an agentic A1 with a single-shot A2 is the confound §5.2 names as the largest available.

## 7. Phase C — corpus inventory and sufficiency

| quantity | count |
|---|---|
| (instruction, script) pairs in the bench archive | 321 |
| ... executed | 302 |
| ... scored | 288 |
| ... passing at `cd_pca <= 0.0252` | 165 |
| deduplicated, execution-verified | 302 |
| **distinct instructions** | 32 |
| op-sequence pairs | 40 |

Verdict: see `phaseC/corpus_inventory.md` — the binding number is the distinct-instruction count (32 with at least one executing script), not the pair count.

## 8. Limitations

1. **Bench size.** 20 instances x 4 draws = 80 completions per arm. One completion is 1.25 pp, so no rate difference below that is interpreted.
2. **A1/A5 have no temperature or seed control.** The Claude Code CLI accepts neither, so those arms' four draws are four independent samples at the lane's own settings; every completion record says so (`seed: null`, `temperature: null`). `ModelConfig.seed` was added for the local lanes and is verified to reach the wire.
3. **BlenderLLM is a December-2024 checkpoint.** Its published frontier comparisons are stale; it is used here as an existence proof of what domain SFT buys, not as a production candidate.
4. **Prompt parity is imperfect by construction.** The op arms get the harness system prompt (190 lines) and 56 tool schemas; the raw arms get the benchmark's own prompt (38 lines). Full unified diff: `phaseB/prompt_parity.diff` (222 diff lines, 29 added / 181 removed). The task text differs only as shown below.

```diff
--- a1_a2_task_text
+++ a3_a4_a5_task_text
@@ -10,16 +10,7 @@
   primitives and stop.
 - Do not add cameras or lights. Do not render to disk from your Python. Do not call
   sys.exit or bpy.ops.wm.quit_blender.
-- Every piece of geometry must be created inside `run_python` chunks. Those chunks are
-  collected verbatim into a standalone script that is re-executed from an empty scene to
-  score this run, so anything built outside a chunk will not exist when it is re-run.
 Placement: the scored mesh is compared in world space against a reference mesh,
 and neither is reoriented. Align the object's principal axes with the world axes:
 - Up is +Z. Legs, stems and stand-offs point straight down; tops and caps are
   horizontal. No tilt, no roll, no spin to an arbitrary angle.
-
-This is a SINGLE-SHOT task. You get exactly one reply and there will be no
-further turns: no tool results come back, no follow-up message, no chance to
-verify or correct. Emit every tool call the object needs in THIS reply, in
-order. A reply that only declares a plan, or that answers in prose, builds
-nothing and scores zero.
```

5. **The canonical-orientation epilogue is asymmetric.** A1/A2's emitted scripts end with `apply_canonical_depth_axis()`; a raw script cannot, because the epilogue imports `blended`. `cd_yawmin` is therefore never compared across formats — `cd_pca` quotients orientation out and is what the arms are ranked on here.
6. **The G3 judge over-reports, measured.** 25.0% disagreement against hand verification of 20 rows, every disagreement a false positive (37.5% precision on positives). Two mechanisms: colour/material constraints judged on geometry the benchmark requires to be untextured, and near-white turntable renders that are unreadable. The judge only re-labels rows already inside `F_geom`, so no §3 rule turns on it.
7. **Re-bake reproducibility.** Two bakes of one script give the same solid and a different tessellation; cd_pca moves by ~0.000328. Archived scores were therefore read, never regenerated.
8. **Some A2/A3 completions were killed by the harness's own 1500 s per-completion cap and are recorded as `E5`.** Their rows are synthesized and carry `synthesized_by`, so they can never be mistaken for a reply a model returned: 11 of A2's 80 and 15 of A3's 80. Mechanism, measured rather than assumed: `max_completion_tokens` is 16,384 and this lane decodes at 11.8-12.8 tok/s, so a completion that runs to the ceiling needs ~1,365 s of generation alone — and ~4x that per stream when four draws share the four slots. The completions that DID finish are fast (A2 median 70 s, 200 output tokens), and re-running the killed ones at reduced concurrency still hit the cap, so this is a property of the model-plus-cap, not of queueing alone. Constrained decoding is not the cause: measured 11.81 tok/s unconstrained against 12.75 tok/s with the 56-tool envelope grammar on the same prompt.
9. **A1/A2/A3 ran four draws concurrently against four slots; A4 ran the same way.** Latency percentiles therefore include queue time and are not a clean per-completion measurement; executability and pass rates are unaffected, since a completion either produced a script or did not.
10. **The op arms did not test the op FACADE.** A1/A2's task text is the archive's, and it still says every piece of geometry must be created inside `run_python` chunks, because those chunks are what the bake collects. So A2 and A3 were both writing bpy; A2 merely had to wrap it in tool-call JSON. A2 − A3 is therefore bpy against bpy-in-an-envelope, not facade against raw, and it also explains A2's collapse — a 7B was handed a ~17k-character system prompt, 56 schemas and a JSON envelope around the same task it already failed at unwrapped. Any future facade arm must change the task text so facade ops are the geometry path.
11. **Effective sample size is ~20, not 80.** Four draws per instance are correlated, so §4's intervals are clustered on the 20 instances and a 45.0% pass rate carries roughly ±19 pp. Every cross-arm shape comparison in this report except Δ_tune sits inside its interval. The fix is more instances (`bench_sets/instances_dev_all.txt` holds 145), not more draws.

## 9. Traceability spot-checks

- `phaseA/taxonomy.csv` holds 285 harness rows, of which 109 carry a G-code and 2 an E-code (excluding E6) — the F_geom and F_syntax numerators.
- `phaseB/scores.csv` holds 80 rows for arm a1, 64 with `render_status == OK` — the arm's executability numerator.
- `phaseB/scores.csv` holds 80 rows for arm a2, 0 with `render_status == OK` — the arm's executability numerator.
- `phaseB/scores.csv` holds 80 rows for arm a3, 2 with `render_status == OK` — the arm's executability numerator.
- `phaseB/scores.csv` holds 80 rows for arm a4, 79 with `render_status == OK` — the arm's executability numerator.
- `phaseB/scores.csv` holds 80 rows for arm a5, 65 with `render_status == OK` — the arm's executability numerator.

## 10. Model revisions

| id | repo | revision |
|---|---|---|
| `blenderllm` | `FreedomIntelligence/BlenderLLM` | `095b8f8cdc606b59afa3128805aea233c1ba77b0` |
| `qwen2.5-coder-7b-instruct` | `Qwen/Qwen2.5-Coder-7B-Instruct` | `c03e6d358207e414f1eca0bb1891e29f1db0e242` |
