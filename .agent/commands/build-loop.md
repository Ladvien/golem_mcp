---
description: One iteration of the golem_mcp loop (issue, then bug, then improvement)
argument-hint: "[optional: issue number or focus, e.g. '#1' or 'pbr']"
---

# golem_mcp: One Unit of Work, Fixed, Documented, Deployed

You are one iteration of a loop on golem_mcp: one MCP entry point over a
GPU half on big (image to mesh, rig, animation) and a Mac half that
drives Blender 5.2 with a measured acceptance gate and a PBR texture lane.
Do exactly one unit of work, prove it, document it, deploy it to the home
machines, log it. Then stop. $ARGUMENTS

## Choosing the work: first non-empty tier wins
1. **Open issue.** `gh issue list`. Take the one with the highest user
   impact that you can finish in one iteration (an explicit argument
   overrides). Carve oversized issues to the most valuable slice and
   comment the remainder on the issue.
2. **Bug.** If no issue is workable, hunt for bugs (step 2) and fix the
   worst one. File every bug you find but do not fix as an issue.
3. **Improvement.** Only when the issue list is empty or blocked and the
   bug hunt finds nothing worth fixing, make one improvement (step 3).

One unit per iteration. Never combine tiers.

**Start anywhere in the repo, but treat the repo root as the base.** This
command lives at `.agent/commands/build-loop.md`, which omp's `agents`
provider finds from the root and from subdirectories like `blender/`. Every
path below is root-relative (`blender/...`), and the make targets are called
with `-C blender` rather than by changing directory.

## Directory (every agent uses exactly this)
```
docs/loop/                       # repo root; create on the first run
  log.md   needs-decision/
  runs/YYYY-MM-DD-NN/
    plan.md  eval.md  deploy.md
    evidence/ (before/, after/, renders/)
```

## 1. Orient
Read `docs/loop/log.md`, `blender/BACKLOG.md` (open items),
`blender/BACKLOG_DONE.md` (closed, with dates), `blender/ISSUES.md`,
`git log --oneline -20`. Confirm main is clean and in sync
(`git status --porcelain`, `git rev-list --count HEAD..origin/main` = 0).
Then run the baseline and record exactly what is already red:

```
make test-golem                       # root: golem's own unit tests (~30 s)
make -C blender test-pure             # no Blender needed, ~20 s
make -C blender test-mcp              # the MCP server's unit layer (~30 s)
make -C blender test-blender-app      # inside Blender 5.2, minutes
```

