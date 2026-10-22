# Round 8: the popular set, the marbles, and a node graph

The lane recreates real ambientCG PBR sets from a DESCRIPTION. Measured
against the truth's own 154 materials across three sets.

## Where the lane stands (measured, ambientcg_popular, 47 materials)

| metric | before this round | after |
|---|---|---|
| the brightness | 1.206x | 1.14x |
| the contrast | 1.298x | 1.21x |
| the scale | 0.921x | 1.04x |

The mean brightness on `ambientcg` is 0.99x and on `ambientcg_wide` 1.07x.

## The bugs, in order of how much they cost

### 1. The marble's PERIOD was quantised to a power of two
The truth's Marble012 measures fourteen features across and its
Marble016 twenty-two; both quantised to sixteen, so the two marbles
came out with the SAME veins. The period is the cells themselves now.

### 2. The marble's WARP was unbounded
The warp displaces along the field's SLOPE, and the slope is
unbounded - where the bed was steep the displacement ran to many
cells and the contours folded into a fine mess (146 features where
the truth has 14). The displacement is clipped to a quarter of a
cell now.

### 3. A COATED metal wore the metal's colour, not the coat's
The truth's Metal027/029 are "black, covered, metal, painted, powder,
steel" at 0.180 and 0.128; the steel's word said 0.4686. But the
SHEET's word must beat the TONE's for a RUSTED plate (Metal063 is
0.429, and "black" would have said 0.06). The COAT is what tells
them apart.

### 4. A metal's colour came from the GENERAL table
The truth's Metal062C is "damaged, dirty, metal, platinum" at 0.733;
the general "platinum" is 0.1435. The metals have their own table now.

### 5. "plastic" and "leather" have no pattern of their own
"black, plastic, shiny, smooth" fell through to VORONOI - a field of
cobbles - where the truth's Plastic006 is a smooth moulded surface
(sd 0.0145) with fine vertical scratches. Same for the leathers.

## What Material Maker gives us that we do not have

Material Maker (MIT, RodZill4) is 426 node files and a 328-entry
library. Read at /tmp/material-maker.

### Its MARBLE template is the blueprint for the vein
`Workflow/Materials/Marble` builds the vein as a **gradient along the
warped X** - a LEVEL SET of the warped field, which is exactly the
construction the lane converged on by measurement. Its `graph_2` is a
`perlin` -> `transform` with `translate_x`/`translate_y` as the WARP
AMOUNT, and the vein is `colorize` over a `Simple Gradient` on
`$uv.x`.

So the vein is: warp the UV by a perlin's gradient, then take the
level set of the warped coordinate. Our version warps the *field*
instead of the *coordinate* - which is the same thing, but ours
measures the veins' own period, and the truth's confirms the level
set is right.

### Its noise is VALUE noise with a quintic fade
`value_noise_2d` uses `t = f*f*f*(f*(f*6-15)+10)` - the QUINTIC
smoothstep, not the cubic. A quintic fade has zero second derivative
at the lattice points, so the noise is C2 continuous and the field's
CONTOURS are smooth curves. Our perlin is gradient-based; a quintic
value noise's contours are what a marble's veins want.

### Its blend node is a full Photoshop-mode set
`blend.mmg` carries normal, dissolve, multiply, screen, overlay,
hard-light, soft-light, burn, dodge and more, each with an opacity
and a `blend_type` enum. That is the COMPOSITION layer the lane has
no equivalent of.

### Its `splatter`, `scratches2`, `crystal`, `beehive` are primitives
we do not have at all.

## The plan

### A. The node graph - compositing different textures
A description is not one pattern but a STACK: a base, a warp, an
overlay, a set of scratches. The lane picks ONE pattern and paints
it. Material Maker composes.

The node graph is a list of nodes, each with a type, parameters, and
a connection list, and it renders to an image. A named node type
resolves to a function that returns a field.

The graph is described in a small declarative form, so an agent can
write one:

    {"nodes": [
        {"type": "voronoi", "name": "base", "params": {...}},
        {"type": "warp", "name": "warp", "params": {"amount": 0.1},
         "inputs": {"strength": "base"}},
        {"type": "blend", "name": "mix", "params": {"mode": "multiply"},
         "inputs": {"a": "base", "b": "warp", "amount": 0.3}}
    ]}

The first version composites in the FIELD domain (a mask), not the
image domain - a blend of two fields is a blend of two fields, and
the image is written once at the end.

### B. The primitives Material Maker has that we do not
- `splatter` - droplets at Poisson-scattered points
- `scratches` - lines with waviness and randomness
- `crystal` / `beehive` - cellular structure
- the blend modes

### C. The remaining pattern routing
- "plastic" -> a smooth moulded surface
- "leather" -> a fine even grain, and the CLEAN one nearly flat

## The loop
Every change is measured against the truth's own, and every change is
LOOKED AT. A number without a picture is not a result.
