# golem_mcp — the work loop log

One entry per iteration of `/build-loop`. Newest last. Each entry names the
tier, the unit, the evidence, the commit, the deploy result and what is left.

| run | date | tier | unit | commit |
|---|---|---|---|---|
| 2026-10-24-01 | 2026-10-24 | 1 (issue) | #19 `duplicate_object` kept the source's parent | `bb3dfa6` |

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
