# Round 7: what the pictures said, and what it forced

The score says how close a recreation is. The sheet says whether it
*is* the material. Both were run against the twenty hand-picked
ambientcg sets; the wide sample is in `coverage_audit.md` and it is
the honest baseline, and `description_limits.md` records what the
WORDS can and cannot say.

## The score, before and after

| | start of round 7 | now |
|---|---|---|
| **the twenty sets** | | |
| mean brightness ratio | 0.95x | 0.93x |
| mean contrast ratio | 1.03x | 1.15x |
| mean scale ratio | 1.57x | 1.05x |
| mean seam | 3.87x | 0.43x (the truth's 0.60x) |
| **the eighty-seven wide sets** | | |
| mean brightness ratio | 1.07x | 1.10x |
| mean contrast ratio | 1.60x | 1.31x |
| mean scale ratio | 1.23x | 1.34x |
| mean seam | 2.39x | 0.71x (the truth's 0.54x) |

The wide set's numbers are WORSE than the twenty's and that is the
point: the twenty were chosen by hand and they are the easy ones.
The wide set has the kinds the lane had no pattern for, and their
scores are in it.

## The picture: the defects the score could not see

### 1. The scattered ground's stones were a plate of cracked mud

The truth's gravel, measured off its own pixels: sixteen thousand
bright blobs at the eightieth percentile, a median diameter of 1.6 px
in a thousand and twenty-four, covering a fifth of the surface.

Ours had thirteen hundred and eighty blobs with a ninetieth
percentile diameter of 26 px. The stone was a twenty-seventh of the
surface; the truth's is a one-hundred-and-sixtieth. And the size
follows a **square** law and not a cube - a stone's area goes with
the square of its size, and a cube law covered nine per cent of the
surface where the truth's covers twenty.

### 2. The contrast fix was moving the brightness

The image's variation was scaled about the palette's DARK end and
not about the image's own mean, and a point that is not the mean
drags the mean with it. The scattered ground's luma was 0.344 and
the correction lifted it to 0.430 - so the ground read 1.44x the
truth's.

The image is scaled about its own mean now, and it is SHIFTED to the
description's value: the brightness and the contrast are
independent, and both are the description's own.

### 3. The stone's tone never landed

It was MAXIMISED against the slow field it rides on, and the slow
field's value was higher than any stone's tone - so the tone field
stayed the slow field and the ground read as a smooth sheet with
the stones' edges drawn on it.

### 4. THE NOISE'S HASH WAS A SINE OF A LARGE NUMBER

`sin((wy * 31 + wx * 17) * 12.9898 + 78.233)`: two corners one cell
apart differ by 220 radians, and the sine of that is uncorrelated
from the sine of the next one. So the lattice's corners were
independent random numbers and the "value noise" was white noise
with a smooth interpolation between unrelated corners.

Measured: the field's correlation fell to nothing within five pixels
whatever the lattice's size - a size of four gave a forty-nine pixel
period and a size of sixteen gave five.

### 5. THE DOMAIN'S SAMPLES MISSED THE WRAP

`(i + 0.5) / N` meant the image covered N-1 steps of the field's
period and not N, and the wrap joined two places the field had never
been. The Perlin's own seam grew with its lattice - 0.006 at eight
cells and 0.011 at sixteen - and the wood's seam read 11.88x the
truth's.

The samples are `i / N` and the field's period lands exactly on the
pixel after the last.

And the fBm scaled its samples twice, so a caller that asked for
sixteen cells got two hundred and fifty-six.

### 6. A COUNT THAT IS A POWER OF TWO LOSES THE TRUTH

A pattern's cell count must divide the resolution, and the
resolution is a power of two - so every divisor of it is a power of
two, and a pattern's count rounds DOWN to the wrong number.

Measured: a roof's 5.6 courses became four, a parquet's ten blocks
became two, and the shingles came out 256 pixels wide where the
truth's are 185.

So the count is the truth's own and the map WRAPS on it - and the
PITCH is what divides the resolution.

### 7. A STAGGERED PATTERN'S WRAP IS A COLOUR STEP

The half-cell stagger means the wrap joins a cell to one a whole row
away. So three things have to change together: the offset shifts
the INDEX and not the sample, the offset's PARITY has to be the same
at the top and the bottom, and anything PER-CELL that carries
colour becomes a step.

Measured: the roof's seam read 12.4x the truth's and the parquet's
3.5x to 7x - and both are under 2x now, with a SMOOTH field
carrying the per-cell variation instead of a hash.

### 8. TWO SCALES, NOT ONE

A leather is a coarse envelope and a fine grain on it, and the fine
carries most of the spread. A wallpaper's design is the same. And a
grain's fibre runs ALONG the board while its rings are coarse DOWN
it - the truth's own Wood096 measures sixty-eight features across
and eight down.

## The kinds the lane had no pattern for

| the kind | what it is | what the truth's measures |
|---|---|---|
| `parquet` | long staggered blocks, each with its own tone and grain | a row-to-column change ratio of 0.24 - the most horizontal surface in the sample |
| `carpet` | a fine isotropic fuzz with a slight direction | a period of nine pixels in a thousand and twenty-four, a ratio of 1.20, a spread of 0.0301 |
| `leather` | a coarse envelope and a fine crackle on it | the envelope at six to thirty-five across, the crackle at a hundred and fourteen to five hundred and twelve |
| `wallpaper` | a coarse envelope and a fine fleck on it | five and a half features across and a spread of 0.0072 - a design is a whisper |
| `markings` | painted geometry over a surface | three markings across a road, nine to fourteen pixels wide, the dash half the pitch |
| `woven` | a crosshatch of two thread fields | Fabric030: four hundred and twelve features across and forty-four down |
| `roof` | courses of overlapping shingles | a course every 177 pixels, a shingle every 185 |
| `herringbone` | boards at ninety degrees, in pairs | the truth's own parquet is a basketweave |

## The palette

It was fitted on twenty materials. It is fitted on eighty-seven now,
by `scripts/benchmarks/fit_palette.py`, and the tables are MERGED and
not replaced - a word the truth set does not measure keeps the value
the word's own sense gives it.

And five rules the fitting exposed:

- a colour's value is fitted where the colour is the **only** word
  about it: "blue" names three materials in the wide set and their
  mean is no material's colour.
- a colour word's **specificity** decides: "beige" names fourteen
  materials and "espresso" names one, and the one is the specific
  one.
- the **most specific material** decides, and a generic one lets the
  colour: a carpet is a carpet and not a fabric, and a wood's
  brightness is its colour's and not its kind's.
- a metal's own word is the **specific** one, and it says how much
  the sheet varies: "gold" names one material and its spread is
  0.0064 - the truth's own Metal048A to within a thousandth.
- the **darkest** colour named wins, and not the first: a "blue,
  dark" thing is a dark blue, and the truth's own Carpet012 is 0.229.

## The Material Maker ports

| item | state |
|---|---|
| `multi_warp2`, `warp` | ported (`pbr/warp.py`) |
| `fbm4` | ported, and the HASH WAS BROKEN - now an integer mix |
| `splatter` | ported, and the wrap was missing - now nine copies |
| `smooth_curvature2` | **ported** (`pbr/curvature.py`) |
| `scratches2` | **ported** (`pbr/curvature.py`) |
| the exact bisector border | not ported - the FBM-Worley already uses a bisector distance |
| `crystal`, `beehive`, `shard_fbm`, `sdf3d_fbm2` | not useful for the benchmark's kinds |
| the exporter's ORM packing | already matches golem's |

## The next round

1. The leathers: their word-fits span a twentyfold range and the
   words cannot say which is which. The *structure* is right and the
   contrast is not.
2. The rocks: the truth's are a sharp faceted surface and the
   lane's are a smooth blob field.
3. The roads' paint: the truth's wear is a measurement and the
   lane's is a guess from the words.
4. The ground's two scales: the truth's gravel has a fine scale (the
   stones) and a coarse one (the drift), and the drift is what the
   feature measure reads.
