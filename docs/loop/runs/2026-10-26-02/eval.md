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
