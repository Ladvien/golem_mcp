#!/usr/bin/env python
"""Generate a character from SEVERAL views with TRELLIS.2, keeping its PBR.

    trellis2_multi_image.py --images a.png b.png c.png --out-dir output --name hero

WHY THIS IS NOT A THREE-LINE CHANGE
-----------------------------------
The plan for this said "TRELLIS.2's get_cond() already accepts a list". It does -
and that is not multi-view conditioning. Traced:

    get_cond(image, resolution) -> self.image_cond_model(image)
    DinoV3FeatureExtractor.__call__ -> "A tensor of shape (B, N, D)"   B = images

so a list is a BATCH of independent images, and `run()` passing `[image]` is just
wrapping its single image. TRELLIS.2 has no multi-image support anywhere: the only
"multiview" symbol in the tree is a render utility. TRELLIS 1's run_multi_image,
which generate_3d_multi_image has been using, is a real feature TRELLIS.2 dropped.

So it is ported here, by the same mechanism TRELLIS 1 uses - per-denoising-step
conditioning, not a blended input image. Both engines expose the same sampler
shape (`_inference_model(model, x_t, t, cond, **kw)` with CFG and guidance-interval
mixins layered over a FlowEuler base), so the port is a transcription rather than a
redesign.

  stochastic       each denoising step is conditioned on ONE view, cycling.
  multidiffusion   every step averages the model's prediction across all views.

WHERE THE PATCH GOES, AND WHY IT MATTERS
----------------------------------------
Below classifier-free guidance, on the FlowEuler base - NOT on the sampler's
outermost _inference_model.

This is forced by the checkpoint's own parameters: guidance_rescale is 0.7 for the
sparse-structure sampler and 0.5 for the shape sampler, and rescale divides by the
standard deviation of the prediction. That makes CFG NON-LINEAR, so averaging
guided predictions is not the same as guiding an averaged prediction. Patching
underneath means pred_pos arrives already averaged and the vendored code applies
guidance and rescale exactly once, unmodified. It also evaluates the negative
prompt once per step rather than once per view.

The mixins reach the base through `super()._inference_model(...)`, which resolves
on the CLASS and ignores instance attributes - so the patch is applied to
FlowEulerSampler itself, inside a context manager that restores it.
"""

import argparse
import contextlib
import json
import os
import sys
import time
from pathlib import Path

REPO = os.environ.get("SEGVIGEN_REPO", "/home/ladvien/segvigen/repo")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, REPO)

from trellis2_character import materials, topology  # noqa: E402  (after sys.path)


