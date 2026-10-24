# golem_mcp — the work loop log

One entry per iteration of `/build-loop`. Newest last. Each entry names the
tier, the unit, the evidence, the commit, the deploy result and what is left.

| run | date | tier | unit | commit |
|---|---|---|---|---|
| 2026-10-24-01 | 2026-10-24 | 1 (issue) | #19 `duplicate_object` kept the source's parent | `bb3dfa6` |
| 2026-10-25-01 | 2026-10-25 | 1 (issue) | #24 the GPU-timeout test raced bash's startup | `c32f998` |

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
