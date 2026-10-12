# 3DCodeBench diagnostic — blended-deepseek-v4-pro-iter3

Replication: `/Users/ladvien/3dcodebench/metrics/shape_chamfer.py` imported unmodified; 20 instance cd_yawmin values asserted equal to `_metrics/shape_chamfer.json`.

## Per-instance (sorted by cd_yawmin descending)

| instance | cd_yawmin | cd_pca | Δ_orient | verdict | thin_gen | thin_ref | brief(words/quant/orient) | turns | dur_s |
|---|---|---|---|---|---|---|---|---|---|
| Leaf_seed0 | 0.2710 | 0.0035 | +0.2675 | orientation-artifact | 0.09 | 0.05 | 48/q/- | 2 | 145.16 |
| DoorCasing_seed0 | 0.2363 | 0.0090 | +0.2274 | orientation-artifact | 0.01 | 0.17 | 20/q/- | 3 | 60.0 |
| Nautilus_seed0 | 0.1776 | 0.0775 | +0.1001 | orientation-artifact | 0.23 | 0.90 | 43/q/flafac | 14 | 717.23 |
| Tap_seed0 | 0.1732 | 0.0680 | +0.1052 | orientation-artifact | 0.24 | 0.65 | 55/q/fla | 9 | 410.41 |
| LeafBananaTree_seed0 | 0.0991 | 0.0017 | +0.0973 | orientation-artifact | 0.07 | 0.10 | 43/q/- | 3 | 226.78 |
| FoodBox_seed0 | 0.0829 | 0.0618 | +0.0211 | orientation-artifact | 0.75 | 0.31 | 54/q/fla | 27 | 702.52 |
| Jar_seed0 | 0.0798 | 0.0798 | +0.0000 | shape-mismatch | 0.74 | 0.32 | 42/q/fla | 22 | 695.95 |
| Sink_seed0 | 0.0669 | 0.0218 | +0.0451 | orientation-artifact | 0.82 | 0.57 | 52/q/fla | 20 | 647.57 |
| Crab_seed0 | 0.0575 | 0.0163 | +0.0412 | orientation-artifact | 0.24 | 0.56 | 94/q/- | 35 | 656.15 |
| CellShelf_seed0 | 0.0547 | 0.0070 | +0.0477 | orientation-artifact | 0.25 | 0.19 | 38/q/- | 15 | 497.81 |
| Mirror_seed0 | 0.0477 | 0.0257 | +0.0220 | orientation-artifact | 0.02 | 0.01 | 42/q/- | 7 | 273.09 |
| CabinetDoorIkea_seed0 | 0.0380 | 0.0380 | +0.0000 | shape-mismatch | 0.01 | 0.10 | 66/q/verfla | 4 | 42.01 |
| AquariumTank_seed0 | 0.0331 | 0.0343 | -0.0012 | shape-mismatch | 0.50 | 0.84 | 94/q/fla | 29 | 896.97 |
| Plate_seed0 | 0.0224 | 0.0224 | -0.0000 | shape-mismatch | 0.06 | 0.21 | 53/q/fla | 4 | 104.97 |
| FruitStarfruit_seed0 | 0.0224 | 0.0207 | +0.0017 | shape-mismatch | 0.52 | 0.78 | 95/q/- | 25 | 358.46 |
| Pillar_seed0 | 0.0185 | 0.0185 | +0.0000 | shape-mismatch | 0.29 | 0.13 | 40/q/verfla | 32 | 694.01 |
| Beetle_seed0 | 0.0153 | 0.0148 | +0.0005 | shape-mismatch | 0.41 | 0.46 | 90/q/fla | 7 | 204.08 |
| Rug_seed0 | 0.0144 | 0.0144 | +0.0000 | shape-mismatch | 0.01 | 0.01 | 14/q/fla | 3 | 32.19 |
| Bottle_seed0 | 0.0067 | 0.0067 | -0.0000 | shape-mismatch | 0.30 | 0.37 | 40/q/- | 8 | 111.05 |
| Spoon_seed0 | 0.0044 | 0.0044 | -0.0000 | shape-mismatch | 0.04 | 0.06 | 51/q/fla | 34 | 689.94 |

Orientation artifacts (Δ_orient >= 0.02): 10 — Leaf_seed0 (Δ=+0.268), DoorCasing_seed0 (Δ=+0.227), Nautilus_seed0 (Δ=+0.100), Tap_seed0 (Δ=+0.105), LeafBananaTree_seed0 (Δ=+0.097), FoodBox_seed0 (Δ=+0.021), Sink_seed0 (Δ=+0.045), Crab_seed0 (Δ=+0.041), CellShelf_seed0 (Δ=+0.048), Mirror_seed0 (Δ=+0.022)

