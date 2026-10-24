# Run 2026-10-25-01 — evaluation

## The defect, measured twice in opposite directions

| when | page cache | result of `test_a_job_over_its_timeout_is_terminated_and_reported` |
|---|---|---|
| 2026-10-24 (previous run), fresh worktree at `c217f2f` | cold | **5 of 5 failed** |
| 2026-10-25 (this run), same code | warm | **10 of 10 passed** |

Same code, same machine. The outcome tracks exec latency, not the module.

## Why: the old fixture asked a question about bash, not about `run_gpu_job`

The old test asserted that a marker file existed, where the marker was written
by the fake `gpu-tenant`'s `trap … TERM`. A shell runs a trap only for a signal
that arrives **after** the trap is installed, and the test allows the job one
second.

**Startup-delay sweep, old fixture** (`evidence/old-vs-new-fixture.txt`):

| delay before the fixture reaches its trap line | trap ran | exit |
|---|---|---|
| 0.00 s | yes | 143 |
| 0.05 s | yes | 143 |
| 0.25 s | yes | 143 |
| 0.50 s | yes | 143 |
| **1.50 s** | **no** | **−15** |

**The cause: a fresh script's first exec on this Mac** (8 freshly written
scripts, then the same 8 again):

| | spawn → the script's own first write |
|---|---|
| fresh file (first exec) | 5.388, 0.187, 0.202, 0.214, 0.199, **7.802**, 0.197, 0.189 s |
| same files, re-executed | 0.010, 0.008, 0.010, 0.009, 0.009, 0.009, 0.007, 0.009 s |

A 1 s timeout sits inside the tail of a distribution reaching 7.8 s. The
threshold measured above (works ≤ 0.5 s, fails ≥ 1.5 s) straddles it, which is
exactly the 5-of-5-red / 10-of-10-green inversion.

## The change

Fixture becomes `exec python -c "time.sleep(41.3)" <per-run token>`;
assertions become (1) `GpuJobError` matching `exceeded 1s and was killed`,
(2) **the job's process is gone from the process table**, (3) the call returned
well under the 41.3 s the job would have run.

**New fixture, same delay sweep — deterministic at every delay:**

| delay | job still running after the call |
|---|---|
| 0.00 / 0.05 / 0.25 / 0.50 / 1.50 s | **false** at every one |

## Two of my own mistakes, both caught by mutation testing

1. **The first assertion set was insufficient.** A mutant that raises on timeout
   but never stops the job **passed** a timing-only check (it returns in ~1 s
   while the job runs on). Fixed by asserting the pid is absent.
2. **The first token was invisible.** `exec sleep 41.3 # <token>` puts the token
   in a shell *comment* — never in argv — so the process-table check matched
   nothing and passed vacuously. `sleep 41.3 <token>` is rejected by `sleep`
   ("invalid time interval"). Fixed by using a python job, whose argv carries the
   token: measured visible while running, absent after termination
   (`evidence/token-in-argv.txt`).

A fixed marker also collided with an orphan from an earlier probe and turned a
green run red, so the token is per run (`uuid4`), and the test kills any
survivors itself so it leaves no 41 s sleep behind (verified: 0 orphans after
10 runs).

## Mutation sweep (the test must fail when the feature breaks)

| mutation to `gpu.run_gpu_job` | test result |
|---|---|
| remove the `GpuJobError` raise (job killed, not reported) | **failed** |
| keep the raise, remove `_stop` (reported, job left running) | **failed** |
| `timeout=None` (wait the job out) | **failed** (41.5 s) |
| unmutated | **passed**, 10 of 10 consecutive runs |

## Gates

| gate | baseline (before) | after |
|---|---|---|
| `make test-golem` | 3 of 3 passed (warm cache) | **5 of 5 passed**; single test 10 of 10 |
| `make -C blender test-pure` | 1547 passed, 1 xfailed | 1547 passed, 1 xfailed |
| `make -C blender test-mcp` | all OK | all OK (36 / 1 / 36 / 7 / 53) |
| `make -C blender test-blender-app` | 475 passed, 1 skipped | 475 passed, 1 skipped |

No product code changed, so no `test-repro` (no builder), no `test-bench-scripts`
(no benchmark script), and no renders: this is a test-harness defect with a
numeric proof, not a geometry or appearance change.
