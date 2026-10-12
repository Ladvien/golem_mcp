"""Test briefs: a prompt, and what the result must MEASURE.

A convergence loop needs its acceptance criteria to be executable, not
adjudicated. CADCodeVerify's contribution (10.48550/arXiv.2410.05340) is
exactly this — it recovers correctness by asking measurable questions of
the geometry rather than asking a VLM whether the picture looks right —
and the TikZ visual-verification study (10.48550/arXiv.2606.15693) is the
reason not to invert that order: verifiers
looking at renders are systematically biased toward accepting.

So every brief carries four kinds of assertion, all measured:

* DIMENSIONS — bounding-box extents per axis, against a named tolerance.
* SOLIDITY PROBES — is there material at this point, or not? This is the
  one that earns its place. "The planter's drainage hole is sealed shut"
  is the canonical wrong-object failure the analyzer cannot see and a
  render will not show: a sealed hole and an open one are the same
  picture from outside. A parity ray cast at the hole's centre answers
  it in a number.
* GROUNDING — the base sits on z=0, within tolerance.
* GROUND CONTACT — each foot presents a flat sole ON z=0, measured as
  an area. Grounding is one number and a single touching point
  satisfies it; standing up requires a face.

A brief names PARTS, not one object. Most briefs are single-part — the
object the agent builds — but an assembly (a crate with a lid) has two
objects, each with its own acceptance spec, plus RELATIONS that pin
how the parts sit against each other. `object_name` does not exist;
the parts are the objects.

Config is separate from construction (project rule): every quantity
below is a named constant with its unit in the name, and briefs compose
those constants. No literal appears inside an assertion.
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field

from blended.analyze.mesh_checks import DEFAULT_PROP_TRIANGLE_BUDGET, MeshBudget
from blended.analyze.pair_checks import CONTACT_DEPTH_TOLERANCE_M

# --- Shared tolerances -------------------------------------------------
# Proportion tolerance: the agent is given target dimensions in the
# prompt, so this is a build-accuracy tolerance, not an art tolerance.
DIMENSION_TOLERANCE_M = 0.02
# A base is "on the ground" within this. Tighter than the dimension
# tolerance because snapping to z=0 is an exact operation in the ops
# vocabulary, not an estimate.
GROUNDING_TOLERANCE_M = 0.002
# A sole is "flat on the ground" when its downward face lies in the z=0
# plane within this. Deliberately tighter than GROUNDING_TOLERANCE_M:
# grounding asks where the LOWEST point is, flatness asks whether the
# whole face is down there with it. Measured 2026-08-22 (iteration 4):
# a leg tilted 11.3 deg from vertical and cut at an angle presents a
# sole spanning 0.0118 m in z while its minimum sits exactly at z=0 —
# so base_z passes and the stool still rocks.
SOLE_PLANARITY_TOLERANCE_M = 0.0005
# Sole faces count toward a foot when their centroid falls within this
# of the foot's expected centre. Half the foot-circle radius: wide
# enough for any plausible leg, narrow enough that two feet cannot
# claim the same face.
FOOT_SEARCH_RADIUS_M = 0.07
# A foot must present at least this much flat face. One square
# centimetre — below that it is a chamfer or a numerical sliver, not
# something a stool stands on.
MINIMUM_SOLE_CONTACT_AREA_M2 = 1.0e-4
# Where a foot may sit, measured from the flat sole's own centroid.
# Measured 2026-08-22 (iteration 10): a correct stool's front
# orthographic view puts the 120 and 240 degree legs at the SAME
# world x, so they overlap into what reads as one leg and the view
# cannot show spacing at all. The human answered "Unclear" and was
# right to; placement is not a question a contact sheet can answer.
FOOT_RADIUS_TOLERANCE_M = 0.01
FOOT_ANGLE_TOLERANCE_DEG = 5.0

# --- Brief 1: planter box ----------------------------------------------
PLANTER_WIDTH_X_M = 0.30
PLANTER_DEPTH_Y_M = 0.20
PLANTER_HEIGHT_Z_M = 0.25
PLANTER_WALL_THICKNESS_M = 0.02
PLANTER_DRAIN_HOLE_RADIUS_M = 0.015

# Probe points, derived from the dimensions above so the spec stays
# consistent if a dimension changes.
PLANTER_DRAIN_PROBE_Z_M = PLANTER_WALL_THICKNESS_M / 2.0
PLANTER_CAVITY_PROBE_Z_M = PLANTER_HEIGHT_Z_M * 0.6
PLANTER_WALL_PROBE_X_M = (PLANTER_WIDTH_X_M - PLANTER_WALL_THICKNESS_M) / 2.0
PLANTER_FLOOR_PROBE_X_M = PLANTER_WIDTH_X_M * 0.3

# --- Brief 2: three-legged stool ---------------------------------------
STOOL_SEAT_DIAMETER_M = 0.32
STOOL_TOTAL_HEIGHT_Z_M = 0.45
# What the follow-up instruction asks for. Far enough from the
# original that no tolerance could absorb the difference.
STOOL_REFINED_HEIGHT_Z_M = 0.55
STOOL_SEAT_THICKNESS_M = 0.04
STOOL_LEG_COUNT = 3
# Feet sit on a circle of this radius; the splay is what made this brief
# worth keeping (see the matrix_world entry in drift/catalog.py).
STOOL_FOOT_CIRCLE_RADIUS_M = 0.14
STOOL_LEG_PROBE_Z_M = 0.03
STOOL_CENTRE_PROBE_Z_M = STOOL_TOTAL_HEIGHT_Z_M * 0.4
STOOL_SEAT_PROBE_Z_M = STOOL_TOTAL_HEIGHT_Z_M - (STOOL_SEAT_THICKNESS_M / 2.0)

# Second refinement step: a wider seat. The seat probes' z derives from
# the height the previous step set, so the step carries new seat probes
# in `changed_probes`.
STOOL_REFINED_SEAT_DIAMETER_M = 0.40

# Third refinement step: thicker legs. Leg radius is NOT a bounding-box
# extent, so it is expressed in probes only: solid inside a 0.03 m leg
# at foot-circle radius plus 0.025 m, empty further out at plus 0.045 m
# so the check cannot be satisfied by an oversized leg.
STOOL_REFINED_LEG_RADIUS_M = 0.03
STOOL_THICK_LEG_PROBE_OFFSET_M = 0.025
STOOL_THICK_LEG_PROBE_EMPTY_OFFSET_M = 0.045

# --- Brief 3: uv crate --------------------------------------------------
CRATE_SIZE_M = 0.50
CRATE_BEVEL_M = 0.02
# The discriminating number for the UV gate: a beveled cube is 6 faces +
# 12 edge bevels + 8 corners, so a per-face unwrap yields ~26 islands
# while any real seam-and-unwrap lands well under 12. The gate fails a
# per-face layout on exactly this.
UV_CRATE_MAXIMUM_UV_ISLANDS = 12

# --- Brief 4: ribbed column ---------------------------------------------
COLUMN_DIAMETER_M = 0.20
COLUMN_HEIGHT_Z_M = 1.00
COLUMN_RIB_COUNT = 5
COLUMN_TRIANGLE_BUDGET = 1200
# The shaft is narrower than the named diameter; the ribs stand proud
# of it and reach the diameter. Measured at iteration 27: a brief that
# named only the diameter left the agent free to read it as the shaft
# size, and probes at 0.09 m sat inside a 0.10 m shaft so the
# between-ribs check could never fire. The shaft and the rib reach are
# both named now, and the probes sit at the rib radius.
COLUMN_SHAFT_DIAMETER_M = 0.16
COLUMN_RIB_RADIUS_M = COLUMN_DIAMETER_M / 2.0 - 0.01
# Where the ribs sit. Measured at iteration 37: the agent built five
# ribs centered at 0.1/0.3/0.5/0.7/0.9 m — a legitimate reading of
# "evenly spaced down the height" — while the probes assumed 1/3 and
# 2/3 height and read empty between the real ribs. The brief now names
# the centers, and the probes sit on them.
COLUMN_RIB_CENTRE_Z_M = tuple(
    (COLUMN_HEIGHT_Z_M / COLUMN_RIB_COUNT) * (index + 0.5)
    for index in range(COLUMN_RIB_COUNT)
)
# How tall each rib is. Measured at iteration 41: the agent built ribs
# 0.04 m tall (half-height 0.02) and the between-ribs probe at
# center + 0.02 landed exactly on the rib's top edge, reading solid.
# The brief now names the thickness, and the between-ribs probe sits
# at the midpoint between centers — guaranteed empty for any rib
# thinner than the gap.
COLUMN_RIB_THICKNESS_M = 0.03
COLUMN_RIB_HALF_THICKNESS_M = COLUMN_RIB_THICKNESS_M / 2.0
COLUMN_BETWEEN_RIBS_PROBE_Z_M = (
    COLUMN_RIB_CENTRE_Z_M[1] + COLUMN_RIB_CENTRE_Z_M[2]
) / 2.0

# --- Brief 5: crate with lid (assembly) ---------------------------------
CRATE_BODY_SIZE_M = 0.50
CRATE_BODY_HEIGHT_Z_M = 0.40
CRATE_WALL_THICKNESS_M = 0.02
CRATE_LID_SIZE_M = 0.50
CRATE_LID_THICKNESS_M = 0.06
# How far apart the crate's two parts must be in linear RGB before the
# lid is visible at all. The signed-off reference measures exactly 0.15
# (body 0.6/0.4/0.2 against lid 0.5/0.3/0.15), so the floor sits below
# it with margin: the artifact that earned the pin conforms, and the
# uniform-colour run that made the lid disappear (distance 0) does not.
CRATE_LID_MINIMUM_COLOUR_DISTANCE_RGB = 0.10
# "Resting on" another part, same tolerance as resting on the ground
# plane — the planter's grounding tolerance.
CRATE_LID_STACK_TOLERANCE_M = GROUNDING_TOLERANCE_M
CRATE_LID_CENTRE_TOLERANCE_M = 0.005

AXIS_NAMES = ("x", "y", "z")


@dataclass(frozen=True)
class DimensionSpec:
    """One bounding-box extent the built object must hit."""

    name: str
    axis: str
    expected_m: float
    tolerance_m: float = DIMENSION_TOLERANCE_M

    def __post_init__(self) -> None:
        if self.axis not in AXIS_NAMES:
            raise ValueError(f"{self.name}: axis {self.axis!r} not in {AXIS_NAMES}")


@dataclass(frozen=True)
class SolidityProbe:
    """Is there material at this point?

    `expect_inside=False` is how negative space becomes measurable: a
    drainage hole, a hollow cavity, the gap between a stool's legs.
    """

    name: str
    point_m: tuple[float, float, float]
    expect_inside: bool
    why: str  # what a failure here means, in the brief's own terms


@dataclass(frozen=True)
class ClearAxisProbe:
    """Nothing may block the straight line through this point.

    A parity probe answers "is there material HERE", which is not the
    same question as "does this hole go all the way through". Measured
    2026-08-22 (iteration 1): a planter whose drainage hole was a blind
    RECESS — cut from the cavity down into the floor but not out the
    bottom — passed `drain_hole_is_open`, because a single upward ray
    from inside the recess exits through the open top and counts zero
    crossings. The top-down render showed solid material on the same
    axis. Parity says nothing about the half-space behind the ray.

    So a through-hole is specified as an unobstructed line of sight:
    cast the full length of the axis and require no hit at all.
    """

    name: str
    point_m: tuple[float, float, float]
    axis: str
    why: str

    def __post_init__(self) -> None:
        if self.axis not in AXIS_NAMES:
            raise ValueError(f"{self.name}: axis {self.axis!r} not in {AXIS_NAMES}")


@dataclass(frozen=True)
class GroundContactProbe:
    """The sole at this foot must be a flat face lying on z=0.

    `base_z` is one number — the minimum z of the whole object — so any
    single point touching the floor satisfies it. Measured 2026-08-22
    (iteration 4): the stool passed grounding at base_z +0.0000 m with a
    foot whose cut face was angled, and both the harness's visual
    critique and its pixel scan of the render read the resulting 3-pixel
    silhouette taper as anti-aliasing. Contact is an AREA, not a height,
    so it is measured as one: the total area of faces lying within
    `SOLE_PLANARITY_TOLERANCE_M` of z=0 near this foot.
    """

    name: str
    centre_xy_m: tuple[float, float]
    why: str
    # Where the sole must actually be, in the brief's own terms: on a
    # circle of this radius, at this bearing from +X. Measured from the
    # flat sole's centroid, so it answers "evenly spaced, first on the
    # +X axis" with two numbers instead of a look at a render.
    expected_radius_m: float = 0.0
    expected_angle_deg: float = 0.0
    minimum_area_m2: float = MINIMUM_SOLE_CONTACT_AREA_M2
    planarity_tolerance_m: float = SOLE_PLANARITY_TOLERANCE_M
    search_radius_m: float = FOOT_SEARCH_RADIUS_M
    radius_tolerance_m: float = FOOT_RADIUS_TOLERANCE_M
    angle_tolerance_deg: float = FOOT_ANGLE_TOLERANCE_DEG


@dataclass(frozen=True)
class RefinementStep:
    """A follow-up instruction, and what it may and may not change.

    The user-guided refinement phase is only real if "localized" is
    measurable. It is: after the edit, the named dimensions must hit
    their NEW targets, and every other measurement must still match what
    it measured BEFORE the edit — not merely still satisfy the original
    spec, which a full rebuild would also do. Preservation is the whole
    claim, so preservation is what is asserted.
    """

    name: str
    instruction_text: str  # what the user says next
    changed: tuple[DimensionSpec, ...]  # what must now measure differently
    why: str  # what a failure here means, in the user's terms
    # Probes whose point is DERIVED from a changed dimension have to move
    # with it. A stool asked to grow from 0.45 to 0.55 m still has a seat;
    # it is no longer at z=0.43, and a spec that did not move its probe
    # would report the seat missing and blame the edit.
    changed_probes: tuple[SolidityProbe, ...] = ()


@dataclass(frozen=True)
class PartSpec:
    """One named object the brief demands, and its own acceptance spec.

    Only the part that rests on the floor carries `require_base_at_ground`;
    a lid that sits on a crate does not — the stack relation pins where
    it rests.
    """

    name: str
    dimensions: tuple[DimensionSpec, ...] = ()
    probes: tuple[SolidityProbe, ...] = ()
    clear_axes: tuple[ClearAxisProbe, ...] = ()
    ground_contacts: tuple[GroundContactProbe, ...] = ()
    require_base_at_ground: bool = False


@dataclass(frozen=True)
class StackedOnSpec:
    """`upper_part` must rest ON `lower_part`: gap in z within tolerance.

    Measured against the parts' bounding boxes: upper.bbox_min_z minus
    lower.bbox_max_z within `tolerance_m` of zero. Zero tolerance would
    demand exact float contact; the tolerance is the same "resting on"
    tolerance the grounding check uses against the floor plane.
    """

    name: str
    upper_part: str
    lower_part: str
    tolerance_m: float
    why: str


@dataclass(frozen=True)
class SharedCentreSpec:
    """Two parts' bounding-box centres must agree on the named axes.

    One question, answered directly: is the lid hanging off one side of
    the crate it sits on? Axes are named ("x", "y") so a relation that
    only constrains x exists without a dead y branch.
    """

    name: str
    part_a: str
    part_b: str
    axes: tuple[str, ...]
    tolerance_m: float
    why: str


@dataclass(frozen=True)
class NoInterpenetrationSpec:
    """One part must not pass through another: measured on the SURFACE.

    Not the bounding boxes (a lid sunk through a rim can still satisfy
    every bbox relation) and not vertex distance (scp measured a
    nearest-vertex reading 60 mm where the true surface gap was
    6.5 mm — on box geometry the nearest vertex is a far corner).

    ``minimum_separation_m`` is None when contact is correct (a lid
    rests on its crate): only interpenetration is a failure then. It is
    also an UPPER bound on the true separation, not the separation
    itself — see `analyze.pair_checks.analyze_pair`.

    ``maximum_aabb_penetration_depth_m`` is the only number that sees a
    crossing whose face pairs the contact tolerance suppresses: two
    1 mm-thick plates passing through each other report 0 intersecting
    pairs and 0.999 m of separation, and 0.001 m of depth (measured,
    Blender 5.2.0). Opt-in like the separation bound, because AABB depth
    is meaningless for parts that legitimately share a bounding volume —
    a hoop around a barrel overlaps its AABB on every axis without
    touching it.
    """

    name: str
    first_part: str
    second_part: str
    why: str
    maximum_intersecting_face_pairs: int = 0
    minimum_separation_m: float | None = None
    maximum_aabb_penetration_depth_m: float | None = None


@dataclass(frozen=True)
class DistinctMaterialSpec:
    """Two touching parts must be TELLABLE APART in a render.

    The gap this closes, measured 2026-09-05. The crate brief specifies
    a lid with the body's exact footprint, resting flush on the rim, and
    every numeric check passed: 0.5000 x 0.5000 x 0.0600 at base_z
    0.4000, sitting on the body, centred, not sunk. And the render shows
    ONE CONTINUOUS BOX — no seam, no ledge, no lid. The examiner said so
    (`missing_feature`) and the geometry gates could not, because
    nothing was geometrically wrong.

    What makes the signed-off reference readable is COLOUR: its body is
    (0.6, 0.4, 0.2) and its lid (0.5, 0.3, 0.15), a distance of exactly
    0.15, while the run that vanished gave both parts (0.45, 0.30, 0.15)
    — a distance of 0. So the requirement is contrast between the
    parts, not a particular colour: an asset whose parts cannot be
    distinguished in any view has not delivered the brief, whatever it
    measures.

    Distance is Euclidean over linear RGB base colour. Deliberately NOT
    a required hue or luminance: pinning THOSE would bake one writer's
    taste into the acceptance spec, and the brief never asked for a
    particular brown.
    """

    name: str
    part_a: str
    part_b: str
    minimum_colour_distance_rgb: float
    why: str


# --- Provenance: where each number came from ---------------------------
# A brief's `prompt_text` carries executable specs, but nothing currently
# answers *where each number came from* or *what a human asked to change*.
# Provenance is the worked example the next brief copies: each entry pins
# one number in the brief to the requester's own words, the module constant
# that holds it, and the source class (measured, literature, reference, or
# art direction). A Correction records what moved when a human asked for a
# change. Both are frozen and defaulted empty so no existing construction
# breaks.

SOURCE_MEASURED = "measured"
SOURCE_LITERATURE = "literature"
SOURCE_REFERENCE = "reference"
SOURCE_ART_DIRECTION = "art-direction"
SOURCES = (SOURCE_MEASURED, SOURCE_LITERATURE, SOURCE_REFERENCE, SOURCE_ART_DIRECTION)
# A provenance value is a claim about a constant, written as a literal
# so the claim and the constant are two independent sources. Compared at
# this tolerance because a literal typed to the constant's own precision
# must match exactly; anything looser would accept a typo in the last
# digit of a millimetre.
PROVENANCE_VALUE_REL_TOL = 1.0e-9
# Dates are ISO so a sign-off is sortable and unambiguous. Format only —
# whether the date is real is not something this module can know.
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Provenance:
    """Where one number in this brief came from.

    `phrase` is the requester's own words (a substring of the brief's
    `prompt_text`), not a paraphrase. `symbol` is the constant in this
    module, e.g. ``STOOL_LEG_COUNT``, so `validate_briefs` can check the
    constant still exists and still holds the value the provenance claims.
    `cites` is REQUIRED when the source is literature or reference.
    """

    phrase: str
    symbol: str
    value: float | int | str
    source: str
    cites: str = ""


@dataclass(frozen=True)
class Correction:
    """A human asked for a change; this is what moved.

    `changed` is the symbol that moved, or ``""`` when nothing did (the
    human asked, but the number was already right). `on` is an ISO date.
    """

    said: str
    changed: str
    on: str


@dataclass(frozen=True)
class AssetBrief:
    """A prompt plus its executable acceptance spec.

    `parts` are the objects the agent must build, each measured by its
    own acceptance spec. `relations` pin how the parts sit against each
    other. Budget, grounding and material requirements are brief-level
    and apply to every part.
    """

    name: str
    prompt_text: str
    parts: tuple[PartSpec, ...]
    relations: tuple[
        StackedOnSpec
        | SharedCentreSpec
        | NoInterpenetrationSpec
        | DistinctMaterialSpec,
        ...,
    ] = ()
    refinements: tuple[RefinementStep, ...] = ()
    budget: MeshBudget = field(default_factory=MeshBudget)
    grounding_tolerance_m: float = GROUNDING_TOLERANCE_M
    # A game asset with no material slot is not shippable, and an empty
    # slot list is the single cheapest thing to forget. Checked
    # deterministically so it never reaches the visual pass.
    require_material: bool = True
    # Where each number in this brief came from, and what a human asked
    # to change. Both default empty so existing constructions keep working;
    # `validate_briefs` tolerates an empty tuple.
    provenance: tuple[Provenance, ...] = ()
    corrections: tuple[Correction, ...] = ()
    # ISO date, empty until a human signs off on the brief.
    signed_off: str = ""

    @property
    def part_names(self) -> tuple[str, ...]:
        """The part names in order. Two briefs cannot share a name."""
        return tuple(part.name for part in self.parts)


def _stool_foot_probes() -> tuple[SolidityProbe, ...]:
    """One probe inside each leg, at the foot circle.

    Legs are placed at even angular intervals starting at +X. The agent
    is told this in the prompt, so it is a spec, not a guess.
    """
    import math

    probes: list[SolidityProbe] = []
    for leg_index in range(STOOL_LEG_COUNT):
        angle_rad = (2.0 * math.pi / STOOL_LEG_COUNT) * leg_index
        probes.append(
            SolidityProbe(
                name=f"leg_{leg_index}_foot_is_solid",
                point_m=(
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.cos(angle_rad),
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.sin(angle_rad),
                    STOOL_LEG_PROBE_Z_M,
                ),
                expect_inside=True,
                why=(
                    f"leg {leg_index} must actually stand at "
                    f"{STOOL_FOOT_CIRCLE_RADIUS_M} m from the axis"
                ),
            )
        )
    return tuple(probes)


def _stool_ground_contacts() -> tuple[GroundContactProbe, ...]:
    """One sole-contact probe per foot, on the same circle as the legs."""
    import math

    contacts: list[GroundContactProbe] = []
    for leg_index in range(STOOL_LEG_COUNT):
        angle_rad = (2.0 * math.pi / STOOL_LEG_COUNT) * leg_index
        contacts.append(
            GroundContactProbe(
                name=f"leg_{leg_index}_sole_is_flat_on_the_ground",
                centre_xy_m=(
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.cos(angle_rad),
                    STOOL_FOOT_CIRCLE_RADIUS_M * math.sin(angle_rad),
                ),
                expected_radius_m=STOOL_FOOT_CIRCLE_RADIUS_M,
                expected_angle_deg=math.degrees(angle_rad),
                why=(
                    f"leg {leg_index} does not stand flat: its sole is "
                    f"angled or missing, so the stool touches the floor "
                    f"along an edge and rocks"
                ),
            )
        )
    return tuple(contacts)


def _stool_part() -> PartSpec:
    """The stool's part spec: the single object the agent must build."""
    return PartSpec(
        name="Stool",
        dimensions=(
            DimensionSpec("seat_diameter_x", "x", STOOL_SEAT_DIAMETER_M),
            DimensionSpec("seat_diameter_y", "y", STOOL_SEAT_DIAMETER_M),
            DimensionSpec("total_height_z", "z", STOOL_TOTAL_HEIGHT_Z_M),
        ),
        probes=(
            *_stool_foot_probes(),
            SolidityProbe(
                name="no_central_post",
                point_m=(0.0, 0.0, STOOL_CENTRE_PROBE_Z_M),
                expect_inside=False,
                why=(
                    "the legs collapsed to the central axis instead of "
                    "splaying (see drift/catalog.py: matrix_world is stale "
                    "until update)"
                ),
            ),
            SolidityProbe(
                name="seat_is_solid",
                point_m=(0.0, 0.0, STOOL_SEAT_PROBE_Z_M),
                expect_inside=True,
                why="there is no seat",
            ),
        ),
        ground_contacts=_stool_ground_contacts(),
        require_base_at_ground=True,
    )


