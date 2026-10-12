"""The Experience Library: mistakes that must never recur.

3DCodeBench's curated Experience Library is the model — a durable
record consulted BEFORE acting, not a postmortem written after. The
drift catalog next door holds API-level lessons (a symbol moved, a call
lies). This holds LOOP-level lessons: what the harness, the prompt, or
the acceptance spec got wrong, and the assertion that now guards it.

A record is not complete until `guarded_by` names something executable.
"Be careful about X" is not a guard; a test that fails when X recurs is.

Shape per CoALA's procedural memory — reflect experience into knowledge,
then into a code library (DOI 10.48550/arXiv.2309.02427); the open
problem is stale memory dominating (memory-mechanism survey,
DOI 10.48550/arXiv.2404.13501), which is why `recorded_on` is a field.
"""

from __future__ import annotations

from dataclasses import dataclass

SCOPE_PROMPT = "prompt"
SCOPE_HARNESS_CODE = "harness_code"
SCOPE_BRIEF = "brief"
SCOPE_PROCESS = "process"
SCOPES = (SCOPE_PROMPT, SCOPE_HARNESS_CODE, SCOPE_BRIEF, SCOPE_PROCESS)


@dataclass(frozen=True)
class MistakeRecord:
    """One (failure -> cause -> fix -> guard) chain."""

    identifier: str
    scope: str
    failure: str  # what was observed, in measurements
    cause: str  # why it happened
    fix: str  # what was changed
    guarded_by: str  # the executable assertion that catches a recurrence
    recorded_on: str  # ISO date


