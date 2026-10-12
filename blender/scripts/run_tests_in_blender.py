"""Run the Blender test layer inside a REAL Blender install.

`make test-blender` runs against whatever `bpy` the dev venv has. On a
machine with no bpy wheel that collects nothing and still reports
success — and even where the wheel exists it is not the environment the
addon ships into. Blender's bundled Python has numpy, no Pillow, and no
pip to add one, which is exactly the configuration five test modules
were silently skipping out of.

pytest and its dependencies are pure Python, so the venv's copy imports
into Blender's interpreter even across minor versions.

    make test-blender-app
    BLENDER=/path/to/blender make test-blender-app
    make test-blender-app ARGS="-k capture -v"
"""

import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def venv_site_packages() -> Path:
    """The dev venv's site-packages — where pytest lives."""
    candidates = sorted(
        (REPOSITORY_ROOT / ".venv" / "lib").glob("python3.*/site-packages")
    )
    if not candidates:
        raise SystemExit(
            f"No .venv under {REPOSITORY_ROOT}: pytest has to come from "
            f"somewhere, and Blender's Python has no pip. Create the dev "
            f"venv first."
        )
    return candidates[-1]


# Packages with compiled extensions built for the VENV's interpreter
# (cpython-311), which cannot import under Blender's Python 3.13. numpy would
# shadow Blender's own bundled copy; Pillow, scipy and trimesh have no Blender
# copy and fail at their C modules (measured 2026-10-10, after numpy and
# Pillow landed in .venv on 2026-10-09). Blender's layer runs with Blender's
# numpy and none of the others (the Makefile's `test-blender-app` note).
# Settled in `sys.modules`, not on `sys.path`, because
# tests/blender/test_bench_bridge.py runs the bench prelude, which inserts the
# venv's site-packages at sys.path[0] again mid-run. A `None` entry is how
# Python records an absent module: `import` raises ModuleNotFoundError and
# `importlib.util.find_spec` returns None.
import numpy  # noqa: E402,F401  Blender's own, imported before the venv is visible

for blocked_package in ("PIL", "scipy", "trimesh"):
    sys.modules[blocked_package] = None  # type: ignore[assignment]
sys.path.insert(0, str(venv_site_packages()))
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
# What `python -m pytest` puts there, and what tests/blender/test_harness.py
# needs to import test_retry by its dotted path.
sys.path.insert(0, str(REPOSITORY_ROOT))
os.chdir(REPOSITORY_ROOT)

# sys.path must be built before pytest is importable at all.
import pytest

extra_arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
raise SystemExit(
    pytest.main(["-q", "tests/blender", "-p", "no:cacheprovider", *extra_arguments])
)