def _stool_refinements() -> tuple[RefinementStep, ...]:
    """The stool's follow-up steps, in declared order.

    Design commitment 6 caps refinement at three rounds then escalates
    to the human; three steps exercise the whole cap. Each step's
    changed probes carry positions derived from the changed dimension —
    the seat probe's z derives from the height the previous step set.
    """
    import math

    return (
        RefinementStep(
            name="taller_stool",
            instruction_text=(
                f"Make the stool {STOOL_REFINED_HEIGHT_Z_M} m tall instead "
                f"of {STOOL_TOTAL_HEIGHT_Z_M} m. Leave everything else "
                f"exactly as it is."
            ),
            changed=(DimensionSpec("total_height_z", "z", STOOL_REFINED_HEIGHT_Z_M),),
            changed_probes=(
                SolidityProbe(
                    name="seat_is_solid",
                    point_m=(
                        0.0,
                        0.0,
                        STOOL_REFINED_HEIGHT_Z_M - (STOOL_SEAT_THICKNESS_M / 2.0),
                    ),
                    expect_inside=True,
                    why="there is no seat at the new height",
                ),
                SolidityProbe(
                    name="no_central_post",
                    point_m=(0.0, 0.0, STOOL_REFINED_HEIGHT_Z_M * 0.4),
                    expect_inside=False,
                    why="the legs collapsed to the central axis",
                ),
            ),
            why=(
                "a height change is a localized edit: the seat size, the "
                "foot circle and the leg bearings must come through it "
                "unchanged, and a rebuild would move them"
            ),
        ),
        RefinementStep(
            name="wider_seat",
            instruction_text=(
                f"Make the seat {STOOL_REFINED_SEAT_DIAMETER_M} m across "
                f"instead of {STOOL_SEAT_DIAMETER_M} m. Leave everything "
                f"else exactly as it is."
            ),
            changed=(
                DimensionSpec("seat_diameter_x", "x", STOOL_REFINED_SEAT_DIAMETER_M),
                DimensionSpec("seat_diameter_y", "y", STOOL_REFINED_SEAT_DIAMETER_M),
            ),
            changed_probes=(
                # The seat probe's z derives from the height the previous
                # step set, so it has to move with this step's seat.
                SolidityProbe(
                    name="seat_is_solid",
                    point_m=(
                        0.0,
                        0.0,
                        STOOL_REFINED_HEIGHT_Z_M - (STOOL_SEAT_THICKNESS_M / 2.0),
                    ),
                    expect_inside=True,
                    why="there is no seat at the new width",
                ),
            ),
            why=(
                "a seat widening is a localized edit: the stool height, "
                "the foot circle and the leg bearings must come through "
                "it unchanged, and a rebuild would move them"
            ),
        ),
        RefinementStep(
            name="thicker_legs",
            instruction_text=(
                f"Make the legs {STOOL_REFINED_LEG_RADIUS_M} m in radius "
                f"instead of 0.02 m. Leave everything else exactly as it "
                f"is."
            ),
            changed=(),
            changed_probes=(
                *(
                    SolidityProbe(
                        name=f"leg_{leg_index}_thickened_is_solid",
                        point_m=(
                            (
                                STOOL_FOOT_CIRCLE_RADIUS_M
                                + STOOL_THICK_LEG_PROBE_OFFSET_M
                            )
                            * math.cos(angle_rad),
                            (
                                STOOL_FOOT_CIRCLE_RADIUS_M
                                + STOOL_THICK_LEG_PROBE_OFFSET_M
                            )
                            * math.sin(angle_rad),
                            STOOL_LEG_PROBE_Z_M,
                        ),
                        expect_inside=True,
                        why=(
                            f"leg {leg_index} did not thicken: material "
                            f"missing at foot-circle radius plus "
                            f"{STOOL_THICK_LEG_PROBE_OFFSET_M} m, inside a "
                            f"{STOOL_REFINED_LEG_RADIUS_M} m leg"
                        ),
                    )
                    for leg_index, angle_rad in [
                        (index, (2.0 * math.pi / STOOL_LEG_COUNT) * index)
                        for index in range(STOOL_LEG_COUNT)
                    ]
                ),
                *(
                    SolidityProbe(
                        name=f"leg_{leg_index}_not_oversized_is_empty",
                        point_m=(
                            (
                                STOOL_FOOT_CIRCLE_RADIUS_M
                                + STOOL_THICK_LEG_PROBE_EMPTY_OFFSET_M
                            )
                            * math.cos(angle_rad),
                            (
                                STOOL_FOOT_CIRCLE_RADIUS_M
                                + STOOL_THICK_LEG_PROBE_EMPTY_OFFSET_M
                            )
                            * math.sin(angle_rad),
                            STOOL_LEG_PROBE_Z_M,
                        ),
                        expect_inside=False,
                        why=(
                            f"leg {leg_index} is oversized: material at "
                            f"foot-circle radius plus "
                            f"{STOOL_THICK_LEG_PROBE_EMPTY_OFFSET_M} m, "
                            f"outside a {STOOL_REFINED_LEG_RADIUS_M} m leg"
                        ),
                    )
                    for leg_index, angle_rad in [
                        (index, (2.0 * math.pi / STOOL_LEG_COUNT) * index)
                        for index in range(STOOL_LEG_COUNT)
                    ]
                ),
            ),
            why=(
                "a leg thickening is a localized edit: the seat size, the "
                "stool height and the foot bearings must come through it "
                "unchanged — and the leg is measured as geometry (solid "
                "inside the new radius, empty outside), not as a number "
                "the brief can check"
            ),
        ),
    )


