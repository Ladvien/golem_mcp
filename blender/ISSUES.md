# ISSUES.md — the 2026-10-07 review follow-up

The 2026-10-07 full-repo review left S1-S3, P1-P5, D1-D8 and a PROPOSED list open; the follow-up on branch `fix/review-followup-2026-10-07` verified each and closed all of them (closures below). Three new findings made during the follow-up are open, listed first; nothing else is.

## Open (found during the follow-up, not fixed)

### N1 — `rebuild_twice --iteration` cannot replay iteration 49, and the `uv_crate` golden asserts nothing about UVs
`make test-repro ARGS="--iteration 49"` exits 1 on `main` as well as on this branch (measured on both): chunk 1 raises `AttributeError: 'str' object has no attribute 'location'`, because `add_box` returns an `ObjectName` and the recorded chunk predates that. `scripts/rebuild_twice.py` aborts on any failed chunk; `blended.evaluate.replay.replay_record` (what the golden tests use) does not. Replayed through `replay_record`, 12 of iteration 49's 20 replayed calls (run_python chunks and op calls) fail (`TypeError: ops take object NAMES (str), got Object` and `AttributeError`), and the scene ends with one object `Crate` whose meshes (`Crate`, `Crate.002`) have no UV layer. `tests/blender/test_golden_convergence.py` still passes for `uv_crate` because it asserts the form gate and dimensions only. So the "uv_crate golden" does not pin a UV-unwrapped crate, and the iteration lane of `test-repro` is unusable for records that contain failed chunks. A fix is a decision: re-record the golden in the viewport (`CLAUDE.md`, "Pin verified behavior"), and either make `rebuild_twice` replay through `replay_record` or restrict `--iteration` to records without failed chunks.

### N2 — `BMB_ENDPOINT` names an address bmb no longer has
`src/blended/agent/loop.py:74` (and `tests/pure/test_review_agent_loop.py:232`) hardcode `http://192.168.1.233:9292`. On 2026-10-07 bmb answered at `192.168.1.205` (`bmb.local` resolves to it; `ssh bmb` reaches it) and `192.168.1.233` did not answer (`curl` code 000, `ping` 100% loss). The memory note already says the address moves; the constant should resolve `bmb.local`. Not changed: the follow-up rotated the key and probed through `bmb.local:9292`, and changing the endpoint is a lane decision.

### N3 — three comments cite BlenderGym's "verification ratio" for a deterministic verifier
`scripts/orientation_policy_sim.py:25`, `src/blended/evaluate/bench_bridge.py:134` and `src/blended/ops/canonical_orientation.py:33` say BlenderGym measures a win from raising a loop's *deterministic* verification ratio. The paper (arXiv 2504.01786, section 4.3 and Fig. 7-8) measures that systems with a higher share of queries spent on **VLM verifier** calls (VeriRatio 0.33, 0.62, 0.73) outperform those with a lower share; a deterministic geometric check is the repo's extension of that result, not something the paper measured. Not reworded: the three sites are comments in pinned text paths and the wording is the owner's call.

## Closed

