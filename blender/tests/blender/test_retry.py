"""The retry loop end to end against real bpy."""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")

pytestmark = pytest.mark.blender

# A script an agent trained on Blender <=4.0 would plausibly write:
# build the crate, then reach for the removed auto-smooth attribute.
BROKEN_SMOOTH_CRATE_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.builders import CrateBuilder, CrateParameters

crate_object = CrateBuilder(CrateParameters(name="RetryCrate")).build()
crate_object.data.use_auto_smooth = True
"""

# The drift-catalog fix applied: smooth shading via the data API.
FIXED_SMOOTH_CRATE_SOURCE = """
import sys
sys.path.insert(0, "src")
from blended.builders import CrateBuilder, CrateParameters

crate_object = CrateBuilder(CrateParameters(name="RetryCrate")).build()
for polygon in crate_object.data.polygons:
    polygon.use_smooth = True
"""


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def _scripted_fixer(source_code: str, result) -> str:
    """Deterministic stand-in for the agent: applies the drift fix."""
    assert result.matched_drift, "fixer expected drift guidance in the result"
    return FIXED_SMOOTH_CRATE_SOURCE


def test_retry_fixes_drift_failure_on_first_retry(empty_scene):
    from blended.run.retry import run_with_retries

    outcome = run_with_retries(BROKEN_SMOOTH_CRATE_SOURCE, _scripted_fixer)

    assert outcome.ok
    assert outcome.attempt_count == 2  # initial failure + one successful retry
    first_attempt, second_attempt = outcome.attempts
    assert not first_attempt.result.ok
    assert any(
        "use_auto_smooth" in entry.symbol
        for entry in first_attempt.result.matched_drift
    )
    assert second_attempt.result.ok
    # The retry actually produced the object, and it is smooth-shaded.
    crate_object = bpy.data.objects["RetryCrate"]
    assert all(polygon.use_smooth for polygon in crate_object.data.polygons)


def test_retry_gives_up_after_cap(empty_scene):
    from blended.run.retry import run_with_retries

    def hopeless_fixer(source_code: str, result) -> str:
        return "raise RuntimeError('still broken')"

    outcome = run_with_retries(
        "raise RuntimeError('broken')", hopeless_fixer, maximum_retries=2
    )
    assert not outcome.ok
    assert outcome.attempt_count == 3  # initial + 2 retries, then stop
