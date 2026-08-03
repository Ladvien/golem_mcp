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
#   5. SDPA, not flash-attn and not xformers. Neither compiled attention backend
#      is obtainable here: xformers has no cu13 build at ANY version (its PyPI
#      wheel installs but reports "xFormers wasn't build with CUDA support"), and
#      no flash-attn cu13 wheel exists for torch 2.13 at any Python version.
#      Building flash-attn from source was measured at ~7 hours on this box - its
#      setup.py ignores TORCH_CUDA_ARCH_LIST (it reads FLASH_ATTN_CUDA_ARCHS) and
#      emits sm_80/90/100/120 for all 72 .cu files, three-quarters of it dead
#      weight for a 3090. It also cannot be built unguarded: at MAX_JOBS=2 it
#      spawns three cicc processes at ~3.7 GB each and exhausts all 31 GB.
#      Instead we add an SDPA backend to trellis2's SPARSE attention, which
#      upstream already ships for its DENSE attention
#      (trellis2/modules/attention/full_attn.py) but omitted from the sparse
#      module. The models only use attn_mode='full', so sparse/windowed_attn.py
#      is never reached and one dispatch branch closes the gap. See
#      scripts/segvigen-patches/. Run everything with ATTN_BACKEND=sdpa.
#
# OTHER TRAPS, EACH ALREADY PAID FOR:
#
#   - inference_full.py's --img is the render's OUTPUT path, not an input. The
#     patch in segvigen-patches makes it skip the render when that file already
#     exists, so the caller can render in its own process (bpy must not share a
#     process with the ~16 GB inference CUDA context).
#   - example_full_seg.py is training-data prep, NOT an inference example. Reading
#     it as one sends you down a completely wrong path.
#   - bpy 5.x removed cycles.filter_type, which data_toolkit/bpy_render.py sets.
#     Hence the 4.5.9 pin, and hence cp311 (5.x is cp313-only).
#   - mathutils is not a site-packages module. bpy registers it in sys.modules from
#     its embedded interpreter, so `import mathutils` works only AFTER `import bpy`.
#
# PROVEN ON THIS BOX (do not re-litigate):
#
#   - The 512^3 voxelizer accepts our generated assets, which are ~269 disconnected
#     non-watertight shells. That was the single biggest risk to the whole approach.
#   - Inference peaks at ~16.6 GB VRAM and takes 45-85 s per asset on a 3090. The
#     README's "24 GB minimum" is boilerplate inherited from TRELLIS.2.
set -euo pipefail

ROOT="${SEGVIGEN_ROOT:-/home/ladvien/segvigen}"
REPO="$ROOT/repo"                 # SegviGen
T2="$ROOT/TRELLIS.2"              # provides o-voxel source
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

# Pinned because we apply a source patch on top. An unpinned clone would let
# upstream drift out from under the patch and fail in a confusing place.
SEGVIGEN_COMMIT=81ec99ede1fbe566c73322dd968cd64bb508f5f7
TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
PATCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/segvigen-patches"

command -v uv >/dev/null || { echo "FATAL: uv not on PATH" >&2; exit 1; }
export CUDA_HOME="${CUDA_HOME:-/opt/cuda}"
[ -x "$CUDA_HOME/bin/nvcc" ] || { echo "FATAL: no nvcc at $CUDA_HOME/bin/nvcc" >&2; exit 1; }
export PATH="$CUDA_HOME/bin:$PATH"
echo "==> CUDA: $("$CUDA_HOME/bin/nvcc" --version | tail -2 | head -1)"

mkdir -p "$ROOT"

# --- sources -----------------------------------------------------------------
# TRELLIS.2 must be --recursive: o-voxel vendors Eigen as a submodule.
[ -d "$T2/.git" ] || { echo "==> Cloning TRELLIS.2 (recursive) @ $TRELLIS2_COMMIT"; \
    git clone --recursive https://github.com/microsoft/TRELLIS.2.git "$T2"; \
    git -C "$T2" checkout --recurse-submodules "$TRELLIS2_COMMIT"; }
