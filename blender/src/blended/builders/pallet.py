"""A stringer pallet: arrayed deck boards unioned onto three stringers.

The third builder, and the first genuinely multi-part one: it exists to
prove the array -> union -> single-solid flow. Deck boards are embedded
a fraction of a millimeter into the stringers before the union so no
boolean ever sees exactly-coplanar faces (the EXACT solver's worst
case).
"""

from __future__ import annotations

from dataclasses import dataclass

# Parts overlap by this much before a union, so booleans never operate
# on exactly-coplanar faces.
BOOLEAN_EMBED_M = 0.0005
STRINGER_COUNT = 3


@dataclass(frozen=True)
class PalletParameters:
    """All dimensions in meters. Defaults near a EUR-pallet footprint."""

    length_m: float = 1.2
    width_m: float = 0.8
    stringer_height_m: float = 0.10
    stringer_width_m: float = 0.045
    deck_board_count: int = 5
    deck_board_width_m: float = 0.14
    deck_board_thickness_m: float = 0.022
    # WHICH ORDER the stringers are unioned in. Same reason as the
    # barrel's hoop_build_order: `probe` only ever varies parameters, so
    # a construction order that is not a parameter cannot be reordered
    # by any relation.
    stringer_build_order: tuple[int, ...] = (0, 1, 2)
    name: str = "Pallet"

    def validate(self) -> None:
        if min(self.length_m, self.width_m) <= 0.0:
            raise ValueError("Pallet footprint must be positive.")
        if self.deck_board_count < 2:
            raise ValueError("A pallet needs at least two deck boards.")
        total_board_span_m = self.deck_board_count * self.deck_board_width_m
        if total_board_span_m > self.length_m:
            raise ValueError(
                f"{self.deck_board_count} boards of "
                f"{self.deck_board_width_m} m exceed pallet length "
                f"{self.length_m} m."
            )
        if self.stringer_width_m * STRINGER_COUNT > self.width_m:
            raise ValueError("Stringers wider than the pallet.")
        if self.deck_board_thickness_m <= BOOLEAN_EMBED_M:
            raise ValueError("Deck boards thinner than the boolean embed.")
        if sorted(self.stringer_build_order) != list(range(STRINGER_COUNT)):
            raise ValueError(
                "Stringer build order must be a permutation of the stringers."
            )

    @property
    def deck_board_pitch_m(self) -> float:
        """Center-to-center spacing placing first/last boards at the ends."""
        return (self.length_m - self.deck_board_width_m) / (self.deck_board_count - 1)

    @property
    def total_height_m(self) -> float:
        return self.stringer_height_m + self.deck_board_thickness_m - BOOLEAN_EMBED_M


class PalletBuilder:
    def __init__(self, parameters: PalletParameters) -> None:
        parameters.validate()
        self.parameters = parameters
        self.created_object_names: list[str] = []

    def build(self):
        """Build the pallet and return its Blender object, base at z=0."""
        import bpy

        from blended.ops import add_box, boolean_union, linear_array, link_into_scene

        parameters = self.parameters

        # Deck: one board at the -X end, arrayed along +X.
        first_board_center_x_m = (
            -parameters.length_m / 2.0 + parameters.deck_board_width_m / 2.0
        )
        deck_name = add_box(
            parameters.name,
            width_m=parameters.deck_board_width_m,
            depth_m=parameters.width_m,
            height_m=parameters.deck_board_thickness_m,
            location_m=(
                first_board_center_x_m,
                0.0,
                parameters.stringer_height_m - BOOLEAN_EMBED_M,
            ),
        )
        link_into_scene(deck_name)
        self.created_object_names.append(deck_name)
        linear_array(
            deck_name,
            count=parameters.deck_board_count,
            offset_m=(parameters.deck_board_pitch_m, 0.0, 0.0),
        )

        # Three stringers bridge the boards into one solid.
        stringer_center_ys_m = (
            -parameters.width_m / 2.0 + parameters.stringer_width_m / 2.0,
            0.0,
            parameters.width_m / 2.0 - parameters.stringer_width_m / 2.0,
        )
        # Indexed by stringer_index throughout, so stringer i is
        # identical whatever order it is unioned in.
        for stringer_index in parameters.stringer_build_order:
            stringer_center_y_m = stringer_center_ys_m[stringer_index]
            stringer_name = add_box(
                f"{parameters.name}_stringer_{stringer_index}",
                width_m=parameters.length_m,
                depth_m=parameters.stringer_width_m,
                height_m=parameters.stringer_height_m,
                location_m=(0.0, stringer_center_y_m, 0.0),
            )
            link_into_scene(stringer_name)
            boolean_union(deck_name, stringer_name)

        return bpy.data.objects[deck_name]
