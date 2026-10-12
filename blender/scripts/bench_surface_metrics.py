"""The pose-normalised shape metrics, defined once.

`diagnose_3dcode.py` (every roll's per-instance JSON, which the panel
ranks on), `bench_fscore.py` (the per-threshold table and the reference
audit) and `shape_error_decompose.py` all need the same two things: the
best rigid alignment of a generated cloud onto its reference over the
24-rotation PCA frame, and F-score / precision / recall at a distance
threshold on the aligned clouds. Before OT-36 the alignment search was
written twice and F-score lived only in `bench_fscore.py`, so the panel
could not carry the axis the OT-33 pre-registration named. One module,
imported by all three.

Why F-score ranks: Tatarchenko, Richter, Ranftl, Li, Koltun & Brox, "What
Do Single-View 3D Reconstruction Networks Learn?", CVPR 2019
(DOI 10.1109/cvpr.2019.00352) — Chamfer distance and IoU are dominated
by category-level priors, F-score at a threshold is not. Precision is
"of the surface we made, how much belongs"; recall is "of the surface
that should be there, how much did we make".

Runs under the bench venv (numpy + scipy). The Chamfer itself is never
reimplemented: callers pass the scorer module (`shape_chamfer`) in, so
`cd_pca` is the scorer's own `chamfer_squared` under the best rotation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_thresholds import (  # the pre-registered rule
    FSCORE_THRESHOLDS,
    PRIMARY_FSCORE_THRESHOLD,
    metric_column,
)

__all__ = [
    "FSCORE_THRESHOLDS",
    "PRIMARY_FSCORE_THRESHOLD",
    "best_pca_alignment",
    "cd_pca",
    "fscore",
    "metric_column",
    "pca_frame",
    "signed_permutations",
    "surface_columns",
]


def signed_permutations():
    """All 48 signed permutation matrices (6 axis orders x 8 sign choices)."""
    out = []
    for perm in ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0)):
        for signs in (
            (1, 1, 1),
            (1, 1, -1),
            (1, -1, 1),
            (1, -1, -1),
            (-1, 1, 1),
            (-1, 1, -1),
            (-1, -1, 1),
            (-1, -1, -1),
        ):
            matrix = np.zeros((3, 3))
            for row, col in enumerate(perm):
                matrix[row, col] = signs[row]
            out.append(matrix)
    return out


PERMUTATIONS = signed_permutations()


def pca_frame(points):
    """Right singular vectors of the (centered) cloud, columns = axes."""
    _, _, vt = np.linalg.svd(points, full_matrices=False)
    return vt.T


def best_pca_alignment(sc, reference_points, generated_points):
    """(rotation, chamfer) of the best proper rotation mapping the
    generated cloud's PCA frame onto the reference's.

    Composes the two PCA frames with each of the 48 signed permutations,
    keeps the 24 results that are proper rotations, and takes the one
    with the smallest symmetric squared Chamfer, reusing the scorer's
    own `chamfer_squared`. The rotation is returned so F-score
    can be measured on the SAME aligned cloud cd_pca was measured on:
    the two metrics then answer the same question about the same pose.
    """
    reference_frame = pca_frame(reference_points)
    generated_frame = pca_frame(generated_points)
    best_rotation, best_distance = None, np.inf
    for permutation in PERMUTATIONS:
        rotation = reference_frame @ permutation @ generated_frame.T
        if np.linalg.det(rotation) <= 0.0:
            continue
        distance = sc.chamfer_squared(reference_points, generated_points @ rotation.T)
        if distance < best_distance:
            best_rotation, best_distance = rotation, distance
    return best_rotation, float(best_distance)


def cd_pca(sc, reference_points, generated_points) -> float:
    """Min symmetric squared chamfer over the 24-rotation PCA frame."""
    return best_pca_alignment(sc, reference_points, generated_points)[1]


def fscore(reference_points, generated_points, threshold):
    """(F, precision, recall) at `threshold`.

    Precision: the fraction of GENERATED points within `threshold` of the
    reference surface — surface we made that belongs. Recall: the
    fraction of REFERENCE points within `threshold` of ours — surface
    that should be there and is. Distances are Euclidean on clouds the
    scorer has already normalised to a unit sphere, so `threshold` reads
    as a fraction of the object's radius.
    """
    generated_to_reference, _ = cKDTree(reference_points).query(generated_points, k=1)
    reference_to_generated, _ = cKDTree(generated_points).query(reference_points, k=1)
    precision = float((generated_to_reference < threshold).mean())
    recall = float((reference_to_generated < threshold).mean())
    if precision + recall <= 0.0:
        return 0.0, precision, recall
    return 2.0 * precision * recall / (precision + recall), precision, recall


def surface_columns(
    reference_points, aligned_points, threshold=PRIMARY_FSCORE_THRESHOLD
) -> dict:
    """The three panel columns for one instance at one threshold, keyed
    the way every diagnose JSON row carries them (`fscore_005`, ...)."""
    value, precision, recall = fscore(reference_points, aligned_points, threshold)
    return {
        metric_column("fscore", threshold): value,
        metric_column("precision", threshold): precision,
        metric_column("recall", threshold): recall,
    }
