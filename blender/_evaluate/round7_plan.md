# Round 7: what the pictures said, and what it forced

The score says how close a recreation is. The sheet says whether it
*is* the material. Both were run against the twenty hand-picked
ambientcg sets; the wide sample is in `coverage_audit.md` and it is
the honest baseline.

## The twenty-set score, before and after

| | start of round 7 | now |
|---|---|---|
| mean brightness ratio | 0.95x | 0.99x |
| mean contrast ratio | 1.03x | 1.04x |
| mean scale ratio | 1.57x | 0.97x |
| **mean seam** | **3.87x** | **0.41x** |

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

## The kinds the lane had no pattern for

| the kind | what it is | what the truth's measures |
|---|---|---|
| `parquet` | long staggered blocks, each with its own tone and grain | a row-to-column change ratio of 0.24 - the most horizontal surface in the sample |
| `carpet` | a fine isotropic fuzz with a slight direction | a period of nine pixels in a thousand and twenty-four, a ratio of 1.20, a spread of 0.0301 |
| `leather` | a fine even pebbled hide | the loose ground's primitive at a much finer scale |
| `wallpaper` | a flat sheet with a faint printed design | a spread of 0.0032 - a design is a whisper |
| `markings` | painted geometry over a surface | three markings across a road, nine to fourteen pixels wide, the dash half the pitch |
| `woven` | a crosshatch of two thread fields | Fabric030: four hundred and twelve features across and forty-four down |
| `roof` | courses of overlapping shingles | a course every 177 pixels, a shingle every 185 |
| `herringbone` | boards at ninety degrees, in pairs | the truth's own parquet is a basketweave |

## The palette

It was fitted on twenty materials. It is fitted on eighty-seven now,
by `scripts/benchmarks/fit_palette.py`, and the tables are MERGED and
not replaced - a word the truth set does not measure keeps the value
the word's own sense gives it.

And three rules the fitting exposed:

- a colour's value is fitted where the colour is the **only** word
  about it: "blue" names three materials in the wide set and their
  mean is no material's colour.
- a colour word's **specificity** decides: "beige" names fourteen
  materials and "espresso" names one, and the one is the specific
  one.
- the **most specific material** decides, and a generic one lets the
  colour: a carpet is a carpet and not a fabric, and a wood's
  brightness is its colour's and not its kind's.

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

1. The wide eighty-seven-set run, and what it says.
2. The two-scale structure: the truth's ground has a fine scale (the
   stones) and a coarse one (the drift), and the drift is what the
   feature measure reads.
3. The per-stone hue: the truth's stones vary by 1.5% in their red
   and blue shares, and ours are all one tan.
4. The leather's own scale: the six leathers range from five
   features across to five hundred and twelve.
