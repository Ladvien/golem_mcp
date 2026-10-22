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
