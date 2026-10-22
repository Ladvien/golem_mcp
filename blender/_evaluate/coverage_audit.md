# The coverage audit: what the lane has a pattern for, and what it guesses

The benchmark's twenty sets were chosen by hand, and a fit against
twenty materials is a fit against twenty materials. So the benchmark
now runs against a **wide** sample: seventy real ambientcg sets over
sixteen kinds, fetched by the same script with a wider net.

The question this records is not the score. It is the **coverage**:
for each real material, which pattern the lane picks, and whether
that pattern is the material's actual kind.

## The sample

Seventy materials over sixteen kinds - brick, wood, tile, metal,
ground, rock, fabric, concrete, plaster, gravel, sand, asphalt,
leather, carpet, roof, wallpaper - eight of each kind, the popular
list's order breaking the ties.

## What the lane had, and what it guesses

| the lane's pattern | the materials |
|---|---|
| `voronoi` | 24 |
| `brick` | 17 |
| `grain` | 9 |
| `scattered` | 8 |
| `metal` | 8 |
| `flat` | 4 |

Twenty-four of the seventy went to `voronoi`, and `voronoi` is the
**guess** - what a surface that matches nothing is assumed to be.

## What it guessed wrong

The wide set has kinds the lane had **no pattern for**:

- **leather** - a pebbled hide; the truth's cells are a fine, even
  grain and not stones.
- **carpet** - a pile of fibres; a directional fine grain.
- **roof** - courses of shingles; the truth's rows are staggered and
  their tone is per shingle.
- **wallpaper** - a printed pattern; a *flat* sheet with a design on
  it, and not a noise.
- **parquet and planks** - a wood floor; the truth's blocks are
  laid in a pattern and not a grain.
- **leaves, grass, moss** - an organic scatter; the truth's is a
  dense mat of overlapping shapes.
- **road markings** - a painted line on a surface; the truth's is
  geometry and not noise at all.
- **a woven cloth** - a crosshatch of two thread fields; the truth's
  is hundreds of features across.

And a *wood* floor is a wood floor, and the lane's `grain` is a
plank's grain and not a parquet's blocks.

## What it gets right

- the loose grounds are `scattered` now, and the truth's gravel is
  a field of separate stones and not a tiling.
- the smooth surfaces are `flat`, and the truth's plaster is one
  sheet and not a field of cobbles.
- the metals are `metal`, and the truth's is a sheet with a
  direction and not a set of cells.
- the woods are `grain`, and the truth's is a board's fibre.

## The kinds that are now there

| the kind | what it is | what the truth's measures |
|---|---|---|
| `parquet` | long staggered blocks, each with its own tone and its own grain | a row-to-column change ratio of 0.24 - the most horizontal surface in the sample |
| `carpet` | a fine isotropic fuzz with a slight direction | a period of nine pixels in a thousand and twenty-four, a ratio of 1.20, a spread of 0.0301 |
| `leather` | a fine even pebbled hide | the loose ground's primitive at a much finer scale and a much tighter packing |
| `wallpaper` | a flat sheet with a printed design on it | the flat sheet with the tile's structure on it |
| `markings` | painted geometry over a surface | three markings across a road, nine to fourteen pixels wide, the dash half the pitch |
| `woven` | a crosshatch of two thread fields | Fabric030: four hundred and twelve features across and forty-four down |

## The next kinds to add

In the order the wide set says they are worth having:

1. **roof** - courses of shingles, which are the brick's courses with
   a per-shingle tone.
2. **a rough cloth** - a fabric whose threads are coarse and whose
   weave is irregular.
3. **a printed cloth** - a fabric with a printed design on it, which
   is the wallpaper's structure on a fabric's palette.
