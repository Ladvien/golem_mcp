# Round 7, in one page

## What was asked

Keep refining the procedural PBR lane, benchmark it against real
ambientcg materials, use Material Maker's source for what it can
give, and look at every picture.

## What was measured

| | start | end |
|---|---|---|
| **the twenty hand-picked sets** | | |
| brightness | 0.95x | 0.93x |
| contrast | 1.03x | 1.14x |
| feature scale | 1.57x | 1.03x |
| **seam** | **3.87x** | **0.58x** (the truth's 0.60x) |
| **the eighty-seven wide sets** | | |
| brightness | 1.07x | 1.10x |
| contrast | 1.60x | 1.30x |
| feature scale | 1.23x | 1.32x |
| **seam** | **2.39x** | **0.34x** (the truth's 0.54x) |

The wide set's numbers are worse than the twenty's and that is the
point: the twenty were chosen by hand. The wide set has the kinds
the lane had no pattern for.

## The defects the pictures found, and the fixes

1. **The gravel's stones were a plate of cracked mud** - 26 px wide
   where the truth's are 1.6. The stone's size follows a SQUARE law
   and not a cube, and the count is thirty thousand and not seven
   hundred.
2. **The contrast fix was moving the brightness** - the variation was
   scaled about the palette's dark end and not about the image's own
   mean, and a point that is not the mean drags the mean with it.
3. **The noise's hash was a sine of a large number** - two corners
   one cell apart differ by 220 radians, so the lattice's corners
   were independent random numbers. The hash is an integer mix now.
4. **The domain's samples missed the wrap** - `(i + 0.5) / N` covers
   N-1 steps of the field's period and not N.
5. **A count that is a power of two loses the truth** - the count
   must divide the resolution, and every divisor of a power of two
   is a power of two. The count is the truth's own and the pitch
   divides.
6. **A staggered pattern's wrap is a colour step** - the offset
   shifts the INDEX and not the sample, the offset's parity has to
   match at the top and the bottom, and a per-cell hash is a step.
7. **The upsample clipped instead of wrapping** - and the coarse
   grid has to cover its period and one step more.
8. **Two scales, not one** - a leather is an envelope and a fine
   crackle on it, and the fine carries the spread.
9. **The words were a substring test** - "corrugated" contains
   "rug", and the truth's own corrugated steel came out as a carpet.

## The kinds that were added

`parquet`, `carpet`, `leather`, `wallpaper`, `markings`, `woven`,
`roof`, `herringbone` - eight kinds the lane had no pattern for, and
the wide set's seventeen missing materials were fetched to measure
them.

And three kinds that were WRONG and are fixed: a `concrete` was a
field of cobbles, a `fabric` was a field of pebbles, and a `metal`
was banded.

## Material Maker

Ported and WIRED IN:

- `smooth_curvature2` - a rock's facets are its curvature
- `scratches2` - a sheet's abrasion

Ported already: `multi_warp2`, `warp`, `fbm4`, `splatter`.

## The palette

Fitted on eighty-seven materials by
`scripts/benchmarks/fit_palette.py`, and six rules the fitting
exposed - the most specific word decides, a generic material lets
the colour decide, the darkest colour named wins, a material's own
word says how much it varies, and a metal's own word is the
specific one.

## What is left, and why

The leathers: their word-fits span a twentyfold range and the words
cannot say which is which. The structure is right and the contrast
is not.

The two-colour surfaces: the truth's own Rock051 is a grey with
yellow veins in it, and one hue for the whole surface cannot say it.

That and the rest is in `description_limits.md`.
