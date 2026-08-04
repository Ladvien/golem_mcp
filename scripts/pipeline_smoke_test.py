#!/usr/bin/env python
"""End-to-end smoke test: one prompt through every tool this MCP exposes.

    pipeline_smoke_test.py [--name emberwake_herald] [--skip generate_orbit_views]

Run with the TRELLIS venv, which is where the server package lives:

    /home/ladvien/trellis/.venv/bin/python scripts/pipeline_smoke_test.py

WHY ONE PROMPT AND NOT A FIXTURE PER TOOL
-----------------------------------------
The tools are a pipeline, not a menu: segment_mesh needs a mesh generate_3d made,
generate_garment needs a body to drape onto, apply_animation needs a rig that
rig_model made canonical. A per-tool fixture would test each in isolation and miss
exactly the handoffs that have broken in practice - a returned key renamed, a
published filename gaining a second extension, a rig whose bone names do not match
what the retargeter expects.

WHY THE SUBJECT IS SHAPED THE WAY IT IS
---------------------------------------
Every clause in SUBJECT is load-bearing for some downstream stage:

  * A-pose wording      rig_model reads limb chains off a generated skeleton, and
                        arms fused to the torso give it nothing to find.
  * distinct materials  segment_mesh has to have parts to find. Brass plates over
                        a crimson tunic over bare skin is three obvious regions.
  * two curved horns    exercises the appendage chains - bones outside the
                        mixamorig: namespace that apply_animation must leave alone.
  * plain white bg      every stage downstream of the image assumes the subject is
                        separable from the background.
  * NO view language    generate_views rejects a prompt containing "front view",
                        "in profile" and friends, because they fight its own
                        per-view conditioning. See _VIEW_CONFLICTS.

This harness RECORDS failures and keeps going, unlike the tools themselves, which
fail loudly by design. A test that stops at the first failure tells you one thing
is broken; this one tells you which things are.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/ladvien/trellis2_mcp/src")

SUBJECT = (
    "an emberwake herald, a horned fire-priestess with pale ash-grey skin, "
    "two long curved black horns swept back from the temples, close-cropped white hair, "
    "wearing a sleeveless deep crimson tunic, polished brass shoulder plates and brass greaves, "
    "a wide black leather belt, bare arms"
)

HERO_PROMPT = (
    f"{SUBJECT}, full body, standing in a neutral A-pose with arms held out and down "
    "at 45 degrees, clearly separated from the torso, legs shoulder-width apart, feet flat "
    "on the ground, centred on a plain flat white background, even studio lighting, "
    "no shadows, full figure in frame, sharp focus, game asset reference sheet"
)

GARMENT = "hooded cloak with a deep pointed hood and a long open front, heavy dark wool"

CLIP = "mutant walking"

SCRIPTS = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default="emberwake_herald")
    ap.add_argument("--skip", nargs="*", default=[], help="stage names to skip")
    ap.add_argument("--report", default="/home/ladvien/trellis/output/smoke_test.json")
    # Image generation runs on the Mac and costs ~8 minutes for a four-view set.
    # Handing back images from an earlier run lets a failure further down the
    # pipeline be re-tested without paying for them again.
    ap.add_argument("--hero", help="reuse this hero image instead of generating one")
    ap.add_argument("--views", nargs="*", default=[], help="reuse these view images")
    args = ap.parse_args()

    from trellis2_mcp import server

    def call(tool, **kw):
        fn = getattr(server, tool)
        return getattr(fn, "fn", fn)(**kw)

    name = args.name
    results, order = {}, []

    def stage(label, fn):
        """Run one stage, record it, and keep going if it fails."""
        order.append(label)
        if label in args.skip:
            results[label] = {"skipped": True}
            print(f"-- {label}: SKIPPED", flush=True)
            return None
        started = time.time()
        try:
            out = fn()
            ok = bool(out.get("success", True)) if isinstance(out, dict) else True
        except Exception as e:  # a raising tool is a failure like any other
            out, ok = {"success": False, "error": f"{type(e).__name__}: {e}"}, False
        secs = round(time.time() - started, 1)
        results[label] = {"ok": ok, "seconds": secs,
                          "result": out if isinstance(out, dict) else {"value": str(out)}}
        detail = "" if ok else f"  <- {str(out.get('error'))[:220]}"
        print(f"-- {label}: {'OK' if ok else 'FAIL'} ({secs}s){detail}", flush=True)
        return out if ok else None

    stage("health_check", lambda: call("health_check"))

    if args.hero:
        hero_png = args.hero
        results["generate_image"] = {"reused": args.hero}
        order.append("generate_image")
        print(f"-- generate_image: REUSED {args.hero}", flush=True)
    else:
        hero = stage("generate_image", lambda: call(
            "generate_image", prompt=HERO_PROMPT, output_name=f"{name}_hero", steps=6))
        # generate_image returns local_path, NOT image_path. Reading the wrong key
        # used to work by accident through a fallback; there is no fallback now.
        hero_png = hero["local_path"] if hero else None

    if args.views:
        view_paths = list(args.views)
        results["generate_views"] = {"reused": view_paths}
        order.append("generate_views")
        print(f"-- generate_views: REUSED {len(view_paths)} images", flush=True)
    else:
        views = stage("generate_views", lambda: call(
            "generate_views", prompt=SUBJECT, views="front,back,left,right",
            output_name=f"{name}_views"))
        view_paths = [v["local_path"] for v in views["views"].values()] if (
            views and isinstance(views.get("views"), dict)) else []

    # evict_trellis_for_bake because the bake and the resident TRELLIS weights do
    # not fit at once on a card that is also hosting something else. Without it the
    # preflight refuses at "needs ~5.4 GB but only 5.4 GB is free".
    stage("generate_3d", lambda: call(
        "generate_3d", image=hero_png, output_name=name, evict_trellis_for_bake=True)
        if hero_png else {"success": False, "error": "no hero image"})

    # `images` is a JSON STRING, not a list - it crosses the MCP boundary as one
    # scalar argument. Passing the list itself fails inside json.loads with
    # "the JSON object must be str, bytes or bytearray, not list".
    stage("generate_3d_multi_image", lambda: call(
        "generate_3d_multi_image", images=json.dumps(view_paths),
        output_name=f"{name}_mv", evict_trellis_for_bake=True)
        if view_paths else {"success": False, "error": "no view set"})

    # Known broken: inference_i2mv_sdxl.py does birefnet.to(device) with no dtype
    # cast, and newer transformers honours the fp16 torch_dtype. Kept in the run so
    # the failure stays visible rather than being quietly dropped from the suite.
    stage("generate_orbit_views", lambda: call(
        "generate_orbit_views", image=hero_png, output_name=f"{name}_orbit")
        if hero_png else {"success": False, "error": "no hero image"})

    stage("segment_mesh", lambda: call("segment_mesh", mesh=f"{name}.glb"))

    stage("generate_garment", lambda: call(
        "generate_garment", garment=GARMENT, body=f"{name}.glb",
        output_name=f"{name}_cloak"))

    rig = stage("rig_model", lambda: call("rig_model", mesh=f"{name}.glb"))

    stage("list_animations", lambda: call("list_animations", search="walk", limit=10))

    if rig:
        stage("apply_animation", lambda: call(
            "apply_animation", character=Path(rig["rigged_glb"]).name, clip=CLIP))
    else:
        stage("apply_animation", lambda: {"success": False, "error": "no rig"})

    def split():
        asset_dir = server.CODEX_GEN_AI_DIR / "characters" / name
        proc = subprocess.run(
            [str(server.SEGVIGEN_PYTHON), str(SCRIPTS / "split_by_parts.py"),
             "--mesh", str(asset_dir / "asset.glb"),
             "--labels", str(asset_dir / "asset_face_labels.npy"),
             "--out-dir", str(asset_dir)],
            capture_output=True, text=True, timeout=900)
        written = (asset_dir / "asset_split.glb").is_file()
        return {"success": written, "error": proc.stderr[-300:] if not written else None,
                "out": str(asset_dir / "asset_split.glb")}

    stage("split_by_parts", split)
    stage("list_outputs", lambda: call("list_outputs", limit=10))
    stage("free_gpu", lambda: call("free_gpu"))

    failed = [k for k in order if not results[k].get("ok", True)
              and not results[k].get("skipped")]
    summary = {
        "name": name, "prompt": HERO_PROMPT, "subject": SUBJECT, "garment": GARMENT,
        "stages": len(order), "failed": failed, "results": results,
    }
    Path(args.report).write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n{len(order) - len(failed)}/{len(order)} stages OK. Report: {args.report}")
    if failed:
        print("FAILED: " + ", ".join(failed))
    print("SMOKE_TEST_DONE")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
