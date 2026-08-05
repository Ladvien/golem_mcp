# Autorigging: everything that went wrong, and where I would look next

Written at the end of a long debugging session, for whoever picks this up — likely
future me. Every number here was measured, and the measurement command is in git
history if you want to re-run it. Where I got something wrong, I have said so,
because the wrong turns cost more than the fixes and are worth not repeating.

## Candid summary

The rig is still not good, and I do not think the remaining distance is more
tuning. Three problems compound, and only one of them is really "rigging":

1. **The generated mesh is not a connected surface.** It is a few hundred
   disconnected patches. No surface-based skinning algorithm can work on that.
2. **The skeleton generator is being used as something it is not.** TokenRig
   produces a per-asset skeleton with varying topology and no names. We use it as
   a landmark detector and impose a Mixamo template on top.
3. **Every placement rule is a proportion measured off one reference rig.** That
   is the approach the literature specifically says does not generalise, and we
   confirmed it: the same rule that put a human's shoulder right put a dwarf's at
   0.67 H.

Fixing (2) and (3) properly means replacing our fitter with a learned pose prior.
Fixing (1) may be a one-line mesh repair. I would start there.

---

## 0. The finding I would research first: the mesh is not a surface

Measured on the TRELLIS output, before any rigging touches it:

| | emberwake_tpose | female_base_v5 | forge_warden |
|---|---|---|---|
| vertices | 7,730 | 6,272 | 9,513 |
| connected components | **316** | 123 | 236 |
| largest component | 244 verts (**3%** of mesh) | 777 | 289 |
| edges used by only ONE face | **29%** | 19% | — |
| Euler characteristic V−E+F | **312** | 106 | — |

A single closed surface has χ ≈ 2. Welding vertices at tolerances from 0 to 3 mm
on a 1 m character changes nothing — vertex count does not move, component count
does not move. These are not unwelded duplicates. The surface is genuinely made of
hundreds of separate open patches.

**Why this matters more than anything else in this document.** Skin weights are
normally propagated across the surface — bone heat diffusion, geodesic distance,
anything that walks edges. With 29% of edges being boundaries and no component
larger than 3% of the mesh, there is nothing to propagate along. Each patch gets
weights independently, neighbouring patches disagree, and they separate the moment
a limb rotates. That is exactly the "skirt and boots tear away from the body"
symptom that has survived every rigging fix in this document.

Things to try, cheapest first:

- **`rig_model(use_postprocess=True)`.** This parameter already exists and its own
  description is *"Voxel-based skin cleanup. Enable when weights bleed across
  disconnected parts."* It is default `False` and **has never once been tried in
  this project.** It is one boolean.
- **Repair the mesh before rigging.** Remesh to a single manifold — voxel remesh,
  Poisson, or `trimesh`/Instant Meshes — then rig. Costs surface detail; may cost
  the texture, since UVs would need reprojecting.
- **Bind by proximity in 3D rather than along the surface.** Geodesic voxel binding
  (Maya) exists precisely for meshes like this. Blender's "Bone Envelope" or a
  voxel heat method is the equivalent.

Also worth checking whether `generate_3d`'s `simplify=0.95` decimation is what
shatters it. Nobody has looked at the pre-decimation mesh.

---

## 1. What the pipeline actually does

```
prompt ─ generate_image ─→ hero PNG
             ↓
        generate_3d (TRELLIS) ─→ asset.glb   (textured, 4-10k verts, SHATTERED)
             ↓
        rig_model:
          pass 1  TokenRig, no skeleton     → a generated skeleton, used ONLY as
                                              a landmark source
          fit     canonical_skeleton.py     → Mixamo template placed from those
                                              landmarks, + texture transfer
          pass 2  TokenRig --use_skeleton   → skin weights against OUR skeleton
          restore-names                     → TokenRig drops names; re-applied by index
          orient_bones                      → point each bone at its child
             ↓
        apply_animation ─→ retarget a Mixamo/UE5 clip onto it
```

Two TokenRig passes, ~70 s total. The canonical skeleton is 27 bones: a 23-bone
`mixamorig:` core, four tip bones, and named `wing_`/`tail_`/`horn_` chains for
anything else the classifier finds.

### Why this shape, and why it is shaky

TokenRig will not give us an animatable rig directly. Its README documents that the
same mesh and seed produces 47 vs 44 joints, the topology varies per asset, and the
bones are unnamed (`bone_0…bone_N`). No clip can drive that, and neither Unreal's
IK Retargeter nor Unity's Humanoid avatar can consume it.

So we invert its role: run it, read the limb chains out of whatever it produced,
and resample a fixed Mixamo skeleton along them. That works — but it inherits
TokenRig's errors and adds our own, and every placement decision is a hand-tuned
constant:

| constant | value | where it came from |
|---|---|---|
| `SHOULDER_FRAC` | 0.82 | human proportion; the generated chain starts at the clavicle root at 0.88–0.95 H |
| `HIP_ABOVE_FEMUR` | 0.058 | measured off one Mixamo rig |
| `TOE_TIP_FRAC` | 0.077 | same rig |
| `t_hip` clamp | ≤ 0.10 | tuned after an unclamped version put a dwarf's femur at 0.42 H |
| `t_sh` clamp | 0.05–0.35 | tuned after a lateral-offset rule put a dwarf's shoulder at 0.67 H |
| elbow | midpoint of shoulder→hand | assumed |

Both papers we read call this out. HumanRig (arXiv 2412.02317) on geometric and
GNN-based rigging: they *"struggle with complex 3D models, particularly those
generated by AI … irregular shapes, detailed clothing or accessories, and
differing head-to-body ratios."* Their answer was a learned 2D pose prior. Rigel3D
(arXiv 2605.13129) makes the same point about semantic joint labels.

---

## 2. Defects found and fixed

Measurements as fractions of leg length or body height, against a real Mixamo rig
where one applies.

| defect | evidence | fix |
|---|---|---|
| **Up-axis swap** | asset extents `[0.694, 1.0, 0.365]` vs fit output `[0.694, 0.365, 1.0]` | trimesh hands back glTF Y-up; a bpy scene reads it as Z-up; the exporter then converts again. Pre-convert before `Asset.from_data` |
| **Lateral axis hardcoded** | arm-tip separation per axis: `[0.411,0,0]`, `[0.609,.035,.016]`, `[0.375,0,0]` — lateral is **X** on 3 of 4 characters, but the code assumed **Z** | derive it per character from branch spread. Every "lateral" measurement had been reading DEPTH |
| **Handedness mirrored** | every Left bone in both clip libraries sits at **+lat**; ours sat at **−lat** | flip the side test. A mirror is not a rotation, so no retarget can compensate |
| **Shoulder at the clavicle root** | 0.88–0.95 H, i.e. ear height | anchor on height (0.82 H) rather than chain parameter |
| **Femur head in the belly** | 0.58–0.60 H vs ~0.52 target | sample down the leg chain, clamped |
| **Pelvis floating above the femurs** | Hips at **+21.5%** above femur midpoint vs Mixamo's **+5.8%** | place Hips against the femoral heads |
| **Leaf bones overshoot the mesh** | hand 26.0% of leg vs Mixamo 17.1%; toe 15.6% vs 7.7% — each exactly its parent's length, because Blender gives a childless bone its parent's length | add `Hand_End` / `Toe_End` tips |
| **Bone axes not along limbs** | 8 of 18 bones >20° off the direction to their child, worst **116°** | `orient_bones.py`, recomputing inverseBindMatrices so bind pose survives (0.26 µm max shift) |
| **Textures dropped** | source `materials=1`, fit output `materials=0` | SkinTokens' `Asset` has no UV/material field at all. Transfer them onto the fitted GLB face-corner by face-corner |
| **A-pose rest breaks retargeting** | A-pose: UE5 walk gait **+0.923** (wrong sign), swing 5%. T-pose: **−0.951**, 27% | generate in T-pose; every clip is authored against a T-pose rest |
| **Geometric landmark fitting** | failed differently on all three characters | deleted, not disabled |

---

## 3. Still open

- **Skin tearing** — skirt and boots separate under large rotations. See §0; I now
  believe this is the mesh, not the rig.
- **Femoral heads too far apart** — 31.3% of leg length vs Mixamo's 19.9%, which
  leaves a Hips→UpLeg gap of 17.2% against its 11.5%. Inherited from where the
  generated skeleton branches its legs. Narrowing them moves the thigh pivot, so
  it is a deformation change, not a cosmetic one.
- **Arm swing amplitude** — 60.5% of the source clip's, against a hand mean offset
  that is now correct (+17.3% vs +19.2%).
- **Appendage classifier** — the horns get no chain at all on `emberwake_herald`;
  `succubus_warden` gets `horn_L`, `horn_R`, `tail`, `wing_R` but misses `wing_L`.
- **Hand tip too short** — 10.3% of leg against Mixamo's 17.1%, because the arm
  chain's last 10% is short. Overshooting was worse, but this undershoots.
- **`scp610_midstage_v2` cannot be rigged** — 34,670 verts, 3× the next largest
  asset and outside TokenRig's documented 1k–20k range. OOM-killed at 7.2 GB RSS.
- **The curated library is A-pose.** The five re-rigged characters have correct
  handedness but an A-pose rest, so Mixamo clips work and UE5 clips do not. Only
  regeneration in T-pose fixes that, and it replaces hand-curated meshes.

---

## 4. Ruled out — do not re-investigate

Each of these cost a rig and a retarget to eliminate.

