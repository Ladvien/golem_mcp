# Autorigging: everything that went wrong, and where I would look next

Written at the end of a long debugging session, for whoever picks this up — likely
future me. Every number here was measured, and the measurement command is in git
history if you want to re-run it. Where I got something wrong, I have said so,
because the wrong turns cost more than the fixes and are worth not repeating.

## Candid summary

The rig is still not good, and I do not think the remaining distance is more
tuning. Three problems, in ascending order of how much work they are:

1. **A hard skin-weight seam at the hip.** 931 of 14,679 edges (6.3%) jump more
   than 0.5 in weight, the worst of them at Hips↔UpLeg — which is where the skirt
   is, and what "the skirt tears away" actually is. Localised and directly
   fixable by smoothing. NOT a mesh defect: the mesh is a single closed manifold,
   see the corrected §0, where I originally got this badly wrong.
2. **The skeleton generator is being used as something it is not.** TokenRig
   produces a per-asset skeleton with varying topology and no names. We use it as
   a landmark detector and impose a Mixamo template on top.
3. **Every placement rule is a proportion measured off one reference rig.** That
   is the approach the literature specifically says does not generalise, and we
   confirmed it: the same rule that put a human's shoulder right put a dwarf's at
   0.67 H.

(1) is a weekend of work on a graph that demonstrably exists. (2) and (3) mean
replacing the fitter with a learned prior — RigAnything or HumanRig, with the
labelling trade-off spelled out in §6. I would do (1) first: it is the most
visible remaining defect and the cheapest to attack.

---

## 0. CORRECTED — the mesh is fine. The skinning has a hard seam at the hip.

**The first version of this section was wrong, and a companion review of the
home-still corpus caught why.** It is left corrected rather than deleted, because
the mistake is instructive.

### What I claimed, and why it was wrong

I reported the TRELLIS meshes as "not connected surfaces" — 316 components, 29% of
edges used by a single face, Euler characteristic 312 — and concluded that no
surface-based skinning could work. The evidence was a weld sweep from 0 to 3 mm
that moved neither vertex nor component count.

That sweep used **vertex-to-vertex** distance, which is insensitive to this failure
mode at *every* tolerance, so a flat response across it was never evidence either
way. (Liu, Zhang & Yuksel, arXiv 2409.15458 §4.1.1, make exactly this point: patches
that abut can still have large vertex-to-vertex distance depending on how each was
discretised.) `trimesh.merge_vertices` also preserves UV and normal splits by
default, so it will not weld a texture seam no matter what tolerance it is given.

Welding on **position alone**:

| | as loaded | welded on position |
|---|---|---|
| vertices | 7,730 | **4,889** (2,841 duplicates, 37%) |
| connected components | **316** | **1** |
| boundary edges | 5,050 (29%) | **0 (0.0%)** |
| Euler characteristic | 312 | **−4** |

It is a single closed manifold surface. The "316 components" were UV-atlas seam
duplicates. **No mesh repair is needed.** Cross-component vertex-to-vertex distance
measures 0.00 mm — the patches share vertex positions exactly.

### The seam hypothesis is also refuted

The obvious follow-up was that duplicated seam vertices might receive *different*
skin weights and split under motion. Measured on all 4,889 coincident groups in the
rigged GLB, weight disagreement within a group (L1, 0 = identical, 2 = disjoint):

    median 0.0000    p90 0.0000    max 0.0000

TokenRig assigns coincident vertices identical weights. There are no seam cracks.

### What the skinning problem actually is

Weight discontinuity across mesh edges, on the welded topology:

    median 0.1008   p90 0.4194   p99 0.8709   max 1.5738
    edges jumping >0.5:  931 (6.34%)
    edges jumping >1.0:   76 (0.52%)

    worst boundaries: RightUpLeg↔Hips (14), Hips↔LeftUpLeg (7),
                      RightLeg↔RightUpLeg (6), Head↔HeadTop_End (6)

The sharpest transitions are at the **hip/thigh junction** — precisely where the
skirt is, and precisely what "the skirt tears away from the body" looks like. The
weights go near-binary across a handful of edges, so the skirt splits along that
line when the thigh swings. It is a weight-smoothness problem, localised, and the
mesh being a genuine manifold means it is directly fixable.

### `use_postprocess=True` — tried, and it makes this worse

The one untried boolean, whose description is *"voxel-based skin cleanup, enable
when weights bleed across disconnected parts"*:

| | median | p90 | p99 | max | >0.5 | >1.0 |
|---|---|---|---|---|---|---|
| OFF | 0.1008 | 0.4194 | 0.8709 | 1.5738 | 6.34% | 0.52% |
| **ON** | 0.0819 | 0.5606 | 1.3594 | 1.9839 | **12.09%** | **3.07%** |

