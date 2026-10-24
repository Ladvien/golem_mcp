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