MISTAKES: tuple[MistakeRecord, ...] = (
    MistakeRecord(
        identifier="stale-version-pin-lies-to-the-model",
        scope="harness_code",
        failure=(
            "make test-blender-app: 1 failed, 72 passed — "
            "BlenderVersionError, running (5, 2) against pin (5, 0)."
        ),
        cause=(
            "TARGET_BLENDER_SERIES is interpolated into the first line of "
            "the system prompt, so a stale pin is not only a red test: "
            "every session opened by telling the agent it was coding "
            "against Blender 5.0 while running 5.2."
        ),
        fix=(
            "Bumped the pin to (5, 2) after confirming all 72 other blender "
            "tests pass unchanged on 5.2 (so no ops drift exists between "
            "the series), and recorded the lesson in drift/catalog.py in "
            "the same commit."
        ),
        guarded_by="tests/blender/test_walking_skeleton.py::test_pinned_blender_series",
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="material-slot-is-not-a-material",
        scope="harness_code",
        failure=(
            "The acceptance gate passed a planter built with NO material: "
            "material_slot_count == 1 while nothing was assigned."
        ),
        cause=(
            "Applying a boolean modifier appends an empty material slot to "
            "the target (measured: len(mesh.materials) 0 -> 1, contents "
            "[None]). len() counts slots, not materials, so every mesh "
            "that had ever been through a boolean read as textured."
        ),
        fix=(
            "The gate reports two numbers — slots and assigned — and "
            "requires assigned_material_count > 0."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_missing_material_trips_the_material_check"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="unlinked-object-crashed-the-gate",
        scope="harness_code",
        failure=(
            "evaluate_brief raised RuntimeError('Object has no evaluated "
            "mesh data') instead of returning a failing report."
        ),
        cause=(
            "Construction and linking are separate ops, so an object can "
            "exist in bpy.data with no depsgraph instance. The probe cast "
            "rays at it and Blender raised."
        ),
        fix=(
            "linked_into_scene is measured first and reported as an "
            "ordinary acceptance failure naming the missing "
            "link_into_scene call."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_unlinked_object_reports_a_measurement_not_a_crash"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="no-observation-channel-so-the-agent-raised-to-print",
        scope="harness_code",
        failure=(
            "Iteration 1, planter_box, prompt v1: both deterministic gates "
            "passed, but the run burned all 16 tool calls and ended with "
            "'Stopped after 16 tool calls without reaching an answer'. "
            "Three of those calls came back as FAILED tracebacks reading "
            "'RuntimeError: ring_verts=24 radii=[0.015]', "
            "'RuntimeError: material_slots_non_none=1', "
            "'RuntimeError: base_color=(0.72, 0.35, 0.22, 1.0)'."
        ),
        cause=(
            "run_source_in_process never captured stdout and RunResult had "
            "no field for it, so print() went to Blender's console where "
            "the model cannot see it, and an ungated run_python returned "
            "only 'Executed OK in 0.02s.'. With no way to read a value out "
            "of the scene, raising an exception was the agent's only "
            "channel — and every observation therefore arrived in its "
            "context labelled as a failure."
        ),
        fix=(
            "RunResult carries stdout_text, captured via "
            "contextlib.redirect_stdout in both the in-process and "
            "subprocess paths, bounded to MAXIMUM_STDOUT_CHARACTERS "
            "keeping the tail. Both run_python branches return it, and the "
            "tool description tells the agent print() is how it asks the "
            "scene a question. Silence is reported explicitly as "
            "'(nothing printed)'."
        ),
        guarded_by=(
            "tests/blender/test_observation_channel.py (6 assertions, "
            "including test_run_python_tool_returns_printed_output)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="parity-probe-passed-a-sealed-drain-hole",
        scope="brief",
        failure=(
            "Iteration 1, planter_box: the acceptance gate reported FORM "
            "PASS with 'drain_hole_is_open: expected empty, measured empty "
            "(0 surface crossings)', while the top-down render showed "
            "opaque material on the drain axis (centre pixel 0.604 grey, "
            "alpha 1.0, against a transparent background). The gate "
            "certified the exact wrong-object failure the brief existed "
            "to catch."
        ),
        cause=(
            "SolidityProbe answers 'is there material at this point' by "
            "counting crossings along ONE ray. A drain cut from the cavity "
            "down into the floor but not out the bottom leaves the probe "
            "point in open air with the open top above it — zero "
            "crossings, indistinguishable from a real through-hole. Parity "
            "says nothing about the half-space behind the ray."
        ),
        fix=(
            "Added ClearAxisProbe: sweeps the entire axis from beyond one "
            "side and requires no hit at all, reporting the blocking "
            "coordinate when there is one. planter_box asserts a clear "
            "z-axis at (0, 0)."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_blind_recess_trips_the_clear_axis_probe — which also "
            "asserts the parity probes still CANNOT see it, so the "
            "fixture keeps reproducing the original failure"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="workbench-renders-grey-so-the-eye-invented-a-defect",
        scope="harness_code",
        failure=(
            "Iteration 1: the agent assigned a terracotta material, the "
            "contact sheet came back grey (measured 0.604, 0.608, 0.612), "
            "the vision model reported 'gray, not terracotta', and the "
            "agent spent tool calls investigating a defect that did not "
            "exist. It ran out of its tool budget mid-investigation."
        ),
        cause=(
            "Workbench shades from material.diffuse_color and never reads "
            "the shader graph, so setting only the Principled BSDF base "
            "colour renders as default grey. Compounding it, there was no "
            "whitelisted material op at all — the gate required a "
            "material the ops vocabulary could not make — so the agent "
            "used raw bpy and hit the trap unaided."
        ),
        fix=(
            "Added ops/materials.assign_material, which sets the shader "
            "base colour AND diffuse_color together and is idempotent by "
            "name; registered it in OP_MODULE_NAMES so it appears in the "
            "manifest and in search_ops."
        ),
        guarded_by=(
            "tests/blender/test_material_op.py::"
            "test_the_render_actually_shows_the_colour — asserts on "
            "rendered PIXELS, not on properties"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="no-rotate-op-in-the-whitelisted-vocabulary",
        scope="harness_code",
        failure=(
            "Iteration 3, three_leg_stool: the agent spent 3 search_ops "
            "calls plus a dir() probe — 4 of its 16 — before its own "
            "reasoning recorded 'There's no rotate op', then improvised "
            "with raw attribute writes. It exhausted the budget without "
            "finishing."
        ),
        cause=(
            "blended.ops exposed primitives, booleans, arrays, bevel, "
            "heal, uv and three transforms, but nothing that rotates or "
            "places an object. The architecture claims the ops are the "
            "only sanctioned way to build, and a splayed-leg assembly is "
            "not buildable through it."
        ),
        fix=(
            "Added transforms.rotate_object_euler and "
            "transforms.move_object_to. Both SET rather than accumulate "
            "(idempotent chunks) and refresh the depsgraph, so the "
            "stale-matrix_world trap cannot bite through them."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py (6 assertions, including "
            "test_rotation_survives_apply_object_transform and "
            "test_both_ops_are_discoverable_through_search)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="object-dimensions-ignores-rotation",
        scope="harness_code",
        failure=(
            "A 0.1 x 0.1 x 1.0 m box rotated a quarter turn about Y still "
            "reported object.dimensions (0.1, 0.1, 1.0) while occupying "
            "1.0 m on world X."
        ),
        cause=(
            "object.dimensions is the local bounding box times scale and "
            "ignores rotation entirely. Found while writing the test for "
            "the new rotate op — the assertion was written the obvious "
            "way and failed."
        ),
        fix=(
            "Catalogued as drift, so it reaches the agent through the "
            "manifest's API-traps section. This matters directly for "
            "prompt v3, which tells the agent to verify stated sizes by "
            "measuring: without the trap catalogued, that instruction "
            "would have sent it to the wrong property. The acceptance "
            "gate already measured world extents via matrix_world."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py::"
            "test_rotation_reaches_matrix_world_immediately — asserts "
            "dimensions STILL ignores rotation, so the catalogued trap "
            "cannot go stale silently"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="base-z-certified-a-stool-that-rocks",
        scope="brief",
        failure=(
            "Iteration 4, three_leg_stool: FORM PASS with base_z +0.0000 m "
            "and total_height_z 0.4500 m — both exact — while a foot's sole "
            "was angled, so the stool stood on three edges. The human "
            "answered No to 'do all three feet sit flat on the ground' "
            "against a render the gate had already certified."
        ),
        cause=(
            "Grounding was one number: the minimum z of the whole object. "
            "A tilted end cap touching the floor at a single point drives "
            "that number to exactly 0.0000, indistinguishable from a flat "
            "sole. Contact is an AREA and was being measured as a HEIGHT. "
            "Rays cannot fix it either — from above they hit the seat, and "
            "from below they hit one point of an angled cap and report "
            "z=0 just as a flat one would."
        ),
        fix=(
            "Added GroundContactProbe: sums the world-space area of faces "
            "that reach the floor, face downward, and lie within "
            "SOLE_PLANARITY_TOLERANCE_M of z=0 near each expected foot, "
            "and requires MINIMUM_SOLE_CONTACT_AREA_M2. Zero area with "
            "rejected faces reports the tilt; zero with none reports a "
            "missing leg — different repairs, so they read differently. "
            "The reference stool in the tests had the same defect and now "
            "cuts its soles flat BEFORE snapping to ground; snapping "
            "first leaves nothing below the plane to cut."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_angled_sole_trips_the_ground_contact_probe — which also "
            "asserts base_z, the parity probes and the dimensions ALL "
            "still pass, so the fixture keeps reproducing the blindness"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-critique-explained-away-its-own-evidence",
        scope="process",
        failure=(
            "Iteration 4: the harness's visual critique answered Yes to "
            "'do all three feet sit flat on the ground', citing 63 "
            "vertices below z=0.005 in three clusters. Its own pixel scan "
            "of the front render had already measured the right-hand foot "
            "narrowing from 42 to 24 pixels over its last 3 rows while "
            "the left held 41 — and that measurement was dismissed in "
            "one clause as anti-aliasing. The human answered No."
        ),
        cause=(
            "The critique held both the evidence and the verdict, so it "
            "could rationalise the evidence to fit. A 5 mm threshold was "
            "chosen loose enough to admit a tilted cap, then the vertex "
            "count under it was read as proof of flatness. Neither step "
            "was wrong on its own; nothing forced them to disagree."
        ),
        fix=(
            "Moved the question out of the critique entirely. Flat-sole "
            "contact is now a deterministic gate (GroundContactProbe) "
            "that runs before any render is looked at, so this can never "
            "again be a judgement call about a picture. The general "
            "lesson is recorded here: when the visual pass measures "
            "something numerically and then argues with the number, the "
            "measurement belongs in the deterministic gate."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_angled_sole_is_reported_as_a_tilt_not_a_missing_leg — "
            "the tilt now arrives as a reported span in metres, not as "
            "something to interpret"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="search-matched-the-whole-query-as-one-string",
        scope="harness_code",
        failure=(
            "Iteration 4, three_leg_stool: 3 of 16 turns returned 'No "
            "operation matches' for 'boolean union', 'material assign' "
            "and 'assign material'. boolean_union and assign_material "
            "both existed; single-word retries found them immediately. "
            "19 percent of the turn budget was lost to word count, and "
            "the run then exhausted that budget without answering."
        ),
        cause=(
            "search_ops tested `query in haystack` — the raw query as one "
            "contiguous substring. That can never span the underscore in "
            "`boolean_union`, and it cannot survive reversed word order. "
            "The tool's own description only ever showed single-word "
            "examples, so the failure looked like an absent op rather "
            "than an unlucky phrasing — the same wrong conclusion as the "
            "no-rotate-op record below, reached without a missing op."
        ),
        fix=(
            "Both sides are split on non-alphanumerics and every query "
            "word must appear, so underscores and spaces are the same "
            "character to a searcher and word order stops mattering. A "
            "query with no words left is refused rather than matching "
            "everything, because all() of an empty list is True."
        ),
        guarded_by=(
            "tests/blender/test_transform_ops.py::"
            "test_multi_word_search_finds_the_op — parametrised over the "
            "three exact queries iteration 4 sent"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="budget-counted-messages-and-reported-calls",
        scope="harness_code",
        failure=(
            "Iteration 4 executed 20 tool calls and ended with 'Stopped "
            "after 16 tool calls in one turn without reaching an answer'. "
            "The iteration record therefore carried a tool_calls list of "
            "20 beside a message claiming 16."
        ),
        cause=(
            "The loop iterated `range(maximum_tool_calls_per_turn)` over "
            "assistant MESSAGES, and one message can carry several tool "
            "calls. The field name, the driver's --max-tool-calls flag "
            "and the exhaustion text all said calls; only the loop said "
            "messages, and it was the one enforcing the limit."
        ),
        fix=(
            "The budget counts calls as they are dispatched, charged "
            "before dispatch so a raising call still costs its turn. A "
            "message's calls are never half-answered, so the final count "
            "can overshoot the budget — it is reported as measured, with "
            "the configured budget beside it."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_the_budget_counts_calls_not_messages — three calls per "
            "message against a budget of four"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-healer-freed-the-faces-it-was-iterating",
        scope="harness_code",
        failure=(
            "Iteration 5, three_leg_stool: boolean_union raised "
            "'ReferenceError: BMesh data of type BMFace has been removed' "
            "at heal.py:57, inside its own healing step. The union had "
            "already applied and the addend had already been consumed, so "
            "the next call reported KeyError 'Stool_leg_0' not found. The "
            "agent spent 10 of its 16 calls rebuilding legs into a scene "
            "it could no longer describe, and shipped a mesh with 6 "
            "non-manifold edges, 57 boundary edges and no material."
        ),
        cause=(
            "weld_and_dissolve collected every zero-area face, then called "
            "bmesh.ops.collapse once per face while still holding that "
            "list. Collapsing an edge frees neighbouring faces, so reading "
            "`sliver_face.edges` off a later entry touched dead BMesh "
            "data. It only fires when two zero-area faces are adjacent, "
            "which is why unions had run clean until a splayed-leg seam "
            "produced a pair."
        ),
        fix=(
            "Every shortest edge is chosen BEFORE anything is collapsed, "
            "deduplicated by index (adjacent slivers can nominate the same "
            "edge), and collapsed in one bmesh.ops.collapse call."
        ),
        guarded_by=(
            "tests/blender/test_heal_ops.py::"
            "test_adjacent_slivers_do_not_kill_the_healer — two bow-tie "
            "quads sharing vertices. Zero-area QUADS are the fixture that "
            "works: dissolve_degenerate removes every collinear triangle "
            "before the collapse branch is reached, so a triangle fixture "
            "silently tests nothing (it was tried first and passed "
            "against the buggy code)."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-log-kept-a-preview-of-the-call-that-crashed",
        scope="harness_code",
        failure=(
            "Diagnosing iteration 5 needed the run_python source that "
            "raised. Both the iteration log and the transcript held its "
            "first 200 characters — 'import bpy\\nfrom blended.ops.booleans "
            "import boolean_union\\n\\nseat = bpy.data.objects[...' — and "
            "the rest was gone. The crash had to be re-derived from the "
            "traceback and reproduced by experiment instead."
        ),
        cause=(
            "AgentSession.send truncated at the point of RECORDING rather "
            "than the point of display: emit('tool', ...[:200]). The "
            "driver that consumes those events already previews them at "
            "400 characters for the console, so the clipping bought "
            "nothing and cost the ability to replay a run from its own "
            "record."
        ),
        fix=(
            "The event carries the whole call; display layers keep their own previews."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_the_recorded_call_is_replayable — asserts the LAST line "
            "of a >400-character source survives into the event"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-boolean-on-unlinked-objects-lied-and-ate-the-operand",
        scope="harness_code",
        failure=(
            "Iteration 8, three_leg_stool: the run ended with NO OBJECT AT "
            "ALL — 'no object named Stool in the scene'. Measured "
            "directly: boolean_union on two unlinked boxes returns "
            "normally, leaves the target at 8 vertices (no union "
            "happened), and destroys the addend anyway."
        ),
        cause=(
            "Construction and linking are separate ops, so add_box hands "
            "back an unlinked object. The boolean modifier cannot "
            "evaluate an operand the depsgraph has no instance of, so it "
            "applies as a no-op — and _apply_boolean then removed the "
            "operand regardless. The op reported success for a result it "
            "had not produced. The agent correctly concluded something "
            "was wrong, wiped every mesh in the scene to A/B-test the op "
            "in isolation, and destroyed its own finished stool doing it: "
            "5 of 16 calls on the experiment, plus the asset."
        ),
        fix=(
            "_apply_boolean checks both operands are in the scene BEFORE "
            "touching anything and raises UnlinkedOperand naming "
            "link_into_scene. Checked before mutation, so a refusal "
            "leaves the scene exactly as the agent left it."
        ),
        guarded_by=(
            "tests/blender/test_heal_ops.py::"
            "test_boolean_on_unlinked_objects_refuses_instead_of_lying — "
            "asserts the addend SURVIVES the refusal, then that the same "
            "call succeeds once both objects are linked"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="preflight-was-shorter-than-a-cold-start",
        scope="harness_code",
        failure=(
            "Iteration 6 refused to run: 'Model unreachable, refusing to "
            "score a run: http://localhost:11434: timed out'. The backend "
            "was healthy — the same one-token ping by curl answered in "
            "23.3 s."
        ),
        cause=(
            "PREFLIGHT_TIMEOUT_SECONDS was 10 while the preflight sends a "
            "real chat completion, so it paid the cloud model's cold "
            "start and called a working backend dead."
        ),
        fix=(
            "PREFLIGHT_TIMEOUT_SECONDS 10 -> 90: generous against a "
            "measured 23.3 s cold start, still far below "
            "REQUEST_TIMEOUT_SECONDS (300) so a genuinely dead endpoint "
            "is still reported rather than waited on."
        ),
        guarded_by=(
            "tests/blender/test_agent_loop.py::"
            "test_preflight_timeout_allows_a_cold_start"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-front-view-cannot-show-three-fold-symmetry",
        scope="process",
        failure=(
            "Iteration 10: the harness answered Yes to 'are the legs "
            "evenly spaced, first one on +X'. The human answered "
            "Unclear — 'the top left image looks off' — and was right. "
            "Measured from the render afterwards: the two visible feet "
            "sit at world x -0.0700 and +0.1392, which matches perfect "
            "0/120/240 spacing (predicted -0.0700 and +0.1400) to 0.8 "
            "mm. The geometry was correct and the view still could not "
            "show it."
        ),
        cause=(
            "In the front orthographic view the 120 and 240 degree legs "
            "project to the SAME world x and overlap into what reads as "
            "one leg, leaving an asymmetric two-leg silhouette. The "
            "contact sheet does not contain the information the question "
            "needs, so any confident answer from it — Yes or No — is "
            "luck. This is the second time a placement question was "
            "answered from a view that could not support it (see "
            "the-critique-explained-away-its-own-evidence)."
        ),
        fix=(
            "Two changes. GroundContactProbe now carries expected_radius_m "
            "and expected_angle_deg, and the measurement reports the flat "
            "sole's area-weighted centroid as a radius and a bearing — so "
            "placement is a number, not a look. And every scored run now "
            "exports a verified .glb beside its contact sheet, because a "
            "reviewer can turn a .glb and cannot turn a render."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_uneven_leg_spacing_trips_the_placement_check (gaps of "
            "105/120/135 deg) and ::"
            "test_correct_spacing_measures_the_specified_bearings"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-reference-stool-put-its-soles-inboard",
        scope="harness_code",
        failure=(
            "The new placement probe rejected the test suite's own "
            "reference stool: sole centre r=0.1281 m against a specified "
            "0.1400 +/- 0.0100. The agent's build (iteration 10) measured "
            "0.1400 exactly on all three feet."
        ),
        cause=(
            "The fixture stood each leg's base on z=0 and tilted it "
            "there, so the tilted end cap crossed the cut plane — high on "
            "the outer side, low on the inner. Cutting at z=0 then left a "
            "crescent rather than the full ellipse, and its centroid sat "
            "12 mm inboard of the axis. The agent's build was more "
            "correct than the reference it was being checked against."
        ),
        fix=(
            "The fixture drops each leg by leg_radius/cos(splay) plus a "
            "margin so the whole cap clears the plane, starts the base "
            "further out by overhang*tan(splay) so the axis crosses z=0 "
            "exactly on the foot circle, and lengthens the leg by exactly "
            "the drop. The tolerance was NOT loosened — that would have "
            "tuned the gate until the fixture passed."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_correct_spacing_measures_the_specified_bearings — "
            "asserts the measured bearings are exactly [0, 120, 240] and "
            "every radius is in tolerance"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-contact-sheet-could-not-see-the-legs",
        scope="harness_code",
        failure=(
            "Iterations 10 and 11: the human answered 'Unclear' then "
            "'the top left image still seems weird' to whether the legs "
            "were evenly spaced — twice, on stools whose spacing was "
            "later measured correct to 0.3 degrees. No amount of "
            "explaining fixed it, because the reviewer was right."
        ),
        cause=(
            "Of the four views, `top` is blind to a stool's legs (the "
            "0.16 m seat covers feet at 0.14 m) and `front` projects the "
            "120 and 240 degree legs to the SAME world x, overlapping "
            "them into what reads as one leg and leaving an asymmetric "
            "two-leg silhouette. Only `right` and `three_quarter` carried "
            "the information — the two views the human said looked "
            "right. The sheet did not contain the answer, so a confident "
            "verdict from it was luck either way."
        ),
        fix=(
            "Added a `bottom` view (0, 0, -1). From below nothing "
            "occludes the legs and the spacing is direct: measured off "
            "the new render's pixels, the three feet sit at 0.3, 120.0 "
            "and 240.2 degrees. Every scored run also exports a "
            "round-trip-verified .glb, which a reviewer can turn."
        ),
        guarded_by=(
            "tests/blender/test_capture_v2.py::"
            "test_the_sheet_can_see_underneath and ::"
            "test_every_named_view_is_actually_rendered"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-golden-snapshot-cannot-be-checked-by-re-import",
        scope="harness_code",
        failure=(
            "The first golden-snapshot suite re-imported the signed-off "
            ".glb and every assertion failed: the form gate, the "
            "dimensions and all three foot placements, on assets that had "
            "just passed those exact checks."
        ),
        cause=(
            "ingest.import_glb is the GENERATED-asset lane. It "
            "deliberately normalizes what it reads — joins the parts, "
            "recentres on the vertex CENTROID (the bounding-box centre since "
            "2026-10-07) and re-grounds — which is "
            "correct for an arbitrary generated mesh and destructive for "
            "evidence. A stool's vertex centroid is not its axis, so the "
            "round trip moved the feet off the 0.14 m circle the "
            "snapshot existed to pin."
        ),
        fix=(
            "Golden tests REPLAY the run's own recorded chunks instead "
            "(evaluate/replay.py), which needs no model and no network "
            "and reproduces the acceptance report number for number. The "
            ".glb files remain as evidence for a human to turn; they are "
            "not the measurement."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py (9 assertions "
            "including test_golden_stool_feet_are_where_they_were_"
            "signed_off, which pins contact area, radius and all three "
            "bearings)"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="convergence-was-blocked-by-the-harness-not-the-prompt",
        scope="process",
        failure=(
            "The loop ran 9 iterations without converging and hit its "
            "abort cap. Every prompt edit had been CONFIRMED on its "
            "stated target (v2 terminal state: 17 calls -> 3; v3 measure "
            "your numbers: base_z -0.0043 -> +0.0000; v4 stop searching "
            "for listed ops: 16 calls -> 5; v5 contact not height: sole "
            "area 0.000000 -> 0.001459 m2) and the suite still would not "
            "produce three clean runs."
        ),
        cause=(
            "Three of the six stool runs failed on harness defects, not "
            "prompt wording — a healer that freed the faces it was "
            "iterating, a boolean that silently no-opped on unlinked "
            "objects and ate the addend, a preflight shorter than a cold "
            "start. Each iteration surfaced a NEW latent defect, so the "
            "three-consecutive-clean count could never start. The final "
            "two blockers were not the prompt either: a writer too weak "
            "to place geometry (deepseek-v4-flash) and a 16-call budget "
            "too small to build, verify AND report — iteration 10 built "
            "a flawless asset in 17 calls and had nothing left to say it "
            "with."
        ),
        fix=(
            "Fixed 15 harness defects with a guard each, swapped the "
            "writer to deepseek-v4-pro (the eye was never the "
            "bottleneck: it correctly flagged the broken mesh in "
            "iteration 5 and the empty scene in iteration 8), and raised "
            "the budget to 24 from the measured 17. Convergence followed "
            "immediately: iterations 11, 12 and 13, at 7, 10 and 9 "
            "calls. The process lesson is that a prompt cannot be tuned "
            "through an unstable harness, and the classification "
            "discipline — only a prompt failure may edit the prompt — is "
            "what kept that visible instead of hiding it in reworded "
            "instructions."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py::"
            "test_the_pinned_prompt_is_the_one_that_converged — asserts "
            "the pinned revision's content hash, so the signed-off TEXT "
            "cannot drift after the fact"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-critique-called-a-clean-rebuild-a-failure",
        scope="process",
        failure=(
            "Iteration 14: every gate passed and the human confirmed "
            "the render, but the examiner raised a deviation anyway — "
            "the taller_stool follow-up re-ran add_cylinder / "
            "boolean_union / ground-cut at 0.55 m instead of editing "
            "the existing stool, which v6 forbids in words. It was "
            "classified harness_code, on the reasoning that the "
            "refinement gate was blind to it. The human ruled the "
            "rebuild ACCEPTABLE: it preserved 2 dimensions and 3 foot "
            "placements exactly, 0 disturbed. The finding was a FALSE "
            "POSITIVE, and a run that had passed was nearly recorded "
            "as a failure in an append-only log."
        ),
        cause=(
            "The examiner scored the run against the prompt's wording "
            "rather than against the result, and treated a rule the "
            "harness states as a rule the harness has verified is "
            "wanted. 'The gate cannot see X' is a statement about the "
            "gate; whether X should fail a run is a question for the "
            "human, and it was answered by assumption instead. Note "
            "the direction: the earlier critique failure "
            "(the-critique-explained-away-its-own-evidence) was a MISS, "
            "this one is a FALSE ALARM. Both are harness_critique "
            "failures, which is why that classification exists."
        ),
        fix=(
            "Object identity is stamped and READ BACK after every "
            "follow-up (evaluate/object_identity.py), so edit-versus-"
            "rebuild is measured rather than argued — and recorded as "
            "evidence in `IterationRecord.refinement_locality`, never "
            "consulted by `passed`. v7 softens the prompt to match what "
            "is actually enforced: editing is preferred for its cost, "
            "preserving settled detail is the binding requirement. The "
            "general lesson: when the critique wants to fail a run on a "
            "rule no gate enforces, that is a question for the human, "
            "not a finding."
        ),
        guarded_by=(
            "tests/pure/test_object_identity.py::"
            "test_a_rebuild_is_recorded_as_evidence_and_never_gated — "
            "asserts a rebuilt object reads as not edited_in_place AND "
            "that IterationRecord.passed stays True with that evidence "
            "present, so wiring locality into the gate breaks the test "
            "rather than silently reversing the ruling."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="multi-step-refinement-was-scored-against-the-original-brief",
        scope="harness_code",
        failure=(
            "Iteration 23, the first run with three refinement steps: "
            "the FIRST build passed both gates, but all three "
            "REFINEMENT steps failed — wider_seat failed for still "
            "having a 0.40 m seat (expected 0.32), thicker_legs failed "
            "for having the 0.40 m seat and 0.55 m height the previous "
            "steps had correctly produced. The agent's build was "
            "right; the scorer was wrong."
        ),
        cause=(
            "The driver scored every step against "
            "refine_brief(ORIGINAL_brief, step) instead of the brief "
            "refined by its predecessors. A multi-step sequence is "
            "cumulative: step N's spec is the original brief with steps "
            "1..N applied, and scoring step N against the original "
            "reports every earlier step's change as a failure."
        ),
        fix=(
            "The driver accumulates step_brief = refine_brief(step_brief, "
            "step) per step and scores each outcome against it; replay "
            "and the golden tests apply exactly the steps the record "
            "carries in refinement_locality (evaluate/replay.py::"
            "steps_applied), so records from before the suite gained "
            "steps are not graded against steps they never ran."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py::"
            "test_golden_stool_measures_the_signed_off_numbers — the "
            "v10 stool snapshot pins the 0.40 m seat, which only "
            "measures correctly when all three steps are composed"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-boolean-that-changed-nothing-returned-normally",
        scope="harness_code",
        failure=(
            "Iteration 33, planter_box: the agent's cavity sat 0.01 m "
            "short of the box top, boolean_difference RETURNED NORMALLY "
            "with the mesh unchanged, the gate caught 2 disconnected "
            "components, and the agent spent 21 tool calls debugging an "
            "op that was never wrong — reading its source, trying "
            "FAST/MANIFOLD solvers, wiping the scene — before "
            "exhausting its budget with no object at all."
        ),
        cause=(
            "_apply_boolean verified the operands were linked (the "
            "iteration-8 lesson) but never verified the boolean had "
            "DONE anything. A cutter that does not intersect the target "
            "applies as a silent no-op, and the agent cannot tell 'the "
            "op failed' from 'my geometry was wrong' — so it "
            "investigated the op."
        ),
        fix=(
            "BooleanNoOp: after applying, the op compares vertex "
            "positions (rounded to 1e-6) before and after and raises "
            "when nothing moved. Counts are NOT compared — the EXACT "
            "solver cuts a tilted cap flat while preserving counts "
            "exactly (measured: 136 verts / 76 polys before and after "
            "trim_soles_flat, z range -0.0269 -> 0.0000), so a "
            "count-based guard fires falsely on legitimate trims."
        ),
        guarded_by=(
            "tests/blender/test_csg_ops.py::"
            "test_non_intersecting_cutter_raises_instead_of_silently_"
            "no_oping — a cutter outside the target must raise and "
            "leave both objects intact. Plus the full Blender suite: "
            "every trim_soles_flat call exercises the guard against "
            "false positives."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="assign-material-destroyed-a-shared-datablock",
        scope="harness_code",
        failure=(
            "Iteration 46, crate_with_lid: the agent assigned "
            "'CrateWood' to the crate body, then assigned the same "
            "name to the lid. The assembly failed the material gate "
            "with CrateBody 0 assigned in 1 slot — everything else "
            "passed. The agent used the documented op correctly."
        ),
        cause=(
            "assign_material was idempotent by REMOVING the existing "
            "datablock and creating a fresh one. A material name is a "
            "shared resource across parts: removing it dangles every "
            "other object's slot to None. Single-object briefs never "
            "hit it; the assembly brief exposed it on its first run."
        ),
        fix=(
            "assign_material reuses the existing datablock in place — "
            "updates the colours, reassigns to the caller — so "
            "references from other objects survive. Idempotency is "
            "preserved (one datablock, one slot per object), only the "
            "destruction is gone."
        ),
        guarded_by=(
            "tests/blender/test_material_op.py::"
            "test_a_shared_material_name_survives_reassignment — two "
            "objects sharing a name must both keep their assignment "
            "and reference the SAME datablock"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-vision-model-cannot-yet-guard-visible-defects",
        scope="process",
        failure=(
            "Stage-7 measurement, 2026-08-22, scripts/measure_eye.py "
            "(since deleted, see the-eye-scorer-counted-a-denial-as-a-"
            "sighting): "
            "7 fixtures x 2 conditions against minimax-m3:cloud. NoRef "
            "recall 3/5 (0.60) with 2/2 false positives; Ref recall 2/5 "
            "(0.40) with 2/2 false positives. The defect class that "
            "started the loop — sealed_drain — was missed in BOTH "
            "conditions: the eye noticed the hole difference and "
            "dismissed it as 'rendering/opacity'. floating_seat was "
            "caught WITHOUT the reference and missed WITH it: the eye "
            "wrote 'I cannot identify any meaningful visual "
            "differences... they appear essentially identical' — the "
            "reference invited rationalization. The controls drew "
            "false-positive defect language in every condition."
        ),
        cause=(
            "An unmeasured instrument was assumed to be a gate. The "
            "TikZ study's finding held: a VLM critic is biased toward "
            "accepting, and a reference image does not fix the bias — "
            "it reframes the task as 'explain why these match' and the "
            "eye complies. The sealed_drain miss matters most: it is "
            "the exact wrong-object failure the whole loop exists to "
            "catch, and no render-based instrument caught it."
        ),
        fix=(
            "None. The pre-decided branch applied: Ref recall (0.40) "
            "did not beat NoRef (0.60) by >= 0.2, so no reference "
            "wiring was added to VisionDescriber and no critique code "
            "changed. The measurement is the outcome: the human gate "
            "stays, and the eye stays advisory. The deterministic "
            "gates are the only pass/fail authority until a future "
            "measurement beats this one."
        ),
        guarded_by=(
            "_evaluate/eye_measurement.jsonl holds the raw replies, but "
            "its NUMBERS are void: the scorer that produced them "
            "counted denials as sightings (see "
            "the-eye-scorer-counted-a-denial-as-a-sighting). The live "
            "guard is now `make calibrate-eye`, whose "
            "_evaluate/eye_calibration.json must license a machine "
            "verdict before the loop will accept one — "
            "tests/pure/test_examiner.py::"
            "test_calibration_problems_are_loud asserts an examiner "
            "under threshold is refused."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-eye-scorer-counted-a-denial-as-a-sighting",
        scope="harness_code",
        failure=(
            "In _evaluate/eye_measurement.jsonl both clean controls "
            "scored false_positive=true in BOTH conditions, and "
            "floating_seat/NoRef scored hit=true, off replies that "
            "said the opposite: \"I don't see any missing, misplaced, "
            'floating, or duplicated parts" and "no floating, '
            'intersecting, or duplicated parts". The recorded numbers '
            "(NoRef 3/5 hits with 2/2 false positives, Ref 2/5 with "
            "2/2) were instrument artifacts, not measurements of the "
            "eye."
        ),
        cause=(
            "scripts/measure_eye.py::is_hit did case-insensitive "
            "SUBSTRING matching over a flat defect vocabulary, so a "
            "denial containing the defect word matched as a sighting — "
            "negation was invisible to the scorer. Worse, control "
            'scoring called it with part_words=("",), and '
            'any("" in text) is always true, so any defect word '
            "anywhere in a reply was a false positive by construction."
        ),
        fix=(
            "The eye now answers in a CLOSED TAG VOCABULARY "
            "(evaluate/examiner.py: DEVIATION_TAGS + no_deviation + "
            "cannot_tell) inside a JSON contract, and scoring is exact "
            "tag comparison — so negation is not a scoring surface at "
            "all. A reply that is not the contract raises rather than "
            "being pattern-matched, and every view is examined in both "
            "image orders with only order-consistent tags surviving. "
            "scripts/measure_eye.py is gone; scripts/calibrate_examiner.py "
            "replaces it and writes _evaluate/eye_calibration.json, "
            "which must license a machine verdict before the loop will "
            "accept one."
        ),
        guarded_by=(
            "tests/pure/test_examiner.py::"
            "test_a_denial_is_not_a_deviation — the exact denial string "
            "from the bad measurement, which must yield zero deviations"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="the-convergence-rule-was-never-executable",
        scope="process",
        failure=(
            "evaluate/iteration_log.py::consecutive_clean_runs had no "
            "caller anywhere in the repository (repo-wide grep: the "
            "definition only), and it required every brief to appear "
            "under the SAME iteration number. On iterations 47-51 — "
            "the very cycle that earned the v10 pin, one brief per "
            "iteration — it returns 0. The convergence claim was "
            "verified by hand while the executable rule disagreed with "
            "it."
        ),
        cause=(
            "The rule was written against a two-brief suite where one "
            "iteration held every brief. The five-brief protocol runs "
            "ONE brief per iteration, and because nothing ever called "
            "the function, no test and no run noticed the shape change."
        ),
        fix=(
            "converged_suite_cycles builds a cycle from the NEWEST "
            "record per brief, walking iterations downwards, and "
            "returns (trailing clean cycles, the one prompt identity "
            "they ran). The orchestrator calls it every round, so the "
            "rule is executed on the same evidence a person would "
            "read."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_the_v10_cycle_is_one_converged_cycle — reads the real "
            "_evaluate logs and requires the recorded v10 cycle to "
            "count, plus cases for mixed identities, abstention, "
            "deviations and an unexamined run"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="two-same-size-images-fused-so-the-examiner-was-blind",
        scope="harness_code",
        failure=(
            "The first live examiner call, 2026-08-22 against "
            "qwen3-vl:8b on native ollama 0.32.14, answered "
            "'The reference image (first image) is not provided' and "
            "tagged cannot_tell. Probing the wire: two 512x512 renders "
            "in one /api/chat message cost 1055 prompt tokens — the "
            "same as ONE image (1047) — the model answered '1' to 'how "
            "many distinct images did you receive?', and sending "
            "[planter, stool] made it describe the planter and ignore "
            "the stool. The examiner had never been shown the render "
            "under review; it was comparing the reference to itself."
        ),
        cause=(
            "Two layers compounding. Ollama's renderer prepends "
            "[img-0][img-1]... back to back for a message that carries "
            "images and no explicit placeholders "
            "(model/renderers/image_tags.go), and llama.cpp's mtmd "
            "tokenizer merges CONSECUTIVE same-size bitmaps into video "
            "frames for the qwen-vl family "
            "(clip_model_n_temporal_merge == 2). Reported as "
            "ollama/ollama#17321 and ggml-org/llama.cpp#24303, both "
            "open. Every render this harness makes comes out of the "
            "same CaptureSettings, so every examiner pair is the same "
            "size: the merge case was not an edge case, it was the "
            "only case. Nothing logged a warning at any layer."
        ),
        fix=(
            "loop.py::_image_placeholders emits one labelled `[img]` "
            "per image with text between them, so the renderer "
            "substitutes them in order and no two bitmaps are "
            "consecutive parts. Prompt tokens for the same pair went "
            "1055 -> 2089; the identical pair then scored "
            "no_deviation and stool-vs-planter scored missing_part. "
            "VisionDescriber.describe is the only place images are "
            "built for the eye, and it is now unconditional: the "
            "writer's path sends ONE contact sheet (render_views "
            "composites five views into a single PNG) so it was never "
            "bitten, but it carries a placeholder too, so a caller that "
            "ever attaches several images cannot silently lose them."
        ),
        guarded_by=(
            "tests/pure/test_vision_transport.py::"
            "test_no_two_placeholders_are_adjacent and "
            "::test_every_image_gets_its_own_placeholder — asserted on "
            "the payload at the _request boundary, because describe() "
            "builds its own client and the wire is the only honest "
            "place to see what the model will be shown"
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="a-local-8b-eye-scored-0.20-and-may-not-judge",
        scope="process",
        failure=(
            "First real calibration, 2026-08-22: `make calibrate-eye` "
            "against qwen3-vl:8b-instruct on big (native ollama "
            "0.32.14, one RTX 3090), 100 eye calls over 10 fixtures x "
            "5 views x 2 orders in 228 s. sensitivity 0.20 (1/5), "
            "control specificity 1.00 (5/5). Only lid_offset was "
            "caught. missing_leg scored detected=True in a --only run "
            "four minutes earlier and detected=False in the zoo — at "
            "temperature 0.2 the bottom view's two orders disagreed, "
            "and order-consistency correctly dropped it. sealed_drain "
            "drew material_missing where missing_feature was expected: "
            "a sighting under the wrong name, which the tag "
            "intersection does not credit. The thinking sibling "
            "qwen3-vl:8b could not be used at all — on a "
            "stool-vs-planter pair it emitted 30387 tokens into "
            "`thinking`, hit done_reason=length against a 32k context "
            "and returned EMPTY content after 331 s."
        ),
        cause=(
            "An 8B eye at 512x512 is simply under-sensitive to the "
            "defect classes this suite cares about, and the controls "
            "prove it is not the opposite failure: 5/5 clean assets "
            "drew zero deviations, so it is not trigger-happy, it does "
            "not see. RESP's +0.49 recall from a reference is a delta, "
            "not a floor — the absolute level is the model's."
        ),
        fix=(
            "None, deliberately. MINIMUM_FIXTURE_SENSITIVITY (0.6) and "
            "REQUIRED_CONTROL_SPECIFICITY (1.0) were NOT moved and "
            "prompts/examiner.md.j2 was NOT softened; either would have "
            "bought a licence by lowering the bar the licence exists to "
            "certify. _evaluate/eye_calibration.json recorded the "
            "measurement under identity "
            "qwen3-vl:8b-instruct+examiner:60a9920cb938, machine "
            "verdicts stayed unlicensed, and --examiner none remains the "
            "driver default. The file has since been overwritten by the "
            "calibrations of other eyes (git: 1c65544, 0cf56b6, de30d79) "
            "and the 8B run is retained nowhere in the repository; this "
            "record is its only trace. The next lever is a stronger eye, not more "
            "prompt engineering — BlenderGym's finding that verifier "
            "quality is the compute worth buying."
        ),
        guarded_by=(
            "tests/pure/test_examiner.py::"
            "test_calibration_problems_are_loud pins the refusal: a "
            "sensitivity of 0.4 and a calibration for another eye each "
            "yield a problem, and the driver exits 1 on a non-empty "
            "problem list. The 2026-08-22 live check (`run_agent_task.py "
            "--examiner auto` exited 1 in 0.7 s with 'sensitivity 0.20 < "
            "0.6: not distinguishable from the no-reference rubber "
            "stamp' and wrote no iteration or verdict row) is not "
            "reproducible now: the calibration it ran against is gone."
        ),
        recorded_on="2026-08-22",
    ),
    MistakeRecord(
        identifier="open-meshes-were-never-normal-checked",
        scope="harness_code",
        failure=(
            "Every open prop shipped with zero normals checking: the "
            "parity-ray flipped-normal test only runs on closed manifold "
            "meshes, and the analyzer recorded 0 flipped triangles for "
            "every open mesh. scp measured the distinction: edge "
            "contiguity passes an island wound inside-out, and decimation "
            "and boolean work create inverted facets on open meshes too "
            "(backpack 0 -> 15/164 facets, body 0 -> 5/749). Recalculating "
            "normals does not fix them — the geometry has folded."
        ),
        cause=(
            "The inverted-facet test asks whether a face agrees with "
            "ITSELF (winding normal against its own stored corner "
            "normals), which needs no closed solid, but the old code "
            "gated every normals check on the closed-manifold branch."
        ),
        fix=(
            "Added facet_disagrees_with_its_normals (pure arithmetic) and "
            "_count_inverted_facets, called UNCONDITIONALLY in "
            "analyze_object; MeshReport.inverted_facet_count and "
            "MeshBudget.allow_inverted_facets gate it. Per-corner normals "
            "match what glTF ships, so the file-level report reads the "
            "same numbers back out of the .glb."
        ),
        guarded_by=(
            "tests/blender/test_flipped_normals.py::"
            "test_open_mesh_inverted_facet_is_counted"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="the-scene-is-not-the-shipped-file",
        scope="harness_code",
        failure=(
            "Export verification re-imported the .glb into Blender, so "
            "scene counts described geometry that never shipped: scp's "
            "'5k' tier shipped 9,488 triangles, and a file report and a "
            "raw bmesh disagreed 0 vs 6,196 boundary edges because one "
            "welded by position and one counted UV seams."
        ),
        cause=(
            "export_apply=True bakes modifiers, so scene polygon counts "
            "drift from the artifact; the re-import is not the artifact."
        ),
        fix=(
            "Added src/blended/export/glb_report.py (stdlib only): parses "
            "the file's own bytes, counts POSITION-welded topology, "
            "inverted facets from the stored NORMAL accessor, and root "
            "node names. ExportReport.round_trip_failures now also gates "
            "file triangle count vs pre-export, file boundary edges vs "
            "the welded re-import, file inverted facets, root node names, "
            "and file extents under the exporter's axis permutation."
        ),
        guarded_by=(
            "tests/blender/test_glb_file_report.py::test_file_and_welded_reimport_agree"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="nearest-vertex-is-not-the-surface",
        scope="harness_code",
        failure=(
            "scp's palm-to-weapon distance read 60 mm against mesh "
            "VERTICES and 6.5 mm against the mesh SURFACE: on box "
            "geometry the nearest vertex is a far corner. Two wrong root "
            "causes were announced off the vertex artifact."
        ),
        cause=(
            "closest_point_on_mesh was measured against vertices; a "
            "nearest-vertex implementation answers 'how far is a corner', "
            "not 'how far is the surface'."
        ),
        fix=(
            "Added src/blended/analyze/pair_checks.py: analyze_pair "
            "measures interpenetration via BVH overlap with the narrow "
            "phase _count_self_intersecting_pairs uses, and separation "
            "via closest_point_on_mesh in the other object's local "
            "space. NoInterpenetrationSpec is scored in "
            "_measure_relations; crate_with_lid now asserts the lid does "
            "not sink into the body."
        ),
        guarded_by=(
            "tests/blender/test_pair_checks.py::"
            "test_separation_is_measured_on_the_surface"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="a-hole-fill-can-cost-more-than-it-buys",
        scope="harness_code",
        failure=(
            "scp measured hole filling on valkyrie_body and REJECTED it: "
            "every ordering traded open edges for non-manifold edges and "
            "inverted facets — 241 boundary / 0 non-manifold / 5 "
            "inverted became 36 / 18 / 21. An inverted facet is a "
            "wrongly-lit patch visible in normal gameplay; an open "
            "boundary costs only gib caps."
        ),
        cause=(
            "Filling a boundary shared by two shells creates non-manifold "
            "edges; filling a folded boundary creates inverted facets."
        ),
        fix=(
            "cleanup_mesh keeps the fill (props are closed solids) but "
            "copies the mesh before the pass and reverts when "
            "non_manifold_edge_count or inverted_facet_count rises — "
            "CleanupReport.reverted_hole_fills reports the reversal and "
            "the holes stay open, reported as remaining failures."
        ),
        guarded_by=(
            "tests/blender/test_ingest_cleanup.py::test_a_regressing_fill_is_reverted"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="a-guessed-visual-threshold-fails-good-assets",
        scope="process",
        failure=(
            "scp's pre-calibration visual-gate guesses (IoU >= 0.980, "
            "RMSE <= 0.030) failed all twelve views of a good asset. A "
            "threshold is a measurement of the harness's own render "
            "noise, not a number to copy."
        ),
        cause=(
            "Thresholds copied from a different harness (a clothed "
            "humanoid at 512x768 EEVEE with film_transparent alpha) do "
            "not transfer to opaque 512x512 Workbench captures."
        ),
        fix=(
            "scripts/calibrate_visual_gate.py measures: golden-vs-itself "
            "control must read exactly IoU 1.0 / RMSE 0.0, clean replays "
            "of the pinned iterations bound the thresholds with margins, "
            "and a Decimate mutation must land outside them or the "
            "calibration refuses to write. The gate refuses to run "
            "without the calibration file."
        ),
        guarded_by=(
            "tests/pure/test_visual_gate_verdict.py::"
            "test_gate_refuses_to_run_uncalibrated"
        ),
        recorded_on="2026-08-23",
    ),
    MistakeRecord(
        identifier="extent-rank-tie-break-cannot-canonicalise-a-cube",
        scope="harness_code",
        failure=(
            "The first canonical_orientation draft ranked the three world "
            "extents by POSITION (stable argsort, ties broken by axis "
            "index) and asserted afterwards that the depth axis held rank "
            "1. On an isotropic object — extents (1, 1, 1) — the rule "
            "selected X as the source axis, applied a quarter turn about "
            "Z, and then its own post-condition read rank 0, so "
            "apply_canonical_depth_axis raised RuntimeError on a perfect "
            "cube. Every 3DCodeBench script ends with that call, so it "
            "would have converted a scoring question into ERR_EXEC."
        ),
        cause=(
            "'Middle extent' is a VALUE, not a position. With two equal "
            "extents the middle axis is ambiguous while the middle number "
            "never is, and a position-based rule both picks an arbitrary "
            "axis and then fails to recognise its own output as correct — "
            "the rule was not idempotent, which is the one property a "
            "re-baked epilogue must have."
        ),
        fix=(
            "canonical_depth_axis_rotation_euler_rad now compares against "
            "middle_extent_m (sorted(extents)[1]) and returns identity "
            "whenever depth_axis_holds_middle_extent is already true; the "
            "post-condition asserts that same value invariant with a "
            "relative tolerance instead of a rank equality. Reported rank "
            "is kept as a diagnostic and never asserted on. The GLB audit "
            "in scripts/orientation_policy_sim.py carries the matching "
            "tie tolerance, so a radially symmetric object is not "
            "reported as off-policy (measured: Bottle, Jar, Pillar, "
            "Auger, Lid, Wineglass all tie within 0.2% of max extent)."
        ),
        guarded_by=(
            "tests/pure/test_canonical_orientation.py::"
            "test_a_cube_needs_no_rotation, plus "
            "test_ties_are_deterministic_and_settle_after_one_call and "
            "tests/blender/test_canonical_orientation_op.py::"
            "test_a_second_call_is_a_no_op"
        ),
        recorded_on="2026-09-03",
    ),
    MistakeRecord(
        identifier="a-tool-schema-without-descriptions-is-a-list-of-names",
        scope="harness_code",
        failure=(
            "First live turn on the Claude Code lane: the writer answered "
            '"I\'m unable to create the Crate cube right now" and made '
            "ZERO tool calls, with a valid schema in the request."
        ),
        cause=(
            "envelope_schema built each oneOf variant from a tool's NAME "
            "and parameters and dropped its description. On the HTTP lanes "
            "descriptions ride the API's own `tools` field, so nothing "
            "else had ever needed them explicitly — this lane has no such "
            "field, so the model was handed seven names it knew nothing "
            "about."
        ),
        fix=(
            "Each variant carries `description` from the same "
            "TOOL_SCHEMAS entry as its arguments schema. Verified live: "
            "the same prompt then called run_python on the first turn."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_the_envelope_pins_each_tool_to_its_own_arguments"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-agent-cli-reaches-for-its-own-tools",
        scope="harness_code",
        failure=(
            "chat_e2e --only object on claude-code:sonnet: 0 tool calls, "
            'FAIL, and the answer read "Every tool call I make '
            "(run_python, list_scene, search_ops) is being rejected with "
            "'No such tool available'\"."
        ),
        cause=(
            "The harness system prompt describes the six tools as "
            "callable, which is true on every lane that hands them over "
            "natively. Claude Code is itself an agent harness, so the "
            'model emitted native tool_use blocks — and `--tools ""` '
            "correctly refused them. The structured envelope was "
            "available and simply never used."
        ),
        fix=(
            "TOOL_PROTOCOL_NOTE is appended to the system prompt in the "
            "same `if tools:` branch that adds --json-schema, so the "
            "schema and the instruction for using it can never ship "
            "apart. The scenario then passed with one run_python call, "
            "gate PASS, dims 0.600x0.400x0.500."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_the_command_disables_every_built_in_capability"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-gate-that-cannot-see-the-scene",
        scope="harness_code",
        failure=(
            "A live GUI turn built `Barrel` with 192 faces and a "
            "WoodMaterial; run_python reported GATE PASS, inspect_object "
            "reported GATE PASS, render_views returned a contact sheet — "
            "and bpy.context.scene.objects held only Camera, Cube and "
            "Light. The viewport never changed and the object would have "
            "been absent from any export."
        ),
        cause=(
            "run_chunk located the gated object with "
            "bpy.data.objects.get() and never asked whether it was "
            "LINKED. Every downstream check works on the datablock: the "
            "mesh analyzer reads the mesh, and the capture path links a "
            "copy into a temporary scene of its own to render it — so a "
            "chunk that forgot link_into_scene passed every gate while "
            "changing nothing the user can see. The failure message even "
            "said 'not found in scene' while reading bpy.data."
        ),
        fix=(
            "_gate_capture_export refuses before it analyzes, through "
            "harness.invisibility_failure(): one ordered walk that names "
            "the cause (unlinked / excluded collection / hidden / "
            "hide_render) so the writer can fix it from the tool result. "
            "inspect_object calls the SAME function, so the writer's own "
            "check cannot contradict the gate, and the "
            "missing-datablock message no longer claims to be about the "
            "scene."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_an_unlinked_object_fails_the_gate, "
            "test_a_linked_object_passes_the_same_gate and "
            "test_every_invisibility_cause_is_named_not_just_detected"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="visible_get-covers-four-causes-hide_render-covers-none",
        scope="harness_code",
        failure=(
            "Probing the gate for siblings of the unlinked-object hole "
            "found three more, all reporting GATE PASS: hide_viewport = "
            "True, hide_set(True), and membership of a collection "
            "excluded from the view layer. A fourth, hide_render = True, "
            "passed while halving the harness's own contact sheet "
            "(634280 bytes with the object, 318310 without) — the eye "
            "was reviewing a render the asset was absent from."
        ),
        cause=(
            "The first fix tested exactly one symptom "
            "(name in scene.objects) instead of the property that "
            "matters: can this be seen. Object.visible_get() is False "
            "for all four visibility causes INCLUDING the unlinked one, "
            "so the narrow test was both incomplete and redundant. "
            "hide_render is the exception in the other direction: "
            "visible_get() stays True, so a visibility-only rule would "
            "have missed the one cause that breaks the render the model "
            "is judged by."
        ),
        fix=(
            "invisibility_failure() walks scene membership, view-layer "
            "membership, visible_get() and hide_render in that order, "
            "returning the cause-specific instruction. Both run_chunk "
            "and inspect_object call it."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_every_invisibility_cause_is_named_not_just_detected, "
            "test_an_unrenderable_object_fails_even_though_it_is_visible "
            "and test_inspect_object_agrees_with_the_gate"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="view-layer-membership-lags-the-link",
        scope="harness_code",
        failure=(
            "The first draft of the visibility gate turned 9 green "
            "Blender tests red, accusing every freshly built object of "
            "sitting in an excluded collection. The SAME trap then bit "
            "in the other direction: the transform gate let a "
            "`scale = (1, 1, 0)` chunk through with GATE PASS, because "
            "matrix_world still held the pre-assignment value."
        ),
        cause=(
            "Evaluated scene state lags an assignment. An object linked "
            "by the chunk that just ran appears in "
            "bpy.context.scene.objects immediately but NOT in "
            "bpy.context.view_layer.objects, and a scale assigned by "
            "that chunk is NOT yet in matrix_world, until the depsgraph "
            "catches up. Both probes that designed the rules had called "
            "view_layer.update() by hand, so both rules looked correct "
            "in isolation and read the previous frame in the gate."
        ),
        fix=(
            "One helper, harness._synchronise_view_layer(), called at "
            "the top of BOTH invisibility_failure() and "
            "degenerate_transform_failure(). Rule: any scene-state "
            "assertion made immediately after a chunk runs syncs first "
            "— view-layer membership, matrix_world, dimensions and "
            "visible_get() are all evaluated state."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_a_linked_object_passes_the_same_gate, "
            "test_the_gate_reports_a_broken_transform_through_run_chunk "
            "and tests/blender/test_task_loop.py::"
            "test_task_succeeds_first_round"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-object-matrix-is-outside-the-mesh-analyzer",
        scope="harness_code",
        failure=(
            "Four broken transforms all reported GATE PASS with a "
            "perfect mesh report: scale.x = 0 (world extent 0, 1, 1), "
            "scale.x = 1e-9, location.x = NaN (world extent nan, 1, 1), "
            "and scale.x = inf — the last of which makes the glTF "
            "export raise RuntimeError on geometry the gate had just "
            "called clean."
        ),
        cause=(
            "analyze_object measures the EVALUATED mesh (so modifiers "
            "are covered) but in the object's LOCAL space, which puts "
            "the object matrix outside everything it can see. A NaN "
            "transform is the worst case: the mesh measures perfect, "
            "the gate passes, and every world-space number the model "
            "prints back to itself is NaN."
        ),
        fix=(
            "degenerate_transform_failure() refuses non-finite matrix "
            "elements and collapsed axes, testing the SCALE LENGTHS' "
            "anisotropy (min/max < 1e-6) rather than the determinant — "
            "a legitimately tiny object scaled 0.001 uniformly has "
            "determinant 1e-9, so a determinant threshold would have "
            "refused real work. A 10x stretch, a 0.001 uniform scale "
            "and a 0.01-thin panel all still pass."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_a_collapsed_or_non_finite_transform_fails_the_gate and "
            "test_legitimate_scales_are_left_alone"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-domain-reports-had-the-same-hole-as-the-gate",
        scope="harness_code",
        failure=(
            "Auditing the rig/weight/animation reports for the gate's "
            "own blind spot found three: rig_report counted a mesh as "
            "BOUND while its Armature modifier was switched off in "
            "viewport or render; weight_report reported non-zero "
            "weights for a vertex group whose name matched no bone (one "
            "typo away, and it deforms nothing); animation_report "
            "counted keyframes on MUTED fcurves and keyframes outside "
            "the scene's frame range as animation."
        ),
        cause=(
            "Each report measured the presence of a thing rather than "
            "its effect: a modifier exists, a weight is non-zero, a "
            "keyframe is stored. Every one of those can be true while "
            "the mesh never deforms and the object never moves — the "
            "same mistake the mesh gate made by measuring the mesh and "
            "not what the user could see."
        ),
        fix=(
            "bound_mesh_names now means DEFORMING (enabled in viewport "
            "and render) with disabled_modifier_mesh_names reported "
            "beside it; weight_report cross-checks group names against "
            "the deforming armature's bones "
            "(groups_without_bones / bones_without_groups, both empty "
            "for an unrigged mesh so ordinary modelling is never "
            "accused); animation_report adds muted_fcurve_count and "
            "keyframes_outside_frame_range_count. chat_e2e asserts all "
            "of them are clean, so the criteria mean what they say."
        ),
        guarded_by=(
            "tests/blender/test_domain_report_blind_spots.py (8 tests, "
            "each pathology beside its control) and "
            "scripts/chat_e2e.py::check_rig / check_weights / "
            "check_animation"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="an-experiment-displaced-the-pins-own-evidence",
        scope="process",
        failure=(
            "test_the_v10_cycle_is_one_converged_cycle went red with "
            "'the recorded v10 cycle (iterations 47-51) must count as "
            "converged: assert 0 >= 1' — without anyone touching those "
            "records, the convergence rule, or the prompt. Five runs "
            "qualifying a new WRITER had been appended to "
            "_evaluate/iterations.jsonl."
        ),
        cause=(
            "`converged_suite_cycles` counts TRAILING cycles, walking "
            "iterations downwards and taking the newest record per "
            "brief. Appending a newer sweep therefore makes the newest "
            "cycle the sweep, and the pin's own evidence is no longer "
            "trailing. The sweep was not a convergence cycle at all: it "
            "was a lane qualification against goldens minted from a "
            "DIFFERENT writer, so its examiner verdicts carried "
            "deviations by construction and the count fell to zero."
        ),
        fix=(
            "A lane qualification gets its own artifact: "
            "_evaluate/writer_qualification_iterations.jsonl (and the "
            "matching verdicts file), leaving the protocol's log to the "
            "protocol. The general rule, already learned once for the "
            "3DCodeBench runs: never write an experiment into a "
            "canonical log that a rule reads positionally — appending "
            "is not harmless when 'newest' is part of the meaning."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_the_v10_cycle_is_one_converged_cycle (goes red the "
            "moment a foreign cycle is appended); "
            "tests/pure/test_prompt_templates.py::"
            "test_the_shipped_configuration_is_the_converged_configuration "
            "reads the qualification artifact instead"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="a-vision-read-inverted-a-profile",
        scope="process",
        failure=(
            "A verification pass nearly reported a false defect. The "
            "writer described its own render as 'narrower flat rims at "
            "top and bottom, bulging out to its widest point at "
            "mid-height — the classic barrel belly'. An independent "
            "vision read of the SAME contact sheet said the opposite: "
            "'the mid-height is the NARROWEST point ... the inverse of "
            "a barrel (hourglass/spool profile)', with specific "
            "supporting evidence ('horizontal crease where the "
            "silhouette is narrowest'). Measuring the mesh settled it: "
            "max radius 0.1500 at both rims and 0.1900 across "
            "z 0.15-0.25, i.e. widest at mid-height. The writer was "
            "right and the vision read was wrong."
        ),
        cause=(
            "A single vision read of a shaded render is a MEASUREMENT "
            "with an error rate, not ground truth. The shading crease "
            "along the widest ring of a lathed solid reads as a waist "
            "when the lighting puts a dark band there — and the reading "
            "arrived with confident, specific-sounding evidence for the "
            "inverted profile, which is exactly what makes it "
            "dangerous."
        ),
        fix=(
            "Never escalate a visual discrepancy without the "
            "deterministic measurement, when geometry can answer: here, "
            "eight radius bands from the mesh vertices took one command "
            "and were unambiguous. This is the harness's founding order "
            "(deterministic gate first, visual critique second; tool "
            "feedback outranks model feedback, "
            "10.48550/arXiv.2409.02977) applied to the REVIEWER rather "
            "than to the writer — the reviewer's eye is the same kind "
            "of instrument as the examiner's."
        ),
        guarded_by=(
            "src/blended/evaluate/examiner.py thresholds "
            "(MINIMUM_FIXTURE_SENSITIVITY, REQUIRED_CONTROL_SPECIFICITY, "
            "CROSS_RUN_CONTROL_MINIMUM_SPECIFICITY) and "
            "_evaluate/eye_calibration.json bound how far ANY eye is "
            "trusted. Measured 2026-09-06: sensitivity 0.75, same-run "
            "specificity 1.00, cross-run specificity 0.75 against a "
            "required 1.0, so the shipped eye is NOT licensed for "
            "fresh-vs-exemplar runs. Pinned by "
            "tests/pure/test_examiner.py::test_calibration_problems_are_loud, "
            "::test_the_licence_identity_still_matches_the_shipped_eye and "
            "::test_a_licence_measured_on_identical_images_does_not_cover_a_fresh_run; "
            "::test_the_shipped_eye_holds_the_licence_in_the_repository is "
            "xfail(strict) until the Phase B decision "
            "(docs/2026-09-06-token-budget-plan.md) and goes red the day "
            "the licence is earned"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-pin-loop-could-not-advance-a-revision",
        scope="harness_code",
        failure=(
            "Every door to pinning a candidate revision refused, in a "
            "cycle: `converge_auto --revision 11` refused because "
            "_evaluate/golden/<brief>_v11 did not exist; "
            "`make pin-golden-views REVISION=11` refused with 'iteration "
            "51 ran v10:b6627b38f4c1, not v11:d90e5ee9e59d — refusing to "
            "pin the wrong text'; and `make pin` refuses a proposal "
            "'composed by hand'. The loop could not advance past the "
            "revision it had already pinned."
        ),
        cause=(
            "pin_golden_views sourced its runs from "
            "prompt_versions.CONVERGENCE_RUNS — the runs of the "
            "CURRENTLY PINNED revision, which by definition executed the "
            "old text — and then asserted the recorded identity equals "
            "the revision being stamped. Those two rules can only both "
            "hold for the revision already pinned. CONVERGENCE_RUNS is "
            "rewritten by `make pin`, which needs the proposal, which "
            "needs the reference: a genuine deadlock, introduced by "
            "tightening the identity guard (correct) while leaving the "
            "run SOURCE as the previous pin (wrong)."
        ),
        fix=(
            "The source is now the log, scoped to the identity being "
            "stamped: `clean_cycle_for_identity` takes the newest run "
            "per brief that EXECUTED that revision with all three "
            "deterministic gates green, and pin_golden_views refuses "
            "loudly, naming the briefs, when the suite has not been run "
            "at that revision yet. The identity guard is kept — it was "
            "always the right check, just applied to the wrong "
            "candidates. Bootstrap order for a new revision: run the "
            "suite at it, mint from those runs, then converge."
        ),
        guarded_by=(
            "tests/pure/test_convergence_rule.py::"
            "test_only_runs_that_executed_a_revision_may_mint_its_reference"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="every-number-was-right-and-the-lid-was-invisible",
        scope="brief",
        failure=(
            "crate_with_lid passed every deterministic check — CrateLid "
            "0.5000 x 0.5000 x 0.0600 at base_z 0.4000, resting on the "
            "body, centred, not sunk — and the render showed ONE "
            "CONTINUOUS BOX. No lid, no seam, no ledge. The examiner "
            "reported `missing_feature` and no measurement could, which "
            "halted the v11 convergence attempt as harness_critique."
        ),
        cause=(
            "The brief specified a lid with the body's EXACT footprint "
            "resting flush on the rim, so nothing about the geometry "
            "distinguishes the two parts from outside. What made the "
            "signed-off reference readable was never geometry but "
            "COLOUR: body (0.6, 0.4, 0.2) against lid (0.5, 0.3, 0.15), "
            "a distance of 0.15. The run that vanished gave both parts "
            "(0.45, 0.30, 0.15) — distance 0 — which no check forbade."
        ),
        fix=(
            "DistinctMaterialSpec: two named parts must differ in base "
            "colour by at least CRATE_LID_MINIMUM_COLOUR_DISTANCE_RGB "
            "(0.10, set below the reference's measured 0.15 so the "
            "artifact that earned the pin still conforms), and the brief "
            "text now says so. Deliberately contrast, NOT a required "
            "hue or luminance: pinning those would bake one writer's "
            "taste into the acceptance spec. Verified across two later "
            "cycles — `missing_feature` never returned."
        ),
        guarded_by=(
            "tests/blender/test_acceptance_gate.py::"
            "test_a_lid_the_same_colour_as_the_body_fails_even_though_it_"
            "measures_right (and ::test_a_contrasting_lid_passes, which "
            "keeps the probe from condemning the reference)"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="the-examiners-licence-did-not-cover-how-it-is-used",
        scope="harness_code",
        failure=(
            "Three convergence cycles on one unchanged configuration "
            "(15 runs, 14 of them green on every deterministic gate) "
            "never produced a clean examiner sweep, and the deviations "
            "MOVED: uv_crate came back `material_missing` in one cycle "
            "and clean in the next, ribbed_column the reverse, "
            "planter_box clean then flagged. A pin needs 5/5 clean at "
            "once, so the loop cannot close — and re-rolling cycles "
            "until one comes up clean would be selecting on the "
            "instrument's noise."
        ),
        cause=(
            "calibrate_examiner builds its five clean CONTROLS by "
            "replaying ONE recorded run and comparing it against the "
            "reference minted from THAT SAME run — pixel-identical "
            "inputs. Control specificity 1.00 therefore measures "
            "'does it stay quiet when shown the same image twice', "
            "while the loop uses it to compare a FRESH run against an "
            "exemplar. That regime was never measured, and the "
            "false-alarm rate in it is plainly not zero: planter_box "
            "iteration 62 was flagged against planter_box_v11, an "
            "exemplar minted from iteration 57 — same lane, same "
            "prompt, same brief, both gate-clean."
        ),
        fix=(
            "The cross-run control class was added to "
            "scripts/calibrate_examiner.py and measured 2026-09-06: "
            "specificity 0.50 (see "
            "the-examiner-was-asked-the-wrong-question), under "
            "REQUIRED_CONTROL_SPECIFICITY, so the examiner is not "
            "licensed for the regime the loop uses. "
            "Calibration.problems() now reports "
            "cross_run_control_specificity and a miss disqualifies the "
            "examiner, so converge_auto refuses to gate on it "
            "(docs/2026-09-06-token-budget-plan.md, Phase A). Machine "
            "verdicts on a fresh run stay advisory and the "
            "deterministic gates carry the qualification (which is the "
            "existing order: tool feedback outranks model feedback, "
            "10.48550/arXiv.2409.02977)."
        ),
        guarded_by=(
            "tests/pure/test_examiner.py::"
            "test_a_licence_measured_on_identical_images_does_not_"
            "cover_a_fresh_run (a cross-run specificity miss "
            "disqualifies); _evaluate/verdicts.jsonl iterations 52-65 "
            "record the hopping deviations"
        ),
        recorded_on="2026-09-05",
    ),
    MistakeRecord(
        identifier="sixty-nine-iterations-with-no-idea-what-they-cost",
        scope="harness_code",
        failure=(
            "Asked whether the harness made good use of prompt caching, "
            "the answer was that NOBODY HAD EVER CHECKED. 69 logged "
            "iterations, three convergence cycles in one day, and not "
            "one token of accounting anywhere: no `usage` parsing on "
            "any lane, no cost in the iteration record, and the "
            "`rate_limit_event` frame the Claude Code transport already "
            "parsed was thrown away. Measured once accounting existed: "
            "ONE brief costs $1.4182 and 738,839 input tokens across 26 "
            "API calls, so a 5-brief cycle is ~$7 and 3.7M tokens."
        ),
        cause=(
            "Every gate in this harness measures the ARTIFACT. Nothing "
            "measured the harness itself, so the one quantity that "
            "scales with every experiment stayed invisible — and a "
            "harness whose whole thesis is 'measure, do not assume' was "
            "assuming. Two specifics only measurement could reveal: one "
            "harness turn is 2-3 API calls (the CLI runs the model again "
            "to conform to `--json-schema`), and 85% of the effective "
            "input cost is cache WRITES at 1.25x rather than reads at "
            "0.1x."
        ),
        fix=(
            "`TurnCost` + `parse_turn_cost` on the Claude Code lane, "
            "`_turn_cost_from_body` for the OpenAI/Ollama lanes, "
            "`OllamaClient.spent` accumulating across a run with the "
            "eye's client folded in, and six cost fields on "
            "`IterationRecord`. Also measured and worth keeping: prompt "
            "caching DOES survive our stateless one-process-per-turn "
            "design (12,241 tok cost $0.0507 cold, $0.0043 warm — "
            "11.8x) because the system prompt is byte-stable and "
            "history is append-only. Those two properties were "
            "accidental and are now tested."
        ),
        guarded_by=(
            "tests/pure/test_claude_code_lane.py::"
            "test_a_growing_transcript_keeps_the_previous_turn_as_its_"
            "prefix, ::test_the_system_prompt_is_byte_stable_across_"
            "builds, ::test_one_harness_turn_reports_every_api_call_it_"
            "made; docs/2026-09-06-token-budget-audit.md"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="the-examiner-was-asked-the-wrong-question",
        scope="harness_code",
        failure=(
            "Three convergence cycles halted on examiner deviations, "
            "and the pending question was whether the examiner was "
            "noisy. Measured 2026-09-06 with a new cross-run control "
            "class: specificity 0.50 (2 of 4 gate-clean runs flagged), "
            "against a required 1.00. At a per-brief false-alarm rate "
            "of 0.5 a five-brief cycle comes up clean with probability "
            "0.5^5 = 3%, so re-rolling cycles would have cost ~32 "
            "cycles and ~$224 to reach a pin BY LUCK."
        ),
        cause=(
            "The deviations are not noise — they are TRUE. Measured "
            "from the meshes: planter_box's exemplar (iteration 57) is "
            "base colour (0.45, 0.28, 0.15) and the flagged candidate "
            "(62) is (0.35, 0.22, 0.12), a distance of 0.120, with "
            "IDENTICAL dimensions; three_leg_stool 59 vs 64 share a "
            "bbox but differ in internal proportion. The loop asks "
            "'does this match the exemplar?' and reads the answer as "
            "'does this satisfy the brief?'. Everything the brief "
            "leaves free differs between runs BY CONSTRUCTION, so an "
            "exemplar-matching question manufactures deviations at a "
            "rate set by how much the brief leaves unspecified."
        ),
        fix=(
            "B2', the plan's recommended branch, landed 2026-09-06 "
            "(de30d79): MEASURED_DEVIATION_TAGS (wrong_proportion, "
            "material_missing) were split out of HALTING_DEVIATION_TAGS "
            "and are recorded as AssetVerdict.measured_property_reports "
            "(evidence, never a gate); the reference stays paired, since "
            "pairing is worth +0.32 F1 (10.48550/arXiv.2604.11082) and "
            "tool feedback outranks model feedback "
            "(10.48550/arXiv.2409.02977); fat_seat left the eye's zoo "
            "for tests/blender/test_acceptance_gate.py after the gate "
            "coverage was measured. Re-licence: sensitivity 0.75 (3/4), "
            "same-run specificity 1.00, cross-run specificity 0.50 -> "
            "0.75 (3/4) against a required 1.0 — improved, did NOT pass: "
            "three_leg_stool still fires, as intersecting_parts + "
            "surface_artifact, on geometric variation the brief leaves "
            "free. The examiner stays unlicensed for the loop's regime; "
            "the final branch (the plan recommends B4', machine "
            "verdicts advisory on fresh-vs-exemplar) is still a human "
            "decision, named by the xfail(strict) on "
            "tests/pure/test_examiner.py::"
            "test_the_shipped_eye_holds_the_licence_in_the_repository. "
            "My own first draft — count a deviation only if it "
            "reproduces across independent examinations — is REFUTED "
            "by the 0.50 measurement, because a systematic true "
            "difference reproduces every time and the rule would have "
            "doubled examiner calls for nothing."
        ),
        guarded_by=(
            'make calibrate-eye ARGS="--cross-run-only"; '
            "tests/pure/test_examiner.py::"
            "test_a_licence_measured_on_identical_images_does_not_"
            "cover_a_fresh_run; docs/2026-09-06-token-budget-plan.md"
        ),
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="vertex-penetration-is-not-surface-penetration",
        scope="harness_code",
        failure=(
            "scp measured 28-vertex shoulder straps at 0 deep pokes and "
            "1.6 mm max depth — green — while triangle-vs-triangle "
            "counted 1,200 pairs with their centroid inside the "
            "shoulder. Palm-to-weapon read 60 mm against vertices "
            "and 6.5 mm against the surface. The gap widens as "
            "geometry gets coarser."
        ),
        cause=(
            "A vertex-penetration probe samples the query object's "
            "vertices against the target's closest surface point. "
            "When the query mesh is sparse (28 vertices on a strap), "
            "no vertex falls inside the target, so the probe reads "
            "zero penetration even though the surfaces fully "
            "intersect. The triangle-vs-triangle broad phase sees "
            "the real overlap but is gated behind an AABB depth "
            "threshold (CONTACT_DEPTH_TOLERANCE_M, 2 mm) that a "
            "shallow overlap never reaches, so it reports zero too."
        ),
        fix=(
            "PairReport reports aabb_penetration_depth_m (the "
            "world-AABB minimum translation depth) alongside "
            "intersecting_face_pair_count. NoInterpenetrationSpec "
            "gates on maximum_aabb_penetration_depth_m, and "
            "evaluate.acceptance compares it — so a caller sees the "
            "shallow overlap that the vertex probe misses and the "
            "face-pair count gates. The surface-distance probe "
            "remains for separation, not penetration."
        ),
        guarded_by="blended.evaluate.acceptance (NoInterpenetrationSpec.maximum_aabb_penetration_depth_m) and tests/blender/test_pair_checks.py",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-separation-measure-must-be-symmetric",
        scope="harness_code",
        failure=(
            "scp measured analyze_pair sampling only the first "
            "argument's vertices as query points, so the same pair "
            "measured differently depending on argument order. On the "
            "local fixture (24-segment cylinder vs 8-vertex cube, "
            "overlapping) the one-directional readings were "
            "0.0224 m one way and 0.3274 m the other — a 14.6x "
            "spread on the same pair."
        ),
        cause=(
            "When the two meshes differ in vertex density, the "
            "sparse object's vertices miss the close approach that "
            "the dense object's vertices find. Sampling only one "
            "direction picks whichever density the argument order "
            "happened to give, so the measure is not a function of "
            "the pair but of the call."
        ),
        fix=(
            "analyze_pair now samples BOTH objects' vertices via "
            "_sampled_minimum_distance_m (the extracted helper) and "
            "reports the minimum of the two directional readings. "
            "It also reports aabb_penetration_depth_m, the "
            "world-AABB minimum translation depth that gates the "
            "face-pair count."
        ),
        guarded_by="tests/blender/test_pair_checks.py::test_separation_does_not_depend_on_argument_order",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-gate-sharing-a-derivation-cannot-fail",
        scope="process",
        failure=(
            "scp measured read_hand_frame's palm_out at ~150 degrees "
            "from the real palm normal; every grip gate measured "
            "against that same vector and all passed (1.8 mm, "
            "0.0 mm, 'palm faces up') while a render showed the "
            "weapon gripped from the wrong side. The same pattern "
            "recurred in this repo: every shipped Provenance passed "
            "value=<the constant itself>, so validate_briefs read the "
            "constant back through the Provenance and compared it to "
            "itself — a tautology that passed until the values became "
            "literals and a constant edit reddened it ('claims value "
            "0.32, constant holds 0.36')."
        ),
        cause=(
            "The gate and the pose reader shared the same "
            "derivation: palm_out was computed once and then every "
            "check compared against it. A derivation that is wrong "
            "in the same way as the thing it validates produces "
            "self-consistent green readings on a wrong result. "
            "Defining the 'must not move' set by reading it off the "
            "artefact under test (zero weight on a bone) was "
            "vacuous — 200 deliberately bled vertices produced "
            "zero violations."
        ),
        fix=(
            "A relation must be anchored in the semantics of what "
            "is being built, never in the implementation's own "
            "arithmetic. The metamorphic gate transforms the input "
            "and asserts a relation between the two outputs, "
            "reaching outside the artefact's own derivation."
        ),
        guarded_by="tests/blender/test_metamorphic.py (a relation anchored outside the artefact)",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="hashing-raw-floats-cries-wolf",
        scope="harness_code",
        failure=(
            "Inherited doctrine, not a local measurement: blended "
            "never had a byte or float hash to fail. scp measured "
            "that .blend bytes carry a version stamp and floats "
            "carry last-bit noise, so a byte or float hash reports "
            "drift on an unchanged build; bmesh emits geometry in "
            "pointer-hash order, so face order is not signal. The "
            "lesson is why blended.evaluate.digest was designed to "
            "hash quantized semantic tuples from the start."
        ),
        cause=(
            "Hashing raw floats or .blend bytes treats last-bit "
            "noise and Blender version stamps as semantic drift. "
            "The hash fires on every rebuild even when the shipped "
            "geometry is identical, so it is switched off inside a "
            "week — and the real drift it was meant to catch goes "
            "unguarded."
        ),
        fix=(
            "blended.evaluate.digest hashes quantized semantic "
            "tuples (positions to 0.1 mm, UVs to 1e-5, matrices to "
            "1e-5, weights to 1e-4), with faces canonicalized by "
            "rotating each face's index cycle to start at its "
            "lowest index before sorting. Winding direction is "
            "preserved so a flipped face still changes the digest."
        ),
        guarded_by="scripts/rebuild_twice.py / make test-repro (two fresh Blenders, PYTHONHASHSEED 0 vs 1) and tests/blender/test_rebuild_in_session.py",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="undo-is-not-a-reset",
        scope="harness_code",
        failure=(
            "Inherited doctrine, not a local measurement: blended "
            "never had a rebuild that trusted the undo stack. scp "
            "measured Blender's undo stack as unreliable from "
            "script-driven operators, so a rebuild that trusts it "
            "measures residue from the previous build. The lesson is "
            "why blended.reset.reset_scene wipes every collection in "
            "dependency order and asserts the wipe took, rather than "
            "relying on undo."
        ),
        cause=(
            "bpy.ops.wm.read_factory_settings(use_empty=True) "
            "wipes the scene but does not assert the wipe took, and "
            "Blender's undo stack does not reliably unwind "
            "script-driven operators. A rebuild that assumes the "
            "scene is clean measures the previous build's orphaned "
            "datablocks alongside the new one."
        ),
        fix=(
            "blended.reset.reset_scene wipes every collection in "
            "dependency order (objects before meshes before "
            "materials), calls orphans_purge, sets the canonical "
            "FPS, and finishes with assert_clean_scene, which "
            "raises SceneNotClean listing every non-empty "
            "MUST_BE_EMPTY collection and a non-canonical FPS at "
            "once."
        ),
        guarded_by="tests/blender/test_reset.py::test_a_leftover_object_is_not_a_clean_scene and ::test_a_rewritten_fps_is_not_a_clean_scene and ::test_every_problem_is_reported_in_one_raise",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="git-checkout-reverts-to-the-index-not-to-your-snapshot",
        scope="process",
        failure=(
            "Running a negative control on "
            "src/blended/ops/canonical_orientation.py — reorder "
            "AXIS_NAMES, confirm 3 of 21 tests redden, revert — "
            "DELETED the uncommitted orientation_reading function the "
            "control was proving. The revert step was `git checkout -- "
            "<file>`; the assertion that the file matched its "
            "pre-probe bytes then failed, which is the only reason the "
            "loss was noticed at all."
        ),
        cause=(
            "`git checkout -- <path>` restores from the INDEX (or HEAD), "
            "not from the working-tree state that was snapshotted a "
            "moment earlier. The same command was safe on "
            "src/blended/drift/catalog.py in the same session, because "
            "that file had already been committed and its index copy WAS "
            "the snapshot — so the habit reads as correct right up until "
            "it is applied to a file with uncommitted work."
        ),
        fix=(
            "A probe on a file with uncommitted work snapshots BYTES and "
            "restores BYTES: read the file, write the probe, measure, "
            "write the saved bytes back, then assert byte equality. "
            "`git checkout` is for reverting to a commit, never for "
            "undoing a scratch edit. Assert the restore, always — the "
            "assertion is what turned a silent deletion into a caught "
            "one."
        ),
        guarded_by="No test can guard a shell habit; the guard is the byte-equality assertion at the end of every negative control, and this record. tests/pure/test_canonical_orientation.py::test_the_reading_names_the_axis_holding_the_middle_extent is what reddened under the probe and what proved the restore.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-digest-is-mesh-identity-not-solid-identity",
        scope="harness_code",
        failure=(
            "The permutative metamorphic relation, written to assert "
            "semantic_digest and triangle_count unchanged when the "
            "boolean union order is reversed, FAILED on both multi-part "
            "builders on its first run: 2 failed, 4 passed. Measured — "
            "barrel 816 -> 816 triangles with a BIT-IDENTICAL volume "
            "(0.31573285487001135 both) but digest 665a17f1 -> "
            "4f927c63; pallet 334 -> 336 triangles, volume rel 1.7e-8, "
            "area rel 8.5e-9, digest 7213b524 -> 0284e97f."
        ),
        cause=(
            "Union is commutative on SOLIDS, not on TESSELLATIONS. "
            "Blender's EXACT boolean retriangulates from whatever "
            "intermediate mesh it was handed, so operand order decides "
            "the triangulation and the vertex order — which is all a "
            "digest sees. The relation asserted mesh identity while its "
            "own justification claimed to be about geometry, so it would "
            "have failed forever on correct builders: a gate that cannot "
            "pass is as useless as one that cannot fail."
        ),
        fix=(
            "MeshReport gained volume_m3 and surface_area_m2 (computed "
            "first, off the mesh as loaded, in the bmesh analyze_object "
            "already opens — one measurement path), measure_build "
            "carries them, and the relation asserts the SOLID: volume "
            "and area within a MEASURED CONSTRUCTION_ORDER_REL_TOL of "
            "1e-6 (~60x the worst observed noise), plus extents and the "
            "four topology counts exactly. triangle_count and the digest "
            "are deliberately not asserted, and the falsification is "
            "recorded in the module docstring WITH the numbers so the "
            "vacuous version is not retried. The semantic_digest key "
            "added for the dead assertion was removed with it."
        ),
        guarded_by="tests/blender/test_metamorphic.py::test_builders_satisfy_their_metamorphic_relations[barrel] and [pallet] carry construction_order_does_not_change_the_mesh. Negative control, run and reverted: making hoop z depend on sequence_position rather than hoop_index reddens it on surface_area_m2 (2.59578341525048 -> 2.5958127349149436, rel 1.1e-5, 11x the tolerance) while volume_m3 stays inside tolerance, because HOOP_POSITION_FRACTIONS 0.2 and 0.8 sit at equal radii on a sine-bulged barrel and the two shifts cancel in volume. Asserting both quantities is what catches it; either one alone would have missed it.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-lane-with-no-acceptance-spec-cannot-fail",
        scope="harness_code",
        failure=(
            "scripts/photo_to_model.py returned 0 whenever ANY mesh "
            "existed. `error` was set from the turn's traceback and "
            "written into summary.json but never read for the exit code; "
            "`structural_failures` was printed and stored but never "
            "enforced; and an unreachable eye was swallowed upstream — "
            "deliver_images substituted EYE_UNREACHABLE_NOTE, so the "
            "writer got a prompt that deliberately names no shape and no "
            "pixels, invented an object, and the run exited 0. The "
            "no-mesh path returned 1 while writing NO summary.json at "
            "all, so the run with the most to explain explained nothing."
        ),
        cause=(
            "The module docstring's own sentence — 'there is no "
            "acceptance spec: a photograph carries no dimensions' — was "
            "read as 'therefore nothing can be gated'. But a photograph "
            "supports a COMPARATIVE spec even though it supports no "
            "dimensional one, and `examine_view` already existed and "
            "already takes two arbitrary images."
        ),
        fix=(
            "The photograph is the reference view and the three_quarter "
            "render is the candidate; examine_view runs both orders and "
            "only tags surviving the swap count, so a position-biased "
            "answer cannot decide the run. A surviving HALTING tag exits "
            "1, abstention is recorded and never a failure, a raised "
            "turn exits 1, and the gate needs an eye that is not the "
            "writer (--vision-model '' exits 2 BEFORE any Blender work) "
            "because a writer grading its own build against the picture "
            "it was handed holds both the evidence and the verdict. "
            "deliver_images gained eye_failure_is_fatal, True only at "
            "the reference-photo call site, raising a dedicated "
            "EyeUnreachable rather than a traceback the caller has to "
            "string-match. Every path past the turn now writes "
            "summary.json."
        ),
        guarded_by="tests/pure/test_reference_images.py::test_a_blind_eye_on_the_photo_path_raises_instead_of_guessing (the writer receives NO payload) and ::test_a_blind_eye_on_the_render_path_still_reports_a_note (the control that keeps the change from spreading). Live runs 2026-09-06, exit codes 2 / 1 / 0: --vision-model '' exits 2 naming the flag; --vision-model no-such-model-exists:v0 exits 1 with eye_reachable false, tool_calls 0 and objects []; a real run exits 0 with no surviving deviation. Gate sensitivity proven separately — a stool photograph against a crate render yields the surviving tag missing_part, so the exit 0 is not a gate that cannot fail.",
        recorded_on="2026-09-06",
    ),
    MistakeRecord(
        identifier="a-signature-change-invalidates-recorded-model-code-not-just-callers",
        scope="harness_code",
        failure=(
            "OT-2 made every op take and return object NAMES. make "
            "test-blender-app: 3 failed, 305 passed — the golden replays "
            "of iteration 48 (planter: materials 0 assigned in 1 slot) and "
            "50 (column: exists but not linked; no dimension named "
            "'diameter_x'). Every hand-written caller and all 305 other "
            "tests had already been converted and were green."
        ),
        cause=(
            "The goldens replay what the MODEL wrote on 2026-08-22 against "
            "the object-returning API: planter chunk 7 fetched "
            "bpy.data.objects['PlanterBox'] and passed it to "
            "assign_material; column chunks 1-2 read `.name` off "
            "add_lathe's return and chunk 3 passed the bpy object to "
            "link_into_scene. Under the name contract those chunks raise "
            "and the rest of the chunk never runs. The other three goldens "
            "survived only because their sources never dereferenced an "
            "op's return — a behaviour-preserving API change still breaks "
            "recorded evidence, and grep over src/ and tests/ cannot see it."
        ),
        fix=(
            "Re-converged the two briefs on the new vocabulary at the SAME "
            "pinned v10 text (iterations 66 and 67, claude-code:sonnet, 8 and "
            "6 turns, 0 name-vs-object errors, identical form numbers) and "
            "re-minted their golden views, per the v9->v10 precedent in "
            "test_golden_convergence.py. The three untouched briefs were "
            "re-minted pixel-identical (0.00% differing) and reverted. "
            "Iterations 48 and 50 stay in the append-only log. Budget "
            "this: an ops API change costs one converge run per golden "
            "whose recorded source touches the changed surface."
        ),
        guarded_by=(
            "tests/blender/test_golden_convergence.py (replays the recorded "
            "sources: a signature change that breaks recorded model code "
            "fails here, not in the ops tests); "
            "tests/pure/test_ops_signature_contract.py (the contract itself)"
        ),
        recorded_on="2026-09-10",
    ),
    MistakeRecord(
        identifier="a-pure-helper-under-a-package-whose-init-imports-the-harness-is-a-cycle",
        scope="harness_code",
        failure=(
            "OT-4 put the EXE-6 stage vocabulary in blended/run/stages.py "
            "and imported it from harness.py. make test-pure: 625 passed. "
            "make test-blender-app -k agent_loop: 6 failed — every "
            "run_python tool call answered 'Tool raised ImportError: cannot "
            "import name HarnessResult from partially initialized module "
            "blended.harness', and the scene stayed empty."
        ),
        cause=(
            "blended/run/__init__.py eagerly imported run.batch (deleted "
            "2026-10-07), which imported blended.harness at module level. "
            "harness -> "
            "run.stages -> run/__init__ -> run.batch -> harness is a cycle "
            "whenever harness is the FIRST of the two imported. The pure "
            "suite never saw it because an earlier test had already "
            "imported blended.run.executor, so the package was initialised "
            "before harness loaded; a Blender probe that imported executor "
            "first passed for the same reason and was misleading."
        ),
        fix=(
            "Moved the vocabulary to blended/stages.py, a top-level module "
            "under the side-effect-free blended/__init__.py, and repointed "
            "harness.py, agent/op_call.py, the tests and the spec. Added a "
            "fresh-interpreter import test so import order is probed in a "
            "process that has imported nothing else."
        ),
        guarded_by=(
            "tests/pure/test_import_integrity.py::"
            "test_the_harness_imports_first_in_a_fresh_interpreter; "
            "tests/blender/test_agent_loop.py::test_loop_runs_a_tool_then_answers"
        ),
        recorded_on="2026-09-10",
    ),
    MistakeRecord(
        identifier="a-budget-derived-before-the-surface-changed-stops-honest-turns",
        scope="harness_code",
        failure=(
            "OT-17 set MAXIMUM_TURN_TOKENS = 750,000 from the 8-tool "
            "measurement (25,851 tokens per call). The first v12 run with "
            "50 tools (iteration 68, planter_box, Claude Code lane) was "
            "stopped by that budget at call 16 of 24: 931,851 tokens, "
            "913,854 input of which 835,080 cached, $0.71."
        ),
        cause=(
            "The per-call bill on the CLI lane scales with the tool schema "
            "the envelope carries on every API call: 50 oneOf variants "
            "(OT-3) took the measured per-call bill from 25,851 to 58,241 "
            "tokens (2.25x, 91% of it cache reads). A budget derived from "
            "a measurement taken on a different surface is not a "
            "measurement of this one."
        ),
        fix=(
            "Re-derived from the heaviest measured call on the heaviest "
            "lane: 24 x 58,241 = 1.40M, plus a fifth -> 1,700,000. Both "
            "numbers stay in the constant's comment; the 2.25x is the "
            "price of one tool per op on this lane and is OT-13's "
            "evidence. Re-run the planter (iteration 73) under the new "
            "budget rather than reading 68 as a failure of the surface."
        ),
        guarded_by=(
            "tests/pure/test_turn_token_budget.py::"
            "test_the_turn_stops_at_the_seam_when_the_token_budget_is_exceeded "
            "(the seam); the derivation rule in the constant's comment "
            "(the number)"
        ),
        recorded_on="2026-09-10",
    ),
    MistakeRecord(
        identifier="the-host-blender-already-holds-an-older-blended",
        scope="harness_code",
        failure=(
            "OT-21 smoke: one bench instance through the new runner "
            "(OK_AGENT_DONE, 690 s, 1 op call in the script) re-baked as "
            "ERR_EXEC — 'ModuleNotFoundError: No module named "
            "blended.agent.op_call' — although the module exists on disk "
            "and the same three prelude lines import it fine in a bare "
            "Blender."
        ),
        cause=(
            "The bench bakes with `blender --background --python "
            "core/render.py`, no --factory-startup, so the user's addons "
            "load first: the installed blended_agent addon (deleted in "
            "the MCP cutover) bundled a copy "
            "of `blended` and imported it at startup (measured: "
            "sys.modules['blended'] pointed at scripts/addons/blended_agent/"
            "blended/, with blended.ui already loaded). The script's "
            "sys.path inserts came too late; `import blended.agent.op_call` "
            "resolved against the addon's older package."
        ),
        fix=(
            "The emitted script's prelude evicts every `blended*` entry from "
            "sys.modules before its first blended import, so the script "
            "imports the tree it names whatever the host Blender preloaded. "
            "Roll 1's 13 OK bakes had only used blended.ops names the old "
            "copy also had, which is why the defect stayed invisible."
        ),
        guarded_by=(
            "tests/pure/test_bench_bridge.py::"
            "test_a_record_of_chunks_only_keeps_the_chunk_format (eviction "
            "precedes the first import); the OT-21 smoke re-bake"
        ),
        recorded_on="2026-09-10",
    ),
    MistakeRecord(
        identifier="the-reading-and-the-op-measured-different-boxes",
        scope="harness_code",
        failure=(
            "A 0.9 x 0.3 x 0.6 m box turned a quarter turn about X: the "
            "gate's `orient:` line and `inspect_object` read (0.9, 0.3, "
            "0.6), 'middle extent on z, canonical depth axis is y', while "
            "the box occupied (0.9, 0.6, 0.3) and apply_canonical_depth_axis "
            "composed identity. The writer was told one axis assignment and "
            "had another applied (measured 2026-09-11, OT-34)."
        ),
        cause=(
            "harness.gate_object and tools.inspect_object built the extents "
            "from object.dimensions — the local box scaled, rotation-blind "
            "(see object-dimensions-ignores-rotation, catalogued 2026-08-22) "
            "— while canonical_orientation measured matrix_world @ bound_box. "
            "Two readers of one quantity, two implementations; the trap was "
            "already in the drift catalog and the reading fell into it "
            "anyway because the harness comment said `dimensions` came "
            "'from the evaluated transform', which is true of scale only."
        ),
        fix=(
            "One private helper, ops/transforms._world_extents_m, is the "
            "only place world extents are measured; the gate, "
            "inspect_object, list_scene, world_bounds and "
            "apply_canonical_depth_axis all read it. A reading and the op "
            "that acts on it must come from the same numbers, or the "
            "reading is a gate that lies."
        ),
        guarded_by=(
            "tests/blender/test_harness.py::"
            "test_the_reading_and_the_op_measure_the_same_box and "
            "::test_inspect_object_and_list_scene_read_the_world_box (red "
            "before the change: reported (0.9, 0.3, 0.6) for a box "
            "occupying (0.9, 0.6, 0.3))"
        ),
        recorded_on="2026-09-11",
    ),
    MistakeRecord(
        identifier="a-frozen-tree-predates-the-fix-it-was-meant-to-carry",
        scope="process",
        failure=(
            "OT-27 cloud roll 3 (2026-09-10 19:53 to 01:47): 13/20 "
            "executable, 7 instances ERR_MODEL_CALL, every one HTTP 502 "
            "from ollama.com through the local daemon ('connection reset by "
            "peer'), 0 retry lines in any transcript, 5 of the 7 dead on "
            "the first call, spread over 20:52-23:24. Rolls 1 and 2 had "
            "each lost one instance the same way. The plan that launched "
            "the roll said the gateway retry 'already flows through "
            "OllamaClient'."
        ),
        cause=(
            "The roll ran from the hand-made worktree blended-bench-v4 at "
            "c6e4bfc; the bounded retry (RETRYABLE_HTTP_STATUSES, "
            "RETRY_BACKOFF_SECONDS) landed in 179ab11, AFTER that commit. "
            "Nothing in the launch named the commit the roll carried, so "
            "'the fix is in the tree' was asserted from memory of main, not "
            "read from the freeze. A worktree named after its purpose "
            "(-v4) cannot answer 'which fixes does it have'; one named after "
            "its commit can."
        ),
        fix=(
            "scripts/bench_chain.sh refuses any WORKTREE outside "
            "$FREEZE_ROOT (where scripts/freeze_worktree.sh names every "
            "freeze by its commit) before it touches the bench, and writes "
            "the frozen commit as the first line of chain_<MODEL_DIR>.log. "
            "The blended-bench-v4 worktree and the incumbent-ot27 branch "
            "were removed; the next set runs from a freeze of HEAD after "
            "OT-34 and OT-36."
        ),
        guarded_by=(
            "tests/pure/test_bench_chain_guard.py::"
            "test_a_worktree_outside_the_freeze_root_is_refused_before_anything_runs, "
            "::test_a_real_freeze_logs_its_commit_first"
        ),
        recorded_on="2026-09-11",
    ),
    MistakeRecord(
        identifier="home-does-not-isolate-blender-config-on-macos",
        scope="harness_code",
        failure=(
            "make test-mcp-blender (the vendored blender_mcp live test) "
            "rewrote the REAL ~/Library/Application Support/Blender/5.2/"
            "config/userpref.blend at 16:33:16 on 2026-09-26: the enabled "
            "add-ons fell from 11 to 9 (mpfb, right_mouse_navigation and "
            "rigify gone, the test's mcp added) and use_online_access went "
            "True -> False, so the GUI add-on refused to open port 9876 "
            "('Online access must be enabled'). No .blend1, Time Machine or "
            "APFS snapshot existed; only the recorded add-on set and online "
            "access could be restored, other preferences were lost."
        ),
        cause=(
            "The test isolated Blender with HOME=tmpdir only. On macOS "
            "Blender resolves its user resources without $HOME "
            "(user_resource('CONFIG') stayed ~/Library/... with HOME=/tmp/x), "
            "and the test's '--factory-startup --command extension "
            "install-file --enable' saves preferences: factory defaults "
            "landed on the user's file. Upstream runs these tests on Linux, "
            "where HOME does redirect the config."
        ),
        fix=(
            "_blender_env also sets BLENDER_USER_RESOURCES=<tmpdir>/"
            "blender_user_resources (measured: config and extensions then "
            "resolve under it). A rerun left the real userpref.blend "
            "byte-identical (sha dab75cd1b0dbb4f0 before and after)."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blender_mcp_with_blender.py::"
            "_assert_blender_config_isolated, run first in setUpClass: "
            "raises unless Blender's user_resource('CONFIG') resolves inside "
            "the test tmpdir (proven to raise with a HOME-only env)"
        ),
        recorded_on="2026-09-26",
    ),
    MistakeRecord(
        identifier="live-mcp-test-drove-the-users-blender",
        scope="harness_code",
        failure=(
            "make test-mcp-blender with the GUI Blender open: 8 failures + "
            "1 error of 39 (screenshot/jump tools 'expected to fail in "
            "non-interactive mode' succeeded; deferred-response test got no "
            "'status'). The suite had run against the GUI instance, and its "
            "setUp read_homefile reset that session's scene."
        ),
        cause=(
            "TestBackgroundServer's fixed port was 9876, the add-on's "
            "default, which the auto-started GUI add-on already held. The "
            "test Blender could not bind it, and _wait_for_port accepted the "
            "GUI's listener as the test server."
        ),
        fix=(
            "Test ports moved to 9886-9888, off the add-on default; "
            "_assert_port_free raises before launching a test Blender when "
            "its port is taken. Rerun beside the GUI on 9876: 39/39 OK."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blender_mcp_with_blender.py::"
            "_assert_port_free, called in setUpClass immediately before the "
            "test Blender is launched"
        ),
        recorded_on="2026-09-26",
    ),
    MistakeRecord(
        identifier="mcp-served-stale-code-until-restart",
        scope="harness_code",
        failure=(
            "Edits to src/blended or blender_mcp/mcp/blmcp were invisible "
            "to the chat agent: the stdio MCP server kept the tool list and "
            "instructions it read at start until a manual /mcp reconnect, "
            "and Blender kept the blended modules it imported on the first "
            "call until Blender quit. The mcp add-on was an installed copy, "
            "so add-on edits also needed make install-mcp-addon."
        ),
        cause=(
            "Three caches, none keyed to the source: the server process, "
            "blended in Blender's sys.modules, and the extension directory "
            "copy. Nothing compared what was loaded against what was on disk."
        ),
        fix=(
            "blended_bridge.source_fingerprint() (path, mtime_ns, size of "
            "every source file under src/blended and blmcp; API/manual docs "
            "and __pycache__ skipped; 167 files, ~1.5 ms) rides on every "
            "call's Params; the Blender side purges every blended.* module "
            "and re-imports when it differs from the fingerprint stamped on "
            "the imported package. BlendedFastMCP."
            "exit_on_source_change exits the idle server once the "
            "fingerprint changed and held still for SOURCE_SETTLE_S; omp "
            "reconnects stdio servers on close. The add-on is now a symlink "
            "(make install-mcp-addon fails unless addon_utils.check returns "
            "(True, True)). "
            "Measured 2026-09-27 against one GUI Blender session: before "
            "the edit world_bounds returned no probe; after a docstring + "
            "body edit a fresh client saw the new description and "
            "'probe': true, and after the revert both were gone, three "
            "server processes, Cube still in the scene. Inside one omp -p "
            "session the same edit showed up in the tool description and "
            "result with no error (two logs/mcp-*.jsonl, 16 s apart). "
            "First probe attempt failed usefully: appending ' Freshness "
            "probe.' pushed the summary past the 120-char op contract, and "
            "the restarted server died with ContractViolation instead of "
            "serving the edit. A review on 2026-10-02 found six defects in "
            "this fix and fixed them. (1) 'Idle' meant only that call_tool "
            "had returned, which happens before the SDK writes the response; "
            "an exit in that gap dropped the result of a call Blender had "
            "applied (5 of 5 at a 1 ms lead), so the exit now also waits "
            "SOURCE_RESPONSE_DRAIN_S after the last return. (2) A file "
            "removed between the listing and the stat (macOS sed -i temp "
            "files: 1173 of 3663 edits) or a dangling Emacs .#name.py lock "
            "raised FileNotFoundError, killing the server and failing calls; "
            "it now counts as absent. (3) A change landing while the server "
            "waited for idle did not restart the settle clock, so the exit "
            "could land mid-rewrite. (4) The watcher also killed --transport "
            "http servers, which nothing restarts; it was made stdio-only. "
            "That default was still wrong: Claude Code does not restart a "
            "stdio server either, and the review's own session lost every "
            "blended tool 8 s after an edit. Since 2026-10-02 the watcher is "
            "off by default for every transport; omp opts in through its "
            "own blended entry in .omp/mcp.json (measured: omp spawned that "
            "entry with the flag, not the one in .mcp.json). A watcher exit "
            "now writes logs/mcp-handoff-<client pid>.json, so the client's "
            "next server keeps the declared plan and the session log; before "
            "that, a restart answered the next scene-changing call with 'No "
            "plan declared'. (5) The purge ran before the stale-copy check, so "
            "another checkout's blended was dropped silently instead of "
            "refused. (6) CPython accepts a timestamp .pyc whose source has "
            "the same size and whole-second mtime, so after a same-size edit "
            "in the second of the last compile the purge re-imported the old "
            "code (Blender 5.2, scripted edit, call, revert, call: 20 of 20 "
            "stale at a 0 s gap); the purge now deletes this interpreter's "
            "cached bytecode for the package first."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blended_bridge.py: TestToolcodeReimport "
            "(the toolcode run as the add-on runs it, fresh exec namespace "
            "per call and bytecode on, against fake checkouts: only a "
            "changed fingerprint re-imports, even past a same-size rewrite "
            "under the old mtime; another checkout's copy is refused and "
            "left loaded); TestSourceWatcher (fake clock, calls run through "
            "the real call_tool: a settled edit exits cleanly; the exit waits "
            "SOURCE_RESPONSE_DRAIN_S after the last call returned; an edit "
            "while waiting restarts the settle clock; a revert to the "
            "baseline never exits; a broken watcher exits with the failure "
            "code once idle); TestSourceFingerprint (a same-size rewrite "
            "and a resize under the old mtime each change it; __pycache__, "
            "skipped paths and a dangling symlink do not; a missing root "
            "raises). Each failed against the logic it guards reverted "
            "(2026-10-02). TestWatcherIsOptIn (default off; only omp's "
            "config passes the flag); TestHandoff (resume keeps the plan "
            "and the log's numbering; another client's pid, an expired "
            "handoff and a malformed one start fresh; a failed write still "
            "exits) and test_blender_mcp_with_blender.py::"
            "test_a_watcher_restart_keeps_the_declared_plan (two real "
            "server processes: add_box after the restart passes the gate; "
            "it failed with the resume disabled)."
        ),
        recorded_on="2026-09-27",
    ),
    MistakeRecord(
        identifier="mcp-instructions-past-2048-characters-never-arrive",
        scope="harness_code",
        failure=(
            "The blended MCP server sends 22,896 characters of instructions; "
            "a Claude Code agent received them cut at index 2048, mid-word "
            "('\"Five r... [truncated]'). A rule appended anywhere after the "
            "head, such as keeping the part being worked on in the user's "
            "view, would have shipped and never been read."
        ),
        cause=(
            "Claude Code shows an MCP client only the first 2,048 characters "
            "of a server's instructions; blended_instructions put the "
            "working agreement first and upstream's text after it, so "
            "position in the string decided what an agent saw."
        ),
        fix=(
            "The first fix was wrong twice. It put a 632-character rule "
            "ahead of build_system_prompt() telling agents to call "
            "jump_to_view3d_object_by_name after every call that creates "
            "an object, and to stop if framing failed. (a) add_box, "
            "add_cylinder and add_lathe return objects not yet in the "
            "scene, and framing one raises 'not in View Layer' (Blender "
            "5.2), so the rule would have halted agents before "
            "link_into_scene. (b) Its 632 characters pushed 634 characters "
            "of the working agreement out of the head, including 'measure "
            "every number after the LAST operation' and 'every named "
            "feature is real geometry'. Now the bridge frames whatever a "
            "scene-changing call touched once it is in the scene "
            "(blended.viewport_follow, a viewport: line on the result), and "
            "MCP_INSTRUCTIONS_HEAD (1,823 characters, MCP only) condenses "
            "working-agreement revision 10 and leads the instructions. The "
            "scored working agreement is unchanged."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blended_bridge.py::TestInstructionsHead "
            "(the head leads the instructions and fits "
            "CLAUDE_CODE_INSTRUCTIONS_LIMIT_CHARACTERS; it condenses the "
            "active revision; the tool it names is in the registry); "
            "blender_mcp/tests/test_mcp_server.py::TestMCPServer::"
            "test_instructions_lead_with_the_must_read_head on what a "
            "running server sends; make test-viewport-gui (every corner of "
            "a framed box projects inside the region, in perspective, "
            "ortho and from camera view; an unlinked object is reported, "
            "not framed; it failed 6 of 6 with the margin at 0.3); "
            "test_blender_mcp_with_blender.py::"
            "test_blended_tools_dispatch_through_blender (the viewport: "
            "line through the real MCP path)"
        ),
        recorded_on="2026-10-02",
    ),
    MistakeRecord(
        identifier="a-splice-to-end-of-file-deleted-another-agents-tests",
        scope="process",
        failure=(
            "test_blended_bridge.py went from 19 tests to 13 after an edit "
            "that meant to replace one test class: TestSourceWatcher and "
            "TestToolcodeReimport were gone."
        ),
        cause=(
            "The splice ran from the class header to the "
            "'if __name__ == \"__main__\"' anchor, i.e. to the end of the "
            "file. Meanwhile a concurrent /code-review --fix agent had "
            "appended classes after that class. The file had changed on disk "
            "since it was last read, and an end anchor of 'end of file' "
            "takes whatever is there."
        ),
        fix=(
            "Restored by replaying the review agent's 9 recorded Edit "
            "results from its transcript onto the last full originalFile. "
            "The rebuilt prefix matched the file on disk byte for byte, and "
            "all 20 tests then ran. A splice now ends at the next class "
            "header, never at the end of the file."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blended_bridge.py::TestSuitesPresent "
            "(the module still defines every test class it shipped with)"
        ),
        recorded_on="2026-10-02",
    ),
    MistakeRecord(
        identifier="a-guard-that-names-deleted-code-still-validated",
        scope="process",
        failure=(
            "Review 2026-10-07: 23 of 92 records were guarded by nothing. "
            "21 carried a 'RETIRED 2026-09' guard naming test files, "
            "modules and a draw handler deleted in 184095f and 22e1d87 "
            "(the in-Blender chat client and its streamed transport), and 2 more named a GUI-verification rule for "
            "that client (outputs/gui_cmd.py absent, layout_transcript "
            "deleted). Four live records also asserted state the "
            "repository had since replaced: the eye-calibration file "
            "'records the qwen3-vl:8b-instruct measurement' (it holds "
            "claude-code:sonnet), 'sensitivity 0.80' (0.75), 'NOT YET "
            "FIXED' and 'PENDING a human decision' for a question "
            "measured and decided in de30d79. validate_memory() returned "
            "[] throughout."
        ),
        cause=(
            "validate_memory() asks only that guarded_by is non-empty, and "
            "nothing ran it: no test, script or Makefile target called "
            "it, although the specification quotes 'validate_memory() == "
            "[]' from hand runs. The cutover marked guards RETIRED in "
            "place, which is a non-empty string, so a record guarded by "
            "nothing was indistinguishable from a healthy one. Nothing "
            "dated or re-measured a record's claims either, so measured "
            "state that later moved stayed written as present tense."
        ),
        fix=(
            "The 23 guard-less records were deleted (their lessons are in "
            "git history; blended_bridge_toolcode.py's two citations were "
            "reworded to state the bugs inline), the four stale records "
            "were rewritten in place with the measured current state, and "
            "DuplicateMistake (never raised) was deleted. A suite now "
            "resolves every path, test name and make target a guard "
            "cites against the tree and rejects a RETIRED marker."
        ),
        guarded_by=(
            "tests/pure/test_review_mistake_memory.py::"
            "test_a_guard_names_only_things_that_exist and "
            "::test_a_guard_names_something_executable (run against the "
            "pre-fix file they failed on exactly those 23 records)"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="constrained-decode-accepts-any-json-object",
        scope="harness_code",
        failure=(
            "A bare {name, arguments} reply on the local llama-server lane "
            "decoded to content='' and raised EmptyReply: the model's own "
            "text was erased."
        ),
        cause=(
            "The decode keyed only on isinstance(envelope, dict) and also "
            "ran on tool-less requests, which carry no response_format."
        ),
        fix=(
            "Decode only when the dict holds both ENVELOPE_REQUIRED_KEYS "
            "and the request carried tools."
        ),
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_a_bare_tool_call_object_is_not_mistaken_for_the_envelope"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="local-llama-server-300s-ceiling",
        scope="harness_code",
        failure=(
            "ModelConfig.from_environment(model='blenderllm')."
            "request_timeout_seconds was 300, not 2000: any completion over "
            "300 s was retried across the whole ladder."
        ),
        cause=(
            "The endpoint joined OPENAI_PROTOCOL_ENDPOINTS but not the "
            "predicate that picks the long ceiling."
        ),
        fix="One LONG_CEILING_ENDPOINTS tuple keys the ceiling.",
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_the_local_llama_server_gets_the_long_ceiling"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="constrained-lane-exact-endpoint-match",
        scope="harness_code",
        failure=(
            "http://127.0.0.1:8091/ took the OpenAI wire with "
            "constrains_tool_calls False, so wire tools went to a model "
            "that cannot emit them."
        ),
        cause=(
            "constrains_tool_calls matched by equality beside a protocol "
            "check that matches by substring."
        ),
        fix="Both checks match by containment.",
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_constrained_lane_matches_by_containment_like_the_protocol_check"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="malformed-openai-tool-arguments-crash-turn",
        scope="harness_code",
        failure=(
            "A truncated arguments string raised JSONDecodeError out of "
            "send(), stranding the assistant's tool calls without results."
        ),
        cause="json.loads ran unguarded on the model's own output.",
        fix=(
            "_parse_tool_arguments refuses a non-JSON or non-object value "
            "as a tool result the model can correct."
        ),
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_malformed_arguments_are_refused_not_raised"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="malformed-plan-step-raises-after-dispatch",
        scope="harness_code",
        failure="plan_step='abc' raised ValueError after the tool had already run.",
        cause="plan_step_of was unguarded between dispatch and the tool result.",
        fix="The step is ignored and a note is appended to the tool result.",
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_a_malformed_plan_step_is_reported_after_the_tool_ran"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="eye-spend-lost-on-failed-call",
        scope="harness_code",
        failure=(
            "api_calls stayed 0 after a billed eye reply was cut at the "
            "length limit, so the metered cap never saw the spend."
        ),
        cause="The spend was folded into the run record only after a successful chat.",
        fix="Fold it in a finally block.",
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_an_eye_call_that_fails_after_billing_still_counts_against_the_run"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="gate-cap-render-before-answering-queued-calls",
        scope="harness_code",
        failure=(
            "A render_views that raised at the gate cap left the queued "
            "tool calls without a result."
        ),
        cause="The queued calls were answered after the render dispatch.",
        fix="Answer them first; the exception still propagates.",
        guarded_by=(
            "tests/pure/test_review_agent_loop.py::"
            "test_the_gate_cap_answers_queued_calls_before_it_renders"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="claude-code-stderr-pipe-deadlock",
        scope="harness_code",
        failure=(
            "A child writing 512 KiB to stderr made chat() run to the "
            "watchdog ('did not answer within 10 s')."
        ),
        cause=(
            "stderr was read only after stdout reached EOF, so a full pipe "
            "blocked the child while the parent waited on stdout."
        ),
        fix="A drain thread reads stderr as it arrives.",
        guarded_by=(
            "tests/pure/test_review_agent_surface.py::"
            "test_a_stderr_flood_does_not_stall_the_turn"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="claude-code-child-leaked-on-frame-error",
        scope="harness_code",
        failure=(
            "After a json.loads error in _consume the CLI process was still "
            "alive and never waited on."
        ),
        cause="The kill and wait() sat after the call, not in a finally.",
        fix="Kill on any exception; wait() and the stream closes in finally.",
        guarded_by=(
            "tests/pure/test_review_agent_surface.py::"
            "test_a_malformed_frame_does_not_leave_the_cli_running"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="claude-code-thinking-duplicated",
        scope="harness_code",
        failure=(
            "Streamed thinking read 'weighingweighing': the deltas "
            "'weigh','ing it' came before the complete frame 'weighing it'."
        ),
        cause=(
            "The dedupe tested the full string against a list of fragments, "
            "so it never matched."
        ),
        fix="Compare against the joined text.",
        guarded_by=(
            "tests/pure/test_review_agent_surface.py::"
            "test_streamed_thinking_is_not_repeated_by_the_complete_frame"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="rejected-op-call-recorded-empty",
        scope="harness_code",
        failure=(
            "dispatch_tool('add_box', {..., 'bogus': 1}) recorded "
            "validated_arguments == {}, so the candidate-op miner lost what "
            "the model sent."
        ),
        cause="A failed bind has empty bound arguments and the code always used them.",
        fix="Fall back to the op arguments as sent, plan_step stripped.",
        guarded_by=(
            "tests/pure/test_review_agent_surface.py::"
            "test_a_rejected_op_call_is_recorded_with_what_the_model_sent"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="registry-string-block-corrupts-text",
        scope="harness_code",
        failure=(
            "A hypothesis or outcome containing a double quote wrote an "
            "unimportable registry; backslash-n became a real newline; "
            "hyphen and long-word wraps gained a space ('state- of-the-art')."
        ),
        cause="The literal writer used textwrap defaults and no escaping.",
        fix=(
            "Wrap without breaking words or hyphens and escape each chunk "
            "with json.dumps."
        ),
        guarded_by=(
            "tests/pure/test_review_agent_prompts.py::"
            "test_string_block_round_trips_quotes_backslashes_and_hyphens"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="record-outcome-no-rollback-on-import-failure",
        scope="harness_code",
        failure=(
            "When the edited registry failed to import, _probe_registry "
            "raised RevisionRejected and the broken file stayed on disk."
        ),
        cause="Only the 'problems' branch restored the original.",
        fix="Restore the original on both paths, as write_revision does.",
        guarded_by=(
            "tests/pure/test_review_agent_prompts.py::"
            "test_record_outcome_restores_the_registry_when_it_no_longer_imports"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="clear-axis-sweep-used-local-distance",
        scope="harness_code",
        failure=(
            "A 2 m cube scaled 0.1 or 0.01 reported blocked_at=None on the "
            "z axis through its centre (scale 1.0 gave -1.0): a through-hole "
            "check passed on a solid."
        ),
        cause=(
            "ray_cast distance is in the object's LOCAL space but the sweep "
            "(start 50 m away) was defined in world metres, so for scale < "
            "0.5 the ray ended before reaching the object."
        ),
        fix="Map both sweep ends to local space and use their local length.",
        guarded_by=(
            "tests/blender/test_review_eval_core.py::"
            "test_a_scaled_solid_blocks_the_axis_through_its_centre"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="sole-bearing-drift-ignored-modulo-360",
        scope="harness_code",
        failure=(
            "A foot moving 0.2 -> 359.9 deg read as a 359.7 deg swing in "
            "preservation_failures: a false REFINEMENT FAIL."
        ),
        cause="The drift was a raw subtraction of angles in [0, 360).",
        fix=(
            "One signed_angle_difference_deg() serves the drift and "
            "GroundContactMeasurement.angle_error_deg."
        ),
        guarded_by=(
            "tests/pure/test_review_eval_core.py::"
            "test_a_foot_straddling_the_plus_x_axis_has_not_swung"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="examiner-reply-brace-counting",
        scope="harness_code",
        failure=(
            "A valid reply whose reasoning contained '{left}' or a lone '{' "
            "raised ExaminerReplyUnparseable."
        ),
        cause="_first_json_object counted braces and ignored JSON string quoting.",
        fix="json.JSONDecoder().raw_decode from the first '{'.",
        guarded_by=(
            "tests/pure/test_review_eval_core.py::"
            "test_a_brace_inside_the_reasoning_string_does_not_reject_a_valid_reply"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="golden-manifest-allowed-unpinned-view",
        scope="harness_code",
        failure=(
            "verify_golden_manifest passed a manifest with no hash for an "
            "examined view, so that view could drift unnoticed."
        ),
        cause="It checked only the views the manifest recorded.",
        fix="Require every EXAMINED_VIEW_NAMES entry in view_sha256.",
        guarded_by=(
            "tests/pure/test_review_eval_core.py::"
            "test_a_view_the_manifest_does_not_pin_is_refused"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="jsonl-reload-lost-tuple-types",
        scope="harness_code",
        failure=(
            "A reloaded IterationRecord.tool_calls was a list and "
            "IterationVerdict.view_tags a list of lists, so comparisons "
            "against () were False on reloaded data."
        ),
        cause="JSON has no tuple and the loaders passed **payload straight through.",
        fix="The loaders restore tuples for default_factory=tuple fields and nested view_tags.",
        guarded_by=(
            "tests/pure/test_review_eval_core.py::"
            "test_a_reloaded_verdict_has_tuple_view_tags"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="summary-hid-missing-part",
        scope="harness_code",
        failure=(
            "A multi-part AcceptanceReport with a missing part printed only "
            "failures[0], which could be another part's dimension failure."
        ),
        cause="The early return indexed failures[0].",
        fix="Print every failure.",
        guarded_by=(
            "tests/pure/test_review_eval_core.py::"
            "test_the_summary_names_a_missing_part_even_when_another_part_failed_first"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="visual-diff-zero-size-frame-index-error",
        scope="harness_code",
        failure=(
            "compare_view_arrays on a (0, 0, 4) array raised a bare "
            "IndexError from golden_array[0, 0] with no view name."
        ),
        cause="_background_rgb indexed the golden corners before any emptiness check.",
        fix="Raise EmptyFrame(view_name) right after the size-mismatch check.",
        guarded_by=(
            "tests/blender/test_review_eval_rest.py::"
            "test_a_zero_pixel_frame_is_refused_by_name_not_by_an_index_error"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="remove-by-name-type-blind",
        scope="harness_code",
        failure=(
            "add_box('Rig') over an existing armature raised TypeError from "
            "meshes.remove(<Armature>) after the armature was already deleted."
        ),
        cause="The removal assumed the object's data was a mesh.",
        fix="batch_remove on any data type; rigging reuses remove_object_and_mesh.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_constructor_replaces_an_object_of_another_type"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="armature-parent-order-in-edit-mode",
        scope="harness_code",
        failure=(
            "A bone listed before its parent raised KeyError inside EDIT "
            "mode and left the file stuck there with a half-built rig."
        ),
        cause="Validation checked 'parent exists', not 'parent is listed first'.",
        fix="Validate the order up front; the EDIT build returns to OBJECT in finally.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_parent_listed_after_its_child_is_rejected_before_any_mutation"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="bind-without-parent-inverse",
        scope="harness_code",
        failure=(
            "bind_mesh_to_armature(automatic_weights=False) moved a box from "
            "z 0..1 to z 1..2 under an armature at z=1."
        ),
        cause="Assigning .parent leaves matrix_parent_inverse at identity.",
        fix="Set it to the armature's inverse world matrix after a view-layer update.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_binding_without_automatic_weights_leaves_the_mesh_in_place"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="world-vs-local-location",
        scope="harness_code",
        failure=(
            "move_object_to on a child of a parent at z=5 left the child at "
            "world z=5 instead of the requested location."
        ),
        cause="The op claims a world location but wrote the parent-relative .location.",
        fix="Parented objects set the world-matrix translation.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_move_object_to_places_a_parented_object_in_world_space"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="normal-transform-needs-inverse-transpose",
        scope="harness_code",
        failure=(
            "A 45 degree face under z-scale 10 selected as +z: the true "
            "world normal is (-0.995, 0, 0.10), the code produced "
            "(-0.10, 0, 0.995)."
        ),
        cause="The plain 3x3 matrix was applied to normals.",
        fix="Use the inverse-transpose (equal to the rotation for rigid transforms).",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_axis_normal_selection_uses_true_world_normals_under_non_uniform_scale"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="stale-matrix-world-in-reader-ops",
        scope="harness_code",
        failure=(
            "assign_weights_by_height returned 0 where 4 vertices were "
            "expected, right after the box's location was set to z=10."
        ),
        cause="matrix_world is lazy and the op never refreshed it.",
        fix="view_layer.update() first, in this op and in select_faces.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_height_weights_see_a_location_set_a_moment_ago"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="internal-helper-leaks-on-failure",
        scope="harness_code",
        failure="A failed trim_soles_flat left its own <name>_SoleCutter linked in the scene.",
        cause="Only the successful boolean consumed the cutter.",
        fix="Remove the cutter in a finally block.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_failed_sole_trim_does_not_leave_its_cutter_in_the_scene"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="unwrap-strands-edit-mode-and-masks-error",
        scope="harness_code",
        failure=(
            "A failed unwrap operator left the object in EDIT mode, then "
            "select_all raised an unrelated poll error that hid the real one."
        ),
        cause="Leaving EDIT mode was not the first statement of the finally block.",
        fix="Leave EDIT mode first in finally.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_failed_unwrap_leaves_the_object_out_of_edit_mode"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="empty-action-index-error",
        scope="harness_code",
        failure="animation_report raised IndexError on an action with no keyframes.",
        cause="It assumed layers[0].strips[0] always exists.",
        fix="An action with no layers or no slot has 0 fcurves.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_animation_report_on_an_action_with_no_keyframes_is_empty_not_an_error"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="flat-colour-ignored-on-reused-textured-material",
        scope="harness_code",
        failure=(
            "After a flat red assign_material on a reused name, "
            "material_report still said base_color_linked=True and only "
            "Workbench showed the colour."
        ),
        cause="A linked input ignores default_value and the old texture link stayed.",
        fix="assign_material removes stale Base Color links.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_flat_colour_replaces_a_texture_left_on_a_reused_material"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="rotation-mode-set-before-validation",
        scope="harness_code",
        failure=(
            "A bad Euler order raised but left rotation_mode changed (AXIS_ANGLE)."
        ),
        cause="The mutation preceded the call that validates the argument.",
        fix="Build the Euler first.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_a_rejected_euler_order_leaves_the_rotation_mode_alone"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="rename-return-vs-truncated-name",
        scope="harness_code",
        failure=(
            "A 300-character new name returned a name absent from bpy.data.objects."
        ),
        cause="Blender truncates object names at 255 bytes; the op echoed the request.",
        fix="Return obj.name.",
        guarded_by=(
            "tests/blender/test_review_ops.py::"
            "test_rename_returns_the_name_the_object_actually_has"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="contact-sheet-pillow-branch-returns-none",
        scope="harness_code",
        failure=(
            "compose_contact_sheet returned None and wrote no file whenever "
            "Pillow was installed; capture_contact_sheet handed the None on. "
            "mypy had reported it as 'missing return statement'."
        ),
        cause=(
            "The save and return lines were lost in an edit after commit "
            "361d792 (the numpy fallback)."
        ),
        fix="Restored sheet.save and return output_path.",
        guarded_by=(
            "tests/bench_scripts/test_contact_sheet_pillow.py::"
            "test_contact_sheet_pillow_branch_returns_the_written_sheet"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="cleanup-revert-snapshot-taken-before-writeback",
        scope="harness_code",
        failure=(
            "On a folded hole plus 2 loose vertices the log said 'deleted 2 "
            "loose vertices' then 'REVERTED'; 3 components remained and the "
            "2 vertices were back."
        ),
        cause=(
            "The 'pre-fill' snapshot was data.copy() taken before the "
            "bmesh edits were written back, i.e. the untouched original."
        ),
        fix="Snapshot from working_mesh.to_mesh() right before the fill loop.",
        guarded_by=(
            "tests/blender/test_review_analyze_capture.py::"
            "test_reverted_fill_keeps_the_cleanup_that_preceded_it"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="empty-mesh-passes-the-gate",
        scope="harness_code",
        failure=(
            "analyze_object on a face-less mesh returned all zeros and "
            "failures(MeshBudget()) == []."
        ),
        cause="Every check is 'count of bad things > 0'; zero faces yields zero of everything.",
        fix="failures() fails when triangle_count == 0.",
        guarded_by=(
            "tests/blender/test_review_analyze_capture.py::"
            "test_analyzer_gate_fails_an_empty_mesh"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="drift-signature-never-matches-real-error",
        scope="harness_code",
        failure=(
            "The cone entry's signature 'is invalid' never appears in Blender "
            "5.2.0's message ('keyword \"diameter1\" unrecognized')."
        ),
        cause="The signature was written from memory; no test raised the real error.",
        fix="Corrected it and added a test that raises six real errors and requires a catalog match.",
        guarded_by=(
            "tests/blender/test_review_analyze_capture.py::"
            "test_drift_signatures_match_the_error_blender_really_raises"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="glb-normalized-signed-decoded-raw",
        scope="harness_code",
        failure="Normalized int8/int16 accessors came back as raw integers.",
        cause="_COMPONENT_MAXIMA held unsigned types only; the missing divisor fell through.",
        fix="Added 5120 and 5122 with the glTF section 3.11 clamp to -1.0.",
        guarded_by=(
            "tests/pure/test_review_analyze_capture.py::"
            "test_signed_normalized_short_decodes_and_clamps"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="system-exit-escapes-the-chunk-executor",
        scope="harness_code",
        failure=(
            "run_source_in_process('import sys; sys.exit(3)') raised "
            "SystemExit out of execute_captured instead of returning a "
            "RunResult (measured in Blender 5.2 background)."
        ),
        cause="execute_captured caught Exception only; SystemExit is a BaseException.",
        fix="Catch (Exception, SystemExit) in executor.execute_captured.",
        guarded_by=(
            "tests/pure/test_review_harness_core.py::"
            "test_a_chunk_that_calls_sys_exit_comes_back_as_a_failed_result"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="run-agent-task-zero-rounds-unbound-result",
        scope="harness_code",
        failure=(
            "run_agent_task(maximum_rounds=0) raised UnboundLocalError on "
            "'result'; run_with_retries(maximum_retries=-1) raised "
            "IndexError in final_result."
        ),
        cause="A cap was used as a range bound with no lower-bound check.",
        fix="ValueError at both entry points.",
        guarded_by=(
            "tests/pure/test_review_harness_core.py::"
            "test_zero_task_rounds_is_refused_not_an_unbound_variable and "
            "::test_negative_retries_is_refused_not_an_index_error"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="locate-feedback-says-missing-when-object-exists",
        scope="harness_code",
        failure=(
            "For a hidden, unlinked or collapsed object the retry feedback "
            "said 'no object named X existed afterwards' while it existed, "
            "so the agent rebuilt an object that was already there."
        ),
        cause="The locate stage serves missing-object and scene-state failures; the feedback assumed the first.",
        fix="The text says 'not usable' and appends the execution_summary that carries the reason.",
        guarded_by=(
            "tests/pure/test_review_harness_core.py::"
            "test_locate_feedback_carries_the_scene_state_reason"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="sibling-script-import-went-stale",
        scope="harness_code",
        failure=(
            "scripts/orientation_policy_sim.py raised ImportError on its "
            "first import line (reproduced under the bench venv)."
        ),
        cause=(
            "OT-36 moved signed_permutations from diagnose_3dcode to "
            "bench_surface_metrics; test_import_integrity resolves only "
            "blended-rooted imports, so nothing caught the sibling import."
        ),
        fix="Import from bench_surface_metrics and add an AST check over sibling-script imports.",
        guarded_by=(
            "tests/pure/test_review_scripts_bench.py::"
            "test_every_sibling_script_import_names_something_the_sibling_binds"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="reference-render-passed-on-previous-runs-log",
        scope="harness_code",
        failure=(
            "Under --overwrite a Blender that died before writing "
            "render_log.json left the old OK log and four PNGs, so the "
            "instance read as freshly rendered; a hung Blender stalled the sweep."
        ),
        cause="Success was read from artifacts a prior run had left, and there was no timeout.",
        fix="Delete the stale log before the run; a per-instance timeout counts as a failed instance.",
        guarded_by=(
            "tests/pure/test_review_scripts_bench.py::"
            "test_a_blender_that_dies_without_a_log_does_not_pass_on_the_stale_log and "
            "::test_a_hung_blender_is_a_failed_instance_not_a_stalled_sweep"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="phase-b-counts-from-record-counters",
        scope="harness_code",
        failure=(
            "The Phase B op/hatch rate line mixed completion-record n_ops "
            "(reader ops included) with n_hatch (dispatched, collected or "
            "not); Phase C reported 76 op-sequence pairs against 40 by baked labels."
        ),
        cause=(
            "Counters named like measurements but defined by a different "
            "instrument (emits_geometry includes readers; n_hatch counts dispatch)."
        ),
        fix="Count off the baked script labels via finetune_phase_a.baked_call_counts everywhere.",
        guarded_by=(
            "tests/pure/test_review_scripts_finetune.py::"
            "test_funnel_hatch_and_op_calls_come_from_baked_labels_not_record_counters and "
            "::test_phase_c_counts_ops_off_the_baked_script_not_the_meta_counters"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="sweep-reports-stale-record",
        scope="harness_code",
        failure=(
            "The sweep printed a crashed re-run's outcome as the previous "
            "run's parse_result (or SKIPPED); 'blender --python x.py' where "
            "x raises exits 0 (measured)."
        ),
        cause=(
            "last_completion() returned the newest matching record whether "
            "or not this subprocess wrote it, and Blender needs --python-exit-code."
        ),
        fix="Only records appended by the subprocess count; skip is decided before spawn; ERR_NO_RECORD; --python-exit-code 1.",
        guarded_by=(
            "tests/pure/test_review_scripts_finetune.py::"
            "test_sweep_reads_only_records_the_subprocess_wrote and "
            "::test_blender_ops_command_turns_a_script_exception_into_a_nonzero_exit"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="judge-rerun-truncates-hand-verified-rows",
        scope="process",
        failure="Re-running the judge opens g3_judgements.jsonl 'w' and erases 20 hand-verified rows.",
        cause="Generator output and human annotations share one file.",
        fix="The judge refuses when any row has hand_verified true.",
        guarded_by=(
            "tests/pure/test_review_scripts_finetune.py::"
            "test_judge_refuses_to_truncate_hand_verified_rows"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="stale-bake-artifacts-for-no-script-completion",
        scope="harness_code",
        failure=(
            "A completion with script_written False read an old render_log "
            "(status OK) from an earlier --overwrite run."
        ),
        cause="execution_row read the bake directory unconditionally.",
        fix="No script means no artifacts are read; the status is NO_SCRIPT.",
        guarded_by=(
            "tests/pure/test_review_scripts_finetune.py::"
            "test_execution_row_ignores_stale_artifacts_when_no_script_was_written"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="converge-auto-classified-a-crashed-run-by-an-older-record",
        scope="harness_code",
        failure=(
            "run_one_brief discarded the driver exit code; a run that died "
            "before writing its record left _newest_cycle returning an older "
            "record of that brief, which classify treated as this run "
            "(read from the code path, not a live repro)."
        ),
        cause="The loop assumed every run appends exactly one record.",
        fix="Halt with a report when no record exists for the exact (iteration, brief); never blacklist a hunk for a crashed screening run.",
        guarded_by=(
            "tests/pure/test_review_scripts_misc.py::"
            "test_record_for_run_is_none_when_only_an_older_run_of_the_brief_exists"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="pin-revision-pinned-an-empty-model",
        scope="harness_code",
        failure=(
            "make pin accepted writer_model='' (emitted by converge_auto for "
            "mixed-model runs) and wrote CONVERGENCE_WRITER_MODEL = ''; the "
            "CONVERGENCE_RUNS rewrite did nothing and raised nothing."
        ),
        cause="The proposal was not validated and re.sub was used without a match check.",
        fix="Refuse empty model names; subn with a loud failure on no match.",
        guarded_by=(
            "tests/pure/test_review_scripts_misc.py::"
            "test_pin_refuses_a_proposal_that_names_no_writer_model"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="provider-smoke-typo-lane-ran-zero-lanes",
        scope="harness_code",
        failure="--only claude_code ran nothing and a lone typo crashed on max() of an empty list.",
        cause="The lane filter never checked names, so 'every lane answers' held for zero lanes.",
        fix="parse_lanes checks against KNOWN_LANES.",
        guarded_by=(
            "tests/pure/test_review_scripts_misc.py::"
            "test_provider_smoke_rejects_an_unknown_lane"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="api-docs-realpath-root-guard",
        scope="harness_code",
        failure=(
            "get_python_api_docs('foo') returned 'suggestions' instead of "
            "'exact' when the API root was reached through a symlink "
            "(/tmp -> /private/tmp)."
        ),
        cause="The traversal guard compared realpath results with an unresolved root.",
        fix="api_path = os.path.realpath(...).",
        guarded_by=(
            "tests/pure/test_review_mcp_tools.py::"
            "test_api_docs_exact_match_through_symlinked_data_root"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="usage-guess-stale-5x-node-tree",
        scope="harness_code",
        failure=(
            "On Blender 5.2.0 scene.node_tree is missing, so Compositing "
            "scored 0 and Render Layers was ignored on every file."
        ),
        cause="Code written against the pre-5.0 API.",
        fix="Read scene.compositing_node_group.",
        guarded_by=(
            "tests/blender/test_review_mcp_tools.py::"
            "test_usage_guess_sees_a_compositor_tree"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="stale-eevee-engine-id",
        scope="harness_code",
        failure="'BLENDER_EEVEE_NEXT' never matches on 5.x, so the thumbnail sample cap never applied.",
        cause="The engine id was renamed away in 5.x and the string was compared blind.",
        fix="Compare with 'BLENDER_EEVEE'; a test checks every engine id tool code compares against exists.",
        guarded_by=(
            "tests/blender/test_review_mcp_tools.py::"
            "test_every_engine_id_tool_code_compares_against_exists_in_blender"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="image-downscale-silent-oversize",
        scope="harness_code",
        failure="A 16-byte size limit returned a 781,866-byte PNG from a tool that promises a cap.",
        cause="The final return was the full-size encode when no downscale fit.",
        fix="Raise RuntimeError when nothing fits.",
        guarded_by=(
            "tests/blender/test_review_mcp_tools.py::"
            "test_image_downscale_raises_when_no_downscale_fits"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="folded-search-hit-text-not-extended",
        scope="harness_code",
        failure=(
            "search(context=2) with matches at paragraphs 0, 2 and 5 "
            "returned one hit scored 3 whose text ended at paragraph 2: "
            "'needle_zz third' was scored but absent."
        ),
        cause="The fold branch added the later match's score but never rebuilt the text.",
        fix="Rebuild the hit text over last_lo..idx+context+1 on every fold.",
        guarded_by=(
            "tests/pure/test_review_mcp_helpers.py::"
            "test_folded_matches_are_all_in_the_hit_text"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="handoff-read-outside-try",
        scope="harness_code",
        failure=(
            "A non-UTF-8 mcp-handoff-<pid>.json raised UnicodeDecodeError at "
            "server start and stayed on disk, so every restart crashed."
        ),
        cause="read_text ran before the try with unlink after it, and exists()-then-read raced a concurrent start.",
        fix="Read bytes (FileNotFoundError means no handoff), unlink(missing_ok=True), decode inside the try.",
        guarded_by=(
            "tests/pure/test_review_mcp_helpers.py::"
            "test_handoff_that_is_not_utf8_is_refused_loudly_and_consumed"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="addon-code-runner-catches-only-exception",
        scope="harness_code",
        failure=(
            "In Blender 5.2 background, exit(4) and raise SystemExit(3) "
            "escaped _execute_code; the sandbox blocked only sys.exit."
        ),
        cause="except Exception does not catch SystemExit, and exit() or a raised SystemExit never goes through sys.exit.",
        fix="Catch (Exception, SystemExit) in _execute_code and in the deferred check_fn call.",
        guarded_by=(
            "tests/blender/test_review_mcp_addon.py::"
            "test_exiting_code_is_an_error_response_not_an_exit"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="select-on-buffered-reader-misses-lines",
        scope="harness_code",
        failure=(
            "select() reported the second JSON line 'not ready' after "
            "readline() returned the first, so the test client timed out on "
            "a response it already held."
        ),
        cause="select sees the OS pipe, not Python's BufferedReader buffer.",
        fix="Read with os.read into the client's own line buffer.",
        guarded_by=(
            "tests/pure/test_review_mcp_addon.py::"
            "test_response_in_the_same_chunk_as_a_notification_is_not_missed"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="integration-test-home-only-sandbox",
        scope="process",
        failure=(
            "The LLM integration test set only HOME, then ran 'extension "
            "install-file --enable' and save_userpref(): on macOS that "
            "overwrites the real userpref.blend."
        ),
        cause="HOME does not isolate Blender's config directory on macOS.",
        fix="Set BLENDER_USER_RESOURCES and assert user_resource('CONFIG') is inside the tempdir before any install or save.",
        guarded_by=(
            "blender_mcp/tests/integration/test_blender_mcp_with_llm.py::"
            "_assert_blender_config_isolated"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="test-file-embeds-real-api-key",
        scope="process",
        failure=(
            "Commit 1c65544 put the real bmb llama-swap key (64 hex) in "
            "tests/pure/test_openai_transport.py in a PUBLIC repository; the "
            "same test compared against the real key file, so it passed only "
            "on this machine. The key is in history and must be rotated."
        ),
        cause=(
            "The test needed 'a bmb key' and the live one was pasted; the "
            "assertion read it back through a name imported before the monkeypatch."
        ),
        fix="A fake key; an autouse fixture isolates _read_bmb_api_key, OLLAMA_HOST and OLLAMA_API_KEY.",
        guarded_by=(
            "tests/pure/test_openai_transport.py::"
            "test_the_bmb_key_file_feeds_bmb_models_only"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="describer-routing-asserted-on-writer-client",
        scope="harness_code",
        failure="The describer routing assertions passed whatever the eye routing did.",
        cause="VisionDescriber.client is the writer's client, so asserting its endpoint checks the writer.",
        fix="Drive describe() through a captured _request and assert the endpoint the eye actually hit.",
        guarded_by=(
            "tests/pure/test_openai_transport.py::"
            "test_the_eye_rides_the_daemon_when_the_writer_rides_bmb"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="wire-edge-passed-the-manifold-gate",
        scope="harness_code",
        failure=(
            "A closed six-face cube plus one edge to a lone vertex measured "
            "non_manifold_edge_count == 0 and failures(MeshBudget()) listed "
            "no non-manifold entry (assert 0 == 1); the gate passed a mesh "
            "with a hanging wire edge."
        ),
        cause=(
            "analyze_object counted only edges shared by MORE than two faces. "
            "An edge shared by none (link_faces == 0) is neither that nor a "
            "boundary edge (== 1), yet Blender's own Select Non-Manifold "
            "selects it. A gate that counts a narrower predicate than the "
            "name it reports under cannot fail on the case it omits, and no "
            "golden carried a wire edge."
        ),
        fix="The predicate is `len(edge.link_faces) > 2 or len(edge.link_faces) == 0`.",
        guarded_by=(
            "tests/blender/test_review_followup.py::"
            "test_a_wire_edge_on_a_closed_cube_fails_the_manifold_gate"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="splayed-leg-axis-ended-short-of-the-top",
        scope="harness_code",
        failure=(
            "On STOOL_SPEC the leg axis, walked length_m up from the base, "
            "ended at z = 0.409632 against top_z_m 0.41 (0.37 mm short) and "
            "0.06 mm outboard of top_radius_m; the foot circle was exact."
        ),
        cause=(
            "length_m added sole_drop_m, which is measured straight down, to "
            "a length measured along the splayed axis: the axis must regain "
            "drop / cos(splay). The test that was meant to guard it asserted "
            "the same formula (hypot + drop) as its expectation, so the "
            "derivation it checked was the derivation it shared."
        ),
        fix=(
            "length_m = hypot(rise, run) + sole_drop_m / cos(splay_rad); the "
            "guard now walks the axis from the base and compares where it "
            "ends with top_z_m and top_radius_m."
        ),
        guarded_by=(
            "tests/pure/test_splayed_leg_spec.py::"
            "test_the_axis_top_lands_on_the_top_circle"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="glb-import-recentred-on-vertex-mean",
        scope="harness_code",
        failure=(
            "A unit cube with ten cuts on each +X face edge, exported to GLB "
            "and read back by import_glb, had its bounding-box centre x at "
            "-0.3846 m (assert 0.3846154 < 1e-05): the mean of the vertices "
            "sat at 0, the box did not."
        ),
        cause=(
            "import_glb recentred on the mean of the vertex coordinates, so "
            "the result depended on tessellation density; the stated "
            "convention is 'centered on X/Y'."
        ),
        fix="Recentre on the bounding-box centre, (min + max) / 2 on x and y.",
        guarded_by=(
            "tests/blender/test_review_followup.py::"
            "test_import_glb_centres_on_the_bounding_box_not_the_vertex_mean"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="reset-left-frame-range-units-and-resolution",
        scope="harness_code",
        failure=(
            "The review measured frame_start/end/current (5/99/42), "
            "unit_settings.scale_length (0.01) and render.resolution_x (321) "
            "surviving reset_scene. This change's own fail-before: "
            "assert_clean_scene() after frame_end = 99 raised nothing "
            "('DID NOT RAISE SceneNotClean')."
        ),
        cause=(
            "reset_scene wiped datablocks and restored fps only, and "
            "assert_clean_scene checked the same two things, so a rebuild "
            "started from whatever the previous build left in the scene "
            "settings."
        ),
        fix=(
            "reset_scene restores the frame range and current frame, the "
            "unit system, scale and length unit and the render resolution "
            "to Blender 5.2.0's factory values (named CANONICAL_* "
            "constants); assert_clean_scene reports each mismatch."
        ),
        guarded_by=(
            "tests/blender/test_review_followup.py::"
            "test_reset_scene_restores_frame_range_units_and_resolution and "
            "::test_a_stale_frame_end_after_reset_is_not_a_clean_scene"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="addon-bound-any-host-without-auth",
        scope="harness_code",
        failure=(
            "mcp_to_blender_server.start('0.0.0.0', port) bound and "
            "listened (pytest.raises(ValueError): 'DID NOT RAISE'); the "
            "server runs arbitrary Python from any peer with no "
            "authentication."
        ),
        cause=(
            "The host preference and --host accepted any string; only the "
            "default ('localhost') was loopback."
        ),
        fix=(
            "start() resolves the host first and refuses, with a ValueError "
            "naming the addresses, unless every one is loopback."
        ),
        guarded_by=(
            "tests/blender/test_review_mcp_addon.py::"
            "test_the_server_refuses_a_non_loopback_host and "
            "::test_the_server_still_binds_loopback"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="http-transport-without-rebinding-protection",
        scope="harness_code",
        failure=(
            "blender-mcp --transport http set "
            "enable_dns_rebinding_protection=False and accepted --host "
            "0.0.0.0 (read from the code; the pre-fix server was not run): "
            "with run_python behind it, any page that reaches the port had "
            "code execution in Blender. After the fix, a live server "
            "answered Host evil.example with 421 and Origin "
            "http://evil.example with 403, and 200 for a loopback Host and "
            "a localhost Origin."
        ),
        cause=(
            "Upstream disabled the check so the llama.cpp web UI could "
            "connect, and nothing restricted the bind address."
        ),
        fix=(
            "--host must resolve only to loopback (parser.error otherwise); "
            "the transport allows only loopback Host and Origin headers "
            "(LOOPBACK_ALLOWED_HOSTS / LOOPBACK_ALLOWED_ORIGINS). CORS "
            "stays, since the Origin check now refuses other pages."
        ),
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_the_http_transport_refuses_a_non_loopback_host and "
            "::test_the_transport_security_settings_reject_a_rebound_host_and_origin"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="raised-chunk-reindented-string-literals",
        scope="harness_code",
        failure=(
            "A raised-but-built chunk whose source was NOTE = '''a\\nb''' "
            "replayed with NOTE == 'a\\n    b' (assert 'a\\n    b' == "
            "'a\\nb'): the bake built a different value than the run did."
        ),
        cause=(
            "standalone_script wrapped the body in try: with "
            "textwrap.indent, which also indents the continuation lines "
            "inside a triple-quoted string."
        ),
        fix=(
            "The body is emitted as exec(compile(<repr>, <label>, 'exec'), "
            "globals()) inside the try, byte for byte; the labels are "
            "unchanged because scripts/finetune_* prefix-match them."
        ),
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_a_raised_chunk_keeps_its_multiline_string_literals"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="render-path-returned-a-file-blender-never-wrote",
        scope="harness_code",
        failure=(
            "render_viewport_to_path and render_thumbnail_to_path answered "
            "with filepath '<tempdir>/blender_mcp/probe' for output_path "
            "'probe' (assert result.filepath.endswith('.png') failed); "
            "with the extension resolved first, the file exists at "
            "'.../probe.png'."
        ),
        cause=(
            "write_still appends the format's extension to render.filepath "
            "when use_file_extension is set, and the tool reported the "
            "path it had set, not the path Blender wrote. The deferred "
            "check for the file watched the same wrong path."
        ),
        fix=(
            "The extension (render.file_extension) is appended before "
            "filepath is set, so the deferred check and the returned path "
            "name the real file."
        ),
        guarded_by=(
            "tests/blender/test_review_mcp_tools.py::"
            "test_a_render_tool_returns_the_file_it_wrote"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="objects-summary-hide-viewport-read-view-layer-hide",
        scope="harness_code",
        failure=(
            "get_objects_summary reported hide_viewport False for an "
            "object whose hide_viewport was True (assert False is True)."
        ),
        cause=(
            "The field was filled from obj.hide_get(), the view-layer eye, "
            "which is a different property from the monitor icon "
            "obj.hide_viewport."
        ),
        fix=(
            "hide_viewport reads obj.hide_viewport; the view-layer hide "
            "is reported separately as hide_in_view_layer."
        ),
        guarded_by=(
            "tests/blender/test_review_mcp_tools.py::"
            "test_the_objects_summary_separates_viewport_hide_from_view_layer_hide"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="watchdog-kill-surfaced-as-json-error",
        scope="harness_code",
        failure=(
            "A CLI killed by the watchdog mid-frame (stdout ended on "
            "'{\"type\":') raised JSONDecodeError: Expecting value: line 1 "
            "column 9 (char 8) instead of 'did not answer within'."
        ),
        cause=(
            "The kill truncates the last stdout line; _consume parsed that "
            "fragment and the except BaseException handler re-raised the "
            "symptom before the timed_out check could report the cause."
        ),
        fix="chat() re-raises only when the watchdog did not fire; otherwise the timeout is reported.",
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_a_watchdog_kill_mid_frame_reports_the_timeout_not_a_json_error"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="auth-status-non-object-crashed-check-connection",
        scope="harness_code",
        failure=(
            "`claude auth status` printing '[]' raised AttributeError: "
            "'list' object has no attribute 'get' out of check_connection."
        ),
        cause="Only json.loads sat inside the try; the result was used as a dict unchecked.",
        fix="A payload that is not a JSON object is a failed check naming its type.",
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_an_auth_status_that_is_not_a_json_object_is_a_failed_check"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="duplicate-skill-module-name-unchecked",
        scope="harness_code",
        failure=(
            "With the first registered skill module listed twice, "
            "validate_modules() returned [] while get_module served only "
            "the first."
        ),
        cause="`registered` was a set, so a repeated name collapsed to one.",
        fix="validate_modules counts names and reports any registered more than once.",
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_a_duplicate_skill_module_name_is_a_registry_problem"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="bmb-key-committed-in-public-history",
        scope="process",
        failure=(
            "The bmb llama-swap key (64 hex) sat in "
            "tests/pure/test_openai_transport.py from commit 1c65544 in a "
            "PUBLIC repository. Rotated 2026-10-07: a POST to "
            "/v1/chat/completions with the new key answered 400 (the key "
            "passed auth; the probe sends a nonexistent model) and with "
            "the old key 401."
        ),
        cause=(
            "A real credential was pasted into a test as a literal; the "
            "tree was cleaned later but history keeps it, and cleaning the "
            "tree is not rotating the key."
        ),
        fix=(
            "A new key replaced the old entry in bmb's llama-swap apiKeys "
            "(hot-reloaded) and in ~/.blended/bmb_api_key (mode 0600); "
            "history was not rewritten, by the owner's decision. The test "
            "now feeds a fake key through the key file."
        ),
        guarded_by=(
            "tests/pure/test_openai_transport.py::"
            "test_the_bmb_key_file_feeds_bmb_models_only"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="drift-fix-text-claimed-silent-empty",
        scope="harness_code",
        failure=(
            "The drift catalog told the model that reading action.fcurves "
            "'returns empty and silently does nothing'. Measured on Blender "
            "5.2.0 LTS: it raises AttributeError ('Action' object has no "
            "attribute 'fcurves'). The text is in the assembled prompt."
        ),
        cause=(
            "The fix text described a guess about the failure mode, not the "
            "traceback the signature matches."
        ),
        fix=(
            "The text states the measured AttributeError; the assembled "
            "fingerprint moved a10:c68237772de1 -> a10:c16070bc954b with "
            "no new revision (the OT-24 precedent) and the pin was rewritten."
        ),
        guarded_by=(
            "tests/blender/test_review_analyze_capture.py::"
            "test_drift_signatures_match_the_error_blender_really_raises"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="formatter-target-newer-than-blender-python",
        scope="harness_code",
        failure=(
            "After `ruff format .`, `make test-blender-app` failed at import: "
            "mcp_to_blender_server.py line 258, `except Exception, "
            "SystemExit:` — SyntaxError: multiple exception types must be "
            "parenthesized. Four sites in two add-on files "
            "(mcp_to_blender_server.py x3, deferred_tool.py x1). ruff check, "
            "mypy and make test-pure (the dev venv, Python 3.11) stayed "
            "green; only Blender's own import saw it."
        ),
        cause=(
            "blender_mcp/addon/pyproject.toml, the subtree's own config, "
            "sets ruff target-version py314. ruff format drops the "
            "parentheses around an except tuple for a 3.14 target (PEP 758), "
            "and Blender 5.2.0 LTS runs Python 3.13.13 (measured). The "
            "formatter was told a Python newer than the one that runs the "
            "file."
        ),
        fix=(
            "The add-on's target-version is py313, the Python the installed "
            "Blender runs; the add-on was reformatted from its pre-format "
            "state."
        ),
        guarded_by=(
            "tests/pure/test_review_followup.py::"
            "test_every_python_file_parses_under_the_minimum_python"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="missing-blender-surfaced-as-raw-errors-and-a-headless-spawn",
        scope="harness_code",
        failure=(
            "With no Blender answering, over the real stdio server (measured on "
            "main f1a2636 against an isolated GUI Blender that was then "
            "killed): list_scene came back as 'Cannot connect to Blender at "
            "...', get_objects_summary as 'Error executing tool ...: Cannot "
            "connect ...', add_box as 'No plan declared this turn' (the plan "
            "gate ran before anything looked for Blender), and "
            "get_blendfile_summary_path_info_for_cli started a headless "
            "Blender ('Blender executable not found at blender' without "
            "BLENDER_PATH; with it, subprocess.run of Blender --background "
            "answered status ok from the file on disk). An agent could read "
            "none of these as 'stop and tell the user'."
        ),
        cause=(
            "send_code's ConnectionError propagated raw (FastMCP wraps an "
            "upstream one in a ToolError), the plan check ran first, and the "
            "five *_for_cli tools had a second path, run_blender_cli, so a "
            "missing Blender was silently worked around with a different one "
            "than the user's open session."
        ),
        fix=(
            "Every tool except the three docs-only ones looks for the open "
            "Blender first (require_live_blender, before the plan gate), and "
            "any ConnectionError becomes an error result that starts with "
            "PAUSED:, names the host and port, and tells the agent to stop and "
            "tell the user. A *_for_cli tool answers from the open Blender "
            "when it has that file open and otherwise pauses naming both "
            "files; blender_cli.py and BLENDER_PATH are deleted, so nothing "
            "can start a headless Blender. The instructions head carries the "
            "rule and the same PAUSED: constant."
        ),
        guarded_by=(
            "tests/pure/test_live_blender.py::"
            "test_every_tool_pauses_when_no_blender_answers and "
            "::test_a_for_cli_tool_pauses_when_the_open_blender_has_another_file; "
            "blender_mcp/tests/test_blender_mcp_with_blender.py::"
            "test_a_for_cli_tool_pauses_when_the_open_blender_has_another_file"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="viewport-followed-names-not-changes",
        scope="harness_code",
        failure=(
            "A run_python chunk that moved Crate without naming it ended "
            "'viewport: unchanged: nothing this call touched is in the scene "
            "yet' and the view stayed put (measured over the real stdio "
            "server on main f1a2636, and in a GUI Blender: "
            "follow_viewport(ToolOutcome('ok')) after moving a box 3 m left "
            "view_distance as it was)."
        ),
        cause=(
            "The framing targets were the names the outcome carried (gated "
            "objects and op arguments); a chunk that names nothing "
            "contributes none. Every earlier framing test handed the framer "
            "a name, so none could fail on this."
        ),
        fix=(
            "snapshot_scene() before a scene-changing call and "
            "changed_object_names() after it add every object the call "
            "created or changed (type, parent, world transform, data-block, "
            "material slots, modifier stack, base-mesh coordinates, "
            "evaluated bounding box) to what is framed. Known blind spot: a "
            "setting that changes none of those, such as a bevel width on a "
            "cube (the first draft of the modifier test used one and the diff "
            "was empty, because a bevel leaves a cube's bounds as they were)."
        ),
        guarded_by=(
            "tests/blender/test_viewport_follow_diff.py::"
            "test_a_moved_object_is_changed_without_a_view_layer_update and "
            "::test_an_in_place_vertex_edit_is_changed; make test-viewport-gui "
            "(tests/gui/check_viewport_follow.py: the unnamed move, with a "
            "no-snapshot control that frames nothing)"
        ),
        recorded_on="2026-10-07",
    ),
    MistakeRecord(
        identifier="stubbed-send_code-test-passed-only-with-a-blender-listening",
        scope="harness_code",
        failure=(
            "make test-mcp on 6250965 with nothing listening on 9876: "
            "blender_mcp/tests/test_blended_bridge.py ran 28 tests, 7 errored "
            "with LiveBlenderUnavailable 'No open Blender answers at "
            "localhost:9876 (Connection refused)' (4 in TestBlendedBridge, 3 in "
            "TestHandoff). The same file ran 28/28 OK with a throwaway "
            "listener on a spare port and BLENDER_MCP_PORT pointing at it."
        ),
        cause=(
            "BlendedSession.call() now probes for the open Blender (a socket "
            "connect) before the plan gate, and these suites stubbed only "
            "send_code. The probe is a second route to Blender that the stub "
            "did not cover, so the suite's verdict depended on whether the "
            "developer's Blender bridge happened to be up. A passing run on a "
            "machine with a listener says nothing about the same run without "
            "one."
        ),
        fix=(
            "_stub_live_blender_probe(test_case) patches "
            "blended_bridge.require_live_blender in both setUps that stub "
            "send_code. The pause itself is still tested against the real "
            "probe in tests/pure/test_live_blender.py. Known blind spot: a "
            "run with a Blender listening still passes whether or not the "
            "stub is there, so only a run with nothing on the port can catch "
            "its removal."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blended_bridge.py::TestBlendedBridge and "
            "::TestHandoff, run with nothing listening on the Blender port: "
            "make test-mcp"
        ),
        recorded_on="2026-10-08",
    ),
    MistakeRecord(
        identifier="libraries-write-segfaults-on-a-scene-made-by-scenes-new",
        scope="harness_code",
        failure=(
            "The first save_blend wrote the named objects through "
            "bpy.data.libraries.write from a temporary scene made by "
            "bpy.data.scenes.new plus a temporary collection. The first "
            "test run killed Blender with 'Fatal Python error: Segmentation "
            "fault' at the write call, in the user's own tool path."
        ),
        cause=(
            "Measured 2026-10-10 in Blender 5.2.0 LTS with a scratch "
            "script: libraries.write on ANY scene created by scenes.new "
            "segfaults (empty, with objects linked directly, with a world "
            "set, compressed or not), while the same call on the session's "
            "own scene, on a Scene.copy() and on a Collection holding the "
            "same object writes fine. The failure is in the new scene, not "
            "in the objects or the path."
        ),
        fix=(
            "save_blend writes an emptied shallow copy of the current scene "
            "(Scene.copy(), children and objects unlinked from the copy's "
            "own master collection, camera and world cleared, the named "
            "objects linked in), then removes the copy. Unlinking from the "
            "copy's master collection leaves the live collections alone, "
            "which the session-unchanged test measures."
        ),
        guarded_by=(
            "tests/blender/test_save_blend.py::"
            "test_the_file_reopens_with_exactly_the_named_objects and "
            "::test_the_session_is_unchanged_by_the_save (a segfault takes "
            "the whole Blender layer down, so it cannot pass quietly)"
        ),
        recorded_on="2026-10-10",
    ),
    MistakeRecord(
        identifier="the-blender-test-layer-imported-the-venvs-numpy-and-pillow",
        scope="process",
        failure=(
            "make test-blender-app collected zero tests: "
            "tests/blender/test_review_eval_rest.py failed at import with "
            "'No module named numpy._core._multiarray_umath' (a "
            "cpython-311 .so under Blender's Python 3.13), and after "
            "appending the venv instead, every capture test failed at "
            "'cannot import name _imaging from PIL'."
        ),
        cause=(
            "numpy 2.4.6 and pillow 12.3.0 were installed into .venv on "
            "2026-10-09, against the Makefile's rule that they never enter "
            "it. scripts/run_tests_in_blender.py put the whole venv "
            "site-packages first on Blender's sys.path, so a compiled "
            "package built for another Python shadowed Blender's own "
            "numpy, and Pillow has no Blender copy to fall back on."
        ),
        fix=(
            "A path filter was not enough: test_bench_bridge's prelude "
            "inserts the venv at sys.path[0] again mid-run. The script now "
            "imports Blender's own numpy before the venv is visible and "
            "marks PIL, scipy and trimesh absent in sys.modules (a None "
            "entry: import raises ModuleNotFoundError, find_spec returns "
            "None), so Blender runs with its bundled numpy and no Pillow "
            "whatever lands in the venv. The venv itself was not touched, "
            "because other tools may run on it."
        ),
        guarded_by=(
            "make test-blender-app itself (it imports numpy-using test "
            "modules and the capture path under Blender); "
            "scripts/run_tests_in_blender.py (the sys.modules block)"
        ),
        recorded_on="2026-10-10",
    ),
    MistakeRecord(
        identifier="the-documented-head-length-was-a-stale-copy",
        scope="process",
        failure=(
            "The README, the spec and a mistake record all said "
            "MCP_INSTRUCTIONS_HEAD is 1,823 characters, leaving 225 spare; "
            "OT-50 planned a rule that needed about 190. The head measured "
            "1,981, leaving 67, so the rule did not fit."
        ),
        cause=(
            "1,823 was a measurement from 2026-10-02 copied forward through "
            "later edits to the head; no test compared the documented "
            "number with len(MCP_INSTRUCTIONS_HEAD), only with the limit."
        ),
        fix=(
            "Measured the head (1,981), shortened the intro and the "
            "viewport paragraph (dropping the 'every client delivers this "
            "head' sentence and the 'found by comparing' parenthetical), "
            "and added the .blend rule: 2,047 of 2,048. The README states "
            "the measured number and a test compares it with the head. The "
            "older record above keeps its 1,823 as the number true on its "
            "date."
        ),
        guarded_by=(
            "blender_mcp/tests/test_blended_bridge.py::TestInstructionsHead::"
            "test_readme_states_the_measured_head_length"
        ),
        recorded_on="2026-10-10",
    ),
    MistakeRecord(
        identifier="a-reexported-dependency-type-imports-the-dependency-at-facade-import",
        scope="harness_code",
        failure=(
            "The OT-51 brief asked blended.ops.motion to re-export skinclip's "
            "RingSkirtSpec while importing skinclip only inside op bodies. "
            "With skinclip v0.1.0, `sys.modules['numpy'] = None; from "
            "skinclip.cloth import RingSkirtSpec` raised ModuleNotFoundError "
            "at skinclip/cloth.py line 27 (`import numpy as np`); numpy is "
            "absent from .venv by rule, so that import was the facade's, the "
            "MCP server's and tests/pure's. The first fix was a mirror "
            "dataclass in blended, field for field, with a test comparing "
            "the two."
        ),
        cause=(
            "A type that lives in a numpy module cannot be named in a "
            "module that must import without numpy: `typing.get_type_hints` "
            "(the schema generator) and `dataclasses.fields` (the manifest) "
            "need the real class in the module's globals, so a lazy "
            "`__getattr__` is not enough. A copy of a dependency's type is a "
            "second definition that can drift."
        ),
        fix=(
            "skinclip v0.1.1 moved RingSkirtSpec into skinclip.spec, a module "
            "that imports nothing; blended.ops.motion re-exports that class "
            "(the mirror and its field-for-field test are deleted). The "
            "construction checks skinclip's dataclass first lacked (equal "
            "heights divide by zero in the weights) were kept in blended "
            "until skinclip v0.1.2 put them in RingSkirtSpec.__post_init__; "
            "blended's copy was deleted, and the agent binds the spec while "
            "building the call, so a bad spec fails before the op body and "
            "the scene are reached."
        ),
        guarded_by=(
            "tests/pure/test_motion_ops_pure.py::"
            "test_the_ops_import_with_numpy_unavailable, "
            "tests/pure/test_motion_ops_pure.py::"
            "test_a_bad_spec_fails_before_the_op_body_runs_and_so_before_the_scene_is_touched and "
            "tests/blender/test_motion_ops.py::"
            "test_the_exported_ring_skirt_spec_is_skinclips_own"
        ),
        recorded_on="2026-10-12",
    ),
    MistakeRecord(
        identifier="a-repaired-clip-is-not-a-fixed-point-of-the-repair",
        scope="harness_code",
        failure=(
            "tests/blender/test_motion_ops.py's first second-repair test "
            "asserted frames_repaired == 0 after repairing the tube "
            "humanoid's hand_through_torso; measured 4 frames repaired at "
            "worst_depth_m_before 9.1e-07 m (a micrometre), after a first "
            "pass that took 0.0979 m to 8.9e-07 m."
        ),
        cause=(
            "The solver stops on the clearance's edge (margin 5 mm plus the "
            "capsule radii), and Blender stores keyframes as float32, so "
            "writing the repaired rotations back moves a depth of 0 to a "
            "micrometre. 'No overlap' is a tolerance, not an equality."
        ),
        fix=(
            "The test asserts the invariant the op promises: the second "
            "pass starts and ends at or below 0.002 m and moves no key by "
            "1e-3 or more."
        ),
        guarded_by=(
            "tests/blender/test_motion_ops.py::"
            "test_a_second_repair_only_trims_micrometres"
        ),
        recorded_on="2026-10-12",
    ),
    MistakeRecord(
        identifier="removing-an-fcurve-leaves-the-property-at-its-last-value",
        scope="harness_code",
        failure=(
            "The OT-51 cloth control ('chains that were never baked') removed "
            "the 24 chain bones' rotation_quaternion fcurves and read the "
            "clearance: -0.0555 m on skinclip v0.1.0/v0.1.1, -0.0690 m on "
            "v0.1.2. Same bones, same thighs, but the number moved with the "
            "skinclip version, which a never-baked chain cannot depend on. "
            "With the pose reset to rest it reads -0.0700 m on v0.1.2."
        ),
        cause=(
            "Deleting an fcurve does not reset the property it drove: the "
            "pose bone keeps the last value evaluated, here the baked "
            "frame-30 rotation, so the control held the chains frozen in a "
            "baked pose, not at rest. The comment above it claimed 'rest "
            "pose'. A control must be varied against what it controls: the "
            "number moving with the thing under test was the tell."
        ),
        fix=(
            "The control resets each chain pose bone to the identity "
            "quaternion after removing its curves; the comment records both "
            "readings and the mechanism."
        ),
        guarded_by=(
            "tests/blender/test_motion_ops.py::"
            "test_the_clearance_probe_fails_on_chains_that_were_never_baked"
        ),
        recorded_on="2026-10-12",
    ),
    MistakeRecord(
        identifier="a-probe-ceiling-was-written-before-it-was-measured",
        scope="process",
        failure=(
            "The comment above UNBAKED_CHAIN_CLEARANCE_CEILING_M said the "
            "unbaked chains read about -0.07 m against the swinging thighs; "
            "measured through the same probe they read -0.0555 m (baked: "
            "+0.0113 m)."
        ),
        cause=(
            "The number was estimated from the geometry while the test was "
            "being written, and went into a comment as if measured; the "
            "assertion (< -0.02 m) was loose enough to hide it."
        ),
        fix=(
            "Measured both numbers in Blender and wrote them into the "
            "comment; the control asserts the unbaked reading is below the "
            "ceiling and the baked one above -0.005 m."
        ),
        guarded_by=(
            "tests/blender/test_motion_ops.py::"
            "test_the_clearance_probe_fails_on_chains_that_were_never_baked"
        ),
        recorded_on="2026-10-12",
    ),
)


def validate_memory() -> list[str]:
    """Schema problems (empty list = healthy memory)."""
    problems: list[str] = []
    seen: set[str] = set()
    for record in MISTAKES:
        if record.scope not in SCOPES:
            problems.append(
                f"{record.identifier}: scope {record.scope!r} not in SCOPES"
            )
        if not record.guarded_by.strip():
            problems.append(f"{record.identifier}: no guard — the record is not done")
        if record.identifier in seen:
            problems.append(f"duplicate identifier: {record.identifier}")
        seen.add(record.identifier)
    return problems


def consult(scope: str = "") -> str:
    """Render the memory for reading BEFORE an adjustment.

    Nothing in src/, scripts/, tests/ or blender_mcp/ calls this (grep,
    2026-10-07): whoever consults the memory must run it or read this
    file. If this returns text nobody reads, the memory is decoration.
    """
    selected = [record for record in MISTAKES if not scope or record.scope == scope]
    if not selected:
        return f"(no recorded mistakes for scope {scope!r})"
    lines: list[str] = []
    for record in selected:
        lines.append(f"[{record.scope}] {record.identifier} ({record.recorded_on})")
        lines.append(f"  failure: {record.failure}")
        lines.append(f"  cause:   {record.cause}")
        lines.append(f"  fix:     {record.fix}")
        lines.append(f"  guard:   {record.guarded_by}")
    return "\n".join(lines)
