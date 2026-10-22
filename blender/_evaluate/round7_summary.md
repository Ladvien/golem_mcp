# Round 7, in one page

## What was asked

Keep refining the procedural PBR lane, benchmark it against real
ambientcg materials, use Material Maker's source for what it can
give, and look at every picture.

## What was measured

| | start | end |
|---|---|---|
| **the twenty hand-picked sets** - brightness / contrast / scale | 0.95x / 1.03x / 1.57x | 0.97x / 1.02x / 0.96x |
| **twenty sets - seam** | **3.87x** | **0.50x** (truth 0.60x) |
| **the eighty-seven wide sets** - brightness / contrast / scale | 1.07x / 1.60x / 1.23x | 1.07x / 1.16x / 1.05x |
| **eighty-seven sets - seam** | **2.39x** | **0.31x** (truth 0.54x) |
| **the value's word-fit** (87 materials) | 0.0790 | **0.0594** |
| **the spread's word-fit** (87 materials) | 0.0151 | **0.0115** |

The wide set's numbers are *worse* than the twenty's - correctly,
because the twenty were hand-picked. The seventeen materials the
popular list never reaches (leather, roofing tiles, wallpaper,
carpets, parquets, planks) are the ones that found the rules below.

The wide set's means are inflated by two materials and its medians
are the honest summary: brightness 1.000, contrast 1.003, scale
1.000.

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
  blur - a fifth of the map's variance.
- **A FABRIC is a WEAVE** - the truth's own Fabric085 is a twill and
  its neighbours Fabric061 and Fabric066 are a mesh and a
  herringbone, and a Voronoi is a set of cells with joints between
  them.
- **A GROUND is a PACKED bed of grit** - the truth's own Ground110
  measures the bright stones' widths at 1, 2, 3, 4, 5, 7 and 8
  pixels in the counts 1071, 541, 30, 8, 2, 2 and 1, and its darkest
  thousandth is 0.000. The count is what puts the shadow in.
- **A ROCK's joint is a CRACK** - the truth's own Rock064's cracks
  read a luma of 0.336 where its ramp's dark end is 0.324, and a
  brick's grout reads 0.427 where its value is 0.460. A crack is a
  shadow; a grout is a filled joint.
- **A wood's RINGS are not its features** - at four rings the lane
  reads 9.2 features and at eight it reads 19.3, so the features are
  two and a third times the rings.
- **A leather's CRACKLE follows the surface** - the truth's six
  leathers measure nineteen to five hundred and twelve features and
  the crackle is what the measure reads on four of them.
- **A ROCK's moss is a patch** - the truth's own Rock064's green share
  has a standard deviation of 0.0336 over sixteen-pixel blocks and
  the lane's had 0.0019, because the hue variation was applied only
  to the scattered path's stones.

## The rules the eighty-seven taught

1. **The EXTREME words are the value, and the kind is not.**
   "tiles" names eight materials whose lumas run from 0.211 to
   0.972 - the kind says nothing about how light it is. But "black",
   "white", "dark" and "light" are about the lightness and about
   nothing else. Mean error 0.0790 -> 0.0594, worst 0.4035 -> 0.2224.

2. **The SPREAD is the most specific word, and the material's own
   wins.** "roof" names three and says 0.0192; "tiles" names eleven
   at a mean of 0.0494, and the truth's own RoofingTiles012A is
   0.0149. Mean error 0.0151 -> 0.0115, median 0.0090 -> 0.0055.

3. **The SPECIFIC kind is read before the generic one.** The truth's
   own Tiles141 is tagged with BOTH "stone" and "tiles", and
   "stone" is the generic one.

4. **A word that names FEW materials can still disagree with
   itself.** "granular" names two and the two disagree by 0.0678, so
   it says nothing about either, and the "asphalt" beside it says
   0.0178.

## New capabilities

Eight kinds added (`parquet`, `carpet`, `leather`, `wallpaper`,
`markings`, `woven`, `roof`, `herringbone`); three wrong kinds fixed
(concrete was cobbles, fabric was pebbles, metal was banded).
Material Maker's `smooth_curvature2` and `scratches2` are now
**wired in** - a rock's facets are its curvature, a worn sheet's
abrasion is its scratches. The brick's face is a **domain-warped**
field, per brick, so a wall of them reads as a wall of worked
stones. A fabric is a **weave** and its threads are all the cloth.

## What's left, honestly

- The leathers' word-fits span 20x and the words can't distinguish
  them - structure right, contrast not.
- One hue per surface can't say a grey rock with yellow veins (the
  truth's own Rock051).
- The palette's value can't be refitted honestly: a leave-one-out
  refit of the material table is *worse* (0.0870 against 0.0716), so
  the table stands and the word simply cannot pin the value.
- The WOOD's structure is a board with straight seams, knots and
  nested cathedral arcs, and the lane's is a field of soft blobs.
  The wood's feature scale now reads 0.82x the truth's where it read
  1.74x, but the *shape* is still wrong.
- The ROCK is a set of flat facets with thin joints and the truth's
  is a continuous relief: the truth's gradient's median is 0.0362
  and only one and a half per cent of its surface is flat, where the
  lane's is flat over fifty-four per cent.

That and the rest is in `description_limits.md`.
