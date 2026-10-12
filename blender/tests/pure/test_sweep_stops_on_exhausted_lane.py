"""A sweep stops when the lane is out of credits, instead of burning the
backoff on every remaining instance.

Measured 2026-09-11 (OT-37, third set): Ollama cloud ran out of usage
credits at 15:20 CDT; six instances in a row each spent ~5 min of retries
on a `429 usage credits ... max reached` the user alone could clear, and
the sweep carried on to the next. Every later instance was a certain
loss and the roll was void under §P8a from the first one. The sweep now
reads the runner's recorded error and stops with its own exit code,
naming the instances it did not attempt. Driven here with a fake Blender
that writes the runner's metadata, so no Blender and no bench are needed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SWEEP = Path(__file__).resolve().parents[2] / "scripts" / "sweep_3dcode.py"

FAKE_BLENDER = '''#!/usr/bin/env python3
"""Stands in for Blender: writes the runner's metadata for the instance."""
import json, sys
from pathlib import Path
args = sys.argv[sys.argv.index("--") + 1:]
def option(name):
    return args[args.index(name) + 1]
directory = Path(option("--bench-root")) / option("--results-root") / option("--model-dir") / option("--instance")
directory.mkdir(parents=True, exist_ok=True)
(directory / ".agent_meta.json").write_text(json.dumps({
    "instance": option("--instance"),
    "status": "ERR_CONNECTION",
    "error": 'http://localhost:11434: HTTP 429 {"error":"usage credits auto reload monthly max reached"}',
}))
print("fake blender ran", option("--instance"))
'''


def test_the_sweep_stops_on_the_first_exhausted_credit_loss(tmp_path):
    fake = tmp_path / "blender"
    fake.write_text(FAKE_BLENDER)
    fake.chmod(0o755)
    instances = tmp_path / "instances.txt"
    instances.write_text("Jar_seed0\nPlate_seed0\nRug_seed0\n")
    bench_root = tmp_path / "bench"
    bench_root.mkdir()

    completed = subprocess.run(
        [
            sys.executable,
            str(SWEEP),
            "--bench-root",
            str(bench_root),
            "--instances-file",
            str(instances),
            "--model-dir",
            "roll-under-test",
            "--blender",
            str(fake),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={**os.environ, "PYTHONPATH": str(SWEEP.parents[1] / "src")},
    )

    assert completed.returncode == 3, (
        completed.stdout + completed.stderr
    )  # LANE_EXHAUSTED_EXIT
    assert "[SWEEP STOPPED] Jar_seed0" in completed.stdout
    assert "2 instance(s) not attempted" in completed.stdout
    assert completed.stdout.count("[STATUS]") == 1
    results = bench_root / "results" / "text_to_3D_agent" / "roll-under-test"
    assert (results / "Jar_seed0" / ".agent_meta.json").exists()
    assert not (results / "Plate_seed0").exists()  # never attempted
    assert (
        json.loads((results / "Jar_seed0" / ".agent_meta.json").read_text())["status"]
        == "ERR_CONNECTION"
    )
