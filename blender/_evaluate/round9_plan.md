# Round 9 plan — every defect the close sheet shows

Source: `scripts/benchmarks/close_sheet.py` over `ambientcg_top` (the
site's own 60 most-downloaded materials), after commit 3287a0f. Each
row is the truth whole, ours whole, then a quarter of each at the
truth's own pixel scale. The score is in the row label; the defect is
what the picture shows.

Scores at the start (four sets):

| set | brightness | contrast | scale | seam (truth) |
|---|---|---|---|---|
| ambientcg (20) | 0.97 | 1.07 | 0.79 | 0.31 (0.60) |
| ambientcg_wide (87) | 1.05 | 1.15 | 0.92 | 0.54 (0.54) |
| ambientcg_popular (47) | 0.98 | 1.10 | 0.97 | 0.39 (0.48) |
| ambientcg_top (60) | 1.11 | 1.11 | 0.86 | 0.57 (0.44) |

## A. Colour — the words are not honoured

- **A1 Saturated stray hues.** Red-orange blotches in Marble006 and
  Marble016, pink speckle in Fabric061 and Fabric066, lilac in
  Fabric019, peach in Bricks060 ("white") and Carpet016, pink in
  Ground048. No truth has these hues. Suspect: the per-cell hue
  jitter (`hue_variation`) or a channel ramp running past its range.
- **A2 Named colours lost.** Metal007 "gold" → grey; Metal034 "gold,
  yellow" → pale cream; Concrete031 "gray, green" → yellow-olive;
  Rock020/030 "grey" → green; Marble014 "beige" → grey; Wood052
  "orange" → brown.
- **A3 Dark woods too light**: Wood066 1.73x, Wood067 1.72x, Wood028
  1.72x, Wood026/027 1.54x.

## B. Structure — the wrong primitive or an invisible one

- **B1 Wood grain invisible at 2048** (every Wood0xx): the map is a
  flat brown with a few dark smudges; the probe at 1024 showed
  streaks. The benchmark draws at 2048.
- **B2 Brushed metal shows no brushing** (Metal009, Metal011): blotchy
  smooth grey where the truth is dense horizontal lines.
- **B3 Bricks060 has no bricks**: a flat field, contrast 0.27.
- **B4 Tiles are staggered bricks** (Tiles107, Tiles040, Concrete031):
  a tile floor is a SQUARE grid with a thin grout.
- **B5 Rock and moss are flat Voronoi facets** (Rock020, Rock030,
  Rock035, Moss002): the truth is fine fractal texture, no polygons.
- **B6 Grass and mossy ground are camouflage blotches** (Grass001,
  Grass004, Ground037): the truth is fine blades.
- **B7 Fabric has no weave** (Fabric030, Fabric036, Fabric061,
  Fabric066): blobs or speckle where the truth is a visible weave or
  check.
- **B8 Square-block lattice visible** (Concrete030, Concrete042A): an
  upsampling or value-noise artifact.
- **B9 Wood floors** (WoodFloor040/041/007/043): boards horizontal
  where the truth's run vertically; WoodFloor040's **seam 16.46x**.
- **B10 Road007**: five lane lines where the truth has one dashed
  centre line.

## C. Compositing — layered materials

Material Maker composes MATERIALS, not only fields: `blend2.mmg` takes
N layers each with its own float mask and amount
(`a = amount*mask`), and the masks come from height (`mwf_*`), noise
(`dirt.mmg`: shape + fbm + colorize) and curvature (`edge_detect` →
`smooth_curvature`). Our `nodegraph.py` composes greyscale fields into
ONE field and colorizes it; it cannot put moss in a brick's joints or
rust on a sheet. Build: a layer stack of whole materials (albedo,
roughness, metallic, height) under masks, rendered and LOOKED AT.

## Order

Breadth first: A1 (seven materials), B1 (nineteen woods), B8 (an
artifact), B9's seam (a wrap bug), B3, B4, B5, B6, B7, A2, A3, B2,
B9, B10, then C. Each fix gets a before/after crop READ in the
transcript; the four sets re-run after each batch.

## Progress (each fix looked at in a before/after crop sheet)

| defect | cause found | fix | commit |
|---|---|---|---|
| A1 red/pink specks | `_shift_to_value` moved each pixel along ITS OWN colour/luma; a near-black pixel's ratio is noise | lift along the image's mean hue; Blender test fails before (sat 1.00), passes after | fdbad6d |
| A2 gold metal grey | silver+steel outvoted gold | a coloured metal takes its metal's hue (2 materials change, both better) | (coloured metal) |
| B1 wood smudges | envelope was a Perlin's magnitude (blobs, same on every wood) | Material Maker's wood: 1-cell-along x 96-across noise, bent by a slow field | f6ed97c |
| B8 concrete checker | single-octave value noise shows its lattice | 4/3-octave fBm | c20f460 |
| B9 floor seam 16.46x | in-board position read against the WRAPPED column; stagger was whole blocks | fraction of the staggered coordinate; per-course golden fraction; boards get ring grain | 0334de2 |
| (roof) | same two faults | half-shingle / golden fraction | roof commit |
| B3 Bricks060 flat peach | "brick" sorted before "white" for hue; "bright" (one fitted marble) set the spread | white-only hue; lightness words step aside for a material word (holdout 0.4085 -> 0.4060) | 3006acb |
| B4 tiles staggered | tiles went down the brick path with its stagger | `staggered=False` for tiles, two features per tile, glazed tone at a twentieth of the ramp | 3006acb |
| B5/B6 rock, moss, grass | routed to voronoi / scattered | rock_field, moss_field, grass_field; routing | (natural kinds) |
| palette fitted on 3 sets | grass/moss hues fitted on one olive ground | refit on four sets incl. MATERIAL_HUES | (natural kinds) |
| dead code | 4 duplicate/dead definitions | deleted | 3287a0f |
| grass/moss/wood scale | grass's 320 blades, moss's clumps at 2x, wood's 96 rings: fixed counts whatever the surface | blades = 6/feature (min 192), clumps at the surface's scale, rings = 8/cell (min 64); scale error 0.745 -> 0.253 (grass), 0.490 -> 0.359 (woods) | cb01ddf |
| the agent never got the palette | `generate_procedural_base_color` took no description: every map the agent wrote was default grey | `description` chooses the kind and the palette, the benchmark's own two calls | 8dd6719 |
| C compositing | no tool | `generate_layered_texture_set`: BaseColor/ORM/Normal from a described base + described layers under height/noise/cavity masks | 6716074 |
| C moss on whole bricks | height read from the colour: a weathered wall's dark bricks are darker than its mortar (2.2x the moss) | a jointed kind's height is its own joint field (`joint_height_out`) | 6716074 |
| C rust was a grey metal | "rust" a METAL word; its hue/roughness fitted on one grey glossy steel | rust is weathering when a metal is named and an orange rough crust when not; dust/grime/rust route flat | 6716074 |
| tile grout 15-27 px, soft | grout a fraction of the tile's half-width (a tile is twice a brick's cell); truths 1-4 px | grout drawn from cell boundaries, 2 px at 1024, wrapped | 8e4b9b7 |
| tile faces blotchy | hairline grout left the spread to the slow drift (31-51 px; truths 2-5) | fine tooth on a glazed face, swept to 0.3 | 8e4b9b7 |
| rock greenish, silver tan | material hues fitted on every description, mossy rocks and a gold "silver" included | fitted where no OTHER colour is named; LOO hue 0.0818 -> 0.0790 | 8e4b9b7, e616af3 |
| B2 brushed metal | "brushed" built as a pressed sheet's ribs; the fibre saturated the line writer (94%) | streaks for brushed (Metal009 86/81 -> 24/8 vs 24/1), sparse mottle for plain sheets | e616af3 |
| scratches a grid of dashes, 80 s | frame wrapped per cell (every cell every scratch); each cell drawn 9x over the image | Material Maker's scratches2, one pass a layer (0.35 s) | e616af3 |
| B7 fabric speckle | the crosshatch's two axes were the SAME isotropic noise: no thread anywhere | Material Maker's weave; threaded regime where the features resolve threads, fine wandering threads under a light mottle where they do not; Fabric030 fine/slow 0.63 -> >2.5 (truth 10.5) | 387b337 |
| camouflage squares, pixel blocks | a value noise's lattice (powered for the metal mottle; 8 px cells for rock grain) | `noise.gaussian_grain` (FFT-smoothed white noise, periodic); Metal007 8/8 vs 9/10 | 09d30bb |
| powder-coated metal mottled | a coat routed to the metal sheet | coating words + a metal route to the flat sheet | 6658f51 |
| marble: polygon net, dashed loops, no veins on black | a Worley crackle over everything, a contour band breaking on steep slopes, F2-F1 widths; the fibre was the stone and saturated; the writer draws high fibre towards the light | level-set veins of a warped fBm at a fixed pixel width, two families, a presence mask; the fibre is the veins; a pale marble's line mirrored; envelope 0.4 -> 0.05... 0.2 (fine/slow err 0.94 -> 0.22) | c779b44 |
| Wood052 orange as tan | the wood rule ignored every colour word | a colour warmer than the wood decides (woods 0.1044 -> 0.0952) | 3af878f |
| moss/rock/wood hues diluted | material hues fitted over descriptions where the word was one material of several | fitted first where it is the only material (LOO 0.0784 -> 0.0779, median 0.0511 -> 0.0462) | 55df6a3 |
| Fabric085 grey, Leather038 brown | with only generic materials named the first word with a hue decided ("fabric" before "orange") | a dyed material (fabric, wool, leather, carpet) takes its colour word; 0.0613 -> 0.0588 | b7698d9 |
| marble scale 0.54 | the presence mask at half the count set the scale | presence at the count (seven marbles' scale error 0.279 -> 0.183) | 0245750 |
| B10 Road007 five lines | markings at random places of a lattice of four (the constant's own comment said three) | the measured layout: solid edges at 7.5%/92.5%, a dashed centre, four dashes; an asphalt grain; the road's spread is what the paint leaves | eddec6e |
| Fabric036 no slubs | a weave under an isotropic mottle reads the same both ways (9/9; truth 12/3) | an oriented Gaussian grain along the rows, fading in below 40 features (linen Fabric030 unstreaked); scale 1.43 -> 1.20 | (slubs) |

Measured but NOT taken (lost on the holdout or in-sample): colour-word-first hue (41 better / 56 worse);
a one-colour-word hue (28/58); dropping lightness words from the spread outright (holdout 0.4323);
refusing words fitted on one material (holdout 0.5384); a wood's warmth fitted on its predicted
value (the truths' darker woods ARE warmer, -0.49 with their own luma, but only -0.23 with the
value the words predict; leave-one-out hue 0.1110 -> 0.1166, 13/13); fitting each material once
instead of once per set (leave-one-out 65 better / 66 worse); averaging the hues of several named colour
words (mean 0.0620 -> 0.0595 but median 0.0375 -> 0.0387, 9 better / 6 worse).

## Still open

- Moss002 too pale (value 0.466 vs 0.353) and unsaturated; Concrete031 olive (its words say
  "green" and its pixels are grey: a description limit); dark woods too light (Wood067 1.71x,
  Wood026 1.54x): the truths are saturated red-brown, and the words do not carry it.
- Fabric019's knit is not drawn (no knit kind); Fabric085's boucle is a coarse basket weave.
- Marble014's beige (the specificity rule picks marble's neutral; numerically closer to the truth).
- Tiles107's face tooth is right in amount (0.032 against the truth's 0.025 fine std) but coarser
  than the truth's; WoodFloor040/041 are vertical planks (orientation is not in the words).
