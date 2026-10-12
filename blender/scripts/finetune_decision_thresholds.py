"""Pre-registration for the fine-tune decision experiment (2026-09-19).

Frozen BEFORE any result of this experiment was read, the same way
`scripts/bench_thresholds.py` holds the bench's pre-registration. The
spec is `docs/research/2026-09-19-finetune-decision-experiment.md`; its
§3 decision rules read the four deltas computed from these numbers, so
re-choosing one after seeing a result would be selection on the test set.

Stdlib-only and importing nothing from `blended`, for the same reason
`bench_thresholds` is: the analysis runs under two different venvs (this
repository's `.venv` for the arm runner, 3DCodeBench's own venv for
anything that touches `trimesh`/`scipy`), and a threshold quoted by both
must live in a module neither venv can break. No analysis script may
repeat one of these literals.
"""

from __future__ import annotations

# --- The instance set ------------------------------------------------------
#
# The frozen 20-instance holdout. Byte-identical to the benchmark's own
# `instances_v1.txt` (verified with `cmp`, 2026-09-19), so every arm here
# is scored on exactly the set the archived rolls were scored on.
INSTANCES_FILE = "bench_sets/instances_holdout.txt"
INSTANCES_SHA256 = "ab39317f95e17680cb7faf39c0d14d614fe68828c9afd687eb42946ad2f8bf00"

# --- Sampling (spec §5.2) --------------------------------------------------
#
# k = 3 completions per task at temperature 0.2 plus one greedy draw.
# Seeds are fixed and recorded per completion; a lane that cannot honour
# a seed (the Claude Code CLI accepts neither temperature nor seed) says
# so in its own completion record rather than pretending to.
DRAWS_SAMPLED = 3
TEMPERATURE_SAMPLED = 0.2
SAMPLED_SEEDS = (1, 2, 3)
TEMPERATURE_GREEDY = 0.0
GREEDY_SEED = 0
# 20 instances x 4 draws. EVERY rate in this experiment has this
# denominator: rates are over completions, not over tasks, because a
# task that fails on one draw and passes on another is exactly the
# variance the four draws exist to measure.
COMPLETIONS_PER_ARM = 80

# --- The stage-4 pass bar --------------------------------------------------
#
# `cd_pca <= CD_PCA_PASS` is "shape pass". The repository has no cd_pca
# pass threshold of its own (its ranking metric is `fscore_005`, see
# `bench_thresholds.RANKING_METRIC`), so the bar is the INCUMBENT's own
# measured mean cd_pca over the six surviving 20-instance rolls —
# 0.0252, quoted from `scripts/bench_panel.py` — i.e. "as good as the
# production writer's average archived run". Fixed from PAST rolls,
# before this experiment produced a number.
CD_PCA_PASS = 0.0252

# --- Execution parity with the archive -------------------------------------
#
# The benchmark's own contract (`prompts/text_to_3d_system_prompt.txt`
# tells the model 240 s) and `core/render.py`'s default. The archived
# rolls baked at this value, so holding it keeps every arm comparable to
# the archive. The spec's 120 s would have made this experiment's
# timeouts incomparable with the Phase A denominator.
BAKE_TIMEOUT_SECONDS = 240

# --- Instrument calibration, added when the parity gate was run ------------
#
# NOT a §3 decision threshold: nothing in the decision matrix reads it.
# Recorded here because the parity gate measured that the bake is
# GEOMETRICALLY reproducible and COMBINATORIALLY not: two bakes of the
# same script produce the same solid (volume equal to ~1e-17 relative)
# with a different triangle order, and where the script uses boolean
# modifiers, a different internal tessellation. The bench's scorer draws
# 8,192 surface samples from that triangulation with a fixed seed, so a
# re-bake moves cd_pca by ~3.5e-4. Two consequences, both stated before
# any arm ran:
#   * exact scorer parity is asserted on the SAME artifacts through two
#     model-dir layouts, which is the claim the spec's §5.2 makes;
#   * a re-bake is compared on the SOLID (volume), not on the mesh bytes.
SOLID_VOLUME_RELATIVE_TOLERANCE = 1e-9

