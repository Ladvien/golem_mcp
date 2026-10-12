"""Golden snapshots of the runs that converged prompt v10.

Sign-off stores the render, the parameter snapshot and the regression
test together, and the harness detects drift against them. These are
the five runs that met the convergence rule on 2026-08-22 — human
verified, both deterministic gates clean, no prompt change between them,
one run per brief:
iteration 47 (three_leg_stool), 49 (uv_crate), 51 (crate_with_lid), and
— since 2026-09-10 — 66 (planter_box) and 67 (ribbed_column).

66 and 67 replaced 48 and 50 when OPS-21 (OT-2) made every op take and
return object NAMES. The recorded sources of 48 and 50 fetched a bpy
object and handed it to an op (`assign_material(o, ...)`,
`link_into_scene(col)`), or read `.name` off a constructor's return;
under the new contract those chunks raise, so the runs no longer
replay: planter measured 0 of 1 material slots assigned, the column was
never linked. The three survivors never dereferenced an op's return.
The replacements ran the SAME pinned v10 text (identity checked below)
on the claude-code:sonnet lane and passed both deterministic gates with
the same numbers; the pixel gate reported "the render moved" against
the 48/50 views (planter shading RMSE 0.075, column silhouette IoU
0.9948), which is what a fresh run looks like next to a replay. The
48/50 sign-off survives in the append-only iteration log.

Signed off by the user on the 66/67 contact sheets, 2026-09-10: same
geometry and form numbers as 48/50, planter a shade darker, column a
greyer material. The pin stands.

The v9 snapshots this file used to hold were replaced, not kept beside
these. v9 converged on the two-brief suite; the five-brief suite
changed the briefs (parts restructure, three new briefs, two new
refinement steps), so its numbers are not reproducible against today's
code, and a golden test that cannot run is not evidence. The v9
sign-off survives where it belongs: in the append-only iteration log,
and in `prompt_versions`, where v9 still carries its measured outcome.

Each is rebuilt by REPLAYING the run's own recorded chunks, so this
suite needs no model, no network and no lucky generation. Replay rather
than re-import: `ingest.import_glb` normalizes what it reads — it
recentres on its bounding-box centre and re-grounds — which is right for an
arbitrary generated asset and wrong for evidence, because it moves the
very placement the snapshot exists to pin. The .glb files beside these
tests are for a human to turn; the numbers come from the replay.

This answers a different question from the reference-stool fixtures
next door: those ask "is the brief satisfiable", this asks "does the
thing we signed off still measure the same". A change to a probe, a
tolerance, an op or a builder that silently moves these numbers fails
here.
"""

from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module")

pytestmark = pytest.mark.blender

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIRECTORY = REPOSITORY_ROOT / "_evaluate" / "golden"
ITERATION_LOG = REPOSITORY_ROOT / "_evaluate" / "iterations.jsonl"

# The five runs that met the convergence rule, one per brief.
CONVERGING_ITERATIONS = {
    "three_leg_stool": 47,
    "planter_box": 66,
    "uv_crate": 49,
    "ribbed_column": 67,
    "crate_with_lid": 51,
}
PINNED_REVISION = 10

# A brief carrying a RefinementStep is judged at its TERMINAL state.
# `replay_record` re-runs every recorded chunk, follow-up included, so
# the stool it rebuilds is the 0.55 m one the user last asked for —
# scoring that against the original 0.45 m brief would fail a run that
# passed. `_expected_brief` applies the refinements the same way the
# driver did.

