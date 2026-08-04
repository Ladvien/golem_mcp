# Agent test prompt

Paste everything in the fenced block below to any agent connected to the
`trellis2-mcp` server on the LAN. It exercises every tool, in dependency order,
and ends with a Blender scene to look at.

Everything after the fence is written for the agent, not for you.

Two things this prompt deliberately does NOT do, both learned the hard way:

- It does not tell the agent which failures are "expected". Pre-labelling a
  failure as a machine limit means the agent cannot notice when that stage turns
  into a real defect. It gets the evidence commands instead, and decides.
- It does not treat tool-reported numbers as acceptance. `frame_alignment_deg`
  moved 180 -> 97 -> 9 degrees across three separate fixes while the retargeted
  walk stayed broken. Correctness is measured on the geometry, by the snippet in
  step 12.

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

Judge every stage on evidence you gathered, not on what a tool told you about
itself. Where I give you a measurement to run, the measurement decides.

THE SUBJECT
Use this exact text as SUBJECT wherever a step refers to it:

  an emberwake herald, a horned fire-priestess with pale ash-grey skin, two long
  curved black horns swept back from the temples, close-cropped white hair,
  wearing a sleeveless deep crimson tunic, polished brass shoulder plates and
  brass greaves, a wide black leather belt, bare arms

It is built for the pipeline rather than for looks: the T-pose in step 2 gives the
rigger limb chains to find AND matches the rest pose every animation clip is
authored against, and the six distinct materials give the segmenter parts to find.

Name step 4's output exactly `emberwake_herald`. Later stages that take a `body=`
or `character=` argument resolve against that name, and rig, segmentation and
animation results are published back into its asset directory. Outputs you give a
different name (e.g. `emberwake_herald_mv`) get their OWN asset directory — that
is expected, not a bug.

THE STEPS

1.  health_check. Report free VRAM, and run `nvidia-smi --query-compute-apps=
    pid,used_memory,process_name --format=csv` to name anything already holding
    the card. Steps 6 and 7 need ~18-19 GB; if that is not free, say which
    process is holding it.

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

    The returned key is `local_path`, not `image_path`. Use that in steps 4 and 7.

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

6.  segment_mesh on "emberwake_herald.glb". Report the part count and whether the
    parts correspond to the subject's distinct materials.

7.  generate_orbit_views on the step 2 image, output_name
    "emberwake_herald_orbit".

8.  generate_garment with garment "hooded cloak with a deep pointed hood and a
    long open front, heavy dark wool", body "emberwake_herald.glb", output_name
    "emberwake_herald_cloak".

    For 6, 7 and 8: if any of them fails, gather evidence before you classify it.
    A VRAM refusal names its own numbers. Exit code -9 is SIGKILL — check
    `journalctl -k --since "10 min ago" | grep -i "killed process"` to see whether
    the kernel OOM killer took it, and at what RSS. A Python traceback is a
    defect. Report which of those you actually observed; do not assume.

9.  rig_model on "emberwake_herald.glb". Fits a canonical Mixamo skeleton and runs
    the rigger twice internally, so expect 60-90 s. Report `canonical.core_bones`
    (expect 23), `skeleton.zero_weight_vertices` (expect 0), and
    `canonical.extra_chains`. Extra chains are wing/tail/horn bones outside the
    mixamorig namespace; on this subject they usually come back EMPTY, which is a
    known gap in the appendage classifier rather than a pass.

10. VERIFY HANDEDNESS. This is the bug that cost the most to find, and no tool
    output reveals it — a rig can be perfectly self-consistent and still mirrored
    against the convention every clip uses. With Blender:

      /home/ladvien/segvigen/.venv/bin/python -c "
      import bpy
      bpy.ops.wm.read_factory_settings(use_empty=True)
      bpy.ops.import_scene.gltf(filepath='<the step 9 rigged glb>')
      a=[o for o in bpy.context.scene.objects if o.type=='ARMATURE'][0]
      M='mixamorig:'; R=lambda n: a.pose.bones[M+n].bone.matrix_local.translation
      up=(R('Spine2')-R('Hips')).normalized()
      f=((R('LeftToeBase')-R('LeftFoot'))+(R('RightToeBase')-R('RightFoot')))
      f=(f-up*f.dot(up)).normalized(); lat=up.cross(f); mid=(R('Hips')+R('Spine2'))/2
      print('LeftArm', (R('LeftArm')-mid).dot(lat), 'LeftUpLeg', (R('LeftUpLeg')-mid).dot(lat))
      "

    BOTH numbers must be POSITIVE. That is the convention Mixamo and the UE5
    Mannequin both use. Negative means the rig is mirrored, and arm animation will
    invert while the legs look fine.

