# Prompt Convergence Loop — Plan

**Date:** 2026-08-22
**Evidence base:** `docs/research/2026-08-20-agentic-blender-game-asset-harness-research.md`
**Tunable artifact:** `src/blended/agent/system_prompt.py`

## What exists already

The harness is built through Stage 5 of the roadmap. `AgentSession` (writer +
separate vision "eye") drives `dispatch_tool`, which routes `run_python`
through `harness.run_chunk` -> analyzer gate -> contact sheet. The analyzer
(`analyze/mesh_checks.py`) is the hard deterministic gate. What does NOT exist
is the convergence loop itself: nothing records iterations, nothing versions
the prompt, there is no test-prompt suite with a deterministic acceptance
spec, and there is no mistake memory.

## Blocking defect (Phase 0)

`TARGET_BLENDER_SERIES = (5, 0)`; the installed Blender is 5.2.0 LTS. Effects:

1. `make test-blender-app` -> 1 failed, 72 passed. No green baseline.
2. `build_system_prompt()` interpolates the pin into its first line, so the
   harness currently **tells the model it is running Blender 5.0 when it is
   running 5.2**. That violates design commitment 5 (pin the API) at the exact
   point the prompt is supposed to be authoritative.

Fix: bump the pin to (5, 2), add the 5.0->5.2 observation to `drift/catalog.py`
in the same commit (commitment 5), re-run the suite to green.

## Phase 1 — loop infrastructure (harness code, not prompt tuning)

| Piece | File | Purpose |
|---|---|---|
| Versioned prompts | `src/blended/agent/prompt_versions.py` | Prompt as an addressable, rollback-able artifact. `PROMPT_VERSIONS[n]`, `ACTIVE_PROMPT_VERSION`. |
| Test-prompt suite | `src/blended/evaluate/briefs.py` | `AssetBrief`: prompt text + **deterministic acceptance spec** (named dims + tolerances, component count, budget, feature assertions). Config, not construction. |
| Deterministic gate | `src/blended/evaluate/acceptance.py` | Executes the spec against the built scene. Returns measured deltas, never booleans alone. |
| Iteration log | `src/blended/evaluate/iteration_log.py` | Append-only JSONL: prompt version, plan, gate results, render path, deviations, classification, hypothesis, outcome. |
| Mistake memory | `src/blended/evaluate/mistake_memory.py` | In-package (failure -> cause -> fix -> guarding assertion). Consulted before every adjustment. |
| Driver | `scripts/run_agent_task.py` | Runs one brief through `AgentSession` inside real Blender headless; runs acceptance; renders; appends the iteration record. |

## Phase 2 — the loop

RUN -> RENDER -> EXAMINE (deterministic gate, then visual critique, then
classify) -> ADJUST (exactly one prompt element, hypothesis stated first) ->
REPEAT. Cap 10 iterations.

Classification decides the action, and only one of the four touches the prompt:
- **prompt failure** -> one surgical prompt edit
- **harness-code failure** -> fix the code, no prompt edit
- **harness-critique failure** -> fix the critique (question set, render, or move
  the judgement into the deterministic gate), no prompt edit. The critique is a
  fallible instrument: LL3M's critic VLM missed spatial errors a human caught,
  and the TikZ study measured visual verification at imperfect precision and
  recall. A missed deviation and a false positive are both critique failures,
  and tuning the working agreement to satisfy a blind critic tunes the wrong
  artifact.
- **bad test prompt** -> fix the brief, no prompt edit

## Phase 3 — convergence

One clean human-verified run per brief, consecutive, with no prompt change
between them — the rule the 2026-08-22 five-brief attempt used. A run is clean
when the driver exits 0 and the human reports zero visual deviations. The
earlier "3 consecutive runs" rule was a proxy for "the suite passes" when the
suite was two briefs; with five briefs, the rule is one run per brief, so a
prompt that fixes one brief by breaking another cannot earn the pin. Then: pin
`prompt_vN`, capture regression tests at builder / assembly / scene level with
parameter snapshot + golden render, record final version and evidence in the
mistake memory.

Abort at 10 iterations: stop, present the full log, state what blocks
convergence. Never ship a degraded prompt.
