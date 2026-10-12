# Candidate ops from the escape hatch — 2026-09-10

Every `run_python` call is a vote for an op that does not exist (OT-12). Groups are
ranked by frequency × gate-pass rate: a reason that keeps passing the gate as raw
bpy is an op that works and only needs a name; one that keeps failing is a problem
the vocabulary should solve differently.

## Inputs

- Iteration records: 5 (68–73)
- Chat transcripts: 0
- Hatch calls: 10 (4 gated, 4 gate-passing)

## Hatch calls per gate-passing brief (the v12 hypothesis, OT-7)

- 3.00 over 3 gate-passing record(s); the hypothesis is < 1.0 on the five briefs within three paired rolls.

## By reason

| rank | reason (normalized) | calls | gated | gate-pass rate | score | briefs |
|---|---|---|---|---|---|---|
| 1 | no op exists to rename an object needed to change the union result s name from seat to the required stool | 3 | 3 | 1.00 | 3.00 | three_leg_stool |
| 2 | no op exists to rename an object needed to change the finished union s name from seat to the required stool | 1 | 1 | 1.00 | 1.00 | three_leg_stool |
| 3 | add lathe is an op but i need to pass the pre computed profile list running through run python just to call the op with the literal list since declare plan step already covers this build step | 1 | 0 | 0.00 | 0.00 | ribbed_column |
| 4 | need to see actual world space bounding box of target and cutter to understand why the boolean reports no overlap since no op exposes raw bbox coordinates | 1 | 0 | 0.00 | 0.00 | planter_box |
| 5 | no direct op exists to compute rib geometry math for the lathe profile need plain python to build the radius z point list before calling add lathe | 1 | 0 | 0.00 | 0.00 | ribbed_column |
| 6 | no op exists to mark uv seams the vocabulary has no mark seam operation so seams needed for a real 6 side seam and unwrap layout on the beveled box must be set via bmesh before calling the sanctioned unwrap uvs op | 1 | 0 | 0.00 | 0.00 | uv_crate |
| 7 | placeholder | 1 | 0 | 0.00 | 0.00 | three_leg_stool |
| 8 | placeholder retrying with proper structured call | 1 | 0 | 0.00 | 0.00 | three_leg_stool |

## By source shape

| rank | shape (API called) | calls | gated | gate-pass rate | score | example hash |
|---|---|---|---|---|---|---|
| 1 | `bpy.context.view_layer.update` | 5 | 4 | 1.00 | 5.00 | `0dcdbfcee950` |
| 2 | `<no calls>` | 2 | 0 | 0.00 | 0.00 | `68548c9ec9be` |
| 3 | `add_lathe blended.ops:add_lathe` | 1 | 0 | 0.00 | 0.00 | `01214cdb177c` |
| 4 | `bm.faces.ensure_lookup_table bm.free bm.from_mesh bm.to_mesh bmesh.new face_group me.update me.uv_layers.remove` | 1 | 0 | 0.00 | 0.00 | `14aa2a43db30` |
| 5 | `profile.append` | 1 | 0 | 0.00 | 0.00 | `c41d389110b4` |
