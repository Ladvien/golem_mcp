#!/usr/bin/env bash
# Build the SegviGen INFERENCE environment (Python 3.12).
#
# SegviGen needs two environments on this box, because no single Python version
# has prebuilt wheels for both halves and source-building the missing half
# exceeds this machine's RAM (flash-attn spawns cicc processes at ~3.7 GB each
# and blew through 31 GB even at MAX_JOBS=2):
#
#            cp311        cp312        cp313
#   bpy      4.5.9 OK     none         5.1.2 (API broke cycles.filter_type)
#   flash-attn cu13  none  2.8.3 OK    none
#   xformers CUDA    no cu13 build at all, any version
#
# So:  .venv-prep (3.11) voxelizes + renders   ->   .venv (3.12) runs the model.
# inference_full.py is patched to skip its internal render when the image already
# exists, and to import bpy lazily, so this env never needs bpy.
set -euo pipefail

ROOT="${SEGVIGEN_ROOT:-/home/ladvien/segvigen}"
REPO="$ROOT/repo"
T2="$ROOT/TRELLIS.2"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

command -v uv >/dev/null || { echo "FATAL: uv not on PATH" >&2; exit 1; }
export CUDA_HOME="${CUDA_HOME:-/opt/cuda}"
[ -x "$CUDA_HOME/bin/nvcc" ] || { echo "FATAL: no nvcc at $CUDA_HOME/bin/nvcc" >&2; exit 1; }
export PATH="$CUDA_HOME/bin:$PATH"
[ -d "$T2/o-voxel" ] || { echo "FATAL: $T2 missing; run install_segvigen.sh first" >&2; exit 1; }

if [ -x "$PY" ]; then
    echo "==> Venv already present at $VENV"
else
    echo "==> Creating Python 3.12 venv"
    uv venv --python 3.12 "$VENV"
fi

# torch 2.9.0 is what flash-attn's only cu13 wheel is built against; torchvision
# 0.24.0 is its matched partner. Pin both - leaving torchvision loose drags torch
# past its pin and every import dies on "operator torchvision::nms does not exist".
echo "==> Installing torch 2.9.0 + torchvision 0.24.0 (cu130, matched pair)"
uv pip install --python "$PY" torch==2.9.0 torchvision==0.24.0 \
    --index-url https://download.pytorch.org/whl/cu130

echo "==> Installing prebuilt flash-attn (cu13/torch2.9/cp312 - the only cu13 wheel)"
uv pip install --python "$PY" \
    "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/flash_attn-2.8.3+cu13torch2.9cxx11abiTRUE-cp312-cp312-linux_x86_64.whl"

echo "==> Installing base requirements"
uv pip install --python "$PY" \
    imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh \
    tensorboard pandas lpips zstandard kornia timm \
    numpy scipy Pillow omegaconf safetensors huggingface_hub einops
uv pip install --python "$PY" \
    "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
uv pip install --python "$PY" "transformers==4.57.6"

# torch 2.9's headers do not compile under gcc 16: ATen/core/List_inl.h:201 trips
# "need 'typename' before 'decltype'". torch 2.13 fixed it, but flash-attn's only
# cu13 wheel is ABI-locked to torch 2.9, so the compiler moves instead of torch.
# gcc 13 is fetched rootlessly from the Arch archive; CUDA 13.3 accepts it (unlike
# CUDA 12.4, which fails on glibc 2.43 regardless of compiler).
GCC13="$ROOT/gcc13"
if [ ! -x "$GCC13/bin/g++" ]; then
    echo "==> Fetching gcc 13 (torch 2.9 headers need it; gcc 16 is too strict)"
    mkdir -p "$GCC13"
    PKG='gcc13-13.3.1%2Br432%2Bgfc8bd63119c0-3-x86_64.pkg.tar.zst'
    curl -fsSL -o /tmp/gcc13.pkg.tar.zst "https://archive.archlinux.org/packages/g/gcc13/$PKG"
    bsdtar -xf /tmp/gcc13.pkg.tar.zst -C "$GCC13" 2>/dev/null \
        || tar --zstd -xf /tmp/gcc13.pkg.tar.zst -C "$GCC13"
    rm -f /tmp/gcc13.pkg.tar.zst
    mkdir -p "$GCC13/bin"
    ln -sf "$GCC13/usr/bin/gcc-13" "$GCC13/bin/gcc"; ln -sf "$GCC13/usr/bin/g++-13" "$GCC13/bin/g++"
    ln -sf "$GCC13/usr/bin/gcc-13" "$GCC13/bin/cc";  ln -sf "$GCC13/usr/bin/g++-13" "$GCC13/bin/c++"
