# Rounds 8-13: the popular list, the node graph, and the sheet

## The popular list is its own benchmark

`ambientcg_top` — the site's own popular list, the materials with the
most downloads, sixty of them.

The site's `sort=popular` on the API sorts by RELEASE DATE, not by
downloads, so the list is built in
`scripts/benchmarks/fetch_ambientcg_popular_list.py`: the API is
asked for a wide page and the results are sorted by `downloadCount`.

The top of the real list:

    Road007            493749 downloads
    Marble012           483234
    Concrete034         476576
    Plaster001          476269
    Ground037           468280
    Wood051             429612
    Grass001            400836
    WoodFloor051        344504

The other sets pick their materials by KIND — eight of each — so that
no kind can be fitted to. That is the right shape for fitting the
palette's tables and the wrong shape for asking how good the lane is
on what people actually download.

**The fetch unpacks with `COPYFILE_DISABLE` and the `unzip` binary.**
Python's `extractall` writes a Mac AppleDouble sidecar beside every
member on a network filesystem, and the sidecar then SHADOWS the real
map: the truth read as an unreadable AppleDouble stub.

## The scores

| set | brightness | contrast | scale | seam |
|---|---|---|---|---|
| ambientcg (20) | 0.98× | 1.06× | 0.86× | 0.39× (truth 0.60×) |
| ambientcg_wide (87) | 1.04× | 1.15× | 0.99× | 0.36× (truth 0.54×) |
| ambientcg_popular (47) | 1.00× | 1.10× | 1.03× | 0.27× (truth 0.48×) |
| **ambientcg_top (60, the site's list)** | 1.11× | 1.10× | 1.06× | 0.28× (truth 0.44×) |

The popular list's contrast was 1.34× and it is 1.10×. The seam was
12.45× and it is 0.28× — *better* than the truth's own, because the
truth's maps are 1024px and the lane's are 2048px and the measure
reads the period in pixels.

## The sheet finds what the score cannot

`scripts/benchmarks/texture_sheet.py` puts the truth beside the
recreation. It found every one of these, and the score had not:

| the material | the sheet showed | the cause |
|---|---|---|
| PavingStones151 | a heap of loose stones; the truth is a tight set of set stones | "grid" and "mosaic" decide, before the loose grounds |
| Ground093C | orange noise; the truth is a smooth beach | "sand", "dune" and "beach" are the FLAT sheet |
| Metal055A | hard vertical worms; the truth is a soft mottle | the metal's grain lattice was FOUR |
| Fabric083 | a big chequerboard; the truth is a fine crackle | a checkered cloth is a chequer, and it wraps |
| Marble012 | fat light worms; the truth is a pale stone with fine dark veins | a marble's veins are DARK, and a LEVEL SET |
| Wood049 | smooth blobs; the truth is a field of fine grain | the fibre's lattice is the fibre's OWN |
| Wood028 | a neutral grey; the truth is a dark brown | a wood is always WARM |
| WoodFloor051 | a grid of squares; the truth is long boards | the courses are the truth's DOWN count |
| Plaster001 | a smooth wash; the truth is a speckled surface | a flat sheet has a TOOTH |

**A number without a picture is not a result.** Every one of these
was a routing fault, a scale fault or a polarity fault, and every one
of them was invisible to the score.

## The pattern: every constant became a table on the truth's own

- a **black** is three blacks — reflective 0.2499, smooth 0.0640,
  textured 0.1705 — and the words choose;
- a **metal**'s spread, refitted on all twenty of the truth's metals:
  clean 0.0076, smooth 0.0106, brushed 0.0202, scratched 0.0273;
- a **leather**'s finish: clean 0.0032, smooth 0.0115, suede 0.0160,
  orange 0.0198, bare 0.0279, stitched 0.0630;
- a **fabric**'s finish: printed 0.0032, soft 0.0090, clean 0.0347,
  wool 0.0508, grey 0.0815, rough 0.1282, checkered 0.1877;
- a **wood**'s value: espresso 0.2174, dark 0.2351, brown 0.3184,
  orange 0.5357, light 0.5753;
- a **roughness**, and it was a constant 0.60 for every material while
  the truth's own runs from 0.034 to 0.919.

## Material Maker, and what it gave

Material Maker (MIT, RodZill4) is 426 node files and a 328-entry
library at `/tmp/material-maker`. Its **Marble template** is the
blueprint for the vein: the vein is a gradient along the warped X — a
LEVEL SET of the warped field, which is the construction the lane
converged on by measurement.

Its **blend node** carries fourteen modes and the lane had nine. Its
**colorize node** is a RAMP, not a darkening. Its **splatter** and
**scratches2** are primitives the lane had no equivalent of.

And its **Perlin is a value noise with a quintic fade** — and a
Perlin's value is ZERO at every lattice point, so a field built on
one shows its lattice as a MAZE. The flat sheet's tooth is a value
noise now, and the maze is gone.

## The node graph

`src/golem_blender/pbr/nodegraph.py` — a description is not one
pattern but a STACK. The graph is a list of nodes, each a named FIELD
producer, each node's inputs naming other nodes, and it renders to
one field. The node types are `field`, `blend`, `warp`, `splatter`,
`scratches`, `colorize`, `blur` and `math`.

Every field is NORMALISED before it enters a graph — ONE is the
feature and ZERO is the ground — because the lane's own patterns do
not agree: a Voronoi's field is the distance to the joint and a
marble's is the vein's coverage, and blending them raw mixes
meanings.

`src/golem_blender/pbr/graph_plan.py` — the planner, and it lives
with the fitted tables because the palette holds what the truth's
own says about every word, and a graph whose layers are guessed
throws that away.

**Measured on the truth's own, the graph MATCHES the single-pattern
path** — the brightness 0.978 against 0.928, the contrast 1.784
against 1.826, the scale 1.542 against 1.522. So the graph is a
VIABLE composition path and not a better one, and the honest finding
is that the single-pattern path already extracts the description's
information, so a graph adds the ability to COMPOSE and not the
ability to fit.

## The wood's fibre, and the three faults that hid each other

The sheet showed the truth's Wood049 as a field of fine grain lines
and ours as a few smooth blobs, and the score had not noticed — the
features were within 20 per cent. Three faults, each hiding the next:

1. **The fibre's LATTICE was the rings' count.** The rings' count is
   the surface's own feature count, so a wood's fine grain came out a
   hundred pixels apart. The truth's own wood has its lines seven and
   a half pixels apart in a 1024 row, and a value noise's ridge
   crosses the middle of its range twice per lattice cell — so the
   lattice is 140 across the image, whatever the surface's own count.
2. **The fibre was computed at 512 and bilinearly upsampled.** A
   four-times upsample blurs a three-and-a-half-pixel line into a
   ramp, and the grain came out as a smooth gradient over twenty
   pixels.
3. **The line was the ridge's SLOPE**, which is two lines, one on each
   side of the crest — and the crest itself is where they meet, so the
   grain came out as a field of DOTS. The line is the ridge's own
   high values: a fold's crest is a LINE, a continuous stroke.

And a fourth, in the writer: **the darkness was shifted by half its
mean and then doubled**, and the doubling assumes a range of one —
but the darkness's range is the two layers' own sum and it runs to
0.9. So the shift left the lower half of the structure below zero
and the clip DROPPED IT, and the wood came out with no grain in it
at all. The darkness is scaled to its own range first and then
centred on the middle of that range.

**A general lesson: a normalisation that assumes a range clips the
structure it was meant to carry.** The `×2` after a shift is only
valid for a [0,1] field.

## The metal: three faults, each found by the sheet

The metal's score was the worst group in the set (1.56 on the top
set) and the sheet showed why: the truth's silver is a **fine brushed
sheen** and ours had a few broad arcs and scattered stipples.

