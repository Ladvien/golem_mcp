# 3DCodeBench iter1 re-roll measurement — Leaf / Jar / FruitStarfruit (3 rolls)

**Question:** is iter1's cd_yawmin_cond regression on these three instances (vs v1) a real
placement-clause effect or per-roll noise?

**Config across all rolls:** identical — writer `deepseek-v4-pro:cloud`, eye
`kimi-k2.7-code:cloud`, prompt variant `description`, max-tool-calls 36, timeout 1200 s,
system prompt pinned at revision 10. Roll 1 = the original iter1 run; rolls 2 and 3 are
fresh sweeps into `blended-deepseek-v4-pro-iter1-roll2` / `-roll3` (fresh model dirs, no
`--overwrite`). Every roll of every instance ended `OK_AGENT_DONE` (roll3 FruitStarfruit
needed one sweep retry after `ERR_EXIT_-11`, then one stale-session script deletion +
re-run after the bench-side bake hit the known `KeyError: 'Stem'` leak; final bake
3/3 OK, executability pass_rate 1.0).

## Per-instance cd_yawmin by roll

| Instance | roll1 (iter1) | roll2 | roll3 | mean | max−min |
|---|---|---|---|---|---|
| Leaf_seed0 | **0.2719** | **0.2767** | **0.2608** | 0.2698 | 0.0159 |
| Jar_seed0 | 0.0853 | 0.0711 | 0.0629 | 0.0731 | 0.0224 |
| FruitStarfruit_seed0 | 0.0677 | 0.0450 | 0.0633 | 0.0587 | 0.0227 |

Reference points: v1 scored Leaf 0.0033, Jar 0.0565, FruitStarfruit (n/a to this comparison
row, v1 not re-run here).

## Verdict

**Leaf is a systematic orientation failure, not a coin flip — and it is the dominant
finding.** Leaf scores 0.26–0.28 on all three independent rolls (criterion for the
"systematic" branch: ≥0.15 on ≥2 of 3 — met on 3 of 3, with a roll spread of only 0.016).
A fresh writer roll does NOT re-roll Leaf back toward its v1 0.0033. The brief
(`data/Leaf_seed0/prompt_description.txt`) describes only "a narrow, elongated leaf …
slender blade with a pointed tip, a visible central midrib … slight natural curvature" —
nothing pins the standing-vs-flat or long-axis-X-vs-Z choice, so the writer's orientation
is unconstrained and it consistently produces the orientation that mismatches the
reference's long axis (reference long along Blender-Y; generated long along Blender-X in
iter1 — a 90° yaw-about-up rotation, which `chamfer_with_yaw` cannot absorb because its
yaw alignment rotates about glTF Z, a depth axis).

**Jar and FruitStarfruit are within re-roll noise.** Jar's three rolls span 0.0224,
FruitStarfruit's 0.0227 — both comfortably inside the ±0.02-per-instance band this plan
anticipated. iter1's apparent regression on these two instances (part of the
0.0706→0.0903 mean delta attributed to three instances) is substantially noise: their
3-roll means (0.0731, 0.0587) sit at or below their iter1 roll-1 values' neighborhood of
v1's own numbers, and a single roll of Jar swings ±0.011 around its mean.

**Consequence for the 20-instance comparison:** single-roll cd_yawmin_cond deltas below
~0.02 on the 20-instance mean are within per-roll noise on this harness; Leaf alone
contributes a stable ~0.013 penalty to the 20-mean (0.27/20) that is real, not noise, and
the runtime orientation intervention (Step 2) targets exactly that failure family.

**Analysis-only note (no prompt edit per plan):** Leaf's brief does not imply a standing
or flat orientation — the failure is un-pinned orientation in the reference-vs-generated
axis convention, not an underspecified brief. The nudge from Step 2 names the measured
axes (long axis along world Y, thin ratio) so it helps both leaf-like orientations; it
does not rely on the brief's wording.