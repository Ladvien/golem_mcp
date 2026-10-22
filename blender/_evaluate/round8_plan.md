# Round 8 and 9: the popular list, the node graph, and the sheet

## The popular list is its own benchmark now

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

## What the sheet showed that the score did not

The score says how close a recreation is. The sheet says whether it
*looks* like the material, and the sheet found four things the score
had hidden:

| the material | the score said | the sheet showed |
|---|---|---|
| PavingStones151 | the scale 0.83x | a heap of loose stones where the truth is a tight grid of set stones — and the words say "grid, mosaic" |
| Ground093C | the brightness 0.64x | orange noise where the truth is a smooth beach — and the words say "beach, dune, sand" |
| Metal055A | the contrast 1.29x | hard vertical worms where the truth is a soft mottle |
| Fabric083 | the contrast 1.24x | a big chequerboard where the truth is a fine crackle weave |

Each was a ROUTING or a SCALE fault, and each was found by looking.

## The faults, and what fixed them

### 1. A PAVING is not a loose ground
"cobblestone" routed to SCATTERED — a heap of loose stones — and the
truth's PavingStones151 is a tight set of set stones, seventy-three
features across. So "grid" and "mosaic" decide, and they are read
before the loose grounds.

### 2. A SAND is a smooth sheet
"beach, dune, sand" routed to SCATTERED, and the truth's Ground093C
measures 7.6 features across with a spread of 0.0148 — a beach is
smooth. So "sand", "dune" and "beach" are the FLAT sheet, and they
come before the loose grounds.

### 3. A METAL's grain was at the wrong scale
The metal's grain noise was sampled on a lattice of FOUR — a grain
cell was 512 pixels across at 2048, so the "grain" was a handful of
enormous smooth lenses. The truth's own metals are ISOTROPIC: Metal055A
correlates +0.836 across and +0.842 down. So the lattice is sixteen
and the stretch is a half, and the correlation error fell from 0.1734
to 0.1454.

### 4. A CHECKERED cloth is a chequer and not a crosshatch
The truth's Fabric083's correlation goes NEGATIVE at a lag of eight
(-0.136) and a crosshatch of threads never does. So a "checkered"
cloth is a chequer of squares over the threads, and the chequer
wraps — it did not, and Fabric080's seam read 522.79.

### 5. A black is THREE blacks
The truth's own fifteen blacks split three ways and the word "black"
cannot tell them apart:

- a REFLECTIVE black catches the light and is the lightest — the
  truth's own Metal046B is 0.2463 and its Marble016 0.2436;
- a SMOOTH dielectric has nowhere to catch it and is the darkest —
  the truth's own Plastic006 is 0.0303 and its Leather026 0.0976;
- a TEXTURED dielectric is in between — the truth's own Plastic012A
  is 0.1700.

The value's mean error over a hundred and twenty-five of the truth's
own fell from 0.0645 to 0.0608.

### 6. A LEATHER's finish is its character
The truth's own six leathers' spreads run from 0.0032 to 0.0630 and
the material's own word said 0.0238 — a mean of nothing in
particular. The finish says which: clean 0.0032, smooth 0.0115,
suede 0.0160, orange 0.0198, bare 0.0279, stitched 0.0630. All six
read exactly now.

## Material Maker, and what it gave

Material Maker (MIT, RodZill4) is 426 node files and a 328-entry
library. It is not bpy-drivable and it does not need to be — it is
the closest thing to a well-organised catalogue of procedural PBR node
designs, and every one is clean-room-implementable in NumPy.

Its own **Marble template** is the blueprint for the vein: the vein is
a gradient along the warped X — a LEVEL SET of the warped field, which
is the construction the lane converged on by measurement.

Its **blend node** carries fourteen modes and the lane had nine. The
five it lacked are lighten, darken, difference, additive and addsub —
and addsub is the one that draws a dark vein on a pale stone and a
pale vein on a dark one.

Its **colorize node** is a RAMP and not a darkening: it says where
the stone goes from one tone to another and how fast, and a linear
darkening cannot. The marble's ramp has its veins at 0.09 and 0.34
and its stone between them.

Its **splatter** and **scratches2** are primitives the lane had no
equivalent of, and both are in the node graph now.

## The node graph

`src/golem_blender/pbr/nodegraph.py` — a description is not one
pattern but a STACK. A marble is flat stone with a network of veins
over it; a leather is a fine grain with a stain on it; a metal is a
sheet, brushed, with scratches.

The graph is a list of nodes, each a named FIELD producer, each
node's inputs naming other nodes, and it renders to one field. The
node types are `field`, `blend`, `warp`, `splatter`, `scratches`,
`colorize` and `math`.

And every field is NORMALISED before it enters a graph — ONE is the
feature and ZERO is the ground — because the lane's own patterns do
not agree: a Voronoi's field is the distance to the joint and a
marble's is the vein's coverage, and blending them raw mixes
meanings.

It is exposed through `generate_procedural_base_color`'s
`graph_json`, so an agent can author one.

## The loop

Every change is measured against the truth's own, and every change is
LOOKED AT. A number without a picture is not a result.
