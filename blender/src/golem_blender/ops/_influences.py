"""The one number that decides how many bones can move a vertex.

glTF stores a vertex's influences in `JOINTS_0` and `WEIGHTS_0`, and both
are VEC4: four 16-bit joint indices and four normalised weights. A fifth
influence has nowhere to go in the file, so the engine silently drops it —
and a vertex whose four kept weights do not sum to 1 is scaled by whatever
they do sum to, which pulls the vertex toward the origin.

The constant lives here, numpy-free, because two audiences need it and
neither may import the other: `ops/_skinned.py` (the skinclip adapter) and
`ops/weight_transfer.py` (the RSWT port), which is imported at module level
by the facade — and the facade must import with no numpy present.
"""

from __future__ import annotations

MAXIMUM_INFLUENCES_PER_VERTEX = 4
