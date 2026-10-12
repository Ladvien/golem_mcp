# blended — Backlog: done

Items move here from `BACKLOG.md` verbatim when they satisfy the closing rule
(`BACKLOG.md` § Closing rule): **Done means** test in the tree and green in both
layers (`make test`), spec rows amended in the same change, and — for OT-9
through OT-11 — the pre-registered hypothesis filled with a measured outcome.

Each entry records: the item block as written, the closing commit, the test(s)
that gate it, and the date closed. Nothing here is edited after it lands; a
regression reopens the item in `BACKLOG.md` with a pointer back to this entry.

---

## OT-1 Complete the ops facade

**What:** `blended.ops.__init__` MUST re-export every public op, including `legs`, `canonical_orientation`, and `add_lathe`. The barrel builder MUST import `add_lathe` from the facade.
**Why:** OT-3 generates schemas by introspecting the facade. Anything not on the facade is invisible to the agent and to the tests that check the whitelist. Closes spec §7.3 row 5.
**Amends:** OPS-1.
**Done means:** `tests/pure/test_one_path_ops.py` asserts that every public callable under `src/blended/ops/*.py` is reachable from the facade, and no builder imports an ops submodule directly.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_one_path_ops.py::test_every_public_op_is_reachable_from_the_facade`, `::test_facade_exports_nothing_it_does_not_define`, `::test_builders_import_only_the_facade`, `::test_every_ops_submodule_is_in_the_manifest`.
**Spec:** OPS-1 row amended; §7.3 facade gap row removed.
**Side effect, measured:** adding `canonical_orientation` to `OP_MODULE_NAMES` put its ops into the manifest the model reads; assembled prompt fingerprint moved `a10:f13911deb826` → `a10:315c684fd7f6` (pin updated in the same commit). `PromptRevision.identity` did not move.
**Layers:** pure 432 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `7226f01`.

---

## OT-2 Op signature contract

**What:** Every op on the facade MUST satisfy a machine-checkable contract: type-annotated parameters; unit-suffixed names for quantities (`_m`, `_deg`, `_px`) per NFR-8; a docstring whose first line is the one-sentence description; an explicit return annotation naming the object(s) created or modified; no `bpy` types in the signature (object references are names, `str`).
**Why:** The schema generator can only emit what the signature carries. This is the same discipline OPS-16 already applies to `Parameters`; it extends it to ops.
**Amends:** adds `OPS-21`.
**Done means:** `tests/pure/test_ops_signature_contract.py` fails on any facade op that violates the contract. A seeded-defect fixture op (NFR-15) trips it.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_ops_signature_contract.py::test_facade_op_satisfies_the_signature_contract` (parametrized over every facade op), `::test_the_contract_trips_on_a_seeded_defect` (NFR-15 fixture), `::test_unitless_allowlist_is_all_in_use`, `::test_typing_is_not_needed_at_import`.
**Spec:** OPS-21 row added; §5.5 gains the contract constants; §6.3 OPS 20 → 21.
**Shape of the change:** every op takes object NAMES (`str`) and returns the name(s) it created or modified; `blended.ops._objects.object_by_name` is the one resolver and raises `UnknownObject` / `WrongObjectType`. Callers converted: three builders, harness, agent tools, export, ingest cleanup, `examples/harness_demo.py`, `scripts/calibrate_examiner.py`, `scripts/chat_e2e.py`, 25 Blender test modules.
**Side effects, measured:** the manifest renders the new signatures, so the assembled prompt fingerprint moved `a10:315c684fd7f6` → `a10:2933f0ebd234` (pin updated); `PromptRevision.identity` (`v10:b6627b38f4c1`) did not move. Goldens 48 (planter_box) and 50 (ribbed_column) stopped replaying — their recorded model sources passed bpy objects into ops — and were replaced by iterations 66 and 67, run on the same v10 text on `claude-code:sonnet` (8 and 6 turns, 0 name-vs-object errors, identical form numbers). Pixel gate against the old views: planter shading RMSE 0.075 vs 0.010 limit, column silhouette IoU 0.9948 vs 0.998 floor — a fresh run beside a replay. The three untouched goldens re-minted pixel-identical (0.00 % differing) and were reverted. Mechanism recorded in `mistake_memory.py` as `a-signature-change-invalidates-recorded-model-code-not-just-callers`.
**Signed off:** 2026-09-10, by the user on the 66/67 contact sheets (the banner this line replaces said it would come off with the sign-off).
**Layers:** pure 477 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `22fdc8c`.

---

## OT-3 Generate tool schemas from the facade

**What:** `build_tool_schemas()` MUST produce one JSON-schema tool entry per facade op from introspection, using the same machinery `build_manifest` uses for prose. `TOOL_SCHEMAS` MUST become the union of the hand-written service tools and the generated op tools.
**Why:** PRM-2 already forbids hand-written manifest prose; the same rule should apply to schemas, or the two will drift.
**Amends:** AGT-1 ("exactly eight tools" becomes "the service tools plus every facade op, generated"), PRM-2.
**Done means:** `tests/pure/test_tool_schemas.py` checks that adding an op to the facade adds a tool, that the parameter set of each generated tool equals the op's signature, and that unit suffixes appear in every quantity parameter name. Fingerprint the generated schema set the way the prompt is fingerprinted (PRM-7) so a schema change is visible in the iteration log.

**Decision recorded here, to be measured in OT-13:** one tool per op, not a single `call_op(name, arguments)` tool. Rationale: per-op tools carry typed arguments into the transport's constrained decoding (the Claude Code lane already builds a `oneOf`-per-tool envelope, AGT-14). Fallback if tool count breaks a local lane: a single `call_op` with `name` as an enum and per-op argument schemas surfaced through `search_ops`.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_tool_schemas.py` — `::test_adding_an_op_to_the_facade_adds_a_tool`, `::test_the_parameter_set_equals_the_signature` (parametrized over every facade op), `::test_every_numeric_parameter_carries_a_unit_in_its_name`, `::test_a_contract_violation_refuses_the_whole_set`, `::test_the_tool_set_has_not_drifted` (pin), plus the type-mapping cases (fixed tuple, optional, config dataclass, tuple of dataclasses, unmappable annotation is loud); `tests/pure/test_prompt_citations.py::test_every_other_registered_tool_is_a_facade_op`.
**Spec:** AGT-1 amended (service tools + every facade op, fingerprinted and pinned); PRM-2 amended (schemas generated like prose); §2.2 rewritten; §5.4 gains `TOOL_SCHEMAS_FINGERPRINT_PREFIX` / `JSON_TYPE_FOR_SCALAR`.
**Shape of the change:** the OPS-21 contract moved from the test into `blended.ops._contract` so the generator and the test read one definition; `blended.agent.tool_schemas` maps resolved type hints to JSON schema (scalars, `Path`, unions with `None`, fixed and variadic tuples, lists, config dataclasses as objects with required fields; anything else raises `UnsupportedAnnotation`) and refuses an op that violates the contract; `tools.py` splits `SERVICE_TOOL_SCHEMAS` (8, hand-written) from `OP_TOOL_SCHEMAS` (generated) and asserts the names are disjoint; `IterationRecord.tool_schemas_fingerprint` is written by `run_agent_task.py`.
**Measured:** 42 op tools generated; `TOOL_SCHEMAS` is 50 entries; fingerprint `t:1fe7f62007ef` pinned in `_evaluate/golden/pinned_tool_schemas_fingerprint.txt`. The assembled prompt fingerprint did not move (tools travel in the API `tools` field / the Claude Code envelope, not the prompt text). `envelope_schema(TOOL_SCHEMAS)` builds 50 `oneOf` variants (existing `test_claude_code_lane` assertion).
**Recorded, to be measured in OT-13:** one tool per op is a hypothesis. Tam et al. (DOI 10.18653/v1/2024.emnlp-industry.91) measured that a schema constraint raises prompt sensitivity and lowers average performance on reasoning tasks while helping classification; the generator docstring carries the citation next to the decision.
**Known gap, closed by OT-4:** `dispatch_tool` does not yet route an op tool; a call to one returns the existing `Unknown tool` result until OT-4 lands. No live lane ran in between.
**Layers:** pure 616 passed / 1 skipped / 1 xfailed; Blender 308 passed / 3 skipped.
**Commit:** `5275dc2`.

---

## OT-4 Op-call dispatch

**What:** `dispatch_tool` MUST route a generated op tool to the facade function, on the main thread (AGT-2), with argument validation failing loud on unknown or missing parameters (NFR-13). The result MUST carry the same `stage_reached` vocabulary as `run_chunk` (EXE-6).
**Why:** The op tool must be at least as observable as `run_python`, or the agent will prefer the hatch.
**Amends:** adds `AGT-21`.
**Done means:** `tests/pure/test_agent_dispatch.py` covers valid call, unknown op, bad argument type, off-main-thread refusal. `tests/blender/test_agent_loop.py` runs a brief to gate-pass using only op tools.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_an_op_tool_call_binds_runs_and_reports_done`, `::test_an_unregistered_tool_is_refused_at_the_door_without_bpy`, `::test_a_mistyped_argument_fails_at_execute_with_the_cause_and_no_traceback`, `::test_unknown_and_missing_parameters_are_named`, `::test_arguments_are_converted_to_the_signature_types`, `::test_binding_is_strict_about_json_types`, `::test_an_op_that_raises_is_a_failed_call_with_its_type_and_traceback`, `::test_an_op_tool_off_the_main_thread_is_refused_like_any_tool`; `tests/blender/test_agent_loop.py::test_a_brief_reaches_gate_pass_with_op_tools_only` (planter_box, nine op calls, zero `run_python`, form gate PASS), `::test_an_op_tool_failure_names_the_op_error_to_the_model`; `tests/pure/test_import_integrity.py::test_the_harness_imports_first_in_a_fresh_interpreter`.
**Spec:** AGT-21 added; EXE-6 amended (vocabulary defined once in `blended.stages`, shared by `run_chunk` and op calls); §2.2 updated; §6.3 AGT 20 → 21.
**Shape of the change:** `blended.agent.op_call` binds JSON arguments against the op's type hints (the hints the schema came from) — unknown, missing and mistyped parameters fail loud, nested config dataclasses and paths convert — runs the op through `run.executor.execute_captured`, the one capture path `run_source_in_process` now also uses, and reports `stage_reached` (`execute` on failure, `done` on return). `dispatch_tool` routes op tools and refuses unregistered names before `import bpy`; a service tool with a schema but no branch is an assertion, not a fallthrough. `blended.stages` replaces five inline stage literals in `harness.py`.
**Measured:** pure op `middle_extent_m` runs end to end in the pure layer (door, binding, capture, stage). A binding failure reports no traceback (its frames are the harness's); an op's own exception keeps its traceback, bounded to `MAXIMUM_TRACEBACK_CHARACTERS`.
**Mistake recorded:** `a-pure-helper-under-a-package-whose-init-imports-the-harness-is-a-cycle` — the first placement of the stage module under `blended.run` made `harness → run.stages → run/__init__ → run.batch → harness` a cycle that the pure suite could not see (executor already imported) and six Blender agent-loop tests did; guarded by a fresh-interpreter import test.
**Pre-registration (OT-9):** appended before this shipped, as the backlog required.
**Layers:** pure 626 passed / 1 skipped / 1 xfailed; Blender 310 passed / 3 skipped.
**Commit:** `ace7618`.

---

## OT-5 Gate every scene-changing op call

**What:** An op tool whose return names an object MUST run the scene-state gate and the analyzer on that object and return the verdict, exactly as `run_python` does when `object_name` is given (AGT-3). An op that creates an intermediate (an operand about to be consumed by a boolean) MAY be marked `@op(gated=False)` in the signature contract, and the marker MUST appear in the schema description.
**Why:** OPS-20 already requires re-analysis after every CSG result. This makes the rule uniform and automatic.
**Amends:** AGT-3, OPS-20.
**Done means:** `tests/blender/test_agent_loop.py` asserts a gate verdict on every gated op result, and that an ungated intermediate is followed by a gated consumer before the turn can end with an answer.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_agent_loop.py::test_a_brief_reaches_gate_pass_with_op_tools_only` (a gate verdict on every gated op result, none on the ungated constructor or the material op), `::test_an_unresolved_intermediate_blocks_the_answer_until_resolved`, `::test_a_gate_failure_on_an_op_result_is_reported_at_gate` (two disjoint boxes unioned: `FAILED at gate`, 2 components), `::test_an_armature_is_gated_on_scene_state_only`, `::test_a_gated_op_on_a_missing_object_fails_at_locate`; `tests/pure/test_intermediates.py` (ledger debits before credits; refusal names creator; loop refuses then accepts; refusal counts against the budget); `tests/pure/test_ops_signature_contract.py` (marker rules: `@op(gated=False)` on a text-returning op is a violation, an ungated constructor must take `name`); `tests/pure/test_tool_schemas.py::test_the_three_unlinked_constructors_are_the_only_ungated_object_returners`, `::test_the_description_is_the_summary_and_the_return` (marker in the description).
**Spec:** AGT-3 amended (op tools gated through the same `gate_named_object`; marker; ledger refusal); OPS-20 amended (booleans return `ObjectName`, gated automatically); OPS-4 amended (`link_into_scene` idempotent); §2.2, §5.4.
**Shape of the change:** "whose return names an object" is machine-checkable: `blended.ops._objects.ObjectName = NewType("ObjectName", str)` is the return type of the 22 ops that create or modify an object (material and weight ops return datablock names and stay `-> str`). `@op(gated=False)` marks `add_box`, `add_cylinder`, `add_lathe` — the three constructors that return an unlinked object, where a gate would say "not linked" on every call. `blended.harness.GateVerdict` / `gate_object` is the ONE gate: scene state, then the analyzer for a mesh, scene state alone for an armature; `run_chunk` and `op_call` both read it, and `gate_summary_lines` renders it for both. `ToolOutcome` replaces the `(text, images)` tuple across the dispatch seam so the loop's `IntermediateLedger` learns what each call created and resolved without parsing text; an answer while the ledger is non-empty is refused with the pending objects named and counts against the budget.
**Measured:** planter_box via nine op calls: the two `link_into_scene` and two `boolean_difference` results carry `gate: PASS` and an `orient:` line, the four constructors and `assign_material` carry none. Contact sheets are NOT captured per op call (a sheet per call would be N renders per turn; `render_views` and `run_python` keep theirs). Tool-set fingerprint `t:959b39398cda`; assembled prompt `a10:673809a9e687` (the manifest now shows `-> ObjectName`).
**Observation for OT-13, not acted on:** in the recorded goldens the model forgot `link_into_scene` on the first attempt in three of five briefs; a constructor that links would remove that failure class and the ungated set with it.
**Mistake recorded:** `a-typing-object-compared-by-identity-breaks-under-dev-reload`.
**Layers:** pure 634 passed / 1 skipped / 1 xfailed; Blender 314 passed / 3 skipped.
**Commit:** `ab97d36`.

