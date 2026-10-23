# Round 10 plan — the whole PBR set, and every defect the three sets' sheets show

Round 9 judged the albedo alone and read the top set's sheet. Round 10 scores the WHOLE set the
agent makes (roughness, metallic, AO, normal) against the truths' own maps
(`scripts/benchmarks/score_pbr_channels.py`) and reads the popular and wide sets' sheets too
(4 + 8 pages, every row). Defects are grouped into FAMILIES and ordered by how many truths a
family covers.

## A. Families seen on the sheets (worst-first by breadth)

| # | family | truths | what the sheet shows |
|---|---|---|---|
| A1 | asphalt and roads | Asphalt031/033, Road008A/B, 009C, 012A/B, 013A, 014A, 015C | polygon PLATES; the truths are a fine aggregate with cracks (Asphalt031 also salmon) |
| A2 | scattered grounds | Ground103/105/106/108/109/110, Gravel043, ScatteredLeaves009, Ground048 | CAMOUFLAGE blotches; the truths are distinct pebbles and stones |
| A3 | stone block walls | Bricks106A–113A (8, identical words) | uniform brick courses with flat tones; the truths are ashlar - blocks of varied length, each a textured stone |
| A4 | irregular stonework | Bricks089, Bricks076A, Bricks075A, Tiles130, PavingStones150/151 | regular courses or tiles; the truths are random stone walls, crazy paving, fanned cobbles. PavingStones150 is FLAT grey - a bug |
| A5 | carpets | Fabric028, Fabric023, Carpet012, Carpet016 | huge blobs and a worm-like MAZE; the truths are fine fibre piles |
| A6 | corrugated steel | CorrugatedSteel009 | no ribs at all: the pressed sheet's fibre saturates the line writer and buries them (normal 2.0 deg vs 20.7) |
| A7 | rubble routed to bricks | Ground107 | "brick, debris, fragments, rubble, scattered" drew an orange brick grid |
| A8 | leather | Leather038 (coarse cells), Leather034C (stitched) | big polygon cells; the truth is a smooth fine hide; "stitched" is a quilted diamond |
| A9 | banded stones | Onyx015, Travertine009 | marble veins; the truths are banded layers (travertine also beige, not white) |
| A10 | bark | Bark015 | smooth wood grain; the truth is fissured bark |
| A11 | planks | Planks037A (no boards), Planks039 (large planks), WoodFloor043 (soft board ends) | grain without joints; small boards; smeared ends |
| A12 | metals' colour and wear | Metal048A/034 (lemon gold), Metal062C (platinum as gold), Metal053C/052C/062C (big flecks) | gold too saturated; damaged metal as large blobs |
| A13 | stacks | Rock063, Rock064, Ground037, Metal053C | a mossy rock as flat moss; rusted iron as grey blobs - layered sets, composed from the words (C1) |

## B. The PBR channels (score_pbr_channels.py; scripts/benchmarks/channel_sheet.py to look)

| # | channel | first measure (ambientcg, 20) |
|---|---|---|
| B1 | roughness spread | ours flat (0.000) against 0.006-0.172: mean \|log\| 2.17 |
| B2 | normal strength | woods 17.6 deg vs 0.5-2.7; metals 13 vs 0.4; tiles 2.9 vs 0.5-1.0; bricks 4.9 vs 7-9; corrugated 2.0 vs 20.7: mean \|log\| 1.26 |
| B3 | roughness mean | good: mean \|error\| 0.018 |
| B4 | metallic | only the top set ships metalness (11 truths); a missing map is unknown, not zero |

## C. Compositing and sources

- C1 compose from descriptions: a description naming a base and a covering material ("moss" on a
  "rock", "rust" on "iron") builds a layered set automatically; benchmark on A13's truths.
- C2 Material Maker and the reference list: port only where a measured defect needs it.

## Progress

| defect | cause found | fix | commit |
|---|---|---|---|
| layered set crashed on the codex share | the scratch cleanup globbed a macOS "._" sidecar that vanished | remove the scratch directory whole | (this round) |
| B1 roughness flat | one roughness per description | the kind's measured spread, following the height (and, jointed, the luma) at the kind's correlations, plus a grain; spread mean \|log\| ~2.1 -> 0.35-0.48 | (channels) |
| B2 one normal strength | NORMAL_STRENGTH 6 for every surface | the normal scaled to its kind's measured tilt; tiles, smooth finishes and pressed metal refined; mean \|log\| 1.09-1.43 -> 0.27-0.51 | (channels) |
| bricks as pyramids | the joint distance peaked each brick | flat-topped pieces rising over a bevel (looked at) | (channels) |
| polished stones rough, brushed metal glossy | "stone" outranked "polished"; brushed 0.12 | marble/onyx/travertine fitted (0.078/0.044/0.037), brushed 0.505; roughness mean error 0.112 -> 0.095 | (channels) |

## Still open
