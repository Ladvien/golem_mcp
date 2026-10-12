# blended — Incremental Harness Roadmap

**Date:** 2026-08-21
**Evidence base:** `docs/research/2026-08-20-agentic-blender-game-asset-harness-research.md` (cited below as *[brief §N]*)

## Design commitments

These are fixed unless the evidence changes:

1. **Program-as-artifact.** The agent's output is Python (`*Parameters` + `*Builder` modules), never a bare mesh. Programs are deterministic, diffable, editable, and re-runnable; meshes are not. *[brief §1.1]*
2. **Shared core, two frontends.** One package that imports inside any bpy — the headless runner (`blender --background`, or the pip `bpy` wheel) for tests/CI, and a live-GUI MCP session for interactive work. Every subsystem must work identically in both, behind one interface.
3. **The environment is the teacher.** Engineering effort goes into feedback fidelity — tracebacks, mesh measurements, framed renders — not into making the agent "smarter." A dumb traceback-retry loop captures most of the available win (+27 pp executability); agent autonomy does *not* improve geometry once code compiles. *[brief §1.2]*
4. **The Mesh Analyzer is the hard gate. Render critique is advisory.** VLM verifiers are systematically biased toward accepting, and get *less* reliable as the generator gets better. A screenshot critic is a wide cheap net, never an acceptance gate. *[brief §1.5]*
5. **Version pinned, drift cataloged.** API drift is the dominant failure family (~85% of below-floor failures in 3DCodeBench). The pin lives in `version.py`; every traceback that teaches us something lands in `drift/catalog.py` in the same commit. *[brief §1.3]*
6. **≤3 refinement iterations, then escalate to the human.** Quality degrades or converges after ~3 rounds; art direction is the human's. *[brief §1.7]*
7. **`bpy` imports live inside functions.** The pure layer (parameters, budgets, reports, drift catalog) imports and tests on machines with no Blender.
8. **Prefer the data API (`bmesh`, `bpy.data`) over `bpy.ops`.** Operators are context-dependent and their kwargs drift; data-API construction is deterministic and headless-safe.
9. **A gate must be able to fail.** Every validator ships with a seeded-defect test that trips it. A check that cannot fail is not a check (scp_characters rule 8).

## Two lanes, one set of gates

```
PROGRAM LANE                    INGEST LANE
prompt/spec                     image / text
    │                               │
Parameters + Builder            trellis2 / Rodin → GLB import
    │                               │
    └──────────► executed bpy ◄─────┘
                     │
              MESH ANALYZER  (hard gate)
                     │
              CLEANUP / RETOPO / UV   (as needed per lane)
                     │
              CAPTURE views  (+ VLM critique, advisory)
                     │
              EXPORT gate (glTF, budgets)
                     │
              pinned regression test
```

Everything downstream of "executed bpy" is lane-agnostic. That is the point of building the gates first.

---

## Stage 0 — Walking skeleton ✅ (this commit)

One thin vertical slice through every layer, on the program lane.

| Piece | File | Status |
|---|---|---|
| Version pin + skew assertion | `src/blended/version.py` | ✅ pinned to 5.0 |
| Drift catalog (5 seeded entries, schema-tested) | `src/blended/drift/catalog.py` | ✅ |
| Reusable ops vocabulary (box via bmesh, bevel, apply-modifiers via depsgraph) | `src/blended/ops/` | ✅ |
| First builder (`CrateParameters` + `CrateBuilder`) | `src/blended/builders/crate.py` | ✅ |
| Mesh Analyzer v0 — 7 measurements, budget gate | `src/blended/analyze/mesh_checks.py` | ✅ |
| Multi-view capture (front/right/top/¾, ortho+persp, Workbench→Cycles fallback) | `src/blended/capture/views.py` | ✅ |
| Executor — in-process + subprocess, structured traceback, drift matching | `src/blended/run/executor.py` | ✅ |
| Tests: 8 pure + 7 blender, incl. seeded-defect gate test | `tests/` | ✅ 15/15 green on bpy 5.0.1 |

