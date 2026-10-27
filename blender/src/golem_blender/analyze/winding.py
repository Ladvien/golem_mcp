"""Which way a surface faces, decided by the solid it bounds — not by a normal's agreement with a neighbour.

Why a new measure: `MeshReport.flipped_normal_triangle_count` counts triangles
whose face normal disagrees with its own vertex normals, which finds a
DECIMATION that folded a surface but never finds a whole shell that was
built inside out: every normal agrees with every other and the shell is
still backwards, so the exporter's back-face culling deletes the model in
the engine while the viewport shows it. Signed volume catches that on a
CLOSED mesh only, and the garment that started this — an open tube of
quads — has no volume to sign.

The generalized winding number (Jacobson, Kavan and Sorkine-Hornung 2013,
"Robust Inside-Outside Segmentation using Generalized Winding Numbers",
DOI 10.1145/2461912.2461916) answers it for open surfaces too. The winding
number of a point p is the signed solid angle the surface subtends there,
divided by 4π: +1 inside a correctly oriented closed shell, 0 outside, and
1/2 on a lone plane. Its own face contributes ±1/2 just either side of a
plane, so the sum of the winding numbers measured at a face's centroid
from both sides is exactly twice the OTHER faces' winding there — and
that half-difference, with the face's own contribution removed, is what
each face's orientation score reads. No ε offset is needed, which is the
reason this works where "sample a point just off the surface" does not.

The solid angle of one triangle is Van Oosterom and Strackee's (1983,
DOI 10.1109/TBME.1983.325207):

    Ω = 2·atan2(a·(b×c), |a||b||c| + (a·b)|c| + (a·c)|b| + (b·c)|a|)

The same quantity is what `analyze/occluders.py` signs a ray hit by, so a
render and this audit agree about which way a face points.

numpy INSIDE the functions, like `analyze/enclosure.py`: Blender's Python
ships numpy and the dev venv does not, so this module must import in the
pure test tier with no numpy present.
"""

from __future__ import annotations

import math

# A triangle whose three corners and the query point are coplanar has NO
# solid angle. atan2's numerator is exactly zero there, but a point
# coplanar with the triangle's PLANE yet outside the triangle reads a
# non-zero triple product by rounding and would be summed as 2π. The test
# is relative: |a·(b×c)| against 1e-12 of the three lengths' product, so it
# scales with the triangle and does not depend on metres.
COPLANAR_TRIPLE_PRODUCT_EPSILON = 1.0e-12

FULL_TURN_STERADIANS = 4.0 * math.pi

# A face is called outward above this score and inward below its negative.
# The score of a face on a correct closed shell is 1 (measured on a cube:
# 1.000000 to 1e-6), of one on an inverted shell -1, and of a lone plane 0.
# Faces between are UNDECIDED, not guessed: an open shell's rim face reads
# between the two because half its neighbourhood is missing, and calling
# it by a round number would be an invented answer.
#
# Measured 2026-10-27 in Blender 5.2's Python by `tests/blender/test_winding.py`
# on open tubes (the garment case, where half the neighbourhood is missing):
#
#   32-sided, 8 rings: rim faces score 0.5714, middle ring 0.7961
#   12-sided, 2 rings: 0.7241 .. 0.8147
#    4-sided, 1 ring:  0.8541 (every face)
#
# Coarser is not worse, which is why the rim is the floor: the missing half
# of a rim face's neighbourhood costs a fixed 0.4-ish regardless of side
# count. The margin therefore sits 5.7x under the worst correct face, so a
# correct garment is never called undecided, while a lone plane (0.0) and a
# face wrapped in less than a fifth of a surface stay undecided.
WINDING_DECISION_MARGIN = 0.1

# Query faces are processed in blocks of this many (face, triangle) pairs,
# so the (Q, T) solid-angle block never materialises whole: a 4096-face
# audit of a 50 000-triangle mesh would otherwise allocate 1.6 GB of
# float64. The gate measures 256 faces of up to 50 000 triangles, and 4e6
# pairs at 8 bytes each is 32 MB per block.
WINDING_CHUNK_PAIR_COUNT = 4_000_000

