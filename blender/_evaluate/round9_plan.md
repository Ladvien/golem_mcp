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
