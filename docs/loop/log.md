# golem_mcp — the work loop log

One entry per iteration of `/build-loop`. Newest last. Each entry names the
tier, the unit, the evidence, the commit, the deploy result and what is left.

| run | date | tier | unit | commit |
|---|---|---|---|---|
| 2026-10-24-01 | 2026-10-24 | 1 (issue) | #19 `duplicate_object` kept the source's parent | `bb3dfa6` |
| 2026-10-25-01 | 2026-10-25 | 1 (issue) | #24 the GPU-timeout test raced bash's startup | `c32f998` |
| 2026-10-26-01 | 2026-10-26 | 1 (issue) | #21 `join_objects` combines parts into one mesh | `9ad4b71` |
| 2026-10-26-02 | 2026-10-26 | 1 (issue) x6 | six-way fan-out: #12, #15, #16, #18, #20, #22 | `66be8f8`, `16303df`, `2579653`, `fb104c4`, `add1fa1`, `60397ba` |
| 2026-10-24-02 | 2026-10-24 | 1 (issue) x6 | six-way fan-out: #25, #26, #23, #17 + PBR #14, #13 | `643b3fe`, `8c4ed4f`, `a5fb116`, `ae1b73e`, `d2dfcd0`, `30bbf21` |

---

## 2026-10-24-01 — issue #19: a copy is placed where it was told