---

## OT-6 Plan integration

**What:** Generated op tools MUST be members of `PLAN_REQUIRED_TOOLS` (AGT-5) and MUST accept `plan_step`, so a scene-changing op without a declared plan is refused with the same text as `run_python`.
**Amends:** AGT-5, AGT-7.
**Done means:** `tests/pure/test_turn_plan.py` covers refusal and progress reporting for an op tool.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_turn_plan.py::test_plan_required_tools_are_run_python_and_every_scene_changing_op`, `::test_an_op_tool_without_a_plan_is_refused_with_the_same_text` (refusal text identical to `run_python`'s; dispatch never reached), `::test_a_reader_op_needs_no_plan`, `::test_an_op_tool_call_with_plan_step_reports_progress` (step event), `::test_dispatch_strips_plan_step_before_binding`; `tests/pure/test_tool_schemas.py::test_the_readers_are_the_only_plan_free_op_tools`, `::test_the_parameter_set_equals_the_signature` (plan_step on every action op tool, never required, never on a reader); `tests/pure/test_ops_signature_contract.py::test_a_reader_that_returns_an_object_name_is_a_violation`; `tests/blender/test_agent_loop.py::test_an_action_op_accepts_plan_step_and_the_op_never_sees_it`.
**Spec:** AGT-5 amended (`PLAN_REQUIRED_TOOLS` derived from the facade: `run_python` + every op not `@op(reads_only=True)`); AGT-7 amended (`PLAN_STEP_SCHEMA` defined once, carried by every plan-requiring tool, stripped before binding); §5.4.
**Shape of the change:** `@op(reads_only=True)` marks the ten inspection ops (four `*_report`, `deforming_bone_names`, `orientation_reading`, four pure orientation computations); the contract refuses a reader that returns an `ObjectName`. `PLAN_REQUIRED_TOOLS` is computed, not listed: 33 entries. The generator adds `plan_step` to every scene-changing op tool's schema; `dispatch_tool` removes it before `call_op` binds, so the op signature stays the only source of the op's arguments. The four identical hand-written `plan_step` schemas in the service tools now reference `PLAN_STEP_SCHEMA`.
**Measured:** tool-set fingerprint `t:8e3f56aff46c` (plan_step on 32 op tools). The assembled prompt fingerprint did not move.
**Layers:** pure 641 passed / 1 skipped / 1 xfailed; Blender 315 passed / 3 skipped.
**Commit:** `65bb719`.

---

## OT-7 Demote `run_python` to an escape hatch

**What:** `run_python` MUST require a non-blank `reason` parameter naming what the ops vocabulary could not express. The working agreement MUST gain a revision (one hunk, PRM-5) stating that construction goes through op tools and `run_python` is for what they cannot do. Each `run_python` call MUST be transcribed as a `candidate_op` record (see OT-8).
**Why:** The hatch has to stay (a vocabulary that cannot be exceeded cannot grow), but every use must be a measured signal, not a silent default.
**Amends:** AGT-3; adds `PRM-15` (prompt revision registered with hypothesis before the run, PRM-4).
**Done means:** `tests/pure/test_agent_dispatch.py` refuses `run_python` without `reason`. `validate_revisions()` passes with the new revision. The revision's hypothesis: *escape-hatch calls per gate-passing brief fall below 1.0 on the five briefs within three paired rolls.*

**Closed:** 2026-09-10 — with the hypothesis PENDING measurement (recorded on revision 12 with `outcome=""`; the closing rule's outcome requirement applies to OT-9–OT-11, and OT-7's Done means is the refusal test plus a healthy registry).
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_run_python_without_a_reason_is_refused_before_bpy` (missing, blank, whitespace and non-string reasons), `::test_run_python_with_a_reason_reaches_bpy`, `::test_the_run_python_schema_requires_the_reason`; `tests/pure/test_prompt_templates.py::test_the_revision_history_is_disciplined` (`validate_revisions() == []` with v12), `::test_each_revision_changes_exactly_one_place[12]`.
**Spec:** AGT-3 amended (`run_python` is the escape hatch; `reason` required, refused at the door; outcome carries reason and source hash); PRM-15 added; §2.2 run_python row; §5.4; §6.3 PRM 14 → 15.
**Shape of the change:** the `run_python` schema requires `reason` and its description opens with ESCAPE HATCH; `dispatch_tool` refuses a blank reason before `import bpy` with `RUN_PYTHON_REASON_REFUSAL`; a reasoned call's `ToolOutcome` carries `hatch_reason` and `source_sha256` (12 hex) — the candidate_op record's inputs, written into the transcript by OT-8. Working agreement v12 differs from v11 by exactly one hunk (the opening paragraph: a step is an op-tool call, or a chunk only when no op fits; the hatch must name what was missing) and is registered with the backlog's hypothesis; `ACTIVE_PROMPT_REVISION` stays at the pin (10) until measured.
**Measured:** hunks v11 → v12: `['replace lines 2-5 -> 2-11']`. A first draft that also reworded the loop's step 1 measured two hunks (the blank line between them is an equal line to difflib) and was cut back per PRM-5. Tool-set fingerprint `t:cc2df4bef820`; assembled prompt fingerprint unchanged (v10 is still active).
**Not done here, by design:** the candidate_op record itself is OT-8's transcript schema; the hypothesis outcome is OT-12's mining over v2 transcripts.
**Layers:** pure 645 passed / 1 skipped / 1 xfailed; Blender 315 passed / 3 skipped.
**Commit:** `70d80d8`.

---

## OT-8 Structured transcript

**What:** `TRANSCRIPT_SCHEMA_VERSION` MUST bump to 2. Every tool event MUST record: tool name, validated arguments, `plan_step`, gate verdict and analyzer fields when gated, `stage_reached`, wall time, and for `run_python` the `reason` and source hash. `IterationRecord` MUST carry the op-call sequence, not only the `run_python` sources (CNV-11 replay must still work from it).
**Why:** This is what turns normal use into a dataset. Free-text transcripts are not trainable and not minable.
**Amends:** AGT-17, CNV-11.
**Done means:** `tests/pure/test_transcript.py` round-trips a v2 record; `scripts/replay_iteration.py` rebuilds a scored iteration from an op-call sequence with no `run_python` present.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_tool_event.py::test_a_tool_event_round_trips_through_json`, `::test_a_v1_payload_is_refused_not_misread`, `::test_the_loop_emits_one_structured_event_per_dispatched_call` (validated arguments, plan step, stage, gates, wall time; ordered after the text the model reads), `::test_a_refused_call_is_recorded_as_refused`, `::test_the_hatch_record_carries_reason_and_hash`; `tests/pure/test_transcript.py::test_schema_two_stores_the_tool_event_under_data`; `tests/blender/test_replay_op_calls.py::test_an_op_call_sequence_replays_to_a_scored_pass` (twelve recorded calls, no `run_python`, three non-changing service calls skipped, form gate PASS), `::test_a_replay_that_builds_nothing_is_loud`; the five golden replays still pass through the same `replay_record`.
**Spec:** AGT-17 amended (schema 2, `tool_event`, `data`, `IterationRecord.tool_events`); CNV-11 amended (replay from the recorded call sequence, op calls through `call_op`); §2.5 iteration-log row; §5.4.
**Shape of the change:** `agent.tool_event.ToolEvent` (schema 2) is emitted by the loop on the `tool_event` channel after every dispatched or refused call, with the wall time measured around the dispatch. `ToolOutcome` now carries `ok`, `stage_reached`, `validated_arguments` and `gates`, and every service-tool branch returns one (the `(text, images)` tuple is gone from the service layer too); `harness.gate_verdict_json` / `harness_result_gate_json` give `run_chunk`'s gate and an op call's gate the same JSON shape. `ChatTranscript` schema 2 stores the event decoded under `data` and keeps it out of the Markdown; the addon lists `tool_event` as state-only. `run_agent_task.py` collects the sequence into `IterationRecord.tool_events`. `replay.calls_from` reads every recorded call; `replay_record` re-executes `run_python` sources and re-binds op calls through `call_op` — one read path over `tool_calls` for pre-OT-8 records and new ones alike, so the goldens needed no migration.
**Decision:** `tool_calls` (the raw call text the loop emitted) stays the replay source; `tool_events` is the measured record. A migration of the 67 historical records into `tool_events` was considered and rejected: it would have manufactured stage, gate and timing fields that were never measured.
**Layers:** pure 651 passed / 1 skipped / 1 xfailed; Blender 317 passed / 3 skipped.
**Commit:** `9a60a55`.

---

## OT-15 Schema-driven `search_ops`

**What:** `search_ops` MUST return the generated schema for each hit, not only the signature string, capped at `MAXIMUM_SEARCH_RESULTS`.
**Why:** Small models need the argument shape at the moment of use, not in the system prompt.
**Amends:** AGT-18.
**Done means:** `tests/pure/test_agent_dispatch.py` asserts schema presence in results.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_dispatch.py::test_search_ops_returns_each_hit_with_its_generated_schema` (schema JSON present per hit; cap honoured), `::test_search_ops_spans_the_underscore_and_word_order` (three spellings of one op; a miss and an empty query are not ok); `tests/blender/test_transform_ops.py` search tests (the iteration-4 queries, narrowing by `schema:` line count).
**Spec:** AGT-18 amended.
**Shape of the change:** `search_ops` is a pure function over `OP_TOOL_SCHEMAS` (name, module, generated description) dispatched above `import bpy`; each hit prints the tool's description and its parameters schema as compact JSON; hits are ranked name-match first, shorter name first, facade order after — measured need: with facade order alone, "assign material" returned `assign_image_texture_material` first. The manifest-text search path is gone.
**Layers:** pure 653 passed / 1 skipped / 1 xfailed; Blender 317 passed / 3 skipped.
**Commit:** `0967110`.