PLANTER_BOX_BRIEF = AssetBrief(
    name="planter_box",
    prompt_text=(
        f"Build a rectangular garden planter box named 'PlanterBox'. "
        f"It is {PLANTER_WIDTH_X_M} m wide on X, {PLANTER_DEPTH_Y_M} m deep "
        f"on Y, and {PLANTER_HEIGHT_Z_M} m tall on Z, sitting on the ground "
        f"at z=0. The walls and floor are {PLANTER_WALL_THICKNESS_M} m thick. "
        f"The top is open — it is a container, hollow inside, not a solid "
        f"block. There is one drainage hole of radius "
        f"{PLANTER_DRAIN_HOLE_RADIUS_M} m bored straight down through the "
        f"centre of the floor, and it must go all the way through so water "
        f"can actually drain. The finished object must be a single watertight "
        f"manifold mesh under {DEFAULT_PROP_TRIANGLE_BUDGET} triangles, "
        f"with a material assigned, and it must be the only mesh object "
        f"left in the scene when you are done."
    ),
    parts=(
        PartSpec(
            name="PlanterBox",
            dimensions=(
                DimensionSpec("width_x", "x", PLANTER_WIDTH_X_M),
                DimensionSpec("depth_y", "y", PLANTER_DEPTH_Y_M),
                DimensionSpec("height_z", "z", PLANTER_HEIGHT_Z_M),
            ),
            probes=(
                SolidityProbe(
                    name="drain_hole_is_open",
                    point_m=(0.0, 0.0, PLANTER_DRAIN_PROBE_Z_M),
                    expect_inside=False,
                    why="the drainage hole is sealed shut — water cannot drain",
                ),
                SolidityProbe(
                    name="interior_is_hollow",
                    point_m=(0.0, 0.0, PLANTER_CAVITY_PROBE_Z_M),
                    expect_inside=False,
                    why="the planter is a solid block, not a container",
                ),
                SolidityProbe(
                    name="floor_is_solid_off_centre",
                    point_m=(PLANTER_FLOOR_PROBE_X_M, 0.0, PLANTER_DRAIN_PROBE_Z_M),
                    expect_inside=True,
                    why="the floor is missing — soil would fall straight out",
                ),
                SolidityProbe(
                    name="wall_is_solid",
                    point_m=(PLANTER_WALL_PROBE_X_M, 0.0, PLANTER_CAVITY_PROBE_Z_M),
                    expect_inside=True,
                    why="the side wall has no thickness",
                ),
            ),
            clear_axes=(
                ClearAxisProbe(
                    name="drain_hole_goes_all_the_way_through",
                    point_m=(0.0, 0.0, 0.0),
                    axis="z",
                    why=(
                        "the drainage hole does not pass through the floor "
                        "— it is a blind recess, so water cannot drain"
                    ),
                ),
            ),
            require_base_at_ground=True,
        ),
    ),
)

