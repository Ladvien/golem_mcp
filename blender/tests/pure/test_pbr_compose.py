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
