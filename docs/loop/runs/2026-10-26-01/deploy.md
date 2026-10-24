# Run 2026-10-26-01 — deploy

## The commit

`9ad4b71` — `blender: join_objects combines a piece's parts into one mesh
(issue #21)`, followed by one fix commit for the gated-report defect a live
call found. On `main`, plain fast-forward.

Changed, in the run's own working tree (all Mac-half):

| file | why |
|---|---|
| `blender/src/golem_blender/ops/assets.py` | `join_objects`, `JoinReport`, `_append_part_into`; `@op(gated=True)` on the op |
| `blender/src/golem_blender/ops/_contract.py` | `PLURAL_NAME_ANNOTATIONS`, the `_names$` branch, `is_marked_gated`, `gate_target_names`, `GATE_TARGET_FIELD`, and the contract rule for a gated report |
| `blender/src/golem_blender/ops/__init__.py` | facade exports |
| `blender/src/golem_blender/agent/op_call.py` | the dispatcher reads the gate target through `gate_target_names` (the crash fix) |
| `blender/src/golem_blender/agent/tool_schemas.py` | the gated marker is printed for a gated op, not only for an object-name return |
| `blender/_evaluate/golden/pinned_tool_schemas_fingerprint.txt` | regenerated, never hand-edited |

## Mac half

| check | result |
|---|---|
| anything read at server start changed? | **yes** — the tool LISTING changed (one new tool), so the MCP server must restart. omp's `golem` entry runs `blender-mcp --exit-on-source-change`, and the restarted server served it: `search_ops "join objects"` returns `join_objects` with its full schema |
| tool count / fingerprint, live | 72 tools / **`t:ff9833ed06ec`**, equal to the pin file's content |
| smoke call per merged op | **`join_objects` called live** (two 1 m boxes): `execute: ok`, the full `JoinReport` in `returned:`, and `gate: FAIL (24 tris, 2 components) — 2 disconnected components (budget 1)`, which is the correct verdict for two disjoint boxes. Both throwaway objects then removed |
| Blender add-on | untouched (`blender_mcp/addon` not edited); `golem_blender` is loaded by the MCP server, not by the add-on, so the restart above is the whole of it |
| scene left clean | yes — `list_scene` shows the same 35 Sanctuary objects it showed before the smoke calls |

**This is the deploy that mattered.** The op executed and passed its unit tests
while being unreachable through the tool surface; the live call is what proved
it works, and it is what found the `TypeError` that no test caught.

## big

`src/golem_mcp` is unchanged, so big's editable install serves byte-identical
code. No restart, no `make sync-golem` (no dependency change), and no GPU job
was queued that the change could affect.

## bmb

Untouched: no mflux, FLUX or rigging change. Nothing written to
`needs-decision/`.
