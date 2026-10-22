"""Layered materials: whole materials composed under masks.

A layer is one material where its mask lies - green AND rough AND
raised where the moss is - and a composite of tileable materials under
periodic masks must tile.
"""

from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy", reason="the layer module is NumPy")

from golem_blender.pbr import layers

RESOLUTION = 128


def _maps(rgb, roughness, metallic, height):
    shape = (RESOLUTION, RESOLUTION)
    return layers.MaterialMaps(
        albedo=numpy.broadcast_to(numpy.array(rgb, dtype=float), shape + (3,)).copy(),
        roughness=roughness,
        metallic=metallic,
        height=numpy.full(shape, height) if numpy.ndim(height) == 0 else height,
    )


@pytest.mark.parametrize("coverage", [0.1, 0.35, 0.7])
def test_a_noise_mask_covers_the_share_it_is_asked_for(coverage):
    mask = layers.noise_mask(
        RESOLUTION, cells=6, coverage=coverage, softness=0.02, seed=3
    )
    covered = float((mask > 0.5).mean())
    assert covered == pytest.approx(coverage, abs=0.03)


def test_every_channel_follows_the_mask():
    """Where the mask is one the surface IS the layer, where it is zero the base."""
    base = _maps((0.5, 0.4, 0.3), roughness=0.4, metallic=1.0, height=0.2)
    moss = _maps((0.1, 0.5, 0.1), roughness=0.9, metallic=0.0, height=0.0)
    mask = numpy.zeros((RESOLUTION, RESOLUTION))
    mask[:, : RESOLUTION // 2] = 1.0
    out = layers.composite(base, [layers.Layer(maps=moss, mask=mask, thickness=0.1)])
    covered, bare = (slice(None), slice(0, 10)), (slice(None), slice(-10, None))
    assert numpy.allclose(out.albedo[covered], (0.1, 0.5, 0.1))
    assert numpy.allclose(out.roughness[covered], 0.9)
    assert numpy.allclose(out.metallic[covered], 0.0)
    assert float(out.height[covered].min()) > 0.2
    assert numpy.allclose(out.albedo[bare], (0.5, 0.4, 0.3))
    assert numpy.allclose(out.metallic[bare], 1.0)
    assert numpy.allclose(out.height[bare], 0.2)


def test_a_composite_of_periodic_masks_tiles():
    """The edge's own step is no bigger than the interior's ordinary steps."""
    height = layers.noise_mask(RESOLUTION, cells=4, coverage=0.5, softness=1.0, seed=1)
    base = _maps((0.6, 0.6, 0.6), roughness=0.5, metallic=0.0, height=height)
    rust = _maps((0.5, 0.2, 0.1), roughness=0.9, metallic=0.0, height=0.0)
    mask = layers.combine_masks(
        layers.cavity_mask(height, radius_px=6),
        layers.noise_mask(RESOLUTION, cells=5, coverage=0.4, softness=0.3, seed=2),
        mode="max",
    )
    out = layers.composite(base, [layers.Layer(maps=rust, mask=mask)])
    luma = out.albedo.mean(axis=2)
    seam = float(numpy.abs(luma[:, 0] - luma[:, -1]).mean())
    interior = numpy.abs(numpy.diff(luma, axis=1)).mean(axis=0)
    assert seam <= float(numpy.percentile(interior, 95)) * 1.5


def test_a_low_height_mask_lies_in_the_hollows():
    height = numpy.tile(numpy.linspace(0.0, 1.0, RESOLUTION), (RESOLUTION, 1))
    mask = layers.height_mask(height, level=0.3, softness=0.05, below=True)
    assert float(mask[:, 5].mean()) > 0.95
    assert float(mask[:, -5].mean()) < 0.05


def test_masks_combine_as_all_or_any():
    a = numpy.array([[1.0, 0.0], [1.0, 0.0]])
    b = numpy.array([[1.0, 1.0], [0.0, 0.0]])
    assert numpy.array_equal(layers.combine_masks(a, b), [[1.0, 0.0], [0.0, 0.0]])
    assert numpy.array_equal(
        layers.combine_masks(a, b, mode="max"), [[1.0, 1.0], [1.0, 0.0]]
    )
    with pytest.raises(ValueError, match="Unknown mask mode"):
        layers.combine_masks(a, b, mode="screen")


def test_a_mask_of_the_wrong_size_is_refused():
    base = _maps((0.5, 0.5, 0.5), roughness=0.5, metallic=0.0, height=0.0)
    with pytest.raises(ValueError, match="mask"):
        layers.composite(
            base, [layers.Layer(maps=base, mask=numpy.ones((RESOLUTION, 3)))]
        )
