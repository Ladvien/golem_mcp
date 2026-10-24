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

**Gates.** `test-golem` 10 passed; `test-pure` 1547 passed / 1 xfailed;
`test-mcp` all OK; `test-blender-app` 469 → **475 passed**, 1 skipped. Nothing
went worse. Tool count unchanged at 71; fingerprint `t:16855e3dd426` →
`t:7a8ffdbc17da`, pin updated in the same commit.

**Deploy.** Mac half only; the schema is read at server start and the omp
`golem` entry's `--exit-on-source-change` restarted it (the live
`duplicate_object` tool description already carries "parent dropped"). Big's
half is untouched — `src/golem_mcp` did not change, so its editable install
serves identical code and was not restarted.

**Issues filed.** None (nothing found that was not fixed).

**Top 5 remaining.**
1. #2 — the loose-ground scatter's colour model (stones read as flat discs).
2. #1 — the full four-set run after the knit/plaid/seam and AO/leaf-litter batches.
3. #19's sibling gap, now measured: **no op sets an object's parent**. Building
   the fixture for this issue needed `run_python`; a kitbash piece that mounts
   on another part has no op path. File as an issue in the next run if it is
   still true.
4. #11 — the tile-floors scale measure reads hairline grout and hands the lane
   2–3× the truth's tile count.
5. #20 — a seeded jitter op, so a stone or straw bundle is not a smooth
   primitive.
