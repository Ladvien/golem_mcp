"""Build, wipe, rebuild: the same parameters must hash the same.

This is the cheap tier of the reproducibility gate — a tripwire, not
the pin. It cannot catch process-global state that survives a scene
wipe (a seeded RNG, a cached module, an operator preference), which is
why `scripts/rebuild_twice.py` runs the authoritative comparison in two
fresh Blenders under different `PYTHONHASHSEED`.

The assertion order matters: components first, so a failure names the
drifted datablock, and only then the overall hash. Asserting `overall`
first would report "not identical" and leave the reader to find out
what moved.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

BUILDER_NAMES = ("barrel", "crate", "pallet")


def _build(builder_name: str):
    """One build of the named builder with DEFAULT parameters."""
    from blended.builders import (
        BarrelBuilder,
        BarrelParameters,
        CrateBuilder,
        CrateParameters,
        PalletBuilder,
        PalletParameters,
    )

    pairs = {
        "barrel": (BarrelBuilder, BarrelParameters),
        "crate": (CrateBuilder, CrateParameters),
        "pallet": (PalletBuilder, PalletParameters),
    }
    builder_class, parameters_class = pairs[builder_name]
    return builder_class(parameters_class()).build()


@pytest.mark.parametrize("builder_name", BUILDER_NAMES)
def test_rebuilding_after_a_reset_reproduces_the_digest(builder_name):
    from blended.evaluate.digest import compare_digests, object_digest
    from blended.reset import reset_scene

    reset_scene()
    first_digest = object_digest(_build(builder_name))

    reset_scene()
    second_digest = object_digest(_build(builder_name))

    assert compare_digests(first_digest, second_digest) == []
    assert first_digest["overall"] == second_digest["overall"]


@pytest.mark.parametrize("builder_name", BUILDER_NAMES)
def test_a_changed_parameter_changes_the_digest(builder_name):
    """A digest that cannot see a real change is not a gate.

    One extra bevel segment / profile ring / deck board is the smallest
    change a builder can make, and it must move the mesh component
    without moving the transform component.
    """
    import dataclasses

    from blended.evaluate.digest import object_digest
    from blended.reset import reset_scene

    reset_scene()
    baseline_object = _build(builder_name)
    baseline = object_digest(baseline_object)
    baseline_name = baseline_object.name

    count_fields = {
        "barrel": "ring_count",
        "crate": "bevel_segment_count",
        "pallet": "deck_board_count",
    }
    from blended.builders import (
        BarrelBuilder,
        BarrelParameters,
        CrateBuilder,
        CrateParameters,
        PalletBuilder,
        PalletParameters,
    )

    pairs = {
        "barrel": (BarrelBuilder, BarrelParameters),
        "crate": (CrateBuilder, CrateParameters),
        "pallet": (PalletBuilder, PalletParameters),
    }
    builder_class, parameters_class = pairs[builder_name]
    field_name = count_fields[builder_name]
    parameters = parameters_class()
    changed = dataclasses.replace(
        parameters, **{field_name: getattr(parameters, field_name) + 1}
    )

    reset_scene()
    changed_digest = object_digest(builder_class(changed).build())

    assert (
        changed_digest["components"][f"mesh:{baseline_name}"]
        != baseline["components"][f"mesh:{baseline_name}"]
    ), f"{field_name} + 1 did not move the mesh digest"
    assert (
        changed_digest["components"][f"transform:{baseline_name}"]
        == baseline["components"][f"transform:{baseline_name}"]
    ), "a count change moved the transform: the components are not separable"


@pytest.mark.parametrize("builder_name", BUILDER_NAMES)
def test_digest_has_non_empty_components(builder_name):
    """An empty scene has 0 components and compare_digests returns [],
    so two children that both crashed identically would read as
    reproducible. This floor ensures a build actually left something.

    One-line edit that reddens it: replace ``_build(builder_name)`` with
    ``None`` — object_digest(None) would raise, but if the build path is
    stubbed to return an empty scene, the assert below fails.
    """
    from blended.evaluate.digest import object_digest
    from blended.reset import reset_scene

    reset_scene()
    digest = object_digest(_build(builder_name))

    assert digest["components"], (
        f"{builder_name} produced an empty digest — the build left nothing"
    )
