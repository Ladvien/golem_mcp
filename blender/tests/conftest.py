import os
import sys
from pathlib import Path

# The pinned tool-schema fingerprint and the ungated-op allowlist describe the
# CORE op set. An op plugin installed in this venv (blended.plugins) would
# change both, so the suite runs core-only. Set before any blended import.
os.environ["BLENDED_DISABLE_PLUGINS"] = "1"

# src-layout without requiring an editable install.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