`make -C blender test` is the full gate (pure + Blender app + bench scripts
+ MCP). The root Makefile has no `test-pure`; `make` at the root runs
`test-golem` then `test-blender` (which is `blender/`'s pure + MCP layers).
If an earlier iteration left work half done (uncommitted, undeployed,
unlogged), finish or revert it first.

## 2. Bug hunt (tier 2 only)
Evidence first. Run real tasks through the single `golem` entry point as an
agent would: model a prop with ops, hit the gate with bad geometry, run
`generate_3d` then `rig_model` then `animate_mesh`, generate a PBR set from
words, register a kit pack. Check the known drift too:
- Tool count and fingerprint in `blender/BACKLOG.md`'s "Measured starting
  point" vs the live set, from the repo root:
  `GOLEM_BLENDER_DISABLE_PLUGINS=1 blender/.venv/bin/python -c "from
  golem_blender.agent.tools import TOOL_SCHEMAS, TOOL_SCHEMAS_FINGERPRINT;
  print(len(TOOL_SCHEMAS), TOOL_SCHEMAS_FINGERPRINT)"`, against
  `blender/_evaluate/golden/pinned_tool_schemas_fingerprint.txt` (71 /
  `t:16855e3dd426` on 2026-10-24; `BACKLOG.md` still said 64 /
  `t:278d1153fe2c`). `test-pure`'s
  `tests/pure/test_tool_schemas.py` catches a pin that drifted from the
  code, not a `BACKLOG.md` row that drifted from both.
- Stale `src/blended/` paths and old counts in the spec's measured-state
  table (`blender/docs/2026-09-10-specification-and-requirements.md`).
- Hard-coded absolute paths: `blender/.mcp.json` (committed) and the
  user-level `~/.omp/agent/mcp.json` `golem` entry both name this machine's
  checkout path, so a checkout elsewhere breaks. `blender/README.md`
  documents `.mcp.json` as machine-specific; the user entry is not in the
  repo.
- The xfail in `test-pure` (`tests/pure/test_examiner.py::
  test_the_shipped_eye_holds_the_licence_in_the_repository`): still failing
  for the stated reason?
- Ops whose tool schema and behavior disagree; tracebacks that miss a
  known API-drift fix (`blender/src/golem_blender/drift/`).
- Host-specific paths in tracked files (`git grep -l '/Users/' -- '*.py' '*.sh'`):
  ten `blender/scripts/` entries prepend this machine's checkout to
  `sys.path` (an absolute `/Users/.../blender/src` plus a hardcoded
  `.venv/lib/python*/site-packages` glob), so the benchmark runs only from
  this path. `blender/.mcp.json` is documented as machine-specific.
  Anything you touch becomes relative
  (`pathlib.Path(__file__).resolve().parents[2] / "src"`, as
  `refit_palette_tables.py` already does).

Rank by harm: wrong output passing the gate, lost work, crashes, then
misleading messages, then docs. A bug without a reproduction is not a bug.

## 3. Improvement (tier 3 only)
Pick the single most valuable gap (the missing ops in #16-#23 if still
open, a lane metric, an agent-facing error message). Justify it in one
sentence against the runner-up. It must fit the conventions below.

## 4. Plan and build
Write `plan.md`: the failing behavior or goal, the fix, touched modules,
tests, and deploy impact (does the tool fingerprint change, does the GPU
half change?). Conventions that bind every change:
- The agent's artifact is a program: structured tracebacks, retries capped
  at 2, every attempt logged to JSONL.
- The analyzer decides, renders advise. Scene-changing ops stay gated.
  `declare_plan` precedes scene-changing calls.
- Op tools are generated from the ops facade signatures, never hand-written.
- Fail loud, one path per feature, no fallbacks or stubs. Pinned prompt and
  tool fingerprints are test-enforced: a schema change updates the pins in
  the same commit and is called out in the log.
- The big half holds no VRAM; every job is a subprocess under a gpu-tenant
  lease. Never bypass the lease.
- Decisions that need the operator (package layout, licensing, anything
  touching the vendored `blender_mcp` subtree, GPU scheduling policy) go to
  `needs-decision/` with options and a recommendation. Pick another item.
- No real hostnames, IPs or secrets in committed docs.

## 5. Verify
- A test that fails before the change and passes after (a regression test
  for bugs and issues; behavior tests for improvements).
- `make test-golem`, `make -C blender test-pure`, `make -C blender test-mcp`,
  `make -C blender test-blender-app`; add `test-repro` and
  `test-bench-scripts` when you touched builders or benchmark scripts.
  Nothing may get worse than the step 1 baseline.
- **Look at it.** Anything that changes geometry, materials, rigs or
  animation needs real renders (`render_views`, `preview_texture`) at
  identical state before and after, plus zoomed crops (OpenCV/Pillow) of
  the affected region. Write the critique before the verdict. Only a clear
  win passes; after 5 failed rounds, log the blocker and revert.
  Done means executed, passed the gate, and looks right.
- **PBR lane changes** re-score against the ambientCG sets with the same
  command and sets as the last logged score. From `blender/`, per set
  (`blender` is not on PATH here; `blender/Makefile`'s `BLENDER` default is
  the installed app):
  ```
  export GOLEM_BENCH_ROOT=~/mnt/codex_fs/game_assets/benchmarks/<set>
  export BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"   # blender/Makefile's default
  "$BLENDER" --background --factory-startup --python scripts/benchmarks/recreate_from_descriptions.py
  "$BLENDER" --background --factory-startup --python scripts/benchmarks/score_recreations.py
  "$BLENDER" --background --factory-startup --python scripts/benchmarks/score_pbr_channels.py
  python scripts/benchmarks/close_sheet.py --root "$GOLEM_BENCH_ROOT" --out <dir> --rows 12
  ```
  The sets are `ambientcg`, `ambientcg_wide`, `ambientcg_popular`,
  `ambientcg_top` (159 materials). Record every metric before and after
  (albedo brightness, contrast, feature scale, colour, roughness, normal
  strength, AO, height-luma) in `eval.md`, and read the close sheet — a
  number hides a routing or scale fault. A change must not worsen a metric
  it did not target.

## 6. Document
Update everything the change touched: docs, the op or tool descriptions,
`blender/BACKLOG.md` (including the measured starting point if the tool
count or fingerprint moved), the spec rows it affects, and
`blender/ISSUES.md` where relevant. Fix any stale claim you touched. Close
the issue by commit message or `gh issue close` with a comment pointing at
the evidence.

## 7. Publish and deploy to the home machines
There is no CI, so the local make targets are the gate. Publish in order:
1. Commit and push main (plain fast-forward; never force).
2. Deploy to each machine the change touches, by the repo's documented
   procedure and nothing else:
   - **big** (GPU half, `:9786/mcp`): the checkout is golem's server
     working directory on that host (`WorkingDirectory` in
     `golem-mcp.service`), the package is installed **editable**, and
     `SETUP.md` §"The service" states the one documented step: after a
     server-code change, `systemctl --user restart golem-mcp` (a running
     instance keeps serving the old code). Bringing the checkout to the new
     commit (`git fetch` + `git merge --ff-only origin/main` over SSH) is
     what makes that restart pick the change up; `make sync-golem` only when
     dependencies or `pyproject.toml` moved. Before restarting, check the GPU
     lease: `ssh big gpu-tenant status`, also reported by `health_check` as
     `gpu`. Never restart under a running job — wait or defer the deploy and
     log it as deferred.
   - **this Mac** (Blender add-on and harness): edits under
     `blender/src/golem_blender` are live on the next call (Blender purges
     and re-imports on a source-fingerprint change). Anything loaded at
     server start (tool listing, descriptions, instructions, any `blmcp`
     edit) needs the MCP server restarted; the user-level omp `golem` entry
     in `~/.omp/agent/mcp.json` passes `--exit-on-source-change`, so omp
     restarts it. Add-on edits (`blender_mcp/addon`) need a Blender restart,
     and a changed add-on install is `make -C blender install-mcp-addon`.
   - **bmb** (mflux for `generate_image`, SkinTokens for `rig_model`): if
     no documented procedure covers what changed, write the gap to
     `needs-decision/` and stop at the commit; never improvise a copy.
3. Verify on each machine and write `deploy.md`: the commit that is
   running, the live tool count and fingerprint matching what the tests
   pin, and one smoke call per touched half through the single `golem`
   entry point. A machine whose fingerprint or commit does not match is a
   failed deploy: fix or roll back, then log it.

## 8. Log
Append to `docs/loop/log.md`: tier, what changed, why it was chosen,
evidence and before/after numbers, commit, per-machine deploy result,
issues filed, and the top 5 remaining items.

## Rules
- One unit per iteration: tested, looked at, documented, deployed, logged.
- No claim of improvement without a number or before/after renders.
- Not deployed means not done. Not logged means not done.
- If blocked, log it and take the next item in the tier.