11. list_animations with search "walk". Report how many clips total and how many
    are usable. A clip is a (file, action) pair, so the count is much larger than
    the number of files.

12. apply_animation twice, to prove the name map spans both conventions:
      a) clip "mutant walking"                                  (Mixamo names)
      b) clip "/mnt/codex_fs/game_assets/animation/
         universal_animation_library_v1/Unreal-Godot/UAL1_Standard.glb"
         with action "Walk_Loop"                                (UE5 names)

    Both must be WALKS, because a walk has a checkable ground truth and a dance
    does not. Report `bones_driven` for each. Do NOT report `frame_alignment_deg`
    as evidence of anything — it has moved by 170 degrees across fixes that
    changed nothing observable.

    Then MEASURE THE GAIT on each output, and on the two source clips for
    comparison:

      /home/ladvien/segvigen/.venv/bin/python -c "
      import bpy
      def norm(v):
          m=sum(v)/len(v); c=[x-m for x in v]; g=sum(x*x for x in c)**0.5
          return [x/g for x in c] if g>1e-9 else c
      def corr(a,b):
          x,y=norm(a),norm(b); return sum(p*q for p,q in zip(x,y))
      def gait(path):
          bpy.ops.wm.read_factory_settings(use_empty=True)
          bpy.ops.import_scene.gltf(filepath=path)
          sc=bpy.context.scene
          a=[o for o in sc.objects if o.type=='ARMATURE'][0]
          act=bpy.data.actions[0]
          if a.animation_data is None: a.animation_data_create()
          a.animation_data.action=act
          if getattr(act,'slots',None): a.animation_data.action_slot=act.slots[0]
          M='mixamorig:'; R=lambda n: a.pose.bones[M+n].bone.matrix_local.translation
          up=(R('Spine2')-R('Hips')).normalized()
          f=((R('LeftToeBase')-R('LeftFoot'))+(R('RightToeBase')-R('RightFoot')))
          f=(f-up*f.dot(up)).normalized()
          s,e=(int(round(v)) for v in act.frame_range)
          t={'LeftHand':[], 'LeftFoot':[]}
          for fr in range(s,e+1):
              sc.frame_set(fr); bpy.context.view_layer.update()
              h=a.pose.bones[M+'Hips'].matrix.translation
              for n in t: t[n].append(float((a.pose.bones[M+n].matrix.translation-h).dot(f)))
          return corr(t['LeftHand'], t['LeftFoot'])
      print(gait('<animated glb>'))
      "

    This is left hand against left foot, measured relative to the hips and
    projected on the character's OWN forward axis, derived from the toes. It must
    be NEGATIVE: in a real walk the left arm opposes the left leg. Positive means
    the arm swings with the same-side leg, which is a broken gait however healthy
    the tool output looked. The source clips measure about -0.96; anything
    negative and within ~0.3 of that is fine.

    Do not substitute your own metric for this one. Measuring along a WORLD axis
    instead of the character's own gives a number that flips sign depending on
    which way the character happens to face, and it will mislead you.

13. list_outputs and free_gpu.

IF YOU ALSO HAVE SHELL ACCESS

14. If step 6 succeeded, split the mesh into per-part objects:

      /home/ladvien/segvigen/.venv/bin/python \
        /home/ladvien/trellis2_mcp/scripts/split_by_parts.py \
        --mesh <asset dir>/asset.glb \
        --labels <asset dir>/asset_face_labels.npy \
        --out-dir <asset dir>

15. Build the Blender scene and tell me the path:

      /home/ladvien/segvigen/.venv/bin/python \
        /home/ladvien/trellis2_mcp/scripts/assemble_blend.py \
        --out /home/ladvien/trellis/output/emberwake_showcase.blend \
        --item "1 generate_3d=<the step 4 glb>" \
        --item "2 multi_image=<the step 5 glb>" \
        --item "3 rig_model=<the step 9 rigged glb>" \
        --item "4 walk=<the step 12a animated glb>"

    It lays the stages out side by side, feet on the ground, labelled, with the
    frame range set so the animated one plays on spacebar.

WHAT TO GIVE ME

  * a pass/fail table, one row per step, with elapsed time
  * the handedness numbers from step 10 and the gait numbers from step 12, each
    against the source clips
  * for each failure: defect or machine limit, and the specific evidence — the
    VRAM figures, the OOM-killer line, or the traceback. "Known issue" is not
    evidence
  * the .blend path from step 15
  * anything a tool reported that contradicted its own documentation, and anything
    where a tool reported success but the measurement disagreed
```