| Item | How it was closed | Guard |
|---|---|---|
| S1 | bmb llama-swap key rotated on 2026-10-07 (history not rewritten, by the owner's decision). Probe `POST /v1/chat/completions`: new key 400 (past auth, nonexistent model), old key 401. The rotation's old key is no longer valid; `git grep` finds the new key nowhere. | `bmb-key-committed-in-public-history` |
| S2 | HTTP transport: `--host` must be loopback; DNS-rebinding protection on with loopback `Host` and `Origin` only (live: evil Host 421, evil Origin 403, loopback 200). | `tests/pure/test_review_followup.py` |
| S3 | Add-on `start()` refuses any host that does not resolve only to loopback. | `tests/blender/test_review_mcp_addon.py` |
| P1 | `Action.fcurves` fix text states the measured `AttributeError`; assembled fingerprint `a10:c68237772de1` -> `a10:c16070bc954b`, pin rewritten. | `tests/blender/test_review_analyze_capture.py::test_drift_signatures_match_the_error_blender_really_raises` |
| P2 | A wire edge counts as non-manifold (`link_faces > 2 or == 0`); no golden moved. | `tests/blender/test_review_followup.py` |
| P3 | `length_m = hypot(rise, run) + drop / cos(splay)`; the golden stool and leg tests stayed green. | `tests/pure/test_splayed_leg_spec.py::test_the_axis_top_lands_on_the_top_circle` |
| P4 | `import_glb` recentres on the bounding-box centre; no golden moved. | `tests/blender/test_review_followup.py` |
| P5 | `view_name` dropped from `_examiner_prompt`; `examiner_identity` unchanged (`x+examiner:4bc67293e36c` before and after). | `tests/pure/test_examiner.py` |
| D1 | `run_batch`, `run_script_subprocess`, `run/_bootstrap.py` deleted with their tests and records; EXE-9 and EXE-10 retired in place. | `git grep` finds only past-tense narrative |
| D2 | `reset_scene` restores frame range, current frame, units and resolution; `assert_clean_scene` asserts them. | `tests/blender/test_review_followup.py` |
| D3 | The two test files that never ran moved to `tests/bench_scripts/`, run by `make test-bench-scripts` in a throwaway env (numpy, scipy, trimesh, Pillow never enter `.venv`). 0 skipped there; `make test-pure` has no import skips. | `make test-bench-scripts` |
| D4 | `blender_mcp/mcp/pyproject.toml`: `requires-python >=3.11`, `anyio` declared; `blended` stays undeclared (the workspace root supplies it, and declaring it would be circular). `uv.lock` updated. | `uv lock` / `uv sync` |
| D5 | Render tools append the format's extension before setting the path and return the written file; the objects summary reports `hide_viewport` and a separate `hide_in_view_layer`. | `tests/blender/test_review_mcp_tools.py` |
| D6 | A raised chunk is emitted as `exec(compile(<repr>, <label>, "exec"), globals())`, byte for byte. | `tests/pure/test_review_followup.py` |
| D7 | Not a defect: the cap overshoot is deliberate. `tests/blender/test_agent_loop.py::test_the_budget_counts_calls_not_messages` pins "a message's calls are never half-answered", and the stop text reports the executed count. | that test |
| D8 | `tests/pure/test_agent_cancel.py` renamed `test_turn_token_budget.py`; live references updated; `BACKLOG_DONE.md` gained an append-only Errata section and its in-place edit was reverted. | `tests/pure/test_review_mistake_memory.py` |

PROPOSED items:

- `digest.py` `_uv_component` loop order: falsified as a risk, no code changed. The three builders (barrel, crate, pallet) passed `make test-repro` but carry no UV layer (`grep unwrap_uvs src/blended/builders` finds nothing), so those runs say nothing about UVs, and iteration 49 could not run (N1). A UV-bearing build was measured instead: a beveled box with a bore and a notch (two EXACT booleans) unwrapped with `ANGLE_BASED`, 78 polygons, 348 UV loops with 348 distinct values (the probe varies), built in six fresh Blenders under `PYTHONHASHSEED` 0-5: identical scene digest and identical raw UV loop order in all six. Scope of the claim: that build family and that seed range, one thread configuration.
- `CALIBRATION_PATH` (`visual_diff`, `examiner`) cwd-relative: not a defect. Every entry point `chdir`s to the repository root (`scripts/run_agent_task.py:39`, `scripts/run_tests_in_blender.py:44`, `scripts/calibrate_visual_gate.py:48`, `scripts/calibrate_examiner.py:53`), and `examiner.py` reports a missing file by path.
- `claude_code.py` `check_connection` non-object JSON and a watchdog kill mid-frame: both reproduced and fixed (`tests/pure/test_review_followup.py`).
- `prompt_search` rejected-hunk memory keyed by line range: by design. `prompt_versions.changed_hunks` keys a hunk as `"<opcode> lines i1-i2 -> j1-j2"`, which is positional by construction; the memory refuses a repeated edit at the same place and does not claim to recognise a shifted one. The consequence of a miss was not measured.
- `validate_modules()` duplicate names: fixed (`tests/pure/test_review_followup.py`).
- Examiner numeric claims, checked against the papers' full text (home-still `paper_get` and `distill_search` timed out after 900 s each, so arXiv HTML was read): BlenderGym 0.66 is the best VLM verifier (Claude-3.5-Sonnet) against 0.79 inter-human, confirmed; RefGlitch-Bench (the `RESP` the comments cite, arXiv 2604.11082), Qwen3-VL-8B recall 0.76 with the oracle reference, 0.69 with the best automatic reference, 0.28 with none, and the irrelevant-reference drop of 0.23 F1, all confirmed. One citation was NOT supported: `examiner.py` said BlenderGym measured judge position bias, and the paper's text has no position-bias measurement (the words "position bias" occur zero times); the attribution was removed and MT-bench kept. The comment's "five-defect zoo" is a four-defect zoo (`scripts/calibrate_examiner.py::_fixtures`) and now says so.
- `.mcp.json` absolute paths: documented in `README.md` ("`.mcp.json` and `.omp/mcp.json` name this machine's absolute paths").
- `heal.py` edge-index keying: `edges.index_update()` added. A collision could not be made: 4 constructed meshes and 40 randomised icospheres (vertices snapped within and beyond the weld distance, faces collapsed) gave contiguous, duplicate-free, non-negative edge indices after `remove_doubles` and `dissolve_degenerate`. No test, no record.

Verification counts and the commands are in the pull request.
