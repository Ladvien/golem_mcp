#!/usr/bin/env bash
# Install MV-Adapter into its own Python 3.11 environment.
#
# MV-Adapter generates 6 geometrically consistent views from one reference image,
# including true 90 and 270 degree profiles - which FLUX.2 klein will not produce
# at any prompt. Those views are what generate_3d_multi_image wants.
#
# Third CUDA environment on this box, for the same reason as SkinTokens: it needs
# its own torch/diffusers stack and cannot share the TRELLIS interpreter.
set -euo pipefail

ROOT="${MVADAPTER_ROOT:-/home/ladvien/mvadapter}"
REPO="$ROOT/repo"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

command -v uv >/dev/null || { echo "FATAL: uv not on PATH" >&2; exit 1; }
command -v nvidia-smi >/dev/null || { echo "FATAL: nvidia-smi not found" >&2; exit 1; }

mkdir -p "$ROOT"

if [ -d "$REPO/.git" ]; then
    echo "==> Repo already present at $REPO"
else
    echo "==> Cloning MV-Adapter"
    git clone https://github.com/huanngzh/MV-Adapter.git "$REPO"
fi

# uv venv recreates an existing environment, discarding the multi-GB torch install.
if [ -x "$PY" ]; then
    echo "==> Venv already present at $VENV"
else
    echo "==> Creating Python 3.11 venv at $VENV"
    uv venv --python 3.11 "$VENV"
fi

# Unlike TRELLIS and SkinTokens, this environment has to COMPILE a CUDA extension
# (nvdiffrast), so torch's CUDA major version must match the system toolkit -
# torch's cpp_extension refuses to build across a major mismatch. This box has
# CUDA 13.3 at /opt/cuda, hence the cu130 wheels rather than cu128.
CUDA_HOME="${CUDA_HOME:-/opt/cuda}"
[ -x "$CUDA_HOME/bin/nvcc" ] || {
    echo "FATAL: no nvcc at $CUDA_HOME/bin/nvcc. Install the CUDA toolkit (pacman -S cuda) " >&2
    echo "       or set CUDA_HOME. nvdiffrast cannot be built without it, and the pip " >&2
    echo "       nvidia-cuda-nvcc-cu12 wheel ships only ptxas, not the compiler driver." >&2
    exit 1
}
export CUDA_HOME PATH="$CUDA_HOME/bin:$PATH"
echo "==> Using CUDA at $CUDA_HOME ($("$CUDA_HOME/bin/nvcc" --version | tail -2 | head -1))"

echo "==> Installing torch (cu130, to match the system toolkit)"
uv pip install --python "$PY" torch torchvision \
    --index-url https://download.pytorch.org/whl/cu130

# Deliberately NOT the full requirements.txt. open3d, pymeshlab, spandrel,
# cvcuda_cu12 and pytorch-lightning are only used by the texturing and training
# pipelines; the image-to-multiview path does not touch them.
echo "==> Installing image-to-multiview dependencies"
uv pip install --python "$PY" \
    diffusers transformers peft accelerate safetensors huggingface_hub \
    numpy opencv-python pillow omegaconf einops timm kornia scikit-image \
    sentencepiece trimesh controlnet_aux ninja \
    matplotlib jaxtyping

# mvadapter.utils imports mesh_utils, which imports nvdiffrast, so it is required
# even for the pure image path. It JIT-builds CUDA extensions on first import.
echo "==> Building nvdiffrast against $CUDA_HOME"
uv pip install --python "$PY" --no-build-isolation \
    "git+https://github.com/NVlabs/nvdiffrast.git"

# Upstream loads SDXL at full precision and only converts to fp16 afterwards via
# pipe.to(), peaking around 14 GB of HOST ram. On a 32 GB box that is an OOM kill
# (exit 137) during "Loading pipeline components". Loading fp16 directly halves it.
echo "==> Patching inference script to load fp16 directly"
"$PY" - "$REPO/scripts/inference_i2mv_sdxl.py" <<'EOF'
import sys

path = sys.argv[1]
src = open(path).read()