---

## OT-16 Enforce retry and turn caps in the loop

**What:** The loop MUST enforce a named per-turn cap on consecutive gate failures on the same object (`MAXIMUM_GATE_FAILURES_PER_OBJECT`) and stop the turn with a contact sheet and a message, making the working agreement's "three honest attempts" code rather than prose.
**Why:** Closes AGT-20 / spec §7.2. With op tools, a retry is cheap and precise, so a cap no longer costs capability.
**Amends:** AGT-20 becomes verified.
**Done means:** `tests/blender/test_agent_loop.py` trips the cap with a builder that always fails the gate.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_agent_loop.py::test_a_builder_that_always_fails_the_gate_trips_the_cap` (a chunk whose applied array leaves two islands fails the gate every time; the turn stops after three with `Bad_sheet.png` rendered and three tool results, not six); `tests/pure/test_turn_caps.py::test_three_consecutive_gate_failures_stop_the_turn_with_a_sheet`, `::test_a_passing_verdict_resets_the_count`, `::test_queued_calls_after_the_cap_get_a_not_run_result`.
**Spec:** AGT-20 rewritten from gap to requirement (verified); §7.2 gap row removed; §5.4 `MAXIMUM_GATE_FAILURES_PER_OBJECT`; §6.3 AGT unverified 2 → 1.
**Shape of the change:** the loop keeps a per-turn count of consecutive non-`done` gate verdicts per object, read from `ToolOutcome.gates` (so `run_python` with `object_name` and every gated op tool count alike); at `MAXIMUM_GATE_FAILURES_PER_OBJECT` it renders the object through the same dispatch seam (`render_views`), answers the model's queued calls with `GATE_CAP_TOOL_RESULT`, and returns `GATE_CAP_ANSWER` naming the object, the count and the last verdict. `_answer_pending_tool_calls` is now shared by cancel and the cap, and positional rather than id-based — measured: a scripted call with no id was answered twice under the id-based rule.
**Layers:** pure 656 passed / 1 skipped / 1 xfailed; Blender 318 passed / 3 skipped.
**Commit:** `be4c33f`.

---

## OT-17 Token budget per turn

**What:** `TurnCost` MUST be compared against a named `MAXIMUM_TURN_TOKENS` and the turn MUST stop at the next seam when exceeded, reported as text (same shape as the tool-call budget exhaustion, AGT-9).
**Why:** Cost is measured, not bounded (spec §7.2). Op tools shrink per-call tokens, which makes a budget that used to be unreachable reachable.
**Done means:** `tests/pure/test_agent_cancel.py` covers the seam.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_agent_cancel.py::test_the_turn_stops_at_the_seam_when_the_token_budget_is_exceeded` (reply 1 runs, reply 2 takes the turn over budget: its calls answered `TOKEN_CAP_TOOL_RESULT`, the turn ends with the exhaustion text), `::test_an_answer_over_budget_is_still_returned`, `::test_the_budget_is_per_turn_not_per_session`.
**Spec:** AGT-9 amended; §7.2 gap row removed (both §7.2 loop-limit rows are now closed); §5.4 `MAXIMUM_TURN_TOKENS`.
**Shape of the change:** `MAXIMUM_TURN_TOKENS` = 750,000, derived from measurement (24 calls × 25,851 tokens measured per call on the Claude Code lane ≈ 620k, plus a fifth). The loop snapshots `client.spent` at turn start and, at the seam after every reply, compares tokens billed since (input including cache reads and writes, plus output); a reply that wants more tool calls over budget has them answered `TOKEN_CAP_TOOL_RESULT` and the turn ends with `TOKEN_CAP_ANSWER`, the same shape as the tool-call exhaustion; a reply that already answers ends the turn whatever it cost. Every scripted client in the pure tests now carries `spent` like the real ones. `_answer_pending_tool_calls` finds the reply being closed as the LATEST occurrence in history — measured: a scripted client replaying one dict object twice made the first-occurrence search skip the pending calls.
**Layers:** pure 659 passed / 1 skipped / 1 xfailed; Blender 318 passed / 3 skipped.
**Commit:** `2922411`.

---

## OT-14 Selection as a first-class parameter type

**What:** Ops that act on a subset of geometry MUST accept a typed `EdgeSelector` / `FaceSelector` (by dihedral angle, by material slot, by axis-aligned face normal, by name pattern) rather than indices.
**Why:** Vertex indices are not something a model can reason about from a manifest; selectors are. This is the difference between an op vocabulary a 7B model can drive and one it cannot.
**Done means:** selector round-trips through the schema generator (OT-3) with an enum of selector kinds; `tests/blender/test_selectors.py` covers each kind against a fixture mesh.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_selectors.py` — `::test_edge_selectors_resolve_each_kind`, `::test_face_selectors_resolve_each_kind`, `::test_vertex_selectors_resolve_each_kind` (every kind against one fixture box: 12 edges / 6 faces / 8 vertices with a marked top face and a `top_ring` group), `::test_weights_take_a_selector_not_indices`, `::test_a_selector_dispatches_as_a_tool_argument` (JSON in, enum validated, indices out; an unknown kind is an `ArgumentError`); `tests/pure/test_tool_schemas.py::test_a_selector_round_trips_as_an_object_with_an_enum_of_kinds`, `::test_the_select_ops_are_readers_with_selector_parameters`.
**Spec:** OPS-22 added; §5.5 selector constants; §6.3 OPS 21 → 22.
**Shape of the change:** `blended.ops.selectors` defines `EdgeSelector` (dihedral angle, material slot, vertex-group name pattern, all), `FaceSelector` (axis-aligned normal, material slot, vertex-group pattern, all) and `VertexSelector` (vertex-group pattern, height range, all) as frozen dataclasses whose `kind` is a `Literal`; `__post_init__` refuses a nonsensical selector. The schema generator maps `Literal` to an enum and a dataclass default to its fields; the binder checks enum membership. `select_edges` / `select_faces` / `select_vertices` are reader ops on the facade; `assign_vertex_group_weights` takes a `VertexSelector` instead of indices (the only subset op that took indices). "By name pattern" is read as a full-match regex over vertex-group names, stated once in the module docstring.
**Measured:** 45 op tools; tool-set fingerprint `t:2614a1448ba7`; assembled prompt `a10:107d5c63f0b0` (the manifest gained the selectors module and three config objects).
**Layers:** pure 678 passed / 1 skipped / 1 xfailed; Blender 323 passed / 3 skipped.
**Commit:** `36afbd7`.

---

## OT-12 Missing-op mining

**What:** `scripts/mine_candidate_ops.py` MUST read v2 transcripts and iteration logs, group `run_python` events by `reason` and by normalized source shape, and emit a dated markdown report ranking candidate ops by frequency × gate-pass rate.
**Why:** Vocabulary growth should be driven by measured demand, not guessed. Every hatch use is a vote.
**Done means:** the script is self-checking (fails on a v1 transcript rather than silently reading nothing) and produces a report on the existing five-brief runs after OT-8 lands.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_candidate_ops.py::test_a_record_without_tool_events_is_refused_not_read_as_empty` (v1 records and schema-1 transcripts refused by name), `::test_a_reason_is_one_spelling_and_a_shape_ignores_literals`, `::test_the_ranking_is_frequency_times_gate_pass_rate`, `::test_a_refused_hatch_call_is_not_a_vote`; the script refuses the un-filtered log (`iteration 1 ... predates OT-8`) and produced the report on the post-OT-8 runs.
**Spec:** CNV-14 added; §2.4 `make mine-ops`; §6.3 CNV 13 → 14.
**Shape of the change:** `blended.evaluate.candidate_ops` (pure) groups hatch events by normalized reason and by source shape (the dotted API the chunk called, facade imports included, literals and builtins excluded), ranks by frequency × gate-pass rate, and reports hatch calls per gate-passing brief — the v12 hypothesis metric. `scripts/mine_candidate_ops.py` / `make mine-ops FROM=68` write a dated Markdown report under `docs/candidate_ops/`.
**Measured (the report):** iterations 68–73, five gate-passing briefs' worth of runs on v12: 10 hatch calls on 68–71 plus 0 on 73; 3.00 hatch calls per gate-passing brief (hypothesis < 1.0: NOT met on this roll — one roll, no claim). Ranked candidates: rename an object (4 calls, 4/4 gate-passing), world-bounds reader (5 chunks, 4/4), mark UV seams by selector, lathe profile from rib parameters; two "placeholder" reasons show the reason field is gameable. The strongest finding is not a missing op: `location_m` was read as a center in both planter runs because the base convention never reaches the model (summary line only). All recorded on OT-13.
**Layers:** pure 678 passed / 1 skipped / 1 xfailed; Blender 323 passed / 3 skipped.
**Commit:** `2e7e2ac`.

---

## OT-11 Chat E2E on op tools

**What:** `make chat-e2e` scenarios MUST pass with `run_python` disabled entirely, for every scenario the vocabulary claims to cover (object, material, iterative edit at minimum; rig, weights, animation as the facade covers them).
**Why:** The E2E suite is the only headless proof that the surface is usable from the UI (NFR-18).
**Done means:** a `--no-hatch` flag on `scripts/chat_e2e.py`; scenarios that require the hatch are listed by name in the output as missing-op evidence for OT-12.

**Closed:** 2026-09-10.
**Gating tests:** `make chat-e2e ARGS="--no-hatch"` on 2026-09-10 (v12, Claude Code lane): 6/6 scenarios passed — object 8 tool calls, rig 10, weights 9, animation 8, material 8, iterative 12 — zero hatch attempts, no disabled-tool refusal, `MISSING-OP EVIDENCE (for OT-12): none`; transcripts under `outputs/chat_e2e/20260910-165504/`. `tests/pure/test_turn_caps.py::test_a_disabled_tool_is_neither_offered_nor_dispatched` covers the mechanism.
**Spec:** AGT-22 added (session `disabled_tools`, the loop refusal, the E2E flag and its listing); §2.4 `make chat-e2e ARGS="--no-hatch"`.
**Shape of the change:** `AgentSession.disabled_tools` withholds a tool from the schemas offered to the model and refuses a call to it with `DISABLED_TOOL_REFUSAL` (counted, recorded as a refused tool event). `scripts/chat_e2e.py --no-hatch` sets it for `run_python`, counts hatch attempts per scenario, and prints the scenarios that failed or reached for the hatch as missing-op evidence; its default revision is now v12.
**Measured beside it:** v12's outcome is recorded on the revision as measured once — the E2E passes without the hatch, while the five-brief roll sits at 3.00 hatch calls per gate-passing brief and the planter fails the form gate on the `location_m` convention (OT-13's first evidence).
**Layers:** pure passing with the revision outcome filled (below); Blender 323 passed / 3 skipped (unchanged since OT-14).
**Commit:** `485917e`.