It sharpens weights toward binary. The median falls because more vertices become
fully assigned, but hard boundaries **double** and near-binary edges go up sixfold.
Exactly the wrong direction. Leave it off.

### What I would do instead

**Laplacian smoothing of the skin weights** over the position-welded topology,
constrained to preserve the partition of unity. The mesh is a closed manifold, the
problem is 931 edges out of 14,679, and the fix is a well-understood diffusion on a
graph that demonstrably exists. Nothing volumetric is required.

The corpus review recommended virtual-edge merging (FA-QEM, arXiv 2605.14029),
winding-number tet meshing plus Bounded Biharmonic Weights, and voxel-grid binding
(Kavan & Sorkine 2012). All three are sound, and all three are aimed at a mesh
defect that does not exist here. Worth keeping in mind if a future asset genuinely
is shattered — but the measurement to run first is the position-weld above, not a
vertex sweep.

One thing from that review does hold and is worth recording: the **facet
orientation check came back clean** — 0 of 12,154 manifold edges are wound
inconsistently — so the winding-number path is not gated shut if it is ever needed.

## 1. What the pipeline actually does

```
prompt ─ generate_image ─→ hero PNG
             ↓
        generate_3d (TRELLIS) ─→ asset.glb   (textured, 4-10k verts, closed manifold
                                              once welded on position; as shipped it
                                              carries ~37% UV-seam duplicates)
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

## 2b. Fixed after this document was first written

All measured, all on a fresh asset built end to end by the current pipeline.

| fix | evidence |
|---|---|
| **Skin weight seam** | edges jumping >0.5 in weight: 6.34% -> **0.81%**; over 1.0: 0.52% -> **0.00%**, median unmoved. Laplacian diffusion over the position-welded topology, top-4 truncated once at the end |
| **Femoral separation** | 31.3% of leg -> **20.1%** against Mixamo's 19.9%; Hips->UpLeg gap 27.2% -> **11.7%** against 11.5% |
| **Shoulder placement** | was anchored on HEIGHT, which cannot discriminate on a T-pose (constant height along the arm) and put the joint out near the elbow. Now anchored on lateral offset, 16.9% of leg |
| **Wrist and elbow** | wrist one hand-length back from the chain end rather than a fixed t=0.9; elbow at 46% of the shoulder-wrist span, not the midpoint. shoulder->wrist 49.6% -> 55.7-61.0% against 64.4% |
| **Arm swing** | 0.605 -> **0.703** of source. Joint rotation magnitudes match the source to 98%, so the deficit was lever arm, not retargeting |
| **Appendage sides** | succubus_warden now resolves wing_L, which the `size < 2` filter had been dropping. Sides come from mirrored pairs rather than the sign of a near-zero lateral mean |
| **generate_orbit_views** | the documented BiRefNet dtype bug had never been REACHED - the VRAM preflight refused first every time. With the card free it fails at "Input type (float) and bias type (c10::Half)"; BiRefNet's config declares fp16 and newer transformers honours it. Forced to float32, in the checkout and in install_mvadapter.sh's edits list. Returns all six azimuths |
| **generate_garment** | no code defect at all. It succeeds whenever there is RAM; it had only ever been run under memory pressure |

Final acceptance on a fresh asset: handedness LeftArm +17.5% / LeftUpLeg +10.5%
(both must be positive), femur separation 20.1% against 19.9%, Hips->UpLeg gap
11.7% against 11.5%, gait -0.947 against the source's -0.957, hand mean offset
+19.0% against +19.2%.

---

## 3. Still open

- ~~Skin tearing~~ — **fixed**, see §2b.
- ~~Femoral heads too far apart~~ — **fixed**, see §2b.
- **Arm swing amplitude** — improved to ~0.64-0.70 of the source but not closed.
  Rotation magnitude (98% of source) and lever arm (0.947 of source) are both
  eliminated as causes, so roughly a quarter of the deficit remains unexplained.
  Hand mean offset is exact (+19.0% vs +19.2%).
- **Appendage classifier** — `wing_L` is fixed, but `horn_R` still over-splits into
  15 chains on `succubus_warden`, and horned characters get NO extras at all
  because the highest leaf is a horn tip, so the horn is absorbed into the spine.
  That also makes `HeadTop_End` a horn tip and compresses every height fraction
  measured against it. Choosing the spine by "most central path among the tallest
  leaves" was tried and reverted - it broke succubus_warden without fixing
  emberwake.
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
