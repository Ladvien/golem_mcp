# Agent test prompt

Paste everything in the fenced block below to any agent connected to the
`golem-mcp` server on the LAN. It exercises every tool, in dependency order,
and ends with renders to look at.

Everything after the fence is written for the agent, not for you.

Three things this prompt deliberately does, all learned the hard way:

- **It does not tell the agent which failures are "expected".** Pre-labelling a
  failure as a machine limit means the agent cannot notice when that stage turns
  into a real defect. It gets the evidence commands instead, and decides.
- **It does not treat tool-reported numbers as acceptance.**
  `frame_alignment_deg` moved 180 → 97 → 9 degrees across three separate fixes
  while the retargeted walk stayed broken.
- **It ends by LOOKING, and says so in as many words.** Every serious defect in
  this project's history was found by rendering the thing, not by measuring it.
  The most recent: a rig scoring gait −0.939 and 104% of source arm swing — the
  best numbers ever recorded here — whose arms were shredded into spikes. Numbers
  passing is not the finish line.

The agent runs on your laptop; the pipeline runs on `big`. Every shell command
below is written as `ssh big ...` for that reason. If you are already on `big`,
drop the prefix.

---

```
You have access to an MCP server called golem-mcp that generates rigged,
animated, game-ready 3D characters. Run a full end-to-end test and report what
works.

Work through the steps in order — later steps consume earlier outputs, so don't
reorder them or run them in parallel. The GPU is shared and serialised by a lock;
one heavy tool at a time.

Record every call's outcome. Do NOT stop at the first failure: note it, keep
going, and give me a pass/fail table at the end. I want to know which things are
broken, not just the first one.

Judge every stage on evidence you gathered, not on what a tool told you about
itself. Where I give you a measurement to run, the measurement decides. Where I
tell you to look at a render, looking decides — and it OVERRULES the numbers.

Shell commands are written as `ssh big ...` because the pipeline runs there. Drop
the prefix if you are already on that host.

THE SUBJECT
Use this exact text as SUBJECT wherever a step refers to it:

  an emberwake herald, a horned fire-priestess with pale ash-grey skin, two long
  curved black horns swept back from the temples, close-cropped white hair,
  wearing a sleeveless deep crimson tunic, polished brass shoulder plates and
  brass greaves, a wide black leather belt, bare arms

It is built for the pipeline rather than for looks: the T-pose in step 2 is
load-bearing (see below), and the six distinct materials give the segmenter parts
to find and the PBR channels something to differentiate.

THE T-POSE IS NOT COSMETIC. Every Mixamo and UE5 clip is authored against a T-pose
rest, and the retarget preserves the character's own rest offset. An arm hanging
at the side is nearly parallel to the axis a walk clip rotates it about, so most
of the clip becomes twist instead of swing. Measured on this exact pipeline, same
rig code, same clip, differing only in the pose of the reference image:

    A-pose reference   rest laterality +0.41   gait -0.295   arm swing 23%
    T-pose reference   rest laterality +0.98   gait -0.939   arm swing 78%

Use this exact suffix wherever a step says POSE_SUFFIX:

  , full body from head to feet, standing in a T-pose with both arms held
  straight out horizontally to the sides at shoulder height, palms down, elbows
  straight, legs shoulder-width apart, feet flat on the ground, the entire figure
  including both feet inside the frame with margin above the head and below the
  feet, centred on a plain flat white background, even studio lighting, no
  shadows, sharp focus, no text, no watermark, no logo, no lettering

Name step 4's output exactly `emberwake_herald`. Later stages that take a `body=`
or `character=` argument resolve against that name, and rig, segmentation and
animation results are published back into its asset directory. Outputs you give a
different name get their OWN asset directory — expected, not a bug.

THE STEPS

1.  health_check. Report free VRAM, then:
      ssh big 'nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv'
    to name anything already holding the card. Generation needs ~16 GB free.

    Also confirm the rigging host is reachable, because rigging does NOT run on
    big — it runs on bmb over ssh:
      ssh big 'ssh -o BatchMode=yes -o ConnectTimeout=10 bmb "echo bmb-ok; sw_vers -productVersion"'
    If that fails, step 9 will fail and you will know why.

2.  generate_image with prompt = SUBJECT + POSE_SUFFIX, output_name
    "emberwake_hero". Then LOOK at the image before going further, and confirm all
    four: arms horizontal (not hanging), both feet inside the frame, no text or
    watermark anywhere, plain background. If any of those is wrong, say so and
    regenerate with a different seed — a bad reference poisons every later stage
    and you will otherwise spend twenty minutes diagnosing the rig instead.

3.  generate_views with prompt = SUBJECT + POSE_SUFFIX, views "front,back",
    output_name "emberwake_views".

    Then run it AGAIN with views "front,back,left,right", output_name
    "emberwake_views4". View count is a real trade-off here, not a dial, and I want
    both measured. On this subject, same prompt and seed:

      2 views   ragged torn hem, correct long black horns, 21 components
      4 views   clean even hem, horns shrunken and gold-tinted, 50 components

    Neither dominates, because the cause is that the views DISAGREE with each
    other — adding sides outvoted a bad hem and then the sides' smaller horns
    outvoted the correct ones. Also note: an older version of this document claimed
    FLUX.2 klein returns left/right as front-facing three-quarters. With the T-pose
    prompt above they came back as genuine flat side profiles. Check which you got
    and say so.

    LOOK at both. The back must actually be a back (no face visible) and must
    match the front's outfit. Then keep the `images_json` field from the result —
    step 5 wants exactly that string.

    The result also carries `view_consistency`. Report it. It measures whether the
    views agree about where garment edges sit on the body, which is the ceiling on
    this whole pipeline: a front hem at mid-thigh against a back hem below the knee
    produced a visibly TORN, ragged skirt, because the generator reconciles two
    garments into one surface. If it names an outlier view, regenerate that view
    (change the seed) before continuing — it costs one image instead of a mesh, a
    rig and an animation.

    If `consistent` is false with no majority, step 5 will REFUSE, by design. That
    is the tool working, not a bug. Say so and regenerate.

4.  generate_3d on the step 2 image, output_name "emberwake_herald".

    This runs TRELLIS.2. Report `geometry.triangles` (expect ~90-100k, NOT ~6k),
    `geometry.components` and `materials`. `materials.metallicRoughnessTexture`
    MUST be true and the images MUST be 2048x2048 — that is the whole reason this
    tool moved off TRELLIS 1, and a diffuse-only result is a regression even if
    the mesh looks fine.

5.  generate_3d_multi_image with images = step 3's `images_json` string,
    output_name "emberwake_herald_mv".

    `images` is a JSON STRING — '["/path/a.png","/path/b.png"]' — not a list.
    Passing a list fails with "the JSON object must be str, bytes or bytearray,
    not list". Step 3's `images_json` is already in that form; pass it through.

    Report `multi_view_steps`. It MUST be greater than zero — it counts denoising
    steps that actually saw more than one view, and it exists because a silently
    single-view run produces a perfectly plausible mesh while reporting itself as
    multi-view. Expect 36 (three samplers x twelve steps).

    Then run it a second time with blend_mode "multidiffusion", output_name
    "emberwake_herald_md", and compare. Neither mode dominates: on this subject
    stochastic gave a cleaner body while multidiffusion recovered detail
    stochastic dropped. Say which you would ship and why, from the renders.

6.  generate_orbit_views on the step 2 image, output_name "emberwake_orbit".

7.  generate_garment with garment "hooded cloak with a deep pointed hood and a
    long open front, heavy dark wool", body "emberwake_herald.glb", output_name
    "emberwake_herald_cloak".

8.  segment_mesh on "emberwake_herald.glb". Report the part count and whether the
    parts correspond to the subject's distinct materials.

    For 6, 7 and 8: if any fails, gather evidence before classifying it. A VRAM
    refusal names its own numbers. Exit code -9 is SIGKILL — check
      ssh big 'journalctl -k --since "20 min ago" | grep -i "killed process"'
    to see whether the kernel OOM killer took it and at what RSS. A Python
    traceback is a defect. Report which you actually observed; do not assume.

    Note that `free` on big is misleading: its swap is ZRAM, a compressed block
    device backed by the same physical RAM, so processes die around 12.7 GB while
    it reports ~25 GB available. An OOM at 12-13 GB is that, not a leak.

9.  rig_model on "emberwake_herald.glb". Expect 100-150 s. Report:

      rigged_on            — must be host bmb, device mps, dtype float32. This
                             box cannot rig at all; if this says anything else,
                             say so loudly.
      skeleton.joints      — expect 27 (a 23-bone Mixamo core plus four tip
                             bones: LeftHand_End, RightHand_End, LeftToe_End,
                             RightToe_End, which exist because Blender gives a
                             CHILDLESS bone its parent's length, so without them
                             the hand and toe bones overshoot the mesh by about
                             their own length). More than 27 means appendage
                             chains were found — correct on a winged or tailed
                             character.
      skeleton.rest_arm_laterality  — expect > 0.9. This is the T-pose check.
                             Below 0.7 the tool emits a warning naming the cause
                             as the reference image, and the rig will SKIN fine
                             and ANIMATE badly.
      skeleton.zero_weight_vertices and skeleton.unweighted_bones — both 0.
      skeleton.warnings    — quote them all.
      passes.rigged_at_proxy_resolution — true is normal at this mesh size.

10. list_animations with search "walk". Report how many clips total and how many
    are usable. A clip is a (file, action) PAIR, so the count is much larger than
    the number of files.

11. apply_animation twice, to prove the name map spans both conventions:
      a) clip "mutant walking"                                  (Mixamo names)
      b) clip "/mnt/codex_fs/game_assets/animation/
         universal_animation_library_v1/Unreal-Godot/UAL1_Standard.glb"
         with action "Walk_Loop"                                (UE5 names)

    Both must be WALKS, because a walk has a checkable ground truth and a dance
    does not. Report `bones_driven` for each. Do NOT report `frame_alignment_deg`
    as evidence of anything — it has moved by 170 degrees across fixes that
    changed nothing observable.

12. MEASURE THE GAIT on both outputs. The repo ships the measurement:

      ssh big '/home/ladvien/segvigen/.venv/bin/python \
        /home/ladvien/golem_mcp/scripts/gait_report.py -- \
        <animated glb> /tmp/gait_<name>'

    It prints a GAIT line and writes eight renders. Acceptance, against the
    source clip's own +1.00 / -0.957 / +19.2 / 74.4:

      rest_arm_laterality      > 0.9     (a mirrored or A-posed rig fails here)
      gait_corr_lhand_lfoot    < -0.85   NEGATIVE = contralateral = correct
      hand_mean_offset_pct_leg POSITIVE  hands in front, like the source's
      hand_swing_pct_leg       > 50      below ~30 means the clip became twist

    The offset term is not redundant with the correlation. `norm()` mean-centres
    both series, so a character walking with its hands parked permanently BEHIND
    its body still scores -0.96. That defect shipped once.

13. NOW LOOK AT IT. This step is not optional and it outranks step 12.

    gait_report.py already wrote /tmp/gait_<name>_front_0..3.png and
    _side_0..3.png. Fetch them and actually view them. Check specifically:

      - are the ARMS intact, or torn into spikes and ribbons? A rig can score
        perfect gait and full swing while its arms shred — that exact case is why
        this step exists. It is a skin-weight defect and no gait number sees it.
      - does the skirt tear away from the body?
      - do the feet plant, or skate/sink?
      - does the mesh still carry its texture, and does brass read as metal
        against cloth? PBR must survive rigging.

    If something looks wrong, localise it before reporting: render the RAW mesh
    and the RIGGED REST pose too. If those are clean and only the animated one is
    broken, it is the weights, not generation and not the bind.

14. list_outputs.

15. REPORT. A pass/fail table over every tool called, then:
      - the four gait numbers for both clips, against the acceptance values
      - which multi-image blend mode you would ship, and why, from the renders
      - every skeleton warning, quoted
      - for each failure: the evidence you gathered and your classification
        (machine limit / defect / bad input), and what you would check next
      - anything that PASSED its numbers but looked wrong. That category has
        historically contained the most important findings in this project.
```
