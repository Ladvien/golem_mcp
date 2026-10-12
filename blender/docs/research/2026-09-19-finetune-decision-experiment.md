# Fine-Tune Decision Experiment — Specification

**Date:** 2026-09-19
**Repo:** `blended`
**Suggested location:** `docs/research/2026-09-19-finetune-decision-experiment.md`
**Status:** pre-registered — thresholds in §3 are fixed before the run and must not be edited after results are seen

---

## 1. Purpose

Decide whether to invest in fine-tuning a small (~7–9B) local model as a tool-callable geometry specialist for the `blended` harness, **before** spending GPU time on training.

The experiment answers three questions:

- **Q1 — Where does the current harness actually fail?** Are failures *syntactic/API* ("how to say it") or *spatial/semantic* ("what to build")? Fine-tuning reliably improves the first and does not reliably improve the second.
- **Q2 — How much of the gap does the ops facade already close?** If the 48-op facade lets a small model carry most of the load, the marginal value of a fine-tune shrinks.
- **Q3 — What does domain fine-tuning demonstrably buy?** Measured by running a released, already-fine-tuned bpy model (BlenderLLM) against an untuned model of the same size on the same bench.

**No training happens in this experiment.** Output is a decision plus the evidence behind it.

---

## 2. Preconditions

The agent must verify and record all of the following before starting. If any fails, stop and report rather than improvising a substitute.

| Item | Requirement |
|---|---|
| Bench | 3DCodeBench runnable end-to-end; record task count `N` |
| Metric | `cd_pca` implementation available and callable on a produced mesh vs. reference |
| Blender | Single pinned version for all arms; record exact version string |
| GPU host | RTX 3090 (24 GB) reachable; record driver + CUDA version |
| Frontier access | API access for the arm-1 model; record model string |
| Transcripts | Schema-2 tool-event transcript store readable; record path and count |
| Disk | ≥ 100 GB free for model weights + rendered artifacts |

**Sandboxing:** every generated script executes in a subprocess with a hard wall-clock timeout (default 120 s), a memory cap, and no network. A hang is a result (`E5`), not a reason to retry.

---

## 3. Hypotheses and pre-registered decision matrix

Let:

- `F_syntax` = share of *failures* in Phase A coded `E1–E5` or `O1–O2`
- `F_geom` = share of *failures* coded `G1–G3`
- `Δ_tune` = executability rate of arm A4 minus arm A3 (percentage points)
- `Δ_facade` = executability rate of arm A2 minus arm A3 (percentage points)
- `Δ_size` = cd_pca pass rate of arm A1 minus arm A2 (percentage points)

Decision rules, applied in order:

1. **`F_geom` ≥ 60%** → **Do not fine-tune.** Failures are planning failures. Invest instead in decomposition, reference-image grounding, and the multi-angle visual inspection loop.
2. **`F_syntax` ≥ 40% AND `Δ_tune` ≥ 15 pp** → **Fine-tune is justified.** Proceed to a dataset-extraction and QLoRA plan.
3. **`F_syntax` ≥ 40% AND `Δ_tune` < 15 pp** → **Do not fine-tune yet.** The failure class is real but domain tuning did not move it. Try constrained/grammar-guided decoding and prompt-level op documentation first; re-measure.
4. **`Δ_facade` ≥ 25 pp** → the facade is carrying the work. Note this regardless of the other outcomes: it argues that *if* a fine-tune happens, its training target should be **op-call sequences, not raw bpy**.
5. **`Δ_size` ≤ 10 pp** → a small model is already close to the frontier path on this bench. Record as strong supporting evidence for the specialist, independent of rules 1–3.

Anything not covered by the above → report as inconclusive and recommend enlarging `N`. Do not invent a rule post hoc.

---

## 4. Phase A — Failure taxonomy of existing rolls

**Input:** all archived 3DCodeBench rolls currently in the repo. If fewer than 100 scored task attempts exist, run a fresh full roll on the current production path first.

**Task:** classify every non-passing attempt into exactly one code. Classification is by first observed failure, not by severity.

