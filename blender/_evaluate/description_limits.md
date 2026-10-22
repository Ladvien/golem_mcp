# What the description can and cannot say

The lane recreates a material from its OWN WORDS - the tags
ambientcg gives it, which are what a person would write to describe
the surface. The score measures how close the recreation is to the
truth.

Some of the gap is the lane's fault and it is fixable. Some of it is
not, and this records which is which - because a gap that is
inherent is not a bug to be fixed and a gap that is inherent
*pretended* to be a bug is a lie in the score.

## The limits the truth set itself shows

### Two materials with the same words and different colours

The wide set's own WoodFloor040 and Planks037A have the same
description - "floor, parquet, planks, wood" - and they measure
0.556 and 0.252.

A word's value is the MEAN over the materials that name it, so a
description that names four materials whose brightnesses span
0.23 to 0.56 cannot say which one it means. The best the lane can
do is the mean, and the mean is wrong by a factor of two for one of
them.

The same holds for the LEATHERS: the six of them measure 0.098 to
0.800 and their spreads 0.0031 to 0.0630 - a twentyfold range -
and they share the words "brown, dark, leather".

So a material's own properties vary far more than its words
describe, and the words are a lossy channel. The lane's job is to
get the STRUCTURE right and the brightness as close as the words
allow.

### The specificity is the only lever

"beige" names fourteen materials in the wide set and their lumas
run from 0.360 to 0.798 - so its value is a mean of nothing in
particular. And "espresso" names ONE - a dark hardwood floor at
0.214 - and it says exactly how dark.

So a colour word's SPECIFICITY decides: the words that name few
materials win, and the general ones are the fallback. That is
worth a factor of two on a wood floor, and it is free.

### The material's KIND and the colour are different channels

A "fabric" on its own says a thing's kind and not its colour, and
the truth's fabrics are 0.242 and 0.536 - the orange one and the
blue one. So a generic material lets the colour decide.

And the most specific MATERIAL decides: a carpet is a carpet and
not a fabric, and the lane's kind for a carpet took a fabric's
colour and came out a saturated orange.

## What the lane fixes and what it cannot

| the gap | whose fault | fixable |
|---|---|---|
| the gravel's stones were a plate of cracked mud | the lane | yes - the stone's size and count are measured |
| the contrast correction moved the brightness | the lane | yes - the scaling is about the image's own mean |
| the noise's hash was a sine of a large number | the lane | yes - it is an integer mix now |
| the domain's samples missed the wrap | the lane | yes - the samples are `i / N` |
| a fabric came out as a field of pebbles | the lane | yes - a fabric is a weave |
| a metal came out banded | the lane | yes - a sheet is banded only when it was rolled |
| a wallpaper's design came out as a chessboard | the lane | yes - a design is a fleck |
| a road with markings came out with no markings | the lane | yes - the markings are geometry |
| a parquet's grain ran across the board | the lane | yes - the lattice's axes were the wrong way round |
| a leather's crackle was nine pixels wide | the lane | yes - the truth's is two |
| a brick's face was flat and a tile's was a chequerboard | the lane | yes - a brick is worked and a tile is glazed |
| the extreme words lost to the material's word | the lane | yes - the kind says nothing about the lightness |
| the spread read the tiers in order and a roof was a tile | the lane | yes - the most specific word wins |
| a wood floor's brightness is a factor of two out | the WORDS | no |
| a leather's spread is a factor of ten out | the WORDS | no |
| a road's paint colour is the road's own and not the paint's | the WORDS | partly - the wear is a guess |

### A rock's moss is a patch, and the patch's colour is a second hue

The truth's own Rock064 is a grey rock with green MOSS on it, and
its green share has a standard deviation of 0.0336 over
sixteen-pixel blocks - the moss is a patch, and the patch is a
different hue from the rock.

The lane draws one hue over the whole surface, and a rock's own hue
is the grey: the words say "gray" and "stone" and "moss" and
"mossy", and the moss is a minority of the surface. So a rock's
cells carry their own hue and only some of them carry the moss -
and a cell with a full hue swing on every cell gave a green and a
tan patchwork instead.

What is still wrong: the truth's rock is rough at EVERY scale - its
gradient's median is 0.0362 and only one and a half per cent of its
surface is flat, where the lane's rock is flat over fifty-four per
cent. The lane's rock is a set of flat facets with thin joints and
the truth's is a continuous relief. The truth's spectrum falls as k
to the minus two and the lane's matches it, so the energy is in the
right places; it is the *shape* of the surface that differs, and a
facet-and-joint mosaic is not a relief.

