# Run 2026-10-24-02 — deploy

## The commits

Six cherry-picks onto `main`, each `-x` so the source sha is in the message:

```
643b3fe  a5  blender: give a light asphalt its own contrast, a grass one blade pitch, and a tile its pits
8c4ed4f  a6  blender: a height map's range follows its kind, measured from the truths
a5fb116  a3  blender: measure a set of objects as one piece, so a LOD budget is on the piece
ae1b73e  a4  blender: a piece names several objects and is measured as one asset (issue #17)
d2dfcd0  a1  blender: place by FEATURE, not by origin (issue #25)
30bbf21  a2  blender: an assembly op — define, measure, gate, render and export many pieces as ONE asset (#26)
7b22824  —     Log the six-way fan-out: the assembly ops and the PBR pair
```

Every code change is Mac-half (`blender/`). `src/golem_mcp` is untouched, so
big's editable install serves byte-identical code.

## Live deploy check

| check | result |
|---|---|
| the tool LISTING changed? | **yes** — 78 → 88 tools |
| the restarted server serves the new ops? | **yes** — `measure_objects`, `define_piece`, `piece_report`, `define_assembly`, `assembly_report`, `align_to`, `stand_against`, `span_between` all callable through the live `golem` MCP |
| tool count / fingerprint, live vs pin | **88 / `t:365aafec29d4`**, equal to `pinned_tool_schemas_fingerprint.txt` |
| the user's scene | untouched — `list_scene` before and after shows only `Landmark_BlacksmithShop` (21 328 tris) |

## One smoke call per new op, through the `golem` MCP

A plan was declared first (`declare_plan`), as the ops require. All throwaway
objects were placed far from the user's asset and removed afterwards.

**`measure_objects`** — two 1 m boxes, `check_part_intersections=true`:

```
{"triangles_total": 24, "triangles_by_object": {"SmokeA": 12, "SmokeB": 12},
 "dimensions_m": [4.0, 1.0, 1.0], "lowest_point_m": 0.0, "unlinked": [],
 "part_intersections": [], "part_intersections_checked": true}
```

The union 4.0 m, not the 8 m a bounds sum would give — criterion 1 live.

**`define_piece`** / **`piece_report`** — the same two boxes:

```
{"object_name": "SmokePiece", "triangles_total": 24,
 "parts": [{"name": "SmokeA", "triangles": 12}, {"name": "SmokeB", "triangles": 12}]}
```

`piece_report` returns the identical report, and it is read-only.

**`define_assembly`** / **`assembly_report`** — with a name that was never linked:

```
{"triangles_total": 24, "unlinked": ["GhostNeverLinked"], "dimensions_m": [4.0, 1.0, 1.0],
 "part_intersections": [], "laps": [], "pivot": "footprint_centre_base"}
```

`unlinked` names the ghost and the total stays 24 — the silent-miss case #26
criterion 1 is about, on a live call.

**`align_to`** — `SmokeB.min_x` onto `SmokeA.max_x`, gap 0:

```
{"moved_m": [-2.0, 0.0, 0.0], "feature_object_m": [-1.0, 0.0, 0.5],
 "feature_target_m": [-1.0, 0.0, 0.5], "achieved_gap_m": 0.0,
 "clear_of": ["SmokeA"], "collides_with": ["Landmark_BlacksmithShop"], "aligned_axis": "x"}
gate: PASS
```

Both features land on the same point to the printed precision, and the move is
on x only. `collides_with` naming the user's shop turned out to be **correct,
not a defect**: the move put SmokeB at x -1.0..0.0, which is inside the shop's
own footprint (x -4.3..4.3) — verified with `world_bounds` on both. The op
reported the world as it is.

**`stand_against`** — `ShelfT` against `WallT`, side `+x`, gap 2 mm:

```
{"moved_m": [-5.002, 0.0, 0.0], "feature_object_m": [19.498, 0.0, 0.5],
 "feature_target_m": [19.5, 0.0, 0.5], "achieved_gap_m": 0.0019989,
 "clear_of": ["WallT"], "collides_with": [], "hangs_in_air": true}
gate: PASS
```

The wall's inner face is at x 19.5 and the shelf's near face lands at 19.498 —
exactly the 2 mm asked for, and `hangs_in_air` is true because the shelf's base
is above the floor.

**`span_between`** — twice, once expected to fail and once not:

```
PipeT (3 m tall, 9 m apart):  end_gap_from_m 3.0000, end_gap_to_m 3.0000,
                              within_radius false, achieved_gap_m 3.0
LongPipe (12 m, same gap):    end_gap_from_m 0.5000, end_gap_to_m 0.5000,
                              within_radius false, collides_with ["ForgeT","PipeT","ShelfT","WallT"]
```

Both reported honestly. The first is the truthful answer for a pipe shorter than
the gap it must span; the second is 0.5 m at each end against a 0.05 m radius,
with the objects it crosses named. The `within_radius` flag is what a caller
chains on, and it is not silently true.

**Not smoke-called live:** `export_assembly` and `render_assembly`. Both write
files or add camera objects, and neither needs a live call to be trusted: the
branch's own tests export a 49-part, 21 168-triangle assembly and re-import the
written `.glb` (49 objects, same triangle total, same material names), and
measure the `focus` render's frame coverage (1.00 / 0.78 / 0.76 against a 0.5
floor). Stated rather than implied, so "not called" cannot be read as
"not checked".

## Two observations from the smoke run, worth a future op

Neither is a defect in this run's work; both are existing behaviour that the
new ops made visible.

1. **`add_box` writes the position into the MESH, not the transform.** A box
   created at `location_m=[-30,-30,0]` has `object.location == (0,0,0)` and
   vertices at -30.5..-29.5. Every geometry reader agrees with the mesh
   (`world_bounds`, `measure_objects`, `align_to` all measure the true world
   position), so nothing is wrong — but an op that reports
   `object.location` (the object-detail summary does) shows a number that
   differs from where the geometry is. A future `world_bounds`-only rule for
   "where is this" would make that unambiguous.
2. **`define_assembly` moves its parts to honour the pivot.** That is by design
   and documented, but it means a smoke call changes positions a caller may not
   expect. Worth an explicit line in the op's summary for the same reason
   `move_object_to` documents its parent-relative behaviour.

## bmb

Untouched: no mflux, FLUX or rigging change.