[ -d "$REPO/.git" ] || { echo "==> Cloning SegviGen @ $SEGVIGEN_COMMIT"; \
    git clone https://github.com/Nelipot-Lee/SegviGen.git "$REPO"; \
    git -C "$REPO" checkout "$SEGVIGEN_COMMIT"; }

# The SDPA backend (header note 5) and the pre-rendered-conditioning-image change
# live here, not in the clone. `git apply --check --reverse` succeeding means the
# patch is already in - that is the idempotent case, not an error.
echo "==> Applying source patches"
for p in "$PATCH_DIR"/*.patch; do
    name=$(basename "$p")
    if git -C "$REPO" apply --check --reverse "$p" 2>/dev/null; then
        echo "    $name already applied"
    elif git -C "$REPO" apply "$p"; then
        echo "    $name applied"
    else
        echo "FATAL: $name does not apply to $REPO." >&2
        echo "       Expected SegviGen at $SEGVIGEN_COMMIT, found $(git -C "$REPO" rev-parse HEAD)." >&2
        exit 1
    fi
done

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
# numpy is capped below 2 because bpy 4.5.9 requires it. Left unpinned, this step
# installs numpy 2.x and the bpy step below immediately downgrades it, so every
# re-run churns two packages and briefly leaves the env inconsistent.
echo "==> Installing base requirements"
uv pip install --python "$PY" \
    imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja trimesh \
    tensorboard pandas lpips zstandard kornia timm \
    "numpy<2" scipy Pillow omegaconf safetensors huggingface_hub einops

echo "==> Installing utils3d (pinned commit, as upstream does)"
uv pip install --python "$PY" \
    "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

echo "==> Pinning transformers==4.57.6 (SegviGen: TRELLIS.2 issue #101)"
uv pip install --python "$PY" "transformers==4.57.6"

# Guarded because uv reinstalls this ~350 MB wheel on every run otherwise - it
# considers the installed tree dirty, presumably because Blender writes into its
# own package directory at runtime.
if "$PY" -c "import bpy; assert bpy.app.version[:2] == (4, 5)" 2>/dev/null; then
    echo "==> bpy 4.5.x already installed"
else
    echo "==> Installing bpy 4.5.9 (Blender as a module; supplies mathutils)"
    uv pip install --python "$PY" "bpy==4.5.9"
fi

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
cd "$REPO" && ATTN_BACKEND=sdpa "$PY" - <<'EOF'
import sys

import torch

print(f"python  {sys.version.split()[0]}")
print(f"torch   {torch.__version__} (cuda {torch.version.cuda}, available={torch.cuda.is_available()})")

import flex_gemm  # noqa: F401
import o_voxel  # noqa: F401
print("o_voxel + flex_gemm import OK")

# mathutils is not a site-packages module: bpy registers it in sys.modules from
# its embedded interpreter, so it is importable only AFTER bpy. data_toolkit's
# bpy_render.py relies on exactly that ordering.
import bpy  # noqa: F401
import mathutils  # noqa: F401
print("bpy + mathutils import OK")

sys.path.insert(0, ".")
from trellis2 import models  # noqa: F401
from trellis2.representations import MeshWithVoxel  # noqa: F401
import trellis2.modules.sparse as sp  # noqa: F401
print("trellis2 imports OK (no nvdiffrast)")

# The patch is the whole reason this env works; prove it took, rather than
# discovering it two minutes into an inference run.
assert sp.config.ATTN == 'sdpa', f"sdpa backend not selected, got {sp.config.ATTN}"
q = sp.VarLenTensor(torch.randn(6, 3, 2, 16, device='cuda', dtype=torch.bfloat16),
                    [slice(0, 4), slice(4, 6)])
out = sp.sparse_scaled_dot_product_attention(q)
assert out.feats.shape == (6, 2, 16) and out.feats.isfinite().all()
print("sparse sdpa attention OK")
EOF

echo
echo "==> Done. Run inference with ATTN_BACKEND=sdpa set."
