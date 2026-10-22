# Round 7: what the pictures say, and the plan it forces

The score says how close a recreation is. The sheet says whether it
*is* the material. Both were run against the twenty hand-picked
ambientcg sets; the wide seventy-set sample is in `coverage_audit.md`
and it is the honest baseline.

## The score

| | before | after the wrap fix |
|---|---|---|
| mean brightness ratio | 0.95x | 1.03x |
| mean contrast ratio | 1.03x | 1.03x |
| mean scale ratio | 1.57x | 1.62x |
| **mean seam** | **3.87x** | **0.47x** |

The seam was the one real bug and it is fixed: the splatter drew
each stone at only its own centre, so a stone at the edge was cut in
half and the two halves did not match. It now draws each stone at all
nine wrapped positions. Measured, the scattered ground's seam fell
from 23.73x the truth's to 0.37x.

## The picture: three defects the score cannot see

### 1. The scattered ground's stones are too big and too white

The truth's gravel, in numbers measured from its own pixels:

| | truth | ours |
|---|---|---|
| the bright stones' luma | 0.547 | 0.722 |
| the dark matrix's luma | 0.242 | 0.397 |
| the stones' share of the surface | 29% | 27% |
| the median bright run along a row | 4 px | 24 px |
| the bright structure that survives a 16 px blur | 19% | 32% |

The stones are **six times too wide** and **0.18 too bright**, and
the matrix is 0.15 too bright. The truth's gravel is a fine gravel
seen from close up: hundreds of small stones in a dark matrix.

The cause is a number, not a shape: `STONE_SCATTER_SIZE` is 0.0130
of the surface, which at 2048 px is a 27 px stone. The truth's stones
are 4 px of a 1024 px surface, or 0.004 of it.

### 2. The brick's face is flat

The truth's bricks carry their own surface - a swirl, a scratch, a
stain - and the truth's mortar is **pale** (RGB 0.657 0.619 0.555,
which is 0.17 *lighter* than the bricks' own 0.459). Ours is a dark
grout line, so a brick reads as a coloured rectangle.

Measured on the truth's own bricks: the pale mortar is 1% of the
surface, the bricks' own tones span 0.533 to 0.609, and the truth's
structure that survives a 16 px blur is 11% - ours is 25%, so ours
carries contrast at the wrong scale.

### 3. The gravel is one scale where the truth is two

The truth's gravel has a **coarse** structure (the drift of the
whole patch, ~50 px) *and* a **fine** one (the stones themselves,
4 px). Ours has one scale: the stones, at 25 px. The truth's
autocorrelation decays to a quarter by 40 px and stays there; ours
decays to a quarter by 60 px and stays there too - the same *shape*,
three times too coarse.

The fix is the same as defect 1, and it is the *slow* variation: the
slow field must be at the **surface's** scale, and the stones at
their own.

## The plan

1. **The stone's size** - from the truth's own measurement, not from
   a constant. The stone's width is a fraction of the surface, and
   the truth's gravel carries 256 stones across a row where ours
   carries 82.
2. **The stone's tone** - the truth's stones are 0.547 and the
   matrix 0.242, so the stone's tone is a *fixed fraction of the
   surface's spread above the matrix*, and the matrix is the
   surface's own slow variation.
3. **The brick's face** - the mortar is PALE and not dark, and the
   brick's own face carries a surface. The pale mortar is measured
   from the truth's own pixels: the brightest 1% of the surface.
4. **The two scales** - the slow variation is at the surface's
   measured feature scale, and the stones at theirs.

## And after that

The wide seventy-set run, and the four kinds the coverage audit says
are missing: **leather** (a fine even pebbled grain), **carpet** (a
directional pile), **parquet** (blocks in a pattern) and
**wallpaper** (a flat sheet with a printed design).
