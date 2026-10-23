# Round 11 plan - every defect the sheets show, worst-first

Read from the close sheets of all four sets at 58a1fe5 (19 pages, 159 materials, every page read): the
truth whole, ours whole, and a quarter of each at the truth's own pixel scale. Each family lists the
materials it was seen on. Order: how many materials it hurts times how far off it looks.

| # | family | seen on | what is wrong | status |
|---|---|---|---|---|
| F20 | the set has no HEIGHT map, and its AO is not scored | every set | the truths ship a displacement (and often an AO); ours writes neither a height file nor a score for it | open |
| F4 | colour words | Marble014, Fabric028, Carpet016, Ground105 (beige -> grey); Rock035, Marble006, Leather030, Wood027/028/067 (black/dark too light); Wood026/066 (brown woods 1.5-1.7x); Concrete030/042A/044D (1.45-1.50x); Fabric080/083 (checks pink/purple whatever the colour); Concrete031 lime; Tiles130 salmon; Tiles140 rust; Metal062C platinum yellow; Wood092 orange; Ground080/093C sands grey-brown | the words' colours lost or overridden | open |
| F1 | stone bricks and brick faces | Bricks106A/107A/108A/108B/109A/109B/112A/113A ("bricks, natural, stone": coursed natural stone of mixed sizes), every brick (faces a soft PILLOW with a wide dark rim), Bricks089 ("random, stone, wall": a rubble wall), Bricks097 (red brick drawn grey/brown/black) | regular brick grid, pillow faces, flat speckle, extreme per-brick tones | open |
| F2 | metal camouflage | Metal007/027/029/038/046B/052C/055A/062C | a metal is drawn as cells of mottle (contrast up to 1.9x); the truths are smooth sheets with streaks and specks | open |
| F3 | scattered stones are flat discs | Ground048/103/105/106/107/108/110/112, Gravel043, ScatteredLeaves009 | stones are flat paint blobs with no shading; "fine" gravel gets large blobs; soils carry pale blobs; leaves are discs | open |
| F5 | compositions missing from the albedo benchmark | Rock063, Rock064, Metal053C, Ground037 | the albedo recreation draws the base alone, so a mossy rock is all moss and a rusted metal has no rust; Rock064 is a STACKED STONE wall with moss in its joints | open |
| F6 | tiles | Tiles139/140/141/142/143/144 (grout faint or gone), Tiles107 (white faces speckled), Tiles138 (3.8x the count), Tiles144 (1.41x bright) | a tile is a cloud of speckle with no joint | open |
| F9 | rock speckle | Rock020/030/051/058/060 | salt-and-pepper grain at 1.7-1.8x contrast; the truths are broad tones with veins and fractures | open |
| F7 | wood | Wood096/092/058, WoodFloor040/041 (grain runs DOWN in the truth); Wood094 smooth wood at 2.39x contrast | orientation; a smooth wood's grain too strong | open |
| F8 | board ends | WoodFloor007/043, Planks037A | a board's end is a soft dark band ~10 px wide, not a line | open |
| F10 | fabrics | Fabric085, Fabric019 (wool is a KNIT), Fabric080 (plaid is crossed stripes) | knit and tartan not drawn | open |
| F11 | fan setts | PavingStones150/151 | setts' tones too contrasty, the arches lost whole | open |
| F12 | leather | Leather038 (blurry blotches close up), Leather034C (stitched quilting) | | open |
| F14 | roofs | RoofingTiles012A/013A (blurry clouds on each tile), 014A (shakes), 013A (slate) | | open |
| F15 | carpet pile | Carpet012, Carpet016 | pile too faint (contrast 0.30-0.40) | open |
| F16 | light asphalt | Asphalt031 | aggregate too faint (contrast 0.36) | open |
| F17 | grass scale | Ground037 | strokes 3x the truth's | open |
| F18 | moss colour | Moss002 | olive and pale against a vivid green (fitted table: refit) | open |
| F19 | planks | Planks039 ("large", dirty), WoodFloor070 basketweave | | open |

Description-limited (documented, not forced): Concrete045 board-formed concrete ("pattern" only), Road008B/009C
markings without a marking word, Plastic010 blue-grey "white", Leather037/039 hues, Bricks075A flagstones
called "bricks", Bricks076A stone called "bricks", Wood066 red-brown called "brown".

## Four-set runs (round 11)

| run | albedo brightness | contrast | scale | colour | roughness mean err | spread \|log\| | normal \|log\| |
|---|---|---|---|---|---|---|---|
| round 10 end (26f83b3) | 0.162 | 0.212 | 0.306 | 0.1291 | 0.0896 | 0.400 | 0.423 |
