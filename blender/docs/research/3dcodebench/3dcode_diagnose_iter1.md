# 3DCodeBench diagnostic — blended-deepseek-v4-pro-iter1

Replication: `/Users/ladvien/3dcodebench/metrics/shape_chamfer.py` imported unmodified; 20 instance cd_yawmin values asserted equal to `_metrics/shape_chamfer.json`.

## Per-instance (sorted by cd_yawmin descending)

| instance | cd_yawmin | cd_pca | Δ_orient | verdict | thin_gen | thin_ref | brief(words/quant/orient) | turns | dur_s |
|---|---|---|---|---|---|---|---|---|---|
| Leaf_seed0 | 0.2719 | 0.0025 | +0.2693 | orientation-artifact | 0.09 | 0.05 | 48/q/- | 1 | 133.59 |
| Mirror_seed0 | 0.2454 | 0.0175 | +0.2279 | orientation-artifact | 0.02 | 0.01 | 42/q/- | 10 | 186.29 |
| CellShelf_seed0 | 0.2412 | 0.0068 | +0.2345 | orientation-artifact | 0.22 | 0.19 | 38/q/- | 24 | 478.17 |
| Tap_seed0 | 0.1723 | 0.0569 | +0.1154 | orientation-artifact | 0.31 | 0.65 | 55/q/fla | 8 | 182.21 |
| Nautilus_seed0 | 0.1570 | 0.0502 | +0.1068 | orientation-artifact | 0.23 | 0.90 | 43/q/flafac | 4 | 264.99 |
| CabinetDoorIkea_seed0 | 0.1311 | 0.0380 | +0.0931 | orientation-artifact | 0.01 | 0.10 | 66/q/verfla | 3 | 23.96 |
| LeafBananaTree_seed0 | 0.1239 | 0.0028 | +0.1211 | orientation-artifact | 0.16 | 0.10 | 43/q/- | 13 | 544.35 |
| Jar_seed0 | 0.0853 | 0.0853 | +0.0000 | shape-mismatch | 0.76 | 0.32 | 42/q/fla | 12 | 179.04 |
| Sink_seed0 | 0.0839 | 0.0118 | +0.0720 | orientation-artifact | 0.65 | 0.57 | 52/q/fla | 13 | 472.51 |
| FruitStarfruit_seed0 | 0.0677 | 0.0669 | +0.0009 | shape-mismatch | 0.32 | 0.78 | 95/q/- | 9 | 209.99 |
| Crab_seed0 | 0.0512 | 0.0288 | +0.0224 | orientation-artifact | 0.30 | 0.56 | 94/q/- | 24 | 490.06 |
| FoodBox_seed0 | 0.0470 | 0.0470 | -0.0000 | shape-mismatch | 0.67 | 0.31 | 54/q/fla | 15 | 331.59 |
| AquariumTank_seed0 | 0.0458 | 0.0366 | +0.0092 | shape-mismatch | 0.50 | 0.84 | 94/q/fla | 26 | 571.05 |
| Beetle_seed0 | 0.0239 | 0.0219 | +0.0021 | shape-mismatch | 0.51 | 0.46 | 90/q/fla | 15 | 346.81 |
| Plate_seed0 | 0.0215 | 0.0215 | +0.0000 | shape-mismatch | 0.07 | 0.21 | 53/q/fla | 7 | 71.28 |
| Rug_seed0 | 0.0133 | 0.0133 | +0.0000 | shape-mismatch | 0.01 | 0.01 | 14/q/fla | 2 | 53.74 |
| DoorCasing_seed0 | 0.0095 | 0.0095 | +0.0000 | shape-mismatch | 0.01 | 0.17 | 20/q/- | 9 | 239.21 |
| Pillar_seed0 | 0.0072 | 0.0072 | -0.0000 | shape-mismatch | 0.22 | 0.13 | 40/q/verfla | 15 | 197.19 |
| Spoon_seed0 | 0.0035 | 0.0037 | -0.0002 | shape-mismatch | 0.05 | 0.06 | 51/q/fla | 4 | 179.49 |
| Bottle_seed0 | 0.0025 | 0.0025 | +0.0000 | shape-mismatch | 0.37 | 0.37 | 40/q/- | 8 | 97.27 |

Orientation artifacts (Δ_orient >= 0.02): 9 — Leaf_seed0 (Δ=+0.269), Mirror_seed0 (Δ=+0.228), CellShelf_seed0 (Δ=+0.234), Tap_seed0 (Δ=+0.115), Nautilus_seed0 (Δ=+0.107), CabinetDoorIkea_seed0 (Δ=+0.093), LeafBananaTree_seed0 (Δ=+0.121), Sink_seed0 (Δ=+0.072), Crab_seed0 (Δ=+0.022)

## Reference thin-axis prior (20 baked refs, 10 thin at <0.3 max-extent)

X: 3 (30%), Y: 5 (50%), Z: 2 (20%)
No majority thin axis (>50% of thin references).

## Budget

- instances with meta: 20/20
- tool-call cap(s) seen: [24, 36]
- turns: mean 11.1, max 26, turns>=20: 3
- excluded chunks: 26 total
- mean duration: 262.6s

## Self-test

cd_pca(S,S) < 1e-6; cd_pca(S, Ry90(S)) < 1e-6; cd_yawmin(S, Ry90(S)) > 0.5 — all asserted before this report was written.