fi
export PATH="$GCC13/bin:$PATH" CC="$GCC13/bin/gcc" CXX="$GCC13/bin/g++" CUDAHOSTCXX="$GCC13/bin/g++"
# nvcc ignores CUDAHOSTCXX (that is a CMake variable) and does not reliably take
# the host compiler from PATH either. -ccbin is the only thing it honours, and the
# failing translation units are all .cu, i.e. nvcc's host pass.
export NVCC_PREPEND_FLAGS="-ccbin $GCC13/bin/g++"
echo "==> Host compiler: $("$GCC13/bin/g++" --version | head -1) (nvcc -ccbin set)"

# Cap parallelism: unbounded, these builds OOM-killed 13 of their own compiler
# processes on this 32 GB box.
export MAX_JOBS="${MAX_JOBS:-4}"
echo "==> Building CUDA extensions with MAX_JOBS=$MAX_JOBS"

EXT=/tmp/segvigen-extensions
mkdir -p "$EXT"
for pkg in CuMesh FlexGEMM; do
    case "$pkg" in FlexGEMM) mod=flex_gemm ;; *) mod=$(echo "$pkg" | tr '[:upper:]' '[:lower:]') ;; esac
    if "$PY" -c "import $mod" 2>/dev/null; then echo "==> $pkg already installed"; continue; fi
    echo "==> Building $pkg"
    [ -d "$EXT/$pkg" ] || git clone --recursive "https://github.com/JeffreyXiang/$pkg.git" "$EXT/$pkg"
    uv pip install --python "$PY" --no-build-isolation "$EXT/$pkg"
done

# o_voxel/postprocess.py imports nvdiffrast at package level, so o_voxel cannot be
# imported without it - despite trellis2's segmentation path never rasterizing.
if "$PY" -c "import nvdiffrast.torch" 2>/dev/null; then
    echo "==> nvdiffrast already installed"
else
    echo "==> Building nvdiffrast (required by o_voxel.postprocess)"
    uv pip install --python "$PY" --no-build-isolation \
        "git+https://github.com/NVlabs/nvdiffrast.git@v0.4.0"
fi
"$PY" -c "import o_voxel" 2>/dev/null || {
    echo "==> Building o-voxel"
    uv pip install --python "$PY" --no-build-isolation "$T2/o-voxel"
}

echo "==> Verifying"
cd "$REPO" && ATTN_BACKEND=flash_attn "$PY" - <<'EOF'
import sys

import torch

print(f"python  {sys.version.split()[0]}")
print(f"torch   {torch.__version__} (cuda {torch.version.cuda}, available={torch.cuda.is_available()})")

import flash_attn_2_cuda  # noqa: F401  the actual CUDA kernels, not just the wrapper
import flex_gemm  # noqa: F401
import o_voxel  # noqa: F401
print("flash-attn CUDA kernels + o_voxel + flex_gemm OK")

sys.path.insert(0, ".")
from trellis2 import models  # noqa: F401
import trellis2.modules.sparse as sp  # noqa: F401
from trellis2.modules.image_feature_extractor import DinoV3FeatureExtractor  # noqa: F401
from trellis2.pipelines.rembg import BiRefNet  # noqa: F401
print("trellis2 inference chain OK (no bpy needed here)")
EOF

echo
echo "==> Done. Prep runs in $ROOT/.venv-prep, inference in $VENV."