OUTWARD = 1
UNDECIDED = 0
INWARD = -1


def triangle_solid_angles(query_points, corners):
    """Signed solid angle in steradians of every triangle, seen from every query point.

    `query_points` is (Q, 3) metres, `corners` is (T, 3, 3) metres — the
    three corners of each triangle in its face winding, which is what
    signs the result. Returns (Q, T) float64.

    A coplanar triple contributes exactly 0 rather than 2π: `atan2(y, x)`
    with y = 0 and x < 0 is π, which is the failure mode this guard exists
    for (a point on a triangle's plane but outside it would otherwise be
    summed as a full turn).
    """
    import numpy as np

    query_points = np.asarray(query_points, dtype=float)
    corners = np.asarray(corners, dtype=float)
    if corners.ndim != 3 or corners.shape[1:] != (3, 3):
        raise ValueError(f"corners must be (T, 3, 3), got {corners.shape}")
    if query_points.ndim != 2 or query_points.shape[1] != 3:
        raise ValueError(f"query_points must be (Q, 3), got {query_points.shape}")

    a = corners[None, :, 0, :] - query_points[:, None, :]
    b = corners[None, :, 1, :] - query_points[:, None, :]
    c = corners[None, :, 2, :] - query_points[:, None, :]

    length_a = np.linalg.norm(a, axis=-1)
    length_b = np.linalg.norm(b, axis=-1)
    length_c = np.linalg.norm(c, axis=-1)

    numerator = np.einsum("qtk,qtk->qt", a, np.cross(b, c))
    denominator = (
        length_a * length_b * length_c
        + np.einsum("qtk,qtk->qt", a, b) * length_c
        + np.einsum("qtk,qtk->qt", a, c) * length_b
        + np.einsum("qtk,qtk->qt", b, c) * length_a
    )
    angles = 2.0 * np.arctan2(numerator, denominator)
    coplanar = np.abs(numerator) <= (
        COPLANAR_TRIPLE_PRODUCT_EPSILON * length_a * length_b * length_c
    )
    return np.where(coplanar, 0.0, angles)


def face_orientation_scores(corners, query_face_indices):
    """Orientation score per queried face: +1 outward, −1 inward, 0 undecided.

    `corners` is (T, 3, 3) metres in world space, `query_face_indices` are
    indices into it. For each query face q with centroid p:

        s_q = 2 · Σ_{t ≠ q} Ω_t(p) / 4π

    Why doubling: the summed solid angle of a CLOSED shell measured at a
    point ON its surface is half a sphere, i.e. 2π, not 4π — the surface is
    a hemisphere from there. The own face contributes the missing 2π (it
    is exactly at the point), and its sign depends on which side you
    measure from (+2π from behind, −2π from in front), so the own entry is
    zeroed explicitly and the rest doubled: the answer is then the same
    from both sides and needs no offset ε. The zeroing is explicit rather
    than left to `triangle_solid_angles`'s coplanarity guard, which returns
    0 for exactly the same entries — if that guard ever moved, a sum that
    inherited the own face would read 2 or 0 instead of ±1.

    The queries are processed in blocks of `WINDING_CHUNK_PAIR_COUNT` pairs.
    """
    import numpy as np

    corners = np.asarray(corners, dtype=float)
    query_face_indices = np.asarray(query_face_indices, dtype=np.int64)
    if corners.ndim != 3 or corners.shape[1:] != (3, 3):
        raise ValueError(f"corners must be (T, 3, 3), got {corners.shape}")
    if query_face_indices.size == 0:
        return np.zeros(0, dtype=float)

    triangle_count = len(corners)
    query_count = len(query_face_indices)
    centroids = corners.mean(axis=1)
    scores = np.zeros(query_count, dtype=float)
    block = max(1, WINDING_CHUNK_PAIR_COUNT // max(1, triangle_count))
    for start in range(0, query_count, block):
        stop = min(start + block, query_count)
        block_indices = query_face_indices[start:stop]
        angles = triangle_solid_angles(centroids[block_indices], corners)
        angles[np.arange(stop - start), block_indices] = 0.0
        scores[start:stop] = 2.0 * angles.sum(axis=1) / FULL_TURN_STERADIANS
    return scores


def classify_faces(scores):
    """Per face: +1 outward, −1 inward, 0 undecided — at `WINDING_DECISION_MARGIN`."""
    import numpy as np

    scores = np.asarray(scores, dtype=float)
    classified = np.full(scores.shape, UNDECIDED, dtype=np.int8)
    classified[scores > WINDING_DECISION_MARGIN] = OUTWARD
    classified[scores < -WINDING_DECISION_MARGIN] = INWARD
    return classified


def triangle_areas(corners):
    """Area in m² of every triangle, from its three corners."""
    import numpy as np

    corners = np.asarray(corners, dtype=float)
    return 0.5 * np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]),
        axis=-1,
    )