# --- §3 decision thresholds (verbatim from the spec) -----------------------
F_GEOM_DO_NOT_TUNE = 0.60  # rule 1: F_geom >= 60% -> do not fine-tune
F_SYNTAX_MINIMUM = 0.40  # rules 2 and 3 gate on F_syntax >= 40%
DELTA_TUNE_MINIMUM_PP = 15.0  # rule 2 vs rule 3 split, percentage points
DELTA_FACADE_MINIMUM_PP = 25.0  # rule 4: the facade is carrying the work
DELTA_SIZE_MAXIMUM_PP = 10.0  # rule 5: a small model is near the frontier

# --- The G3 judge (spec §4) ------------------------------------------------
#
# 40 non-passing executed attempts, stratified across the included rolls,
# of which 20 are hand-checked so the judge's disagreement rate is
# measured rather than assumed.
JUDGE_SAMPLE_SIZE = 40
JUDGE_HAND_VERIFIED = 20

# --- Phase A classification vocabulary ------------------------------------
#
# The spec's codes plus two this execution adds, both stated before any
# row was classified:
#   E7    an executed-path Python error matching none of E1-E4
#         (IndexError, NoneType attribute, KeyError, ...). The spec's
#         enumeration has no bucket for it; it counts inside F_syntax
#         because it is a code-writing failure, which is the class SFT on
#         verified scripts addresses.
#   INFRA an excluded outcome, in NEITHER numerator nor denominator,
#         counted and listed separately. Fingerprint-matched: a stale
#         installed-addon import of the harness, a path inside Blender's
#         application-support tree, or a foreign absolute path.
SYNTAX_CODES = ("E1", "E2", "E3", "E4", "E5", "E7", "O1", "O2")
GEOMETRY_CODES = ("G1", "G2", "G3")
# E6 (executed, empty or degenerate scene) is a failure in neither class:
# the spec's §3 defines F_syntax over E1-E5/O1-O2 and F_geom over G1-G3,
# and E6 is deliberately outside both. It is reported on its own row and
# is part of the failure denominator, so the two shares need not sum to 1.
DEGENERATE_CODE = "E6"
INFRASTRUCTURE_CODE = "INFRA"
# Substrings that mark a bake-environment artifact rather than a model
# failure. Pre-registered from the archive's own 10 ERR_EXEC rows.
INFRASTRUCTURE_FINGERPRINTS = (
    "cannot import name",
    "Library/Application Support/Blender",
    "/lab/",
)
# The second exclusion, added when Phase A first ran and NOT a
# reclassification of anything: an attempt that executed and left a mesh
# for which the roll carries no cd_pca at all. Measured on
# `blended-deepseek-v4-pro-ops-roll1` — 20 rows with `cd_pca: null` in
# both the archived diagnose JSON and the dir's own
# `_metrics/shape_chamfer.json`, that roll being the documented VOID one
# whose chain never ran the bench's bake (BACKLOG.md, OT-9 roll 1).
# Re-baking it today cannot repair it: the parity gate measured that a
# re-bake reproduces the solid but not the tessellation, so a fresh
# score is not the score that roll would have had. Excluded from both
# numerator and denominator, counted and listed.
UNSCORED_CODE = "UNSCORED"
EXCLUDED_CODES = (INFRASTRUCTURE_CODE, UNSCORED_CODE)

# --- Phase C sufficiency reference point -----------------------------------
#
# BlendNet: 8,000 instruction->script pairs (2,000 human-annotated, 6,000
# model-validated); the BlenderLLM self-improvement rounds used ~2,000
# samples each (arXiv:2412.14203, DOI 10.48550/arXiv.2412.14203). A
# usable first SFT run needs roughly this many deduplicated,
# execution-verified pairs.
SFT_PAIRS_MINIMUM = 1000
SFT_PAIRS_COMFORTABLE = 3000

