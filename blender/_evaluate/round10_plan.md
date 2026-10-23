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

## A2 measured (next)

The scattered grounds' blur profile (share of variance finer than a 1/2/4/8/16/32 px blur, median of
11): truths 0.14 0.32 0.52 0.69 0.81 0.90, ours 0.09 0.22 0.39 0.52 0.58 0.66 - a third of our
variance is coarser than 32 px against the truths' tenth. The one-octave `slow_variation` (a value
noise at a power-of-two lattice, crosses visible) modulates both the stones' tone and the matrix, so
after the spread is scaled the stones have no contrast left: camouflage. Fix: a multi-octave drift at
a fraction of today's weight, the stones' tone their own.

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
| A7/A11/A4 routes | "brick", "wood" and "patterned" were read before "debris", "planks" and "cobblestone" | rubble -> scattered, planks -> boards, cobblestone -> set stones, an irregular stone floor -> crazy paving (looked at: PavingStones150 no longer flat grey) | (routes) |
| A3/A4 walls | every course one block length; a random stone wall's mortar a black crack | ashlar courses (joints moved by a wrapped hash, blocks 0.5-1.5 long, seam = one step) for natural/irregular stone walls; a random wall's mortar pale and twice as wide (looked at). Open: the blocks' faces are still flat tones, not textured stone | (routes) |
| A1 asphalt and roads | asphalt routed to Voronoi plates; a painted road took its paint's yellow; the markings' road was a one-octave blob | an `asphalt` kind: fine/stone/drift grains with variance shares fitted to the truths' blur profiles (granular 0.90/0.05/0.05, worn 0.55/0.25/0.20), pale block cracks along a warped Voronoi's joints when "cracked"; asphalt's own hue (hue error over 11: 0.0338 -> 0.0131); "striped" + road -> markings, on the asphalt field (looked at). Open: patch repairs (no word says them) | (asphalt) |
| A2 scattered grounds | ~209k six-pixel splats (27x the map's area) overlapping into flakes, tones following a one-octave drift, and the writer blending every pixel half stone half soil | a periodic jittered-grid stone layer (4 size octaves, 3x3 neighbour cells, per-cell draws in a table, coarse over fine, lit side, rim, contact shadow), the soil = 1 - mask, a 3-octave drift at 0.6, Gaussian grit on stones and soil (centred: it had clipped at one). Blur profile 0.10/0.26/0.47/0.67/0.84/0.94 vs truths 0.14/0.32/0.52/0.69/0.81/0.90; scale \|log\| over 11 0.63 -> 0.30; ~5x faster (looked at) | (stones) |
| A5 carpet seam | the carpet's field (varying across only) thresholded by the joint falloff into a full-height hairline | a carpet has no joint (looked at). Open: carpets are still Perlin blobs, not fibre | (stones) |
| A5 carpet pile | a Perlin at a lattice of two: great blobs | a fine grain (0.6 px, 0.75), a medium (1.8 px, 0.12) and a mottle at the feature count (0.13), streaked x2.5 along the rows for a cloth carpet; scale \|log\| over 4 0.42 -> 0.32 (looked at). Open: Fabric028 grey vs olive, Carpet016 white vs beige (colour words) | (carpet) |
| A8 leather | the crackle cells followed the feature count (19 -> 16 cells: 100 px polygons on a "fine, smooth" hide); the envelope reached the image only through the joint falloff; one value-noise octave showed squares | a floor of 128 crackle cells; a leather is a soft sheet (envelope + crackle tooth, no cells, no joints); the envelope a Gaussian grain at the feature size (no lattice). Scale \|log\| over 6 0.26 -> 0.30 (Leather038 1.77 -> 1.22, Leather037 0.67 -> 0.44), the polygons gone (looked at). Open: Leather034C stitched quilting; Leather039 suede colour | (leather) |
| A6 corrugated steel | the pressed grain saturated the line writer and drowned the ribs; the ribs ran down the image ("ij" grid read the wrong way); 64 ribs (half-periods) | pressed sheets are a soft field: shaded waves over the weathering, 4 ribs a cell (64 px period vs truth 68, profile deviation 14.1 vs 17.5) (looked at) | (stones) |
| crash: coated metal with a plain colour | `NAMED_COLOURS.get(word, METAL_COLOURS[word])` evaluated its default first | named colour first, the metal's only if missing ("galvanized, gray, steel" raised KeyError) | (stones) |

## Still open

## Four-set runs (round 10)

| run | albedo brightness | contrast | scale | colour | roughness mean err | spread \|log\| | normal \|log\| |
|---|---|---|---|---|---|---|---|
| round 9 end (1be82b2) | 0.166 | 0.234 | 0.325 | 0.1313 | 0.112 | ~2.1 | ~1.2 |
| channels (5e27ac9) | 0.166 | 0.234 | 0.325 | 0.1313 | 0.090 | 0.407 | 0.461 |
| routes + ashlar | 0.166 | 0.221 | 0.325 | 0.1312 | 0.090 | 0.404 | 0.449 |
| asphalt (e306c4f) | 0.162 | 0.212 | 0.326 | 0.1292 | 0.090 | 0.405 | 0.453 |
| stones, carpet seam, ribs (b3c53b0) | 0.162 | 0.212 | 0.309 | 0.1292 | 0.090 | 0.405 | 0.453 |

