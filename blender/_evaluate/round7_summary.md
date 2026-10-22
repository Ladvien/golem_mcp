# Round 7, in one page

## What was asked

Keep refining the procedural PBR lane, benchmark it against real
ambientcg materials, use Material Maker's source for what it can
give, and look at every picture.

## What was measured

| | start | end |
|---|---|---|
| **the twenty hand-picked sets** - brightness / contrast / scale | 0.95x / 1.03x / 1.57x | 0.97x / 1.14x / 0.96x |
| **twenty sets - seam** | **3.87x** | **0.51x** (truth 0.60x) |
| **the eighty-seven wide sets** - brightness / contrast / scale | 1.07x / 1.60x / 1.23x | 1.07x / 1.30x / 1.26x |
| **eighty-seven sets - seam** | **2.39x** | **0.30x** (truth 0.54x) |
| **the value's word-fit** (87 materials) | 0.0790 | **0.0594** |
| **the spread's word-fit** (87 materials) | 0.0151 | **0.0124** |

The wide set's numbers are *worse* than the twenty's - correctly,
because the twenty were hand-picked. The seventeen materials the
popular list never reaches (leather, roofing tiles, wallpaper,
carpets, parquets, planks) are the ones that found the rules below.

## What the pictures found that the score could not

- The **noise's hash was `sin()` of a large number** - two lattice
  corners one cell apart differ by 220 radians, so the "value
  noise" was white noise with smooth interpolation between unrelated
  corners. Now an integer mix.
- **The domain's samples were `(i+0.5)/N`** - covering N-1 steps of a
  periodic field, not N. The wood's seam read 11.88x.
- **The contrast fix scaled about the palette's *dark* end**,
  dragging the brightness with it (ground at 1.44x).
- **The gravel's stones were 26 px wide** vs the truth's 1.6 - a
  stone's area goes with the *square* of its size.
- **A count that divides the resolution is stuck at powers of two**
  - the truth's roof has 5.6 courses.
- **A staggered pattern's wrap is a colour step** - the roof's seam
  was 12.4x; the fix is three coordinated changes.
- **The upsample clipped instead of wrapping** - the rock's seam was
  2.54x.
- **"corrugated" contains "rug"** - the truth's corrugated steel was
  being routed to `carpet`.
- **A BRICK's face is WORKED and a TILE's is GLAZED** - the truth's
  own Bricks113A measures a spread of 0.0716 on the face alone,
  nearly the whole map's, and its blur profile decays from 0.0682 to
  0.0087: the face has structure at EVERY scale. The truth's own
  Tiles141 carries a drift of 0.0349 at a hundred-and-twenty-eight
  blur - a fifth of the map's variance - with a period of a hundred
  and ninety-two pixels. A tile STAINS; a brick is a mosaic of
  worked stones.

## The three rules the eighty-seven taught

1. **The EXTREME words are the value, and the kind is not.**
   "tiles" names eight materials whose lumas run from 0.211 to
   0.972 - the kind says nothing about how light it is. But "black",
   "white", "dark" and "light" are about the lightness and about
   nothing else. The truth's own Rock035 is a "black, cave, cliff,
   grey, rock, stone" at 0.094 and the material's word said 0.362.
   Mean error 0.0790 -> 0.0594, worst 0.4035 -> 0.2224.

2. **The SPREAD is the most specific word, and the material's own
   wins.** "roof" names three and says 0.0192; "tiles" names eleven
   at a mean of 0.0494, and the truth's own RoofingTiles012A is
   0.0149. Mean error 0.0151 -> 0.0124, median 0.0090 -> 0.0055.

3. **The SPECIFIC kind is read before the generic one.** The truth's
   own Tiles141 is tagged with BOTH "stone" and "tiles", and
   "stone" is the generic one.

## New capabilities

Eight kinds added (`parquet`, `carpet`, `leather`, `wallpaper`,
`markings`, `woven`, `roof`, `herringbone`); three wrong kinds fixed
(concrete was cobbles, fabric was pebbles, metal was banded).
Material Maker's `smooth_curvature2` and `scratches2` are now
**wired in** - a rock's facets are its curvature, a worn sheet's
abrasion is its scratches. The brick's face is a **domain-warped**
field, per brick, so a wall of them reads as a wall of worked
stones.

## What's left, honestly

- The leathers' word-fits span 20x and the words can't distinguish
  them - structure right, contrast not.
- One hue per surface can't say a grey rock with yellow veins (the
  truth's own Rock051).
- The palette's value can't be refitted honestly: a leave-one-out
  refit of the material table is *worse* (0.0870 against 0.0716), so
  the table stands and the word simply cannot pin the value.

That and the rest is in `description_limits.md`.
