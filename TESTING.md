# The smoke test

One prompt through every tool, because the tools are a pipeline rather than a
menu: `segment_mesh` needs a mesh `generate_3d` made, `generate_garment` needs a
body to drape onto, `apply_animation` needs a rig `rig_model` made canonical. A
fixture per tool would test each in isolation and miss exactly the handoffs that
break in practice.

```bash
/home/ladvien/trellis/.venv/bin/python scripts/pipeline_smoke_test.py
```

It records failures and keeps going, unlike the tools themselves, which fail
loudly by design — a run tells you *which* things are broken, not just the first.
Report lands at `output/smoke_test.json`; exit code is non-zero if any stage
failed.

Re-testing a late stage without paying ~8 minutes for image generation again:

```bash
scripts/pipeline_smoke_test.py \
    --hero  output/images/emberwake_herald_hero.png \
    --views output/images/emberwake_herald_views_{front,back,left,right}.png \
    --skip  generate_3d rig_model
```

## The prompt

```
an emberwake herald, a horned fire-priestess with pale ash-grey skin, two long
curved black horns swept back from the temples, close-cropped white hair, wearing
a sleeveless deep crimson tunic, polished brass shoulder plates and brass greaves,
a wide black leather belt, bare arms
```

with this appended for the hero shot:

```
, full body, standing in a T-pose with both arms held straight out horizontally to
the sides at shoulder height, palms down, elbows straight, legs shoulder-width
apart, feet flat on the ground, centred on a plain flat white background, even
studio lighting, no shadows, full figure in frame, sharp focus, game asset
reference sheet
```

Every clause earns its place downstream:

| clause | what needs it |
|---|---|
| T-pose wording | `rig_model` needs limb chains to find, and every clip is authored against a T-pose rest. Measured: an A-posed asset retargets a UE5 walk at +0.923 (arm swinging with the same-side leg) against the T-posed asset's −0.951 |
| brass / crimson / leather / skin | `segment_mesh` needs parts to find — six obvious material regions |
| two curved horns | exercises appendage chains: bones outside `mixamorig:` that `apply_animation` must leave undriven |
| plain white background | everything downstream of the image assumes the subject is separable |
| **no** view language | `generate_views` rejects "front view", "in profile" and friends outright — they fight its own per-view conditioning. See `_VIEW_CONFLICTS` |

## Viewing the result

```bash
/home/ladvien/segvigen/.venv/bin/python scripts/assemble_blend.py \
    --out output/showcase.blend \
    --item "1 generate_3d=output/emberwake_herald.glb" \
    --item "2 multi_image=output/emberwake_herald_mv.glb" \
    --item "3 rig_model=output/rigged/emberwake_herald_rigged.glb" \
    --item "4 apply_animation=output/animated/emberwake_herald_rigged_mutant_walking.glb"
```

Lays the stages out side by side, one collection each, feet on the ground, labelled.
Press space in the viewport and the animated one walks.

Three things it handles that are easy to get wrong:

- **`glTF_not_exported`.** SkinTokens' rigged GLBs carry a placeholder the README
  tells you to delete on import. Matching the *name* misses it — the object is
  called `Icosphere`; `glTF_not_exported` names the **collection**. Left in, a
  42-vertex sphere 2.0 m across drives the bounding box of a 1 m character and
  silently sets row spacing, label scale and camera distance for everything.
- **Slotted actions.** Blender 4.4+ evaluates nothing from `animation_data.action`
  alone; the slot has to be bound too. The symptom is every bone at rest, which
  looks exactly like a rig that failed to import.
- **Framing both axes.** Backing the camera off by a multiple of row *width*
  ignores height, which is how the first version cropped everyone's head off.

## Resource limits are reported as failures, and they are not bugs

This box is a 24 GB card and 32 GB of RAM shared with other services. Three stages
are the first to lose that fight:

| stage | needs | fails when |
|---|---|---|
| `generate_orbit_views` | ~19 GB VRAM | anything else holds the card |
| `segment_mesh` | ~18 GB VRAM | same |
| `generate_garment` | ~5 GB RSS, 21 GB virtual | system RAM is short; the kernel OOM killer takes it (exit `-9`) |

`nvidia-smi` and `journalctl -k | grep -i "killed process"` tell you which. The
usual culprit here is `hs-distill-server`, which parks ~5.5 GB of VRAM; stopping it
frees enough for both GPU stages. `generate_3d` needs
`evict_trellis_for_bake=true` whenever the card is shared, or its bake preflight
refuses.
