# Run 2026-10-26-02 — deploy

## The commits

Six cherry-picks onto `main`, each `-x` so the source sha is in the message:

```
66be8f8  a6  blender: delete pbr/splatter.py, the lane's dead second splatter (issue #15)
16303df  a3  blender: a lathe opens an end or revolves a wall (issue #18)
2579653  a4  blender: grid, ring and path array ops lay a whole layout in one call (issue #22)
fb104c4  a2  blender: roughen_object pushes vertices off the ideal surface (issue #20)
add1fa1  a1  blender: decimate_object gives a piece golem built its LOD levels (issue #16)
60397ba  a5  blender: a description's "vertical" turns a wood's grain a quarter turn (issue #12)
```

All six are Mac-half (`blender/`). `src/golem_mcp` is untouched, so big's
editable install serves byte-identical code: no restart, no `make sync-golem`.

## Live deploy check

| check | result |
|---|---|
| the tool LISTING changed? | **yes** — 72 → 78 tools, so the MCP server restarted (omp runs `blender-mcp --exit-on-source-change`) |
| the restarted server serves the new ops? | **yes** — `search_ops` returns `decimate_object`, `roughen_object`, `grid_array` (and the module list now includes `roughen`) with full schemas |
| tool count / fingerprint, live vs pin | **78 / `t:a9c0b64f6da0`**, equal to `pinned_tool_schemas_fingerprint.txt` |

## One smoke call per merged op, through the `golem` MCP

A plan was declared first (`declare_plan`), as the gate requires. Throwaway
objects at (−8, −8), removed afterwards.

**`decimate_object`** — a 64-segment cylinder, `ratio=0.5`:

```
returned: {"triangles_before": 92, "triangles_after": 46, "target_triangles": 46,
           "reached_target": true, "decimate_passes": 1, "parts_present": 1,
           "boundary_edge_count": 0}
gate: PASS (46 tris, 1 components)
```

**`roughen_object`** — the same mesh, `amplitude_m=0.01, seed=7`:

```
returned: {"vertices_moved": 25, "rms_displacement_m": 0.010000000000000253,
           "max_displacement_m": 0.01645, "seed": 7, "mode": "radial",
           "clamped_vertex_count": 0, "inverted_face_count": 0}
gate: PASS (46 tris, 1 components)
```

The RMS lands on the requested amplitude to 15 digits, which is the op's own
promise measured on a live call rather than in a test harness.

**`grid_array`** — `counts=[2,1,1], spacing_m=[3,0,0]`:

```
returned: {"copies": 2, "triangle_count_before": 46, "triangle_count": 92,
           "connected_component_count": 2,
           "copy_origins_m": [[0.0,0.0,0.0],[3.0,0.0,0.0]],
           "overlapping_copy_pair_count": 0, "below_ground_copy_count": 0}
gate: FAIL (92 tris, 2 components) — 2 disconnected components (budget 1)
```

The copies landed at exactly 0 and 3 m. The gate FAIL is the CORRECT verdict:
two disjoint copies are two components, and the budget is one — the gate is
measuring what the op made, which is the point of the gated-report shape issue
#21's live call forced.

**Not smoke-called live:** `add_shell_lathe` / `add_lathe(cap_end=…)` and the
`'vertical'` grain turn. Both are covered by their branches' Blender-layer tests
(12 and 2 tests respectively, with the numbers quoted in their issues), and a
live call would add an object to the user's scene for no new evidence. Stated
rather than implied, so "not called" cannot be mistaken for "not checked".

**Scene left clean:** both throwaway objects removed and `list_scene` confirms no
`Smoke*` object remains. The user was working in the same Blender during this
run (the scene changed from the Sanctuary prop set to a Smithy assembly); nothing
of theirs was touched.

## bmb

Untouched: no mflux, FLUX or rigging change.