| Code | Meaning | Detection |
|---|---|---|
| `E1` | Syntax error | `SyntaxError`, `IndentationError` |
| `E2` | Hallucinated API | `AttributeError` on `bpy.*`, unknown operator, invalid enum value |
| `E3` | Wrong signature / argument | `TypeError`, unexpected keyword |
| `E4` | Context / state error | `poll()` failed, wrong mode, no active object, missing selection |
| `E5` | Timeout, hang, or Blender crash | Non-zero exit or wall-clock cap hit |
| `E6` | Executed, empty or degenerate scene | 0 mesh objects, or 0 verts, or non-manifold-everything |
| `G1` | Executed, structurally wrong geometry | cd_pca far above threshold; wrong topology |
| `G2` | Executed, right kind, wrong proportions or placement | cd_pca above threshold, shape class correct |
| `G3` | Executed, plausible, misses an explicit instruction constraint | Manual/VLM check against prompt |
| `O1` | Tool-schema violation | Invalid op name, malformed arguments, bad JSON |
| `O2` | No usable output | Refusal, empty response, truncation |

**Automation:** `E1–E6` and `O1–O2` are detectable programmatically from the exception trace and scene inspection. `G1–G3` require the rendered image plus prompt; use a VLM judge and **hand-verify a 20-sample stratified subset** to estimate judge error. Report the judge's disagreement rate alongside the numbers.

**Also record separately:** how often `run_python` was invoked (with its `reason` string) versus facade ops, on both passing and failing attempts. A high hatch rate on *passing* attempts is itself a finding.

**Output:** `results/phaseA/taxonomy.csv` (one row per attempt) plus a summary table with `F_syntax` and `F_geom`.

---

## 5. Phase B — Arm comparison

### 5.1 Arms

All arms answer the same 3DCodeBench tasks, scored identically.

| Arm | Model | Output format | Isolates |
|---|---|---|---|
| `A1` | Current frontier model | Op-call sequence (48-op schema) | Production baseline |
| `A2` | Off-the-shelf ~7–9B instruct-coder | Op-call sequence (48-op schema) | Small model on the facade |
| `A3` | *Same model as A2* | Raw bpy | Control: facade contribution (A2 − A3) |
| `A4` | BlenderLLM (Qwen2.5-Coder-7B fine-tuned on BlendNet) | Raw bpy | Control: fine-tune contribution (A4 − A3) |
| `A5` *(optional)* | Current frontier model | Raw bpy | Control: model size on raw bpy |

`A3` **must** use the identical base checkpoint as `A2`, or the A4 − A3 comparison is meaningless.

**Model selection for A2/A3:** the agent should confirm current availability and pick one ~7–9B instruct-tuned coder. Candidates to check, in preference order: a current Qwen coder checkpoint in the 7–9B range, Granite 4.1 8B, Qwen3.5-9B. Constraint: must be servable on the 3090 and must have an instruct/tool-calling format. Record the exact HF revision hash.

**BlenderLLM:** `FreedomIntelligence/BlenderLLM` on Hugging Face, Apache-2.0, based on Qwen2.5-Coder-7B-Instruct. Record the revision. Note in the report that this checkpoint is from December 2024 and its frontier comparisons are stale — it is being used here as *an existence proof of what domain SFT buys*, not as a candidate for production.

### 5.2 Protocol controls

These are the parts most likely to produce a wrong answer if skipped.