**Tier 1 (open issue).** Chosen over the PBR-lane issues (#1–#15) and the
missing-op issues (#16–#23) because #19 is the only `bug`-labelled issue and
its harm is the top of the order: geometry placed somewhere other than the
location the tool was given, while still passing the gate. A PBR issue needs a
four-set re-score to prove anything; this one is decidable in minutes.

**What changed.** `duplicate_object` gained `keep_parent: bool = False`.
`Object.copy()` carries `parent`, `parent_type`, `parent_bone` and
`matrix_parent_inverse`; with them intact `location` stays parent-relative, so
the copy landed at parent + local (measured: a child of an empty at z=5 given
`location_m=(1,2,3)` landed at world `(1,2,8)`). The default now clears all
four before setting the transform; `keep_parent=True` preserves the old
behaviour exactly. `AssetReport.location_is_parent_relative` says which
reading the report measured.

**Evidence** (`runs/2026-10-24-01/`): the issue's five acceptance conditions
measured in Blender 5.2 — world `(1,2,3)` vs `(1,2,8)` with `keep_parent`,
source unchanged at `(0,0,5)`, `parent is None`, own mesh data (a boolean on
the copy cut it to 32 polys, source untouched) — plus the fail-first run
(`assert bpy.data.objects['Mount'] is None` fails on the old code) and a live
smoke through the single `golem` entry point (default copy bounds z 3.0–4.0,
`keep_parent` copy z 6.0–7.0, `location_is_parent_relative: true`).

**Gates.** `test-pure` 1547 passed / 1 xfailed; `test-mcp` all OK;
`test-blender-app` 469 → **475 passed**, 1 skipped. Nothing this run touched got
worse. `test-golem` reads 1 failed / 9 passed at HEAD, and that failure is NOT
this change: `tests/test_gpu.py::test_a_job_over_its_timeout_is_terminated_and_reported`
fails 4–5 of every 5 runs and 5 of 5 in a fresh worktree at `c217f2f` (the
pre-change commit), with `src/golem_mcp/gpu.py` untouched by this run. Its
baseline "10 passed" was one lucky draw of a flake, not a green suite — recorded
as such rather than as a regression.

**Pin.** Tool count unchanged at 71; fingerprint `t:16855e3dd426` →
`t:7a8ffdbc17da`, pin updated in the same commit.

**Deploy.** Mac half only; the schema is read at server start and the omp
`golem` entry's `--exit-on-source-change` restarted it (the live
`duplicate_object` tool description already carries "parent dropped"). Big's
half is untouched — `src/golem_mcp` did not change, so its editable install
serves identical code and was not restarted.

**Issues filed.** #24 — the flaky `test_gpu.py` timeout test, with the measured
mechanism (a freshly written script's first exec costs up to 7.8 s on this Mac;
SIGTERM at 1 s can land before bash installs its trap, so the shell dies `-15`
and never writes the marker) and a verified readiness-gated fix (6/6 with the
gate, 0/2 without).

**Top 5 remaining.**
1. #2 — the loose-ground scatter's colour model (stones read as flat discs).
2. #1 — the full four-set run after the knit/plaid/seam and AO/leaf-litter batches.
3. #24 — the flaky `test_gpu.py` timeout test (filed this run); `make
   test-golem` is red 4 of 5 runs until it lands.
4. **No op sets an object's parent**, measured while building this issue's
   fixture: only `bind_mesh_to_armature` parents anything, so a kitbash piece
   that mounts on another part has no op path and needs `run_python`. Worth an
   issue.
5. #11 — the tile-floors scale measure reads hairline grout and hands the lane
   2–3× the truth's tile count.

---

## 2026-10-25-01 — issue #24: the gate stops reporting red by luck

**Tier 1 (open issue).** Chosen over the PBR-lane issues (#1–#15) and the
missing-op issues (#16–#23) because `make test-golem` is the gate every later
iteration reads, and a gate whose colour depends on page-cache state is worse
than a missing feature. #15 (delete an unused file) is smaller with no user
impact; the PBR issues need a four-set re-score.

**What changed.** `tests/test_gpu.py::test_a_job_over_its_timeout_is_terminated_and_reported`
had asserted that a marker file existed, written by the fake `gpu-tenant`'s
`trap … TERM` inside a **1 s** timeout. A trap only fires for a signal that
arrives after it is installed, so the assertion was asking how fast bash starts.

**Evidence** (`runs/2026-10-25-01/`): the same code read **5 of 5 red** on a
cold cache (2026-10-24, fresh worktree at `c217f2f`) and **10 of 10 green** on a
warm one (today). A startup-delay sweep puts the old fixture's threshold between
0.5 s (pass) and 1.5 s (fail); a freshly written script's first exec on this Mac
measured 5.4–7.8 s against 0.01 s warm. The new fixture (`exec python -c
"time.sleep(41.3)" <per-run token>`) is deterministic at every delay, and
asserts what the op actually promises: it raises, the job's **pid is gone**, and
it returns far under 41.3 s.

**Two of my own attempts were wrong, and mutation testing said so.** A
timing-only assertion **passed** a mutant that reports the timeout and leaves the
job running; a `# <token>` marker was a shell comment that never reached argv, so
the process check matched nothing. Both are recorded rather than quietly fixed:
`eval.md` names them. Final sweep — no raise, no `_stop`, `timeout=None` — each
mutant fails; unmutated passes 10 of 10, leaving 0 orphans.

**Gates.** `test-golem` 5 of 5 green; `test-pure` 1547 / 1 xfailed; `test-mcp`
all OK; `test-blender-app` 475 passed / 1 skipped (unchanged). No product code
touched: `src/golem_mcp/gpu.py` is byte-identical, so no fingerprint move and no
schema pin edit.

**Deploy.** None needed and none skipped: a test-only change is deployed by
landing on `origin/main`. Both servers load no file this change touched —
neither `src/golem_mcp` nor `src/golem_blender` changed, the add-on is
untouched, the tool fingerprint stays `t:7a8ffdbc17da`.

**Issues filed.** None.

**Top 5 remaining.**
1. #2 — the loose-ground scatter's colour model (stones read as flat discs).
2. #1 — the full four-set run after the knit/plaid/seam and AO/leaf-litter batches.
3. **No op sets an object's parent** (measured building #19's fixture): only
   `bind_mesh_to_armature` parents anything, so a kitbash piece that mounts on
   another part needs `run_python`. Still unfiled.
4. #11 — the tile-floors scale measure reads hairline grout and hands the lane
   2–3× the truth's tile count.
5. #15 — remove the unused `pbr/splatter.py` (cheap, no user impact, unblocks a
   clean `git grep`).

---

## 2026-10-26-01 — issue #21: a join op, and the live call that found its defect

**Tier 1 (open issue).** Chosen over #23 (measure a multi-part piece) and the
PBR-lane issues (#1–#15): #21 has production provenance (a timber stack joined
through `bpy.ops.object.join` in `run_python` during the 22-piece Sanctuary run)
and six acceptance conditions decidable in one iteration. #23 needs a report
*and* a gate verdict *and* a piece-grouping concept — the follow-up, not this.

