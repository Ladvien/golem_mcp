"""The one-call loop, demonstrated on both front doors.

Run from the repo root with any Python that can `import bpy`:
    python examples/harness_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)

from blended.builders import BarrelBuilder, BarrelParameters
from blended.harness import HarnessSettings, run_builder, run_chunk
from blended.version import assert_supported_blender

assert_supported_blender()
settings = HarnessSettings(
    output_directory=Path("_renders/harness_demo"),
    export_glb_path=Path("_renders/harness_demo/barrel.glb"),
    export_blend_path=Path("_renders/harness_demo/barrel.blend"),
    session_log_path=Path("_renders/harness_demo/session.jsonl"),
)

print("=== library path: builder in, verified asset out ===")
builder_result = run_builder(BarrelBuilder(BarrelParameters()), settings)
print(builder_result.summary())

print()
print("=== agent path: a chunk that fails the gate, reviewably ===")
DEFECTIVE_CHUNK = """
import sys
sys.path.insert(0, "src")
import bmesh
import bpy
from blended.ops import add_box, link_into_scene
link_into_scene(add_box("DemoDefect", 0.5, 0.5, 0.5))
box = bpy.data.objects["DemoDefect"]
working = bmesh.new(); working.from_mesh(box.data)
working.faces.ensure_lookup_table(); working.faces.remove(working.faces[0])
working.to_mesh(box.data); working.free()
"""
chunk_result = run_chunk(DEFECTIVE_CHUNK, object_name="DemoDefect", settings=settings)
print(chunk_result.summary())
