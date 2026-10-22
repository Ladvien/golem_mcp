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

Measured but NOT taken (lost on the holdout or in-sample): colour-word-first hue (41 better / 56 worse);
a one-colour-word hue (28/58); dropping lightness words from the spread outright (holdout 0.4323);
refusing words fitted on one material (holdout 0.5384); a wood's warmth fitted on its predicted
value (the truths' darker woods ARE warmer, -0.49 with their own luma, but only -0.23 with the
value the words predict; leave-one-out hue 0.1110 -> 0.1166, 13/13); fitting each material once
instead of once per set (leave-one-out 65 better / 66 worse).

## Still open

- Moss002 too pale (value 0.466 vs 0.353) and unsaturated; Concrete031 olive; dark woods too
  light (Wood067 1.71x, Wood026 1.54x): the truths are saturated red-brown.
- B2 brushed metal shows no brushing; B7 fabric weave; B10 road lane count.
- Marble012/014 hue; Rock hue slightly green (the "rock" hue includes mossy rocks; "grey cliff
  rock" reads greenish through the tool).
- Ground037 is a forest floor (moss and dirt patches with twigs): a layered set, not one field.
- `curvature.scratches` is O(cells^2 x resolution^2): every cell draws over the whole image.
