# Run 2026-10-26-02 — six agents, six issues, one worktree each

The fan-out's evidence, kept apart from the run-01 docs so the two runs can be
read independently.

## Isolation, measured before spawning

Each worktree resolved its own package, not the main checkout:

```
a1: /private/tmp/golem-loop/a1   … a6: /private/tmp/golem-loop/a6
```

for `golem_blender` (via `sys.path.insert(0, 'blender/src')`, which shadows the
editable `.pth`) and for `golem_mcp` (via the root `pythonpath = ["src"]`).

## Model routing, verified per child

From each child's own session transcript, not a global counter:

```
loop-a1…loop-a6:
  "model":"deepseek-v4.1-flash:1017"
  "model":"ollama-cloud/deepseek-v4.1-flash:1017"
```

Six of six on the requested model.

## Branch verification before any merge

| agent | commits | files | gates re-run in its own worktree |
|---|---|---|---|
| a1 | 1 (`46bb548`) | 8 | test-golem 10, test-pure 1557 |
| a2 | 1 (`7389091`) | 9 | test-pure 1557 |
| a3 | 1 (`9d00aa3`) | 8 | test-pure 1557 |
| a4 | 1 (`368f5cb`) | 8 | test-pure 1580 |
| a5 | 1 (`6499261`) | 8 | test-pure 1555 |
| a6 | 1 (`c1b873b`) | 3 | test-golem 10, test-pure 1556, test-mcp 53 OK |

Every branch was exactly one commit. `test-blender-app` was run on `main` after
the merges rather than six more times on the branches.

## The merge, pick by pick

| pick | source | conflict | resolution |
|---|---|---|---|
| 1 | a6 `c1b873b` | none | — |
| 2 | a3 `9d00aa3` | none | — |
| 3 | a4 `368f5cb` | pin, BACKLOG, spec row | pin from `TOOL_SCHEMAS_FINGERPRINT`, counts re-measured |
| 4 | a2 `7389091` | pin, BACKLOG, spec row | same; a2's `_contract.py` and `manifest.py` hunks merged clean |
| 5 | a1 `46bb548` | pin, BACKLOG, spec row | same; a1's `_contract.py` hunk merged clean |
| 6 | a5 `6499261` | none | — |

`ops/__init__.py` never conflicted: the four op agents' additions were textually
disjoint and `git` merged all of them.

**The pin was regenerated at every pick that changed it** and the measured
values, not any agent's arithmetic, drove the counts:

