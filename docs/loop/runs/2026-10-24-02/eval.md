# Run 2026-10-24-02 — six agents over the assembly ops (#25, #26, #23, #17) and the PBR pair (#14, #13)

The tier-1 fan-out that follows the blacksmith-shop session. Six open issues,
one agent each, one worktree each, one model, then a fixed-order merge.

## Why these six

The blacksmith-shop session (`~/sanctuary`, 49-part building) filed #25 and #26
out of four measured placement defects and one refused export:

| defect | measured | issue |
|---|---|---|
| two rear corners 11.10 cm apart — every wall "correctly" placed | the village-kit pier's origin sits **11.1 cm** off its bounds centre in y | #25 |
| shelf brackets **111.9 cm** off the wall they support | placement by origin, not by face | #25 |
| a tool board hung flat against a wall instead of facing the room | no way to say "this face looks at the room" | #25 |
| a tuyere pipe **50 cm** from the bellows' nozzle while its bounding box overlapped by 30 cm | a box overlap is not a connection | #25 |
| `export_asset` refused the finished building | single-object gate: 21 328 tris, 6 943 components, 6 486 self-intersecting pairs — *what an assembly is* | #26 |

#23 and #17 are the same complaint from the measurement side: every real asset
is several objects, and golem measured one. #14 and #13 are the two PBR-lane
visual defects small enough to carry in the same run.

#25 and #26 lead the merge order because between them they remove four
origin-class defects and the unusable export.

## Isolation, measured before spawning

BASE `4485106` (pushed to `origin/main` first: `21192b3..4485106`, fast-forward).

Six worktrees under `/tmp/golem-loop/a1..a6`, each resolving its own package:

```
/private/tmp/golem-loop/aN/blender/src/golem_blender/__init__.py
```

for `golem_blender` (via `sys.path.insert(0, 'blender/src')`, which shadows the
editable install).

The `.venv` and `blender/.venv` symlinks point at the shared venvs. A trailing-
slash `.gitignore` pattern ignores a DIRECTORY and not a symlink, so they showed
as untracked in every worktree — a bare `git add -A` would have committed an
absolute path to a shared venv. Both were added to `.git/info/exclude` (local,
uncommitted, applies to all six worktrees) so a clean status means what it says.

## Baselines at the base, re-measured

| gate | value |
|---|---|
| `make test-golem` | 33 passed |
| `make -C blender test-pure` | 1597 passed, 1 xfailed |
| `make -C blender test-mcp` | 53 tests OK |
| `make -C blender test-blender-app` | 541 passed, 1 skipped |

Tool surface at the base: 78 tools, fingerprint `t:a9c0b64f6da0`.

## Model routing, verified per child

`scripts/audit_task_child_models.py --allow-off-pin probe-model`:

```
TOTAL work turns: 1235 | off-pin: 0
PASS every work turn ran on the required provider and model
```

| child | work turns | model | fallback |
|---|---|---|---|
| a1 `AlignOps` | 159 | `ollama-cloud/deepseek-v4.1-flash:1017` | false |
| a2 `AssemblyOps` | 94 | same | false |
| a3 `MeasureObjects` | 179 | same | false |
| a4 `PieceGrouping` | 81 | same | false |
| a5 `PbrSmallDefects` | 106 | same | false |
| a6 `PbrHeightRange` | 181 | same | false |

Every child's own report also carried its `MODEL_ROUTING:` line, and each names
`ollama-cloud/deepseek-v4.1-flash:1017` with `fallback=false`.

## Branch verification before any merge

| agent | issue | commits | commit | gates re-run in its OWN worktree |
|---|---|---|---|---|
| a1 | #25 | 1 | `4e2c51a` | golem 33, pure 1638/1xf |
| a2 | #26 | 1 | `0b5d2d7` | golem 33, pure 1613/1xf, mcp OK |
| a3 | #23 | 1 | `031ba8d` | golem 33, pure 1607/1xf, mcp OK |
| a4 | #17 | 1 | `6ee3bfd` | golem 33, pure 1612/1xf |
| a5 | #14 | 1 | `635bf1c` | pure 1607/1xf |
| a6 | #13 | 1 | `2785854` | golem 33, pure 1601/1xf |

Every branch was exactly one commit and every changed file was under
`blender/` or `docs/`.

## The merge, pick by pick

| pick | source | conflicts | resolution |
|---|---|---|---|
| 1 | a5 `635bf1c` | none | — |
| 2 | a6 `2785854` | none | — |
| 3 | a3 `031ba8d` | none | — |
| 4 | a4 `6ee3bfd` | pin, BACKLOG, spec row, `manifest.py` | both sides kept; pin regenerated; counts re-measured |
| 5 | a1 `4e2c51a` | pin, BACKLOG, spec row, `ops/__init__.py` | both sides; `TargetPlane` ahead of `UnknownPiece` |
| 6 | a2 `0b5d2d7` | pin, BACKLOG, spec row, `ops/__init__.py` | both sides; `define_assembly` before `define_piece`, `export_assembly` after `duplicate_object`, `rename_object` before `render_assembly` |

The pin was NEVER resolved by taking a side. It was regenerated from
`TOOL_SCHEMAS_FINGERPRINT` at every pick and the file then compared to the
printed value:

| after pick | tools | ops | plan-required | readers | fingerprint |
|---|---|---|---|---|---|
| base | 78 | 69 | 52 | 18 | `t:a9c0b64f6da0` |
| a5 | 78 | 69 | 52 | 18 | unchanged |
| a6 | 78 | 69 | 52 | 18 | unchanged |
| a3 | 79 | 70 | 53 | 19 | `t:1594bd99e511` |
| a4 | 81 | 72 | 53 | 20 | `t:308fc204331e` |
| a1 | 84 | 75 | 56 | 20 | `t:653aa9236910` |
| a2 | **88** | **79** | **59** | **21** | **`t:365aafec29d4`** |

88 tools is exactly the base 78 plus the eleven ops added — the plan's predicted
count, confirmed by measurement rather than arithmetic.

`test-pure` was run after every pick (1607, 1611, 1621, 1636, 1677, 1693), so a
wrong resolution was caught at the pick that caused it.

## The one rule broken

a2 wrote a 71-line entry into `docs/loop/log.md` naming its commit `loop/a2` and
inventing run id `2026-10-26-03`. The run log is written after the merge, when
the real shas exist, so that hunk was DROPPED at its pick (`git checkout HEAD --
docs/loop/log.md` before `--continue`) and the entry in `log.md` replaced it.
The code itself was sound and merged whole.

## Final gates on merged `main`

| gate | before the run | after |
|---|---|---|
| `test-golem` | 33 passed | 33 passed |
| `test-pure` | 1597 passed, 1 xfailed | **1693 passed, 1 xfailed** |
| `test-mcp` | 53 OK | 53 OK |
| `test-blender-app` | 541 passed, 1 skipped | **605 passed, 1 skipped** |