@contextlib.contextmanager
def multi_image_conditioning(pipeline, images, mode):
    """Condition every sampler in `pipeline` on all of `images` for this block.

    Two patches, both reverted on exit:

      1. pipeline.get_cond - an INSTANCE attribute, which shadows the method for
         `self.get_cond(...)`. run() calls it with its own single image at each
         resolution it needs; this ignores that argument and encodes all the views
         instead, so run()'s orchestration (pipeline types, the cascade) is reused
         verbatim rather than reimplemented here.

         neg_cond is sliced back to one. get_cond builds it as zeros_like(cond), so
         it would otherwise arrive with a batch of N identical negatives and the
         guidance step would try to pair them off against a single x_t.

      2. FlowEulerSampler._inference_model - a CLASS attribute, because the
         guidance mixins reach it through super(). See the module docstring.
    """
    from trellis2.pipelines.samplers.flow_euler import FlowEulerSampler

    original_get_cond = pipeline.get_cond
    original_inference = FlowEulerSampler._inference_model
    # `multi` counts denoising steps that actually saw more than one view. If a
    # future refactor stops get_cond being shadowed - it is an instance attribute
    # over a method, which is exactly the kind of thing that breaks quietly - every
    # cond arrives with batch 1, this patch becomes a no-op, and the run still
    # produces a perfectly plausible single-view mesh. The caller asserts on it.
    step = {"n": 0, "multi": 0}

    def get_cond(image, resolution, include_neg_cond=True):
        cond = original_get_cond(images, resolution, include_neg_cond)
        if "neg_cond" in cond:
            cond["neg_cond"] = cond["neg_cond"][:1]
        return cond

    def inference(self, model, x_t, t, cond=None, **kwargs):
        # Single-view conditioning reaches here too - the negative prompt every
        # step, and the positive one whenever guidance collapses to strength 1
        # outside its interval. Those must pass through untouched.
        if cond is None or cond.shape[0] <= 1:
            return original_inference(self, model, x_t, t, cond, **kwargs)

        step["multi"] += 1
        if mode == "stochastic":
            index = step["n"] % cond.shape[0]
            step["n"] += 1
            return original_inference(self, model, x_t, t, cond[index:index + 1], **kwargs)

        preds = [original_inference(self, model, x_t, t, cond[i:i + 1], **kwargs)
                 for i in range(cond.shape[0])]
        return sum(preds) / len(preds)

    pipeline.get_cond = get_cond
    FlowEulerSampler._inference_model = inference
    try:
        yield step
    finally:
        FlowEulerSampler._inference_model = original_inference
        try:
            del pipeline.get_cond          # unshadow the class method
        except AttributeError:
            pipeline.get_cond = original_get_cond


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, nargs="+",
                    help="two or more views of the SAME object")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--name", help="output stem (default: the first image's stem)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="stochastic", choices=["stochastic", "multidiffusion"])
    ap.add_argument("--pipeline-type", default="512",
                    choices=["512", "1024", "1024_cascade", "1536_cascade"])
    ap.add_argument("--simplify-target", type=int, default=300000)
    ap.add_argument("--decimation-target", type=int, default=100000)
    ap.add_argument("--texture-size", type=int, default=2048)
    args = ap.parse_args()

    paths = [Path(p) for p in args.images]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise SystemExit("image(s) not found: " + ", ".join(missing))
    if len(paths) < 2:
        raise SystemExit(
            f"multi-image generation needs at least two views; got {len(paths)}. "
            "Use trellis2_character.py for a single image."
        )
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or paths[0].stem
    out_glb = out_dir / f"{stem}.glb"

    # ASSIGNED, not setdefault - see trellis2_character.py. The MCP server used to set
    # ATTN_BACKEND=xformers at import (for TRELLIS 1, since removed) and a subprocess
    # inherited it, so setdefault silently kept the wrong backend and this failed with
    # an empty error when run through the tool but worked by hand.
    os.environ["ATTN_BACKEND"] = "sdpa"
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

    os.chdir(REPO)   # pipeline.json is opened at a relative path

    import o_voxel
    import torch
    import trellis2_common as t2
    from PIL import Image

    started = time.time()
    print(f"[1/4] loading TRELLIS.2-4B ({args.pipeline_type})", flush=True)
    pipeline, dropped = t2.load_pipeline(args.pipeline_type)

    print(f"[2/4] preprocessing {len(paths)} views", flush=True)
    views = [pipeline.preprocess_image(Image.open(p)) for p in paths]

    print(f"[3/4] generating, mode={args.mode}, seed={args.seed}", flush=True)
    with multi_image_conditioning(pipeline, views, args.mode) as conditioning:
        # preprocess_image=False: the views are already preprocessed above, and the
        # image passed here is ignored by the patched get_cond anyway.
        mesh = pipeline.run(views[0], seed=args.seed, preprocess_image=False,
                            pipeline_type=args.pipeline_type)[0]
    if conditioning["multi"] == 0:
        raise SystemExit(
            "FATAL: not one denoising step saw more than one view, so this ran as a "
            "single-image generation while reporting itself as multi-image. The "
            "get_cond shadow or the FlowEulerSampler patch is no longer taking "
            "effect - see multi_image_conditioning."
        )
    peak_gb = torch.cuda.max_memory_allocated() / 1e9

    raw_faces = int(len(mesh.faces))
    mesh.simplify(args.simplify_target)
    print(f"[4/4] exporting ({raw_faces} -> {len(mesh.faces)} faces)", flush=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size, aabb=[[-0.5] * 3, [0.5] * 3],
        decimation_target=args.decimation_target, texture_size=args.texture_size,
        remesh=True, verbose=False,
    )
    glb.export(str(out_glb))

    topo = topology(str(out_glb))
    mats = materials(str(out_glb))

    welded = topo["position_welded"]
    if welded["boundary_edge_pct"] > 5.0:
        raise SystemExit(
            f"FATAL: {out_glb} is {welded['boundary_edge_pct']}% boundary edges even "
            f"after welding on position. A character should come back closed."
        )
    if not mats.get("metallicRoughnessTexture"):
        raise SystemExit(
            f"FATAL: {out_glb} has no metallicRoughnessTexture. Emitting PBR is the "
            "reason this runs TRELLIS.2 rather than TRELLIS 1's run_multi_image."
        )

    report = {
        "source_images": [str(p) for p in paths],
        "num_views": len(paths),
        "blend_mode": args.mode,
        "multi_view_steps": conditioning["multi"],
        "character_glb": str(out_glb),
        "seed": args.seed,
        "pipeline_type": args.pipeline_type,
        "faces_before_simplify": raw_faces,
        "topology": topo,
        "materials": mats,
        "peak_vram_gb": round(peak_gb, 2),
        "dropped_models": dropped,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (out_dir / f"{stem}_multi_image.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"MULTI_IMAGE_OK {out_glb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
