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