THREE_LEG_STOOL_BRIEF = AssetBrief(
    name="three_leg_stool",
    prompt_text=(
        f"Build a three-legged wooden stool named 'Stool'. The round seat is "
        f"{STOOL_SEAT_DIAMETER_M} m across and {STOOL_SEAT_THICKNESS_M} m "
        f"thick. Total height is {STOOL_TOTAL_HEIGHT_Z_M} m with the feet on "
        f"the ground at z=0. The {STOOL_LEG_COUNT} legs splay outward as they "
        f"descend: each foot touches the ground on a circle of radius "
        f"{STOOL_FOOT_CIRCLE_RADIUS_M} m from the central axis, with the legs "
        f"evenly spaced and the first one on the +X axis. The space between "
        f"the legs is open — there is no central post and no skirt. The "
        f"finished object must be a single watertight manifold mesh under "
        f"{DEFAULT_PROP_TRIANGLE_BUDGET} triangles, with a material "
        f"assigned, and it must be the only mesh object left in the "
        f"scene when you are done."
    ),
    parts=(_stool_part(),),
    refinements=_stool_refinements(),
    # The worked example: each number the prompt states, pinned to the
    # requester's own words and the constant that holds it. `value` is
    # written as a LITERAL, never as the constant itself: a provenance
    # that reads `value=STOOL_SEAT_DIAMETER_M` is the same object the
    # validator reads back, so the check is a tautology under any source
    # edit. The literal makes the claim and the constant two independent
    # sources, which is the only arrangement that can disagree. Checked
    # by validate_briefs from tests/pure/test_briefs_provenance.py — not
    # at import; nothing calls it at module scope.
    provenance=(
        Provenance(
            phrase="The round seat is 0.32 m across",
            symbol="STOOL_SEAT_DIAMETER_M",
            value=0.32,
            source=SOURCE_ART_DIRECTION,
        ),
        Provenance(
            phrase="0.04 m thick",
            symbol="STOOL_SEAT_THICKNESS_M",
            value=0.04,
            source=SOURCE_ART_DIRECTION,
        ),
        Provenance(
            phrase="Total height is 0.45 m",
            symbol="STOOL_TOTAL_HEIGHT_Z_M",
            value=0.45,
            source=SOURCE_ART_DIRECTION,
        ),
        Provenance(
            phrase="3 legs splay outward",
            symbol="STOOL_LEG_COUNT",
            value=3,
            source=SOURCE_ART_DIRECTION,
        ),
        Provenance(
            phrase="circle of radius 0.14 m",
            symbol="STOOL_FOOT_CIRCLE_RADIUS_M",
            value=0.14,
            source=SOURCE_ART_DIRECTION,
        ),
    ),
)

