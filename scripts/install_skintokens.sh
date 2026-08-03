#!/usr/bin/env bash
# Install SkinTokens / TokenRig into its own Python 3.11 environment.
#
# SkinTokens cannot share the TRELLIS venv: TRELLIS runs Python 3.10 + torch
# 2.6.0+cu124, SkinTokens requires Python 3.11 (open3d has no cp313 wheel, and
# bpy >= 5.1 is cp313-only) + torch 2.7.0+cu128. The MCP server therefore
# invokes rigging as a subprocess against SKINTOKENS_PYTHON.
set -euo pipefail

ROOT="${SKINTOKENS_ROOT:-/home/ladvien/skintokens}"
REPO="$ROOT/repo"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
FLASH_ATTN_VERSION="2.8.3"

command -v uv >/dev/null || { echo "FATAL: uv not on PATH" >&2; exit 1; }
command -v nvidia-smi >/dev/null || { echo "FATAL: nvidia-smi not found" >&2; exit 1; }

echo "==> Driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader)"

mkdir -p "$ROOT"

if [ -d "$REPO/.git" ]; then
    echo "==> Repo already present at $REPO, leaving it alone"
else
    echo "==> Cloning SkinTokens"
    git clone https://github.com/VAST-AI-Research/SkinTokens.git "$REPO"
fi

# uv venv recreates an existing environment, which would discard the multi-GB
# torch install on every re-run.
if [ -x "$PY" ]; then
    echo "==> Venv already present at $VENV"
else
    echo "==> Creating Python 3.11 venv at $VENV"
    uv venv --python 3.11 "$VENV"
fi

echo "==> Installing torch 2.7.0 (cu128)"
uv pip install --python "$PY" \
    torch==2.7.0 torchvision==0.22.0 torchaudio==2.7.0 \
    --index-url https://download.pytorch.org/whl/cu128

echo "==> Installing requirements (bpy wheel is several hundred MB)"
uv pip install --python "$PY" -r "$REPO/requirements.txt"

# Building flash-attn from source takes 1-3 hours and can OOM system RAM.
# Prebuilt wheels are published for both C++ ABI variants; pick the one
# matching this torch build, otherwise import fails on an undefined symbol.
ABI=$("$PY" -c "import torch; print('TRUE' if torch._C._GLIBCXX_USE_CXX11_ABI else 'FALSE')")
WHEEL="flash_attn-${FLASH_ATTN_VERSION}+cu12torch2.7cxx11abi${ABI}-cp311-cp311-linux_x86_64.whl"
echo "==> Installing prebuilt flash-attn (CXX11 ABI=$ABI)"
uv pip install --python "$PY" \
    "https://github.com/Dao-AILab/flash-attention/releases/download/v${FLASH_ATTN_VERSION}/${WHEEL}"

# Upstream issue #7: bpy_server binds 0.0.0.0 and deserializes untrusted request
# bodies with torch.load(weights_only=False), i.e. pickle -> unauthenticated RCE
# reachable from the LAN while a rig job runs. Its only client is demo.py on
# loopback, so binding to localhost costs nothing.
BPY_SERVER="$REPO/src/server/bpy_server.py"
echo "==> Restricting bpy_server to loopback"
sed -i "s/host='0.0.0.0'/host='127.0.0.1'/" "$BPY_SERVER"
if grep -q "host='0.0.0.0'" "$BPY_SERVER"; then
    echo "FATAL: bpy_server still binds 0.0.0.0 - patch the bind by hand before running" >&2
    exit 1
fi
grep -n "bottle.run" "$BPY_SERVER"

# NOTE: TokenRig rigs are NOT reproducible, and no seed patch will make them so.
# demo.py generates with do_sample=True and ships no seed. Adding one was tried
# and measured: seeding torch/numpy/random at parse_args, then again per-batch
# immediately before generate, then additionally with
# torch.use_deterministic_algorithms(True, warn_only=True),
# CUBLAS_WORKSPACE_CONFIG=:4096:8 and cudnn.deterministic - the same mesh at the
# same seed still produced 47 vs 44 joints. Hashing the input batch across two
# runs gave identical digests, so the data pipeline IS deterministic and the
# divergence is inside the CUDA forward; warn_only leaves flash-attn's
# nondeterministic kernels in place and there is no deterministic flash-attn.
# Autoregressive beam-sample then amplifies float jitter into a different token,
# which changes the whole skeleton. Re-running is the only way to reroll.

echo "==> Downloading checkpoints"
# download.py writes to local_dir="." so it must run with cwd=repo.
cd "$REPO" && "$PY" download.py --model

echo "==> Verifying install"
"$PY" - <<'EOF'
import flash_attn, torch, open3d, bpy, trimesh
print(f"python      {__import__('sys').version.split()[0]}")
print(f"torch       {torch.__version__} (cuda {torch.version.cuda}, available={torch.cuda.is_available()})")
print(f"flash_attn  {flash_attn.__version__}")
print(f"open3d      {open3d.__version__}")
print(f"bpy         {bpy.app.version_string}")
EOF

for ckpt in \
    "$REPO/experiments/skin_vae_2_10_32768/last.ckpt" \
    "$REPO/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt"
do
    [ -s "$ckpt" ] || { echo "FATAL: missing checkpoint $ckpt" >&2; exit 1; }
    echo "ok: $ckpt ($(du -h "$ckpt" | cut -f1))"
done

echo
echo "==> Done. Sanity check:"
echo "    cd $REPO && $PY demo.py --input examples/giraffe.glb --output /tmp/giraffe.glb --use_transfer --num_beams 3"