def area_weighted_fractions(corners, classified):
    """Outward/inward/undecided fractions of the total area, over a classified face set."""
    import numpy as np

    classified = np.asarray(classified)
    areas = triangle_areas(corners)
    total = float(areas.sum())
    if total <= 0.0:
        return {
            "outward_area_fraction": 0.0,
            "inward_area_fraction": 0.0,
            "undecided_area_fraction": 0.0,
        }
    return {
        "outward_area_fraction": float(areas[classified == OUTWARD].sum() / total),
        "inward_area_fraction": float(areas[classified == INWARD].sum() / total),
        "undecided_area_fraction": float(areas[classified == UNDECIDED].sum() / total),
    }


def query_face_sample(triangle_count: int, limit: int):
    """Evenly spread at most `limit` face indices over a mesh of `triangle_count` triangles.

    Even spacing, not the first `limit`: the first faces of a lathe-built
    mesh are one ring, and a sample of one ring is a sample of one ring's
    winding.
    """
    import numpy as np

    if triangle_count <= 0:
        return np.zeros(0, dtype=np.int64)
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    return np.unique(
        np.linspace(0, triangle_count - 1, min(triangle_count, limit))
        .round()
        .astype(np.int64)
    )


def triangle_components(triangles):
    """Component index per triangle, over the connected components of shared vertices."""
    import numpy as np

    triangles = np.asarray(triangles, dtype=np.int64)
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise ValueError(f"triangles must be (T, 3), got {triangles.shape}")
    used_vertices = np.unique(triangles)
    if used_vertices.size == 0:
        return np.zeros(0, dtype=np.int64)
    dense = np.searchsorted(used_vertices, triangles)
    parent = list(range(int(dense.max()) + 1))

    def find(vertex: int) -> int:
        while parent[vertex] != vertex:
            parent[vertex] = parent[parent[vertex]]
            vertex = parent[vertex]
        return vertex

    for left, right, third in dense:
        root = find(int(left))
        for other in (int(right), int(third)):
            other_root = find(other)
            if other_root != root:
                parent[other_root] = root
    roots = np.array([find(int(dense[index, 0])) for index in range(len(dense))])
    _, component_of_root = np.unique(roots, return_inverse=True)
    return component_of_root.astype(np.int64)


def component_is_closed(triangles, mask) -> bool:
    """True when every undirected edge of the masked faces occurs exactly twice."""
    import numpy as np

    triangles = np.asarray(triangles, dtype=np.int64)[np.asarray(mask, dtype=bool)]
    if len(triangles) == 0:
        return False
    edges = np.sort(
        np.concatenate(
            [
                triangles[:, [0, 1]],
                triangles[:, [1, 2]],
                triangles[:, [2, 0]],
            ]
        ),
        axis=1,
    )
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def signed_volume_m3(corners) -> float:
    """Signed volume in m³ of a closed shell: Σ v0·(v1×v2)/6.

    Positive for outward-facing (counter-clockwise from outside) faces,
    negative for an inverted shell. Meaningless on an open surface — a
    garment tube has no enclosed volume, and its number is whatever the
    missing caps imply.
    """
    import numpy as np

    corners = np.asarray(corners, dtype=float)
    return float(
        np.einsum(
            "tk,tk->t", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])
        ).sum()
        / 6.0
    )