UV_CRATE_BRIEF = AssetBrief(
    name="uv_crate",
    prompt_text=(
        f"Build a solid wooden crate named 'Crate'. It is "
        f"{CRATE_SIZE_M} m on each side (X, Y and Z), sitting on the ground "
        f"at z=0, with its edges beveled {CRATE_BEVEL_M} m. The crate must "
        f"be UNWRAPPED for texturing: it needs a UV layout with no "
        f"overlapping faces and no faces outside the 0-1 UV square, in "
        f"under {UV_CRATE_MAXIMUM_UV_ISLANDS} islands — a real seam-and-"
        f"unwrap layout, not one island per face. One material assigned. "
        f"The finished object must be a single watertight manifold mesh "
        f"under {DEFAULT_PROP_TRIANGLE_BUDGET} triangles, and it must be "
        f"the only mesh object left in the scene when you are done."
    ),
    parts=(
        PartSpec(
            name="Crate",
            dimensions=(
                DimensionSpec("width_x", "x", CRATE_SIZE_M),
                DimensionSpec("depth_y", "y", CRATE_SIZE_M),
                DimensionSpec("height_z", "z", CRATE_SIZE_M),
            ),
            probes=(
                SolidityProbe(
                    name="centre_is_solid",
                    point_m=(0.0, 0.0, CRATE_SIZE_M / 2.0),
                    expect_inside=True,
                    why="the crate is hollow — the bounding box is a shell, "
                    "not a solid block",
                ),
                SolidityProbe(
                    name="just_outside_a_face_is_empty",
                    point_m=(CRATE_SIZE_M / 2.0 + 0.05, 0.0, CRATE_SIZE_M / 2.0),
                    expect_inside=False,
                    why="material found outside the box — the bounding box "
                    "is satisfied by geometry in the wrong place",
                ),
            ),
            require_base_at_ground=True,
        ),
    ),
    budget=MeshBudget(
        require_uv_layer=True,
        allow_uv_overlaps=False,
        allow_uv_out_of_bounds=False,
        maximum_uv_island_count=UV_CRATE_MAXIMUM_UV_ISLANDS,
    ),
)

