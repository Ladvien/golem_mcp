"""The first prop: a beveled crate.

Deliberately simple. Its job is to prove the whole loop — parameters ->
builder -> real geometry -> analyzer -> capture — not to be a good
crate. The Parameters/Builder split is the repo convention: parameters
are frozen, validated, bpy-free data; builders own the Blender objects
they create.
"""

from __future__ import annotations

from dataclasses import dataclass

# A bevel wider than a quarter of the smallest dimension starts eating
# the crate's silhouette and can self-intersect.
MAXIMUM_BEVEL_FRACTION_OF_SMALLEST_DIMENSION = 0.25


@dataclass(frozen=True)
class CrateParameters:
    """All dimensions in meters."""

    width_m: float = 0.8
    depth_m: float = 0.8
    height_m: float = 0.8
    bevel_width_m: float = 0.02
    bevel_segment_count: int = 2
    name: str = "Crate"

    def validate(self) -> None:
        smallest_dimension_m = min(self.width_m, self.depth_m, self.height_m)
        if smallest_dimension_m <= 0.0:
            raise ValueError("All crate dimensions must be positive.")
        if self.bevel_width_m < 0.0:
            raise ValueError("Bevel width must be non-negative.")
        maximum_bevel_m = (
            smallest_dimension_m * MAXIMUM_BEVEL_FRACTION_OF_SMALLEST_DIMENSION
        )
        if self.bevel_width_m > maximum_bevel_m:
            raise ValueError(
                f"Bevel width {self.bevel_width_m} m exceeds "
                f"{maximum_bevel_m:.4f} m "
                f"({MAXIMUM_BEVEL_FRACTION_OF_SMALLEST_DIMENSION:.0%} of the "
                f"smallest dimension)."
            )
        if self.bevel_segment_count < 1:
            raise ValueError("Bevel segment count must be at least 1.")


class CrateBuilder:
    def __init__(self, parameters: CrateParameters) -> None:
        parameters.validate()
        self.parameters = parameters
        self.created_object_names: list[str] = []

    def build(self):
        """Build the crate and return its Blender object, base at z=0."""
        import bpy

        from blended.ops import add_bevel, add_box, apply_all_modifiers, link_into_scene

        parameters = self.parameters
        crate_name = add_box(
            name=parameters.name,
            width_m=parameters.width_m,
            depth_m=parameters.depth_m,
            height_m=parameters.height_m,
        )
        link_into_scene(crate_name)
        self.created_object_names.append(crate_name)

        if parameters.bevel_width_m > 0.0:
            add_bevel(
                crate_name,
                width_m=parameters.bevel_width_m,
                segment_count=parameters.bevel_segment_count,
            )
            apply_all_modifiers(crate_name)

        return bpy.data.objects[crate_name]
