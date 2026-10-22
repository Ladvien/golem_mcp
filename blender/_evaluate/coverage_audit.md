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

## What the lane picks

| the lane's pattern | the materials |
|---|---|
| `voronoi` | 24 |
| `brick` | 17 |
| `grain` | 9 |
| `scattered` | 8 |
| `metal` | 8 |
| `flat` | 4 |

Twenty-four of the seventy go to `voronoi`, and `voronoi` is the
**guess** - what a surface that matches nothing is assumed to be.

## What it guesses wrong

The wide set has kinds the lane has **no pattern for**:

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

## The next kinds to add

In the order the wide set says they are worth having:

1. **leather** - a fine even pebbled grain, at a much finer scale
   than a gravel's.
2. **carpet** - a directional pile, which is the wood's fibre with
   a different direction and a much softer line.
3. **parquet** - blocks in a pattern, which is the brick's courses
   with a wood's tone.
4. **wallpaper** - a flat sheet with a printed design, which is the
   `flat` kind with a pattern on it.

The first two are the same primitive at two scales, and the third is
the brick's primitive with a different palette. None of them needs a
new field.