RIBBED_COLUMN_BRIEF = AssetBrief(
    name="ribbed_column",
    prompt_text=(
        f"Build a turned column named 'Column', {COLUMN_DIAMETER_M} m in "
        f"diameter and {COLUMN_HEIGHT_Z_M} m tall, sitting on the ground "
        f"at z=0. The shaft is {COLUMN_SHAFT_DIAMETER_M} m in diameter; "
        f"the {COLUMN_RIB_COUNT} horizontal ribs stand proud of it and "
        f"reach the full {COLUMN_DIAMETER_M} m diameter, centered at "
        f"z = {', '.join(f'{z:.1f}' for z in COLUMN_RIB_CENTRE_Z_M)} m, "
        f"each {COLUMN_RIB_THICKNESS_M} m thick — a real ridge of "
        f"material, not a texture and not a smooth taper. The silhouette "
        f"must read as round, not faceted. The finished object must be "
        f"a single watertight manifold mesh under "
        f"{COLUMN_TRIANGLE_BUDGET} triangles, with a material assigned, "
        f"and it must be the only mesh object left in the scene when you "
        f"are done."
    ),
    parts=(
        PartSpec(
            name="Column",
            dimensions=(
                DimensionSpec("diameter_x", "x", COLUMN_DIAMETER_M),
                DimensionSpec("diameter_y", "y", COLUMN_DIAMETER_M),
                DimensionSpec("height_z", "z", COLUMN_HEIGHT_Z_M),
            ),
            probes=(
                SolidityProbe(
                    name="axis_mid_height_is_solid",
                    point_m=(0.0, 0.0, COLUMN_HEIGHT_Z_M / 2.0),
                    expect_inside=True,
                    why="the column is hollow — the shaft has no material "
                    "at its centre",
                ),
                SolidityProbe(
                    name="rib_crest_is_solid",
                    point_m=(
                        COLUMN_RIB_RADIUS_M,
                        0.0,
                        COLUMN_RIB_CENTRE_Z_M[1],
                    ),
                    expect_inside=True,
                    why=(
                        "no material at rib radius — the ribs do not exist as geometry"
                    ),
                ),
                SolidityProbe(
                    name="between_ribs_is_empty",
                    point_m=(
                        COLUMN_RIB_RADIUS_M,
                        0.0,
                        COLUMN_BETWEEN_RIBS_PROBE_Z_M,
                    ),
                    expect_inside=False,
                    why=(
                        "the rib reads as solid across its whole height — "
                        "the column is a smooth taper with no separate ribs"
                    ),
                ),
            ),
            require_base_at_ground=True,
        ),
    ),
    budget=MeshBudget(maximum_triangle_count=COLUMN_TRIANGLE_BUDGET),
)

