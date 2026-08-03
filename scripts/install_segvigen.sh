#!/usr/bin/env bash
# Install SegviGen (3D part segmentation) into its own Python environment.
#
# SegviGen runs on TRELLIS.2 and compiles three CUDA extensions - o-voxel, CuMesh
# and FlexGEMM. Getting that to build on this box took several dead ends; they are
# recorded here so nobody walks back into them.
#
# WHY NOT UPSTREAM'S EXACT CONFIG (python 3.10, torch 2.6.0+cu124):
#
#   1. CUDA 12.4 cannot be installed. Its runfile's ./cuda-installer is linked
#      against libxml2.so.2 and this distro ships libxml2.so.16; --extract runs the
#      same binary, so it fails too. The makeself payload CAN be unpacked with
#      `--noexec --target`, and that was done - but see (2).
#   2. CUDA 12.4 cannot COMPILE here regardless. This box has glibc 2.43, and
#      glibc >= 2.41 declares rsqrtf and friends in math.h, colliding with CUDA
#      12.4's own math headers. Every .cu fails with redeclaration errors. This is
#      not a compiler-version issue and -allow-unsupported-compiler does not help.
#      (CUDA 12.4 also rejects gcc > 13, and this box has gcc 16; gcc 13 was fetched
#      rootlessly from the Arch archive to test, and the glibc collision remained.)
#   3. So: system CUDA 13.3 at /opt/cuda with gcc 16, which is PROVEN to compile
#      CUDA extensions here - nvdiffrast builds against it for the MV-Adapter env.
#      That forces torch cu130. 2.9.0 was the intended (lowest, closest to 2.6.0)
#      cu130 build, but its partner torchvision 0.24 is not published for cu130, so
#      the pair is unsatisfiable; torch 2.13.0 + torchvision 0.28.0 is the lowest
#      MATCHED cu130 pair. See the pinning note further down.
#   4. Python 3.11, not 3.10: bpy is unobtainable on 3.10. PyPI has no cp310 bpy at
#      any version and download.blender.org/pypi now returns 403. bpy is needed for
#      the conditioning render (data_toolkit/bpy_render.py) and supplies mathutils.
#   5. xformers, not flash-attn: no flash-attn wheel exists for cu13 + this torch +
#      cp311, and building it from source takes hours. TRELLIS.2 supports
#      ATTN_BACKEND=xformers (trellis2/modules/sparse/config.py), so we use it.
set -euo pipefail

ROOT="${SEGVIGEN_ROOT:-/home/ladvien/segvigen}"
REPO="$ROOT/repo"                 # SegviGen
T2="$ROOT/TRELLIS.2"              # provides o-voxel source
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

command -v uv >/dev/null || { echo "FATAL: uv not on PATH" >&2; exit 1; }
export CUDA_HOME="${CUDA_HOME:-/opt/cuda}"
[ -x "$CUDA_HOME/bin/nvcc" ] || { echo "FATAL: no nvcc at $CUDA_HOME/bin/nvcc" >&2; exit 1; }
export PATH="$CUDA_HOME/bin:$PATH"
echo "==> CUDA: $("$CUDA_HOME/bin/nvcc" --version | tail -2 | head -1)"

mkdir -p "$ROOT"

# --- sources -----------------------------------------------------------------
# TRELLIS.2 must be --recursive: o-voxel vendors Eigen as a submodule.
[ -d "$T2/.git" ] || { echo "==> Cloning TRELLIS.2 (recursive)"; \
    git clone -b main --recursive https://github.com/microsoft/TRELLIS.2.git "$T2"; }
[ -d "$REPO/.git" ] || { echo "==> Cloning SegviGen"; \
    git clone https://github.com/Nelipot-Lee/SegviGen.git "$REPO"; }

# --- environment -------------------------------------------------------------
if [ -x "$PY" ]; then
    echo "==> Venv already present at $VENV"
else
    echo "==> Creating Python 3.11 venv"
    uv venv --python 3.11 "$VENV"
fi

# Pin BOTH halves. torchvision must match torch exactly or every import dies with
# "operator torchvision::nms does not exist", and it is on the inference path
# (DINOv3 feature extractor + BiRefNet both use it). Leaving torchvision unpinned
# silently drags torch past its own pin: torch 2.9.0+cu130 has no matching
# torchvision on that index, so the resolver "satisfies" the request by upgrading
# torch instead. Upstream's 2.6.0 has no cu130 build at all.
echo "==> Installing torch 2.13.0 + torchvision 0.28.0 (cu130, matched pair)"
uv pip install --python "$PY" torch==2.13.0 torchvision==0.28.0 \
    --index-url https://download.pytorch.org/whl/cu130

# TRELLIS.2's own --basic set. Omitted: pillow-simd (needs apt libjpeg-dev and
# root, and routinely fails to build), spconv (unused - sparse conv defaults to
# CONV='flex_gemm'), mathutils (no cp311 wheel and its source needs PyLong_AsInt
# from CPython 3.13; bpy bundles it instead).
echo "==> Installing base requirements"
uv pip install --python "$PY" \
    imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh \
    tensorboard pandas lpips zstandard kornia timm \
    numpy scipy Pillow omegaconf safetensors huggingface_hub einops

echo "==> Installing utils3d (pinned commit, as upstream does)"
uv pip install --python "$PY" \
    "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

echo "==> Pinning transformers==4.57.6 (SegviGen: TRELLIS.2 issue #101)"
uv pip install --python "$PY" "transformers==4.57.6"

echo "==> Installing xformers (attention backend; see note 5 above)"
uv pip install --python "$PY" xformers

echo "==> Installing bpy 4.5.9 (Blender as a module; supplies mathutils)"
uv pip install --python "$PY" "bpy==4.5.9"

# --- CUDA extensions ---------------------------------------------------------
# nvdiffrast IS required, despite trellis2's segmentation chain never reaching
# trellis2_texturing or mesh_renderer: o_voxel/postprocess.py imports it at line 10
# and o_voxel/__init__ pulls postprocess in at package level, so `import o_voxel`
# fails without it. Note this drags the Nvidia Source Code License (1-Way
# Commercial, non-commercial use only) into this environment too.
# Cap build parallelism. ninja defaults to one job per core (24 here) and each
# cudafe++ is memory-hungry; unbounded, the o-voxel build triggered 13 OOM kills
# of its own compiler processes on a 32 GB box that was already partly swapped.
# Nothing else on the machine was affected, but the build cannot finish that way.
export MAX_JOBS="${MAX_JOBS:-4}"
echo "==> Building CUDA extensions with MAX_JOBS=$MAX_JOBS"

EXT=/tmp/segvigen-extensions
mkdir -p "$EXT"
for pkg in CuMesh FlexGEMM; do
    # Import names are not the repo names: FlexGEMM installs as flex_gemm.
    case "$pkg" in FlexGEMM) mod=flex_gemm ;; *) mod=$(echo "$pkg" | tr '[:upper:]' '[:lower:]') ;; esac
    if "$PY" -c "import $mod" 2>/dev/null; then echo "==> $pkg already installed"; continue; fi
    echo "==> Building $pkg against $CUDA_HOME"
    rm -rf "$EXT/$pkg"
    git clone --recursive "https://github.com/JeffreyXiang/$pkg.git" "$EXT/$pkg"
    uv pip install --python "$PY" --no-build-isolation "$EXT/$pkg"
