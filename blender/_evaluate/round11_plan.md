# Round 11 plan - every defect the sheets show, worst-first

Read from the close sheets of all four sets at 58a1fe5 (19 pages, 159 materials, every page read): the
truth whole, ours whole, and a quarter of each at the truth's own pixel scale. Each family lists the
materials it was seen on. Order: how many materials it hurts times how far off it looks.

| # | family | seen on | what is wrong | status |
|---|---|---|---|---|
| F20 | the set has no HEIGHT map, and its AO is not scored | every set | the truths ship a displacement (and often an AO); ours writes neither a height file nor a score for it | done: T_<Name>_Height.png written and exported; AO mean/spread and height-luma/skew scored (0949f19). Open: the scores themselves - every non-jointed kind's height is its luma (0.666), the skew 1.13 off |
| F4 | colour words | Marble014, Fabric028, Carpet016, Ground105 (beige -> grey); Rock035, Marble006, Leather030, Wood027/028/067 (black/dark too light); Wood026/066 (brown woods 1.5-1.7x); Concrete030/042A/044D (1.45-1.50x); Fabric080/083 (checks pink/purple whatever the colour); Concrete031 lime; Tiles130 salmon; Tiles140 rust; Metal062C platinum yellow; Wood092 orange; Ground080/093C sands grey-brown | the words' colours lost or overridden | hues fixed (378aaa8: dyed colour first, tiles and bare metals carry no hue; LOO 0.0483 -> 0.0485, median 0.0278). Values left: a no-colour fit of MATERIAL_VALUES is worse under LOO (0.1845 -> 0.1986) - the concretes' and woods' brightness is the words' limit |
| F1 | stone bricks and brick faces | Bricks106A/107A/108A/108B/109A/109B/112A/113A ("bricks, natural, stone": coursed natural stone of mixed sizes), every brick (faces a soft PILLOW with a wide dark rim), Bricks089 ("random, stone, wall": a rubble wall), Bricks097 (red brick drawn grey/brown/black) | regular brick grid, pillow faces, flat speckle, extreme per-brick tones | mortar band, stained stone faces, narrower block tones, sandy mortar (193a80d). Open: Bricks089 a random rubble wall drawn as ashlar; Bricks097 red named after brown |
| F2 | metal camouflage | Metal007/027/029/038/046B/052C/055A/062C | a metal is drawn as cells of mottle (contrast up to 1.9x); the truths are smooth sheets with streaks and specks | done (3d2def8): clouds + grain + tooth at the truths' shares, sparse dark specks, scratches; bimodality 0.66 -> 0.33 |
| F3 | scattered stones are flat discs | Ground048/103/105/106/107/108/110/112, Gravel043, ScatteredLeaves009 | stones are flat paint blobs with no shading; "fine" gravel gets large blobs; soils carry pale blobs; leaves are discs | tried and reverted: a dome light per stone reaches the albedo (tone-luma r 0.78) but the stones still read flat - pale stones on a dark matrix, rescaled to the spread. The truths' stones are both darker and lighter than a mid soil: needs the scatter's colour model redone |
| F5 | compositions missing from the albedo benchmark | Rock063, Rock064, Metal053C, Ground037 | the albedo recreation draws the base alone, so a mossy rock is all moss and a rusted metal has no rust; Rock064 is a STACKED STONE wall with moss in its joints | done (9f0955a): the albedo benchmark draws composing descriptions as their layered set; stacked stone is a wall (Rock064 now moss in its joints). Open: moss covers more than the truths' (a 0.5 patch coverage changed little and read worse); rust blobs larger than Metal053C's flecks |
| F6 | tiles | Tiles139/140/141/142/143/144 (grout faint or gone), Tiles107 (white faces speckled), Tiles138 (3.8x the count), Tiles144 (1.41x bright) | a tile is a cloud of speckle with no joint | grout a mid tone (df569ad): dark on light tiles, pale on dark. Open: the harness's count makes floors two to three times the truth's tiles (a measure limit), faces' pits |
| F9 | rock speckle | Rock020/030/051/058/060 | salt-and-pepper grain at 1.7-1.8x contrast; the truths are broad tones with veins and fractures | done (df569ad): broad tone at the truths' variance shares, a fracture web |
| F7 | wood | Wood096/092/058, WoodFloor040/041 (grain runs DOWN in the truth); Wood094 smooth wood at 2.39x contrast | orientation; a smooth wood's grain too strong | description-limited: 20 of the 27 wood truths run across and the five vertical ones name no direction; Wood094's 2.39x contrast shares Wood066's words (0.87x) |
| F8 | board ends | WoodFloor007/043, Planks037A | a board's end is a soft dark band ~10 px wide, not a line | done: a wood floor's seams are dark hairlines read from the pattern's distance (a long board wraps, so its ids cannot show its end) |
| F10 | fabrics | Fabric085, Fabric019 (wool is a KNIT), Fabric080 (plaid is crossed stripes) | knit and tartan not drawn | done: wool is a KNIT of V stitches (Fabric085 scale 1.64 -> 1.12, Fabric019 1.50 -> 1.20); a plaid is stripes on warp and weft (Material Maker weave2's thread masks; Fabric080 colour 0.177 -> 0.154). Open: one hue per cloth - a tartan's greens and navies are not in the ramp |
| F11 | fan setts | PavingStones150/151 | setts' tones too contrasty, the arches lost whole | setts' tones narrowed to 0.45 of the ramp; the arches still read weakly at the whole map's scale |
| F12 | leather | Leather038 (blurry blotches close up), Leather034C (stitched quilting) | | open |
| F14 | roofs | RoofingTiles012A/013A (blurry clouds on each tile), 014A (shakes), 013A (slate) | | open |
| F15 | carpet pile | Carpet012, Carpet016 | pile too faint (contrast 0.30-0.40) | description-limited: giving every carpet the carpet word's spread scores the same (2.21 -> 2.16) |
| F16 | light asphalt | Asphalt031 | aggregate too faint (contrast 0.36) | open |
| F17 | grass scale | Ground037 | strokes 3x the truth's | open |
| F18 | moss colour | Moss002 | olive and pale against a vivid green (fitted table: refit) | open |
| F19 | planks | Planks039 ("large", dirty), WoodFloor070 basketweave | | open |

Description-limited (documented, not forced): Concrete045 board-formed concrete ("pattern" only), Road008B/009C
markings without a marking word, Plastic010 blue-grey "white", Leather037/039 hues, Bricks075A flagstones
called "bricks", Bricks076A stone called "bricks", Wood066 red-brown called "brown".

## Four-set runs (round 11)

| run | albedo brightness | contrast | scale | colour | roughness mean err | spread \|log\| | normal \|log\| | AO mean err / spread \|log\| (74) | height-luma err / skew err (159) |
|---|---|---|---|---|---|---|---|---|---|
| round 10 end (26f83b3) | 0.162 | 0.212 | 0.306 | 0.1291 | 0.0896 | 0.400 | 0.423 | - | - |
| height map, hues (378aaa8) | 0.162 | 0.213 | 0.306 | 0.1288 | 0.0896 | 0.400 | 0.423 | 0.067 / 0.844 | 0.666 / 1.132 |
| metal sheets, wall mortar and faces (193a80d) | 0.162 | 0.212 | 0.310 | 0.1288 | 0.0896 | 0.400 | 0.420 | 0.067 / 0.844 | 0.672 / 1.129 |
| composed albedo, stacked stone (c3f0b20) | 0.161 | 0.218 | 0.309 | 0.1284 | 0.0888 | 0.401 | 0.430 | 0.067 / 0.843 | 0.669 / 1.127 |
| tile grout, rock faces (df569ad) | 0.161 | 0.218 | 0.332 (Tiles107 0.74 -> 13.0 and Tiles138 3.8 -> 9.5 are 0.020 of the 0.023: the zero-crossing measure reads a hairline grid's grout) | 0.1283 | 0.0888 | 0.399 | 0.430 | 0.067 / 0.842 | 0.670 / 1.129 |
| height relief by kind (c5edf97) | 0.161 | 0.218 | 0.331 | 0.1286 | 0.0885 | 0.398 | 0.427 | 0.067 / 0.800 | 0.318 / 0.902 |

## Applied at the end of the session (AO and leaf litter); the rest still next

- **AO by kind (F20) - applied.** Our AO is one less 0.6 of the cavity mask, so its spread is about 0.14 for every
  kind; the truths' run from 0.030 (parquet) to 0.117 (roof), median 0.082, and their means from 0.789
  (woven) and 0.814 (asphalt) to 0.983 (parquet), against our 0.91 everywhere. Design: standardise the
  cavity field and place it at the kind's measured (mean, spread) - brick (0.857, 0.099), scattered
  (0.858, 0.096), flat (0.930, 0.039), asphalt (0.814, 0.056), woven (0.789, 0.050), parquet (0.983,
  0.030), rock (0.914, 0.073), roof (0.810, 0.117), others (0.882, 0.082). Expected to cut the AO spread
  error (0.800) most.
- **Leaf litter (F3, ScatteredLeaves009) - applied; looked at: orange, tan, olive and brown leaves on soil (scale ratio 3.25: the measure reads the truth's clumps).** Prototyped and looked at: tapered lens-shaped leaves with a
  dark midrib and a light rim, three size octaves on jittered grids (3x3 neighbours, wrapped), periods
  3x the surface's feature count (the truth reads 20 features - its clumps - over leaves about 17 pixels
  long); at that factor the leaves match the truth's size. Plan: a `leaf_litter` palette flag (leaf words)
  swaps the scatter's stone field for a `leaves_field` returning the same six fields, so the scatter's
  writer draws the leaves on their soil with the palette's warm hue. Needs a one-pixel soft rim.
- **Still open from the list above:** the scatter's colour model (F3: pale stones on a dark matrix read
  flat; the truths' stones are darker and lighter than a mid soil), Bricks089 as a rubble wall, moss
  coverage and Metal053C's rust flecks (F5), leather close-up blur and stitching (F12), roof tiles' clouds
  and shakes (F14), the fan's arches at whole-map scale (F11), a plaid's second and third hue (F10),
  basketweave and "large" planks (F19), the moss colour refit (F18).