- **Single-turn only.** Every arm gets one prompt and produces one response. No agentic loop, no retry, no error feedback, no visual inspection. This is deliberate: the specialist under consideration would be *called as a tool* by the planning agent, so single-shot is the regime that matters. Running A1 in its full agentic mode and comparing to a single-shot A2 would be the single biggest confound available.
- **Secondary measurement (optional, run after the primary):** A1 and A2 in full agentic mode, reported in a clearly separate table. Never mix these numbers with the primary.
- **Sampling:** `k = 3` completions per task at `temperature = 0.2`, plus one at `temperature = 0`. Report `pass@1` (mean over the k), `pass@3`, and the greedy result. Fixed seeds, recorded.
- **Prompt parity:** A1 and A2 get byte-identical system prompts and op schemas. A3, A4, A5 get a raw-bpy prompt that is as close as possible in content; diff the two prompts and include the diff in the report.
- **Serving:** one OpenAI-compatible endpoint for all local arms (vLLM on the 3090) so the client code path is identical. Record quantization used — if A2/A3 run at a different precision than A4, note it as a limitation.
- **Execution parity:** all arms' outputs run through the same sandbox, same Blender build, same timeout, same scene-export path, same `cd_pca` call. Arms A3–A5 need a raw-bpy execution adapter that reaches the identical scoring function as the op-sequence path. **Build and validate this adapter first** — verify it by running a handful of known-good op sequences lowered to raw bpy and confirming identical cd_pca scores through both paths.

### 5.3 Metrics

Per arm, report:

1. **Schema conformance rate** — output parsed as a valid op sequence (A1/A2) or valid Python (A3–A5)
2. **Executability rate** — ran to completion without exception or timeout
3. **Non-degenerate rate** — produced ≥ 1 mesh object with > 0 verts
4. **cd_pca pass rate** — at the repo's existing threshold; also report the full distribution, not just the pass rate
5. **cd_pca median and IQR** over non-degenerate results
6. **Failure code histogram** — same codes as Phase A
7. **Latency** — p50 and p95 per completion
8. **Cost** — API spend for A1/A5; GPU-seconds for A2–A4

Report metrics 1–4 as a funnel. A model that fails at stage 2 and a model that fails at stage 4 need different fixes, and a single aggregate score hides that.

---

## 6. Phase C — Training-corpus inventory

Cheap, runs in parallel, and determines whether a fine-tune is even *possible* without new data collection.

From the schema-2 tool-event transcripts, report:

- Total runs; runs ending in a scored success
- Count of distinct `(instruction → op sequence)` pairs recoverable
- Count of those with an associated cd_pca score
- Deduplicated count (near-duplicate instructions collapsed)
- Op-coverage histogram: how many of the 48 ops appear, and how many appear fewer than 20 times
- `run_python` hatch invocations, grouped by `reason`

**Reference point:** BlendNet used 8,000 instruction→script pairs (2,000 human-annotated, 6,000 model-validated) and the BlenderLLM self-improvement rounds used ~2,000 samples each to avoid saturation. A usable first SFT run needs roughly 1–3k deduplicated, execution-verified pairs. If the corpus is an order of magnitude below that, the real blocker is data generation, not training — say so plainly in the report.

---

## 7. Artifacts

```
docs/research/2026-09-19-finetune-decision-experiment.md   (this spec)
results/2026-09-19-finetune-decision/
  env.json                 versions, hashes, seeds, model revisions
  phaseA/taxonomy.csv
  phaseA/summary.md
  phaseB/<arm>/completions.jsonl     prompt, raw output, parse result
  phaseB/<arm>/executions.jsonl      exit code, traceback, timing
  phaseB/<arm>/scores.csv            per-task cd_pca, codes
  phaseB/renders/<arm>/<task>.png
  phaseB/summary.md
  phaseC/corpus_inventory.md
  REPORT.md
```

Every number in `REPORT.md` must trace to a file above. Raw completions are kept so the run is re-scorable without re-inference.

---

## 8. Reporting requirements

`REPORT.md` contains, in order:

1. Environment table (§2) and any precondition deviations
2. Phase A summary with `F_syntax` / `F_geom` and the VLM-judge disagreement rate
3. Phase B funnel table, all arms, primary (single-turn) regime
4. The four deltas: `Δ_tune`, `Δ_facade`, `Δ_size`, and hatch rate
5. **Which decision rule in §3 fired, stated before any interpretation**
6. Secondary agentic-mode table, if run, clearly labelled
7. Phase C inventory and the data-sufficiency verdict
8. Limitations — at minimum: bench size, quantization mismatch across arms, BlenderLLM's age, prompt-parity diff, VLM-judge error

