# golem_mcp — the work loop log

One entry per iteration of `/build-loop`. Newest last. Each entry names the
tier, the unit, the evidence, the commit, the deploy result and what is left.

| run | date | tier | unit | commit |
|---|---|---|---|---|
| 2026-10-24-01 | 2026-10-24 | 1 (issue) | #19 `duplicate_object` kept the source's parent | `bb3dfa6` |
| 2026-10-25-01 | 2026-10-25 | 1 (issue) | #24 the GPU-timeout test raced bash's startup | `c32f998` |
| 2026-10-26-01 | 2026-10-26 | 1 (issue) | #21 `join_objects` combines parts into one mesh | `9ad4b71` |
| 2026-10-26-02 | 2026-10-26 | 1 (issue) x6 | six-way fan-out: #12, #15, #16, #18, #20, #22 | `66be8f8`, `16303df`, `2579653`, `fb104c4`, `add1fa1`, `60397ba` |

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