## Reference thin-axis prior (20 baked refs, 10 thin at <0.3 max-extent)

X: 3 (30%), Y: 5 (50%), Z: 2 (20%)
No majority thin axis (>50% of thin references).

## Budget

- instances with meta: 20/20
- tool-call cap(s) seen: [36]
- turns: mean 15.2, max 35, turns>=20: 8
- excluded chunks: 24 total
- mean duration: 408.3s

## Self-test

cd_pca(S,S) < 1e-6; cd_pca(S, Ry90(S)) < 1e-6; cd_yawmin(S, Ry90(S)) > 0.5 — all asserted before this report was written.

## iter3 pre-registered outcome — HYPOTHESIS FAILED

iter3 changed exactly one thing against iter2: `scripts/run_3dcode_instance.py`
appends a deterministic orientation epilogue
(`blended.ops.canonical_orientation.apply_canonical_depth_axis`) that turns the
scene so its MIDDLE world extent lies on Blender Y — the depth axis, i.e. the
one degree of freedom `metrics/shape_chamfer.py chamfer_with_yaw` penalises in
full. Writer `deepseek-v4-pro:cloud`, eye `kimi-k2.7-code:cloud`, prompt pinned
v10, `--max-tool-calls 36`, all unchanged. The iter2 in-band nudge (which fired
0/20) was deleted.

| quantity | pre-registered | observed |
|---|---|---|
| `cd_yawmin_cond` | 0.040 - 0.050 (target <= 0.060) | **0.0761** |
| delta vs iter2 (0.0714) | -0.032 | +0.0047 |
| `exec_pass_rate` | 1.0 | **1.0 (20/20)** |
| orientation artifacts (Δ_orient >= 0.02) | fewer than iter2's 8 | 10 |
| mean Δ_orient | ~0.016 | 0.0488 (iter2: 0.048) |
| mean `cd_pca` (shape error) | unchanged ~0.023 | 0.0273 |

0.0761 is above the pre-registered ambiguity band `[0.055, 0.065]`, so this is a
failed hypothesis: no second roll was taken and the policy constant was NOT
re-tuned against the holdout, which is the generalization-gap failure MLE-bench
documents (DOI 10.48550/arXiv.2507.02554). +0.0047 against iter2 is also well
inside the measured ±0.02 single-roll noise floor (DOI 10.1145/3697010), so the
honest reading is "no measurable change", not "a regression".

### The mechanism worked; the hypothesis was wrong

`scripts/orientation_policy_sim.py --generated-model blended-deepseek-v4-pro-iter3`
reports **20/20** generated GLBs carrying the middle extent on glTF Z (17 exact
rank 1; Bottle, Jar and Pillar are radially symmetric, where glTF X and Z agree
to within 0.1% of max and the rank position is meaningless). So the epilogue
fired everywhere and survived the glTF export — unlike iter2's nudge, which
fired 0/20. The failure is in the premise, not the plumbing.

Post-hoc (`outputs/bench/orientation_policy_sim_holdout_posthoc.md`, run over the
HOLDOUT references only, after the roll, and used for explanation only — the
shipped constant is still the dev-derived `DEPTH_AXIS_EXTENT_RANK = 1`):

| depth-axis policy | dev (145) | holdout (20) |
|---|---|---|
| rank 0 - largest on depth | 0.0701 | 0.0970 |
| rank 1 - middle on depth | **0.0311** | **0.0590** |
| rank 2 - smallest on depth | 0.0883 | 0.1355 |
| unconstrained | 0.0632 | 0.0972 |

Rank 1 is still the argmin on the holdout, so the policy choice generalised —
its VALUE did not. A shape-perfect generation obeying this rule still pays
0.0590 on these 20 references, because the holdout is harder than dev: 10/20
references are thin (min/max < 0.3) against 54/145 on dev, and only 7/20 hold
their middle extent on the depth axis against 59/145. Adding the measured shape
error (mean `cd_pca` 0.0273) to a 0.0590 orientation floor cannot reach 0.060.
**The <= 0.060 target was unreachable through orientation alone on this holdout,
and the dev floor understated the holdout floor by 1.9x.** That understatement is
itself the pre-registration lesson: a floor measured on the dev split is not a
floor on the test split.

The residual is now genuinely split two ways: 0.0273 mean shape error
(`cd_pca`), and 0.0488 mean orientation that a single canonical axis assignment
provably cannot remove — the four worst instances (Leaf +0.268, DoorCasing
+0.227, Tap +0.105, Nautilus +0.100) are thin panels and spouts whose references
put their LONGEST extent on depth, exactly the 9/20 rank-0 majority this rule
turns away from. Both are different experiments and need their own plans; per the
plan's own terminal condition, this one stops here.
