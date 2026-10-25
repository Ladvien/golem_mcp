# Run 2026-10-24-03 — deploy

## The commit

One commit onto `main`, no cherry-picks:

```
8ad89db  blender: a long assembly call cannot wedge the session or lose the scene, and how an object faces is measurable
```

Every code change is Mac-half (`blender/`). `src/golem_mcp`, `pyproject.toml` and
`uv.lock` are untouched, so big's editable install serves byte-identical code and
no host needed a dependency sync.

## What it answers

Measured need, from one live bakery session (77 parts): `export_assembly`
outlived the client's 300 s socket timeout, the bridge answered `PAUSED:` — "no
Blender" — while Blender was still measuring, and the parts existed only in
memory. Plus four questions that kept being answered by hand-written
`run_python` raycasts (surface height, face pitch, which side is an opening,
which side faces away), and a `assembly_report` that could not separate an
intended clash from a defect.

- `run/call_context.py` (new): progress file, safety copy, wall-clock deadline.
- `gate="none"|"structure"|"full"` + `budget_s` on `define_assembly`,
  `assembly_report` and `export_assembly`; `truncated` + `skipped_checks`.
- `export_assembly` saves the safety copy, then the `.blend`, then the `.glb`,
  and gates afterwards.
- `declare_join(first_name, second_name, reason)`, feeding
  `undeclared_clashes` / `declared_without_contact`.
- `measure_feature(object_name, kind=...)` (new `ops/features.py`).
- `connection.BlenderCallTimedOut` (not a `ConnectionError`, so not a pause) and
  a 1800 s golem-lane timeout with an MCP progress heartbeat.
- The root cause of the wedge: the welded-assembly analyses now pass
  `MeshBudget()`, which allows UV overlaps, so the pairwise count is skipped.

## Verification, before the push

| suite | result |
|---|---|
| `make -C blender test-pure` | **1726 passed, 1 xfailed** (baseline 1708 + 1) |
| `make -C blender test-blender-app` | **658 passed, 1 skipped** (baseline 633 + 1) |
| `make -C blender test-mcp` | **OK** |
| `make test-golem` | **33 passed** |
| facade from its own output | 92 tools / 83 ops / 62 plan-required / 22 readers, `t:53a0be11d45e`, equal to the pin |

## Headless reproduction of the wedge (throwaway `/tmp/repro_wedge.py`)

77 parts on a 7 x 11 grid at 0.9 m pitch, `define_assembly(gate="structure")`
then `export_assembly(gate="full", budget_s=5.0)` inside a `call_context`:

| measurement | value |
|---|---|
| `define_assembly(gate="structure")` | 0.03 s, 256 candidate pairs, 0 checked with triangles |
| export, 5 292-triangle parts, `budget_s=5.0` | **5.01 s**, `truncated True`, 23 of 77 parts checked, skipped `['clearance', 'combined_analysis', 'reimport']` |
| the files after a truncated export | `.glb`, `.blend`, `progress.json`, `scratch/export_assembly.blend` — **all four present** |
| export, 192-triangle parts, `budget_s=5.0` | 2.71 s, `truncated False`, 77 of 77 checked, `assembly_failures()` empty |
| `progress.json` as written | `{"tool": "export_assembly", "stage": "re-import", "part": 1, "of": 1, "elapsed_s": 2.7}` |
| `analyze_object` on the welded sheet, no budget | **11.74 s**, 98 565 overlapping UV pairs |
| the same, `MeshBudget()` | **0.12 s**, 0 (the count is not asked for) |

The last two rows are step 1's own price: **98x** for a number
`ExportReport.assembly_failures` never reads.

## Release to the four machines

| host | role | before | after | check |
|---|---|---|---|---|
| mac_air | Mac half, this machine | `8ad89db` | `8ad89db` | already at HEAD (the commit was made here); 92 / `t:53a0be11d45e`, `measure_feature` and `declare_join` both import |
| big_mac | Mac half | `1665cf4` | `8ad89db` | pulled `--ff-only`; **92 / `t:53a0be11d45e`**, both ops import |
| bmb | Mac half | `1665cf4` | `8ad89db` | pulled `--ff-only`; **92 / `t:53a0be11d45e`**, both ops import. No `make sync`: neither `blender/pyproject.toml` nor `blender/uv.lock` changed in `1665cf4..8ad89db` |
| big | GPU half, HTTP service | `1665cf4` | `8ad89db` | pulled `--ff-only`; `git diff --quiet 1665cf4 8ad89db -- src pyproject.toml uv.lock` is **zero**, so the service's code did not move and `systemctl --user restart golem-mcp` was correctly skipped. `systemctl --user is-active golem-mcp` → **active**; `gpu-tenant status` → `tenant=none`, `queue=0` |

**big_mac and bmb were one commit behind, not stale**: `1665cf4` is this
machine's own previous HEAD (`22e709f`'s parent), so both fast-forwarded
cleanly with no local changes to reconcile.

**big_mac's `golem` entry** still sits in `~/.omp/agent/mcp.json`
`disabledServers`, and its Blender is 5.0.1, so it cannot host the 5.2 add-on.
Both left exactly as they were — recording is the point; a release does not
silently re-point a server the user disabled.

## Live smoke — NOT RUN, Blender is closed

`require_live_blender()` answered `No open Blender answers at localhost:9876
(Connection refused)`, and nothing listens on 9876. Blender was not started: the
tools drive the user's open Blender and starting one is the thing the pause
exists to prevent.

What was checked instead, against the real MCP server process (no Blender
needed to list what it serves):

```
measure_feature True   declare_join True   export_assembly True
assembly_report True   define_assembly True
TOOL_COUNT 92
MEASURE_FEATURE_KEYS ['against_name', 'face_selector', 'kind', 'object_name', 'x_m', 'y_m']
```

The three reader results the plan asked to quote (`measure_feature` on the two
ovens, `exterior_face` on a wall against the plinth) therefore have no live
numbers in this record. Their behaviour is measured by
`tests/blender/test_measure_feature.py` against geometry the tests build: a
box's top at z 1.0 with normal `(0, 0, 1)`; a slab rotated 30° fitting a 30°
plane through both `plane_fit` and `surface_height`; a box with a mouth cutter
reading `deepest_side == "front"` with a 0.7 m maximum depth, and the SAME local
side after a 180° turn with its world normal flipping `-Y` → `+Y`; a wall reading
`facing_side == "front"` against a room box at +Y.

`define_assembly` moves parts to its pivot, so it must never run on the user's
scene; `declare_join`, the gate modes and the budget are proven by
`tests/blender/test_assembly_safety.py` and the reproduction above.

## Left alone, deliberately

- The pre-existing `RUF022` (`__all__` not sorted) in `ops/__init__.py` and the
  twelve other `ruff` findings in the tree: the same set at HEAD, only line
  numbers moved. Lint was compared before and after rather than assumed.
- `tests/blender/test_relief_slab.py` and `test_pbr_textures.py` emit Blender's
  `Material.use_nodes` deprecation warning. Untouched by this change.
