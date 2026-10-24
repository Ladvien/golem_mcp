"""Acceptance re-run of issue #19's five conditions through the MCP dispatch path."""
import json
import os
import sys

import glob
for _p in glob.glob("/Users/ladvien/golem_mcp/blender/.venv/lib/python*/site-packages"):
    sys.path.append(_p)
sys.path.insert(0, "/Users/ladvien/golem_mcp/blender/src")
import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
from golem_blender.ops.primitives import add_box, link_into_scene
from golem_blender.ops.assets import duplicate_object

# Fixture: a child of an empty at z=5, the issue's own case.
child = add_box("Child", 1.0, 1.0, 1.0, (0.0, 0.0, 0.0))
link_into_scene(child)
parent = bpy.data.objects.new("Mount", None)
bpy.context.scene.collection.objects.link(parent)
parent.location = (0.0, 0.0, 5.0)
bpy.context.view_layer.update()
bpy.data.objects[child].parent = parent
bpy.context.view_layer.update()
source_world_before = tuple(bpy.data.objects[child].matrix_world.translation)

report = duplicate_object("Child", "Copy", (1.0, 2.0, 3.0), 0.0)
copy_world = tuple(bpy.data.objects["Copy"].matrix_world.translation)
kept = duplicate_object("Child", "CopyParented", (1.0, 2.0, 3.0), 0.0, keep_parent=True)
parented_world = tuple(bpy.data.objects["CopyParented"].matrix_world.translation)
source_world_after = tuple(bpy.data.objects[child].matrix_world.translation)

print("1 copy world:", tuple(round(v, 6) for v in copy_world), "->", copy_world == (1.0, 2.0, 3.0))
print("2 keep_parent world:", tuple(round(v, 6) for v in parented_world), "->", parented_world == (1.0, 2.0, 8.0))
print("3 source unchanged:", source_world_before == source_world_after, source_world_after)
print("4 copy.parent is None:", bpy.data.objects["Copy"].parent is None)
# 5: own mesh data — duplicate first, then mutate the COPY's mesh
probe = duplicate_object("Child", "Probe", (0.0, 0.0, 0.0), 0.0)
before = [tuple(v.co) for v in bpy.data.objects["Child"].data.vertices]
from mathutils import Matrix
bpy.data.objects["Probe"].data.transform(Matrix.Translation((1.0, 0.0, 0.0)))
after = [tuple(v.co) for v in bpy.data.objects["Child"].data.vertices]
print("5 own mesh data:", bpy.data.objects["Probe"].data is not bpy.data.objects["Child"].data, before == after)
print("report flag default:", report.location_is_parent_relative, "kept:", kept.location_is_parent_relative)
# And the boolean-on-the-copy test the issue names
from golem_blender.ops.primitives import add_cylinder
cutter = add_cylinder("Cutter", 0.2, 1.0, 24, (1.0, 0.0, 0.4))
link_into_scene(cutter)
from golem_blender.ops.booleans import boolean_difference
source_tris = len(bpy.data.objects["Child"].data.polygons)
boolean_difference("Probe", "Cutter")
print("6 boolean on the copy left the source's polygons alone:", len(bpy.data.objects["Child"].data.polygons) == source_tris,
      "probe now:", len(bpy.data.objects["Probe"].data.polygons))
print("JSON form:", json.dumps({"object_name": report.object_name, "location_is_parent_relative": report.location_is_parent_relative}))
