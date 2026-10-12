"""Regressions found reviewing the bench scripts (2026-10-07).

1. `orientation_policy_sim.py` imported `signed_permutations` from
   `diagnose_3dcode`, which stopped defining it when OT-36 moved the helper
   into `bench_surface_metrics`: ImportError on the first line that ran.
   `tests/pure/test_import_integrity.py` only resolves `blended`-rooted
   imports, so a sibling-script import rotted unseen.
2. `bench_render_references.render_instance` judged success from
   `render_log.json` on disk. Under `--overwrite` a Blender that died before
   writing a log left the PREVIOUS run's OK log and four PNGs in place, and
   the instance read as freshly rendered; it also had no timeout.
"""

from __future__ import annotations

import ast
import json
import os
import stat
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bench_render_references

from blended.evaluate.bench_reference_views import REFERENCE_VIEW_FILENAMES

# Names bound at a script's module level, by whatever statement binds them.
_BINDING_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _module_level_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, _BINDING_NODES):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(
                (alias.asname or alias.name).split(".")[0] for alias in node.names
            )
    return names


def test_every_sibling_script_import_names_something_the_sibling_binds():
    modules = {path.stem: path for path in SCRIPTS.glob("*.py")}
    probed = 0
    stale: list[str] = []
    for path in sorted(modules.values()):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module in modules
            ):
                continue
            bound = _module_level_names(modules[node.module])
            for alias in node.names:
                probed += 1
                if alias.name not in bound:
                    stale.append(f"{path.name}: from {node.module} import {alias.name}")
    assert probed > 0, "the probe found no sibling-script imports to check"
    assert not stale, f"imports of names a sibling script no longer defines: {stale}"


def _stage_reference(bench_root: Path, instance: str) -> Path:
    """A factory, plus the previous run's OK log and four views."""
    factory = bench_root / "data" / instance / f"{instance}.py"
    factory.parent.mkdir(parents=True)
    factory.write_text("pass\n")
    output = bench_render_references.images_directory(bench_root, instance)
    output.mkdir(parents=True)
    (output / "render_log.json").write_text(json.dumps({"status": "OK"}))
    for name in REFERENCE_VIEW_FILENAMES:
        (output / name).write_bytes(b"png")
    assert bench_render_references.is_rendered(output)
    return output


def _fake_blender(directory: Path, body: str) -> str:
    path = directory / "fake_blender.sh"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_a_blender_that_dies_without_a_log_does_not_pass_on_the_stale_log(tmp_path):
    output = _stage_reference(tmp_path, "Jar_seed0")
    blender = _fake_blender(tmp_path, "exit 1")
    ok = bench_render_references.render_instance(tmp_path, blender, "Jar_seed0", 30)
    assert ok is False
    assert not (output / "render_log.json").exists()


def test_a_hung_blender_is_a_failed_instance_not_a_stalled_sweep(tmp_path):
    _stage_reference(tmp_path, "Jar_seed0")
    blender = _fake_blender(tmp_path, "exec sleep 60")
    ok = bench_render_references.render_instance(tmp_path, blender, "Jar_seed0", 1)
    assert ok is False


def test_a_blender_that_writes_a_fresh_ok_log_and_views_still_passes(tmp_path):
    """The guard removes only the stale log: a real render still succeeds."""
    output = _stage_reference(tmp_path, "Jar_seed0")
    log = output / "render_log.json"
    blender = _fake_blender(tmp_path, f"echo '{{\"status\": \"OK\"}}' > '{log}'")
    assert (
        bench_render_references.render_instance(tmp_path, blender, "Jar_seed0", 30)
        is True
    )
    assert os.path.getsize(log) > 0