1. **Retarget formulation.** Four tried: rest-relative delta (+0.874 gait,
   geometry intact), absolute rotation (−0.956, geometry shattered), swing-only by
   bone axis (−0.977, contorted), swing-only by joint direction (−0.960, abduction
   near-exact, still contorted). **Every variant that satisfies the gait metric
   destroys the pose**, because direction-only aiming leaves twist unconstrained
   and roll accumulates through the spine. Delta is retained.
2. **Frame alignment.** Maps forward to forward at +1.000. Its 97° magnitude is
   mostly the Mixamo FBX's Y-up armature space converting to our Z-up.
3. **Bone axes as a cause of retargeting error.** Orienting every bone produced
   *byte-identical* retarget output. The rest-relative delta cancels bone-axis
   convention. (They still matter for the viewport and for hand animation.)
4. **Bone roll.** Roll gaps against the source are large and unpatterned —
   `LeftLeg` has the largest at 175.7° and its limb retargets correctly.
5. **Spine / torso.** Shoulder phase relative to the foot has the correct sign.
6. **Side-label self-consistency.** Necessary but not sufficient — the rig was
   internally consistent while being mirrored against the world.

---

## 5. Metrics that lied, and the methodology lesson

This is the part I would most want a successor to read. Five separate times, a
number said "fine" while the thing was visibly broken. Every real defect in the
back half of this session was found by *looking*, not by measuring.

| metric | how it lied |
|---|---|
| `_skeleton_report` symmetry | mirrors **local** node translations, so it is not rotation-invariant. Read 0.913 and 0.652 for the *same skeleton*. I quoted 0.913 as a quality win; the meaningful world-space number was 1.000 both times |
| `frame_alignment_deg` | moved 180 → 97 → 9 across three fixes while the walk stayed broken |
| gait correlation | mean-centres both series, so it is **structurally blind to a constant offset**. Hands parked permanently behind the character still score −0.96. That defect shipped and was caught by eye |
| any world-axis motion metric | flips sign with the character's facing. Two of us independently built one and got confused by it |
| every headless render I made | drew the mesh, never the armature — so a rig with bone axes 116° off its limbs looked perfect in all of them |

The lesson: **build the observation harness before the seventh hypothesis, not
after.** Seven plausible causes were falsified for the arm-inversion bug, each
costing a rig and a retarget. What finally solved it was driving one bone with a
synthetic rotation of known sign and watching where the hand went — a two-minute
experiment with no GPU that could have been run first.

Two of my own errors worth recording:

- I dismissed `orient_bones.py` as "does not affect retargeting" and left it
  unwired. True, and the wrong call — the rig shipped *looking* broken and could
  not be hand-animated.
- I ran the T-pose experiment while the handedness bug was still live, concluded
  the rest-pose hypothesis was refuted, and moved on. It was confounded. A failed
  experiment on top of an unfixed bug proves nothing.

---

## 6. Where I would research

**The mesh, first.** Everything in §0. If the tearing is connectivity, no amount of
skeleton work fixes it, and it is the most visible remaining defect.

**Replace the fitter with a learned prior.** This is the real answer to §1.

- **HumanRig** (arXiv 2412.02317) — closest to our problem. Aligns meshes to a
  standard Mixamo skeleton; their PGSE renders a front view, runs a fine-tuned
  RTMPose, and lifts to 3D with the known camera. Trained on 11,434 meshes. That
  would replace every hand-tuned constant in the table in §1.
- **Rigel3D** (arXiv 2605.13129) — semantic joint labels for generated skeletons.
- **RigNet** — what both papers critique; useful for understanding why
  template-free skeletons fail for animation.
- **Mixamo's own auto-rigger** — the commercial baseline that works. Worth being
  honest about whether uploading to it beats anything we build.
- **UniRig / MagicArticulate / ArticulateAnything** — newer work in the same space
  worth a literature sweep; I have not read them.

**Skinning as a separate problem from skeleton placement.** Even a perfect skeleton
with bad weights tears. Look at geodesic voxel binding, voxel heat diffusion, and
learned skinning (RigNet's skinning branch). Note that TokenRig's own README calls
skinning *"the part the model is genuinely good at"* — which suggests the weights
may be fine and the mesh is the problem, again pointing at §0.

**A-pose vs T-pose as a generation-time decision.** It is now the documented
default and it is load-bearing, not cosmetic: it changed a UE5 walk from +0.923
(arms swinging with the same-side leg) to −0.951.

---

## Appendix: how to reproduce any measurement here

Everything is in `git log`. The useful entry points:

- `scripts/canonical_skeleton.py fit --mesh X --from-rig Y --out Z` — the fitter
- `scripts/orient_bones.py --rigged X --out Y` — bone axes, prints before/after
- `scripts/retarget_animation.py --character X --clip Y --out Z`
- `AGENT_TEST_PROMPT.md` — end-to-end test with the handedness and gait checks
  built in, including the mean-offset check the correlation is blind to
- `~/.claude/plans/can-you-make-a-shimmering-russell.md` — the running log, with
  every falsified hypothesis and its evidence
