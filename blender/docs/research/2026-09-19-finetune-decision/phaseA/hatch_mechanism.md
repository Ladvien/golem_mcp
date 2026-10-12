# The hatch share, its instrument, and why the facade is abandoned

Every number here is read from artifacts already on disk: the schema-2 `tool_event` blocks in `<inst>/.agent_transcript.txt`, the `# --- chunk N ---` / `# --- op N: name ---` labels in the baked `<inst>/<inst>.py`, and `<inst>/.agent_meta.json`. No roll and no re-bake.

## 1. The published hatch share is partly an instrument reading

164 of 285 harness attempts come from rolls whose `.agent_meta.json` carries no `n_op_calls_included` key at all: that era's bridge collected `run_python` and nothing else, so those attempts CANNOT show an op call however many the agent made. Measured directly on `blended-deepseek-v4-pro-ops-roll1/Tap_seed0`: 13 scene-changing op calls dispatched, every one `ok`, and 0 op labels in the baked script.

| corpus | attempts | chunks | scene ops | hatch share | attempts using an op |
|---|---|---|---|---|---|
| all rolls, passing | 154 | 1271 | 34 | 97.4% | 17 |
| all rolls, failing | 111 | 1054 | 99 | 91.4% | 22 |
| op-collecting rolls, passing | 72 | 321 | 34 | 90.4% | 17 |
| op-collecting rolls, failing | 49 | 235 | 99 | 70.4% | 22 |

Two further biases in the published counts, both from `bench_bridge`: `emits_geometry` is "hatch or any facade op", so `n_op_calls_included` counts READER ops (69 of them across the archive) as geometry-emitting, and `n_chunks_included` is the label counter, which advances on op calls too.

## 2. Op-failure feedback is NOT the mechanism

The hypothesis: an op call that errors teaches the agent, inside the run, that `run_python` is the reliable path. It predicts a higher op failure rate in the multi-turn archive than in single-shot A1, and a first chunk that FOLLOWS the first op failure. Both predictions fail.

The archive column below is the 121 instrumented attempts whose bake COULD collect an op call; pooling the pre-collection rolls in would read their instrument blindness as agent failure.

| quantity | archive (multi-turn) | A1 (single-shot) |
|---|---|---|
| scene-op calls dispatched | 143 | 746 |
| ... never collected by the bake | 7.0% | 26.3% |
| chunks dispatched | 607 | 59 |
| ... never collected by the bake | 8.4% | 8.5% |

The op path is no less reliable in the archive than in A1. Ordering kills the hypothesis outright: of 144 instrumented attempts that used a chunk, 96 never called a scene-changing op at all, and of the 16 that did see an op fail, only 5 failed BEFORE the first chunk — 11 had already switched. 93.8% of instrumented attempts made a chunk their FIRST geometry-emitting call. The facade is not abandoned after it breaks; it is never entered.

## 3. What does separate the rolls: the offered set

| roll | writer | attempts | instrumented | disclosed set | baked op share | dispatched op share |
|---|---|---|---|---|---|---|
| blended-deepseek-v4-pro-disclosed2-roll1 | deepseek-v4-pro:cloud | 20 | 20 | yes | 23.9% | 24.3% |
| blended-deepseek-v4-pro-disclosed2-roll3 | deepseek-v4-pro:cloud | 20 | 20 | yes | 22.6% | 22.5% |
| blended-deepseek-v4-pro-disclosed2-roll2 | deepseek-v4-pro:cloud | 16 | 16 | yes | 20.7% | 21.3% |
| blended-deepseek-v4-pro-disclosed-roll2 | deepseek-v4-pro:cloud | 20 | 20 | yes | 18.7% | 16.7% |
| blended-deepseek-v4-pro-disclosed-roll3 | deepseek-v4-pro:cloud | 20 | 15 | yes | 16.2% | 15.1% |
| blended-deepseek-v4-pro-disclosed3-roll1 | deepseek-v4-pro:cloud | 20 | 15 | yes | 15.1% | 15.1% |
| blended-deepseek-v4-pro-disclosed-roll1 | deepseek-v4-pro:cloud | 20 | 20 | yes | 14.0% | 12.6% |
| blended-claude-code-sonnet-dev | claude-code:sonnet | 12 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-chat1 | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-chat1-roll2 | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-dev-iter3 | deepseek-v4-pro:cloud | 12 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-iter1 | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-iter2 | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-iter3 | deepseek-v4-pro:cloud | 20 | 0 | no | 0.0% | — |
| blended-deepseek-v4-pro-ops-roll1 | deepseek-v4-pro:cloud | 20 | 20 | no | 0.0% | 23.4% |

Every roll that offered the disclosed set (`t:6b6093efb569`, the 29-of-56 set production offers today) bakes a nonzero op share; every roll that predates op collection bakes zero, and for the rolls with no tool events at all the distinction between "did not call" and "was not recorded" is not measurable. A1, single-shot with all 56 schemas offered, baked 91.1% ops.