**What changed.** `join_objects(object_names, result_name,
keep_material_slots=True) -> JoinReport` in `ops/assets.py`. Sources are
consumed; world transforms are baked (a moved part keeps its place); material
slots deduplicate by datablock (sixteen tufts, one slot); the result keeps the
first part's origin; one name, a duplicate name and a non-mesh are errors raised
BEFORE anything mutates. It is the first PLURAL name parameter, so `_contract.py`
gained `PLURAL_NAME_ANNOTATIONS` — the container widened, the element type did
not.

**Evidence** (`runs/2026-10-26-01/`): gates `test-golem` 10, `test-pure` 1553 /
1 xfailed, `test-mcp` all OK, `test-blender-app` 488 passed / 1 skipped. The
measured boundary — 50 % overlap 8 self-intersecting pairs, 1 mm gap 0, 1 m gap
0, face-to-face contact 1 — is asserted with the reading beside it, because the
issue expected contact to be clear and the analyzer counts coplanar surfaces.

**The live call found what the units could not.** The op was annotated
`-> ObjectName` and returned `JoinReport`; every test passed, and the first real
MCP call raised `TypeError: 'JoinReport' object is not iterable` in
`_returned_object_names`. Fixed at the contract: an op may now be
`@op(gated=True)` with a report return, `gate_target_names` reads the report's
own `object_name`, and a marked-gated op whose return carries none is a
violation (proven failing by disabling the rule). The tool description gained the
gated marker, so the pin moved twice: `t:b1b01b125501` → `t:ff9833ed06ec`.

**A second live finding that was NOT a defect.** The overlapping smoke pair
reported `4 triangles face inward`. Measured: disjoint boxes 0 of 24, overlapping
4 of 24, each source 0. The join does not flip normals; parity is reporting faces
inside another solid, which the analyzer already calls "join-without-union".
Nothing changed for it.

**Deploy.** Mac half, tool listing changed → MCP server restart, which omp's
`--exit-on-source-change` did; the restarted server served `join_objects` and a
live call returned the report and `gate: FAIL (24 tris, 2 components)` for two
disjoint boxes — the correct verdict. Smoke objects removed; the scene holds the
same 35 Sanctuary objects as before. big and bmb untouched.

**Issues filed.** None.

**Top 5 remaining.**
1. #23 — measure/save/export a multi-part piece as ONE asset (now unblocked).
2. #2 — the loose-ground scatter's colour model (stones read as flat discs).
3. #1 — the full four-set PBR run after the knit/plaid/seam batches.
4. **No op sets an object's parent** — still unfiled; `bind_mesh_to_armature`
   is the only parenting path.
5. #15 — remove the unused `pbr/splatter.py` (cheap, unblocks a clean `git grep`).

---

## 2026-10-26-02 — six agents, six issues, one worktree each

