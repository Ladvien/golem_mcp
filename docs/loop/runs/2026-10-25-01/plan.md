# Run 2026-10-25-01 — issue #24: the timeout test races bash's startup

**Tier:** 1 (open issue). **Chosen over** the PBR-lane issues (#1–#15) and the
missing-op issues (#16–#23) because it is the only open item that makes the
suite itself unreliable: `make test-golem` is the gate every future iteration
reads, and a gate that reports red or green by luck is worse than a missing
feature. #15 (delete an unused file) is smaller but has no user impact; the PBR
issues need a four-set re-score to prove anything.

## The failing behaviour (measured twice, in opposite directions)

The same code, same machine, different cache state:

| when | cache | result |
|---|---|---|
| 2026-10-24 (previous run), fresh worktree at `c217f2f` | cold | **5 of 5 failed** |
| 2026-10-25 (this run) | warm | **10 of 10 passed** |

`tests/test_gpu.py:test_a_job_over_its_timeout_is_terminated_and_reported`
ends with `assert terminated.exists()`, where `terminated` is written by the
fake `gpu-tenant`'s `trap … TERM`. A shell only runs a trap for a signal that
arrives **after** the trap is installed, and the test gives the job
`timeout_s=1`. So the assertion asks whether bash reached its second line
within one second — a question about the host's exec latency, not about
`gpu.run_gpu_job`.

Deterministic reproduction (`evidence/old-fixture-under-slow-exec.txt`), the
old fixture body with a startup delay injected as its first line:

| delay before the fixture's own first line | rc | trap ran |
|---|---|---|
| 0.0 s | 143 | **true** |
| 1.5 s | −15 | **false** |
| 3.0 s | −15 | **false** |

And the underlying cause, measured directly on this Mac (8 freshly written
scripts, then the same 8 again):

| | spawn → the script's own first write |
|---|---|
| fresh file (first exec) | 5.4, 0.19, 0.20, 0.21, 0.20, 7.8, 0.20, 0.19 s |
| same files, re-executed | 0.010, 0.008, 0.010, 0.009, 0.009, 0.009, 0.007, 0.009 s |

A 1 s timeout sits inside the tail of a distribution that reaches 7.8 s, so
the test's outcome is a coin flip weighted by page-cache state. `run_gpu_job`
is correct in both outcomes — it raises `exceeded 1s and was killed` either
way, because `proc.terminate()` reaches the child pid whether or not bash has
installed a handler.

## The change

Rewrite the fixture and the assertion so nothing depends on bash scheduling:

- The fake `gpu-tenant` body becomes `exec sleep 30` — no trap, no marker
  file. `exec` replaces bash with `sleep`, so the child exists as one process
  from the first instant.
- The assertions become the two things `run_gpu_job` actually promises:
  1. it raises `GpuJobError` matching `exceeded 1s and was killed`;
  2. it **returns promptly** — elapsed time stays far below the 30 s the job
     would have run, which is what "terminated" means.
- A module constant `JOB_WOULD_HAVE_RUN_S = 30` and `TERMINATED_WITHIN_S = 15`
  replace the inline numbers (the repo's named-tolerance rule).

The trap-ran marker is dropped deliberately: it asserted a property of bash,
not of this module. What proves the timeout branch still works is that
`pytest.raises` fails the moment the branch is removed (verified below).

## Touched

- `tests/test_gpu.py` — the fixture body and the assertion.
- No product code: `src/golem_mcp/gpu.py` is untouched, so no tool schema, no
  fingerprint, no GPU-half change.

## Deploy impact

**None.** The change is a test in the root environment only. `src/golem_mcp`
is unchanged, so big's editable install serves identical code (no restart); the
Mac half does not contain this file (no server restart). Verification is that
the live servers are unchanged, recorded in `deploy.md`.

## Verification

1. The rewritten test passes 10 of 10 consecutive runs.
2. Fail-before on the real test: with the timeout branch removed from a copy of
   `run_gpu_job`, the test must fail (proves it still guards the feature) — run
   with `monkeypatch`-free source mutation in a scratch copy.
3. The old fixture's determinism failure under slow exec is already recorded
   (the table above).
4. Gates: `make test-golem`, `make -C blender test-pure`, `test-mcp`,
   `test-blender-app`.
