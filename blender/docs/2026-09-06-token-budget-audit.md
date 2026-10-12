# Token budget audit — measured 2026-09-06

The honest answer to "are we making the best use of caching": **nobody
had checked.** The harness had no token accounting of any kind — no
`usage` parsing on any lane, no cost in the iteration log, and the
`rate_limit_event` frame the Claude Code transport already parses was
never recorded. Everything below is measured, not estimated.

Measurement scripts: `outputs/token_cost_probe.py` (cache behaviour),
`outputs/token_cost_probe2.py` (flag isolation),
`outputs/token_cost_probe3.py` (API calls per invocation),
`outputs/token_cost_run.py` (one real brief, instrumented).

## What is already right

**Prompt caching works across our stateless processes.** The transport
spawns one `claude -p` per turn with `--no-session-persistence`, which
looks like it should defeat caching. It does not — Anthropic's cache is
server-side and content-addressed:

| invocation | cache write | cache read | cost |
|---|---|---|---|
| cold | 12,241 | 0 | $0.0507 |
| warm (byte-identical) | 0 | 12,241 | $0.0043 |
| grown (same prefix + one turn) | 948 | 11,355 | $0.0080 |

**11.8x cheaper warm than cold**, and a grown transcript re-reads the
prefix and writes only the delta. Three properties earn that, all of
them accidental rather than designed, and all worth protecting:

1. The system prompt is built ONCE per session
   (`AgentSession.__post_init__`) and is byte-stable across builds —
   verified by hashing two independent `build_system_prompt()` calls.
   Nothing volatile (scene state, timestamps, counters) is injected
   into it.
2. History is strictly APPEND-ONLY: `send()` appends user, assistant
   and tool messages and never rewrites an earlier one.
3. `render_call` folds deterministically, so turn N+1's wire bytes have
   turn N's as a prefix. The continuation cue is appended at the end
   each turn and never lands mid-transcript.

Any future change that edits history in place — pruning old renders,
summarising early turns, injecting live scene state into the system
prompt — breaks all three and forfeits the 11.8x. That is the single
most valuable invariant in this document.

**The eye is lean.** `VisionDescriber.describe` sends the question and
the images with NO system prompt. Shipping eye == writer also removed
the second model call per render entirely (`uses_separate_eye` False).

**Renders are already small.** Views are 512x512 = ~349 image tokens.

## What is measurably wasted

### 0. What a brief actually costs

`planter_box` at revision 11, examiner off, recorded by the accounting
this audit added (`_evaluate` row 900, `outputs/cost_check_*.jsonl`):

| | |
|---|---|
| harness turns | 13 |
| **API calls** | **26** |
| cache reads | 502,618 tok (0.1x) |
| cache writes | 236,169 tok (1.25x) |
| fresh input | 52 tok |
| output | 30,535 tok |
| **cost** | **$1.4182** |

Two facts fall out. **Caching is doing its job**: 502,618 of 738,839
input tokens are cache reads and only 52 are fresh. And **85% of the
effective input cost is cache WRITES** — 236,169 at 1.25x against
502,618 at 0.1x, or 9,083 written per API call. At this rate a 5-brief
cycle costs **~$7 and 3.7M input tokens** before the examiner is even
switched on, and three cycles were run today.

The write column is where the money is, and it is driven by CALL
COUNT, not by our prompt: each of the 26 calls re-reads the prefix and
writes its own tail.

### 1. Two to three API calls per harness turn (largest, ~2x)

A separate build-only run of `crate_with_lid` (7 turns, no refinement)
shows the same shape at smaller scale: **14 API calls**, cache_read
198,176, cache_write 44,961, $0.0733 — 76,019 effective
token-equivalents against 243,137 uncached, a **69% saving from
caching** and still 3.4x the content we assembled.

| turn | api calls | our assembled prompt | billed input |
|---|---|---|---|
| 1 | 2 | ~12.5k | 25,851 |
| 2 | 2 | ~12.6k | 26,842 |
| 3 | 3 | ~15.1k | 48,247 |
| 4 | 2 | ~17.5k | 37,062 |
| 5 | 2 | ~17.9k | 38,172 |
| 6 | 1 | ~18.0k | 19,144 |
| 7 | 2 | ~22.5k | 47,847 |

Counted from `message_start` stream events. A turn that assembles 12.5k
of prompt bills 25.8k because the CLI runs the model twice: once for
the turn, once to conform the answer to `--json-schema`. Isolated by
varying one flag at a time — `--effort`, `--json-schema` and
`--include-partial-messages` each bill exactly 1.0x one call on a
prompt the model answers immediately, so the second pass appears when
the turn does real work. No CLI flag suppresses it (`claude --help`).

### 2. CLI overhead is 40% of every call

Our own content in a minimal call is 7,374 tok (system prompt 5,686 +
envelope schema 1,547 + tool protocol note 141). The call bills 12,241.
The difference — **4,867 tok, 40%** — is Claude Code's own system
prompt, charged on every one of the 26 calls a brief makes.

### 3. The examiner costs more than the writer

`examine_view` calls the eye TWICE per view (position-bias mitigation,
10.48550/arXiv.2306.05685) across 5 views = **10 cold CLI processes per
brief**, each carrying 2 images (~700 tok) plus the 4,867 tok CLI
overhead plus the examiner prompt. That is ~83k tok per brief examined
and ~415k per 5-brief cycle. And `_evaluate/verdicts.jsonl` stores only
aggregate deviations, so there is no evidence about which views ever
earn their two calls.

