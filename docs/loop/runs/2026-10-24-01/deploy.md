# Run 2026-10-24-01 — deploy

## The commit

`bb3dfa6` — `blender: duplicate_object drops the source's parent, so location_m is world (issue #19)`,
on `origin/main` (a plain fast-forward; never a force). It carries the op, the
six tests, the moved pin, `BACKLOG.md`, the spec row and
`kitbash/procedure.md`.

## Mac half (the change)

| check | result |
|---|---|
| `src/golem_blender` live on the next call | yes — the harness re-imports on a source-fingerprint change |
| tool schema read at server start | the omp `golem` entry passes `--exit-on-source-change`, so the server restarted on its own |
| live tool description | `xd://mcp__golem_duplicate_object` serves "Copy the named object (own mesh data) to new_name at world location_m, turned z_rad about Z; parent dropped." with `keep_parent` in the schema — the new code is what is running |
| live fingerprint | `t:7a8ffdbc17da`, equal to `_evaluate/golden/pinned_tool_schemas_fingerprint.txt` |
| live tool count | 71 (9 service + 62 op) — unchanged, as intended |
| smoke call through the single `golem` entry point | `duplicate_object("SmokeMount", "SmokeCopy", (1,2,3))` on a mesh parented to an empty at z=3 returned `bounds_min_m [0.5, 1.5, 3.0]`, `location_is_parent_relative false`; the same call with `keep_parent=True` returned `bounds_min_m [0.5, 1.5, 6.0]`, `location_is_parent_relative true` |
| scene left as found | yes — `list_scene` back to the same three objects |

## big (untouched)

`src/golem_mcp` did not change, so big's editable install still serves
byte-identical code and the unit was **not** restarted. Checked before deciding:
`ssh big gpu-tenant status` reported `tenant=none`, `queue=0`, so a restart was
possible — it was simply unnecessary. `health_check` was not re-run, because
nothing on that host moved.

## bmb (untouched)

No mflux or rigging change. No documented procedure was needed, so nothing was
written to `needs-decision/`.
