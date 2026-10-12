"""The proportion-headroom math on hand-built clouds (2026-09-11).

The script's claim over real rolls — F@0.05 0.4531 -> 0.7017 under oracle
proportions, 0 floating components of 160 — is reproduced by re-running it
on the same eight model dirs; these tests pin the pieces that claim rests
on so a refactor cannot change what "oracle proportions" or "floating"
mean without turning red.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

# The bench scripts need numpy, scipy and trimesh, which never enter `.venv`
# (Blender, on Python 3.13, puts its site-packages first on sys.path).
# `make test-bench-scripts` runs this directory in a throwaway env that has them.

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bench_proportion_headroom import (
    axis_log2_errors,
    component_counts,
    extents_at_percentiles,
    oracle_rescaled,
)
from bench_thresholds import PROPORTION_EXTENT_PERCENTILES


class _Scorer:
    """The one scorer function the oracle needs, in the scorer's own words."""

    @staticmethod
    def normalize_unit_sphere(points):
        points = points - points.mean(axis=0)
        return points / np.linalg.norm(points, axis=1).max()


def _box_cloud(extents, n=4000, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.random((n, 3)) - 0.5) * np.asarray(extents, dtype=np.float64)


def test_extents_are_read_between_the_registered_percentiles():
    cloud = _box_cloud((2.0, 1.0, 0.5))
    cloud[0] = (50.0, 50.0, 50.0)  # one stray vertex must not set an axis
    extents = extents_at_percentiles(cloud)
    assert PROPORTION_EXTENT_PERCENTILES == (1.0, 99.0)
    assert np.allclose(extents, (2.0, 1.0, 0.5), rtol=0.05)


def test_oracle_rescale_gives_the_generated_cloud_the_reference_extents():
    reference = _Scorer.normalize_unit_sphere(_box_cloud((1.0, 3.0, 1.0)))  # tall jar
    generated = _Scorer.normalize_unit_sphere(
        _box_cloud((2.0, 3.0, 2.0))
    )  # 2x too wide
    rescaled = oracle_rescaled(_Scorer, reference, generated)
    ratio = extents_at_percentiles(rescaled) / extents_at_percentiles(reference)
    assert np.allclose(ratio, 1.0, rtol=0.05)


def test_axis_errors_are_ordered_by_the_reference_extent_and_in_log2():
    reference = _box_cloud((1.0, 3.0, 1.0))
    generated = _box_cloud((2.0, 3.0, 1.0))  # one axis 2x too wide
    largest, middle, smallest = axis_log2_errors(reference, generated)
    assert largest == pytest.approx(0.0, abs=0.1)  # the 3.0 axis is right
    assert middle == pytest.approx(1.0, abs=0.1)  # 2x on one of the 1.0 axes
    assert smallest == pytest.approx(0.0, abs=0.1)


def test_a_touching_pair_is_not_floating_and_a_detached_one_is():
    a = trimesh.creation.box(extents=(1, 1, 1))
    b = trimesh.creation.box(extents=(1, 1, 1))
    b.apply_translation((1.0, 0, 0))  # face to face
    touching = trimesh.util.concatenate([a, b])
    count, floating = component_counts(touching)
    assert (count, floating) == (2, 0)

    c = trimesh.creation.box(extents=(1, 1, 1))
    c.apply_translation((5.0, 0, 0))  # in the air
    detached = trimesh.util.concatenate([a, c])
    count, floating = component_counts(detached)
    assert (count, floating) == (2, 2)  # each touches nothing: both float
