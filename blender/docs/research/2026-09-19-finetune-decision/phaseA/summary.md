# Phase A — failure taxonomy of the archived rolls

Attempts with a render log: **285** across 16 harness roll(s); 20 third-party attempt(s) reported separately and never pooled.

Denominators: *primary* = attempts whose per-instance scores were already archived by an earlier `diagnose_3dcode.py --json` run (261 attempts, 14 rolls); *secondary* = every included attempt (285).

## Codes

| code | attempts | share of failures |
|---|---|---|
| PASS | 154 | — |
| G2 | 97 | 87.4% |
| UNSCORED | 13 | — |
| G1 | 12 | 10.8% |
| INFRA | 7 | — |
| E7 | 2 | 1.8% |

## The two shares §3 reads

- attempts counted (INFRA and UNSCORED excluded): **265**
- passes (`cd_pca <= 0.0252`): **154**
- failures: **111**
- `F_syntax` = 2/111 = **1.8%** (E1-E5, E7, O1-O2)
- `F_geom` = 109/111 = **98.2%** (G1-G3)
- `E6` (executed, degenerate) = 0/111 = 0.0% — in neither share by the spec's own definitions, so the two do not sum to 100%.

## Excluded, in neither share

Two exclusions, both pre-registered before the shares were read: `INFRA` is a bake-environment artifact matched on the error text, `UNSCORED` is an attempt that executed and left a mesh for which its roll carries no `cd_pca`.

| code | roll | instance | reason |
|---|---|---|---|
| INFRA | blended-deepseek-v4-pro-ops-roll1 | AquariumTank_seed0 | `TypeError: CollectionObjects.link(): error with argument 1, "object" -  Function.object expected a O` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Beetle_seed0 | `executed, but this roll carries no cd_pca` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | Bottle_seed0 | `ImportError: cannot import name 'add_lathe' from 'blended.ops' (/Users/ladvien/Library/Application S` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | CabinetDoorIkea_seed0 | `executed, but this roll carries no cd_pca` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | CellShelf_seed0 | `AttributeError: 'str' object has no attribute 'name'` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | Crab_seed0 | `ImportError: cannot import name 'add_lathe' from 'blended.ops' (/Users/ladvien/Library/Application S` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | DoorCasing_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | FoodBox_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | FruitStarfruit_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Jar_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | LeafBananaTree_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Leaf_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Mirror_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Nautilus_seed0 | `executed, but this roll carries no cd_pca` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | Pillar_seed0 | `ImportError: cannot import name 'add_lathe' from 'blended.ops' (/Users/ladvien/Library/Application S` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | Plate_seed0 | `ImportError: cannot import name 'add_lathe' from 'blended.ops' (/Users/ladvien/Library/Application S` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Rug_seed0 | `executed, but this roll carries no cd_pca` |
| INFRA | blended-deepseek-v4-pro-ops-roll1 | Sink_seed0 | `TypeError: CollectionObjects.link(): error with argument 1, "object" -  Function.object expected a O` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Spoon_seed0 | `executed, but this roll carries no cd_pca` |
| UNSCORED | blended-deepseek-v4-pro-ops-roll1 | Tap_seed0 | `executed, but this roll carries no cd_pca` |
| INFRA | baseline-opus | Pillar_seed0 | `RuntimeError: Error: Cannot open file /lab/yipeng/infinigen/eval/results/text_to_3D_agent/opus/Pilla` |

## Hatch accounting

Counted off the BAKED script's labels, not `.agent_meta.json` — meta counts reader ops as geometry-emitting and numbers chunks with a counter that advances on op calls. Rolls predating op collection in the bridge are excluded from the share and shown in their own columns: their scripts cannot hold an op call, so their 100% is the instrument, not the agent (`phaseA/hatch_mechanism.md`).

| rows | attempts | collecting ops | baked run_python chunks | scene-changing op calls | reader op calls | attempts using any op | hatch share | pre-collection attempts (chunks) |
|---|---|---|---|---|---|---|---|---|
| passing | 154 | 72 | 321 | 34 | 35 | 17 | 90.4% | 82 (950) |
| failing | 111 | 49 | 235 | 99 | 34 | 22 | 70.4% | 62 (819) |

## Cross-tab against the benchmark's own categoriser

`metrics/failure_taxonomy.categorize` on the same error text — an external instrument, not a second copy of the rules above.

| code | B5-API | BMSH | CTX | OTHER | (no error text) |
|---|---|---|---|---|---|
| E7 | 0 | 0 | 0 | 2 | 0 |
| G1 | 0 | 0 | 0 | 0 | 12 |
| G2 | 0 | 0 | 0 | 0 | 97 |
| INFRA | 0 | 0 | 0 | 7 | 0 |
| PASS | 0 | 0 | 0 | 0 | 154 |
| UNSCORED | 0 | 0 | 0 | 0 | 13 |

## Third-party row, reported separately

`baseline-opus`: {'G2': 10, 'PASS': 9, 'INFRA': 1}
