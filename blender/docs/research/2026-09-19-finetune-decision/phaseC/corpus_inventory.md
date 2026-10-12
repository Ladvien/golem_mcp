# Phase C — training-corpus inventory

**Data-sufficiency verdict: INSUFFICIENT.** 302 deduplicated execution-verified pairs, but only 32 DISTINCT instructions — 31x short of the 1000 a first SFT run needs, and duplicate instructions do not add information. The blocker is data GENERATION, not training.

## The benchmark archive as an instruction -> script corpus

| quantity | count |
|---|---|
| (instruction, script) pairs | 321 |
| ... that executed (`render_log.status == OK`) | 302 |
| ... that carry a `cd_pca` | 288 |
| ... that pass at `cd_pca <= 0.0252` | 165 |
| deduplicated on (instance, sha256(script)) | 321 |
| ... and execution-verified | 302 |
| **distinct instructions** | 32 |
| ... with at least one executing script | 32 |

The distinct-instruction row is the binding one: the frozen holdout is 20 prompts and every roll answers the same 20, so pair counts grow without adding instructions.

## Op-sequence pairs (the target rule 4 would name)

- attempts whose emitted script calls any facade op (reader ops included): **76**
- op calls in those scripts: **205**
- distinct ops exercised: **13** of 48
- baked `run_python` chunks against baked scene-changing op calls, over the pairs whose bridge could record an op: **581** against **136**; 198 earlier pairs come from a bridge that collected no op calls, so their chunk counts are not comparable

## Convergence log (`_evaluate/iterations.jsonl`)

- records: **97**
- records carrying schema-2 `tool_events`: **28**
- decodable tool events: **657** (0 refused by `decode_tool_event`)
- records with structural and form gates green: **0**

## Chat transcripts (`logs/chat-*.jsonl`)

- transcripts: **157**
- minable (schema-2 tool-event rows): **0**
- hatch invocations: **0**

Top hatch reasons, normalised:

| reason | invocations |
|---|---|

## Op coverage over the whole facade

- ops in the facade: **48**
- ops appearing anywhere in the archived scripts or the convergence log: **24**
- ops appearing fewer than 20 times: **13**
- ops never appearing: **24**

Ops the corpus never exercises, and therefore cannot teach:

```
add_armature, add_splayed_leg, animation_report, apply_canonical_depth_axis, apply_object_transform, assign_image_texture_material, assign_procedural_material, assign_vertex_group_weights, assign_weights_by_height, bind_mesh_to_armature, boolean_intersect, deforming_bone_names, depth_axis_extent_rank, keyframe_object_transform, keyframe_pose_bone_rotation, linear_array, middle_extent_m, orientation_reading, rig_report, rotate_object_euler, select_vertices, set_frame_range, weight_report, weld_and_dissolve
```

## Reference point

BlendNet: 8,000 instruction->script pairs (2,000 human-annotated, 6,000 model-validated); the BlenderLLM self-improvement rounds used ~2,000 samples each (arXiv:2412.14203, DOI 10.48550/arXiv.2412.14203). A usable first SFT run needs roughly 1000-3000 deduplicated, execution-verified pairs.