**Acceptance (met):** `make test` green; the ¾ render visually confirmed to show a beveled crate; the analyzer trips on a seeded open-box defect.

**Run it:** `make test-pure` anywhere; `make test-blender` needs `pip install bpy` (5.0 wheel, Python 3.11) or Blender's own Python.

---

## Stage 1 — The retry loop + live-session frontend

The kernel becomes usable interactively.

- **Retry loop**: on `RunResult.ok == False`, re-prompt with the traceback plus any `matched_drift` fixes, **max 2 retries** (the measured sweet spot — stateless, cheap, +27 pp). Log every attempt.
- **MCP frontend**: a thin session layer over `run_source_in_process` for use inside a live Blender (blender-mcp / addon). Same `RunResult`, same drift matching — the seam is already there.
- **Chunked execution**: builders emitted and executed in small chunks (scp_characters doctrine — large scripts time out and are undebuggable).
- **Session log**: an append-only JSONL of (chunk, result, drift matches) per session — this becomes training data for the drift catalog.

**Acceptance:** a deliberately broken script (using `use_auto_smooth`) fixes itself on retry #1 because the drift fix was in the prompt; the session log shows it.

## Stage 2 — Ops vocabulary + constructive geometry

Grow the reusable component library the agent composes from.

- `ops/booleans.py` (union/difference/intersect via modifier + apply), `ops/arrays.py`, `ops/mirror.py`, `ops/curves.py` (profile extrusion), `ops/transforms.py` (snap-base-to-z0, center-on-origin).
- Two or three more builders that *only* use the ops vocabulary (barrel, shelf, pallet). If a builder needs raw bmesh, that's a missing op — extract it.
- A `components/` registry so builders can nest (crate-with-lid = crate + lid builder), mirroring the scp_characters sub-builder pattern.

**Acceptance:** each new builder passes the analyzer gate with zero raw-`bmesh` calls in builder code; a seeded bad-boolean (non-manifold result) is caught by the gate.

## Stage 3 — Mesh Analyzer v1 (the full Attene taxonomy)

The gate grows to cover what *designed/generated* meshes actually get wrong. *[brief §3.2]*

- Self-intersection count (BVH overlap), T-junction detection, flipped-normal detection via ray-parity voting (Takayama), sliver/degenerate-triangle ratio, UV presence + island count + overlap check.
- `MeshBudget` presets: `PROP_BUDGET` (≤2,000 tris — Vaughan p.340), `HERO_PROP_BUDGET`, `CHARACTER_BUDGET` (13,000, from scp_characters).
- **Fixture zoo**: one tiny `.py` per defect class that *constructs* the defect, and a test asserting exactly its check trips. This is the "gate must be able to fail" rule made systematic.

**Acceptance:** every check has a fixture that trips it and a clean fixture that doesn't; analyzer runs in <1s on a 15k-tri mesh.

## Stage 4 — Inspection v2: live viewport, X-ray, contact sheets

- Live-GUI implementation of `capture_views` via viewport framing + screenshot, **with the rotation assertion** (smooth-view trap: assert `region_3d.view_rotation` reached its target before trusting a capture — measured failure, scp_characters).
- **X-ray/transparency mode** helper for debugging mesh conflicts: set `shading.show_xray` + per-object display alpha, capture, restore. Used when two meshes interpenetrate and the question is *where*.
- Contrasting debug colors per object (scp_characters rule), auto-assigned from a fixed palette.
- Contact-sheet composer: the 4 views tiled into one image for one-glance review.

**Acceptance:** same `capture_views(obj, out_dir)` call works headless and live; an interpenetration case is visibly diagnosable from the X-ray capture.

## Stage 5 — Ingest lane: image → 3D → cleanup

"Model from an image," with the mess handled. Uses the local trellis2 MCP server (`generate_3d`, `generate_3d_multi_image`, `segment_mesh`) or any GLB source.

