# Run 2026-10-25-01 — deploy

## The commit

`TBD` — `golem: the GPU-timeout test stops racing bash's startup (issue #24)`.

Changed file: `tests/test_gpu.py` only. `src/golem_mcp/gpu.py` is byte-identical
to HEAD (verified: `git diff --quiet HEAD -- src/golem_mcp/gpu.py`).

## Mac half

| check | result |
|---|---|
| anything read at server start changed? | **no** — no `src/golem_blender` file and no `blmcp` tool module was touched, so the running `golem` MCP serves identical code |
| tool count / fingerprint | unchanged at 71 / `t:7a8ffdbc17da`; the pin file needs no edit |
| smoke call needed? | none — both halves' tool surface is untouched by this change, so a call would prove nothing about it. The deploy question ("is the new code running?") is answered by the changed file not being loaded by either server |
| Blender add-on | untouched (`blender_mcp/addon` not edited), so no restart |

## big

`src/golem_mcp` is unchanged, so big's editable install serves byte-identical
code. The unit was **not** restarted, and no GPU job was running or queued that
the change could affect. No `make sync-golem` (no dependency change).

## bmb

Untouched: no mflux or rigging change. No documented procedure needed, nothing
written to `needs-decision/`.

## What "deployed" means for a test-only change

A test change is deployed by the commit landing on `origin/main` and the gates
being green at that commit — there is no server to restart. Recorded here so the
next iteration can tell "no deploy needed" from "deploy skipped".
