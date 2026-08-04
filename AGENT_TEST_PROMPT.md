# Agent test prompt

Paste everything in the fenced block below to any agent connected to the
`trellis2-mcp` server on the LAN. It exercises every tool, in dependency order,
and ends with a Blender scene to look at.

Everything after the fence is written for the agent, not for you.

---

```
You have access to an MCP server called trellis2-mcp that generates game-ready 3D
characters. Run a full end-to-end test of it and report what works.

Work through the steps in order — later steps consume earlier outputs, so don't
reorder them or run them in parallel. The GPU is shared and serialised by a lock;
one heavy tool at a time.

Record every call's outcome. Do NOT stop at the first failure: note it, keep
going, and give me a pass/fail table at the end. I want to know which things are
broken, not just the first one.

THE SUBJECT
Use this exact text as SUBJECT wherever a step refers to it:

  an emberwake herald, a horned fire-priestess with pale ash-grey skin, two long
  curved black horns swept back from the temples, close-cropped white hair,
  wearing a sleeveless deep crimson tunic, polished brass shoulder plates and
  brass greaves, a wide black leather belt, bare arms

It is built for the pipeline rather than for looks: the T-pose gives the rigger
limb chains to find AND matches the rest pose every animation clip assumes, the
six distinct materials give the segmenter parts to find, and the two horns
exercise the appendage chains that animation must leave alone.

Name every output `emberwake_herald` (or `emberwake_herald_<suffix>`) so the
tools' publishing logic files them all under one asset directory.

THE STEPS

1.  health_check. Report free VRAM. If less than ~19 GB is free, say so now —
    steps 6 and 7 need that much and will refuse, and that is a machine limit,
    not a defect.

2.  generate_image with prompt = SUBJECT plus this suffix, output_name
    "emberwake_herald_hero", steps 6:

      , full body, standing in a T-pose with both arms held straight out
      horizontally to the sides at shoulder height, palms down, elbows straight,
      legs shoulder-width apart, feet flat on the ground, centred on a plain flat
      white background, even studio lighting, no shadows, full figure in frame,
      sharp focus, game asset reference sheet

    The T-pose is load-bearing, not cosmetic. Every clip is authored against a
    T-pose rest and the retarget preserves the character's own rest offset, so an
    A-posed asset retargets with damped and sometimes inverted arm swing.

    The returned key is `local_path`, not `image_path`. Use that in step 4.

3.  generate_views with prompt = SUBJECT exactly (no suffix), views
    "front,back,left,right", output_name "emberwake_herald_views". Takes several
    minutes; it runs on a Mac over the network.

    Do not add words like "front view", "in profile", "seen from" or
    "three-quarter" to this prompt. The tool rejects them outright because they
    fight its own per-view conditioning.

4.  generate_3d on the step 2 image, output_name "emberwake_herald", and pass
    evict_trellis_for_bake=true. Without it the texture bake preflight refuses
    whenever anything else is holding the card.

5.  generate_3d_multi_image on the four step 3 images, output_name
    "emberwake_herald_mv", evict_trellis_for_bake=true. `images` is a JSON STRING
    — '["/path/a.png","/path/b.png"]' — not a list. Passing a list fails with
    "the JSON object must be str, bytes or bytearray, not list".

6.  segment_mesh on "emberwake_herald.glb". Needs ~18 GB VRAM. If it refuses on
    VRAM, report that and continue.

7.  generate_orbit_views on the step 2 image, output_name
    "emberwake_herald_orbit". Needs ~19 GB VRAM. This one is also known to be
    broken independently of VRAM — a dtype mismatch in MV-Adapter's background
    remover — so report whichever failure you actually get and move on.

8.  generate_garment with garment "hooded cloak with a deep pointed hood and a
    long open front, heavy dark wool", body "emberwake_herald.glb", output_name
    "emberwake_herald_cloak". If it dies with exit -9, that is the kernel OOM
    killer taking it, not a crash — say so.

9.  rig_model on "emberwake_herald.glb". This fits a canonical Mixamo skeleton
    and runs the rigger twice internally, so expect ~60-90 s. Confirm in the
    result that `canonical.core_bones` is 23 and
    `skeleton.zero_weight_vertices` is 0.

10. list_animations with search "walk". Report how many clips total and how many
    are usable. A clip is a (file, action) pair, so the count is much larger than
    the number of files.

11. apply_animation with character = the rigged .glb's filename from step 9 and
    clip "mutant walking". Then do it again with a UE5-convention clip to prove
    the name map works — use clip
    "/mnt/codex_fs/game_assets/animation/universal_animation_library_v1/Unreal-Godot/UAL1_Standard.glb"
    with action "Dance_Loop". Report `bones_driven` and `frame_alignment_deg` for
    both.

12. list_outputs and free_gpu.

IF YOU ALSO HAVE SHELL ACCESS

13. If step 6 succeeded, split the mesh into per-part objects:

      /home/ladvien/segvigen/.venv/bin/python \
        /home/ladvien/trellis2_mcp/scripts/split_by_parts.py \
        --mesh <asset dir>/asset.glb \
        --labels <asset dir>/asset_face_labels.npy \
        --out-dir <asset dir>

14. Build the Blender scene and tell me the path:

      /home/ladvien/segvigen/.venv/bin/python \
        /home/ladvien/trellis2_mcp/scripts/assemble_blend.py \
        --out /home/ladvien/trellis/output/emberwake_showcase.blend \
        --item "1 generate_3d=<the step 4 glb>" \
        --item "2 multi_image=<the step 5 glb>" \
        --item "3 rig_model=<the step 9 rigged glb>" \
        --item "4 apply_animation=<the step 11 animated glb>"

    It lays the stages out side by side, feet on the ground, labelled, with the
    frame range set so the animated one plays on spacebar.

WHAT TO GIVE ME

  * a pass/fail table, one row per step, with elapsed time
  * for each failure, whether it is a defect or a machine limit (VRAM, RAM,
    OOM kill), and the evidence you used to decide
  * the .blend path from step 14
  * anything a tool reported that contradicted its own documentation
```