**The run shape.** Six `loop-worker` agents (`ollama-cloud/deepseek-v4.1-flash:1017`,
`thinking: high`, model verified in each child's own session transcript), each in
its own `git worktree` under `/tmp/golem-loop/a1…a6` branched from `786af06`, one
issue per agent, then six cherry-picks onto `main`. Isolation was measured before
spawning: in every worktree `sys.path[0]` resolved `golem_blender` and
`golem_mcp` to a path under that worktree, not the main checkout.

| agent | issue | outcome | commit on main |
|---|---|---|---|
| a1 | #16 decimate op | merged | `add1fa1` |
| a2 | #20 seeded roughen op | merged | `fb104c4` |
| a3 | #18 open lathe profiles | merged | `16303df` |
| a4 | #22 grid/ring/path arrays | merged | `2579653` |
| a5 | #12 'vertical' turns the grain | merged | `60397ba` |
| a6 | #15 delete `pbr/splatter.py` | merged | `66be8f8` |

**Merged surface, re-measured after every pick, not taken from any branch.**
63 → **69 ops**, 72 → **78 tools**, 46 → **52 plan-required**, 18 readers
unchanged. Fingerprint `t:ff9833ed06ec` → **`t:a9c0b64f6da0`**, always written
from `TOOL_SCHEMAS_FINGERPRINT`'s own output. Contract violations across the
whole facade: none.

**Gates on merged `main`:** `test-golem` 10 passed; `test-pure` **1597 passed /
1 xfailed** (from 1553); `test-mcp` 53 OK; `test-blender-app` **541 passed /
1 skipped** (from 487).

**Every conflict was the one the plan predicted** — `ops/__init__.py`, the pin,
`BACKLOG.md`, the spec's tool-surface row — and every one had a fixed resolution.
The pin was never taken from a side; the counts were re-measured from the live
facade at each pick, which is how the row moved 63 → 69 ops without trusting any
agent's arithmetic. `ops/__init__.py` merged textually clean in every pick.

**Two agents edited shared contract surface, additively.** a1 added
`target_triangles` and `ratio` to `UNITLESS_NUMERIC_NAMES`; a2 added `frequency`
and `seed`. Both survive, both are guarded by the existing
`test_unitless_allowlist_is_all_in_use` (an unused entry is a failure).

**One agent broke the isolation rule and it is recorded, not buried.** a5 wrote
into `/Users/ladvien/golem_mcp` before moving to its worktree, then ran
`git checkout --` on exactly those six files. The user chose to merge on the
evidence rather than reject on the rule, so main was first verified byte-clean
(`git status --porcelain` empty, `git diff HEAD -- pbr/` empty) and a5's branch
gates were re-run in its own worktree. The work is sound; the slip is in the log
and in #12's closing comment because a future reader deserves both facts.

**A finding no issue asked for:** a5 measured that `tile_seam_ratio` reads the
last column against the first and **never the rows**, so a turned wood's own row
steps register as a "seam" (0.001× → 0.224×) on a map whose content did not
change. Documented in `scripts/benchmarks/README.md`'s known-limits list and
asserted in the test (the two axes' numbers must swap). Also recorded by a6: the
same reachability walk that proved `splatter.py` dead cannot reach
`pbr/noise_curl.py` or `pbr/noise_gabor.py` either — #15 named only
`splatter.py`, so those were left alone and are worth their own issue.

**Issues closed with evidence:** #12, #15, #16, #18, #20, #22.

**Top 5 remaining.**
1. #23 — measure/save/export a multi-part piece as ONE asset (unblocked by #21).
2. #17 — a piece grouping; the same complaint from the catalog side.
3. #2 — the loose-ground scatter's colour model (stones read as flat discs).
4. New — `pbr/noise_curl.py` and `pbr/noise_gabor.py` are unreachable by the same
   AST walk that condemned `splatter.py`; confirm dead, then delete or wire.
5. #1 — the full four-set PBR run after the knit/plaid/seam batches.

---

## 2026-10-24-02 — six-way fan-out: the assembly ops (#25, #26, #23, #17) and the PBR pair (#14, #13)

**Tier 1 (open issue) x6.** The fan-out follows the blacksmith-shop session
(`~/sanctuary`, a 49-part building from the village kit), which filed #25 and
#26 out of four measured placement defects and one refused export — 11.10 cm
between two rear corners, brackets 111.9 cm off their wall, a tool board hung
flat, a tuyere pipe 50 cm from its nozzle while overlapping its bellows' box,
and `export_asset` refusing a building for not being one closed manifold under
2000 triangles.

Six agents, one worktree each, one commit each, all on
`ollama-cloud/deepseek-v4.1-flash:1017`. BASE `4485106`.

### #25 — place by FEATURE, not by origin (`d2dfcd0`)

`align_to`, `stand_against`, `span_between` in `ops/alignment.py`, all three
gated and returning `AlignReport`. Features are measured from the EVALUATED
MESH: a yawed 24-gon's `matrix_world @ bound_box` reads 1.41421 m on x where
its mesh reads 1.00000, so the alignment lands the mesh face at 3.0 within 1e-4.
The pier case is asserted with its own off-centre origin (`0.111 m`) so origin
placement cannot satisfy it. Three chained piers keep every adjacency within
1 mm. `stand_against` leaves the base unchanged and reports `hangs_in_air`.
`span_between` reports each end's distance to its OWN object's SURFACE and the
`collides_with` list for a line through a third object.

One documented deviation: `target_feature` is typed `str | TargetPlane`
because a heterogeneous `tuple[str, str, float]` has no JSON schema and would
have made `json_schema_for_type` refuse the whole op set. The issue's
`("plane", axis, coordinate)` triple is still accepted at runtime and tested
for byte-identical equivalence.

### #26 — an assembly is a first-class thing (`30bbf21`)

`define_assembly`, `assembly_report`, `export_assembly`, `render_assembly` in
`ops/assembly.py`. The gate is the PER-PART one, unchanged, and part-vs-part
interpenetration is REPORTED with the pair's names and volume, never failed:
`PartIntersection.kind` separates a LAP (the two boxes end in the same plane
across the penetration axis — cut to meet) from a CLASH (an interior pushed
through a face). Two walls lapping 0.406 m read as a lap with 0 clashes;
a 0.1 m overlap reads one intersection at 0.1000 m³. A 49-part, 21 168-triangle
assembly exports `keep_parts: 49` and re-imports as 49 objects with the same
triangle total and material names. `focus=["Wall","Shelf"]` fills 1.00 / 0.78 /
0.76 of the frame against a 0.5 floor, from three angles.

`AssemblyReport.object_name` names the ASSEMBLY — a registry entry, not a scene
object — so `define_assembly`/`assembly_report` are deliberately NOT gated (the
name would make `gate_named_object` answer "no object named…"); the verdict
rides on `ExportReport`. That is the branch the contract forces, stated in the
module docstring.

### #23 — measure a set as a piece (`a5fb116`)

`measure_objects` -> `SetReport`, read-only. Two 100-triangle boxes report 200
and `dimensions_m` 4.0 (the union, where a sum would say 8). A never-linked
name lands in `unlinked` and is excluded from every total, because the silent
miss at export time is the point. Touching parts are not intersections — the
coplanar knowledge `BooleanNoOp` already has is reused, not rewritten. Distinct
materials, not slots: one material on two parts reports 1.

### #17 — a piece names several objects (`ae1b73e`)

`define_piece`, `piece_report` in `ops/pieces.py` (a separate module on purpose,
so this merge and #26's are independent). A member removed after definition
makes every read raise `PieceChangedError` rather than report a smaller total.
Condition 4 was met by EXTENDING the op: `snap_base_to_ground(piece=…)` moves
every member by one offset and the piece reports `lowest_point_m == 0.0`.
Order independence is asserted over the whole report, and `save_blend` gained
its optional `piece` — which moves the fingerprint but not the tool count.

### #14 — three PBR face defects (`643b3fe`)

Measured on `ambientcg_wide`, which contains all six assets, with the scripts
copy-rewritten so the imported module resolved under the agent's own worktree.

- Asphalt031: contrast 0.36x -> **1.33x**. The eight asphalt truths split by
  lightness (light cv 0.163, dark 0.092), so the spread is now the coefficient
  times the description's value instead of one flat 0.028.
- Ground037: scale 3.09x -> **0.76x**. Blades followed six per feature, so a
  forest floor's 9.8 features — which are its MOSS PATCHES — drew 59 blades
  where its own are 71. The pitch is now the truths' own 15.5 px at 1024
  whatever the feature count is.
- Tiles139/141/143/144: 0 pits and 0.00% coverage -> **45-68 pits/tile, 3.5σ
  deep, 0.61-0.64% coverage** against truths of 37-47, 3.45-3.75σ, 0.47-0.78%.

Six-asset means: contrast 0.86x -> 1.09x, scale 1.40x -> 1.01x.
Honest caveat, recorded by the agent: our asphalt is still 1.33x too bright and
our tiles' grout is wider and browner than the truths' pale grey. Both are
palette value/hue defects, not the three face defects this issue named.

### #13 — a height map's range follows its kind (`8c4ed4f`)

`KIND_HEIGHT_RANGE` and `KIND_HEIGHT_RANGE_TRUTHS` measured over all four truth
sets — 159 distinct materials, each asset's own displacement at p1/p99, the
median per kind. Metal (0.435, 0.571) spans 0.135; rock (0.159, 0.916) spans
0.757. Seven kinds with one or two truths are not fitted and fall back to 0..1
with `is_measured=false`, said in the table, the metadata and the procedure.

Written height span error on `ambientcg`: mean |error| **0.301 -> 0.160**, mean
relative **4.135 -> 0.790**. The shape metrics are unchanged, as a scale-only
change must be (height-luma |error| 0.431, skew 0.696, normal strength 0.304,
all before and after) — that is the normal-map-unaffected proof at the
benchmark level, and a test pins it directly. The range reaches the consumer:
`height_range` in the returned dict, a `T_<Name>_Height.json` sidecar, and
`"height"` in the exported `metadata.json`, verified end to end.

### The merge

Six cherry-picks `-x` in the order a5, a6, a3, a4, a1, a2. The PBR pair landed
clean. The four op picks conflicted on the pin, `BACKLOG.md`'s row, the spec's
row, and (a1, a2) `ops/__init__.py` and `manifest.py` — all four resolved by
the rule the plan fixed: keep both sides, and take NO side for the pin. The pin
was regenerated from `TOOL_SCHEMAS_FINGERPRINT` at every pick and the counts
re-measured from the merged facade:

| after pick | tools | ops | plan-required | readers | fingerprint |
|---|---|---|---|---|---|
| base | 78 | 69 | 52 | 18 | `t:a9c0b64f6da0` |
| a5 | 78 | 69 | 52 | 18 | unchanged (no facade change) |
| a6 | 78 | 69 | 52 | 18 | unchanged (no facade change) |
| a3 | 79 | 70 | 53 | 19 | `t:1594bd99e511` |
| a4 | 81 | 72 | 53 | 20 | `t:308fc204331e` |
| a1 | 84 | 75 | 56 | 20 | `t:653aa9236910` |
| a2 | **88** | **79** | **59** | **21** | **`t:365aafec29d4`** |

88 tools, exactly the base 78 plus the eleven ops the four agents added — the
plan's predicted number, measured rather than assumed.

Two `ops/__init__.py` orderings were wrong in the agents' own branches and were
fixed at the pick: `TargetPlane` sorts before `UnknownPiece`, and a2 had put
`export_assembly` before `deforming_bone_names` and `render_assembly` before
`rename_object`. The base file's three pre-existing case-insensitive
out-of-order pairs were left alone — they are not this run's.

**One branch rule broken, and how it was handled.** a2 appended a 71-line log
entry to `docs/loop/log.md` naming its commit as `loop/a2` and inventing a run
id (`2026-10-26-03`). The run log is written after the merge, when the real shas
exist, so that hunk was DROPPED at the pick and this entry replaced it. The
work itself was sound and merged whole; only the premature bookkeeping was
removed.

### Gates on merged `main`

| gate | before the run | after |
|---|---|---|
| `test-golem` | 33 passed | 33 passed |
| `test-pure` | 1597 passed, 1 xfailed | **1693 passed, 1 xfailed** |
| `test-mcp` | 53 OK | 53 OK |
| `test-blender-app` | 541 passed, 1 skipped | **605 passed, 1 skipped** |

Every branch's gates were also re-run IN ITS OWN WORKTREE before the merge — a
reported green is not proof.

### Model routing

`scripts/audit_task_child_models.py` over the six children:
`PASS every work turn ran on the required provider and model`, 1235 work turns,
**off-pin 0**. Per child: a1 159, a2 94, a3 179, a4 81, a5 106, a6 181 work
turns, every one `ollama-cloud/deepseek-v4.1-flash:1017`, `fallback=false`, and
each child's own report carried its `MODEL_ROUTING:` line.

### Issues closed with evidence

#25, #26, #23, #17, #14, #13.

### Top 5 remaining

1. #1 — the full four-set PBR run, now that the height range and the grass/
   asphalt/tile fixes have landed one set at a time.
2. A new issue for the two palette defects a5 named and did not fix: the
   asphalt's brightness (1.33x) and the tile grout's width and hue.
3. The `focus` render path is the one the blacksmith session said it would use
   every turn; a run that re-does that assembly with `define_assembly` +
   `render_assembly(focus=[…])` would be the honest end-to-end test of #26.
4. `pbr/noise_curl.py` and `pbr/noise_gabor.py` are unreachable by the same AST
   walk that condemned `splatter.py` — confirm dead, then delete or wire.
5. #2 — the loose-ground scatter's colour model (stones read as flat discs).
