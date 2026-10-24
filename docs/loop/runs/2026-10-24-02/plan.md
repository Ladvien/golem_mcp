# Run 2026-10-24-02 — plan

Six-way fan-out. Six open issues, one agent each, one git worktree each, all on
`ollama-cloud/deepseek-v4.1-flash:1017`, then one merge into `main` in a fixed
order and a release to the four machines that run the `golem` MCP.

BASE: `4485106` (`origin/main` after the `21192b3..4485106` push).

## The six units

| worktree | branch | issue | unit |
|---|---|---|---|
| a1 | `loop/a1` | #25 | `align_to`, `stand_against`, `span_between` — place a FACE on a target, not an origin at a coordinate |
| a2 | `loop/a2` | #26 | `define_assembly`, `assembly_report`, `export_assembly`, `render_assembly` — many pieces as ONE asset, with an assembly-shaped gate |
| a3 | `loop/a3` | #23 | `measure_objects` — the analyzer's numbers for a set, not one object |
| a4 | `loop/a4` | #17 | `define_piece`, `piece_report`, `save_blend(piece=…)` — a named set held for the session |
| a5 | `loop/a5` | #14 | three PBR visual defects: a light asphalt's aggregate, a forest ground's grass scale, tile face pits |
| a6 | `loop/a6` | #13 | a height map's range follows its kind, measured from the truths' displacements |

## Merge order

```bash
git cherry-pick -x <a5>   # PBR #14 — no facade change
git cherry-pick -x <a6>   # PBR #13 — no facade change
git cherry-pick -x <a3>   # measure_objects (new op)
git cherry-pick -x <a4>   # pieces (new module + save_blend param)
git cherry-pick -x <a1>   # align_to family (new ops)
git cherry-pick -x <a2>   # assembly (new ops)
```

The PBR pair first because neither touches the facade, so any failure there is
unambiguously theirs. #25 and #26 last but both merged, because the two issues
the user named first are the ones that would have prevented the session's
defects.

## Release

After the merge: push, pull on each machine, and upgrade the `golem` MCP on
Big Mac, MacAir, BMB and Big — see `deploy.md`.
