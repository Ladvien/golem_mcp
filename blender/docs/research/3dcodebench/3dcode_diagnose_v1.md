# 3DCodeBench diagnostic — blended-deepseek-v4-pro

Replication: `/Users/ladvien/3dcodebench/metrics/shape_chamfer.py` imported unmodified; 20 instance cd_yawmin values asserted equal to `_metrics/shape_chamfer.json`.

## Per-instance (sorted by cd_yawmin descending)

| instance | cd_yawmin | cd_pca | Δ_orient | verdict | thin_gen | thin_ref | brief(words/quant/orient) | turns | dur_s |
|---|---|---|---|---|---|---|---|---|---|
| CellShelf_seed0 | 0.2321 | 0.0070 | +0.2251 | orientation-artifact | 0.25 | 0.19 | 38/q/- | 13 | 382.8 |
| Mirror_seed0 | 0.2286 | 0.0258 | +0.2028 | orientation-artifact | 0.02 | 0.01 | 42/q/- | 14 | 449.08 |
| Tap_seed0 | 0.1847 | 0.0622 | +0.1225 | orientation-artifact | 0.33 | 0.65 | 55/q/fla | 7 | 129.35 |
| Nautilus_seed0 | 0.1623 | 0.0592 | +0.1031 | orientation-artifact | 0.28 | 0.90 | 43/q/flafac | 18 | 907.66 |
| CabinetDoorIkea_seed0 | 0.1309 | 0.0381 | +0.0929 | orientation-artifact | 0.01 | 0.10 | 66/q/verfla | 2 | 63.75 |
| LeafBananaTree_seed0 | 0.1062 | 0.0019 | +0.1043 | orientation-artifact | 0.07 | 0.10 | 43/q/- | 10 | 502.79 |
| Sink_seed0 | 0.0838 | 0.0395 | +0.0443 | orientation-artifact | 0.83 | 0.57 | 52/q/fla | 22 | 662.37 |
| Beetle_seed0 | 0.0706 | 0.0305 | +0.0401 | orientation-artifact | 0.49 | 0.46 | 90/q/fla | 24 | 583.08 |
| AquariumTank_seed0 | 0.0465 | 0.0397 | +0.0068 | shape-mismatch | 0.51 | 0.84 | 94/q/fla | 22 | 650.14 |
| FoodBox_seed0 | 0.0398 | 0.0398 | +0.0000 | shape-mismatch | 0.63 | 0.31 | 54/q/fla | 23 | 553.56 |
| Crab_seed0 | 0.0274 | 0.0291 | -0.0017 | shape-mismatch | 0.18 | 0.56 | 94/q/- | 21 | 908.65 |
| Plate_seed0 | 0.0222 | 0.0222 | +0.0000 | shape-mismatch | 0.08 | 0.21 | 53/q/fla | 6 | 160.05 |
| FruitStarfruit_seed0 | 0.0221 | 0.0197 | +0.0024 | shape-mismatch | 0.51 | 0.78 | 95/q/- | 8 | 156.25 |
| Jar_seed0 | 0.0197 | 0.0196 | +0.0001 | shape-mismatch | 0.50 | 0.32 | 42/q/fla | 23 | 1087.65 |
| Rug_seed0 | 0.0131 | 0.0131 | +0.0000 | shape-mismatch | 0.01 | 0.01 | 14/q/fla | 3 | 63.25 |
| DoorCasing_seed0 | 0.0090 | 0.0090 | +0.0000 | shape-mismatch | 0.01 | 0.17 | 20/q/- | 5 | 129.52 |
| Pillar_seed0 | 0.0056 | 0.0056 | +0.0000 | shape-mismatch | 0.22 | 0.13 | 40/q/verfla | 12 | 163.06 |
| Leaf_seed0 | 0.0033 | 0.0032 | +0.0000 | shape-mismatch | 0.09 | 0.05 | 48/q/- | 1 | 170.71 |
| Spoon_seed0 | 0.0028 | 0.0028 | +0.0000 | shape-mismatch | 0.06 | 0.06 | 51/q/fla | 11 | 423.51 |
| Bottle_seed0 | 0.0016 | 0.0016 | +0.0000 | shape-mismatch | 0.42 | 0.37 | 40/q/- | 20 | 368.73 |

Orientation artifacts (Δ_orient >= 0.02): 8 — CellShelf_seed0 (Δ=+0.225), Mirror_seed0 (Δ=+0.203), Tap_seed0 (Δ=+0.123), Nautilus_seed0 (Δ=+0.103), CabinetDoorIkea_seed0 (Δ=+0.093), LeafBananaTree_seed0 (Δ=+0.104), Sink_seed0 (Δ=+0.044), Beetle_seed0 (Δ=+0.040)

## Reference thin-axis prior (20 baked refs, 10 thin at <0.3 max-extent)

X: 3 (30%), Y: 5 (50%), Z: 2 (20%)
No majority thin axis (>50% of thin references).

## Budget

- instances with meta: 20/20
- tool-call cap(s) seen: [24]
- turns: mean 13.2, max 24, turns>=20: 7
- excluded chunks: 39 total
- mean duration: 425.8s

## Self-test

cd_pca(S,S) < 1e-6; cd_pca(S, Ry90(S)) < 1e-6; cd_yawmin(S, Ry90(S)) > 0.5 — all asserted before this report was written.
