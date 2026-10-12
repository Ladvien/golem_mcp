"""The one FastMCP instance every golem tool registers on."""

from fastmcp import FastMCP

INSTRUCTIONS = (
    "Image -> 3D -> rigged-character pipeline. "
    "generate_image (FLUX via mflux on bmb) produces a reference image; "
    "generate_3d / generate_3d_multi_image turn images into a textured .glb via TRELLIS; "
    "rig_model adds a skeleton and skin weights via SkinTokens/TokenRig. "
    "Every GPU job takes a gpu-tenant lease on big's RTX 3090 (it unloads llama-swap models and waits up to 20 min "
    "behind other holders), so GPU calls run one at a time. "
    "health_check reports `vram_free_gb` and which GPU tools fit right now (`gpu_tools`). "
    "IMPORTANT: TRELLIS normalizes every asset into a unit cube, so output is ~1 m tall "
    "regardless of subject. Scale downstream before using any measurement in metres; "
    "geometry.dimensions_m in the response gives the shipped size. "
    "Text-to-motion for rigged characters (NVIDIA Kimodo, SOMA skeleton) retargeted onto your GLB. "
    "The input must be a canonically rigged GLB (mixamorig:* skeleton, e.g. from rig_model) "
    "in T-pose. Prompts should start with 'A person ...', one or two behaviours per segment, at most "
    "10 s each. There is no finger or face animation. Output is in place unless root_motion is set. "
    "A job takes ~1-3 min, including the GPU queue and loading the CPU text encoder on a cache miss. "
    "Optional controls: root_path (waypoints; needs root_motion), start_heading_deg, "
    "text_cfg_weight / constraint_cfg_weight (default 2.0), transition_frames (default 5). "
    "Every sample is checked for its own surface passing through itself (self_intersection: off | score | "
    "repair, default repair: a crossing sample has its arms and legs turned off the body and the original is "
    "kept as <name>_unrepaired.glb); max_rerolls (default 0) re-rolls the seed while no sample is clean, "
    "contour_limit_cm (default 4) is how long a frame's intersection contour may be, and cloth_materials "
    "names loose-cloth materials whose self-contact is not counted."
)

mcp = FastMCP("golem", instructions=INSTRUCTIONS, version="0.5.0")
