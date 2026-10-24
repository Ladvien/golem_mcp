# Run 2026-10-24-01 — evaluation

## Fail-first, then pass (issue #19)

On unchanged `main` (`blender/src/golem_blender/ops/assets.py` before the edit),
inside Blender 5.2:

```
FAILED tests/blender/test_asset_ops.py::
  test_a_copy_is_placed_where_it_was_told_not_relative_to_the_sources_parent
E  AssertionError: assert bpy.data.objects['Mount'] is None
E   +  where bpy.data.objects['Mount'] = bpy.data.objects['Copy'].parent
```

The old op copied the source's parent, so the copy was never at the location
the call named. After the change the same module plus the five new tests pass
(`make -C blender test-blender-app`; the module run is recorded below).

## The issue's five acceptance conditions, measured in Blender 5.2

Fixture: a 1 m box parented to an empty `Mount` at z=5 (the issue's own case);
`location_m=(1, 2, 3)`. Script kept at `evidence/verify_issue19.py`, its output
at `evidence/issue19-acceptance.txt`.

| # | condition | measured |
|---|---|---|
| 1 | copy at world `(1, 2, 3)` with the default | `(1.0, 2.0, 3.0)` — **pass** (old: `(1, 2, 8)`) |
| 2 | copy at world `(1, 2, 8)` with `keep_parent=True` | `(1.0, 2.0, 8.0)` — **pass** |
| 3 | source's world location unchanged | `(0.0, 0.0, 5.0)` before and after — **pass** |
| 4 | `copy.parent is None` with the default | `True` — **pass** |
| 5 | own mesh data (a boolean on the copy leaves the source alone) | distinct mesh datablocks; a `DIFFERENCE` on the copy cut it to 32 polys while the source kept its 6 — **pass** |
| + | report says when the location is parent-relative | `False` default, `True` with `keep_parent=True` and a non-zero location — **pass** |

Report bounds on the fixed copy: `bounds_min_m [0.5, 1.5, 3.0]`,
`bounds_max_m [1.5, 2.5, 4.0]` — i.e. the measured world box matches
`location_m`, which is what the old code could not say.

## Probe that justified the fix's shape (not just the parent pointer)

`Object.copy()` carries four things, and clearing only `parent` leaves a bone
parent set as `parent_type='BONE'` (measured on a mesh bone-parented to a
`Spine` bone). The fix clears `parent`, `parent_type`, `parent_bone` and
`matrix_parent_inverse`; `test_clearing_the_parent_also_clears_a_bone_parent`
pins that.

## Gates

| gate | baseline (before) | after |
|---|---|---|
| `make test-golem` | 10 passed | **1 failed, 9 passed** — a pre-existing flake, not this change: `tests/test_gpu.py::test_a_job_over_its_timeout_is_terminated_and_reported` fails 4–5 of every 5 runs, and 5 of 5 in a fresh worktree at `c217f2f` (the pre-change commit). `src/golem_mcp/gpu.py` and `tests/test_gpu.py` are untouched by this run. Filed as issue #24 with the measured mechanism and a verified fix. |
| `make -C blender test-pure` | 1547 passed, 1 xfailed | 1547 passed, 1 xfailed |
| `make -C blender test-mcp` | all OK (36 / 1 / 36 / 7 / 53) | all OK (36 / 1 / 36 / 7 / 53) |
| `make -C blender test-blender-app` | 469 passed, 1 skipped | 475 passed, 1 skipped (the six new tests) |

No `test-repro` (no builder touched) and no `test-bench-scripts` (no benchmark
script touched) — neither target covers this op.

## Rendering

Not applicable: the change is placement arithmetic and its evidence is
`matrix_world` read from Blender plus the measured report bounds. There is no
geometry, material, rig or animation appearance to compare, so no renders are
claimed.
