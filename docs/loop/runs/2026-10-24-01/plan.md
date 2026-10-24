# Run 2026-10-24-01 — issue #19: `duplicate_object` keeps the source's parent

**Tier:** 1 (open issue). **Chosen over** #15–#23 because #19 is the only
`bug`-labelled issue and it silently puts geometry somewhere other than the
location the tool was given — wrong output that still passes the gate, the top
of the harm order.

## The failing behaviour (measured, not read)

Probe in Blender 5.2 (`/tmp/probe_copy.py`, this run): a mesh parented to an
empty at z=5 with `matrix_parent_inverse` translation z=1, `location=(1,2,3)`:

| object | parent | local location | matrix_parent_inverse | world |
|---|---|---|---|---|
| source | `Parent` | (1, 2, 3) | z=1 | (1, 2, 9) |
| `Object.copy()` | `Parent` | (1, 2, 3) | z=1 | (1, 2, 9) |
| copy after `parent=None` + identity MPI | `None` | (1, 2, 3) | identity | **(1, 2, 3)** |

`Object.copy()` carries `parent`, `parent_type`, `parent_bone` and
`matrix_parent_inverse`; `ops/assets.py:duplicate_object` sets `location` and
`rotation_euler` and nothing else, so the docstring's promise ("Location and
rotation are SET on the copy") holds only locally. `move_object_to` already
handles the world-vs-parent distinction (`ops/transforms.py:161-168`).

## The change

`duplicate_object(..., keep_parent: bool = False) -> AssetReport`:

- `keep_parent=False` (default): clear `parent`, reset `parent_type` to
  `OBJECT`, `parent_bone` to `""`, and `matrix_parent_inverse` to identity
  before setting the transform, so `location_m` is the world location the
  docstring promises. Proven necessary: bone-parented copies keep
  `parent_type='BONE'` until cleared (probe 2, this run).
- `keep_parent=True`: today's behaviour exactly, including
  `matrix_parent_inverse`.
- `AssetReport.location_is_parent_relative: bool` (new field, default `False`
  so the two import ops are unchanged) is `True` only when `keep_parent=True`
  and `location_m != (0, 0, 0)` — the report then says the location it measured
  is parent-relative.
- Collection membership is left as `source.users_collection` iterated, which
  the probe shows reproduces the source's membership exactly (`['A', 'B']`
  for a nested A→B); nesting is not a duplicate link, so nothing is deduped
  (deduping would make the copy differ from its source).

## Touched

- `blender/src/golem_blender/ops/assets.py` — op body, `AssetReport`, docstring.
- `blender/tests/blender/test_asset_ops.py` — 5 new acceptance tests (the
  issue's five conditions) + one for the report field.
- `blender/_evaluate/golden/pinned_tool_schemas_fingerprint.txt` — the
  signature moved, so the pin moves in the same commit.
- `blender/BACKLOG.md` — the "Measured starting point" tool row.
- `blender/src/golem_blender/kitbash/procedure.md` §6A — the duplicate step
  now states the copy is independent of the source's placement.

## Deploy impact

Mac half only (`src/golem_blender`), which is live on the next tool call; the
tool *schema* is loaded at MCP-server start, so the server restart is the
deploy step. Big's half is untouched (`src/golem_mcp` is not edited) — its
editable install still serves the same code, so nothing to restart there.
Fingerprint: moves (signature + summary). Tool count: unchanged at 71.

## Verification

Fail-first, then pass: the new tests must fail on `main`'s op and pass after.
Gates: `make test-golem`, `make -C blender test-pure`, `test-mcp`,
`test-blender-app`. No renders: the change is placement arithmetic, proven by
measuring `matrix_world` in Blender, not by looking at a render.
