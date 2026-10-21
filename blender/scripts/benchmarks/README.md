# The benchmark: recreating real PBR sets from a description

The lane had only ever been measured against a texture it made itself.
This measures it against **real sets**: ambientcg's, which are CC0,
photoreal, and carry the three maps the lane produces - the albedo,
the normal map and the roughness.

The **recreation** gets only the material's own words - "bricks,
stone", "beige, grain, knots, wood", "aged, black, brown,
oxidized, steel" - and never the ground truth's pixels. The pattern,
the palette and the scale all come from those words and from the
size.

## The score

Over twenty materials, against the truth's:

| | the lane's | the truth's |
|---|---|---|
| the brightness | 0.95x | 1.00x |
| the contrast | 1.04x | 1.00x |
| the feature scale | 0.88x | 1.00x |
| the seam | 0.35x | 0.60x |

The reference sets' own seams run from 0.32x to 2.35x, so the lane is
inside the range real PBR sets occupy.

The colour is the truth's own too. A palette with no hue made every
material grey, and the truth's are not: the fabric is R 0.217 G
0.333 B 0.451, the wood R 0.420 G 0.328 B 0.251 and the ground R
0.379 G 0.336 B 0.286, and only the metal and the concrete are
neutral.

## The order the scripts run in

```
python scripts/benchmarks/fetch_ambientcg_ground_truth.py
blender --background --factory-startup --python scripts/benchmarks/convert_ground_truth.py
blender --background --factory-startup --python scripts/benchmarks/measure_ground_truth.py
blender --background --factory-startup --python scripts/benchmarks/recreate_from_descriptions.py
blender --background --factory-startup --python scripts/benchmarks/score_recreations.py
```

The fetch is the only one that needs the network. The rest are
Blender, because the measures read the images through Blender's own
loader and the sets are PNGs it has to decode.

**The writing and the measuring are separate processes, and that
matters.** Measuring inside the writing process reads the recreation
into Blender, and the next write's read inherits that datablock - so
every file after the first came out as the first one's pattern.
Measured: ten files, all 467876 bytes, all the same hash, the same
seam for every one. The lane was never broken; the measurement was.

## What it is for

The per-material reading is where the work is. The metals are the
worst, because a description says "aged, black, brown, oxidized,
steel" and the palette reads "black" and the pattern reads pieces -
and neither is what a steel plate is. Every material's own numbers
are on disk with the sets, so the next thing to fix is measurable
rather than guessed.
