# The coverage audit: what the lane has a pattern for, and what it guesses

The benchmark's twenty sets were chosen by hand, and a fit against
twenty materials is a fit against twenty materials. So the benchmark
now runs against a **wide** sample: eighty-seven real ambientcg sets
over twenty kinds, and the seventeen that the popular list never
reaches - the leather, the roofing tiles, the wallpaper, the
carpets, the parquets and the planks - are fetched directly by
`scripts/benchmarks/fetch_ambientcg_kinds.py`.

The question this record is not the score. It is the **coverage**:
for each real material, which pattern the lane picks, and whether
that pattern is the material's actual kind.

## The kinds the lane had NO pattern for, and what they are now

| the kind | what it is | what the truth's measures |
|---|---|---|
| `parquet` | long staggered blocks, each with its own tone and its own grain | a row-to-column change ratio of 0.24 - the most horizontal surface in the sample |
| `carpet` | a fine isotropic fuzz with a slight direction | a period of nine pixels in a thousand and twenty-four, a ratio of 1.20, a spread of 0.0301 |
| `leather` | a coarse envelope and a fine crackle on it | the envelope at six to thirty-five across, the crackle at a hundred and fourteen to five hundred and twelve |
| `wallpaper` | a coarse envelope and a fine fleck on it | five and a half features across and a spread of 0.0072 - a design is a whisper |
| `markings` | painted geometry over a surface | three markings across a road, nine to fourteen pixels wide, the dash half the pitch |
| `woven` | a crosshatch of two thread fields | Fabric030: four hundred and twelve features across and forty-four down |
| `roof` | courses of overlapping shingles | a course every 177 pixels, a shingle every 185 |
| `herringbone` | boards at ninety degrees, in pairs | the truth's own parquet is a basketweave |

## And the kinds that were WRONG, not missing

- a **concrete** was a `voronoi` - a field of cobbles - and it is a
  `flat` sheet. The truth's own Concrete048 measures seventy-nine
  features across with a spread of 0.0280.
- a **fabric** was a `voronoi` - a field of pebbles - and it is a
  `woven` crosshatch. The truth's own Fabric030 measures four
  hundred and twelve features across and forty-four down.
- a **metal** was banded and it is a sheet. The truth's own metals'
  row-to-column change ratios are 1.04, 1.00, 1.13 and 1.00, and
  ours came out at 0.52 and 4.39.
- a **wallpaper**'s design was a chequer and it is a fleck.
- a **rock** was a smooth blob field and it has FACETS - and the
  facets are the surface's curvature, which is Material Maker's
  `smooth_curvature2` and the map that gives a hand-painted edge
  treatment its rim.

## The words have to be WHOLE words

"corrugated" contains "rug", and "rug" is a carpet - so the truth's
own corrugated steel came out as a carpet until the match was
changed to whole words.

And a kind a word names OUTRIGHT is read before the structures: a
"parquet" is a parquet and not a plank, and a "corrugated steel" is
a pressed metal sheet and not a road with markings on it.

## What the words can and cannot say

`description_limits.md` has the full account. The short version: the
wide set's own WoodFloor040 and Planks037A have the SAME
description and measure 0.556 and 0.252, so a description cannot
say which one it means - and the leathers' spreads span twenty times
over their six.

So the lane's job is to get the STRUCTURE right and the brightness
as close as the words allow, and the score says where it cannot.

## The next kinds to add

In the order the wide set says they are worth having:

1. **a rough cloth** - a fabric whose threads are coarse and whose
   weave is irregular. The truth's own Fabric061 and Fabric066
   measure a spread of 0.127 and 0.131 against the woven one's
   0.114.
2. **a printed cloth** - a fabric with a printed design on it, which
   is the wallpaper's structure on a fabric's palette. The truth's
   own Fabric081C is a white printed plastisol with a spread of
   0.0032.
3. **a two-colour surface** - a rock with grey stone and yellow
   moss on it, or a tile with a different glaze in the middle. One
   hue for the whole surface cannot say it, and the truth's own
   Rock051 is a grey with yellow veins in it.