---

## OT-13 First vocabulary expansion, from the five briefs

**What:** Implement the ops the five briefs (`planter_box`, `three_leg_stool`, `uv_crate`, `ribbed_column`, `crate_with_lid`) need to reach gate-pass with zero hatch calls. Expected from the brief contents, to be confirmed by OT-12: hollow-out with named wall thickness, bevel by edge selector, radial array, inset faces, mirror across a named plane, edge-selector primitives (by angle, by material, by name pattern).
**Why:** These are the briefs the convergence loop and the goldens already exercise; closing them first means every downstream instrument keeps working.
**Amends:** adds one `OPS-n` row per op, each with a fixture that trips its validation (GATE-18 discipline applied to ops).
**Done means:** `make converge` on each brief reaches structural + form gate pass with `run_python` disabled.
**Evidence 2026-09-10 (v12, Claude Code lane, iterations 68–73; report `docs/candidate_ops/2026-09-10-candidate-ops.md`):**
- Hatch calls per gate-passing brief: 3.00 over 3 (stool 6, uv_crate 1, column 2); planter 0 on its re-run (73) but it failed the form gate.
- Top candidate by reason and by gate-pass rate: **rename an object** (4 calls, 4/4 gate-passing) — `boolean_union` keeps the target's name and the brief wants `Stool`. Cheapest op in the list.
- Top by source shape: **read world bounds** (5 measurement chunks, 4/4 gate-passing) — the writer wants both operands' world boxes when a boolean says "no overlap".
- **Mark UV seams by edge selector** (uv_crate), **compute a lathe profile from rib parameters** (ribbed_column, 2 calls: the tool call cannot take a computed list), and "placeholder" reasons (2 on the stool: the reason field is gameable; count them).
- **Measured twice, not a missing op: `location_m` read as a CENTER** (68 and 73 both built the planter at base z 0.125 and failed the floor probe). Mechanism: `add_box`'s base-at-z convention lives in the docstring BODY, and both the manifest and the generated tool description carry only the summary line. Fix belongs here: either the parameter name carries the convention (`base_center_m`, which breaks every recorded golden source and costs a re-converge) or the schema carries the convention sentence. Decide by measurement on the planter.
- Cost of the surface on this lane: 58k tokens per call with 50 tools vs 26k with 8 (OT-17 correction); run 72 (crate_with_lid) died on `error_max_structured_output_retries` with the 50-variant envelope — one occurrence, not yet a cause.
- **First fix, measured (commit `fa3b1e5`, iteration 74):** `add_box`'s summary line now states BASE at `location_m[2]` (no rename). The planter then passed both deterministic gates on op tools alone: 14 calls, 0 hatch calls, base_z +0.0000, $0.30. One run; the pixel gate reports "the render moved" against golden 66 as any fresh run does.

**Closed:** 2026-09-10.
**Gating runs (`make converge ... ARGS="--no-hatch"`, v12, Claude Code lane, `run_python` withheld):** planter_box 75 (14 calls), three_leg_stool 76 (51 calls, three turns), ribbed_column 78 (7 calls), crate_with_lid 79 (15 calls), uv_crate 80 (11 calls) — every one passed the structural AND form gates with zero hatch calls, by construction. uv_crate's first sample (77) failed: seams on every edge above 30° after the bevel gave 26 islands against the cap of 12, seven `select_edges` probes and three rebuilds spent the 24-call budget, and the last box was left unlinked. The second sample used seams then unwrap and passed with 6 islands and 0 overlaps.
**Gating tests:** `tests/blender/test_vocabulary_ot13.py` (each op and the fixture that trips it: `NameTaken`, an empty new name, `NoEdgesSelected`; all three dispatch as tools with a gate verdict on the object-returning ones); `tests/blender/test_selectors.py` (OT-14) for the selector kinds the seam op uses.
**Spec:** OPS-23 (`rename_object`), OPS-24 (`world_bounds`), OPS-25 (`mark_uv_seams`); §2.4 `--no-hatch`; §6.3 OPS 22 → 25.
**What was built, and why these and not the expected list:** the backlog expected hollow-out, bevel by selector, radial array, inset, mirror. The measured demand (OT-12) was different: the stool needed to rename a boolean's result (4/4 gate-passing hatch calls), the writer wanted world bounds when a boolean reported no overlap (5 chunks), and the crate set seams through bmesh. Those three became ops. The `location_m` misread (planter, twice) was fixed by stating the base convention in `add_box`'s summary line (`fa3b1e5`), which is all the manifest and schema carry — measured true on iteration 74 and again on 75. Nothing from the expected list was needed to pass the five briefs; each stays unbuilt until a run asks for it.
**Costs, measured:** the five passing no-hatch runs billed $0.3–2.3 each on this lane. 75 briefs' worth of runs today; the account's 7-day window was at 62% before them.
**Observations for the next roll, not acted on:** `select_edges` used as a probe loop (seven calls in 77) suggests the reader should return what the edges ARE (their dihedral angles, count) rather than indices; the structured-output failure on run 72 has one occurrence.
**Layers:** pure 690 passed / 1 skipped / 1 xfailed; Blender 328 passed / 3 skipped.
**Commit:** `709dc33`.

---

## OT-20 The bench bridge carries op calls

**What:** `scripts/run_3dcode_instance.py` MUST emit the standalone script from the recorded call SEQUENCE — every executed `run_python` chunk AND every successful op-tool call, in order, the op calls as `from blended.ops import <op>` plus the call with its validated arguments (the encoding `evaluate.replay.calls_from` already reads) — so the bench re-bakes what the agent built. A chunk or op call whose result was not OK is excluded, as today.
**Why:** the bridge predates the op tools; a roll that drops 37 op calls from a script measures a different program than the one the gates passed. Found by reading OT-9's roll 1 before scoring it.
**Amends:** BEN-1 (the bridge), CNV-11 (replay and the bridge read one encoding).
**Done means:** `tests/blender/test_bench_bridge.py` builds a brief with op calls only, runs the bridge's script assembly, executes the emitted script in a fresh scene, and the form gate passes on the re-baked object; a run with zero op calls emits byte-identical output to today's.

**Closed:** 2026-09-10.
**Gating tests:** `tests/blender/test_bench_bridge.py::test_an_op_built_brief_re_bakes_from_the_standalone_script` (the planter through the real dispatcher: 13 calls, 9 op calls and 1 chunk included, 1 raising boolean excluded, the emitted script re-executed in an empty scene passes the form gate; `plan_step` absent from the script); `tests/pure/test_bench_bridge.py` (inclusion by stage, not text; op calls emitted in order through the binder; a chunks-only record keeps the chunk format byte for byte; nothing ran means no epilogue).
**Spec:** BEN-1 amended; CNV-11 notes the shared rule.
**Shape of the change:** `blended.evaluate.bench_bridge` owns the rule and the assembly: `RecordedCall(tool_name, validated arguments, stage_reached)`; a call is included iff its stage is past `execute` — the same fact for a chunk and an op call, replacing the text-prefix heuristic `chunk_executed`; an op call is emitted as `_op(name, {validated arguments})` and bound at bake time through `bind_arguments`, so a `tuple[BoneSpec, ...]` or an `EdgeSelector` is rebuilt by the one converter the loop used. The runner records every dispatched call and reports `n_op_calls_included`. The chunk body and the epilogue are byte-identical to the previous assembly; the prelude grew the helper.
**Not byte-identical, stated:** the Done means asked for identical output on a record with zero op calls; the prelude now carries the `_op` helper on every script, so identity holds for the chunk section and the epilogue, not the prelude.
**Layers:** pure 694 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `de44184`.

---

## OT-21 The bench chain bakes before it scores

**What:** the sweep chain MUST run the bench's own bake (`/Users/ladvien/3dcodebench/.venv/bin/python core/render.py --model <dir> --results-root <root> --blender <Blender>`) between the sweep and the scorers, and MUST refuse to score a model dir whose instances lack `renders/render_log.json`.
**Why:** `executability.py` and `shape_chamfer.py` read what the bake wrote; without it they report 0/20 with a fingerprint that reads like a model failure.
**Done means:** `outputs/bench/logs/*_chain.sh` carry the step; a dry run on roll 1's existing scripts produces 20 render logs; the scorer step is guarded.

**Closed:** 2026-09-10.
**Gating runs:** `scripts/bake_3dcode.py` on roll 1's 20 existing scripts: 20 render logs, render statuses `{OK: 13, ERR_EXEC: 7}`, GLBs for the 13 that executed, exit 0 "safe to score" — the 7 that did not execute are the benchmark's own executability number for the pre-OT-20 bridge, not a bake defect. One fresh instance (AquariumTank) through the OT-20 runner on the cloud lane, then baked: `OK_AGENT_DONE` in 690 s, one `_op(` line in the script, re-bake status OK, 1 mesh, 4 views, GLB 33.6 KB.
**Spec:** BEN-11 added; §2.4 `scripts/bench_chain.sh`; §6.3 BEN 10 → 11.
**Shape of the change:** `scripts/bake_3dcode.py` runs the bench's `core/render.py` and `core/export_glb.py` for a model dir and then refuses (exit 2, instances named) unless every scripted instance has its render log and, where the log says the script executed, its GLB. `scripts/bench_chain.sh` is the committed roll template: sweep → bake → executability → shape_chamfer → diagnose, the scorers gated on the bake's exit; the operational chains under `outputs/bench/logs/` are regenerated from it for OT-27.
**Found by the smoke, fixed here:** (1) the first guard demanded a GLB from a script that failed to execute — the benchmark's failure semantics, restored; (2) `--overwrite` had reached only the render orchestrator; (3) the emitted script's `blended` imports resolved against the installed `blended_agent` addon's bundled copy, because the bench bakes without `--factory-startup` — the prelude now evicts `blended*` from `sys.modules` first; recorded as `the-host-blender-already-holds-an-older-blended`.
**Layers:** pure 698 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `3c76b39`.

---

## OT-23 Measure the composition of a call, per lane