The agent must not recommend a course of action that the fired decision rule does not support. If the results are ambiguous, the report says inconclusive.

---

## 9. Stop conditions

Halt and report rather than continuing:

- The raw-bpy execution adapter cannot be validated against the op path (§5.2) — without it, A3–A5 are not comparable and the whole experiment is void
- `N` < 100 scored tasks and no way to expand the bench
- BlenderLLM weights unavailable or won't load on the 3090
- Any arm's schema-conformance rate < 20% — investigate the prompt before burning the full roll
- Estimated total spend exceeds the agreed budget

---

## 10. Non-goals

Explicitly out of scope for this run:

- Any training, LoRA or otherwise
- Image-to-model / VLM evaluation — different modality, different fine-tune, measure separately
- Changes to the 48-op facade or the harness agent prompts
- Multi-GPU or rented-cloud inference
- Any claim about production behaviour not backed by a paired roll, per existing repo convention

---

## 11. Effort estimate

| Phase | Work |
|---|---|
| Adapter + harness plumbing | 0.5–1 day |
| Phase A classification | 0.5 day (mostly automated) |
| Phase B rolls (5 arms × N × 4 completions) | 0.5–1 day wall clock, mostly GPU-bound |
| Phase C inventory | 1–2 hours |
| Report | 0.5 day |

Dominant risk is the raw-bpy execution adapter, not the inference.
---

## Execution deviations

Recorded at execution time (2026-09-19). The §3 thresholds above are untouched;
these three statements say where the repository already answered a §2/§5/§7
question differently from the spec's assumption, with the evidence for each.

1. **The raw-bpy execution adapter of §5.2 / §9 does not exist as work; it is
   replaced by a pipeline *parity gate*.** Both output formats already reach the
   identical scorer: `scripts/bake_3dcode.py` bakes and validates any
   `<model-dir>/<inst>/<inst>.py` through the bench's own `core/render.py` +
   `core/export_glb.py`, and `src/blended/evaluate/bench_bridge.py:126`
   (`standalone_script`) already lowers a recorded op sequence to a standalone
   script written to that same path. What the spec's "build and validate this
   adapter first" buys is therefore a *round-trip assertion*, not an adapter:
   archived op-path scripts are re-baked through the raw arms' directory layout
   and their `cd_pca` must reproduce the archived value.
   Evidence: `scripts/bake_3dcode.py:71,116`,
   `src/blended/evaluate/bench_bridge.py:93,126`,
   `outputs/finetune_decision/parity_gate.json`.

2. **The `results/…` artifact root of §7 is re-homed.** `results/` does not
   exist in this repository, `.gitignore` ignores `outputs/`, and `_evaluate/`
   is the committed-text convention (its PNG/GLB are ignored). Committed text
   lands under `docs/research/2026-09-19-finetune-decision/`; large regenerable
   per-arm JSON and run logs land under `outputs/finetune_decision/`
   (gitignored); rendered turntables stay where the bench writes them, under
   `/Users/ladvien/3dcodebench/results/text_to_3D_agent/ft-<arm>-k<draw>/<inst>/renders/`,
   and `phaseB/scores.csv` carries their paths instead of copying them.
   Evidence: `.gitignore` (`outputs/`, `_evaluate/renders/**/*.png`),
   `docs/research/2026-09-19-finetune-decision/`.

3. **vLLM is not installed on the 3090 host, so §5.2's "vLLM on the 3090" is
   served by the host's existing llama-swap instead** — one
   OpenAI-compatible endpoint for all local arms, which is what the control
   requires. Both checkpoints are served at **F16**, which removes the
   quantization-mismatch limitation §8 asks to record rather than leaving it in
   the report.
   Evidence: `ssh big command -v vllm` → absent;
   `ssh big ls ~/.local/llama.cpp/` → `cuda`, `cuda-ece963`,
   `cuda-prism-1a07bfa`, `llama-b8952`;
   `docs/research/2026-09-19-finetune-decision/env.json`
   (`serving.precision`, `serving.context_tokens`).
