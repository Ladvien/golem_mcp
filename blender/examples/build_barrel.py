"""Build the barrel, gate it, and render the four inspection views.

Run from the repo root with any Python that can `import bpy`:
    python examples/build_barrel.py
Renders land in _renders/barrel_example/.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

from blended.analyze import MeshBudget, analyze_object
from blended.builders import BarrelBuilder, BarrelParameters
from blended.capture import capture_contact_sheet
from blended.version import assert_supported_blender

assert_supported_blender()
barrel_object = BarrelBuilder(BarrelParameters()).build()
report = analyze_object(barrel_object)
failures = report.failures(MeshBudget())
print(report)
if failures:
    raise SystemExit(f"GATE FAILED: {failures}")
sheet_path = capture_contact_sheet(
    barrel_object,
    Path("_renders/barrel_example"),
    report=report,
)
print("GATE PASSED. Contact sheet:", sheet_path)
