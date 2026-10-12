"""Splayed legs that stand flat where they were asked to stand.

A splayed leg is a tilted cylinder, and a tilted cylinder's end cap is
a tilted ellipse. Stand its base centre on the foot circle, then cut
the result flush with the floor, and the cap crosses z=0 — high on the
outer side, low on the inner — so the cut keeps a crescent whose
centroid sits INBOARD of where the leg was placed. Measured, twice, at
exactly r=0.1281 m against a specified 0.1400 +/- 0.0100.

Twice is why this module exists. The first was this suite's own
reference stool. The second was the agent at iteration 17, which placed
all three bases on the foot circle, cut them flat, and reported success
because it verified the axis it had positioned rather than the sole
that resulted — "each foot's axis landing on radius 0.14". A trap that
catches the harness's author and the agent it supervises is not a
lapse of care, and prose telling the reader to remember trigonometry
would leave it to be re-derived on every run.

So the arithmetic lives here instead:

  drop        = leg_radius / cos(splay) + margin   whole cap clears z=0
  base_radius = foot_radius + drop * tan(splay)    axis crosses z=0 ON
                                                   the foot circle
  length      = hypot(rise, run) + drop / cos(splay)
                                                   regains what the
                                                   drop spent, along the axis

`add_splayed_leg` applies all three together. There is no argument
combination that reproduces the trap, which is the point: the failure
mode is now unreachable rather than discouraged.

`trim_soles_flat` is the other half. A leg placed by this module still
ends below the floor by design, and the cut is what turns its tilted
cap into a face to stand on. Cut BEFORE snapping to the ground, never
after: snapping lifts the object until its lowest POINT is at z=0,
which leaves nothing below the plane for the cutter to remove.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from blended.ops._objects import ObjectName

# The reference stool's measured values, promoted from the fixture that
# proved them. Named here so a caller never writes the literal.
DEFAULT_LEG_SEGMENT_COUNT = 12

# How far past "just touching" the cap is pushed below the cut plane.
# Zero would put the cap's low edge exactly on z=0, where a float
# rounding the wrong way leaves a sliver of tilted cap uncut.
DEFAULT_SOLE_CLEARANCE_MARGIN_M = 0.005

# Deep enough that the cutter's own underside never becomes the mesh's
# lowest face for any leg this module places.
DEFAULT_GROUND_CUTTER_DEPTH_M = 0.1

# The cutter has to out-span the asset in x and y. Expressed as a
# multiple of the widest thing the caller names rather than a fixed
# size, so it scales with the part instead of capping it.
GROUND_CUTTER_SPAN_FACTOR = 4.0


class ImpossibleLeg(ValueError):
    """Raised for a leg specification with no valid geometry.

    There is no nearest-sane-value fallback. A leg asked to rise zero
    metres, or to stand on a circle of negative radius, is a mistake in
    the caller's numbers, and silently building something adjacent to
    what was asked for is how a stool passes a gate while being wrong.
    """


@dataclass(frozen=True)
class SplayedLegSpec:
    """Where a leg starts, where it lands, and how thick it is.

    Every derived quantity is a property rather than a constructor
    argument, so a caller cannot supply a base radius or a length that
    disagrees with the foot placement it also asked for.
    """

    foot_radius_m: float  # where the SOLE lands, not where the axis points
    foot_bearing_deg: float
    top_radius_m: float  # how far from the axis the leg meets what it carries
    top_z_m: float  # the underside it meets, e.g. the seat's bottom face
    leg_radius_m: float
    segment_count: int = DEFAULT_LEG_SEGMENT_COUNT
    sole_clearance_margin_m: float = DEFAULT_SOLE_CLEARANCE_MARGIN_M

    def __post_init__(self) -> None:
        if self.top_z_m <= 0.0:
            raise ImpossibleLeg(f"top_z_m must be above the floor, got {self.top_z_m}")
        if self.leg_radius_m <= 0.0:
            raise ImpossibleLeg(
                f"leg_radius_m must be positive, got {self.leg_radius_m}"
            )
        if self.foot_radius_m < 0.0 or self.top_radius_m < 0.0:
            raise ImpossibleLeg(
                f"radii cannot be negative: foot={self.foot_radius_m}, "
                f"top={self.top_radius_m}"
            )
        if self.segment_count < 3:
            raise ImpossibleLeg(
                f"segment_count must be at least 3, got {self.segment_count}"
            )

    @property
    def rise_m(self) -> float:
        """Vertical distance the leg covers, floor to what it carries."""
        return self.top_z_m

    @property
    def run_m(self) -> float:
        """Horizontal distance it covers, going outward on the way down."""
        return self.foot_radius_m - self.top_radius_m

    @property
    def splay_rad(self) -> float:
        """Lean from vertical. Zero for a leg that goes straight down."""
        return math.atan2(self.run_m, self.rise_m)

    @property
    def sole_drop_m(self) -> float:
        """How far below z=0 the base sits so the WHOLE cap clears it."""
        return (
            self.leg_radius_m / math.cos(self.splay_rad) + self.sole_clearance_margin_m
        )

    @property
    def base_radius_m(self) -> float:
        """Where the base centre goes — outboard of the foot circle.

        Going DOWN the axis leans outward, so a base dropped below the
        floor has to start further out for the axis to cross z=0
        exactly on the foot circle. This offset is the whole fix.
        """
        return self.foot_radius_m + self.sole_drop_m * math.tan(self.splay_rad)

    @property
    def length_m(self) -> float:
        """Hypotenuse plus the drop along the axis: it has to regain what it spent.

        The drop is measured straight down, the leg runs along the splayed
        axis, so the axis must lengthen by drop / cos(splay), not by drop:
        only then does its top end exactly on (`top_radius_m`, `top_z_m`).
        """
        return math.hypot(self.rise_m, self.run_m) + self.sole_drop_m / math.cos(
            self.splay_rad
        )

    @property
    def bearing_rad(self) -> float:
        return math.radians(self.foot_bearing_deg)


def add_splayed_leg(name: str, spec: SplayedLegSpec) -> ObjectName:
    """Build one splayed leg mesh object, LINKED and with its transform applied.

    Positioned so that trimming flush with the floor leaves a sole
    whose centre is on `spec.foot_radius_m` at `spec.foot_bearing_deg`.
    Do not call `link_into_scene` on the result — it is already linked.
    Call `trim_soles_flat` once, after all legs are unioned on.
    """
    from mathutils import Euler

    from blended.ops._objects import object_by_name
    from blended.ops.primitives import add_cylinder, link_into_scene
    from blended.ops.transforms import apply_object_transform

    leg_name = add_cylinder(
        name,
        radius_m=spec.leg_radius_m,
        height_m=spec.length_m,
        segment_count=spec.segment_count,
    )
    link_into_scene(leg_name)
    leg = object_by_name(leg_name)
    # Tilt outward along the leg's own radial direction. Rotation is
    # about the cylinder's base, which is why the base is what gets
    # positioned below.
    bearing_rad = spec.bearing_rad
    leg.rotation_euler = Euler(
        (
            spec.splay_rad * math.sin(bearing_rad),
            -spec.splay_rad * math.cos(bearing_rad),
            0.0,
        ),
        "XYZ",
    )
    leg.location = (
        spec.base_radius_m * math.cos(bearing_rad),
        spec.base_radius_m * math.sin(bearing_rad),
        -spec.sole_drop_m,
    )
    apply_object_transform(leg_name)
    return leg_name


def splayed_leg_ring(
    name_prefix: str,
    count: int,
    spec: SplayedLegSpec,
    first_bearing_deg: float = 0.0,
) -> list[ObjectName]:
    """Build `count` leg mesh objects evenly spaced, the first at `first_bearing_deg`.

    Spacing is computed, not listed, so three legs cannot come out at
    0/120/239 degrees because someone typed a rounded third.
    """
    if count < 1:
        raise ImpossibleLeg(f"count must be at least 1, got {count}")
    import dataclasses

    legs = []
    for index in range(count):
        bearing_deg = first_bearing_deg + (360.0 / count) * index
        legs.append(
            add_splayed_leg(
                f"{name_prefix}{index}",
                dataclasses.replace(spec, foot_bearing_deg=bearing_deg),
            )
        )
    return legs


def trim_soles_flat(
    object_name: str,
    span_m: float,
    cutter_depth_m: float = DEFAULT_GROUND_CUTTER_DEPTH_M,
) -> ObjectName:
    """Cut everything below z=0 off the named mesh, so feet present faces not edges.

    `span_m` is the widest dimension of the object being trimmed; the
    cutter is sized from it. Call this BEFORE snapping to the ground,
    never after — snapping lifts the object until its lowest POINT is
    at z=0, which leaves nothing below the plane to remove.
    """
    from blended.ops.booleans import boolean_difference
    from blended.ops.primitives import add_box, link_into_scene, remove_object_and_mesh

    if span_m <= 0.0:
        raise ImpossibleLeg(f"span_m must be positive, got {span_m}")
    cutter_span_m = span_m * GROUND_CUTTER_SPAN_FACTOR
    cutter_name = add_box(
        f"{object_name}_SoleCutter",
        width_m=cutter_span_m,
        depth_m=cutter_span_m,
        height_m=cutter_depth_m,
        location_m=(0.0, 0.0, -cutter_depth_m),
    )
    link_into_scene(cutter_name)
    try:
        boolean_difference(object_name, cutter_name)
    finally:
        # The boolean consumes the cutter on success (this is then a no-op).
        # On failure it would stay linked into the scene as a stray 4*span
        # slab (measured: BooleanNoOp left `<name>_SoleCutter` behind) and
        # this op created it, so this op removes it.
        remove_object_and_mesh(cutter_name)
    return ObjectName(object_name)
