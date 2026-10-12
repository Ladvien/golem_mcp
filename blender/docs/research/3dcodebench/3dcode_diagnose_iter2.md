# 3DCodeBench diagnostic — blended-deepseek-v4-pro-iter2

Replication: `/Users/ladvien/3dcodebench/metrics/shape_chamfer.py` imported unmodified; 20 instance cd_yawmin values asserted equal to `_metrics/shape_chamfer.json`.

## Per-instance (sorted by cd_yawmin descending)

| instance | cd_yawmin | cd_pca | Δ_orient | verdict | thin_gen | thin_ref | brief(words/quant/orient) | turns | dur_s |
|---|---|---|---|---|---|---|---|---|---|
| CellShelf_seed0 | 0.2863 | 0.0071 | +0.2792 | orientation-artifact | 0.16 | 0.19 | 38/q/- | 29 | 512.91 |
| Mirror_seed0 | 0.2601 | 0.0076 | +0.2524 | orientation-artifact | 0.02 | 0.01 | 42/q/- | 11 | 114.73 |
| Nautilus_seed0 | 0.1666 | 0.0508 | +0.1158 | orientation-artifact | 0.24 | 0.90 | 43/q/flafac | 6 | 348.85 |
| Tap_seed0 | 0.1596 | 0.0628 | +0.0968 | orientation-artifact | 0.27 | 0.65 | 55/q/fla | 19 | 497.52 |
| CabinetDoorIkea_seed0 | 0.1311 | 0.0380 | +0.0931 | orientation-artifact | 0.01 | 0.10 | 66/q/verfla | 2 | 30.35 |
| Sink_seed0 | 0.0837 | 0.0181 | +0.0657 | orientation-artifact | 0.78 | 0.57 | 52/q/fla | 8 | 222.39 |
| Jar_seed0 | 0.0609 | 0.0608 | +0.0001 | shape-mismatch | 0.69 | 0.32 | 42/q/fla | 4 | 162.93 |
| Crab_seed0 | 0.0573 | 0.0207 | +0.0366 | orientation-artifact | 0.24 | 0.56 | 94/q/- | 28 | 379.35 |
| Beetle_seed0 | 0.0438 | 0.0392 | +0.0046 | shape-mismatch | 0.56 | 0.46 | 90/q/fla | 32 | 712.28 |
| FruitStarfruit_seed0 | 0.0417 | 0.0407 | +0.0010 | shape-mismatch | 0.41 | 0.78 | 95/q/- | 7 | 261.6 |
| FoodBox_seed0 | 0.0396 | 0.0174 | +0.0223 | orientation-artifact | 0.51 | 0.31 | 54/q/fla | 35 | 733.83 |
| AquariumTank_seed0 | 0.0278 | 0.0291 | -0.0013 | shape-mismatch | 0.67 | 0.84 | 94/q/fla | 30 | 1159.88 |
| Plate_seed0 | 0.0227 | 0.0227 | +0.0000 | shape-mismatch | 0.06 | 0.21 | 53/q/fla | 4 | 71.06 |
| Rug_seed0 | 0.0138 | 0.0138 | -0.0000 | shape-mismatch | 0.01 | 0.01 | 14/q/fla | 3 | 81.32 |
| Leaf_seed0 | 0.0084 | 0.0078 | +0.0005 | shape-mismatch | 0.06 | 0.05 | 48/q/- | 15 | 336.61 |
| DoorCasing_seed0 | 0.0081 | 0.0081 | +0.0000 | shape-mismatch | 0.02 | 0.17 | 20/q/- | 15 | 511.56 |
| Bottle_seed0 | 0.0074 | 0.0074 | -0.0000 | shape-mismatch | 0.30 | 0.37 | 40/q/- | 7 | 135.16 |
| Pillar_seed0 | 0.0058 | 0.0057 | +0.0000 | shape-mismatch | 0.23 | 0.13 | 40/q/verfla | 11 | 184.1 |
| Spoon_seed0 | 0.0025 | 0.0025 | +0.0000 | shape-mismatch | 0.05 | 0.06 | 51/q/fla | 2 | 103.91 |
| LeafBananaTree_seed0 | 0.0011 | 0.0011 | +0.0000 | shape-mismatch | 0.10 | 0.10 | 43/q/- | 3 | 214.73 |

Orientation artifacts (Δ_orient >= 0.02): 8 — CellShelf_seed0 (Δ=+0.279), Mirror_seed0 (Δ=+0.252), Nautilus_seed0 (Δ=+0.116), Tap_seed0 (Δ=+0.097), CabinetDoorIkea_seed0 (Δ=+0.093), Sink_seed0 (Δ=+0.066), Crab_seed0 (Δ=+0.037), FoodBox_seed0 (Δ=+0.022)

## Reference thin-axis prior (20 baked refs, 10 thin at <0.3 max-extent)

X: 3 (30%), Y: 5 (50%), Z: 2 (20%)
No majority thin axis (>50% of thin references).

## Budget

- instances with meta: 20/20
- tool-call cap(s) seen: [36]
- turns: mean 13.6, max 35, turns>=20: 5
- excluded chunks: 27 total
- mean duration: 338.8s

## Self-test

cd_pca(S,S) < 1e-6; cd_pca(S, Ry90(S)) < 1e-6; cd_yawmin(S, Ry90(S)) > 0.5 — all asserted before this report was written.