edits = [
    # BiRefNet's config declares torch_dtype float16 and newer transformers honours
    # it, so the background remover's weights arrive in half while the transform
    # feeding it still produces float32: "Input type (float) and bias type
    # (c10::Half) should be the same", and generate_orbit_views dies at exit 1.
    # Force it to float32 - it is a small model and fp32 is the better matte.
    (
        "        birefnet.to(args.device)",
        "        birefnet.to(args.device)\n        birefnet.float()",
    ),
    (
        "    pipe = MVAdapterI2MVSDXLPipeline.from_pretrained(base_model, **pipe_kwargs)",
        '    pipe = MVAdapterI2MVSDXLPipeline.from_pretrained(\n'
        '        base_model, torch_dtype=dtype, variant="fp16", **pipe_kwargs\n'
        "    )",
    ),
    (
        '        pipe_kwargs["vae"] = AutoencoderKL.from_pretrained(vae_model)',
        '        pipe_kwargs["vae"] = AutoencoderKL.from_pretrained(vae_model, torch_dtype=dtype)',
    ),
]

# DO NOT add pipe.enable_attention_slicing() here, however tempting the ~16 GB
# peak makes it. Slicing swaps in diffusers' SlicedAttnProcessor, which does not
# accept MV-Adapter's cross_attention_kwargs (ref_hidden_states, mv_scale,
# ref_scale, num_views) and silently drops them. Both the reference conditioning
# and the multi-view coupling are then dead: the run still exits 0 and writes a
# strip of six unrelated images bearing no resemblance to the reference. Upstream
# already enables vae slicing, which is safe because the VAE only decodes.
# enable_xformers_memory_efficient_attention() replaces the same processor and
# breaks it identically.

for old, new in edits:
    if new.strip() in src:
        continue
    if old not in src:
        raise SystemExit(f"FATAL: could not find line to patch:\n{old}")
    src = src.replace(old, new)

open(path, "w").write(src)
print("fp16 loading patch applied")
EOF
grep -n "torch_dtype=dtype" "$REPO/scripts/inference_i2mv_sdxl.py"

echo "==> Pre-downloading model weights (~9 GB)"
cd "$REPO" && "$PY" - <<'EOF'
from huggingface_hub import hf_hub_download, snapshot_download

# SDXL base is the backbone MV-Adapter adapts; CreativeML Open RAIL++-M, which
# permits commercial use. The adapter itself is Apache 2.0.
snapshot_download(
    "stabilityai/stable-diffusion-xl-base-1.0",
    allow_patterns=["*.json", "*.txt", "**/*fp16.safetensors", "tokenizer*/*", "scheduler/*"],
)
snapshot_download("madebyollin/sdxl-vae-fp16-fix", allow_patterns=["*.json", "*.safetensors"])
p = hf_hub_download("huanngzh/mv-adapter", "mvadapter_i2mv_sdxl.safetensors")
print(f"[ADAPTER] {p}")
EOF

echo "==> Verifying"
cd "$REPO" && "$PY" - <<'EOF'
import sys

import torch

print(f"python      {sys.version.split()[0]}")
print(f"torch       {torch.__version__} (cuda {torch.version.cuda}, available={torch.cuda.is_available()})")

import diffusers
import nvdiffrast.torch  # noqa: F401  triggers the CUDA extension build
import transformers

print(f"diffusers   {diffusers.__version__}")
print(f"transformers{transformers.__version__}")

sys.path.insert(0, ".")
from mvadapter.pipelines.pipeline_mvadapter_i2mv_sdxl import MVAdapterI2MVSDXLPipeline  # noqa: F401
from mvadapter.utils import get_orthogonal_camera, make_image_grid  # noqa: F401

print("mvadapter   imports OK")
EOF

echo
echo "==> Done. Smoke test:"
echo "    cd $REPO && $PY -m scripts.inference_i2mv_sdxl \\"
echo "        --image assets/demo/i2mv/A_decorative_figurine_of_a_young_anime-style_girl.png \\"
echo "        --text 'high quality' --seed 21 --output /tmp/mv_test.png"