**Measured 2026-09-06** (`--cross-run-only`, 4 briefs): 40 eye calls,
258,200 input tok, $0.4165 — **$0.104 and 64,550 input tok per brief
examined**. And the instrument those calls buy has a cross-run control
specificity of **0.50**, so most of that spend currently buys a
deviation the brief never specified. Cost-of-pass, not tokens: see
`docs/2026-09-06-token-budget-plan.md`.

### 4. Contact sheets accumulate in the prefix

The writer's sheets are 1048x1568 = **2,191 image tokens** each
(588-945 KB). By turn 7 the transcript carried four of them: ~8.8k
tokens of the prefix and 4.4 MB of base64 through the pipe every turn.
Re-reads are cheap (0.1x) but each sheet is written once at 1.25x, and
the wire cost is real.

### 5. Cold start per run

Every `run_agent_task` invocation starts cold: 12.2k written at 1.25x =
15.3k token-equivalents. A 5-brief cycle pays that 5 times, plus once
per examiner process.

## Hypothesis tested and REJECTED

Since writes cost 1.25x and dominate, the obvious suspect was the fold:
`render_call` merges every message since the last image into ONE text
block, so the trailing block mutates every turn and a cache breakpoint
placed after it cannot match on the next turn.

Measured (`outputs/token_cost_probe4.py`, three cumulative turns sent
both ways, same text, only block boundaries differing):

| turn | as shipped (1 merged block) | one block per message |
|---|---|---|
| 1 | write 1,374 | write 2,057 |
| 2 | write 5,369 | write 3,242 |
| 3 | write 5,169 | write 6,102 |

No reliable improvement — turn 3 is WORSE — so block layout is not the
lever and the transport keeps its single-block fold. What the numbers
do show is that writes track the number of API calls: the turns that
billed three calls wrote the most. Cutting calls is the only measured
lever on the write column.

## Ranked proposal

Each item states the measured target and how it is verified. Nothing
here is a guess; where an item needs a number we do not have, the item
is "measure it", not "change it".

**0. Record what we spend — DONE 2026-09-06, this is what produced the
numbers above.** `TurnCost` in `agent/claude_code.py` parses the result
frame's `usage` and counts `message_start` events for the real call
count; `_turn_cost_from_body` does the same job from `prompt_tokens` /
`prompt_eval_count` on the OpenAI and Ollama lanes; `OllamaClient.spent`
accumulates, `VisionDescriber.describe` folds the eye's client back in,
and `IterationRecord` carries `api_calls`, `input_tokens`,
`cache_read_tokens`, `cache_write_tokens`, `output_tokens`, `cost_usd`.
`run_agent_task` prints a `spent:` line. Zero on the 69 older rows
means "not recorded", not "free". Verified end to end: row 900 reports
26 api calls / 738,839 input / $1.4182, matching the transport totals.

**Guarded, because the 11.8x is worth a test.**
`test_a_growing_transcript_keeps_the_previous_turn_as_its_prefix` and
`test_the_system_prompt_is_byte_stable_across_builds` in
`tests/pure/test_claude_code_lane.py` fail the moment someone prunes
history, summarises early turns or injects live state into the system
prompt — the three things that would forfeit caching silently.

**1. Cut examiner calls 10 -> 2 per brief (biggest single saving,
~66k tok/brief).** Send all five views in ONE call per ordering instead
of one call per view. The eye already handles multiple unfused images
in order on this lane (measured: 1315/1685/2068 tok for 0/1/2 images).
This changes the instrument, so it MUST be re-licensed on the fixture
zoo — which is the cross-run calibration work already pending from the
convergence halt. One change, two problems.
Verified by `make calibrate-eye`: sensitivity >= 0.6 and control
specificity 1.00, or the change is rejected.

**2. Log per-view tags, then retire views that never earn them.**
Cheap, and it converts item 1's remaining cost into evidence. If
`bottom` has never produced an order-consistent tag, it is 2 calls per
brief for zero information. Verified against the extended verdict log
over one full cycle before any view is dropped.

**3. Decide the billing question deliberately.** The double call and
the 4,867-tok overhead are the CLI's, and only leaving the CLI for the
direct Anthropic API removes them. But the CLI rides the SUBSCRIPTION
while the API is metered dollars: at $0.073 a brief the money is
trivial, so the real currency is the 5-hour window. If that window is
the binding constraint, reduce CALLS (items 1-2); if it is not, change
nothing. Item 0 supplies the number that decides this.
NOT proposed: `--resume`/`--session-id`. The API is stateless, so a
resumed session re-sends its history exactly like we do; caching
already covers it, and the CLI's session store would become a second
source of truth beside `AgentSession.messages`, which the recorder and
replayer read.

**4. Measure a smaller contact sheet before shrinking one.** A 2x2
sheet at 768x768 costs 786 tok against 2,191 — but a sheet the writer
cannot read costs a whole run. Verified on the fixture zoo the same way
the eye is licensed; adopt only if the gates hold.

**5. Protect the cache invariant with a test.** The 11.8x depends on
byte-stability and append-only history, both currently accidental. A
pure test that folds a two-turn transcript twice and asserts turn 2's
wire bytes start with turn 1's would fail the moment someone prunes
history or injects live state into the system prompt.

## Not a problem, checked

- **Tool result verbosity**: the whole transcript text after 7 turns is
  6,989 chars. Gate reports are already terse.
- **llama-swap / Ollama lanes**: append-only prefix stability is
  exactly what llama.cpp's slot KV reuse needs, so those lanes benefit
  from the same invariant. No change, and none possible without
  touching remote config.
- **The envelope schema** (1,547 tok/call) is rebuilt per call but
  byte-identical, so it is cached; trimming it would trade behaviour
  for pennies.