# Measured off the converging runs. Every number here was produced by the
# agent and confirmed by the human; none was chosen to make a test pass.
STOOL_SNAPSHOT = {
    "seat_diameter_x": 0.4000,
    "seat_diameter_y": 0.4000,
    # The terminal height: iteration 47 ended with the taller stool.
    "total_height_z": 0.5500,
    "base_z": 0.0000,
    "sole_contact_area_m2": 0.002702,
    "sole_radius_m": 0.1400,
    "sole_bearings_deg": (0.0, 120.0, 240.0),
}
PLANTER_SNAPSHOT = {
    "width_x": 0.3000,
    "depth_y": 0.2000,
    "height_z": 0.2500,
    "base_z": 0.0000,
}
CRATE_SNAPSHOT = {
    "width_x": 0.5000,
    "depth_y": 0.5000,
    "height_z": 0.5000,
    "base_z": 0.0000,
}
COLUMN_SNAPSHOT = {
    "diameter_x": 0.2000,
    "diameter_y": 0.2000,
    "height_z": 1.0000,
    "base_z": 0.0000,
}
CRATE_WITH_LID_SNAPSHOT = {
    "width_x": 0.5000,
    "depth_y": 0.5000,
    "height_z": 0.4000,
    "base_z": 0.0000,
    "lid_width_x": 0.5000,
    "lid_depth_y": 0.5000,
    "lid_height_z": 0.0600,
}
# A .glb round trip splits vertices at flat-shading seams and re-quantises
# positions, so the snapshot is compared at the precision the format
# actually preserves, not at float equality.
SNAPSHOT_TOLERANCE_M = 0.0005
SOLE_AREA_TOLERANCE_M2 = 5.0e-5
SOLE_BEARING_TOLERANCE_DEG = 1.0


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _expected_brief(brief, record):
    """The brief the replayed asset should be judged against.

    Only the refinement steps the run actually EXECUTED are applied —
    the record carries one `LOCALITY <step>: ...` line per executed
    step. A record from before the suite gained steps must not be
    graded against steps it never ran.
    """
    from blended.evaluate.acceptance import refine_brief
    from blended.evaluate.replay import steps_applied

    for step in steps_applied(record, brief):
        brief = refine_brief(brief, step)
    return brief


def _measure(brief_name: str):
    """Rebuild the converging run for this brief and score it."""
    from blended.evaluate.acceptance import evaluate_brief
    from blended.evaluate.briefs import get_brief
    from blended.evaluate.replay import load_record, replay_record

    brief = get_brief(brief_name)
    record = load_record(ITERATION_LOG, CONVERGING_ITERATIONS[brief_name])
    assert record["brief_name"] == brief_name, record["brief_name"]
    assert record["prompt_revision"] == PINNED_REVISION, record["prompt_revision"]
    replay_record(record, brief.part_names)
    expected = _expected_brief(brief, record)
    return expected, evaluate_brief(expected)


def _dimension(report, name: str) -> float:
    for measurement in report.dimensions:
        if measurement.spec.name == name:
            return measurement.measured_m
    raise AssertionError(f"no dimension named {name!r} in the report")


def test_golden_stool_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("three_leg_stool")
    assert report.passes(brief), report.summary(brief)


