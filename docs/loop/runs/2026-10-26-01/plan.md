# Run 2026-10-26-01 — issue #21: a join op

**Tier:** 1 (open issue). **Chosen over** #23 (measure a multi-part piece) and
the PBR-lane issues (#1–#15). #21 and #23 are the same complaint from two
sides — a piece is many objects and no op can treat it as one — but #21 has
production provenance (a timber stack that had to be joined through
`bpy.ops.object.join` in `run_python` during the 22-piece Sanctuary run) and six
acceptance conditions that are decidable in one iteration. #23 needs a new
report *and* a gate verdict *and* a piece-grouping concept; it is the natural
follow-up, not this unit.

## The failing behaviour (reproduced)

No join exists. `grep -niE "def .*(join|merge_objects|combine)"` over
`ops/*.py` finds `assets._import_joined` (private, imports a .glb) and
`relief._joint_response` (a stone joint). `weld_and_dissolve` welds within one
mesh. So the only path to one mesh from several is the escape hatch:

```python
bpy.ops.object.join()   # in run_python, as Prop_TimberStack had to
```

Reproduction is the absence itself: a test that calls `join_objects` fails with
`ImportError` on `main`.

## The change

`join_objects(object_names: list[str], result_name: str, keep_material_slots:
bool = True) -> JoinReport` in `ops/assets.py` (beside the other
"many parts become one object" code, which is where `_import_joined` already
lives), exported through the facade.

Decisions, each stated so a reviewer can disagree with a specific one:

- **The sources are consumed**, like `boolean_difference` consumes its cutter.
  Leaving them behind makes the piece's triangle count unmeasurable, which is
  #23's whole problem.
- **World transforms are baked** (`matrix_world @ vertex.co`, with faces
  reversed under a mirroring matrix), because a part that was only moved would
  otherwise snap to the origin. This is the same arithmetic `_import_joined`
  already uses; the new op shares nothing else with it, because an import also
  has to cope with importer-created objects and materials it did not author.
- **Material slots are deduplicated by material datablock**, so sixteen tufts of
  one material report **one** slot, not sixteen. `keep_material_slots=False`
  keeps the first slot only (a single-material joined mesh for a consumer that
  wants one draw call).
- **The result's origin is the first named object's origin**: the mesh is baked
  into the result's local space with `matrix_world` of the first object, so the
  piece's base stays where the primary part's was and `snap_base_to_ground` / the
  canonical-orientation reading still mean something.
- **One name is an error, not a silent rename** (`ValueError`): a "join" of one
  object that renames it is the surprising choice the issue calls out.
- **A non-mesh is rejected loudly** via `object_by_name(name, "MESH")`, which
  already names both sides.
- **A duplicate name in the list** is an error, because joining an object with
  itself would double its geometry and then delete it.

`JoinReport` carries `object_name`, `triangles`, `parts_joined`,
`material_slots`, `consumed_names`, plus the measured `connected_component_count`,
`boundary_edge_count` and `self_intersecting_face_pair_count` — the last one so
the issue's "two overlapping solids intersect; two touching ones should not" is
a number rather than a claim.

The op returns `ObjectName`, so the existing gate measures the result — the
issue's condition 5 (a gate verdict comes back) needs no new plumbing.

## Touched

- `blender/src/golem_blender/ops/assets.py` — the op and `JoinReport`.
- `blender/src/golem_blender/ops/__init__.py` — facade export.
- `blender/tests/blender/test_join_objects.py` — new, the six acceptance
  conditions plus the edge cases above.
- `blender/_evaluate/golden/pinned_tool_schemas_fingerprint.txt` — the tool set
  grows by one, so the pin moves in the same commit.
- `blender/BACKLOG.md` — the measured starting point (72 tools).
- `blender/src/golem_blender/kitbash/procedure.md` — where a kit piece needs one
  mesh.

## Deploy impact

Mac half only: `src/golem_blender` is live on the next call, but the tool
**listing** is read at MCP-server start, so the server restarts (omp's entry
does it via `--exit-on-source-change`). Big is untouched (`src/golem_mcp` does
not change, and it has no ops). Fingerprint moves; tool count 71 → 72.

## Verification

1. Fail-before: the new module's tests must fail at the import on `main`'s
   facade (recorded in `eval.md`).
2. The six acceptance conditions, measured in Blender 5.2.
3. A render pair of the joined timber stack (`render_views` before/after), since
   the change is geometry: the joined result must look identical to the parts.
4. Gates: `test-golem`, `test-pure`, `test-mcp`, `test-blender-app`.