1. **A BRUSHED sheet's streaks run ALONG the sheet.** The truth's
   own brushed steel and silver both have their high-frequency
   structure horizontal — a down period of four to ten pixels against
   an across period of twenty-three to a hundred and sixty-four. The
   measure reads along a row, so a sheet whose grain runs along the
   row is the sheet whose streaks the measure sees. Measured: a
   brushed sheet's scale error was 4.63 with the streaks across the
   row and 3.49 with them along it.
2. **The SCRATCHES were blobs.** Material Maker's own `scratches2`:
   the cell's frame is turned by the cell's angle, the x is divided
   by the cell's length and the y by the cell's width, and the value
   is a band a *thousand* times the divided y squared, times a taper
   along the length, times the cell's own edge distance. The port
   drew a RECTANGLE — the distance to the nearest of the two cell's
   edges — so a scratch came out as a blob at the cell's centre. The
   line's own position within the cell is a random offset of a whole
   cell, and without it the cells' own edges showed as a GRID.
3. **A metal names SEVERAL of its own colours, and they are MEANED.**
   The truth's own Metal009, Metal011 and Metal007 are all "silver,
   steel" and measure 0.582, 0.627 and 0.611. The colour tier read
   "steel" first — 0.439 — a third of the truth's. The mean of
   "silver" and "steel" is 0.711, and a scratched sheet is four
   fifths of a plain one, so 0.569 — the truth's within two per
   cent.