def test_golden_stool_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("three_leg_stool")

    for name in ("seat_diameter_x", "seat_diameter_y", "total_height_z"):
        assert _dimension(report, name) == pytest.approx(
            STOOL_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        STOOL_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_stool_feet_are_where_they_were_signed_off(empty_scene):
    """The placement probe is the newest gate, so it is the one most
    likely to drift silently. Pin what it measured at sign-off."""
    _, report = _measure("three_leg_stool")

    assert len(report.ground_contacts) == 3
    for measurement in report.ground_contacts:
        assert measurement.contact_area_m2 == pytest.approx(
            STOOL_SNAPSHOT["sole_contact_area_m2"], abs=SOLE_AREA_TOLERANCE_M2
        ), measurement.describe()
        assert measurement.measured_radius_m == pytest.approx(
            STOOL_SNAPSHOT["sole_radius_m"], abs=SNAPSHOT_TOLERANCE_M
        ), measurement.describe()

    bearings = sorted(round(m.measured_angle_deg, 1) for m in report.ground_contacts)
    for measured, expected in zip(bearings, STOOL_SNAPSHOT["sole_bearings_deg"]):
        assert measured == pytest.approx(expected, abs=SOLE_BEARING_TOLERANCE_DEG)


def test_golden_planter_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("planter_box")
    assert report.passes(brief), report.summary(brief)


def test_golden_planter_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("planter_box")

    for name in ("width_x", "depth_y", "height_z"):
        assert _dimension(report, name) == pytest.approx(
            PLANTER_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        PLANTER_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_crate_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("uv_crate")
    assert report.passes(brief), report.summary(brief)


def test_golden_crate_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("uv_crate")

    for name in ("width_x", "depth_y", "height_z"):
        assert _dimension(report, name) == pytest.approx(
            CRATE_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        CRATE_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_column_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("ribbed_column")
    assert report.passes(brief), report.summary(brief)


def test_golden_column_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("ribbed_column")

    for name in ("diameter_x", "diameter_y", "height_z"):
        assert _dimension(report, name) == pytest.approx(
            COLUMN_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        COLUMN_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )


def test_golden_crate_with_lid_still_passes_the_form_gate(empty_scene):
    brief, report = _measure("crate_with_lid")
    assert report.passes(brief), report.summary(brief)


def test_golden_crate_with_lid_measures_the_signed_off_numbers(empty_scene):
    _, report = _measure("crate_with_lid")

    for name in (
        "width_x",
        "depth_y",
        "height_z",
        "lid_width_x",
        "lid_depth_y",
        "lid_height_z",
    ):
        assert _dimension(report, name) == pytest.approx(
            CRATE_WITH_LID_SNAPSHOT[name], abs=SNAPSHOT_TOLERANCE_M
        ), name
    assert report.base_z_m == pytest.approx(
        CRATE_WITH_LID_SNAPSHOT["base_z"], abs=SNAPSHOT_TOLERANCE_M
    )
    assert report.relation_failures == (), report.relation_failures


def test_golden_per_view_references_and_manifests_are_pinned():
    """The examiner compares PER VIEW, so the sign-off evidence is the
    per-view golden set, not just the contact sheet. Each brief's
    directory must carry a manifest and all five views, each non-empty.
    A missing or drifted reference would corrupt every later
    examination (RESP: an irrelevant reference is worse than none,
    10.48550/arXiv.2604.11082)."""
    import json

    for brief_name, iteration in CONVERGING_ITERATIONS.items():
        directory = GOLDEN_DIRECTORY / f"{brief_name}_v{PINNED_REVISION}"
        manifest_path = directory / "manifest.json"
        assert manifest_path.exists(), f"missing golden manifest {manifest_path}"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["brief"] == brief_name
        assert manifest["iteration"] == iteration
        assert manifest["prompt_identity"] == _pinned_identity()
        recorded_views = set(manifest["view_sha256"])
        assert recorded_views == {"front", "right", "top", "bottom", "three_quarter"}
        for view_name in recorded_views:
            png = directory / f"{view_name}.png"
            assert png.exists(), f"missing golden view {png}"
            assert png.stat().st_size > 0


def _pinned_identity() -> str:
    """The pinned identity, from the artifact `make pin` writes.

    Read rather than hardcoded so pinning is one command; the guarantee
    is unchanged, because any later edit to the pinned `.j2` changes the
    revision's identity while this file does not.
    """
    path = GOLDEN_DIRECTORY / "pinned_identity.txt"
    assert path.exists(), (
        f"no {path}: the pinned identity is written by `make pin`, and "
        f"without it nothing proves the pinned text is what converged"
    )
    return path.read_text(encoding="utf-8").strip()


def test_the_pinned_prompt_is_the_one_that_converged():
    """Pinning is a claim about history; it has to stay true."""
    from blended.agent import prompt_versions

    assert prompt_versions.ACTIVE_PROMPT_REVISION == (
        prompt_versions.PINNED_PROMPT_REVISION
    )
    pinned = prompt_versions.get_revision(prompt_versions.PINNED_PROMPT_REVISION)
    # The hash proves the TEXT did not drift after sign-off.
    assert pinned.identity == _pinned_identity()
    assert len(prompt_versions.CONVERGENCE_RUNS) == 5
    assert pinned.outcome, "a pinned revision must carry its measured outcome"