CRATE_WITH_LID_BRIEF = AssetBrief(
    name="crate_with_lid",
    prompt_text=(
        f"Build a crate with a lid as TWO separate named objects. The "
        f"first, named 'CrateBody', is a hollow open-top crate "
        f"{CRATE_BODY_SIZE_M} m on X and Y and {CRATE_BODY_HEIGHT_Z_M} m "
        f"tall, sitting on the ground at z=0, with walls "
        f"{CRATE_WALL_THICKNESS_M} m thick. The second, named 'CrateLid', "
        f"is a solid slab {CRATE_LID_SIZE_M} m on X and Y and "
        f"{CRATE_LID_THICKNESS_M} m thick, resting on the crate's rim — "
        f"not floating above it and not sunk into it — centred on the "
        f"crate so it does not overhang one side. Each object is a single "
        f"watertight manifold mesh under {DEFAULT_PROP_TRIANGLE_BUDGET} "
        f"triangles with a material assigned. Because the lid has the "
        f"body's exact footprint and sits flush on the rim, COLOUR is "
        f"the only thing that makes it visible: give the two objects "
        f"materials whose base colours differ by at least "
        f"{CRATE_LID_MINIMUM_COLOUR_DISTANCE_RGB} in linear RGB "
        f"distance, or the crate renders as one featureless box. The "
        f"only mesh objects left "
        f"in the scene when you are done are 'CrateBody' and 'CrateLid'."
    ),
    parts=(
        PartSpec(
            name="CrateBody",
            dimensions=(
                DimensionSpec("width_x", "x", CRATE_BODY_SIZE_M),
                DimensionSpec("depth_y", "y", CRATE_BODY_SIZE_M),
                DimensionSpec("height_z", "z", CRATE_BODY_HEIGHT_Z_M),
            ),
            probes=(
                SolidityProbe(
                    name="cavity_is_hollow",
                    point_m=(0.0, 0.0, CRATE_BODY_HEIGHT_Z_M / 2.0),
                    expect_inside=False,
                    why="the crate body is a solid block, not a hollow container",
                ),
                SolidityProbe(
                    name="wall_is_solid",
                    point_m=(
                        CRATE_BODY_SIZE_M / 2.0 - CRATE_WALL_THICKNESS_M / 2.0,
                        0.0,
                        CRATE_BODY_HEIGHT_Z_M / 2.0,
                    ),
                    expect_inside=True,
                    why="the crate wall has no thickness",
                ),
            ),
            require_base_at_ground=True,
        ),
        PartSpec(
            name="CrateLid",
            dimensions=(
                DimensionSpec("lid_width_x", "x", CRATE_LID_SIZE_M),
                DimensionSpec("lid_depth_y", "y", CRATE_LID_SIZE_M),
                DimensionSpec("lid_height_z", "z", CRATE_LID_THICKNESS_M),
            ),
        ),
    ),
    relations=(
        StackedOnSpec(
            name="lid_sits_on_the_body",
            upper_part="CrateLid",
            lower_part="CrateBody",
            tolerance_m=CRATE_LID_STACK_TOLERANCE_M,
            why=(
                "the lid floats above the crate or sinks into it instead "
                "of resting on the rim"
            ),
        ),
        SharedCentreSpec(
            name="lid_is_centred_on_the_body",
            part_a="CrateLid",
            part_b="CrateBody",
            axes=("x", "y"),
            tolerance_m=CRATE_LID_CENTRE_TOLERANCE_M,
            why="the lid is offset and overhangs one side",
        ),
        NoInterpenetrationSpec(
            name="lid_does_not_sink_into_the_body",
            first_part="CrateLid",
            second_part="CrateBody",
            maximum_intersecting_face_pairs=0,
            minimum_separation_m=None,  # the lid rests ON the body: contact is correct
            # The lid's footprint matches the body's, so the AABBs overlap
            # on x and y in every correct build and the minimum-axis depth
            # IS the sink depth. The signed-off reference sits ~1 mm into
            # the rim, so the bound is the same resting tolerance the pair
            # module uses to suppress the face-pair count.
            maximum_aabb_penetration_depth_m=CONTACT_DEPTH_TOLERANCE_M,
            why=("a lid sunk into the body reads as closed in every orthographic view"),
        ),
        DistinctMaterialSpec(
            name="lid_is_distinguishable_from_the_body",
            part_a="CrateLid",
            part_b="CrateBody",
            minimum_colour_distance_rgb=(CRATE_LID_MINIMUM_COLOUR_DISTANCE_RGB),
            why=(
                "a lid the same colour as the body, flush on the rim and "
                "the same footprint, is invisible in every view: the "
                "render shows one continuous box and no measurement "
                "notices"
            ),
        ),
    ),
)