# --- Arms (spec §5.1, with the base-model correction) ----------------------
#
# A2/A3 ride **Qwen2.5-Coder-7B-Instruct**, BlenderLLM's true base, so
# that A4 - A3 is a same-base, same-format SFT delta and A2 - A3 is a
# same-model format delta. Three independent measurements, 2026-09-19,
# against the alternative the HF card names (`Qwen/Qwen2.5-7B-Instruct`):
#   1. BlenderLLM's own `config.json` has
#      `_name_or_path: /wangbenyou/models/Qwen2.5-Coder-7B-Instruct`.
#   2. Its four safetensors shards are byte-identical in SIZE to the
#      coder repo's (4877660776 / 4932751008 / 4330865200 / 1089994880),
#      and its `model.safetensors.index.json` is the SAME blob
#      (6ca5084b...); the non-coder instruct repo's shards and index
#      differ.
#   3. Weights: mean |Δ| against the coder base is 1.0-1.1% of the mean
#      magnitude (q_proj L10 1.61e-4, down_proj L20 1.49e-4,
#      embed_tokens 1.45e-5); against the non-coder instruct it is
#      99-124% (1.70e-2, 1.48e-2, 1.42e-2) — two unrelated checkpoints.
# The card metadata is simply wrong, and the spec's own §5.1 text
# ("BlenderLLM (Qwen2.5-Coder-7B fine-tuned on BlendNet)") agrees with
# the checkpoint.
ARMS = {
    "a1": {"model": "claude-code:sonnet", "format": "ops"},
    "a2": {"model": "qwen2.5-coder-7b-instruct", "format": "ops"},
    "a3": {"model": "qwen2.5-coder-7b-instruct", "format": "raw"},
    "a4": {"model": "blenderllm", "format": "raw"},
    "a5": {"model": "claude-code:sonnet", "format": "raw"},
}
HF_REVISIONS = {
    "qwen2.5-coder-7b-instruct": (
        "Qwen/Qwen2.5-Coder-7B-Instruct",
        "c03e6d358207e414f1eca0bb1891e29f1db0e242",
    ),
    "blenderllm": (
        "FreedomIntelligence/BlenderLLM",
        "095b8f8cdc606b59afa3128805aea233c1ba77b0",
    ),
}
# Served precision and window for both local checkpoints. Q8_0 for BOTH,
# so precision is not a confound between A3 and A4.
#
# F16 was the registered choice and it OOMed, measured: llama-server
# asked CUDA for 13,486.77 MiB of weights and the 3090 refused, because
# 10.0 GiB of the card was already held by two ORPHANED llama-server
# processes (a Qwen3.5-9B with four live ESTABLISHED connections and a
# bge reranker) plus an Ollama child. Those are a foreign workload, so
# they were not preempted. Q8_0 is 7.54 GiB of weights, which fits the
# 14.2 GiB that was actually free, and the plan's own contingency names
# it — for BOTH checkpoints or not at all.
SERVED_PRECISION = "q8_0"
SERVED_CONTEXT_TOKENS = 16_384


def draw_sampling(draw: int) -> tuple[float, int]:
    """(temperature, seed) for a draw index. Draw 0 is the greedy draw."""
    if draw == 0:
        return TEMPERATURE_GREEDY, GREEDY_SEED
    if 1 <= draw <= DRAWS_SAMPLED:
        return TEMPERATURE_SAMPLED, SAMPLED_SEEDS[draw - 1]
    raise ValueError(f"draw {draw} is outside 0..{DRAWS_SAMPLED}")


def model_directory(arm: str, draw: int) -> str:
    """The bench model dir an (arm, draw) writes into. Derived, never passed,
    so a completion record and a rendered turntable cannot disagree."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; known: {sorted(ARMS)}")
    draw_sampling(draw)
    return f"ft-{arm}-k{draw}"


def is_infrastructure(error_text: str) -> bool:
    """An excluded bake-environment artifact, not a model failure."""
    return any(mark in error_text for mark in INFRASTRUCTURE_FINGERPRINTS)
