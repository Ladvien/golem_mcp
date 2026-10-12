"""blended — a Blender-based harness for agentic modeling of game assets.

Layering rule: `bpy` is only imported inside functions, never at module
top level. The pure layer (parameters, budgets, drift catalog, reports)
must import and test on machines with no Blender at all.
"""

from blended.version import TARGET_BLENDER_SERIES

__all__ = ["TARGET_BLENDER_SERIES"]