BRIEFS: dict[str, AssetBrief] = {
    PLANTER_BOX_BRIEF.name: PLANTER_BOX_BRIEF,
    THREE_LEG_STOOL_BRIEF.name: THREE_LEG_STOOL_BRIEF,
    UV_CRATE_BRIEF.name: UV_CRATE_BRIEF,
    RIBBED_COLUMN_BRIEF.name: RIBBED_COLUMN_BRIEF,
    CRATE_WITH_LID_BRIEF.name: CRATE_WITH_LID_BRIEF,
}


class UnknownBrief(KeyError):
    """Raised when a brief name has no entry. There is no default brief."""


def get_brief(name: str) -> AssetBrief:
    if name not in BRIEFS:
        raise UnknownBrief(
            f"No brief {name!r}. Available: {', '.join(sorted(BRIEFS))}."
        )
    return BRIEFS[name]


def _validate_brief(brief: AssetBrief) -> list[str]:
    """Problems for one brief (empty list = healthy).

    Factored out of `validate_briefs` so a test can call it with a
    constructed brief rather than mutating module state.
    """
    problems: list[str] = []
    for prov in brief.provenance:
        if prov.source not in SOURCES:
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} has "
                f"unknown source {prov.source!r}"
            )
        if (
            prov.source in (SOURCE_LITERATURE, SOURCE_REFERENCE)
            and not prov.cites.strip()
        ):
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} is "
                f"{prov.source} but carries no citation"
            )
        if not hasattr(sys.modules[__name__], prov.symbol):
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} does not "
                f"resolve to a module-level name in blended.evaluate.briefs"
            )
            continue
        current = getattr(sys.modules[__name__], prov.symbol)
        both_numeric = isinstance(current, (int, float)) and isinstance(
            prov.value, (int, float)
        )
        if both_numeric:
            if not math.isclose(
                float(current), float(prov.value), rel_tol=PROVENANCE_VALUE_REL_TOL
            ):
                problems.append(
                    f"{brief.name}: provenance symbol {prov.symbol!r} claims "
                    f"value {prov.value}, constant holds {current}"
                )
        elif type(current) is not type(prov.value):
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} claims a "
                f"{type(prov.value).__name__} but the constant holds a "
                f"{type(current).__name__} ({current!r}) — the symbol names "
                f"the wrong module-level object"
            )
        elif current != prov.value:
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} claims "
                f"value {prov.value!r}, constant holds {current!r}"
            )
        # A number with no words is not provenance. Required, not
        # skipped-when-empty: an optional phrase is an opt-out from the
        # only check that ties the number to what was actually asked for.
        if not prov.phrase.strip():
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} has an empty phrase"
            )
        elif prov.phrase not in brief.prompt_text:
            problems.append(
                f"{brief.name}: provenance symbol {prov.symbol!r} phrase "
                f"{prov.phrase!r} is not a substring of the brief's "
                f"prompt_text"
            )
    for correction in brief.corrections:
        if not correction.said.strip():
            problems.append(
                f"{brief.name}: correction with empty `said` — a change "
                f"nobody asked for is not a change"
            )
        if not _ISO_DATE.fullmatch(correction.on):
            problems.append(
                f"{brief.name}: correction dated {correction.on!r} is not an "
                f"ISO date (YYYY-MM-DD)"
            )
    # signed_off is empty until a human signs off; when it is set it is a
    # date, and an unparseable one makes the sign-off unauditable.
    if brief.signed_off and not _ISO_DATE.fullmatch(brief.signed_off):
        problems.append(
            f"{brief.name}: signed_off {brief.signed_off!r} is not an ISO "
            f"date (YYYY-MM-DD)"
        )
    return problems


def validate_briefs() -> list[str]:
    """Return a list of provenance problems (empty list = healthy).

    Mirrors `drift.catalog.validate_catalog` and
    `agent.skill_modules.validate_modules` in shape: returns problems
    rather than raising. Every `Provenance.source` is in `SOURCES`;
    `cites` is non-empty for literature or reference; `symbol` resolves
    to a module-level name in this module (checked with `hasattr`, so a
    renamed constant is a red test rather than silent fiction); the
    provenance `value` equals that constant's current value and is of
    the same type; every `phrase` is non-empty and appears verbatim in
    `prompt_text`; no brief carries a `Correction` with an empty `said`;
    dates are ISO; and every registry KEY matches the brief's own name.

    The key check, not a name-uniqueness check: `BRIEFS` is a dict, so
    its keys are unique by construction and a uniqueness loop over them
    can never fire. What can go wrong is disagreement — `get_brief`
    looks up by key while every message here prints `brief.name`, so a
    mismatch reports a brief the caller cannot fetch.
    """

    problems: list[str] = []
    for name, brief in BRIEFS.items():
        problems.extend(_validate_brief(brief))
        if brief.name != name:
            problems.append(f"registry key {name!r} holds a brief named {brief.name!r}")
    return problems
