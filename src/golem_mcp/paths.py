"""Interpreters and driver scripts shared by the image-to-3D tools (server.py) and the motion tools (motion.py)."""

import os
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# SegviGen's Python 3.11 venv: it carries bpy and TRELLIS.2, so the retargeter and every driver script run on it.
SEGVIGEN_PYTHON = Path(os.environ.get("SEGVIGEN_PYTHON", "/home/ladvien/segvigen/.venv/bin/python"))
RETARGET_DRIVER = SCRIPTS / "retarget_animation.py"