### The ground's two scales, and the slow one cannot be pinned

A ground has TWO scales: the slow variation at the surface's own
scale and the stones at theirs, and they are far apart. Measured on
the truth's own: the truth's Ground110's slow field decorrelates at
112 pixels and its stones at sixteen - a ratio of seven - and the
truth's Ground106's at 243 and seventeen, a ratio of fourteen.

The lane's stones decorrelated at thirty-six pixels, because at
random a Poisson field has a hole in it as often as it has a pair,
and the stones came in clumps. So the stones are on a JITTERED
LATTICE, and the jitter is about each cell's own centre - a jitter
from the corner makes the first cell of a row nine tenths of the
lattice wide and the last one a tenth, and the wrap joins a wide
cell to a narrow one.

And the stones' own size is a CONSTANT: the truth's eight grounds
all have a stone scale of twelve to twenty pixels, whatever their
feature count.

What the words cannot say is the SLOW scale's own value: the
truth's slow fields run from 101 to 243 pixels across eight grounds,
and their correlation with the feature count is only 0.57 - so the
lane's is a constant 142, which is the middle of the truth's range
and the best a single number can do.

### A brick's face is sand, and the sand is per-pixel

The truth's own Bricks113A has a face that is GRIT: its correlation
falls steadily from +0.391 at a one-pixel lag to +0.086 at a
thirty-two, with no dominant scale and no direction.

The lane's face was a DOMAIN-WARPED field, and a warp has a
DIRECTION - so every brick carried the same diagonal herringbone and
the wall came out as a field of chevrons.

A per-pixel random field was tried for the sand and it changed
nothing: the face's correlation at a one-pixel lag stayed at 0.223
whatever the field. So the sand is not what the measure reads, and
the Perlin's own fine octave is.

And the face's grain rides the course's own offset, and the offset
must be REDUCED into the course count: the index at the last course
is not the index at the first, and the wrap joined two courses with
different grain - the brick's horizontal seam read 1.875x, as big
as the biggest feature.

### A field's period must be a whole number of cells

A value-noise's period is its lattice's size, and a STRETCH that is
a factor on the *sample* makes the period a fraction of a cell - and
a fraction of a cell is not a whole cell, so the field does not wrap.

The metal's grain was stretched by a quarter, and its own wrap read
0.136 against its spread of 0.132: it did not wrap at all. The
corrugated steel's seam read 6.52 against the truth's 0.35 - nineteen
times - and it reads 0.45 now.

The stretch is the lattice's own SIZE now, so the period is a whole
number of cells and the wrap joins two whole ones.

The same holds for the ribs' count, which was the cells times eleven,
and for the envelope's lattice, and for the scratches' cells: a
count that does not divide the resolution leaves a fraction of a
cell at the edge, and the wrap joins it to a whole one.

### The value cannot be refitted honestly

The palette's material values are a fit against the truth's own
eighty-seven, and every word's value is the mean of the materials
that name it. A refit of that table on the same eighty-seven gives
a mean error of 0.0594 against 0.0716 - and a **leave-one-out**
refit, which drops each material from its own word's mean before
measuring it, gives 0.0870: WORSE than the table it refits.

So the table is not under-fitted; the WORDS are the limit. A
description that names a material whose own brightness spans 0.23 to
0.56 cannot say which one it means, and no refit of the same words
can fix it.

The one thing the words CAN say is the extreme: "black", "white",
"dark" and "light" are about the lightness and about nothing else,
and the truth's own Rock035 is a "black, cave, cliff, grey, rock,
stone" at a luma of 0.094 while the material's word said 0.362. So
the extreme words are read first - and that is a fact about the
words, not a fit.

### A word that names FEW materials can still disagree with itself

"granular" names two materials in the wide set and the two disagree:
the truth's own Asphalt033 at a spread of 0.0178 and its Gravel043
at 0.0856. So the word's own materials must AGREE for the word to
be trusted, and an unreliable modifier loses to the material's own
word beside it.

## The honest summary

The wide set's mean ratios - brightness, contrast, scale and seam -
are the lane's score. They are measured on eighty-seven real
materials, and every number in them is reproducible with
`scripts/benchmarks/recreate_from_descriptions.py` and
`scripts/benchmarks/score_recreations.py`.

Where a material's words cannot say what it looks like, the score
says so - and the fix is a better description, not a better
pattern.