| after pick | tools | ops | plan-required | fingerprint |
|---|---|---|---|---|
| a6 | 72 | 63 | 46 | `t:ff9833ed06ec` |
| a3 | 73 | 64 | 47 | (a3's own) |
| a4 | 76 | 67 | 50 | `t:cb85220cfa65` |
| a2 | 77 | 68 | 51 | `t:2960e75df3dd` |
| a1 | **78** | **69** | **52** | **`t:a9c0b64f6da0`** |
| a5 | 78 | 69 | 52 | unchanged (no op) |

Readers stayed 18 throughout. Contract violations across the whole facade: none
at the final state.

## Final gates on merged main

| gate | before the run | after |
|---|---|---|
| `test-golem` | 10 passed | 10 passed |
| `test-pure` | 1553 passed, 1 xfailed | **1597 passed, 1 xfailed** |
| `test-mcp` | 53 OK | 53 OK |
| `test-blender-app` | 487 passed, 1 skipped | **541 passed, 1 skipped** |

## The two findings no issue asked for

1. **`tile_seam_ratio` is axis-blind** (a5): it compares the last column to the
   first and never the rows, so a turned wood's own row steps read as a seam —
   0.001× → 0.224× on a map whose content did not change. Documented in
   `scripts/benchmarks/README.md`'s known-limits list; the test measures both
   axes and asserts the two numbers swap.
2. **Two more pbr modules are unreachable** (a6): the same AST walk that proved
   `pbr/splatter.py` dead cannot reach `pbr/noise_curl.py` or
   `pbr/noise_gabor.py`. #15 named only `splatter.py`, so they were left alone.

## The isolation break

a5 wrote into `/Users/ladvien/golem_mcp` before moving to its worktree, then ran
`git checkout --` on exactly those six files. Main was verified byte-clean
(`git status --porcelain` empty, `git diff HEAD -- pbr/` empty) and a5's branch
gates were re-run in its own worktree before the merge. The user chose to merge
on that evidence. Both facts — the sound work and the broken rule — are in
`docs/loop/log.md` and #12's closing comment.

## Model routing: how it is guaranteed, not just observed

Six children, one model. Counted from each child's own transcript, by purpose:

| child | model calls | model |
|---|---|---|
| loop-a1 … loop-a6 | 3 each, `purpose=task-completion-probe` | `deepseek-v4.1-flash:1017` |

Eighteen of eighteen on the required model; the full `"model"` field audit over
all six transcripts (840 records) found no other model.

**Two layers pin it, and the stronger one now outranks the agent file.**

1. `~/.omp/agent/config.yml` → `task.agentModelOverrides` pins `loop-worker`,
   `task` and `sonic` to `ollama-cloud/deepseek-v4.1-flash:1017`. This layer
   takes precedence OVER agent frontmatter, so a frontmatter edit, a stale agent
   file or a future agent with no `model:` line cannot drift off the required
   model.
2. `.omp/agents/loop-worker.md` (tracked, on `main`) carries
   `model: ollama-cloud/deepseek-v4.1-flash:1017` as the per-agent default.

**Both layers proven by live probes, not inference.** Two throwaway agents, each
deleted afterwards:

- `model-probe` named `deepseek-v4-flash` in its frontmatter and the child failed
  with `HTTP 410 … deepseek-v4-flash:0731 was retired`. The frontmatter's model
  was genuinely what got called, so frontmatter routing is real and not merely
  inheritance from the parent session.
- `routing-check` named the SAME retired model in frontmatter while the config
  override pinned it to `flash:1017`, and the child answered: `override wins`.
  The override layer therefore wins, which is what makes the pin structural.

**One honest caveat about harness-internal calls.** A `purpose=auto-thinking`
record for `typesafe/jev-1.14` appears in a child's transcript. It is the
harness's own classifier, not the agent's work model — the same probe's
`purpose=model` entries are `flash:1017`. The six loop children show no such
entry at all. Reported rather than omitted so the count above cannot be
misread as "every single API call in the process".

## The per-turn audit, and the field that actually answers the question

Earlier in this run I quoted `model_usage` records — 3 per child. Those are
billed calls, but they are `purpose=task-completion-probe`, so **3 records out of
142 work turns** was a badly under-sampled answer that looked complete. The
record that answers "what did this agent actually run on" is the assistant turn:

```
type: message, message.role == "assistant"
  carries provider, model, api, usage, credentialId, ttft, duration
```

Counted over all six children:

| child | work turns | provider / model | off-pin |
|---|---|---|---|
| loop-a1 | 142 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |
| loop-a2 | 135 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |
| loop-a3 | 149 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |
| loop-a4 | 121 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |
| loop-a5 | 212 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |
| loop-a6 | 57 | `ollama-cloud / deepseek-v4.1-flash:1017` | 0 |

**816 work turns, 816 on the required provider and model, 0 off-pin.** Each
child's `model_change` names the same model with `resolvedModelIsFallback:
false`, so no retry switched a child mid-run.

Two records that must not be counted as work turns, named so a future audit
cannot mistake them:

- `purpose=task-completion-probe` usage rows — real billed calls, ~3 per session.
- `purpose=auto-thinking` rows (e.g. `typesafe/jev-1.14`) — the harness's own
  classifier, not an agent work model.

`scripts/audit_task_child_models.py` makes the whole audit repeatable and gives
it an exit status:

```
$ python3 scripts/audit_task_child_models.py
TOTAL work turns: 816 | off-pin: 0
PASS every work turn ran on the required provider and model        # exit 0
```

Proven it can fail, on a two-agent fixture with one drifted child and a fallback
resolution: `exit 1`, with
`FAIL loop-a2: 1 work turn(s) off the required pin` and
`FAIL loop-a2: resolved through a fallback (['anthropic/claude-haiku-5-5'])`.

## Child-side attestation, not only parent-side archaeology

Every check above was the parent reading transcripts. A child can measure the
same thing about itself, and one was spawned to do exactly that — a `self-attest`
agent (frontmatter `model: ollama-cloud/deepseek-v4.1-flash:1017`, since deleted)
told to find its own transcript and report three vectors without trusting the
prompt. It reported, verbatim:

| vector | value |
|---|---|
| `session_init` → `resolvedModel` | `ollama-cloud/deepseek-v4.1-flash:1017` |
| `model_change` → `model` / `resolvedModelIsFallback` | `ollama-cloud/deepseek-v4.1-flash:1017` / `false` |
| assistant turns by `(provider, model)` | `ollama-cloud` × `deepseek-v4.1-flash:1017`, 4 turns, none off |

Two things about that report are worth keeping:

- **It flagged its own weakness.** It noted the transcript is append-only and it
  sits inside it, so its count was the turns written at read time and could never
  include its own final message. The parent audit, run afterwards, counted 5 —
  the predicted growth, not a contradiction.
- **It excluded nothing by accident.** Its transcript contained no
  `model_usage` rows at all, so no turn had to be set aside as a completion probe
  or an `auto-thinking` classifier.

Every model-bearing record class in the six-way run is now accounted for, not
just the work turns: `session_init` resolved the required model in all seven
records across the six children, `title` records are empty (no title-model call),
and `model_usage` appears only as 18 `task-completion-probe` rows.

`scripts/audit_task_child_models.py` now also FAILS on a `session_init` that
resolved another model, so the resolution vector cannot pass unnoticed. Proven:
a fixture whose work turns are all on the pin but whose `session_init` names
`anthropic/claude-sonnet-5-5` exits 1 with
`FAIL loop-a1: session_init resolvedModel is ['anthropic/claude-sonnet-5-5']`.

## The imperative: every child attests, and the parent gates on it

Seven earlier answers were the parent reading transcripts. That is archaeology:
it proves what happened, and nothing makes a future child state its own routing.
The `loop-worker` brief now carries a MODEL section that is an imperative, not a
note:

- measure three vectors from your OWN transcript (`session_init.resolvedModel`,
  `model_change.model` + `resolvedModelIsFallback`, and every assistant turn's
  `provider`/`model`);
- never count a `model_usage` row as a work turn (completion probe or the
  harness's `auto-thinking` classifier);
- if anything differs or `resolvedModelIsFallback` is true, put `MISMATCH:` first
  in the report and do NOT claim the required model;
- publish exactly one line:
  `MODEL_ROUTING: <provider>/<model> across <N> work turns, fallback=<true|false>`

**Proven on a live spawn of the `loop-worker` definition itself:**

```
probe ok
V1 session_init.resolvedModel  -> ollama-cloud/deepseek-v4.1-flash:1017
V2 model_change                -> model ollama-cloud/deepseek-v4.1-flash:1017,
                                  resolvedModelIsFallback false
V3 assistant work turns        -> (ollama-cloud, deepseek-v4.1-flash:1017) x 7

MODEL_ROUTING: ollama-cloud/deepseek-v4.1-flash:1017 across 7 work turns, fallback=false
```

The parent audit run afterwards on the same transcript read 8 work turns on the
same provider/model with `fallback=False`. The count differs by design — a child
cannot see its own final message — so the gate compares the **model**, never the
turn count.

`tests/test_loop_worker_report_routing.py` makes the line a hard requirement and
refuses the two dangerous shapes: no line at all (a confident report with no
attestation) and two lines (one is stale), plus a bare model name with no
provider, which parses but cannot compare equal to the required selector.

## No mid-run switch vector is left open

`task.prewalk`, `task.agentPrewalk` and `task.agentAdvisor` are all unset, and
the agent declares neither `prewalk` nor `advisor` — so no child can start on the
pinned model and be handed off to another one after its first edit.

## Concurrency: six at once, each attesting, all on the pin

Every earlier probe was a single spawn, and the real fan-out had six agents in
flight — which is exactly when a provider rate limit could cause a silent
switch. So six `loop-worker` agents were spawned **in one batch** and told to do
nothing but measure and attest their own routing.

Each child's own report, and the parent audit run afterwards:

| child | child's own attested turns | parent audit turns | provider / model | fallback |
|---|---|---|---|---|
| conc-a1 | 4 | 5 | `ollama-cloud / deepseek-v4.1-flash:1017` | false |
| conc-a2 | 7 | 8 | same | false |
| conc-a3 | 2 | 3 | same | false |
| conc-a4 | 6 | 7 | same | false |
| conc-a5 | 4 | 5 | same | false |
| conc-a6 | 3 | 6 | same | false |

**34 work turns under concurrency, 0 off-pin.** Every child also reported
`session_init.resolvedModel` and `model_change.model` agreeing, with
`resolvedModelIsFallback: false`. Where the parent's count exceeds the child's,
that is the append-only growth a child cannot see (its own final message); a6's
gap is larger because its measurement ran earlier in a longer turn. The model,
which is what the requirement names, agreed in every case.

## Why a silent switch is not merely unlikely but impossible here

`retry.fallbackChains` in the user config contains exactly one key, `web`. There
is **no model fallback chain**, so a model failure ERRORS rather than quietly
switching provider. Combined with `task.prewalk`, `task.agentPrewalk` and
`task.agentAdvisor` all being unset and the agent declaring neither `prewalk` nor
`advisor`, there is no configured path by which a child starts on the pinned
model and continues on another.

## The audit had a blind spot, and finding it was the point

Nine earlier answers swept `loop-a*.jsonl`. The session actually held **17 child
transcripts**: six `loop-a*`, six `conc-a*` from the concurrency test, and five
probes. The default run therefore printed

```
TOTAL work turns: 816 | off-pin: 0
PASS every work turn ran on the required provider and model
```

having read **6 of 17 children**. A narrow default is the worst kind of audit
bug: it prints PASS for a population it never looked at.

Sweeping all 17:

| group | work turns | off-pin |
|---|---|---|
| `loop-a1..a6` (the fan-out) | 816 | 0 |
| `conc-a1..a6` (concurrency test) | 34 | 0 |
| probes (`probe-imperative`, `probe-loopworker`, `probe-override`, `probe-selfattest`) | 15 | 0 |
| `probe-model` (deliberate discriminator) | 1 | **1** |

**866 work turns, 1 off-pin — and that one is the point of the exercise.**
`probe-model` was spawned ON PURPOSE on the retired `deepseek-v4-flash` to prove
which layer routes; its single turn is
`provider: ollama-cloud, model: deepseek-v4-flash, stopReason: error`, empty
output. It is the control that makes the pin meaningful, not a drifted worker.

The script now:

- sweeps **every** child transcript by default, excluding only the parent's own
  dated `2026-*.jsonl`;
- takes `--allow-off-pin AGENT` for exactly that discriminator case, and prints
  `NOTE excused as a deliberate discriminator: probe-model` so an excused child
  can never be silently green;
- is covered by three new tests — a conforming directory passes, an off-pin child
  ANYWHERE in the directory fails (not just in `loop-a*`), and an excused agent
  is named in the output.
