"""A description naming a base and an overlay composes its own layered set."""

from __future__ import annotations

from golem_blender.pbr.layered_set import compose_from_description


def _layers(description: str):
    base, layers = compose_from_description({"description": description})
    return base, [layer["description"] for layer in layers], layers


def test_a_mossy_rock_is_a_grey_rock_with_moss_on_it():
    """The truths' Rock063 and Rock064 are grey rock with moss in the
    hollows; one pattern drew them uniform olive - "green" tinted every
    stone - so the moss and its colour leave the rock's own words."""
    base, names, _ = _layers("gray, green, mossy, natural, rock, rough")
    assert any("moss" in name for name in names)
    assert "green" not in base["description"] and "mossy" not in base["description"]
    assert base["kind"] == "rock"


def test_a_moss_is_itself_and_rust_on_stone_is_not_composed():
    """A moss's overlay is the material itself, and rust is laid only on a
    metal."""
    assert _layers("green, moss, mossy")[1] == []
    assert _layers("damp, grass, ground, moss, overgrown")[1] == []
    assert _layers("rusty, stone, wall")[1] == []


def test_rust_is_heavy_on_a_rusted_metal_and_faint_on_a_polished_one():
    """The truth's Metal053C ("damaged, iron, rusted") is half rust; its
    Metal063 says "rust, rusty" of a polished steel with faint stains."""
    _, names, heavy = _layers("damaged, iron, metal, old, rusted")
    _, _, light = _layers("glossy, metal, polished, rust, rusty, smooth")
    assert any("rust" in name for name in names)
    assert (
        heavy[0]["mask"]["noise"]["coverage"]
        > 2 * light[0]["mask"]["noise"]["coverage"]
    )
    assert heavy[0]["amount"] > light[0]["amount"]


def test_a_height_range_is_only_used_on_three_or_more_truths():
    """A kind's displacement range is a measurement of the KIND, so it is
    fitted only when there are enough truths to say something about the
    kind and not about the two assets that happen to be in it.

    The counts live beside the ranges so the threshold is enforced rather
    than described: a range whose count is below the minimum is not used,
    and every fitted kind's count is at or above it.
    """
    from golem_blender.pbr import layered_set

    minimum = layered_set.HEIGHT_RANGE_MINIMUM_TRUTHS
    ranges = layered_set.KIND_HEIGHT_RANGE
    counts = layered_set.KIND_HEIGHT_RANGE_TRUTHS
    assert set(ranges) == set(counts), (
        "every fitted range must say how many truths it was measured over: "
        f"{set(ranges) ^ set(counts)} is missing one"
    )
    for kind, count in counts.items():
        assert count >= minimum, (
            f"{kind}'s range was fitted on {count} truths, under the minimum "
            f"of {minimum}"
        )
        assert layered_set.height_range_is_measured(kind), kind
        assert layered_set.height_range_for(kind) == ranges[kind]

    # A kind that is not fitted keeps 0..1 and says so.
    for kind in ("bark", "knit", "moss", "voronoi", "wallpaper", "banded", "fan"):
        assert kind not in ranges, f"{kind} has too few truths to be fitted"
        assert layered_set.height_range_for(kind) == (0.0, 1.0)
        assert not layered_set.height_range_is_measured(kind)
    assert layered_set.height_range_for("a kind nobody ever measured") == (0.0, 1.0)


def test_a_metals_height_range_is_narrower_than_a_rocks():
    """The truths' own displacement maps: a metal's spans 0.135 at the
    median and a rock's 0.757.

    A range that named the wrong way round would write a steel sheet with
    a rubble's depth - the defect this table exists to prevent - so the
    ORDER is asserted and not just the presence.
    """
    from golem_blender.pbr import layered_set

    metal_low, metal_high = layered_set.height_range_for("metal")
    rock_low, rock_high = layered_set.height_range_for("rock")
    asphalt_low, asphalt_high = layered_set.height_range_for("asphalt")
    scattered_low, scattered_high = layered_set.height_range_for("scattered")
    assert (metal_high - metal_low) < (asphalt_high - asphalt_low)
    assert (asphalt_high - asphalt_low) < (scattered_high - scattered_low)
    assert (scattered_high - scattered_low) < (rock_high - rock_low)