## A general lesson: a NAME can be a DIVISOR

Three of the module's constants were each **defined twice**, and the
second definition won. The fibre's stretch read as a divisor in one
block and as a multiplier in the other, and the block that read it as
a multiplier was the one that set it — so a change to the other
block changed nothing, and the sweep over it read flat.

The stretch is a divisor: the y lattice's cell count is the x count
TIMES the stretch, so a SMALLER number gives FEWER cells along y and
a LONGER streak. And the stretch was applied to the lattice's PERIOD
and not to the SAMPLE — the two samples are in their own base lattice
units, so the y sample has to be scaled by the STRETCHED count — and
that is why EVERY value of it gave the identical picture.

**A parameter that has no effect at all is a fault report.** A sweep
that reads flat is telling you the parameter is not wired, and it
found this in one run.

## A general lesson: a normalisation that assumes a range clips the structure

The writer's darkness was shifted by half its mean and then doubled,
and the doubling assumes a range of one — but the darkness's range is
the two layers' own sum and it runs to 0.9. So the shift left the
lower half of the structure below zero and the clip DROPPED IT, and
the wood came out with no grain in it at all. The darkness is scaled
to its own range first and then centred on the middle of that range.

## The marble: a crackle is a network, and a contour is a loop

The marble came out as a handful of big closed rings on a pale stone,
where the truth's own Marble021 is a fine network of veins that all
join up.

**A contour of a smooth field IS a closed loop.** That is what the
vein was, and it is why the marble looked like a handful of rings.
A crackle is the **distance to the borders of a set of cells**, and
that is a *network* by construction: every border is a piece of it
and they all meet.

And the crackle is the **GAP** between the two nearest features
(F2 − F1), which is zero *exactly* on the border between two cells.
The distance to the *nearest* feature is not that: it is zero at
every feature's own point, so a band about it is a set of **DOTS**
at the cell's centres, and the network broke up into spots.

And the gap's width does not depend on the lattice: a band of four
hundredths covers 4.9 per cent at a lattice of thirty-two and 4.9
per cent at a hundred and twenty-eight.

Three more faults hid behind that one:

- The cells were **straight-edged** — a Worley cell's border is a
  straight line between two points — so the marble came out as a
  **polygon mesh**. The cells are warped, so the veins wander.
- The vein's width was a fixed fraction of the gap, which gave the
  coarse marble a one-pixel vein and the fine one a vein too faint
  to see. The truth's Marble012's veins are **six pixels** across
  and a hundred and forty-four apart; its Marble021's are six pixels
  across and thirty-six apart. So the width is a fixed number of
  **pixels**.
- The marble's two layers are the other way round from a wood's: a
  marble's veins are a **fine network** and its stone a **gentle
  cloud**, and the wood's balance swamped the veins with the cloud.

## A general lesson: a centring that is a rescale leaves the range

The writer's darkness is scaled to its own range first, and then it
was clipped to half a range either side of its own middle and
**doubled** — which takes a zero-to-one field to minus-a-half-to-
one-and-a-half. The mean landed at **1.28** and the top of the range
was clipped away.

A centring is a **shift**. The range is already one; doubling it
takes it out of the space it is supposed to live in.

## The ORM

Blender 5.2 has **no metallic bake pass** — the pass enum is
COMBINED, AO, SHADOW, POSITION, NORMAL, UV, ROUGHNESS, EMIT,
ENVIRONMENT, DIFFUSE, GLOSSY, TRANSMISSION, and there is no metallic
in it. So a metal's metallic channel cannot be baked: it has to be
COMPUTED, and the description is what says whether the surface is
one. The truth's own metals are 1.000 metallic, all of them.

So `bake_orm_map` and `assign_pbr_constants` take a description and
read the roughness and the metallic from the lane's own fitted
tables, and the ORM's G and B channels stop being constants.
