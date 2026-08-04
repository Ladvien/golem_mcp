"""Shared TRELLIS.2 loading and export, used by the generate and garment drivers.

TRIMMED MODEL LOADING - the reason this module exists
-----------------------------------------------------
`pipeline.json` lists eight models totalling 14.82 GB, and `low_vram=True` keeps
every one of them in HOST RAM. But `Trellis2ImageTo3DPipeline.run` only asserts on
a subset per `pipeline_type`: a '1024' run never touches
`shape_slat_flow_model_512` or `tex_slat_flow_model_512`, and a '512' run never
touches their 1024 counterparts. That is 5.16 GB held for nothing.

It is not academic. On this 32 GB box - where /tmp is a 16 GB tmpfs, so scratch
files are also RAM - loading the full set was OOM-killed by the kernel at both
'1024' and '512', and looked exactly like "TRELLIS.2 cannot run here". Loading a
trimmed config instead peaks at 10.7 GB RSS and runs fine.

SIMPLIFY BEFORE EXPORT
----------------------
`to_glb` on a raw extraction is fatal: 1024 produces ~9M faces, 512 ~2-3M, and
handing that straight to the exporter gets the process OOM-killed. Both upstream
entrypoints call simplify first (TRELLIS.2/example.py:26,
SegviGen/inference_full.py:285).
"""

import json
import os

MODEL_DIR = "microsoft/TRELLIS.2-4B"

# Models every tier needs, plus the flow models each specific tier asserts on.
_ALWAYS = ["sparse_structure_decoder", "sparse_structure_flow_model",
           "shape_slat_decoder", "tex_slat_decoder"]
NEEDED = {
    "512": _ALWAYS + ["shape_slat_flow_model_512", "tex_slat_flow_model_512"],
    "1024": _ALWAYS + ["shape_slat_flow_model_1024", "tex_slat_flow_model_1024"],
    "1024_cascade": _ALWAYS + ["shape_slat_flow_model_512", "shape_slat_flow_model_1024",
                               "tex_slat_flow_model_1024"],
    "1536_cascade": _ALWAYS + ["shape_slat_flow_model_512", "shape_slat_flow_model_1024",
                               "tex_slat_flow_model_1024"],
}


def host_rss_peak_gb() -> float:
    """Peak resident set size. The binding constraint here is host RAM, not VRAM."""
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM"):
                return int(line.split()[1]) / 1048576
    return float("nan")


def write_trimmed_config(pipeline_type: str, model_dir: str = MODEL_DIR,
                         low_vram: bool = False) -> tuple[str, list[str]]:
    """Write a config listing only the models this tier uses. Returns (filename, dropped).

    low_vram defaults to FALSE here, inverting upstream. Upstream's True keeps every
    model in host RAM and streams them to the GPU per use - correct when VRAM is the
    scarce resource. On this box it is backwards: 13 GB of host RAM (a 16 GB tmpfs
    eats into 32 GB total) against 19 GB of free VRAM. Holding 9.1 GB of models in
    RAM left too little for mesh extraction and the kernel OOM-killed the run at both
    512 and 1024. Trimmed models on the GPU cost ~9.6 GB VRAM, which fits alongside
    the ~5.6 GB generation peak, and hands the host RAM back to the extraction.
    """
    if pipeline_type not in NEEDED:
        raise SystemExit(f"unknown pipeline_type {pipeline_type!r}; expected one of {sorted(NEEDED)}")
    cfg = json.load(open(os.path.join(model_dir, "pipeline.json")))
    keep = NEEDED[pipeline_type]
    dropped = [k for k in cfg["args"]["models"] if k not in keep]
    missing = [k for k in keep if k not in cfg["args"]["models"]]
    if missing:
        raise SystemExit(f"pipeline.json is missing {missing}, needed for pipeline_type={pipeline_type}")
    cfg["args"]["models"] = {k: v for k, v in cfg["args"]["models"].items() if k in keep}
    cfg["args"]["default_pipeline_type"] = pipeline_type
    cfg["args"]["low_vram"] = low_vram
    name = f"pipeline_{pipeline_type}.json"
    # Written beside the real config so its relative ckpt paths still resolve.
    json.dump(cfg, open(os.path.join(model_dir, name), "w"), indent=2)
    return name, dropped


def load_pipeline(pipeline_type: str, model_dir: str = MODEL_DIR, low_vram: bool = False):
    """Load TRELLIS.2 with only the models this tier needs. Returns (pipeline, dropped)."""
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    config, dropped = write_trimmed_config(pipeline_type, model_dir, low_vram)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(model_dir, config_file=config)
    pipeline.cuda()
    return pipeline, dropped


def export_glb(mesh, out_path: str, simplify_to: int, decimate_to: int, texture_size: int,
               remesh: bool = False):
    """simplify -> to_glb. Returns the raw face count for reporting."""
    import o_voxel

    raw = int(len(mesh.faces))
    mesh.simplify(simplify_to)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces,
        attr_volume=mesh.attrs, coords=mesh.coords, attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size, aabb=[[-0.5] * 3, [0.5] * 3],
        decimation_target=decimate_to, texture_size=texture_size,
        remesh=remesh, verbose=False,
    )
    glb.export(out_path)
    return raw


def mesh_stats(path: str) -> dict:
    import numpy as np
    import trimesh

    m = trimesh.load(path, force="mesh", process=False)
    _, counts = np.unique(m.edges_sorted, axis=0, return_counts=True)
    tex = getattr(getattr(m.visual, "material", None), "baseColorTexture", None)
    extents = m.bounds[1] - m.bounds[0]
    return {
        "vertices": int(len(m.vertices)), "faces": int(len(m.faces)),
        "is_watertight": bool(m.is_watertight),
        "boundary_edges": int((counts == 1).sum()),
        "texture": list(tex.size) if tex else None,
        "dimensions_m": [round(float(v), 4) for v in extents],
    }