done

if "$PY" -c "import nvdiffrast.torch" 2>/dev/null; then
    echo "==> nvdiffrast already installed"
else
    echo "==> Building nvdiffrast (required by o_voxel.postprocess)"
    uv pip install --python "$PY" --no-build-isolation \
        "git+https://github.com/NVlabs/nvdiffrast.git@v0.4.0"
fi

if "$PY" -c "import o_voxel" 2>/dev/null; then
    echo "==> o-voxel already installed"
else
    echo "==> Building o-voxel"
    [ -d "$T2/o-voxel" ] || { echo "FATAL: $T2/o-voxel missing - TRELLIS.2 not cloned --recursive?" >&2; exit 1; }
    uv pip install --python "$PY" --no-build-isolation "$T2/o-voxel"
fi

# --- weights -----------------------------------------------------------------
echo "==> Downloading weights"
"$PY" - <<'EOF'
from huggingface_hub import snapshot_download

for repo in ("fenghora/SegviGen", "microsoft/TRELLIS.2-4B",
             "briaai/RMBG-2.0", "facebook/dinov3-vitl16-pretrain-lvd1689m"):
    print(f"[{repo}] {snapshot_download(repo)}")
EOF

# inference_full.py opens "microsoft/TRELLIS.2-4B/pipeline.json" as a RELATIVE path
# and models.from_pretrained takes "microsoft/TRELLIS.2-4B/ckpts/...", so the repo
# expects the backbone checked out under its own root rather than read from the HF
# cache. Symlink instead of re-downloading ~16 GB.
echo "==> Linking TRELLIS.2-4B to the relative path inference expects"
"$PY" - "$REPO" <<'EOF'
import os
import sys
from huggingface_hub import snapshot_download

repo = sys.argv[1]
snap = snapshot_download("microsoft/TRELLIS.2-4B")
dest = os.path.join(repo, "microsoft", "TRELLIS.2-4B")
os.makedirs(os.path.dirname(dest), exist_ok=True)
if os.path.islink(dest) or os.path.exists(dest):
    os.remove(dest) if os.path.islink(dest) else None
if not os.path.exists(dest):
    os.symlink(snap, dest)
assert os.path.isfile(os.path.join(dest, "pipeline.json")), "pipeline.json not reachable"
print(f"  {dest} -> {snap}")
EOF

# --- verify ------------------------------------------------------------------
echo "==> Verifying"
cd "$REPO" && ATTN_BACKEND=xformers "$PY" - <<'EOF'
import sys

import torch

print(f"python  {sys.version.split()[0]}")
print(f"torch   {torch.__version__} (cuda {torch.version.cuda}, available={torch.cuda.is_available()})")

import flex_gemm  # noqa: F401
import o_voxel  # noqa: F401
print("o_voxel + flex_gemm import OK")

import mathutils  # noqa: F401  (from bpy)
import xformers  # noqa: F401
print("mathutils + xformers import OK")

sys.path.insert(0, ".")
from trellis2 import models  # noqa: F401
from trellis2.representations import MeshWithVoxel  # noqa: F401
import trellis2.modules.sparse as sp  # noqa: F401
print("trellis2 imports OK (no nvdiffrast)")
EOF

echo
echo "==> Done. Run inference with ATTN_BACKEND=xformers set."