- `ingest/import_glb.py`: import, normalize scale/orientation (Y-up→Z-up, base at z=0), rename to convention.
- `ingest/cleanup.py` — the standard pass, in order: merge doubles (`DUPLICATE_VERTEX_DISTANCE_M`), dissolve degenerate, recalc normals outside, fill holes below a *reported* threshold (never blind-fill — Attene), delete loose, then re-analyze.
- **Before/after `MeshReport` diff** is the deliverable of every cleanup: what changed, what remains, what exceeded thresholds and was left alone.
- Decimate-to-budget with UV preservation check (texture bleeding is the known failure — Simplifying Textured Meshes in the Wild).

**Acceptance:** a raw TRELLIS/Hunyuan GLB goes from N analyzer failures to a passing report (or a report that honestly lists what cleanup could not fix), with the diff logged.

## Stage 6 — Retopo, UV, bake lane

The "make it actually game-ready" stage. *[brief §2 — generated meshes have wrong topology and unusable UVs; this lane is what makes the ingest lane shippable.]*

- Remesh wrappers: voxel remesh (safe default), quad-ish remesh; face-count targeting.
- UV: seam marking heuristics, unwrap, island packing; distortion + coverage metrics into `MeshReport`.
- High→low normal bake via `bpy` bake API (cage, margin as named constants); the ZBrush green-channel flip check as a validator.
- Texture cleanup utilities: resize/limit to budget, strip unused, verify PBR channel packing.

**Acceptance:** an ingested high-poly mesh becomes a ≤2,000-tri prop with one UV atlas and a baked normal map, and passes the full gate.

## Stage 7 — VLM critique (advisory) + applied-fix verification

Only now, because the evidence says its role is narrow. *[brief §1.5, §1.6]*

- Render-and-critique: 4 views + the spec → VLM lists discrepancies. **Advisory**: it can send work back, it cannot pass work.
- **Applied-fix check** (LL3M's verification agent): after a fix, re-render and diff old/new against the critique list — "did the edit actually land" is a separate, cheap check that catches a real failure mode.
- Iteration cap: 3, then escalate to the human with the contact sheet.
- Optional: SigLIP-2 view-similarity as the automated fidelity number when a reference image exists (r=0.964 against human preference — the one defensible automated visual metric). *[brief §3.1]*

**Acceptance:** on a seeded visual defect (wrong proportions), the loop converges ≤3 rounds or escalates; the applied-fix check catches a deliberately ignored critique item.

## Stage 8 — Export gate + golden pinning

- `export/gltf.py`: glTF export contract (Y-up, apply transforms, triangulate, ≤4 joint influences when rigged), re-import verification (round-trip the file and re-run the analyzer on what came back — measure the artifact, not the export call).
- Engine-readiness report: file size, tri/vert counts, texture memory, draw-call estimate.
- **Golden pinning**: once a human signs off on an asset, its `MeshReport` + export stats become a regression test (scp_characters "pinned by tests, once verified").

**Acceptance:** `make test` catches a change that silently regresses a pinned asset's tri count or export size.

---

## What to do next session (Stage 1, concretely)

1. Write `run/retry.py`: `run_with_retries(source, max_retries=2)` — compose `run_source_in_process` + drift-annotated re-prompt. ~60 lines.
2. Write the session JSONL logger. ~40 lines.
3. Try the harness against the live Blender on the Mac via blender-mcp: execute one `CrateBuilder` chunk through the MCP `execute_blender_code` path, confirm the same `RunResult` shape comes back.
4. First drift-catalog growth from a real session: whatever breaks in step 3 goes in the catalog.

## Known constraints and honest gaps

- The pip `bpy` 5.0.1 wheel (Python 3.11) is what CI/container tests run against; the Mac runs full Blender 5.x. Same series — but wheel and full app differ in GPU/GUI capabilities, so capture falls back to Cycles where Workbench has no GL context, and viewport-based inspection only exists on the live frontend.
- Whether a VLM can reliably spot 3D-specific defects (flipped normals, poke-through, non-manifold seams) from screenshots is **unmeasured in the literature** *[brief §8]*. Stage 7 should measure it against our own fixture zoo before trusting it with anything.
- Auto-retopo quality (Stage 6) is the weakest link in every published pipeline; expect the human in that loop for hero assets indefinitely.