**What:** `scripts/context_composition.py` MUST split one call's tokens into working agreement, manifest sections, tool schemas, scene block and history, per lane, using each lane's own tokenizer where one is reachable (bmb's `/tokenize`) and the transport's `usage` otherwise, and write the row into the spec's measured-state table.
**Why:** everything in this phase is sized by this number; `TurnCost` measures the total only.
**Done means:** the script is self-checking (the parts sum to the assembled whole within the tokenizer's join error) and its output is in the spec.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_context_budget.py::test_every_part_is_a_verbatim_substring_and_the_remainder_is_small`, `::test_the_composition_sums_and_names_both_lanes`, `::test_an_unreachable_tokenizer_refuses_instead_of_estimating`, `::test_the_spec_row_is_written_once_and_replaced_in_place`; the live run wrote the "Context per call" row into the spec's measured-state table.
**Spec:** the row; §2.4 `scripts/context_composition.py`.
**Measured (bmb `qwen3.8-27b` tokenizer, wire encoding, v12, 56 tools):** system prompt 7,569 — working agreement 1,770, conventions 228, manifest operations + config objects 3,074, gate fields + budget 291, drift catalog 2,148, scaffolding 58; tools 9,245 on the OpenAI/Ollama lanes (op tools 7,904, service 1,342) and 10,485 as the Claude Code envelope with its protocol note; **static per call 16,814 / 18,054** before scene and history. The earlier 15.0k figure used compact JSON; the wire uses the default separators, which cost 1.8k more.
**Shape of the change:** `blended.agent.context_budget` splits the assembled prompt into verbatim substrings plus a measured scaffolding remainder, renders the tool set the way each lane sends it, counts with an injected tokenizer (`bmb_tokenizer` binds to llama-server's `/tokenize` and raises `TokenizerUnreachable` rather than estimate), and writes one idempotent spec row.
**Layers:** as OT-21.
**Commit:** `cc28cf1` (OT-23 code landed with OT-21's commit `3c76b39`).

---

## OT-22 Context preflight and truncation as failures

**What:** every lane MUST know its model context (`ModelConfig.context_tokens`: 65,536 for bmb's `qwen3.8-27b`, `num_ctx` for Ollama-native, the CLI's for Claude Code) and the loop MUST refuse to send a request whose prompt tokens plus tool schema plus the reply ceiling exceed it, naming the sizes; a transport reply that reports truncation MUST be an error, never a result. The per-request ceiling on the llama-swap lane (`LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` = 900) MUST be measured against a real 27B turn and re-derived the way the token budget was.
**Why:** the one place the fail-loud rule is missing. A 65k-context lane holding 15k of static prefix reaches its limit inside a long turn, and the OT-10 roll's first instance died at the request ceiling instead.
**Amends:** NFR-13; adds `AGT-23`.
**Done means:** `tests/pure/test_context_preflight.py` refuses an oversize prompt with the sizes named and passes one that fits; a fake transport reporting `truncated` is an error.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_context_preflight.py::test_context_tokens_come_from_each_lanes_own_number`, `::test_the_estimate_is_the_measured_ratio`, `::test_preflight_refuses_with_every_number_named`, `::test_a_cut_reply_is_an_error_on_every_wire` (finish_reason/done_reason length, `truncated`, prompt larger than the context), `::test_the_loop_refuses_before_calling_the_model` (a 32k lane with 16k reserved and ~20k of history: the model is never called, the answer names the sizes), `::test_an_unmeasured_lane_is_reported_once_and_still_runs`.
**Spec:** AGT-23 added; NFR-13 amended; §5.4 (`LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS`, `CONTEXT_TOKENS_BY_MODEL`, `CLAUDE_CODE_CONTEXT_TOKENS`, `CHARS_PER_TOKEN_ESTIMATE`); §6.3 AGT 22 → 23; §7.2 gains the unmeasured-lane row.
**Shape of the change:** `ModelConfig.context_tokens` reads the served `-c` per model from bmb's llama-swap config (65,536 for `qwen3.8-27b`, 32,768 for the 32B and smaller), `num_ctx` on the Ollama lanes, the documented 200k on the Claude Code lane, and `None` for a model with no measured entry. `blended.agent.context_preflight` estimates the request at the measured 3.8 characters per token, refuses at the seam before the model call when the estimate plus the reserved completion exceeds the context (every number in the message), reports an unmeasured lane once per turn on a `preflight` event, and turns a cut reply into an error on both wire protocols and both streamed paths (the assemblers now carry `finish_reason` / `done_reason`).
**Measured (bmb `qwen3.8-27b`, one real full-prefix request, 16,997 prompt tokens):** cold 226.1 s — prefill 142.9 s (119 tok/s), 711 completion tokens in 67.7 s (10.5 tok/s); warm 17.6 s with the prefix read from llama-server's cache in 0.3 s. The request ceiling is re-derived from that: cold load ~240 s + prefill 143 s + 16,384 completion tokens at 10.5 tok/s ≈ 1,943 s → `LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS` = 2000 (was 900, which killed OT-10's first instance mid-generation). The model's first move on that request was `declare_plan`.
**Layers:** pure 704 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped.
**Commit:** `6ef543c`.

---

## OT-24 One description per op: drop the manifest's ops section

**What:** the manifest MUST stop rendering the operations section into the prompt (3,074 tokens); the generated schema is the one description of each op. Conventions, gate fields, budget knobs and the drift catalog stay. Register the prompt change with a hypothesis before the run.
**Why:** "nothing is written twice" applies to the context window as much as to source.
**Amends:** PRM-1, PRM-2; a new prompt revision is NOT needed (the `.j2` does not change) but the assembled fingerprint moves and is re-pinned.
**Done means:** the five briefs still pass with the hatch withheld; `tests/pure/test_manifest.py` asserts no op signature appears in the assembled prompt.

**Closed:** 2026-09-10.
**Gating runs and tests:** `make converge ... REVISION=14 ARGS="--no-hatch"`: planter 81 (13 calls), stool 86 (56 calls, three refinements pass), uv_crate 83 (10), column 84 (8), crate_with_lid 85 (21) — all FORM PASS, zero `search_ops` calls; `make chat-e2e ARGS="--no-hatch --revision 14"` 6/6 in 46 tool calls. `tests/pure/test_prompt_templates.py::test_the_prompt_describes_no_op_twice`; `::test_each_revision_changes_exactly_one_place[13]`, `[14]`; `tests/pure/test_refinement_missing_part.py`.
**Spec:** PRM-1 amended (the operations section leaves the prompt), PRM-2 verification; §5.4 pins row; the "Context per call" row re-measured on v14.
**Shape of the change:** `build_system_prompt` renders conventions plus the manifest's gate-fields and drift-catalog slice, never the operations section; `include_operations` is gone and the manifest headings are asserted, not searched for with a silent -1. Working agreement v13 (one hunk: "the rest of your tool list") and v14 (one hunk: the tool-discipline bullet now points at the tool list and `search_ops`) are registered with hypotheses and measured outcomes; `ACTIVE_PROMPT_REVISION` stays at the pin. The composition script measures the prompt without the section.
**Measured:** system prompt 7,569 → 4,482 tokens on bmb's tokenizer (−3,087); static per call 16,814 → 13,727 (OpenAI/Ollama) and 18,054 → 14,967 (Claude Code); assembled fingerprint moved to `a10:c68237772de1`.
**Found by the first stool run (82), fixed here:** the driver died in `RefinementOutcome._measured` when a refinement turn left the part named `Seat` — a missing dimension now reads "missing (part not found)" in the summary and counts as a failure instead of losing the record.
**Layers:** pure 713 passed / 1 skipped / 1 xfailed; Blender 329 passed / 3 skipped (both by exit code).
**Commit:** `75ec2c9`.

## OT-25 Progressive disclosure of op tools

**What:** the loop MUST offer the service tools, the readers and a CORE set of op tools on every call, and expose the rest through `search_ops` (which already returns the schema). The core set MUST be derived from `tool_events` frequency across gate-passing runs, never listed by hand, and the offered set MUST be fingerprinted per turn so the pin tests see a change.
**Why:** 15 of 48 ops carried all five briefs; the other 33 cost 4k+ tokens per call on every lane and a `oneOf` variant each on the CLI lane.
**Hypothesis to register before the roll:** executability on the local lane rises, per-call tokens fall below the 8-tool baseline (25,851 on the CLI lane), and hatch calls per gate-passing brief do not change.
**Done means:** `tests/pure/test_tool_disclosure.py` covers the derivation, the per-turn fingerprint and a search-then-call round trip; the five briefs pass no-hatch on the disclosed set.

**Closed:** 2026-09-10.
**Gating runs and tests:** `make converge ... REVISION=14 ARGS="--no-hatch"` on the disclosed surface: planter 87 (14 API calls), uv_crate 89 (15), column 90 (8), crate_with_lid 91 (9), stool 92 (38; three refinements pass) — all FORM PASS, zero hatch calls, 12 `search_ops` calls for 11 undisclosed ops; the stool's first run 88 FAILED its third refinement at the 24-call turn cap (recorded in the pre-registration outcome). `make chat-e2e ARGS="--no-hatch --revision 14"` 6/6 in 56 tool calls (46 on the whole set). `tests/pure/test_tool_disclosure.py` (8 tests: derivation; generated module equals the derivation from the real log; offered set seen by the client; a withheld tool leaves it; undisclosed op dispatches after `search_ops` with the fingerprint on every event; envelope catch-all; module round trip), `tests/blender/test_agent_loop.py::test_an_undisclosed_op_found_by_search_ops_runs_through_the_real_dispatcher`.
**Spec:** AGT-1 (the offered set, the generated module, the fingerprint on events and records), AGT-14 (envelope from the offered set + catch-all variant; preflight sends the same), §2.5 `src/blended/agent/core_tools.py`, §5.4 `MINIMUM_BRIEFS_USING_OP`, the scripts table (`scripts/derive_core_tools.py`), the "Context per call" row re-measured on the offered set.
**Shape of the change:** `tool_disclosure.py` derives the core (scene-changing ops used successfully in ≥ 2 gate-passing briefs) and writes it as the generated module `core_tools.py` (`CORE_OPS`: add_box, add_cylinder, assign_material, boolean_difference, link_into_scene, rename_object, snap_base_to_ground); `AgentSession.offered_tools()` = service + readers + core − withheld, fingerprinted per turn and stamped on every `ToolEvent` and the `IterationRecord`; the door and the binder are untouched, so any facade op runs by name once `search_ops` has shown it; the Claude Code envelope gains one catch-all variant (enum of the undisclosed names, free-form arguments). Hypotheses H4–H7 pre-registered before the runs; H5 holds (mean 18,891 tokens per call, four of five briefs under 25,851), H7 read 1.09 per op, H4/H6 wait for OT-27.
**Measured:** offered 29 of 56 (8 service + 14 readers + 7 core); static per call 13,727 → 8,646 (OpenAI/Ollama) and 14,967 → 9,626 (Claude Code) tokens on bmb's tokenizer; the Claude Code lane billed 16,880–17,833 tokens per API call on the four single-turn briefs (24,248–30,498 on the whole set at v14).
**Layers:** recorded in the closing commit message (both by exit code).
**Commit:** implementation `e7b6d5e`; closing `1016942`.

## OT-26 Cache-friendly prefix order

**What:** on lanes with prefix caching (Claude Code, OpenRouter) the static content — working agreement, conventions, tool set — MUST precede everything that changes per turn (scene block, history), and the cache-read fraction MUST be reported per run.
**Why:** measured today on the CLI lane: 89 % of input tokens were already cache reads (iteration 74: 331,796 of 372,080), so the remaining lever is the last 11 %; this item is ranked last for that reason and is closed by measurement, not by reordering on faith.
**Done means:** `TurnCost` cache-read fraction per run is in the record; a paired comparison shows the fraction did not fall.

**Closed:** 2026-09-10 — by measurement; no reordering was needed.
**Gating tests:** `tests/pure/test_cache_report.py` (the fraction is one function, `TurnCost.cache_read_fraction`, shown in the `spent` line; rows skip pre-accounting records; the paired comparison takes each brief's latest run on each side); the order itself was already pinned by `tests/pure/test_claude_code_lane.py::test_the_system_prompt_is_byte_stable_across_builds` and `::test_a_growing_transcript_keeps_the_previous_turn_as_its_prefix` — the system prompt (working agreement, conventions, protocol note) is static and travels as `--system-prompt`, the tool envelope as `--json-schema`, and the fold is append-only, so nothing per-turn precedes the static content on the Claude Code lane.
**Spec:** AGT-24 added; the "Prefix cache" row in the measured-state table; the scripts table (`scripts/cache_read_report.py`).
**Measured (`scripts/cache_read_report.py --before 81-86 --after 87-92`, whole set → disclosed set, both v14, hatch withheld):**

| brief | cache read before (iteration) | after (iteration) | delta | writes/call before | after | delta |
|---|---|---|---|---|---|---|
| crate_with_lid | 0.851 (85) | 0.812 (91) | -0.039 | 3,989 | 3,274 | -715 |
| planter_box | 0.829 (81) | 0.791 (87) | -0.039 | 4,259 | 3,733 | -527 |
| ribbed_column | 0.923 (84) | 0.885 (90) | -0.037 | 1,908 | 1,956 | +48 |
| three_leg_stool | 0.729 (86) | 0.647 (92) | -0.082 | 8,686 | 8,910 | +224 |
| uv_crate | 0.937 (83) | 0.883 (89) | -0.054 | 1,531 | 1,978 | +447 |

mean cache-read delta -0.050 over 5 paired brief(s); fell on 5; mean writes/call delta -104; rose on 3

The **Done means** as written ("the fraction did not fall") is NOT met: it fell on all five briefs. The mechanism is the ratio, not the order: the numerator is the static prefix, and OT-25 cut that prefix by ~5,300 tokens per call while each turn's new content (tool results, `search_ops` pages) stayed, so a smaller share of a smaller call is cached even though every call is cheaper (planter: 24,933 → 17,833 tokens per call). The number a volatile prefix would inflate — cache WRITES per call — moved −104 on average (rose on three briefs by 48–447 tokens, the extra `search_ops` result text; fell on two by 527–715). Recorded as the wrong number and the right one; the criterion for any future reorder is writes per call, and the fraction is reported per run as the item asked.
**Layers:** recorded in the closing commit message (both by exit code).
**Commit:** `1016942`.

## OT-28 The metered lane tells the truth about itself

**What:** on a lane that charges money per call the harness MUST read the served window
from the provider (`GET /v1/models`) at `check_connection` and pin it, MUST ask for and
record the price of every call (`usage.cost`), and MUST stop a run that passes a cap
derived from a measured run. An id the catalogue does not list is refused by name.
**Why:** `context_tokens` returned `None` on this lane, so AGT-23's preflight reported
"not checked" and skipped; `cost_usd` stayed 0, so a metered run's record claimed it was
free. NFR-27's ban on a paid lane can only become a cap if the cap is enforced in code.
**Amends:** AGT-23 (the OpenRouter half), NFR-27 (rewritten with the cap), §5.4.
**Done means:** `tests/pure/test_metered_lane.py` covers the discovered window, the refused
id, the price off the usage object, the cap and the lanes that are never capped;
`scripts/provider_smoke.py --only openrouter` passes text and image on the model.

**Closed:** 2026-09-10.
**Gating tests:** `tests/pure/test_metered_lane.py` (13: the window and the completion reservation from the pinned provider's endpoint; a provider that does not serve the id refused with those that do; the price off `usage.cost` and zero where none is reported; the cache split and the thinking share; the run cap; the lanes never capped; the retry loop). Live: `scripts/provider_smoke.py --only openrouter` 2/2 (text and image, so one model is writer and eye).
**Spec:** NFR-27 rewritten with the cap and the reason the prohibition failed; AGT-23 the OpenRouter half; AGT-25 (an empty reply is a dropped turn); AGT-26 (the assistant's tool calls travel with their results); AGT-27 (retry); NFR-28 (a crash is not a success); the lanes row and §5.4.
**Measured:** context 1,048,575 discovered from the pinned provider's endpoint; a 36-in/17-out call cost $0.0000312; caching runs 92–95 % once the history is well formed; `MAXIMUM_RUN_COST_USD` $1.00 from the heaviest measured run at the reachable price.
**What it cost to find the provider — the wrong answers are the lesson:** unrouted, OpenRouter sent two of five briefs to Novita (504 then HTTP 400). `DeepSeek` (the display name) filters every endpoint out, because `provider.order` matches the routing slug. `deepseek` (the vendor's own endpoint, cheapest at $0.15/$0.60, 99.99 % uptime) is excluded by this account's guardrail. Of the seven left, `fireworks`, `novita` and `parasail` all answered "Provider returned error" on a model published that day. `gmicloud` carries the full window at 99.97 % uptime, at $0.30/$1.20 — twice the catalogue's headline, which is why the first cap was derived from a price the lane cannot reach.
**Layers:** pure 747 passed / 1 skipped / 1 xfailed; Blender 330 passed / 3 skipped (both by exit code).
**Commits:** `06c59e2`, `cf7bcf0`, `e46ad1a`, `8e0984e`, `179ab11`, `74d990b`.

## OT-29 The iteration loop runs on the metered lane

**What:** run the five briefs no-hatch at v14 on `deepseek/deepseek-v4.1-flash` as writer
and its own eye, from a frozen worktree, and record per brief: form gate, refinement gate,
API calls, `search_ops` calls, hatch calls, tokens and dollars. Compare against iterations
87–92 (the same briefs, same surface, Claude Code lane). `RECOMMENDED_MODELS` gains the
lane only if the briefs pass, with the measured numbers behind the recommendation.
**Why:** this is the loop the user asked to iterate on; until it is measured on this lane
the lane is a hypothesis.
**Open question this run answers:** whether `max_completion_tokens` (16,384, derived for
bmb's 27B) starves a reasoning model on a 1M-context lane — the exact failure that killed
the local arm. A turn cut at the ceiling is already a loud error (AGT-23), so the run
either shows the number is fine or names the turn that hit it. **Do not raise it on faith.**
**Done means:** the per-brief table is in the spec's measured-state section with cost and
gate outcome per lane; a brief that fails on this lane is named with its failure.
**Closed:** 2026-09-10 — measured, and the recommendation does NOT change.
**Gating run:** the five briefs no-hatch at v14 on `deepseek/deepseek-v4.1-flash` as writer and its own eye, from a frozen worktree at `74d990b` (iterations 118–122).

| brief | form gate | api calls | tool calls | `search_ops` | cached | reasoning / output | cost |
|---|---|---|---|---|---|---|---|
| planter_box | PASS | 15 | 17 | 0 | 94 % | 7,328 / 10,454 | $0.0163 |
| three_leg_stool | **FAIL** | 10 | 25 | 9 | 95 % | 12,621 / 14,564 | $0.0198 |
| uv_crate | PASS | 14 | 22 | 8 | 93 % | 37,504 / 39,668 | $0.0516 |
| ribbed_column | **FAIL** | 12 | 24 | 14 | 92 % | 13,573 / 15,813 | $0.0231 |
| crate_with_lid | PASS | 14 | 24 | 2 | 94 % | 4,694 / 8,241 | $0.0133 |

**3 of 5 form-gate passes for $0.124.** The same five briefs on `claude-code:sonnet`
(iterations 87–92, same surface, same revision, hatch withheld) were **5 of 5 for $2.75**
— 22x the price. Four of the five metered runs hit the 24-call turn budget; the two
failures are also the two that searched hardest (9 and 14 `search_ops` calls against 0–2
on the passes), so the model flails rather than stops when it cannot find an op.

**The open question this run was to answer — does the 16,384-token reservation starve a reasoning model? — is answered YES, by a cut turn.** uv_crate died on `ReplyTruncated` at the old ceiling; with the reservation taken from the provider (65,536) the same brief passes and spends 37,504 reasoning tokens in one run. The number was not raised on faith: it was raised after a turn was measured being cut.
**The recommendation:** `RECOMMENDED_MODELS` is unchanged. The lane is mechanically sound and 22x cheaper, but this writer passes 3 of 5 where the default passes 5 of 5, and OT-29's own rule was that the default changes only if the briefs pass. The lane is worth using for cheap iteration on harness mechanics — which is exactly what it did today — and not yet for gating.
**What the lane found, none of it in the tool surface:** four harness defects, each of which had been latent on every lane the harness has ever used — the assistant's tool calls never reached the model (AGT-26), an empty reply was read as an answer (AGT-25), a crash exited 0 (NFR-28), and a transient gateway killed whole runs (AGT-27). That is the return on the item.
**Record gap:** iterations 93–117 were run on the broken transport from worktrees since removed; only 118–122 are in `_evaluate/iterations.jsonl`. The failures are recorded in the commits above, not in the log.
**Layers:** pure 747 passed / 1 skipped / 1 xfailed; Blender 330 passed / 3 skipped (both by exit code).
**Commit:** `74d990b`; closing `92b7d7e`.

## OT-32 The lane survives a gateway, and a crash is not a success

**What:** two defects found by running the five briefs on the metered lane, neither in the
tool surface. (1) Blender exits 0 on an uncaught Python exception, so a converge run that
died mid-way reported success to every caller that gates on the exit status. (2) A
gateway's transient "not now" killed whole runs.
**Why:** measured 2026-09-10. Iteration 109's visual gate raised `EmptyFrame` after the
build and export and `make converge` returned 0; three metered briefs died on HTTP 429 and
returned 0 as well, so one chain recorded four successes it never had — while the repo's
closing rule gates commits on exactly such exit codes. Separately, five briefs in a row
failed inside ~2 minutes on upstream 429s while a probe minutes later passed 12 of 12.
**Done means:** `tests/pure/test_script_exit.py` (a crash exits 70, a deliberate exit
passes through, an interrupt is 130, and every Blender-hosted entry point is guarded) and
the three retry tests in `tests/pure/test_metered_lane.py`; a converge run given a bad
brief exits 70 instead of 0.

**Closed:** 2026-09-10 with OT-28 and OT-29.
**Gating tests:** `tests/pure/test_script_exit.py` (6: a crash exits 70, a deliberate `SystemExit` keeps its own code, an interrupt is 130, every Blender-hosted entry point is guarded) and the three retry tests in `tests/pure/test_metered_lane.py`. Live: `make converge` with a bad brief exits 70 where it returned 0.
**Spec:** AGT-27 (retry on a gateway's "not now", never on a permanent status, counted on `TurnCost.retried_calls`), NFR-28 (a Blender-hosted script exits non-zero when it dies).
**Measured:** `blender --python-expr "raise RuntimeError(...)"` exits 0 while `raise SystemExit(3)` exits 3; the retry budget of 5+15+45+90 s comes from windows in which five briefs failed inside ~2 minutes on upstream 429s while a probe minutes later passed 12 of 12.
**Commit:** `179ab11`.

## OT-31 The bake reproduces a chunk that raised after it changed the scene

**What:** `bench_bridge` includes a recorded call only when its `stage_reached` reached
`locate`/`gate`/`export`/`done`. A `run_python` chunk that raised PART WAY THROUGH is
excluded — but the objects it made up to that point stayed in the live scene, and every
later call in the recorded conversation was written against them. The baked script must
reproduce the scene the run actually had, which means emitting such a chunk with its
failure reproduced, not omitting it.
**Why:** measured in OT-27's cloud roll 1 (Spoon_seed0, 2026-09-10): the first chunk built
the handle, then raised `TypeError: create_uvsphere: keyword "diameter" is invalid`; the
next `list_scene` reported `Spoon: 956 tris`; the bake dropped the chunk and died with
`UnknownObject: no object named 'Spoon'`. One instance in twenty — 5 % of an executability
score that ranks configurations lexicographically first (BEN-5).
**Not before:** OT-27's rolls finish. Changing the instrument between rolls 1 and 3 makes
them incomparable; roll 1's reading already names the affected instance.
**Done means:** a Blender test records a chunk that creates an object and then raises,
bakes it, and the object exists in the fresh scene with the later calls succeeding; the
inclusion rule is stated in terms of "changed the scene", not "reached a stage".

**Closed:** 2026-09-10.
**Safe to do now, despite the "not before" above:** OT-27's rolls run from the frozen worktree `/Users/ladvien/blended-bench-v4`, so the main tree moving does not change the instrument any of the three rolls use. They stay comparable with each other, and roll 1's reading already names the affected instance.
**Gating tests:** `tests/blender/test_bench_bridge.py::test_a_chunk_that_built_then_raised_is_replayed_so_later_calls_find_its_object` — a chunk that creates `Handle` and then dies on the same invalid keyword goes through the live dispatcher, the scene is observed to have kept the object, the emitted script is re-baked in a fresh scene, the reproduced failure is announced rather than swallowed, and the later `rename_object` finds its object; plus `tests/pure/test_bench_bridge.py::test_a_chunk_that_raised_after_changing_the_scene_is_replayed` and `::test_the_default_keeps_the_old_rule_for_a_caller_that_cannot_look`.
**Spec:** BEN-1 amended.
**Shape of the change:** `RecordedCall` gains `changed_scene`, measured by the runner from `bpy.data` either side of each dispatch (names and vertex counts, so a boolean rewriting a mesh in place counts too) — ground truth, never read off the outcome. `include_call` = executed OR changed the scene. A call that raised having changed the scene is emitted inside a `try` printing the same error, which is faithful because the chunk is deterministic: re-running it stops at the same point leaving the same partial geometry. A call that raised and changed nothing stays out, and the field defaults False so a recorder with no scene to read keeps the old rule exactly.
**Layers:** pure 749 passed / 1 skipped / 1 xfailed; Blender 331 passed / 3 skipped (both by exit code).
**Commit:** `9b1be03`.

## OT-34 The `orient:` reading is computed from the same world extents the op reads

**What:** `harness.gate_object` (`src/blended/harness.py:147`) and `inspect_object`
(`src/blended/agent/tools.py:582`) build the extents behind `orientation_reading` from
`blender_object.dimensions` — the LOCAL bounding box scaled, which ignores rotation.
`apply_canonical_depth_axis` reads `matrix_world @ bound_box`. One private helper in
`ops/transforms.py` (the OPS-14 home of the depsgraph refresh) computes the joint world
extents; `world_bounds`, `apply_canonical_depth_axis`, the gate, `inspect_object` and
`list_scene` all read it. The duplicate in `canonical_orientation.py` is deleted.
**Why:** a 0.9 × 0.3 × 0.6 box rotated a quarter turn about X reads `(0.9, 0.3, 0.6)`,
"middle extent on z", while it occupies `(0.9, 0.6, 0.3)` and the op composes identity. The
harness tells the writer one axis assignment and applies another; the drift catalog
(`drift/catalog.py:282`) and mistake memory already name this trap.
**Done means:** a Blender test rotates the box, gates it, and asserts the reported extents,
the reading's named axis and `canonical_depth_axis_rotation_euler_rad(*extents)` agree —
red before the change, green after; OPS-18 amended in place; both layers green.

**Closed:** 2026-09-11.
**Gating tests:** `tests/blender/test_harness.py::test_the_reading_and_the_op_measure_the_same_box` (red before the change: reported (0.9, 0.3, 0.6) for a box occupying (0.9, 0.6, 0.3); green after) and `::test_inspect_object_and_list_scene_read_the_world_box`.
**Spec:** OPS-18 amended in place.
**Shape of the change:** `ops/transforms._world_bounds_m` / `_world_extents_m` is the one place `matrix_world @ bound_box` is measured; `world_bounds`, `apply_canonical_depth_axis`, `harness.gate_object`, `tools.inspect_object` and `tools.list_scene` read it; the duplicate in `canonical_orientation.py` is deleted. Mistake memory: `the-reading-and-the-op-measured-different-boxes`.
**Layers:** pure 749 passed / 1 skipped / 1 xfailed; Blender 333 passed / 3 skipped (both by exit code).
**Commit:** `57562c6`.

## OT-36 F-score ranks the next roll set, and a roll below 20/20 cannot rank

**What:** per the OT-33 pre-registration and the user's decision of 2026-09-11, F@0.05
becomes `RANKING_METRIC` with an explicit direction; `diagnose_3dcode.py` writes
`fscore_005`, `precision_005`, `recall_005` per row from ONE implementation shared with
`bench_fscore.py`; `bench_panel.py` honours the direction and refuses any group in which a
roll executed fewer instances than it attempted (§P8a). The nine rolls on disk (six
incumbent, three void disclosed) are re-diagnosed, asserting every re-derived `cd_pca`
reproduces the stored value.
**Why:** the panel cannot rank on a column it does not carry, and it currently accepts a
19/20 roll as rankable, which the rule forbids.
**Done means:** the panel on the nine JSONs ranks on F@0.05 and refuses the disclosed group;
a pure test feeds a 19/20 roll and asserts the refusal; BEN-4/BEN-5 amended in place; the
second-set pre-registration is written with the incumbent's F@0.05 mean and SD before launch.

**Closed:** 2026-09-11.
**Gating tests:** `tests/pure/test_bench_panel.py::test_the_ranking_axis_is_f_score_and_higher_ranks_first`, `::test_a_roll_that_failed_one_instance_cannot_rank` (a 20-row roll with one `ERR_MODEL_CALL` is refused by name with "executability 19/20"), `::test_a_worse_executability_cannot_rank_first` (rewritten: a group with failed instances is refused, not ranked lower), `tests/pure/test_paired_bench_delta.py::test_the_ranking_metric_is_f_score_at_the_registered_threshold`, `::test_a_falling_f_score_is_a_regression_and_a_rising_one_is_not`.
**Spec:** BEN-4 and BEN-6 amended in place.
**Shape of the change:** `scripts/bench_surface_metrics.py` holds the one alignment search and the one F-score; `diagnose_3dcode.py` writes `fscore_005`/`precision_005`/`recall_005` per row on the same aligned cloud as `cd_pca`; `bench_fscore.py` and `shape_error_decompose.py` import from it. `bench_thresholds.py`: `RANKING_METRIC = "fscore_005"`, `higher_is_better`/`worsening_sign` read by the panel's sort and the paired delta's sign and target. `bench_panel.is_rankable` requires executed == attempted ≥ 20 and every attempt scored.
**Measured:** nine rolls re-diagnosed, 180/180 `cd_pca` values reproduced to 1e-9. Incumbent `deepseek-v10` F@0.05 0.4528, SD 0.0200, margin at the floor 3.07× (cd_pca 1.84×). The panel on both groups exits 1: "group disclosed has 0 rankable roll(s) … roll1 (18 instances scored, executability 19/20), roll2 (18, 19/20), roll3 (13, 13/20)". Sidecar-vs-diagnose F@0.05 differ in the fourth decimal (0.4060 vs 0.4066) from RNG stream order around unscoreable instances; recorded in the pre-registration.
**Layers:** pure 752 passed / 1 skipped / 1 xfailed (by exit code); no Blender-layer file touched.
**Commit:** `359ec63`.

## OT-35 One transport path: the stream retries and is costed

**What:** `OllamaClient._request` retries a gateway's "not now" (OT-32); its streaming twin
`_stream_lines` does not, and `_chat_streamed` returns before the cost fold and the NFR-27
cap at `loop.py:1496-1499`. One opener carries the retry; `_stream_lines` opens eagerly
through it so an `HTTPError` surfaces before any delta is emitted (the only safe replay
point; a stream cut mid-body is not retried). The assemblers keep the final frame's counts
and the streamed branch folds `_turn_cost_from_body` and runs `_check_run_cost`.
**Why:** the addon's `stream_replies=True` lane is the one the user watches, and it is the
one lane with no retry and a turn record that says 0 tokens.
**Done means:** pure tests at the `urlopen` boundary — a streamed call that 502s twice then
streams delivers every delta once with `retried_calls == 2`; a stream cut mid-body raises
with no retry; a streamed `done` frame's counts land on `spent` — red before, green after;
AGT-27 amended to name both `chat` paths.

**Closed:** 2026-09-11.
**Gating tests:** `tests/pure/test_streaming.py::test_a_streamed_call_refused_by_the_gateway_is_retried_then_streams_once` (two 502s at `urlopen`, then the stream: waits (5, 15), `retried_calls` 2, every delta once), `::test_a_stream_that_dies_after_a_delta_is_not_replayed` (a body that resets after one frame raises `ConnectionResetError`, one open, no wait), `::test_an_ollama_stream_is_costed_from_its_done_frame` (12 in / 8 out land on `spent`), `::test_an_openai_stream_asks_for_usage_and_is_costed_from_the_usage_chunk` (`stream_options.include_usage` sent; 40/9/4 reasoning/$0.0021 folded), `::test_a_streamed_metered_call_is_stopped_by_the_run_cap`, `::test_a_stream_cut_before_its_final_frame_still_counts_as_a_call`. The four pre-existing streaming tests now stub `_open`, not `_stream_lines`, so the real decoder and fold run. Live smoke: a local HTTP server answering 503 twice then streaming NDJSON — `[retry]` lines printed, reply assembled once, `1 api call(s), 21 input tok, 4 out, 2 retried`.
**Spec:** AGT-27 (both `chat` paths through `_open`; no replay after a delta) and NFR-27 (the streamed fold and cap) amended in place.
**Shape of the change:** `OllamaClient._open` is the one socket opener and carries the retry; `_request` = `_open` + `json.loads`; `_stream_lines` opens eagerly through `_open` and returns `_decoded_lines(...)`. The assemblers keep the usage-bearing final frame under `STREAM_USAGE_KEY`; `_chat_streamed` pops it, folds `_turn_cost_from_body`, runs `_check_run_cost`, and passes `reasoning_tokens` to `check_reply_is_a_turn`. `test_metered_lane._urlopen_from` now runs its handler at call time, as the real `urlopen` raises. Mistake memory: `the-retry-covered-one-of-two-transport-paths`.
**Layers:** pure 764 passed / 1 skipped / 1 xfailed; Blender 333 passed / 3 skipped (both by exit code).
**Commit:** `b39a74e`.

### OT-50 Every export saves its .blend

**What:** `blended.export.save_blend(object_names, blend_path) -> BlendSaveReport` writes a compressed `.blend` whose one scene holds exactly the named objects (mesh, materials, transforms, same names) through `bpy.data.libraries.write` from a temporary scene and collection, re-reads the written file with `bpy.data.libraries.load`, and raises `BlendSaveError` when a name is missing, a triangle count differs or the path does not end in `.blend`. It never touches the running session (`bpy.data.filepath`, current scene, selection, collections stay). `export_glb(blender_object, output_path, *, blend_path)` takes a REQUIRED `blend_path` and calls it after the .glb round trip; `ExportReport.blend` carries the report. `HarnessSettings.export_blend_path` is required whenever `export_glb_path` is set (`run_builder` fails before building otherwise). The `export_asset` service tool requires `blend_path`; a new `save_blend` service tool (`object_names`, `blend_path`) covers pieces exported another way (several objects in one .glb). The MCP rules head gains one rule: an asset without its .blend is not done.
**Why:** the owner requires that any exported asset can be edited and re-exported later; a .glb alone is a baked artifact (the exporter applies modifiers and splits vertices along flat-shading seams), so the source was being thrown away on every export. Literature: `hs distill search` (2026-10-10) returned only a book chapter on glTF export settings and no DOI-bearing source, so nothing here rests on a citation; the behaviour is pinned by the tests below.
**Amends:** EXP-1 (export MUST also save the .blend), new EXP-5 (`save_blend` contract and verification), the `export_glb` row of §2.1 and the `export_asset` row of §2.2 (new `blend_path` parameter, new `save_blend` row, nine service tools, 57 tools), AGT-1 (service tool list, count and fingerprint), the MCP instructions head row (rule count and character count).
**Done means:** Blender tests prove (a) the written file re-opens with exactly the named objects and equal triangle counts, (b) `bpy.data.filepath`, the current scene and the objects' collections are unchanged after the call, (c) a path not ending in `.blend` raises `BlendSaveError`, (d) `export_asset` without `blend_path` fails and with it writes both files, (e) a negative control: a missing object fails loudly and writes nothing, (f) `run_builder` with `export_glb_path` and no `export_blend_path` fails before building; pure tests pin the argument validation, the report shape, both tool schemas and the rules-head limit; fingerprint pins regenerated from their generators; `make test` green.

**Closed:** 2026-10-10.
**Gating tests:** `tests/blender/test_save_blend.py::test_the_file_reopens_with_exactly_the_named_objects` (a: exactly the two named objects, one scene, no camera, the bystander absent, material and transform kept, triangle counts equal the live ones, zstd-compressed), `::test_the_session_is_unchanged_by_the_save` (b: filepath, current scene, scenes, collections, objects, meshes, libraries, each object's `users_collection`, selection and active object identical before and after), `::test_a_path_not_ending_in_blend_raises_and_writes_nothing` (c), `::test_export_asset_fails_without_blend_path_and_writes_both_files_with_it` (d: missing, relative and non-.blend paths all fail with nothing written; with it both files exist), `::test_a_missing_object_fails_loudly_and_writes_nothing`, `::test_a_dependency_pulled_into_the_file_fails_loudly` and `::test_a_triangle_mismatch_in_the_written_file_fails_and_deletes_it` (e: negative controls), `::test_the_open_file_of_the_session_is_never_overwritten`, `::test_export_glb_requires_a_blend_path_and_ships_both_files`, `::test_export_glb_with_a_bad_blend_path_writes_no_glb`, `::test_the_save_blend_tool_saves_several_objects_and_refuses_the_rest`; `tests/blender/test_harness.py::test_a_glb_export_without_a_blend_path_is_refused_before_building` (f); `tests/pure/test_save_blend_arguments.py` (argument validation, frozen report shape, both tool schemas, the harness refusal); `blender_mcp/tests/test_blended_bridge.py::TestInstructionsHead::test_head_requires_the_blend_source_and_names_real_tools` and `::test_readme_states_the_measured_head_length`.
**Spec:** EXP-1 amended, EXP-5 added, §2.1 `export_glb` row and new `save_blend` row, §2.2 `export_asset` row and new `save_blend` row, AGT-1 (nine service tools, 57 tools, 30 offered, fingerprints `t:e34f29ae95dc` and `t:3492bb0d2708`), MCP-4 (head 2,047 characters), the measured-starting-point row of this backlog.
**Shape of the change:** `src/blended/export/blend.py` (`save_blend`, `BlendSaveReport`, `BlendSaveError`, `validate_blend_request`); `export_glb(blender_object, output_path, *, blend_path)` validates the path before writing anything and saves after the round trip (`ExportReport.blend`); `HarnessSettings.export_blend_path`, required with `export_glb_path` (`require_export_blend_path`, called first in `run_builder` and `run_chunk`), `HarnessResult.export_blend_path`; service tools `export_asset` (required `blend_path`, absolute, `.blend`) and `save_blend` in `agent/tools.py`; rule 9 of `MCP_INSTRUCTIONS_HEAD`; the pinned tool fingerprint regenerated from `tool_schemas_fingerprint(TOOL_SCHEMAS)`; `_TOOL_CALL_PATTERN` gained the `save` verb. The write is an emptied copy of the current scene, because a scene from `bpy.data.scenes.new` segfaults `libraries.write` in Blender 5.2.0 LTS. Mistake memory: `libraries-write-segfaults-on-a-scene-made-by-scenes-new`, `the-blender-test-layer-imported-the-venvs-numpy-and-pillow` (`scripts/run_tests_in_blender.py` now blocks the venv's numpy and Pillow), `the-documented-head-length-was-a-stale-copy`. Literature: `hs distill search` returned no DOI-bearing source, so none is cited.
**Layers:** pure 1288 passed / 1 xfailed; Blender 315 passed / 1 skipped; bench scripts 5 passed; MCP unit layers OK; `make test-mcp-blender` 42 tests OK (all by exit code).
**Commit:** 09b3e9f.

---

## OT-51 Skinned-motion ops: self-intersection, capsules, limb repair, cloth chains

**What:** Four ops in a new `blended.ops.motion`, built on the numpy-only package `skinclip`
(`Ladvien/skinclip`, tag `v0.1.2`) through an internal adapter `blended.ops._skinned` that reads an
armature, its bound meshes and an action into skinclip's objects and writes keys back.
`clip_self_intersection_report(armature_name, action_name, cloth_material, contour_limit_m)` and
`body_capsules_report(armature_name)` are readers; `repair_limb_penetration(armature_name,
action_name, loop)` and `bake_cloth_chains(armature_name, mesh_name, garment_material,
anchor_bone_name, action_name, spec, loop)` are writers (plan required, return reports, not gated).
`RingSkirtSpec` is the writer's config object (in `OP_CONFIG_DATACLASSES`), `ArmatureRotationModeError`
refuses a keyed bone that is not in QUATERNION mode. Op modules import skinclip only inside op
bodies, so the facade, the MCP server and `tests/pure` import them with no numpy.
**Why:** A retargeted or generated clip crosses its own body (a hand through the thigh, a knee through
a skirt) and nothing in the vocabulary sees it: the structural gate measures the mesh at rest, where
it is sound. The check is metamorphic, not a reference comparison: a surface free of intersections at
rest must stay free of them in every pose, measured as the length of the intersection contour (ContourCraft,
SIGGRAPH 2024, DOI 10.1145/3641519.3657408). The repair and the cloth bake are skinclip's own solvers
over body capsules (segment-segment distance, Ericson 2005, 5.1.9) and position-based dynamics (Abu
Rumman and Fratarcangeli, CGF 2015, DOI 10.1111/cgf.12533); the three `hs distill search` queries of
2026-10-12 found no per-frame limb solver and no skirt-bone paper to cite instead.
**Amends:** OPS-1 and AGT-1 (52 ops, 60 tools, the two readers are always offered), adds OPS-26 and OPS-27,
§5.5 (the new named constants), the measured-state table, §6.1–§6.3 counts.
**Done means:** `tests/blender/test_motion_ops.py` (run by `make test-blender-app`) imports skinclip's tube
humanoid into Blender and asserts: the `hand_through_torso` report fails and names an arm bone against the
trunk, in Blender frame numbers; `body_capsules_report` gives 18 capsules (6 central, 6 a side) and
`rig_convention == "ue5"`; after `repair_limb_penetration` the report passes and
`worst_depth_m_after <= 0.002`, with every curve it did not change untouched; on `thigh_swing`
`bake_cloth_chains` creates 24 bones, weights the garment, gives `worst_clearance_m >= -0.005` measured on the
posed pose bones in Blender (and a control shows the same probe failing on unbaked chains), and a second call
creates 0; `tests/pure/test_motion_ops_pure.py` and `test_pose_paths.py` pin the numpy-free import and the
data-path reader; `make test` is green and the tool-schema pin is moved in the same change.

**Closed:** 2026-10-12.
**Gating tests:** `tests/blender/test_motion_ops.py` (27 tests): `::test_the_hand_through_the_torso_fails_and_names_the_arm_against_the_trunk` (61 frames, 36 failing, worst frame 28, 1.781 m, `lowerarm_l` against `pelvis` / `thigh_l` / `spine_01`, `hand_l` against `thigh_l`), `::test_frames_are_blender_frame_numbers_when_the_action_starts_late`, `::test_the_capsule_report_holds_the_eighteen_capsules_of_a_ue5_humanoid`, `::test_the_repair_clears_the_hand_and_touches_only_the_arm` (depth 0.0979 → 8.9e-07 m, contour 1.781 → 0.0 m, 45 frames, only `upperarm_l` and `lowerarm_l` rewritten), `::test_the_cloth_bake_creates_the_chains_weights_the_garment_and_clears_the_legs` (24 bones, 768 vertices, 31 frames, clearance +0.0113 m), `::test_the_clearance_probe_fails_on_chains_that_were_never_baked` (same probe on unbaked chains: -0.0555 m), `::test_a_second_bake_reuses_the_bones_and_leaves_the_weights_alone`, `::test_a_refused_bake_leaves_the_scene_as_it_found_it`, `::test_a_moved_and_turned_armature_measures_the_same`; `tests/pure/test_motion_ops_pure.py::test_the_ops_import_with_numpy_and_skinclip_unavailable`; `tests/pure/test_pose_paths.py`.
**Spec:** OPS-26 and OPS-27 added; the measured-state table, §3.9 package map, AGT-1, §5.5 constants, §6.1–§6.3 counts amended in place; `docs/harness_design.md` row 32; OPS-10 and three `manifest.py` cites re-resolved.
**Shape of the change:** `blended.ops._skinned` reads an armature and its action as Blender evaluates it (`rest_local @ basis`) into skinclip's `Figure` / `Clip` and writes `rotation_quaternion` keys back (`basis_r = conjugate(rest_r) (x) local_r`); `rigging._create_edit_bones` became the one place bones are made. `RingSkirtSpec` is skinclip's own class re-exported from `skinclip.spec`: v0.1.0 kept it in `skinclip.cloth`, which imports numpy, so the first version of this change carried a field-for-field mirror; skinclip v0.1.1 moved it to a module that imports nothing and the mirror was deleted, and v0.1.2 gave it its own `__post_init__` checks and docstring, so blended keeps none (the facade's re-export is allowlisted in `tests/pure/test_one_path_ops.py`).
**Side effects, measured:** tool-schema fingerprint `t:fd10e7f510a8` → `t:181a889fa64b` (60 tools, 16 readers); the offered set 29 of 56 → 31 of 60 (`t:6b6093efb569` → `t:f26ac89217a9`), because readers are always offered; the assembled-prompt pin did not move. `uv sync` removed `numpy`, `pillow` and the hand-installed `spyrite-tile-ops` from `.venv` (the last was reinstalled).
**Cloth numbers, three skinclip versions (`thigh_swing`, `worst_clearance_m` read from the posed pose bones in Blender):** v0.1.0 and v0.1.1 gave the same +0.011331 m to nine digits (v0.1.1 only changed the push for a body that tilts; this one never does), v0.1.2 gives **+0.016970 m** (the foot swinging past `skirt_00_b` no longer sets the minimum: v0.1.2 presses hands and forearms the short way and keeps the legs' push outward). The probe is not dead: it takes 9 distinct values over the 31 frames. The minimum now sits on frames 7, 8, 22, 23 at 0.0170 m and is a pinned chain top (`skirt_04_a`, `skirt_02_a`) against a thigh capsule, which the simulation cannot push (it ignores hits within 35% of a pinned top); the target is 0.05 m, so the posed bones reach 0.0170 of it. The threshold (>= -0.005 m) holds with 0.022 m of margin. The control (same 24 bones, chain keys removed AND pose reset to rest) reads **-0.0700 m**; the earlier controls (-0.0555 on v0.1.0/v0.1.1, -0.0690 on v0.1.2) removed the keys without resetting the pose, which leaves each property at its last evaluated value, i.e. the chains frozen in the baked frame-30 pose, not at rest (mistake `removing-an-fcurve-leaves-the-property-at-its-last-value`). A second call creates 0 bones and reproduces +0.016970 m.
**Layers:** pure 1325 passed / 1 xfailed; Blender 330 passed / 1 skipped; bench-scripts 5 passed; MCP unit 126 tests OK (36 + 1 + 29 + 7 + 53).
**Commit:** `78b0c31`, then `a2a2606` (skinclip `v0.1.1`: the real `RingSkirtSpec`, the mirror deleted), then `396f2ad` (skinclip `v0.1.2`: skinclip's own spec validation, blended's copy deleted, the control corrected).

---

## Errata (append-only; entries above are not edited)

- 2026-10-07: `tests/blender/test_agent_loop.py::test_a_gated_op_on_a_missing_object_fails_at_locate` (OT-4 gating test) is now `::test_a_gated_op_on_a_missing_object_fails_at_execute`; the call fails at execute with `UnknownObject`.
- 2026-10-07: `tests/pure/test_agent_cancel.py` (OT-17) is now `tests/pure/test_turn_token_budget.py`; its test names are unchanged.