- Ground037 is a forest floor (moss and dirt patches with twigs): a layered set, not one field. Built
  with generate_layered_texture_set (dirt + moss patches + grass patches) it carries the truth's
  patchwork; the single-material benchmark cannot. Its moss is olive: even 'green' is fitted olive on
  mossy rocks and grounds, and Moss002's vivid green is the corpus's one pure moss.
- Ground048 (dark crumbly soil, 73 features) renders as pale scattered blobs - a description limit:
  'soil' names four truths at 0.438, 0.392, 0.419 and Ground048's 0.259, and the other three are the
  pebbly grounds whose words it shares. Concrete ('concrete, smooth' at 0.367-0.800) and Metal034
  (a 'smooth gold metal' at 0.687 beside one at 0.893) are the same kind of limit.
- Metal034's gold reads lemon (contrast 5.24x on a near-uniform truth); Wood092 salmon against amber.
- Tile counts vary against the truths (Tiles107 ours smaller, Tiles040 larger): the count is the
  feature measure's.

## Benchmark across the round's last four runs (mean |log| ratio over 159 materials; colour error)

| run | brightness | contrast | scale | colour |
|---|---|---|---|---|
| after cb01ddf | 0.165 | 0.257 | 0.329 | 0.1352 |
| after e616af3 | 0.165 | 0.256 | 0.320 | 0.1339 |
| after 55df6a3 | 0.165 | 0.255 | 0.328 | 0.1327 |
| after eddec6e | 0.166 | 0.254 | 0.321 | 0.1313 |

The seam rose (top 0.13 -> 0.19, truth 0.44) as the maps gained truth-like fine texture; every
wrap step ranks inside its own map's interior steps (0.09-0.74), so none is a seam.

## The reference list's primitives

Ported only where a sheet defect needed them. None needed Poisson disk or curl noise. The one that
called for a Gabor-like oriented noise - Fabric036's slubs - is an oriented Gaussian grain
(`noise.gaussian_grain(..., along_rows=)`), the same FFT-smoothed white noise that replaced the
value noise's squares: periodic, axis-free, no kernel sums.
